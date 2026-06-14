# 作成者: Codex
# 作成日: 2026-05-27
# 概要: 公開DEMを取得し、ROIポリゴンで真にクリップしたGeoTIFFとメタデータを保存する。

"""公開DEM取得スクリプト。

本スクリプトは公開DEMを取得し、指定したROIポリゴンで真にクリップした
GeoTIFFをローカルへ保存する。現在は以下に対応する。

- Copernicus GLO-30  (GEE: COPERNICUS/DEM/GLO30)
- NASADEM            (GEE: NASA/NASADEM_HGT/001)
- SRTMGL1 v003       (GEE: USGS/SRTMGL1_003)
- FABDEM V1-2        (GEE: projects/sat-io/open-datasets/FABDEM)

すべてのデータセットをGEE経由で取得する。

主な出力:
1. `data/GISData/DEM/<dataset>_hanoi_dem.tif`
2. `data/GISData/DEM/<dataset>_hanoi_dem_metadata.json`
"""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_ROI_PATH = PROJECT_ROOT / "data" / "GISData" / "ROI" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "GISData" / "DEM"
REQUEST_TIMEOUT_SECONDS = 300
CLIP_NODATA = -9999.0


@dataclass(frozen=True)
class DemDatasetConfig:
    """公開DEMデータセットの設定を保持する。"""

    dataset_key: str
    gee_asset_id: str
    band_name: str
    is_image_collection: bool
    default_scale_m: float
    output_stem: str
    dataset_name: str
    source_url: str
    characteristics: str
    dataset_created_date: str
    source_observation_period: str
    date_note: str
    source_type: str


DATASET_CONFIGS: dict[str, DemDatasetConfig] = {
    "copernicus_glo30": DemDatasetConfig(
        dataset_key="copernicus_glo30",
        gee_asset_id="COPERNICUS/DEM/GLO30",
        band_name="DEM",
        is_image_collection=True,
        default_scale_m=30.0,
        output_stem="copernicus_glo30_hanoi_dem",
        dataset_name="Copernicus DEM GLO-30",
        source_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30",
        characteristics=(
            "約30m、全球、Copernicus提供。水域平坦化などの編集済みDSMで、"
            "建物・植生を含む表層高になりうる。"
        ),
        dataset_created_date="2021 release",
        source_observation_period="2010-12-01 to 2015-01-31",
        date_note=(
            "公開配布リリースは2021年。GEEカタログには元データの利用可能期間として"
            "2010-12から2015-01が示される。"
        ),
        source_type="gee",
    ),
    "nasadem": DemDatasetConfig(
        dataset_key="nasadem",
        gee_asset_id="NASA/NASADEM_HGT/001",
        band_name="elevation",
        is_image_collection=False,
        default_scale_m=30.0,
        output_stem="nasadem_hanoi_dem",
        dataset_name="NASADEM",
        source_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001",
        characteristics=(
            "約30m、SRTM再処理版。ASTER GDEM・ICESat GLAS・PRISMを補助利用し、"
            "ボイド低減と精度改善が図られている。"
        ),
        dataset_created_date="2020-01",
        source_observation_period="2000-02-11 to 2000-02-22",
        date_note=(
            "NASADEM User Guideの版頭に January 2020 と記載。観測自体は"
            "SRTMの2000年2月取得データに基づく。"
        ),
        source_type="gee",
    ),
    "srtmgl1": DemDatasetConfig(
        dataset_key="srtmgl1",
        gee_asset_id="USGS/SRTMGL1_003",
        band_name="elevation",
        is_image_collection=False,
        default_scale_m=30.0,
        output_stem="srtmgl1_hanoi_dem",
        dataset_name="SRTMGL1 v003",
        source_url="https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003",
        characteristics=(
            "約30m、全球。広く使われる基礎DEMだが取得時期が2000年で、"
            "比較的新しい都市開発は反映しない。"
        ),
        dataset_created_date="Version 3 product release date is not explicitly exposed in GEE metadata",
        source_observation_period="2000-02-11 to 2000-02-22",
        date_note=(
            "GEEカタログでは取得期間は明示されるが、単一の公開日までは明示されない。"
            "SRTM Plus Version 3として流通している。"
        ),
        source_type="gee",
    ),
    "fabdem": DemDatasetConfig(
        dataset_key="fabdem",
        gee_asset_id="projects/sat-io/open-datasets/FABDEM",
        band_name="b1",
        is_image_collection=True,
        default_scale_m=30.0,
        output_stem="fabdem_hanoi_dem",
        dataset_name="FABDEM V1-2",
        source_url="https://gee-community-catalog.org/projects/fabdem/",
        characteristics=(
            "約30m、60°S〜80°N。Copernicus GLO-30をベースにランダムフォレスト回帰で"
            "建物・森林バイアスを除去した準DTM。ライセンスはCC BY-NC-SA 4.0（非商用）。"
        ),
        dataset_created_date="2023-01-18",
        source_observation_period=(
            "Based on Copernicus GLO-30 / WorldDEM source acquisitions from roughly 2010 to 2015"
        ),
        date_note=(
            "University of Bristolのデータセット公開日は2023-01-18。元データは"
            "Copernicus GLO-30由来で、厳密なピクセル単位作成日は別管理。"
        ),
        source_type="gee",
    ),
}


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解釈する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(description="公開DEMを取得してROIポリゴンでクリップする。")
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASET_CONFIGS.keys()),
        default="copernicus_glo30",
        help="取得対象の公開DEMデータセット。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_ROI_PATH,
        help="ROIのShapefileパス。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="出力GeoTIFFパス。未指定時は data/GISData/DEM/ 配下へ保存する。",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=None,
        help="メタデータJSONパス。未指定時はGeoTIFFと同名で保存する。",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="GEEプロジェクトIDを読む設定CSVパス。",
    )
    parser.add_argument(
        "--gee-project-id",
        default="",
        help="GEEプロジェクトID。未指定時は設定CSVから取得する。",
    )
    parser.add_argument(
        "--output-crs",
        default="EPSG:4326",
        help="出力GeoTIFFのCRS。",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="出力解像度（m）。未指定時はデータセット既定値。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存ファイルを上書きする。",
    )
    return parser.parse_args()


