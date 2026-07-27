"""WorldPop / LandScan Global から Hanoi ROI の人口分布を取得する。

データソース（いずれも Google Earth Engine 経由）:
- WorldPop Global Project Population Data: `WorldPop/GP/100m/pop`
  （University of Southampton、国勢調査を Random Forest で空間按分した居住人口）
- LandScan Global: `projects/sat-io/open-datasets/ORNL/LANDSCAN_GLOBAL`
  （Oak Ridge National Laboratory、昼夜間の人口移動を考慮した実効人口）

ライセンス: いずれも CC BY 4.0。LandScan は GEE コミュニティカタログ
（Awesome GEE Community Catalog）がホストする複製であり、ORNL 公式配布物との
ビット単位一致は保証されない。出典表記は ORNL に対して行う。

制約メモ（2026-07-26 確認）:
- **WorldPop のベトナム（country=VNM）は 2000-2020 年しか存在しない**。本研究の Landsat
  観測年（2023年）に対応する年次が無いため、既定は取得可能な最新年の 2020 年とする。
  LandScan は 2000-2024 年があり 2023 年を直接取得できる。
- **両データセットとも配布値は「密度」ではなく「セルあたりの人口カウント（人／セル）」**。
  本スクリプトはカウントをそのまま第1バンドに保持し、第2バンドに人口密度（人/km²）を
  導出して 2 バンドの GeoTIFF として出力する。EPSG:4326 のセル面積は緯度により変わるため、
  密度は行ごとに WGS84 楕円体上の実面積を求めて算出する（定数で割らない）。
- ダウンロードは各画像の**ネイティブグリッド**（`projection()` の crs / transform）を
  指定して行う。`scale` 指定だと再投影のリサンプリングでカウントの総和が保存されないため。
  WorldPop は約 92.77m、LandScan は約 927.66m（いずれも EPSG:4326）。
- GEE の GeoTIFF 出力はマスク画素を 0 で書き出すため、「人口 0 の場所」と「データ無し」が
  区別できなくなる。ダウンロード前に `unmask(-9999)` して両者を分離する。
"""

from __future__ import annotations

import argparse
import io
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import array_bounds
from shapely.geometry import box

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT, WGS84_CRS
from src.common.gee import authenticate_gee, load_gee_project_id
from src.common.http_fetch import fetch_bytes_with_retry
from src.common.paths import (
    prepare_output_path,
    resolve_existing_path,
    to_project_relative_string,
)
from src.common.raster_grid import compute_cell_area_km2, compute_density_array
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary

DEFAULT_GEE_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "gis" / "population"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

REQUEST_TIMEOUT_SECONDS = 300
# 出力 GeoTIFF の nodata。DEM 取得スクリプトと同じ値に揃える。
OUTPUT_NODATA = -9999.0
# 出力バンドの並び（1始まりのバンド番号に対応）
BAND_COUNT_NAME = "population_count"
BAND_DENSITY_NAME = "population_density_per_km2"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PopulationDatasetConfig:
    """人口データセットの取得設定を保持する。"""

    dataset_key: str
    dataset_name: str
    gee_asset_id: str
    band_name: str
    source_url: str
    license_name: str
    license_note: str
    population_concept: str
    first_year: int
    last_year: int
    default_year: int
    native_scale_m: float
    output_subdir: str
    output_prefix: str
    # WorldPop は country / year プロパティで、LandScan は system:index で年次を選ぶ
    country_code: str = ""
    index_template: str = ""


