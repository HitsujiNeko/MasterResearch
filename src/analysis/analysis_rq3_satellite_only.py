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
    ANALYSIS_AREA_ROI,
    ANALYSIS_AREAS,
    DEFAULT_REQUIRED_MASK_COLUMNS,
    IN_ANALYSIS_AREA_COLUMN,
    LST_VALID_RATIO_COLUMN,
    analysis_area_output_part,
    filter_valid_rows,
    load_analysis_dataset,
    require_analysis_area_columns,
    resolve_analysis_area_mask_columns,
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
from src.common.evaluation_cells import (  # noqa: E402
    build_evaluation_record,
    evaluation_input_paths,
    load_evaluation_set_for_run,
    resolve_evaluation_folds,
    resolve_evaluation_output_dir,
    resolve_evaluation_output_stem,
    select_evaluation_rows,
)
from src.common.model_metrics import (  # noqa: E402
    compute_vif,
    sanitize_vif_for_json,
)
from src.common.paths import to_project_relative_string  # noqa: E402
from src.common.run_parameters import build_run_parameters_from_args  # noqa: E402
from src.common.shap_report import compute_shap_outputs  # noqa: E402
from src.common.spatial_cv import split_by_spatial_blocks  # noqa: E402
from src.common.summary import build_provenance, save_summary  # noqa: E402

# 分析対象は30m・単一観測日（2022-09-06 03:23:58Z）に限定する
# （Limitedと同じ制約。他日時・他スケールの拡張は別途行う）。
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "output"
    / "datasets"
    / "dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"
)
# 旧経路（data/output/satellite_only/）とは集計単位・格子が異なる別物のため、
# 出力先ディレクトリを分ける。
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "output" / "satellite_only_cellbased" / "20220906_032358"
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
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "出力先ディレクトリ。未指定なら DEFAULT_OUTPUT_DIR（--evaluation-cells 指定時は"
            "その名前に _common_evaluation を付けた別ディレクトリ）"
        ),
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
    parser.add_argument(
        "--analysis-area",
        choices=ANALYSIS_AREAS,
        default=ANALYSIS_AREA_ROI,
        help=(
            "分析対象範囲。roi は IN_ANALYSIS_AREA == 1 のセル（従来どおり）、survey は"
            "さらに IN_ANALYSIS_AREA_SURVEY == 1（測量GIS範囲）に絞る。survey には"
            "mask_survey テーブルを結合したデータセットが必要。"
        ),
    )
    parser.add_argument(
        "--evaluation-cells",
        type=Path,
        default=None,
        help=(
            "シナリオ間で共通の評価セル CSV（build_common_evaluation_set.py の出力）。"
            "指定すると標本抽出と GroupKFold の代わりに、CSV の cell_id を CSV の行順で選び、"
            "CSV の fold 列で Spatial CV を行う。対になるメタデータと引数が一致しなければ停止する。"
        ),
    )
    args = parser.parse_args(argv)
    if args.output_dir is None:
        args.output_dir = (
            DEFAULT_OUTPUT_DIR
            if args.evaluation_cells is None
            else resolve_evaluation_output_dir(DEFAULT_OUTPUT_DIR)
        )
    return args


def resolve_output_stem(dataset_path: Path, analysis_area: str = ANALYSIS_AREA_ROI) -> str:
    """データセットパスと分析対象範囲から出力ファイル名の接頭辞を求める。

    分析対象範囲の部品（`roi` は付けず、それ以外は `area_{範囲}`）の規則は
    `analysis_area_output_part` に一本化しており、Limited と共有する。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        analysis_area: 分析対象範囲（`ANALYSIS_AREAS` のいずれか）。既定は `roi`。
    Returns:
        出力ファイル名の接頭辞（データセットファイル名の拡張子を除いた部分に、
        `roi` 以外なら範囲の印を `_` で連結したもの）。
    Raises:
        ValueError: `analysis_area` が対応外の場合。
    """
    area_part = analysis_area_output_part(analysis_area)
    if not area_part:
        return dataset_path.stem
    return f"{dataset_path.stem}_{area_part}"


