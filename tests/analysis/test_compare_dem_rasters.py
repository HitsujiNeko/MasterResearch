"""compare_dem_rasters.py（DEM 比較スクリプト）のテスト。

相関係数の計算を対象に、参照値との突き合わせと、`None` を返す条件を確認する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import compare_dem_rasters as target


def _correlation_by_previous_formula(base_values: np.ndarray, target_values: np.ndarray) -> float:
    """置き換え前の式（平均・標準偏差・共分散）で相関係数を求める参照値。"""
    base_centered = base_values.astype(np.float64) - base_values.astype(np.float64).mean()
    target_centered = target_values.astype(np.float64) - target_values.astype(np.float64).mean()
    covariance = float(np.mean(base_centered * target_centered))
    return covariance / float(
        np.sqrt(np.mean(np.square(base_centered))) * np.sqrt(np.mean(np.square(target_centered)))
    )


def _correlated_values(size: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    """相関のある2本の標高らしい値を作る。"""
    rng = np.random.default_rng(42)
    base = 7.0 + 2.0 * rng.normal(size=size)
    return base, 0.8 * base + 3.0 + rng.normal(size=size)


class TestCalculateSafeCorrelation:
    """calculate_safe_correlation のテスト。"""

    def test_matches_previous_formula(self) -> None:
        """置き換え前の式と相対 1e-9 以内で一致する。"""
        base, other = _correlated_values()

        result = target.calculate_safe_correlation(base, other)

        assert result == pytest.approx(_correlation_by_previous_formula(base, other), rel=1e-9)

    def test_matches_numpy_corrcoef(self) -> None:
        """`np.corrcoef` と相対 1e-9 以内で一致する。"""
        base, other = _correlated_values()

        result = target.calculate_safe_correlation(base, other)

        assert result == pytest.approx(float(np.corrcoef(base, other)[0, 1]), rel=1e-9)

    def test_matches_hand_calculated_value(self) -> None:
        """手計算の値と一致する（偏差積和 7、偏差平方和 10 と 6 → 7/√60）。"""
        base = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        other = np.array([2.0, 2.0, 3.0, 3.0, 5.0])

        result = target.calculate_safe_correlation(base, other)

        assert result == pytest.approx(7.0 / math.sqrt(60.0))

    def test_float32_input_is_computed_in_float64(self) -> None:
        """float32 の入力は、同じ値を float64 で渡した場合と完全に同じ結果になる。"""
        base, other = _correlated_values()
        base32 = base.astype(np.float32)
        other32 = other.astype(np.float32)

        result = target.calculate_safe_correlation(base32, other32)

        assert result == target.calculate_safe_correlation(
            base32.astype(np.float64), other32.astype(np.float64)
        )

    def test_integer_input_matches_float_input(self) -> None:
        """整数の入力は浮動小数点の入力と同じ値になる。"""
        base = np.array([1, 5, 2, 9], dtype=np.int16)
        other = np.array([2, 4, 3, 8], dtype=np.int16)

        result = target.calculate_safe_correlation(base, other)

        assert result == pytest.approx(
            target.calculate_safe_correlation(base.astype(float), other.astype(float))
        )

    @pytest.mark.parametrize(("slope", "expected"), [(2.0, 1.0), (-3.0, -1.0)])
    def test_perfect_linear_relation(self, slope: float, expected: float) -> None:
        """完全な線形関係では相関係数が +1 または -1 になる。"""
        base, _ = _correlated_values()

        result = target.calculate_safe_correlation(base, slope * base + 1.0)

        assert result == pytest.approx(expected)

    def test_two_elements_give_unit_correlation(self) -> None:
        """2要素は最小の計算可能な長さで、相関係数は ±1 になる。"""
        result = target.calculate_safe_correlation(np.array([1.0, 2.0]), np.array([3.0, 1.0]))

        assert result == pytest.approx(-1.0)

    @pytest.mark.parametrize("scale", [1e-200, 1e200])
    def test_is_invariant_to_extreme_scale(self, scale: float) -> None:
        """極端なスケールでもアンダーフロー・オーバーフローせず同じ値になる。"""
        base, other = _correlated_values()

        result = target.calculate_safe_correlation(base * scale, other * scale)

        assert result == pytest.approx(target.calculate_safe_correlation(base, other), rel=1e-9)

    def test_returns_builtin_float(self) -> None:
        """サマリー JSON に書き出せるよう、組み込みの float を返す。"""
        base, other = _correlated_values()

        assert type(target.calculate_safe_correlation(base, other)) is float

    @pytest.mark.parametrize(
        ("base", "other"),
        [
            (np.array([]), np.array([])),
            (np.array([1.0]), np.array([2.0])),
            (np.array([1.0, 2.0]), np.array([2.0])),
        ],
        ids=["empty", "single", "one_side_single"],
    )
    def test_returns_none_when_too_few_values(self, base: np.ndarray, other: np.ndarray) -> None:
        """要素数が2未満なら計算できないため None を返す。"""
        assert target.calculate_safe_correlation(base, other) is None

    @pytest.mark.parametrize("constant", [3.0, 0.0, 0.1])
    def test_returns_none_for_constant_values(self, constant: float) -> None:
        """定数列は相関を定義できないため None を返す。

        0.1 は平均に丸め誤差が入り、分散での判定だと 0 にならない値である。
        """
        values = np.arange(7.0)
        constants = np.full(7, constant)

        assert target.calculate_safe_correlation(constants, values) is None
        assert target.calculate_safe_correlation(values, constants) is None

    def test_non_finite_values_give_nan(self) -> None:
        """NaN を含む入力は None にせず NaN を返す（呼び出し側は有効域のみを渡す）。"""
        result = target.calculate_safe_correlation(
            np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 4.0])
        )

        assert result is not None
        assert math.isnan(result)

    @pytest.mark.parametrize(
        ("base", "other"),
        [
            ([1.0, np.inf, 3.0], [1.0, 2.0, 4.0]),
            ([1.0, 2.0, 3.0], [1.0, -np.inf, 4.0]),
            ([np.inf, -np.inf, 3.0], [1.0, 2.0, 4.0]),
            ([np.inf, np.inf, np.inf], [1.0, 2.0, 4.0]),
        ],
        ids=["positive_in_base", "negative_in_other", "both_signs", "all_infinite"],
    )
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    @pytest.mark.filterwarnings("ignore::scipy.stats.ConstantInputWarning")
    def test_infinite_values_give_nan(self, base: list[float], other: list[float]) -> None:
        """無限大を含む入力も None にせず NaN を返す（呼び出し側は有効域のみを渡す）。

        値の範囲が NaN になる全要素が無限大の場合も、定数列としては扱わない。
        numpy・scipy の実行時警告が出るが、戻り値の仕様だけを固定する。
        """
        result = target.calculate_safe_correlation(np.array(base), np.array(other))

        assert result is not None
        assert math.isnan(result)

    def test_raises_when_lengths_differ(self) -> None:
        """長さが異なる配列は比較できないため例外にする。"""
        with pytest.raises(ValueError):
            target.calculate_safe_correlation(np.arange(4.0), np.arange(5.0))


class TestCalculateComparisonMetrics:
    """calculate_comparison_metrics のテスト。"""

    def test_correlation_uses_only_overlapping_pixels(self) -> None:
        """片方が欠損の画素を除いた重複域だけで相関係数を求める。"""
        base = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
        other = np.array([[2.0, 3.0], [5.0, 100.0]], dtype=np.float32)

        metrics, _ = target.calculate_comparison_metrics(base, other)

        valid_base = np.array([1.0, 2.0, 3.0])
        valid_other = np.array([2.0, 3.0, 5.0])
        assert metrics["overlap_pixel_count"] == 3
        assert metrics["correlation"] == pytest.approx(
            float(np.corrcoef(valid_base, valid_other)[0, 1])
        )

    def test_constant_overlap_gives_none_correlation(self) -> None:
        """重複域が定数なら、ほかの統計は残して相関係数だけ None にする。"""
        base = np.full((2, 2), 5.0, dtype=np.float32)
        other = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

        metrics, _ = target.calculate_comparison_metrics(base, other)

        assert metrics["correlation"] is None
        assert metrics["mean_difference"] == pytest.approx(2.5)
