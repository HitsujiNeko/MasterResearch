"""src/common/model_metrics.py（回帰モデル評価指標）のテスト。"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from src.common.model_metrics import (
    VIF_PERFECT_COLLINEARITY_THRESHOLD,
    compute_correlation_matrix,
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


def _vif_by_sklearn_regression(dataframe: pd.DataFrame) -> dict[str, float]:
    """置き換え前の式（sklearnの補助回帰のR²から1/(1-R²)）でVIFを求める。

    statsmodels への置き換えで値が変わらないことの参照値として残す。
    """
    vif_values: dict[str, float] = {}
    for column in dataframe.columns:
        target = dataframe[column]
        others = dataframe.drop(columns=column)
        r_squared = LinearRegression().fit(others, target).score(others, target)
        vif_values[column] = float(1.0 / (1.0 - r_squared))
    return vif_values


def _vif_by_inverse_correlation(dataframe: pd.DataFrame) -> dict[str, float]:
    """相関行列の逆行列の対角成分としてVIFを求める（回帰を使わない参照値）。"""
    inverse = np.linalg.inv(dataframe.corr().to_numpy())
    return dict(zip(dataframe.columns, np.diag(inverse).tolist(), strict=True))


def _correlated_dataframe(row_count: int = 500) -> pd.DataFrame:
    """相関のある列を含む、VIFが有限になる合成データを作る。"""
    rng = np.random.default_rng(42)
    base = rng.normal(size=row_count)
    other = rng.normal(size=row_count)
    return pd.DataFrame(
        {
            "a": base,
            "b": other,
            "c": base + 0.5 * other + rng.normal(scale=0.5, size=row_count),
            "d": 100.0 + 20.0 * base + rng.normal(scale=10.0, size=row_count),
        }
    )


class TestComputeVif:
    """compute_vif のテスト。"""

    def test_matches_previous_sklearn_implementation(self) -> None:
        """置き換え前の式と相対1e-9以内で一致する。"""
        dataframe = _correlated_dataframe()

        result = compute_vif(dataframe)

        assert result == pytest.approx(_vif_by_sklearn_regression(dataframe), rel=1e-9)

    def test_matches_inverse_correlation_diagonal(self) -> None:
        """VIFは相関行列の逆行列の対角成分に等しい（回帰によらない検算）。"""
        dataframe = _correlated_dataframe()

        result = compute_vif(dataframe)

        assert result == pytest.approx(_vif_by_inverse_correlation(dataframe), rel=1e-9)

    def test_two_columns_match_closed_form(self) -> None:
        """2変数のVIFは相関係数rから1/(1-r²)で求まる値に等しい。"""
        dataframe = _correlated_dataframe()[["a", "c"]]
        correlation = float(np.corrcoef(dataframe["a"], dataframe["c"])[0, 1])

        result = compute_vif(dataframe)

        expected = 1.0 / (1.0 - correlation**2)
        assert result["a"] == pytest.approx(expected, rel=1e-9)
        assert result["c"] == pytest.approx(expected, rel=1e-9)

    def test_is_invariant_to_extreme_column_scales(self) -> None:
        """列の桁が大きく異なっても、小さい列を無視せず正しいVIFを返す。

        VIFは列の定数倍・定数加算で変わらない。置き換え前の実装は、桁の差が約1e9を
        超えると小さい列を実質的に無視し、誤った値を返していた。
        """
        dataframe = _correlated_dataframe()
        scaled = dataframe.assign(a=dataframe["a"] * 1e6 + 1e7, b=dataframe["b"] * 1e-6)

        result = compute_vif(scaled)

        assert result == pytest.approx(compute_vif(dataframe), rel=1e-6)

    def test_constant_column_is_infinite_without_changing_others(self) -> None:
        """定数列はInfになり、残りの列のVIFは定数列が無い場合と変わらない。"""
        dataframe = _correlated_dataframe()

        result = compute_vif(dataframe.assign(constant=3.0, zeros=0.0))

        assert math.isinf(result["constant"])
        assert math.isinf(result["zeros"])
        others = {name: result[name] for name in dataframe.columns}
        assert others == pytest.approx(compute_vif(dataframe), rel=1e-12)

    def test_single_varying_column_has_vif_of_one(self) -> None:
        """定数列以外が1列だけなら、説明する列が無いためVIFは1になる。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0, 4.0, 8.0], "constant": [5.0] * 4})

        result = compute_vif(dataframe)

        assert result["a"] == pytest.approx(1.0)
        assert math.isinf(result["constant"])

    def test_all_constant_columns_are_infinite(self) -> None:
        """全列が定数でも例外にせず、全列をInfとして返す。"""
        dataframe = pd.DataFrame({"a": [1.0] * 4, "b": [2.0] * 4})

        result = compute_vif(dataframe)

        assert list(result) == ["a", "b"]
        assert all(math.isinf(value) for value in result.values())

    def test_linearly_dependent_three_columns_are_infinite(self) -> None:
        """2列の和である3列目を含むと、3列とも完全共線としてInfになる。"""
        dataframe = _correlated_dataframe()[["a", "b"]]

        result = compute_vif(dataframe.assign(total=dataframe["a"] + dataframe["b"]))

        assert all(math.isinf(value) for value in result.values())

    def test_threshold_separates_finite_and_infinite(self) -> None:
        """VIFが閾値を超えるとInfになり、下回れば有限の値のまま返す。

        `b` が `a` にノイズを足した列のとき、VIFはノイズの分散に反比例する。
        """
        dataframe = _correlated_dataframe()[["a", "b"]]
        noise_at_threshold = 1.0 / math.sqrt(VIF_PERFECT_COLLINEARITY_THRESHOLD)

        above = compute_vif(
            dataframe.assign(b=dataframe["a"] + 0.5 * noise_at_threshold * dataframe["b"])
        )
        below = compute_vif(
            dataframe.assign(b=dataframe["a"] + 2.0 * noise_at_threshold * dataframe["b"])
        )

        assert math.isinf(above["a"])
        assert 1e5 < below["a"] < VIF_PERFECT_COLLINEARITY_THRESHOLD

    def test_column_order_and_names_are_kept(self) -> None:
        """結果は入力の列順で返り、statsmodelsの定数項の既定名constとも衝突しない。"""
        dataframe = _correlated_dataframe()[["c", "a", "b"]].rename(columns={"a": "const"})

        result = compute_vif(dataframe)

        assert list(result) == ["c", "const", "b"]
        assert all(math.isfinite(value) for value in result.values())

    def test_integer_columns_match_float_columns(self) -> None:
        """整数列は浮動小数点の列と同じ値になる。"""
        dataframe = pd.DataFrame({"a": [1, 2, 3, 5, 8], "b": [2, 1, 0, 5, 7]})

        result = compute_vif(dataframe)

        assert result == pytest.approx(compute_vif(dataframe.astype(float)))

    def test_float32_input_is_computed_in_float64(self) -> None:
        """float32の入力は、同じ値をfloat64で渡した場合と完全に同じ結果になる。

        保存済みのVIFは置き換え前の実装がfloat32のまま回帰した値で、float64の値と
        相対1e-6程度異なる。置き換え後はその差が生じないことを固定する。
        """
        dataframe = _correlated_dataframe().astype("float32")

        result = compute_vif(dataframe)

        assert result == compute_vif(dataframe.astype("float64"))

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
    def test_raises_when_values_are_not_finite(self, bad_value: float) -> None:
        """欠測・無限大を含む場合は値を返さず例外にする。"""
        dataframe = pd.DataFrame({"a": [1.0, bad_value, 3.0, 4.0], "b": [2.0, 1.0, 0.0, 5.0]})

        with pytest.raises(ValueError, match="欠測・無限大"):
            compute_vif(dataframe)

    def test_raises_when_no_rows(self) -> None:
        """行が無い場合はVIFを定義できないため例外にする。"""
        dataframe = pd.DataFrame({"a": np.array([], dtype=float), "b": np.array([], dtype=float)})

        with pytest.raises(ValueError, match="1行以上"):
            compute_vif(dataframe)

    def test_raises_when_column_is_not_numeric(self) -> None:
        """数値に変換できない列を含む場合は例外にする。"""
        dataframe = pd.DataFrame({"a": ["x", "y", "z"], "b": [1.0, 2.0, 3.0]})

        with pytest.raises(ValueError):
            compute_vif(dataframe)

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


