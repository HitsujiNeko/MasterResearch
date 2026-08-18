"""SHAP値の算出・重要度表・可視化画像を出力する共通モジュール。

特徴量名はモジュールグローバルな定数ではなく `shap_features.columns` から
取得するため、シナリオ（Satellite Only / Limited / Full）ごとに異なる
特徴量集合でも同じ関数を再利用できる。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestRegressor

from src.common.paths import to_project_relative_string


def _finalize_current_figure(output_path: Path, title: str) -> None:
    """現在のmatplotlib figureにタイトルを付けて保存し、閉じる。

    `compute_shap_outputs` 内の3箇所（summary/bar/dependence）で同じ
    保存手順が繰り返されるため、共通化する。

    Args:
        output_path: 保存先の画像パス。
        title: 図に付けるタイトル。
    """
    plt.title(title)
    plt.tight_layout()
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
    _finalize_current_figure(bar_path, f"SHAP value distribution {observation_label}")

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
