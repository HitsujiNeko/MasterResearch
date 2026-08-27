"""geometry.py（ジオメトリ処理・ラスタ化・グリッド集約）のテスト。"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiPoint, Point, Polygon

from src.analysis.urban_params.geometry import (
    aggregate_mean_from_fine_mask,
    aggregate_mean_max_from_fine_values,
    aggregate_sum_from_fine_mask,
    centroid_cell_indices,
    compute_line_length,
    compute_polygon_coverage,
    count_polygon_centroids,
    geometry_is_line,
    geometry_is_point,
    geometry_is_polygon,
    project_geometry_safe,
    rasterize_binary_mask,
    rasterize_max_value_field,
)
from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import read_layer_dataframe

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS


def test_geometry_predicates() -> None:
    """Polygon/LineString/Point系の判定が正しく行われる。"""
    assert geometry_is_polygon(Polygon([(0, 0), (1, 0), (1, 1)]))
    assert not geometry_is_polygon(LineString([(0, 0), (1, 1)]))

    assert geometry_is_line(LineString([(0, 0), (1, 1)]))
    assert not geometry_is_line(Point(0, 0))

    assert geometry_is_point(Point(0, 0))
    assert geometry_is_point(MultiPoint([(0, 0), (1, 1)]))
    assert not geometry_is_point(Polygon([(0, 0), (1, 0), (1, 1)]))


def test_project_geometry_safe_valid_and_invalid() -> None:
    """正常なGeoJSONは投影され、不正なジオメトリはNoneになる。"""
    identity = Transformer.from_crs(ANALYSIS_CRS, ANALYSIS_CRS, always_xy=True)

    projected = project_geometry_safe({"type": "Point", "coordinates": (1.0, 2.0)}, identity)
    assert projected is not None
    assert projected.x == pytest.approx(1.0)
    assert projected.y == pytest.approx(2.0)

    assert project_geometry_safe({"type": "NotAGeometry"}, identity) is None


def test_rasterize_binary_mask_marks_expected_cells() -> None:
    """ポリゴンが中心点を含むセルのみが1になる。"""
    # 8x8グリッド、1セル1m。x[2,5), y[2,5) のセル中心を含む正方形。
    out_transform = from_origin(0, 8, 1, 1)
    polygon = Polygon([(2, 2), (5, 2), (5, 5), (2, 5), (2, 2)])

    mask = rasterize_binary_mask([polygon], out_shape=(8, 8), out_transform=out_transform)

    assert mask.sum() == 9
    assert mask[3:6, 2:5].sum() == 9


def test_aggregate_mean_and_sum_from_fine_mask() -> None:
    """fineマスクの2x2ブロックごとの平均・合計が正しく算出される。"""
    fine_mask = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )

    mean_array = aggregate_mean_from_fine_mask(fine_mask, factor=2)
    sum_array = aggregate_sum_from_fine_mask(fine_mask, factor=2)

    expected_mean = np.zeros((2, 2), dtype=np.float32)
    expected_sum = np.zeros((2, 2), dtype=np.float32)
    for r in range(2):
        for c in range(2):
            block = fine_mask[r * 2 : (r + 1) * 2, c * 2 : (c + 1) * 2]
            expected_mean[r, c] = block.mean()
            expected_sum[r, c] = block.sum()

    np.testing.assert_allclose(mean_array, expected_mean)
    np.testing.assert_allclose(sum_array, expected_sum)


def test_rasterize_max_value_field_keeps_maximum_regardless_of_input_order() -> None:
    """入力を降順で渡しても、内部ソートにより重なりセルには最大値が残る。"""
    out_transform = from_origin(0, 8, 1, 1)
    # 完全に重なる正方形（x[2,5), y[2,5)）を2つ用意する。
    square = Polygon([(2, 2), (5, 2), (5, 5), (2, 5), (2, 2)])

    # 値の降順（高い値を先に）で渡す。呼び出し側のソートに依存しない
    # 契約であることを確認するため、意図的に昇順とは逆にする。
    result = rasterize_max_value_field(
        geometries=np.array([square, square], dtype=object),
        values=np.array([12.0, 4.0]),
        out_shape=(8, 8),
        out_transform=out_transform,
        nodata=-1.0,
    )

    assert result[3, 3] == pytest.approx(12.0)
    # 被覆されていないセルは番兵値のまま残る。
    assert result[0, 0] == pytest.approx(-1.0)


def test_rasterize_max_value_field_skips_non_finite_values() -> None:
    """NaN・infの値を持つジオメトリは焼かれず、セルは番兵値のまま残る。"""
    out_transform = from_origin(0, 8, 1, 1)
    polygon = Polygon([(2, 2), (5, 2), (5, 5), (2, 5), (2, 2)])

    result = rasterize_max_value_field(
        geometries=np.array([polygon, polygon], dtype=object),
        values=np.array([np.nan, np.inf]),
        out_shape=(8, 8),
        out_transform=out_transform,
        nodata=-1.0,
    )

    np.testing.assert_array_equal(result, -1.0)


def test_rasterize_max_value_field_empty_geometries() -> None:
    """ジオメトリが0件でも例外にならず、全セルが番兵値のままになる。"""
    out_transform = from_origin(0, 8, 1, 1)

    result = rasterize_max_value_field(
        geometries=np.array([], dtype=object),
        values=np.array([], dtype=np.float64),
        out_shape=(8, 8),
        out_transform=out_transform,
        nodata=-1.0,
    )

    np.testing.assert_array_equal(result, -1.0)


def test_aggregate_mean_max_from_fine_values_computes_block_statistics() -> None:
    """fine値配列の2x2ブロックごとの平均・最大が、未被覆セルを除いて算出される。"""
    nodata = -1.0
    fine_values = np.array(
        [
            [4.0, 8.0, nodata, nodata],
            [nodata, nodata, nodata, nodata],
            [nodata, nodata, 6.0, nodata],
            [nodata, nodata, nodata, nodata],
        ],
        dtype=np.float32,
    )

    mean_array, max_array = aggregate_mean_max_from_fine_values(
        fine_values, factor=2, nodata=nodata
    )

    # ブロック(0,0): 有効値は4.0・8.0の2件（nodataの2件は分母に含めない）。
    assert mean_array[0, 0] == pytest.approx(6.0)
    assert max_array[0, 0] == pytest.approx(8.0)

    # ブロック(0,1)・(1,0): 全fineセルがnodata → 平均・最大ともNaN。
    assert np.isnan(mean_array[0, 1])
    assert np.isnan(max_array[0, 1])
    assert np.isnan(mean_array[1, 0])
    assert np.isnan(max_array[1, 0])

    # ブロック(1,1): 有効値1件のみ（6.0）。
    assert mean_array[1, 1] == pytest.approx(6.0)
    assert max_array[1, 1] == pytest.approx(6.0)


def test_aggregate_mean_max_from_fine_values_counts_valid_cells_before_clipping() -> None:
    """有効セル数はクリップ前に数えるため、全セルnodataのブロックはNaNになる。

    クリップ（nodataを0.0へ寄せる処理）の後に「0以上」で有効判定すると、
    nodataが0.0になって誤って有効値として数えられ、分母が全fineセル数
    （このケースでは4）になってしまう。クリップ前に数えていれば有効件数は
    0であり、NaNになる。
    """
    nodata = -1.0
    fine_values = np.full((2, 2), nodata, dtype=np.float32)

    mean_array, max_array = aggregate_mean_max_from_fine_values(
        fine_values, factor=2, nodata=nodata
    )

    assert mean_array.shape == (1, 1)
    assert np.isnan(mean_array[0, 0])
    assert np.isnan(max_array[0, 0])


def test_aggregate_mean_max_from_fine_values_preserves_negative_valid_values() -> None:
    """有効な負値はnodata置換の対象にならず、平均・最大に正しく反映される。

    nodataより大きければ有効値として扱う契約のため、nodata未満ではない負値
    （例: nodata=-10.0に対する-5.0）も有効値になりうる。集約前に0以上へ
    クリップすると、この有効な負値が0.0に化けて平均が誤る
    （CodeRabbitレビュー指摘、2026-08-27）。
    """
    nodata = -10.0
    fine_values = np.array([[-5.0, -2.0], [nodata, nodata]], dtype=np.float32)

    mean_array, max_array = aggregate_mean_max_from_fine_values(
        fine_values, factor=2, nodata=nodata
    )

    # 有効値は-5.0と-2.0の2件（nodataの2件は分母に含めない）。
    # クリップされていれば平均は(0.0+0.0)/2=0.0になってしまうが、
    # 正しくは(-5.0+-2.0)/2=-3.5。
    assert mean_array[0, 0] == pytest.approx(-3.5)
    assert max_array[0, 0] == pytest.approx(-2.0)


def test_compute_polygon_coverage_and_centroid_count(polygon_resource) -> None:
    """coarseセル(0, 0)を完全に覆うポリゴンは被覆率1・重心1件となる。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    coverage = compute_polygon_coverage(polygon_resource, ANALYSIS_BBOX, grid_spec)
    centroid_counts = count_polygon_centroids(polygon_resource, ANALYSIS_BBOX, grid_spec)

    assert coverage.shape == grid_spec.coarse_shape
    assert coverage[0, 0] == pytest.approx(1.0)
    assert coverage.sum() == pytest.approx(1.0)

    assert centroid_counts[0, 0] == pytest.approx(1.0)
    assert centroid_counts.sum() == pytest.approx(1.0)


