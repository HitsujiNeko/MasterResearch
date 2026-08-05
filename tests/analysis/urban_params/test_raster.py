"""params/raster.py（衛星指標のグリッド集約）のテスト。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.params.raster import (
    aggregate_raster_to_grid,
    aggregate_valid_ratio_to_grid,
)
from src.common.geo_metadata import BBox


def _write_test_raster(
    path: Path, data: np.ndarray, transform: rasterio.Affine, crs: str = "EPSG:3857"
) -> None:
    """テスト用GeoTIFFを書き出す（nodata未設定＝GEE出力と同じ状態）。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_aggregate_raster_nan_not_propagated(tmp_path: Path) -> None:
    """nodata=NoneかつNaN混在ラスタで、有効ピクセルの平均が保持される。"""
    data = np.array(
        [
            [1.0, 2.0, 3.0, 4.0],
            [5.0, 6.0, 7.0, 8.0],
            [9.0, 10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0, np.nan],
        ],
        dtype=np.float32,
    )
    tif_path = tmp_path / "test.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, data, transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    result = aggregate_raster_to_grid(tif_path, grid_spec)

    # NaN を含まないブロック: 正確な平均値。
    assert result[0, 0] == pytest.approx(3.5, abs=0.5)
    assert result[0, 1] == pytest.approx(5.5, abs=0.5)
    assert result[1, 0] == pytest.approx(11.5, abs=0.5)
    # NaN を1ピクセル含むブロック: NaN ではなく有効値の平均。
    assert not np.isnan(result[1, 1])
    assert result[1, 1] == pytest.approx((11.0 + 12.0 + 15.0) / 3, abs=1.0)


def test_aggregate_raster_all_nan_cell_stays_nan(tmp_path: Path) -> None:
    """全ピクセルがNaNのブロックはNaNのまま残る。"""
    data = np.full((4, 4), np.nan, dtype=np.float32)
    data[0, 0] = 5.0
    tif_path = tmp_path / "all_nan.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, data, transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    result = aggregate_raster_to_grid(tif_path, grid_spec)

    assert not np.isnan(result[0, 0])
    assert np.isnan(result[0, 1])
    assert np.isnan(result[1, 1])


@pytest.mark.parametrize(
    "aggregate_function", [aggregate_raster_to_grid, aggregate_valid_ratio_to_grid]
)
@pytest.mark.parametrize("band_index", [0, 2])
def test_aggregate_rejects_out_of_range_band(
    tmp_path: Path, aggregate_function, band_index: int
) -> None:
    """バンド数を超える指定は、素のIndexErrorではなく日本語のValueErrorになる。"""
    tif_path = tmp_path / "single_band.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, np.ones((4, 4), dtype=np.float32), transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    with pytest.raises(ValueError, match="バンド番号"):
        aggregate_function(tif_path, grid_spec, band_index)
