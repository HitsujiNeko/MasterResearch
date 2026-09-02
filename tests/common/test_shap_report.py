"""src/common/shap_report.py（SHAP値算出・重要度表・可視化）のテスト。"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestRegressor

from src.common.shap_report import _widen_figure_until_xlabel_fits, compute_shap_outputs

# matplotlibのバックエンド（Agg）は tests/common/conftest.py で設定済み。


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """出力先ディレクトリの基準パス。

    compute_shap_outputsはto_project_relative_string()でPROJECT_ROOT相対パスへ
    変換するが、tmp_path（PROJECT_ROOT外）に対しては絶対パスへフォールバックする
    設計のため、以前のようなPROJECT_ROOTのmonkeypatchは不要。
    """
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


def _fit_forest_with_long_feature_names(
    n: int = 120, seed: int = 0
) -> tuple[RandomForestRegressor, pd.DataFrame]:
    """x軸ラベルの見切れが起きる条件を再現するモデルとデータを作る。

    棒グラフのx軸ラベル（shapが置く定型文）は固定長なので、見切れるかどうかは
    軸の幅で決まる。軸の幅はy軸目盛ラベル（＝特徴量名）の長さに押されて狭くなる
    ため、実データと同程度に長い特徴量名を使って再現条件を作る。
    """
    feature_names = [
        "ndvi_mean",
        "ndbi_mean",
        "ndwi_mean",
        "building_height_mean",
        "road_density",
    ]
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({name: rng.normal(size=n) for name in feature_names})
    y = 2.0 * x["ndvi_mean"] + 0.5 * x["ndbi_mean"] + rng.normal(scale=0.1, size=n)
    model = RandomForestRegressor(n_estimators=10, random_state=seed, n_jobs=1)
    model.fit(x, y)
    return model, x


def _count_ink_pixels_on_side_edges(image_path: Path) -> int:
    """画像の左端・右端の列にある「背景でない画素」の数を数える。

    `bbox_inches="tight"` は描画物の外側に余白（既定0.1インチ）を付けて保存する
    ため、すべての描画物が収まっていれば左右の端の列は背景色だけになる。逆に
    軸ラベルが画像の縁で切れている場合は、端の列に文字の画素が現れる。
    """
    image = mpimg.imread(image_path)
    rgb_channels = image[:, :, :3]
    # 完全な白のみを背景とみなすと、アンチエイリアスの薄い画素を拾ってしまう。
    is_ink = (rgb_channels < 0.98).any(axis=2)
    return int(is_ink[:, 0].sum() + is_ink[:, -1].sum())


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
        # output_dirはPROJECT_ROOT外（tmp_path）のため、to_project_relative_string()は
        # 絶対パスへフォールバックする。区切り文字の差異を避けるためPathで比較する。
        assert Path(shap_result["outputs"]["shap_importance_csv"]) == importance_path.resolve()

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


class TestBarPlotXLabelFits:
    """棒グラフのx軸ラベルが保存画像に収まることのテスト。"""

    def test_bar_plot_xlabel_is_not_cut_off_at_image_edge(self, project_root: Path) -> None:
        """特徴量名が長く軸が狭い場合でも、棒グラフの軸ラベルが画像の縁で切れない。

        shapが棒グラフに置くx軸ラベルは長く、`bbox_inches="tight"` を指定しても
        matplotlib側の仕様で保存領域が横へ広がらないため、描画側でfigureを広げて
        いる。その効果を、保存画像の左右端に文字の画素が無いことで確認する。
        """
        model, x = _fit_forest_with_long_feature_names()
        output_dir = project_root / "out"
        output_dir.mkdir()

        compute_shap_outputs(
            model=model,
            shap_features=x.iloc[:40],
            background_features=x.iloc[40:60],
            output_dir=output_dir,
            output_stem="test",
            observation_label="2023-07-07",
        )

        assert _count_ink_pixels_on_side_edges(output_dir / "test_shap_bar.png") == 0

    def test_leaves_figure_width_unchanged_when_xlabel_already_fits(self) -> None:
        """ラベルが既に収まっているfigureの幅は変更しない。

        軸ラベルが短いsummary図・dependence図の見た目を、この処理が変えないこと
        を保証する。
        """
        figure = plt.figure(figsize=(8.0, 5.0))
        figure.gca().set_xlabel("short")
        figure.tight_layout()

        _widen_figure_until_xlabel_fits(figure)

        assert figure.get_size_inches()[0] == pytest.approx(8.0)
        plt.close(figure)

    def test_widens_figure_when_xlabel_overflows(self) -> None:
        """軸より横に長いラベルを与えるとfigureの幅を広げる。"""
        figure = plt.figure(figsize=(4.0, 3.0))
        figure.gca().set_xlabel("very long axis label " * 6)
        figure.tight_layout()

        _widen_figure_until_xlabel_fits(figure)

        assert figure.get_size_inches()[0] > 4.0
        plt.close(figure)

    def test_warns_when_xlabel_does_not_fit_within_iteration_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """拡張の上限に達しても収まらない場合は警告を記録する。

        収まらないまま保存すると軸ラベルが切れた画像になるため、無言で見逃さない
        ことを確認する。上限回数を0にして、収まらない状態を意図的に作る。
        """
        figure = plt.figure(figsize=(4.0, 3.0))
        figure.gca().set_xlabel("very long axis label " * 6)
        figure.tight_layout()

        with caplog.at_level(logging.WARNING, logger="src.common.shap_report"):
            _widen_figure_until_xlabel_fits(figure, max_iterations=0)

        assert "保存領域に収まりませんでした" in caplog.text
        plt.close(figure)

    def test_does_not_warn_when_xlabel_already_fits(self, caplog: pytest.LogCaptureFixture) -> None:
        """ラベルが収まっている場合は警告を出さない。"""
        figure = plt.figure(figsize=(8.0, 5.0))
        figure.gca().set_xlabel("short")
        figure.tight_layout()

        with caplog.at_level(logging.WARNING, logger="src.common.shap_report"):
            _widen_figure_until_xlabel_fits(figure)

        # 他モジュールのログを拾って偽陽性にならないよう、対象ロガーだけを見る。
        warned = [r for r in caplog.records if r.name == "src.common.shap_report"]
        assert warned == []
        plt.close(figure)
