"""params/lst.py（LSTパラメータの算出）のテスト。"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import RasterResource
from src.analysis.urban_params.params import lst

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

# ANALYSIS_BBOX（0-80m四方）を coarse=20m で分割した 4x4 グリッドを前提とする。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0


def _build_grid_spec():
    """テスト共通の 4x4 coarseグリッド仕様を構築する。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def _write_lst(path: Path, data: np.ndarray, nodata: float | None = None) -> None:
    """解析範囲（0-80m四方）を覆う10m解像度のLSTラスタを書き出す。

    Args:
        path: 出力先のGeoTIFFパス。
        data: LST値（°C相当）の配列（8x8）。
        nodata: nodata値。``None`` の場合はタグを設定しない。
    """
    transform = from_origin(0, 80, FINE_RES_M, FINE_RES_M)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data.astype(np.float32), 1)


def _gradient_lst() -> np.ndarray:
    """行・列から一意に決まる 8x8 のLST配列を作る（セル平均が手計算できる、°C相当）。"""
    rows, cols = np.indices((8, 8))
    return (20.0 + rows * 8 + cols).astype(np.float32)


def test_compute_returns_cell_mean_lst(tmp_path: Path) -> None:
    """LST列にcoarseセル内の平均地表面温度（°C）が入る。"""
    lst_path = tmp_path / "lst.tif"
    _write_lst(lst_path, _gradient_lst())

    result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert set(result) == {"LST", "LST_VALID_RATIO"}
    lst_mean = result["LST"]
    assert lst_mean.shape == (4, 4)
    assert lst_mean.dtype == np.float32
    # セル(0, 0) は左上2x2画素（20, 21, 28, 29）の平均。
    assert lst_mean[0, 0] == pytest.approx(24.5, abs=0.5)
    # セル(3, 3) は右下2x2画素（74, 75, 82, 83）の平均。
    assert lst_mean[3, 3] == pytest.approx(78.5, abs=0.5)


def test_compute_excludes_nodata_from_mean(tmp_path: Path) -> None:
    """雲マスク等のnodataが平均へ混入せず、有効画素のみで平均される。"""
    data = np.full((8, 8), 30.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のうち1画素だけをnodataにする。
    data[0, 0] = -9999.0
    lst_path = tmp_path / "lst_nodata.tif"
    _write_lst(lst_path, data, nodata=-9999.0)

    lst_mean = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())["LST"]

    # -9999 が混ざれば平均は大きく負に振れる。有効画素のみなら30.0のまま。
    assert lst_mean[0, 0] == pytest.approx(30.0, abs=0.5)
    assert not np.isnan(lst_mean[0, 0])


def test_compute_keeps_all_nodata_cell_as_nan(tmp_path: Path) -> None:
    """全画素が雲被覆（nodata）のセルはNaNのまま残る（0で埋めない）。"""
    data = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のみ有効値にする。
    data[0:2, 0:2] = 25.0
    lst_path = tmp_path / "lst_all_nodata.tif"
    _write_lst(lst_path, data, nodata=-9999.0)

    lst_mean = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())["LST"]

    assert lst_mean[0, 0] == pytest.approx(25.0, abs=0.5)
    assert np.isnan(lst_mean[0, 1])
    assert np.isnan(lst_mean[3, 3])


def test_valid_ratio_is_one_for_fully_covered_cells(tmp_path: Path) -> None:
    """全画素が有効なセルの有効画素率は1.0になる。"""
    lst_path = tmp_path / "lst_full.tif"
    _write_lst(lst_path, _gradient_lst(), nodata=-9999.0)

    valid_ratio = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())["LST_VALID_RATIO"]

    assert valid_ratio.shape == (4, 4)
    assert valid_ratio.dtype == np.float32
    np.testing.assert_allclose(valid_ratio, np.ones((4, 4), dtype=np.float32), atol=1e-5)


