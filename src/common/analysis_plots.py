"""モデル比較・特徴量重要度・Spatial CV fold・相関行列の可視化を行う共通モジュール。

特徴量名はモジュールグローバルな定数ではなく、渡された辞書のキーから取得する
ため、シナリオ（Satellite Only / Limited / Full）ごとに異なる特徴量集合でも
同じ関数を再利用できる。

`matplotlib` のバックエンド設定（`matplotlib.use("Agg")`）はこのモジュールでは
行わない。呼び出し側（エントリスクリプト）がGDAL関連のPATH設定後にimportする
必要があるため、設定順序をエントリスクリプト側の責務として残す。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 相関行列ヒートマップへ数値を書き込む変数数の上限。これを超えるとセル数が
# 二乗で増えて注記が判読不能になるため、色のみの表示へ切り替える。数値の正本は
# 併せて出力する `*_correlation_*.csv` であり、図は共線構造の当たりを付けるための
# ものと位置づける。
CORRELATION_ANNOTATION_MAX_FEATURES = 15


def _finalize_figure(fig: plt.Figure, output_path: Path) -> None:
    """figureのレイアウトを整えて画像として保存し、閉じる。

    本モジュールの各関数で同じ保存手順（tight_layout・savefig・close）が
    繰り返されるため、共通化する。dpi・bbox_inchesの変更を1箇所に集約する。

    Args:
        fig: 保存対象のfigure。
        output_path: 出力画像パス。
    """
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_model_comparison_plot(
    output_path: Path,
    random_linear_metrics: dict[str, float],
    random_rf_metrics: dict[str, float],
    spatial_linear_metrics: dict[str, float],
    spatial_rf_metrics: dict[str, float],
    observation_label: str,
) -> None:
    """ランダム分割とSpatial CVのモデル比較図を保存する。

    Args:
        output_path: 出力画像パス。
        random_linear_metrics: ランダム分割の線形回帰指標（`compute_metrics` の戻り値）。
        random_rf_metrics: ランダム分割のRF指標。
        spatial_linear_metrics: Spatial CVの線形回帰指標（`summarize_metric_dicts` の戻り値）。
        spatial_rf_metrics: Spatial CVのRF指標。
        observation_label: 図タイトルに使う観測日時ラベル。
    """
    metric_names = ["r2", "rmse", "mae"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    for index, metric_name in enumerate(metric_names):
        values = [
            random_linear_metrics[metric_name],
            random_rf_metrics[metric_name],
            spatial_linear_metrics[f"{metric_name}_mean"],
            spatial_rf_metrics[f"{metric_name}_mean"],
        ]
        axes[index].bar(
            ["Linear\nRandom", "RF\nRandom", "Linear\nSpatialCV", "RF\nSpatialCV"],
            values,
            color=["#4c78a8", "#f58518", "#72b7b2", "#e45756"],
        )
        axes[index].set_title(metric_name.upper())
        axes[index].grid(axis="y", alpha=0.3)

    fig.suptitle(f"Model Performance Comparison {observation_label}")
    _finalize_figure(fig, output_path)


def save_feature_importance_plot(
    output_path: Path,
    standardized_coefficients: dict[str, float],
    rf_importance: dict[str, float],
    observation_label: str,
) -> None:
    """線形回帰とRFの特徴量重要度比較図を保存する。

    Args:
        output_path: 出力画像パス。
        standardized_coefficients: 線形回帰の標準化係数（キーが特徴量名）。
        rf_importance: RFの特徴量重要度（`standardized_coefficients` と同じ
            キー集合を持つ必要がある）。
        observation_label: 図タイトルに使う観測日時ラベル。
    Raises:
        ValueError: `standardized_coefficients` と `rf_importance` のキー集合が
            一致しない場合。素の `KeyError` にすると原因が分かりにくいため。
    """
    if set(standardized_coefficients.keys()) != set(rf_importance.keys()):
        raise ValueError(
            "standardized_coefficientsとrf_importanceのキー集合が一致していません: "
            f"{sorted(standardized_coefficients.keys())} vs {sorted(rf_importance.keys())}"
        )

    feature_names = list(standardized_coefficients.keys())
    linear_values = [abs(standardized_coefficients[feature]) for feature in feature_names]
    rf_values = [rf_importance[feature] for feature in feature_names]
    x_positions = np.arange(len(feature_names))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(
        x_positions - width / 2, linear_values, width=width, label="|Linear coef|", color="#54a24b"
    )
    ax.bar(x_positions + width / 2, rf_values, width=width, label="RF importance", color="#e45756")
    ax.set_xticks(x_positions, feature_names)
    ax.set_title(f"Feature Importance {observation_label}")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    _finalize_figure(fig, output_path)


def save_spatial_cv_plot(output_path: Path, fold_metrics_df: pd.DataFrame) -> None:
    """Spatial CVのfold別性能推移を可視化して保存する。

    Args:
        output_path: 出力画像パス。
        fold_metrics_df: fold別評価指標データ（`fold` / `linear_r2` / `rf_r2` 等の列を持つ）。
    """
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    metrics = [("r2", "R²"), ("rmse", "RMSE"), ("mae", "MAE")]

    for index, (metric_suffix, title) in enumerate(metrics):
        axes[index].plot(
            fold_metrics_df["fold"],
            fold_metrics_df[f"linear_{metric_suffix}"],
            marker="o",
            label="Linear",
            color="#4c78a8",
        )
        axes[index].plot(
            fold_metrics_df["fold"],
            fold_metrics_df[f"rf_{metric_suffix}"],
            marker="o",
            label="RF",
            color="#e45756",
        )
        axes[index].set_title(f"Spatial CV {title}")
        axes[index].set_xlabel("Fold")
        axes[index].grid(alpha=0.3)

    axes[0].legend()
    _finalize_figure(fig, output_path)


def save_correlation_heatmap(
    output_path: Path,
    correlation_matrix: pd.DataFrame,
    method_label: str,
    observation_label: str,
) -> None:
    """相関行列のヒートマップを保存する。

    Args:
        output_path: 出力画像パス。
        correlation_matrix: `compute_correlation_matrix` の戻り値（正方行列で、
            行ラベルと列ラベルが一致している必要がある）。
        method_label: 相関係数の種類（図タイトルに使う。例: `Pearson`）。
        observation_label: 図タイトルに使う観測日時ラベル。
    Raises:
        ValueError: `correlation_matrix` の行ラベルと列ラベルが一致しない場合。
            素の描画エラーにすると原因が分かりにくいため。
    """
    if list(correlation_matrix.index) != list(correlation_matrix.columns):
        raise ValueError(
            "correlation_matrixの行ラベルと列ラベルが一致していません: "
            f"{list(correlation_matrix.index)} vs {list(correlation_matrix.columns)}"
        )

    feature_names = [str(name) for name in correlation_matrix.columns]
    feature_count = len(feature_names)
    # 変数数に応じて図を広げないと、軸ラベルが重なって読めなくなる。
    figure_side = max(6.0, 0.55 * feature_count + 3.0)

    colormap = plt.get_cmap("coolwarm").copy()
    # 定数列に由来するNaNを灰色で描き、相関0（中間色）と区別できるようにする。
    colormap.set_bad("#dddddd")

    fig, ax = plt.subplots(figsize=(figure_side, figure_side))
    image = ax.imshow(
        np.ma.masked_invalid(correlation_matrix.to_numpy(dtype=np.float64)),
        cmap=colormap,
        vmin=-1.0,
        vmax=1.0,
    )
    ax.set_xticks(np.arange(feature_count), feature_names, rotation=90)
    ax.set_yticks(np.arange(feature_count), feature_names)
    ax.set_title(f"{method_label} Correlation {observation_label}")
    fig.colorbar(image, ax=ax, shrink=0.8)

    if feature_count <= CORRELATION_ANNOTATION_MAX_FEATURES:
        for row_index in range(feature_count):
            for column_index in range(feature_count):
                value = correlation_matrix.iat[row_index, column_index]
                ax.text(
                    column_index,
                    row_index,
                    "n/a" if pd.isna(value) else f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black",
                )

    _finalize_figure(fig, output_path)
