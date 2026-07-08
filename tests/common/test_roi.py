"""roi.py（ROI読み込み）のテスト。"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from src.common.roi import load_roi_geometry


def _make_roi_gdf(crs: str | None) -> gpd.GeoDataFrame:
    """テスト用の単純な矩形ROIのGeoDataFrameを作成する。"""
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    return gpd.GeoDataFrame({"id": [1]}, geometry=[polygon], crs=crs)


def test_load_roi_geometry_normalizes_and_unions(tmp_path: Path) -> None:
    """EPSG:3857のROIがEPSG:4326へ正規化され、統合ジオメトリが返る。"""
    roi_path = tmp_path / "roi.shp"
    _make_roi_gdf(crs="EPSG:3857").to_file(roi_path)

    roi_gdf, roi_union = load_roi_geometry(roi_path)

    assert roi_gdf.crs.to_string() == "EPSG:4326"
    assert roi_union.is_valid
    assert not roi_union.is_empty


def test_load_roi_geometry_file_not_found(tmp_path: Path) -> None:
    """存在しないROIファイルはFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError):
        load_roi_geometry(tmp_path / "missing.shp")


def test_load_roi_geometry_empty_raises(tmp_path: Path) -> None:
    """地物がないROIファイルはValueErrorになる。"""
    roi_path = tmp_path / "empty.shp"
    _make_roi_gdf(crs="EPSG:4326").iloc[0:0].to_file(roi_path)

    with pytest.raises(ValueError):
        load_roi_geometry(roi_path)


def test_load_roi_geometry_crs_undefined_raises(tmp_path: Path) -> None:
    """CRSが未定義のROIファイルはValueErrorになる。"""
    roi_path = tmp_path / "no_crs.shp"
    _make_roi_gdf(crs=None).to_file(roi_path)

    with pytest.raises(ValueError):
        load_roi_geometry(roi_path)
