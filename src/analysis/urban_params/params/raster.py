"""衛星指標ラスタ（NDVI/NDBI/NDWI/FVC）をグリッドへ集約するモジュール。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from ..grid import GridSpec


def aggregate_raster_to_grid(
    raster_path: Path, grid_spec: GridSpec, band_index: int = 1
) -> np.ndarray:
    """ラスタをcoarseグリッドへ平均再投影し、セル平均値を返す。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 再投影先のグリッド仕様（``coarse_transform``・``analysis_crs``を使用）。
        band_index: 読み込むバンド番号（1始まり）。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) へ平均再投影したセル値配列。
        入力ラスタのnodata・範囲外セルは ``NaN``。
    """
    dst_array = np.full(grid_spec.coarse_shape, np.nan, dtype=np.float32)

    with rasterio.open(raster_path) as src:
        # GEE出力ラスタは nodata タグが None でも NaN を実値として含む。
        nodata = src.nodata
        if nodata is None and np.issubdtype(src.dtypes[band_index - 1], np.floating):
            nodata = np.nan

        reproject(
            source=rasterio.band(src, band_index),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=grid_spec.coarse_transform,
            dst_crs=grid_spec.analysis_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
            init_dest_nodata=True,
            num_threads=2,
        )

    return dst_array.astype(np.float32)


def compute(
    raster_resources: dict[str, tuple[Path, int]],
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """検出済みの衛星指標ラスタをcoarseグリッドへ集約する。

    Args:
        raster_resources: ``io.find_satellite_rasters`` で検出した
            指標名（NDVI/NDBI/NDWI/FVC）からラスタパスとバンド番号への辞書。
        grid_spec: 集約先のグリッド仕様。

    Returns:
        指標名（サフィックス無し）から集約済みセル平均値配列への辞書。
    """
    output_columns: dict[str, np.ndarray] = {}
    for key, (raster_path, band_index) in raster_resources.items():
        output_columns[key] = aggregate_raster_to_grid(raster_path, grid_spec, band_index)
    return output_columns