def to_project_relative_string(path: Path) -> str:
    """可能ならプロジェクト相対パスへ変換する。

    Args:
        path (Path): 変換対象パス。

    Returns:
        str: プロジェクト相対パス、または絶対パス文字列。
    """
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved_path)


def resolve_output_paths(
    dataset_config: DemDatasetConfig,
    output_path: Path | None,
    metadata_path: Path | None,
) -> tuple[Path, Path]:
    """出力GeoTIFFとメタデータJSONの保存先を解決する。"""
    resolved_output_path = output_path
    if resolved_output_path is None:
        resolved_output_path = DEFAULT_OUTPUT_DIR / f"{dataset_config.output_stem}.tif"

    resolved_metadata_path = metadata_path
    if resolved_metadata_path is None:
        resolved_metadata_path = resolved_output_path.with_name(
            f"{resolved_output_path.stem}_metadata.json"
        )

    return resolved_output_path, resolved_metadata_path


def ensure_output_paths(
    output_path: Path,
    metadata_path: Path,
    overwrite: bool,
) -> None:
    """出力先の存在確認とディレクトリ作成を行う。"""
    for path in (output_path, metadata_path):
        if path.exists():
            if not overwrite:
                raise FileExistsError(
                    f"出力ファイルが既に存在します: {path}。上書きする場合は --overwrite を指定してください。"
                )
            path.unlink()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)


def load_gee_project_id(config_path: Path, explicit_project_id: str) -> str:
    """GEEプロジェクトIDを取得する。"""
    if explicit_project_id.strip():
        return explicit_project_id.strip()

    if not config_path.exists():
        raise FileNotFoundError(f"GEE設定CSVが見つかりません: {config_path}")

    config_df = pd.read_csv(config_path)
    if config_df.empty:
        raise ValueError(f"GEE設定CSVが空です: {config_path}")

    project_id = str(config_df.iloc[0].get("gee_project_id", "")).strip()
    if not project_id or project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError(
            "GEEプロジェクトIDが取得できませんでした。--gee-project-id を指定するか設定CSVを確認してください。"
        )
    return project_id


def initialize_gee(project_id: str) -> None:
    """Google Earth Engine を初期化する。"""
    ee.Initialize(project=project_id)


def load_roi_geodataframe(roi_path: Path) -> gpd.GeoDataFrame:
    """ROIのShapefileを読み込み、WGS84へ正規化する。"""
    if not roi_path.exists():
        raise FileNotFoundError(f"ROIファイルが見つかりません: {roi_path}")

    roi_gdf = gpd.read_file(roi_path)
    if roi_gdf.empty:
        raise ValueError(f"ROIファイルに地物がありません: {roi_path}")
    if roi_gdf.crs is None:
        raise ValueError(f"ROIファイルのCRSが未定義です: {roi_path}")

    return roi_gdf.to_crs(epsg=4326)


