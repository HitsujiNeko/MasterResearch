"""tables.py（正準グリッド整合のグリッド構築・cell_id 付きテーブル化）のテスト。"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
import shapely
from pyproj import CRS

from src.analysis.urban_params import tables
from src.analysis.urban_params.canonical_grid import (
    CELL_ID_STRIDE,
    build_canonical_grid,
    make_cell_id,
    split_cell_id,
)
from src.analysis.urban_params.grid import GridSpec, build_grid
from src.common.geo_metadata import BBox

ANALYSIS_CRS = CRS.from_epsg(3857)

# 原点(0, 0)・20m解像度で col 2-7 / row 1-6（6x6セル）となる解析範囲。
# 下限・上限のいずれもセル境界と一致しないため、整合BBoxが元のBBoxと異なる。
SAMPLE_BBOX = BBox(50.0, 30.0, 150.0, 130.0)
SAMPLE_RES_M = 20.0
SAMPLE_FINE_RES_M = 10.0


@pytest.fixture()
def canonical_spec():
    """6x6セルの小さな正準グリッド仕様。"""
    return build_canonical_grid(SAMPLE_BBOX, ANALYSIS_CRS, SAMPLE_RES_M)


def test_aligned_bbox_snaps_to_cell_boundaries(canonical_spec) -> None:
    """整合BBoxはセル境界に載り、元の解析BBoxを包含する。"""
    bbox = tables.aligned_bbox(canonical_spec)

    # col 2-7 / row 1-6 の外周（原点0・20m解像度）。
    assert (bbox.minx, bbox.miny, bbox.maxx, bbox.maxy) == (40.0, 20.0, 160.0, 140.0)
    assert bbox.minx <= SAMPLE_BBOX.minx and bbox.miny <= SAMPLE_BBOX.miny
    assert bbox.maxx >= SAMPLE_BBOX.maxx and bbox.maxy >= SAMPLE_BBOX.maxy
    # 幅・高さが解像度の整数倍であること（パディング0の前提）。
    assert (bbox.maxx - bbox.minx) == canonical_spec.n_cols * SAMPLE_RES_M
    assert (bbox.maxy - bbox.miny) == canonical_spec.n_rows * SAMPLE_RES_M


def test_build_aligned_grid_matches_canonical_shape(canonical_spec) -> None:
    """coarse_shape が正準グリッドの (n_rows, n_cols) と一致し、fine側もパディング0になる。"""
    grid_spec = tables.build_aligned_grid(canonical_spec, SAMPLE_FINE_RES_M)

    assert grid_spec.coarse_shape == (canonical_spec.n_rows, canonical_spec.n_cols)
    assert grid_spec.factor == 2
    assert grid_spec.fine_shape == (
        canonical_spec.n_rows * grid_spec.factor,
        canonical_spec.n_cols * grid_spec.factor,
    )


def test_build_aligned_grid_cell_centers_match_canonical(canonical_spec) -> None:
    """coarse配列の各セル中心が、対応する正準セルの中心と一致する。"""
    grid_spec = tables.build_aligned_grid(canonical_spec, SAMPLE_FINE_RES_M)
    half_res = canonical_spec.res_m / 2.0

    for row_index in range(canonical_spec.n_rows):
        for col_index in range(canonical_spec.n_cols):
            grid_x, grid_y = grid_spec.coarse_transform * (col_index + 0.5, row_index + 0.5)
            canonical_row = canonical_spec.row_max - row_index
            canonical_col = canonical_spec.col_min + col_index
            expected_x = canonical_spec.origin_x + (canonical_col * canonical_spec.res_m) + half_res
            expected_y = canonical_spec.origin_y + (canonical_row * canonical_spec.res_m) + half_res

            assert grid_x == pytest.approx(expected_x)
            assert grid_y == pytest.approx(expected_y)


def test_build_aligned_grid_rejects_shape_mismatch(canonical_spec, monkeypatch) -> None:
    """構築結果の形状が正準グリッドと食い違う場合はValueErrorになる。"""

    def fake_build_grid(
        bbox_analysis: BBox, analysis_crs: CRS, coarse_res_m: float, fine_res_m: float
    ) -> GridSpec:
        """形状だけを1行ずらしたGridSpecを返す。"""
        original = build_grid(bbox_analysis, analysis_crs, coarse_res_m, fine_res_m)
        rows, cols = original.coarse_shape
        return GridSpec(
            analysis_crs=original.analysis_crs,
            to_wgs84=original.to_wgs84,
            coarse_res_m=original.coarse_res_m,
            fine_res_m=original.fine_res_m,
            factor=original.factor,
            coarse_shape=(rows + 1, cols),
            fine_shape=original.fine_shape,
            coarse_transform=original.coarse_transform,
            fine_transform=original.fine_transform,
        )

    monkeypatch.setattr(tables, "build_grid", fake_build_grid)

    with pytest.raises(ValueError, match="正準グリッドと一致しません"):
        tables.build_aligned_grid(canonical_spec, SAMPLE_FINE_RES_M)


def test_build_aligned_grid_rejects_incompatible_fine_res(canonical_spec) -> None:
    """coarse解像度の約数でない補助解像度はValueErrorになる。"""
    with pytest.raises(ValueError):
        tables.build_aligned_grid(canonical_spec, 30.0)


def test_cell_id_array_first_row_is_northmost(canonical_spec) -> None:
    """配列の先頭行が row_max（最も北）、末尾行が row_min に対応する。"""
    cell_ids = tables.cell_id_array(canonical_spec)

    assert cell_ids.shape == (canonical_spec.n_rows, canonical_spec.n_cols)
    assert cell_ids[0, 0] == make_cell_id(canonical_spec.row_max, canonical_spec.col_min)
    assert cell_ids[-1, -1] == make_cell_id(canonical_spec.row_min, canonical_spec.col_max)
    # 行添字が増えると row は減り、列添字が増えると col は増える。
    assert cell_ids[1, 0] - cell_ids[0, 0] == -CELL_ID_STRIDE
    assert cell_ids[0, 1] - cell_ids[0, 0] == 1


def test_cell_id_array_roundtrip_returns_original_indices(canonical_spec) -> None:
    """添字 → cell_id → split_cell_id の往復で元の正準インデックスに戻る。"""
    cell_ids = tables.cell_id_array(canonical_spec)
    rows, cols = split_cell_id(cell_ids)

    row_indices, col_indices = np.meshgrid(
        np.arange(canonical_spec.n_rows), np.arange(canonical_spec.n_cols), indexing="ij"
    )
    np.testing.assert_array_equal(rows, canonical_spec.row_max - row_indices)
    np.testing.assert_array_equal(cols, canonical_spec.col_min + col_indices)


def _write_grid_layer(gpkg_path: Path, cell_ids: np.ndarray, layer_name: str) -> None:
    """正準グリッドを模した（ジオメトリつきの）レイヤを書き出す。"""
    rows, cols = split_cell_id(cell_ids)
    min_x = cols * SAMPLE_RES_M
    min_y = rows * SAMPLE_RES_M
    frame = gpd.GeoDataFrame(
        {"cell_id": cell_ids, "row": rows, "col": cols},
        geometry=shapely.box(min_x, min_y, min_x + SAMPLE_RES_M, min_y + SAMPLE_RES_M),
        crs=ANALYSIS_CRS,
    )
    pyogrio.write_dataframe(frame, gpkg_path, layer=layer_name, driver="GPKG")


def test_read_grid_cell_ids_preserves_stored_order(tmp_path: Path, canonical_spec) -> None:
    """レイヤの格納順のままint64配列として読み出す。"""
    gpkg_path = tmp_path / "grid.gpkg"
    stored = tables.cell_id_array(canonical_spec).ravel()[[5, 0, 20, 11]]
    _write_grid_layer(gpkg_path, stored, "grid_20m")

    cell_ids = tables.read_grid_cell_ids(gpkg_path, "grid_20m")

    assert cell_ids.dtype == np.int64
    np.testing.assert_array_equal(cell_ids, stored)


def test_read_grid_cell_ids_missing_file_raises(tmp_path: Path) -> None:
    """GeoPackageが存在しない場合はFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError, match="正準グリッドGeoPackage"):
        tables.read_grid_cell_ids(tmp_path / "missing.gpkg", "grid_20m")


