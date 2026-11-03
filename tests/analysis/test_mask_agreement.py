"""mask_agreement.py（二値マスクの一致度指標）のテスト。

手計算できる小さな配列で、各指標・有効域の扱い・分母 0 の境界を確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis.mask_agreement import compute_binary_agreement


class TestComputeBinaryAgreement:
    """compute_binary_agreement のテスト。"""

    def test_matches_hand_calculation(self) -> None:
        """両方 2・A のみ 1・B のみ 3・どちらでもない 4 の配置で手計算と一致する。"""
        mask_a = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], dtype=bool)
        mask_b = np.array([1, 1, 0, 1, 1, 1, 0, 0, 0, 0], dtype=bool)
        valid = np.ones(10, dtype=bool)

        result = compute_binary_agreement(mask_a, mask_b, valid)

        assert result["both_cells"] == 2
        assert result["a_only_cells"] == 1
        assert result["b_only_cells"] == 3
        assert result["neither_cells"] == 4
        assert result["iou"] == pytest.approx(2 / 6)
        assert result["agreement_given_a"] == pytest.approx(2 / 3)
        assert result["agreement_given_b"] == pytest.approx(2 / 5)
        assert result["b_to_a_cell_ratio"] == pytest.approx(5 / 3)
        assert result["overall_agreement"] == pytest.approx(6 / 10)
        # 観測一致 0.6、偶然一致 0.3*0.5 + 0.7*0.5 = 0.5 → kappa = 0.1 / 0.5
        assert result["cohens_kappa"] == pytest.approx(0.2)

    def test_excludes_invalid_cells(self) -> None:
        """有効域外のセルは True でも数えない。"""
        mask_a = np.array([[True, True], [False, True]])
        mask_b = np.array([[True, False], [True, True]])
        valid = np.array([[True, True], [True, False]])

        result = compute_binary_agreement(mask_a, mask_b, valid)

        assert result["valid_cells"] == 3
        assert result["a_cells"] == 2
        assert result["b_cells"] == 2
        assert result["both_cells"] == 1

    def test_identical_masks_give_full_agreement(self) -> None:
        """同じマスク同士は IoU・一致率・kappa がすべて 1。"""
        mask = np.array([1, 0, 1, 0], dtype=bool)

        result = compute_binary_agreement(mask, mask, np.ones(4, dtype=bool))

        assert result["iou"] == 1.0
        assert result["agreement_given_a"] == 1.0
        assert result["cohens_kappa"] == pytest.approx(1.0)

    def test_ratios_are_none_when_denominator_is_zero(self) -> None:
        """どちらも True が無い場合、IoU・一致率・画素数比は None（0 と区別する）。"""
        empty = np.zeros(4, dtype=bool)

        result = compute_binary_agreement(empty, empty, np.ones(4, dtype=bool))

        assert result["iou"] is None
        assert result["agreement_given_a"] is None
        assert result["b_to_a_cell_ratio"] is None
        assert result["overall_agreement"] == 1.0

    def test_no_valid_cells(self) -> None:
        """有効セルが 0 の場合、全体一致率と kappa も None。"""
        mask = np.ones(3, dtype=bool)

        result = compute_binary_agreement(mask, mask, np.zeros(3, dtype=bool))

        assert result["valid_cells"] == 0
        assert result["overall_agreement"] is None
        assert result["cohens_kappa"] is None

    def test_area_is_reported_only_when_cell_area_is_given(self) -> None:
        """セル面積を渡したときだけ km² の面積を返す（30m セル 1,000 個 = 0.9 km²）。"""
        mask_a = np.ones(1000, dtype=bool)
        mask_b = np.zeros(1000, dtype=bool)
        valid = np.ones(1000, dtype=bool)

        without_area = compute_binary_agreement(mask_a, mask_b, valid)
        with_area = compute_binary_agreement(mask_a, mask_b, valid, cell_area_m2=900.0)

        assert "a_area_km2" not in without_area
        assert with_area["a_area_km2"] == pytest.approx(0.9)
        assert with_area["b_area_km2"] == 0.0

    def test_rejects_mismatched_shapes(self) -> None:
        """形状が一致しない場合は停止する。"""
        with pytest.raises(ValueError, match="形状が一致しません"):
            compute_binary_agreement(
                np.zeros(3, dtype=bool), np.zeros(4, dtype=bool), np.ones(3, dtype=bool)
            )
