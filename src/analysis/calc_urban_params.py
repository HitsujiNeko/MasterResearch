# 作成者: GitHub Copilot
# 作成日: 2026-03-31
# 概要: 都市構造パラメータを30mグリッドで算出し、必要に応じて衛星指標を統合してCSV出力する。

"""都市構造パラメータ算出スクリプト。

本スクリプトは、測量GISデータ（WGS84）から都市構造パラメータを算出し、
必要に応じて衛星由来ラスタ指標（NDVI/NDBI/NDWI/FVC）を30mグリッドへ集約して
1つのCSVとして出力する。

重要な前提:
    - LSTはGEE算出時点でROI（行政区画）にクリップ済みである。
    - 本スクリプトは、ROI内のGIS有効域（矩形）を分析対象として説明変数を作成する。
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from rasterio.enums import MergeAlg, Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

try:
    from shapely import make_valid as shapely_make_valid
except Exception:  # pragma: no cover
    shapely_make_valid = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RASTER_KEYS = ("NDVI", "NDBI", "NDWI", "FVC")


@dataclass(frozen=True)
class BBox:
    """経緯度座標系のバウンディングボックス。"""

    minx: float
    miny: float
    maxx: float
    maxy: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Fionaのbbox引数へ渡す形式で返す。"""
        return (self.minx, self.miny, self.maxx, self.maxy)


@dataclass(frozen=True)
class GridSpec:
    """解析グリッドの仕様を保持する。"""

    analysis_crs: CRS
    to_wgs84: Transformer
    coarse_res_m: float
    fine_res_m: float
    factor: int
    coarse_shape: tuple[int, int]
    fine_shape: tuple[int, int]
    coarse_transform: Affine
    fine_transform: Affine


@dataclass(frozen=True)
class LayerResource:
    """入力レイヤと解析用CRSへの変換情報を保持する。"""

    path: Path
    layer_name: str
    source_crs: CRS
    analysis_crs: CRS
    to_analysis: Transformer
    from_analysis: Transformer


