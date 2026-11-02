"""水域データ（GLC_FCS30D・Esri 10m LULC・JRC GSW・観測日の MNDWI）の空間的一致度を評価する。

Limited シナリオの水域被覆率 `LULC_WATER_COV` は GLC_FCS30D の水域クラス（210）から
算出している。その元データの妥当性を見るため、独立した水域データと同じグリッド上で比べ、
水域の範囲がデータ選択でどれだけ変わり、どこで食い違うかを集計する。

方法上の要点:
- 比較の土台は、主採用観測のデータセットが使う **30m 正準グリッド（解析CRS・投影座標系）**
  である。データセットの `cell_id` から格子を復元し、`IN_ANALYSIS_AREA == 1` のセルを対象にする。
- 各ラスタはセル内の水域面積率へ集約する。集約には `LULC_WATER_COV` と同じ
  `aggregate_class_fractions_to_grid()`（`Resampling.average`）を使うため、GLC の結果は
  データセットの `LULC_WATER_COV` と一致するはずであり、これを検算として記録する。
- JRC の Occurrence（0〜100%）・年次・月次は、画素値 → 水域／非水域の引き当て表で二値化してから
  同じ関数で集約する（閾値ごとに引き当て表を変えるだけで、一時ファイルを作らない）。
- セルは「有効画素率が `MIN_VALID_RATIO` 以上」のときだけ有効とし、水域面積率が
  `WATER_FRACTION_THRESHOLD` 以上なら水域とみなす。MNDWI はセル値を閾値で二値化する。
- どのデータも真値ではないため、精度（accuracy）ではなく**一致度（agreement）**として扱う。
  MNDWI は LST と同じ画像から算出しており、観測日の水域の目安にはなるが独立な参照ではない。
- 面積は投影座標系のセル（30m × 30m）の個数から km² で求める。

実行例::

    python -m src.analysis.compare_water_sources
"""

from __future__ import annotations

import argparse
import csv
import itertools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import pyogrio
import rasterio
from pyproj import CRS

from src.analysis.mask_agreement import compute_binary_agreement
from src.analysis.urban_params.canonical_grid import (
    CanonicalGridSpec,
    build_canonical_grid,
    split_cell_id,
)
from src.analysis.urban_params.config import ANALYSIS_EXTENT_LAYER_KEY, CITY_CONFIG
from src.analysis.urban_params.grid import GridSpec
from src.analysis.urban_params.io import bbox_from_layer, get_layer_resource
from src.analysis.urban_params.params.lulc import COLUMN_TO_COMMON_CLASS
from src.analysis.urban_params.params.raster import aggregate_class_fractions_to_grid
from src.analysis.urban_params.tables import build_aligned_grid
from src.common.analysis_dataset import IN_ANALYSIS_AREA_COLUMN
from src.common.config import PROJECT_ROOT
from src.common.lulc_classes import (
    COMMON_CLASS_LABELS,
    COMMON_WATER,
    ESRI_TO_COMMON,
    GLC_TO_COMMON,
    build_class_lookup,
)
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.summary import build_provenance, save_summary
from src.preprocessing.fetch_jrc_gsw_hanoi import BAND_DEFINITIONS as JRC_BAND_DEFINITIONS

SCRIPT_NAME = "src.analysis.compare_water_sources"
# 来歴で生成スクリプトと既定の監視パス（`src/common/` 等）に加えて監視するコード。
# 集約（`LULC_WATER_COV` と同じ関数・グリッドの作り方）、一致度の指標、JRC のバンド定義は
# いずれも `src/common/` の外にあり、変わると比較結果が変わるため陳腐化として検出する。
WATCH_PATHS: tuple[str, ...] = (
    "src/analysis/mask_agreement.py",
    "src/analysis/compare_lulc_esri_glc.py",
    "src/analysis/urban_params/params/raster.py",
    "src/analysis/urban_params/params/lulc.py",
    "src/analysis/urban_params/tables.py",
    "src/analysis/urban_params/grid.py",
    "src/analysis/urban_params/io.py",
    "src/analysis/urban_params/config.py",
    "src/preprocessing/fetch_jrc_gsw_hanoi.py",
)

DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "data" / "output" / "datasets" / "dataset_limited_20220906_032358_hanoi_30m.gpkg"
)
DEFAULT_GLC_PATH = (
    PROJECT_ROOT / "data" / "gis" / "lulc" / "glc_fcs30d" / "glc_fcs30d_hanoi_2022.tif"
)
DEFAULT_ESRI_PATH = PROJECT_ROOT / "data" / "gis" / "lulc" / "esri_10m" / "esri_lulc_hanoi_2022.tif"
DEFAULT_JRC_PATH = (
    PROJECT_ROOT / "data" / "gis" / "water" / "jrc_gsw" / "jrc_gsw_hanoi_y2021_m202109.tif"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"
DEFAULT_MASK_DIR = PROJECT_ROOT / "data" / "gis" / "water" / "comparison"
DEFAULT_LABEL = "hanoi_20220906"

CITY = "hanoi"
CELL_ID_COLUMN = "cell_id"
MNDWI_COLUMN = "MNDWI"
DATASET_WATER_COLUMN = "LULC_WATER_COV"

# 正準グリッドの解像度（m）。fine 解像度は build_aligned_grid() の引数として要るだけで、
# 面積率の集約は coarse グリッドへ直接行われる（LULC パイプラインと同じ）
COARSE_RES_M = 30.0
FINE_RES_M = 10.0

# セルを有効とみなす有効画素率の下限。月次の雲欠測などで一部しか観測されていないセルを、
# 少数画素だけで水域判定しないための規則（セルの過半が観測されていること）
MIN_VALID_RATIO = 0.5
# セルを水域とみなす水域面積率の下限（セルの過半が水域）
WATER_FRACTION_THRESHOLD = 0.5

# JRC Occurrence の閾値（%）。主は 50%（期間の半分以上で水域）
OCCURRENCE_THRESHOLDS: tuple[int, ...] = (25, 50, 75, 90)
PRIMARY_OCCURRENCE_THRESHOLD = 50

# MNDWI の閾値。主は 0（Xu, 2006 の標準閾値）。感度は -0.2〜0.3 を 0.05 刻みで見る
# 浮動小数の刻み（np.arange）で作ると 0 付近が -0.0 になり識別子が `mndwi_-0.00` に化けるため、
# 百分率の整数から作る
MNDWI_THRESHOLDS: tuple[float, ...] = tuple(step / 100 for step in range(-20, 31, 5))
PRIMARY_MNDWI_THRESHOLD = 0.0
# 大津の閾値の算出に使うヒストグラムのビン数
OTSU_BINS = 256

# 二値化の引き当て表で使うクラス ID（集約関数へ渡すための便宜上の値）
BINARY_WATER = 1
BINARY_OTHER = 2

# JRC GeoTIFF のバンド番号（取得スクリプトのバンド定義の順）
JRC_BAND_INDEX = {band.name: index for index, band in enumerate(JRC_BAND_DEFINITIONS, start=1)}

# マスク GeoTIFF の値
MASK_NOT_WATER = 0
MASK_WATER = 1
MASK_NODATA = 255

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaterLayer:
    """比較に使う 1 種類の水域判定（セル単位）。

    Attributes:
        key: 出力で使う識別子。
        label: 日本語の表示名。
        definition: 水域の定義（閾値を含む）。
        water: 水域セルを True とする 1 次元配列（無効セルは False）。
        valid: 判定が有効なセルを True とする 1 次元配列。
        fraction: セル内の水域面積率（ラスタ由来のみ。MNDWI は None）。
    """

    key: str
    label: str
    definition: str
    water: np.ndarray
    valid: np.ndarray
    fraction: np.ndarray | None = None


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="GLC・Esri・JRC GSW・MNDWI の水域を 30m 正準グリッド上で比較する。"
    )
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--glc-path", type=Path, default=DEFAULT_GLC_PATH)
    parser.add_argument("--esri-path", type=Path, default=DEFAULT_ESRI_PATH)
    parser.add_argument("--jrc-path", type=Path, default=DEFAULT_JRC_PATH)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="サマリー JSON・CSV の出力先。",
    )
    parser.add_argument(
        "--mask-dir",
        type=Path,
        default=DEFAULT_MASK_DIR,
        help="セル単位の水域マスク GeoTIFF（Git管理外）の出力先。",
    )
    parser.add_argument("--label", default=DEFAULT_LABEL, help="出力ファイル名に使う識別子。")
    return parser.parse_args()


