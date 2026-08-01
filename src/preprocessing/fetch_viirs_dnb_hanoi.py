"""VIIRS DNB 年次コンポジットから Hanoi ROI の夜間光を取得する。

データソース（Google Earth Engine 経由）:
- VIIRS Nighttime Day/Night Band Annual Composites V2.2: `NOAA/VIIRS/DNB/ANNUAL_V22`
- 同 V2.1（2013-2021 年）: `NOAA/VIIRS/DNB/ANNUAL_V21`
  （いずれも NOAA/NCEI、処理は Colorado School of Mines の Earth Observation Group）

ライセンス: パブリックドメイン。出典表記は Earth Observation Group（Colorado School of
Mines）に対して行う。

制約メモ（2026-07-27 確認）:
- **GEE のアセット ID はカタログページのスラッグと異なる**。カタログ URL は
  `NOAA_VIIRS_DNB_ANNUAL_V22` だが、実アセット ID は `NOAA/VIIRS/DNB/ANNUAL_V22`
  （`DNB` の後がスラッシュ）。前者を指定すると `not found` になる。
- 提供年は V2.2 が 2022-2025 年（4枚）、V2.1 が 2013-2021 年（9枚）。本研究の Landsat
  観測年（2023年）は V2.2 に含まれるため、年次コンポジットを直接取得できる。
- 画像の `system:index` は年初日（例 2023 年 → `20230101`）。
- ネイティブグリッドは EPSG:4326・約 463.83m（15 arc-sec）。原点は
  `-180.00208333335 / 75.00208333335` で、**整数度から半画素ずれる**。他データセットと
  画素単位で突き合わせる際は再投影が要る。
- ダウンロードは `scale` ではなくネイティブの `crs` / `crs_transform` を指定して行う
  （再投影のリサンプリングで放射輝度がならされるのを避けるため）。
- GEE の GeoTIFF 出力はマスク画素を 0 で書き出すため、「夜間光 0 の場所」と「データ無し」が
  区別できなくなる。ダウンロード前に `unmask(-9999)` して両者を分離する。
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd
import numpy as np

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT, WGS84_CRS
from src.common.gee import authenticate_gee, load_gee_project_id
from src.common.gee_raster import build_native_download_url, download_gee_raster
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.raster_area import (
    DEFAULT_RASTER_NODATA,
    build_target_area,
    clip_multiband_to_area,
)
from src.common.raster_stats import build_multiband_pixel_statistics
from src.common.summary import save_summary

DEFAULT_GEE_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "gis" / "nighttime_lights" / "viirs_dnb"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

REQUEST_TIMEOUT_SECONDS = 300
OUTPUT_NODATA = DEFAULT_RASTER_NODATA
# 本研究の Landsat 観測年。既定の取得年であり、時間差の判定にも使う。
LANDSAT_OBSERVATION_YEAR = 2023

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnualCollectionConfig:
    """VIIRS DNB 年次コンポジットのバージョン別設定を保持する。"""

    version_key: str
    dataset_name: str
    gee_asset_id: str
    first_year: int
    last_year: int
    source_url: str


@dataclass(frozen=True)
class BandDefinition:
    """出力 GeoTIFF の 1 バンド分の定義。"""

    source_name: str
    output_name: str
    unit: str
    description: str
    # 飽和評価の対象とするか（放射輝度バンドのみ True）
    is_saturation_target: bool


# 新しい年ほど先に並べる（`resolve_collection` は先頭から順に該当を探すため、
# 重複年があった場合に新しいバージョンが選ばれる）
COLLECTION_CONFIGS: tuple[AnnualCollectionConfig, ...] = (
    AnnualCollectionConfig(
        version_key="v22",
        dataset_name="VIIRS Nighttime Day/Night Band Annual Composites V2.2",
        gee_asset_id="NOAA/VIIRS/DNB/ANNUAL_V22",
        first_year=2022,
        last_year=2025,
        source_url=(
            "https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_ANNUAL_V22"
        ),
    ),
    AnnualCollectionConfig(
        version_key="v21",
        dataset_name="VIIRS Nighttime Day/Night Band Annual Composites V2.1",
        gee_asset_id="NOAA/VIIRS/DNB/ANNUAL_V21",
        first_year=2013,
        last_year=2021,
        source_url=(
            "https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_ANNUAL_V21"
        ),
    ),
)

RADIANCE_UNIT = "nW·cm⁻²·sr⁻¹"

# データ被覆率を代表させるバンド。マスク処理を経ておらず、ROI 全域に値があるはずのもの。
PRIMARY_BAND_NAME = "avg_radiance"

# 出力バンドの並び（1始まりのバンド番号に対応）
BAND_DEFINITIONS: tuple[BandDefinition, ...] = (
    BandDefinition(
        source_name="average",
        output_name="avg_radiance",
        unit=RADIANCE_UNIT,
        description="年次平均放射輝度（背景・生物発光を除去していない生の合成値）",
        is_saturation_target=True,
    ),
    BandDefinition(
        source_name="average_masked",
        output_name="avg_radiance_masked",
        unit=RADIANCE_UNIT,
        description=(
            "年次平均放射輝度から背景（生物発光・その他の非電力光源）を除いた値。"
            "背景と判定された画素の扱いは配布データ側に依存し、0 で現れる場合と"
            "マスク（nodata）で現れる場合がある"
        ),
        is_saturation_target=True,
    ),
    BandDefinition(
        source_name="cf_cvg",
        output_name="cf_cvg",
        unit="観測回数",
        description="合成に用いた雲なし観測の回数。少ない画素は平均値の信頼度が低い",
        is_saturation_target=False,
    ),
    BandDefinition(
        source_name="maximum",
        output_name="max_radiance",
        unit=RADIANCE_UNIT,
        description="年次の最大放射輝度。都市中心部の飽和状況の確認に用いる",
        is_saturation_target=True,
    ),
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="VIIRS DNB 年次コンポジットから Hanoi ROI の夜間光を取得する。"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=LANDSAT_OBSERVATION_YEAR,
        help=(
            "取得対象年。バージョンは年から自動で決まる（2022年以降は V2.2、2013-2021年は V2.1）。"
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
        help="出力 GeoTIFF パス。未指定時は data/gis/nighttime_lights/viirs_dnb/ 配下へ保存する。",
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


def resolve_collection(year: int) -> AnnualCollectionConfig:
    """取得対象年に対応する年次コンポジットのバージョンを決める。

    Args:
        year: 取得対象年。

    Returns:
        該当するバージョンの設定。

    Raises:
        ValueError: どのバージョンにも該当年が無い場合。
    """
    for collection_config in COLLECTION_CONFIGS:
        if collection_config.first_year <= year <= collection_config.last_year:
            return collection_config

    available = "、".join(
        f"{config.version_key.upper()}: {config.first_year}-{config.last_year}"
        for config in COLLECTION_CONFIGS
    )
    # 対応年は定数で持っているため、データセット側に新しい年が追加されても自動では
    # 追従しない。「データセットに存在しない」ではなく「本スクリプトが対応していない」
    # と述べ、更新箇所を示す
    raise ValueError(
        f"本スクリプトが対応する VIIRS DNB 年次コンポジットに {year} 年は含まれません"
        f"（対応年 — {available}）。"
        "データセット側に新しい年が追加されている場合は COLLECTION_CONFIGS の"
        "last_year を更新してください。"
    )


def resolve_output_paths(
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
    is_trial: bool = False,
) -> tuple[Path, Path]:
    """出力 GeoTIFF とサマリー JSON の保存先を解決する。

    試行実行（BBOX 指定）で出力パスが未指定の場合は、既定ファイル名に `_trial` を
    付ける。ROI 全域の成果物を、範囲の狭い試行結果で上書きしてしまうのを防ぐため。

    Args:
        year: 取得対象年。
        output_path: 指定された出力パス。
        summary_path: 指定されたサマリーパス。
        is_trial: 試行実行かどうか。

    Returns:
        (出力 GeoTIFF パス, サマリー JSON パス)。
    """
    trial_suffix = "_trial" if is_trial else ""
    output_stem = f"viirs_dnb_hanoi_{year}{trial_suffix}"
    resolved_output_path = output_path or (DEFAULT_OUTPUT_ROOT / f"{output_stem}.tif")
    resolved_summary_path = summary_path or (
        DEFAULT_SUMMARY_DIR / f"nighttime_lights_{output_stem}_summary.json"
    )
    return (
        prepare_output_path(resolved_output_path),
        prepare_output_path(resolved_summary_path),
    )


def select_annual_image(collection_config: AnnualCollectionConfig, year: int) -> ee.Image:
    """対象年の年次コンポジット画像を 1 枚に特定する。

    年次コンポジットの `system:index` は年初日（例 2023 年 → `20230101`）である。

    Args:
        collection_config: 年次コンポジットのバージョン設定。
        year: 取得対象年。

    Returns:
        必要バンドのみを選び、出力バンド名へ改名した画像。

    Raises:
        RuntimeError: 該当画像が 1 枚に定まらない場合。
    """
    image_index = f"{year}0101"
    collection = ee.ImageCollection(collection_config.gee_asset_id).filter(
        ee.Filter.eq("system:index", image_index)
    )

    matched_count = int(collection.size().getInfo())
    if matched_count != 1:
        raise RuntimeError(
            f"{collection_config.dataset_name} で対象画像が 1 枚に定まりません"
            f"（条件: system:index == {image_index!r}、該当: {matched_count} 枚）。"
        )

    source_names = [band.source_name for band in BAND_DEFINITIONS]
    output_names = [band.output_name for band in BAND_DEFINITIONS]
    return ee.Image(collection.first()).select(source_names, output_names)


def build_pixel_statistics(
    band_arrays: dict[str, np.ndarray],
    area_mask: np.ndarray,
    covers_area: bool,
) -> dict[str, Any]:
    """出力ラスタの画素統計と飽和指標を集計する。

    集計そのものは共通処理へ委ね、本関数は「どのバンドが被覆を代表するか」「どの
    バンドに飽和指標を付けるか」というデータセット固有の指定だけを担う。

    `avg_radiance_masked` は背景（生物発光等）を除いたバンドで、背景と判定された
    画素の扱いは配布データ側に依存する（0 で現れる場合と nodata で現れる場合がある）。
    後者のとき有効画素が減るが、それは「データが取れていない」のではなく「電力由来の
    光が検出されなかった」ことを意味する。そのため有効画素はバンドごとに数え、
    被覆率は背景除去前の主バンドで代表させる。

    Args:
        band_arrays: 出力バンド名 -> 2 次元配列。
        area_mask: 対象範囲内を True とする 2 次元マスク。
        covers_area: 出力が要求範囲を覆えているか。

    Returns:
        画素数・バンド別統計・飽和指標を含む辞書。
    """
    return build_multiband_pixel_statistics(
        band_arrays=band_arrays,
        area_mask=area_mask,
        covers_area=covers_area,
        primary_band=PRIMARY_BAND_NAME,
        nodata=OUTPUT_NODATA,
        saturation_bands=[
            band.output_name for band in BAND_DEFINITIONS if band.is_saturation_target
        ],
    )


def clip_and_write(
    source_path: Path,
    area_gdf: gpd.GeoDataFrame,
    output_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """ダウンロードしたラスタを対象範囲でクリップし、複数バンド GeoTIFF として保存する。

    Args:
        source_path: ダウンロードした GeoTIFF パス。
        area_gdf: 取得対象範囲（EPSG:4326）。
        output_path: 出力 GeoTIFF パス。

    Returns:
        (出力ラスタの諸元, 画素統計)。

    Raises:
        ValueError: ソースラスタの CRS が未定義の場合、
            またはバンド数が想定と異なる場合（バンド名の割り当てがずれるため）。
    """
    clip_result = clip_multiband_to_area(
        source_path=source_path,
        area_gdf=area_gdf,
        output_path=output_path,
        band_names=[band.output_name for band in BAND_DEFINITIONS],
        nodata=OUTPUT_NODATA,
    )
    pixel_stats = build_pixel_statistics(
        band_arrays=clip_result.band_arrays,
        area_mask=clip_result.area_mask,
        covers_area=clip_result.covers_area,
    )
    return clip_result.raster_profile, pixel_stats


def build_summary(
    collection_config: AnnualCollectionConfig,
    year: int,
    roi_path: Path,
    is_trial: bool,
    area_bounds: tuple[float, float, float, float],
    projection_info: dict[str, Any],
    raster_profile: dict[str, Any],
    pixel_stats: dict[str, Any],
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    Args:
        collection_config: 年次コンポジットのバージョン設定。
        year: 取得対象年。
        roi_path: ROI ファイルパス。
        is_trial: 試行実行（BBOX 指定）かどうか。
        area_bounds: 取得対象範囲の BBOX。
        projection_info: GEE のネイティブ投影情報。
        raster_profile: 出力ラスタの諸元。
        pixel_stats: 画素統計。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        retrieved_at: 取得日時（ISO8601）。

    Returns:
        サマリー辞書。
    """
    year_note = (
        f"{collection_config.dataset_name} の提供年は "
        f"{collection_config.first_year}-{collection_config.last_year} 年。"
    )
    if year == LANDSAT_OBSERVATION_YEAR:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）と一致しており、時間差はない。"
        )
    else:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）との間に "
            f"{abs(LANDSAT_OBSERVATION_YEAR - year)} 年の時間差がある。"
        )

    return {
        "dataset": collection_config.dataset_name,
        "dataset_key": f"viirs_dnb_{collection_config.version_key}",
        "gee_asset_id": collection_config.gee_asset_id,
        "source": collection_config.source_url,
        "license": "パブリックドメイン",
        "license_note": (
            "出典表記は Earth Observation Group（Colorado School of Mines）に対して行う。"
        ),
        "retrieved_at": retrieved_at,
        "year": year,
        "year_note": year_note,
        "native_projection": {
            "crs": projection_info.get("crs"),
            "transform": projection_info.get("transform"),
        },
        "resampling_note": (
            "ネイティブの crs / crs_transform を指定して取得しており、リサンプリングは"
            "行っていない。グリッド原点は整数度から半画素ずれるため、他データセットと"
            "画素単位で突き合わせる際は再投影が要る。"
        ),
        "roi_path": to_project_relative_string(roi_path),
        "is_trial_run": is_trial,
        "area_bbox": list(area_bounds),
        # サマリーJSONの標準項目として最上位に置く。実体は raster_profile 側が正で、
        # ここはファイルから読み直した値をそのまま写している
        "crs": raster_profile["crs"],
        "raster_profile": raster_profile,
        "bands": {
            str(index): {
                "name": band.output_name,
                "source_band": band.source_name,
                "unit": band.unit,
                "description": band.description,
            }
            for index, band in enumerate(BAND_DEFINITIONS, start=1)
        },
        "pixel_stats": pixel_stats,
        "saturation_note": (
            "飽和指標は放射輝度バンドについてのみ算出している。p99_to_max_ratio が 1 に"
            "近く、かつ ratio_near_max が無視できない大きさであれば、上位の値が"
            "最大値へ張り付いている（飽和が疑われる）。逆に最大値が少数画素にしか現れず"
            "p99 との差が大きい場合、値域内で階調が保たれていると解釈できる。"
        ),
        "coverage_note": (
            "ROI ポリゴンで真にクリップしているため出力は BBOX 矩形となり、ROI 外の余白は "
            f"nodata（{OUTPUT_NODATA}）で埋まる。valid_pixel_ratio の分母 roi_pixels は"
            "**クリップ後の出力に含まれる ROI 内画素**であり、ROI 全体ではない。"
            "有効画素はバンドごとに別々に数えており、最上位の valid_pixels / "
            f"valid_pixel_ratio はデータ被覆の指標として主バンド {PRIMARY_BAND_NAME} で"
            "代表させている。バンドごとの valid_pixels が主バンドより少ない場合、"
            "それはデータ欠測とは限らず、元データ側のマスク（背景判定など）による"
            "こともあるため、バンドの意味に照らして解釈する必要がある。"
            "データソースが ROI を覆いきれていない場合は covers_requested_area で別に判定する。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
    }


def run(
    year: int,
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
        year: 取得対象年。
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
    collection_config = resolve_collection(year)
    # 出力先の決定に試行実行かどうかが要るため、ROI の読み込みを先に行う
    area_gdf, is_trial, resolved_roi_path = build_target_area(roi_path=roi_path, bbox=bbox)
    area_bounds = tuple(float(value) for value in area_gdf.total_bounds)
    logger.info("取得対象範囲の BBOX: %s", area_bounds)

    resolved_output_path, resolved_summary_path = resolve_output_paths(
        year=year,
        output_path=output_path,
        summary_path=summary_path,
        is_trial=is_trial,
    )
    # GeoTIFF とサマリー JSON は対で更新するため、どちらか一方でも既存なら止める
    for existing_path in (resolved_output_path, resolved_summary_path):
        if existing_path.exists() and not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します: {existing_path}。"
                "上書きする場合は --overwrite を指定してください。"
            )

    project_id = load_gee_project_id(config_path=config_path, explicit_project_id=gee_project_id)
    authenticate_gee(project_id)

    annual_image = select_annual_image(collection_config, year)
    region_geojson = area_gdf.geometry.union_all().__geo_interface__
    download_url, projection_info = build_native_download_url(
        image=annual_image, region_geojson=region_geojson, nodata=OUTPUT_NODATA
    )
    logger.info(
        "ネイティブ投影で取得します（%s, crs=%s, transform=%s）",
        collection_config.gee_asset_id,
        projection_info.get("crs"),
        projection_info.get("transform"),
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="viirs_dnb_download_") as temporary_dir:
        downloaded_path = Path(temporary_dir) / f"viirs_dnb_{year}_raw.tif"
        download_gee_raster(download_url, downloaded_path, timeout=REQUEST_TIMEOUT_SECONDS)
        raster_profile, pixel_stats = clip_and_write(
            source_path=downloaded_path,
            area_gdf=area_gdf,
            output_path=resolved_output_path,
        )

    if raster_profile["crs"] != WGS84_CRS:
        logger.warning("出力 CRS が %s ではありません: %s", WGS84_CRS, raster_profile["crs"])

    summary = build_summary(
        collection_config=collection_config,
        year=year,
        roi_path=resolved_roi_path,
        is_trial=is_trial,
        area_bounds=area_bounds,
        projection_info=projection_info,
        raster_profile=raster_profile,
        pixel_stats=pixel_stats,
        output_path=resolved_output_path,
        summary_path=resolved_summary_path,
        retrieved_at=retrieved_at,
    )
    save_summary(summary, resolved_summary_path)

    log_results(pixel_stats)
    return resolved_output_path, resolved_summary_path


def log_results(pixel_stats: dict[str, Any]) -> None:
    """取得結果の要点をログへ出力する。

    Args:
        pixel_stats: 画素統計。
    """
    logger.info(
        "有効画素率: %.4f（有効 %d / 範囲内 %d、ラスタ全体 %d）",
        pixel_stats["valid_pixel_ratio"],
        pixel_stats["valid_pixels"],
        pixel_stats["roi_pixels"],
        pixel_stats["total_pixels"],
    )
    for band in BAND_DEFINITIONS:
        band_stats = pixel_stats[band.output_name]
        if "min" not in band_stats:
            logger.warning("バンド %s に有効画素がありません。", band.output_name)
            continue
        logger.info(
            "%s（%s）: 有効 %d 画素（%.4f） min=%.3f median=%.3f p95=%.3f p99=%.3f max=%.3f",
            band.output_name,
            band.unit,
            band_stats["valid_pixels"],
            band_stats["valid_pixel_ratio"],
            band_stats["min"],
            band_stats["median"],
            band_stats["p95"],
            band_stats["p99"],
            band_stats["max"],
        )

    for band_name, indicators in pixel_stats["saturation"].items():
        if indicators is None:
            continue
        ratio_text = (
            "算出不可"
            if indicators["p99_to_max_ratio"] is None
            else f"{indicators['p99_to_max_ratio']:.3f}"
        )
        # 近傍幅は可変なので、文言に固定値を埋め込まず実際の設定値から組み立てる
        neighborhood_percent = indicators["neighborhood_ratio"] * 100
        logger.info(
            "飽和指標 %s: p99/max=%s、最大値と同値 %d 画素、最大値の%.3g%%以内 %d 画素（%.4f）",
            band_name,
            ratio_text,
            indicators["pixels_at_max"],
            neighborhood_percent,
            indicators["pixels_near_max"],
            indicators["ratio_near_max"],
        )

    if pixel_stats["valid_pixel_ratio"] < 1.0:
        logger.warning(
            "範囲内に主バンド %s の無効画素があります（有効率 %.4f）。"
            "データ提供範囲の限界を確認してください。",
            PRIMARY_BAND_NAME,
            pixel_stats["valid_pixel_ratio"],
        )
    if not pixel_stats["covers_requested_area"]:
        # 覆えていない領域は出力にも有効率の分母にも現れないため、別途警告する
        logger.warning(
            "出力が要求範囲を覆いきれていません。有効率は覆えた範囲内でしか評価されていない"
            "ため、データソースの提供範囲を確認してください。"
        )


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_path, summary_path = run(
        year=args.year,
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
