# 作成者: GitHub Copilot
# 作成日: 2026-04-02
# 概要: Landsat 8 / Landsat 9 SRから衛星指標を算出し、統計CSVとGeoTIFFを出力する。

"""Google Earth Engineを使用したLandsat 8 / Landsat 9衛星指標算出プログラム。

本プログラムは、Landsat 8 / Landsat 9 Collection 2 Level-2（SR）を用いて
以下の衛星指標を算出する。

- 算出指標: NDVI, NDBI, NDWI, MNDWI
- 対象センサ: 設定CSVの `sensors` 列（`;` 区切り、例: `L8;L9`）。列がない・空欄の
  場合は L8 のみ。Landsat 9（OLI-2）の SR バンド構成は Landsat 8 と同一のため、
  指標の定義・スケーリングはセンサによらず共通とする

主な出力:
1. 画像ごとの統計量CSV
2. 指標バンドを含むGeoTIFF（Google Driveへ出力）

設計方針:
- 認証、設定読込、ROI読込、Driveフォルダ命名は gee_calc_LST.py を再利用する
- LST側の安定実装に依存しつつ、指標算出の責務のみ本ファイルに分離する
"""

from __future__ import annotations

import logging
import sys
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
    load_config,
    load_roi_from_shapefile,
)
from src.module.landsat_sensor import (
    DEFAULT_SENSOR,
    get_collection_id,
    get_sensor_label,
    parse_sensors,
)

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "output" / "gee_calc_indices_results.csv"

# 正規化差分指標の定義表: 指標名 -> (バンドA, バンドB)。指標 = (A - B) / (A + B)
# SR_B3=GREEN, SR_B4=RED, SR_B5=NIR, SR_B6=SWIR1（Landsat 8 OLI / Landsat 9 OLI-2 で共通）
# MNDWIはXu (2006) の定義（GREENとSWIR1）。定義の順序が出力バンドの順序になる。
NORMALIZED_DIFFERENCE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "NDVI": ("SR_B5", "SR_B4"),
    "NDBI": ("SR_B6", "SR_B5"),
    "NDWI": ("SR_B3", "SR_B5"),
    "MNDWI": ("SR_B3", "SR_B6"),
}
BASE_INDEX_BANDS = list(NORMALIZED_DIFFERENCE_DEFINITIONS)
# 分母のゼロ近傍を未定義として除外する閾値
DENOMINATOR_EPS = 1e-6
SR_SCALE_FACTOR = 0.0000275
SR_ADD_OFFSET = -0.2
# USGS FAQのCollection 2 Level-2 SR有効DN範囲（scale適用前）
SR_VALID_DN_MIN = 7273
SR_VALID_DN_MAX = 43636


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def to_float_or_nan(value: Any) -> float:
    """値をfloatへ変換し、変換不能時はNaNを返す。

    Args:
        value (Any): 変換対象の値。

    Returns:
        float: 変換結果。Noneや変換不能値はNaN。
    """
    if value is None:
        return float("nan")

    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def get_target_band_names() -> list[str]:
    """算出対象バンド名の一覧を返す。

    Returns:
        list[str]: 算出対象の指標バンド名一覧（NDVI, NDBI, NDWI, MNDWI）。
    """
    return list(BASE_INDEX_BANDS)


