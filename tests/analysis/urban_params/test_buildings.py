"""params/buildings.py（建物パラメータ算出）のテスト。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from src.analysis.urban_params.geometry import compute_polygon_coverage, count_polygon_centroids
from src.analysis.urban_params.grid import build_grid, cell_area_ha
from src.analysis.urban_params.params import buildings

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

EXPECTED_COLUMNS = {"BUILD_COV", "BUILD_DEN", "BUILD_H_MEAN", "BUILD_H_MAX"}


def _build_test_grid():
    """テスト共通の解析グリッド（coarse 20m / fine 10m、4x4セル）を作る。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, coarse_res_m=20.0, fine_res_m=10.0)


def test_compute_returns_empty_dict_without_resource() -> None:
    """レイヤ未指定のシナリオでは空辞書を返す。"""
    grid_spec = _build_test_grid()

    assert buildings.compute(None, ANALYSIS_BBOX, grid_spec) == {}


def test_compute_output_schema(building_resource) -> None:
    """4列が揃い、形状がcoarse_shapeと一致し、dtypeがfloat32である。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)

    assert set(result.keys()) == EXPECTED_COLUMNS
    for values in result.values():
        assert values.shape == grid_spec.coarse_shape
        assert values.dtype == np.float32


def test_compute_coverage_matches_expected_values(building_resource) -> None:
    """被覆率が手計算の期待値と一致する。"""
    grid_spec = _build_test_grid()

    coverage = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)["BUILD_COV"]

    expected = np.zeros(grid_spec.coarse_shape, dtype=np.float32)
    expected[0, 0] = 1.0  # 1セルを完全に覆う1棟
    expected[0, 1] = 1.0
    expected[1, 0] = 1.0
    expected[1, 1] = 0.5  # 1/4セル分の建物が2棟
    np.testing.assert_allclose(coverage, expected)


def test_compute_coverage_matches_existing_polygon_coverage(building_resource) -> None:
    """ベクトル化した被覆率が既存のcompute_polygon_coverage()と一致する。"""
    grid_spec = _build_test_grid()

    coverage = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)["BUILD_COV"]
    expected = compute_polygon_coverage(building_resource, ANALYSIS_BBOX, grid_spec)

    np.testing.assert_allclose(coverage, expected)


def test_compute_density_matches_expected_values(building_resource) -> None:
    """棟数密度が期待値（棟/ha）と一致し、既存の重心カウントとも整合する。"""
    grid_spec = _build_test_grid()

    density = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)["BUILD_DEN"]

    # coarse 20m のセル面積は 0.04 ha なので、1棟あたり 25 棟/ha となる。
    area_ha = cell_area_ha(grid_spec)
    assert area_ha == pytest.approx(0.04)

    expected = np.zeros(grid_spec.coarse_shape, dtype=np.float32)
    expected[0, 0] = 1.0 / area_ha
    expected[0, 1] = 1.0 / area_ha
    expected[1, 0] = 1.0 / area_ha
    expected[1, 1] = 2.0 / area_ha
    np.testing.assert_allclose(density, expected)

    counts = count_polygon_centroids(building_resource, ANALYSIS_BBOX, grid_spec)
    np.testing.assert_allclose(density, counts / area_ha)


def test_compute_excludes_unreliable_heights(building_resource) -> None:
    """分散が負・欠測の建物は高さ集計から除外され、被覆率・棟数密度には計上される。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)
    mean_heights = result["BUILD_H_MEAN"]
    max_heights = result["BUILD_H_MAX"]

    # 分散1の有効な1棟のみのセル。
    assert mean_heights[0, 0] == pytest.approx(10.0)
    assert max_heights[0, 0] == pytest.approx(10.0)

    # 分散-1（負値）の建物しかないセルは高さが不明。
    assert np.isnan(mean_heights[0, 1])
    assert np.isnan(max_heights[0, 1])

    # 分散が欠測（NaN）の建物しかないセルも高さが不明。
    assert np.isnan(mean_heights[1, 0])
    assert np.isnan(max_heights[1, 0])

    # 高さ集計から外れたセルでも、フットプリント由来の指標は計上されている。
    assert result["BUILD_COV"][0, 1] == pytest.approx(1.0)
    assert result["BUILD_DEN"][0, 1] > 0
    assert result["BUILD_COV"][1, 0] == pytest.approx(1.0)
    assert result["BUILD_DEN"][1, 0] > 0