def test_read_grid_cell_ids_missing_layer_lists_candidates(tmp_path: Path, canonical_spec) -> None:
    """レイヤ名が存在しない場合は候補つきのValueErrorになる。"""
    gpkg_path = tmp_path / "grid.gpkg"
    _write_grid_layer(gpkg_path, tables.cell_id_array(canonical_spec).ravel()[:3], "grid_20m")

    with pytest.raises(ValueError, match="grid_20m"):
        tables.read_grid_cell_ids(gpkg_path, "grid_30m")


def test_read_grid_cell_ids_missing_column_raises(tmp_path: Path) -> None:
    """cell_id 列を持たないレイヤは、原因の分かる日本語のValueErrorになる。"""
    gpkg_path = tmp_path / "grid.gpkg"
    pyogrio.write_dataframe(
        pd.DataFrame({"other_id": np.array([1, 2], dtype=np.int64)}),
        gpkg_path,
        layer="grid_20m",
        driver="GPKG",
    )

    with pytest.raises(ValueError, match="cell_id 列がありません"):
        tables.read_grid_cell_ids(gpkg_path, "grid_20m")


def _sequential_columns(canonical_spec) -> dict[str, np.ndarray]:
    """添字順に連番を並べた検証用の列を作る。"""
    size = canonical_spec.n_rows * canonical_spec.n_cols
    return {
        "BUILD_COV": np.arange(size, dtype=np.float32).reshape(
            canonical_spec.n_rows, canonical_spec.n_cols
        )
    }


