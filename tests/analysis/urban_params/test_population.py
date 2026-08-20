"""params/population.py（人口密度パラメータの算出）のテスト。

集約そのもの（nodata除外・部分被覆・範囲外・再投影・警告）は標高と共通の
``params.raster.aggregate_mean_and_valid_ratio()`` が担い ``test_elevation.py`` が
網羅しているため、ここでは**人口固有の責務**に絞る。すなわち、人/km² から人/ha への
単位換算、換算を有効画素率へ波及させないこと、密度バンドの選択、および
運用上の解釈（``POP_DEN × POP_VALID_RATIO`` がセル全体を母数とする密度になること）である。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.config import POPULATION_BASE_COLUMNS
from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import RasterResource
from src.analysis.urban_params.params import population

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

# ANALYSIS_BBOX（0-80m四方）を coarse=20m で分割した 4x4 グリッドを前提とする。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0

# 実データと同じバンド構成（band 1: カウント、band 2: 密度）。
COUNT_BAND = 1
DENSITY_BAND = 2


def _build_grid_spec():
    """テスト共通の 4x4 coarseグリッド仕様を構築する。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def _write_population_raster(
    path: Path,
    density: np.ndarray,
    count: np.ndarray | None = None,
    nodata: float | None = -9999.0,
) -> None:
    """解析範囲（0-80m四方）を覆う10m解像度の2バンド人口ラスタを書き出す。

    実データ（WorldPop / LandScan）と同じく band 1 にカウント、band 2 に密度を置く。
    バンドを取り違えたときに値が明確に変わるよう、``count`` の既定値は密度の10倍とする。

    Args:
        path: 出力先のGeoTIFFパス。
        density: 人口密度（人/km²）の配列（8x8）。band 2 へ書き込む。
        count: 人口カウント（人/セル）の配列。``None`` の場合は ``density`` の10倍。
        nodata: nodata値。``None`` の場合はタグを設定しない。
    """
    if count is None:
        count = density * 10.0
    transform = from_origin(0, 80, FINE_RES_M, FINE_RES_M)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=density.shape[0],
        width=density.shape[1],
        count=2,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(count.astype(np.float32), COUNT_BAND)
        dst.write(density.astype(np.float32), DENSITY_BAND)
        dst.descriptions = ("population_count", "population_density_per_km2")


def _uniform_density(value: float) -> np.ndarray:
    """一様な密度（人/km²）の 8x8 配列を作る。"""
    return np.full((8, 8), value, dtype=np.float32)


def test_compute_returns_empty_dict_for_none_resource() -> None:
    """resourceがNoneのシナリオでは空辞書を返す（他パラメータモジュールと同じ規約）。"""
    result = population.compute(None, ANALYSIS_BBOX, _build_grid_spec())

    assert result == {}


def test_compute_converts_density_from_per_km2_to_per_hectare(tmp_path: Path) -> None:
    """POP_DEN は人/km²を100で割った人/haで出力される。

    単位を誤ると値が2桁ずれるが、密度としてはどちらもあり得る大きさになるため、
    出力を眺めるだけでは気づけない。
    """
    raster_path = tmp_path / "pop_uniform.tif"
    # LandScan 2023 のROI平均密度（2,621.8 人/km²）を模した値。
    _write_population_raster(raster_path, _uniform_density(2621.8))

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    # モジュールが返すのは接尾辞を付ける**前**の基底名である。実際の出力列名
    # （POP_DEN_LANDSCAN2023 等）は run.py の apply_column_suffix() が組み立てる。
    assert set(result) == set(POPULATION_BASE_COLUMNS) == {"POP_DEN", "POP_VALID_RATIO"}
    pop_den = result["POP_DEN"]
    assert pop_den.shape == (4, 4)
    assert pop_den.dtype == np.float32
    np.testing.assert_allclose(pop_den, np.full((4, 4), 26.218, dtype=np.float32), rtol=1e-4)


def test_compute_averages_within_cell_before_conversion(tmp_path: Path) -> None:
    """セル平均を取ったうえで換算する（画素ごとの値がそのまま残らない）。"""
    density = np.zeros((8, 8), dtype=np.float32)
    # セル(0, 0) に対応する左上2x2へ、平均が 400 人/km² になる4値を置く。
    density[0, 0] = 100.0
    density[0, 1] = 300.0
    density[1, 0] = 500.0
    density[1, 1] = 700.0
    raster_path = tmp_path / "pop_varied.tif"
    _write_population_raster(raster_path, density)

    pop_den = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )["POP_DEN"]

    assert pop_den[0, 0] == pytest.approx(4.0, abs=0.05)


