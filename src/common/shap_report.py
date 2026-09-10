"""SHAP値の算出・重要度表・可視化画像を出力する共通モジュール。

特徴量名はモジュールグローバルな定数ではなく `shap_features.columns` から
取得するため、シナリオ（Satellite Only / Limited / Full）ごとに異なる
特徴量集合でも同じ関数を再利用できる。
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from matplotlib.figure import Figure
from sklearn.ensemble import RandomForestRegressor

from src.common.paths import to_project_relative_string

logger = logging.getLogger(__name__)


def _measure_xlabel_overflow_inches(figure: Figure) -> float | None:
    """x軸ラベルが保存領域からはみ出す量を測る。

    Args:
        figure: 対象のfigure。

    Returns:
        はみ出し量（インチ）。収まっている場合は0以下の値になる。軸が無い場合、
        またはx軸ラベルが空の場合は None。
    """
    if not figure.axes:
        return None

    # 軸ラベルの位置は描画時に確定するため、測る前に一度描画する。
    figure.canvas.draw()
    label = figure.gca().xaxis.label
    if not label.get_text():
        return None

    # rendererを省略すると、matplotlibがfigureから適切なものを取得する（特定の
    # バックエンドに依存しないよう、こちらでrendererを取り出さない）。
    # get_window_extent()はピクセル単位、get_tightbbox()はインチ単位で返る。
    label_bbox = label.get_window_extent()
    saved_bbox = figure.get_tightbbox()
    return max(
        saved_bbox.x0 - label_bbox.x0 / figure.dpi,
        label_bbox.x1 / figure.dpi - saved_bbox.x1,
    )


def _widen_figure_until_xlabel_fits(
    figure: Figure,
    max_iterations: int = 5,
    margin_inches: float = 0.05,
) -> None:
    """x軸ラベル全体が保存領域に収まるまで、figureの幅を広げる。

    `savefig(bbox_inches="tight")` は保存領域を描画物の外接矩形から決めるが、
    matplotlibは `Axes.get_tightbbox()` の内部で軸ラベルの幅を1ピクセルへ潰して
    扱う（レイアウト調整では改善できない量とみなすため）。このためx軸ラベルが
    軸より横に長い場合、`bbox_inches="tight"` を指定しても保存領域は横へ広がらず、
    ラベルの端が切れたまま保存される。figure自体を広げれば軸も広がり、ラベルが
    保存領域に収まる。

    figureを広げると軸の中心も動いてラベルの位置が変わるため、収まるまで反復する。

    **この潰す挙動は matplotlib 3.11 で変わった。** 3.11 以降は
    `Figure.get_tightbbox()` が軸ラベル全体を含めるため、`bbox_inches="tight"`
    だけで保存領域が横へ広がり、見切れ自体が起きない。その場合この関数は何も
    しない（はみ出し量が0以下と測れるため即座に戻る）。3.10 以前でも動くよう
    残してあり、両方のバージョンで「保存後にラベルが収まっている」ことは変わらない。

    Args:
        figure: 対象のfigure。呼び出し前にレイアウトを確定させておく。
        max_iterations: 幅を広げる試行の上限回数。収束しない場合の無限ループを防ぐ。
            上限に達しても収まらない場合は警告を記録し、そのまま処理を終える。
        margin_inches: 1回の拡張で超過分に上乗せする余白（インチ）。
    """
    for _ in range(max_iterations):
        overflow_inches = _measure_xlabel_overflow_inches(figure)
        if overflow_inches is None or overflow_inches <= 0:
            return

        # figureを広げると軸の右端は同じ量だけ動く一方、ラベルの中心（＝軸の中心）は
        # その半分しか動かないため、超過分を解消するには2倍を広げる必要がある。
        width, height = figure.get_size_inches()
        figure.set_size_inches(width + overflow_inches * 2 + margin_inches, height)
        figure.tight_layout()

    remaining_overflow_inches = _measure_xlabel_overflow_inches(figure)
    if remaining_overflow_inches is not None and remaining_overflow_inches > 0:
        # 収まらないまま保存すると軸ラベルが切れるため、無言で見逃さないよう記録する。
        logger.warning(
            "x軸ラベルが%d回の拡張でも保存領域に収まりませんでした（超過幅: %.3fインチ）。"
            "ラベルの端が切れた画像が保存されます。",
            max_iterations,
            remaining_overflow_inches,
        )


def _finalize_current_figure(output_path: Path, title: str, fit_xlabel: bool = False) -> None:
    """現在のmatplotlib figureにタイトルを付けて保存し、閉じる。

    `compute_shap_outputs` 内の3箇所（summary/bar/dependence）で同じ
    保存手順が繰り返されるため、共通化する。

    Args:
        output_path: 保存先の画像パス。
        title: 図に付けるタイトル。
        fit_xlabel: Trueの場合、保存前にx軸ラベル全体が収まるようfigureを広げる。
            軸より横に長いラベルを持つ図にのみ指定する（本モジュールでは棒グラフ。
            summary図・dependence図のラベルは短く、見切れが起きないため広げない）。
    """
    plt.title(title)
    plt.tight_layout()
    if fit_xlabel:
        _widen_figure_until_xlabel_fits(plt.gcf())
    plt.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close()


def _validate_shap_feature_columns(
    model: RandomForestRegressor,
    shap_features: pd.DataFrame,
    background_features: pd.DataFrame,
) -> None:
    """SHAP計算対象・背景データの列が、モデルの学習時列順と一致することを確認する。

    `shap.TreeExplainer` はモデル内部の学習時列順（位置）でSHAP値を解釈する一方、
    `feature_names` は渡された `shap_features.columns` から独立に取得される。
    両者の列順がずれると、値と特徴量名の対応が黙って入れ替わり、原因の
    分かりにくい誤った重要度になる（例: 支配的な特徴量とそうでない特徴量の
    SHAP値が丸ごと入れ替わる）ため、処理の入口で検証する。

    Args:
        model: 学習済みモデル（DataFrameで学習されていれば `feature_names_in_` を持つ）。
        shap_features: SHAP計算対象データ。
        background_features: SHAP背景データ。
    Raises:
        ValueError: `shap_features` または `background_features` の列（名前・順序）が、
            モデルの学習時列順と一致しない場合。
    """
    if not hasattr(model, "feature_names_in_"):
        # numpy配列で学習されたモデルは学習時列順を持たないため、検証しようがない。
        return

    expected_columns = list(model.feature_names_in_)
    for label, dataframe in (
        ("shap_features", shap_features),
        ("background_features", background_features),
    ):
        actual_columns = list(dataframe.columns)
        if actual_columns != expected_columns:
            raise ValueError(
                f"{label}の列（特徴量名・順序）がモデルの学習時列順と一致していません: "
                f"{actual_columns} vs {expected_columns}"
            )


def compute_shap_outputs(
    model: RandomForestRegressor,
    shap_features: pd.DataFrame,
    background_features: pd.DataFrame,
    output_dir: Path,
    output_stem: str,
    observation_label: str,
) -> tuple[dict[str, object], pd.DataFrame]:
    """SHAP値を計算し、重要度表と可視化画像を保存する。

    Args:
        model: 学習済みのランダムフォレストモデル。
        shap_features: SHAP計算対象データ（特徴量列のみ）。
        background_features: SHAP背景データ（特徴量列のみ、shap_featuresと同じ列）。
        output_dir: 出力先ディレクトリ。結果に含めるパスは `to_project_relative_string()`
            で `PROJECT_ROOT` からの相対パスへ変換して記録する（`PROJECT_ROOT` 配下
            でない場合は絶対パスのまま記録する）。
        output_stem: 出力ファイル名の接頭辞。
        observation_label: 図タイトルに使う観測日時ラベル。
    Returns:
        SHAP集計結果辞書（`mean_abs_shap` と `outputs` を含む）と、
        重要度降順に並べたデータフレームのタプル。
    Raises:
        ValueError: `shap_features` または `background_features` の列が、
            モデルの学習時列順と一致しない場合。
    """
    _validate_shap_feature_columns(model, shap_features, background_features)
    feature_names = list(shap_features.columns)
    explainer = shap.TreeExplainer(model, data=background_features, feature_names=feature_names)
    shap_values = explainer(shap_features)

    # 各特徴量の寄与の大きさを比較するため、絶対SHAP値の平均を算出する。
    mean_abs_values = np.abs(shap_values.values).mean(axis=0)
    shap_importance_df = pd.DataFrame(
        {
            "feature": feature_names,
            "mean_abs_shap": mean_abs_values,
        }
    ).sort_values("mean_abs_shap", ascending=False)

    shap_importance_path = output_dir / f"{output_stem}_shap_importance.csv"
    shap_importance_df.to_csv(shap_importance_path, index=False)

    summary_path = output_dir / f"{output_stem}_shap_summary.png"
    plt.figure(figsize=(8, 5))
    shap.summary_plot(shap_values.values, shap_features, show=False)
    _finalize_current_figure(summary_path, f"SHAP value distribution {observation_label}")

    bar_path = output_dir / f"{output_stem}_shap_bar.png"
    plt.figure(figsize=(8, 5))
    shap.summary_plot(shap_values.values, shap_features, plot_type="bar", show=False)
    _finalize_current_figure(
        bar_path, f"SHAP value distribution {observation_label}", fit_xlabel=True
    )

    dependence_paths: dict[str, str] = {}
    for feature in feature_names:
        dependence_path = output_dir / f"{output_stem}_shap_dependence_{feature}.png"
        shap.dependence_plot(
            feature,
            shap_values.values,
            shap_features,
            show=False,
            interaction_index="auto",
        )
        _finalize_current_figure(
            dependence_path, f"SHAP value distribution {observation_label}: {feature}"
        )
        dependence_paths[feature] = to_project_relative_string(dependence_path)

    shap_result = {
        "sample_size": int(len(shap_features)),
        "background_size": int(len(background_features)),
        "mean_abs_shap": {
            row["feature"]: float(row["mean_abs_shap"]) for _, row in shap_importance_df.iterrows()
        },
        "outputs": {
            "shap_importance_csv": to_project_relative_string(shap_importance_path),
            "shap_summary_png": to_project_relative_string(summary_path),
            "shap_bar_png": to_project_relative_string(bar_path),
            "shap_dependence_png": dependence_paths,
        },
    }
    return shap_result, shap_importance_df
