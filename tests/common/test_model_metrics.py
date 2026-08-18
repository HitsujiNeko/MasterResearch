"""src/common/model_metrics.py（回帰モデル評価指標）のテスト。"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from src.common.model_metrics import (
    compute_metrics,
    compute_vif,
    sanitize_vif_for_json,
    summarize_metric_dicts,
)


class TestComputeMetrics:
    """compute_metrics のテスト。"""

    def test_perfect_prediction_has_zero_error(self) -> None:
        """予測が正解と完全一致すればR2=1、RMSE=MAE=0になる。"""
        y_true = pd.Series([1.0, 2.0, 3.0, 4.0])
        y_pred = np.array([1.0, 2.0, 3.0, 4.0])

        result = compute_metrics(y_true, y_pred)

        assert result["r2"] == pytest.approx(1.0)
        assert result["rmse"] == pytest.approx(0.0)
        assert result["mae"] == pytest.approx(0.0)

    def test_reports_known_error_magnitude(self) -> None:
        """既知の誤差でRMSE・MAEが期待どおりの値になる。"""
        y_true = pd.Series([0.0, 0.0, 0.0, 0.0])
        y_pred = np.array([0.0, 0.0, 0.0, 4.0])

        result = compute_metrics(y_true, y_pred)

        assert result["mae"] == pytest.approx(1.0)
        assert result["rmse"] == pytest.approx(2.0)


class TestSummarizeMetricDicts:
    """summarize_metric_dicts のテスト。"""

    def test_averages_and_std_across_folds(self) -> None:
        """fold間の平均・標準偏差を指標ごとに算出する。"""
        metric_dicts = [
            {"r2": 0.8, "rmse": 1.0, "mae": 0.5},
            {"r2": 0.6, "rmse": 3.0, "mae": 1.5},
        ]

        result = summarize_metric_dicts(metric_dicts)

        assert result["r2_mean"] == pytest.approx(0.7)
        assert result["rmse_mean"] == pytest.approx(2.0)
        assert result["mae_mean"] == pytest.approx(1.0)
        # population std（ddof=0）: [1.0, 3.0] -> std = 1.0
        assert result["rmse_std"] == pytest.approx(1.0)

    def test_single_fold_has_zero_std(self) -> None:
        """foldが1つのみなら標準偏差は0になる。"""
        result = summarize_metric_dicts([{"r2": 0.9}])

        assert result["r2_mean"] == pytest.approx(0.9)
        assert result["r2_std"] == pytest.approx(0.0)

    def test_raises_when_metric_dicts_is_empty(self) -> None:
        """fold結果が1件も無い場合は、集計を捏造せず例外にする。"""
        with pytest.raises(ValueError, match="空です"):
            summarize_metric_dicts([])


class TestComputeVif:
    """compute_vif のテスト。"""

    def test_independent_columns_have_low_vif(self) -> None:
        """互いに無相関な列はVIFが1に近い値になる。"""
        rng = np.random.default_rng(42)
        dataframe = pd.DataFrame(
            {
                "a": rng.normal(size=200),
                "b": rng.normal(size=200),
            }
        )

        result = compute_vif(dataframe)

        assert result["a"] == pytest.approx(1.0, abs=0.3)
        assert result["b"] == pytest.approx(1.0, abs=0.3)

    def test_perfectly_collinear_columns_have_infinite_vif(self) -> None:
        """完全共線（線形従属）な列はVIFがInfになる。"""
        dataframe = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [2.0, 4.0, 6.0, 8.0, 10.0],  # a の定数倍
            }
        )

        result = compute_vif(dataframe)

        assert math.isinf(result["a"])
        assert math.isinf(result["b"])

    def test_raises_when_fewer_than_two_columns(self) -> None:
        """説明変数が1列以下では比較対象がなくVIFを定義できないため例外にする。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0, 3.0]})

        with pytest.raises(ValueError, match="2列以上"):
            compute_vif(dataframe)


class TestSanitizeVifForJson:
    """sanitize_vif_for_json のテスト。"""

    def test_finite_values_are_kept_as_is(self) -> None:
        """有限値はそのまま保持し、非有限値の該当リストは空になる。"""
        result = sanitize_vif_for_json({"a": 1.5, "b": 2.0})

        assert result["vif"] == {"a": 1.5, "b": 2.0}
        assert result["vif_non_finite_features"] == []

    def test_infinite_values_become_none_and_are_recorded(self) -> None:
        """Inf値はNoneに変換され、変数名がvif_non_finite_featuresに記録される。"""
        result = sanitize_vif_for_json({"a": 1.5, "b": float("inf")})

        assert result["vif"] == {"a": 1.5, "b": None}
        assert result["vif_non_finite_features"] == ["b"]

    def test_nan_values_become_none_and_are_recorded(self) -> None:
        """NaN値もInfと同様にNoneへ変換し、別キーに記録する。"""
        result = sanitize_vif_for_json({"a": 1.5, "b": float("nan")})

        assert result["vif"] == {"a": 1.5, "b": None}
        assert result["vif_non_finite_features"] == ["b"]

    def test_result_is_json_serializable_without_nan(self) -> None:
        """Inf・NaNを含んでいても allow_nan=False でJSON化できる。"""
        result = sanitize_vif_for_json({"a": float("inf"), "b": float("nan")})

        json.dumps(result, ensure_ascii=False, allow_nan=False)
