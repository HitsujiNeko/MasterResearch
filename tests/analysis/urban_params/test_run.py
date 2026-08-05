"""run.py（オーケストレーション補助関数）のテスト。"""

from __future__ import annotations

import argparse
from pathlib import Path

import fiona
import numpy as np
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import LayerResource, RasterResource
from src.analysis.urban_params.run import (
    build_quality_columns,
    build_satellite_quality,
    run_for_scale,
)
from src.common.geo_metadata import BBox

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS, _make_layer_resource


def test_build_quality_columns_marks_cells_with_any_positive_indicator() -> None:
    """いずれかの指標が0より大きいセルのみVALID_GIS_MASK=1となる。"""
    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0
    )

    indicator_a = np.array([[0.0, 0.0], [np.nan, 0.0]], dtype=np.float32)
    indicator_b = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float32)

    valid_gis_mask, missing_reason = build_quality_columns([indicator_a, indicator_b], grid_spec)

    expected_mask = np.array([[1, 0], [0, 0]], dtype=np.int8)
    expected_reason = np.array([["none", "no_gis_feature"], ["no_gis_feature", "no_gis_feature"]])

    np.testing.assert_array_equal(valid_gis_mask, expected_mask)
    np.testing.assert_array_equal(missing_reason, expected_reason)


def test_build_satellite_quality_detects_non_nan_cells() -> None:
    """NaNでないセルがあればVALID_SATELLITE_MASK=1になる。"""
    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0
    )

    ndvi = np.array([[0.5, np.nan], [np.nan, np.nan]], dtype=np.float32)
    ndbi = np.array([[np.nan, -0.2], [np.nan, np.nan]], dtype=np.float32)

    valid_sat_mask = build_satellite_quality([ndvi, ndbi], grid_spec)

    expected = np.array([[1, 1], [0, 0]], dtype=np.int8)
    np.testing.assert_array_equal(valid_sat_mask, expected)


def test_build_satellite_quality_empty_arrays() -> None:
    """衛星指標がない場合（satellite_dir未指定）は全セル0になる。"""
    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0
    )

    valid_sat_mask = build_satellite_quality([], grid_spec)

    np.testing.assert_array_equal(valid_sat_mask, np.zeros((2, 2), dtype=np.int8))


def test_run_for_scale_returns_expected_columns(polygon_resource) -> None:
    """run_for_scaleがIN_ANALYSIS_AREA==1の行のみ返し、必須列を含む。"""
    args = argparse.Namespace(fine_res=10.0, scenario="satellite_only")
    scenario_cfg = {"data_source": "satellite"}

    df = run_for_scale(
        scale=20,
        args=args,
        scenario_cfg=scenario_cfg,
        analysis_crs=ANALYSIS_CRS,
        analysis_bbox=ANALYSIS_BBOX,
        mask_resource=polygon_resource,
        building_resource=None,
        road_resource=None,
        elevation_resource=None,
        raster_resources={},
    )

    expected_columns = {
        "lon",
        "lat",
        "IN_ANALYSIS_AREA",
        "VALID_GIS_MASK",
        "VALID_SATELLITE_MASK",
        "MISSING_REASON",
        "DATA_SOURCE",
        "SCENARIO",
    }
    assert expected_columns.issubset(set(df.columns))
    assert (df["IN_ANALYSIS_AREA"] == 1).all()
    assert len(df) > 0
    assert df["SCENARIO"].iloc[0] == "satellite_only"


def _write_elevation_raster(path: Path, value: float = 30.0) -> RasterResource:
    """解析範囲全体を一定標高で覆うDEMを書き出し、RasterResourceを返す。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, 10, 10),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((8, 8), value, dtype=np.float32), 1)
    return RasterResource(path, 1)


def _write_full_extent_mask(path: Path) -> LayerResource:
    """解析範囲（0-80m四方）全体を覆うマスクポリゴンを書き出す。

    建物が存在しないセルも ``IN_ANALYSIS_AREA == 1`` として残すために使う。
    """
    ring = [(0.0, 0.0), (80.0, 0.0), (80.0, 80.0), (0.0, 80.0), (0.0, 0.0)]
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {}},
    ) as dst:
        dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})
    return _make_layer_resource(path, "data")


def _run_limited_like(
    elevation_resource: RasterResource | None,
    building_resource: LayerResource,
    mask_resource: LayerResource,
):
    """limited相当（建物レイヤ＋DEMラスタ）の構成で run_for_scale を実行する。"""
    return run_for_scale(
        scale=20,
        args=argparse.Namespace(fine_res=10.0, scenario="limited"),
        scenario_cfg={"data_source": "open_gis"},
        analysis_crs=ANALYSIS_CRS,
        analysis_bbox=ANALYSIS_BBOX,
        mask_resource=mask_resource,
        building_resource=building_resource,
        road_resource=None,
        elevation_resource=elevation_resource,
        raster_resources={},
    )


def test_run_for_scale_outputs_elevation_column(tmp_path: Path, building_resource) -> None:
    """DEMラスタを渡すとELEV_MEAN_{scale}列が出力される。"""
    elevation_resource = _write_elevation_raster(tmp_path / "dem.tif")
    mask_resource = _write_full_extent_mask(tmp_path / "mask.gpkg")

    df = _run_limited_like(elevation_resource, building_resource, mask_resource)

    assert "ELEV_MEAN_20" in df.columns
    assert (df["ELEV_MEAN_20"] == 30.0).all()


def test_run_for_scale_elevation_does_not_affect_gis_quality(
    tmp_path: Path, building_resource
) -> None:
    """標高はVALID_GIS_MASK・MISSING_REASONの判定に影響しない。

    標高を判定に含めるとROI内のほぼ全セルが有効となり、VALID_GIS_MASKが
    「建物・道路データが存在するか」という本来の意味を失うため。
    """
    elevation_resource = _write_elevation_raster(tmp_path / "dem.tif")
    mask_resource = _write_full_extent_mask(tmp_path / "mask.gpkg")

    with_elevation = _run_limited_like(elevation_resource, building_resource, mask_resource)
    without_elevation = _run_limited_like(None, building_resource, mask_resource)

    np.testing.assert_array_equal(
        with_elevation["VALID_GIS_MASK"].to_numpy(),
        without_elevation["VALID_GIS_MASK"].to_numpy(),
    )
    np.testing.assert_array_equal(
        with_elevation["MISSING_REASON"].to_numpy(),
        without_elevation["MISSING_REASON"].to_numpy(),
    )
    # 標高列が無い側にはELEV_MEAN列自体が現れない。
    assert "ELEV_MEAN_20" not in without_elevation.columns
    # 建物が無いセルは、標高があってもVALID_GIS_MASK=0のまま。
    assert (with_elevation["VALID_GIS_MASK"] == 0).any()