def test_compute_interpolates_when_raster_is_coarser_than_cell(tmp_path: Path) -> None:
    """入力ラスタがcoarseセルより粗い場合、セルは被覆画素の値をそのまま取る。

    **実運用ではこちらが主要経路である。** LandScan（約928m）は30m・90m・300mの全解析
    スケールでセルより粗く、WorldPop（約92.77m）も30mでは粗い。他のラスタパラメータ
    （FABDEM・LST・衛星指標）はいずれもセルと同等以上に細かく、この経路を通らない。

    このとき集約は「セル内の面積平均密度」ではなく内挿であり、1画素の値が複数セルへ
    一様に配られる。値は正しく運ばれるが**セル間の変動が入力の解像度に由来しない**ため、
    RQ2のスケール間比較でこの経路の値を過大解釈しないこと。
    """
    # 40m画素 2x2（coarseセル20mの2倍の粗さ）で解析範囲（0-80m四方）を覆う。
    coarse_density = np.array([[1000.0, 2000.0], [3000.0, 4000.0]], dtype=np.float32)
    raster_path = tmp_path / "pop_coarse.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=2,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, 40.0, 40.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(coarse_density * 10.0, COUNT_BAND)
        dst.write(coarse_density, DENSITY_BAND)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    # 各画素の値が、対応する2x2のcoarseセルへ一様に配られる（人/haへ換算済み）。
    expected = np.repeat(np.repeat(coarse_density / 100.0, 2, axis=0), 2, axis=1)
    np.testing.assert_allclose(result["POP_DEN"], expected, rtol=1e-5)
    # 画素が粗くても、セルはすべて有効画素に覆われている（部分被覆にはならない）。
    np.testing.assert_allclose(
        result["POP_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_does_not_scale_valid_ratio(tmp_path: Path) -> None:
    """有効画素率は単位換算の対象外であり、0-1の範囲を保つ。

    戻り値の辞書ごと100で割ると比率まで1/100になり、有効カバレッジを
    極端に低く見せる。列を選んで換算していることを担保する。
    """
    density = _uniform_density(1000.0)
    # セル(0, 0) の左上2x2のうち1画素だけをnodataにする（有効画素率 3/4）。
    density[0, 0] = -9999.0
    raster_path = tmp_path / "pop_partial.tif"
    _write_population_raster(raster_path, density)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    valid_ratio = result["POP_VALID_RATIO"]
    assert valid_ratio.dtype == np.float32
    assert valid_ratio[0, 0] == pytest.approx(0.75, abs=0.05)
    assert valid_ratio[3, 3] == pytest.approx(1.0, abs=1e-5)
    assert ((valid_ratio >= 0.0) & (valid_ratio <= 1.0)).all()


def test_cell_wide_density_is_product_of_mean_and_valid_ratio(tmp_path: Path) -> None:
    """POP_DEN × POP_VALID_RATIO がセル全体を母数とする密度になる。

    WorldPopは水域を無効画素にするため、水域が大半のセルでも陸地部分の密度が
    そのまま ``POP_DEN`` に入る。セル全体で薄まった密度が必要な場合の換算式を
    出力仕様として固定しておく。
    """
    density = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) の左上2x2のうち1画素だけが陸地（2,000 人/km² = 20 人/ha）。
    density[0, 0] = 2000.0
    raster_path = tmp_path / "pop_water.tif"
    _write_population_raster(raster_path, density)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    # 有効画素のみの平均であり、水域で薄まらない。
    assert result["POP_DEN"][0, 0] == pytest.approx(20.0, abs=0.2)
    assert result["POP_VALID_RATIO"][0, 0] == pytest.approx(0.25, abs=0.05)
    # セル全体を母数にすると 1/4 になる。
    cell_wide = result["POP_DEN"][0, 0] * result["POP_VALID_RATIO"][0, 0]
    assert cell_wide == pytest.approx(5.0, abs=0.2)


def test_compute_keeps_nan_for_cells_without_valid_pixels(tmp_path: Path) -> None:
    """有効画素が無いセルは換算後もNaNのまま残り、0で埋められない。

    人口密度0は「誰も住んでいない」という実測値であり、欠測とは別物である。
    """
    density = np.full((8, 8), -9999.0, dtype=np.float32)
    density[0:2, 0:2] = 1500.0
    raster_path = tmp_path / "pop_all_nodata.tif"
    _write_population_raster(raster_path, density)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert result["POP_DEN"][0, 0] == pytest.approx(15.0, abs=0.2)
    assert np.isnan(result["POP_DEN"][3, 3])
    assert result["POP_VALID_RATIO"][3, 3] == pytest.approx(0.0, abs=1e-5)


def test_compute_distinguishes_zero_density_from_missing(tmp_path: Path) -> None:
    """人口密度0は実値として保持され、欠損（NaN）と区別される。"""
    density = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) を密度0、セル(0, 1) はnodataのままにする。
    density[0:2, 0:2] = 0.0
    raster_path = tmp_path / "pop_zero.tif"
    _write_population_raster(raster_path, density)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert result["POP_DEN"][0, 0] == pytest.approx(0.0, abs=1e-6)
    assert not np.isnan(result["POP_DEN"][0, 0])
    assert result["POP_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert np.isnan(result["POP_DEN"][0, 1])


def test_compute_reads_density_band_not_count_band(tmp_path: Path) -> None:
    """band_indexで指定した密度バンドを読む（カウントバンドと取り違えない）。

    実データは band 1 がカウント、band 2 が密度である。カウントを集約すると
    単位が人/haにならないうえ、値としては密度と紛らわしい大きさになる。
    """
    raster_path = tmp_path / "pop_bands.tif"
    _write_population_raster(raster_path, _uniform_density(1000.0))

    density_result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )["POP_DEN"]
    count_result = population.compute(
        RasterResource(raster_path, COUNT_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )["POP_DEN"]

    assert density_result[0, 0] == pytest.approx(10.0, abs=0.1)
    # カウントバンドは密度の10倍で書いてあるため、読み分けができていれば値が異なる。
    assert count_result[0, 0] == pytest.approx(100.0, abs=1.0)


def test_validate_resource_warns_for_count_band(tmp_path: Path) -> None:
    """カウントバンド（band 1）を指した入力は、算出を始める前に警告する。

    取り違えても値は出るため、集約後の統計を見ても気づけない。検証は ``compute()``
    ではなく入力解決時に行うため、警告もそちらの経路から出る。
    """
    raster_path = tmp_path / "pop_bands.tif"
    _write_population_raster(raster_path, _uniform_density(1000.0))

    with pytest.warns(UserWarning, match="バンド番号の取り違え"):
        population.validate_resource(RasterResource(raster_path, COUNT_BAND))


def test_validate_resource_does_not_warn_for_density_band(tmp_path: Path) -> None:
    """密度バンドを指した通常の入力では、バンド説明の警告を出さない。"""
    raster_path = tmp_path / "pop_ok.tif"
    _write_population_raster(raster_path, _uniform_density(1000.0))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        population.validate_resource(RasterResource(raster_path, DENSITY_BAND))

    # バンド説明に関する警告のみを対象にする（依存ライブラリの無関係な警告では失敗させない）。
    assert not [record for record in caught if "バンド番号の取り違え" in str(record.message)]


def test_density_band_keywords_match_fetch_script_output_name() -> None:
    """照合キーワードは、取得スクリプトが付ける密度バンド名に含まれる。

    ``DENSITY_BAND_KEYWORDS`` は ``fetch_population_hanoi.py`` が書き出すバンド名への
    仮定である。取得側の名前を変えると、この検査は「正常な入力に毎回警告を出す」か
    「取り違えを素通りさせる」かのどちらかに黙って壊れる。バンドの取り違えは出力統計に
    現れないため、検査が壊れていること自体に気づけない。
    """
    from src.preprocessing.fetch_population_hanoi import BAND_COUNT_NAME, BAND_DENSITY_NAME

    for keyword in population.DENSITY_BAND_KEYWORDS:
        assert keyword in BAND_DENSITY_NAME.lower(), (
            f"密度バンド名 '{BAND_DENSITY_NAME}' が照合キーワード '{keyword}' を含みません"
        )
        # カウントバンドが同じ語を含むと、取り違えを検知できなくなる。
        assert keyword not in BAND_COUNT_NAME.lower(), (
            f"カウントバンド名 '{BAND_COUNT_NAME}' が照合キーワード '{keyword}' を含みます"
        )


def test_compute_reprojects_from_geographic_crs(tmp_path: Path) -> None:
    """人口ラスタが地理座標系（EPSG:4326）でも、再投影されて値が保持される。

    WorldPop・LandScanはいずれもEPSG:4326で保存され、解析CRSはEPSG:5897である。
    実運用では必ず再投影を伴うため、この経路を明示的に検証する。
    """
    # ANALYSIS_BBOX（EPSG:3857 の 0-80m四方）は経緯度の原点近傍にあたる。
    raster_path = tmp_path / "pop_wgs84.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=2,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-0.001, 0.002, 0.0005, 0.0005),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((10, 10), 99999.0, dtype=np.float32), COUNT_BAND)
        dst.write(np.full((10, 10), 3000.0, dtype=np.float32), DENSITY_BAND)

    result = population.compute(
        RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    np.testing.assert_allclose(
        result["POP_DEN"], np.full((4, 4), 30.0, dtype=np.float32), rtol=1e-4
    )
    np.testing.assert_allclose(
        result["POP_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_warns_with_population_label_when_raster_does_not_overlap(
    tmp_path: Path,
) -> None:
    """人口ラスタがグリッドと重ならない場合、人口の入力だと分かる警告を出す。

    複数の人口データセットを並べて実行するため、どの入力が外れているかが
    警告文から分からないと切り分けができない。
    """
    raster_path = tmp_path / "pop_far.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=2,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(100000, 100000, FINE_RES_M, FINE_RES_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((8, 8), 10.0, dtype=np.float32), COUNT_BAND)
        dst.write(np.full((8, 8), 1000.0, dtype=np.float32), DENSITY_BAND)

    with pytest.warns(UserWarning, match="人口ラスタが解析グリッドと重なりません"):
        result = population.compute(
            RasterResource(raster_path, DENSITY_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )

    assert np.isnan(result["POP_DEN"]).all()
    np.testing.assert_allclose(result["POP_VALID_RATIO"], 0.0, atol=1e-5)
