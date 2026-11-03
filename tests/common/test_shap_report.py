"""src/common/shap_report.py（SHAP値算出・重要度表・可視化）のテスト。"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestRegressor

from src.common import shap_report
from src.common.shap_report import (
    _fixed_global_numpy_random_state,
    _measure_xlabel_overflow_inches,
    _widen_figure_until_xlabel_fits,
    compute_shap_outputs,
)

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
            random_state=0,
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
            random_state=0,
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
            random_state=0,
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
            random_state=0,
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
                random_state=0,
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
                random_state=0,
            )


def _render_shap_outputs(output_dir: Path, random_state: int) -> dict[str, bytes]:
    """同じモデル・データでSHAP出力を書き出し、ファイル名ごとのバイト列を返す。

    出力の比較に使う。散布図の点が描画順の違いで重なり方を変えられるよう、
    サンプル数を多めにとる。
    """
    model, x = _fit_small_forest(n=200)
    output_dir.mkdir()
    compute_shap_outputs(
        model=model,
        shap_features=x.iloc[:150],
        background_features=x.iloc[150:],
        output_dir=output_dir,
        output_stem="test",
        observation_label="2023-07-07",
        random_state=random_state,
    )
    return {path.name: path.read_bytes() for path in sorted(output_dir.iterdir())}


def _set_global_numpy_random_state(seed: int) -> None:
    """グローバルな `np.random` の状態を、シードから作った状態に置き換える。

    `np.random.seed()` を使うと、shap の「グローバルな乱数がシード済み」という
    判定がプロセスの終わりまで残り、後で実行される他のテストに FutureWarning を
    出させうる。`set_state()` はこの判定を変えないため、テストではこちらを使う。
    """
    np.random.set_state(np.random.RandomState(seed).get_state())


class TestShapPlotReproducibility:
    """summary図・dependence図の描画の乱数を固定することのテスト。"""

    def test_same_random_state_gives_byte_identical_images(self, project_root: Path) -> None:
        """同じ入力・同じrandom_stateなら、summary図・dependence図のPNGがバイト単位で一致する。

        shapはこれらの図の点の描画順などに乱数を使うため、固定しないと再実行の
        たびに画像が変わる。
        """
        first = _render_shap_outputs(project_root / "first", random_state=7)
        second = _render_shap_outputs(project_root / "second", random_state=7)

        compared_names = [
            "test_shap_summary.png",
            "test_shap_dependence_feat_a.png",
            "test_shap_dependence_feat_b.png",
        ]
        assert set(compared_names) <= set(first)
        for name in compared_names:
            assert first[name] == second[name], name

    def test_random_state_affects_only_point_layout(self, project_root: Path) -> None:
        """random_stateを変えても、SHAP重要度のCSVと棒グラフのPNGは変わらない。

        シードの影響が summary図・dependence図の点の並びに限られ、SHAP値や
        棒グラフには及ばないことを確かめる。あわせて、summary図はシードで
        実際に変わること（＝シードが描画に渡っていること）も確かめる。
        """
        seed_a = _render_shap_outputs(project_root / "seed_a", random_state=1)
        seed_b = _render_shap_outputs(project_root / "seed_b", random_state=2)

        assert seed_a["test_shap_importance.csv"] == seed_b["test_shap_importance.csv"]
        assert seed_a["test_shap_bar.png"] == seed_b["test_shap_bar.png"]
        assert seed_a["test_shap_summary.png"] != seed_b["test_shap_summary.png"]

    def test_does_not_change_global_numpy_random_state(self, project_root: Path) -> None:
        """compute_shap_outputsの前後で、グローバルなnp.randomの状態が変わらない。"""
        _set_global_numpy_random_state(12345)
        expected_next_values = np.random.RandomState(12345).random_sample(5)

        _render_shap_outputs(project_root / "out", random_state=7)

        np.testing.assert_array_equal(np.random.random_sample(5), expected_next_values)

    def test_does_not_emit_future_warning_when_global_rng_is_seeded(
        self, project_root: Path
    ) -> None:
        """グローバルな乱数がシード済みでも、shapのFutureWarningを出さない。

        shap は `rng` を渡されない `summary_plot` で、`np.random.seed()` 済みの
        グローバルな乱数を使うと FutureWarning を出す。summary図に `rng` を
        渡していれば、呼び出し側（他の処理）がシードしていても警告は出ない。
        この条件を作るため、ここでは意図的に `np.random.seed()` を呼ぶ。
        """
        np.random.seed(0)
        with warnings.catch_warnings():
            # 他のライブラリの将来の非推奨警告で落ちないよう、shapの警告だけをエラーにする。
            warnings.filterwarnings(
                "error",
                message="The NumPy global RNG was seeded",
                category=FutureWarning,
            )
            _render_shap_outputs(project_root / "out", random_state=7)


class TestFixedGlobalNumpyRandomState:
    """_fixed_global_numpy_random_state のテスト。"""

    def test_fixes_state_inside_block(self) -> None:
        """ブロック内の乱数列はシードだけで決まる。"""
        _set_global_numpy_random_state(1)
        with _fixed_global_numpy_random_state(99):
            first = np.random.random_sample(3)
        _set_global_numpy_random_state(2)
        with _fixed_global_numpy_random_state(99):
            second = np.random.random_sample(3)

        np.testing.assert_array_equal(first, second)

    def test_restores_state_after_exception(self) -> None:
        """ブロック内で例外が起きても、抜けた後はブロックに入る前の状態に戻る。"""
        _set_global_numpy_random_state(3)
        expected_next_values = np.random.RandomState(3).random_sample(4)

        with pytest.raises(RuntimeError):
            with _fixed_global_numpy_random_state(99):
                np.random.random_sample(10)
                raise RuntimeError("描画中の失敗を模擬")

        np.testing.assert_array_equal(np.random.random_sample(4), expected_next_values)


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
            random_state=0,
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

    def test_xlabel_fits_after_widening(self) -> None:
        """軸より横に長いラベルを与えても、処理後はラベルが保存領域に収まる。

        「幅が広がったか」ではなく「収まっているか」で確認する。matplotlib 3.11 で
        `Figure.get_tightbbox()` が軸ラベルを含めるようになり、そのバージョンでは
        見切れ自体が起きないため拡張は何もしない。どちらの挙動でも成り立つ契約は
        「処理後は収まっている」ことのほうである。
        """
        figure = plt.figure(figsize=(4.0, 3.0))
        figure.gca().set_xlabel("very long axis label " * 6)
        figure.tight_layout()

        _widen_figure_until_xlabel_fits(figure)

        overflow_inches = _measure_xlabel_overflow_inches(figure)
        assert overflow_inches is not None
        assert overflow_inches <= 0
        plt.close(figure)

    def test_warns_when_xlabel_does_not_fit_within_iteration_limit(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """拡張の上限に達しても収まらない場合は警告を記録する。

        収まらないまま保存すると軸ラベルが切れた画像になるため、無言で見逃さない
        ことを確認する。はみ出し量の測定結果は matplotlib のバージョンで変わる
        （3.11 以降は常に収まっていると返る）ため、測定を差し替えて失敗経路を
        確実に作る。上限回数は0にする。
        """
        monkeypatch.setattr(shap_report, "_measure_xlabel_overflow_inches", lambda figure: 1.0)
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