def resolve_required_mask_columns(analysis_area: str = ANALYSIS_AREA_ROI) -> tuple[str, ...]:
    """`== 1` を要求する品質列名を、分析対象範囲に応じて組み立てる。

    有効母集団の定義の一部であり、`main()` と、シナリオ間で共通の評価セル集合を
    作る処理の両方がこの関数を呼ぶ（条件を呼び出し側で書き直さないため）。

    Args:
        analysis_area: 分析対象範囲（`ANALYSIS_AREAS` のいずれか）。既定は `roi`。
    Returns:
        `DEFAULT_REQUIRED_MASK_COLUMNS` に分析対象範囲の品質列を加えたタプル。
    Raises:
        ValueError: `analysis_area` が対応外の場合。
    """
    return (*DEFAULT_REQUIRED_MASK_COLUMNS, *resolve_analysis_area_mask_columns(analysis_area))


def load_scenario_dataset(
    dataset_path: Path, analysis_area: str = ANALYSIS_AREA_ROI
) -> pd.DataFrame:
    """Satellite Only の分析に使う列だけを読み込み、分析対象範囲の品質列を検査する。

    分析対象範囲の品質列は、フィルタ条件（`resolve_required_mask_columns`）だけで
    なく読込列にも加える。読込列に無いと列が読まれず、
    `require_analysis_area_columns` が常に停止する。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        analysis_area: 分析対象範囲（`ANALYSIS_AREAS` のいずれか）。既定は `roi`。
    Returns:
        読み込んだデータフレーム（フィルタ前の全行）。
    Raises:
        ValueError: `analysis_area` が対応外の場合、または分析対象範囲の品質列が
            データセットに無い場合。
    """
    # 実際に使う列だけを読み込み、他シナリオ用の品質列等の読込コストを避ける。
    required_columns = [
        "cell_id",
        "lon",
        "lat",
        *FEATURE_COLUMNS,
        TARGET_COLUMN,
        IN_ANALYSIS_AREA_COLUMN,
        LST_VALID_RATIO_COLUMN,
        *resolve_analysis_area_mask_columns(analysis_area),
    ]
    dataframe = load_analysis_dataset(dataset_path, columns=required_columns)
    # 存在しない列は読込時に黙って読み飛ばされるため、読込後に検査する。
    require_analysis_area_columns(dataframe, analysis_area, dataset_path)
    return dataframe


def build_valid_population(
    dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
    required_mask_columns: tuple[str, ...] = DEFAULT_REQUIRED_MASK_COLUMNS,
) -> pd.DataFrame:
    """品質列フィルタを適用し、サンプリング前の有効母集団を求める。

    有効母集団の定義（分光指数と LST が非NULL・品質列が1・`LST_VALID_RATIO` が
    下限以上）を1か所に置き、`build_filtered_sample` と、シナリオ間で共通の
    評価セル集合を作る処理の両方から呼ぶ。

    Args:
        dataframe: `load_scenario_dataset` の戻り値。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限。
        required_mask_columns: `== 1` を要求する品質列名
            （`resolve_required_mask_columns` の戻り値）。
    Returns:
        有効母集団のデータフレーム（行の並びは入力のまま）。
    """
    return filter_valid_rows(
        dataframe,
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
        required_mask_columns=required_mask_columns,
    )


@dataclass(frozen=True)
class FilteredSampleResult:
    """build_filtered_sample の戻り値。

    `sampled` と `filter_dropout` を1つのオブジェクトにまとめて返す
    （`dict[str, object]` にしないのは、Limitedの `FilteredSampleResult`
    ―`src.analysis.analysis_rq3_limited` ― と同じ理由: フィールド名で
    明示的に区別し、取り違えを防ぐため）。

    Attributes:
        sampled: フィルタ・サンプリング後のデータフレーム（学習・評価に使う実体）。
        population_size: フィルタ後・サンプリング前の母数（有効母集団のセル数）。
        filter_dropout: `summarize_filter_dropout` が返すフィルタ脱落診断
            （`src.common.analysis_dataset` 参照）。基準段階（target_available）
            からの脱落の内訳を要因グループ別に持つ。
    """

    sampled: pd.DataFrame
    population_size: int
    filter_dropout: dict[str, object]


