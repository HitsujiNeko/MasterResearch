"""モデル比較・特徴量重要度・Spatial CV foldの可視化を行う共通モジュール。

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
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


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
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


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
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
