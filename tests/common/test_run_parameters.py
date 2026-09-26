"""src/common/run_parameters.py（分析ランの実行パラメータ記録）のテスト。

記録値が実際の処理で使われる値と食い違わないこと（固定値は処理側の定数を
参照していること）、キー構成が固定されていること、JSONへ書き出せることを検証する。
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import pytest

from src.common.analysis_runs import RANDOM_SPLIT_TEST_FRACTION, run_random_split_models
from src.common.regression_models import (
    PERMUTATION_N_REPEATS,
    RF_MIN_SAMPLES_LEAF,
    fit_random_forest,
)
from src.common.run_parameters import build_run_parameters, build_run_parameters_from_args

# 記録するキーの一覧。シナリオ間で同一のキー構成を保証するため、ここで固定する。
EXPECTED_KEYS = {
    "random_state",
    "rf_trees",
    "requested_sample_size",
    "scale_m",
    "requested_shap_sample_size",
    "requested_shap_background_size",
    "random_split_test_fraction",
    "rf_min_samples_leaf",
    "permutation_n_repeats",
}


def _build_default_parameters() -> dict[str, int | float]:
    """CLI既定値相当の引数で実行パラメータ辞書を作る。"""
    return build_run_parameters(
        random_state=42,
        rf_trees=300,
        requested_sample_size=100_000,
        scale_m=30,
        requested_shap_sample_size=2_000,
        requested_shap_background_size=500,
    )


def _toy_regression_data(n: int = 100) -> pd.DataFrame:
    """固定シードの乱数で作る小規模な回帰用データ。"""
    rng = np.random.default_rng(seed=0)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": 2.0 * x1 - x2 + rng.normal(scale=0.1, size=n)})


class TestBuildRunParameters:
    """build_run_parameters のテスト。"""

    def test_has_expected_keys_only(self) -> None:
        """記録キーは固定の一覧と過不足なく一致する（シナリオ間のキー一致の前提）。"""
        assert set(_build_default_parameters()) == EXPECTED_KEYS

    def test_passes_through_cli_values(self) -> None:
        """CLI引数由来の値は、渡した値がそのまま記録される。"""
        parameters = build_run_parameters(
            random_state=7,
            rf_trees=50,
            requested_sample_size=0,
            scale_m=90,
            requested_shap_sample_size=100,
            requested_shap_background_size=20,
        )

        assert parameters["random_state"] == 7
        assert parameters["rf_trees"] == 50
        assert parameters["requested_sample_size"] == 0
        assert parameters["scale_m"] == 90
        assert parameters["requested_shap_sample_size"] == 100
        assert parameters["requested_shap_background_size"] == 20

    def test_fixed_values_reference_processing_constants(self) -> None:
        """固定値は処理側の定数と一致する（二重管理による食い違いがない）。"""
        parameters = _build_default_parameters()

        assert parameters["random_split_test_fraction"] == pytest.approx(RANDOM_SPLIT_TEST_FRACTION)
        assert parameters["rf_min_samples_leaf"] == RF_MIN_SAMPLES_LEAF
        assert parameters["permutation_n_repeats"] == PERMUTATION_N_REPEATS

    def test_fixed_values_keep_current_behavior(self) -> None:
        """定数化の前後で処理の既定値が変わっていない（0.2 / 5 / 10）。"""
        assert RANDOM_SPLIT_TEST_FRACTION == pytest.approx(0.2)
        assert RF_MIN_SAMPLES_LEAF == 5
        assert PERMUTATION_N_REPEATS == 10

    def test_recorded_min_samples_leaf_is_used_by_random_forest(self) -> None:
        """記録した min_samples_leaf が、実際に学習したRFの設定と一致する。"""
        data = _toy_regression_data()
        x, y = data[["x1", "x2"]], data["y"]

        model, _, _, _, _ = fit_random_forest(
            x.iloc[:80],
            x.iloc[80:],
            y.iloc[:80],
            y.iloc[80:],
            random_state=0,
            n_estimators=5,
            compute_permutation_importance=False,
        )

        assert model.min_samples_leaf == _build_default_parameters()["rf_min_samples_leaf"]

    def test_recorded_test_fraction_matches_random_split(self) -> None:
        """記録した評価データ割合が、実際のランダム分割の行数と一致する。"""
        data = _toy_regression_data(n=100)

        result = run_random_split_models(data, ["x1", "x2"], "y", random_state=0, rf_trees=5)

        fraction = _build_default_parameters()["random_split_test_fraction"]
        assert len(result.x_test) == round(len(data) * fraction)

    def test_is_json_serializable(self) -> None:
        """JSONへ書き出して読み戻すと同じ辞書になる（numpy型等が混入しない）。"""
        parameters = _build_default_parameters()

        assert json.loads(json.dumps(parameters)) == parameters

    def test_converts_numpy_scalars_to_builtin_types(self) -> None:
        """numpyの整数型を渡しても、Python組み込みの型で記録される。"""
        parameters = build_run_parameters(
            random_state=np.int64(1),
            rf_trees=np.int32(10),
            requested_sample_size=np.int64(10),
            scale_m=np.int64(30),
            requested_shap_sample_size=np.int64(5),
            requested_shap_background_size=np.int64(5),
        )

        assert all(type(value) in (int, float) for value in parameters.values())


class TestBuildRunParametersFromArgs:
    """build_run_parameters_from_args のテスト。"""

    def _namespace(self, **overrides: int) -> argparse.Namespace:
        """両シナリオの parse_arguments が共通に持つ引数だけを持つ名前空間を作る。"""
        values = {
            "random_state": 42,
            "rf_trees": 300,
            "sample_size": 100_000,
            "scale": 30,
            "shap_sample_size": 2_000,
            "shap_background_size": 500,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_maps_cli_argument_names_to_recorded_keys(self) -> None:
        """CLI引数名（sample_size・scale等）を記録キー（requested_sample_size・scale_m等）へ対応づける。"""
        parameters = build_run_parameters_from_args(
            self._namespace(random_state=1, rf_trees=2, sample_size=3, scale=90)
        )

        assert parameters["random_state"] == 1
        assert parameters["rf_trees"] == 2
        assert parameters["requested_sample_size"] == 3
        assert parameters["scale_m"] == 90
        assert parameters["requested_shap_sample_size"] == 2_000
        assert parameters["requested_shap_background_size"] == 500

    def test_matches_build_run_parameters(self) -> None:
        """既定値相当の引数では build_run_parameters と同じ辞書になる。"""
        assert build_run_parameters_from_args(self._namespace()) == _build_default_parameters()

    def test_raises_when_required_argument_is_missing(self) -> None:
        """必要な引数が欠けていれば、欠けた引数名を含むValueErrorを送出する。"""
        args = self._namespace()
        del args.rf_trees

        with pytest.raises(ValueError, match="rf_trees"):
            build_run_parameters_from_args(args)