def build_roi_geometry(roi_gdf: gpd.GeoDataFrame) -> tuple[ee.Geometry, dict[str, Any]]:
    """GeoDataFrameからEarth Engine用のROIを構築する。"""
    roi_union = roi_gdf.geometry.union_all()
    roi_geojson = roi_union.__geo_interface__
    return ee.Geometry(roi_geojson), roi_geojson


def get_dem_image(dataset_config: DemDatasetConfig) -> ee.Image:
    """対象データセットのDEM画像を返す。"""
    if dataset_config.is_image_collection:
        return (
            ee.ImageCollection(dataset_config.gee_asset_id)
            .select(dataset_config.band_name)
            .mosaic()
            .rename("elevation")
        )

    return (
        ee.Image(dataset_config.gee_asset_id).select(dataset_config.band_name).rename("elevation")
    )


def build_gee_download_url(
    dem_image: ee.Image,
    roi_geometry: ee.Geometry,
    roi_geojson: dict[str, Any],
    output_crs: str,
    scale_m: float,
) -> str:
    """Earth EngineのダウンロードURLを生成する。"""
    clipped_image = dem_image.clip(roi_geometry)
    return clipped_image.getDownloadURL(
        {
            "scale": scale_m,
            "crs": output_crs,
            "region": roi_geojson,
            "format": "GEO_TIFF",
        }
    )


