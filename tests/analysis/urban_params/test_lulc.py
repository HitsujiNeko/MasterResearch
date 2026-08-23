"""params/lulc.py（土地被覆クラス別面積率パラメータの算出）のテスト。

集約そのもの（和=1・母数・欠測規約・nodata除外・警告の切り分け）は
``params.raster.aggregate_class_fractions_to_grid()`` が担い ``test_raster.py``
が網羅しているため、ここでは**LULC固有の責務**に絞る。すなわち、GLC/Esri
双方で同一列名を返すこと、雪氷を出力クラスから除くこと、ROI内に出現しない
クラスも列として出力すること、``class_scheme`` の検証、``None`` での空辞書
である。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.config import LULC_COLUMNS
from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import RasterResource
from src.analysis.urban_params.params import lulc

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

# ANALYSIS_BBOX（0-80m四方）を coarse=20m で分割した 4x4 グリッドを前提とする。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0
BAND_INDEX = 1

# GLC体系: 市街地(190)・水域(210)・雪氷(220)を2行ずつ敷く（coarse行0/1/2に対応）。
# 残り2行（coarse行3）はnodata(0)のまま。裸地(200)はROI内に出現しない構成にし、
# 「出現しないクラスも列として出力される」ことを検証できるようにする。
_GLC_ROWS = {190: (0, 2), 210: (2, 4), 220: (4, 6)}
# Esri体系: 市街地(7)・水域(1)・雪氷(9)。裸地(8)は同様に出現しない。
_ESRI_ROWS = {7: (0, 2), 1: (2, 4), 9: (4, 6)}


def _build_grid_spec():
    """テスト共通の 4x4 coarseグリッド仕様を構築する。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def _write_category_raster(path: Path, row_ranges_by_value: dict[int, tuple[int, int]]) -> None:
    """解析範囲（0-80m四方）を覆う10m解像度のカテゴリラスタを書き出す。

    行帯ごとに単一の画素値を敷く。指定しなかった行はnodata（0）のまま残る。

    Args:
        path: 出力先のGeoTIFFパス。
        row_ranges_by_value: 画素値から `(開始行, 終了行)`（終端は排他的）への辞書。
    """
    data = np.zeros((8, 8), dtype=np.uint8)
    for value, (row_start, row_end) in row_ranges_by_value.items():
        data[row_start:row_end, :] = value

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="uint8",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, FINE_RES_M, FINE_RES_M),
        nodata=0,
    ) as dst:
        dst.write(data, 1)


def test_compute_returns_empty_dict_for_none_resource() -> None:
    """resourceがNoneのシナリオでは空辞書を返す（他パラメータモジュールと同じ規約）。"""
    result = lulc.compute(None, ANALYSIS_BBOX, _build_grid_spec())

    assert result == {}


