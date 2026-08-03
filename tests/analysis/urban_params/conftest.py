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


def _write_building_layer(gpkg_path: Path, records: list[dict[str, object]]) -> None:
    """建物レイヤ（高さ・推定分散つきポリゴン）を書き出す。

    Args:
        gpkg_path: 出力先のGPKGパス。
        records: ``bounds``（minx, miny, maxx, maxy）・``height``・``var`` を
            持つ辞書のリスト。``height`` と ``var`` は ``None`` を許容する。
    """
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        for record in records:
            min_x, min_y, max_x, max_y = record["bounds"]
            ring = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
                (min_x, min_y),
            ]
            dst.write(
                {
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"height": record["height"], "var": record["var"]},
                }
            )


@pytest.fixture()
def building_resource(tmp_path: Path) -> LayerResource:
    """高さの有効・無効が混在する建物レイヤ。

    coarse_res=20m のグリッド（4x4セル）を前提に、各セルの期待値が手計算で
    確かめられるよう配置している。

    - セル(0, 0): 1セルを完全に覆う1棟。高さ10m・分散1（有効）
    - セル(0, 1): 1セルを完全に覆う1棟。高さ20m・分散-1（高さは無効）
    - セル(1, 0): 1セルを完全に覆う1棟。高さ30m・分散なし（高さは無効）
    - セル(1, 1): 1/4セル分の2棟。高さ6m・分散0 と 高さ8m・分散2（いずれも有効）
    """
    gpkg_path = tmp_path / "buildings.gpkg"
    _write_building_layer(
        gpkg_path,
        [
            {"bounds": (0.0, 60.0, 20.0, 80.0), "height": 10.0, "var": 1.0},
            {"bounds": (20.0, 60.0, 40.0, 80.0), "height": 20.0, "var": -1.0},
            {"bounds": (0.0, 40.0, 20.0, 60.0), "height": 30.0, "var": None},
            {"bounds": (20.0, 40.0, 30.0, 50.0), "height": 6.0, "var": 0.0},
            {"bounds": (30.0, 50.0, 40.0, 60.0), "height": 8.0, "var": 2.0},
        ],
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def edge_building_resource(tmp_path: Path) -> LayerResource:
    """重心がグリッド範囲外に出る建物1棟だけを持つレイヤ。

    x 60-100 / y 30-50 の建物。重心 (80, 40) の列添字は範囲外だが、
    x 60-80 の部分はグリッド内にあり被覆率には計上される。
    """
    gpkg_path = tmp_path / "edge_building.gpkg"
    _write_building_layer(
        gpkg_path, [{"bounds": (60.0, 30.0, 100.0, 50.0), "height": 12.0, "var": 1.0}]
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def mixed_geometry_building_resource(tmp_path: Path) -> LayerResource:
    """ポリゴン1件とライン1件を持つ建物レイヤ（測量GIS由来の構成を模す）。"""
    gpkg_path = tmp_path / "mixed_geometry.gpkg"
    schema = {"geometry": "Unknown", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(20, 20), (40, 40)]},
                "properties": {"height": 7.0, "var": 1.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def empty_building_resource(tmp_path: Path) -> LayerResource:
    """建物が1件も無い建物レイヤ。"""
    gpkg_path = tmp_path / "empty_buildings.gpkg"
    _write_building_layer(gpkg_path, [])
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def null_geometry_building_resource(tmp_path: Path) -> LayerResource:
    """NULLジオメトリ1件と正常なポリゴン1件を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "null_geometry.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write({"geometry": None, "properties": {"height": 99.0, "var": 1.0}})
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def negative_height_building_resource(tmp_path: Path) -> LayerResource:
    """高さが負値の建物1棟と、正常な建物1棟を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "negative_height.gpkg"
    _write_building_layer(
        gpkg_path,
        [
            {"bounds": (0.0, 60.0, 20.0, 80.0), "height": 10.0, "var": 1.0},
            {"bounds": (20.0, 60.0, 40.0, 80.0), "height": -5.0, "var": 1.0},
        ],
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def height_without_variance_resource(tmp_path: Path) -> LayerResource:
    """高さ属性はあるが推定分散を持たない建物レイヤ。"""
    gpkg_path = tmp_path / "height_only.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def invalid_building_resource(tmp_path: Path) -> LayerResource:
    """自己交差する不正ポリゴン1棟と、正常なポリゴン1棟を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "invalid_buildings.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    # 8の字型（自己交差）のリング。shapely の is_valid が偽になる。
    bowtie_ring = [(20.0, 40.0), (40.0, 60.0), (40.0, 40.0), (20.0, 60.0), (20.0, 40.0)]
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write(
            {
                "geometry": {"type": "Polygon", "coordinates": [bowtie_ring]},
                "properties": {"height": 15.0, "var": 1.0},
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
