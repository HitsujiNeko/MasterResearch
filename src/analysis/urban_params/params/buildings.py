"""建物パラメータ（BUILD_COV / BUILD_DEN / BUILD_H_MEAN / BUILD_H_MAX）算出モジュール。

現時点ではスタブであり、実装は別Issue（#7）で行う。
BUILD_DEN は棟数/ha、BUILD_H_MEAN・BUILD_H_MAX はGBAの高さ属性から算出する
予定であり、面積正規化には ``grid.cell_area_ha()`` を使用する。
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
    """建物パラメータを算出する（未実装のため常に空辞書を返す）。

    Args:
        resource: 建物レイヤ（未指定シナリオでは ``None``）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        常に空辞書。
    """
    return {}
