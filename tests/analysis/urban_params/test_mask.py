"""params/mask.py（解析対象域フラグの算出）のテスト。"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np
import pytest

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.params import mask

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS, _make_layer_resource

# conftest の polygon_resource と同じ 4x4（coarse=20m）のグリッド。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0


def _build_grid_spec():
    """テスト用のfine/coarseグリッド仕様を作る。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def test_compute_flags_covered_cell(polygon_resource) -> None:
    """ポリゴンが覆うセルのみ IN_ANALYSIS_AREA=1 になる。"""
    grid_spec = _build_grid_spec()

    result = mask.compute(polygon_resource, ANALYSIS_BBOX, grid_spec)

    assert set(result) == {"IN_ANALYSIS_AREA"}
    flags = result["IN_ANALYSIS_AREA"]
    assert flags.dtype == np.int8
    assert flags.shape == grid_spec.coarse_shape
    # polygon_resource は coarseセル(0, 0) をちょうど1セル分覆う。
    assert flags[0, 0] == 1
    assert int(flags.sum()) == 1


def test_compute_flags_partially_covered_cell(tmp_path: Path) -> None:
    """セルの一部しか覆わない場合も1とする（被覆率ではなく有無で判定する）。"""
    gpkg_path = tmp_path / "partial.gpkg"
    # coarseセル(0, 0)（x 0-20 / y 60-80）の左下 1/4 だけを覆う。
    ring = [(0.0, 60.0), (10.0, 60.0), (10.0, 70.0), (0.0, 70.0), (0.0, 60.0)]
    with fiona.open(
        gpkg_path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {}},
    ) as dst:
        dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})

    result = mask.compute(
        _make_layer_resource(gpkg_path, "data"), ANALYSIS_BBOX, _build_grid_spec()
    )

    flags = result["IN_ANALYSIS_AREA"]
    assert flags[0, 0] == 1
    assert int(flags.sum()) == 1


def test_compute_excludes_cell_grazed_without_fine_pixel_center(tmp_path: Path) -> None:
    """セルと交差しても、fineピクセル中心を1つも含まなければ0になる。

    正準グリッドは「セルとマスクポリゴンの交差」でセルを選ぶのに対し、本モジュールは
    「fineピクセル中心がポリゴン内に入るか」で判定する。この差が「交差 ⊇
    IN_ANALYSIS_AREA」の包含関係を生み、**パラメータテーブルの行集合は解析対象域
    より広い**という結論の根拠になっている。境界ケースを固定して、判定基準が
    入れ替わったことに気づけるようにする。
    """
    gpkg_path = tmp_path / "grazed.gpkg"
    # coarseセル(0, 0)（x 0-20 / y 60-80）の左上の角だけをかすめる。
    # 同セルのfineピクセル中心は (5, 65) (15, 65) (5, 75) (15, 75) の4点で、
    # x <= 4 の帯にはどれも入らない。
    ring = [(0.0, 76.0), (4.0, 76.0), (4.0, 80.0), (0.0, 80.0), (0.0, 76.0)]
    with fiona.open(
        gpkg_path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {}},
    ) as dst:
        dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})

    result = mask.compute(
        _make_layer_resource(gpkg_path, "data"), ANALYSIS_BBOX, _build_grid_spec()
    )

    flags = result["IN_ANALYSIS_AREA"]
    assert flags[0, 0] == 0
    assert int(flags.sum()) == 0


