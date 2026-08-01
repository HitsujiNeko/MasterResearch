"""roi.py（ROI読み込み・ラスタ上のROIマスク生成）のテスト。"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from src.common.roi import build_raster_roi_mask, load_roi_geometry


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


class TestBuildRasterRoiMask:
    """build_raster_roi_mask のテスト。"""

    # 1画素0.1度・4×4の格子（左上が経度105.0・緯度21.0）
    PIXEL_SIZE_DEG = 0.1
    SHAPE = (4, 4)
    TRANSFORM = from_origin(105.0, 21.0, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG)

    def test_marks_only_pixels_inside_the_roi(self) -> None:
        """ROI内の画素だけがTrueになる。"""
        # 左上2×2画素ぶん（経度105.0-105.2 / 緯度20.8-21.0）を覆うROI
        roi_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 20.8, 105.2, 21.0)], crs="EPSG:4326")

        mask = build_raster_roi_mask(
            roi_gdf=roi_gdf, crs="EPSG:4326", shape=self.SHAPE, transform=self.TRANSFORM
        )

        assert mask.shape == self.SHAPE
        assert np.count_nonzero(mask) == 4
        assert mask[0, 0] and mask[1, 1]
        assert not mask[2, 2]

    def test_reprojects_roi_into_the_raster_crs(self) -> None:
        """ラスタのCRSが違う場合、ROIを変換してからラスタライズする。

        変換を忘れると例外にならないまま**全く別の場所**にマスクができるため、
        投影座標系のROIを渡して同じ位置が選ばれることを確かめる。
        """
        roi_wgs84 = gpd.GeoDataFrame(geometry=[box(105.0, 20.8, 105.2, 21.0)], crs="EPSG:4326")
        roi_projected = roi_wgs84.to_crs("EPSG:3857")

        mask_from_projected = build_raster_roi_mask(
            roi_gdf=roi_projected, crs="EPSG:4326", shape=self.SHAPE, transform=self.TRANSFORM
        )
        mask_from_wgs84 = build_raster_roi_mask(
            roi_gdf=roi_wgs84, crs="EPSG:4326", shape=self.SHAPE, transform=self.TRANSFORM
        )

        assert np.array_equal(mask_from_projected, mask_from_wgs84)

    def test_returns_all_false_when_roi_is_outside_the_raster(self) -> None:
        """ラスタ範囲外のROIでは、全画素がFalseになる（例外にはしない）。"""
        roi_gdf = gpd.GeoDataFrame(geometry=[box(100.0, 10.0, 100.1, 10.1)], crs="EPSG:4326")

        mask = build_raster_roi_mask(
            roi_gdf=roi_gdf, crs="EPSG:4326", shape=self.SHAPE, transform=self.TRANSFORM
        )

        assert not np.any(mask)
