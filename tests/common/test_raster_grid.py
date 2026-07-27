"""raster_grid.py（地理座標系ラスタのセル面積・密度換算）のテスト。

セル面積が緯度に依存することと、nodata が密度側へ正しく伝播することを確認する。
"""

from __future__ import annotations

import numpy as np
import pytest
from affine import Affine
from rasterio.transform import from_origin

from src.common.raster_grid import compute_cell_area_km2, compute_density_array

# 30 arc-sec（LandScan の 1km グリッドと同じ刻み）
PIXEL_SIZE_DEG = 1.0 / 120.0
NODATA = -9999.0


class TestComputeCellAreaKm2:
    """compute_cell_area_km2 のテスト。"""

    def test_matches_known_area_at_equator(self) -> None:
        """赤道上の 30 秒グリッドのセル面積が既知の値と一致する。"""
        transform = from_origin(0.0, PIXEL_SIZE_DEG / 2, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG)

        areas = compute_cell_area_km2(transform, height=1, width=1)

        # 赤道での経度 30 秒は約 927.66m だが、緯度 30 秒は子午線弧が短く約 921.45m。
        # セルは正方形ではないため面積は 927.66^2 ではなく約 0.8548 km² になる。
        assert areas.shape == (1, 1)
        assert areas[0, 0] == pytest.approx(0.8548, rel=1e-3)

    def test_area_decreases_toward_the_pole(self) -> None:
        """緯度が上がるほどセル面積は小さくなる（定数で割ってはいけない根拠）。"""
        transform = from_origin(105.0, 21.4, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG)

        areas = compute_cell_area_km2(transform, height=100, width=10)

        assert areas.shape == (100, 1)
        assert np.all(np.diff(areas[:, 0]) > 0)  # 南へ行くほど（＝低緯度ほど）面積が大きい

    def test_hanoi_cell_area_is_smaller_than_equator(self) -> None:
        """ハノイ（北緯約21度）のセル面積は赤道より約7%小さい。"""
        equator = compute_cell_area_km2(
            from_origin(0.0, PIXEL_SIZE_DEG / 2, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG), 1, 1
        )
        hanoi = compute_cell_area_km2(
            from_origin(105.85, 21.03, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG), 1, 1
        )

        ratio = float(hanoi[0, 0] / equator[0, 0])
        assert 0.92 < ratio < 0.94

    def test_rejects_non_positive_dimensions(self) -> None:
        """寸法が 0 以下なら例外にする。"""
        transform = from_origin(105.0, 21.0, 0.01, 0.01)

        with pytest.raises(ValueError):
            compute_cell_area_km2(transform, height=0, width=10)

    def test_rejects_rotated_grid(self) -> None:
        """回転・スキューのあるグリッドは行単位の面積計算が破綻するため弾く。"""
        rotated_transform = Affine(0.01, 0.002, 105.0, 0.002, -0.01, 21.0)

        with pytest.raises(ValueError, match="回転・スキュー"):
            compute_cell_area_km2(rotated_transform, height=10, width=10)


class TestComputeDensityArray:
    """compute_density_array のテスト。"""

    def test_divides_count_by_cell_area(self) -> None:
        """密度はカウントをセル面積（km²）で割った値になる。"""
        count_array = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
        cell_area_km2 = np.array([[0.5], [2.0]])

        density = compute_density_array(count_array, cell_area_km2, NODATA)

        assert density[0, 0] == pytest.approx(20.0)
        assert density[0, 1] == pytest.approx(40.0)
        assert density[1, 0] == pytest.approx(15.0)
        assert density[1, 1] == pytest.approx(20.0)

    def test_keeps_nodata_pixels_as_nodata(self) -> None:
        """nodata 画素は密度側でも nodata のまま残す（0 と混同しないため）。"""
        count_array = np.array([[NODATA, 5.0]], dtype=np.float32)
        cell_area_km2 = np.array([[0.5]])

        density = compute_density_array(count_array, cell_area_km2, NODATA)

        assert density[0, 0] == NODATA
        assert density[0, 1] == pytest.approx(10.0)

    def test_zero_count_stays_zero(self) -> None:
        """値 0 の画素は密度 0 になり、nodata にはならない。"""
        count_array = np.array([[0.0]], dtype=np.float32)

        density = compute_density_array(count_array, np.array([[0.5]]), NODATA)

        assert density[0, 0] == 0.0

    def test_returns_float32(self) -> None:
        """出力 dtype は float32（GeoTIFF の profile と揃える）。"""
        count_array = np.array([[1.0]], dtype=np.float32)

        density = compute_density_array(count_array, np.array([[0.5]]), NODATA)

        assert density.dtype == np.float32
