"""grid.py（解析グリッドの構築・座標変換）のテスト。"""

from __future__ import annotations

import pytest
from pyproj import CRS

from src.analysis.urban_params.grid import (
    build_grid,
    cell_area_ha,
    grid_centers_wgs84,
)
from src.common.geo_metadata import BBox

ANALYSIS_CRS = CRS.from_epsg(3857)


def test_build_grid_shapes_and_factor() -> None:
    """80m四方・fine=10m・coarse=20mで factor=2、coarse 4x4・fine 8x8になる。"""
    bbox = BBox(0.0, 0.0, 80.0, 80.0)

    grid_spec = build_grid(bbox, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    assert grid_spec.factor == 2
    assert grid_spec.fine_shape == (8, 8)
    assert grid_spec.coarse_shape == (4, 4)


def test_build_grid_pads_to_factor_multiple() -> None:
    """fine側がfactorの倍数に足りない場合は余白を加えて切り上げる。"""
    # 幅85m・fine=10mだとfine_width=9となり、factor=2の倍数(10)へ切り上げられる。
    bbox = BBox(0.0, 0.0, 85.0, 80.0)

    grid_spec = build_grid(bbox, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    assert grid_spec.fine_shape == (8, 10)
    assert grid_spec.coarse_shape == (4, 5)


def test_build_grid_invalid_factor_raises() -> None:
    """coarse_res_mがfine_res_mの整数倍でない場合はValueErrorになる。"""
    bbox = BBox(0.0, 0.0, 80.0, 80.0)

    with pytest.raises(ValueError):
        build_grid(bbox, ANALYSIS_CRS, coarse_res_m=15.0, fine_res_m=10.0)


def test_cell_area_ha() -> None:
    """coarseセル1辺100mなら1ha、30mなら0.09haになる。"""
    bbox = BBox(0.0, 0.0, 100.0, 100.0)

    grid_100m = build_grid(bbox, ANALYSIS_CRS, coarse_res_m=100.0, fine_res_m=10.0)
    grid_30m = build_grid(bbox, ANALYSIS_CRS, coarse_res_m=30.0, fine_res_m=10.0)

    assert cell_area_ha(grid_100m) == pytest.approx(1.0)
    assert cell_area_ha(grid_30m) == pytest.approx(0.09)


def test_grid_centers_wgs84_shape_and_order() -> None:
    """セル中心配列の形状がcoarse_shapeと一致し、列方向に経度が増加する。"""
    bbox = BBox(0.0, 0.0, 80.0, 80.0)
    grid_spec = build_grid(bbox, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    lon, lat = grid_centers_wgs84(grid_spec)

    assert lon.shape == grid_spec.coarse_shape
    assert lat.shape == grid_spec.coarse_shape
    # EPSG:3857では東に向かうほど経度が増加する。
    assert lon[0, 0] < lon[0, -1]
