"""canonical_grid.py（正準グリッド）のテスト。

解析用CRSにはEPSG:3857を用いる（既存テストと揃えている）。原点スナップ・
インデックス採番のロジックはCRSの種類ではなく座標値で決まるため、投影座標系で
あればどれでも同じ経路を通る。

ただし**採番できるかは座標値の大きさに依存する**。cell_idの桁設計上 col は
1,000,000 未満である必要があり、座標値の大きいCRS・細かい解像度の組合せでは
この上限を超える。本ファイルは小さな合成座標を使うため上限には触れないので、
上限側の挙動は専用のテストで別途検証している。
"""

from __future__ import annotations

from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS, Transformer
from shapely.geometry import Polygon

from src.analysis.urban_params.canonical_grid import (
    CELL_ID_MAX_ROW,
    CELL_ID_STRIDE,
    SNAP_UNIT_M,
    CanonicalGridSpec,
    build_canonical_grid,
    iter_cell_blocks,
    make_cell_id,
    resolve_output_path,
    snap_origin,
    split_cell_id,
    write_grid_layers,
)
from src.common.geo_metadata import BBox

ANALYSIS_CRS = CRS.from_epsg(3857)

# 原点(0, 0)・res=30m のとき col 30-59 / row 60-89（30x30セル）となるBBox。
SAMPLE_BBOX = BBox(900.0, 1800.0, 1800.0, 2700.0)

# 900mの正方形。30m/90m/300mのいずれでも割り切れ、親子対応の件数を手計算できる。
NESTED_BBOX = BBox(0.0, 0.0, 900.0, 900.0)


def _collect_cells(
    grid_spec: CanonicalGridSpec,
    block_rows: int = 500,
    mask_geometries: np.ndarray | None = None,
) -> gpd.GeoDataFrame:
    """全ブロックのセルを1つのGeoDataFrameへまとめる（テスト用）。"""
    blocks = [
        block
        for block in iter_cell_blocks(grid_spec, block_rows, mask_geometries)
        if len(block) > 0
    ]
    if not blocks:
        return gpd.GeoDataFrame(geometry=[], crs=grid_spec.analysis_crs)
    return gpd.GeoDataFrame(pd.concat(blocks, ignore_index=True), crs=grid_spec.analysis_crs)


def _bounds_keyed_cell_ids(cells: gpd.GeoDataFrame) -> pd.DataFrame:
    """セル矩形の境界座標をキーとする cell_id 表を作る（テスト用）。"""
    keyed = cells.geometry.bounds.round(6)
    keyed["cell_id"] = cells["cell_id"].to_numpy()
    return keyed


# --- snap_origin ---------------------------------------------------------


def test_snap_origin_floors_to_multiple() -> None:
    """倍数でない値は900mの倍数へ切り下げられる。"""
    assert snap_origin(1234.5) == 900.0
    assert snap_origin(899.9) == 0.0


def test_snap_origin_keeps_exact_multiple() -> None:
    """既に900mの倍数である値は変わらない。"""
    assert snap_origin(0.0) == 0.0
    assert snap_origin(1800.0) == 1800.0


def test_snap_origin_floors_negative_value() -> None:
    """負値でも切り上げではなく切り下げになる。"""
    assert snap_origin(-100.0) == -900.0
    assert snap_origin(-900.0) == -900.0
    assert snap_origin(-901.0) == -1800.0


def test_snap_origin_invalid_unit_raises() -> None:
    """スナップ単位が正でない場合はValueErrorになる。"""
    with pytest.raises(ValueError, match="snap_unit_m"):
        snap_origin(1234.5, snap_unit_m=0.0)


# --- build_canonical_grid ------------------------------------------------


def test_build_canonical_grid_origin_is_snap_unit_multiple() -> None:
    """原点が900mの倍数にスナップされている（完了条件）。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)

    assert grid_spec.origin_x % SNAP_UNIT_M == 0.0
    assert grid_spec.origin_y % SNAP_UNIT_M == 0.0


def test_build_canonical_grid_origin_is_independent_of_bbox() -> None:
    """解析範囲を変えても原点は動かない（cell_id不変性の前提）。"""
    narrow = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)
    wide = build_canonical_grid(BBox(30.0, 60.0, 12345.0, 23456.0), ANALYSIS_CRS, res_m=30.0)

    assert narrow.origin_x == wide.origin_x
    assert narrow.origin_y == wide.origin_y


def test_build_canonical_grid_index_range() -> None:
    """原点からの絶対インデックスが手計算値と一致する。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)

    assert (grid_spec.col_min, grid_spec.col_max) == (30, 59)
    assert (grid_spec.row_min, grid_spec.row_max) == (60, 89)
    assert (grid_spec.n_cols, grid_spec.n_rows, grid_spec.n_cells) == (30, 30, 900)


