"""src/common/spatial_points.py（空間統計の入力の検証）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from src.common.spatial_points import validate_points


def _unit_grid(n: int) -> np.ndarray:
    """1間隔の n×n 格子の座標を作る。"""
    row, col = np.divmod(np.arange(n * n), n)
    return np.column_stack((col, row)).astype(float)


class TestValidatePoints:
    """validate_points のテスト。"""

    def test_raises_on_duplicate_coords(self) -> None:
        """重複座標は距離0の組の扱いを保証できないため例外にする。"""
        with pytest.raises(ValueError, match="重複"):
            validate_points(np.zeros((2, 2)), np.array([1.0, 2.0]))

    def test_raises_on_nan(self) -> None:
        """値に NaN があると統計量が黙って壊れるため例外にする。"""
        with pytest.raises(ValueError, match="NaN"):
            validate_points(_unit_grid(2), np.array([1.0, np.nan, 2.0, 3.0]))

    def test_raises_on_length_mismatch(self) -> None:
        """座標と値の長さが違う場合は例外にする。"""
        with pytest.raises(ValueError, match="一致"):
            validate_points(_unit_grid(2), np.zeros(3))

    def test_returns_float_arrays(self) -> None:
        """整数の入力も float 配列にして返す。"""
        coords, values = validate_points(np.array([[0, 0], [1, 0]]), np.array([1, 2]))
        assert coords.dtype == float
        assert values.dtype == float
