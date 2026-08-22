"""LULC（土地被覆）のクラス体系に関する共通定義。

GLC_FCS30D（30m・35クラス）と Esri 10m LULC（写像対象8クラス）は、それぞれ異なる
分類体系を持つ。両者を比較・集計するには共通の粒度へ写像する必要があり、その写像表
（GLC 35クラス→共通7クラス、Esri 8クラス→共通7クラス。いずれも雪氷を除く）は
`src/analysis/compare_lulc_esri_glc.py` の一致度比較で実データに基づき検証済みである。

本モジュールはその写像表と、写像を適用する関数を切り出したものである。
`compare_lulc_esri_glc.py`（データセット間の一致度評価）と
`src/analysis/urban_params/params/lulc.py`（都市構造パラメータの算出）の双方が
ここを参照することで、同じ写像表を二重管理しない。
"""

from __future__ import annotations

import numpy as np

# 共通クラス体系。GLC 35クラスと Esri（写像対象8クラス）の双方を写像できる
# 最小粒度として定めた。0 は「写像表に無い値（無効値・体系外）」を表す。
COMMON_INVALID = 0
COMMON_WATER = 1
COMMON_FOREST = 2
COMMON_CROPLAND = 3
COMMON_BUILT = 4
COMMON_GRASS_SHRUB = 5
COMMON_BARE = 6
COMMON_WETLAND = 7
COMMON_SNOW_ICE = 8

COMMON_CLASS_LABELS: dict[int, str] = {
    COMMON_WATER: "水域",
    COMMON_FOREST: "樹林",
    COMMON_CROPLAND: "農地",
    COMMON_BUILT: "市街地（不透水面）",
    COMMON_GRASS_SHRUB: "草地・低木",
    COMMON_BARE: "裸地",
    COMMON_WETLAND: "湿地",
    COMMON_SNOW_ICE: "雪氷",
}

# GLC_FCS30D（35クラス）→ 共通クラス
GLC_TO_COMMON: dict[int, int] = {
    10: COMMON_CROPLAND,
    11: COMMON_CROPLAND,
    12: COMMON_CROPLAND,
    20: COMMON_CROPLAND,
    51: COMMON_FOREST,
    52: COMMON_FOREST,
    61: COMMON_FOREST,
    62: COMMON_FOREST,
    71: COMMON_FOREST,
    72: COMMON_FOREST,
    81: COMMON_FOREST,
    82: COMMON_FOREST,
    91: COMMON_FOREST,
    92: COMMON_FOREST,
    120: COMMON_GRASS_SHRUB,
    121: COMMON_GRASS_SHRUB,
    122: COMMON_GRASS_SHRUB,
    130: COMMON_GRASS_SHRUB,
    140: COMMON_GRASS_SHRUB,
    150: COMMON_GRASS_SHRUB,
    152: COMMON_GRASS_SHRUB,
    153: COMMON_GRASS_SHRUB,
    181: COMMON_WETLAND,
    182: COMMON_WETLAND,
    183: COMMON_WETLAND,
    184: COMMON_WETLAND,
    185: COMMON_WETLAND,
    186: COMMON_WETLAND,
    187: COMMON_WETLAND,
    190: COMMON_BUILT,
    200: COMMON_BARE,
    201: COMMON_BARE,
    202: COMMON_BARE,
    210: COMMON_WATER,
    220: COMMON_SNOW_ICE,
}

# Esri 10m LULC（写像対象8クラス。分類体系としては No Data を除く9クラスだが、
# 品質フラグである Clouds は写像対象に含めない）→ 共通クラス
ESRI_TO_COMMON: dict[int, int] = {
    1: COMMON_WATER,
    2: COMMON_FOREST,
    4: COMMON_WETLAND,
    5: COMMON_CROPLAND,
    7: COMMON_BUILT,
    8: COMMON_BARE,
    9: COMMON_SNOW_ICE,
    11: COMMON_GRASS_SHRUB,
}

# RasterResource.class_scheme の値 → 写像表。算出モジュール（params/lulc.py）が
# データセットの分類体系を判別するために使う。画素値の分布から体系を推定する経路は
# 採れない（値 10・11 が両体系に存在するが意味が異なるため）。
CLASS_SCHEMES: dict[str, dict[int, int]] = {
    "glc2022": GLC_TO_COMMON,
    "esri2022": ESRI_TO_COMMON,
}


def build_class_lookup(mapping: dict[int, int]) -> np.ndarray:
    """写像表から「画素値 → 共通クラスID」の添字表を作る。

    添字表は `lookup[画素値]` で共通クラスIDを引ける形にした `np.ndarray` であり、
    画素値ごとの dict 参照より大幅に速い。写像表に無い画素値（配列の範囲内であっても）
    は `COMMON_INVALID`（0）になる。

    Args:
        mapping (dict[int, int]): 元クラス値から共通クラス値への対応。

    Returns:
        np.ndarray: 添字表（uint8、長さは `max(mapping) + 1`）。
    """
    lookup = np.zeros(int(max(mapping)) + 1, dtype=np.uint8)
    for source_value, common_value in mapping.items():
        lookup[source_value] = common_value
    return lookup


def map_to_common_classes(array: np.ndarray, mapping: dict[int, int]) -> np.ndarray:
    """クラス値配列を共通クラス体系へ写像する。

    写像表に無い値（無効値・体系外の値。添字表の範囲外の値を含む）は
    `COMMON_INVALID`（0）にする。

    Args:
        array (np.ndarray): 元のクラス値配列。
        mapping (dict[int, int]): 元クラス値から共通クラス値への対応。

    Returns:
        np.ndarray: 共通クラス値の配列（uint8）。
    """
    lookup = build_class_lookup(mapping)
    common = np.zeros(array.shape, dtype=np.uint8)
    in_range = array < lookup.size
    common[in_range] = lookup[array[in_range]]
    return common