def test_build_canonical_grid_covers_bbox_minimally() -> None:
    """インデックス範囲がBBoxを覆い、かつ余分なセルを持たない。"""
    bbox = BBox(905.0, 1795.0, 1801.0, 2702.0)
    grid_spec = build_canonical_grid(bbox, ANALYSIS_CRS, res_m=30.0)

    left = grid_spec.origin_x + (grid_spec.col_min * grid_spec.res_m)
    right = grid_spec.origin_x + ((grid_spec.col_max + 1) * grid_spec.res_m)
    bottom = grid_spec.origin_y + (grid_spec.row_min * grid_spec.res_m)
    top = grid_spec.origin_y + ((grid_spec.row_max + 1) * grid_spec.res_m)

    # BBoxを覆う。
    assert left <= bbox.minx and right >= bbox.maxx
    assert bottom <= bbox.miny and top >= bbox.maxy
    # 端のセルを1つ削るとBBoxを覆えなくなる（＝余分なセルが無い）。
    assert left + grid_spec.res_m > bbox.minx
    assert right - grid_spec.res_m < bbox.maxx
    assert bottom + grid_spec.res_m > bbox.miny
    assert top - grid_spec.res_m < bbox.maxy


def test_build_canonical_grid_bbox_on_cell_boundary() -> None:
    """BBoxの端がセル境界にちょうど載る場合、幅ゼロの余分なセルを作らない。"""
    grid_spec = build_canonical_grid(BBox(0.0, 0.0, 900.0, 900.0), ANALYSIS_CRS, res_m=30.0)

    assert (grid_spec.col_min, grid_spec.col_max) == (0, 29)
    assert (grid_spec.row_min, grid_spec.row_max) == (0, 29)


