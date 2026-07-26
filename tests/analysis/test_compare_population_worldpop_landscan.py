"""compare_population_worldpop_landscan.py（人口データセット比較）のテスト。

集約が総人口を保存すること・一致度統計の性質・2バンド前提の検証を対象とする。
ラスタ入出力は合成した小さな GeoTIFF で確認する。
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.analysis import compare_population_worldpop_landscan as target

# 細かい側（WorldPop 相当）と粗い側（LandScan 相当）の刻み。実データと同じ 10 倍差にする。
FINE_PIXEL_DEG = 1.0 / 1200.0
COARSE_PIXEL_DEG = 1.0 / 120.0


class TestAggregateCountsToReferenceGrid:
    """aggregate_counts_to_reference_grid のテスト。"""

    def test_preserves_total_population(self) -> None:
        """集約の前後で総人口が保存される（合計保存量としての要件）。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        rng = np.random.default_rng(seed=42)
        fine_counts = rng.uniform(0.0, 100.0, size=(30, 30)).astype(np.float32)

        aggregated, contributing = target.aggregate_counts_to_reference_grid(
            fine_counts, fine_transform, coarse_transform, (3, 3)
        )

        assert aggregated.sum() == pytest.approx(float(fine_counts.sum()), rel=1e-6)
        assert contributing.sum() == fine_counts.size

    def test_assigns_each_fine_pixel_to_exactly_one_cell(self) -> None:
        """1 つの細かい画素は 1 つの粗いセルにのみ寄与する。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_counts = np.ones((20, 20), dtype=np.float32)

        _, contributing = target.aggregate_counts_to_reference_grid(
            fine_counts, fine_transform, coarse_transform, (2, 2)
        )

        # 10x10 の細かい画素がちょうど 1 つの粗いセルに入る
        assert contributing.tolist() == [[100, 100], [100, 100]]

    def test_excludes_nodata_pixels_from_aggregation(self) -> None:
        """nodata 画素は加算にも寄与画素数にも数えない。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_counts = np.full((10, 10), 5.0, dtype=np.float32)
        fine_counts[0, 0] = target.NODATA

        aggregated, contributing = target.aggregate_counts_to_reference_grid(
            fine_counts, fine_transform, coarse_transform, (1, 1)
        )

        assert aggregated[0, 0] == pytest.approx(99 * 5.0)
        assert contributing[0, 0] == 99

    def test_ignores_pixels_outside_reference_grid(self) -> None:
        """基準グリッドの外へ出る画素は無視する（範囲外への書き込みをしない）。"""
        # 基準グリッドの西側にはみ出す位置にソースを置く
        fine_transform = from_origin(104.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_counts = np.ones((10, 10), dtype=np.float32)

        aggregated, contributing = target.aggregate_counts_to_reference_grid(
            fine_counts, fine_transform, coarse_transform, (2, 2)
        )

        assert aggregated.sum() == 0.0
        assert contributing.sum() == 0

    def test_rejects_non_2d_source(self) -> None:
        """3 次元配列（バンド軸つき）を渡した場合は例外にする。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)

        with pytest.raises(ValueError, match="2 次元"):
            target.aggregate_counts_to_reference_grid(
                np.ones((1, 10, 10), dtype=np.float32), fine_transform, coarse_transform, (1, 1)
            )


class TestBuildPairedStatistics:
    """build_paired_statistics のテスト。"""

    def test_identical_series_have_perfect_correlation_and_no_error(self) -> None:
        """完全一致なら相関 1・誤差 0 になる。"""
        values = np.array([1.0, 5.0, 10.0, 50.0, 100.0])

        result = target.build_paired_statistics(values, values)

        assert result["pearson_r"] == pytest.approx(1.0)
        assert result["spearman_rho"] == pytest.approx(1.0)
        assert result["root_mean_squared_error"] == pytest.approx(0.0)
        assert result["mean_bias"] == pytest.approx(0.0)

    def test_bias_sign_follows_comparison_minus_reference(self) -> None:
        """バイアスは「比較側 − 基準側」の符号になる。"""
        reference = np.array([10.0, 20.0, 30.0])
        comparison = reference + 5.0

        result = target.build_paired_statistics(reference, comparison)

        assert result["mean_bias"] == pytest.approx(5.0)
        assert result["median_bias"] == pytest.approx(5.0)
        assert result["mean_absolute_error"] == pytest.approx(5.0)

    def test_returns_cell_count_only_for_empty_input(self) -> None:
        """比較対象セルが無い場合は件数だけを返す（相関を計算しない）。"""
        empty = np.array([], dtype=np.float64)

        result = target.build_paired_statistics(empty, empty)

        assert result == {"cell_count": 0}

    def test_rejects_length_mismatch(self) -> None:
        """長さの異なる系列はセルの対応が崩れているため例外にする。"""
        with pytest.raises(ValueError, match="要素数が一致しません"):
            target.build_paired_statistics(np.array([1.0, 2.0]), np.array([1.0]))


def _write_population_raster(
    path: Path,
    counts: np.ndarray,
    densities: np.ndarray,
    transform: object,
) -> None:
    """テスト用の 2 バンド人口ラスタを書き出す。"""
    profile = {
        "driver": "GTiff",
        "height": counts.shape[0],
        "width": counts.shape[1],
        "count": 2,
        "dtype": "float32",
        "crs": CRS.from_epsg(4326),
        "transform": transform,
        "nodata": target.NODATA,
    }
    with rasterio.open(path, "w", **profile) as destination:
        destination.write(counts.astype(np.float32), 1)
        destination.write(densities.astype(np.float32), 2)


class TestLoadPopulationRaster:
    """load_population_raster のテスト。"""

    def test_reads_both_bands(self, tmp_path: Path) -> None:
        """カウントと密度の両バンドを読み出す。"""
        raster_path = tmp_path / "pop.tif"
        counts = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        densities = counts * 10.0
        _write_population_raster(
            raster_path, counts, densities, from_origin(105.0, 21.0, 0.01, 0.01)
        )

        raster = target.load_population_raster(raster_path)

        assert raster["counts"].tolist() == counts.tolist()
        assert raster["densities"].tolist() == densities.tolist()
        assert raster["shape"] == (2, 2)

    def test_rejects_single_band_raster(self, tmp_path: Path) -> None:
        """単バンドのラスタは密度バンドを持たないため弾く。"""
        raster_path = tmp_path / "single.tif"
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 1,
            "dtype": "float32",
            "crs": CRS.from_epsg(4326),
            "transform": from_origin(105.0, 21.0, 0.01, 0.01),
            "nodata": target.NODATA,
        }
        with rasterio.open(raster_path, "w", **profile) as destination:
            destination.write(np.ones((2, 2), dtype=np.float32), 1)

        with pytest.raises(ValueError, match="2 バンド"):
            target.load_population_raster(raster_path)


class TestSummarizeDataset:
    """summarize_dataset のテスト。"""

    def test_excludes_nodata_from_totals(self, tmp_path: Path) -> None:
        """nodata 画素は総人口・有効面積のどちらにも数えない。"""
        raster_path = tmp_path / "pop.tif"
        counts = np.array([[10.0, 20.0], [target.NODATA, 40.0]], dtype=np.float32)
        _write_population_raster(
            raster_path,
            counts,
            counts,
            from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG),
        )
        raster = target.load_population_raster(raster_path)
        roi_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0 - 2 * COARSE_PIXEL_DEG, 105.0 + 2 * COARSE_PIXEL_DEG, 21.0)],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(raster, roi_gdf)

        summary = target.summarize_dataset(raster, roi_mask)

        assert summary["total_population"] == pytest.approx(70.0)
        assert summary["valid_cells"] == 3
        # 有効面積は 3 セル分。平均密度は総人口 ÷ 有効面積と整合する
        assert summary["mean_density_per_km2"] == pytest.approx(
            summary["total_population"] / summary["total_area_km2"]
        )
