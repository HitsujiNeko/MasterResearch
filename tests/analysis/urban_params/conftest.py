"""urban_paramsパッケージのテストで共通利用するフィクスチャ。"""

from __future__ import annotations

from pathlib import Path

import fiona
import pytest
from pyproj import CRS, Transformer

from src.analysis.urban_params.io import LayerResource
from src.common.geo_metadata import BBox

# テスト用の解析範囲BBox。fine_res=10m, coarse_res=20mで factor=2 となる。
ANALYSIS_BBOX = BBox(0.0, 0.0, 80.0, 80.0)
ANALYSIS_CRS = CRS.from_epsg(3857)


def _make_layer_resource(gpkg_path: Path, layer_name: str) -> LayerResource:
    """同一CRS（恒等変換）のLayerResourceを作成する。"""
    identity = Transformer.from_crs(ANALYSIS_CRS, ANALYSIS_CRS, always_xy=True)
    return LayerResource(
        path=gpkg_path,
        layer_name=layer_name,
        source_crs=ANALYSIS_CRS,
        analysis_crs=ANALYSIS_CRS,
        to_analysis=identity,
        from_analysis=identity,
    )


@pytest.fixture()
def polygon_resource(tmp_path: Path) -> LayerResource:
    """coarseセル(0, 0)を1セル分ちょうど覆うポリゴンを持つレイヤ。"""
    gpkg_path = tmp_path / "polygons.gpkg"
    schema = {"geometry": "Polygon", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def centroid_polygon_resource(tmp_path: Path) -> LayerResource:
    """重心が既知の正方形ポリゴン群を持つレイヤ。

    coarse_res=20m のグリッドを前提に、通常セル・セル境界上・グリッド範囲外の
    3種類の重心を含める。
    """
    gpkg_path = tmp_path / "centroids.gpkg"
    schema = {"geometry": "Polygon", "properties": {}}
    # (重心X, 重心Y): 期待セルは (row, col) = (floor((80-y)/20), floor(x/20))
    centroids = [
        (10.0, 70.0),  # セル(0, 0)
        (30.0, 30.0),  # セル(2, 1)
        (20.0, 60.0),  # セル境界上 -> セル(1, 1)
        (70.0, 10.0),  # セル(3, 3)
        (90.0, 40.0),  # グリッド範囲外
    ]
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        for center_x, center_y in centroids:
            half = 4.0
            ring = [
                (center_x - half, center_y - half),
                (center_x + half, center_y - half),
                (center_x + half, center_y + half),
                (center_x - half, center_y + half),
                (center_x - half, center_y - half),
            ]
            dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def line_resource(tmp_path: Path) -> LayerResource:
    """解析範囲を横断するラインを持つレイヤ。"""
    gpkg_path = tmp_path / "lines.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 65), (80, 65)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def boundary_line_resource(tmp_path: Path) -> LayerResource:
    """coarseセル境界（y=60）上を走る水平ラインを持つレイヤ。"""
    gpkg_path = tmp_path / "boundary.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 60), (80, 60)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def diagonal_line_resource(tmp_path: Path) -> LayerResource:
    """対角線ライン (0, 0)→(80, 80) を持つレイヤ。"""
    gpkg_path = tmp_path / "diagonal.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 0), (80, 80)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")
