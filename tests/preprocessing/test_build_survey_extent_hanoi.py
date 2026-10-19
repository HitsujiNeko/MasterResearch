"""build_survey_extent_hanoi.py（測量GIS有効域ポリゴンの生成）のテスト。

合成した図郭（2×2 図葉）で、内枠の選別・面化・クロージング・検証を確かめる。実データと
同じく、隣接図葉の内枠どうしの間にわずかな隙間を空け、外枠（別の Level）と目盛り線
（同じ Level の短い線）を混ぜる。
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pyogrio
import pytest
from shapely import LineString, MultiPolygon, Point, Polygon, box

from src.preprocessing.build_survey_extent_hanoi import (
    EXPECTED_SHEET_COUNT,
    INNER_FRAME_LEVEL,
    assign_crs,
    build_survey_extent,
    close_gaps,
    polygonize_sheets,
    select_inner_frame_lines,
    validate_extent,
    write_extent,
)

# 合成図葉の1辺（m）と、隣接図葉の内枠どうしの隙間（m）。
SHEET_SIZE = 1000.0
SHEET_GAP = 0.2
OUTER_FRAME_LEVEL = 7


def _sheet_box(col: int, row: int, gap: float = SHEET_GAP) -> Polygon:
    """col 列・row 行目の図葉の内枠（隙間を除いた正方形）を返す。"""
    x0 = col * (SHEET_SIZE + gap)
    y0 = row * (SHEET_SIZE + gap)
    return box(x0, y0, x0 + SHEET_SIZE, y0 + SHEET_SIZE)


def _edges(polygon: Polygon) -> list[LineString]:
    """矩形の外周を4辺の LineString に分ける（実データは辺ごとに別の線として持つ）。"""
    coords = list(polygon.exterior.coords)
    return [LineString([coords[i], coords[i + 1]]) for i in range(4)]


def _make_cs_frame(
    cells: list[tuple[int, int]],
    gap: float = SHEET_GAP,
) -> gpd.GeoDataFrame:
    """内枠・外枠・目盛り線・点注記を混ぜた合成 CS レイヤを作る。"""
    levels: list[int] = []
    geometries: list = []
    for col, row in cells:
        inner = _sheet_box(col, row, gap)
        for edge in _edges(inner):
            levels.append(INNER_FRAME_LEVEL)
            geometries.append(edge)
        # 外枠は内枠より外側に張り出し、隣接図葉の外枠と重なる。
        for edge in _edges(inner.buffer(25.0, join_style="mitre")):
            levels.append(OUTER_FRAME_LEVEL)
            geometries.append(edge)
        # 内枠と同じ Level の目盛り線（短い線）。内枠の辺から外へ突き出す。
        min_x, min_y, _, _ = inner.bounds
        levels.append(INNER_FRAME_LEVEL)
        geometries.append(LineString([(min_x + 500.0, min_y), (min_x + 500.0, min_y - 25.0)]))
        # 図葉番号などの注記（点）。
        levels.append(INNER_FRAME_LEVEL)
        geometries.append(Point(min_x + 10.0, min_y + 10.0))
    return gpd.GeoDataFrame({"Level": levels}, geometry=geometries, crs="EPSG:5897")


GRID_2X2 = [(0, 0), (1, 0), (0, 1), (1, 1)]


def test_assign_crs_sets_crs_when_missing() -> None:
    """CRS を持たないレイヤには設定値の CRS を付与する。"""
    gdf = gpd.GeoDataFrame({"Level": [5]}, geometry=[Point(0, 0)])

    result = assign_crs(gdf, 5897)

    assert result.crs.to_epsg() == 5897


def test_assign_crs_keeps_matching_crs() -> None:
    """設定値と同じ CRS を持つレイヤはそのまま返す。"""
    gdf = gpd.GeoDataFrame({"Level": [5]}, geometry=[Point(0, 0)], crs="EPSG:5897")

    result = assign_crs(gdf, 5897)

    assert result.crs.to_epsg() == 5897


def test_assign_crs_rejects_different_crs() -> None:
    """設定値と異なる CRS を持つレイヤは上書きせず例外にする。"""
    gdf = gpd.GeoDataFrame({"Level": [5]}, geometry=[Point(0, 0)], crs="EPSG:4326")

    with pytest.raises(ValueError, match="CRS が想定と異なります"):
        assign_crs(gdf, 5897)


def test_select_inner_frame_lines_keeps_only_long_lines_of_level() -> None:
    """内枠の Level の長い線だけを選び、外枠・目盛り線・点を除く。"""
    cs_gdf = _make_cs_frame(GRID_2X2)

    lines = select_inner_frame_lines(cs_gdf)

    assert len(lines) == 4 * len(GRID_2X2)
    assert (lines.length == SHEET_SIZE).all()


def test_select_inner_frame_lines_raises_when_no_frame() -> None:
    """内枠の線が無い（RG など別レイヤを渡した）場合は例外にする。"""
    cs_gdf = gpd.GeoDataFrame(
        {"Level": [OUTER_FRAME_LEVEL]},
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:5897",
    )

    with pytest.raises(ValueError, match="図郭内枠の線が見つかりません"):
        select_inner_frame_lines(cs_gdf)


def test_polygonize_sheets_returns_one_face_per_sheet() -> None:
    """隙間で区切られた内枠から、図葉ごとに1面ずつ得る。"""
    lines = select_inner_frame_lines(_make_cs_frame(GRID_2X2))

    sheets = polygonize_sheets(lines)

    assert len(sheets) == len(GRID_2X2)
    for sheet in sheets:
        assert sheet.area == pytest.approx(SHEET_SIZE**2)


def test_polygonize_sheets_drops_slivers_between_overlapping_frames() -> None:
    """内枠どうしがわずかに重なる場合も、重なり部分の細い面を除いて図葉面だけを返す。"""
    # 隙間を負にすると隣接図葉の内枠が交わり、交点で分割された細い面ができる。
    lines = select_inner_frame_lines(_make_cs_frame([(0, 0), (1, 0)], gap=-0.2))

    sheets = polygonize_sheets(lines)

    # 重なり（幅 0.2 m）は細い面として除かれるため、各図葉面はその分だけ狭くなる。
    # 除いた帯は隙間と同じ扱いになり、クロージングで埋まる。
    assert len(sheets) == 2
    for sheet in sheets:
        assert sheet.area == pytest.approx(SHEET_SIZE * (SHEET_SIZE - 0.2))
    assert isinstance(close_gaps(MultiPolygon(sheets)), Polygon)


def test_close_gaps_merges_sheets_and_keeps_corners() -> None:
    """クロージングで隙間が埋まり、外周の角は直角のまま残る。"""
    sheets = polygonize_sheets(select_inner_frame_lines(_make_cs_frame(GRID_2X2)))
    union = MultiPolygon(sheets)

    closed = close_gaps(union, radius=1.0)

    assert isinstance(closed, Polygon)
    assert not closed.interiors
    total = 2 * SHEET_SIZE + SHEET_GAP
    # mitre 結合なので外周は 4 頂点の正方形のまま（丸めると角が削れて面積が減る）。
    # 閉じた外周の座標列は始点を終点に重ねて持つため、4 頂点なら 5 点になる。
    assert len(closed.exterior.coords) == 5
    assert closed.area == pytest.approx(total**2, rel=1e-9)


def test_validate_extent_accepts_single_polygon() -> None:
    """想定どおりの単一ポリゴンはそのまま返す。"""
    extent = box(0, 0, 100, 100)

    result = validate_extent(extent, sheet_count=4, union_area=10000.0, expected_sheet_count=4)

    assert result.equals(extent)


@pytest.mark.parametrize(
    ("extent", "sheet_count", "union_area", "message"),
    [
        (box(0, 0, 100, 100), 3, 10000.0, "図葉数が想定と異なります"),
        (MultiPolygon([box(0, 0, 10, 10), box(20, 0, 30, 10)]), 4, 200.0, "部分に分かれています"),
        (box(0, 0, 100, 100).difference(box(40, 40, 60, 60)), 4, 9600.0, "穴が 1 個あります"),
        (box(0, 0, 100, 100), 4, 9000.0, "面積変化が大きすぎます"),
    ],
)
def test_validate_extent_rejects_unexpected_shapes(
    extent: Polygon | MultiPolygon,
    sheet_count: int,
    union_area: float,
    message: str,
) -> None:
    """図葉数の不一致・複数部分・穴・大きな面積変化は例外にする。"""
    with pytest.raises(ValueError, match=message):
        validate_extent(extent, sheet_count, union_area, expected_sheet_count=4)


def test_build_survey_extent_returns_single_row_with_attributes() -> None:
    """合成 CS から1行の有効域を組み立て、図葉数・面積・CRS を持たせる。"""
    cs_gdf = _make_cs_frame(GRID_2X2)

    extent_gdf = build_survey_extent(cs_gdf, expected_sheet_count=len(GRID_2X2))

    assert len(extent_gdf) == 1
    assert extent_gdf["sheet_count"].iloc[0] == len(GRID_2X2)
    total = 2 * SHEET_SIZE + SHEET_GAP
    assert extent_gdf["area_km2"].iloc[0] == pytest.approx(total**2 / 1.0e6)
    assert extent_gdf.crs.to_epsg() == 5897


def test_build_survey_extent_raises_when_sheet_missing() -> None:
    """図葉が欠けている場合は、既定の想定図葉数との不一致で例外にする。"""
    cs_gdf = _make_cs_frame(GRID_2X2)

    with pytest.raises(ValueError, match=f"想定: {EXPECTED_SHEET_COUNT}"):
        build_survey_extent(cs_gdf)


def test_write_extent_writes_layer_and_removes_temp(tmp_path: Path) -> None:
    """GeoPackage に指定レイヤで書き出し、一時ファイルを残さない。"""
    extent_gdf = build_survey_extent(_make_cs_frame(GRID_2X2), expected_sheet_count=4)
    output_path = tmp_path / "extent.gpkg"

    write_extent(extent_gdf, output_path, "survey_extent")

    assert pyogrio.list_layers(output_path)[:, 0].tolist() == ["survey_extent"]
    written = gpd.read_file(output_path, layer="survey_extent")
    assert written.crs.to_epsg() == 5897
    assert written.geometry.iloc[0].area == pytest.approx(extent_gdf.geometry.iloc[0].area)
    assert not (tmp_path / "extent.tmp.gpkg").exists()
