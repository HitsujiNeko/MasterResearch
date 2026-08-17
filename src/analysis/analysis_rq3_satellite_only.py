"""RQ3の衛星データのみシナリオを、cell_id結合の新経路で評価するスクリプト。

データセットパス・特徴量列・出力先のみを持つ薄いエントリであり、実際の処理
（フィルタ・サンプリング・モデル学習・Spatial CV・SHAP・プロット）はすべて
`src.common` 配下の共通モジュールに委譲する。旧実装（ピクセル単位・CSV経路）
とは集計単位・格子・観測日数・Spatial CV方式が異なる別経路であり、
出力先ディレクトリも旧実装（`data/output/satellite_only/`）とは分ける。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.common.config import PROJECT_ROOT

CONDA_ROOT = PROJECT_ROOT / ".conda"
CONDA_PATH_PREFIX = [
    str(CONDA_ROOT),
    str(CONDA_ROOT / "Library" / "bin"),
    str(CONDA_ROOT / "Scripts"),
]
os.environ["PATH"] = os.pathsep.join([*CONDA_PATH_PREFIX, os.environ.get("PATH", "")])

# GDAL関連のPATH設定後にimportする必要があるため、E402を許容する
import matplotlib  # noqa: E402

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from src.analysis.urban_params.canonical_grid import CELL_ID_STRIDE, split_cell_id  # noqa: E402
from src.common.analysis_dataset import (  # noqa: E402
    filter_valid_rows,
    load_analysis_dataset,
    sample_dataset,
)
from src.common.analysis_plots import (  # noqa: E402
    save_feature_importance_plot,
    save_model_comparison_plot,
    save_spatial_cv_plot,
)
from src.common.model_metrics import (  # noqa: E402
    compute_vif,
    sanitize_vif_for_json,
    summarize_metric_dicts,
)
from src.common.regression_models import fit_linear_regression, fit_random_forest  # noqa: E402
from src.common.shap_report import compute_shap_outputs  # noqa: E402
from src.common.spatial_cv import (  # noqa: E402
    assign_spatial_blocks,
    compute_block_cells,
    split_by_spatial_blocks,
)
from src.common.summary import save_summary  # noqa: E402

# 分析対象は着手時点で30m・単一観測日（2023-07-07 03:23:29Z）に限定する
# （30m/90mは当該観測日のテーブルのみ整備済みのため。他日時の拡張は別途行う）。
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "output"
    / "datasets"
    / "dataset_satellite_only_20230707_032329_hanoi_30m.gpkg"
)
# 旧経路（data/output/satellite_only/）とは集計単位・格子が異なる別物のため、
# 出力先ディレクトリを分ける。
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "output" / "satellite_only_cellbased" / "20230707_032329"
)
FEATURE_COLUMNS = ["NDVI", "NDBI", "NDWI"]
TARGET_COLUMN = "LST"
DEFAULT_SCALE_M = 30


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 解析対象の引数リスト。`None` の場合は `sys.argv` から読む
            （テストで既定値以外を指定しやすくするための引数）。
    Returns:
        解析済みの引数オブジェクト。
    """
    parser = argparse.ArgumentParser(
        description="RQ3のSatellite Onlyシナリオをcell_id結合の新経路で評価する。"
    )
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--scale", type=int, default=DEFAULT_SCALE_M, help="正準グリッドの解像度（m）"
    )
    parser.add_argument("--lst-valid-ratio-threshold", type=float, default=0.5)
    parser.add_argument("--sample-size", type=int, default=100_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--cv-splits", type=int, default=5)
    parser.add_argument(
        "--block-size-m",
        type=int,
        default=2_700,
        help=(
            "Spatial CVのブロックサイズ（m）。scaleの倍数である必要がある"
            "（compute_block_cellsが検証する）。既定の2700mはSNAP_UNIT_M（900m）の"
            "倍数でもあり、30/90/300mのいずれでもブロック境界が厳密に一致するが、"
            "この900m倍数の性質は既定値以外を指定した場合には保証されない。"
        ),
    )
    parser.add_argument("--shap-sample-size", type=int, default=2_000)
    parser.add_argument("--shap-background-size", type=int, default=500)
    parser.add_argument("--rf-trees", type=int, default=300)
    return parser.parse_args(argv)


def resolve_output_stem(dataset_path: Path) -> str:
    """データセットパスから出力ファイル名の接頭辞を求める。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
    Returns:
        出力ファイル名の接頭辞（データセットファイル名の拡張子を除いた部分）。
    """
    return dataset_path.stem


def assign_canonical_blocks(
    cell_ids: np.ndarray, block_size_m: int, scale: int
) -> tuple[np.ndarray, dict[str, int]]:
    """cell_idから正準グリッドのrow/colを復元し、空間ブロックIDを割り当てる。

    `canonical_grid.split_cell_id()` によるデコードと `spatial_cv` によるブロック
    割り当ての結線を担う。`spatial_cv` モジュールはanalysis層の `canonical_grid`
    へ依存させない設計のため、この結線はエントリスクリプト側で行う。

    Args:
        cell_ids: 正準グリッドの `cell_id` 配列。
        block_size_m: ブロックの一辺の長さ（メートル）。
        scale: 正準グリッドの解像度（メートル/セル）。
    Returns:
        block_id配列と、ブロック統計情報の辞書（`assign_spatial_blocks` の戻り値）。
    """
    row, col = split_cell_id(cell_ids)
    block_cells = compute_block_cells(block_size_m, scale)
    return assign_spatial_blocks(row, col, block_cells, CELL_ID_STRIDE)


def build_filtered_sample(
    dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
    sample_size: int,
    random_state: int,
) -> pd.DataFrame:
    """品質列フィルタとサンプリングを、フィルタ→サンプリングの順に適用する。

    ブロック割り当てより先にサンプリングを行う必要があるため
    （ブロック割り当てを先にすると各ブロックのセル数が不均等に減り、
    fold のサイズ均衡が崩れる）、呼び出し側はこの関数の戻り値を使って
    ブロック割り当てを行う。

    Args:
        dataframe: `load_analysis_dataset` の戻り値。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限。
        sample_size: 抽出するサンプル数（0で全件）。
        random_state: 乱数シード。
    Returns:
        フィルタ・サンプリング後のデータフレーム。
    """
    filtered = filter_valid_rows(
        dataframe,
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
    )
    return sample_dataset(filtered, sample_size=sample_size, random_state=random_state)


def run_random_split_models(
    sampled: pd.DataFrame, random_state: int, rf_trees: int
) -> dict[str, object]:
    """ランダム分割で線形回帰・RFを学習・評価する。

    Args:
        sampled: フィルタ・サンプリング後のデータ。
        random_state: 乱数シード。
        rf_trees: RFの決定木本数。
    Returns:
        学習データ・評価結果・学習済みRFモデルを含む辞書。
    """
    x = sampled[FEATURE_COLUMNS]
    y = sampled[TARGET_COLUMN]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=random_state
    )

    linear_result, standardized_coefficients, _ = fit_linear_regression(
        x_train, x_test, y_train, y_test
    )
    rf_model, rf_result, rf_importance, permutation_scores, _ = fit_random_forest(
        x_train, x_test, y_train, y_test, random_state=random_state, n_estimators=rf_trees
    )
    return {
        "x_train": x_train,
        "x_test": x_test,
        "linear_result": linear_result,
        "standardized_coefficients": standardized_coefficients,
        "rf_model": rf_model,
        "rf_result": rf_result,
        "rf_importance": rf_importance,
        "permutation_scores": permutation_scores,
    }