DATASET_CONFIGS: dict[str, PopulationDatasetConfig] = {
    "worldpop": PopulationDatasetConfig(
        dataset_key="worldpop",
        dataset_name="WorldPop Global Project Population Data (100m)",
        gee_asset_id="WorldPop/GP/100m/pop",
        band_name="population",
        source_url=(
            "https://developers.google.com/earth-engine/datasets/catalog/WorldPop_GP_100m_pop"
        ),
        license_name="CC BY 4.0",
        license_note="出典表記は WorldPop（University of Southampton）に対して行う。",
        population_concept=(
            "居住人口（夜間人口）。2019年ベトナム国勢調査を基準に、各年のUNPD推計へ"
            "合わせて Random Forest により空間按分した推計値。"
        ),
        first_year=2000,
        last_year=2020,
        default_year=2020,
        native_scale_m=92.7662419568716,
        output_subdir="worldpop",
        output_prefix="worldpop_hanoi",
        country_code="VNM",
    ),
    "landscan": PopulationDatasetConfig(
        dataset_key="landscan",
        dataset_name="LandScan Global (1km)",
        gee_asset_id="projects/sat-io/open-datasets/ORNL/LANDSCAN_GLOBAL",
        band_name="b1",
        source_url="https://gee-community-catalog.org/projects/landscan/",
        license_name="CC BY 4.0",
        license_note=(
            "出典表記は ORNL（Oak Ridge National Laboratory）に対して行う。"
            "GEE コミュニティカタログがホストする複製のため、"
            "ORNL 公式配布物とのビット単位一致は保証されない。"
        ),
        population_concept=(
            "実効人口（アンビエント人口）。通勤・通学等の昼間の人口移動を考慮した"
            "「その時間帯に実際にそこにいる人口」を多変量dasymetricモデルと"
            "専門家による手動補正で推計した値。"
        ),
        first_year=2000,
        last_year=2024,
        default_year=2023,
        native_scale_m=927.6624232401731,
        output_subdir="landscan",
        output_prefix="landscan_hanoi",
        index_template="landscan-global-{year}",
    ),
}


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="WorldPop / LandScan Global から Hanoi ROI の人口分布を取得する。"
    )
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASET_CONFIGS.keys()),
        default="worldpop",
        help="取得対象の人口データセット。",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="取得対象年。未指定時はデータセットごとの既定年（worldpop: 2020 / landscan: 2023）。",
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
        help="出力 GeoTIFF パス。未指定時は data/gis/population/ 配下へ保存する。",
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


def resolve_year(dataset_config: PopulationDatasetConfig, year: int | None) -> int:
    """取得対象年を解決し、データセットの提供年内かを検証する。

    Args:
        dataset_config (PopulationDatasetConfig): データセット設定。
        year (int | None): 指定された年。None なら既定年を使う。

    Returns:
        int: 解決済みの取得対象年。

    Raises:
        ValueError: 指定年がデータセットの提供年の範囲外の場合。
    """
    resolved_year = dataset_config.default_year if year is None else year
    if not dataset_config.first_year <= resolved_year <= dataset_config.last_year:
        raise ValueError(
            f"{dataset_config.dataset_name} の提供年は "
            f"{dataset_config.first_year}-{dataset_config.last_year} です"
            f"（指定: {resolved_year}）。"
        )
    return resolved_year


def resolve_output_paths(
    dataset_config: PopulationDatasetConfig,
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
    is_trial: bool = False,
) -> tuple[Path, Path]:
    """出力 GeoTIFF とサマリー JSON の保存先を解決する。

    試行実行（BBOX 指定）で出力パスが未指定の場合は、既定ファイル名に `_trial` を
    付ける。ROI 全域の成果物を、範囲の狭い試行結果で上書きしてしまうのを防ぐため。

    相対パスはプロジェクトルート基準で解決するため、実行時のカレントディレクトリに
    依存しない。

    Args:
        dataset_config (PopulationDatasetConfig): データセット設定。
        year (int): 取得対象年。
        output_path (Path | None): 指定された出力パス。
        summary_path (Path | None): 指定されたサマリーパス。
        is_trial (bool): 試行実行かどうか。

    Returns:
        tuple[Path, Path]: (出力 GeoTIFF パス, サマリー JSON パス)。
    """
    trial_suffix = "_trial" if is_trial else ""
    output_stem = f"{dataset_config.output_prefix}_{year}{trial_suffix}"
    resolved_output_path = output_path or (
        DEFAULT_OUTPUT_ROOT / dataset_config.output_subdir / f"{output_stem}.tif"
    )
    resolved_summary_path = summary_path or (
        DEFAULT_SUMMARY_DIR / f"population_{output_stem}_summary.json"
    )
    return (
        prepare_output_path(resolved_output_path),
        prepare_output_path(resolved_summary_path),
    )


