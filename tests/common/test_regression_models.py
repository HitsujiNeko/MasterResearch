"""src/common/regression_models.py（回帰モデルの学習・評価）のテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.common.regression_models import fit_linear_regression, fit_random_forest


def _make_linear_dataset(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    """feat_aの寄与がfeat_bより大きい、ノイズの少ない線形データを作る。"""
    rng = np.random.default_rng(seed)
    x = pd.DataFrame(
        {
            "feat_a": rng.normal(size=n),
            "feat_b": rng.normal(size=n),
        }
    )
    y = 2.0 * x["feat_a"] + 0.5 * x["feat_b"] + rng.normal(scale=0.01, size=n)
    return x, y


class TestFitLinearRegression:
    """fit_linear_regression のテスト。"""

    def test_uses_column_names_not_global_constant(self) -> None:
        """特徴量名はx_train.columnsから取得し、モジュールグローバルな定数に依存しない。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        result, coefficients, _ = fit_linear_regression(x_train, x_test, y_train, y_test)

        assert set(coefficients.keys()) == {"feat_a", "feat_b"}
        assert set(result["standardized_coefficients"].keys()) == {"feat_a", "feat_b"}

    def test_dominant_feature_has_larger_standardized_coefficient(self) -> None:
        """係数の大きいfeat_aの標準化係数の絶対値がfeat_bより大きくなる。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        _, coefficients, _ = fit_linear_regression(x_train, x_test, y_train, y_test)

        assert abs(coefficients["feat_a"]) > abs(coefficients["feat_b"])

    def test_fits_well_on_near_noiseless_linear_data(self) -> None:
        """ノイズの少ない線形データではR2が1に近くなる。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)

        assert result["metrics"]["r2"] > 0.99

    def test_raises_when_columns_mismatch(self) -> None:
        """x_trainとx_testの列（特徴量名）が一致しない場合は例外にする。"""
        x, y = _make_linear_dataset()
        x_train = x.iloc[:150]
        x_test = x.iloc[150:].rename(columns={"feat_a": "feat_c"})
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        with pytest.raises(ValueError, match="列"):
            fit_linear_regression(x_train, x_test, y_train, y_test)

    def test_raises_when_column_order_differs(self) -> None:
        """列の集合は同じでも順序が違う場合は例外にする。

        集合比較（set比較）に簡略化する回帰が将来入っても検知できるよう、
        列名リネームとは別に順序違いのケースを独立に検証する。
        """
        x, y = _make_linear_dataset()
        x_train = x.iloc[:150]
        x_test = x.iloc[150:][["feat_b", "feat_a"]]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        with pytest.raises(ValueError, match="列"):
            fit_linear_regression(x_train, x_test, y_train, y_test)


class TestFitRandomForest:
    """fit_random_forest のテスト。"""

    def test_uses_column_names_not_global_constant(self) -> None:
        """特徴量名はx_train.columnsから取得し、モジュールグローバルな定数に依存しない。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        _, result, importance, permutation_scores, y_pred = fit_random_forest(
            x_train, x_test, y_train, y_test, random_state=0, n_estimators=20
        )

        assert set(importance.keys()) == {"feat_a", "feat_b"}
        assert set(permutation_scores.keys()) == {"feat_a", "feat_b"}
        assert set(result["feature_importance"].keys()) == {"feat_a", "feat_b"}
        assert len(y_pred) == len(y_test)

    def test_dominant_feature_has_higher_importance(self) -> None:
        """寄与の大きいfeat_aの不純度ベース重要度がfeat_bより高くなる。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        _, _, importance, _, _ = fit_random_forest(
            x_train, x_test, y_train, y_test, random_state=0, n_estimators=50
        )

        assert importance["feat_a"] > importance["feat_b"]

    def test_same_random_state_is_reproducible(self) -> None:
        """同じrandom_stateなら学習結果（モデル・予測値）が再現される。"""
        x, y = _make_linear_dataset()
        x_train, x_test = x.iloc[:150], x.iloc[150:]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        _, result_1, _, _, y_pred_1 = fit_random_forest(
            x_train, x_test, y_train, y_test, random_state=42, n_estimators=20
        )
        _, result_2, _, _, y_pred_2 = fit_random_forest(
            x_train, x_test, y_train, y_test, random_state=42, n_estimators=20
        )

        assert result_1["metrics"] == result_2["metrics"]
        np.testing.assert_array_equal(y_pred_1, y_pred_2)

    def test_raises_when_columns_mismatch(self) -> None:
        """x_trainとx_testの列（特徴量名）が一致しない場合は例外にする。"""
        x, y = _make_linear_dataset()
        x_train = x.iloc[:150]
        x_test = x.iloc[150:].rename(columns={"feat_a": "feat_c"})
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        with pytest.raises(ValueError, match="列"):
            fit_random_forest(x_train, x_test, y_train, y_test, random_state=0, n_estimators=10)

    def test_raises_when_column_order_differs(self) -> None:
        """列の集合は同じでも順序が違う場合は例外にする（集合比較への簡略化を防ぐ）。"""
        x, y = _make_linear_dataset()
        x_train = x.iloc[:150]
        x_test = x.iloc[150:][["feat_b", "feat_a"]]
        y_train, y_test = y.iloc[:150], y.iloc[150:]

        with pytest.raises(ValueError, match="列"):
            fit_random_forest(x_train, x_test, y_train, y_test, random_state=0, n_estimators=10)
