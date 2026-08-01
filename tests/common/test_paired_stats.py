"""src/common/paired_stats.py（2 系列の一致度統計）のテスト。

本モジュールは人口・夜間光の比較スクリプトが共有するため、利用側スクリプトに
依存しない形で契約を固定する。とくに**相関が定義できない場合に `nan` ではなく
None を返す**ことは、サマリー JSON を RFC 8259 準拠に保つための前提であり、
利用側からは見えにくいので直接検証する。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.common.paired_stats import build_paired_statistics


class TestBuildPairedStatistics:
    """build_paired_statistics のテスト。"""

    def test_identical_series_have_no_error(self) -> None:
        """同じ系列同士なら誤差・バイアスが 0 で相関が 1 になる。"""
        values = np.array([1.0, 2.0, 3.0, 4.0])

        result = build_paired_statistics(values, values)

        assert result["cell_count"] == 4
        assert result["mean_absolute_error"] == pytest.approx(0.0)
        assert result["root_mean_squared_error"] == pytest.approx(0.0)
        assert result["mean_bias"] == pytest.approx(0.0)
        assert result["median_bias"] == pytest.approx(0.0)
        assert result["pearson_r"] == pytest.approx(1.0)
        assert result["spearman_rho"] == pytest.approx(1.0)

    def test_bias_is_comparison_minus_reference(self) -> None:
        """バイアスの符号は「比較側 − 基準側」で定義される。

        符号が逆だと「どちらが明るい/多いか」の解釈がそのまま反転するため、
        方向を明示的に固定する。
        """
        reference = np.array([1.0, 2.0, 3.0])
        comparison = np.array([2.0, 3.0, 4.0])

        result = build_paired_statistics(reference, comparison)

        assert result["mean_bias"] == pytest.approx(1.0)
        assert result["median_bias"] == pytest.approx(1.0)

    def test_reports_error_magnitudes(self) -> None:
        """MAE と RMSE を区別して算出する（外れ値の効き方が異なるため）。"""
        reference = np.array([0.0, 0.0, 0.0, 0.0])
        comparison = np.array([0.0, 0.0, 0.0, 4.0])

        result = build_paired_statistics(reference, comparison)

        assert result["mean_absolute_error"] == pytest.approx(1.0)
        assert result["root_mean_squared_error"] == pytest.approx(2.0)

    def test_negative_correlation_is_reported(self) -> None:
        """逆相関もそのまま返す（絶対値へ丸めない）。"""
        reference = np.array([1.0, 2.0, 3.0, 4.0])

        result = build_paired_statistics(reference, -reference)

        assert result["pearson_r"] == pytest.approx(-1.0)

    def test_spearman_captures_monotonic_but_nonlinear_relation(self) -> None:
        """単調だが非線形な関係では Spearman が Pearson より高くなる。"""
        reference = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        comparison = reference**3

        result = build_paired_statistics(reference, comparison)

        assert result["spearman_rho"] == pytest.approx(1.0)
        assert result["pearson_r"] < result["spearman_rho"]

    def test_empty_input_returns_zero_count_only(self) -> None:
        """空の入力では統計を捏造せず、件数 0 だけを返す。"""
        empty = np.array([])

        assert build_paired_statistics(empty, empty) == {"cell_count": 0}

    def test_single_pair_reports_reason_instead_of_nan(self) -> None:
        """1 件では相関を定義できないため、None と理由を返す。"""
        result = build_paired_statistics(np.array([10.0]), np.array([12.0]))

        assert result["pearson_r"] is None
        assert result["spearman_rho"] is None
        assert "1 件" in result["correlation_note"]
        # バイアス系は 1 件でも定義できるので算出する
        assert result["mean_bias"] == pytest.approx(2.0)

    def test_constant_series_reports_reason_instead_of_nan(self) -> None:
        """定数列では相関を定義できないため、None と理由を返す。

        scipy はこの場合 nan を返す。nan をそのまま JSON へ書くと裸の NaN になり
        RFC 8259 非準拠になるため、None へ統一していることを固定する。
        """
        result = build_paired_statistics(np.array([5.0, 5.0, 5.0]), np.array([1.0, 2.0, 3.0]))

        assert result["pearson_r"] is None
        assert result["spearman_rho"] is None
        assert "定数" in result["correlation_note"]

    def test_result_is_json_serializable_without_nan(self) -> None:
        """定数列でも裸の NaN を含まずに JSON へ書き出せる。"""
        result = build_paired_statistics(np.array([5.0, 5.0]), np.array([5.0, 5.0]))

        json.dumps(result, allow_nan=False)

    def test_raises_when_lengths_differ(self) -> None:
        """長さが違う系列は、黙って切り詰めずに例外にする。"""
        with pytest.raises(ValueError, match="要素数が一致しません"):
            build_paired_statistics(np.array([1.0, 2.0]), np.array([1.0]))