def cloud_mask_sr(image: ee.Image) -> ee.Image:
    """USGS QA定義に基づき、品質不良ピクセルを除去する。

    参照:
    - USGS Landsat Collection 2 QA_PIXEL / QA_RADSAT
    - GEEデータカタログ LANDSAT/LC08/C02/T1_L2, LANDSAT/LC09/C02/T1_L2

    Args:
        image (ee.Image): Landsat 8 / Landsat 9 Collection 2 Level-2画像。

    Returns:
        ee.Image: Fill/雲/雲影/雪/飽和を除去した画像。
    """
    qa = image.select("QA_PIXEL")
    # QA_PIXEL bit定義（Landsat 8-9 Collection 2）
    # bit0: Fill, bit1: Dilated Cloud, bit2: Cirrus, bit3: Cloud,
    # bit4: Cloud Shadow, bit5: Snow
    no_fill = qa.bitwiseAnd(1 << 0).eq(0)
    no_dilated_cloud = qa.bitwiseAnd(1 << 1).eq(0)
    no_cirrus = qa.bitwiseAnd(1 << 2).eq(0)
    no_cloud = qa.bitwiseAnd(1 << 3).eq(0)
    no_shadow = qa.bitwiseAnd(1 << 4).eq(0)
    no_snow = qa.bitwiseAnd(1 << 5).eq(0)

    qa_mask = no_fill.And(no_dilated_cloud).And(no_cirrus).And(no_cloud).And(no_shadow).And(no_snow)

    # QA_RADSATは各バンドの飽和を示す。0のみ採用して飽和画素を除外する。
    no_saturation = image.select("QA_RADSAT").eq(0)

    return image.updateMask(qa_mask).updateMask(no_saturation)


def get_scaled_optical_bands(image: ee.Image) -> ee.Image:
    """SR光学バンドをUSGS仕様でスケーリングし、有効域のみ残す。

    USGS FAQで示されるCollection 2 Level-2 SRの有効DN範囲を使用し、
    物理的に不適切な反射率（スケーリング後で概ね0-1外）を除外する。

    Args:
        image (ee.Image): Landsat 8 / Landsat 9 Collection 2 Level-2画像。

    Returns:
        ee.Image: SR_B3, SR_B4, SR_B5, SR_B6のスケーリング済み画像。
    """
    optical_dn = image.select(["SR_B3", "SR_B4", "SR_B5", "SR_B6"])
    valid_dn_mask = optical_dn.gte(SR_VALID_DN_MIN).And(optical_dn.lte(SR_VALID_DN_MAX))
    optical_dn = optical_dn.updateMask(valid_dn_mask.reduce(ee.Reducer.allNonZero()))

    return optical_dn.multiply(SR_SCALE_FACTOR).add(SR_ADD_OFFSET)


def add_indices(image: ee.Image) -> ee.Image:
    """NDVI/NDBI/NDWI/MNDWIを追加する。

    都市構造パラメータ（衛星由来）の定義式:
        NDVI = (NIR - RED) / (NIR + RED)
        NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)
        NDWI = (GREEN - NIR) / (GREEN + NIR)
        MNDWI = (GREEN - SWIR1) / (GREEN + SWIR1)

    各指標のバンドの組は NORMALIZED_DIFFERENCE_DEFINITIONS を正とする。

    Args:
        image (ee.Image): Landsat 8 / Landsat 9 Collection 2 Level-2画像。

    Returns:
        ee.Image: 定義表の順にNDVI/NDBI/NDWI/MNDWIバンドを追加した画像。
    """
    optical = get_scaled_optical_bands(image)

    # 数学的に分母0は未定義のため、ゼロ近傍を明示的に除外する。
    eps = ee.Number(DENOMINATOR_EPS)
    index_bands = []
    for index_name, (band_a, band_b) in NORMALIZED_DIFFERENCE_DEFINITIONS.items():
        value_a = optical.select(band_a)
        value_b = optical.select(band_b)
        denominator = value_a.add(value_b)
        index_bands.append(
            value_a.subtract(value_b)
            .divide(denominator)
            .updateMask(denominator.abs().gt(eps))
            .rename(index_name)
        )

    return image.addBands(index_bands)


