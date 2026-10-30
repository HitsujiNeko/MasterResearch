"""Black Marble のタイル格子（10°×10°）と、ROI・ファイル属性との対応づけ。

BBOX から必要なタイルを求め、タイル番号が覆う範囲を計算し、HDF5 のルート属性に
記録された境界座標と突き合わせる。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Black Marble のタイルグリッド（10°×10°、原点は北西端の -180E / 90N）
TILE_SIZE_DEG = 10.0
GRID_ORIGIN_LON = -180.0
GRID_ORIGIN_LAT = 90.0
MAX_HORIZONTAL_INDEX = 35
MAX_VERTICAL_INDEX = 17

# ジオリファレンスの照合に使うルート属性
BOUNDING_COORD_ATTRIBUTES = {
    "west": "WestBoundingCoord",
    "east": "EastBoundingCoord",
    "north": "NorthBoundingCoord",
    "south": "SouthBoundingCoord",
}
# 属性由来と h/v 由来の境界座標の許容差（度）。15 arc-sec の 1/100 未満に相当する。
GEOREFERENCE_TOLERANCE_DEG = 1e-5


@dataclass(frozen=True)
class TileIndex:
    """Black Marble のタイル番号（h: 西→東、v: 北→南）。"""

    horizontal: int
    vertical: int

    @property
    def name(self) -> str:
        """`h28v06` 形式のタイル名を返す。"""
        return f"h{self.horizontal:02d}v{self.vertical:02d}"


def resolve_black_marble_tiles(
    bounds: tuple[float, float, float, float],
) -> list[TileIndex]:
    """BBOX を覆う Black Marble タイルの一覧を求める。

    タイルは 10°×10° で、原点は北西端の (-180E, 90N)。境界を「半開区間」として扱い、
    BBOX の東端・南端がちょうどタイル境界に載る場合に、重なりの無い隣のタイルを
    拾わないようにする（`ceil - 1` を使う理由）。

    Args:
        bounds: (min_lon, min_lat, max_lon, max_lat)。EPSG:4326。

    Returns:
        北西から南東の順に並べたタイル一覧。

    Raises:
        ValueError: BBOX の最小値が最大値を超えている場合、または経緯度の値域を
            外れている場合。
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    # 逆転と値域外を同じメッセージで返すと、値域は正しいのに値域の調査に向かってしまう
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError(
            "BBOX の最小値が最大値を超えています"
            f"（経度: {min_lon} > {max_lon} または 緯度: {min_lat} > {max_lat}）: {bounds}"
        )
    if not (-180.0 <= min_lon and max_lon <= 180.0 and -90.0 <= min_lat and max_lat <= 90.0):
        raise ValueError(f"BBOX が経緯度の値域を外れています: {bounds}")

    first_horizontal = math.floor((min_lon - GRID_ORIGIN_LON) / TILE_SIZE_DEG)
    last_horizontal = math.ceil((max_lon - GRID_ORIGIN_LON) / TILE_SIZE_DEG) - 1
    first_vertical = math.floor((GRID_ORIGIN_LAT - max_lat) / TILE_SIZE_DEG)
    last_vertical = math.ceil((GRID_ORIGIN_LAT - min_lat) / TILE_SIZE_DEG) - 1

    # 開始索引を先に値域へ収める。経度 180・緯度 -90 ちょうどの縮退 BBOX では
    # 索引が索引上限を 1 超えるため、ここで丸めておかないと開始 > 終了となり
    # 空リストになる（呼び出し側の tiles[0] が IndexError になる）。
    first_horizontal = min(max(first_horizontal, 0), MAX_HORIZONTAL_INDEX)
    first_vertical = min(max(first_vertical, 0), MAX_VERTICAL_INDEX)
    # 幅・高さが 0 の BBOX では ceil-1 が floor を下回るため、最低 1 タイルは残す
    last_horizontal = min(max(last_horizontal, first_horizontal), MAX_HORIZONTAL_INDEX)
    last_vertical = min(max(last_vertical, first_vertical), MAX_VERTICAL_INDEX)

    return [
        TileIndex(horizontal=horizontal, vertical=vertical)
        for vertical in range(first_vertical, last_vertical + 1)
        for horizontal in range(first_horizontal, last_horizontal + 1)
    ]


def compute_tile_bounds(tile: TileIndex) -> tuple[float, float, float, float]:
    """タイル番号から、そのタイルが覆う範囲を求める。

    Args:
        tile: タイル番号。

    Returns:
        (west, south, east, north)。EPSG:4326。
    """
    west = GRID_ORIGIN_LON + TILE_SIZE_DEG * tile.horizontal
    north = GRID_ORIGIN_LAT - TILE_SIZE_DEG * tile.vertical
    return (west, north - TILE_SIZE_DEG, west + TILE_SIZE_DEG, north)


def verify_tile_georeference(
    root_attributes: dict[str, Any],
    tile: TileIndex,
    tolerance: float = GEOREFERENCE_TOLERANCE_DEG,
) -> dict[str, Any]:
    """ファイル属性の境界座標が、タイル番号から求めた範囲と一致するか検証する。

    タイル番号だけで transform を組み立てると、ファイル名のタイル番号を読み違えても
    気づけない。属性側の境界座標と突き合わせて、両者が一致することを確認する。

    Args:
        root_attributes: HDF5 のルート属性。
        tile: タイル番号。
        tolerance: 許容する座標のずれ（度）。

    Returns:
        照合に用いた属性値と、タイル番号由来の境界の記録。

    Raises:
        KeyError: 境界座標の属性が揃っていない場合。
        ValueError: 属性とタイル番号由来の境界が許容差を超えて食い違う場合。
    """
    missing = [
        attribute_name
        for attribute_name in BOUNDING_COORD_ATTRIBUTES.values()
        if attribute_name not in root_attributes
    ]
    if missing:
        raise KeyError(
            f"境界座標の属性が見つかりません: {missing}"
            f"（実在する属性: {sorted(root_attributes)}）。"
        )

    west, south, east, north = compute_tile_bounds(tile)
    expected = {"west": west, "east": east, "north": north, "south": south}
    actual = {
        key: float(root_attributes[attribute_name])
        for key, attribute_name in BOUNDING_COORD_ATTRIBUTES.items()
    }

    mismatched = {
        key: (actual[key], expected[key])
        for key in expected
        if abs(actual[key] - expected[key]) > tolerance
    }
    if mismatched:
        raise ValueError(
            f"タイル {tile.name} の境界座標がファイル属性と一致しません"
            f"（実測 vs タイル番号由来: {mismatched}）。"
        )

    return {"tile": tile.name, "attribute_bounds": actual, "tile_index_bounds": expected}