def build_filtered_sample(
    dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
    sample_size: int,
    random_state: int,
    block_size_m: int = DEFAULT_BLOCK_SIZE_M,
    scale: int = DEFAULT_SCALE_M,
    required_mask_columns: tuple[str, ...] = DEFAULT_REQUIRED_MASK_COLUMNS,
    evaluation_cells: pd.DataFrame | None = None,
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
        required_mask_columns: `== 1` を要求する品質列名。既定は `IN_ANALYSIS_AREA`
            のみ。分析対象範囲を測量GIS範囲に絞る場合は `IN_ANALYSIS_AREA_SURVEY`
            を加える。`filter_valid_rows` と `summarize_filter_dropout` の両方へ
            同じ値を渡し、脱落診断の基準と分析の母数を揃える。
        evaluation_cells: シナリオ間で共通の評価セル（`EvaluationSet.cells`）。
            渡した場合は `sample_dataset` で抽出せず、有効母集団から評価セルの
            cell_id を評価セルの行順で選ぶ（`select_evaluation_rows`。1件でも
            有効母集団に無ければ停止する）。`None`（既定）なら従来どおり抽出する。
    Returns:
        `FilteredSampleResult`。
    """
    dropout_block_ids, _ = assign_canonical_blocks(
        dataframe["cell_id"].to_numpy(), block_size_m, scale
    )

    filtered = build_valid_population(
        dataframe,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
        required_mask_columns=required_mask_columns,
    )
    if evaluation_cells is None:
        sampled = sample_dataset(filtered, sample_size=sample_size, random_state=random_state)
    else:
        sampled = select_evaluation_rows(filtered, evaluation_cells)

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
        required_mask_columns=required_mask_columns,
    )

    return FilteredSampleResult(
        sampled=sampled, population_size=len(filtered), filter_dropout=filter_dropout
    )


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
    output_stem = resolve_output_stem(args.dataset_path, args.analysis_area)
    observation_label = build_observation_label(output_stem)
    # 評価セルを使う場合は、重い読込より前に引数とメタデータの一致を確かめる。
    evaluation_set = load_evaluation_set_for_run(args)
    if evaluation_set is not None:
        output_stem = resolve_evaluation_output_stem(output_stem, evaluation_set.cells_path)

    required_mask_columns = resolve_required_mask_columns(args.analysis_area)
    dataframe = load_scenario_dataset(args.dataset_path, args.analysis_area)
    filtered_sample_result = build_filtered_sample(
        dataframe,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        sample_size=args.sample_size,
        random_state=args.random_state,
        block_size_m=args.block_size_m,
        scale=args.scale,
        required_mask_columns=required_mask_columns,
        evaluation_cells=None if evaluation_set is None else evaluation_set.cells,
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
    # コストは無視できる。評価セルを使う場合は GroupKFold を行わず、評価セルの fold 列
    # から分割を作って同じ検証（fold数・テスト行数）を行う。
    block_ids, block_info = assign_canonical_blocks(
        sampled["cell_id"].to_numpy(), args.block_size_m, args.scale
    )
    if evaluation_set is None:
        fixed_folds = None
        split_by_spatial_blocks(block_ids, n_splits=args.cv_splits)
    else:
        fixed_folds = resolve_evaluation_folds(evaluation_set.cells, block_ids, args.cv_splits)

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
        folds=fixed_folds,
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
        # 分析対象範囲。有効カバレッジ（測量GIS範囲等）をROI全体と同一視しないよう、
        # 範囲名と、実際に == 1 を要求した品質列の両方を残す。
        "analysis_area": args.analysis_area,
        "required_mask_columns": list(required_mask_columns),
        # 結果ファイルの他のキーから読めない実行条件（乱数シード・RF本数・固定値等）。
        # 記録範囲の判断は `src.common.run_parameters` のmodule docstringを参照する。
        "run_parameters": build_run_parameters_from_args(args),
        "filter_dropout": filtered_sample_result.filter_dropout,
        # 評価セルを使ったランかどうかと、その評価セル・母数（使わない場合は null）。
        "evaluation_cells": (
            None
            if evaluation_set is None
            else build_evaluation_record(evaluation_set, filtered_sample_result.population_size)
        ),
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

    # どのコード・環境・入力から生成したかを追跡できるよう、保存直前に来歴を付与する。
    # 入力はデータセットGeoPackageと、評価セルを使う場合はその CSV・メタデータ JSON
    # （本スクリプトが読むファイルはこれだけである。評価セルを作り直したときに陳腐化
    # として検出されるようにする）。大容量のGeoPackageではハッシュ計算に数秒かかるため、
    # 進捗をログに残す。
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    result["provenance"] = build_provenance(
        "src.analysis.analysis_rq3_satellite_only",
        input_paths=[args.dataset_path, *evaluation_input_paths(evaluation_set)],
    )

    result_path = args.output_dir / f"{output_stem}_results.json"
    save_summary(result, result_path)
    # 長時間処理の事後診断ができるよう、保存内容をそのままログにも残す。
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"結果を保存しました: {result_path}")


if __name__ == "__main__":
    main()
