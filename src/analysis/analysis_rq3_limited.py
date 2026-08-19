"""RQ3のLimitedシナリオ（衛星データ + 公開GIS）を、cell_id結合の新経路で評価するスクリプト。

`analysis_rq3_satellite_only.py` と同じ「薄いエントリ」構成であり、実際の処理
（フィルタ・サンプリング・モデル学習・Spatial CV・SHAP・プロット）はすべて
`src.common` 配下の共通モジュールに委譲する。Limited固有の前処理（建物高さの
0補完）のみ本スクリプトに置く（詳細は `fill_missing_building_heights` を参照）。
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
    DEFAULT_REQUIRED_MASK_COLUMNS,
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
# （Satellite Onlyと同じ制約。他日時・他スケールの拡張は別途行う）。
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "data" / "output" / "datasets" / "dataset_limited_20230707_032329_hanoi_30m.gpkg"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "limited" / "20230707_032329"
FEATURE_COLUMNS = [
    "BUILD_COV",
    "BUILD_DEN",
    "BUILD_H_MEAN",
    "BUILD_H_MAX",
    "ROAD_DEN",
    "ELEV_MEAN",
    "NDVI",
    "NDBI",
    "NDWI",
]
TARGET_COLUMN = "LST"
DEFAULT_SCALE_M = 30
VALID_GIS_MASK_COLUMN = "VALID_GIS_MASK"
# 建物高さが取れる建物が1つも無いセルでNULLになる列（`_aggregate_heights`参照）。
BUILDING_HEIGHT_COLUMNS = ["BUILD_H_MEAN", "BUILD_H_MAX"]
# BUILDING_HEIGHT_COLUMNSの0補完可否を判定する基準列（0なら「建物が無い」ため0mとみなす）。
BUILD_COVERAGE_COLUMN = "BUILD_COV"
# 建物高さを補完した行を追跡するための内部一時列。フィルタ・サンプリングを経ても
# どのセルが補完対象だったかを追えるようにするための列で、`filter_valid_rows` /
# `sample_dataset` は列を素通りさせる（`.loc[mask]` / `.sample()` は他の列を
# 保持するため）。最終的な戻り値（`sampled`）には残さない（内部実装の詳細のため）。
BUILDING_HEIGHT_FILLED_COLUMN = "_BUILDING_HEIGHT_FILLED"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 解析対象の引数リスト。`None` の場合は `sys.argv` から読む
            （テストで既定値以外を指定しやすくするための引数）。
    Returns:
        解析済みの引数オブジェクト。
    """
    parser = argparse.ArgumentParser(
        description="RQ3のLimitedシナリオをcell_id結合の新経路で評価する。"
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
        "--require-valid-gis-mask",
        action="store_true",
        help=(
            "指定すると VALID_GIS_MASK == 1 のセルに限定する感度分析として実行する"
            "（既定は VALID_GIS_MASK を課さず有効域全体を対象にする）。"
        ),
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


def resolve_output_stem(dataset_path: Path, require_valid_gis_mask: bool) -> str:
    """データセットパスとフィルタ条件から出力ファイル名の接頭辞を求める。

    主結果と感度分析（`--require-valid-gis-mask`）を同一ディレクトリへ出力しても
    上書きしないよう、感度分析側の接頭辞にのみ `_gismask` を付与する。これにより
    出力ファイル名自体がフィルタ条件を示す。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        require_valid_gis_mask: `VALID_GIS_MASK == 1` を課す感度分析かどうか。
    Returns:
        出力ファイル名の接頭辞。
    """
    stem = dataset_path.stem
    if require_valid_gis_mask:
        return f"{stem}_gismask"
    return stem


def fill_missing_building_heights(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """建物が存在しないセルに限り、建物高さ列のNULLを0で補完する。

    `BUILD_H_MEAN`/`BUILD_H_MAX` は、高さが取れる建物が1つも無いセルでNULLになる
    （`src.analysis.urban_params.params.buildings._aggregate_heights`）。この
    NULLには「建物が無い」（`BUILD_COV == 0`）場合と「建物はあるが高さが得られ
    ない」（`BUILD_COV > 0`）場合の2種類が混在する。前者のみ「建物が無い ⇒
    建物高さ0m」として0補完し、後者は真の欠落として補完せず、後段の
    `filter_valid_rows` の非NULL要求で除外させる。

    9変数構成を維持したまま有効域を最大化するためのLimited固有の判断であり、
    シナリオ非依存の `filter_valid_rows` へ暗黙に波及させないよう、共通モジュール
    ではなくこのエントリスクリプト側に置く。呼び出し側は `filter_valid_rows` の
    **前**にこの関数を適用する必要がある。

    Args:
        dataframe: `load_analysis_dataset` の戻り値
            （`BUILDING_HEIGHT_COLUMNS` と `BUILD_COVERAGE_COLUMN` を含む）。
    Returns:
        補完後のデータフレームと、補完したセル数（`BUILDING_HEIGHT_COLUMNS` の
        いずれかを補完した行数。両列とも同時にNULL/非NULLになる想定のため、
        実質的にはどちらの列で数えても同じ値になる）のタプル。
    Raises:
        ValueError: `dataframe` に `BUILDING_HEIGHT_COLUMNS`/`BUILD_COVERAGE_COLUMN`
            のいずれかの列が存在しない場合。
    """
    required_columns = [*BUILDING_HEIGHT_COLUMNS, BUILD_COVERAGE_COLUMN]
    missing_columns = [column for column in required_columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"次の列がデータセットに存在しません: {missing_columns}")

    filled = dataframe.copy()
    # BUILD_COVはfine grid（0/1の二値マスク）の平均で算出される（buildings.py の
    # aggregate_mean_from_fine_mask）。建物が1つも無いセルは全画素0のため、
    # 浮動小数点演算を経ずに厳密な0.0になる（0/Nの除算に丸め誤差は生じない）。
    # そのため「==0」の完全一致比較で「建物が無い」ケースを漏れなく検出できる。
    no_building_mask = filled[BUILD_COVERAGE_COLUMN] == 0
    fillable_mask = pd.Series(False, index=filled.index)
    for column in BUILDING_HEIGHT_COLUMNS:
        column_mask = no_building_mask & filled[column].isna()
        fillable_mask |= column_mask
        filled.loc[column_mask, column] = 0.0

    # フィルタ・サンプリング後も「どのセルが補完対象だったか」を追跡できるよう、
    # マスクを列としても残す（呼び出し側の build_filtered_sample が、最終的な
    # 分析サンプルに残った補完セル数を集計するために使う）。
    filled[BUILDING_HEIGHT_FILLED_COLUMN] = fillable_mask
    return filled, int(fillable_mask.sum())


@dataclass(frozen=True)
class FilteredSampleResult:
    """build_filtered_sample の戻り値。

    補完件数を3段階（データセット全体・フィルタ後の母数・最終的な分析サンプル）で
    別々に保持する。段階ごとに規模が大きく異なり（ROI全体で数百万セル→フィルタ後の
    有効域→既定10万件のサンプル）、取り違えると研究記述の母数を誤るため、
    フィールド名で明示的に区別する（`dict[str, object]` にしないのは
    `RandomSplitResult` と同じ理由）。

    Attributes:
        sampled: フィルタ・サンプリング後のデータフレーム（学習・評価に使う実体）。
        dataset_filled_cell_count: 入力 `dataframe`（フィルタ・サンプリング前の
            全体）での建物高さ補完セル数。
        population_size: フィルタ後・サンプリング前の母数（有効域のセル数）。
        population_filled_cell_count: `population_size` のうち建物高さ補完セル数。
        sample_filled_cell_count: 最終的な分析サンプル（`sampled`）に残った
            補完セル数。
    """

    sampled: pd.DataFrame
    dataset_filled_cell_count: int
    population_size: int
    population_filled_cell_count: int
    sample_filled_cell_count: int


def build_filtered_sample(
    dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
    sample_size: int,
    random_state: int,
    required_mask_columns: tuple[str, ...] = DEFAULT_REQUIRED_MASK_COLUMNS,
) -> FilteredSampleResult:
    """建物高さの補完→品質列フィルタ→サンプリングの順に適用する。

    `fill_missing_building_heights` は `filter_valid_rows` より前に適用する
    必要がある（先に非NULL要求で欠損域を除外すると、補完すべきだった行まで
    落ちてしまうため）。この順序依存を呼び出し側（`main()`）に持たせず本関数に
    閉じ込めることで、呼び出し順を誤って補完が空振りする回帰を構造的に防ぐ。

    ブロック割り当てより先にサンプリングを行う必要があるため
    （ブロック割り当てを先にすると各ブロックのセル数が不均等に減り、
    fold のサイズ均衡が崩れる）、呼び出し側はこの関数の戻り値（`sampled`）を
    使ってブロック割り当てを行う。

    補完件数はデータセット全体・フィルタ後の母数（サンプリング前）・最終的な
    分析サンプル（フィルタ・サンプリング後）の3段階で別々に返す
    （`FilteredSampleResult` 参照）。フィルタ後の母数は `filtered`
    （サンプリングの直前に既に計算済みのデータフレーム）の件数を読むだけであり、
    RF学習等の重い処理を追加で行うわけではない。

    Args:
        dataframe: `load_analysis_dataset` の戻り値（未加工。補完前でよい）。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限。
        sample_size: 抽出するサンプル数（0で全件）。
        random_state: 乱数シード。
        required_mask_columns: `== 1` を要求する品質列名。既定は `IN_ANALYSIS_AREA`
            のみ（主結果）。`--require-valid-gis-mask` 指定時は呼び出し側が
            `VALID_GIS_MASK` を追加する（感度分析）。
    Returns:
        `FilteredSampleResult`。
    """
    filled, dataset_filled_cell_count = fill_missing_building_heights(dataframe)
    filtered = filter_valid_rows(
        filled,
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
        required_mask_columns=required_mask_columns,
    )
    population_size = len(filtered)
    population_filled_cell_count = int(filtered[BUILDING_HEIGHT_FILLED_COLUMN].sum())

    sampled = sample_dataset(filtered, sample_size=sample_size, random_state=random_state)
    sample_filled_cell_count = int(sampled[BUILDING_HEIGHT_FILLED_COLUMN].sum())
    sampled = sampled.drop(columns=[BUILDING_HEIGHT_FILLED_COLUMN])
    return FilteredSampleResult(
        sampled=sampled,
        dataset_filled_cell_count=dataset_filled_cell_count,
        population_size=population_size,
        population_filled_cell_count=population_filled_cell_count,
        sample_filled_cell_count=sample_filled_cell_count,
    )


def main() -> None:
    """Limitedシナリオの分析（cell_id結合の新経路）を実行して結果を保存する。

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
    output_stem = resolve_output_stem(args.dataset_path, args.require_valid_gis_mask)
    observation_label = build_observation_label(output_stem)

    required_mask_columns = DEFAULT_REQUIRED_MASK_COLUMNS
    if args.require_valid_gis_mask:
        required_mask_columns = (*DEFAULT_REQUIRED_MASK_COLUMNS, VALID_GIS_MASK_COLUMN)

    # 実際に使う列だけを読み込み、他シナリオ用の品質列等の読込コストを避ける。
    required_columns = [
        "cell_id",
        "lon",
        "lat",
        *FEATURE_COLUMNS,
        TARGET_COLUMN,
        IN_ANALYSIS_AREA_COLUMN,
        LST_VALID_RATIO_COLUMN,
        VALID_GIS_MASK_COLUMN,
    ]
    dataframe = load_analysis_dataset(args.dataset_path, columns=required_columns)
    filtered_sample_result = build_filtered_sample(
        dataframe,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        sample_size=args.sample_size,
        random_state=args.random_state,
        required_mask_columns=required_mask_columns,
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
        "scenario": "Limited",
        "dataset_path": to_project_relative_string(args.dataset_path),
        "sample_path": to_project_relative_string(sampled_path),
        "sample_size": int(len(sampled)),
        "train_size": int(len(random_split.x_train)),
        "test_size": int(len(random_split.x_test)),
        "features": FEATURE_COLUMNS,
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "require_valid_gis_mask": args.require_valid_gis_mask,
        "required_mask_columns": list(required_mask_columns),
        "building_height_fill": {
            "columns": BUILDING_HEIGHT_COLUMNS,
            # dataset_filled_cell_count: フィルタ・サンプリング前のデータセット全体
            # （ROI全体で数百万セル規模）での補完件数。
            # population_size / population_filled_cell_count: 品質列フィルタ後・
            # サンプリング前の母数（有効域のセル数）と、そのうちの補完件数。
            # sample_filled_cell_count: 実際に学習・評価に使った sample_size 件の
            # 分析サンプルに残った補完件数（sample_size/train_size/test_sizeと同じ
            # 母集団）。3者は一致しない（フィルタ・サンプリングで補完セルの一部が
            # 脱落するため）。
            "dataset_filled_cell_count": filtered_sample_result.dataset_filled_cell_count,
            "population_size": filtered_sample_result.population_size,
            "population_filled_cell_count": filtered_sample_result.population_filled_cell_count,
            "sample_filled_cell_count": filtered_sample_result.sample_filled_cell_count,
        },
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
