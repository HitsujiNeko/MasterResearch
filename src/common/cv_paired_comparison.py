"""交差検証の fold ごとの対応のある差と、その信頼区間（素朴 t 区間・補正 t 区間）。

2つのシナリオ（例: Satellite Only と Limited）を**同じセル・同じ fold**で評価した
ときに、fold ごとの評価指標の差 d_j を求め、平均差の信頼区間を出す。

`src.common.paired_stats`（同一セル上に並べた2つの**値の系列**の一致度）とは
役割が違う。こちらは「2つのモデル評価の**性能指標**の差」を扱う。

**補正 t 区間**（Nadeau & Bengio 2003 の corrected resampled t、反復 k-fold への
適用は Bouckaert & Frank 2004）: 分割の総数を J、テスト行数と学習行数の比を
ρ = n_test / n_train として、差の平均の分散を `(1/J + ρ) · s²` とする
（s² は J 個の差の標本分散で、J−1 で割る）。自由度は J−1 とする。CV の fold どうしは
学習データを共有していて独立ではないため、素朴な t 区間（分散 s²/J）は狭く出すぎる。
単発の k-fold では J = k、k-fold を r 回反復した場合は J = k·r であり、J は差の個数
そのものとして求める（引数で別に受け取らない。単発と反復で J を取り違えないため）。

GroupKFold は fold ごとにテスト行数が異なるため、ρ は全分割の `test_size / train_size`
の平均を使い、使った値を出力に記録する。

式（補正係数・分散の分母・自由度）は、両手法を実装した R パッケージ correctR の
`resampled_ttest`・`repkfold_ttest` と一致させてある。原典の論文本文との突き合わせは
未確認である。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

FOLD_COLUMN = "fold"
TRAIN_SIZE_COLUMN = "train_size"
TEST_SIZE_COLUMN = "test_size"
# Spatial CV の fold 別指標 CSV（`run_spatial_cv_models` の出力）が持つ評価指標の列。
FOLD_METRIC_COLUMNS = (
    "linear_r2",
    "linear_rmse",
    "linear_mae",
    "rf_r2",
    "rf_rmse",
    "rf_mae",
)
DEFAULT_CONFIDENCE = 0.95


def compute_fold_differences(
    reference_folds: pd.DataFrame,
    comparison_folds: pd.DataFrame,
    metric_columns: Sequence[str] = FOLD_METRIC_COLUMNS,
) -> pd.DataFrame:
    """fold ごとに「比較側 − 基準側」の評価指標の差を求める。

    同じセル・同じ fold で評価したことの確認として、fold 番号・学習行数・テスト
    行数が両者で一致することを検査する。

    Args:
        reference_folds: 基準側の fold 別指標（例: Satellite Only）。
        comparison_folds: 比較側の fold 別指標（例: Limited）。
        metric_columns: 差を取る評価指標の列。
    Returns:
        fold 番号・学習行数・テスト行数と、各指標の差（列名は指標名のまま）を持つ
        データフレーム（fold 番号順）。
    Raises:
        ValueError: fold 番号・学習行数・テスト行数のいずれかが一致しない場合。
    """
    key_columns = [FOLD_COLUMN, TRAIN_SIZE_COLUMN, TEST_SIZE_COLUMN]
    reference = reference_folds.sort_values(FOLD_COLUMN).reset_index(drop=True)
    comparison = comparison_folds.sort_values(FOLD_COLUMN).reset_index(drop=True)
    if not reference[key_columns].equals(comparison[key_columns]):
        raise ValueError(
            "2つの評価の fold 番号・学習行数・テスト行数が一致しません。"
            "同じ評価セル（同じ標本・同じ fold）で評価した結果か確認してください。"
        )
    differences = reference[key_columns].copy()
    for column in metric_columns:
        differences[column] = comparison[column] - reference[column]
    return differences


def mean_test_train_ratio(train_sizes: Sequence[int], test_sizes: Sequence[int]) -> float:
    """全分割の `test_size / train_size` の平均（補正 t 区間の ρ）を求める。

    Args:
        train_sizes: 分割ごとの学習行数。
        test_sizes: 分割ごとのテスト行数（`train_sizes` と位置対応）。
    Returns:
        比の平均。
    Raises:
        ValueError: 長さが揃わない場合、空の場合、または学習行数が0以下の場合。
    """
    train = np.asarray(train_sizes, dtype=float)
    test = np.asarray(test_sizes, dtype=float)
    if train.shape != test.shape or train.size == 0:
        raise ValueError("学習行数とテスト行数の長さが揃っていない、または空です。")
    if np.any(train <= 0):
        raise ValueError("学習行数が0以下の分割があります。")
    return float(np.mean(test / train))


def summarize_paired_differences(
    differences: Sequence[float],
    test_train_ratio: float,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, Any]:
    """分割ごとの差から、平均差と素朴 t 区間・補正 t 区間を求める。

    分割の総数 J は差の個数とする（単発の k-fold では k、反復では k·r）。

    Args:
        differences: 分割ごとの差（J 個）。
        test_train_ratio: ρ（`mean_test_train_ratio` の戻り値）。
        confidence: 信頼係数（既定 0.95）。
    Returns:
        J・平均差・標準偏差・自由度・t 分位点と、素朴版・補正版それぞれの標準誤差と
        区間、補正係数 `1/J + ρ` を持つ辞書。J が2未満なら区間は `None` にする。
    Raises:
        ValueError: `confidence` が 0〜1 の範囲外の場合。
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence は 0 より大きく 1 より小さい値にしてください: {confidence}")
    values = np.asarray(differences, dtype=float)
    n_splits = int(values.size)
    result: dict[str, Any] = {
        "n_splits": n_splits,
        "mean_difference": float(values.mean()) if n_splits else None,
        "sd_difference": None,
        "degrees_of_freedom": None,
        "t_quantile": None,
        "confidence": confidence,
        "test_train_ratio": float(test_train_ratio),
        "correction_factor": None,
        "naive": None,
        "corrected": None,
    }
    if n_splits < 2:
        return result

    sd = float(values.std(ddof=1))
    degrees_of_freedom = n_splits - 1
    t_quantile = float(stats.t.ppf(0.5 + confidence / 2.0, degrees_of_freedom))
    correction_factor = 1.0 / n_splits + float(test_train_ratio)
    mean = float(values.mean())
    result.update(
        {
            "sd_difference": sd,
            "degrees_of_freedom": degrees_of_freedom,
            "t_quantile": t_quantile,
            "correction_factor": correction_factor,
            "naive": _interval(mean, sd * np.sqrt(1.0 / n_splits), t_quantile),
            "corrected": _interval(mean, sd * np.sqrt(correction_factor), t_quantile),
        }
    )
    return result