def load_dataset_cells(dataset_path: Path) -> pd.DataFrame:
    """データセットから比較に要る列を読み、分析対象範囲のセルに絞る。

    Args:
        dataset_path: データセット GeoPackage のパス（属性のみのレイヤ 1 つ）。

    Returns:
        `cell_id`・`MNDWI`・`LULC_WATER_COV` を持つデータフレーム（`IN_ANALYSIS_AREA == 1` のみ）。

    Raises:
        FileNotFoundError: データセットが存在しない場合。
        ValueError: 必要な列が無い場合、または `cell_id` に重複がある場合。
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"データセットが見つかりません: {dataset_path}")
    columns = [CELL_ID_COLUMN, IN_ANALYSIS_AREA_COLUMN, MNDWI_COLUMN, DATASET_WATER_COLUMN]
    available = set(pyogrio.read_info(dataset_path)["fields"])
    missing = [column for column in columns if column not in available]
    if missing:
        raise ValueError(f"データセットに必要な列がありません: {missing}（{dataset_path}）")

    frame = pyogrio.read_dataframe(dataset_path, columns=columns, read_geometry=False)
    frame = frame.loc[frame[IN_ANALYSIS_AREA_COLUMN] == 1].reset_index(drop=True)
    if frame[CELL_ID_COLUMN].duplicated().any():
        raise ValueError(f"cell_id に重複があります: {dataset_path}")
    return frame


def build_roi_canonical_grid(city: str = CITY) -> tuple[CanonicalGridSpec, Path]:
    """データセットの生成時と同じ手順で、ROI を覆う 30m 正準グリッドを作る。

    集約（`Resampling.average` による再投影）の結果は、集約先の格子の範囲によってわずかに
    変わりうる。`LULC_WATER_COV` と同じ値を得るため、範囲は `urban_params.run` と同じく
    ROI レイヤの BBox から決める（対象セルの範囲から決めない）。

    Args:
        city: `CITY_CONFIG` の都市キー。

    Returns:
        (正準グリッドの仕様, ROI レイヤのパス)。
    """
    city_config = CITY_CONFIG[city]
    analysis_crs = CRS.from_epsg(int(city_config["analysis_epsg"]))
    roi_resource = get_layer_resource(city_config, ANALYSIS_EXTENT_LAYER_KEY, analysis_crs)
    roi_bbox = bbox_from_layer(roi_resource, analysis_crs)
    return build_canonical_grid(roi_bbox, analysis_crs, COARSE_RES_M), roi_resource.path


def locate_cells(
    cell_ids: np.ndarray, canonical_spec: CanonicalGridSpec
) -> tuple[GridSpec, np.ndarray]:
    """集約用の GridSpec と、各セルの 2 次元配列上の位置（平坦化インデックス）を求める。

    正準グリッドの `row` は北向きが正であり、ラスタ配列の行（北から南へ増える）とは向きが逆
    である。そのため配列上の行は `row_max - row` になる（`tables.build_param_table` と同じ対応）。

    Args:
        cell_ids: 対象セルの `cell_id`（1 次元）。
        canonical_spec: 正準グリッドの仕様。

    Returns:
        (集約用の GridSpec, 各セルの平坦化インデックス)。

    Raises:
        ValueError: 正準グリッドの範囲外を指す `cell_id` がある場合（データセットと
            グリッドの取り違え）。
    """
    grid_spec = build_aligned_grid(canonical_spec, FINE_RES_M)
    rows, cols = split_cell_id(np.asarray(cell_ids, dtype=np.int64))
    row_offsets = canonical_spec.row_max - np.asarray(rows, dtype=np.int64)
    col_offsets = np.asarray(cols, dtype=np.int64) - canonical_spec.col_min
    out_of_range = (
        (row_offsets < 0)
        | (row_offsets >= canonical_spec.n_rows)
        | (col_offsets < 0)
        | (col_offsets >= canonical_spec.n_cols)
    )
    if bool(out_of_range.any()):
        raise ValueError(
            f"正準グリッドの範囲外を指す cell_id が {int(out_of_range.sum())} 件あります"
            f"（例: {np.asarray(cell_ids)[out_of_range][:5].tolist()}）。"
        )
    return grid_spec, row_offsets * canonical_spec.n_cols + col_offsets


def build_binary_lookup(water_values: Sequence[int], other_values: Sequence[int]) -> np.ndarray:
    """画素値 → 水域／非水域の引き当て表を作る。どちらにも無い値は無効になる。

    Args:
        water_values: 水域とみなす画素値。
        other_values: 非水域とみなす画素値。

    Returns:
        引き当て表（`BINARY_WATER`・`BINARY_OTHER`・無効 0）。

    Raises:
        ValueError: 同じ値が水域と非水域の両方に含まれる場合。
    """
    overlap = sorted(set(water_values) & set(other_values))
    if overlap:
        raise ValueError(f"水域と非水域の両方に含まれる値があります: {overlap}")
    mapping = {int(value): BINARY_WATER for value in water_values}
    mapping.update({int(value): BINARY_OTHER for value in other_values})
    return build_class_lookup(mapping)


def build_occurrence_lookup(threshold: int) -> np.ndarray:
    """Occurrence（0〜100%）を「閾値以上を水域」とする引き当て表を作る。

    Args:
        threshold: 水域とみなす出現頻度の下限（%）。

    Returns:
        引き当て表。

    Raises:
        ValueError: 閾値が 1〜100 の範囲外の場合（0 以下は全画素が水域になる）。
    """
    if not 1 <= threshold <= 100:
        raise ValueError(f"Occurrence の閾値は 1〜100 で指定してください: {threshold}")
    return build_binary_lookup(range(threshold, 101), range(0, threshold))


def build_water_lookup_from_classes(mapping: dict[int, int]) -> np.ndarray:
    """土地被覆の共通クラス写像表から、水域／非水域の引き当て表を作る。

    Args:
        mapping: 元クラス値 → 共通クラス値（`GLC_TO_COMMON` 等）。

    Returns:
        引き当て表。
    """
    water = [value for value, common in mapping.items() if common == COMMON_WATER]
    other = [value for value, common in mapping.items() if common != COMMON_WATER]
    return build_binary_lookup(water, other)


def aggregate_binary_water(
    raster_path: Path,
    band_index: int,
    lookup: np.ndarray,
    grid_spec: GridSpec,
    flat_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """二値化したラスタをセル内の水域面積率へ集約し、対象セルの値を取り出す。

    Args:
        raster_path: 入力ラスタ。
        band_index: バンド番号（1 始まり）。
        lookup: 画素値 → 水域／非水域の引き当て表。
        grid_spec: 集約先のグリッド。
        flat_indices: 対象セルの平坦化インデックス。

    Returns:
        (水域面積率, 有効画素率)。いずれも対象セル順の 1 次元配列。面積率は有効画素が無いと NaN。
    """
    fractions, valid_ratio = aggregate_class_fractions_to_grid(
        raster_path, grid_spec, band_index, lookup, [BINARY_WATER, BINARY_OTHER], "水域"
    )
    return fractions[BINARY_WATER].ravel()[flat_indices], valid_ratio.ravel()[flat_indices]


def aggregate_lulc_classes(
    raster_path: Path,
    mapping: dict[int, int],
    grid_spec: GridSpec,
    flat_indices: np.ndarray,
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """土地被覆ラスタを、`LULC_*_COV` と同じ 7 クラスの面積率へ集約する。

    Args:
        raster_path: 土地被覆ラスタ。
        mapping: 元クラス値 → 共通クラス値。
        grid_spec: 集約先のグリッド。
        flat_indices: 対象セルの平坦化インデックス。

    Returns:
        (共通クラス ID → 面積率, 有効画素率)。いずれも対象セル順の 1 次元配列。
    """
    fractions, valid_ratio = aggregate_class_fractions_to_grid(
        raster_path,
        grid_spec,
        1,
        build_class_lookup(mapping),
        list(COLUMN_TO_COMMON_CLASS.values()),
        "土地被覆",
    )
    return (
        {class_id: array.ravel()[flat_indices] for class_id, array in fractions.items()},
        valid_ratio.ravel()[flat_indices],
    )


def dominant_class(fractions: dict[int, np.ndarray]) -> np.ndarray:
    """セルごとに面積率が最大の共通クラスを返す。

    同率の場合はクラス ID の小さい方を採る（実行ごとに結果が変わらないように）。

    Args:
        fractions: 共通クラス ID → 面積率（NaN は有効画素なし）。

    Returns:
        共通クラス ID の 1 次元配列。全クラスが NaN のセルは 0。
    """
    class_ids = sorted(fractions)
    stacked = np.stack([np.nan_to_num(fractions[class_id], nan=-1.0) for class_id in class_ids])
    winners = np.array(class_ids)[np.argmax(stacked, axis=0)]
    all_missing = np.all(stacked < 0, axis=0)
    return np.where(all_missing, 0, winners)


def binarize_fraction(
    fraction: np.ndarray,
    valid_ratio: np.ndarray,
    water_threshold: float = WATER_FRACTION_THRESHOLD,
    min_valid_ratio: float = MIN_VALID_RATIO,
) -> tuple[np.ndarray, np.ndarray]:
    """水域面積率を、セル単位の水域判定（水域・有効）へ変換する。

    Args:
        fraction: 水域面積率（NaN は有効画素なし）。
        valid_ratio: 有効画素率。
        water_threshold: 水域とみなす面積率の下限。
        min_valid_ratio: 有効とみなす有効画素率の下限。

    Returns:
        (水域セル, 有効セル)。無効セルの水域は False。
    """
    valid = (valid_ratio >= min_valid_ratio) & ~np.isnan(fraction)
    water = valid & (np.nan_to_num(fraction, nan=0.0) >= water_threshold)
    return water, valid


def binarize_values(values: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    """連続値（MNDWI）を「閾値以上を水域」として二値化する。

    Args:
        values: セル値（NaN は欠測）。
        threshold: 閾値。

    Returns:
        (水域セル, 有効セル)。
    """
    valid = ~np.isnan(values)
    water = valid & (np.nan_to_num(values, nan=-np.inf) >= threshold)
    return water, valid


def otsu_threshold(values: np.ndarray, bins: int = OTSU_BINS) -> float:
    """大津の方法（クラス間分散の最大化）で二値化の閾値を求める。

    Args:
        values: 値（NaN は除外する）。
        bins: ヒストグラムのビン数。

    Returns:
        閾値（このビン境界以上を上側のクラスとする）。

    Raises:
        ValueError: 有効な値が無い場合、または全値が同じで閾値を決められない場合。
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("大津の閾値を求める有効な値がありません。")
    if float(finite.min()) == float(finite.max()):
        raise ValueError("全値が同じため大津の閾値を決められません。")
    counts, edges = np.histogram(finite, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    weight_low = np.cumsum(counts)
    weight_high = weight_low[-1] - weight_low
    cumulative_mean = np.cumsum(counts * centers)
    mean_low = np.divide(
        cumulative_mean, weight_low, out=np.zeros_like(centers), where=weight_low > 0
    )
    mean_high = np.divide(
        cumulative_mean[-1] - cumulative_mean,
        weight_high,
        out=np.zeros_like(centers),
        where=weight_high > 0,
    )
    between_variance = weight_low * weight_high * (mean_low - mean_high) ** 2
    # 最後のビンの後ろは上側クラスが空になるため候補から除く
    best = int(np.argmax(between_variance[:-1]))
    return float(edges[best + 1])


def format_mndwi_key(threshold: float) -> str:
    """MNDWI の閾値から出力用の識別子を作る（例: 0.0 → `mndwi_+0.00`）。

    Args:
        threshold: 閾値。

    Returns:
        識別子。
    """
    return f"mndwi_{threshold:+.2f}"


def build_raster_layers(
    glc_path: Path,
    esri_path: Path,
    jrc_path: Path,
    grid_spec: GridSpec,
    flat_indices: np.ndarray,
) -> tuple[list[WaterLayer], dict[str, np.ndarray]]:
    """GLC・Esri・JRC の水域判定と、食い違いの内訳に使う優占クラスを作る。

    Args:
        glc_path: GLC_FCS30D ラスタ。
        esri_path: Esri 10m LULC ラスタ。
        jrc_path: JRC GSW ラスタ（取得スクリプトの出力）。
        grid_spec: 集約先のグリッド。
        flat_indices: 対象セルの平坦化インデックス。

    Returns:
        (水域判定のリスト, データ名 → セルの優占共通クラス)。
    """
    layers: list[WaterLayer] = []
    dominant: dict[str, np.ndarray] = {}
    for key, label, path, mapping, code_text in (
        ("glc", "GLC_FCS30D 2022", glc_path, GLC_TO_COMMON, "クラス 210"),
        ("esri", "Esri 10m LULC 2022", esri_path, ESRI_TO_COMMON, "クラス 1 Water"),
    ):
        logger.info("%s を集約します。", label)
        class_fractions, valid_ratio = aggregate_lulc_classes(
            path, mapping, grid_spec, flat_indices
        )
        water, valid = binarize_fraction(class_fractions[COMMON_WATER], valid_ratio)
        layers.append(
            WaterLayer(
                key=key,
                label=label,
                definition=f"{code_text} の面積率 ≥ {WATER_FRACTION_THRESHOLD}",
                water=water,
                valid=valid,
                fraction=class_fractions[COMMON_WATER],
            )
        )
        dominant[key] = dominant_class(class_fractions)

    jrc_definitions: list[tuple[str, str, str, int, np.ndarray]] = [
        (
            f"jrc_occ{threshold}",
            f"JRC Occurrence ≥ {threshold}%",
            f"1984-2021 の出現頻度 ≥ {threshold}% の画素の面積率 ≥ {WATER_FRACTION_THRESHOLD}",
            JRC_BAND_INDEX["occurrence"],
            build_occurrence_lookup(threshold),
        )
        for threshold in OCCURRENCE_THRESHOLDS
    ]
    jrc_definitions += [
        (
            "jrc_yearly_sp",
            "JRC 年次 2021（季節＋恒常）",
            f"2021 年の季節水域・恒常水域の面積率 ≥ {WATER_FRACTION_THRESHOLD}",
            JRC_BAND_INDEX["yearly_water_class"],
            build_binary_lookup([2, 3], [1]),
        ),
        (
            "jrc_yearly_p",
            "JRC 年次 2021（恒常のみ）",
            f"2021 年の恒常水域の面積率 ≥ {WATER_FRACTION_THRESHOLD}",
            JRC_BAND_INDEX["yearly_water_class"],
            build_binary_lookup([3], [1, 2]),
        ),
        (
            "jrc_monthly",
            "JRC 月次 2021-09",
            f"2021 年 9 月の水域の面積率 ≥ {WATER_FRACTION_THRESHOLD}",
            JRC_BAND_INDEX["monthly_water"],
            build_binary_lookup([2], [1]),
        ),
    ]
    for key, label, definition, band_index, lookup in jrc_definitions:
        logger.info("%s を集約します。", label)
        fraction, valid_ratio = aggregate_binary_water(
            jrc_path, band_index, lookup, grid_spec, flat_indices
        )
        water, valid = binarize_fraction(fraction, valid_ratio)
        layers.append(WaterLayer(key, label, definition, water, valid, fraction))
    return layers, dominant


def build_mndwi_layers(mndwi: np.ndarray) -> tuple[list[WaterLayer], float]:
    """MNDWI の閾値ごとの水域判定（大津の閾値を含む）を作る。

    Args:
        mndwi: セルの MNDWI（NaN は欠測）。

    Returns:
        (水域判定のリスト, 大津の閾値)。
    """
    otsu = otsu_threshold(mndwi)
    layers = []
    for threshold in MNDWI_THRESHOLDS:
        water, valid = binarize_values(mndwi, threshold)
        layers.append(
            WaterLayer(
                key=format_mndwi_key(threshold),
                label=f"MNDWI ≥ {threshold:+.2f}（2022-09-06）",
                definition=f"観測日のセル MNDWI ≥ {threshold:+.2f}",
                water=water,
                valid=valid,
            )
        )
    water, valid = binarize_values(mndwi, otsu)
    layers.append(
        WaterLayer(
            key="mndwi_otsu",
            label=f"MNDWI ≥ 大津の閾値 {otsu:+.3f}（2022-09-06）",
            definition=f"観測日のセル MNDWI ≥ {otsu:+.4f}（大津の方法、{OTSU_BINS} ビン）",
            water=water,
            valid=valid,
        )
    )
    return layers, otsu


def compare_layer_pairs(
    layers: dict[str, WaterLayer],
    pairs: Sequence[tuple[str, str]],
    comparison_set: str,
    cell_area_m2: float,
) -> list[dict[str, Any]]:
    """指定したペアごとに一致度指標を求める。

    比較対象は両者とも有効なセルに限るため、ペアごとに有効セル数が異なる。

    Args:
        layers: 識別子 → 水域判定。
        pairs: 比較するペア（A, B）。
        comparison_set: 出力行に付ける比較の種類（`main` 等）。
        cell_area_m2: 1 セルの面積（m²）。

    Returns:
        ペアごとの指標の行。
    """
    rows = []
    for key_a, key_b in pairs:
        layer_a, layer_b = layers[key_a], layers[key_b]
        metrics = compute_binary_agreement(
            layer_a.water, layer_b.water, layer_a.valid & layer_b.valid, cell_area_m2
        )
        rows.append({"comparison_set": comparison_set, "a": key_a, "b": key_b, **metrics})
    return rows


def compare_fractions(layers: dict[str, WaterLayer], keys: Sequence[str]) -> list[dict[str, Any]]:
    """水域面積率（連続値）どうしの相関と差を求める。

    分析で使う `LULC_WATER_COV` は連続値であるため、二値化に依らない比較も併せて記録する。

    Args:
        layers: 識別子 → 水域判定（面積率を持つもの）。
        keys: 比較する識別子。

    Returns:
        ペアごとの Pearson 相関・平均絶対差・平均差（B − A）・比較セル数。
    """
    rows = []
    for key_a, key_b in itertools.combinations(keys, 2):
        layer_a, layer_b = layers[key_a], layers[key_b]
        valid = layer_a.valid & layer_b.valid
        values_a = layer_a.fraction[valid].astype(np.float64)
        values_b = layer_b.fraction[valid].astype(np.float64)
        has_variance = values_a.size > 1 and values_a.std() > 0 and values_b.std() > 0
        rows.append(
            {
                "a": key_a,
                "b": key_b,
                "cells": int(valid.sum()),
                "pearson_r": float(np.corrcoef(values_a, values_b)[0, 1]) if has_variance else None,
                "mean_abs_diff": float(np.abs(values_b - values_a).mean())
                if values_a.size
                else None,
                "mean_diff_b_minus_a": float((values_b - values_a).mean())
                if values_a.size
                else None,
            }
        )
    return rows


def build_disagreement_breakdown(
    layers: dict[str, WaterLayer],
    pairs: Sequence[tuple[str, str]],
    dominant: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    """食い違うセル（片方だけが水域）が、GLC・Esri のどの土地被覆クラスに当たるかを数える。

    参照データが比較の当事者（A か B）である組み合わせは数えない。たとえば「B = Esri が
    水域」のセルを Esri の優占クラスで数えると、ほぼ全件が水域になるだけで情報が無いため。

    Args:
        layers: 識別子 → 水域判定。
        pairs: 内訳を求めるペア（A, B）。
        dominant: データ名（`glc`・`esri`）→ セルの優占共通クラス。

    Returns:
        (ペア, 食い違いの向き, 参照データ, 優占クラス) ごとのセル数の行。
    """
    rows = []
    for key_a, key_b in pairs:
        layer_a, layer_b = layers[key_a], layers[key_b]
        valid = layer_a.valid & layer_b.valid
        directions = {
            "a_only": valid & layer_a.water & ~layer_b.water,
            "b_only": valid & ~layer_a.water & layer_b.water,
            "both": valid & layer_a.water & layer_b.water,
        }
        for direction, selected in directions.items():
            for reference, classes in dominant.items():
                if reference in (key_a, key_b):
                    continue
                values, counts = np.unique(classes[selected], return_counts=True)
                for class_id, count in zip(values.tolist(), counts.tolist()):
                    rows.append(
                        {
                            "a": key_a,
                            "b": key_b,
                            "direction": direction,
                            "reference": reference,
                            "dominant_class": int(class_id),
                            "dominant_class_label": COMMON_CLASS_LABELS.get(int(class_id), "無効"),
                            "cells": int(count),
                        }
                    )
    return rows


def verify_against_dataset(
    glc_fraction: np.ndarray, dataset_fraction: np.ndarray
) -> dict[str, Any]:
    """再集約した GLC の水域面積率が、データセットの `LULC_WATER_COV` と一致するかを検算する。

    Args:
        glc_fraction: 本スクリプトで集約した GLC の水域面積率。
        dataset_fraction: データセットの `LULC_WATER_COV`。

    Returns:
        比較セル数・NaN の一致・最大絶対差・`np.isclose` で一致したセルの割合。
    """
    both_valid = ~np.isnan(glc_fraction) & ~np.isnan(dataset_fraction)
    nan_mismatch = int(np.count_nonzero(np.isnan(glc_fraction) != np.isnan(dataset_fraction)))
    diff = np.abs(glc_fraction[both_valid] - dataset_fraction[both_valid])
    close = np.isclose(glc_fraction[both_valid], dataset_fraction[both_valid], atol=1e-6)
    return {
        "compared_cells": int(both_valid.sum()),
        "nan_mismatch_cells": nan_mismatch,
        "max_abs_diff": float(diff.max()) if diff.size else None,
        "close_ratio": float(close.mean()) if close.size else None,
        "note": "1.0 に近ければ LULC_WATER_COV と同じ集約方式で比べていることが確かめられる。",
    }


def write_mask_raster(
    output_path: Path,
    layers: Sequence[WaterLayer],
    canonical_spec: CanonicalGridSpec,
    grid_spec: GridSpec,
    flat_indices: np.ndarray,
) -> Path:
    """セル単位の水域判定を、正準グリッド上の uint8 GeoTIFF（1 判定 1 バンド）として保存する。

    値は 0: 非水域、1: 水域、255: 無効（対象外セル・有効画素不足・欠測）。

    Args:
        output_path: 出力パス。
        layers: 書き出す水域判定（バンド順）。
        canonical_spec: 正準グリッドの仕様。
        grid_spec: 集約に使ったグリッド（アフィン変換・CRS を使う）。
        flat_indices: 対象セルの平坦化インデックス。

    Returns:
        出力パス。
    """
    shape = (canonical_spec.n_rows, canonical_spec.n_cols)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=len(layers),
        dtype="uint8",
        crs=grid_spec.analysis_crs,
        transform=grid_spec.coarse_transform,
        nodata=MASK_NODATA,
        compress="deflate",
    ) as destination:
        for band_index, layer in enumerate(layers, start=1):
            band = np.full(shape[0] * shape[1], MASK_NODATA, dtype=np.uint8)
            values = np.where(layer.water, MASK_WATER, MASK_NOT_WATER).astype(np.uint8)
            values[~layer.valid] = MASK_NODATA
            band[flat_indices] = values
            destination.write(band.reshape(shape), band_index)
            destination.set_band_description(band_index, layer.key)
    return output_path


def write_rows_csv(rows: list[dict[str, Any]], output_path: Path) -> Path:
    """辞書の行を CSV（UTF-8・BOM 付き）へ書き出す。

    Args:
        rows: 行（すべて同じキーを持つこと）。
        output_path: 出力パス。

    Returns:
        出力パス。

    Raises:
        ValueError: 行が空の場合。
    """
    if not rows:
        raise ValueError(f"書き出す行がありません: {output_path}")
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def describe_layer(layer: WaterLayer, cell_area_m2: float) -> dict[str, Any]:
    """水域判定 1 つの有効域と水域セル数をまとめる。

    Args:
        layer: 水域判定。
        cell_area_m2: 1 セルの面積（m²）。

    Returns:
        表示名・定義・有効セル数・水域セル数・水域面積（km²）。
    """
    valid_cells = int(layer.valid.sum())
    water_cells = int(layer.water.sum())
    return {
        "label": layer.label,
        "definition": layer.definition,
        "valid_cells": valid_cells,
        "valid_ratio": valid_cells / layer.valid.size if layer.valid.size else 0.0,
        "water_cells": water_cells,
        "water_area_km2": water_cells * cell_area_m2 / 1e6,
        "water_ratio_in_valid": (water_cells / valid_cells) if valid_cells else None,
    }


def run(
    dataset_path: Path,
    glc_path: Path,
    esri_path: Path,
    jrc_path: Path,
    output_dir: Path,
    mask_dir: Path,
    label: str,
) -> dict[str, Path]:
    """読み込みから集約・比較・保存までの処理全体を実行する。

    Args:
        dataset_path: データセット GeoPackage。
        glc_path: GLC_FCS30D ラスタ。
        esri_path: Esri 10m LULC ラスタ。
        jrc_path: JRC GSW ラスタ。
        output_dir: サマリー・CSV の出力先。
        mask_dir: 水域マスク GeoTIFF の出力先。
        label: 出力ファイル名の識別子。

    Returns:
        出力の種類 → パス。

    Raises:
        FileNotFoundError: 入力ラスタが存在しない場合。
    """
    for input_path in (glc_path, esri_path, jrc_path):
        if not input_path.exists():
            raise FileNotFoundError(f"入力ラスタが見つかりません: {input_path}")

    stem = f"water_sources_agreement_{label}"
    output_paths = {
        "summary": prepare_output_path(output_dir / f"{stem}_summary.json"),
        "pairwise": prepare_output_path(output_dir / f"{stem}_pairwise.csv"),
        "threshold_sensitivity": prepare_output_path(
            output_dir / f"{stem}_threshold_sensitivity.csv"
        ),
        "confusion": prepare_output_path(output_dir / f"{stem}_confusion.csv"),
        "mask_raster": prepare_output_path(mask_dir / f"water_masks_{label}.tif"),
    }

    cells = load_dataset_cells(dataset_path)
    logger.info("対象セル（IN_ANALYSIS_AREA == 1）: %d", len(cells))
    canonical_spec, roi_path = build_roi_canonical_grid()
    analysis_crs = canonical_spec.analysis_crs
    grid_spec, flat_indices = locate_cells(cells[CELL_ID_COLUMN].to_numpy(), canonical_spec)
    cell_area_m2 = COARSE_RES_M * COARSE_RES_M

    raster_layers, dominant = build_raster_layers(
        glc_path, esri_path, jrc_path, grid_spec, flat_indices
    )
    mndwi_layers, otsu = build_mndwi_layers(cells[MNDWI_COLUMN].to_numpy(dtype=np.float64))
    layers = {layer.key: layer for layer in raster_layers + mndwi_layers}

    primary_occurrence = f"jrc_occ{PRIMARY_OCCURRENCE_THRESHOLD}"
    primary_mndwi = format_mndwi_key(PRIMARY_MNDWI_THRESHOLD)
    main_keys = [
        "glc",
        "esri",
        primary_occurrence,
        "jrc_yearly_sp",
        "jrc_yearly_p",
        "jrc_monthly",
        primary_mndwi,
    ]
    pairwise_rows = compare_layer_pairs(
        layers, list(itertools.combinations(main_keys, 2)), "main", cell_area_m2
    )

    occurrence_refs = ["glc", "esri", "jrc_monthly", primary_mndwi]
    mndwi_refs = ["glc", "esri", primary_occurrence, "jrc_monthly"]
    sensitivity_rows = compare_layer_pairs(
        layers,
        [(f"jrc_occ{t}", ref) for t in OCCURRENCE_THRESHOLDS for ref in occurrence_refs],
        "jrc_occurrence_threshold",
        cell_area_m2,
    ) + compare_layer_pairs(
        layers,
        [(layer.key, ref) for layer in mndwi_layers for ref in mndwi_refs],
        "mndwi_threshold",
        cell_area_m2,
    )

    breakdown_keys = ["glc", "esri", primary_occurrence, "jrc_monthly", primary_mndwi]
    confusion_rows = build_disagreement_breakdown(
        layers, list(itertools.combinations(breakdown_keys, 2)), dominant
    )
    fraction_rows = compare_fractions(layers, ["glc", "esri", primary_occurrence, "jrc_monthly"])
    dataset_check = verify_against_dataset(
        layers["glc"].fraction, cells[DATASET_WATER_COLUMN].to_numpy(dtype=np.float32)
    )

    write_rows_csv(pairwise_rows, output_paths["pairwise"])
    write_rows_csv(sensitivity_rows, output_paths["threshold_sensitivity"])
    write_rows_csv(confusion_rows, output_paths["confusion"])
    mask_keys = main_keys + ["mndwi_otsu"]
    write_mask_raster(
        output_paths["mask_raster"],
        [layers[key] for key in mask_keys],
        canonical_spec,
        grid_spec,
        flat_indices,
    )

    summary = {
        "comparison": "GLC_FCS30D・Esri 10m LULC・JRC GSW・MNDWI の水域の一致度",
        "settings": {
            "grid": {
                "analysis_crs": analysis_crs.to_string(),
                "resolution_m": COARSE_RES_M,
                "cell_area_m2": cell_area_m2,
                "target_cells": f"{IN_ANALYSIS_AREA_COLUMN} == 1",
                "aggregation": (
                    "aggregate_class_fractions_to_grid()（Resampling.average）。"
                    "LULC_WATER_COV と同じ集約方式"
                ),
            },
            "min_valid_ratio": MIN_VALID_RATIO,
            "water_fraction_threshold": WATER_FRACTION_THRESHOLD,
            "occurrence_thresholds": list(OCCURRENCE_THRESHOLDS),
            "primary_occurrence_threshold": PRIMARY_OCCURRENCE_THRESHOLD,
            "mndwi_thresholds": list(MNDWI_THRESHOLDS),
            "primary_mndwi_threshold": PRIMARY_MNDWI_THRESHOLD,
            "mndwi_threshold_rationale": (
                "MNDWI ≥ 0 は Xu (2006) が示した標準的な水域の閾値。観測日の画像に合わせた"
                "閾値として大津の方法の値も併記する。"
            ),
            "otsu_threshold": otsu,
            "otsu_bins": OTSU_BINS,
        },
        "target_cells": len(cells),
        "layers": {key: describe_layer(layer, cell_area_m2) for key, layer in layers.items()},
        "pairwise_main": pairwise_rows,
        "fraction_comparison": fraction_rows,
        "dataset_consistency_check": dataset_check,
        "notes": [
            "どのデータも真値ではないため、精度ではなく一致度として扱う。",
            "MNDWI は LST と同じ観測画像から算出しており、独立な参照ではない。",
            "JRC は 2022 年を収録しないため、年次・月次は 2021 年（月次は同じ 9 月）を使った。",
            "比較対象は両者とも有効なセルに限る。有効セル数はペアごとに異なる。",
        ],
        "outputs": {key: to_project_relative_string(path) for key, path in output_paths.items()},
        "provenance": build_provenance(
            SCRIPT_NAME,
            [dataset_path, glc_path, esri_path, jrc_path, roi_path],
            extra_watch_paths=WATCH_PATHS,
        ),
    }
    save_summary(summary, output_paths["summary"])
    log_results(pairwise_rows, dataset_check, otsu)
    return output_paths


def log_results(
    pairwise_rows: list[dict[str, Any]], dataset_check: dict[str, Any], otsu: float
) -> None:
    """主要な結果をログへ出す。

    Args:
        pairwise_rows: 主比較のペアごとの指標。
        dataset_check: データセットとの検算結果。
        otsu: 大津の閾値。
    """
    logger.info(
        "検算（GLC 再集約 vs LULC_WATER_COV）: 一致率 %s、最大絶対差 %s、NaN 不一致 %d",
        dataset_check["close_ratio"],
        dataset_check["max_abs_diff"],
        dataset_check["nan_mismatch_cells"],
    )
    logger.info("MNDWI の大津の閾値: %.4f", otsu)
    for row in pairwise_rows:
        logger.info(
            "  %-14s vs %-14s 有効 %8d / A %7d / B %7d / IoU %s",
            row["a"],
            row["b"],
            row["valid_cells"],
            row["a_cells"],
            row["b_cells"],
            f"{row['iou']:.4f}" if row["iou"] is not None else "-",
        )


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_paths = run(
        dataset_path=args.dataset_path,
        glc_path=args.glc_path,
        esri_path=args.esri_path,
        jrc_path=args.jrc_path,
        output_dir=args.output_dir,
        mask_dir=args.mask_dir,
        label=args.label,
    )
    for kind, path in output_paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
