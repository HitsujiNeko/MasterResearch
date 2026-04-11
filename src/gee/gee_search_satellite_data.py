# 作成者: Codex
# 作成日: 2026-04-09
# 概要: Landsat 8 シーンの探索結果を一覧化し、必要時に LST と衛星指標を同時出力する。

"""Google Earth Engine を用いた Landsat 8 シーン探索・同時出力プログラム。

本スクリプトは、既存の `gee_calc_LST.py` と
`gee_calc_satellite_indices.py` の算出ロジックを維持したまま、
次の2用途を1回の実行で扱えるようにする。

1. 探索専用:
   ROI を完全にカバーするか、LST と衛星指標の有効ピクセル率が
   十分かどうかを一覧化する。
2. エクスポート付き:
   探索結果のうち、ROI 完全包含かつ品質条件を満たすシーンだけを
   Google Drive へ出力する。

出力される GeoTIFF は、LST と INDICES を別ファイルで保持する。
これは既存分析フローとの互換性を維持するためである。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any
import datetime as dt

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import ee
import pandas as pd
from tqdm import tqdm

from src.gee.gee_calc_LST import (
    authenticate_gee,
    build_drive_export_folder,
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
from src.module.lst_smw import calculate_lst_smw


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "output" / "gee_search_satellite_data_results.csv"
ROI_COVERAGE_TOLERANCE = 0.999999


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="Landsat 8 シーンの探索を行い、必要時に LST と衛星指標を同時出力する。"
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
    return parser.parse_args()


def get_raw_landsat_collections(
    start_date: str,
    end_date: str,
    roi: ee.Geometry,
) -> tuple[ee.ImageCollection, ee.ImageCollection]:
    """未マスクの Landsat 8 TOA/SR コレクションを取得する。

    Args:
        start_date (str): 開始日。
        end_date (str): 終了日。
        roi (ee.Geometry): 対象 ROI。

    Returns:
        tuple[ee.ImageCollection, ee.ImageCollection]:
            TOA コレクションと未マスク SR コレクション。
    """
    collection_toa = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA")
        .filterDate(start_date, end_date)
        .filterBounds(roi)
    )
    collection_sr_raw = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterDate(start_date, end_date)
        .filterBounds(roi)
    )
    return collection_toa, collection_sr_raw


def filter_collection_by_target_dates(
    collection: ee.ImageCollection,
    target_observation_datetimes: set[str] | None,
) -> ee.ImageCollection:
    """指定観測日時の日付だけに ImageCollection を絞り込む。

    Args:
        collection (ee.ImageCollection): 絞り込み対象コレクション。
        target_observation_datetimes (set[str] | None): 対象観測日時集合。

    Returns:
        ee.ImageCollection: 対象日付の画像だけを含むコレクション。
    """
    if not target_observation_datetimes:
        return collection

    target_dates = sorted({observation_datetime[:10] for observation_datetime in target_observation_datetimes})
    filtered_collection: ee.ImageCollection | None = None

    for date_text in target_dates:
        start_date = dt.date.fromisoformat(date_text)
        end_date = (start_date + dt.timedelta(days=1)).isoformat()
        daily_collection = collection.filterDate(date_text, end_date)
        filtered_collection = (
            daily_collection
            if filtered_collection is None
            else filtered_collection.merge(daily_collection)
        )

    if filtered_collection is None:
        return collection.filterDate("1900-01-01", "1900-01-02")
    return filtered_collection


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


def build_lst_image(raw_sr_image: ee.Image, collection_toa: ee.ImageCollection, roi: ee.Geometry) -> ee.Image:
    """既存 LST ロジックと同一条件で LST 画像を作成する。

    Args:
        raw_sr_image (ee.Image): 未マスクの SR 画像。
        collection_toa (ee.ImageCollection): TOA コレクション。
        roi (ee.Geometry): ROI。

    Returns:
        ee.Image: LST バンド付き画像。
    """
    lst_sr_image = cloud_mask(raw_sr_image)
    toa_image = get_matching_toa_image(lst_sr_image, collection_toa)
    return calculate_lst_smw(lst_sr_image, toa_image, roi)


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


def build_indices_result(image: ee.Image, roi: ee.Geometry, band_names: list[str]) -> dict[str, float]:
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
    export_image = image.clip(roi).select("LST").set({
        "observation_datetime_utc": observation_datetime_utc
    })

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
    export_image = image.clip(roi).select(band_names).set({
        "observation_datetime_utc": observation_datetime_utc
    })

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


def build_export_prefix(observation_datetime_utc: str, prefix: str) -> str:
    """観測日時から既存運用と互換なファイル接頭辞を作る。

    Args:
        observation_datetime_utc (str): 観測日時。
        prefix (str): `LST` または `INDICES`。

    Returns:
        str: ファイル接頭辞。
    """
    date_time_token = observation_datetime_utc.replace("-", "").replace(":", "").replace("T", "_")
    return f"{prefix}_Landsat8_{date_time_token}Z"


def process_scene(
    raw_sr_image: ee.Image,
    collection_toa: ee.ImageCollection,
    roi: ee.Geometry,
    config: dict[str, Any],
    band_names: list[str],
    export_enabled: bool,
    target_observation_datetimes: set[str] | None = None,
) -> dict[str, Any]:
    """1シーン分の探索結果を作成し、必要時は同時エクスポートする。

    Args:
        raw_sr_image (ee.Image): 未マスク SR 画像。
        collection_toa (ee.ImageCollection): TOA コレクション。
        roi (ee.Geometry): ROI。
        config (dict[str, Any]): 設定辞書。
        band_names (list[str]): 指標バンド名一覧。
        export_enabled (bool): エクスポート実行フラグ。
        target_observation_datetimes (set[str] | None):
            強制エクスポート対象の観測日時集合。

    Returns:
        dict[str, Any]: 探索結果。
    """
    observation_datetime_utc = ee.Date(raw_sr_image.get("system:time_start")).format(
        "YYYY-MM-dd'T'HH:mm:ss"
    ).getInfo()
    date_text = observation_datetime_utc[:10]
    scene_index = ee.String(raw_sr_image.get("system:index")).getInfo()
    cloud_cover_info = raw_sr_image.get("CLOUD_COVER").getInfo()
    cloud_cover = to_float_or_nan(cloud_cover_info)

    scene_covers_roi_flag, scene_coverage_ratio = scene_covers_roi(raw_sr_image, roi)
    lst_image = build_lst_image(raw_sr_image, collection_toa, roi)
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
        lst_export_description = build_export_prefix(observation_datetime_utc, "LST")
        indices_export_description = build_export_prefix(observation_datetime_utc, "INDICES")
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
    return result


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

    authenticate_gee(project_id=gee_project_id)
    roi = load_roi_from_shapefile(roi_path_text)
    collection_toa, collection_sr_raw = get_raw_landsat_collections(start_date, end_date, roi)
    collection_toa = filter_collection_by_target_dates(collection_toa, target_observation_datetimes)
    collection_sr_raw = filter_collection_by_target_dates(collection_sr_raw, target_observation_datetimes)
    image_count = int(collection_sr_raw.size().getInfo())
    if image_count == 0:
        logger.warning("対象画像が0件のため処理を終了します。")
        return

    band_names = get_target_band_names()
    image_list = collection_sr_raw.toList(image_count)
    results: list[dict[str, Any]] = []

    logger.info("探索対象シーン数: %s", image_count)
    logger.info("エクスポートモード: %s", "有効" if export_enabled else "無効")
    if target_observation_datetimes:
        logger.info(
            "強制エクスポート対象: %s",
            ", ".join(sorted(target_observation_datetimes)),
        )

    for index in tqdm(range(image_count), desc="シーン探索中"):
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
            )
            results.append(result)
            logger.info(
                "%s processed: coverage=%.6f, lst_valid=%.2f, indices_valid=%.2f, eligible=%s, forced=%s",
                result["observation_datetime_utc"],
                result["scene_coverage_ratio"],
                result["lst_valid_pixel_ratio"],
                result["indices_valid_pixel_ratio"],
                result["export_eligible"],
                result["forced_export"],
            )
        except Exception as error:
            logger.error("画像処理中にエラーが発生しました（index=%s）: %s", index, error)

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


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
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
