"""ROI（研究対象地域）の読み込み処理。

複数のデータ取得スクリプトで重複していたROI読み込み・正規化処理を集約する。
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid


def load_roi_geometry(roi_path: Path) -> tuple[gpd.GeoDataFrame, BaseGeometry]:
    """ROIのShapefileを読み込み、EPSG:4326に正規化する。

    Args:
        roi_path: ROIのShapefileパス。

    Returns:
        EPSG:4326に正規化したROIのGeoDataFrameと、その統合ジオメトリ。

    Raises:
        FileNotFoundError: ROIファイルが存在しない場合。
        ValueError: ROIファイルに地物がない場合、またはCRSが未定義の場合。
    """
    if not roi_path.exists():
        raise FileNotFoundError(f"ROIファイルが見つかりません: {roi_path}")

    roi_gdf = gpd.read_file(roi_path)
    if roi_gdf.empty:
        raise ValueError(f"ROIファイルに地物がありません: {roi_path}")
    if roi_gdf.crs is None:
        raise ValueError(f"ROIファイルのCRSが未定義です: {roi_path}")

    roi_gdf = roi_gdf.to_crs(epsg=4326)
    roi_union = roi_gdf.geometry.union_all()
    if not roi_union.is_valid:
        roi_union = make_valid(roi_union)

    return roi_gdf, roi_union