def test_compute_returns_declared_columns_for_glc_scheme(tmp_path: Path) -> None:
    """GLC体系の入力で、config.py が宣言する列名と一致する出力を返す。"""
    raster_path = tmp_path / "lulc_glc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    result = lulc.compute(
        RasterResource(raster_path, BAND_INDEX, "glc2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert set(result) == set(LULC_COLUMNS)


def test_compute_returns_same_column_names_for_glc_and_esri_schemes(tmp_path: Path) -> None:
    """GLC・Esriのどちらで算出しても同一の列名を返す（差し替え関係）。"""
    glc_path = tmp_path / "lulc_glc.tif"
    _write_category_raster(glc_path, _GLC_ROWS)
    esri_path = tmp_path / "lulc_esri.tif"
    _write_category_raster(esri_path, _ESRI_ROWS)

    glc_result = lulc.compute(
        RasterResource(glc_path, BAND_INDEX, "glc2022"), ANALYSIS_BBOX, _build_grid_spec()
    )
    esri_result = lulc.compute(
        RasterResource(esri_path, BAND_INDEX, "esri2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert set(glc_result) == set(esri_result) == set(LULC_COLUMNS)


def test_compute_maps_glc_class_values_to_correct_columns(tmp_path: Path) -> None:
    """GLC体系の画素値が、対応する列（LULC_BUILT_COV等）へ正しく写像される。"""
    raster_path = tmp_path / "lulc_glc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    result = lulc.compute(
        RasterResource(raster_path, BAND_INDEX, "glc2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    # coarse row=0（画素値190=市街地の行）は LULC_BUILT_COV が1.0、他クラスは0.0
    np.testing.assert_allclose(result["LULC_BUILT_COV"][0, :], 1.0, atol=1e-5)
    np.testing.assert_allclose(result["LULC_WATER_COV"][0, :], 0.0, atol=1e-5)
    # coarse row=1（画素値210=水域の行）は LULC_WATER_COV が1.0
    np.testing.assert_allclose(result["LULC_WATER_COV"][1, :], 1.0, atol=1e-5)
    np.testing.assert_allclose(result["LULC_BUILT_COV"][1, :], 0.0, atol=1e-5)


def test_compute_maps_esri_class_values_to_correct_columns(tmp_path: Path) -> None:
    """Esri体系の画素値が、GLCと同一の列へ写像される（値は違っても列名は共有）。"""
    raster_path = tmp_path / "lulc_esri.tif"
    _write_category_raster(raster_path, _ESRI_ROWS)

    result = lulc.compute(
        RasterResource(raster_path, BAND_INDEX, "esri2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    # coarse row=0（画素値7=市街地の行）
    np.testing.assert_allclose(result["LULC_BUILT_COV"][0, :], 1.0, atol=1e-5)
    # coarse row=1（画素値1=水域の行）
    np.testing.assert_allclose(result["LULC_WATER_COV"][1, :], 1.0, atol=1e-5)


def test_compute_excludes_snow_ice_cell_becomes_nan_with_zero_ratio(tmp_path: Path) -> None:
    """雪氷のみのセルは出力7クラスへ写像できないため、各クラスNaN・有効画素率0.0になる。

    雪氷はベトナムの対象都市で構造的に出現しないため定義から除外している
    （io_spec.md 6.4節）。除外の効果を、写像不能画素と同じ欠測規約に落ちる
    ことで確認する。
    """
    raster_path = tmp_path / "lulc_glc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    result = lulc.compute(
        RasterResource(raster_path, BAND_INDEX, "glc2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    # coarse row=2（画素値220=雪氷の行）
    for column_name in lulc.COLUMN_TO_COMMON_CLASS:
        assert np.isnan(result[column_name][2, :]).all(), column_name
    np.testing.assert_allclose(result["LULC_VALID_RATIO"][2, :], 0.0, atol=1e-5)


def test_compute_outputs_zero_valued_column_for_class_absent_in_roi(tmp_path: Path) -> None:
    """ROI内に出現しないクラス（裸地）も列として出力され、値は0.0になる。

    出現クラスに応じて列構成を変えると、都市が変わるたびにスキーマが変化して
    都市間比較ができなくなる（io_spec.md 6.4節）。
    """
    raster_path = tmp_path / "lulc_glc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    result = lulc.compute(
        RasterResource(raster_path, BAND_INDEX, "glc2022"), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert "LULC_BARE_COV" in result
    # 写像可能画素があるセル（市街地・水域の行）では裸地の割合は0.0（NaNではない）
    np.testing.assert_allclose(result["LULC_BARE_COV"][0, :], 0.0, atol=1e-5)
    np.testing.assert_allclose(result["LULC_BARE_COV"][1, :], 0.0, atol=1e-5)


def test_validate_resource_rejects_missing_class_scheme(tmp_path: Path) -> None:
    """class_scheme が未設定（既定値の空文字列）だと ValueError になる。"""
    raster_path = tmp_path / "lulc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    with pytest.raises(ValueError, match="未設定または未知"):
        lulc.validate_resource(RasterResource(raster_path, BAND_INDEX))


def test_validate_resource_rejects_unknown_class_scheme(tmp_path: Path) -> None:
    """class_scheme が CLASS_SCHEMES に無い値だと ValueError になる。"""
    raster_path = tmp_path / "lulc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    with pytest.raises(ValueError, match="未設定または未知"):
        lulc.validate_resource(RasterResource(raster_path, BAND_INDEX, "unknown_scheme"))


@pytest.mark.parametrize("class_scheme", ["glc2022", "esri2022"])
def test_validate_resource_accepts_known_class_schemes(tmp_path: Path, class_scheme: str) -> None:
    """既知の class_scheme では例外にならない。"""
    raster_path = tmp_path / "lulc.tif"
    _write_category_raster(raster_path, _GLC_ROWS)

    lulc.validate_resource(RasterResource(raster_path, BAND_INDEX, class_scheme))