@pytest.mark.parametrize("res_m", [30.0, 90.0, 300.0, 10.0])
def test_build_canonical_grid_accepts_snap_unit_divisors(res_m: float) -> None:
    """900mの約数である解像度は受け付ける。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=res_m)

    assert grid_spec.res_m == res_m


def test_build_canonical_grid_non_divisor_resolution_raises() -> None:
    """900mの約数でない解像度（40m）はValueErrorになる。"""
    with pytest.raises(ValueError, match="約数"):
        build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=40.0)


def test_build_canonical_grid_invalid_resolution_raises() -> None:
    """解像度が正でない場合はValueErrorになる。"""
    with pytest.raises(ValueError, match="res_m"):
        build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=0.0)


def test_build_canonical_grid_degenerate_bbox_raises() -> None:
    """幅・高さが正でないBBoxはValueErrorになる。"""
    with pytest.raises(ValueError, match="bbox_analysis"):
        build_canonical_grid(BBox(900.0, 1800.0, 900.0, 2700.0), ANALYSIS_CRS, res_m=30.0)


def test_build_canonical_grid_negative_index_raises() -> None:
    """原点より西・南にはみ出すBBoxは仕様構築の時点でValueErrorになる。

    採番できないインデックスをそのまま返すと、セル生成まで進んでから
    make_cell_id() で落ち、原因が読み取りにくくなる。
    """
    with pytest.raises(ValueError, match="採番範囲に収まりません"):
        build_canonical_grid(BBox(-5000.0, -5000.0, 12345.0, 23456.0), ANALYSIS_CRS, res_m=30.0)


def test_build_canonical_grid_col_overflow_raises() -> None:
    """col が cell_id の桁上限を超える組合せは仕様構築の時点でValueErrorになる。

    座標値の大きいCRSと細かい解像度を組み合わせると col が 1,000,000 を超える。
    """
    with pytest.raises(ValueError, match="採番範囲に収まりません"):
        build_canonical_grid(BBox(11.70e6, 2.30e6, 11.71e6, 2.31e6), ANALYSIS_CRS, res_m=10.0)


def test_build_canonical_grid_geographic_crs_raises() -> None:
    """地理座標系（度単位）を渡した場合はValueErrorになる。

    res_m をメートルとして扱うため、度単位のCRSでは黙って無意味なグリッドが
    できてしまう。これを実行時に防ぐ。
    """
    with pytest.raises(ValueError, match="投影座標系"):
        build_canonical_grid(BBox(105.0, 20.0, 106.0, 21.0), CRS.from_epsg(4326), res_m=30.0)


# --- make_cell_id / split_cell_id ----------------------------------------


@pytest.mark.parametrize(
    ("row", "col"),
    [(0, 0), (1, 5), (78864, 20205), (0, CELL_ID_STRIDE - 1)],
)
def test_cell_id_round_trip(row: int, col: int) -> None:
    """make_cell_id と split_cell_id は往復して元の (row, col) に戻る。"""
    cell_id = make_cell_id(row, col)

    assert isinstance(cell_id, int)
    assert split_cell_id(cell_id) == (row, col)


def test_cell_id_round_trip_with_arrays() -> None:
    """配列入力でも往復して元の (row, col) に戻る。"""
    rows = np.array([0, 1, 78864], dtype=np.int64)
    cols = np.array([0, 5, 20205], dtype=np.int64)

    cell_ids = make_cell_id(rows, cols)
    restored_rows, restored_cols = split_cell_id(cell_ids)

    assert cell_ids.dtype == np.int64
    np.testing.assert_array_equal(restored_rows, rows)
    np.testing.assert_array_equal(restored_cols, cols)


def test_cell_id_is_unique_for_distinct_indices() -> None:
    """異なる (row, col) は異なる cell_id になる。"""
    rows, cols = np.meshgrid(np.arange(60, 90), np.arange(30, 60), indexing="ij")

    cell_ids = make_cell_id(rows.ravel(), cols.ravel())

    assert len(np.unique(cell_ids)) == cell_ids.size


@pytest.mark.parametrize("col", [-1, CELL_ID_STRIDE, CELL_ID_STRIDE + 1])
def test_make_cell_id_out_of_range_col_raises(col: int) -> None:
    """colが0未満または桁上限以上の場合はValueErrorになる。"""
    with pytest.raises(ValueError, match="col は"):
        make_cell_id(1, col)


def test_make_cell_id_negative_row_raises() -> None:
    """rowが0未満の場合はValueErrorになる。"""
    with pytest.raises(ValueError, match="row は"):
        make_cell_id(-1, 5)


def test_make_cell_id_detects_out_of_range_in_array() -> None:
    """配列の一部だけが範囲外でもValueErrorになる。"""
    with pytest.raises(ValueError, match="col は"):
        make_cell_id(np.array([1, 2]), np.array([5, CELL_ID_STRIDE]))


@pytest.mark.parametrize(("row", "col"), [(1.9, 2.9), (1, 2.0), (1.0, 2)])
def test_make_cell_id_float_raises(row: float, col: float) -> None:
    """小数を渡した場合はValueErrorになる。

    int64 への変換で黙って切り捨てられ、例外なしに誤った cell_id を返すため。
    """
    with pytest.raises(ValueError, match="整数で指定してください"):
        make_cell_id(row, col)


def test_make_cell_id_row_overflow_raises() -> None:
    """row が int64 の桁を溢れさせる大きさの場合はValueErrorになる。

    検証がないと負値の cell_id を例外なしに返す。
    """
    with pytest.raises(ValueError, match="row は"):
        make_cell_id(CELL_ID_MAX_ROW + 1, 0)


def test_make_cell_id_accepts_max_row() -> None:
    """上限ちょうどの row は受け付け、cell_id が正のまま往復する。"""
    cell_id = make_cell_id(CELL_ID_MAX_ROW, CELL_ID_STRIDE - 1)

    assert cell_id > 0
    assert split_cell_id(cell_id) == (CELL_ID_MAX_ROW, CELL_ID_STRIDE - 1)


def test_split_cell_id_negative_raises() -> None:
    """負の cell_id はValueErrorになる（make_cell_id は生成しないため）。"""
    with pytest.raises(ValueError, match="cell_id は"):
        split_cell_id(-1)


# --- iter_cell_blocks（セルポリゴン生成） --------------------------------


def test_iter_cell_blocks_cell_id_is_unique() -> None:
    """1レイヤ分の全セルで cell_id が一意である（完了条件）。"""
    cells = _collect_cells(build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0))

    assert len(cells) == 900
    assert cells["cell_id"].nunique() == len(cells)


def test_iter_cell_blocks_cell_geometry_matches_index() -> None:
    """セル矩形の四隅が origin + index * res と一致し、面積が res^2 になる。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)

    cells = _collect_cells(grid_spec)
    bounds = cells.geometry.bounds

    expected_minx = grid_spec.origin_x + (cells["col"].to_numpy() * grid_spec.res_m)
    expected_miny = grid_spec.origin_y + (cells["row"].to_numpy() * grid_spec.res_m)
    np.testing.assert_allclose(bounds["minx"].to_numpy(), expected_minx)
    np.testing.assert_allclose(bounds["miny"].to_numpy(), expected_miny)
    np.testing.assert_allclose(bounds["maxx"].to_numpy(), expected_minx + grid_spec.res_m)
    np.testing.assert_allclose(bounds["maxy"].to_numpy(), expected_miny + grid_spec.res_m)
    np.testing.assert_allclose(cells.geometry.area.to_numpy(), grid_spec.res_m**2)