def get_landsat_sr_collection(
    start_date: str,
    end_date: str,
    roi: ee.Geometry,
    sensor: str = DEFAULT_SENSOR,
) -> ee.ImageCollection:
    """期間とROIで指定センサのLandsat SRコレクションを取得する。

    Args:
        start_date (str): 取得開始日（YYYY-MM-DD）。
        end_date (str): 取得終了日（YYYY-MM-DD）。
        roi (ee.Geometry): 解析対象の領域。
        sensor (str): センサ名（"L8" / "L9"）。

    Returns:
        ee.ImageCollection: 雲マスクと指標バンド付与を行った画像コレクション。

    Raises:
        ValueError: 未定義のセンサ名の場合。
    """

    def add_indices_map(image: ee.Image) -> ee.Image:
        return add_indices(image)

    collection = (
        ee.ImageCollection(get_collection_id(sensor, "sr"))
        .filterDate(start_date, end_date)
        .filterBounds(roi)
        .map(cloud_mask_sr)
        .map(add_indices_map)
    )

    count = collection.size().getInfo()
    logger.info("対象期間内の画像数（%s）: %s", get_sensor_label(sensor), count)
    return collection


def calculate_valid_pixel_ratio(
    image: ee.Image, roi: ee.Geometry, band_name: str = "NDVI"
) -> float:
    """対象バンドの有効ピクセル比（%）を算出する。

    Args:
        image (ee.Image): 指標バンドを含む画像。
        roi (ee.Geometry): 集計対象領域。
        band_name (str): 有効率判定に使用するバンド名。既定値はNDVI。

    Returns:
        float: 有効ピクセル比（0-100）。
    """
    band = image.select(band_name)

    total_pixels = ee.Number(
        band.unmask()
        .reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=roi,
            scale=30,
            maxPixels=1e9,
        )
        .get(band_name)
    )
    valid_pixels = ee.Number(
        band.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=roi,
            scale=30,
            maxPixels=1e9,
        ).get(band_name)
    )

    total = float(total_pixels.getInfo() or 0)
    valid = float(valid_pixels.getInfo() or 0)
    if total == 0:
        return 0.0

    return (valid / total) * 100.0


