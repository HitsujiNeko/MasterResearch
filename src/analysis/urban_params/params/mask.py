"""解析対象域フラグ（IN_ANALYSIS_AREA）算出モジュール。

解析範囲レイヤ（ROI）のポリゴンがセルを覆うかどうかを判定し、他のパラメータと
同じ枠組み（``compute()`` の標準シグネチャ）で扱えるようにする。判定そのものは
``geometry.compute_polygon_coverage()`` に委ね、ロジックを二重に持たない。

**このフラグは独立したテーブルとして出力し、他のパラメータテーブルには持たせない。**
全テーブルに同じ値を複製すると、パラメータ単位で独立させる狙いに反するためである。

**正準グリッドのセル集合とは判定基準が異なる点に注意する。** 正準グリッドは
「セルとマスクポリゴンの交差」でセルを選ぶのに対し、本モジュールは
``compute_polygon_coverage()`` すなわち「fineピクセル中心がポリゴン内に入るか」で
判定する。角をわずかにかすめるセルは交差するがピクセル中心は1つも入らないため、
両者は「交差 ⊇ IN_ANALYSIS_AREA」の包含関係にある。したがって**パラメータテーブル
の行集合（正準グリッド基準）は解析対象域より広く、有効域と同一視してはならない**。
"""

from __future__ import annotations

import numpy as np

from ..geometry import compute_polygon_coverage
from ..grid import BBox, GridSpec
from ..io import LayerResource


def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """解析対象域フラグを算出する。

    Args:
        resource: 解析範囲レイヤ（未指定の場合は ``None``）。面ジオメトリを持つ
            レイヤである必要がある（線・点主体のレイヤでは面積ベースの判定が
            成立しない）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        ``{"IN_ANALYSIS_AREA": array}`` 形式の辞書。被覆率が0より大きいセルを1、
        それ以外を0とする ``int8`` 配列。``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    coverage = compute_polygon_coverage(resource, bbox_analysis, grid_spec)
    return {"IN_ANALYSIS_AREA": (coverage > 0).astype(np.int8)}
