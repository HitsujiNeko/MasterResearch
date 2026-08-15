"""params/elevation.py（標高パラメータの算出）のテスト。"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import RasterResource
from src.analysis.urban_params.params import elevation

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

# ANALYSIS_BBOX（0-80m四方）を coarse=20m で分割した 4x4 グリッドを前提とする。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0


def _build_grid_spec():
    """テスト共通の 4x4 coarseグリッド仕様を構築する。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def _write_dem(
    path: Path,
    data: np.ndarray,
    nodata: float | None = None,
    band_count: int = 1,
) -> None:
    """解析範囲（0-80m四方）を覆う10m解像度のDEMを書き出す。

    Args:
        path: 出力先のGeoTIFFパス。
        data: 標高値の配列（8x8）。``band_count`` が2以上の場合は最終バンドへ書き込み、
            それ以外のバンドにはゼロを書き込む。
        nodata: nodata値。``None`` の場合はタグを設定しない。
        band_count: 作成するバンド数。バンド番号の指定を検証する際に使う。
    """
    transform = from_origin(0, 80, FINE_RES_M, FINE_RES_M)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=band_count,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=transform,
        nodata=nodata,
    ) as dst:
        for band_index in range(1, band_count + 1):
            if band_index == band_count:
                dst.write(data.astype(np.float32), band_index)
            else:
                dst.write(np.zeros(data.shape, dtype=np.float32), band_index)


def _gradient_dem() -> np.ndarray:
    """行・列から一意に決まる 8x8 の標高配列を作る（セル平均が手計算できる）。"""
    rows, cols = np.indices((8, 8))
    return (rows * 8 + cols).astype(np.float32)


def test_compute_returns_empty_dict_for_none_resource() -> None:
    """resourceがNoneのシナリオでは空辞書を返す（他パラメータモジュールと同じ規約）。"""
    result = elevation.compute(None, ANALYSIS_BBOX, _build_grid_spec())

    assert result == {}


def test_compute_returns_cell_mean_elevation(tmp_path: Path) -> None:
    """ELEV_MEAN列にcoarseセル内の平均標高（m）が入る。"""
    dem_path = tmp_path / "dem.tif"
    _write_dem(dem_path, _gradient_dem())

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    assert set(result) == {"ELEV_MEAN", "ELEV_VALID_RATIO"}
    elev_mean = result["ELEV_MEAN"]
    assert elev_mean.shape == (4, 4)
    assert elev_mean.dtype == np.float32
    # セル(0, 0) は左上2x2画素（0, 1, 8, 9）の平均。
    assert elev_mean[0, 0] == pytest.approx(4.5, abs=0.5)
    # セル(3, 3) は右下2x2画素（54, 55, 62, 63）の平均。
    assert elev_mean[3, 3] == pytest.approx(58.5, abs=0.5)


def test_compute_excludes_nodata_from_mean(tmp_path: Path) -> None:
    """nodata（-9999）が平均へ混入せず、有効画素のみで平均される。"""
    data = np.full((8, 8), 10.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のうち1画素だけをnodataにする。
    data[0, 0] = -9999.0
    dem_path = tmp_path / "dem_nodata.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    elev_mean = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_MEAN"
    ]

    # -9999 が混ざれば平均は大きく負に振れる。有効画素のみなら10.0のまま。
    assert elev_mean[0, 0] == pytest.approx(10.0, abs=0.5)
    assert not np.isnan(elev_mean[0, 0])


def test_compute_keeps_all_nodata_cell_as_nan(tmp_path: Path) -> None:
    """全画素がnodataのセルはNaNのまま残る（0で埋めない）。"""
    data = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のみ有効値にする。
    data[0:2, 0:2] = 25.0
    dem_path = tmp_path / "dem_all_nodata.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    elev_mean = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_MEAN"
    ]

    assert elev_mean[0, 0] == pytest.approx(25.0, abs=0.5)
    assert np.isnan(elev_mean[0, 1])
    assert np.isnan(elev_mean[3, 3])


def test_compute_distinguishes_zero_elevation_from_missing(tmp_path: Path) -> None:
    """標高0mは実値として保持され、欠損（NaN）と区別される。

    FABDEMには最小0.0mの実画素が存在する。0を欠損と同一視すると海抜0mの
    セルが失われるため、両者が別物として出力されることを担保する。
    """
    data = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) を標高0m、セル(0, 1) はnodataのままにする。
    data[0:2, 0:2] = 0.0
    dem_path = tmp_path / "dem_zero.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    elev_mean = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_MEAN"
    ]

    assert elev_mean[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert not np.isnan(elev_mean[0, 0])
    assert np.isnan(elev_mean[0, 1])


def test_valid_ratio_is_one_for_fully_covered_cells(tmp_path: Path) -> None:
    """全画素が有効なセルの有効画素率は1.0になる。"""
    dem_path = tmp_path / "dem_full.tif"
    _write_dem(dem_path, _gradient_dem(), nodata=-9999.0)

    valid_ratio = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_VALID_RATIO"
    ]

    assert valid_ratio.shape == (4, 4)
    assert valid_ratio.dtype == np.float32
    np.testing.assert_allclose(valid_ratio, np.ones((4, 4), dtype=np.float32), atol=1e-5)