def run_spatial_cv_models(
    sampled: pd.DataFrame,
    block_ids: np.ndarray,
    cv_splits: int,
    random_state: int,
    rf_trees: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    """空間ブロックCVで線形回帰・RFを学習・評価する。

    Args:
        sampled: フィルタ・サンプリング後のデータ。
        block_ids: `assign_canonical_blocks` の戻り値（サンプルごとのblock_id）。
        cv_splits: 分割数。
        random_state: 乱数シード。
        rf_trees: RFの決定木本数。
    Returns:
        集計結果と、fold別の評価指標データフレームのタプル。
    """
    x = sampled[FEATURE_COLUMNS]
    y = sampled[TARGET_COLUMN]
    folds = split_by_spatial_blocks(block_ids, n_splits=cv_splits)

    fold_rows: list[dict[str, float | int]] = []
    linear_metrics: list[dict[str, float]] = []
    rf_metrics: list[dict[str, float]] = []
    for fold_index, (train_idx, test_idx) in enumerate(folds, start=1):
        x_train, x_test = x.iloc[train_idx], x.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        linear_result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
        _, rf_result, _, _, _ = fit_random_forest(
            x_train, x_test, y_train, y_test, random_state=random_state, n_estimators=rf_trees
        )

        linear_metrics.append(linear_result["metrics"])
        rf_metrics.append(rf_result["metrics"])
        fold_rows.append(
            {
                "fold": fold_index,
                "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                "linear_r2": linear_result["metrics"]["r2"],
                "linear_rmse": linear_result["metrics"]["rmse"],
                "linear_mae": linear_result["metrics"]["mae"],
                "rf_r2": rf_result["metrics"]["r2"],
                "rf_rmse": rf_result["metrics"]["rmse"],
                "rf_mae": rf_result["metrics"]["mae"],
            }
        )

    summary = {
        "cv_splits": cv_splits,
        "linear_regression": summarize_metric_dicts(linear_metrics),
        "random_forest": summarize_metric_dicts(rf_metrics),
    }
    return summary, pd.DataFrame(fold_rows)


def main() -> None:
    """衛星データのみシナリオの分析（cell_id結合の新経路）を実行して結果を保存する。

    Args:
        なし
    Returns:
        None
    """
    args = parse_arguments()
    args.dataset_path = args.dataset_path.resolve()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = resolve_output_stem(args.dataset_path)
    observation_label = output_stem

    dataframe = load_analysis_dataset(args.dataset_path)
    sampled = build_filtered_sample(
        dataframe,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        sample_size=args.sample_size,
        random_state=args.random_state,
    )

    sampled_path = args.output_dir / f"{output_stem}_sample_{args.sample_size}.csv"
    sampled.to_csv(sampled_path, index=False)

    vif = compute_vif(sampled[FEATURE_COLUMNS])
    random_split = run_random_split_models(sampled, args.random_state, args.rf_trees)

    block_ids, block_info = assign_canonical_blocks(
        sampled["cell_id"].to_numpy(), args.block_size_m, args.scale
    )
    spatial_cv_summary, spatial_cv_folds = run_spatial_cv_models(
        sampled, block_ids, args.cv_splits, args.random_state, args.rf_trees
    )
    spatial_cv_summary["block_definition"] = {
        "block_size_m": args.block_size_m,
        "n_blocks": block_info["n_blocks"],
    }

    feature_importance_df = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "linear_abs_standardized_coefficient": [
                abs(random_split["standardized_coefficients"][feature])
                for feature in FEATURE_COLUMNS
            ],
            "random_forest_importance": [
                random_split["rf_importance"][feature] for feature in FEATURE_COLUMNS
            ],
            "permutation_importance": [
                random_split["permutation_scores"][feature] for feature in FEATURE_COLUMNS
            ],
            "vif": [vif[feature] for feature in FEATURE_COLUMNS],
        }
    )
    feature_importance_path = args.output_dir / f"{output_stem}_feature_importance.csv"
    feature_importance_df.to_csv(feature_importance_path, index=False)

    spatial_cv_folds_path = args.output_dir / f"{output_stem}_spatial_cv_folds.csv"
    spatial_cv_folds.to_csv(spatial_cv_folds_path, index=False)

    comparison_plot_path = args.output_dir / f"{output_stem}_model_comparison.png"
    importance_plot_path = args.output_dir / f"{output_stem}_feature_importance.png"
    spatial_cv_plot_path = args.output_dir / f"{output_stem}_spatial_cv.png"
    save_model_comparison_plot(
        comparison_plot_path,
        random_split["linear_result"]["metrics"],
        random_split["rf_result"]["metrics"],
        spatial_cv_summary["linear_regression"],
        spatial_cv_summary["random_forest"],
        observation_label,
    )
    save_feature_importance_plot(
        importance_plot_path,
        random_split["standardized_coefficients"],
        random_split["rf_importance"],
        observation_label,
    )
    save_spatial_cv_plot(spatial_cv_plot_path, spatial_cv_folds)

    shap_source = random_split["x_test"].reset_index(drop=True)
    shap_sample_size = min(args.shap_sample_size, len(shap_source))
    background_size = min(args.shap_background_size, len(random_split["x_train"]))
    shap_features = shap_source.sample(n=shap_sample_size, random_state=args.random_state)
    background_features = random_split["x_train"].sample(
        n=background_size, random_state=args.random_state
    )
    shap_result, _ = compute_shap_outputs(
        model=random_split["rf_model"],
        shap_features=shap_features,
        background_features=background_features,
        output_dir=args.output_dir,
        output_stem=output_stem,
        observation_label=observation_label,
    )

    result = {
        "scenario": "Satellite Only",
        "dataset_path": str(args.dataset_path.relative_to(PROJECT_ROOT)),
        "sample_path": str(sampled_path.relative_to(PROJECT_ROOT)),
        "sample_size": int(len(sampled)),
        "train_size": int(len(random_split["x_train"])),
        "test_size": int(len(random_split["x_test"])),
        "features": FEATURE_COLUMNS,
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "random_split": {
            "linear_regression": random_split["linear_result"],
            "random_forest": random_split["rf_result"],
        },
        "spatial_cv": {
            **spatial_cv_summary,
            "outputs": {
                "fold_metrics_csv": str(spatial_cv_folds_path.relative_to(PROJECT_ROOT)),
                "spatial_cv_png": str(spatial_cv_plot_path.relative_to(PROJECT_ROOT)),
            },
        },
        **sanitize_vif_for_json(vif),
        "shap": shap_result,
        "outputs": {
            "feature_importance_csv": str(feature_importance_path.relative_to(PROJECT_ROOT)),
            "model_comparison_png": str(comparison_plot_path.relative_to(PROJECT_ROOT)),
            "feature_importance_png": str(importance_plot_path.relative_to(PROJECT_ROOT)),
        },
    }

    result_path = args.output_dir / f"{output_stem}_results.json"
    save_summary(result, result_path)
    print(f"結果を保存しました: {result_path}")


if __name__ == "__main__":
    main()
