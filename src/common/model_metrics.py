"""回帰モデルの評価指標を計算する共通モジュール。

R²/RMSE/MAEの算出、fold単位の指標集計、多重共線性を確認するためのVIF計算を
まとめる。RQ3のシナリオ別分析スクリプト（Satellite Only / Limited / Full）が
共通して必要とする処理であり、シナリオ固有の特徴量名には依存しない。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def compute_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    """回帰評価指標を計算する。

    Args:
        y_true: 正解値。
        y_pred: 予測値。
    Returns:
        R2, RMSE, MAEを格納した辞書。
    """
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }


def summarize_metric_dicts(metric_dicts: list[dict[str, float]]) -> dict[str, float]:
    """評価指標辞書の平均と標準偏差を集計する。

    Args:
        metric_dicts: foldごとの評価指標辞書（`compute_metrics` の戻り値のリスト）。
    Returns:
        各指標の平均・標準偏差を含む辞書（キーは `{指標名}_mean` / `{指標名}_std`）。
    Raises:
        ValueError: `metric_dicts` が空の場合。
    """
    if not metric_dicts:
        raise ValueError("集計対象のfold評価指標が空です。CV分割数を確認してください。")

    summary: dict[str, float] = {}
    for metric_name in metric_dicts[0]:
        values = np.array([metrics[metric_name] for metrics in metric_dicts], dtype=np.float64)
        summary[f"{metric_name}_mean"] = float(values.mean())
        summary[f"{metric_name}_std"] = float(values.std(ddof=0))
    return summary


def compute_vif(dataframe: pd.DataFrame) -> dict[str, float]:
    """説明変数ごとのVIF（分散拡大係数）を計算する。

    Args:
        dataframe: 説明変数のみを含むデータフレーム（2列以上必要）。
    Returns:
        変数名をキー、VIFを値とする辞書。完全共線（決定係数がほぼ1）の場合は
        `float("inf")` を返す。
    Raises:
        ValueError: `dataframe` の列数が2未満の場合。VIFは対象列を残りの列に
            回帰して求めるため、比較対象となる他の列が最低1つ必要。
    """
    if dataframe.shape[1] < 2:
        raise ValueError(f"VIFの計算には説明変数が2列以上必要です（列数: {dataframe.shape[1]}）。")

    vif_values: dict[str, float] = {}
    for column in dataframe.columns:
        y = dataframe[column]
        x = dataframe.drop(columns=column)
        model = LinearRegression()
        model.fit(x, y)
        r_squared = model.score(x, y)
        if r_squared >= 0.999999:
            vif_values[column] = float("inf")
            continue
        vif_values[column] = float(1.0 / (1.0 - r_squared))
    return vif_values


def sanitize_vif_for_json(vif_values: dict[str, float]) -> dict[str, object]:
    """VIFの非有限値（Inf・NaN）をJSON書き出し可能な形に変換する。

    `compute_vif` は完全共線時に `float("inf")` を返すが、
    `src.common.summary.save_summary()` は `allow_nan=False` でInf・NaNを例外にする。
    黙って`null`へ落とすと「完全共線で発散した」のか「数値的に不安定でNaNになった」
    のかが区別できなくなるため、非有限値だった変数名を別キーに残す
    （NaNは通常発生しないが、極端な多重共線性下での数値誤差に備えて同列に扱う）。

    Args:
        vif_values: `compute_vif` の戻り値（変数名をキー、VIFを値とする辞書）。
    Returns:
        `"vif"`（非有限値を`None`に置き換えた辞書）と `"vif_non_finite_features"`
        （Inf・NaNだった変数名のリスト）を持つ辞書。
    """
    non_finite_features = [name for name, value in vif_values.items() if not math.isfinite(value)]
    sanitized_vif = {
        name: (None if not math.isfinite(value) else value) for name, value in vif_values.items()
    }
    return {"vif": sanitized_vif, "vif_non_finite_features": non_finite_features}
