"""params/raster.py（衛星指標のグリッド集約）のテスト。"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.params.raster import (
    aggregate_mean_and_valid_ratio,
    aggregate_raster_to_grid,
    aggregate_valid_ratio_to_grid,
    coarse_grid_bounds,
    raster_overlaps_grid,
    warn_if_band_description_unexpected,
)
from src.common.geo_metadata import BBox


def _write_test_raster(
    path: Path, data: np.ndarray, transform: rasterio.Affine, crs: str = "EPSG:3857"
) -> None:
    """テスト用GeoTIFFを書き出す（nodata未設定＝GEE出力と同じ状態）。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_aggregate_raster_nan_not_propagated(tmp_path: Path) -> None:
    """nodata=NoneかつNaN混在ラスタで、有効ピクセルの平均が保持される。"""
    data = np.array(
        [
            [1.0, 2.0, 3.0, 4.0],
            [5.0, 6.0, 7.0, 8.0],
            [9.0, 10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0, np.nan],
        ],
        dtype=np.float32,
    )
    tif_path = tmp_path / "test.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, data, transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    result = aggregate_raster_to_grid(tif_path, grid_spec)

    # NaN を含まないブロック: 正確な平均値。
    assert result[0, 0] == pytest.approx(3.5, abs=0.5)
    assert result[0, 1] == pytest.approx(5.5, abs=0.5)
    assert result[1, 0] == pytest.approx(11.5, abs=0.5)
    # NaN を1ピクセル含むブロック: NaN ではなく有効値の平均。
    assert not np.isnan(result[1, 1])
    assert result[1, 1] == pytest.approx((11.0 + 12.0 + 15.0) / 3, abs=1.0)


def test_aggregate_raster_all_nan_cell_stays_nan(tmp_path: Path) -> None:
    """全ピクセルがNaNのブロックはNaNのまま残る。"""
    data = np.full((4, 4), np.nan, dtype=np.float32)
    data[0, 0] = 5.0
    tif_path = tmp_path / "all_nan.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, data, transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    result = aggregate_raster_to_grid(tif_path, grid_spec)

    assert not np.isnan(result[0, 0])
    assert np.isnan(result[0, 1])
    assert np.isnan(result[1, 1])


# GDALの補助メタデータ（PAM）。GeoTIFF本体はデータセット全体で1つのnodata
# （``TIFFTAG_GDAL_NODATA``）しか保持できないため、バンド別のnodataはサイドカー
# ファイル（``*.tif.aux.xml``）に記録する。GDALのPython バインディング（osgeo）は
# CI環境に無いため、rasterioのみで完結する本方式を用いる。
_PER_BAND_NODATA_PAM = """<PAMDataset>
  <PAMRasterBand band="1">
    <NoDataValue>-1</NoDataValue>
  </PAMRasterBand>
  <PAMRasterBand band="2">
    <NoDataValue>-9999</NoDataValue>
  </PAMRasterBand>
</PAMDataset>
"""


def _write_per_band_nodata_raster(path: Path) -> None:
    """バンドごとに異なるnodataを持つ2バンドラスタを書き出す。

    バンド1: nodata=-1、全画素が -1（＝全画素無効）。
    バンド2: nodata=-9999、左上1画素のみ -1（実値として有効）、残りは 10.0。

    Args:
        path: 出力先のGeoTIFFパス（サイドカーは ``<path>.aux.xml``）。
    """
    band2_values = np.full((4, 4), 10.0, dtype=np.float32)
    band2_values[0, 0] = -1.0

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=2,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 40, 10, 10),
    ) as dst:
        dst.write(np.full((4, 4), -1.0, dtype=np.float32), 1)
        dst.write(band2_values, 2)

    path.with_name(f"{path.name}.aux.xml").write_text(_PER_BAND_NODATA_PAM, encoding="utf-8")


def test_aggregate_uses_nodata_of_target_band(tmp_path: Path) -> None:
    """nodataは対象バンドの値を使う（バンド1の値で判定しない）。

    ``src.nodata`` はバンド1のnodataを返すため、それを使うとバンド2の集約で
    バンド1のnodata（-1）を無効値とみなし、実値の -1 を欠損として捨ててしまう。
    複数バンドを1ファイルに持つラスタで起こり得る。
    """
    raster_path = tmp_path / "per_band_nodata.tif"
    _write_per_band_nodata_raster(raster_path)

    # バンド別nodataが読めない環境（PAM無効）では前提が成立しないため検証しない。
    with rasterio.open(raster_path) as src:
        if src.nodatavals != (-1.0, -9999.0):
            pytest.skip("GDALのPAMサイドカーが無効でバンド別nodataを再現できない")

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    mean = aggregate_raster_to_grid(raster_path, grid_spec, band_index=2)
    valid_ratio = aggregate_valid_ratio_to_grid(raster_path, grid_spec, band_index=2)

    # バンド2の -1 は実値であり、平均に含まれる（バンド1のnodataで判定すると
    # 除外され、平均は10.0・有効画素率は0.75になる）。
    assert mean[0, 0] == pytest.approx((10.0 * 3 - 1.0) / 4, abs=0.5)
    assert valid_ratio[0, 0] == pytest.approx(1.0, abs=1e-5)