def build_target_area(
    roi_path: Path,
    bbox: list[float] | None,
) -> tuple[gpd.GeoDataFrame, bool]:
    """取得対象範囲の GeoDataFrame を作る。

    `bbox` を指定した場合は試行実行用の矩形を、未指定の場合は ROI を返す。

    Args:
        roi_path (Path): ROI の Shapefile パス。
        bbox (list[float] | None): (min_lon, min_lat, max_lon, max_lat)。

    Returns:
        tuple[gpd.GeoDataFrame, bool]: (対象範囲, 試行実行かどうか)。
    """
    if bbox is None:
        # 相対パスを実行時のカレントディレクトリに依存させないため、先に解決する
        roi_gdf, _ = load_roi_geometry(resolve_existing_path(roi_path))
        return roi_gdf, False

    trial_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs=WGS84_CRS)
    logger.warning("試行実行モードです（BBOX: %s）。ROI 全域ではありません。", bbox)
    return trial_gdf, True


def select_population_image(dataset_config: PopulationDatasetConfig, year: int) -> ee.Image:
    """対象年の人口画像を 1 枚に特定する。

    WorldPop は国別×年次のコレクションのため country / year プロパティで、
    LandScan は年次1枚のコレクションのため `system:index` で絞り込む。

    Args:
        dataset_config (PopulationDatasetConfig): データセット設定。
        year (int): 取得対象年。

    Returns:
        ee.Image: 特定した画像（バンド名を `population_count` に統一済み）。

    Raises:
        RuntimeError: 該当画像が 1 枚に定まらない場合。
    """
    collection = ee.ImageCollection(dataset_config.gee_asset_id)
    if dataset_config.index_template:
        image_index = dataset_config.index_template.format(year=year)
        collection = collection.filter(ee.Filter.eq("system:index", image_index))
        criteria = f"system:index == {image_index!r}"
    else:
        collection = collection.filter(ee.Filter.eq("year", year))
        criteria = f"year == {year}"
        if dataset_config.country_code:
            collection = collection.filter(ee.Filter.eq("country", dataset_config.country_code))
            criteria += f" and country == {dataset_config.country_code!r}"

    matched_count = int(collection.size().getInfo())
    if matched_count != 1:
        raise RuntimeError(
            f"{dataset_config.dataset_name} で対象画像が 1 枚に定まりません"
            f"（条件: {criteria}、該当: {matched_count} 枚）。"
        )

    return ee.Image(collection.first()).select(dataset_config.band_name).rename(BAND_COUNT_NAME)