def test_valid_ratio_distinguishes_partially_covered_cells(tmp_path: Path) -> None:
    """雲による部分被覆セルはLSTでは完全被覆セルと区別できず、有効画素率でのみ区別できる。

    実データでは雲マスクにより有効画素率が25.4〜45.7%と低いため、この列を
    併設しないと部分被覆セルの信頼度を判断できない。
    """
    data = np.full((8, 8), 30.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のうち1画素だけを雲被覆（nodata）にする。
    data[0, 0] = -9999.0
    lst_path = tmp_path / "lst_partial.tif"
    _write_lst(lst_path, data, nodata=-9999.0)

    result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    # LST は部分被覆セルと完全被覆セルで同じ値になる（区別できない）。
    assert result["LST"][0, 0] == pytest.approx(result["LST"][0, 1], abs=1e-5)
    # LST_VALID_RATIO は両者を区別する。
    assert result["LST_VALID_RATIO"][0, 0] == pytest.approx(0.75, abs=0.05)
    assert result["LST_VALID_RATIO"][0, 1] == pytest.approx(1.0, abs=1e-5)


def test_valid_ratio_is_zero_for_all_nodata_cells(tmp_path: Path) -> None:
    """全画素が雲被覆（nodata）のセルは有効画素率0.0であり、LSTはNaNになる。"""
    data = np.full((8, 8), -9999.0, dtype=np.float32)
    data[0:2, 0:2] = 25.0
    lst_path = tmp_path / "lst_ratio_nodata.tif"
    _write_lst(lst_path, data, nodata=-9999.0)

    result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert result["LST_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert result["LST_VALID_RATIO"][3, 3] == pytest.approx(0.0, abs=1e-5)
    assert np.isnan(result["LST"][3, 3])


def test_valid_ratio_is_zero_outside_raster_extent(tmp_path: Path) -> None:
    """ラスタの範囲外セルは、NaNではなく有効画素率0.0になる。

    範囲外を ``NaN`` にすると「雲被覆で覆われたセル」と区別が付かなくなるため、
    どちらも「有効画素なし」を意味する0.0へ揃える。
    """
    # 解析範囲（0-80m四方）の左半分（x: 0-40m）だけを覆うLSTラスタを書き出す。
    lst_path = tmp_path / "lst_half.tif"
    with rasterio.open(
        lst_path,
        "w",
        driver="GTiff",
        height=8,
        width=4,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, FINE_RES_M, FINE_RES_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((8, 4), 32.0, dtype=np.float32), 1)

    result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert result["LST_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert result["LST_VALID_RATIO"][0, 3] == pytest.approx(0.0, abs=1e-5)
    assert not np.isnan(result["LST_VALID_RATIO"]).any()
    assert np.isnan(result["LST"][0, 3])


def test_compute_reprojects_from_geographic_crs(tmp_path: Path) -> None:
    """LSTラスタが解析CRSと異なる地理座標系でも、再投影されて値が保持される。

    実運用のLSTラスタはEPSG:4326、解析CRSはEPSG:5897（投影座標系）であり、
    必ず再投影を伴う。同一CRSのテストだけではこの経路を通らないため、
    地理座標系のラスタを明示的に検証する。
    """
    # ANALYSIS_BBOX（EPSG:3857 の 0-80m四方）は経緯度の原点近傍にあたる。
    # 0.0005度刻みの10x10画素で、その範囲を余裕を持って覆う。
    lst_path = tmp_path / "lst_wgs84.tif"
    with rasterio.open(
        lst_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-0.001, 0.002, 0.0005, 0.0005),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((10, 10), 35.0, dtype=np.float32), 1)

    result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    lst_mean = result["LST"]
    assert not np.isnan(lst_mean).any()
    np.testing.assert_allclose(lst_mean, np.full((4, 4), 35.0, dtype=np.float32), rtol=1e-5)
    # 有効画素率も同じ再投影経路を通るため、あわせて検証する（実運用は必ずこの経路）。
    np.testing.assert_allclose(
        result["LST_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_warns_when_median_looks_like_kelvin(tmp_path: Path) -> None:
    """集約後の中央値が摂氏として妥当な範囲の外（約300）なら警告する。

    ケルビン単位のLSTラスタを誤って渡した場合を検知するための警告である。
    """
    lst_path = tmp_path / "lst_kelvin.tif"
    _write_lst(lst_path, np.full((8, 8), 305.0, dtype=np.float32))

    with pytest.warns(UserWarning, match="妥当な範囲"):
        result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    np.testing.assert_allclose(result["LST"], 305.0, rtol=1e-5)


@pytest.mark.parametrize(
    ("boundary_value", "label"),
    [(lst.PLAUSIBLE_LST_MIN_C, "min"), (lst.PLAUSIBLE_LST_MAX_C, "max")],
)
def test_compute_does_not_warn_at_plausible_range_boundary(
    tmp_path: Path, boundary_value: float, label: str
) -> None:
    """妥当範囲の境界値（-60°C・90°C）ちょうどでは警告しない（境界は範囲に含む）。"""
    lst_path = tmp_path / f"lst_boundary_{label}.tif"
    _write_lst(lst_path, np.full((8, 8), boundary_value, dtype=np.float32))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert not [record for record in caught if "妥当な範囲" in str(record.message)]


@pytest.mark.parametrize(
    ("outside_value", "label"),
    [(lst.PLAUSIBLE_LST_MIN_C - 0.1, "below_min"), (lst.PLAUSIBLE_LST_MAX_C + 0.1, "above_max")],
)
def test_compute_warns_just_outside_plausible_range(
    tmp_path: Path, outside_value: float, label: str
) -> None:
    """妥当範囲をわずかに外れた値では警告する（境界の1歩外側、閾値の実装ミスを検知する）。"""
    lst_path = tmp_path / f"lst_outside_{label}.tif"
    _write_lst(lst_path, np.full((8, 8), outside_value, dtype=np.float32))

    with pytest.warns(UserWarning, match="妥当な範囲"):
        lst.compute(RasterResource(lst_path, 1), _build_grid_spec())


def test_compute_does_not_warn_for_plausible_celsius_values(tmp_path: Path) -> None:
    """実データの値域に近い摂氏の値では警告しない。"""
    lst_path = tmp_path / "lst_celsius.tif"
    _write_lst(lst_path, np.full((8, 8), 40.0, dtype=np.float32))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert not [record for record in caught if "妥当な範囲" in str(record.message)]


def test_compute_does_not_warn_kelvin_check_when_all_values_are_missing(tmp_path: Path) -> None:
    """有効値が1件も無い場合、ケルビン検知（妥当な範囲チェック）は行わない。

    正常なLSTを弾かない設計上、判定材料が無いセル集合を「範囲外」と誤検知して
    はならない。全欠測自体は別の警告（重なりません）で検知する。
    """
    lst_path = tmp_path / "lst_all_missing.tif"
    _write_lst(lst_path, np.full((8, 8), -9999.0, dtype=np.float32), nodata=-9999.0)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert not [record for record in caught if "妥当な範囲" in str(record.message)]
    assert np.isnan(result["LST"]).all()


def test_compute_warns_when_lst_does_not_overlap_grid(tmp_path: Path) -> None:
    """LSTラスタが解析グリッドと全く重ならない場合は警告する。

    都市とLSTラスタの取り違え・切り出し範囲の誤りではファイルが存在するため
    入力解決を素通りし、全セルNaNの列が黙って出力される。列が残るぶん欠損に
    気づきにくい（elevation.pyと同じ規約）。
    """
    # 解析範囲（0-80m四方）から大きく離れた位置のLSTラスタを書き出す。
    lst_path = tmp_path / "lst_far.tif"
    with rasterio.open(
        lst_path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(100000, 100000, FINE_RES_M, FINE_RES_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((8, 8), 35.0, dtype=np.float32), 1)

    with pytest.warns(UserWarning, match="重なりません"):
        result = lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert np.isnan(result["LST"]).all()
    np.testing.assert_allclose(result["LST_VALID_RATIO"], 0.0, atol=1e-5)


def test_compute_does_not_warn_overlap_when_lst_overlaps_grid(tmp_path: Path) -> None:
    """LSTラスタがグリッドと重なる通常の入力では、重なりの警告をしない。"""
    lst_path = tmp_path / "lst_overlap.tif"
    _write_lst(lst_path, _gradient_lst(), nodata=-9999.0)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lst.compute(RasterResource(lst_path, 1), _build_grid_spec())

    assert not [record for record in caught if "重なりません" in str(record.message)]
