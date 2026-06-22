"""run.py（オーケストレーション補助関数）のテスト。"""

from __future__ import annotations

import argparse

import numpy as np

from src.analysis.urban_params.grid import BBox, build_grid
from src.analysis.urban_params.run import (
    build_quality_columns,
    build_satellite_quality,
    run_for_scale,
)

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS


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