def _interval(mean: float, standard_error: float, t_quantile: float) -> dict[str, float]:
    """平均・標準誤差・t 分位点から区間を作る。

    Args:
        mean: 平均差。
        standard_error: 標準誤差。
        t_quantile: t 分布の分位点。
    Returns:
        標準誤差・下限・上限の辞書。
    """
    half_width = t_quantile * standard_error
    return {
        "standard_error": float(standard_error),
        "lower": float(mean - half_width),
        "upper": float(mean + half_width),
    }


def summarize_metric_differences(
    differences: pd.DataFrame,
    metric_columns: Sequence[str] = FOLD_METRIC_COLUMNS,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, Any]:
    """`compute_fold_differences` の戻り値（を縦に連結したもの）から、指標ごとの区間を求める。

    ρ は `differences` の全行の学習行数・テスト行数から1つ求め、全指標に共通で使う。

    Args:
        differences: 分割ごとの差（`TRAIN_SIZE_COLUMN`・`TEST_SIZE_COLUMN` と指標の列）。
        metric_columns: 区間を求める指標の列。
        confidence: 信頼係数。
    Returns:
        ρ と、指標名をキー・`summarize_paired_differences` の戻り値を値とする辞書。
    """
    ratio = mean_test_train_ratio(
        differences[TRAIN_SIZE_COLUMN].to_numpy(), differences[TEST_SIZE_COLUMN].to_numpy()
    )
    return {
        "test_train_ratio": ratio,
        "metrics": {
            column: summarize_paired_differences(differences[column], ratio, confidence)
            for column in metric_columns
        },
    }
