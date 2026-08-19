"""src/common/analysis_runs.py（RQ3エントリスクリプト共通の観測ラベル生成・
スケール検証・ランダム分割/Spatial CV学習パイプライン）のテスト。

`feature_columns` / `target_column` はシナリオ非依存であることを示すため、
実際のシナリオ（Satellite Only / Limited 等）の列名ではなく汎用的な名前を使う。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.analysis_runs import (
    build_observation_label,
    run_random_split_models,
    run_spatial_cv_models,
    validate_scale_matches_dataset,
)

FEATURE_COLUMNS = ["FEATURE_A", "FEATURE_B"]
TARGET_COLUMN = "TARGET_VALUE"


class TestBuildObservationLabel:
    """build_observation_label のテスト。"""

    def test_formats_date_and_time_from_output_stem(self) -> None:
        """8桁の日付・6桁の時刻を可読な形式へ整形する。"""
        label = build_observation_label("dataset_example_scenario_20230707_032329_hanoi_30m")

        assert label == "2023-07-07 03:23:29"

    def test_formats_date_and_time_with_extra_suffix(self) -> None:
        """接頭辞の末尾に追加のsuffix（例: 感度分析用の_gismask）が付いていても
        日付・時刻パターンを検出できる。
        """
        label = build_observation_label("dataset_example_20230707_032329_hanoi_30m_gismask")

        assert label == "2023-07-07 03:23:29"

    def test_returns_output_stem_when_pattern_not_found(self) -> None:
        """日付・時刻パターンが見つからない場合はoutput_stemをそのまま返す。"""
        label = build_observation_label("dataset_without_date")

        assert label == "dataset_without_date"


class TestValidateScaleMatchesDataset:
    """validate_scale_matches_dataset のテスト。"""

    def test_accepts_matching_scale(self) -> None:
        """ファイル名末尾が--scaleと一致する場合は例外にならない。"""
        path = Path("data/output/datasets/dataset_example_20230707_032329_hanoi_30m.gpkg")

        validate_scale_matches_dataset(path, scale=30)

    def test_raises_when_scale_does_not_match_filename(self) -> None:
        """ファイル名末尾が--scaleと一致しない場合はValueErrorになる。

        90mデータセットに--scale=30を指定するような設定ミスを、誤ったブロック
        サイズでSpatial CVが静かに実行される前に検出する。
        """
        path = Path("data/output/datasets/dataset_example_20230707_032329_hanoi_90m.gpkg")

        with pytest.raises(ValueError, match="--scale"):
            validate_scale_matches_dataset(path, scale=30)


def _linear_sample_dataframe(n: int = 60, seed: int = 0) -> pd.DataFrame:
    """run_random_split_models / run_spatial_cv_models 用の合成データ。

    値には多少のばらつきを持たせる（定数列だとVIF計算やRFの分岐が退化するため）。
    """
    rng = np.random.default_rng(seed)
    data = {feature: rng.normal(size=n) for feature in FEATURE_COLUMNS}
    data[TARGET_COLUMN] = rng.normal(size=n)
    return pd.DataFrame(data)


class TestRunRandomSplitModels:
    """run_random_split_models のスモークテスト。"""

    def test_returns_result_with_expected_shapes_and_keys(self) -> None:
        """train/testの分割比率、metrics・重要度辞書のキー構成を検証する。"""
        sampled = _linear_sample_dataframe(n=100)

        result = run_random_split_models(
            sampled, FEATURE_COLUMNS, TARGET_COLUMN, random_state=42, rf_trees=5
        )

        # test_size=0.2固定のため、100件なら test=20, train=80 になる。
        assert len(result.x_train) == 80
        assert len(result.x_test) == 20
        assert set(result.linear_result["metrics"].keys()) == {"r2", "rmse", "mae"}
        assert set(result.rf_result["metrics"].keys()) == {"r2", "rmse", "mae"}
        # 標準化係数・重要度はlinear_result/rf_resultの中に含まれ、専用フィールド
        # としては持たない（二重管理を避けるため）。
        assert set(result.linear_result["standardized_coefficients"].keys()) == set(FEATURE_COLUMNS)
        assert set(result.rf_result["feature_importance"].keys()) == set(FEATURE_COLUMNS)
        assert set(result.rf_result["permutation_importance"].keys()) == set(FEATURE_COLUMNS)

    def test_uses_given_feature_and_target_columns_not_a_fixed_scenario(self) -> None:
        """feature_columns/target_columnを差し替えても正しく参照する
        （モジュールグローバル定数に依存しない、シナリオ非依存の設計を検証する）。
        """
        rng = np.random.default_rng(1)
        n = 100
        sampled = pd.DataFrame(
            {
                "OTHER_FEATURE": rng.normal(size=n),
                "ANOTHER_TARGET": rng.normal(size=n),
            }
        )

        result = run_random_split_models(
            sampled, ["OTHER_FEATURE"], "ANOTHER_TARGET", random_state=42, rf_trees=5
        )

        assert list(result.x_train.columns) == ["OTHER_FEATURE"]
        assert set(result.rf_result["feature_importance"].keys()) == {"OTHER_FEATURE"}


class TestRunSpatialCvModels:
    """run_spatial_cv_models のスモークテスト（fold集計と出力契約）。"""

    def test_returns_fold_metrics_columns_expected_by_plot(self) -> None:
        """プロット関数（save_spatial_cv_plot / save_model_comparison_plot）が
        要求する列名・キー名を返す。列名の変更をここで検出する。
        """
        sampled = _linear_sample_dataframe(n=60)
        block_ids = np.repeat(np.arange(6), 10)

        summary, fold_metrics_df = run_spatial_cv_models(
            sampled,
            FEATURE_COLUMNS,
            TARGET_COLUMN,
            block_ids,
            cv_splits=3,
            random_state=42,
            rf_trees=5,
        )

        assert len(fold_metrics_df) == 3
        for column in (
            "fold",
            "train_size",
            "test_size",
            "linear_r2",
            "linear_rmse",
            "linear_mae",
            "rf_r2",
            "rf_rmse",
            "rf_mae",
        ):
            assert column in fold_metrics_df.columns
        assert "r2_mean" in summary["linear_regression"]
        assert "r2_mean" in summary["random_forest"]
        assert summary["cv_splits"] == 3