def test_build_param_table_selects_and_orders_by_cell_ids(canonical_spec) -> None:
    """指定した cell_id の行だけを、指定の順序で返す。"""
    all_cell_ids = tables.cell_id_array(canonical_spec)
    columns = _sequential_columns(canonical_spec)
    # 添字 (0, 0) / (2, 3) / (5, 5) を、この順で取り出す。
    picked = np.array([all_cell_ids[0, 0], all_cell_ids[2, 3], all_cell_ids[5, 5]], dtype=np.int64)

    table = tables.build_param_table(columns, canonical_spec, picked)

    assert list(table.columns) == ["cell_id", "BUILD_COV"]
    np.testing.assert_array_equal(table["cell_id"].to_numpy(), picked)
    expected = [
        columns["BUILD_COV"][0, 0],
        columns["BUILD_COV"][2, 3],
        columns["BUILD_COV"][5, 5],
    ]
    np.testing.assert_array_equal(table["BUILD_COV"].to_numpy(), np.array(expected))


def test_build_param_table_keeps_nan_values(canonical_spec) -> None:
    """欠測（NaN）はそのまま保持され、0に置き換えられない。"""
    columns = _sequential_columns(canonical_spec)
    columns["BUILD_H_MEAN"] = np.full(
        (canonical_spec.n_rows, canonical_spec.n_cols), np.nan, dtype=np.float32
    )
    cell_ids = tables.cell_id_array(canonical_spec).ravel()

    table = tables.build_param_table(columns, canonical_spec, cell_ids)

    assert table["BUILD_H_MEAN"].isna().all()


def test_build_param_table_full_grid_matches_ravel_order(canonical_spec) -> None:
    """添字順の cell_id をすべて渡すと、配列の ravel 順と一致する。"""
    columns = _sequential_columns(canonical_spec)
    cell_ids = tables.cell_id_array(canonical_spec).ravel()

    table = tables.build_param_table(columns, canonical_spec, cell_ids)

    assert len(table) == canonical_spec.n_rows * canonical_spec.n_cols
    np.testing.assert_array_equal(table["BUILD_COV"].to_numpy(), columns["BUILD_COV"].ravel())


def test_build_param_table_rejects_out_of_range_cell_id(canonical_spec) -> None:
    """正準グリッドの範囲外を指す cell_id はValueErrorになる。"""
    columns = _sequential_columns(canonical_spec)
    outside = make_cell_id(canonical_spec.row_max + 1, canonical_spec.col_min)

    with pytest.raises(ValueError, match="範囲外"):
        tables.build_param_table(columns, canonical_spec, np.array([outside], dtype=np.int64))


def test_build_param_table_rejects_duplicated_cell_id(canonical_spec) -> None:
    """cell_id に重複があるとValueErrorになる。"""
    columns = _sequential_columns(canonical_spec)
    cell_id = tables.cell_id_array(canonical_spec)[0, 0]

    with pytest.raises(ValueError, match="重複"):
        tables.build_param_table(
            columns, canonical_spec, np.array([cell_id, cell_id], dtype=np.int64)
        )