class TestComputeCorrelationMatrix:
    """compute_correlation_matrix のテスト。"""

    def test_pearson_detects_perfect_linear_relations(self) -> None:
        """完全な正相関・負相関がそれぞれ+1・-1として現れる。"""
        dataframe = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0],
                "b": [2.0, 4.0, 6.0, 8.0],
                "c": [4.0, 3.0, 2.0, 1.0],
            }
        )

        result = compute_correlation_matrix(dataframe, method="pearson")

        assert list(result.index) == ["a", "b", "c"]
        assert list(result.columns) == ["a", "b", "c"]
        assert result.loc["a", "b"] == pytest.approx(1.0)
        assert result.loc["a", "c"] == pytest.approx(-1.0)
        assert result.loc["a", "a"] == pytest.approx(1.0)

    def test_spearman_captures_monotonic_nonlinear_relation(self) -> None:
        """単調だが非線形な関係はSpearmanで1になり、Pearsonでは1未満になる。

        被覆率型の変数のように分布が偏る場合、線形相関だけでは関係を過小評価
        しうるため、2つの方法を使い分ける意味があることを確認する。
        """
        dataframe = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0],
                "b": [1.0, 8.0, 27.0, 64.0],
            }
        )

        pearson = compute_correlation_matrix(dataframe, method="pearson")
        spearman = compute_correlation_matrix(dataframe, method="spearman")

        assert spearman.loc["a", "b"] == pytest.approx(1.0)
        assert pearson.loc["a", "b"] < 1.0

    def test_constant_column_yields_nan_instead_of_zero(self) -> None:
        """分散0の列は相関が定義できないためNaNになり、無相関(0)と区別できる。"""
        dataframe = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0],
                "constant": [0.0, 0.0, 0.0, 0.0],
            }
        )

        result = compute_correlation_matrix(dataframe)

        assert math.isnan(result.loc["a", "constant"])

    def test_missing_values_use_pairwise_deletion(self) -> None:
        """欠測は変数対ごとに除外される（リストワイズ削除ではない）。

        docstringに明記した挙動を固定する。`c` の欠測行が `a`-`b` の算出から
        除外されないことで、セルごとに母数が変わることを確認する。
        """
        dataframe = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0],
                "b": [1.0, 2.0, 3.0, 400.0],
                "c": [1.0, 2.0, 3.0, float("nan")],
            }
        )

        result = compute_correlation_matrix(dataframe)

        # リストワイズ削除なら第4行が落ちて a-b は完全相関(1.0)になるはず。
        assert result.loc["a", "b"] < 1.0
        # a-c は両方が非NULLの3行だけで算出されるため完全相関になる。
        assert result.loc["a", "c"] == pytest.approx(1.0)

    def test_defaults_to_pearson(self) -> None:
        """method未指定時はPearsonと同じ結果になる。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 8.0, 27.0, 64.0]})

        assert compute_correlation_matrix(dataframe).equals(
            compute_correlation_matrix(dataframe, method="pearson")
        )

    def test_raises_for_unsupported_method(self) -> None:
        """対応外の相関係数を指定した場合は原因の分かる例外にする。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})

        with pytest.raises(ValueError, match="対応していない相関係数"):
            compute_correlation_matrix(dataframe, method="kendall")

    def test_raises_when_single_column(self) -> None:
        """1列では変数対が作れないため例外にする。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0, 3.0]})

        with pytest.raises(ValueError, match="2列以上"):
            compute_correlation_matrix(dataframe)

    def test_raises_when_non_numeric_column_included(self) -> None:
        """数値でない列が混ざった場合は原因の分かる例外にする。"""
        dataframe = pd.DataFrame({"a": [1.0, 2.0], "label": ["x", "y"]})

        with pytest.raises(ValueError, match="数値でない列"):
            compute_correlation_matrix(dataframe)
