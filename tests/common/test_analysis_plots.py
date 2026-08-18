"""src/common/analysis_plots.py（モデル比較・重要度・Spatial CV可視化）のテスト。

プロット内容そのものの検証は前例が無いため作り込まず、「ファイルが生成され、
サイズが0でない」ことの確認に留める（計画書の方針）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.common.analysis_plots import (
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
