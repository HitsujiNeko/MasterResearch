"""Google Earth Engine を用いた Landsat 8 / Landsat 9 シーン探索・同時出力プログラム。

本スクリプトは、既存の `gee_calc_LST.py` と
`gee_calc_satellite_indices.py` の算出ロジックを維持したまま、
次の2用途を1回の実行で扱えるようにする。

1. 探索専用:
   ROI を完全にカバーするか、LST と衛星指標の有効ピクセル率が
   十分かどうかを一覧化する。
2. エクスポート付き:
   探索結果のうち、ROI 完全包含かつ品質条件を満たすシーンだけを
   Google Drive へ出力する。

対象センサは設定 CSV の `sensors` 列（`;` 区切り、例: `L8;L9`）で指定し、
列がない・空欄の場合は L8 のみとする。センサごとにコレクションを取得して
処理し、結果 CSV の `satellite` 列（`Landsat8` / `Landsat9`）で区別する。処理に失敗したシーンは
センサ別の件数と一覧を最後にログへ要約する。

出力される GeoTIFF は、LST と INDICES を別ファイルで保持する。
これは既存分析フローとの互換性を維持するためである。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import ee
import pandas as pd
from tqdm import tqdm

from src.common.config import PROJECT_ROOT
from src.gee.gee_calc_LST import (
    authenticate_gee,
    build_drive_export_folder,
    build_export_description,
    calculate_pixel_stats,
    cloud_mask,
    extract_statistics,
    get_matching_toa_image,
    load_config,
    load_roi_from_shapefile,
)
from src.gee.gee_calc_satellite_indices import (
    add_indices,
    build_indices_drive_export_folder,
    calculate_index_stats,
    calculate_valid_pixel_ratio,
    cloud_mask_sr,
    get_target_band_names,
    to_float_or_nan,
)
from src.module.landsat_sensor import (
    DEFAULT_SENSOR,
    get_collection_id,
    get_sensor_label,
    parse_sensors,
)
from src.module.lst_smw import calculate_lst_smw

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "output" / "gee_search_satellite_data_results.csv"
DEFAULT_RANKING_CSV = PROJECT_ROOT / "data" / "output" / "gee_search_observation_ranking.csv"
ROI_COVERAGE_TOLERANCE = 0.999999


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description=(
            "Landsat 8 / Landsat 9 シーンの探索を行い、必要時に LST と衛星指標を同時出力する。"
        )
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="設定CSVのパス。",
    )
    parser.add_argument(
        "--output-csv-path",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="探索結果CSVの出力先。",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="条件を満たすシーンを Google Drive へ出力する。",
    )
    parser.add_argument(
        "--target-observation-datetimes",
        nargs="*",
        default=None,
        help=(
            "指定した観測日時だけをエクスポート対象にする。"
            "例: 2024-11-30T03:23:36 2023-07-23T03:23:09"
        ),
    )
    parser.add_argument(
        "--rerank-only",
        action="store_true",
        help=(
            "GEE へ接続せず、既存の探索結果CSVから実効ROIカバー率を算出し、"
            "結果CSVへの列追加とランキングCSVの出力のみを行う。"
        ),
    )
    parser.add_argument(
        "--ranking-csv-path",
        type=Path,
        default=DEFAULT_RANKING_CSV,
        help="--rerank-only 時のランキングCSV出力先。",
    )
    return parser.parse_args()


def get_raw_landsat_collections(
    start_date: str,
    end_date: str,
    roi: ee.Geometry,
    sensor: str = DEFAULT_SENSOR,
) -> tuple[ee.ImageCollection, ee.ImageCollection]:
    """未マスクの Landsat TOA/SR コレクションを指定センサについて取得する。

    Args:
        start_date (str): 開始日。
        end_date (str): 終了日。
        roi (ee.Geometry): 対象 ROI。
        sensor (str): センサ名（"L8" / "L9"）。

    Returns:
        tuple[ee.ImageCollection, ee.ImageCollection]:
            TOA コレクションと未マスク SR コレクション。

    Raises:
        ValueError: 未定義のセンサ名の場合。
    """
    collection_toa = (
        ee.ImageCollection(get_collection_id(sensor, "toa"))
        .filterDate(start_date, end_date)
        .filterBounds(roi)
    )
    collection_sr_raw = (
        ee.ImageCollection(get_collection_id(sensor, "sr"))
        .filterDate(start_date, end_date)
        .filterBounds(roi)
    )
    return collection_toa, collection_sr_raw


def build_target_date_ranges(target_observation_datetimes: set[str]) -> list[tuple[str, str]]:
    """観測日時集合から、対象日ごとの日付範囲（開始日, 翌日）を作る。

    同じ日付の観測日時は1つの範囲にまとめ、開始日の昇順に並べる。
    終了日は GEE の `filterDate` と同じく範囲に含まない（翌日の0時）。

    Args:
        target_observation_datetimes (set[str]): 対象観測日時集合
            （`YYYY-MM-DDTHH:MM:SS` 形式。先頭10文字を日付として用いる）。

    Returns:
        list[tuple[str, str]]: `(開始日, 翌日)` の ISO 形式日付の組のリスト。
    """
    target_dates = sorted(
        {observation_datetime[:10] for observation_datetime in target_observation_datetimes}
    )
    return [
        (date_text, (dt.date.fromisoformat(date_text) + dt.timedelta(days=1)).isoformat())
        for date_text in target_dates
    ]


def filter_collection_by_target_dates(
    collection: ee.ImageCollection,
    target_observation_datetimes: set[str] | None,
) -> ee.ImageCollection:
    """指定観測日時の日付だけに ImageCollection を絞り込む。

    対象日ごとの日付範囲を `ee.Filter.Or` でまとめ、元のコレクションに1回だけ
    `filter` をかける。日付ごとに絞り込んだコレクションを `merge` すると、
    GEE が `system:index` に結合元の番号（`1_`・`2_`、3日以上では `1_1_` のような
    入れ子）を付け、結果CSVの `scene_index` が通常の探索結果と一致しなくなるため。

    Args:
        collection (ee.ImageCollection): 絞り込み対象コレクション。
        target_observation_datetimes (set[str] | None): 対象観測日時集合。

    Returns:
        ee.ImageCollection: 対象日付の画像だけを含むコレクション
            （`system:index` は元のコレクションのまま）。
    """
    if not target_observation_datetimes:
        return collection

    date_filters = [
        ee.Filter.date(start_date, end_date)
        for start_date, end_date in build_target_date_ranges(target_observation_datetimes)
    ]
    return collection.filter(ee.Filter.Or(*date_filters))


def calculate_scene_coverage_ratio(image: ee.Image, roi: ee.Geometry) -> float:
    """雲マスク前のシーン footprint が ROI をどこまで覆うかを計算する。

    Args:
        image (ee.Image): 未マスクの Landsat 画像。
        roi (ee.Geometry): 判定対象の ROI。

    Returns:
        float: ROI に対する footprint の被覆率。
    """
    roi_area = ee.Number(roi.area(1))
    intersection_area = ee.Number(roi.intersection(image.geometry(), ee.ErrorMargin(1)).area(1))
    roi_area_value = float(roi_area.getInfo() or 0.0)
    intersection_area_value = float(intersection_area.getInfo() or 0.0)
    if roi_area_value == 0:
        return 0.0
    return intersection_area_value / roi_area_value


def scene_covers_roi(image: ee.Image, roi: ee.Geometry) -> tuple[bool, float]:
    """シーン footprint が ROI を完全包含するか判定する。

    Args:
        image (ee.Image): 未マスクの Landsat 画像。
        roi (ee.Geometry): 判定対象の ROI。

    Returns:
        tuple[bool, float]: 完全包含フラグと被覆率。
    """
    coverage_ratio = calculate_scene_coverage_ratio(image, roi)
    return coverage_ratio >= ROI_COVERAGE_TOLERANCE, coverage_ratio


def build_lst_image(
    raw_sr_image: ee.Image,
    collection_toa: ee.ImageCollection,
    roi: ee.Geometry,
    sensor: str = DEFAULT_SENSOR,
) -> ee.Image:
    """既存 LST ロジックと同一条件で LST 画像を作成する。

    Args:
        raw_sr_image (ee.Image): 未マスクの SR 画像。
        collection_toa (ee.ImageCollection): TOA コレクション（SR と同じセンサ）。
        roi (ee.Geometry): ROI。
        sensor (str): 画像の取得元センサ名（"L8" / "L9"）。SMW 係数の選択に用いる。

    Returns:
        ee.Image: LST バンド付き画像。
    """
    lst_sr_image = cloud_mask(raw_sr_image)
    toa_image = get_matching_toa_image(lst_sr_image, collection_toa)
    return calculate_lst_smw(lst_sr_image, toa_image, roi, sensor=sensor)


def build_indices_image(raw_sr_image: ee.Image) -> ee.Image:
    """既存指標ロジックと同一条件で NDVI/NDBI/NDWI 画像を作成する。

    Args:
        raw_sr_image (ee.Image): 未マスクの SR 画像。

    Returns:
        ee.Image: 指標バンド付き画像。
    """
    return add_indices(cloud_mask_sr(raw_sr_image))


def build_lst_result(image: ee.Image, roi: ee.Geometry) -> dict[str, float]:
    """LST 側の統計量と有効ピクセル率をまとめる。

    Args:
        image (ee.Image): LST 画像。
        roi (ee.Geometry): 集計対象 ROI。

    Returns:
        dict[str, float]: LST 関連の結果辞書。
    """
    pixel_stats = calculate_pixel_stats(image, roi)
    total_pixels = float(pixel_stats.get("total_pixels") or 0.0)
    valid_pixels = float(pixel_stats.get("valid_pixels") or 0.0)
    valid_ratio = (valid_pixels / total_pixels * 100.0) if total_pixels > 0 else 0.0
    temperature_stats = extract_statistics(image, roi)

    return {
        "lst_total_pixels": total_pixels,
        "lst_valid_pixels": valid_pixels,
        "lst_valid_pixel_ratio": valid_ratio,
        "lst_mean_temp_c": to_float_or_nan(temperature_stats.get("mean")),
        "lst_min_temp_c": to_float_or_nan(temperature_stats.get("min")),
        "lst_max_temp_c": to_float_or_nan(temperature_stats.get("max")),
        "lst_std_temp_c": to_float_or_nan(temperature_stats.get("std")),
    }


def build_indices_result(
    image: ee.Image, roi: ee.Geometry, band_names: list[str]
) -> dict[str, float]:
    """衛星指標側の統計量と有効ピクセル率をまとめる。

    Args:
        image (ee.Image): 指標画像。
        roi (ee.Geometry): 集計対象 ROI。
        band_names (list[str]): 指標バンド名一覧。

    Returns:
        dict[str, float]: 指標関連の結果辞書。
    """
    valid_ratio = calculate_valid_pixel_ratio(image, roi, band_name="NDVI")
    index_stats = calculate_index_stats(image, roi, band_names)

    return {
        "indices_valid_pixel_ratio": valid_ratio,
        **index_stats,
    }


def calculate_effective_roi_coverage(
    scene_coverage_ratio: float | None, valid_pixel_ratio: float | None
) -> float:
    """シーンのROI被覆率と有効ピクセル率から、実効ROIカバー率を算出する。

    `scene_coverage_ratio` は 0-1 スケール、`valid_pixel_ratio` は 0-100 スケール
    （`lst_valid_pixel_ratio` / `indices_valid_pixel_ratio` と同一）で受け取り、
    戻り値は `*_valid_pixel_ratio` に合わせて 0-100 スケールに統一する。

    Args:
        scene_coverage_ratio (float | None): ROIに対するシーンfootprintの被覆率（0-1）。
        valid_pixel_ratio (float | None): ROI内の有効ピクセル率（0-100）。

    Returns:
        float: 実効ROIカバー率（0-100）。入力が欠損（None/NaN）の場合はNaN。
    """
    if scene_coverage_ratio is None or valid_pixel_ratio is None:
        return float("nan")
    if math.isnan(scene_coverage_ratio) or math.isnan(valid_pixel_ratio):
        return float("nan")
    return float(scene_coverage_ratio) * float(valid_pixel_ratio)


def build_effective_roi_coverage_result(
    scene_coverage_ratio: float | None,
    lst_valid_pixel_ratio: float | None,
    indices_valid_pixel_ratio: float | None,
) -> dict[str, float]:
    """LST・指標それぞれの実効ROIカバー率と、選定キーとなる最小値をまとめる。

    最小値を選定キーとするのは、`build_dataset.validate_observation_consistency()`
    がLSTと衛星指標を同一観測に強制するため、分析に使えるのは両方が有効な
    セルに限られるからである。平均を取ると片方の欠測が薄まり、実際に使える
    セル数を過大評価する。

    Args:
        scene_coverage_ratio (float | None): ROIに対するシーンfootprintの被覆率（0-1）。
        lst_valid_pixel_ratio (float | None): LSTの有効ピクセル率（0-100）。
        indices_valid_pixel_ratio (float | None): 衛星指標の有効ピクセル率（0-100）。

    Returns:
        dict[str, float]: `lst_effective_roi_coverage` / `indices_effective_roi_coverage` /
            `effective_roi_coverage`（前2列の最小値）を含む辞書。
    """
    lst_effective_roi_coverage = calculate_effective_roi_coverage(
        scene_coverage_ratio, lst_valid_pixel_ratio
    )
    indices_effective_roi_coverage = calculate_effective_roi_coverage(
        scene_coverage_ratio, indices_valid_pixel_ratio
    )
    if math.isnan(lst_effective_roi_coverage) or math.isnan(indices_effective_roi_coverage):
        effective_roi_coverage = float("nan")
    else:
        effective_roi_coverage = min(lst_effective_roi_coverage, indices_effective_roi_coverage)

    return {
        "lst_effective_roi_coverage": lst_effective_roi_coverage,
        "indices_effective_roi_coverage": indices_effective_roi_coverage,
        "effective_roi_coverage": effective_roi_coverage,
    }


def determine_export_reason(
    scene_covers_roi_flag: bool,
    lst_valid_ratio: float,
    indices_valid_ratio: float,
    valid_threshold: float,
) -> str:
    """エクスポート可否の理由を簡潔に返す。

    Args:
        scene_covers_roi_flag (bool): ROI 完全包含フラグ。
        lst_valid_ratio (float): LST 有効ピクセル率。
        indices_valid_ratio (float): 指標有効ピクセル率。
        valid_threshold (float): 閾値。

    Returns:
        str: 判定理由。
    """
    reasons: list[str] = []

    if not scene_covers_roi_flag:
        reasons.append("scene_does_not_cover_roi")
    if lst_valid_ratio < valid_threshold:
        reasons.append("lst_valid_ratio_below_threshold")
    if indices_valid_ratio < valid_threshold:
        reasons.append("indices_valid_ratio_below_threshold")

    if not reasons:
        return "eligible"
    return "|".join(reasons)


def export_lst_to_drive(
    image: ee.Image,
    roi: ee.Geometry,
    output_epsg: int,
    folder_name: str,
    description: str,
    observation_datetime_utc: str,
) -> None:
    """LST 画像を ROI クリップ済み GeoTIFF として Drive に出力する。

    Args:
        image (ee.Image): LST 画像。
        roi (ee.Geometry): ROI。
        output_epsg (int): 出力 EPSG。
        folder_name (str): Drive フォルダ名。
        description (str): ファイル接頭辞。
        observation_datetime_utc (str): 観測日時。
    """
    export_image = (
        image.clip(roi).select("LST").set({"observation_datetime_utc": observation_datetime_utc})
    )

    task = ee.batch.Export.image.toDrive(
        image=export_image,
        description=description,
        folder=folder_name,
        fileNamePrefix=description,
        region=roi,
        scale=30,
        crs=f"EPSG:{output_epsg}",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
    )
    task.start()


def export_indices_to_drive(
    image: ee.Image,
    roi: ee.Geometry,
    output_epsg: int,
    folder_name: str,
    description: str,
    observation_datetime_utc: str,
    band_names: list[str],
) -> None:
    """指標画像を ROI クリップ済み GeoTIFF として Drive に出力する。

    Args:
        image (ee.Image): 指標画像。
        roi (ee.Geometry): ROI。
        output_epsg (int): 出力 EPSG。
        folder_name (str): Drive フォルダ名。
        description (str): ファイル接頭辞。
        observation_datetime_utc (str): 観測日時。
        band_names (list[str]): 出力バンド名。
    """
    export_image = (
        image.clip(roi)
        .select(band_names)
        .set({"observation_datetime_utc": observation_datetime_utc})
    )

    task = ee.batch.Export.image.toDrive(
        image=export_image,
        description=description,
        folder=folder_name,
        fileNamePrefix=description,
        region=roi,
        scale=30,
        crs=f"EPSG:{output_epsg}",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
    )
    task.start()


def count_scenes_by_path_row(scene_rows: list[list[Any]]) -> dict[str, int]:
    """WRS-2 の path/row ごとのシーン件数を数える。

    Args:
        scene_rows (list[list[Any]]): 各シーンの `[WRS_PATH, WRS_ROW, ...]`
            （GEE から取得した値。先頭2要素のみを用いる）。

    Returns:
        dict[str, int]: `"PPP/RRR"`（3桁ゼロ埋め）をキー、件数を値とする辞書（キーの昇順）。
    """
    counts = Counter(f"{int(row[0]):03d}/{int(row[1]):03d}" for row in scene_rows)
    return dict(sorted(counts.items()))


def build_failure_summary_lines(
    image_counts: dict[str, int], failures: list[dict[str, Any]]
) -> list[str]:
    """処理に失敗したシーンのセンサ別要約をログ出力用の行として組み立てる。

    Args:
        image_counts (dict[str, int]): センサ名 -> 処理対象のシーン数。
        failures (list[dict[str, Any]]): 失敗シーンの記録。各要素は
            `sensor`・`index`・`scene_index`・`error` を持つ。

    Returns:
        list[str]: センサごとの「対象・成功・失敗」件数の行と、失敗シーン1件ごとの行。

    Raises:
        ValueError: `image_counts` にないセンサの失敗記録を含む場合（件数を算出できないため）。
    """
    failures_by_sensor: dict[str, list[dict[str, Any]]] = {sensor: [] for sensor in image_counts}
    for failure in failures:
        if failure["sensor"] not in failures_by_sensor:
            raise ValueError(f"処理対象のシーン数が不明なセンサの失敗記録です: {failure['sensor']}")
        failures_by_sensor[failure["sensor"]].append(failure)

    lines: list[str] = []
    for sensor, sensor_failures in failures_by_sensor.items():
        image_count = image_counts[sensor]
        lines.append(
            f"{get_sensor_label(sensor)}: 対象 {image_count} 件 / "
            f"成功 {image_count - len(sensor_failures)} 件 / 失敗 {len(sensor_failures)} 件"
        )
        for failure in sensor_failures:
            lines.append(
                f"  失敗: index={failure['index']}, scene_index={failure['scene_index']}, "
                f"error={failure['error']}"
            )
    return lines


def process_scene(
    raw_sr_image: ee.Image,
    collection_toa: ee.ImageCollection,
    roi: ee.Geometry,
    config: dict[str, Any],
    band_names: list[str],
    export_enabled: bool,
    target_observation_datetimes: set[str] | None = None,
    sensor: str = DEFAULT_SENSOR,
) -> dict[str, Any]:
    """1シーン分の探索結果を作成し、必要時は同時エクスポートする。

    Args:
        raw_sr_image (ee.Image): 未マスク SR 画像。
        collection_toa (ee.ImageCollection): TOA コレクション（SR と同じセンサ）。
        roi (ee.Geometry): ROI。
        config (dict[str, Any]): 設定辞書。
        band_names (list[str]): 指標バンド名一覧。
        export_enabled (bool): エクスポート実行フラグ。
        target_observation_datetimes (set[str] | None):
            強制エクスポート対象の観測日時集合。
        sensor (str): 画像の取得元センサ名（"L8" / "L9"）。SMW 係数・出力名・
            結果の `satellite` 列に用いる。

    Returns:
        dict[str, Any]: 探索結果。
    """
    observation_datetime_utc = (
        ee.Date(raw_sr_image.get("system:time_start")).format("YYYY-MM-dd'T'HH:mm:ss").getInfo()
    )
    date_text = observation_datetime_utc[:10]
    scene_index = ee.String(raw_sr_image.get("system:index")).getInfo()
    cloud_cover_info = raw_sr_image.get("CLOUD_COVER").getInfo()
    cloud_cover = to_float_or_nan(cloud_cover_info)

    scene_covers_roi_flag, scene_coverage_ratio = scene_covers_roi(raw_sr_image, roi)
    lst_image = build_lst_image(raw_sr_image, collection_toa, roi, sensor=sensor)
    indices_image = build_indices_image(raw_sr_image)

    lst_result = build_lst_result(lst_image, roi)
    indices_result = build_indices_result(indices_image, roi, band_names)
    valid_threshold = float(config.get("valid_pixel_threshold", 50))
    export_reason = determine_export_reason(
        scene_covers_roi_flag=scene_covers_roi_flag,
        lst_valid_ratio=lst_result["lst_valid_pixel_ratio"],
        indices_valid_ratio=indices_result["indices_valid_pixel_ratio"],
        valid_threshold=valid_threshold,
    )
    export_eligible = export_reason == "eligible"
    forced_export = (
        target_observation_datetimes is not None
        and observation_datetime_utc in target_observation_datetimes
    )

    output_epsg = int(config.get("output_epsg", 4326))
    lst_drive_folder = build_drive_export_folder(config, date_text)
    indices_drive_folder = build_indices_drive_export_folder(config, date_text)

    lst_export_description = ""
    indices_export_description = ""
    exported = False
    if export_enabled and (export_eligible or forced_export):
        lst_export_description = build_export_description("LST", observation_datetime_utc, sensor)
        indices_export_description = build_export_description(
            "INDICES", observation_datetime_utc, sensor
        )
        export_lst_to_drive(
            image=lst_image,
            roi=roi,
            output_epsg=output_epsg,
            folder_name=lst_drive_folder,
            description=lst_export_description,
            observation_datetime_utc=observation_datetime_utc,
        )
        export_indices_to_drive(
            image=indices_image,
            roi=roi,
            output_epsg=output_epsg,
            folder_name=indices_drive_folder,
            description=indices_export_description,
            observation_datetime_utc=observation_datetime_utc,
            band_names=band_names,
        )
        exported = True

    result = {
        "date": date_text,
        "observation_datetime_utc": observation_datetime_utc,
        "scene_index": scene_index,
        "satellite": get_sensor_label(sensor),
        "cloud_cover": cloud_cover,
        "scene_covers_roi": scene_covers_roi_flag,
        "scene_coverage_ratio": scene_coverage_ratio,
        "export_requested": export_enabled,
        "export_eligible": export_eligible,
        "forced_export": forced_export,
        "export_reason": export_reason,
        "exported": exported,
        "lst_drive_folder": lst_drive_folder if exported else "",
        "indices_drive_folder": indices_drive_folder if exported else "",
        "lst_export_description": lst_export_description,
        "indices_export_description": indices_export_description,
    }
    result.update(lst_result)
    result.update(indices_result)
    result.update(
        build_effective_roi_coverage_result(
            scene_coverage_ratio=scene_coverage_ratio,
            lst_valid_pixel_ratio=lst_result["lst_valid_pixel_ratio"],
            indices_valid_pixel_ratio=indices_result["indices_valid_pixel_ratio"],
        )
    )
    return result


def process_sensor_scenes(
    sensor: str,
    roi: ee.Geometry,
    config: dict[str, Any],
    band_names: list[str],
    export_enabled: bool,
    target_observation_datetimes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """1センサ分のコレクションを取得し、各シーンを探索する。

    Args:
        sensor (str): センサ名（"L8" / "L9"）。
        roi (ee.Geometry): ROI。
        config (dict[str, Any]): 設定辞書（start_date / end_date を含む）。
        band_names (list[str]): 指標バンド名一覧。
        export_enabled (bool): エクスポート実行フラグ。
        target_observation_datetimes (set[str] | None):
            強制エクスポート対象の観測日時集合（指定時は対象日付のシーンに絞り込む）。

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
            (探索結果のリスト, 失敗シーンの記録のリスト, 処理対象のシーン数)。
    """
    sensor_label = get_sensor_label(sensor)
    collection_toa, collection_sr_raw = get_raw_landsat_collections(
        config["start_date"], config["end_date"], roi, sensor=sensor
    )
    collection_toa = filter_collection_by_target_dates(collection_toa, target_observation_datetimes)
    collection_sr_raw = filter_collection_by_target_dates(
        collection_sr_raw, target_observation_datetimes
    )
    image_count = int(collection_sr_raw.size().getInfo())
    if image_count == 0:
        logger.warning("対象画像が0件です（%s）。", sensor_label)
        return [], [], 0

    # path/row と system:index を toList と同じ順序で1回の往復でまとめて取得する。
    # path/row 別件数は CSV 件数との差（失敗件数）の追跡に、system:index は失敗シーンの特定に用いる
    scene_rows = ee.List(
        collection_sr_raw.reduceColumns(
            ee.Reducer.toList(3), ["WRS_PATH", "WRS_ROW", "system:index"]
        ).get("list")
    ).getInfo()
    logger.info("%s の探索対象シーン数: %s", sensor_label, image_count)
    for path_row, count in count_scenes_by_path_row(scene_rows).items():
        logger.info("  %s path/row=%s: %s 件", sensor_label, path_row, count)

    scene_indices = [row[2] for row in scene_rows]
    image_list = collection_sr_raw.toList(image_count)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index in tqdm(range(image_count), desc=f"シーン探索中（{sensor_label}）"):
        raw_sr_image = ee.Image(image_list.get(index))
        try:
            result = process_scene(
                raw_sr_image=raw_sr_image,
                collection_toa=collection_toa,
                roi=roi,
                config=config,
                band_names=band_names,
                export_enabled=export_enabled,
                target_observation_datetimes=target_observation_datetimes,
                sensor=sensor,
            )
            results.append(result)
            logger.info(
                "%s %s processed: coverage=%.6f, lst_valid=%.2f, indices_valid=%.2f, "
                "eligible=%s, forced=%s",
                sensor_label,
                result["observation_datetime_utc"],
                result["scene_coverage_ratio"],
                result["lst_valid_pixel_ratio"],
                result["indices_valid_pixel_ratio"],
                result["export_eligible"],
                result["forced_export"],
            )
        except Exception as error:
            scene_index = scene_indices[index] if index < len(scene_indices) else "不明"
            logger.error(
                "画像処理中にエラーが発生しました（%s, index=%s, scene_index=%s）: %s",
                sensor_label,
                index,
                scene_index,
                error,
            )
            failures.append(
                {"sensor": sensor, "index": index, "scene_index": scene_index, "error": str(error)}
            )

    return results, failures, image_count


def run(
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_csv_path: Path = DEFAULT_OUTPUT_CSV,
    export_enabled: bool = False,
    target_observation_datetimes: set[str] | None = None,
) -> None:
    """探索処理全体を実行する。

    Args:
        config_path (Path): 設定 CSV のパス。
        output_csv_path (Path): 結果 CSV の出力先。
        export_enabled (bool): エクスポート実行フラグ。
        target_observation_datetimes (set[str] | None):
            強制エクスポート対象の観測日時集合。
    """
    config = load_config(str(config_path))
    gee_project_id = config.get("gee_project_id")
    if not gee_project_id or gee_project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError("GCPプロジェクトIDが設定されていません。設定CSVを確認してください。")

    roi_path_text = str(config.get("roi_shapefile_path") or "").strip()
    if not roi_path_text:
        raise ValueError("設定CSVに roi_shapefile_path がありません。")

    start_date = config.get("start_date")
    end_date = config.get("end_date")
    if not start_date or not end_date:
        raise ValueError("設定CSVに start_date / end_date が必要です。")

    sensors = parse_sensors(config.get("sensors"))

    authenticate_gee(project_id=gee_project_id)
    roi = load_roi_from_shapefile(roi_path_text)
    band_names = get_target_band_names()

    logger.info("処理対象のセンサ: %s", ", ".join(sensors))
    logger.info("エクスポートモード: %s", "有効" if export_enabled else "無効")
    if target_observation_datetimes:
        logger.info(
            "強制エクスポート対象: %s",
            ", ".join(sorted(target_observation_datetimes)),
        )

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    image_counts: dict[str, int] = {}
    for sensor in sensors:
        sensor_results, sensor_failures, sensor_image_count = process_sensor_scenes(
            sensor=sensor,
            roi=roi,
            config=config,
            band_names=band_names,
            export_enabled=export_enabled,
            target_observation_datetimes=target_observation_datetimes,
        )
        results.extend(sensor_results)
        failures.extend(sensor_failures)
        image_counts[sensor] = sensor_image_count

    if sum(image_counts.values()) == 0:
        logger.warning("対象画像が0件のため処理を終了します。")
        return

    # 失敗シーンを黙って欠落させないよう、センサ別の件数と一覧を要約する
    logger.info("センサ別の処理結果:")
    for line in build_failure_summary_lines(image_counts, failures):
        logger.info(line)

    if not results:
        logger.warning("有効な探索結果が無いためCSV出力をスキップします。")
        return

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    result_df = pd.DataFrame(results).sort_values("observation_datetime_utc").reset_index(drop=True)
    result_df.to_csv(output_csv_path, index=False, encoding="utf-8")

    eligible_count = int(result_df["export_eligible"].sum())
    exported_count = int(result_df["exported"].sum())
    logger.info("探索完了: %s 件", len(result_df))
    logger.info("エクスポート候補件数: %s 件", eligible_count)
    logger.info("実際にエクスポートした件数: %s 件", exported_count)
    logger.info("探索結果CSV: %s", output_csv_path)


EFFECTIVE_ROI_COVERAGE_SOURCE_COLUMNS = (
    "scene_coverage_ratio",
    "lst_valid_pixel_ratio",
    "indices_valid_pixel_ratio",
)
EFFECTIVE_ROI_COVERAGE_OUTPUT_COLUMNS = (
    "lst_effective_roi_coverage",
    "indices_effective_roi_coverage",
    "effective_roi_coverage",
)


def add_effective_roi_coverage_columns(results_df: pd.DataFrame) -> pd.DataFrame:
    """探索結果DataFrameへ実効ROIカバー率3列を追加する。

    Args:
        results_df (pd.DataFrame): `scene_coverage_ratio` / `lst_valid_pixel_ratio` /
            `indices_valid_pixel_ratio` を含む探索結果。

    Returns:
        pd.DataFrame: 実効ROIカバー率3列を追加したDataFrame（行順は変更しない）。

    Raises:
        ValueError: 実効ROIカバー率の算出に必要な列が不足している場合。
    """
    missing_columns = [
        column_name
        for column_name in EFFECTIVE_ROI_COVERAGE_SOURCE_COLUMNS
        if column_name not in results_df.columns
    ]
    if missing_columns:
        raise ValueError(f"実効ROIカバー率の算出に必要な列が不足しています: {missing_columns}")

    augmented_df = results_df.copy()
    if augmented_df.empty:
        # 0行の場合 DataFrame.apply は関数を1度も呼ばず元の列をそのまま返すため、
        # 出力列が欠けたままにならないよう空のfloat列として明示的に追加する。
        for column_name in EFFECTIVE_ROI_COVERAGE_OUTPUT_COLUMNS:
            augmented_df[column_name] = pd.Series(dtype="float64")
        return augmented_df

    effective_columns_df = augmented_df.apply(
        lambda row: build_effective_roi_coverage_result(
            row["scene_coverage_ratio"],
            row["lst_valid_pixel_ratio"],
            row["indices_valid_pixel_ratio"],
        ),
        axis=1,
        result_type="expand",
    )
    for column_name in EFFECTIVE_ROI_COVERAGE_OUTPUT_COLUMNS:
        augmented_df[column_name] = effective_columns_df[column_name]
    return augmented_df


def run_rerank_only(
    results_csv_path: Path = DEFAULT_OUTPUT_CSV,
    ranking_csv_path: Path = DEFAULT_RANKING_CSV,
) -> None:
    """GEEへ接続せず、既存の探索結果CSVから実効ROIカバー率を算出し直す。

    既存の探索結果CSV（`results_csv_path`）へ実効ROIカバー率3列を追加した上で
    上書き保存し、`effective_roi_coverage` 降順に並べ替えたランキングCSVを
    `ranking_csv_path` へ出力する。GEEへの接続は行わない。

    Args:
        results_csv_path (Path): 探索結果CSVのパス（列追加のうえ上書きする）。
        ranking_csv_path (Path): ランキングCSVの出力先。

    Raises:
        FileNotFoundError: `results_csv_path` が存在しない場合。
        ValueError: `results_csv_path` に必須列（`scene_coverage_ratio` 等）が
            不足している場合、または `results_csv_path` と `ranking_csv_path` が
            同一パスの場合（後者の書き込みが前者を上書きし、既存行順を保つ要件が
            崩れるため）。
    """
    if not results_csv_path.exists():
        raise FileNotFoundError(f"探索結果CSVが見つかりません: {results_csv_path}")
    if results_csv_path.resolve() == ranking_csv_path.resolve():
        raise ValueError("結果CSVとランキングCSVには異なるパスを指定してください。")

    # 既定の高速パーサーは浮動小数点値を round-trip 精度で読まないため、
    # 既存列の値が最終桁でわずかに変化しうる。既存行は変更しない前提のため
    # float_precision="round_trip" で読み込み、値の同一性を保つ。
    results_df = pd.read_csv(results_csv_path, float_precision="round_trip")
    augmented_df = add_effective_roi_coverage_columns(results_df)
    augmented_df.to_csv(results_csv_path, index=False, encoding="utf-8")
    logger.info("実効ROIカバー率列を追加しました: %s", results_csv_path)

    ranked_df = augmented_df.sort_values("effective_roi_coverage", ascending=False).reset_index(
        drop=True
    )
    ranking_csv_path.parent.mkdir(parents=True, exist_ok=True)
    ranked_df.to_csv(ranking_csv_path, index=False, encoding="utf-8")
    logger.info("ランキングCSVを出力しました: %s", ranking_csv_path)


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()

    if args.rerank_only:
        run_rerank_only(
            results_csv_path=args.output_csv_path,
            ranking_csv_path=args.ranking_csv_path,
        )
        return

    target_observation_datetimes = None
    if args.target_observation_datetimes:
        target_observation_datetimes = {
            observation_datetime.strip()
            for observation_datetime in args.target_observation_datetimes
            if observation_datetime.strip()
        }
    run(
        config_path=args.config_path,
        output_csv_path=args.output_csv_path,
        export_enabled=args.export,
        target_observation_datetimes=target_observation_datetimes,
    )


if __name__ == "__main__":
    main()
