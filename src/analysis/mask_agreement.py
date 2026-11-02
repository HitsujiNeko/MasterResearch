"""2 つの二値マスク（例: 水域／非水域）の空間的一致度を集計する。

どちらのマスクも真値ではない前提で、精度（accuracy）ではなく一致度（agreement）として
扱う。一方を基準にした指標には「A 基準」「B 基準」と明示した名前を付ける
（`compare_lulc_esri_glc.py` の「GLC 基準」「Esri 基準」と同じ規約）。

比較対象は**両マスクとも有効なセル**に限る。有効域の大きさはペアごとに異なるため、
指標と一緒に有効セル数を必ず返す。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.analysis.compare_lulc_esri_glc import cohens_kappa


def _ratio(numerator: int, denominator: int) -> float | None:
    """分母が 0 のとき None を返す割り算。

    Args:
        numerator: 分子。
        denominator: 分母。

    Returns:
        比。分母が 0 の場合は None（0.0 にすると「一致しない」と区別できないため）。
    """
    return (numerator / denominator) if denominator > 0 else None


def compute_binary_agreement(
    mask_a: np.ndarray,
    mask_b: np.ndarray,
    valid: np.ndarray,
    cell_area_m2: float | None = None,
) -> dict[str, Any]:
    """2 つの二値マスクの一致度指標を求める。

    指標:
        - IoU: 両者とも True のセル ÷ どちらかが True のセル
        - A 基準の一致率: A が True のセルのうち B も True の割合（B 基準はその逆）
        - 画素数比（B ÷ A）: True のセル数の比
        - 全体一致率と Cohen's kappa: True／False 両方を含む 2x2 の一致

    Args:
        mask_a: マスク A（True が対象クラス）。
        mask_b: マスク B（形状は ``mask_a`` と同じ）。
        valid: 両マスクとも有効なセルを True とするマスク。False のセルは集計しない。
        cell_area_m2: 1 セルの面積（m²）。指定すると面積（km²）も返す。
            面積は投影座標系のセルでのみ意味を持つため、地理座標系の格子では指定しない。

    Returns:
        セル数（A のみ・B のみ・両方・どちらでもない・有効）と各指標の辞書。
        比の分母が 0 の指標は None。

    Raises:
        ValueError: 3 つの配列の形状が一致しない場合。
    """
    if not (mask_a.shape == mask_b.shape == valid.shape):
        raise ValueError(
            "マスクの形状が一致しません"
            f"（A: {mask_a.shape}、B: {mask_b.shape}、有効域: {valid.shape}）。"
        )

    a = mask_a.astype(bool) & valid
    b = mask_b.astype(bool) & valid
    both = int(np.count_nonzero(a & b))
    a_only = int(np.count_nonzero(a & ~b))
    b_only = int(np.count_nonzero(~a & b))
    valid_cells = int(np.count_nonzero(valid))
    neither = valid_cells - both - a_only - b_only
    a_cells = both + a_only
    b_cells = both + b_only

    confusion = np.array([[both, a_only], [b_only, neither]], dtype=np.int64)
    result: dict[str, Any] = {
        "valid_cells": valid_cells,
        "a_cells": a_cells,
        "b_cells": b_cells,
        "both_cells": both,
        "a_only_cells": a_only,
        "b_only_cells": b_only,
        "neither_cells": neither,
        "iou": _ratio(both, both + a_only + b_only),
        "agreement_given_a": _ratio(both, a_cells),
        "agreement_given_b": _ratio(both, b_cells),
        "b_to_a_cell_ratio": _ratio(b_cells, a_cells),
        "overall_agreement": _ratio(both + neither, valid_cells),
        "cohens_kappa": cohens_kappa(confusion) if valid_cells > 0 else None,
    }
    if cell_area_m2 is not None:
        result["a_area_km2"] = a_cells * cell_area_m2 / 1e6
        result["b_area_km2"] = b_cells * cell_area_m2 / 1e6
    return result