def download_http_content(download_url: str) -> bytes:
    """HTTPレスポンス本文を取得する。"""
    response = requests.get(download_url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def save_downloaded_raster(response_content: bytes, output_path: Path) -> None:
    """ダウンロードしたレスポンスをGeoTIFFとして保存する。"""
    buffer = io.BytesIO(response_content)
    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as zip_file:
            tif_members = [
                member
                for member in zip_file.namelist()
                if member.lower().endswith((".tif", ".tiff"))
            ]
            if not tif_members:
                raise ValueError("ZIP内にGeoTIFFが見つかりませんでした。")
            with zip_file.open(tif_members[0]) as tif_stream:
                output_path.write_bytes(tif_stream.read())
        return

    output_path.write_bytes(response_content)


def clip_raster_to_roi(
    input_raster_path: Path,
    roi_gdf: gpd.GeoDataFrame,
    output_path: Path,
    output_crs: str,
) -> None:
    """ラスタをROIポリゴンで真にクリップし、必要ならCRS変換して保存する。"""
    with rasterio.open(input_raster_path) as src:
        roi_in_src_crs = roi_gdf.to_crs(src.crs)
        clipped_array, clipped_transform = mask(
            src,
            shapes=[geom.__geo_interface__ for geom in roi_in_src_crs.geometry],
            crop=True,
            nodata=CLIP_NODATA,
        )
        clipped_array = clipped_array.astype(np.float32)
        clipped_profile = src.profile.copy()
        clipped_profile.update(
            height=clipped_array.shape[1],
            width=clipped_array.shape[2],
            transform=clipped_transform,
            nodata=CLIP_NODATA,
            dtype="float32",
            count=1,
        )

        clipped_crs_text = (
            clipped_profile["crs"].to_string() if clipped_profile["crs"] is not None else None
        )
        if clipped_crs_text == output_crs:
            with rasterio.open(output_path, "w", **clipped_profile) as dst:
                dst.write(clipped_array)
            return

        bounds = rasterio.transform.array_bounds(
            clipped_profile["height"],
            clipped_profile["width"],
            clipped_transform,
        )
        dst_transform, dst_width, dst_height = calculate_default_transform(
            clipped_profile["crs"],
            output_crs,
            clipped_profile["width"],
            clipped_profile["height"],
            *bounds,
        )
        reprojected_array = np.full((1, dst_height, dst_width), CLIP_NODATA, dtype=np.float32)
        reproject(
            source=clipped_array,
            destination=reprojected_array,
            src_transform=clipped_transform,
            src_crs=clipped_profile["crs"],
            src_nodata=CLIP_NODATA,
            dst_transform=dst_transform,
            dst_crs=output_crs,
            dst_nodata=CLIP_NODATA,
            resampling=Resampling.bilinear,
        )
        clipped_profile.update(
            crs=output_crs,
            transform=dst_transform,
            width=dst_width,
            height=dst_height,
        )
        with rasterio.open(output_path, "w", **clipped_profile) as dst:
            dst.write(reprojected_array)


def read_raster_summary(output_path: Path) -> dict[str, Any]:
    """保存済みGeoTIFFのメタデータと基本統計を取得する。"""
    with rasterio.open(output_path) as src:
        masked_array = src.read(1, masked=True).astype(np.float32)
        valid_values = masked_array.compressed()
        bounds = src.bounds
        summary = {
            "path": to_project_relative_string(output_path),
            "crs": src.crs.to_string() if src.crs is not None else None,
            "resolution": [float(src.res[0]), float(src.res[1])],
            "width": int(src.width),
            "height": int(src.height),
            "bounds": {
                "minx": float(bounds.left),
                "miny": float(bounds.bottom),
                "maxx": float(bounds.right),
                "maxy": float(bounds.top),
            },
            "dtype": str(src.dtypes[0]),
            "nodata": None if src.nodata is None else float(src.nodata),
            "valid_pixel_count": int(valid_values.size),
            "clip_method": "polygon mask with crop=true",
        }
        if valid_values.size == 0:
            summary["statistics"] = None
        else:
            summary["statistics"] = {
                "min": float(valid_values.min()),
                "max": float(valid_values.max()),
                "mean": float(valid_values.mean()),
                "std": float(valid_values.std()),
            }
    return summary


def build_metadata(
    dataset_config: DemDatasetConfig,
    roi_path: Path,
    output_crs: str,
    scale_m: float,
    raster_summary: dict[str, Any],
    source_details: dict[str, Any] | None,
) -> dict[str, Any]:
    """メタデータJSONを構築する。"""
    return {
        "dataset": asdict(dataset_config),
        "roi_path": to_project_relative_string(roi_path),
        "requested_output_crs": output_crs,
        "requested_scale_m": scale_m,
        "raster_summary": raster_summary,
        "source_details": source_details,
    }


def write_metadata(metadata: dict[str, Any], metadata_path: Path) -> None:
    """メタデータJSONを書き込む。"""
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(
    dataset_key: str,
    roi_path: Path,
    output_path: Path | None,
    metadata_path: Path | None,
    config_path: Path,
    gee_project_id: str,
    output_crs: str,
    scale_m: float | None,
    overwrite: bool,
) -> tuple[Path, Path]:
    """公開DEMのダウンロード処理全体を実行する。"""
    dataset_config = DATASET_CONFIGS[dataset_key]
    resolved_output_path, resolved_metadata_path = resolve_output_paths(
        dataset_config=dataset_config,
        output_path=output_path,
        metadata_path=metadata_path,
    )
    ensure_output_paths(
        output_path=resolved_output_path,
        metadata_path=resolved_metadata_path,
        overwrite=overwrite,
    )

    roi_gdf = load_roi_geodataframe(roi_path)
    resolved_scale_m = scale_m or dataset_config.default_scale_m
    source_details: dict[str, Any] | None = None

    if dataset_config.source_type == "gee":
        project_id = load_gee_project_id(
            config_path=config_path, explicit_project_id=gee_project_id
        )
        initialize_gee(project_id=project_id)
        roi_geometry, roi_geojson = build_roi_geometry(roi_gdf)
        dem_image = get_dem_image(dataset_config)
        download_url = build_gee_download_url(
            dem_image=dem_image,
            roi_geometry=roi_geometry,
            roi_geojson=roi_geojson,
            output_crs=output_crs,
            scale_m=resolved_scale_m,
        )
        response_content = download_http_content(download_url)
        with tempfile.TemporaryDirectory(prefix="dem_download_") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            raw_raster_path = temp_dir / f"{dataset_key}_raw.tif"
            save_downloaded_raster(response_content, raw_raster_path)
            clip_raster_to_roi(
                input_raster_path=raw_raster_path,
                roi_gdf=roi_gdf,
                output_path=resolved_output_path,
                output_crs=output_crs,
            )
        source_details = {"download_source": "Google Earth Engine"}

    raster_summary = read_raster_summary(resolved_output_path)
    metadata = build_metadata(
        dataset_config=dataset_config,
        roi_path=roi_path,
        output_crs=output_crs,
        scale_m=resolved_scale_m,
        raster_summary=raster_summary,
        source_details=source_details,
    )
    write_metadata(metadata=metadata, metadata_path=resolved_metadata_path)
    return resolved_output_path, resolved_metadata_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_path, metadata_path = run(
        dataset_key=args.dataset,
        roi_path=args.roi_path,
        output_path=args.output_path,
        metadata_path=args.metadata_path,
        config_path=args.config_path,
        gee_project_id=args.gee_project_id,
        output_crs=args.output_crs,
        scale_m=args.scale,
        overwrite=args.overwrite,
    )
    print(f"GeoTIFFを保存しました: {output_path}")
    print(f"メタデータJSONを保存しました: {metadata_path}")


if __name__ == "__main__":
    main()
