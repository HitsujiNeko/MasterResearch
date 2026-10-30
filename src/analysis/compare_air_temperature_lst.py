"""採用観測の衛星通過時刻の気温（NOAA ISD・ERA5-Land）と LST を並べた対比表を作る。

気温（地上約2mの空気の温度）と LST（地表面の放射温度）は別の物理量であり、
本スクリプトの表は**観測条件の記述**に用いる（LST の妥当性検証ではない）。

対比表は「観測 × 地点」の縦長の表とし、地点は次の3つ。

- `ROI`: ROI 内の有効画素の LST 統計量と、ERA5-Land の 2m 気温の ROI 平均
- ISD の観測所（ノイバイ・ハドン）: 観測所の座標を含む画素を中心とする 3×3 画素の LST と、
  観測所の気温（通過時刻に最も近い値）・観測所の座標の ERA5-Land の格子値

ERA5-Land は通過時刻をはさむ2つの毎時値（例 03:00・04:00 UTC）を線形内挿する。
約9km格子であり、都市内の気温差は表せない。GEE からは `getInfo()` で値を読むだけで、
エクスポートは行わない。

入力:
- LST GeoTIFF（EPSG:4326・°C・無効画素は NaN）
- ROI のシェープファイル
- `src.preprocessing.fetch_isd_hourly_hanoi` で取得した ISD の CSV

出力:
- 対比表 CSV と、来歴・ERA5-Land の内挿前の値を記録したサマリー JSON
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT
from src.common.gee import authenticate_gee, load_gee_project_id
from src.common.paths import (
    prepare_output_path,
    resolve_existing_path,
    resolve_relative_to_project_root,
    to_project_relative_string,
)
from src.common.raster_stats import build_band_statistics
from src.common.roi import build_raster_roi_mask, load_roi_geometry
from src.common.summary import build_provenance, save_summary
from src.preprocessing.fetch_isd_hourly_hanoi import (
    ADOPTED_OBSERVATION_DATETIMES,
    HANOI_ISD_STATIONS,
    IsdStation,
)
from src.preprocessing.fetch_isd_hourly_hanoi import (
    DEFAULT_OUTPUT_DIR as DEFAULT_ISD_DIR,
)
from src.preprocessing.fetch_isd_hourly_hanoi import (
    build_output_path as build_isd_csv_path,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_NAME = "src.analysis.compare_air_temperature_lst"

DEFAULT_LST_ROOT = PROJECT_ROOT / "data" / "satellite" / "lst"
DEFAULT_GEE_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "air_temperature"
OUTPUT_STEM = "air_temperature_lst_comparison"

# 採用観測の LST GeoTIFF（LST のルートからの相対パス）。2024-11-30 は在庫の都合で 2023/ にある
LST_RELATIVE_PATHS: dict[str, str] = {
    "2022-09-06T03:23:58": "2022/LST_Landsat8_20220906_032358Z.tif",
    "2023-07-07T03:23:05": "2023/LST_Landsat8_20230707_032305Z.tif",
    "2024-11-30T03:23:36": "2023/LST_Landsat8_20241130_032336Z.tif",
}

# 観測所付近の LST を平均する窓の一辺の画素数（奇数）
LST_WINDOW_SIZE = 3

# ハノイの現地時刻（UTC+7）。表の補助列にだけ使う
LOCAL_UTC_OFFSET = timedelta(hours=7)

ERA5_LAND_COLLECTION = "ECMWF/ERA5_LAND/HOURLY"
ERA5_LAND_BAND = "temperature_2m"
# ERA5-Land のネイティブ解像度（0.1度 ≒ 11,132m）
ERA5_LAND_SCALE_METERS = 11132
KELVIN_TO_CELSIUS_OFFSET = 273.15

# ISD の TMP の欠測値と、除外する品質コード（ISD の仕様で「疑わしい」「誤り」とされるもの）
ISD_MISSING_TEMPERATURE = "+9999"
ISD_REJECTED_QUALITY_CODES = frozenset({"2", "3", "6", "7"})

# 通過時刻との差の許容幅（分）。3時間ごとの SYNOP で通過時刻に近い観測が欠けた場合に、
# 数時間離れた値が警告なしに表へ入るのを防ぐ
ISD_MAX_OFFSET_MINUTES = 90.0

ROI_SITE_ID = "ROI"


@dataclass(frozen=True)
class NearestIsdValue:
    """通過時刻に最も近い ISD の気温。

    Attributes:
        temperature_c: 気温（°C）。
        observed_at: 観測時刻（UTC）。
        offset_minutes: 観測時刻 − 通過時刻（分。負なら通過前）。
        report_type: 報告の種類（`FM-15`＝METAR、`FM-12`＝SYNOP など）。
    """

    temperature_c: float
    observed_at: datetime
    offset_minutes: float
    report_type: str


def parse_isd_temperature(tmp_field: str) -> float | None:
    """ISD の `TMP` 列（例 `+0285,1`）を摂氏に換算する。

    Args:
        tmp_field: `TMP` 列の値（「10倍した摂氏の符号つき整数,品質コード」）。

    Returns:
        気温（°C）。欠測（`+9999`）または除外する品質コードの場合は None。

    Raises:
        ValueError: 形式が「値,品質コード」でない場合。
    """
    parts = str(tmp_field).strip().split(",")
    if len(parts) != 2:
        raise ValueError(f"TMP の形式が不正です: {tmp_field!r}")
    value, quality = parts
    if value == ISD_MISSING_TEMPERATURE or quality in ISD_REJECTED_QUALITY_CODES:
        return None
    return int(value) / 10.0


def load_isd_temperatures(csv_path: Path) -> pd.DataFrame:
    """ISD の CSV から、有効な気温の時系列を読み込む。

    Args:
        csv_path: `fetch_isd_hourly_hanoi` が保存した CSV。

    Returns:
        `observed_at`（UTC のタイムゾーンつき）・`report_type`・`temperature_c` 列の表。
        欠測・除外した値の行は含まない。
    """
    raw = pd.read_csv(csv_path, dtype=str, usecols=["DATE", "REPORT_TYPE", "TMP"])
    temperatures = raw["TMP"].map(parse_isd_temperature)
    table = pd.DataFrame(
        {
            # ISD の DATE は UTC
            "observed_at": pd.to_datetime(raw["DATE"], utc=True),
            "report_type": raw["REPORT_TYPE"].str.strip(),
            "temperature_c": temperatures,
        }
    )
    return table.dropna(subset=["temperature_c"]).reset_index(drop=True)


def select_nearest_isd_value(
    table: pd.DataFrame, pass_time: datetime, max_offset_minutes: float = ISD_MAX_OFFSET_MINUTES
) -> NearestIsdValue | None:
    """通過時刻に最も近い観測の気温を選ぶ。

    時刻差が同じ観測が前後にある場合は、通過前の観測を採る（通過時刻までの状態を表すため）。

    Args:
        table: `load_isd_temperatures` の戻り値。
        pass_time: 衛星の通過時刻（UTC のタイムゾーンつき）。
        max_offset_minutes: 通過時刻との差の許容幅（分。この値ちょうどは採る）。

    Returns:
        最も近い観測。有効な観測が無い場合、または最も近い観測でも許容幅を超える場合は None。
    """
    if table.empty:
        return None
    offsets = (table["observed_at"] - pd.Timestamp(pass_time)).dt.total_seconds() / 60.0
    # 絶対値が同じなら負（通過前）を先にするため、(絶対値, 時刻差) の順で並べる
    order = sorted(
        range(len(table)), key=lambda index: (abs(offsets.iloc[index]), offsets.iloc[index])
    )
    best = order[0]
    if abs(offsets.iloc[best]) > max_offset_minutes:
        logger.warning(
            f"通過時刻に最も近い ISD の観測でも {offsets.iloc[best]:+.0f} 分離れており、"
            f"許容幅（±{max_offset_minutes:.0f} 分）を超えるため欠測とします"
        )
        return None
    row = table.iloc[best]
    return NearestIsdValue(
        temperature_c=float(row["temperature_c"]),
        observed_at=row["observed_at"].to_pydatetime(),
        offset_minutes=float(offsets.iloc[best]),
        report_type=str(row["report_type"]),
    )


def bracketing_hours(pass_time: datetime) -> tuple[datetime, datetime]:
    """通過時刻をはさむ2つの正時（UTC）を返す。

    Args:
        pass_time: 衛星の通過時刻（UTC のタイムゾーンつき）。

    Returns:
        (通過時刻以前の正時, その1時間後)。
    """
    hour_before = pass_time.replace(minute=0, second=0, microsecond=0)
    return hour_before, hour_before + timedelta(hours=1)


def interpolate_linear(
    time: datetime, time_0: datetime, value_0: float, time_1: datetime, value_1: float
) -> float:
    """2時刻の値から、その間の時刻の値を線形内挿する。

    Args:
        time: 内挿する時刻。
        time_0: 前の時刻。
        value_0: 前の時刻の値。
        time_1: 後の時刻。
        value_1: 後の時刻の値。

    Returns:
        内挿した値。

    Raises:
        ValueError: `time` が `time_0`〜`time_1` の外、または `time_0` と `time_1` が同じ場合。
    """
    if time_1 <= time_0:
        raise ValueError(f"内挿の区間が不正です: {time_0} 〜 {time_1}")
    if not (time_0 <= time <= time_1):
        raise ValueError(f"内挿する時刻 {time} が区間 {time_0} 〜 {time_1} の外です")
    weight = (time - time_0) / (time_1 - time_0)
    return value_0 + (value_1 - value_0) * weight


def kelvin_to_celsius(value_k: float) -> float:
    """ケルビンを摂氏に換算する。

    Args:
        value_k: 温度（K）。

    Returns:
        温度（°C）。
    """
    return value_k - KELVIN_TO_CELSIUS_OFFSET


def fetch_era5_land_values_k(
    hour_start: datetime, roi_geometry: BaseGeometry, stations: tuple[IsdStation, ...]
) -> dict[str, float | None]:
    """ERA5-Land の1時間分の 2m 気温（K）を、ROI 平均と観測所の格子値で取得する。

    観測所の格子値は点ごとの `reduceRegion`（`Reducer.first`）で読む。2024年の画像は
    格子の原点が `-360.05` 度になっており（2022年は `-180.05` 度）、`sampleRegions`・
    `reduceRegions` では点の値が返らなかったため（2026-10-29 確認）。

    Args:
        hour_start: 対象の正時（UTC）。
        roi_geometry: ROI の統合ジオメトリ（EPSG:4326）。
        stations: 格子値を読む観測所。

    Returns:
        `ROI` と各観測所の番号をキー、2m 気温（K）を値とする辞書。値が無い場合は None。

    Raises:
        ValueError: 対象の正時の画像が見つからない場合。
    """
    start = ee.Date(hour_start.isoformat())
    collection = ee.ImageCollection(ERA5_LAND_COLLECTION).filterDate(
        start, start.advance(1, "hour")
    )
    if collection.size().getInfo() == 0:
        raise ValueError(f"ERA5-Land の画像が見つかりません: {hour_start.isoformat()}")
    image = collection.first().select(ERA5_LAND_BAND)

    server_values = {
        ROI_SITE_ID: _reduce_band(
            image, ee.Reducer.mean(), ee.Geometry(roi_geometry.__geo_interface__)
        )
    }
    server_values.update(
        {
            station.station_id: _reduce_band(
                image, ee.Reducer.first(), ee.Geometry.Point([station.longitude, station.latitude])
            )
            for station in stations
        }
    )
    # 地点ごとに getInfo すると往復が増えるため、辞書にまとめて1回で読む
    fetched = ee.Dictionary(server_values).getInfo()
    return {site_id: _to_optional_float(fetched.get(site_id)) for site_id in server_values}


def _reduce_band(image: Any, reducer: Any, geometry: Any) -> Any:
    """画像の 2m 気温バンドを、領域で集計した値（サーバー側のオブジェクト）を返す。

    Args:
        image: `temperature_2m` を選んだ ERA5-Land の画像。
        reducer: 集計方法（ROI は平均、観測所の点は `first`）。
        geometry: 集計する領域。

    Returns:
        集計値（`getInfo()` 前のサーバー側のオブジェクト）。画素が無ければ null になる。
    """
    return image.reduceRegion(
        reducer=reducer,
        geometry=geometry,
        scale=ERA5_LAND_SCALE_METERS,
        maxPixels=int(1e9),
    ).get(ERA5_LAND_BAND)


def _to_optional_float(value: Any) -> float | None:
    """GEE から返った値を float に変換する（None はそのまま）。

    Args:
        value: GEE の `getInfo()` の戻り値。

    Returns:
        float または None。
    """
    return None if value is None else float(value)


def interpolate_era5_to_pass_time(
    pass_time: datetime,
    hour_before: datetime,
    values_before_k: dict[str, float | None],
    hour_after: datetime,
    values_after_k: dict[str, float | None],
) -> dict[str, float | None]:
    """ERA5-Land の前後の正時の値（K）を通過時刻へ内挿し、摂氏で返す。

    Args:
        pass_time: 衛星の通過時刻（UTC）。
        hour_before: 前の正時。
        values_before_k: 前の正時の値（K）。
        hour_after: 後の正時。
        values_after_k: 後の正時の値（K）。

    Returns:
        地点ごとの内挿値（°C）。どちらかの正時が欠けている地点は None。
    """
    interpolated: dict[str, float | None] = {}
    for site_id, value_before in values_before_k.items():
        value_after = values_after_k.get(site_id)
        if value_before is None or value_after is None:
            interpolated[site_id] = None
            continue
        value_k = interpolate_linear(pass_time, hour_before, value_before, hour_after, value_after)
        interpolated[site_id] = kelvin_to_celsius(value_k)
    return interpolated


def read_lst_window(raster_path: Path, longitude: float, latitude: float, size: int) -> np.ndarray:
    """座標を含む画素を中心とする size×size 画素の LST を読む（範囲外は切り詰める）。

    Args:
        raster_path: LST GeoTIFF（EPSG:4326）。
        longitude: 経度。
        latitude: 緯度。
        size: 窓の一辺の画素数（正の奇数）。

    Returns:
        窓内の LST（°C）。無効画素は NaN。

    Raises:
        ValueError: `size` が正の奇数でない、ラスタが EPSG:4326 でない、または座標が
            ラスタの範囲外の場合。
    """
    if size <= 0 or size % 2 == 0:
        raise ValueError(f"窓の大きさは正の奇数にしてください: {size}")
    half = size // 2
    with rasterio.open(raster_path) as dataset:
        # 経緯度で画素を探すため、投影座標系のラスタでは例外にならないまま別の画素を読んでしまう
        if dataset.crs is None or dataset.crs.to_epsg() != 4326:
            raise ValueError(
                f"LST ラスタの CRS が EPSG:4326 ではありません（{dataset.crs}）: {raster_path}"
            )
        row, col = dataset.index(longitude, latitude)
        if not (0 <= row < dataset.height and 0 <= col < dataset.width):
            raise ValueError(f"座標 ({longitude}, {latitude}) がラスタの範囲外です: {raster_path}")
        row_start, col_start = max(row - half, 0), max(col - half, 0)
        row_stop, col_stop = min(row + half + 1, dataset.height), min(col + half + 1, dataset.width)
        window = Window(col_start, row_start, col_stop - col_start, row_stop - row_start)
        values = dataset.read(1, window=window).astype(np.float64)
        if dataset.nodata is not None:
            values[values == dataset.nodata] = np.nan
    return values


def read_lst_in_roi(raster_path: Path, roi_gdf: gpd.GeoDataFrame) -> np.ndarray:
    """ROI 内の有効な LST 画素を1次元配列で読む。

    画素中心が ROI 内にある画素を ROI 内とみなす（`build_raster_roi_mask` の規則）。

    Args:
        raster_path: LST GeoTIFF。
        roi_gdf: ROI。

    Returns:
        ROI 内の有効画素の LST（°C）。
    """
    with rasterio.open(raster_path) as dataset:
        values = dataset.read(1).astype(np.float64)
        if dataset.nodata is not None:
            values[values == dataset.nodata] = np.nan
        roi_mask = build_raster_roi_mask(roi_gdf, dataset.crs, values.shape, dataset.transform)
    selected = values[roi_mask]
    return selected[np.isfinite(selected)]


def summarize_lst(values: np.ndarray) -> dict[str, float | int]:
    """LST の有効画素の平均・最小・最大・標準偏差（母標準偏差）と画素数をまとめる。

    Args:
        values: LST（°C）。NaN を含んでよい。

    Returns:
        `lst_mean_c`・`lst_min_c`・`lst_max_c`・`lst_std_c`・`lst_valid_pixels`。
        有効画素が無い場合、統計量は NaN。
    """
    valid = values[np.isfinite(values)].ravel()
    stats = build_band_statistics(valid)
    if stats is None:
        return {
            "lst_mean_c": math.nan,
            "lst_min_c": math.nan,
            "lst_max_c": math.nan,
            "lst_std_c": math.nan,
            "lst_valid_pixels": 0,
        }
    return {
        "lst_mean_c": stats["mean"],
        "lst_min_c": stats["min"],
        "lst_max_c": stats["max"],
        "lst_std_c": stats["std"],
        "lst_valid_pixels": int(valid.size),
    }


def build_site_row(
    pass_time: datetime,
    site_id: str,
    site_name: str,
    coordinates: tuple[float, float] | None,
    lst_summary: dict[str, float | int],
    lst_extent: str,
    isd_value: NearestIsdValue | None,
    era5_temperature_c: float | None,
) -> dict[str, Any]:
    """対比表の1行（1観測 × 1地点）を組み立て、LST − 気温を計算する。

    Args:
        pass_time: 衛星の通過時刻（UTC）。
        site_id: 地点の識別子（`ROI` または観測所の番号）。
        site_name: 地点名。
        coordinates: 観測所の (経度, 緯度)。ROI の行は None。
        lst_summary: `summarize_lst` の戻り値。
        lst_extent: LST を集計した範囲の説明（例 `ROI`・`3x3`）。
        isd_value: 観測所の気温。ROI の行・欠測は None。
        era5_temperature_c: ERA5-Land の 2m 気温（°C）。欠測は None。

    Returns:
        対比表の1行。
    """
    lst_mean = float(lst_summary["lst_mean_c"])
    isd_temperature = math.nan if isd_value is None else isd_value.temperature_c
    era5_temperature = math.nan if era5_temperature_c is None else era5_temperature_c
    return {
        "observation_datetime_utc": pass_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "observation_local_time": (pass_time + LOCAL_UTC_OFFSET).strftime("%H:%M"),
        "site_id": site_id,
        "site_name": site_name,
        "longitude": math.nan if coordinates is None else coordinates[0],
        "latitude": math.nan if coordinates is None else coordinates[1],
        "lst_extent": lst_extent,
        **lst_summary,
        "isd_temperature_c": isd_temperature,
        "isd_observed_at_utc": ""
        if isd_value is None
        else isd_value.observed_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "isd_offset_minutes": math.nan if isd_value is None else isd_value.offset_minutes,
        "isd_report_type": "" if isd_value is None else isd_value.report_type,
        "era5_land_temperature_c": era5_temperature,
        # NaN どうしの差は NaN になり、欠測はそのまま欠測として残る
        "lst_minus_isd_c": lst_mean - isd_temperature,
        "lst_minus_era5_land_c": lst_mean - era5_temperature,
    }


def parse_pass_time(value: str) -> datetime:
    """観測日時の文字列（UTC・タイムゾーン表記なし）を UTC の datetime にする。

    Args:
        value: `YYYY-MM-DDTHH:MM:SS` 形式の観測日時。

    Returns:
        UTC のタイムゾーンつき datetime。
    """
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def build_observation_rows(
    observation: str,
    lst_path: Path,
    roi_gdf: gpd.GeoDataFrame,
    isd_dir: Path,
    era5_celsius: dict[str, float | None],
) -> list[dict[str, Any]]:
    """1観測分の対比表の行（ROI と各観測所）を作る。

    Args:
        observation: 観測日時（UTC・`YYYY-MM-DDTHH:MM:SS`）。
        lst_path: その観測の LST GeoTIFF。
        roi_gdf: ROI。
        isd_dir: ISD の CSV のディレクトリ。
        era5_celsius: 通過時刻へ内挿した ERA5-Land の 2m 気温（°C）。

    Returns:
        ROI の行と観測所の行のリスト。
    """
    pass_time = parse_pass_time(observation)
    rows = [
        build_site_row(
            pass_time,
            ROI_SITE_ID,
            "ROI",
            None,
            summarize_lst(read_lst_in_roi(lst_path, roi_gdf)),
            "ROI",
            None,
            era5_celsius.get(ROI_SITE_ID),
        )
    ]
    for station in HANOI_ISD_STATIONS:
        isd_path = build_isd_csv_path(isd_dir, station.station_id, pass_time.date())
        isd_value = (
            select_nearest_isd_value(load_isd_temperatures(isd_path), pass_time)
            if isd_path.exists()
            else None
        )
        if isd_value is None:
            logger.warning(f"ISD の気温がありません: {station.name} {observation}（{isd_path}）")
        window = read_lst_window(lst_path, station.longitude, station.latitude, LST_WINDOW_SIZE)
        rows.append(
            build_site_row(
                pass_time,
                station.station_id,
                station.name,
                (station.longitude, station.latitude),
                summarize_lst(window),
                f"{LST_WINDOW_SIZE}x{LST_WINDOW_SIZE}",
                isd_value,
                era5_celsius.get(station.station_id),
            )
        )
    return rows


def fetch_era5_for_observation(
    observation: str, roi_geometry: BaseGeometry
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """1観測の通過時刻へ内挿した ERA5-Land の気温と、内挿前の値の記録を返す。

    Args:
        observation: 観測日時（UTC・`YYYY-MM-DDTHH:MM:SS`）。
        roi_geometry: ROI の統合ジオメトリ（EPSG:4326）。

    Returns:
        (地点ごとの内挿値〔°C〕, サマリー JSON に残す内挿前の値〔K〕の記録)。
    """
    pass_time = parse_pass_time(observation)
    hour_before, hour_after = bracketing_hours(pass_time)
    values_before = fetch_era5_land_values_k(hour_before, roi_geometry, HANOI_ISD_STATIONS)
    values_after = fetch_era5_land_values_k(hour_after, roi_geometry, HANOI_ISD_STATIONS)
    interpolated = interpolate_era5_to_pass_time(
        pass_time, hour_before, values_before, hour_after, values_after
    )
    record = {
        "hour_before_utc": hour_before.isoformat(),
        "hour_after_utc": hour_after.isoformat(),
        "values_before_k": values_before,
        "values_after_k": values_after,
    }
    return interpolated, record


def run(
    lst_root: Path,
    roi_path: Path,
    isd_dir: Path,
    output_dir: Path,
    gee_config_path: Path,
    gee_project_id: str,
) -> tuple[Path, Path]:
    """採用観測3件の対比表を作り、CSV とサマリー JSON を保存する。

    Args:
        lst_root: LST GeoTIFF のルート（`LST_RELATIVE_PATHS` の基準）。
        roi_path: ROI のシェープファイル。
        isd_dir: ISD の CSV のディレクトリ。
        output_dir: 出力先ディレクトリ。
        gee_config_path: GEE のプロジェクト ID を記した設定 CSV。
        gee_project_id: GEE のプロジェクト ID（明示指定。空なら設定 CSV から読む）。

    Returns:
        (対比表 CSV のパス, サマリー JSON のパス)。
    """
    roi_gdf, roi_geometry = load_roi_geometry(roi_path)
    authenticate_gee(load_gee_project_id(gee_config_path, gee_project_id))

    rows: list[dict[str, Any]] = []
    era5_records: dict[str, Any] = {}
    input_paths: list[Path] = [roi_path]
    for observation in ADOPTED_OBSERVATION_DATETIMES:
        lst_path = resolve_existing_path(lst_root / LST_RELATIVE_PATHS[observation])
        input_paths.append(lst_path)
        logger.info(f"ERA5-Land を取得します: {observation}")
        era5_celsius, era5_records[observation] = fetch_era5_for_observation(
            observation, roi_geometry
        )
        rows.extend(build_observation_rows(observation, lst_path, roi_gdf, isd_dir, era5_celsius))
        pass_date = parse_pass_time(observation).date()
        input_paths.extend(
            path
            for path in (
                build_isd_csv_path(isd_dir, station.station_id, pass_date)
                for station in HANOI_ISD_STATIONS
            )
            if path.exists()
        )

    csv_path = prepare_output_path(output_dir / f"{OUTPUT_STEM}.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8")
    summary_path = prepare_output_path(output_dir / f"{OUTPUT_STEM}_summary.json")
    summary = {
        "provenance": build_provenance(SCRIPT_NAME, input_paths),
        "parameters": {
            "observations_utc": list(ADOPTED_OBSERVATION_DATETIMES),
            "lst_paths": {
                observation: to_project_relative_string(lst_root / relative)
                for observation, relative in LST_RELATIVE_PATHS.items()
            },
            "lst_window_size": LST_WINDOW_SIZE,
            "lst_std": "母標準偏差（ddof=0）",
            "isd_stations": [asdict(station) for station in HANOI_ISD_STATIONS],
            "isd_rejected_quality_codes": sorted(ISD_REJECTED_QUALITY_CODES),
            "isd_max_offset_minutes": ISD_MAX_OFFSET_MINUTES,
            "era5_land_collection": ERA5_LAND_COLLECTION,
            "era5_land_band": ERA5_LAND_BAND,
            "era5_land_scale_m": ERA5_LAND_SCALE_METERS,
            "era5_land_interpolation": "通過時刻をはさむ2つの正時の値を線形内挿",
        },
        "era5_land_raw_values": era5_records,
        "output_csv": to_project_relative_string(csv_path),
        "notes": [
            "気温と LST は別の物理量であり、本表は観測条件の記述に用いる"
            "（LST の妥当性検証ではない）",
            "ERA5-Land は約9km格子であり、都市内の気温差は表せない",
        ],
    }
    save_summary(summary, summary_path)
    return csv_path, summary_path


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数のリスト。`None` の場合は `sys.argv` を使う。

    Returns:
        解析結果。
    """
    parser = argparse.ArgumentParser(
        description="採用観測の気温（ISD・ERA5-Land）と LST の対比表を作る"
    )
    parser.add_argument(
        "--lst-root", default="", help="LST GeoTIFF のルート（既定: data/satellite/lst）"
    )
    parser.add_argument(
        "--roi-path", default="", help="ROI のシェープファイル（既定: ハノイの ROI）"
    )
    parser.add_argument(
        "--isd-dir",
        default="",
        help="ISD の CSV のディレクトリ（既定: data/input/air_temperature/isd）",
    )
    parser.add_argument(
        "--output-dir", default="", help="出力先（既定: data/output/air_temperature）"
    )
    parser.add_argument(
        "--gee-config-path",
        default="",
        help="GEE 設定 CSV（既定: data/input/gee_calc_LST_info.csv）",
    )
    parser.add_argument(
        "--gee-project-id", default="", help="GEE のプロジェクト ID（設定 CSV より優先）"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """エントリーポイント。

    Args:
        argv: 引数のリスト。`None` の場合は `sys.argv` を使う。
    """
    args = parse_arguments(argv)

    def resolve(value: str, default: Path) -> Path:
        """CLI 引数の相対パスをプロジェクトルート基準で解決し、未指定なら既定値を返す。"""
        return resolve_relative_to_project_root(value, project_root=PROJECT_ROOT) or default

    csv_path, summary_path = run(
        lst_root=resolve(args.lst_root, DEFAULT_LST_ROOT),
        roi_path=resolve(args.roi_path, DEFAULT_HANOI_ROI_PATH),
        isd_dir=resolve(args.isd_dir, DEFAULT_ISD_DIR),
        output_dir=resolve(args.output_dir, DEFAULT_OUTPUT_DIR),
        gee_config_path=resolve(args.gee_config_path, DEFAULT_GEE_CONFIG_PATH),
        gee_project_id=args.gee_project_id,
    )
    print(f"対比表を保存しました: {csv_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
