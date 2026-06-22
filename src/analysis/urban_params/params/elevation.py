"""標高パラメータ（ELEV_MEAN / ELEV_COUNT）算出モジュール。

現時点ではスタブであり、実装は別Issueで行う。
"""

from __future__ import annotations

import numpy as np

from ..grid import BBox, GridSpec
from ..io import LayerResource


def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """標高パラメータを算出する（未実装のため常に空辞書を返す）。

    Args:
        resource: 標高点レイヤ（未指定シナリオでは ``None``）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        常に空辞書。
    """
    return {}