CITY_CONFIG: dict[str, dict[str, Any]] = {
    "hanoi": {
        "analysis_epsg": 3405,
        "layers": {
            "roi": {
                "path": "data/GISData/ROI/hanoi/hanoi_ROI_EPSG4326.shp",
                "layer": "hanoi_ROI_EPSG4326",
                "crs_epsg": 4326,
            },
            "open_buildings": {
                "path": "data/output/open_gis/hanoi_microsoft_buildings.gpkg",
                "layer": "buildings",
                "crs_epsg": 4326,
            },
            "open_roads": {
                "path": "data/output/open_gis/hanoi_osm_roads.gpkg",
                "layer": "roads",
                "crs_epsg": 4326,
            },
            "rg": {
                "path": "整備データ/merge/merge_RG.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "cs": {
                "path": "整備データ/merge/merge_CS.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "dc": {
                "path": "整備データ/merge/merge_DC.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "gt": {
                "path": "整備データ/merge/merge_GT.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "th": {
                "path": "整備データ/merge/merge_TH.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "tv": {
                "path": "整備データ/merge/merge_TV.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
            "dh": {
                "path": "整備データ/merge/merge_DH.gpkg",
                "layer": "elements",
                "crs_epsg": 3405,
            },
        },
    }
}

SCENARIO_LAYER_KEYS: dict[str, dict[str, str | None]] = {
    "limited": {
        "default_mask": "roi",
        "buildings": "open_buildings",
        "roads": "open_roads",
        "water": None,
        "green": None,
        "elevation": None,
        "data_source": "open_gis",
    },
    "full": {
        "default_mask": "rg",
        "buildings": "dc",
        "roads": "gt",
        "water": "th",
        "green": "tv",
        "elevation": "dh",
        "data_source": "survey_gis",
    },
}


def resolve_layer_name(gpkg_path: Path, preferred_layer: str) -> str:
    """指定レイヤが無い場合は、実在する最初の通常レイヤへフォールバックする。"""
    if not gpkg_path.exists():
        raise FileNotFoundError(f"GPKGファイルが見つかりません: {gpkg_path}")

    layers = list(fiona.listlayers(gpkg_path))
    if preferred_layer in layers:
        return preferred_layer

    filtered_layers = [name for name in layers if not name.startswith("rtree_")]
    if not filtered_layers:
        raise ValueError(f"利用可能なレイヤがありません: {gpkg_path}")

    return filtered_layers[0]


def get_layer_resource(
    city_cfg: dict[str, Any],
    layer_key: str,
    analysis_crs: CRS,
) -> LayerResource:
    """都市設定から対象レイヤのファイルパスとレイヤ名を解決する。"""
    layer_cfg = city_cfg["layers"].get(layer_key)
    if layer_cfg is None:
        raise ValueError(f"都市設定にレイヤがありません: {layer_key}")

    gpkg_path = PROJECT_ROOT / layer_cfg["path"]
    layer_name = resolve_layer_name(gpkg_path, str(layer_cfg["layer"]))
    source_crs = CRS.from_epsg(int(layer_cfg["crs_epsg"]))
    to_analysis = Transformer.from_crs(source_crs, analysis_crs, always_xy=True)
    from_analysis = Transformer.from_crs(analysis_crs, source_crs, always_xy=True)
    return LayerResource(gpkg_path, layer_name, source_crs, analysis_crs, to_analysis, from_analysis)


def transform_bbox(bbox: BBox, transformer: Transformer) -> BBox:
    """BBoxを別の座標系へ変換する。"""
    corners = [
        (bbox.minx, bbox.miny),
        (bbox.minx, bbox.maxy),
        (bbox.maxx, bbox.miny),
        (bbox.maxx, bbox.maxy),
    ]
    x_coords, y_coords = zip(*[transformer.transform(x, y) for x, y in corners])
    return BBox(min(x_coords), min(y_coords), max(x_coords), max(y_coords))


def bbox_from_layer(resource: LayerResource, analysis_crs: CRS) -> BBox:
    """レイヤ全体のBBoxを解析用CRSで取得する。"""
    with fiona.open(resource.path, layer=resource.layer_name) as src:
        minx, miny, maxx, maxy = src.bounds
    bbox = BBox(float(minx), float(miny), float(maxx), float(maxy))
    if resource.source_crs == analysis_crs:
        return bbox
    return transform_bbox(bbox, resource.to_analysis)


def build_grid(
    bbox_analysis: BBox,
    analysis_crs: CRS,
    coarse_res_m: float,
    fine_res_m: float,
) -> GridSpec:
    """解析BBoxから解析用CRS上のfine/coarseグリッド仕様を構築する。"""
    factor = int(round(coarse_res_m / fine_res_m))
    if factor <= 0 or abs(coarse_res_m - (factor * fine_res_m)) > 1e-6:
        raise ValueError("coarse_res_m は fine_res_m の整数倍で指定してください。")

    wgs84 = CRS.from_epsg(4326)
    to_wgs84 = Transformer.from_crs(analysis_crs, wgs84, always_xy=True)
    fine_width = int(math.ceil((bbox_analysis.maxx - bbox_analysis.minx) / fine_res_m))
    fine_height = int(math.ceil((bbox_analysis.maxy - bbox_analysis.miny) / fine_res_m))

    pad_x = (-fine_width) % factor
    pad_y = (-fine_height) % factor
    fine_width += pad_x
    fine_height += pad_y

    coarse_width = fine_width // factor
    coarse_height = fine_height // factor

    fine_transform = from_origin(
        bbox_analysis.minx,
        bbox_analysis.maxy,
        fine_res_m,
        fine_res_m,
    )
    coarse_transform = from_origin(
        bbox_analysis.minx,
        bbox_analysis.maxy,
        coarse_res_m,
        coarse_res_m,
    )

    return GridSpec(
        analysis_crs=analysis_crs,
        to_wgs84=to_wgs84,
        coarse_res_m=coarse_res_m,
        fine_res_m=fine_res_m,
        factor=factor,
        coarse_shape=(coarse_height, coarse_width),
        fine_shape=(fine_height, fine_width),
        coarse_transform=coarse_transform,
        fine_transform=fine_transform,
    )


def iter_feature_records(resource: LayerResource, bbox_analysis: BBox) -> Iterable[dict[str, Any]]:
    """指定BBox内のフィーチャを逐次返す。"""
    query_bbox = bbox_analysis
    if resource.source_crs != resource.analysis_crs:
        query_bbox = transform_bbox(bbox_analysis, resource.from_analysis)

    with fiona.open(resource.path, layer=resource.layer_name, bbox=query_bbox.to_tuple()) as src:
        for feature in src:
            if feature.get("geometry") is None:
                continue
            yield feature


def project_geometry_safe(geometry: dict[str, Any], to_analysis: Transformer):
    """ジオメトリを安全に解析用CRSへ投影する。失敗時はNoneを返す。"""
    try:
        geom = shape(geometry)
    except Exception:
        return None

    if getattr(geom, "is_empty", False):
        return None

    try:
        is_valid = bool(getattr(geom, "is_valid", True))
    except Exception:
        return None

    if not is_valid and shapely_make_valid is not None:
        try:
            geom = shapely_make_valid(geom)
        except Exception:
            return None

    if getattr(geom, "is_empty", False):
        return None

    try:
        projected = shp_transform(to_analysis.transform, geom)
    except Exception:
        return None

    if getattr(projected, "is_empty", False):
        return None

    return projected


def geometry_is_polygon(projected_geom: Any) -> bool:
    """ポリゴン系ジオメトリかを判定する。"""
    return projected_geom.geom_type in {"Polygon", "MultiPolygon"}


def geometry_is_line(projected_geom: Any) -> bool:
    """ライン系ジオメトリかを判定する。"""
    return projected_geom.geom_type in {"LineString", "MultiLineString"}


def geometry_is_point(projected_geom: Any) -> bool:
    """ポイント系ジオメトリかを判定する。"""
    return projected_geom.geom_type in {"Point", "MultiPoint"}


def rasterize_binary_mask(
    geometries: Iterable[Any],
    out_shape: tuple[int, int],
    out_transform: Affine,
    chunk_size: int = 5000,
) -> np.ndarray:
    """ジオメトリ群を0/1マスクへラスタ化する。"""
    out_array = np.zeros(out_shape, dtype=np.uint8)
    chunk: list[tuple[Any, int]] = []

    for geom in geometries:
        chunk.append((geom, 1))
        if len(chunk) >= chunk_size:
            rasterize(
                chunk,
                out=out_array,
                transform=out_transform,
                fill=0,
                default_value=1,
                dtype=np.uint8,
                merge_alg=MergeAlg.replace,
                all_touched=False,
            )
            chunk.clear()

    if chunk:
        rasterize(
            chunk,
            out=out_array,
            transform=out_transform,
            fill=0,
            default_value=1,
            dtype=np.uint8,
            merge_alg=MergeAlg.replace,
            all_touched=False,
        )

    return (out_array > 0).astype(np.uint8)


def iter_projected_geometries(
    resource: LayerResource,
    bbox_analysis: BBox,
    geometry_filter: Any,
) -> Iterable[Any]:
    """条件に合うジオメトリだけを逐次投影して返す。"""
    for feature in iter_feature_records(resource, bbox_analysis):
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if geometry_filter(projected):
            yield projected


def aggregate_mean_from_fine_mask(fine_mask: np.ndarray, factor: int) -> np.ndarray:
    """fineマスクをcoarseへ平均集約し、被覆率を返す。"""
    rows, cols = fine_mask.shape
    coarse_rows = rows // factor
    coarse_cols = cols // factor
    reshaped = fine_mask.reshape(coarse_rows, factor, coarse_cols, factor)
    return reshaped.mean(axis=(1, 3)).astype(np.float32)


def aggregate_sum_from_fine_mask(fine_mask: np.ndarray, factor: int) -> np.ndarray:
    """fineマスクをcoarseへ合計集約する。"""
    rows, cols = fine_mask.shape
    coarse_rows = rows // factor
    coarse_cols = cols // factor
    reshaped = fine_mask.reshape(coarse_rows, factor, coarse_cols, factor)
    return reshaped.sum(axis=(1, 3)).astype(np.float32)


def compute_polygon_coverage(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> np.ndarray:
    """ポリゴン系地物の被覆率を30mグリッドで算出する。"""
    fine_mask = rasterize_binary_mask(
        geometries=iter_projected_geometries(
            resource=resource,
            bbox_analysis=bbox_analysis,
            geometry_filter=geometry_is_polygon,
        ),
        out_shape=grid_spec.fine_shape,
        out_transform=grid_spec.fine_transform,
    )
    return aggregate_mean_from_fine_mask(fine_mask, grid_spec.factor)


def count_polygon_centroids(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> np.ndarray:
    """ポリゴン重心を30mセルへ割り当て、セルごとの件数を返す。"""
    counts = np.zeros(grid_spec.coarse_shape, dtype=np.int32)
    inverse_transform = ~grid_spec.coarse_transform

    for feature in iter_feature_records(resource, bbox_analysis):
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if not geometry_is_polygon(projected):
            continue

        centroid = projected.centroid
        if getattr(centroid, "is_empty", False):
            continue

        col_f, row_f = inverse_transform * (centroid.x, centroid.y)
        col = int(math.floor(col_f))
        row = int(math.floor(row_f))

        if 0 <= row < grid_spec.coarse_shape[0] and 0 <= col < grid_spec.coarse_shape[1]:
            counts[row, col] += 1

    return counts.astype(np.float32)


def compute_line_density(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> np.ndarray:
    """ライン系地物の道路密度（m/cell）を近似計算する。"""
    fine_mask = rasterize_binary_mask(
        geometries=iter_projected_geometries(
            resource=resource,
            bbox_analysis=bbox_analysis,
            geometry_filter=geometry_is_line,
        ),
        out_shape=grid_spec.fine_shape,
        out_transform=grid_spec.fine_transform,
        chunk_size=7000,
    )
    touched_cells = aggregate_sum_from_fine_mask(fine_mask, grid_spec.factor)
    return touched_cells * float(grid_spec.fine_res_m)


def parse_numeric_value(value: Any) -> float | None:
    """属性値から数値を抽出する。数値が無い場合はNoneを返す。"""
    if value is None:
        return None

    if isinstance(value, (int, float, np.integer, np.floating)):
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return numeric

    text = str(value).strip()
    if not text:
        return None

    # 小数点カンマを小数点に置換し、最初の数値を抽出する。
    normalized = text.replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", normalized)
    if match is None:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def extract_elevation_value(properties: dict[str, Any]) -> float | None:
    """属性辞書から最初に解釈可能な標高値を抽出する。"""
    for value in properties.values():
        parsed = parse_numeric_value(value)
        if parsed is not None:
            return parsed
    return None


def compute_elevation_from_points(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> tuple[np.ndarray, np.ndarray]:
    """DHの点地物から標高平均と有効点数を30mセル単位で算出する。"""
    sum_array = np.zeros(grid_spec.coarse_shape, dtype=np.float64)
    count_array = np.zeros(grid_spec.coarse_shape, dtype=np.int32)
    inverse_transform = ~grid_spec.coarse_transform

    for feature in iter_feature_records(resource, bbox_analysis):
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if not geometry_is_point(projected):
            continue

        numeric = extract_elevation_value(feature.get("properties", {}))
        if numeric is None:
            continue

        if projected.geom_type == "Point":
            points = [projected]
        else:
            points = list(projected.geoms)

        for point in points:
            col_f, row_f = inverse_transform * (point.x, point.y)
            col = int(math.floor(col_f))
            row = int(math.floor(row_f))
            if 0 <= row < grid_spec.coarse_shape[0] and 0 <= col < grid_spec.coarse_shape[1]:
                sum_array[row, col] += numeric
                count_array[row, col] += 1

    mean_array = np.full(grid_spec.coarse_shape, np.nan, dtype=np.float32)
    valid_mask = count_array > 0
    mean_array[valid_mask] = (sum_array[valid_mask] / count_array[valid_mask]).astype(np.float32)

    return mean_array, count_array.astype(np.float32)


def get_optional_layer_resource(
    city_cfg: dict[str, Any],
    layer_key: str | None,
) -> LayerResource | None:
    """繧ｷ繝翫Μ繧ｪ縺ｧ譛ｪ謖・ｮ壹・繝ｬ繧､繝､縺ｯNone縺ｨ縺励※謇ｱ縺・・"""
    if layer_key is None:
        return None
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))
    return get_layer_resource(city_cfg, layer_key, analysis_crs)


def grid_centers_wgs84(grid_spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """30mグリッド中心の経度・緯度配列を返す。"""
    rows, cols = grid_spec.coarse_shape

    col_indices = np.arange(cols, dtype=np.float64) + 0.5
    row_indices = np.arange(rows, dtype=np.float64) + 0.5

    xs = grid_spec.coarse_transform.c + (col_indices * grid_spec.coarse_transform.a)
    ys = grid_spec.coarse_transform.f + (row_indices * grid_spec.coarse_transform.e)

    xx, yy = np.meshgrid(xs, ys)
    lon, lat = grid_spec.to_wgs84.transform(xx, yy)
    return lon.astype(np.float64), lat.astype(np.float64)


def find_satellite_rasters(satellite_path: Path) -> dict[str, tuple[Path, int]]:
    """衛星指標ラスタとバンド番号を自動検出する。"""
    import rasterio

    detected: dict[str, tuple[Path, int]] = {}
    if not satellite_path.exists():
        return detected

    if satellite_path.is_file():
        tif_files = [satellite_path]
    else:
        tif_files = sorted(list(satellite_path.glob("*.tif")) + list(satellite_path.glob("*.tiff")))

    for tif_path in tif_files:
        upper_name = tif_path.name.upper()
        try:
            with rasterio.open(tif_path) as src:
                descriptions = src.descriptions
                for band_index, description in enumerate(descriptions, start=1):
                    if description is None:
                        continue
                    key = str(description).upper()
                    if key in RASTER_KEYS and key in detected and detected[key][0] != tif_path:
                        raise ValueError(
                            f"{key} を含む衛星指標ファイルが複数あります。"
                            f" 単一の観測ファイルを指定してください: {detected[key][0]}, {tif_path}"
                        )
                    if key in RASTER_KEYS and key not in detected:
                        detected[key] = (tif_path, band_index)
        except Exception:
            raise

        for key in RASTER_KEYS:
            if key in detected:
                continue
            if key in upper_name:
                detected[key] = (tif_path, 1)

    return detected


def aggregate_raster_to_grid(raster_path: Path, grid_spec: GridSpec, band_index: int = 1) -> np.ndarray:
    """ラスタを30mグリッドへ平均再投影し、セル平均値を返す。"""
    import rasterio

    dst_array = np.full(grid_spec.coarse_shape, np.nan, dtype=np.float32)

    with rasterio.open(raster_path) as src:
        reproject(
            source=rasterio.band(src, band_index),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=grid_spec.coarse_transform,
            dst_crs=grid_spec.analysis_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
            init_dest_nodata=True,
            num_threads=2,
        )

    return dst_array.astype(np.float32)


def build_quality_columns(indicator_arrays: Iterable[np.ndarray], grid_spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """品質管理列を作成する。"""
    valid_gis_mask = np.zeros(grid_spec.coarse_shape, dtype=bool)
    for indicator_array in indicator_arrays:
        valid_gis_mask |= np.nan_to_num(indicator_array, nan=0.0) > 0

    missing_reason = np.where(valid_gis_mask, "none", "no_gis_feature")
    return valid_gis_mask.astype(np.int8), missing_reason


def print_basic_summary(dataframe: pd.DataFrame) -> None:
    """主要列の簡易統計を標準出力する。"""
    numeric_columns = [
        "BUILD_COV_0",
        "BUILD_DEN_0",
        "ROAD_DEN_0",
        "WATER_COV_0",
        "GREEN_COV_0",
        "ELEV_COUNT_0",
    ]
    existing_columns = [column for column in numeric_columns if column in dataframe.columns]

    print("出力行数:", len(dataframe))
    if existing_columns:
        print(dataframe[existing_columns].describe().loc[["min", "mean", "max"]])


def parse_arguments() -> argparse.Namespace:
    """CLI引数を解釈して返す。"""
    parser = argparse.ArgumentParser(description="都市構造パラメータ算出（設計再定義版）")
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument("--scenario", default="limited", choices=list(SCENARIO_LAYER_KEYS.keys()))
    parser.add_argument("--coarse-res", type=float, default=30.0)
    parser.add_argument("--fine-res", type=float, default=10.0)
    parser.add_argument("--mask-layer-key", default="", choices=["", "roi", "rg", "cs"])
    parser.add_argument(
        "--satellite-dir",
        type=str,
        default="",
        help="衛星指標ラスタのファイルまたは格納ディレクトリ（任意）。複数観測がある場合はファイルを指定する。",
    )
    return parser.parse_args()


def main() -> None:
    """都市構造パラメータ算出処理を実行する。"""
    args = parse_arguments()
    city_cfg = CITY_CONFIG[args.city]
    scenario_cfg = SCENARIO_LAYER_KEYS[args.scenario]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))

    mask_layer_key = args.mask_layer_key or str(scenario_cfg["default_mask"])
    mask_resource = get_layer_resource(city_cfg, mask_layer_key, analysis_crs)
    analysis_bbox = bbox_from_layer(mask_resource, analysis_crs)
    grid_spec = build_grid(analysis_bbox, analysis_crs, args.coarse_res, args.fine_res)

    print("シナリオ:", args.scenario)
    print("解析範囲レイヤ:", mask_layer_key, "->", mask_resource.path.name, mask_resource.layer_name)
    print("解析BBox(EPSG:3405):", analysis_bbox)
    print("coarse shape:", grid_spec.coarse_shape, "resolution:", grid_spec.coarse_res_m, "m")

    building_resource = get_optional_layer_resource(city_cfg, scenario_cfg["buildings"])
    road_resource = get_optional_layer_resource(city_cfg, scenario_cfg["roads"])
    water_resource = get_optional_layer_resource(city_cfg, scenario_cfg["water"])
    green_resource = get_optional_layer_resource(city_cfg, scenario_cfg["green"])
    elevation_resource = get_optional_layer_resource(city_cfg, scenario_cfg["elevation"])
    output_columns: dict[str, np.ndarray] = {}
    quality_arrays: list[np.ndarray] = []

    print("[1/6] BUILD_COV_0 を算出中...")
    if building_resource is not None:
        build_cov = compute_polygon_coverage(building_resource, analysis_bbox, grid_spec)
        output_columns["BUILD_COV_0"] = build_cov
        quality_arrays.append(build_cov)
    else:
        print("BUILD_COV_0 は入力レイヤ未指定のため出力しません。")

    print("[2/6] BUILD_DEN_0 を算出中...")
    if building_resource is not None:
        build_den = count_polygon_centroids(building_resource, analysis_bbox, grid_spec)
        output_columns["BUILD_DEN_0"] = build_den
        quality_arrays.append(build_den)
    else:
        print("BUILD_DEN_0 は入力レイヤ未指定のため出力しません。")

    print("[3/6] ROAD_DEN_0 を算出中...")
    if road_resource is not None:
        road_den = compute_line_density(road_resource, analysis_bbox, grid_spec)
        output_columns["ROAD_DEN_0"] = road_den
        quality_arrays.append(road_den)
    else:
        print("ROAD_DEN_0 は入力レイヤ未指定のため出力しません。")

    print("[4/6] WATER_COV_0 を算出中...")
    if water_resource is not None:
        water_cov = compute_polygon_coverage(water_resource, analysis_bbox, grid_spec)
        output_columns["WATER_COV_0"] = water_cov
        quality_arrays.append(water_cov)
    else:
        print("WATER_COV_0 は入力レイヤ未指定のため出力しません。")

    print("[5/6] GREEN_COV_0 を算出中...")
    if green_resource is not None:
        green_cov = compute_polygon_coverage(green_resource, analysis_bbox, grid_spec)
        output_columns["GREEN_COV_0"] = green_cov
        quality_arrays.append(green_cov)
    else:
        print("GREEN_COV_0 は入力レイヤ未指定のため出力しません。")

    print("[6/6] ELEV_MEAN_0 / ELEV_COUNT_0 を算出中...")
    if elevation_resource is not None:
        elev_mean, elev_count = compute_elevation_from_points(elevation_resource, analysis_bbox, grid_spec)
        output_columns["ELEV_MEAN_0"] = elev_mean
        output_columns["ELEV_COUNT_0"] = elev_count
        quality_arrays.append(elev_count)
    else:
        print("ELEV_MEAN_0 / ELEV_COUNT_0 は入力レイヤ未指定のため出力しません。")

    lon, lat = grid_centers_wgs84(grid_spec)
    analysis_mask = compute_polygon_coverage(mask_resource, analysis_bbox, grid_spec) > 0
    valid_gis_mask, missing_reason = build_quality_columns(quality_arrays, grid_spec)

    output_data: dict[str, Any] = {
        "lon": lon.ravel(),
        "lat": lat.ravel(),
    }
    for column_name, values in output_columns.items():
        output_data[column_name] = values.ravel()
    output_data.update(
        {
            "IN_ANALYSIS_AREA": analysis_mask.astype(np.int8).ravel(),
            "VALID_GIS_MASK": valid_gis_mask.ravel(),
            "MISSING_REASON": missing_reason.ravel(),
            "DATA_SOURCE": str(scenario_cfg["data_source"]),
            "SCENARIO": args.scenario,
        }
    )

    output_df = pd.DataFrame(output_data)

    if args.satellite_dir:
        satellite_path = (PROJECT_ROOT / args.satellite_dir).resolve()
        detected = find_satellite_rasters(satellite_path)
        if detected:
            print("衛星ラスタ検出:", ", ".join(sorted(detected.keys())))
            for key in RASTER_KEYS:
                raster_resource = detected.get(key)
                if raster_resource is None:
                    continue
                raster_path, band_index = raster_resource
                print(f"衛星指標 {key}_0 を集約中: {raster_path.name} band={band_index}")
                output_df[f"{key}_0"] = aggregate_raster_to_grid(raster_path, grid_spec, band_index).ravel()
        else:
            print("衛星ラスタは検出されませんでした。GIS由来列のみを出力します。")

    output_df = output_df[output_df["IN_ANALYSIS_AREA"] == 1].copy()

    out_dir = PROJECT_ROOT / "data" / "csv" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"urban_params_{args.scenario}_{args.city}.csv"
    output_df.to_csv(out_path, index=False, encoding="utf-8")

    print("出力先:", out_path)
    print_basic_summary(output_df)


if __name__ == "__main__":
    main()
