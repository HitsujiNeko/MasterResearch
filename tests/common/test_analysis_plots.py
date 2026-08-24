"""src/common/analysis_plots.py（モデル比較・重要度・Spatial CV・相関行列の可視化）のテスト。

プロット内容そのものの検証は前例が無いため作り込まず、「ファイルが生成され、
サイズが0でない」ことの確認に留める（計画書の方針）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.analysis_plots import (
    CORRELATION_ANNOTATION_MAX_FEATURES,
    save_correlation_heatmap,
    save_feature_importance_plot,
    save_model_comparison_plot,
    save_spatial_cv_plot,
)

# matplotlibのバックエンド（Agg）は tests/common/conftest.py で設定済み。


class TestSaveModelComparisonPlot:
    """save_model_comparison_plot のテスト。"""

    def test_creates_non_empty_file(self, tmp_path: Path) -> None:
        """出力画像ファイルが生成され、サイズが0でない。"""
        output_path = tmp_path / "model_comparison.png"
        metrics = {"r2": 0.8, "rmse": 1.0, "mae": 0.5}
        spatial_metrics = {"r2_mean": 0.75, "rmse_mean": 1.1, "mae_mean": 0.55}

        save_model_comparison_plot(
            output_path, metrics, metrics, spatial_metrics, spatial_metrics, "2023-07-07"
        )

        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestSaveFeatureImportancePlot:
    """save_feature_importance_plot のテスト。"""

    def test_creates_non_empty_file_with_arbitrary_feature_names(self, tmp_path: Path) -> None:
        """FEATURE_COLUMNSグローバルに依存せず、任意の特徴量名で動く。"""
        output_path = tmp_path / "feature_importance.png"
        coefficients = {"feat_a": 0.5, "feat_b": -0.3}
        importance = {"feat_a": 0.6, "feat_b": 0.4}

        save_feature_importance_plot(output_path, coefficients, importance, "2023-07-07")

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_raises_when_key_sets_differ(self, tmp_path: Path) -> None:
        """standardized_coefficientsとrf_importanceのキー集合が食い違う場合は
        素のKeyErrorではなく、原因の分かる例外にする。"""
        output_path = tmp_path / "feature_importance.png"
        coefficients = {"feat_a": 0.5, "feat_b": -0.3}
        importance = {"feat_a": 0.6, "feat_c": 0.4}

        with pytest.raises(ValueError, match="キー集合"):
            save_feature_importance_plot(output_path, coefficients, importance, "2023-07-07")


class TestSaveSpatialCvPlot:
    """save_spatial_cv_plot のテスト。"""

    def test_creates_non_empty_file(self, tmp_path: Path) -> None:
        """出力画像ファイルが生成され、サイズが0でない。"""
        output_path = tmp_path / "spatial_cv.png"
        fold_metrics_df = pd.DataFrame(
            {
                "fold": [1, 2, 3],
                "linear_r2": [0.7, 0.72, 0.68],
                "linear_rmse": [1.1, 1.0, 1.2],
                "linear_mae": [0.6, 0.55, 0.65],
                "rf_r2": [0.8, 0.78, 0.79],
                "rf_rmse": [0.9, 0.95, 0.88],
                "rf_mae": [0.5, 0.52, 0.48],
            }
        )

        save_spatial_cv_plot(output_path, fold_metrics_df)

        assert output_path.exists()
        assert output_path.stat().st_size > 0


def _make_correlation_matrix(feature_count: int) -> pd.DataFrame:
    """テスト用の対称な相関行列を組み立てる。

    Args:
        feature_count: 変数の数。
    Returns:
        対角が1、非対角が-1〜1に収まる正方の相関行列。
    """
    feature_names = [f"feat_{index}" for index in range(feature_count)]
    rng = np.random.default_rng(0)
    values = rng.uniform(-1.0, 1.0, size=(feature_count, feature_count))
    symmetric = (values + values.T) / 2.0
    np.fill_diagonal(symmetric, 1.0)
    return pd.DataFrame(symmetric, index=feature_names, columns=feature_names)


class TestSaveCorrelationHeatmap:
    """save_correlation_heatmap のテスト。"""

    def test_creates_non_empty_file_with_annotations(self, tmp_path: Path) -> None:
        """注記を書き込む変数数（上限以下）でも出力画像が生成される。"""
        output_path = tmp_path / "correlation_small.png"
        matrix = _make_correlation_matrix(CORRELATION_ANNOTATION_MAX_FEATURES)

        save_correlation_heatmap(output_path, matrix, "Pearson", "2023-07-07")

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_creates_non_empty_file_without_annotations(self, tmp_path: Path) -> None:
        """注記を省略する変数数（上限超え）でも出力画像が生成される。"""
        output_path = tmp_path / "correlation_large.png"
        matrix = _make_correlation_matrix(CORRELATION_ANNOTATION_MAX_FEATURES + 5)

        save_correlation_heatmap(output_path, matrix, "Spearman", "2023-07-07")

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_handles_nan_from_constant_column(self, tmp_path: Path) -> None:
        """定数列に由来するNaNを含んでいても描画が失敗しない。"""
        output_path = tmp_path / "correlation_nan.png"
        matrix = pd.DataFrame(
            [[1.0, 0.5, float("nan")], [0.5, 1.0, float("nan")], [float("nan")] * 3],
            index=["feat_a", "feat_b", "feat_constant"],
            columns=["feat_a", "feat_b", "feat_constant"],
        )

        save_correlation_heatmap(output_path, matrix, "Pearson", "2023-07-07")

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_raises_when_labels_are_not_square(self, tmp_path: Path) -> None:
        """行ラベルと列ラベルが食い違う場合は原因の分かる例外にする。"""
        output_path = tmp_path / "correlation_invalid.png"
        matrix = pd.DataFrame(
            [[1.0, 0.5], [0.5, 1.0]],
            index=["feat_a", "feat_b"],
            columns=["feat_a", "feat_c"],
        )

        with pytest.raises(ValueError, match="行ラベルと列ラベル"):
            save_correlation_heatmap(output_path, matrix, "Pearson", "2023-07-07")