def test_build_param_table_rejects_reserved_column_name(canonical_spec) -> None:
    """キー列と同名のパラメータ列はValueErrorになる（キーの黙った上書きを防ぐ）。"""
    columns = _sequential_columns(canonical_spec)
    columns[tables.CELL_ID_COLUMN] = np.zeros(
        (canonical_spec.n_rows, canonical_spec.n_cols), dtype=np.float32
    )
    cell_ids = tables.cell_id_array(canonical_spec).ravel()

    with pytest.raises(ValueError, match="予約されています"):
        tables.build_param_table(columns, canonical_spec, cell_ids)


def test_build_param_table_rejects_shape_mismatch(canonical_spec) -> None:
    """列の形状が正準グリッドと一致しない場合はValueErrorになる。"""
    columns = {"BUILD_COV": np.zeros((canonical_spec.n_rows, canonical_spec.n_cols + 1))}
    cell_ids = tables.cell_id_array(canonical_spec).ravel()

    with pytest.raises(ValueError, match="形状"):
        tables.build_param_table(columns, canonical_spec, cell_ids)


def test_build_param_table_rejects_empty_inputs(canonical_spec) -> None:
    """列が空の場合と cell_id が空の場合はいずれもValueErrorになる。"""
    cell_ids = tables.cell_id_array(canonical_spec).ravel()

    with pytest.raises(ValueError, match="出力する列がありません"):
        tables.build_param_table({}, canonical_spec, cell_ids)

    with pytest.raises(ValueError, match="cell_ids が空"):
        tables.build_param_table(
            _sequential_columns(canonical_spec), canonical_spec, np.array([], dtype=np.int64)
        )


def test_write_param_table_creates_attribute_only_layer(tmp_path: Path) -> None:
    """ジオメトリを持たないレイヤとして書き出され、NaNはNULLとして保持される。"""
    output_path = tmp_path / "params" / "build_gba.gpkg"
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_002, 1_000_003], dtype=np.int64),
            "BUILD_COV": np.array([0.25, 0.5], dtype=np.float32),
            "BUILD_H_MEAN": np.array([np.nan, 12.0], dtype=np.float32),
        }
    )

    tables.write_param_table(table, output_path, "build_gba")

    info = pyogrio.read_info(output_path, layer="build_gba")
    assert info["geometry_type"] is None
    assert list(info["fields"]) == ["cell_id", "BUILD_COV", "BUILD_H_MEAN"]

    written = pyogrio.read_dataframe(output_path, layer="build_gba", read_geometry=False)
    assert written["cell_id"].tolist() == [1_000_002, 1_000_003]
    assert written["BUILD_H_MEAN"].isna().tolist() == [True, False]
    # 一時ファイルを残さない。
    assert not (output_path.parent / "build_gba.tmp.gpkg").exists()


def test_write_param_table_rerun_does_not_append(tmp_path: Path) -> None:
    """同じ内容で2回実行しても行数が倍にならない（追記経路を持たない）。"""
    output_path = tmp_path / "build_gba.gpkg"
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_002, 1_000_003], dtype=np.int64),
            "BUILD_COV": np.array([0.25, 0.5], dtype=np.float32),
        }
    )

    tables.write_param_table(table, output_path, "build_gba")
    tables.write_param_table(table, output_path, "build_gba")

    assert int(pyogrio.read_info(output_path, layer="build_gba")["features"]) == 2


def test_write_param_table_keeps_existing_output_on_failure(tmp_path: Path, monkeypatch) -> None:
    """書き出しに失敗しても既存の出力を失わず、一時ファイルも残さない。"""
    output_path = tmp_path / "build_gba.gpkg"
    original = pd.DataFrame({"cell_id": np.array([1_000_002], dtype=np.int64)})
    tables.write_param_table(original, output_path, "build_gba")

    def failing_write(*args: object, **kwargs: object) -> None:
        """書き出し中のI/Oエラーを模す。"""
        raise OSError("書き込みに失敗しました（テスト）")

    monkeypatch.setattr(tables.pyogrio, "write_dataframe", failing_write)

    with pytest.raises(OSError):
        tables.write_param_table(
            pd.DataFrame({"cell_id": np.array([9_000_009], dtype=np.int64)}),
            output_path,
            "build_gba",
        )

    written = pyogrio.read_dataframe(output_path, layer="build_gba", read_geometry=False)
    assert written["cell_id"].tolist() == [1_000_002]
    assert not (tmp_path / "build_gba.tmp.gpkg").exists()
