"""解析グリッド（fine/coarse）の構築と座標変換を扱うモジュール。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_origin


@dataclass(frozen=True)
class BBox:
    """経緯度または投影座標系のバウンディングボックス。

    Attributes:
        minx: 最小X座標（または経度）。
        miny: 最小Y座標（または緯度）。
        maxx: 最大X座標（または経度）。
        maxy: 最大Y座標（または緯度）。
    """

    minx: float
    miny: float
    maxx: float
    maxy: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Fionaのbbox引数へ渡す形式で返す。

        Returns:
            ``(minx, miny, maxx, maxy)`` の順のタプル。
        """
        return (self.minx, self.miny, self.maxx, self.maxy)


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


def transform_bbox(bbox: BBox, transformer: Transformer) -> BBox:
    """BBoxを別の座標系へ変換する。

    BBoxの4隅すべてを変換したうえで、変換後の座標から再度
    最小・最大値を取り直す（回転を伴う変換でも矩形を保つため）。

    Args:
        bbox: 変換元の座標系上のBBox。
        transformer: 変換元から変換先座標系への変換器。

    Returns:
        変換先座標系上のBBox。
    """
    corners = [
        (bbox.minx, bbox.miny),
        (bbox.minx, bbox.maxy),
        (bbox.maxx, bbox.miny),
        (bbox.maxx, bbox.maxy),
    ]
    x_coords, y_coords = zip(*[transformer.transform(x, y) for x, y in corners])
    return BBox(min(x_coords), min(y_coords), max(x_coords), max(y_coords))


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
        ValueError: ``coarse_res_m`` が ``fine_res_m`` の整数倍でない場合。
    """
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