@pytest.mark.parametrize(
    "aggregate_function", [aggregate_raster_to_grid, aggregate_valid_ratio_to_grid]
)
@pytest.mark.parametrize("band_index", [0, 2])
def test_aggregate_rejects_out_of_range_band(
    tmp_path: Path, aggregate_function, band_index: int
) -> None:
    """バンド数を超える指定は、素のIndexErrorではなく日本語のValueErrorになる。"""
    tif_path = tmp_path / "single_band.tif"
    transform = from_origin(0, 40, 10, 10)
    _write_test_raster(tif_path, np.ones((4, 4), dtype=np.float32), transform)

    grid_spec = build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )

    with pytest.raises(ValueError, match="バンド番号"):
        aggregate_function(tif_path, grid_spec, band_index)


# ---------------------------------------------------------------------------
# coarse_grid_bounds / raster_overlaps_grid
# ---------------------------------------------------------------------------


def _grid_spec_0_to_40():
    """解析範囲 0-40m 四方・coarse 20m のグリッド仕様を返す。"""
    return build_grid(
        BBox(0.0, 0.0, 40.0, 40.0), CRS.from_epsg(3857), coarse_res_m=20.0, fine_res_m=10.0
    )


def test_coarse_grid_bounds_returns_full_grid_extent() -> None:
    """coarseグリッド全体の範囲を (minx, miny, maxx, maxy) で返す。"""
    assert coarse_grid_bounds(_grid_spec_0_to_40()) == pytest.approx((0.0, 0.0, 40.0, 40.0))


@pytest.mark.parametrize(
    ("origin_x", "origin_y", "expected", "label"),
    [
        (0.0, 40.0, True, "完全一致"),
        (20.0, 60.0, True, "一部が重なる"),
        (100000.0, 100000.0, False, "遠く離れている"),
        # 右端がグリッド左端にちょうど接するだけ（共有面積ゼロ）は重なりとみなさない。
        (-40.0, 40.0, False, "辺で接するだけ"),
    ],
)
def test_raster_overlaps_grid_judges_by_extent(
    tmp_path: Path, origin_x: float, origin_y: float, expected: bool, label: str
) -> None:
    """ラスタ範囲とグリッド範囲の重なりを、画素値を読まずに判定する。"""
    tif_path = tmp_path / f"overlap_{label}.tif"
    _write_test_raster(
        tif_path, np.ones((4, 4), dtype=np.float32), from_origin(origin_x, origin_y, 10, 10)
    )

    assert raster_overlaps_grid(tif_path, _grid_spec_0_to_40()) is expected


def test_raster_overlaps_grid_handles_geographic_crs(tmp_path: Path) -> None:
    """ラスタが解析CRSと異なる地理座標系でも、範囲を変換して判定する。

    実運用のLST・指標ラスタはEPSG:4326、解析CRSはEPSG:5897であり必ず変換を伴う。
    """
    tif_path = tmp_path / "overlap_wgs84.tif"
    # EPSG:3857 の 0-40m 四方は経緯度の原点近傍にあたる。
    _write_test_raster(
        tif_path,
        np.ones((4, 4), dtype=np.float32),
        from_origin(-0.001, 0.001, 0.0005, 0.0005),
        crs="EPSG:4326",
    )

    assert raster_overlaps_grid(tif_path, _grid_spec_0_to_40()) is True


# ---------------------------------------------------------------------------
# aggregate_mean_and_valid_ratio
# ---------------------------------------------------------------------------