def test_compute_height_mean_and_max_over_multiple_buildings(building_resource) -> None:
    """同一セル内の複数棟について平均・最大高さが正しく集計される。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)

    # 高さ6m（分散0）と8m（分散2）の2棟。分散0は有効として扱う。
    assert result["BUILD_H_MEAN"][1, 1] == pytest.approx(7.0)
    assert result["BUILD_H_MAX"][1, 1] == pytest.approx(8.0)


def test_compute_height_is_nan_for_cells_without_buildings(building_resource) -> None:
    """建物が無いセルの高さは0.0ではなくNaNになる。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)

    # セル(3, 3) には建物が無い。
    assert result["BUILD_COV"][3, 3] == pytest.approx(0.0)
    assert result["BUILD_DEN"][3, 3] == pytest.approx(0.0)
    assert np.isnan(result["BUILD_H_MEAN"][3, 3])
    assert np.isnan(result["BUILD_H_MAX"][3, 3])


def test_compute_max_is_not_less_than_mean(building_resource) -> None:
    """有効な高さを持つセルでは BUILD_H_MAX >= BUILD_H_MEAN が成り立つ。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(building_resource, ANALYSIS_BBOX, grid_spec)
    valid_mask = np.isfinite(result["BUILD_H_MEAN"])

    assert valid_mask.any()
    assert np.all(result["BUILD_H_MAX"][valid_mask] >= result["BUILD_H_MEAN"][valid_mask])


def test_compute_fills_spanning_footprint_without_centroid(edge_building_resource) -> None:
    """重心がグリッド外の建物は棟数密度に入らないが、張り出した被覆部分には高さが入る。

    重心方式のみだった現行では高さは全セルNaNだったが、新方式（重なり方式との
    併用）では、フットプリントが張り出したセル側にも高さが計上される。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(edge_building_resource, ANALYSIS_BBOX, grid_spec)

    # x 60-80 / y 30-50 の部分がグリッド内にあり、2セルを半分ずつ覆う。
    assert result["BUILD_COV"].sum() == pytest.approx(1.0)
    assert result["BUILD_COV"][1, 3] == pytest.approx(0.5)
    assert result["BUILD_COV"][2, 3] == pytest.approx(0.5)
    # 重心 (80, 40) は列添字が範囲外のため、棟数密度には寄与しない。
    assert result["BUILD_DEN"].sum() == pytest.approx(0.0)
    # 高さは重なり方式により、張り出した被覆部分（fineセル中心を覆う範囲）
    # から得られる。
    assert result["BUILD_H_MEAN"][1, 3] == pytest.approx(12.0)
    assert result["BUILD_H_MEAN"][2, 3] == pytest.approx(12.0)
    assert result["BUILD_H_MAX"][1, 3] == pytest.approx(12.0)
    assert result["BUILD_H_MAX"][2, 3] == pytest.approx(12.0)
    # それ以外のセルには建物が無いためNaNのまま。
    other_mask = np.ones(grid_spec.coarse_shape, dtype=bool)
    other_mask[1, 3] = False
    other_mask[2, 3] = False
    assert np.all(np.isnan(result["BUILD_H_MEAN"][other_mask]))
    assert np.all(np.isnan(result["BUILD_H_MAX"][other_mask]))


