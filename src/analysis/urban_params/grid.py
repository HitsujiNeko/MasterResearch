"""解析グリッド（fine/coarse）の構築を扱うモジュール。

バウンディングボックス（``BBox``）と座標変換（``transform_bbox``）は
共通モジュール ``src.common.geo_metadata`` に集約している。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_origin

from src.common.geo_metadata import BBox


@dataclass(frozen=True)
class GridSpec:
    """解析グリッドの仕様を保持する。

    Attributes:
        analysis_crs: 解析用CRS（投影座標系）。
        to_wgs84: ``analysis_crs`` からWGS84への変換器。
        coarse_res_m: coarseグリッドの解像度（m）。
        fine_res_m: fineグリッドの解像度（m）。
        factor: ``coarse_res_m / fine_res_m``（整数）。
        coarse_shape: coarseグリッドの形状 (行数, 列数)。
        fine_shape: fineグリッドの形状 (行数, 列数)。
        coarse_transform: coarseグリッドのアフィン変換。
        fine_transform: fineグリッドのアフィン変換。
    """

    analysis_crs: CRS
    to_wgs84: Transformer
    coarse_res_m: float
    fine_res_m: float
    factor: int
    coarse_shape: tuple[int, int]
    fine_shape: tuple[int, int]
    coarse_transform: Affine
    fine_transform: Affine


def build_grid(
    bbox_analysis: BBox,
    analysis_crs: CRS,
    coarse_res_m: float,
    fine_res_m: float,
) -> GridSpec:
    """解析BBoxから解析用CRS上のfine/coarseグリッド仕様を構築する。

    coarse解像度がfine解像度の整数倍になるように、fineグリッドの幅・高さを
    factor（coarse_res_m / fine_res_m）の倍数まで余白を加えて調整する。

    Args:
        bbox_analysis: 解析用CRS上の解析範囲BBox。
        analysis_crs: 解析用CRS（投影座標系）。
        coarse_res_m: coarseグリッドの解像度（m）。
        fine_res_m: fineグリッドの解像度（m）。``coarse_res_m`` の約数である必要がある。

    Returns:
        構築されたfine/coarseグリッドの仕様。

    Raises:
        ValueError: 解像度が正でない場合、BBoxの幅・高さが正でない場合、
            または ``coarse_res_m`` が ``fine_res_m`` の整数倍でない場合。
    """
    if coarse_res_m <= 0 or fine_res_m <= 0:
        raise ValueError("coarse_res_m と fine_res_m は正の値で指定してください。")
    if bbox_analysis.maxx <= bbox_analysis.minx or bbox_analysis.maxy <= bbox_analysis.miny:
        raise ValueError("bbox_analysis は正の幅・高さを持つ必要があります。")

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


def grid_centers_wgs84(grid_spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """coarseグリッド各セル中心の経度・緯度配列を返す。

    Args:
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) と同じ形状の、
        各セル中心の経度配列と緯度配列の組（WGS84）。
    """
    rows, cols = grid_spec.coarse_shape

    col_indices = np.arange(cols, dtype=np.float64) + 0.5
    row_indices = np.arange(rows, dtype=np.float64) + 0.5

    xs = grid_spec.coarse_transform.c + (col_indices * grid_spec.coarse_transform.a)
    ys = grid_spec.coarse_transform.f + (row_indices * grid_spec.coarse_transform.e)

    xx, yy = np.meshgrid(xs, ys)
    lon, lat = grid_spec.to_wgs84.transform(xx, yy)
    return lon.astype(np.float64), lat.astype(np.float64)


def cell_area_ha(grid_spec: GridSpec) -> float:
    """coarseセル1つあたりの面積（ha）を返す。

    BUILD_DEN（棟数/ha）やROAD_DEN（m/ha）など、面積あたりに正規化した
    密度系パラメータをスケール間で比較可能にするために使用する。

    Args:
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        coarseセル1つあたりの面積（ha）。
    """
    return (grid_spec.coarse_res_m**2) / 10000.0
