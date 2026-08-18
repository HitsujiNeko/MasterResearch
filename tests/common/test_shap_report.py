"""src/common/shap_report.py（SHAP値算出・重要度表・可視化）のテスト。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestRegressor

from src.common import shap_report as shap_report_module
from src.common.shap_report import compute_shap_outputs

# matplotlibのバックエンド（Agg）は tests/common/conftest.py で設定済み。


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """shap_reportモジュールのPROJECT_ROOTをtmp_pathへ差し替える。

    compute_shap_outputsは出力パスをPROJECT_ROOTからの相対パスとして記録する
    ため、標準のtmp_path（PROJECT_ROOT外）ではrelative_to()が失敗する。
    """
    monkeypatch.setattr(shap_report_module, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _fit_small_forest(n: int = 60, seed: int = 0) -> tuple[RandomForestRegressor, pd.DataFrame]:
    """SHAP計算用の小さなRFモデルとデータを作る。"""
    rng = np.random.default_rng(seed)
    x = pd.DataFrame(
        {
            "feat_a": rng.normal(size=n),
            "feat_b": rng.normal(size=n),
        }
    )
    y = 2.0 * x["feat_a"] + 0.5 * x["feat_b"] + rng.normal(scale=0.1, size=n)
    model = RandomForestRegressor(n_estimators=10, random_state=seed, n_jobs=1)
    model.fit(x, y)
    return model, x


class TestComputeShapOutputs:
    """compute_shap_outputs のテスト。"""

    def test_creates_all_expected_output_files(self, project_root: Path) -> None:
        """CSV・summary/bar画像が生成され、サイズが0でない。"""
        model, x = _fit_small_forest()
        output_dir = project_root / "out"
        output_dir.mkdir()

        shap_result, _ = compute_shap_outputs(
            model=model,
            shap_features=x.iloc[:20],
            background_features=x.iloc[20:30],
            output_dir=output_dir,
            output_stem="test",
            observation_label="2023-07-07",
        )

        importance_path = output_dir / "test_shap_importance.csv"
        summary_path = output_dir / "test_shap_summary.png"
        bar_path = output_dir / "test_shap_bar.png"
        assert importance_path.exists()
        assert importance_path.stat().st_size > 0
        assert summary_path.exists()
        assert summary_path.stat().st_size > 0
        assert bar_path.exists()
        assert bar_path.stat().st_size > 0
        # relative_to() の区切り文字はOS依存（Windowsは \）のため、Pathで比較する。
        assert Path(shap_result["outputs"]["shap_importance_csv"]) == Path(
            "out/test_shap_importance.csv"
        )

    def test_creates_one_dependence_plot_per_feature(self, project_root: Path) -> None:
        """渡した特徴量数だけdependenceプロットが生成される。"""
        model, x = _fit_small_forest()
        output_dir = project_root / "out"
        output_dir.mkdir()

        shap_result, _ = compute_shap_outputs(
            model=model,
            shap_features=x.iloc[:20],
            background_features=x.iloc[20:30],
            output_dir=output_dir,
            output_stem="test",
            observation_label="2023-07-07",
        )

        dependence_paths = shap_result["outputs"]["shap_dependence_png"]
        assert set(dependence_paths.keys()) == {"feat_a", "feat_b"}
        for relative_path in dependence_paths.values():
            full_path = project_root / relative_path
            assert full_path.exists()
            assert full_path.stat().st_size > 0

    def test_uses_feature_names_from_columns(self, project_root: Path) -> None:
        """特徴量名はshap_features.columnsから取得し、モジュールグローバルに依存しない。"""
        model, x = _fit_small_forest()
        output_dir = project_root / "out"
        output_dir.mkdir()

        shap_result, shap_importance_df = compute_shap_outputs(
            model=model,
            shap_features=x.iloc[:20],
            background_features=x.iloc[20:30],
            output_dir=output_dir,
            output_stem="test",
            observation_label="2023-07-07",
        )

        assert set(shap_result["mean_abs_shap"].keys()) == {"feat_a", "feat_b"}
        assert set(shap_importance_df["feature"]) == {"feat_a", "feat_b"}

    def test_records_sample_and_background_sizes(self, project_root: Path) -> None:
        """sample_size・background_sizeが渡したデータ件数と一致する。"""
        model, x = _fit_small_forest()
        output_dir = project_root / "out"
        output_dir.mkdir()

        shap_result, _ = compute_shap_outputs(
            model=model,
            shap_features=x.iloc[:20],
            background_features=x.iloc[20:30],
            output_dir=output_dir,
            output_stem="test",
            observation_label="2023-07-07",
        )

        assert shap_result["sample_size"] == 20
        assert shap_result["background_size"] == 10

    def test_raises_when_shap_features_column_order_differs_from_model(
        self, project_root: Path
    ) -> None:
        """shap_featuresの列順がモデルの学習時列順と違う場合は例外にする。

        shap.TreeExplainer はモデル内部の学習時列順（位置）でSHAP値を解釈する
        ため、列順が食い違うと値とラベルの対応が黙って入れ替わる（feat_aが
        支配的なデータでも、逆転した重要度になる）。ここではエラーで検出
        されることのみを確認する。
        """
        model, x = _fit_small_forest()  # モデルは ["feat_a", "feat_b"] の順で学習済み
        output_dir = project_root / "out"
        output_dir.mkdir()
        swapped_features = x.iloc[:20][["feat_b", "feat_a"]]

        with pytest.raises(ValueError, match="shap_features"):
            compute_shap_outputs(
                model=model,
                shap_features=swapped_features,
                background_features=x.iloc[20:30],
                output_dir=output_dir,
                output_stem="test",
                observation_label="2023-07-07",
            )

    def test_raises_when_background_features_column_order_differs_from_model(
        self, project_root: Path
    ) -> None:
        """background_featuresの列順がモデルの学習時列順と違う場合も例外にする。"""
        model, x = _fit_small_forest()
        output_dir = project_root / "out"
        output_dir.mkdir()
        swapped_background = x.iloc[20:30][["feat_b", "feat_a"]]

        with pytest.raises(ValueError, match="background_features"):
            compute_shap_outputs(
                model=model,
                shap_features=x.iloc[:20],
                background_features=swapped_background,
                output_dir=output_dir,
                output_stem="test",
                observation_label="2023-07-07",
            )
