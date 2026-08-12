"""params/mask.py（解析対象域フラグの算出）のテスト。"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np

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