def test_compute_empty_layer(empty_building_resource) -> None:
    """建物が1件も無いレイヤでも例外を出さず、4列が正常な形状で返る。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(empty_building_resource, ANALYSIS_BBOX, grid_spec)

    assert set(result.keys()) == EXPECTED_COLUMNS
    for values in result.values():
        assert values.shape == grid_spec.coarse_shape
    assert np.all(result["BUILD_COV"] == 0.0)
    assert np.all(result["BUILD_DEN"] == 0.0)
    assert np.all(np.isnan(result["BUILD_H_MEAN"]))
    assert np.all(np.isnan(result["BUILD_H_MAX"]))


def test_compute_reports_non_polygon_separately(mixed_geometry_building_resource) -> None:
    """ポリゴン以外の混在は「不正」ではなく別カテゴリの警告として報告される。"""
    grid_spec = _build_test_grid()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = buildings.compute(mixed_geometry_building_resource, ANALYSIS_BBOX, grid_spec)

    messages = [str(record.message) for record in caught]
    assert any("ポリゴン以外の建物ジオメトリを除外しました: 1 件" in m for m in messages)
    # 正常な内訳なので、データ品質の問題としては報告しない。
    assert not any("不正または空" in m for m in messages)
    assert result["BUILD_COV"][0, 0] == pytest.approx(1.0)
    assert result["BUILD_DEN"].sum() == pytest.approx(1.0 / cell_area_ha(grid_spec))


def test_compute_excludes_null_geometry(null_geometry_building_resource) -> None:
    """NULLジオメトリはデータ品質の問題として警告され、正常な建物のみが集計される。"""
    grid_spec = _build_test_grid()

    # NULLは「ポリゴン以外」（測量GISでは正常な内訳）ではなく不正側に数える。
    with pytest.warns(UserWarning, match="不正または空の建物ジオメトリ"):
        result = buildings.compute(null_geometry_building_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_COV"][0, 0] == pytest.approx(1.0)
    assert result["BUILD_DEN"].sum() == pytest.approx(1.0 / cell_area_ha(grid_spec))
    assert result["BUILD_H_MEAN"][0, 0] == pytest.approx(10.0)


def test_compute_excludes_negative_height(negative_height_building_resource) -> None:
    """高さが負値の建物は高さ集計から除外され、被覆率・棟数密度には計上される。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(negative_height_building_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_H_MEAN"][0, 0] == pytest.approx(10.0)
    # 高さ -5.0 の建物があるセルは高さが不明扱いになる。
    assert np.isnan(result["BUILD_H_MEAN"][0, 1])
    assert np.isnan(result["BUILD_H_MAX"][0, 1])
    assert result["BUILD_COV"][0, 1] == pytest.approx(1.0)
    assert result["BUILD_DEN"][0, 1] > 0


def test_compute_warns_when_variance_field_missing(height_without_variance_resource) -> None:
    """推定分散を持たないレイヤでは警告のうえ、取得できた高さをすべて集計する。"""
    grid_spec = _build_test_grid()

    with pytest.warns(UserWarning, match="高さの推定分散"):
        result = buildings.compute(height_without_variance_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_H_MEAN"][0, 0] == pytest.approx(10.0)
    assert result["BUILD_H_MAX"][0, 0] == pytest.approx(10.0)


def test_compute_repairs_invalid_geometry(invalid_building_resource) -> None:
    """不正ジオメトリは警告つきで修復され、逐次経路と同じ被覆率になる。"""
    grid_spec = _build_test_grid()

    with pytest.warns(UserWarning, match="不正な建物ジオメトリを修復しました"):
        result = buildings.compute(invalid_building_resource, ANALYSIS_BBOX, grid_spec)

    # 修復により自己交差ポリゴンも面積を持ち、逐次経路と一致する。
    expected = compute_polygon_coverage(invalid_building_resource, ANALYSIS_BBOX, grid_spec)
    np.testing.assert_allclose(result["BUILD_COV"], expected)
    assert result["BUILD_COV"][0, 0] == pytest.approx(1.0)
    assert result["BUILD_COV"][1, 1] > 0
    # 修復された建物も1棟として計上される。
    assert result["BUILD_DEN"].sum() == pytest.approx(2.0 / cell_area_ha(grid_spec))


def test_compute_handles_multipolygon(multipolygon_building_resource) -> None:
    """MultiPolygon も被覆率・棟数・高さに正しく反映される。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(multipolygon_building_resource, ANALYSIS_BBOX, grid_spec)

    expected = compute_polygon_coverage(multipolygon_building_resource, ANALYSIS_BBOX, grid_spec)
    np.testing.assert_allclose(result["BUILD_COV"], expected)
    # 2つのパートがそれぞれ 1/4 セル分を覆う。
    assert result["BUILD_COV"][0, 0] == pytest.approx(0.25)
    assert result["BUILD_COV"][1, 1] == pytest.approx(0.25)
    # MultiPolygon 全体で1棟として、重心が属するセルへ帰属する。
    assert result["BUILD_DEN"].sum() == pytest.approx(1.0 / cell_area_ha(grid_spec))
    counts = count_polygon_centroids(multipolygon_building_resource, ANALYSIS_BBOX, grid_spec)
    np.testing.assert_allclose(result["BUILD_DEN"], counts / cell_area_ha(grid_spec))
    assert np.nanmax(result["BUILD_H_MEAN"]) == pytest.approx(12.0)


def test_compute_overlap_mean_uses_top_height_area_average(overlap_building_resource) -> None:
    """BUILD_H_MEANは重複箇所を二重計上しない、上端高さの面積平均になる。

    セル(3, 0): 高さ4m・400m2の建物に、高さ12m・200m2の建物が完全に重なる。
    上端高さの面積平均は (12+12+4+4)/4 = 8.0 m。二重計上した面積加重平均
    （(400*4 + 200*12) / 600 = 6.67 m）とは異なる値になる。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_H_MEAN"][3, 0] == pytest.approx(8.0)
    assert result["BUILD_H_MAX"][3, 0] == pytest.approx(12.0)


def test_compute_overlap_fills_missing_overlap_with_centroid(overlap_building_resource) -> None:
    """重なり方式の被覆が無いセルは、重心方式（従来の単純平均）で補完される。

    セル(2, 2)の建物はfineセル中心をどれも覆わないため、重なり方式では
    値が得られない。重心方式では重心がこのセルに属するため、補完によって
    高さ25.0が得られる。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_H_MEAN"][2, 2] == pytest.approx(25.0)
    assert result["BUILD_H_MAX"][2, 2] == pytest.approx(25.0)
    # 被覆自体もfineセル中心を覆わないため0のまま（小さい建物の取りこぼし）。
    assert result["BUILD_COV"][2, 2] == pytest.approx(0.0)
    assert result["BUILD_DEN"][2, 2] > 0


def test_compute_overlap_max_composes_overlap_and_centroid(overlap_building_resource) -> None:
    """BUILD_H_MAXは重なり方式と重心方式の最大をnp.fmax()で合成する。

    セル(0, 0)には、低い大建物（h=10.0, fine中心を覆う）と高い小建物
    （h=30.0, fine中心をどれも覆わない）が同居する。重なり方式のみでは
    小建物の高さ30.0を取りこぼすが、重心方式の最大との合成により救われる。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    # BUILD_H_MEANは重なり方式のみ（小建物のfine被覆が無いため10.0のまま）。
    assert result["BUILD_H_MEAN"][0, 0] == pytest.approx(10.0)
    # BUILD_H_MAXは重心方式の最大（30.0）を合成で取り込む。
    assert result["BUILD_H_MAX"][0, 0] == pytest.approx(30.0)


def test_compute_overlap_fills_spanning_cell(overlap_building_resource) -> None:
    """2セルにまたがる建物は、重心が無い側のセルにも重なり方式で高さが入る。

    セル(3, 2)/(3, 3)にまたがる建物（h=15.0）の重心はセル(3, 3)側にのみ
    属するが、セル(3, 2)側にも張り出した被覆部分から高さが得られる。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    assert result["BUILD_H_MEAN"][3, 2] == pytest.approx(15.0)
    assert result["BUILD_H_MAX"][3, 2] == pytest.approx(15.0)
    assert result["BUILD_H_MEAN"][3, 3] == pytest.approx(15.0)
    assert result["BUILD_H_MAX"][3, 3] == pytest.approx(15.0)


def test_compute_overlap_max_not_less_than_mean(overlap_building_resource) -> None:
    """4シナリオを含むレイヤでも BUILD_H_MAX >= BUILD_H_MEAN が成り立つ。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)
    valid_mask = np.isfinite(result["BUILD_H_MEAN"])

    assert valid_mask.any()
    assert np.all(result["BUILD_H_MAX"][valid_mask] >= result["BUILD_H_MEAN"][valid_mask])


def test_compute_overlap_nan_sets_match_between_mean_and_max(overlap_building_resource) -> None:
    """BUILD_H_MEANとBUILD_H_MAXのNaN集合が完全に一致する。

    `fill_missing_building_heights`（analysis_rq3_limited.py）は両列が同時に
    NULL/非NULLになることを前提にしており、この前提が崩れていないことを
    確認する。
    """
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    np.testing.assert_array_equal(np.isnan(result["BUILD_H_MEAN"]), np.isnan(result["BUILD_H_MAX"]))
    # このフィクスチャでは5セル（(0,0)・(3,0)・(2,2)・(3,2)・(3,3)）のみ非NaN。
    assert int((~np.isnan(result["BUILD_H_MEAN"])).sum()) == 5


def test_compute_overlap_density_matches_centroid_count(overlap_building_resource) -> None:
    """BUILD_DENは新方式でも重心方式のまま変わらない。"""
    grid_spec = _build_test_grid()

    result = buildings.compute(overlap_building_resource, ANALYSIS_BBOX, grid_spec)
    counts = count_polygon_centroids(overlap_building_resource, ANALYSIS_BBOX, grid_spec)

    np.testing.assert_allclose(result["BUILD_DEN"], counts / cell_area_ha(grid_spec))
    # セル(0,0)・(3,0)は2棟、セル(2,2)・(3,3)は1棟、セル(3,2)は0棟。
    assert result["BUILD_DEN"][0, 0] == pytest.approx(2.0 / cell_area_ha(grid_spec))
    assert result["BUILD_DEN"][3, 0] == pytest.approx(2.0 / cell_area_ha(grid_spec))
    assert result["BUILD_DEN"][2, 2] == pytest.approx(1.0 / cell_area_ha(grid_spec))
    assert result["BUILD_DEN"][3, 3] == pytest.approx(1.0 / cell_area_ha(grid_spec))
    assert result["BUILD_DEN"][3, 2] == pytest.approx(0.0)


def test_compute_without_height_fields(polygon_resource) -> None:
    """高さ属性を持たないレイヤでも被覆率・棟数密度は算出され、高さはNaNになる。"""
    grid_spec = _build_test_grid()

    with pytest.warns(UserWarning, match="高さ属性"):
        result = buildings.compute(polygon_resource, ANALYSIS_BBOX, grid_spec)

    assert set(result.keys()) == EXPECTED_COLUMNS
    assert result["BUILD_COV"][0, 0] == pytest.approx(1.0)
    assert result["BUILD_DEN"][0, 0] > 0
    assert np.all(np.isnan(result["BUILD_H_MEAN"]))
    assert np.all(np.isnan(result["BUILD_H_MAX"]))
