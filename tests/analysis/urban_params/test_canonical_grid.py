"""canonical_grid.py（正準グリッドの仕様定義・cell_id採番）のテスト。

解析用CRSにはEPSG:3857を用いる（既存テストと揃えている）。原点スナップ・
インデックス採番のロジックはCRSの種類ではなく座標値で決まるため、投影座標系で
あればどれでも同じ経路を通る。

ただし**採番できるかは座標値の大きさに依存する**。cell_idの桁設計上 col は
1,000,000 未満である必要があり、座標値の大きいCRS・細かい解像度の組合せでは
この上限を超える。本ファイルは小さな合成座標を使うため上限には触れないので、
上限側の挙動は専用のテストで別途検証している。
"""

from __future__ import annotations

import numpy as np
import pytest
from pyproj import CRS

from src.analysis.urban_params.canonical_grid import (
    CELL_ID_MAX_ROW,
    CELL_ID_STRIDE,
    SNAP_UNIT_M,
    build_canonical_grid,
    make_cell_id,
    snap_origin,
    split_cell_id,
)
from src.common.geo_metadata import BBox

ANALYSIS_CRS = CRS.from_epsg(3857)

# 原点(0, 0)・res=30m のとき col 30-59 / row 60-89（30x30セル）となるBBox。
SAMPLE_BBOX = BBox(900.0, 1800.0, 1800.0, 2700.0)


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
