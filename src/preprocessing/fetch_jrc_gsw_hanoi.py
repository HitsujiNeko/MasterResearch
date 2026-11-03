"""JRC Global Surface Water（GSW）から Hanoi ROI の水域レイヤを取得する。

データソース（Google Earth Engine 経由）:
- 全期間の主題図: `JRC/GSW1_4/GlobalSurfaceWater`（Occurrence 等）
- 観測数: `JRC/GSW1_4/Metadata`（`valid_obs` 等）
- 年次の水域分類: `JRC/GSW1_4/YearlyHistory`
- 月次の水域履歴: `JRC/GSW1_4/MonthlyHistory`
  （いずれも European Commission Joint Research Centre。Pekel et al., 2016, Nature）

ライセンス: 無償公開（Copernicus Programme の規則に基づく）。出典表記は
「Source: EC JRC/Google」とする。

制約メモ（2026-10-31 に GEE で確認）:
- 版は v1.4。収録は月次が 1984-03〜2021-12（454 枚）、年次が 1984〜2021 年（38 枚）で、
  **2022 年以降は含まれない**。`JRC/GSW1_5` は GEE に存在しない。
- ネイティブグリッドは EPSG:4326・0.00026949458523585647 度（約 30m）で、
  GLC_FCS30D と同じ画素サイズである。
- Occurrence は「一度も水域にならなかった画素」がマスクされている。そのままダウンロードすると
  「非水域」と「観測なし」が区別できないため、マスクを 0 で埋めたうえで、`Metadata` の
  `valid_obs` が 0 の画素だけを無効にする。
- 年次の `waterClass` は 0: 観測なし、1: 非水域、2: 季節水域、3: 恒常水域。
  月次の `water` は 0: 観測なし、1: 非水域、2: 水域。いずれも 0 を無効にする。
- **年次画像は、水域になったことのない画素がマスクされている**（Hanoi 中心部の 0.1 度四方で
  画素の約 74% がマスク、値 0 は約 0.2%。マスク画素の 99% は Occurrence が 0）。
  このマスクを無効値にすると年次の有効域が実態より大幅に狭くなるため、1（非水域）で埋める。
  月次画像はマスクされておらず、値 0（観測なし）だけが欠測である。
- Occurrence 以外のバンドにも `valid_obs` が 0 の画素のマスクをかけ、全期間を通じて観測が
  無い画素を「非水域」と取り違えないようにする。
- 観測年が収録外のときは、収録範囲内で最も近い年を使う。月次は季節を合わせるため、
  観測日と**同じ暦月**を、その月が収録されている最も近い年から選ぶ。
- 出力は整数値のみのため uint8 の GeoTIFF とし、無効値は 255 とする（Occurrence は 0〜100、
  分類は 1〜3 で、255 と衝突しない）。
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd
import numpy as np
import rasterio

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT
from src.common.gee import authenticate_gee, load_gee_project_id
from src.common.gee_raster import build_native_download_url, download_gee_raster
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.raster_area import (
    DEFAULT_RASTER_NODATA,
    build_raster_profile_record,
    build_target_area,
    read_clipped_float_array,
)
from src.common.raster_classes import build_class_distribution
from src.common.summary import build_provenance, save_summary

SCRIPT_NAME = "src.preprocessing.fetch_jrc_gsw_hanoi"

DEFAULT_GEE_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "gis" / "water" / "jrc_gsw"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

DATASET_NAME = "JRC Global Surface Water"
DATASET_VERSION = "v1.4"
GLOBAL_ASSET_ID = "JRC/GSW1_4/GlobalSurfaceWater"
METADATA_ASSET_ID = "JRC/GSW1_4/Metadata"
YEARLY_ASSET_ID = "JRC/GSW1_4/YearlyHistory"
MONTHLY_ASSET_ID = "JRC/GSW1_4/MonthlyHistory"
SOURCE_URL = (
    "https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater"
)

# 収録範囲（2026-10-31 に GEE の aggregate_min / aggregate_max で確認）
FIRST_YEAR = 1984
LAST_YEAR = 2021
# 月次は 1984 年 3 月から始まる（1984 年 1・2 月は存在しない）
MONTHLY_FIRST_MONTH_OF_FIRST_YEAR = 3

# 主採用観測（Landsat 8/9）の日付。年次・月次の選択の基準にする
DEFAULT_TARGET_DATE = date(2022, 9, 6)

# 出力 GeoTIFF の無効値（uint8）
OUTPUT_NODATA = 255

# 年次画像のマスク（水域になったことのない画素）を埋める値。waterClass の「非水域」
YEARLY_NOT_WATER_CLASS = 1

# バンド間の格子の一致判定で許す原点のずれ（画素単位）。浮動小数の丸め誤差のみを許す
GRID_ALIGNMENT_TOLERANCE_PIXELS = 1e-6

# Occurrence の要約に使う閾値（%）。比較側の感度分析と同じ値
OCCURRENCE_SUMMARY_THRESHOLDS: tuple[int, ...] = (25, 50, 75, 90)

REQUEST_TIMEOUT_SECONDS = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BandDefinition:
    """出力 GeoTIFF の 1 バンド分の定義。"""

    name: str
    description: str
    # 分類バンドのクラス値 -> ラベル（連続量の Occurrence は空）
    class_labels: dict[int, str]


# 出力バンドの並び（1始まりのバンド番号に対応）
BAND_DEFINITIONS: tuple[BandDefinition, ...] = (
    BandDefinition(
        name="occurrence",
        description=(
            "1984-03〜2021-12 の水域出現頻度（%、0〜100）。一度も水域にならなかった画素は 0、"
            "有効な観測が無い画素は無効値"
        ),
        class_labels={},
    ),
    BandDefinition(
        name="yearly_water_class",
        description="年次の水域分類（YearlyHistory の waterClass）。観測なし（0）は無効値",
        class_labels={1: "非水域", 2: "季節水域", 3: "恒常水域"},
    ),
    BandDefinition(
        name="monthly_water",
        description="月次の水域履歴（MonthlyHistory の water）。観測なし（0）は無効値",
        class_labels={1: "非水域", 2: "水域"},
    ),
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="JRC Global Surface Water から Hanoi ROI の水域レイヤを取得する。"
    )
    parser.add_argument(
        "--target-date",
        type=date.fromisoformat,
        default=DEFAULT_TARGET_DATE,
        help=(
            "基準とする観測日（YYYY-MM-DD）。年次・月次はこの日に最も近い収録年から選ぶ。"
            f"既定は主採用観測の {DEFAULT_TARGET_DATE.isoformat()}。"
        ),
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="試行実行用の小範囲 BBOX（EPSG:4326）。指定時は ROI の代わりにこの範囲で取得する。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="出力 GeoTIFF パス。未指定時は data/gis/water/jrc_gsw/ 配下へ保存する。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="サマリー JSON パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_GEE_CONFIG_PATH,
        help="GEE プロジェクト ID を読む設定 CSV パス。",
    )
    parser.add_argument(
        "--gee-project-id",
        default="",
        help="GEE プロジェクト ID。未指定時は設定 CSV から取得する。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def resolve_yearly_year(target_year: int) -> int:
    """年次の水域分類に使う年を、収録範囲内で最も近い年に決める。

    Args:
        target_year: 基準とする年（観測年）。

    Returns:
        収録範囲内で ``target_year`` に最も近い年。
    """
    return min(max(target_year, FIRST_YEAR), LAST_YEAR)


def resolve_monthly_year_month(target_year: int, target_month: int) -> tuple[int, int]:
    """月次の水域履歴に使う年・月を決める。

    季節（雨季・乾季）を観測日に合わせるため、月は観測日と同じ暦月に固定し、
    その月が収録されている年のうち ``target_year`` に最も近い年を選ぶ。

    Args:
        target_year: 基準とする年（観測年）。
        target_month: 基準とする月（1〜12）。

    Returns:
        (年, 月)。

    Raises:
        ValueError: ``target_month`` が 1〜12 の範囲外の場合。
    """
    if not 1 <= target_month <= 12:
        raise ValueError(f"月は 1〜12 で指定してください: {target_month}")
    first_year = FIRST_YEAR if target_month >= MONTHLY_FIRST_MONTH_OF_FIRST_YEAR else FIRST_YEAR + 1
    return min(max(target_year, first_year), LAST_YEAR), target_month


def resolve_output_paths(
    yearly_year: int,
    monthly_year: int,
    monthly_month: int,
    output_path: Path | None,
    summary_path: Path | None,
    is_trial: bool = False,
) -> tuple[Path, Path]:
    """出力 GeoTIFF とサマリー JSON の保存先を解決する。

    試行実行（BBOX 指定）で出力パスが未指定の場合は、既定ファイル名に `_trial` を
    付ける。ROI 全域の成果物を、範囲の狭い試行結果で上書きしてしまうのを防ぐため。

    Args:
        yearly_year: 年次の水域分類に使う年。
        monthly_year: 月次の水域履歴に使う年。
        monthly_month: 月次の水域履歴に使う月。
        output_path: 指定された出力パス。
        summary_path: 指定されたサマリーパス。
        is_trial: 試行実行かどうか。

    Returns:
        (出力 GeoTIFF パス, サマリー JSON パス)。
    """
    trial_suffix = "_trial" if is_trial else ""
    output_stem = f"jrc_gsw_hanoi_y{yearly_year}_m{monthly_year}{monthly_month:02d}{trial_suffix}"
    resolved_output_path = output_path or (DEFAULT_OUTPUT_DIR / f"{output_stem}.tif")
    resolved_summary_path = summary_path or (DEFAULT_SUMMARY_DIR / f"{output_stem}_summary.json")
    return (
        prepare_output_path(resolved_output_path),
        prepare_output_path(resolved_summary_path),
    )


def select_single_image(asset_id: str, conditions: dict[str, int]) -> ee.Image:
    """画像コレクションから、プロパティ条件に合う画像を 1 枚に特定する。

    Args:
        asset_id: GEE の画像コレクション ID。
        conditions: プロパティ名 -> 値（例: ``{"year": 2021, "month": 9}``）。

    Returns:
        該当する画像。

    Raises:
        RuntimeError: 該当画像が 1 枚に定まらない場合。
    """
    collection = ee.ImageCollection(asset_id)
    for property_name, value in conditions.items():
        collection = collection.filter(ee.Filter.eq(property_name, value))
    matched_count = int(collection.size().getInfo())
    if matched_count != 1:
        raise RuntimeError(
            f"{asset_id} で対象画像が 1 枚に定まりません"
            f"（条件: {conditions}、該当: {matched_count} 枚）。"
        )
    return ee.Image(collection.first())


def build_jrc_image(yearly_year: int, monthly_year: int, monthly_month: int) -> ee.Image:
    """取得する 3 バンド（Occurrence・年次・月次）を 1 枚の画像にまとめる。

    無効値の意味をここで揃える。Occurrence はマスク（一度も水域にならなかった）を 0 で、
    年次はマスク（同じく水域になったことがない）を 1（非水域）で埋める。そのうえで
    全バンドに「全期間の有効観測数が 0」のマスクをかけ、年次・月次は値 0（観測なし）も
    マスクする。マスクした画素は、ダウンロード時に無効値へ置き換わる。

    Args:
        yearly_year: 年次の水域分類に使う年。
        monthly_year: 月次の水域履歴に使う年。
        monthly_month: 月次の水域履歴に使う月。

    Returns:
        バンド名を ``BAND_DEFINITIONS`` の順に揃えた画像。
    """
    has_observation = ee.Image(METADATA_ASSET_ID).select("valid_obs").gt(0)
    occurrence = ee.Image(GLOBAL_ASSET_ID).select("occurrence").unmask(0)
    yearly = (
        select_single_image(YEARLY_ASSET_ID, {"year": yearly_year})
        .select("waterClass")
        .unmask(YEARLY_NOT_WATER_CLASS)
    )
    monthly = select_single_image(
        MONTHLY_ASSET_ID, {"year": monthly_year, "month": monthly_month}
    ).select("water")
    return ee.Image.cat(
        [
            occurrence.updateMask(has_observation),
            yearly.updateMask(yearly.gt(0).And(has_observation)),
            monthly.updateMask(monthly.gt(0).And(has_observation)),
        ]
    ).rename([band.name for band in BAND_DEFINITIONS])


def check_band_projections(projections: list[dict[str, Any]]) -> None:
    """全バンドのネイティブ格子が同じ格子（画素の境界が一致する）であることを確かめる。

    ダウンロードは先頭バンドの投影で行うため、他のバンドの格子がずれていると
    黙って再投影（最近傍）されてしまう。GSW は資産ごとに原点が異なる
    （例: Occurrence は北緯 84 度、年次は北緯 78 度）が、差が画素の整数倍であれば
    画素の境界は一致するため、CRS・画素サイズの一致と原点差が整数画素であることを確かめる。

    Args:
        projections: バンドごとの ``projection().getInfo()`` の戻り値
            （``transform`` は ``[x 画素幅, 0, x 原点, 0, y 画素幅, y 原点]``）。

    Raises:
        ValueError: いずれかのバンドの CRS・画素サイズが先頭バンドと異なる場合、
            または原点の差が画素の整数倍でない場合。
    """
    reference = projections[0]
    ref_transform = reference["transform"]
    for band, projection in zip(BAND_DEFINITIONS, projections):
        transform = projection["transform"]
        same_crs = projection.get("crs") == reference.get("crs")
        same_pixel = np.allclose(
            [transform[0], transform[1], transform[3], transform[4]],
            [ref_transform[0], ref_transform[1], ref_transform[3], ref_transform[4]],
            rtol=0.0,
            atol=1e-12,
        )
        offsets_in_pixels = [
            (transform[2] - ref_transform[2]) / ref_transform[0],
            (transform[5] - ref_transform[5]) / ref_transform[4],
        ]
        aligned = all(
            abs(offset - round(offset)) <= GRID_ALIGNMENT_TOLERANCE_PIXELS
            for offset in offsets_in_pixels
        )
        if not (same_crs and same_pixel and aligned):
            raise ValueError(
                f"バンド {band.name} の格子が先頭バンドと揃っていません"
                f"（先頭: {reference}、{band.name}: {projection}）。"
            )


def convert_to_uint8(array: np.ndarray, source_nodata: float) -> np.ndarray:
    """float32 で読んだクラス値・百分率の配列を、無効値 255 の uint8 配列へ変換する。

    Args:
        array: 変換元の配列（無効値は ``source_nodata``）。
        source_nodata: 変換元の無効値。

    Returns:
        uint8 配列（無効値は ``OUTPUT_NODATA``）。

    Raises:
        ValueError: 有効画素に 0〜254 の整数以外の値が含まれる場合（想定外の値を
            黙って丸めると、分類や百分率の意味が変わるため）。
    """
    valid = array != np.float32(source_nodata)
    values = array[valid]
    is_out_of_range = (values < 0) | (values >= OUTPUT_NODATA) | (values != np.round(values))
    if np.any(is_out_of_range):
        examples = np.unique(values[is_out_of_range])[:5].tolist()
        raise ValueError(f"uint8 へ変換できない値が含まれています（例: {examples}）。")
    converted = np.full(array.shape, OUTPUT_NODATA, dtype=np.uint8)
    converted[valid] = values.astype(np.uint8)
    return converted


def write_uint8_raster(
    output_path: Path,
    band_arrays: dict[str, np.ndarray],
    transform: Any,
    crs: Any,
) -> None:
    """uint8 の複数バンド GeoTIFF を、バンド名を説明として付けて書き出す。

    Args:
        output_path: 出力 GeoTIFF パス。
        band_arrays: バンド名 -> 2 次元 uint8 配列（書き出し順はこの辞書の順）。
        transform: アフィン変換。
        crs: 座標参照系。
    """
    first_array = next(iter(band_arrays.values()))
    height, width = first_array.shape
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=len(band_arrays),
        dtype="uint8",
        crs=crs,
        transform=transform,
        nodata=OUTPUT_NODATA,
        compress="deflate",
    ) as destination:
        for index, (name, band_array) in enumerate(band_arrays.items(), start=1):
            destination.write(band_array, index)
            destination.set_band_description(index, name)


def summarize_occurrence(occurrence: np.ndarray, area_mask: np.ndarray) -> dict[str, Any]:
    """Occurrence バンドの有効画素と、閾値ごとの水域画素数を集計する。

    有効画素率の分母は対象範囲内の画素数であり、ROI 全体ではない（クリップ余白を
    欠測と数えないため）。

    Args:
        occurrence: Occurrence の uint8 配列（無効値は ``OUTPUT_NODATA``）。
        area_mask: 対象範囲内を True とするマスク。

    Returns:
        画素数・有効画素率・水域となったことのある画素数・閾値別の画素数。
    """
    in_area = occurrence[area_mask]
    valid = in_area[in_area != OUTPUT_NODATA]
    area_pixels = int(in_area.size)
    return {
        "area_pixels": area_pixels,
        "valid_pixels": int(valid.size),
        "valid_pixel_ratio": (valid.size / area_pixels) if area_pixels > 0 else 0.0,
        "ever_water_pixels": int(np.count_nonzero(valid > 0)),
        "pixels_at_or_above_threshold": {
            str(threshold): int(np.count_nonzero(valid >= threshold))
            for threshold in OCCURRENCE_SUMMARY_THRESHOLDS
        },
    }


def process_downloaded_rasters(
    source_paths: list[Path],
    area_gdf: gpd.GeoDataFrame,
    output_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """バンドごとにダウンロードしたラスタをクリップ・uint8 化し、1 枚に重ねて保存する。

    GEE のダウンロードは float32 で行われ、Hanoi ROI の 3 バンドを一度に要求すると
    リクエスト上限（50MB）を超えるため、バンドごとに別ファイルで受け取る。

    Args:
        source_paths: ``BAND_DEFINITIONS`` の順に並べた単バンド float32 GeoTIFF パス
            （無効値は ``DEFAULT_RASTER_NODATA``）。
        area_gdf: 取得対象範囲（EPSG:4326）。
        output_path: 出力 GeoTIFF パス。

    Returns:
        (出力ラスタの諸元, バンド別の画素統計, 出力が要求範囲を覆えているか)。

    Raises:
        ValueError: ファイル数・バンド数が想定と異なる場合、またはバンド間で
            クリップ後の格子が一致しない場合（重ねると画素がずれるため）。
    """
    if len(source_paths) != len(BAND_DEFINITIONS):
        raise ValueError(
            "入力ファイル数が想定と異なります"
            f"（想定 {len(BAND_DEFINITIONS)}、実際 {len(source_paths)}）。"
        )

    band_arrays: dict[str, np.ndarray] = {}
    reference = None
    for band, source_path in zip(BAND_DEFINITIONS, source_paths):
        clipped = read_clipped_float_array(
            source_path=source_path,
            area_gdf=area_gdf,
            nodata=DEFAULT_RASTER_NODATA,
            require_geographic=True,
        )
        if clipped.array.shape[0] != 1:
            raise ValueError(
                f"単バンドのラスタを想定していますが {clipped.array.shape[0]} バンドあります: "
                f"{source_path}"
            )
        if reference is None:
            reference = clipped
        elif (
            clipped.array.shape != reference.array.shape
            or not clipped.transform.almost_equals(reference.transform)
            or clipped.crs != reference.crs
        ):
            raise ValueError(f"バンド {band.name} の格子が先頭バンドと一致しません: {source_path}")
        band_arrays[band.name] = convert_to_uint8(clipped.array[0], DEFAULT_RASTER_NODATA)

    write_uint8_raster(output_path, band_arrays, reference.transform, reference.crs)

    band_stats: dict[str, Any] = {}
    for band in BAND_DEFINITIONS:
        if band.class_labels:
            band_stats[band.name] = build_class_distribution(
                band_arrays[band.name],
                band.class_labels,
                filled_values=(OUTPUT_NODATA,),
                roi_mask=reference.area_mask,
            )
        else:
            band_stats[band.name] = summarize_occurrence(
                band_arrays[band.name], reference.area_mask
            )
    return build_raster_profile_record(output_path), band_stats, reference.covers_area


def describe_period_gap(selected_year: int, target_date: date) -> str:
    """選んだ年と観測日の年の差を説明する文を作る。

    Args:
        selected_year: 選んだ年。
        target_date: 基準とする観測日。

    Returns:
        説明文。
    """
    if selected_year == target_date.year:
        return f"観測年（{target_date.year}年）と一致する。"
    return (
        f"観測年（{target_date.year}年）は収録外のため、最も近い {selected_year} 年を使った"
        f"（{abs(target_date.year - selected_year)} 年の時間差がある）。"
    )


def build_summary(
    target_date: date,
    yearly_year: int,
    monthly_year: int,
    monthly_month: int,
    roi_path: Path,
    is_trial: bool,
    area_bounds: tuple[float, float, float, float],
    projection_info: dict[str, Any],
    raster_profile: dict[str, Any],
    band_stats: dict[str, Any],
    covers_area: bool,
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    Args:
        target_date: 基準とした観測日。
        yearly_year: 年次の水域分類に使った年。
        monthly_year: 月次の水域履歴に使った年。
        monthly_month: 月次の水域履歴に使った月。
        roi_path: ROI ファイルパス。
        is_trial: 試行実行（BBOX 指定）かどうか。
        area_bounds: 取得対象範囲の BBOX。
        projection_info: バンド名 -> GEE のネイティブ投影情報。
        raster_profile: 出力ラスタの諸元。
        band_stats: バンド別の画素統計。
        covers_area: 出力が要求範囲を覆えているか。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        retrieved_at: 取得日時（ISO8601）。

    Returns:
        サマリー辞書。
    """
    return {
        "dataset": DATASET_NAME,
        "dataset_version": DATASET_VERSION,
        "gee_asset_ids": {
            "occurrence": GLOBAL_ASSET_ID,
            "valid_obs": METADATA_ASSET_ID,
            "yearly": YEARLY_ASSET_ID,
            "monthly": MONTHLY_ASSET_ID,
        },
        "source": SOURCE_URL,
        "license": "無償公開（Copernicus Programme の規則に基づく）",
        "license_note": "出典表記は「Source: EC JRC/Google」とする。",
        "retrieved_at": retrieved_at,
        "coverage_period": {
            "yearly": f"{FIRST_YEAR}-{LAST_YEAR}",
            "monthly": f"{FIRST_YEAR}-{MONTHLY_FIRST_MONTH_OF_FIRST_YEAR:02d}〜{LAST_YEAR}-12",
            "checked_at": "2026-10-31",
        },
        "target_date": target_date.isoformat(),
        "selected_periods": {
            "occurrence": (
                f"{FIRST_YEAR}-{MONTHLY_FIRST_MONTH_OF_FIRST_YEAR:02d}〜{LAST_YEAR}-12（全期間）"
            ),
            "yearly_year": yearly_year,
            "yearly_note": describe_period_gap(yearly_year, target_date),
            "monthly_year": monthly_year,
            "monthly_month": monthly_month,
            "monthly_note": (
                "季節を合わせるため観測日と同じ暦月を選んだ。"
                + describe_period_gap(monthly_year, target_date)
            ),
        },
        "native_projection": {
            band_name: {"crs": projection.get("crs"), "transform": projection.get("transform")}
            for band_name, projection in projection_info.items()
        },
        "resampling_note": (
            "ネイティブの crs / crs_transform を指定してバンドごとに取得しており、"
            "リサンプリングは行っていない。資産ごとに格子の原点は異なるが、差は画素の整数倍で"
            "画素の境界は一致する（取得時に検査している）。"
        ),
        "roi_path": to_project_relative_string(roi_path),
        "is_trial_run": is_trial,
        "area_bbox": list(area_bounds),
        "covers_requested_area": covers_area,
        "crs": raster_profile["crs"],
        "nodata": OUTPUT_NODATA,
        "raster_profile": raster_profile,
        "bands": {
            str(index): {
                "name": band.name,
                "description": band.description,
                "class_labels": {str(value): label for value, label in band.class_labels.items()},
            }
            for index, band in enumerate(BAND_DEFINITIONS, start=1)
        },
        "band_stats": band_stats,
        "coverage_note": (
            "ROI ポリゴンでクリップしているため出力は BBOX 矩形となり、ROI 外の余白は無効値"
            f"（{OUTPUT_NODATA}）で埋まる。有効画素率の分母は対象範囲内の画素数であり、"
            "ROI 全体ではない。月次・年次の無効画素は「その期間に有効な観測が無かった」"
            "画素であり、非水域ではない。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
        "provenance": build_provenance(SCRIPT_NAME, [roi_path]),
    }


def run(
    target_date: date,
    roi_path: Path,
    bbox: list[float] | None,
    output_path: Path | None,
    summary_path: Path | None,
    config_path: Path,
    gee_project_id: str,
    overwrite: bool,
) -> tuple[Path, Path]:
    """取得から検証・保存までの処理全体を実行する。

    Args:
        target_date: 基準とする観測日。
        roi_path: ROI の Shapefile パス。
        bbox: 試行実行用 BBOX。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        config_path: GEE 設定 CSV パス。
        gee_project_id: GEE プロジェクト ID。
        overwrite: 既存出力を上書きするか。

    Returns:
        (出力 GeoTIFF パス, サマリー JSON パス)。

    Raises:
        FileExistsError: 出力ファイルが既に存在し overwrite が False の場合。
    """
    yearly_year = resolve_yearly_year(target_date.year)
    monthly_year, monthly_month = resolve_monthly_year_month(target_date.year, target_date.month)
    if yearly_year != target_date.year or monthly_year != target_date.year:
        logger.warning(
            "観測年 %d は収録外のため、年次は %d 年、月次は %d-%02d を使います。",
            target_date.year,
            yearly_year,
            monthly_year,
            monthly_month,
        )

    area_gdf, is_trial, resolved_roi_path = build_target_area(roi_path=roi_path, bbox=bbox)
    area_bounds = tuple(float(value) for value in area_gdf.total_bounds)
    resolved_output_path, resolved_summary_path = resolve_output_paths(
        yearly_year=yearly_year,
        monthly_year=monthly_year,
        monthly_month=monthly_month,
        output_path=output_path,
        summary_path=summary_path,
        is_trial=is_trial,
    )
    for path in (resolved_output_path, resolved_summary_path):
        if path.exists() and not overwrite:
            raise FileExistsError(f"出力ファイルが既に存在します（--overwrite で上書き）: {path}")

    project_id = load_gee_project_id(config_path=config_path, explicit_project_id=gee_project_id)
    authenticate_gee(project_id)

    image = build_jrc_image(yearly_year, monthly_year, monthly_month)
    check_band_projections(
        [image.select(index).projection().getInfo() for index in range(len(BAND_DEFINITIONS))]
    )
    region_geojson = ee.Geometry.Rectangle(list(area_bounds)).getInfo()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory() as temp_dir:
        downloaded_paths: list[Path] = []
        # GSW は資産ごとに格子の原点が異なるため、投影はバンド別に記録する
        projection_info: dict[str, Any] = {}
        for band in BAND_DEFINITIONS:
            # 3 バンドを一度に要求すると float32 で GEE のリクエスト上限を超えるため、1 枚ずつ取る
            download_url, band_projection = build_native_download_url(
                image=image.select(band.name),
                region_geojson=region_geojson,
                nodata=DEFAULT_RASTER_NODATA,
            )
            projection_info[band.name] = band_projection
            logger.info("バンド %s をダウンロードします。", band.name)
            downloaded_paths.append(
                download_gee_raster(
                    download_url=download_url,
                    destination_path=Path(temp_dir) / f"jrc_gsw_{band.name}.tif",
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            )
        raster_profile, band_stats, covers_area = process_downloaded_rasters(
            source_paths=downloaded_paths,
            area_gdf=area_gdf,
            output_path=resolved_output_path,
        )

    summary = build_summary(
        target_date=target_date,
        yearly_year=yearly_year,
        monthly_year=monthly_year,
        monthly_month=monthly_month,
        roi_path=resolved_roi_path,
        is_trial=is_trial,
        area_bounds=area_bounds,
        projection_info=projection_info,
        raster_profile=raster_profile,
        band_stats=band_stats,
        covers_area=covers_area,
        output_path=resolved_output_path,
        summary_path=resolved_summary_path,
        retrieved_at=retrieved_at,
    )
    save_summary(summary, resolved_summary_path)
    log_summary(band_stats, covers_area)
    return resolved_output_path, resolved_summary_path


def log_summary(band_stats: dict[str, Any], covers_area: bool) -> None:
    """取得結果の要点をログへ出す。

    Args:
        band_stats: バンド別の画素統計。
        covers_area: 出力が要求範囲を覆えているか。
    """
    occurrence = band_stats["occurrence"]
    logger.info(
        "Occurrence: 有効 %d / 範囲内 %d 画素（%.4f）、水域になったことのある画素 %d、閾値別 %s",
        occurrence["valid_pixels"],
        occurrence["area_pixels"],
        occurrence["valid_pixel_ratio"],
        occurrence["ever_water_pixels"],
        occurrence["pixels_at_or_above_threshold"],
    )
    for band_name in ("yearly_water_class", "monthly_water"):
        stats = band_stats[band_name]
        logger.info(
            "%s: 有効画素率 %.4f（無効 %d 画素）",
            band_name,
            stats["valid_pixel_ratio"],
            stats["filled_pixels"],
        )
    if not covers_area:
        logger.warning("出力が要求範囲を覆いきれていません。データの提供範囲を確認してください。")


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_path, summary_path = run(
        target_date=args.target_date,
        roi_path=args.roi_path,
        bbox=args.bbox,
        output_path=args.output_path,
        summary_path=args.summary_path,
        config_path=args.config_path,
        gee_project_id=args.gee_project_id,
        overwrite=args.overwrite,
    )
    print(f"GeoTIFF を保存しました: {output_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
