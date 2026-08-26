"""RQ3のLimitedシナリオ（衛星データ + 公開GIS）を、cell_id結合の新経路で評価するスクリプト。

`analysis_rq3_satellite_only.py` と同じ「薄いエントリ」構成であり、実際の処理
（フィルタ・サンプリング・モデル学習・Spatial CV・SHAP・プロット）はすべて
`src.common` 配下の共通モジュールに委譲する。Limited固有の前処理（建物高さの
0補完）のみ本スクリプトに置く（詳細は `fill_missing_building_heights` を参照）。

説明変数はブロック単位で保持し、`--variable-set` で分光指数（NDVI/NDBI/NDWI）と
土地被覆クラス別面積率のどちらを投入するかを切り替える。建物高さブロック
（`BUILD_H_MEAN`/`BUILD_H_MAX`）は強い相関を持つため、既定では平均高さの1列のみを
投入し、`--building-height` で2列とも投入する構成・最大高さのみの構成・主成分へ
合成する構成へ切り替えられる。多重共線性の診断のみを行いたい場合は
`--diagnose-only` を指定すると、モデル学習・SHAPを実行せずに相関行列・VIF・
フィルタ後母数だけを出力して終了する。
"""

from __future__ import annotations

import argparse
import json
import math
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
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

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
# 説明変数はブロック単位で持ち、`resolve_feature_columns()` が変数セット・建物高さ
# 構成の指定に応じて組み立てる。比較軸を「分光指数 vs 被覆率型」に絞るため、変数
# セットで差し替えるのは SPECTRAL と LULC の2ブロックだけで、それ以外は全構成に
# 共通して入れる。建物高さブロックはこれとは独立に `--building-height` で差し替える
# （`resolve_building_height_columns` 参照）。
BUILDING_FOOTPRINT_FEATURE_COLUMNS = ["BUILD_COV", "BUILD_DEN"]
# 建物高さが取れる建物が1つも無いセルでNULLになる列（`_aggregate_heights`参照）。
BUILDING_HEIGHT_MEAN_COLUMN = "BUILD_H_MEAN"
BUILDING_HEIGHT_MAX_COLUMN = "BUILD_H_MAX"
BUILDING_HEIGHT_COLUMNS = [BUILDING_HEIGHT_MEAN_COLUMN, BUILDING_HEIGHT_MAX_COLUMN]
# 建物ブロック以外の共通ベース列。
OTHER_BASE_FEATURE_COLUMNS = ["ROAD_DEN", "ELEV_MEAN"]
# 共通ベースの既定の並び（建物高さ2列を投入する `both` 構成）。相関行列の対象列
# （`ALL_CANDIDATE_FEATURE_COLUMNS`）は建物高さ構成に依らずこの並びを使うため、
# 高さ2列を含んだ形のまま保つ。
BASE_FEATURE_COLUMNS = [
    *BUILDING_FOOTPRINT_FEATURE_COLUMNS,
    *BUILDING_HEIGHT_COLUMNS,
    *OTHER_BASE_FEATURE_COLUMNS,
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
# （同 §2.2）。合算は平均絶対SHAP値どうしの和であり、グループ寄与の**上限**を
# 与える（行ごとに符号が逆のセルでは打ち消しが起こるため、符号付きSHAP値を先に
# 合算した場合の値以上になる）。順位の目安として読む。
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

# 建物高さ構成の選択肢。`BUILD_H_MEAN` と `BUILD_H_MAX` は同一の建物ポリゴンから
# 集計した高さであり強く相関するため、2列とも投入するとVIFが危険水準へ達する。
# both は2列とも投入する構成、mean / max はどちらか1列だけを投入する構成、
# pc1 は2列を標準化して第1主成分へ合成した1列を投入する構成
# （`resolve_building_height_columns` / `add_building_height_pc1` 参照）。
BUILDING_HEIGHT_MODE_BOTH = "both"
BUILDING_HEIGHT_MODE_MEAN = "mean"
BUILDING_HEIGHT_MODE_MAX = "max"
BUILDING_HEIGHT_MODE_PC1 = "pc1"
BUILDING_HEIGHT_MODES = (
    BUILDING_HEIGHT_MODE_BOTH,
    BUILDING_HEIGHT_MODE_MEAN,
    BUILDING_HEIGHT_MODE_MAX,
    BUILDING_HEIGHT_MODE_PC1,
)
# 既定は mean。3構成を同一セル上で比較した結果、VIFはいずれも危険水準を大きく下回り
# （2.46〜2.89）、説明力・重要度・SHAPに区別できる差が無かったため、
# 「セル内の平均建物高さ」として物理的な意味が直接読める生の観測列を採った
# （比較の実測値と判断は `docs/03_results/limited_analysis_results.md` を正本とする）。
# **出力名の省略基準は既定ではなく both という値であり**（`resolve_output_stem` 参照）、
# この既定変更で既存ランの出力ファイル名は動かない。
DEFAULT_BUILDING_HEIGHT_MODE = BUILDING_HEIGHT_MODE_MEAN
# 主成分構成でのみ作る合成列。入力データセットには存在しない
# （`add_building_height_pc1` が分析サンプル上で追加する）。
BUILDING_HEIGHT_PC1_COLUMN = "BUILD_H_PC1"

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
        "--building-height",
        choices=BUILDING_HEIGHT_MODES,
        default=DEFAULT_BUILDING_HEIGHT_MODE,
        help=(
            "モデルへ投入する建物高さ列の構成。both は BUILD_H_MEAN と BUILD_H_MAX を"
            "2列とも投入する、mean / max はどちらか1列だけを投入する、"
            "pc1 は2列を標準化して第1主成分へ合成した1列を投入する。"
            "既定の mean は高さ2列の多重共線性を避けつつ意味が直接読める構成である。"
            "いずれの構成でも非NULLを要求するフィルタ列は2列のまま変えないため、"
            "構成間で分析サンプルは同一になる。"
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
        ValueError: 未知のデータソース識別子が含まれる場合、または
            `POPULATION_SOURCE_NONE` が他の値と併用されている場合。
    """
    if list(population_sources) == [POPULATION_SOURCE_NONE]:
        return []

    # 併用は `parse_arguments` でも弾いているが、本関数を直接呼ぶ経路では
    # 「未知のデータソース」という誤った理由のエラーになるため、ここでも判定する。
    if POPULATION_SOURCE_NONE in population_sources:
        raise ValueError(
            f"{POPULATION_SOURCE_NONE} は他の人口密度データソースと併用できません: "
            f"{list(population_sources)}。"
        )

    unknown = [source for source in population_sources if source not in POPULATION_SOURCE_COLUMNS]
    if unknown:
        raise ValueError(
            f"未知の人口密度データソースです: {unknown}"
            f"（対応: {', '.join(POPULATION_SOURCE_COLUMNS)}）。"
        )
    return [POPULATION_SOURCE_COLUMNS[source] for source in population_sources]


def resolve_building_height_columns(building_height_mode: str) -> list[str]:
    """建物高さ構成の指定から、モデルへ投入する建物高さ列の列名を求める。

    `BUILD_H_MEAN` と `BUILD_H_MAX` は同一の建物ポリゴンから集計した高さであり
    強く相関する。2列とも投入するとVIFが危険水準（>10）に達し、標準化係数を
    個別の寄与として読めなくなるため、投入する高さ列を切り替えられるようにする。

    **`BUILDING_HEIGHT_MODE_PC1` が返す `BUILDING_HEIGHT_PC1_COLUMN` は入力データ
    セットには存在しない合成列である**（`add_building_height_pc1` が分析サンプル上で
    作る）。そのため非NULL要求のフィルタ列には使えず、`resolve_filter_columns` は
    構成に依らず `BUILDING_HEIGHT_MODE_BOTH` を渡す。

    Args:
        building_height_mode: `BUILDING_HEIGHT_MODES` のいずれか。
    Returns:
        投入する建物高さ列の列名リスト。
    Raises:
        ValueError: `building_height_mode` が対応外の場合。
    """
    if building_height_mode not in BUILDING_HEIGHT_MODES:
        raise ValueError(
            f"対応していない建物高さ構成です: {building_height_mode}"
            f"（対応: {', '.join(BUILDING_HEIGHT_MODES)}）。"
        )
    if building_height_mode == BUILDING_HEIGHT_MODE_BOTH:
        return list(BUILDING_HEIGHT_COLUMNS)
    if building_height_mode == BUILDING_HEIGHT_MODE_MEAN:
        return [BUILDING_HEIGHT_MEAN_COLUMN]
    if building_height_mode == BUILDING_HEIGHT_MODE_MAX:
        return [BUILDING_HEIGHT_MAX_COLUMN]
    return [BUILDING_HEIGHT_PC1_COLUMN]


def resolve_feature_columns(
    variable_set: str,
    population_sources: Sequence[str],
    building_height_mode: str = DEFAULT_BUILDING_HEIGHT_MODE,
) -> list[str]:
    """変数セット・建物高さ構成・人口ソースの指定から、モデルへ投入する説明変数の列名を組み立てる。

    共通ベース（建物・道路・標高・人口・夜間光）を先に並べ、差し替え対象の
    ブロック（分光指数・土地被覆クラス別面積率）を後ろに置く。列順は
    重要度CSV・VIF・SHAPの並び順にそのまま現れるため、構成間で共通部分の
    並びが揃うようにしている。建物高さブロックも共通ベースの位置のまま
    差し替えるため、`building_height_mode` を変えても他の列の並びは動かない。

    Args:
        variable_set: `VARIABLE_SETS` のいずれか。
        population_sources: `--population-source` の値。
        building_height_mode: `BUILDING_HEIGHT_MODES` のいずれか。既定は
            `DEFAULT_BUILDING_HEIGHT_MODE`。
    Returns:
        説明変数の列名リスト。
    Raises:
        ValueError: `variable_set` または `building_height_mode` が対応外の場合、
            または `population_sources` に未知のデータソース識別子が含まれる場合。
    """
    if variable_set not in VARIABLE_SETS:
        raise ValueError(
            f"対応していない変数セットです: {variable_set}（対応: {', '.join(VARIABLE_SETS)}）。"
        )

    feature_columns = [
        *BUILDING_FOOTPRINT_FEATURE_COLUMNS,
        *resolve_building_height_columns(building_height_mode),
        *OTHER_BASE_FEATURE_COLUMNS,
        *resolve_population_columns(population_sources),
        *NIGHTLIGHT_FEATURE_COLUMNS,
    ]
    if variable_set in (VARIABLE_SET_SPECTRAL, VARIABLE_SET_BOTH):
        feature_columns.extend(SPECTRAL_FEATURE_COLUMNS)
    if variable_set in (VARIABLE_SET_COVERAGE, VARIABLE_SET_BOTH):
        feature_columns.extend(LULC_FEATURE_COLUMNS)
    return feature_columns


def resolve_filter_columns(population_sources: Sequence[str]) -> list[str]:
    """非NULLを要求してフィルタに使う列名を、変数セットに依らず一定に組み立てる。

    **モデルへ投入する列（`resolve_feature_columns`）とは別物である。** フィルタ列を
    投入列と一致させると、変数セットごとにフィルタ後の母数が変わり、本スクリプトの
    目的である「分光指数 vs 被覆率型のどちらが LST をよりよく説明するか」の比較が
    母数差の影響と混ざる。比較軸（`--variable-set`）で母数を揃えるため、3構成の
    和集合＝`both` の列を常に要求する。

    これは衛星有効性の担保も兼ねる。`filter_valid_rows` は `VALID_SATELLITE_MASK`
    を独立の条件として課さず、「分光指数の非NULL要求が包含する」ことを前提にして
    いる。投入列でフィルタすると `coverage` 構成でこの前提が崩れ、分光指数が
    すべてNULLのセル（雲マスク由来の欠測）が `coverage` のときだけ母集団へ
    混入する。

    建物高さ構成（`--building-height`）についても同じ理由で `both` を固定し、
    **投入する高さ列が1本でも `BUILD_H_MEAN`・`BUILD_H_MAX` の両方に非NULLを要求
    する**。片方だけを要求すると、もう片方だけが欠測のセルが構成によって出入りし、
    3構成の比較が母数差と混ざる。主成分構成で投入する `BUILD_H_PC1` は入力データ
    セットに存在しない合成列であり、そもそもフィルタ列には使えない。

    Args:
        population_sources: `--population-source` の値。人口だけは選択した版のみを
            要求する（3版すべてを要求すると、投入しない版の欠測で母数が減るため）。
    Returns:
        非NULLを要求する列名リスト。
    """
    return resolve_feature_columns(VARIABLE_SET_BOTH, population_sources, BUILDING_HEIGHT_MODE_BOTH)


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

    **判定は母集団ではなく、渡されたデータフレーム（実運用では分析サンプル）を
    対象に行う。** VIF も同じサンプルで算出するため、判定対象を揃えないと
    「母集団では非定数だがサンプルでは定数」の列が残って VIF が `inf` になる。
    代償として、母集団での出現頻度が低いクラスは `--sample-size` /
    `--random-state` によって除外されたりされなかったりしうる。ラン間で構成が
    変わったことを後から追えるよう、除外した列名は結果JSONへ記録する。

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
    平均絶対SHAP値を合算する。この合算は符号付きSHAP値を先に合算した場合と
    一致せず、グループ寄与の**上限**にあたる（`VEGETATION_COVERAGE_COLUMNS`
    のコメント参照）。

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
            "事後合算した値を記録する。符号付きSHAP値を先に合算した場合と一致せず、"
            "グループ寄与の上限にあたる。"
        ),
    }


def resolve_output_stem(
    dataset_path: Path,
    variable_set: str,
    population_sources: Sequence[str],
    require_valid_gis_mask: bool,
    building_height_mode: str = DEFAULT_BUILDING_HEIGHT_MODE,
) -> str:
    """データセットパスと実行条件から出力ファイル名の接頭辞を求める。

    構成の異なるランを同一ディレクトリへ出力しても上書きしないよう、
    `{データセットstem}_{変数セット}[_bh_{建物高さ}][_pop_{ソース}...][_gismask]`
    の順で組み立てる。これにより出力ファイル名自体が実行条件を示す。

    **省略の基準が人口ソースと建物高さで異なる。**

    - **人口ソースは既定（`DEFAULT_POPULATION_SOURCES`）の場合は付けない。**
      既定から変えたランだけが名前に現れるようにして、既存の出力名との差分を
      変数セットの追加だけに抑えるためである。
    - **建物高さは既定ではなく `BUILDING_HEIGHT_MODE_BOTH` という値の場合に付けない。**
      建物高さは比較の結果しだいで `DEFAULT_BUILDING_HEIGHT_MODE` そのものが
      変わりうる軸である。既定を基準に省略すると、既定を変えた瞬間に新しい既定
      （例: `mean`）の出力名が `_bh_mean` 無しの形へ移り、**`both` で実行済みの
      既存ランの出力ファイルと衝突して上書きする**。値を基準にすれば既定を
      変えても既存の出力名は動かない。
    - **`_gismask` は末尾に置く。** 感度分析の印を末尾に付ける既存の規約を保つ。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        variable_set: `VARIABLE_SETS` のいずれか。
        population_sources: `--population-source` の値。
        require_valid_gis_mask: `VALID_GIS_MASK == 1` を課す感度分析かどうか。
        building_height_mode: `BUILDING_HEIGHT_MODES` のいずれか。既定は
            `DEFAULT_BUILDING_HEIGHT_MODE`。
    Returns:
        出力ファイル名の接頭辞。
    """
    parts = [dataset_path.stem, variable_set]
    if building_height_mode != BUILDING_HEIGHT_MODE_BOTH:
        parts.append(f"bh_{building_height_mode}")
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
    filter_columns: Sequence[str],
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
        filter_columns: 非NULLを要求する列名（`resolve_filter_columns` の戻り値）。
            **モデルへ投入する列とは別物**であり、変数セットに依らず同じ列を
            渡すことで構成間の母数を揃える（理由は `resolve_filter_columns`）。
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
        feature_columns=list(filter_columns),
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


def _sanitize_finite_value(value: float, non_finite_keys: list[str], key: str) -> float | None:
    """非有限値（Inf・NaN）を `None` へ置き換え、該当したキーを記録する。

    `src.common.summary.save_summary` は `allow_nan=False` でありInf・NaNを例外に
    するため、そのまま渡すとフル実行の**最終保存時**に落ちる（モデル学習・SHAPを
    すべて終えた後であり、どの値が原因かも分からない）。`sanitize_vif_for_json` と
    同じ方針で、値は `None` に落としつつ「非有限だった項目名」を別に残す。

    Args:
        value: 検査する値。
        non_finite_keys: 非有限だった場合にキー名を追記するリスト（副作用あり）。
        key: 記録するキー名。**診断辞書の中でのパス**（例: `standardization.means.BUILD_H_MEAN`）
            を渡す。値だけを見て該当箇所を辿れるようにするため、辞書の入れ子構造を
            省略しない。
    Returns:
        有限なら `float`、非有限なら `None`。
    """
    if math.isfinite(value):
        return float(value)
    non_finite_keys.append(key)
    return None


def add_building_height_pc1(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """建物高さ2列を標準化し、第1主成分に合成した列を追加する。

    `BUILD_H_MEAN` と `BUILD_H_MAX` を標準化した2変数の相関行列は `[[1, r], [r, 1]]`
    であり、`r > 0` のとき第1主成分の固有ベクトルは `(1/√2, 1/√2)`・寄与率は
    `(1 + r) / 2` になる。つまり主成分化は「2列の平均的な高さ水準」を1本に束ねる
    操作であり、高さブロックの共線性を残さずに情報を保持する構成になる。
    **`r < 0` では第1主成分が `(1/√2, -1/√2)` へ入れ替わるため、この形は無条件の
    恒等式ではない。**

    **fitは分析サンプル全体で1回だけ行い、Spatial CVのfold内では行わない。**
    平均・尺度に由来するリークは既存パイプラインが既に除いており
    （`src.common.regression_models.fit_linear_regression` は学習側だけで
    `StandardScaler` をfitする）、全体fitのPC1が持ち込むfold依存は「高さ2列の
    標準偏差の比」だけに限られる。この差による決定係数の変化は実測でモデル自身の
    数値的なばらつきより小さく、共通モジュールへfold内変換の仕組みを持ち込む
    コストに見合わないと判断した（判断の根拠は
    `docs/03_results/limited_analysis_results.md` を正本とする）。

    **主成分の符号は実装依存で不定なため、`BUILD_H_MEAN` に対する寄与が正になる
    向きへ揃える。** 揃えないと「PC1が大きいほど建物が低い」という向きが偶発的に
    生じ、標準化係数・SHAP値の符号解釈が反転する。単一主成分では
    `cov(PC1, z_j) = λ * loadings[j]`（`λ > 0`）であり、相関の符号と loadings の
    符号は一致するため、loadings の符号で判定する。

    Args:
        dataframe: 建物高さ2列を非NULLで含むデータフレーム
            （`build_filtered_sample` の戻り値 `sampled` を想定）。
    Returns:
        `BUILDING_HEIGHT_PC1_COLUMN` を追加したデータフレーム（入力は変更しない）と、
        主成分の診断情報（loadings・寄与率・標準化統計・元2列の相関・符号反転の
        有無）の辞書のタプル。**診断情報の数値が非有限（高さ2列が定数に近く主成分が
        縮退した場合）なら `None` へ置き換え、該当項目名を `non_finite_items` に
        残す**（`_sanitize_finite_value` 参照）。
    Raises:
        ValueError: 建物高さ列が存在しない場合、または欠測が残っている場合。
    """
    missing_columns = [
        column for column in BUILDING_HEIGHT_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        raise ValueError(
            f"建物高さの主成分化に必要な列がありません: {missing_columns}"
            f"（必要: {BUILDING_HEIGHT_COLUMNS}）。"
        )

    heights = dataframe[BUILDING_HEIGHT_COLUMNS]
    if bool(heights.isna().to_numpy().any()):
        raise ValueError(
            "建物高さ列に欠測が残っているため主成分化できません。"
            "fill_missing_building_heights と filter_valid_rows を通した後の"
            "データフレームを渡してください。"
        )

    scaler = StandardScaler()
    standardized = scaler.fit_transform(heights.to_numpy(dtype=float))
    pca = PCA(n_components=1)
    scores = pca.fit_transform(standardized)[:, 0]
    loadings = pca.components_[0]

    mean_index = BUILDING_HEIGHT_COLUMNS.index(BUILDING_HEIGHT_MEAN_COLUMN)
    sign_flipped = bool(loadings[mean_index] < 0)
    if sign_flipped:
        loadings = -loadings
        scores = -scores

    with_pc1 = dataframe.copy()
    with_pc1[BUILDING_HEIGHT_PC1_COLUMN] = scores

    # 高さ2列がともに定数の場合、標準化後が全て0になりPCAの寄与率・元2列の相関が
    # NaNになる。そのまま残すと save_summary（allow_nan=False）がフル実行の最終保存
    # 時に落ちるため、VIFと同じ方針で None へ落として項目名を別に残す。
    non_finite_keys: list[str] = []
    diagnostics: dict[str, object] = {
        "column": BUILDING_HEIGHT_PC1_COLUMN,
        "source_columns": list(BUILDING_HEIGHT_COLUMNS),
        # fit対象は分析サンプル（既定10万件）であり、フィルタ前の母集団ではない。
        # 記録する寄与率・loadingsもこのサンプル上の値である。
        "fit_row_count": int(len(dataframe)),
        "loadings": {
            column: _sanitize_finite_value(value, non_finite_keys, f"loadings.{column}")
            for column, value in zip(BUILDING_HEIGHT_COLUMNS, loadings, strict=True)
        },
        "explained_variance_ratio": _sanitize_finite_value(
            pca.explained_variance_ratio_[0], non_finite_keys, "explained_variance_ratio"
        ),
        "source_correlation_pearson": _sanitize_finite_value(
            heights[BUILDING_HEIGHT_MEAN_COLUMN].corr(heights[BUILDING_HEIGHT_MAX_COLUMN]),
            non_finite_keys,
            "source_correlation_pearson",
        ),
        "standardization": {
            "means": {
                column: _sanitize_finite_value(
                    value, non_finite_keys, f"standardization.means.{column}"
                )
                for column, value in zip(BUILDING_HEIGHT_COLUMNS, scaler.mean_, strict=True)
            },
            "scales": {
                column: _sanitize_finite_value(
                    value, non_finite_keys, f"standardization.scales.{column}"
                )
                for column, value in zip(BUILDING_HEIGHT_COLUMNS, scaler.scale_, strict=True)
            },
        },
        "sign_flipped": sign_flipped,
        "non_finite_items": non_finite_keys,
        "note": (
            "主成分は分析サンプル全体で1回fitしており、Spatial CVのfold内では"
            "fitし直していない。標準化はfitと同じサンプル上の平均・標準偏差による。"
            "符号はBUILD_H_MEANへの寄与が正になる向きへ揃えてある。"
            "non_finite_items が空でない場合、高さ2列が定数に近く主成分が縮退している"
            "（該当項目の値は null に置き換えてある）。"
        ),
    }
    return with_pc1, diagnostics


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
    feature_columns = resolve_feature_columns(
        args.variable_set, args.population_source, args.building_height
    )
    # フィルタ列は変数セット・建物高さ構成に依らず一定にして、構成間の母数を揃える
    # （`resolve_filter_columns` の docstring に理由を記す）。
    filter_columns = resolve_filter_columns(args.population_source)
    output_stem = resolve_output_stem(
        args.dataset_path,
        args.variable_set,
        args.population_source,
        args.require_valid_gis_mask,
        args.building_height,
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
        *dict.fromkeys([*filter_columns, *ALL_CANDIDATE_FEATURE_COLUMNS]),
        TARGET_COLUMN,
        IN_ANALYSIS_AREA_COLUMN,
        LST_VALID_RATIO_COLUMN,
        VALID_GIS_MASK_COLUMN,
    ]
    dataframe = load_analysis_dataset(args.dataset_path, columns=required_columns)
    # フィルタ列は投入列の上位集合であり、変数セットに依らず全て必要になる。
    missing_columns = [column for column in filter_columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            f"フィルタに必要な列がデータセットに存在しません: {missing_columns}"
            f"（{args.dataset_path}）。--variable-set の選択に関わらず、構成間で母数を"
            "揃えるため分光指数・土地被覆の両方を要求します。--population-source の"
            "指定と、データセットの生成時に結合したテーブルを確認してください。"
        )

    filtered_sample_result = build_filtered_sample(
        dataframe,
        filter_columns=filter_columns,
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

    # 主成分列は分析サンプル（フィルタ・サンプリング後）を対象にfitするため、
    # VIF算出・モデル学習の前かつ標本が確定した後のここで追加する。定数列の除外
    # （drop_constant_features）より前に置き、合成後の列も同じ検査を通す。
    building_height_pc1 = None
    if args.building_height == BUILDING_HEIGHT_MODE_PC1:
        sampled, building_height_pc1 = add_building_height_pc1(sampled)

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
    run_conditions: dict[str, object] = {
        "variable_set": args.variable_set,
        "building_height_mode": args.building_height,
        "population_sources": list(args.population_source),
        "features": model_feature_columns,
        "requested_features": feature_columns,
        # フィルタ列は投入列と別で、変数セットに依らず一定にしている。構成間で
        # 母数が揃っていることを結果から検証できるよう、列そのものを記録する。
        "filter_columns": filter_columns,
        "filter_columns_note": (
            "非NULLを要求する列は変数セットに依らず一定にし、spectral / coverage / both の"
            "母数を揃えている。投入列でフィルタすると coverage のときだけ衛星有効性の条件"
            "（分光指数の非NULL要求が VALID_SATELLITE_MASK を包含する前提）が外れる。"
        ),
        "dropped_constant_features": dropped_constant_features,
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "require_valid_gis_mask": args.require_valid_gis_mask,
        "required_mask_columns": list(required_mask_columns),
    }
    if building_height_pc1 is not None:
        # 主成分の向き・寄与率は結果の解釈に直結するため、診断のみの実行でも
        # フル実行でも同じ内容を残す。
        run_conditions["building_height_pc1"] = building_height_pc1

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
