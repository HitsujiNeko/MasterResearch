"""src/common/semivariogram.py（scikit-gstat による経験セミバリオグラム）のテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.spatial.distance import pdist

from src.common.semivariogram import (
    LAG_TABLE_COLUMNS,
    build_lag_edges,
    build_lag_table,
    compute_empirical_variogram,
    compute_semivariogram,
    find_empirical_range,
    fit_variogram_model,
)


def _hand_matheron(
    coords: np.ndarray, values: np.ndarray, lag_edges: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """全ペアから Matheron 推定量とペア数を手計算する（検算用）。"""
    distances = pdist(coords)
    diffs = pdist(values[:, None])
    lowers = np.concatenate(([0.0], lag_edges[:-1]))
    semivariance = []
    n_pairs = []
    for lower, upper in zip(lowers, lag_edges, strict=True):
        mask = (distances >= lower) & (distances < upper)
        n_pairs.append(int(mask.sum()))
        semivariance.append(0.5 * np.mean(diffs[mask] ** 2) if mask.any() else np.nan)
    return np.array(semivariance), np.array(n_pairs)


def _grid_field(seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """100m 間隔の格子上に、空間構造と雑音を持つ値を作る。"""
    rng = np.random.default_rng(seed)
    axis = np.arange(0, 3000, 100, dtype=float)
    coords = np.array([(x, y) for x in axis for y in axis])
    values = np.sin(coords[:, 0] / 700.0) + 0.3 * rng.standard_normal(len(coords))
    return coords, values


class TestBuildLagEdges:
    """build_lag_edges のテスト。"""

    def test_builds_upper_edges(self) -> None:
        """ラグの上端が幅の整数倍で最大ラグまで並ぶ。"""
        np.testing.assert_array_equal(
            build_lag_edges(900, 3600), np.array([900.0, 1800.0, 2700.0, 3600.0])
        )

    def test_raises_when_not_multiple(self) -> None:
        """最大ラグが幅の整数倍でない場合は、黙って丸めず例外にする。"""
        with pytest.raises(ValueError, match="整数倍"):
            build_lag_edges(900, 4000)

    @pytest.mark.parametrize(("width", "max_lag"), [(0, 900), (900, 0), (-900, 900)])
    def test_raises_when_not_positive(self, width: float, max_lag: float) -> None:
        """幅・最大ラグが0以下だとラグを定義できないため例外にする。"""
        with pytest.raises(ValueError, match="正の値"):
            build_lag_edges(width, max_lag)


class TestComputeEmpiricalVariogram:
    """compute_empirical_variogram のテスト（Matheron 推定量の手計算との検算）。"""

    def test_matches_hand_matheron(self) -> None:
        """ラグごとの半分散・ペア数が全ペアの手計算と一致する。

        max_dist 指定の疎行列経路でも、最大ラグ以内のペアが過不足なく
        数えられていることの検算を兼ねる。
        """
        coords, values = _grid_field()
        lag_edges = build_lag_edges(300, 1500)
        variogram = compute_empirical_variogram(coords, values, lag_edges)
        expected, expected_pairs = _hand_matheron(coords, values, lag_edges)
        np.testing.assert_allclose(variogram.experimental, expected, rtol=1e-12)
        np.testing.assert_array_equal(variogram.bin_count, expected_pairs)

    def test_lag_interval_is_left_closed_right_open(self) -> None:
        """距離がちょうど境界のペアは上側のラグに入り、最大ラグちょうどのペアは除く。

        一直線上の3点（0, 300, 600m）で、ラグ [0, 300)・[300, 600) を作る。
        距離300mの2ペア（差1と差2）は2番目のラグに入り、距離600mのペアは
        どのラグにも入らない。
        """
        coords = np.array([[0.0, 0.0], [300.0, 0.0], [600.0, 0.0]])
        values = np.array([0.0, 1.0, 3.0])
        variogram = compute_empirical_variogram(coords, values, build_lag_edges(300, 600))
        np.testing.assert_array_equal(variogram.bin_count, [0, 2])
        assert np.isnan(variogram.experimental[0])
        assert variogram.experimental[1] == pytest.approx(0.5 * (1.0**2 + 2.0**2) / 2)

    def test_raises_on_nan_value(self) -> None:
        """値に NaN があると半分散が黙って欠けるため例外にする。"""
        coords = np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 0.0]])
        with pytest.raises(ValueError, match="NaN"):
            compute_empirical_variogram(
                coords, np.array([1.0, np.nan, 2.0]), build_lag_edges(100, 300)
            )

    def test_raises_on_length_mismatch(self) -> None:
        """座標と値の長さが違う場合は例外にする。"""
        with pytest.raises(ValueError, match="一致"):
            compute_empirical_variogram(np.zeros((3, 2)), np.zeros(2), build_lag_edges(100, 300))

    def test_raises_on_duplicate_coords(self) -> None:
        """重複座標があると距離0のペアの扱いを保証できないため例外にする。"""
        coords = np.array([[0.0, 0.0], [100.0, 0.0], [0.0, 0.0]])
        with pytest.raises(ValueError, match="重複"):
            compute_empirical_variogram(
                coords, np.array([1.0, 2.0, 3.0]), build_lag_edges(100, 300)
            )

    def test_raises_on_single_point(self) -> None:
        """1点ではペアを作れないため例外にする。"""
        with pytest.raises(ValueError, match="2点以上"):
            compute_empirical_variogram(np.zeros((1, 2)), np.zeros(1), build_lag_edges(100, 300))


class TestBuildLagTable:
    """build_lag_table のテスト。"""

    def test_columns_and_values(self) -> None:
        """ラグ表の列・ラグの下端/中心・分散比が定義どおりになる。"""
        coords, values = _grid_field()
        lag_edges = build_lag_edges(300, 1500)
        variogram = compute_empirical_variogram(coords, values, lag_edges)
        table = build_lag_table(variogram, variance=2.0)
        assert tuple(table.columns) == LAG_TABLE_COLUMNS
        np.testing.assert_array_equal(table["lag_lower_m"], [0, 300, 600, 900, 1200])
        np.testing.assert_array_equal(table["lag_center_m"], [150, 450, 750, 1050, 1350])
        np.testing.assert_allclose(table["ratio_to_variance"], table["semivariance"] / 2.0)


class TestFindEmpiricalRange:
    """find_empirical_range のテスト。"""

    def test_returns_first_lag_center_reaching_ratio(self) -> None:
        """比が初めてしきい値以上になるラグの中心を返す（後で下がっても最初のもの）。"""
        table = pd.DataFrame(
            {"lag_center_m": [450.0, 1350.0, 2250.0], "ratio_to_variance": [0.5, 0.96, 0.9]}
        )
        assert find_empirical_range(table) == 1350.0

    def test_returns_none_when_not_reached(self) -> None:
        """最大ラグまでに達しない場合は値を作らず None を返す。"""
        table = pd.DataFrame({"lag_center_m": [450.0, 1350.0], "ratio_to_variance": [0.5, 0.94]})
        assert find_empirical_range(table) is None

    def test_ignores_nan_lags(self) -> None:
        """ペアが無いラグ（NaN）は到達とみなさない。"""
        table = pd.DataFrame({"lag_center_m": [450.0, 1350.0], "ratio_to_variance": [np.nan, 1.0]})
        assert find_empirical_range(table) == 1350.0


class TestFitVariogramModel:
    """fit_variogram_model のテスト。"""

    def test_detects_short_range(self) -> None:
        """最大ラグより十分短い空間構造では、range が上限に張り付かない。

        600m 四方の区画ごとに一定値を与え、区画内のペアだけ値が近い場を作る。
        """
        rng = np.random.default_rng(1)
        axis = np.arange(0, 6000, 100, dtype=float)
        coords = np.array([(x, y) for x in axis for y in axis])
        patch = (coords[:, 0] // 600) * 100 + coords[:, 1] // 600
        patch_values = rng.standard_normal(int(patch.max()) + 1)
        values = patch_values[patch.astype(int)] + 0.1 * rng.standard_normal(len(coords))
        variogram = compute_empirical_variogram(coords, values, build_lag_edges(100, 3000))
        result = fit_variogram_model(variogram, "spherical")
        assert not result["range_at_upper_bound"]
        assert 300 < result["effective_range_m"] < 1500
        assert result["total_sill"] == pytest.approx(result["partial_sill"] + result["nugget"])

    def test_flags_range_at_upper_bound(self) -> None:
        """最大ラグ内で頭打ちにならない場では、上限張り付きのフラグが立つ。"""
        coords, values = _grid_field()
        variogram = compute_empirical_variogram(coords, values, build_lag_edges(300, 1500))
        result = fit_variogram_model(variogram, "spherical")
        assert result["range_at_upper_bound"]


class TestComputeSemivariogram:
    """compute_semivariogram のテスト。"""

    def test_summary_records_conditions(self) -> None:
        """要約に測定条件・モデルごとの結果・値の定義が入る。"""
        coords, values = _grid_field()
        table, summary = compute_semivariogram(coords, values, 300, 1500)
        assert summary["n_points"] == len(values)
        assert summary["lag_width_m"] == 300.0
        assert summary["max_lag_m"] == 1500.0
        assert summary["estimator"] == "matheron"
        assert summary["variance"] == pytest.approx(np.var(values, ddof=1))
        assert summary["n_pairs_total"] == int(table["n_pairs"].sum())
        assert [m["model"] for m in summary["models"]] == ["spherical", "exponential"]
        assert {"effective_range_m", "fit_bounds"} <= set(summary["definitions"])
        assert len(table) == 5