def test_compute_returns_zeros_when_polygon_outside_grid(tmp_path: Path) -> None:
    """グリッド範囲外のポリゴンだけの場合は全セル0になる。"""
    gpkg_path = tmp_path / "outside.gpkg"
    ring = [(200.0, 200.0), (220.0, 200.0), (220.0, 220.0), (200.0, 220.0), (200.0, 200.0)]
    with fiona.open(
        gpkg_path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {}},
    ) as dst:
        dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})

    result = mask.compute(
        _make_layer_resource(gpkg_path, "data"), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert int(result["IN_ANALYSIS_AREA"].sum()) == 0


def test_compute_without_resource_returns_empty() -> None:
    """入力が未指定の場合は空辞書を返す（標準シグネチャの規約）。"""
    assert mask.compute(None, ANALYSIS_BBOX, _build_grid_spec()) == {}


def test_compute_ignores_line_geometry(line_resource) -> None:
    """線ジオメトリは面積を持たないため解析対象域に計上されない。

    面ジオメトリを持つレイヤに限る、というモジュールの前提を固定する。
    """
    result = mask.compute(line_resource, ANALYSIS_BBOX, _build_grid_spec())

    assert int(result["IN_ANALYSIS_AREA"].sum()) == 0


def _write_layer(path: Path, geometries: list[dict | None]) -> None:
    """ジオメトリ型の混在を許すレイヤ（定義の型は Unknown）を書き出す（属性なし）。"""
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Unknown", "properties": {}},
    ) as dst:
        for geometry in geometries:
            dst.write({"geometry": geometry, "properties": {}})


SQUARE = {
    "type": "Polygon",
    "coordinates": [[(0.0, 60.0), (20.0, 60.0), (20.0, 80.0), (0.0, 80.0), (0.0, 60.0)]],
}


def test_validate_resource_accepts_polygon_layer(polygon_resource) -> None:
    """面ジオメトリのみのレイヤは受け付ける。"""
    mask.validate_resource(polygon_resource)


def test_validate_resource_ignores_null_geometry_in_mixed_layer(tmp_path: Path) -> None:
    """型の混在を許すレイヤでも、面と NULL だけなら受け付ける。"""
    gpkg_path = tmp_path / "with_null.gpkg"
    _write_layer(gpkg_path, [SQUARE, None])

    mask.validate_resource(_make_layer_resource(gpkg_path, "data"))


def test_validate_resource_accepts_multipolygon(tmp_path: Path) -> None:
    """MultiPolygon も面ジオメトリとして受け付ける（測量GIS有効域の生成結果が該当しうる）。"""
    gpkg_path = tmp_path / "multi.gpkg"
    _write_layer(
        gpkg_path,
        [{"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}, SQUARE],
    )

    mask.validate_resource(_make_layer_resource(gpkg_path, "data"))


def test_validate_resource_rejects_line_layer(line_resource) -> None:
    """線レイヤ（測量GISの RG のような境界線主体のレイヤ）は拒否する。

    算出自体は例外なく終わり全セル 0 のテーブルが出力されるため、入力解決の段階で
    止めないと誤りに気づけない（``test_compute_ignores_line_geometry`` を参照）。
    """
    with pytest.raises(ValueError, match="ジオメトリ型 LineString"):
        mask.validate_resource(line_resource)


def test_validate_resource_rejects_mixed_layer(tmp_path: Path) -> None:
    """面と線が混在するレイヤも、面以外を含む時点で拒否する。

    レイヤ定義の型が ``Unknown`` のため、地物を読んで判定する経路を通る。
    """
    gpkg_path = tmp_path / "mixed.gpkg"
    _write_layer(
        gpkg_path,
        [SQUARE, {"type": "LineString", "coordinates": [(0.0, 65.0), (80.0, 65.0)]}],
    )

    with pytest.raises(ValueError, match="LineString 1件"):
        mask.validate_resource(_make_layer_resource(gpkg_path, "data"))


def test_validate_resource_rejects_empty_layer(tmp_path: Path) -> None:
    """地物が1件も無いレイヤは、全セル 0 になるだけなので拒否する。"""
    gpkg_path = tmp_path / "empty.gpkg"
    _write_layer(gpkg_path, [])

    with pytest.raises(ValueError, match="地物がありません"):
        mask.validate_resource(_make_layer_resource(gpkg_path, "data"))
