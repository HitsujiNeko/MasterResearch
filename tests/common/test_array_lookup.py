"""array_lookup.py（添字表を安全に引くための共通ヘルパー）のテスト。"""

from __future__ import annotations

import numpy as np

from src.common.array_lookup import in_lookup_range


def test_in_range_values_are_true() -> None:
    """0以上かつ添字表のサイズ未満の値は True になる。"""
    values = np.array([0, 1, 4])

    result = in_lookup_range(values, lookup_size=5)

    assert result.tolist() == [True, True, True]


def test_out_of_range_values_are_false() -> None:
    """添字表のサイズ以上の値は False になる。"""
    values = np.array([5, 100])

    result = in_lookup_range(values, lookup_size=5)

    assert result.tolist() == [False, False]


def test_negative_values_are_false_not_negative_indexed() -> None:
    """負の値は False になる（NumPyの負インデックス解釈で「範囲内」と誤判定しない）。

    ``values < lookup_size`` だけの判定だと、負の値は常にこの不等式を満たして
    しまい「範囲内」と誤判定される。``values >= 0`` を組み合わせて弾く。
    """
    values = np.array([-1, -5])

    result = in_lookup_range(values, lookup_size=5)

    assert result.tolist() == [False, False]
