"""同一グリッド上に並べた 2 系列の一致度統計。

2 つのデータセットを突き合わせる分析スクリプト（人口・夜間光など）で共通に使う。
相関が定義できない場合（要素が 1 件・いずれかが定数列）の扱いを 1 箇所に集約し、
スクリプトごとに `nan` の扱いがぶれないようにする。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats


def build_paired_statistics(
    reference_values: np.ndarray,
    comparison_values: np.ndarray,
) -> dict[str, Any]:
    """同一セル上の 2 系列の一致度統計を求める。

    Args:
        reference_values: 基準側の 1 次元配列。
        comparison_values: 比較側の 1 次元配列（同じ長さ）。

    Returns:
        相関・誤差・バイアスの統計。相関が定義できない場合は `pearson_r` /
        `spearman_rho` が None になり、`correlation_note` に理由が入る。

    Raises:
        ValueError: 2 系列の長さが異なる場合。
    """
    if reference_values.shape != comparison_values.shape:
        raise ValueError(
            f"2 系列の要素数が一致しません: {reference_values.shape} vs {comparison_values.shape}"
        )
    if reference_values.size == 0:
        return {"cell_count": 0}

    differences = comparison_values - reference_values
    statistics: dict[str, Any] = {
        "cell_count": int(reference_values.size),
        "mean_absolute_error": float(np.mean(np.abs(differences), dtype=np.float64)),
        "root_mean_squared_error": float(np.sqrt(np.mean(differences**2, dtype=np.float64))),
        "mean_bias": float(np.mean(differences, dtype=np.float64)),
        "median_bias": float(np.median(differences)),
    }

    # 相関は 2 点以上かつ両系列が非定数でなければ定義できない。scipy は前者で例外送出、
    # 後者で nan 返却と振る舞いが分かれるため、ここで先に判定して None に統一する
    # （nan をそのまま JSON へ書くと RFC 8259 非準拠の裸の NaN になる）
    if reference_values.size < 2:
        statistics.update(
            pearson_r=None,
            spearman_rho=None,
            correlation_note="比較対象セルが 1 件のため相関を計算できない。",
        )
        return statistics
    if np.ptp(reference_values) == 0 or np.ptp(comparison_values) == 0:
        statistics.update(
            pearson_r=None,
            spearman_rho=None,
            correlation_note="いずれかの系列が定数のため相関を計算できない。",
        )
        return statistics

    statistics["pearson_r"] = float(stats.pearsonr(reference_values, comparison_values).statistic)
    statistics["spearman_rho"] = float(
        stats.spearmanr(reference_values, comparison_values).statistic
    )
    return statistics
