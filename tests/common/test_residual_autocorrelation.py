"""src/common/residual_autocorrelation.py（距離帯ごとの Moran's I）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest
from esda.moran import Moran
from libpysal.weights import DistanceBand

from src.common.residual_autocorrelation import (
    CORRELOGRAM_COLUMNS,
    build_band_adjacency,
    compute_band_moran,
    compute_moran_correlogram,
)


def _unit_grid(n: int) -> np.ndarray:
    """1間隔の n×n 格子の座標を作る。"""
    row, col = np.divmod(np.arange(n * n), n)
    return np.column_stack((col, row)).astype(float)


class TestBuildBandAdjacency:
    """build_band_adjacency のテスト。"""

    def test_ring_includes_lower_and_excludes_upper(self) -> None:
        """距離がちょうど下端の組は含み、ちょうど上端の組は含まない。

        一直線上の4点（0, 1, 2, 3）で距離帯 [1, 2) を作ると、距離1の組だけが残る。
        """
        coords = np.column_stack((np.arange(4.0), np.zeros(4)))
        adjacency = build_band_adjacency(coords, 1.0, 2.0).toarray()
        expected = np.zeros((4, 4))
        for i in range(3):
            expected[i, i + 1] = expected[i + 1, i] = 1
        np.testing.assert_array_equal(adjacency, expected)

    def test_excludes_self_when_lower_is_zero(self) -> None:
        """下端0でも自分自身（距離0）は近傍に含めない。"""
        adjacency = build_band_adjacency(_unit_grid(3), 0.0, 1.5)
        assert adjacency.diagonal().sum() == 0

    @pytest.mark.parametrize(("lower", "upper"), [(-1.0, 1.0), (2.0, 2.0), (3.0, 1.0)])
    def test_raises_on_invalid_band(self, lower: float, upper: float) -> None:
        """下端が負、または上端が下端以下の距離帯は例外にする。"""
        with pytest.raises(ValueError, match="lower_m < upper_m"):
            build_band_adjacency(_unit_grid(3), lower, upper)


class TestComputeBandMoran:
    """compute_band_moran のテスト（既知パターンと検証済み実装との検算）。"""

    def test_checkerboard_is_perfectly_negative(self) -> None:
        """市松模様は上下左右の近傍で値が必ず逆になるため I = -1 になる。"""
        coords = _unit_grid(10)
        values = np.where((coords[:, 0] + coords[:, 1]) % 2 == 0, 1.0, -1.0)
        # 上端1.2で上下左右だけを近傍にする（斜め隣は距離約1.41で含まない）
        result = compute_band_moran(coords, values, 0.0, 1.2, permutations=99)
        assert result["moran_i"] == pytest.approx(-1.0)
        assert result["p_sim"] == pytest.approx(1 / 100)

    def test_gradient_is_strongly_positive(self) -> None:
        """一方向の勾配は近傍どうしの値が近いため、正の強い自己相関になる。"""
        coords = _unit_grid(10)
        result = compute_band_moran(coords, coords[:, 0], 0.0, 1.5, permutations=99)
        assert result["moran_i"] > 0.8
        assert result["p_sim"] == pytest.approx(1 / 100)

    def test_matches_distance_band_weights(self) -> None:
        """累積の距離帯は libpysal の DistanceBand（二値・行標準化）と一致する。

        上端ちょうどの距離の組が生じない乱数座標で比べる（境界の扱いだけが異なるため）。
        """
        rng = np.random.default_rng(0)
        coords = rng.uniform(0, 100, size=(300, 2))
        values = coords[:, 0] / 10 + rng.standard_normal(300)
        result = compute_band_moran(coords, values, 0.0, 15.3, permutations=0)
        weights = DistanceBand(coords, threshold=15.3, binary=True, silence_warnings=True)
        reference = Moran(values, weights, transformation="r", permutations=0)
        assert result["moran_i"] == pytest.approx(reference.I, rel=1e-12)
        assert result["z_norm"] == pytest.approx(reference.z_norm, rel=1e-9)

    def test_excludes_isolated_points(self) -> None:
        """近傍が無い点は除き、除いた数を記録する（値は孤立点が無い場合と一致）。"""
        coords = _unit_grid(5)
        values = coords[:, 0] + 0.1 * coords[:, 1]
        with_island = compute_band_moran(
            np.vstack((coords, [[100.0, 100.0]])), np.append(values, 50.0), 0.0, 1.5, 0
        )
        without_island = compute_band_moran(coords, values, 0.0, 1.5, 0)
        assert with_island["n_islands"] == 1
        assert with_island["n_points_used"] == 25
        assert with_island["moran_i"] == pytest.approx(without_island["moran_i"])

    def test_returns_nan_when_too_few_points(self) -> None:
        """孤立点を除いて3点未満なら、統計量を作らず NaN にする。"""
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 10.0]])
        result = compute_band_moran(coords, np.array([1.0, 2.0, 3.0]), 0.0, 1.5, 99)
        assert result["n_points_used"] == 2
        assert np.isnan(result["moran_i"])
        assert np.isnan(result["p_sim"])

    def test_counts_pairs_and_neighbors(self) -> None:
        """無向のペア数と平均近傍数を数える（3×3格子の上下左右は12組）。"""
        result = compute_band_moran(_unit_grid(3), np.arange(9.0), 0.0, 1.2, 0)
        assert result["n_pairs"] == 12
        assert result["mean_neighbors"] == pytest.approx(24 / 9)

    def test_seed_is_reproducible_and_restores_global_state(self) -> None:
        """同じシードで並べ替え検定が再現し、グローバル乱数の状態を変えない。"""
        rng = np.random.default_rng(1)
        coords = rng.uniform(0, 20, size=(80, 2))
        values = rng.standard_normal(80)
        np.random.seed(123)
        expected_next = np.random.random()
        np.random.seed(123)
        first = compute_band_moran(coords, values, 0.0, 5.0, permutations=99, seed=7)
        assert np.random.random() == expected_next
        second = compute_band_moran(coords, values, 0.0, 5.0, permutations=99, seed=7)
        assert first["p_sim"] == second["p_sim"]
        assert first["z_sim"] == second["z_sim"]

    def test_skips_permutation_when_zero(self) -> None:
        """並べ替え回数0では、並べ替え検定の結果を NaN にする。"""
        result = compute_band_moran(_unit_grid(4), np.arange(16.0), 0.0, 1.5, 0)
        assert np.isnan(result["p_sim"])
        assert not np.isnan(result["p_norm"])


class TestComputeMoranCorrelogram:
    """compute_moran_correlogram のテスト。"""

    def test_ring_and_cumulative_band_edges(self) -> None:
        """輪帯は前の上端を下端とし、累積は下端が常に0になる。"""
        coords = _unit_grid(6)
        values = coords[:, 0]
        ring = compute_moran_correlogram(coords, values, np.array([1.5, 3.0]), "ring", 0)
        cumulative = compute_moran_correlogram(
            coords, values, np.array([1.5, 3.0]), "cumulative", 0
        )
        assert tuple(ring.columns) == CORRELOGRAM_COLUMNS
        np.testing.assert_array_equal(ring["lag_lower_m"], [0.0, 1.5])
        np.testing.assert_array_equal(cumulative["lag_lower_m"], [0.0, 0.0])
        # 最初の帯は輪帯と累積で同じ定義になる
        assert ring["moran_i"].iloc[0] == pytest.approx(cumulative["moran_i"].iloc[0])
        assert cumulative["n_pairs"].iloc[1] > ring["n_pairs"].iloc[1]

    def test_raises_on_unknown_band_type(self) -> None:
        """未知の距離帯の種類は例外にする。"""
        with pytest.raises(ValueError, match="band_type"):
            compute_moran_correlogram(_unit_grid(3), np.arange(9.0), np.array([1.5]), "knn")
