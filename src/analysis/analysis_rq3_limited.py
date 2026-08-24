"""RQ3のLimitedシナリオ（衛星データ + 公開GIS）を、cell_id結合の新経路で評価するスクリプト。

`analysis_rq3_satellite_only.py` と同じ「薄いエントリ」構成であり、実際の処理
（フィルタ・サンプリング・モデル学習・Spatial CV・SHAP・プロット）はすべて
`src.common` 配下の共通モジュールに委譲する。Limited固有の前処理（建物高さの
0補完）のみ本スクリプトに置く（詳細は `fill_missing_building_heights` を参照）。

説明変数はブロック単位で保持し、`--variable-set` で分光指数（NDVI/NDBI/NDWI）と
土地被覆クラス別面積率のどちらを投入するかを切り替える。多重共線性の診断のみを
行いたい場合は `--diagnose-only` を指定すると、モデル学習・SHAPを実行せずに
相関行列・VIF・フィルタ後母数だけを出力して終了する。
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
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
    save_correlation_heatmap,
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
    CORRELATION_METHODS,
    compute_correlation_matrix,
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
# 説明変数はブロック単位で持ち、`resolve_feature_columns()` が変数セットの指定に
# 応じて組み立てる。比較軸を「分光指数 vs 被覆率型」に絞るため、差し替えるのは
# SPECTRAL と LULC の2ブロックだけで、それ以外は全構成に共通して入れる。
BASE_FEATURE_COLUMNS = [
    "BUILD_COV",
    "BUILD_DEN",
    "BUILD_H_MEAN",
    "BUILD_H_MAX",
    "ROAD_DEN",
    "ELEV_MEAN",
]
SPECTRAL_FEATURE_COLUMNS = ["NDVI", "NDBI", "NDWI"]
NIGHTLIGHT_FEATURE_COLUMNS = ["NTL_MEAN"]

# 土地被覆は雪氷を除く7クラスすべてがテーブルに出力される。7クラスの面積率の和は
# 有効セルで1になるため、そのまま投入するとダミー変数トラップと同一構造の完全な
# 線形従属になる。参照クラスを1つ除外して構成制約を解消する（除外するクラスは
# ROI で最大の農地。urban_structure_parameters.md §2.2 が正本）。
LULC_ALL_COVERAGE_COLUMNS = [
    "LULC_WATER_COV",
    "LULC_TREE_COV",
    "LULC_CROP_COV",
    "LULC_BUILT_COV",
    "LULC_RANGE_COV",
    "LULC_WETLAND_COV",
    "LULC_BARE_COV",
]
LULC_REFERENCE_COLUMN = "LULC_CROP_COV"
LULC_FEATURE_COLUMNS = [
    column for column in LULC_ALL_COVERAGE_COLUMNS if column != LULC_REFERENCE_COLUMN
]

# 植生被覆率（樹林＋草地低木）は独立した説明変数として投入せず、SHAP値を事後に
# 合算して読む。独立列にすると植生クラスの合計が土地被覆構成比に対して完全な線形
# 従属となり、本スクリプトが診断しようとしている多重共線性が形を変えて再発する
# （同 §2.2）。SHAP値は加法的であるため、グループ寄与としての合算は妥当である。
VEGETATION_COVERAGE_COLUMNS = ["LULC_TREE_COV", "LULC_RANGE_COV"]

# 人口密度のデータソース識別子と、対応する列名。3版は概念（居住人口／実効人口）も
# 観測年も異なる別変数であり、データセットには3版とも結合されている。モデルへ
# 投入する版は `--population-source` で選ぶ。
POPULATION_SOURCE_COLUMNS = {
    "worldpop2020": "POP_DEN_WORLDPOP2020",
    "landscan2020": "POP_DEN_LANDSCAN2020",
    "landscan2023": "POP_DEN_LANDSCAN2023",
}
# 人口を1変数も投入しない構成を指定するための値。他の値とは併用できない。
POPULATION_SOURCE_NONE = "none"
DEFAULT_POPULATION_SOURCES = ["worldpop2020"]

# 変数セットの選択肢。spectral / coverage は分光指数と被覆率型のどちらが LST を
# よりよく説明するかを対比するための構成であり、both は両方を投入した構成。
VARIABLE_SET_SPECTRAL = "spectral"
VARIABLE_SET_COVERAGE = "coverage"
VARIABLE_SET_BOTH = "both"
VARIABLE_SETS = (VARIABLE_SET_SPECTRAL, VARIABLE_SET_COVERAGE, VARIABLE_SET_BOTH)
DEFAULT_VARIABLE_SET = VARIABLE_SET_BOTH

# 相関行列の対象となる「拡張後の全候補列」。VIF が実際に投入した特徴量列を対象と
# するのに対し、相関行列は変数セットの選択によらず同じ範囲で算出する。人口3版
# どうし・参照クラスを含む土地被覆7クラス全部のように、特定の変数セットには同時に
# 入らない組み合わせも診断対象に含めるためである。
ALL_CANDIDATE_FEATURE_COLUMNS = [
    *BASE_FEATURE_COLUMNS,
    *SPECTRAL_FEATURE_COLUMNS,
    *LULC_ALL_COVERAGE_COLUMNS,
    *NIGHTLIGHT_FEATURE_COLUMNS,
    *POPULATION_SOURCE_COLUMNS.values(),
]

TARGET_COLUMN = "LST"
DEFAULT_SCALE_M = 30
VALID_GIS_MASK_COLUMN = "VALID_GIS_MASK"
# 建物高さが取れる建物が1つも無いセルでNULLになる列（`_aggregate_heights`参照）。
BUILDING_HEIGHT_COLUMNS = ["BUILD_H_MEAN", "BUILD_H_MAX"]
# BUILDING_HEIGHT_COLUMNSの0補完可否を判定する基準列。両方0なら「建物が無い」ため
# 0mとみなす（BUILD_COV単独では小規模建物の取りこぼしを誤検出するため、
# BUILD_DENとのAND条件にする。fill_missing_building_heightsのdocstring参照）。
BUILD_COVERAGE_COLUMN = "BUILD_COV"
BUILD_DENSITY_COLUMN = "BUILD_DEN"
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
    parser.add_argument(
        "--variable-set",
        choices=VARIABLE_SETS,
        default=DEFAULT_VARIABLE_SET,
        help=(
            "投入する説明変数の構成。spectral は分光指数（NDVI/NDBI/NDWI）のみ、"
            "coverage は土地被覆クラス別面積率のみ、both は両方を投入する"
            "（建物・道路・標高・人口・夜間光はいずれの構成にも共通して入る）。"
        ),
    )
    parser.add_argument(
        "--population-source",
        nargs="+",
        choices=[*POPULATION_SOURCE_COLUMNS, POPULATION_SOURCE_NONE],
        default=list(DEFAULT_POPULATION_SOURCES),
        help=(
            "モデルへ投入する人口密度のデータソース（複数指定可）。"
            f"{POPULATION_SOURCE_NONE} は人口を投入しない指定であり、他の値とは併用できない。"
        ),
    )
    parser.add_argument(
        "--diagnose-only",
        action="store_true",
        help=(
            "相関行列・VIF・フィルタ後母数のみを出力し、モデル学習・SHAPを実行せずに"
            "終了する（多重共線性の診断を、RF学習を待たずに行うための入口）。"
        ),
    )
    args = parser.parse_args(argv)

    sources = args.population_source
    duplicated = sorted({source for source in sources if sources.count(source) > 1})
    if duplicated:
        parser.error(f"--population-source に重複した指定があります: {duplicated}")
    if POPULATION_SOURCE_NONE in args.population_source and len(args.population_source) > 1:
        parser.error(
            f"--population-source の {POPULATION_SOURCE_NONE} は他の値と併用できません: "
            f"{args.population_source}"
        )
    return args


def resolve_population_columns(population_sources: Sequence[str]) -> list[str]:
    """人口密度のデータソース指定を列名へ変換する。

    Args:
        population_sources: `--population-source` の値
            （`POPULATION_SOURCE_COLUMNS` のキー、または `POPULATION_SOURCE_NONE`）。
    Returns:
        投入する人口密度の列名リスト。`POPULATION_SOURCE_NONE` を指定した場合は空。
    Raises:
        ValueError: 未知のデータソース識別子が含まれる場合。
    """
    if list(population_sources) == [POPULATION_SOURCE_NONE]:
        return []

    unknown = [source for source in population_sources if source not in POPULATION_SOURCE_COLUMNS]
    if unknown:
        raise ValueError(
            f"未知の人口密度データソースです: {unknown}"
            f"（対応: {', '.join(POPULATION_SOURCE_COLUMNS)}）。"
        )
    return [POPULATION_SOURCE_COLUMNS[source] for source in population_sources]


def resolve_feature_columns(variable_set: str, population_sources: Sequence[str]) -> list[str]:
    """変数セットと人口ソースの指定から、モデルへ投入する説明変数の列名を組み立てる。

    共通ベース（建物・道路・標高・人口・夜間光）を先に並べ、差し替え対象の
    ブロック（分光指数・土地被覆クラス別面積率）を後ろに置く。列順は
    重要度CSV・VIF・SHAPの並び順にそのまま現れるため、構成間で共通部分の
    並びが揃うようにしている。

    Args:
        variable_set: `VARIABLE_SETS` のいずれか。
        population_sources: `--population-source` の値。
    Returns:
        説明変数の列名リスト。
    Raises:
        ValueError: `variable_set` が対応外の場合、または `population_sources` に
            未知のデータソース識別子が含まれる場合。
    """
    if variable_set not in VARIABLE_SETS:
        raise ValueError(
            f"対応していない変数セットです: {variable_set}（対応: {', '.join(VARIABLE_SETS)}）。"
        )

    feature_columns = [
        *BASE_FEATURE_COLUMNS,
        *resolve_population_columns(population_sources),
        *NIGHTLIGHT_FEATURE_COLUMNS,
    ]
    if variable_set in (VARIABLE_SET_SPECTRAL, VARIABLE_SET_BOTH):
        feature_columns.extend(SPECTRAL_FEATURE_COLUMNS)
    if variable_set in (VARIABLE_SET_COVERAGE, VARIABLE_SET_BOTH):
        feature_columns.extend(LULC_FEATURE_COLUMNS)
    return feature_columns


def drop_constant_features(
    dataframe: pd.DataFrame, feature_columns: Sequence[str]
) -> tuple[list[str], list[str]]:
    """分散が0の特徴量列を、モデル学習・VIF算出の対象から外す。

    定数列を残すと `compute_vif` の補助回帰が決定係数1.0を返し、**VIFが `inf`
    （完全共線）と報告される**。これは実体のある共線性ではなく定数列に起因する
    偽陽性であり、多重共線性の診断そのものを汚染する。

    データ依存の判定にするのは、ソース固定の除外リストでは対応できないためである。
    たとえば主ソース GLC_FCS30D はハノイROIに裸地クラスの画素を1つも持たないため
    `LULC_BARE_COV` が全セルで厳密に0.0になるが、副ソース Esri では非0になりうる。

    Args:
        dataframe: 判定対象のデータフレーム（`feature_columns` を含む）。
        feature_columns: 判定する説明変数の列名。
    Returns:
        （残した列名リスト, 除外した列名リスト）のタプル。順序は
        `feature_columns` の並びを保つ。
    """
    kept: list[str] = []
    dropped: list[str] = []
    for column in feature_columns:
        # nunique() は既定でNaNを数えない。ここへ来る時点で filter_valid_rows により
        # 特徴量列は非NULLに揃っているため、0または1なら定数列とみなせる。
        if dataframe[column].nunique(dropna=True) <= 1:
            dropped.append(column)
            continue
        kept.append(column)
    return kept, dropped


def summarize_vegetation_shap(
    mean_abs_shap: dict[str, float], feature_columns: Sequence[str]
) -> dict[str, object] | None:
    """植生被覆率の寄与を、土地被覆クラス列のSHAP値の事後合算として求める。

    植生被覆率は独立した説明変数として投入しない（モジュール冒頭の
    `VEGETATION_COVERAGE_COLUMNS` のコメント参照）。代わりに樹林・草地低木の
    平均絶対SHAP値を合算し、グループ寄与として記録する。

    Args:
        mean_abs_shap: `compute_shap_outputs` が返す `mean_abs_shap`
            （特徴量名をキー、平均絶対SHAP値を値とする辞書）。
        feature_columns: 実際にモデルへ投入した説明変数の列名。
    Returns:
        合算結果の辞書。植生クラス列が1つもモデルに入っていない場合は `None`
        （分光指数のみの構成では合算する対象が無いため）。
    """
    included = [column for column in VEGETATION_COVERAGE_COLUMNS if column in feature_columns]
    if not included:
        return None

    return {
        "columns": included,
        "excluded_columns": [
            column for column in VEGETATION_COVERAGE_COLUMNS if column not in included
        ],
        "mean_abs_shap_sum": float(sum(mean_abs_shap[column] for column in included)),
        "note": (
            "植生被覆率は独立変数として投入せず、樹林・草地低木クラスの平均絶対SHAP値を"
            "事後合算したグループ寄与として記録する。"
        ),
    }


def resolve_output_stem(
    dataset_path: Path,
    variable_set: str,
    population_sources: Sequence[str],
    require_valid_gis_mask: bool,
) -> str:
    """データセットパスと実行条件から出力ファイル名の接頭辞を求める。

    構成の異なるランを同一ディレクトリへ出力しても上書きしないよう、
    `{データセットstem}_{変数セット}[_pop_{ソース}...][_gismask]` の順で組み立てる。
    これにより出力ファイル名自体が実行条件を示す。

    - **人口ソースは既定（`DEFAULT_POPULATION_SOURCES`）の場合は付けない。**
      既定から変えたランだけが名前に現れるようにして、既存の出力名との差分を
      変数セットの追加だけに抑えるためである。
    - **`_gismask` は末尾に置く。** 感度分析の印を末尾に付ける既存の規約を保つ。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        variable_set: `VARIABLE_SETS` のいずれか。
        population_sources: `--population-source` の値。
        require_valid_gis_mask: `VALID_GIS_MASK == 1` を課す感度分析かどうか。
    Returns:
        出力ファイル名の接頭辞。
    """
    parts = [dataset_path.stem, variable_set]
    if list(population_sources) != list(DEFAULT_POPULATION_SOURCES):
        parts.extend(f"pop_{source}" for source in population_sources)
    if require_valid_gis_mask:
        parts.append("gismask")
    return "_".join(parts)


def fill_missing_building_heights(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """建物が存在しないセルに限り、建物高さ列のNULLを0で補完する。

    `BUILD_H_MEAN`/`BUILD_H_MAX` は、高さが取れる建物が1つも無いセルでNULLになる
    （`src.analysis.urban_params.params.buildings._aggregate_heights`）。この
    NULLには「建物が無い」場合と「建物はあるが高さが得られない」場合の2種類が
    混在する。前者のみ「建物が無い ⇒ 建物高さ0m」として0補完し、後者は真の欠落
    として補完せず、後段の `filter_valid_rows` の非NULL要求で除外させる。

    「建物が無い」の判定は `BUILD_COV == 0`（被覆率）単独ではなく
    `BUILD_COV == 0 AND BUILD_DEN == 0`（棟数密度も0）で行う。`BUILD_COV` は
    fineグリッドへのラスタ化による近似であり、`docs/01_planning/gis_data/
    gis_data_buildings.md`「小さい建物の取りこぼし」に実測があるとおり、
    30mでは建物の重心が存在するセル（`BUILD_DEN > 0`）の14.0%で
    `BUILD_COV == 0` になる（GBAの建物の80.7%が100m²未満で、fine 10mセルの
    中心を1つも含まない場合に被覆率へ寄与しないため）。`BUILD_DEN`
    は高さ集計と同じ建物重心の帰属方式であり、`BUILD_COV` 単独より
    「建物が無い」の判定に適する。

    9変数構成を維持したまま有効域を最大化するためのLimited固有の判断であり、
    シナリオ非依存の `filter_valid_rows` へ暗黙に波及させないよう、共通モジュール
    ではなくこのエントリスクリプト側に置く。呼び出し側は `filter_valid_rows` の
    **前**にこの関数を適用する必要がある。

    Args:
        dataframe: `load_analysis_dataset` の戻り値
            （`BUILDING_HEIGHT_COLUMNS`・`BUILD_COVERAGE_COLUMN`・
            `BUILD_DENSITY_COLUMN` を含む）。
    Returns:
        補完後のデータフレームと、補完したセル数（`BUILDING_HEIGHT_COLUMNS` の
        いずれかを補完した行数。両列とも同時にNULL/非NULLになる想定のため、
        実質的にはどちらの列で数えても同じ値になる）のタプル。
    Raises:
        ValueError: `dataframe` に `BUILDING_HEIGHT_COLUMNS`・
            `BUILD_COVERAGE_COLUMN`・`BUILD_DENSITY_COLUMN` のいずれかの列が
            存在しない場合。
    """
    required_columns = [*BUILDING_HEIGHT_COLUMNS, BUILD_COVERAGE_COLUMN, BUILD_DENSITY_COLUMN]
    missing_columns = [column for column in required_columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"次の列がデータセットに存在しません: {missing_columns}")

    filled = dataframe.copy()
    # BUILD_COV・BUILD_DENはいずれも建物が1つも無いセルで演算を経ずに厳密な0.0
    # になる（BUILD_COVはfine grid二値マスクの平均、BUILD_DENは建物カウントの
    # 面積除算。いずれも分子が整数0であり丸め誤差は生じない）ため、「==0」の
    # 完全一致比較で「建物が無い」ケースを検出できる。
    no_building_mask = (filled[BUILD_COVERAGE_COLUMN] == 0) & (filled[BUILD_DENSITY_COLUMN] == 0)
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
    feature_columns: Sequence[str],
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
        feature_columns: 非NULLを要求する説明変数の列名（`resolve_feature_columns`
            の戻り値）。変数セットによって列数が変わるため、モジュール定数では
            なく引数で受け取る。**構成ごとにフィルタ後の母数が変わりうる**点に
            注意する（全列の非NULLを要求するため、列を増やすと母数は減りうる）。
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
        feature_columns=list(feature_columns),
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


def build_candidate_correlation_frame(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """相関行列の対象となる全候補列を抜き出し、欠測を含む行を落とす。

    **相関行列はモデルへ投入した特徴量ではなく `ALL_CANDIDATE_FEATURE_COLUMNS`
    を対象とする。** 人口3版どうし・参照クラスを含む土地被覆7クラス全部のように、
    特定の変数セットには同時に入らない組み合わせも診断したいためである。

    欠測行を落とすのは、`compute_correlation_matrix` の欠測処理がペアワイズ削除
    であり、放置すると**セルごとに母数の異なる相関行列**になって係数どうしを
    比べられなくなるためである。落とした結果の行数は呼び出し側が記録する。

    Args:
        dataframe: フィルタ・サンプリング後のデータフレーム。
    Returns:
        （候補列のみを持つ欠測なしのデータフレーム, データセットに存在しなかった
        候補列名のリスト）のタプル。
    """
    available = [column for column in ALL_CANDIDATE_FEATURE_COLUMNS if column in dataframe.columns]
    missing = [
        column for column in ALL_CANDIDATE_FEATURE_COLUMNS if column not in dataframe.columns
    ]
    return dataframe[available].dropna(), missing


def save_correlation_outputs(
    candidate_frame: pd.DataFrame,
    output_dir: Path,
    output_stem: str,
    observation_label: str,
) -> dict[str, str]:
    """相関行列をCSVとヒートマップで保存する。

    Pearson を主とするが、被覆率型の変数は細かいスケールで0へ偏りやすく線形相関
    だけでは関係を取りこぼしうるため、Spearman も併せて出力する。方法ごとに図を
    分けるのは、1枚にまとめるとどちらの係数を描いた図か判別できなくなるためである。

    Args:
        candidate_frame: `build_candidate_correlation_frame` の戻り値の1つ目。
        output_dir: 出力先ディレクトリ。
        output_stem: 出力ファイル名の接頭辞。
        observation_label: 図タイトルに使う観測日時ラベル。
    Returns:
        出力パス（`PROJECT_ROOT` からの相対文字列）を方法ごとに格納した辞書。
    """
    outputs: dict[str, str] = {}
    for method in CORRELATION_METHODS:
        matrix = compute_correlation_matrix(candidate_frame, method=method)
        csv_path = output_dir / f"{output_stem}_correlation_{method}.csv"
        matrix.to_csv(csv_path)
        png_path = output_dir / f"{output_stem}_correlation_{method}.png"
        save_correlation_heatmap(png_path, matrix, method.capitalize(), observation_label)
        outputs[f"correlation_{method}_csv"] = to_project_relative_string(csv_path)
        outputs[f"correlation_{method}_png"] = to_project_relative_string(png_path)
    return outputs


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
    feature_columns = resolve_feature_columns(args.variable_set, args.population_source)
    output_stem = resolve_output_stem(
        args.dataset_path,
        args.variable_set,
        args.population_source,
        args.require_valid_gis_mask,
    )
    observation_label = build_observation_label(output_stem)

    required_mask_columns = DEFAULT_REQUIRED_MASK_COLUMNS
    if args.require_valid_gis_mask:
        required_mask_columns = (*DEFAULT_REQUIRED_MASK_COLUMNS, VALID_GIS_MASK_COLUMN)

    # 実際に使う列だけを読み込み、他シナリオ用の品質列等の読込コストを避ける。
    # 相関行列は全候補列を対象とするため、モデルへ投入しない候補列も読み込む
    # （dict.fromkeys で順序を保ったまま重複を除く）。
    required_columns = [
        "cell_id",
        "lon",
        "lat",
        *dict.fromkeys([*feature_columns, *ALL_CANDIDATE_FEATURE_COLUMNS]),
        TARGET_COLUMN,
        IN_ANALYSIS_AREA_COLUMN,
        LST_VALID_RATIO_COLUMN,
        VALID_GIS_MASK_COLUMN,
    ]
    dataframe = load_analysis_dataset(args.dataset_path, columns=required_columns)
    missing_feature_columns = [
        column for column in feature_columns if column not in dataframe.columns
    ]
    if missing_feature_columns:
        raise ValueError(
            f"次の説明変数の列がデータセットに存在しません: {missing_feature_columns}"
            f"（{args.dataset_path}）。--variable-set / --population-source の指定と、"
            "データセットの生成時に結合したテーブルを確認してください。"
        )

    filtered_sample_result = build_filtered_sample(
        dataframe,
        feature_columns=feature_columns,
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

    # 分散0の列を残すと compute_vif が inf を返し、実体のある共線性と区別できなく
    # なるため、VIF算出・モデル学習の前に外す（drop_constant_features 参照）。
    model_feature_columns, dropped_constant_features = drop_constant_features(
        sampled, feature_columns
    )
    if len(model_feature_columns) < 2:
        raise ValueError(
            "分散0の列を除外した結果、説明変数が2列未満になりました: "
            f"{model_feature_columns}（除外: {dropped_constant_features}）。"
        )

    candidate_frame, missing_candidate_columns = build_candidate_correlation_frame(sampled)
    correlation_outputs = save_correlation_outputs(
        candidate_frame, args.output_dir, output_stem, observation_label
    )
    vif = compute_vif(sampled[model_feature_columns])
    # VIFと相関行列は対象範囲が異なる。後から結果を読む人が取り違えないよう、
    # それぞれの対象列を明示的に記録する。
    diagnostics_scope = {
        "vif_columns": model_feature_columns,
        "correlation_columns": list(candidate_frame.columns),
        "correlation_row_count": int(len(candidate_frame)),
        "correlation_missing_columns": missing_candidate_columns,
        "sample_row_count": int(len(sampled)),
        "note": (
            "VIFはモデルへ投入した特徴量列、相関行列は拡張後の全候補列を対象とする。"
            "相関行列は候補列に欠測を含む行を落として算出しているため、"
            "correlation_row_count は sample_row_count 以下になりうる。"
        ),
    }
    run_conditions = {
        "variable_set": args.variable_set,
        "population_sources": list(args.population_source),
        "features": model_feature_columns,
        "requested_features": feature_columns,
        "dropped_constant_features": dropped_constant_features,
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "require_valid_gis_mask": args.require_valid_gis_mask,
        "required_mask_columns": list(required_mask_columns),
    }

    if args.diagnose_only:
        diagnostics = {
            "scenario": "Limited",
            "mode": "diagnose_only",
            "dataset_path": to_project_relative_string(args.dataset_path),
            **run_conditions,
            "population_size": filtered_sample_result.population_size,
            "sample_size": int(len(sampled)),
            "diagnostics_scope": diagnostics_scope,
            **sanitize_vif_for_json(vif),
            "outputs": correlation_outputs,
        }
        diagnostics_path = args.output_dir / f"{output_stem}_diagnostics.json"
        save_summary(diagnostics, diagnostics_path)
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
        print(f"診断結果を保存しました: {diagnostics_path}")
        return

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

    random_split = run_random_split_models(
        sampled, model_feature_columns, TARGET_COLUMN, args.random_state, args.rf_trees
    )

    spatial_cv_summary, spatial_cv_folds = run_spatial_cv_models(
        sampled,
        model_feature_columns,
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
            "feature": model_feature_columns,
            "linear_abs_standardized_coefficient": [
                abs(standardized_coefficients[feature]) for feature in model_feature_columns
            ],
            "random_forest_importance": [
                rf_importance[feature] for feature in model_feature_columns
            ],
            "permutation_importance": [
                permutation_scores[feature] for feature in model_feature_columns
            ],
            "vif": [vif[feature] for feature in model_feature_columns],
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
    vegetation_shap = summarize_vegetation_shap(shap_result["mean_abs_shap"], model_feature_columns)
    if vegetation_shap is not None:
        shap_result["vegetation_coverage"] = vegetation_shap

    result = {
        "scenario": "Limited",
        "dataset_path": to_project_relative_string(args.dataset_path),
        "sample_path": to_project_relative_string(sampled_path),
        "sample_size": int(len(sampled)),
        "train_size": int(len(random_split.x_train)),
        "test_size": int(len(random_split.x_test)),
        **run_conditions,
        "diagnostics_scope": diagnostics_scope,
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
            **correlation_outputs,
        },
    }

    result_path = args.output_dir / f"{output_stem}_results.json"
    save_summary(result, result_path)
    # 長時間処理の事後診断ができるよう、保存内容をそのままログにも残す。
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"結果を保存しました: {result_path}")


if __name__ == "__main__":
    main()