def test_iter_cell_blocks_lon_lat_are_cell_centers() -> None:
    """lon / lat がセル中心のWGS84座標と一致する。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)
    to_wgs84 = Transformer.from_crs(ANALYSIS_CRS, CRS.from_epsg(4326), always_xy=True)

    cells = _collect_cells(grid_spec)
    centroids = cells.geometry.centroid
    expected_lon, expected_lat = to_wgs84.transform(centroids.x.to_numpy(), centroids.y.to_numpy())

    np.testing.assert_allclose(cells["lon"].to_numpy(), expected_lon)
    np.testing.assert_allclose(cells["lat"].to_numpy(), expected_lat)


def test_iter_cell_blocks_cell_id_is_invariant_to_extent() -> None:
    """解析範囲を広げても、同じ座標のセルは同じ cell_id を持つ（完了条件）。"""
    narrow = _collect_cells(
        build_canonical_grid(BBox(900.0, 900.0, 1800.0, 1800.0), ANALYSIS_CRS, res_m=30.0)
    )
    wide = _collect_cells(
        build_canonical_grid(BBox(0.0, 0.0, 2700.0, 2700.0), ANALYSIS_CRS, res_m=30.0)
    )

    merged = _bounds_keyed_cell_ids(narrow).merge(
        _bounds_keyed_cell_ids(wide),
        on=["minx", "miny", "maxx", "maxy"],
        suffixes=("_narrow", "_wide"),
    )

    # 狭い側のセルはすべて広い側にも存在し、cell_id が一致する。
    assert len(merged) == len(narrow) == 900
    assert (merged["cell_id_narrow"] == merged["cell_id_wide"]).all()


def test_iter_cell_blocks_parent_ids_cover_nine_and_hundred_children() -> None:
    """90mセル1つに30mセルが9個、300mセル1つに100個対応する（完了条件）。"""
    cells_30m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=30.0))

    assert len(cells_30m) == 900
    assert (cells_30m.groupby("parent_id_90").size() == 9).all()
    assert (cells_30m.groupby("parent_id_300").size() == 100).all()


def test_iter_cell_blocks_parent_ids_match_parent_layer_cell_ids() -> None:
    """parent_id が親スケールのレイヤの cell_id と厳密に一致する（完了条件）。"""
    cells_30m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=30.0))
    cells_90m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=90.0))
    cells_300m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0))

    assert set(cells_30m["parent_id_90"]) == set(cells_90m["cell_id"])
    assert set(cells_30m["parent_id_300"]) == set(cells_300m["cell_id"])


def test_iter_cell_blocks_parent_ids_only_on_base_scale() -> None:
    """90m / 300m レイヤは親セル列を持たない（入れ子にならないため）。"""
    cells_90m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=90.0))
    cells_300m = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0))

    for cells in (cells_90m, cells_300m):
        assert "parent_id_90" not in cells.columns
        assert "parent_id_300" not in cells.columns


@pytest.mark.parametrize("block_rows", [1, 7, 30, 1000])
def test_iter_cell_blocks_result_is_independent_of_block_size(block_rows: int) -> None:
    """block_rows を変えても総件数・cell_id 集合が変わらない。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)
    baseline = _collect_cells(grid_spec, block_rows=500)

    cells = _collect_cells(grid_spec, block_rows=block_rows)

    assert len(cells) == len(baseline)
    assert set(cells["cell_id"]) == set(baseline["cell_id"])


