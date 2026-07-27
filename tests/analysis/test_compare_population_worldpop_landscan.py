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
from affine import Affine
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

    def test_ignores_pixels_beyond_east_and_south_edges(self) -> None:
        """基準グリッドの東・南（インデックス上限側）へ出る画素も無視する。"""
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        # 基準グリッドは 1x1 セル。その南東隣のセルにあたる位置へソースを置く
        fine_transform = from_origin(
            105.0 + COARSE_PIXEL_DEG, 21.0 - COARSE_PIXEL_DEG, FINE_PIXEL_DEG, FINE_PIXEL_DEG
        )
        fine_counts = np.ones((10, 10), dtype=np.float32)

        aggregated, contributing = target.aggregate_counts_to_reference_grid(
            fine_counts, fine_transform, coarse_transform, (1, 1)
        )

        assert aggregated.sum() == 0.0
        assert contributing.sum() == 0

    def test_rejects_rotated_transform(self) -> None:
        """回転・スキューのあるグリッドは行列インデックス計算が破綻するため弾く。"""
        rotated = Affine(FINE_PIXEL_DEG, 0.0001, 105.0, 0.0001, -FINE_PIXEL_DEG, 21.0)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)

        with pytest.raises(ValueError, match="回転・スキュー"):
            target.aggregate_counts_to_reference_grid(
                np.ones((10, 10), dtype=np.float32), rotated, coarse_transform, (1, 1)
            )

    def test_rejects_non_2d_source(self) -> None:
        """3 次元配列（バンド軸つき）を渡した場合は例外にする。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)

        with pytest.raises(ValueError, match="2 次元"):
            target.aggregate_counts_to_reference_grid(
                np.ones((1, 10, 10), dtype=np.float32), fine_transform, coarse_transform, (1, 1)
            )


class TestExpectedSourcePixelsPerCell:
    """expected_source_pixels_per_cell のテスト。"""

    def test_returns_ratio_of_cell_areas(self) -> None:
        """10倍解像度差なら 1 セルあたり 100 画素になる。"""
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)

        assert target.expected_source_pixels_per_cell(fine_transform, coarse_transform) == 100

    def test_tolerates_non_integer_grid_ratio(self) -> None:
        """刻みが厳密な整数倍でなくても最も近い整数を返す（実データは微小にずれる）。"""
        fine_transform = from_origin(105.0, 21.0, 0.0008333333299579025, 0.0008333333300179816)
        coarse_transform = from_origin(105.0, 21.0, 0.008333333333, 0.008333333333)

        assert target.expected_source_pixels_per_cell(fine_transform, coarse_transform) == 100

    def test_never_returns_zero(self) -> None:
        """ソースが基準より粗い場合でも 1 以上を返す（除算の破綻を避ける）。"""
        fine_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        coarse_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)

        assert target.expected_source_pixels_per_cell(fine_transform, coarse_transform) == 1

    def test_rejects_zero_sized_source_cells(self) -> None:
        """ソースのセル寸法が 0 なら例外にする。"""
        with pytest.raises(ValueError, match="セル寸法"):
            target.expected_source_pixels_per_cell(
                Affine(0.0, 0.0, 105.0, 0.0, -COARSE_PIXEL_DEG, 21.0),
                from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG),
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

    def test_single_cell_returns_none_correlation_instead_of_raising(self) -> None:
        """1 件では相関を定義できないため、例外や nan ではなく None を返す。"""
        result = target.build_paired_statistics(np.array([10.0]), np.array([12.0]))

        assert result["cell_count"] == 1
        assert result["pearson_r"] is None
        assert result["spearman_rho"] is None
        assert "1 件" in result["correlation_note"]
        # 誤差系の統計は 1 件でも意味があるため計算する
        assert result["mean_bias"] == pytest.approx(2.0)

    def test_constant_series_returns_none_correlation_instead_of_nan(self) -> None:
        """定数系列では相関が nan になるため None に統一する（JSON へ nan を書かない）。"""
        result = target.build_paired_statistics(
            np.array([5.0, 5.0, 5.0]), np.array([1.0, 2.0, 3.0])
        )

        assert result["pearson_r"] is None
        assert result["spearman_rho"] is None
        assert "定数" in result["correlation_note"]

    def test_statistics_contain_no_nan(self) -> None:
        """どの経路でも nan を含む値を返さない（save_summary の NaN ガードに掛からないこと）。"""
        for reference, comparison in (
            (np.array([1.0]), np.array([2.0])),
            (np.array([5.0, 5.0]), np.array([5.0, 5.0])),
            (np.array([1.0, 2.0, 3.0]), np.array([2.0, 4.0, 6.0])),
        ):
            result = target.build_paired_statistics(reference, comparison)
            numeric_values = [v for v in result.values() if isinstance(v, float)]
            assert not any(np.isnan(value) for value in numeric_values)


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


class TestCompareOnReferenceGrid:
    """compare_on_reference_grid の end-to-end テスト。"""

    @staticmethod
    def _build_rasters(tmp_path: Path) -> tuple[dict, dict, np.ndarray]:
        """細かい側・粗い側のラスタと ROI マスクを作る。

        粗い側は 3x3 セル。ROI は中央寄りの 2x2 セルだけを覆う。
        """
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)

        rng = np.random.default_rng(seed=7)
        fine_counts = rng.uniform(1.0, 50.0, size=(30, 30)).astype(np.float32)
        coarse_counts = rng.uniform(100.0, 5000.0, size=(3, 3)).astype(np.float32)

        fine_path = tmp_path / "fine.tif"
        coarse_path = tmp_path / "coarse.tif"
        _write_population_raster(fine_path, fine_counts, fine_counts * 10.0, fine_transform)
        _write_population_raster(coarse_path, coarse_counts, coarse_counts * 2.0, coarse_transform)

        fine = target.load_population_raster(fine_path)
        coarse = target.load_population_raster(coarse_path)

        roi_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0 - 2 * COARSE_PIXEL_DEG, 105.0 + 2 * COARSE_PIXEL_DEG, 21.0)],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(coarse, roi_gdf)
        return fine, coarse, roi_mask

    def test_reports_consistent_cell_counts(self, tmp_path: Path) -> None:
        """比較可能セル数と、完全被覆・部分被覆の内訳が整合する。"""
        fine, coarse, roi_mask = self._build_rasters(tmp_path)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        assert result["roi_cells"] == 4
        assert result["comparable_cells"] == 4
        assert result["expected_source_pixels_per_cell"] == 100
        assert result["fully_covered_cells"] + result["partially_covered_cells"] == 4
        assert result["count_agreement"]["cell_count"] == result["comparable_cells"]

    def test_reference_grid_total_excludes_cells_outside_roi(self, tmp_path: Path) -> None:
        """基準グリッド基準の合計は、ROI 外のセルへ落ちた画素を含まない。"""
        fine, coarse, roi_mask = self._build_rasters(tmp_path)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        totals = result["total_population_on_reference_grid"]
        fine_total_everywhere = float(np.sum(fine["counts"], dtype=np.float64))
        # ROI は 3x3 セル中 2x2 しか覆わないため、必ず自グリッド合計より小さくなる
        assert totals["worldpop"] < fine_total_everywhere
        assert totals["worldpop"] > 0

    def test_result_is_json_serializable_without_nan(self, tmp_path: Path) -> None:
        """比較結果をそのまま save_summary に渡しても NaN ガードに掛からない。"""
        import json

        fine, coarse, roi_mask = self._build_rasters(tmp_path)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        json.dumps(result, ensure_ascii=False, allow_nan=False)