def _write_all_nodata_raster(path: Path, transform: rasterio.Affine) -> None:
    """全画素がnodataのラスタを書き出す。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((4, 4), -9999.0, dtype=np.float32), 1)


def test_aggregate_mean_and_valid_ratio_returns_named_columns(tmp_path: Path) -> None:
    """指定した列名でセル平均値と有効画素率の2列を返す。"""
    tif_path = tmp_path / "pair.tif"
    _write_test_raster(
        tif_path, np.full((4, 4), 12.0, dtype=np.float32), from_origin(0, 40, 10, 10)
    )

    columns = aggregate_mean_and_valid_ratio(
        tif_path, _grid_spec_0_to_40(), 1, "ELEV_MEAN", "ELEV_VALID_RATIO", "DEM"
    )

    assert set(columns) == {"ELEV_MEAN", "ELEV_VALID_RATIO"}
    np.testing.assert_allclose(columns["ELEV_MEAN"], 12.0, rtol=1e-5)
    np.testing.assert_allclose(columns["ELEV_VALID_RATIO"], 1.0, atol=1e-5)


def test_aggregate_mean_and_valid_ratio_distinguishes_all_missing_from_no_overlap(
    tmp_path: Path,
) -> None:
    """重なってはいるが全画素欠測の場合、「重なりません」ではない警告を出す。

    どちらも全セルNaNという同じ結果になるが、対処はまったく異なる。前者は観測の
    選び直し（雲被覆）やnodata値の確認、後者は都市・切り出し範囲の確認である。
    """
    tif_path = tmp_path / "all_nodata_overlapping.tif"
    _write_all_nodata_raster(tif_path, from_origin(0, 40, 10, 10))

    with pytest.warns(UserWarning, match="有効画素が1つもありません") as caught:
        columns = aggregate_mean_and_valid_ratio(
            tif_path, _grid_spec_0_to_40(), 1, "LST", "LST_VALID_RATIO", "LST"
        )

    assert np.isnan(columns["LST"]).all()
    assert not [record for record in caught if "重なりません" in str(record.message)]


def test_aggregate_mean_and_valid_ratio_warns_when_raster_does_not_overlap(
    tmp_path: Path,
) -> None:
    """グリッドと重ならないラスタでは「重なりません」と警告する。"""
    tif_path = tmp_path / "far_away.tif"
    _write_test_raster(
        tif_path, np.full((4, 4), 12.0, dtype=np.float32), from_origin(100000, 100000, 10, 10)
    )

    with pytest.warns(UserWarning, match="重なりません"):
        columns = aggregate_mean_and_valid_ratio(
            tif_path, _grid_spec_0_to_40(), 1, "LST", "LST_VALID_RATIO", "LST"
        )

    assert np.isnan(columns["LST"]).all()


def test_aggregate_mean_and_valid_ratio_does_not_warn_for_normal_input(tmp_path: Path) -> None:
    """有効値があるラスタでは警告しない（重なり判定のためにラスタを開き直さない）。"""
    tif_path = tmp_path / "normal.tif"
    _write_test_raster(
        tif_path, np.full((4, 4), 12.0, dtype=np.float32), from_origin(0, 40, 10, 10)
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        aggregate_mean_and_valid_ratio(
            tif_path, _grid_spec_0_to_40(), 1, "ELEV_MEAN", "ELEV_VALID_RATIO", "DEM"
        )

    assert not [record for record in caught if "全セルNaN" in str(record.message)]


def _write_described_raster(path: Path, descriptions: tuple[str | None, ...]) -> None:
    """バンド説明を指定した多バンドラスタを書き出す。

    Args:
        path: 出力先のGeoTIFFパス。
        descriptions: バンドごとの説明。``None`` を含めると未設定バンドを作れる。
    """
    band_count = len(descriptions)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=band_count,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 20, 10, 10),
    ) as dst:
        for band_index in range(1, band_count + 1):
            dst.write(np.full((2, 2), float(band_index), dtype=np.float32), band_index)
        dst.descriptions = descriptions


def test_warn_if_band_description_unexpected_warns_on_mismatch(tmp_path: Path) -> None:
    """期待するキーワードを含まないバンド説明では警告する。"""
    raster_path = tmp_path / "described.tif"
    _write_described_raster(raster_path, ("population_count", "population_density_per_km2"))

    with pytest.warns(UserWarning, match="バンド番号の取り違え"):
        warn_if_band_description_unexpected(raster_path, 1, "density", "人口")


def test_warn_if_band_description_unexpected_accepts_matching_band(tmp_path: Path) -> None:
    """期待するキーワードを含むバンド説明では警告しない。"""
    raster_path = tmp_path / "described_ok.tif"
    _write_described_raster(raster_path, ("population_count", "population_density_per_km2"))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_if_band_description_unexpected(raster_path, 2, "density", "人口")

    assert not [record for record in caught if "バンド番号の取り違え" in str(record.message)]


def test_warn_if_band_description_unexpected_ignores_case(tmp_path: Path) -> None:
    """バンド説明の照合は大文字小文字を区別しない。

    説明の表記はデータ提供元・取得スクリプトによって揺れるため、大小の違いだけで
    警告が出ると、正常な入力まで警告に埋もれる。
    """
    raster_path = tmp_path / "described_upper.tif"
    _write_described_raster(raster_path, ("Population_DENSITY_per_km2",))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_if_band_description_unexpected(raster_path, 1, "density", "人口")

    assert not [record for record in caught if "バンド番号の取り違え" in str(record.message)]


def test_warn_if_band_description_unexpected_skips_raster_without_descriptions(
    tmp_path: Path,
) -> None:
    """バンド説明を持たないラスタでは何もしない。

    説明は任意のメタデータであり、無いことを異常として扱うと正常な入力まで
    警告で埋まる。照合は「説明があり、かつ期待と食い違う」場合に限る。
    """
    raster_path = tmp_path / "undescribed.tif"
    _write_test_raster(raster_path, np.ones((2, 2), dtype=np.float32), from_origin(0, 20, 10, 10))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_if_band_description_unexpected(raster_path, 1, "density", "人口")

    assert not [record for record in caught if "バンド番号の取り違え" in str(record.message)]


def test_warn_if_band_description_unexpected_rejects_out_of_range_band(tmp_path: Path) -> None:
    """範囲外のバンド番号は、素のIndexErrorではなくValueErrorで弾く。"""
    raster_path = tmp_path / "described_range.tif"
    _write_described_raster(raster_path, ("population_density_per_km2",))

    with pytest.raises(ValueError, match="バンド番号が範囲外です"):
        warn_if_band_description_unexpected(raster_path, 3, "density", "人口")
