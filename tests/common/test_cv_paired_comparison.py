"""src/common/cv_paired_comparison.py（fold ごとの対応のある差と信頼区間）のテスト。

区間は手計算した小さな例と突き合わせる。例: 差 d = [0.01, 0.03, 0.02, 0.04, 0.00]
（J = 5）では平均 0.02・標準偏差（J−1 で割る）√(0.001/4) = 0.0158114。
ρ = 0.25 のとき補正係数は 1/5 + 0.25 = 0.45、t(0.975, 4) = 2.776445。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.common.cv_paired_comparison import (
    FOLD_METRIC_COLUMNS,
    compute_fold_differences,
    mean_test_train_ratio,
    summarize_metric_differences,
    summarize_paired_differences,
)

DIFFERENCES = [0.01, 0.03, 0.02, 0.04, 0.00]
SD = math.sqrt(0.001 / 4)
T_975_DF4 = 2.7764451051977987


def _folds(offset: float, test_sizes: tuple[int, ...] = (20, 20, 20, 20, 20)) -> pd.DataFrame:
    """fold 別指標の合成データ（全指標に offset を足す）。"""
    n = len(test_sizes)
    frame = pd.DataFrame(
        {
            "fold": range(1, n + 1),
            "train_size": [100 - size for size in test_sizes],
            "test_size": list(test_sizes),
        }
    )
    for index, column in enumerate(FOLD_METRIC_COLUMNS):
        frame[column] = np.linspace(0.5, 0.7, n) + index + offset
    return frame


class TestSummarizePairedDifferences:
    """summarize_paired_differences のテスト（手計算との一致）。"""

    def test_single_kfold_matches_hand_calculation(self) -> None:
        """単発（J = 5）の補正係数は 1/5 + ρ、標準誤差は s·√(1/J + ρ) になる。"""
        result = summarize_paired_differences(DIFFERENCES, test_train_ratio=0.25)

        assert result["n_splits"] == 5
        assert result["degrees_of_freedom"] == 4
        assert result["mean_difference"] == pytest.approx(0.02)
        assert result["sd_difference"] == pytest.approx(SD)
        assert result["correction_factor"] == pytest.approx(0.45)
        assert result["t_quantile"] == pytest.approx(T_975_DF4)
        assert result["corrected"]["standard_error"] == pytest.approx(SD * math.sqrt(0.45))
        assert result["naive"]["standard_error"] == pytest.approx(SD / math.sqrt(5))
        half_width = T_975_DF4 * SD * math.sqrt(0.45)
        assert result["corrected"]["lower"] == pytest.approx(0.02 - half_width)
        assert result["corrected"]["upper"] == pytest.approx(0.02 + half_width)

    def test_repeated_kfold_uses_total_split_count(self) -> None:
        """反復（J = 5 × 20 = 100）では補正係数が 1/100 + ρ、自由度が 99 になる。"""
        differences = np.tile(DIFFERENCES, 20)

        result = summarize_paired_differences(differences, test_train_ratio=0.25)

        assert result["n_splits"] == 100
        assert result["degrees_of_freedom"] == 99
        assert result["correction_factor"] == pytest.approx(0.01 + 0.25)

    def test_corrected_interval_is_wider_than_naive(self) -> None:
        """補正 t 区間は素朴 t 区間より広い（fold が独立でないことを補う）。"""
        result = summarize_paired_differences(DIFFERENCES, test_train_ratio=0.25)

        naive_width = result["naive"]["upper"] - result["naive"]["lower"]
        corrected_width = result["corrected"]["upper"] - result["corrected"]["lower"]
        assert corrected_width > naive_width

    def test_single_split_has_no_interval(self) -> None:
        """差が1つでは標準偏差を求められないため、区間を None にする。"""
        result = summarize_paired_differences([0.1], test_train_ratio=0.25)

        assert result["mean_difference"] == pytest.approx(0.1)
        assert result["corrected"] is None
        assert result["naive"] is None

    def test_rejects_invalid_confidence(self) -> None:
        """信頼係数が 0〜1 の範囲外なら停止する。"""
        with pytest.raises(ValueError, match="confidence"):
            summarize_paired_differences(DIFFERENCES, 0.25, confidence=1.5)


class TestAgainstCorrectR:
    """R パッケージ correctR の出力との突き合わせ。

    参照値は R 4.5.3・correctR 0.3.1 で下記の入力から算出して固定した（テストは R に
    依存しない）。correctR は統計量と両側 p 値を返すため、平均差と補正後の標準誤差
    から同じ量を求めて比べる。呼び出しは次のとおり。

    - `resampled_ttest(x, y, n = 10, n1 = 900, n2 = 100)`
    - `repkfold_ttest(data, n1 = 80, n2 = 20, k = 5, r = 3)`
    - `resampled_ttest(x, y, n = 5, n1 = 80, n2 = 20)`（単発 5-fold 相当）
    """

    RESAMPLED_X = (0.81, 0.79, 0.84, 0.80, 0.83, 0.78, 0.82, 0.85, 0.80, 0.79)
    RESAMPLED_Y = (0.78, 0.80, 0.81, 0.77, 0.80, 0.79, 0.78, 0.83, 0.81, 0.76)
    REPEATED_X = (
        0.71, 0.74, 0.69, 0.73, 0.72, 0.70, 0.75, 0.71, 0.72, 0.73, 0.74, 0.69, 0.72, 0.70, 0.73,
    )  # fmt: skip
    REPEATED_Y = (
        0.68, 0.73, 0.70, 0.70, 0.69, 0.69, 0.71, 0.69, 0.71, 0.72, 0.70, 0.70, 0.69, 0.68, 0.71,
    )  # fmt: skip

    @staticmethod
    def _assert_matches(
        differences: np.ndarray,
        train_size: int,
        test_size: int,
        expected_statistic: float,
        expected_p_value: float,
    ) -> None:
        """統計量と両側 p 値が参照値に一致することを確かめる。

        Args:
            differences: 分割ごとの差。
            train_size: 分割ごとの学習行数。
            test_size: 分割ごとのテスト行数。
            expected_statistic: correctR の統計量。
            expected_p_value: correctR の両側 p 値。
        """
        n_splits = differences.size
        ratio = mean_test_train_ratio([train_size] * n_splits, [test_size] * n_splits)

        result = summarize_paired_differences(differences, test_train_ratio=ratio)

        statistic = result["mean_difference"] / result["corrected"]["standard_error"]
        p_value = 2.0 * stats.t.sf(abs(statistic), result["degrees_of_freedom"])
        assert statistic == pytest.approx(expected_statistic, rel=1e-12)
        assert p_value == pytest.approx(expected_p_value, rel=1e-9)

    def test_matches_resampled_ttest(self) -> None:
        """反復のないランダム分割（J = 10・ρ = 1/9）で一致する。"""
        differences = np.array(self.RESAMPLED_X) - np.array(self.RESAMPLED_Y)

        self._assert_matches(differences, 900, 100, 1.9697595514974791, 0.080373202837306201)

    def test_matches_repkfold_ttest(self) -> None:
        """反復 k-fold（k = 5・r = 3、J = 15）で一致する。"""
        differences = np.array(self.REPEATED_X) - np.array(self.REPEATED_Y)

        self._assert_matches(differences, 80, 20, 2.1369776791062982, 0.050731670734402559)

    def test_matches_resampled_ttest_for_single_kfold(self) -> None:
        """単発 5-fold 相当（J = 5・ρ = 0.25）で一致する。"""
        self._assert_matches(np.array(DIFFERENCES), 80, 20, 1.8856180831641267, 0.13241892222024934)

    def test_interval_and_p_value_lead_to_same_decision(self) -> None:
        """補正 t 区間が 0 を含むかどうかと、p 値による判定が一致する。

        反復 k-fold の参照値は p = 0.0507 なので、95% 区間は 0 を含み、90% 区間は含まない。
        """
        differences = np.array(self.REPEATED_X) - np.array(self.REPEATED_Y)

        at_95 = summarize_paired_differences(differences, 0.25)["corrected"]
        at_90 = summarize_paired_differences(differences, 0.25, confidence=0.90)["corrected"]

        assert at_95["lower"] < 0.0 < at_95["upper"]
        assert at_90["lower"] > 0.0


class TestMeanTestTrainRatio:
    """mean_test_train_ratio のテスト（ρ の求め方）。"""

    def test_uses_mean_of_per_split_ratios(self) -> None:
        """ρ は分割ごとの test/train の平均（1/(k−1) の近似ではない）。"""
        ratio = mean_test_train_ratio([80, 75], [20, 25])

        assert ratio == pytest.approx((20 / 80 + 25 / 75) / 2)

    def test_rejects_mismatched_lengths(self) -> None:
        """長さが揃わなければ停止する。"""
        with pytest.raises(ValueError, match="長さ"):
            mean_test_train_ratio([80, 75], [20])

    def test_rejects_non_positive_train_size(self) -> None:
        """学習行数が0の分割があれば停止する。"""
        with pytest.raises(ValueError, match="0以下"):
            mean_test_train_ratio([0, 75], [20, 25])


class TestComputeFoldDifferences:
    """compute_fold_differences のテスト（差の向きと対応の検査）。"""

    def test_difference_is_comparison_minus_reference(self) -> None:
        """差は「比較側 − 基準側」で、fold 順に並ぶ。"""
        reference = _folds(0.0)
        comparison = _folds(0.1).iloc[::-1]

        differences = compute_fold_differences(reference, comparison)

        assert list(differences["fold"]) == [1, 2, 3, 4, 5]
        np.testing.assert_allclose(differences["rf_r2"], 0.1)

    def test_rejects_different_test_sizes(self) -> None:
        """fold のテスト行数が違えば（同じ fold で評価していない）停止する。"""
        reference = _folds(0.0)
        comparison = _folds(0.1, test_sizes=(21, 19, 20, 20, 20))

        with pytest.raises(ValueError, match="一致しません"):
            compute_fold_differences(reference, comparison)


class TestSummarizeMetricDifferences:
    """summarize_metric_differences のテスト。"""

    def test_summarizes_every_metric_with_shared_ratio(self) -> None:
        """全指標に同じ ρ（全分割の平均）を使い、指標ごとに区間を出す。"""
        differences = compute_fold_differences(
            _folds(0.0, (20, 30, 20, 20, 10)), _folds(0.1, (20, 30, 20, 20, 10))
        )

        summary = summarize_metric_differences(differences)

        expected_ratio = np.mean(np.array([20, 30, 20, 20, 10]) / np.array([80, 70, 80, 80, 90]))
        assert summary["test_train_ratio"] == pytest.approx(expected_ratio)
        assert set(summary["metrics"]) == set(FOLD_METRIC_COLUMNS)
        assert summary["metrics"]["rf_r2"]["test_train_ratio"] == pytest.approx(expected_ratio)
