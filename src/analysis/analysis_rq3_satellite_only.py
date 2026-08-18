"""RQ3の衛星データのみシナリオを、cell_id結合の新経路で評価するスクリプト。

データセットパス・特徴量列・出力先のみを持つ薄いエントリであり、実際の処理
（フィルタ・サンプリング・モデル学習・Spatial CV・SHAP・プロット）はすべて
`src.common` 配下の共通モジュールに委譲する。旧実装（ピクセル単位・CSV経路）
とは集計単位・格子・観測日数・Spatial CV方式が異なる別経路であり、
出力先ディレクトリも旧実装（`data/output/satellite_only/`）とは分ける。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
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
from sklearn.ensemble import RandomForestRegressor  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from src.analysis.urban_params.canonical_grid import assign_canonical_blocks  # noqa: E402
from src.common.analysis_dataset import (  # noqa: E402
    IN_ANALYSIS_AREA_COLUMN,
    LST_VALID_RATIO_COLUMN,
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
from src.common.paths import to_project_relative_string  # noqa: E402
from src.common.regression_models import fit_linear_regression, fit_random_forest  # noqa: E402
from src.common.shap_report import compute_shap_outputs  # noqa: E402
from src.common.spatial_cv import split_by_spatial_blocks  # noqa: E402
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
    parser.add_argument(
        "--dataset-path", type=Path, default=DEFAULT_DATASET_PATH, help="入力GeoPackageのパス"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="出力先ディレクトリ"
    )
    parser.add_argument(
        "--scale", type=int, default=DEFAULT_SCALE_M, help="正準グリッドの解像度（m）"
    )
    parser.add_argument(
        "--lst-valid-ratio-threshold",
        type=float,
        default=0.5,
        help="LST_VALID_RATIOの下限（この値以上のセルを残す）",
    )
    parser.add_argument(
        "--sample-size", type=int, default=100_000, help="抽出するサンプル数（0で全件）"
    )
    parser.add_argument("--random-state", type=int, default=42, help="乱数シード")
    parser.add_argument("--cv-splits", type=int, default=5, help="Spatial CVの分割数（2以上）")
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
    parser.add_argument("--shap-sample-size", type=int, default=2_000, help="SHAP評価サンプル数")
    parser.add_argument("--shap-background-size", type=int, default=500, help="SHAP背景データ数")
    parser.add_argument("--rf-trees", type=int, default=300, help="ランダムフォレストの決定木本数")
    return parser.parse_args(argv)


def resolve_output_stem(dataset_path: Path) -> str:
    """データセットパスから出力ファイル名の接頭辞を求める。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
    Returns:
        出力ファイル名の接頭辞（データセットファイル名の拡張子を除いた部分）。
    """
    return dataset_path.stem


def build_observation_label(output_stem: str) -> str:
    """出力接頭辞から観測日時ラベルを生成する。

    `resolve_output_stem` の戻り値（例:
    `dataset_satellite_only_20230707_032329_hanoi_30m`）に含まれる
    `{8桁の日付}_{6桁の時刻}` を `"2023-07-07 03:23:29"` のような可読な形式へ
    整形する。プロット・SHAP図のタイトルに使うためのラベルであり、ファイル名
    そのもの（`resolve_output_stem`）とは用途が異なる。

    Args:
        output_stem: `resolve_output_stem` の戻り値。
    Returns:
        可読な観測日時ラベル。該当パターンが見つからない場合は `output_stem`
        をそのまま返す（プロットタイトルが空になるより分かりやすいため）。
    """
    match = re.search(r"(\d{8})_(\d{6})", output_stem)
    if match is None:
        return output_stem

    raw_date, raw_time = match.groups()
    date_label = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    time_label = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:6]}"
    return f"{date_label} {time_label}"


def validate_scale_matches_dataset(dataset_path: Path, scale: int) -> None:
    """`--scale` とデータセットのファイル名から読み取れる解像度の整合性を検証する。

    分析用データセットGeoPackage自体は解像度を保持しない（`cell_id` のデコード
    結果である row/col はスケール非依存の絶対インデックスであり、その物理サイズ
    はスケールに依存する）。そのため、`--dataset-path` と `--scale` の不一致は
    ファイル名の命名規則（`src.analysis.build_dataset.resolve_dataset_path` が
    付与する末尾の `_{scale}m`）でしか検出できない。不一致のまま実行すると、
    誤ったブロックサイズでSpatial CVが静かに実行されるため、ここで早期に
    検出する。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        scale: `--scale` で指定された正準グリッドの解像度（m）。
    Raises:
        ValueError: ファイル名末尾が `_{scale}m` と一致しない場合。
    """
    expected_suffix = f"_{scale}m"
    if not dataset_path.stem.endswith(expected_suffix):
        raise ValueError(
            f"--scale（{scale}）とデータセットのファイル名（{dataset_path.name}）が"
            f"一致しない可能性があります。ファイル名は「{expected_suffix}」で終わる"
            "ことを想定しています。正しい--scaleを指定するか、対応するデータセットを"
            "指定してください。"
        )


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


@dataclass(frozen=True)
class RandomSplitResult:
    """ランダム分割による学習・評価結果。

    `dict[str, object]` ではなく型付きの構造体にすることで、キー名の
    打ち間違いを実行時のKeyErrorではなく型チェッカで検出できるようにする。
    標準化係数・重要度は `linear_result` / `rf_result` の中に既に含まれており
    二重管理を避けるため、専用フィールドは持たせない
    （例: 標準化係数は `linear_result["standardized_coefficients"]` で参照する）。

    Attributes:
        x_train: 学習用説明変数。
        x_test: 評価用説明変数。
        linear_result: 線形回帰の評価結果（`metrics` と `standardized_coefficients` を含む）。
        rf_model: 学習済みランダムフォレストモデル。
        rf_result: RFの評価結果（`metrics` / `feature_importance` /
            `permutation_importance` を含む）。
    """

    x_train: pd.DataFrame
    x_test: pd.DataFrame
    linear_result: dict[str, object]
    rf_model: RandomForestRegressor
    rf_result: dict[str, object]


def run_random_split_models(
    sampled: pd.DataFrame, random_state: int, rf_trees: int
) -> RandomSplitResult:
    """ランダム分割で線形回帰・RFを学習・評価する。

    Args:
        sampled: フィルタ・サンプリング後のデータ。
        random_state: 乱数シード。
        rf_trees: RFの決定木本数。
    Returns:
        学習データ・評価結果・学習済みRFモデルを含む構造体。
    """
    x = sampled[FEATURE_COLUMNS]
    y = sampled[TARGET_COLUMN]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=random_state
    )

    linear_result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
    rf_model, rf_result, _, _, _ = fit_random_forest(
        x_train, x_test, y_train, y_test, random_state=random_state, n_estimators=rf_trees
    )
    return RandomSplitResult(
        x_train=x_train,
        x_test=x_test,
        linear_result=linear_result,
        rf_model=rf_model,
        rf_result=rf_result,
    )


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
        # 各foldではmetricsしか使わないため、permutation importanceの計算は省略する。
        _, rf_result, _, _, _ = fit_random_forest(
            x_train,
            x_test,
            y_train,
            y_test,
            random_state=random_state,
            n_estimators=rf_trees,
            compute_permutation_importance=False,
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
    validate_scale_matches_dataset(args.dataset_path, args.scale)
    output_stem = resolve_output_stem(args.dataset_path)
    observation_label = build_observation_label(output_stem)

    # 実際に使う列だけを読み込み、他シナリオ用の品質列等の読込コストを避ける。
    required_columns = [
        "cell_id",
        "lon",
        "lat",
        *FEATURE_COLUMNS,
        TARGET_COLUMN,
        IN_ANALYSIS_AREA_COLUMN,
        LST_VALID_RATIO_COLUMN,
    ]
    dataframe = load_analysis_dataset(args.dataset_path, columns=required_columns)
    sampled = build_filtered_sample(
        dataframe,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        sample_size=args.sample_size,
        random_state=args.random_state,
    )
    if sampled.empty:
        raise ValueError(
            f"フィルタ後の有効な行がありません: {args.dataset_path}"
            "（--lst-valid-ratio-thresholdの設定や対象日のデータ範囲を確認してください）。"
        )

    sampled_path = args.output_dir / f"{output_stem}_sample_{args.sample_size}.csv"
    sampled.to_csv(sampled_path, index=False)

    # block_size_m/cv_splitsの設定検証を、高コストなモデル学習（run_random_split_models
    # 等）より前に行う。split_by_spatial_blocksの戻り値は後段のrun_spatial_cv_modelsで
    # 再計算するが、fold分割自体はインデックス操作のみで軽量なため、ここでの重複呼び出し
    # コストは無視できる。
    block_ids, block_info = assign_canonical_blocks(
        sampled["cell_id"].to_numpy(), args.block_size_m, args.scale
    )
    split_by_spatial_blocks(block_ids, n_splits=args.cv_splits)

    vif = compute_vif(sampled[FEATURE_COLUMNS])
    random_split = run_random_split_models(sampled, args.random_state, args.rf_trees)

    spatial_cv_summary, spatial_cv_folds = run_spatial_cv_models(
        sampled, block_ids, args.cv_splits, args.random_state, args.rf_trees
    )
    spatial_cv_summary["block_definition"] = {
        "block_size_m": args.block_size_m,
        "n_blocks": block_info["n_blocks"],
    }

    standardized_coefficients = random_split.linear_result["standardized_coefficients"]
    rf_importance = random_split.rf_result["feature_importance"]
    permutation_scores = random_split.rf_result["permutation_importance"]
    feature_importance_df = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "linear_abs_standardized_coefficient": [
                abs(standardized_coefficients[feature]) for feature in FEATURE_COLUMNS
            ],
            "random_forest_importance": [rf_importance[feature] for feature in FEATURE_COLUMNS],
            "permutation_importance": [permutation_scores[feature] for feature in FEATURE_COLUMNS],
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
        random_split.linear_result["metrics"],
        random_split.rf_result["metrics"],
        spatial_cv_summary["linear_regression"],
        spatial_cv_summary["random_forest"],
        observation_label,
    )
    save_feature_importance_plot(
        importance_plot_path,
        standardized_coefficients,
        rf_importance,
        observation_label,
    )
    save_spatial_cv_plot(spatial_cv_plot_path, spatial_cv_folds)

    shap_source = random_split.x_test.reset_index(drop=True)
    shap_sample_size = min(args.shap_sample_size, len(shap_source))
    background_size = min(args.shap_background_size, len(random_split.x_train))
    shap_features = shap_source.sample(n=shap_sample_size, random_state=args.random_state)
    background_features = random_split.x_train.sample(
        n=background_size, random_state=args.random_state
    )
    shap_result, _ = compute_shap_outputs(
        model=random_split.rf_model,
        shap_features=shap_features,
        background_features=background_features,
        output_dir=args.output_dir,
        output_stem=output_stem,
        observation_label=observation_label,
    )

    result = {
        "scenario": "Satellite Only",
        "dataset_path": to_project_relative_string(args.dataset_path),
        "sample_path": to_project_relative_string(sampled_path),
        "sample_size": int(len(sampled)),
        "train_size": int(len(random_split.x_train)),
        "test_size": int(len(random_split.x_test)),
        "features": FEATURE_COLUMNS,
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "random_split": {
            "linear_regression": random_split.linear_result,
            "random_forest": random_split.rf_result,
        },
        "spatial_cv": {
            **spatial_cv_summary,
            "outputs": {
                "fold_metrics_csv": to_project_relative_string(spatial_cv_folds_path),
                "spatial_cv_png": to_project_relative_string(spatial_cv_plot_path),
            },
        },
        **sanitize_vif_for_json(vif),
        "shap": shap_result,
        "outputs": {
            "feature_importance_csv": to_project_relative_string(feature_importance_path),
            "model_comparison_png": to_project_relative_string(comparison_plot_path),
            "feature_importance_png": to_project_relative_string(importance_plot_path),
        },
    }

    result_path = args.output_dir / f"{output_stem}_results.json"
    save_summary(result, result_path)
    # 長時間処理の事後診断ができるよう、保存内容をそのままログにも残す。
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"結果を保存しました: {result_path}")


if __name__ == "__main__":
    main()
