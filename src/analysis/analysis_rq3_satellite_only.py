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

import pandas as pd  # noqa: E402

from src.analysis.urban_params.canonical_grid import assign_canonical_blocks  # noqa: E402
from src.common.analysis_dataset import (  # noqa: E402
    IN_ANALYSIS_AREA_COLUMN,
    LST_VALID_RATIO_COLUMN,
    filter_valid_rows,
    load_analysis_dataset,
    sample_dataset,
    summarize_filter_dropout,
)
from src.common.analysis_plots import (  # noqa: E402
    save_feature_importance_plot,
    save_model_comparison_plot,
    save_spatial_cv_plot,
)
from src.common.analysis_runs import (  # noqa: E402
    build_observation_label,
    run_random_split_models,
    run_spatial_cv_models,
    validate_scale_matches_dataset,
)
from src.common.model_metrics import (  # noqa: E402
    compute_vif,
    sanitize_vif_for_json,
)
from src.common.paths import to_project_relative_string  # noqa: E402
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
# Spatial CVのブロックサイズ（m）の既定値。argparseの`default`と
# `build_filtered_sample`の既定値の両方がこの定数を参照する
# （`--block-size-m`のhelp文言に既定値の性質の説明がある）。
DEFAULT_BLOCK_SIZE_M = 2_700
# フィルタ脱落診断（summarize_filter_dropout）の要因グループ定義。Satellite Only
# はFEATURE_COLUMNS（分光指数）以外の非NULL要求列を持たないため、1グループのみ。
FILTER_DROPOUT_COLUMN_GROUPS = {"spectral_indices": list(FEATURE_COLUMNS)}


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
        default=DEFAULT_BLOCK_SIZE_M,
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


@dataclass(frozen=True)
class FilteredSampleResult:
    """build_filtered_sample の戻り値。

    `sampled` と `filter_dropout` を1つのオブジェクトにまとめて返す
    （`dict[str, object]` にしないのは、Limitedの `FilteredSampleResult`
    ―`src.analysis.analysis_rq3_limited` ― と同じ理由: フィールド名で
    明示的に区別し、取り違えを防ぐため）。

    Attributes:
        sampled: フィルタ・サンプリング後のデータフレーム（学習・評価に使う実体）。
        filter_dropout: `summarize_filter_dropout` が返すフィルタ脱落診断
            （`src.common.analysis_dataset` 参照）。基準段階（target_available）
            からの脱落の内訳を要因グループ別に持つ。
    """

    sampled: pd.DataFrame
    filter_dropout: dict[str, object]


def build_filtered_sample(
    dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
    sample_size: int,
    random_state: int,
    block_size_m: int = DEFAULT_BLOCK_SIZE_M,
    scale: int = DEFAULT_SCALE_M,
) -> FilteredSampleResult:
    """品質列フィルタ→サンプリング→フィルタ脱落診断の順に適用する。

    **Spatial CV用のブロック割り当てとは別物**として、フィルタ脱落診断
    （`summarize_filter_dropout`）用のブロックIDを本関数の内側で計算する。
    Spatial CV用のブロック割り当ては `main()` がサンプリング後の `sampled`
    （既定10万件）を対象に行う（ブロック割り当てを先にすると各ブロックの
    セル数が不均等に減り、fold のサイズ均衡が崩れるため。この呼び出し順は
    変更しない）のに対し、診断用は品質列フィルタ適用前の `dataframe` の
    **全行**を対象に行う必要がある（`src.analysis.analysis_rq3_limited` の
    `build_filtered_sample` と同じ設計判断）。1回の実行でブロック割り当てが
    2回走るが、対象母集団が別物であり統合しない。

    **意図的な挙動変更**: `block_size_m` が `scale` の倍数であることの検証
    （`compute_block_cells`）は、本関数がブロック割り当てを内包したことで
    従来より早い時点（フィルタ・サンプリングより前）で発火するようになる。
    設定ミスをより早く検出する方向の変更であり、フィルタ結果の行集合自体は
    変えない。

    Args:
        dataframe: `load_analysis_dataset` の戻り値。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限。
        sample_size: 抽出するサンプル数（0で全件）。
        random_state: 乱数シード。
        block_size_m: フィルタ脱落診断用ブロックの一辺の長さ（m）。既定は
            `DEFAULT_BLOCK_SIZE_M`。
        scale: 正準グリッドの解像度（m/セル）。既定は `DEFAULT_SCALE_M`。
    Returns:
        `FilteredSampleResult`。
    """
    dropout_block_ids, _ = assign_canonical_blocks(
        dataframe["cell_id"].to_numpy(), block_size_m, scale
    )

    filtered = filter_valid_rows(
        dataframe,
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
    )
    sampled = sample_dataset(filtered, sample_size=sample_size, random_state=random_state)

    filter_dropout = summarize_filter_dropout(
        dataframe,
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
        summary_columns=FEATURE_COLUMNS,
        column_groups=FILTER_DROPOUT_COLUMN_GROUPS,
        block_id=dropout_block_ids,
        block_size_m=block_size_m,
        sampled_row_count=len(sampled),
    )

    return FilteredSampleResult(sampled=sampled, filter_dropout=filter_dropout)


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
    filtered_sample_result = build_filtered_sample(
        dataframe,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        sample_size=args.sample_size,
        random_state=args.random_state,
        block_size_m=args.block_size_m,
        scale=args.scale,
    )
    sampled = filtered_sample_result.sampled
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
    random_split = run_random_split_models(
        sampled, FEATURE_COLUMNS, TARGET_COLUMN, args.random_state, args.rf_trees
    )

    spatial_cv_summary, spatial_cv_folds = run_spatial_cv_models(
        sampled,
        FEATURE_COLUMNS,
        TARGET_COLUMN,
        block_ids,
        args.cv_splits,
        args.random_state,
        args.rf_trees,
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
        "filter_dropout": filtered_sample_result.filter_dropout,
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