def test_valid_ratio_distinguishes_partially_covered_cells(tmp_path: Path) -> None:
    """部分被覆セルはELEV_MEANでは完全被覆セルと区別できず、有効画素率でのみ区別できる。

    ``Resampling.average`` は有効画素のみの平均を返すため、セル内の有効画素が
    3/4しか無くても完全被覆セルと同じ値になる。有効カバレッジを過大評価しない
    ために、比率を別列として出力する必要がある。
    """
    data = np.full((8, 8), 10.0, dtype=np.float32)
    # セル(0, 0) に対応する左上2x2のうち1画素だけをnodataにする（有効画素率 3/4）。
    data[0, 0] = -9999.0
    dem_path = tmp_path / "dem_partial.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    # ELEV_MEAN は部分被覆セルと完全被覆セルで同じ値になる（区別できない）。
    assert result["ELEV_MEAN"][0, 0] == pytest.approx(result["ELEV_MEAN"][0, 1], abs=1e-5)
    # ELEV_VALID_RATIO は両者を区別する。
    assert result["ELEV_VALID_RATIO"][0, 0] == pytest.approx(0.75, abs=0.05)
    assert result["ELEV_VALID_RATIO"][0, 1] == pytest.approx(1.0, abs=1e-5)


def test_valid_ratio_is_zero_for_all_nodata_cells(tmp_path: Path) -> None:
    """全画素がnodataのセルは有効画素率0.0であり、ELEV_MEANはNaNになる。"""
    data = np.full((8, 8), -9999.0, dtype=np.float32)
    data[0:2, 0:2] = 25.0
    dem_path = tmp_path / "dem_ratio_nodata.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    assert result["ELEV_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert result["ELEV_VALID_RATIO"][3, 3] == pytest.approx(0.0, abs=1e-5)
    assert np.isnan(result["ELEV_MEAN"][3, 3])


