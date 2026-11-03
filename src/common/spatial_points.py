"""点の座標と値の組（空間統計の入力）を検証する共通モジュール。

経験セミバリオグラム（``semivariogram``）と距離帯ごとの Moran's I
（``residual_autocorrelation``）は、どちらも最大距離以内の点の組を疎行列で持つ。
疎行列は値0の要素を保持しないことがあり、距離0の組（座標が重複する点）が
数えられるか保証できないため、両者で同じ検証を通してから計算する。
"""

from __future__ import annotations

import numpy as np


def validate_points(coords: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """座標と値の形状・有限性・座標の重複を検証し、float 配列にして返す。

    Args:
        coords: 点の座標（形状 ``(n, 2)``）。
        values: 各点の値（形状 ``(n,)``）。
    Returns:
        float に変換した ``(coords, values)``。
    Raises:
        ValueError: 形状が合わない場合、NaN・無限大を含む場合、座標が重複する
            場合（距離0の組の扱いを保証できないため）。
    """
    coords = np.asarray(coords, dtype=float)
    values = np.asarray(values, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 2 or coords.shape[0] != values.shape[0]:
        raise ValueError(
            f"coords は (n, 2)、values は (n,) で n が一致する必要があります"
            f"（coords={coords.shape}, values={values.shape}）。"
        )
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(coords)):
        raise ValueError("coords・values に NaN または無限大が含まれています。")
    n_unique = np.unique(coords, axis=0).shape[0]
    if n_unique != coords.shape[0]:
        raise ValueError(
            f"coords に重複する座標があります（{coords.shape[0] - n_unique}点）。"
            "距離0の組の扱いを保証できないため、重複を除いてから渡してください。"
        )
    return coords, values
