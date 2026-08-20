"""params/nightlight.py（夜間光強度パラメータの算出）のテスト。

集約そのもの（nodata除外・部分被覆・範囲外・警告の切り分け）は標高と共通の
``params.raster.aggregate_mean_and_valid_ratio()`` が担い ``test_elevation.py`` が
網羅しているため、ここでは**夜間光固有の責務**に絞る。すなわち、放射輝度を単位換算
せずそのまま運ぶこと（人口密度との対比）、実測値0を欠測と区別すること、主バンド以外を
指した場合の検知、および全解析スケールより粗い入力での内挿である。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.config import NIGHTLIGHT_COLUMNS
from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.io import RasterResource
from src.analysis.urban_params.params import nightlight

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS

# ANALYSIS_BBOX（0-80m四方）を coarse=20m で分割した 4x4 グリッドを前提とする。
COARSE_RES_M = 20.0
FINE_RES_M = 10.0

# 実データ（VIIRS DNB）と同じバンド構成。
RADIANCE_BAND = 1
MASKED_BAND = 2
COVERAGE_BAND = 3
MAX_RADIANCE_BAND = 4
# Black Marble の band 2（全視野角合成）。番号は VIIRS の MASKED_BAND と同じだが、
# 指しているバンドの意味が異なるため名前を分ける。
ALL_ANGLE_BAND = 2
VIIRS_DESCRIPTIONS = ("avg_radiance", "avg_radiance_masked", "cf_cvg", "max_radiance")


def _build_grid_spec():
    """テスト共通の 4x4 coarseグリッド仕様を構築する。"""
    return build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, COARSE_RES_M, FINE_RES_M)


def _write_nightlight_raster(
    path: Path,
    radiance: np.ndarray,
    descriptions: tuple[str, ...] = VIIRS_DESCRIPTIONS,
    nodata: float | None = -9999.0,
) -> None:
    """解析範囲（0-80m四方）を覆う10m解像度の4バンド夜間光ラスタを書き出す。

    実データと同じく band 1 に主バンド（放射輝度）を置く。band 3 には観測数を模した
    値（51-96相当）を入れ、バンドを取り違えたときに値が変わることを検証できるようにする。

    Args:
        path: 出力先のGeoTIFFパス。
        radiance: 放射輝度（nW·cm⁻²·sr⁻¹）の配列（8x8）。band 1 へ書き込む。
        descriptions: バンド説明。データセット差の検証で差し替える。
        nodata: nodata値。``None`` の場合はタグを設定しない。
    """
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=radiance.shape[0],
        width=radiance.shape[1],
        count=len(descriptions),
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, FINE_RES_M, FINE_RES_M),
        nodata=nodata,
    ) as dst:
        dst.write(radiance.astype(np.float32), RADIANCE_BAND)
        # band 2 は背景を0へ置換した版、band 3 は観測数、band 4 は最大放射輝度を模す。
        dst.write(np.maximum(radiance, 0.0).astype(np.float32), MASKED_BAND)
        dst.write(np.full(radiance.shape, 74.0, dtype=np.float32), COVERAGE_BAND)
        dst.write((radiance * 1.5).astype(np.float32), MAX_RADIANCE_BAND)
        dst.descriptions = descriptions


def test_compute_returns_empty_dict_for_none_resource() -> None:
    """resourceがNoneのシナリオでは空辞書を返す（他パラメータモジュールと同じ規約）。"""
    result = nightlight.compute(None, ANALYSIS_BBOX, _build_grid_spec())

    assert result == {}


def test_compute_returns_radiance_without_unit_conversion(tmp_path: Path) -> None:
    """NTL_MEAN はセル平均放射輝度をそのまま返す（面積正規化しない）。

    放射輝度は面積に比例しない強度量であり、人口密度のように /ha へ割ると
    意味を失う。人口と同じ集約関数を共有するぶん、換算の有無を取り違えやすい。
    """
    raster_path = tmp_path / "ntl_uniform.tif"
    # VIIRS DNB のROI平均（5.407 nW·cm⁻²·sr⁻¹）を模した値。
    _write_nightlight_raster(raster_path, np.full((8, 8), 5.407, dtype=np.float32))

    result = nightlight.compute(
        RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert set(result) == set(NIGHTLIGHT_COLUMNS) == {"NTL_MEAN", "NTL_VALID_RATIO"}
    ntl_mean = result["NTL_MEAN"]
    assert ntl_mean.shape == (4, 4)
    assert ntl_mean.dtype == np.float32
    np.testing.assert_allclose(ntl_mean, np.full((4, 4), 5.407, dtype=np.float32), rtol=1e-5)


def test_compute_averages_radiance_within_cell(tmp_path: Path) -> None:
    """セル内の有効画素の平均が入る。"""
    radiance = np.zeros((8, 8), dtype=np.float32)
    # セル(0, 0) に対応する左上2x2へ、平均が 10.0 になる4値を置く。
    radiance[0, 0] = 4.0
    radiance[0, 1] = 8.0
    radiance[1, 0] = 12.0
    radiance[1, 1] = 16.0
    raster_path = tmp_path / "ntl_varied.tif"
    _write_nightlight_raster(raster_path, radiance)

    ntl_mean = nightlight.compute(
        RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )["NTL_MEAN"]

    assert ntl_mean[0, 0] == pytest.approx(10.0, abs=0.05)


def test_compute_distinguishes_zero_radiance_from_missing(tmp_path: Path) -> None:
    """放射輝度0は実値として保持され、欠損（NaN）と区別される。

    Black Marble の ``ntl_near_nadir`` は ROI 内の最小値が 0.000 であり、実際に0を
    含む。0を欠損と同一視すると「電力由来の光が検出されなかった」セルが失われる。
    """
    radiance = np.full((8, 8), -9999.0, dtype=np.float32)
    # セル(0, 0) を放射輝度0、セル(0, 1) はnodataのままにする。
    radiance[0:2, 0:2] = 0.0
    raster_path = tmp_path / "ntl_zero.tif"
    _write_nightlight_raster(raster_path, radiance)

    result = nightlight.compute(
        RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    assert result["NTL_MEAN"][0, 0] == pytest.approx(0.0, abs=1e-6)
    assert not np.isnan(result["NTL_MEAN"][0, 0])
    assert result["NTL_VALID_RATIO"][0, 0] == pytest.approx(1.0, abs=1e-5)
    assert np.isnan(result["NTL_MEAN"][0, 1])
    assert result["NTL_VALID_RATIO"][0, 1] == pytest.approx(0.0, abs=1e-5)


def test_compute_interpolates_because_raster_is_coarser_than_every_scale(
    tmp_path: Path,
) -> None:
    """入力が全解析スケールより粗いため、どのスケールでも内挿になる。

    夜間光の解像度は約464mで、30m・90m・300m のいずれよりも粗い。1画素の値が複数
    セルへ一様に配られ、セル間の変動が入力の解像度に由来しない。これがRQ2を割り当て
    ない根拠であり、挙動として固定しておく。
    """
    # 40m画素 2x2（coarseセル20mの2倍の粗さ）で解析範囲（0-80m四方）を覆う。
    coarse_radiance = np.array([[2.5, 10.0], [30.0, 96.1]], dtype=np.float32)
    raster_path = tmp_path / "ntl_coarse.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0, 80, 40.0, 40.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(coarse_radiance, RADIANCE_BAND)

    result = nightlight.compute(
        RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    expected = np.repeat(np.repeat(coarse_radiance, 2, axis=0), 2, axis=1)
    np.testing.assert_allclose(result["NTL_MEAN"], expected, rtol=1e-5)
    np.testing.assert_allclose(
        result["NTL_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_warns_when_band_is_not_radiance(tmp_path: Path) -> None:
    """観測数バンド（cf_cvg）を指すと警告する。

    ``cf_cvg`` は51-96の値を取り、放射輝度と桁が重なる。取り違えても集約後の統計は
    もっともらしく見えるため、値を眺めるだけでは気づけない。
    """
    raster_path = tmp_path / "ntl_bands.tif"
    _write_nightlight_raster(raster_path, np.full((8, 8), 5.0, dtype=np.float32))

    with pytest.warns(UserWarning, match="バンド番号の取り違え"):
        result = nightlight.compute(
            RasterResource(raster_path, COVERAGE_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )

    # 警告は出るが処理は続き、観測数の値がそのまま入る（黙って落とさない）。
    assert result["NTL_MEAN"][0, 0] == pytest.approx(74.0, abs=0.5)


def test_compute_warns_when_masked_band_is_selected(tmp_path: Path) -> None:
    """背景を0置換した band 2（avg_radiance_masked）を指すと警告する。

    **本モジュールが明示的に退けているバンドである。** それでいて値は主バンドとほぼ
    同じ（ROI平均 5.307 対 5.407）ため、出力統計では絶対に判別できない。主バンドと
    語を共有するため、部分一致の照合では素通りしてしまう経路でもある。
    """
    raster_path = tmp_path / "ntl_masked.tif"
    _write_nightlight_raster(raster_path, np.full((8, 8), 5.0, dtype=np.float32))

    with pytest.warns(UserWarning, match="avg_radiance_masked"):
        nightlight.compute(
            RasterResource(raster_path, MASKED_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )


def test_compute_warns_when_max_radiance_band_is_selected(tmp_path: Path) -> None:
    """最大放射輝度バンド（band 4）を指すと警告する。

    平均ではなく最大であるため意味が異なるが、単位も桁も同じでもっともらしく見える。
    """
    raster_path = tmp_path / "ntl_max.tif"
    _write_nightlight_raster(raster_path, np.full((8, 8), 5.0, dtype=np.float32))

    with pytest.warns(UserWarning, match="max_radiance"):
        nightlight.compute(
            RasterResource(raster_path, MAX_RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )


def test_compute_warns_when_all_angle_band_is_selected(tmp_path: Path) -> None:
    """Black Marble の全視野角合成（band 2）を指すと警告する。

    近直下視合成（主バンド）とは観測条件が異なるが、``ntl_`` の語幹を共有するため
    部分一致では検知できない。
    """
    raster_path = tmp_path / "ntl_all_angle.tif"
    _write_nightlight_raster(
        raster_path,
        np.full((8, 8), 6.7, dtype=np.float32),
        descriptions=("ntl_near_nadir", "ntl_all_angle", "near_nadir_num", "near_nadir_std"),
    )

    with pytest.warns(UserWarning, match="ntl_all_angle"):
        nightlight.compute(
            RasterResource(raster_path, ALL_ANGLE_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )


@pytest.mark.parametrize(
    ("descriptions", "label"),
    [
        (VIIRS_DESCRIPTIONS, "VIIRS DNB"),
        (
            ("ntl_near_nadir", "ntl_all_angle", "near_nadir_num", "near_nadir_std"),
            "Black Marble",
        ),
    ],
)
def test_compute_accepts_primary_band_of_both_datasets(
    tmp_path: Path, descriptions: tuple[str, ...], label: str
) -> None:
    """主バンドの名前がデータセット間で異なっても、正しい入力では警告しない。

    VIIRS DNB は ``avg_radiance``、Black Marble は ``ntl_near_nadir`` で共通語を
    持たない。片方しか通らない照合だと、正しい入力に警告が出て信頼されなくなる。
    """
    raster_path = tmp_path / f"ntl_{label.replace(' ', '_')}.tif"
    _write_nightlight_raster(
        raster_path, np.full((8, 8), 6.7, dtype=np.float32), descriptions=descriptions
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        nightlight.compute(
            RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )

    assert not [record for record in caught if "バンド番号の取り違え" in str(record.message)]


def test_radiance_band_names_match_fetch_script_output_names() -> None:
    """主バンド名は取得スクリプトの出力名と一致する。

    **完全一致で照合する以上、この一致が前提になる。** 取得スクリプト側で
    ``output_name`` を変えると、分析側は「正しい入力なのに警告」を出すようになる。
    黙って壊れはしないが原因が遠いため、一致をここで固定する。

    逆方向（GEE・HDF側のバンド改名）は取得スクリプトの ``source_name`` が受け止めて
    そちらが落ちるため、分析側が誤警告を出す経路にはならない。
    """
    from src.preprocessing.fetch_black_marble_hanoi import (
        PRIMARY_BAND_NAME as BLACK_MARBLE_PRIMARY_BAND,
    )
    from src.preprocessing.fetch_viirs_dnb_hanoi import (
        PRIMARY_BAND_NAME as VIIRS_PRIMARY_BAND,
    )

    assert set(nightlight.RADIANCE_BAND_NAMES) == {
        VIIRS_PRIMARY_BAND,
        BLACK_MARBLE_PRIMARY_BAND,
    }


def test_compute_reprojects_from_geographic_crs(tmp_path: Path) -> None:
    """夜間光ラスタが地理座標系（EPSG:4326）でも、再投影されて値が保持される。

    VIIRS DNB・Black Marbleはいずれも EPSG:4326 で保存され、解析CRSは EPSG:5897 で
    ある。実運用では必ず再投影を伴うため、この経路を明示的に検証する。
    """
    # ANALYSIS_BBOX（EPSG:3857 の 0-80m四方）は経緯度の原点近傍にあたる。
    raster_path = tmp_path / "ntl_wgs84.tif"
    with rasterio.open(
        raster_path,
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
        dst.write(np.full((10, 10), 21.3, dtype=np.float32), RADIANCE_BAND)

    result = nightlight.compute(
        RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
    )

    np.testing.assert_allclose(
        result["NTL_MEAN"], np.full((4, 4), 21.3, dtype=np.float32), rtol=1e-4
    )
    np.testing.assert_allclose(
        result["NTL_VALID_RATIO"], np.ones((4, 4), dtype=np.float32), atol=1e-5
    )


def test_compute_warns_with_nightlight_label_when_raster_does_not_overlap(
    tmp_path: Path,
) -> None:
    """夜間光ラスタがグリッドと重ならない場合、夜間光の入力だと分かる警告を出す。"""
    raster_path = tmp_path / "ntl_far.tif"
    with rasterio.open(
        raster_path,
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
        dst.write(np.full((8, 8), 5.0, dtype=np.float32), RADIANCE_BAND)

    with pytest.warns(UserWarning, match="夜間光ラスタが解析グリッドと重なりません"):
        result = nightlight.compute(
            RasterResource(raster_path, RADIANCE_BAND), ANALYSIS_BBOX, _build_grid_spec()
        )

    assert np.isnan(result["NTL_MEAN"]).all()
    np.testing.assert_allclose(result["NTL_VALID_RATIO"], 0.0, atol=1e-5)