def test_valid_ratio_is_zero_outside_raster_extent(tmp_path: Path) -> None:
    """ラスタの範囲外セルは、NaNではなく有効画素率0.0になる。

    範囲外を ``NaN`` にすると「nodataで覆われたセル」と区別が付かなくなるため、
    どちらも「有効画素なし」を意味する0.0へ揃える。
    """
    # 解析範囲（0-80m四方）の左半分（x: 0-40m）だけを覆うDEMを書き出す。
    dem_path = tmp_path / "dem_half.tif"
    with rasterio.open(
        dem_path,
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
        dst.write(np.full((8, 4), 12.0, dtype=np.float32), 1)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    assert result["ELEV_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert result["ELEV_VALID_RATIO"][0, 3] == pytest.approx(0.0, abs=1e-5)
    assert not np.isnan(result["ELEV_VALID_RATIO"]).any()
    assert np.isnan(result["ELEV_MEAN"][0, 3])


def test_valid_ratio_matches_mean_for_nan_pixels_with_nodata_tag(tmp_path: Path) -> None:
    """nodataタグ付きラスタに実値NaNが混じっても、平均と有効画素率の定義が揃う。

    GDALは ``src_nodata`` に単一値しか取れないため、対策が無いとNaNが平均へ伝播し、
    1画素のNaNでセル平均が丸ごとNaNになる一方、有効画素率は0.75を返して両列の
    整合（片方がNaNなら他方は0）が崩れる。
    """
    data = np.full((8, 8), 10.0, dtype=np.float32)
    # nodataタグ（-9999）ではなく実値NaNを1画素だけ置く。
    data[0, 0] = np.nan
    dem_path = tmp_path / "dem_nan_with_tag.tif"
    _write_dem(dem_path, data, nodata=-9999.0)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    # NaNは欠損として平均から除外され、残り3画素の平均が入る。
    assert result["ELEV_MEAN"][0, 0] == pytest.approx(10.0, abs=0.5)
    assert result["ELEV_VALID_RATIO"][0, 0] == pytest.approx(0.75, abs=0.05)
    # 片方がNaNなら他方は0、という整合が全セルで保たれる。
    nan_cells = np.isnan(result["ELEV_MEAN"])
    np.testing.assert_allclose(result["ELEV_VALID_RATIO"][nan_cells], 0.0, atol=1e-5)
    assert (result["ELEV_VALID_RATIO"][~nan_cells] > 0.0).all()


def test_valid_ratio_overestimates_cells_crossing_raster_edge(tmp_path: Path) -> None:
    """ラスタ外周をまたぐセルでは、有効画素率が実被覆より高くなる（既知の制限）。

    比率は「有効画素を1・nodataを0とした配列の平均」で得るため、画素が1つも無い
    領域が占める分は反映されない。ROIでcrop済みの現行DEMでは解析BBox最外周の
    セルに限られるが、仕様として固定しておく。
    """
    # セル(0, 0)（0-20m四方）の左半分（x: 0-10m）だけを覆うDEMを書き出す。
    dem_path = tmp_path / "dem_edge.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=2,
        width=1,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, FINE_RES_M, FINE_RES_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((2, 1), 5.0, dtype=np.float32), 1)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    # 実際の被覆は0.5だが、画素の無い領域は分母に含まれないため1.0になる。
    assert result["ELEV_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert result["ELEV_MEAN"][0, 0] == pytest.approx(5.0, abs=0.5)


def test_compute_warns_when_dem_does_not_overlap_grid(tmp_path: Path) -> None:
    """DEMが解析グリッドとまったく重ならない場合は警告する。

    都市とDEMの取り違え・切り出し範囲の誤りではファイルが存在するため入力解決を
    素通りし、全セルNaNの列が黙って出力される。列が残るぶん欠損に気づきにくい。
    """
    # 解析範囲（0-80m四方）から大きく離れた位置のDEMを書き出す。
    dem_path = tmp_path / "dem_far.tif"
    with rasterio.open(
        dem_path,
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
        dst.write(np.full((8, 8), 20.0, dtype=np.float32), 1)

    with pytest.warns(UserWarning, match="重なりません"):
        result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    assert np.isnan(result["ELEV_MEAN"]).all()
    np.testing.assert_allclose(result["ELEV_VALID_RATIO"], 0.0, atol=1e-5)


def test_compute_warns_all_missing_not_no_overlap_when_dem_is_fully_nodata(
    tmp_path: Path,
) -> None:
    """DEMがグリッドと重なっていて全画素nodataの場合、「重なりません」とは言わない。

    どちらも全セルNaNという同じ結果になるが、切り出し範囲を疑うべき場合と、
    nodata値の取り違えを疑うべき場合とで対処が異なる。
    """
    dem_path = tmp_path / "dem_all_nodata.tif"
    _write_dem(dem_path, np.full((8, 8), -9999.0, dtype=np.float32), nodata=-9999.0)

    with pytest.warns(UserWarning, match="有効画素が1つもありません") as caught:
        result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    assert not [record for record in caught if "重なりません" in str(record.message)]
    assert np.isnan(result["ELEV_MEAN"]).all()


def test_compute_does_not_warn_when_dem_overlaps_grid(tmp_path: Path) -> None:
    """DEMがグリッドと重なる通常の入力では警告しない。"""
    dem_path = tmp_path / "dem_overlap.tif"
    _write_dem(dem_path, _gradient_dem(), nodata=-9999.0)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    # 非重複の警告のみを対象にする（依存ライブラリの無関係な警告では失敗させない）。
    assert not [record for record in caught if "重なりません" in str(record.message)]


def test_compute_reprojects_from_geographic_crs(tmp_path: Path) -> None:
    """DEMが解析CRSと異なる地理座標系でも、再投影されて値が保持される。

    FABDEMはEPSG:4326、解析CRSはEPSG:5897（投影座標系）であり、実運用では
    必ず再投影を伴う。同一CRSのテストだけではこの経路を通らないため、
    地理座標系のDEMを明示的に検証する。
    """
    # ANALYSIS_BBOX（EPSG:3857 の 0-80m四方）は経緯度の原点近傍にあたる。
    # 0.0005度刻みの10x10画素で、その範囲を余裕を持って覆う。
    dem_path = tmp_path / "dem_wgs84.tif"
    with rasterio.open(
        dem_path,
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
        dst.write(np.full((10, 10), 55.0, dtype=np.float32), 1)

    result = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())

    elev_mean = result["ELEV_MEAN"]
    assert not np.isnan(elev_mean).any()
    np.testing.assert_allclose(elev_mean, np.full((4, 4), 55.0, dtype=np.float32), rtol=1e-5)
    # 有効画素率も同じ再投影経路を通るため、あわせて検証する（実運用は必ずこの経路）。
    np.testing.assert_allclose(
        result["ELEV_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_uses_specified_band(tmp_path: Path) -> None:
    """RasterResourceのband_indexで指定したバンドを読み込む。"""
    dem_path = tmp_path / "dem_multiband.tif"
    _write_dem(dem_path, np.full((8, 8), 42.0, dtype=np.float32), band_count=2)

    elev_band2 = elevation.compute(RasterResource(dem_path, 2), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_MEAN"
    ]
    elev_band1 = elevation.compute(RasterResource(dem_path, 1), ANALYSIS_BBOX, _build_grid_spec())[
        "ELEV_MEAN"
    ]

    assert elev_band2[0, 0] == pytest.approx(42.0, abs=0.5)
    assert elev_band1[0, 0] == pytest.approx(0.0, abs=0.5)
