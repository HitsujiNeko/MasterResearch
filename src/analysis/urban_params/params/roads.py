"""道路パラメータ（ROAD_DEN）算出モジュール。

OSM 道路データから車道の延長密度（m/ha）をグリッドセルごとに算出する。
フィルタリング方針:
    - ホワイトリスト方式で車道タグのみを対象とする
    - トンネル・地下道（z_order < 0）を除外する
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..geometry import compute_line_length
from ..grid import BBox, GridSpec, cell_area_ha
from ..io import LayerResource

VEHICLE_ROAD_TAGS: frozenset[str] = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "residential",
        "unclassified",
        "living_street",
        "service",
    }
)


def _is_vehicle_road(feature: dict[str, Any]) -> bool:
    """フィーチャが地表の車道であるかを判定する。

    Args:
        feature: Fiona が返すフィーチャ辞書。

    Returns:
        highway タグがホワイトリストに含まれ、かつ
        z_order が 0 以上（地表または高架）であれば ``True``。
    """
    props = feature.get("properties", {})
    highway = props.get("highway")
    if highway not in VEHICLE_ROAD_TAGS:
        return False
    z_order = props.get("z_order", 0)
    if isinstance(z_order, (int, float)) and z_order < 0:
        return False
    return True


def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """道路パラメータを算出する。

    Args:
        resource: 道路レイヤ（未指定シナリオでは ``None``）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        ``{"ROAD_DEN": array}`` 形式の辞書。道路密度の単位は m/ha。
        ``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    length_per_cell = compute_line_length(
        resource,
        bbox_analysis,
        grid_spec,
        feature_filter=_is_vehicle_road,
    )
    ha = cell_area_ha(grid_spec)
    road_den = length_per_cell / ha

    return {"ROAD_DEN": road_den.astype(np.float32)}
