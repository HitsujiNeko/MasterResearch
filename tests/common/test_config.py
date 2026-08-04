"""config.py（共通定数）のテスト。"""

from __future__ import annotations

from src.common.config import (
    DEFAULT_HANOI_ROI_PATH,
    HANOI_UTM_CRS,
    LANDSAT_OBSERVATION_YEAR,
    PROJECT_ROOT,
    WGS84_CRS,
)


def test_project_root_points_to_repository_root() -> None:
    """PROJECT_ROOTがpyproject.tomlの存在する階層を指す。"""
    assert (PROJECT_ROOT / "pyproject.toml").exists()


def test_crs_constants() -> None:
    """CRS定数が期待するEPSGコードを持つ。"""
    assert WGS84_CRS == "EPSG:4326"
    assert HANOI_UTM_CRS == "EPSG:32648"


def test_landsat_observation_year() -> None:
    """Landsat観測年が本研究の対象年（2023年）を指す。"""
    assert LANDSAT_OBSERVATION_YEAR == 2023


def test_default_hanoi_roi_path() -> None:
    """デフォルトROIパスがPROJECT_ROOT配下の期待する相対パスを指す。"""
    assert DEFAULT_HANOI_ROI_PATH == (
        PROJECT_ROOT / "data" / "gis" / "boundaries" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
    )
