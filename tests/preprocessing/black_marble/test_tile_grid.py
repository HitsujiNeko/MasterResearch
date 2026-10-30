"""タイル格子（`black_marble.tile_grid`）のテスト。"""

from __future__ import annotations

import pytest

from src.preprocessing.black_marble import tile_grid as target
from tests.helpers import HANOI_ROI_BOUNDS


class TestResolveBlackMarbleTiles:
    """resolve_black_marble_tiles のテスト。"""

    def test_hanoi_roi_fits_in_a_single_tile(self) -> None:
        """Hanoi ROI は h28v06 の 1 タイルに収まる。"""
        tiles = target.resolve_black_marble_tiles(HANOI_ROI_BOUNDS)

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_tile_name_is_zero_padded(self) -> None:
        """タイル名は 2 桁ゼロ詰め（配布ファイル名と一致させるため）。"""
        assert target.TileIndex(horizontal=3, vertical=7).name == "h03v07"

    def test_spans_multiple_tiles_when_bbox_crosses_boundary(self) -> None:
        """タイル境界をまたぐ BBOX では、はみ出した先のタイルも含めて返す。

        経度 99.5-110.5 は h27（90-100E）・h28（100-110E）・h29（110-120E）に、
        緯度 19.5-30.5 は v05（30-40N）・v06（20-30N）・v07（10-20N）にまたがる。
        並び順は北西から南東（v の昇順 → h の昇順）。
        """
        tiles = target.resolve_black_marble_tiles((99.5, 19.5, 110.5, 30.5))

        assert [tile.name for tile in tiles] == [
            "h27v05",
            "h28v05",
            "h29v05",
            "h27v06",
            "h28v06",
            "h29v06",
            "h27v07",
            "h28v07",
            "h29v07",
        ]

    def test_east_edge_on_tile_boundary_does_not_add_empty_tile(self) -> None:
        """東端がちょうどタイル境界の場合、重なりの無い隣のタイルを拾わない。"""
        tiles = target.resolve_black_marble_tiles((100.0, 20.0, 110.0, 30.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_south_edge_on_tile_boundary_does_not_add_empty_tile(self) -> None:
        """南端がちょうどタイル境界の場合も同様。"""
        tiles = target.resolve_black_marble_tiles((100.5, 20.0, 100.6, 21.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_northwest_corner_maps_to_first_tile(self) -> None:
        """グリッド原点（-180E, 90N）は h00v00。"""
        tiles = target.resolve_black_marble_tiles((-180.0, 85.0, -179.0, 90.0))

        assert [tile.name for tile in tiles] == ["h00v00"]

    def test_southeast_corner_maps_to_last_tile(self) -> None:
        """南東端（180E, -90N）は h35v17（範囲外の索引を作らない）。"""
        tiles = target.resolve_black_marble_tiles((179.0, -90.0, 180.0, -89.0))

        assert [tile.name for tile in tiles] == ["h35v17"]

    def test_degenerate_bbox_still_returns_one_tile(self) -> None:
        """幅・高さが 0 の BBOX でも 1 タイルは返す（空リストにしない）。"""
        tiles = target.resolve_black_marble_tiles((105.8, 21.0, 105.8, 21.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_degenerate_bbox_at_grid_maximum_still_returns_one_tile(self) -> None:
        """経度 180・緯度 -90 ちょうどの縮退 BBOX でも空リストにしない。

        この位置では索引式が索引上限を 1 超えるため、丸め方を誤ると開始 > 終了と
        なり空リストになる。呼び出し側は `tiles[0]` を取るので、素の IndexError に
        化けて原因が読めなくなる。
        """

        def tile_names(bounds: tuple[float, float, float, float]) -> list[str]:
            """指定 BBOX を覆うタイル名の一覧を返す。"""
            return [tile.name for tile in target.resolve_black_marble_tiles(bounds)]

        assert tile_names((180.0, -90.0, 180.0, -90.0)) == ["h35v17"]
        assert tile_names((180.0, 20.0, 180.0, 21.0)) == ["h35v06"]
        assert tile_names((105.0, -90.0, 106.0, -90.0)) == ["h28v17"]

    def test_rejects_out_of_range_bbox(self) -> None:
        """経緯度の値域を外れる BBOX は弾く。"""
        with pytest.raises(ValueError, match="値域"):
            target.resolve_black_marble_tiles((105.0, 20.0, 190.0, 21.0))


class TestComputeTileBounds:
    """compute_tile_bounds のテスト。"""

    def test_hanoi_tile_covers_expected_range(self) -> None:
        """h28v06 は経度 100-110E・緯度 20-30N を覆う。"""
        bounds = target.compute_tile_bounds(target.TileIndex(28, 6))

        assert bounds == pytest.approx((100.0, 20.0, 110.0, 30.0))

    def test_origin_tile_starts_at_grid_origin(self) -> None:
        """h00v00 は北西端の原点から始まる。"""
        bounds = target.compute_tile_bounds(target.TileIndex(0, 0))

        assert bounds == pytest.approx((-180.0, 80.0, -170.0, 90.0))

    def test_roi_is_contained_in_resolved_tile(self) -> None:
        """解決したタイルが実際に ROI を包含する（索引式の符号ミスを検出する）。"""
        tile = target.resolve_black_marble_tiles(HANOI_ROI_BOUNDS)[0]
        west, south, east, north = target.compute_tile_bounds(tile)

        assert west <= HANOI_ROI_BOUNDS[0] and HANOI_ROI_BOUNDS[2] <= east
        assert south <= HANOI_ROI_BOUNDS[1] and HANOI_ROI_BOUNDS[3] <= north


class TestVerifyTileGeoreference:
    """verify_tile_georeference のテスト。"""

    def test_accepts_matching_bounds(self) -> None:
        """属性とタイル番号由来の境界が一致すれば通す。"""
        tile = target.TileIndex(28, 6)
        attributes = {
            "WestBoundingCoord": 100.0,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        result = target.verify_tile_georeference(attributes, tile)

        assert result["tile"] == "h28v06"

    def test_rejects_mismatched_bounds(self) -> None:
        """食い違えば、タイル番号の読み違いを疑って止める。"""
        tile = target.TileIndex(28, 6)
        attributes = {
            "WestBoundingCoord": 110.0,
            "EastBoundingCoord": 120.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        with pytest.raises(ValueError, match="一致しません"):
            target.verify_tile_georeference(attributes, tile)

    def test_accepts_difference_within_tolerance(self) -> None:
        """許容差の内側のずれは通す（丸め誤差で止まらないことの担保）。"""
        attributes = {
            "WestBoundingCoord": 100.0 + target.GEOREFERENCE_TOLERANCE_DEG / 2,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        result = target.verify_tile_georeference(attributes, target.TileIndex(28, 6))

        assert result["tile"] == "h28v06"

    def test_rejects_difference_over_tolerance(self) -> None:
        """許容差を超えるずれは、値が近くても弾く。"""
        attributes = {
            "WestBoundingCoord": 100.0 + target.GEOREFERENCE_TOLERANCE_DEG * 10,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        with pytest.raises(ValueError, match="一致しません"):
            target.verify_tile_georeference(attributes, target.TileIndex(28, 6))

    def test_raises_when_attributes_are_missing(self) -> None:
        """境界座標の属性が欠けていれば例外にする。"""
        with pytest.raises(KeyError, match="BoundingCoord"):
            target.verify_tile_georeference({"WestBoundingCoord": 100.0}, target.TileIndex(28, 6))