def test_iter_cell_blocks_block_count_is_predictable() -> None:
    """ブロック数は行数と block_rows のみで決まる（空ブロックも返す）。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)

    blocks = list(iter_cell_blocks(grid_spec, block_rows=7))

    # 30行を7行ずつ区切ると 7+7+7+7+2 の5ブロックになる。
    assert len(blocks) == 5
    assert [len(block) for block in blocks] == [7 * 30, 7 * 30, 7 * 30, 7 * 30, 2 * 30]


def test_iter_cell_blocks_invalid_block_rows_raises() -> None:
    """block_rows が正でない場合はValueErrorになる。"""
    grid_spec = build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, res_m=30.0)

    with pytest.raises(ValueError, match="block_rows"):
        list(iter_cell_blocks(grid_spec, block_rows=0))


def test_iter_cell_blocks_mask_excludes_outside_cells() -> None:
    """マスクポリゴンと交差しないセルが除外される。"""
    grid_spec = build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0)
    # 3x3セルのうち左下1セル（0-300, 0-300）の内側だけを覆うポリゴン。
    mask = np.array([Polygon([(10.0, 10.0), (290.0, 10.0), (290.0, 290.0), (10.0, 290.0)])])

    cells = _collect_cells(grid_spec, mask_geometries=mask)

    assert len(cells) == 1
    assert cells["row"].tolist() == [0]
    assert cells["col"].tolist() == [0]


def test_iter_cell_blocks_mask_includes_touching_cells() -> None:
    """セル境界にかかるポリゴンは、またぐ両側のセルを残す（交差判定のため）。"""
    grid_spec = build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0)
    # x=300 の境界をまたぐポリゴン。左下と右下の2セルに跨る。
    mask = np.array([Polygon([(290.0, 10.0), (310.0, 10.0), (310.0, 290.0), (290.0, 290.0)])])

    cells = _collect_cells(grid_spec, mask_geometries=mask)

    assert len(cells) == 2
    assert sorted(cells["col"].tolist()) == [0, 1]


def test_iter_cell_blocks_mask_deduplicates_overlapping_polygons() -> None:
    """複数のマスクポリゴンが重なってもセルが重複しない。"""
    grid_spec = build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0)
    overlapping = np.array(
        [
            Polygon([(10.0, 10.0), (290.0, 10.0), (290.0, 290.0), (10.0, 290.0)]),
            Polygon([(20.0, 20.0), (280.0, 20.0), (280.0, 280.0), (20.0, 280.0)]),
        ]
    )

    cells = _collect_cells(grid_spec, mask_geometries=overlapping)

    assert len(cells) == 1


# --- write_grid_layers（GeoPackage出力） ---------------------------------


def test_write_grid_layers_creates_three_layers(tmp_path: Path) -> None:
    """30m / 90m / 300m の3レイヤが出力される（完了条件）。"""
    output_path = tmp_path / "grid_test.gpkg"

    cell_counts = write_grid_layers(
        NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90, 300], block_rows=7
    )

    assert set(fiona.listlayers(output_path)) >= {"grid_30m", "grid_90m", "grid_300m"}
    assert cell_counts == {"grid_30m": 900, "grid_90m": 100, "grid_300m": 9}
    for layer_name, expected_count in cell_counts.items():
        assert len(gpd.read_file(output_path, layer=layer_name)) == expected_count


def test_write_grid_layers_schema_and_dtypes(tmp_path: Path) -> None:
    """CRS・列名・dtypeが仕様どおりに保存される。"""
    output_path = tmp_path / "grid_test.gpkg"
    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90], block_rows=7)

    cells_30m = gpd.read_file(output_path, layer="grid_30m")
    cells_90m = gpd.read_file(output_path, layer="grid_90m")

    assert cells_30m.crs == ANALYSIS_CRS
    assert set(cells_30m.columns) == {
        "cell_id",
        "row",
        "col",
        "lon",
        "lat",
        "parent_id_90",
        "parent_id_300",
        "geometry",
    }
    assert set(cells_90m.columns) == {"cell_id", "row", "col", "lon", "lat", "geometry"}
    assert cells_30m["cell_id"].dtype == np.int64
    assert cells_30m["row"].dtype == np.int32
    assert cells_30m["col"].dtype == np.int32
    assert cells_30m["lon"].dtype == np.float64
    assert cells_30m["lat"].dtype == np.float64
    assert cells_30m["parent_id_90"].dtype == np.int64
    assert cells_30m["parent_id_300"].dtype == np.int64


def test_write_grid_layers_cell_id_unique_per_layer(tmp_path: Path) -> None:
    """保存後のレイヤでも cell_id が一意である（完了条件）。"""
    output_path = tmp_path / "grid_test.gpkg"
    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90, 300], block_rows=7)

    for layer_name in ("grid_30m", "grid_90m", "grid_300m"):
        cells = gpd.read_file(output_path, layer=layer_name)
        assert cells["cell_id"].nunique() == len(cells)


def test_write_grid_layers_refuses_existing_file(tmp_path: Path) -> None:
    """既存ファイルへは overwrite なしで書き込まない。"""
    output_path = tmp_path / "grid_test.gpkg"
    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[300], block_rows=7)

    with pytest.raises(FileExistsError, match="overwrite"):
        write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[300], block_rows=7)


def test_write_grid_layers_overwrite_does_not_duplicate(tmp_path: Path) -> None:
    """overwrite での再実行後もセル数が倍にならない（重複防止の回帰テスト）。"""
    output_path = tmp_path / "grid_test.gpkg"
    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90], block_rows=7)

    cell_counts = write_grid_layers(
        NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90], block_rows=7, overwrite=True
    )

    assert cell_counts == {"grid_30m": 900, "grid_90m": 100}
    assert len(gpd.read_file(output_path, layer="grid_30m")) == 900
    assert len(gpd.read_file(output_path, layer="grid_90m")) == 100


def test_write_grid_layers_keeps_earlier_layers(tmp_path: Path) -> None:
    """後続レイヤの書き出しで先行レイヤが消えない。"""
    output_path = tmp_path / "grid_test.gpkg"
    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[30, 90, 300], block_rows=7)

    # 最初に書いた 30m レイヤが 90m / 300m の書き出し後も残っている。
    assert len(gpd.read_file(output_path, layer="grid_30m")) == 900


def test_write_grid_layers_empty_mask_raises(tmp_path: Path) -> None:
    """マスクと交差するセルが1件も無い場合はValueErrorになる。"""
    output_path = tmp_path / "grid_test.gpkg"
    # グリッド範囲外のポリゴン。
    outside = np.array(
        [Polygon([(5000.0, 5000.0), (5100.0, 5000.0), (5100.0, 5100.0), (5000.0, 5100.0)])]
    )

    with pytest.raises(ValueError, match="書き出すセルがありません"):
        write_grid_layers(
            NESTED_BBOX,
            ANALYSIS_CRS,
            output_path,
            scales=[300],
            mask_geometries=outside,
            block_rows=7,
        )


def test_write_grid_layers_creates_parent_directory(tmp_path: Path) -> None:
    """出力先の親ディレクトリが存在しない場合は作成する。"""
    output_path = tmp_path / "nested" / "dir" / "grid_test.gpkg"

    write_grid_layers(NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[300], block_rows=7)

    assert output_path.exists()


def test_write_grid_layers_masked_output_is_subset(tmp_path: Path) -> None:
    """マスク適用時も cell_id はマスクなしの場合と同じ値を保つ。"""
    output_path = tmp_path / "grid_masked.gpkg"
    mask = np.array([Polygon([(10.0, 10.0), (290.0, 10.0), (290.0, 290.0), (10.0, 290.0)])])
    write_grid_layers(
        NESTED_BBOX, ANALYSIS_CRS, output_path, scales=[300], mask_geometries=mask, block_rows=7
    )

    masked = gpd.read_file(output_path, layer="grid_300m")
    unmasked = _collect_cells(build_canonical_grid(NESTED_BBOX, ANALYSIS_CRS, res_m=300.0))

    assert set(masked["cell_id"]).issubset(set(unmasked["cell_id"]))
    assert len(masked) == 1


# --- resolve_output_path -------------------------------------------------


def test_resolve_output_path_default_is_city_specific() -> None:
    """--output 未指定なら data/output/grid/grid_{city}.gpkg になる。"""
    output_path = resolve_output_path("", "hanoi")

    assert output_path.is_absolute()
    assert output_path.parts[-3:] == ("output", "grid", "grid_hanoi.gpkg")


def test_resolve_output_path_relative_is_project_root_based() -> None:
    """相対パスはプロジェクトルート基準で解決される。"""
    output_path = resolve_output_path("data/tmp/custom.gpkg", "hanoi")

    assert output_path.is_absolute()
    assert output_path.parts[-3:] == ("data", "tmp", "custom.gpkg")


def test_resolve_output_path_absolute_is_kept(tmp_path: Path) -> None:
    """絶対パスはそのまま使う（検証時に任意の場所へ書き出せる）。"""
    absolute_path = tmp_path / "custom.gpkg"

    assert resolve_output_path(str(absolute_path), "hanoi") == absolute_path