def test_centroid_cell_indices_maps_known_points() -> None:
    """既知座標が期待どおりのcoarseセル添字へ写り、範囲外・非有限値は除外される。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    xs = np.array([10.0, 30.0, 20.0, 0.0, -1.0, 85.0, 40.0, np.nan])
    ys = np.array([70.0, 30.0, 60.0, 80.0, 40.0, 40.0, 85.0, 40.0])

    rows, cols, inside = centroid_cell_indices(xs, ys, grid_spec)

    # 通常セル・セル境界上（20, 60）・左上端（0, 80）は範囲内。
    np.testing.assert_array_equal(inside, [True, True, True, True, False, False, False, False])
    np.testing.assert_array_equal(rows[:4], [0, 2, 1, 0])
    np.testing.assert_array_equal(cols[:4], [0, 1, 1, 0])


def test_centroid_cell_indices_rejects_shape_mismatch() -> None:
    """xs と ys の形状が一致しない場合はValueErrorになる。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    # ブロードキャストで黙って通ってしまう組み合わせも拒否する。
    with pytest.raises(ValueError):
        centroid_cell_indices(np.array([10.0, 30.0]), np.array([70.0]), grid_spec)


def test_centroid_cell_indices_matches_count_polygon_centroids(centroid_polygon_resource) -> None:
    """ベクトル化した重心帰属が既存のcount_polygon_centroids()と一致する。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    expected = count_polygon_centroids(centroid_polygon_resource, ANALYSIS_BBOX, grid_spec)

    gdf = read_layer_dataframe(centroid_polygon_resource)
    centroids = gdf.geometry.centroid
    rows, cols, inside = centroid_cell_indices(
        centroids.x.to_numpy(), centroids.y.to_numpy(), grid_spec
    )
    n_rows, n_cols = grid_spec.coarse_shape
    flat_index = rows[inside] * n_cols + cols[inside]
    actual = np.bincount(flat_index, minlength=n_rows * n_cols).reshape(grid_spec.coarse_shape)

    np.testing.assert_array_equal(actual.astype(np.float32), expected)
    # 範囲内の4件のみが計上され、範囲外の1件は両者とも除外される。
    assert expected.sum() == pytest.approx(4.0)


def test_compute_line_length_horizontal(line_resource) -> None:
    """水平線 (0, 65)→(80, 65) のセル内総延長合計が実長80mと一致する。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    length = compute_line_length(line_resource, ANALYSIS_BBOX, grid_spec)

    assert length.sum() == pytest.approx(80.0, rel=1e-6)
    assert (length > 0).sum() == 4


def test_compute_line_length_boundary_no_double_count(boundary_line_resource) -> None:
    """セル境界（y=60）上の水平線が二重計上されず実長80mになる。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    length = compute_line_length(boundary_line_resource, ANALYSIS_BBOX, grid_spec)

    assert length.sum() == pytest.approx(80.0, rel=1e-6)


def test_compute_line_length_diagonal(diagonal_line_resource) -> None:
    """斜め線 (0, 0)→(80, 80) のセル内総延長合計が実長 80√2 mと一致する。"""
    grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)

    length = compute_line_length(diagonal_line_resource, ANALYSIS_BBOX, grid_spec)

    expected_total = math.sqrt(80.0**2 + 80.0**2)
    assert length.sum() == pytest.approx(expected_total, rel=1e-6)