def build_download_url(
    population_image: ee.Image,
    region_geojson: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """ネイティブグリッドを保ったままダウンロードする URL を生成する。

    `scale` ではなく画像本来の `crs` / `crs_transform` を渡すことで再投影を避ける。
    人口カウントは合計保存量であり、リサンプリングすると ROI 内の総人口が変わるため。

    Args:
        population_image (ee.Image): 対象画像（単一バンド）。
        region_geojson (dict[str, Any]): 取得範囲の GeoJSON（EPSG:4326）。

    Returns:
        tuple[str, dict[str, Any]]: (ダウンロード URL, 使用したネイティブ投影情報)。
    """
    projection_info = population_image.projection().getInfo()
    # マスク画素を明示的な nodata に置き換える（GEE は既定で 0 を書き出すため）
    unmasked_image = population_image.toFloat().unmask(OUTPUT_NODATA)
    download_url = unmasked_image.getDownloadURL(
        {
            "crs": projection_info["crs"],
            "crs_transform": projection_info["transform"],
            "region": region_geojson,
            "format": "GEO_TIFF",
        }
    )
    return download_url, projection_info


def download_raster(download_url: str, destination_path: Path) -> Path:
    """ダウンロード URL から GeoTIFF を取得して保存する。

    GEE は単一バンドでも ZIP で返す場合があるため、ZIP なら中の GeoTIFF を取り出す。
    一時的な 5xx・接続エラーに備え、共通のリトライ付き取得を使う。

    Args:
        download_url (str): ダウンロード URL。
        destination_path (Path): 保存先パス。

    Returns:
        Path: 保存したパス。

    Raises:
        ValueError: ZIP 内に GeoTIFF が見つからない場合。
    """
    response_body = fetch_bytes_with_retry(download_url, timeout=REQUEST_TIMEOUT_SECONDS)

    buffer = io.BytesIO(response_body)
    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as archive:
            tif_members = [
                member
                for member in archive.namelist()
                if member.lower().endswith((".tif", ".tiff"))
            ]
            if not tif_members:
                raise ValueError(f"ZIP 内に GeoTIFF がありません: {archive.namelist()}")
            destination_path.write_bytes(archive.read(tif_members[0]))
        return destination_path

    destination_path.write_bytes(response_body)
    return destination_path


def covers_requested_area(
    raster_bounds: tuple[float, float, float, float],
    requested_bounds: tuple[float, float, float, float],
    pixel_size: tuple[float, float],
) -> bool:
    """出力ラスタが、要求した範囲の BBOX を覆いきれているかを判定する。

    `valid_pixel_ratio` の分母はクリップ後の窓に含まれる画素だけを数えるため、
    データソースが要求範囲を覆っていない場合でも 1.0 になりうる。覆えていない
    ぶんは出力にも分母にも現れず、欠測として検知できないためこの判定を併記する。

    Args:
        raster_bounds: 出力ラスタの (minx, miny, maxx, maxy)。
        requested_bounds: 要求範囲の (minx, miny, maxx, maxy)。同じ CRS であること。
        pixel_size: (画素幅, 画素高)。境界の丸め誤差を吸収する許容量に使う。

    Returns:
        覆いきれていれば True。
    """
    # クリップは画素境界に丸められるため、1 画素分の許容を持たせる
    tolerance_x, tolerance_y = pixel_size
    return (
        raster_bounds[0] <= requested_bounds[0] + tolerance_x
        and raster_bounds[1] <= requested_bounds[1] + tolerance_y
        and raster_bounds[2] >= requested_bounds[2] - tolerance_x
        and raster_bounds[3] >= requested_bounds[3] - tolerance_y
    )


def build_band_statistics(values: np.ndarray) -> dict[str, float] | None:
    """有効画素の記述統計を求める。

    Args:
        values (np.ndarray): 有効画素の 1 次元配列。

    Returns:
        dict[str, float] | None: 記述統計。有効画素が無い場合は None。
    """
    if values.size == 0:
        return None
    # float32 のまま累算すると平均・標準偏差が丸め誤差を拾うため float64 で集計する
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values, dtype=np.float64)),
        "std": float(np.std(values, dtype=np.float64)),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }


def build_summary(
    dataset_config: PopulationDatasetConfig,
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
        dataset_config (PopulationDatasetConfig): データセット設定。
        year (int): 取得対象年。
        roi_path (Path): ROI ファイルパス。
        is_trial (bool): 試行実行（BBOX 指定）かどうか。
        area_bounds (tuple[float, float, float, float]): 取得対象範囲の BBOX。
        projection_info (dict[str, Any]): GEE のネイティブ投影情報。
        raster_profile (dict[str, Any]): 出力ラスタの諸元。
        pixel_stats (dict[str, Any]): 画素統計。
        output_path (Path): 出力 GeoTIFF パス。
        summary_path (Path): サマリー JSON パス。
        retrieved_at (str): 取得日時（ISO8601）。

    Returns:
        dict[str, Any]: サマリー辞書。
    """
    year_note = (
        f"{dataset_config.dataset_name} の提供年は "
        f"{dataset_config.first_year}-{dataset_config.last_year} 年。"
    )
    if dataset_config.last_year < 2023:
        year_note += (
            "本研究の Landsat 観測年（2023年）に対応する年次が存在しないため、"
            f"取得可能な最新年 {dataset_config.last_year} 年との時間差がある。"
        )
    return {
        "dataset": dataset_config.dataset_name,
        "dataset_key": dataset_config.dataset_key,
        "gee_asset_id": dataset_config.gee_asset_id,
        "source": dataset_config.source_url,
        "license": dataset_config.license_name,
        "license_note": dataset_config.license_note,
        "population_concept": dataset_config.population_concept,
        "retrieved_at": retrieved_at,
        "year": year,
        "year_note": year_note,
        "native_projection": {
            "crs": projection_info.get("crs"),
            "transform": projection_info.get("transform"),
            "nominal_scale_m": dataset_config.native_scale_m,
        },
        "resampling_note": (
            "ネイティブの crs / crs_transform を指定して取得しており、リサンプリングは"
            "行っていない。人口カウントは合計保存量のため、再投影すると範囲内総人口が"
            "変わる点に注意する。"
        ),
        "roi_path": to_project_relative_string(roi_path),
        "is_trial_run": is_trial,
        "area_bbox": list(area_bounds),
        # サマリーJSONの標準項目として最上位に置く。実体は raster_profile 側が正で、
        # ここはファイルから読み直した値をそのまま写している
        "crs": raster_profile["crs"],
        "raster_profile": raster_profile,
        "bands": {
            "1": {"name": BAND_COUNT_NAME, "unit": "人／セル", "description": "セルあたり人口"},
            "2": {
                "name": BAND_DENSITY_NAME,
                "unit": "人/km²",
                "description": (
                    "人口カウントを WGS84 楕円体上のセル実面積で割った密度。"
                    "セル面積は緯度により変わるため行ごとに算出している。"
                ),
            },
        },
        "pixel_stats": pixel_stats,
        "coverage_note": (
            "ROI ポリゴンで真にクリップしているため出力は BBOX 矩形となり、ROI 外の余白は "
            f"nodata（{OUTPUT_NODATA}）で埋まる。valid_pixel_ratio の分母 roi_pixels は"
            "**クリップ後の出力に含まれる ROI 内画素**であり、ROI 全体ではない。"
            "データソースが ROI を覆いきれていない場合、覆えていない領域は出力にも分母にも"
            "現れず有効率に反映されないため、範囲を覆えているかは covers_requested_area で"
            "別に判定する。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
    }


def clip_and_write(
    source_path: Path,
    area_gdf: gpd.GeoDataFrame,
    output_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """ダウンロードしたラスタを対象範囲でクリップし、2 バンド GeoTIFF として保存する。

    第1バンドに人口カウント、第2バンドに導出した人口密度（人/km²）を書き込む。

    Args:
        source_path (Path): ダウンロードした GeoTIFF パス。
        area_gdf (gpd.GeoDataFrame): 取得対象範囲（EPSG:4326）。
        output_path (Path): 出力 GeoTIFF パス。

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: (出力ラスタの諸元, 画素統計)。

    Raises:
        ValueError: ソースラスタの CRS が未定義、または地理座標系でない場合。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        source_crs = source.crs
        if source_crs is None:
            raise ValueError(f"ソースラスタの CRS が未定義です: {source_path}")
        # 密度導出は「セルの辺が度で表される」前提の測地計算を行う。投影座標系のラスタを
        # 渡すとメートル値を度として扱い、例外にならないまま誤った面積になる
        if not CRS.from_user_input(source_crs).is_geographic:
            raise ValueError(
                "地理座標系（度単位）のラスタのみに対応しています"
                f"（検出した CRS: {source_crs.to_string()}）。"
            )
        area_in_source_crs = area_gdf.to_crs(source_crs)
        count_array, clipped_transform = mask(
            source,
            shapes=[geometry.__geo_interface__ for geometry in area_in_source_crs.geometry],
            crop=True,
            indexes=[1],
            nodata=OUTPUT_NODATA,
        )
        profile = source.profile.copy()

    count_array = count_array[0].astype(np.float32)
    height, width = count_array.shape
    cell_area_km2 = compute_cell_area_km2(clipped_transform, height, width)
    density_array = compute_density_array(count_array, cell_area_km2, OUTPUT_NODATA)

    profile.update(
        driver="GTiff",
        count=2,
        dtype="float32",
        height=height,
        width=width,
        transform=clipped_transform,
        nodata=OUTPUT_NODATA,
    )
    with rasterio.open(output_path, "w", **profile) as destination:
        destination.write(count_array, 1)
        destination.write(density_array, 2)
        destination.set_band_description(1, BAND_COUNT_NAME)
        destination.set_band_description(2, BAND_DENSITY_NAME)

    # クリップ余白（範囲外）を欠測と数えないよう、対象範囲内のマスクを別に作る。
    # ジオメトリは clipped_transform と同じソース CRS のものを使う（座標系がずれると
    # roi_pixels・valid_pixel_ratio・総人口が静かに壊れるため）
    area_mask = geometry_mask(
        geometries=[geometry.__geo_interface__ for geometry in area_in_source_crs.geometry],
        out_shape=(height, width),
        transform=clipped_transform,
        invert=True,
    )
    valid_mask = area_mask & (count_array != OUTPUT_NODATA)
    area_pixel_count = int(np.count_nonzero(area_mask))
    valid_pixel_count = int(np.count_nonzero(valid_mask))

    pixel_stats = {
        "total_pixels": int(count_array.size),
        "roi_pixels": area_pixel_count,
        "outside_roi_pixels": int(count_array.size) - area_pixel_count,
        "valid_pixels": valid_pixel_count,
        "valid_pixel_ratio": (
            valid_pixel_count / area_pixel_count if area_pixel_count > 0 else 0.0
        ),
        "covers_requested_area": covers_requested_area(
            raster_bounds=array_bounds(height, width, clipped_transform),
            requested_bounds=tuple(float(value) for value in area_in_source_crs.total_bounds),
            pixel_size=(abs(clipped_transform.a), abs(clipped_transform.e)),
        ),
        # float32 のまま累算すると 800 万人規模で刻みが 1.0 になるため float64 で足す
        "total_population": float(np.sum(count_array[valid_mask], dtype=np.float64)),
        "total_area_km2": float(
            np.sum(np.broadcast_to(cell_area_km2, count_array.shape)[valid_mask], dtype=np.float64)
        ),
        BAND_COUNT_NAME: build_band_statistics(count_array[valid_mask]),
        BAND_DENSITY_NAME: build_band_statistics(density_array[valid_mask]),
    }

    with rasterio.open(output_path) as destination:
        bounds = destination.bounds
        raster_profile = {
            "crs": destination.crs.to_string() if destination.crs is not None else None,
            "dtype": str(destination.dtypes[0]),
            "band_count": int(destination.count),
            "width": int(destination.width),
            "height": int(destination.height),
            "resolution": [float(destination.res[0]), float(destination.res[1])],
            "bounds": {
                "minx": float(bounds.left),
                "miny": float(bounds.bottom),
                "maxx": float(bounds.right),
                "maxy": float(bounds.top),
            },
            "nodata": float(OUTPUT_NODATA),
        }

    return raster_profile, pixel_stats


def run(
    dataset_key: str,
    year: int | None,
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
        dataset_key (str): データセットキー（worldpop / landscan）。
        year (int | None): 取得対象年。
        roi_path (Path): ROI の Shapefile パス。
        bbox (list[float] | None): 試行実行用 BBOX。
        output_path (Path | None): 出力 GeoTIFF パス。
        summary_path (Path | None): サマリー JSON パス。
        config_path (Path): GEE 設定 CSV パス。
        gee_project_id (str): GEE プロジェクト ID。
        overwrite (bool): 既存出力を上書きするか。

    Returns:
        tuple[Path, Path]: (出力 GeoTIFF パス, サマリー JSON パス)。

    Raises:
        FileExistsError: 出力ファイルが既に存在し overwrite が False の場合。
    """
    dataset_config = DATASET_CONFIGS[dataset_key]
    resolved_year = resolve_year(dataset_config, year)
    # 出力先の決定に試行実行かどうかが要るため、ROI の読み込みを先に行う
    area_gdf, is_trial = build_target_area(roi_path=roi_path, bbox=bbox)
    area_bounds = tuple(float(value) for value in area_gdf.total_bounds)
    logger.info("取得対象範囲の BBOX: %s", area_bounds)

    resolved_output_path, resolved_summary_path = resolve_output_paths(
        dataset_config=dataset_config,
        year=resolved_year,
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

    population_image = select_population_image(dataset_config, resolved_year)
    region_geojson = area_gdf.geometry.union_all().__geo_interface__
    download_url, projection_info = build_download_url(
        population_image=population_image, region_geojson=region_geojson
    )
    logger.info(
        "ネイティブ投影で取得します（crs=%s, transform=%s）",
        projection_info.get("crs"),
        projection_info.get("transform"),
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="population_download_") as temporary_dir:
        downloaded_path = Path(temporary_dir) / f"{dataset_key}_{resolved_year}_raw.tif"
        download_raster(download_url, downloaded_path)
        raster_profile, pixel_stats = clip_and_write(
            source_path=downloaded_path,
            area_gdf=area_gdf,
            output_path=resolved_output_path,
        )

    if raster_profile["crs"] != WGS84_CRS:
        logger.warning("出力 CRS が %s ではありません: %s", WGS84_CRS, raster_profile["crs"])

    summary = build_summary(
        dataset_config=dataset_config,
        year=resolved_year,
        roi_path=roi_path,
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

    logger.info(
        "有効画素率: %.4f（有効 %d / 範囲内 %d、ラスタ全体 %d）",
        pixel_stats["valid_pixel_ratio"],
        pixel_stats["valid_pixels"],
        pixel_stats["roi_pixels"],
        pixel_stats["total_pixels"],
    )
    logger.info(
        "範囲内総人口: %.1f 人（面積 %.2f km²、平均密度 %.1f 人/km²）",
        pixel_stats["total_population"],
        pixel_stats["total_area_km2"],
        pixel_stats["total_population"] / pixel_stats["total_area_km2"]
        if pixel_stats["total_area_km2"] > 0
        else 0.0,
    )
    density_stats = pixel_stats[BAND_DENSITY_NAME]
    if density_stats is not None:
        logger.info(
            "人口密度（人/km²）: min=%.1f median=%.1f p95=%.1f max=%.1f",
            density_stats["min"],
            density_stats["median"],
            density_stats["p95"],
            density_stats["max"],
        )
    if pixel_stats["valid_pixel_ratio"] < 1.0:
        logger.warning(
            "範囲内に無効画素があります（有効率 %.4f）。データ提供範囲の限界を確認してください。",
            pixel_stats["valid_pixel_ratio"],
        )
    if not pixel_stats["covers_requested_area"]:
        # 覆えていない領域は出力にも有効率の分母にも現れないため、別途警告する
        logger.warning(
            "出力が要求範囲を覆いきれていません。有効率は覆えた範囲内でしか評価されていない"
            "ため、データソースの提供範囲を確認してください。"
        )

    return resolved_output_path, resolved_summary_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_path, summary_path = run(
        dataset_key=args.dataset,
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