def calculate_index_stats(
    image: ee.Image, roi: ee.Geometry, band_names: list[str]
) -> dict[str, float]:
    """指定した指標の平均・最小・最大・標準偏差を取得する。

    Args:
        image (ee.Image): 指標バンドを含む画像。
        roi (ee.Geometry): 統計量の計算領域。
        band_names (list[str]): 統計対象のバンド名一覧。

    Returns:
        dict[str, float]: 各バンドの mean/min/max/std を格納した辞書。
    """
    stats: dict[str, float] = {}

    for band in band_names:
        reduced = image.select(band).reduceRegion(
            reducer=ee.Reducer.mean()
            .combine(ee.Reducer.min(), sharedInputs=True)
            .combine(ee.Reducer.max(), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
            geometry=roi,
            scale=30,
            maxPixels=1e9,
        )

        mean_value = reduced.get(f"{band}_mean").getInfo()
        min_value = reduced.get(f"{band}_min").getInfo()
        max_value = reduced.get(f"{band}_max").getInfo()
        std_value = reduced.get(f"{band}_stdDev").getInfo()

        stats[f"{band.lower()}_mean"] = to_float_or_nan(mean_value)
        stats[f"{band.lower()}_min"] = to_float_or_nan(min_value)
        stats[f"{band.lower()}_max"] = to_float_or_nan(max_value)
        stats[f"{band.lower()}_std"] = to_float_or_nan(std_value)

    return stats


def build_indices_drive_export_folder(config: dict[str, Any], date_text: str) -> str:
    """LST基準のフォルダ名規則を踏襲し、INDICES用へ変換する。

    Args:
        config (dict[str, Any]): 設定CSVから読み込んだ設定辞書。
        date_text (str): 対象日付（YYYY-MM-DD）。

    Returns:
        str: Google Driveの出力先フォルダ名。
    """
    lst_folder = build_drive_export_folder(config, date_text)

    if "LST" in lst_folder.upper():
        return lst_folder.replace("LST", "INDICES")

    if lst_folder.upper().endswith("_INDICES"):
        return lst_folder

    return f"{lst_folder}_INDICES"


def export_indices_to_drive(
    image: ee.Image,
    roi: ee.Geometry,
    output_epsg: int,
    folder_name: str,
    description: str,
    observation_datetime_utc: str,
    band_names: list[str],
    scale_m: int = 30,
) -> None:
    """指定バンドをGoogle DriveへGeoTIFF出力する。

    Args:
        image (ee.Image): エクスポート対象画像。
        roi (ee.Geometry): エクスポート領域。
        output_epsg (int): 出力座標系EPSGコード。
        folder_name (str): Google Driveの出力先フォルダ名。
        description (str): GEEタスク名と出力ファイル接頭辞。
        band_names (list[str]): 出力対象バンド一覧。
        scale_m (int): 出力解像度（メートル）。既定値30。

    Returns:
        None: GEEの非同期エクスポートタスクを起動する。
    """
    image_with_metadata = (
        image.clip(roi)
        .select(band_names)
        .set({"observation_datetime_utc": observation_datetime_utc})
    )

    task = ee.batch.Export.image.toDrive(
        image=image_with_metadata,
        description=description,
        folder=folder_name,
        fileNamePrefix=description,
        region=roi,
        scale=scale_m,
        crs=f"EPSG:{output_epsg}",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
    )
    task.start()
    logger.info("Export task started: %s -> %s", description, folder_name)


def process_image(
    image: ee.Image,
    roi: ee.Geometry,
    config: dict[str, Any],
    band_names: list[str],
    sensor: str = DEFAULT_SENSOR,
) -> dict[str, Any]:
    """1画像分の統計計算とエクスポート判定を行う。

    Args:
        image (ee.Image): 処理対象の1シーン画像。
        roi (ee.Geometry): 集計・出力対象の領域。
        config (dict[str, Any]): 設定CSVから読み込んだ設定辞書。
        band_names (list[str]): 指標算出と出力に使用するバンド一覧。
        sensor (str): 画像の取得元センサ名（"L8" / "L9"）。出力名と結果の列に用いる。

    Returns:
        dict[str, Any]: 日付、センサ、雲量、有効率、統計量、エクスポート可否を含む結果辞書。
    """
    observation_datetime_utc = (
        ee.Date(image.get("system:time_start")).format("YYYY-MM-dd'T'HH:mm:ss").getInfo()
    )
    date_text = observation_datetime_utc[:10]

    cloud_cover = image.get("CLOUD_COVER")
    cloud_cover_info = cloud_cover.getInfo() if cloud_cover is not None else None
    cloud_cover_value = to_float_or_nan(cloud_cover_info)

    valid_ratio = calculate_valid_pixel_ratio(image, roi, band_name="NDVI")
    stats = calculate_index_stats(image, roi, band_names=band_names)

    output_epsg = int(config.get("output_epsg", 4326))
    valid_threshold = float(config.get("valid_pixel_threshold", 50))
    drive_folder = build_indices_drive_export_folder(config, date_text)

    exported = False
    if valid_ratio >= valid_threshold:
        description = build_export_description("INDICES", observation_datetime_utc, sensor)
        export_indices_to_drive(
            image=image,
            roi=roi,
            output_epsg=output_epsg,
            folder_name=drive_folder,
            description=description,
            observation_datetime_utc=observation_datetime_utc,
            band_names=band_names,
            scale_m=30,
        )
        exported = True

    result = {
        "date": date_text,
        "observation_datetime_utc": observation_datetime_utc,
        "satellite": get_sensor_label(sensor),
        "cloud_cover": cloud_cover_value,
        "valid_pixel_ratio": valid_ratio,
        "exported": exported,
        "drive_folder": drive_folder,
    }
    result.update(stats)
    return result


def process_sensor(
    sensor: str,
    roi: ee.Geometry,
    config: dict[str, Any],
    band_names: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """1センサ分のSRコレクションを取得し、各画像の指標統計を算出する。

    Args:
        sensor (str): センサ名（"L8" / "L9"）。
        roi (ee.Geometry): 集計・出力対象の領域。
        config (dict[str, Any]): 設定CSVから読み込んだ設定辞書（start_date / end_date を含む）。
        band_names (list[str]): 指標算出と出力に使用するバンド一覧。

    Returns:
        tuple[list[dict[str, Any]], int]: (結果辞書のリスト, コレクションの画像数)。
            処理に失敗した画像は結果に含めずログに記録する。
    """
    collection = get_landsat_sr_collection(
        start_date=config["start_date"],
        end_date=config["end_date"],
        roi=roi,
        sensor=sensor,
    )
    image_count = int(collection.size().getInfo())
    if image_count == 0:
        logger.warning("対象画像が0件です（%s）。", get_sensor_label(sensor))
        return [], 0

    image_list = collection.toList(image_count)
    results: list[dict[str, Any]] = []

    for index in tqdm(range(image_count), desc=f"衛星指標を処理中（{get_sensor_label(sensor)}）"):
        image = ee.Image(image_list.get(index))
        try:
            results.append(process_image(image, roi, config, band_names=band_names, sensor=sensor))
        except Exception as error:
            logger.error(
                "画像処理中にエラーが発生しました（%s, index=%s）: %s",
                get_sensor_label(sensor),
                index,
                error,
            )

    return results, image_count


def run(
    config_path: Path = DEFAULT_CONFIG_PATH, output_csv_path: Path = DEFAULT_OUTPUT_CSV
) -> None:
    """衛星指標算出処理を実行する。

    Args:
        config_path (Path): 設定CSVファイルのパス。
        output_csv_path (Path): 結果CSVの出力パス。

    Returns:
        None: 指標算出、統計集計、必要時のDrive出力を実行する。
    """
    config = load_config(str(config_path))

    gee_project_id = config.get("gee_project_id")
    if not gee_project_id or gee_project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError("GCPプロジェクトIDが設定されていません。設定CSVを確認してください。")

    band_names = get_target_band_names()
    logger.info("算出対象バンド: %s", ", ".join(band_names))

    authenticate_gee(project_id=gee_project_id)

    roi_path_text = str(config.get("roi_shapefile_path") or "").strip()
    if not roi_path_text:
        raise ValueError("設定CSVに roi_shapefile_path がありません。")

    roi = load_roi_from_shapefile(roi_path_text)

    start_date = config.get("start_date")
    end_date = config.get("end_date")
    if not start_date or not end_date:
        raise ValueError("設定CSVに start_date / end_date が必要です。")

    sensors = parse_sensors(config.get("sensors"))
    logger.info("処理対象のセンサ: %s", ", ".join(sensors))

    results: list[dict[str, Any]] = []
    total_image_count = 0
    for sensor in sensors:
        sensor_results, sensor_image_count = process_sensor(sensor, roi, config, band_names)
        results.extend(sensor_results)
        total_image_count += sensor_image_count

    if total_image_count == 0:
        logger.warning("対象画像が0件のため処理を終了します。")
        return

    if not results:
        logger.warning("有効な処理結果が無いためCSV出力をスキップします。")
        return

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    result_df = pd.DataFrame(results)
    # 複数センサの結果を観測日時順に並べる（同日内の順序も一意に定める）
    result_df = result_df.sort_values("observation_datetime_utc", kind="stable").reset_index(
        drop=True
    )
    result_df.to_csv(output_csv_path, index=False, encoding="utf-8")

    exported_count = int(result_df["exported"].sum())
    logger.info("処理完了: %s 件", len(result_df))
    logger.info("エクスポート対象件数: %s 件", exported_count)
    logger.info("結果CSV: %s", output_csv_path)


def main() -> None:
    """エントリーポイント。

    Returns:
        None: run関数を実行する。
    """
    run()


if __name__ == "__main__":
    main()
