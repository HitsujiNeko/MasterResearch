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

    def test_allows_identical_grids(self) -> None:
        """同一グリッド（比 1.0）は 1 画素として許容する。"""
        transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)

        assert target.expected_source_pixels_per_cell(transform, transform) == 1

    def test_rejects_reference_grid_finer_than_source(self) -> None:
        """引数を逆に渡した場合（基準が細かい）は弾く。

        以前は max(1, ...) で 1 に丸めており、各セルが 0〜1 画素でも「完全被覆」と
        判定され、結果が無意味なまま JSON に残る状態だった。
        """
        source_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        reference_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)

        with pytest.raises(ValueError, match="同等以上に粗い"):
            target.expected_source_pixels_per_cell(source_transform, reference_transform)

    def test_rejects_zero_sized_source_cells(self) -> None:
        """ソースのセル寸法が 0 なら例外にする。"""
        with pytest.raises(ValueError, match="セル寸法"):
            target.expected_source_pixels_per_cell(
                Affine(0.0, 0.0, 105.0, 0.0, -COARSE_PIXEL_DEG, 21.0),
                from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG),
            )


class TestBuildContributingPixelSummary:
    """build_contributing_pixel_summary のテスト。"""

    def test_returns_none_for_empty_input(self) -> None:
        """比較対象セルが 0 件でも np.min/np.max でクラッシュしない。"""
        assert target.build_contributing_pixel_summary(np.array([], dtype=np.int64)) is None

    def test_summarizes_min_max_median(self) -> None:
        """寄与画素数の min / max / median を返す。"""
        result = target.build_contributing_pixel_summary(np.array([11, 100, 100, 50]))

        assert result == {"min": 11, "max": 100, "median": 75.0}


# `build_paired_statistics` は src/common/paired_stats.py へ移設したため、
# 単体の検証は tests/common/test_paired_stats.py が持つ。ここでは本スクリプト
# 固有の使い方（集約後のカウント・密度の一致度）だけを見る。


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
        # CRS を落とすと後段の build_roi_mask が誤った位置でマスクを作る
        assert raster["crs"].to_epsg() == 4326

    def test_reads_non_square_raster_with_correct_shape(self, tmp_path: Path) -> None:
        """行数と列数が異なるラスタでも (行, 列) の順で保持する。"""
        raster_path = tmp_path / "non_square.tif"
        counts = np.arange(6, dtype=np.float32).reshape(2, 3)
        _write_population_raster(raster_path, counts, counts, from_origin(105.0, 21.0, 0.01, 0.01))

        raster = target.load_population_raster(raster_path)

        assert raster["shape"] == (2, 3)
        assert raster["counts"].shape == (2, 3)

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

    def test_rejects_projected_crs(self, tmp_path: Path) -> None:
        """投影座標系のラスタは、度前提のセル面積計算が破綻するため弾く。"""
        raster_path = tmp_path / "projected.tif"
        counts = np.ones((2, 2), dtype=np.float32)
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 2,
            "dtype": "float32",
            "crs": CRS.from_epsg(32648),  # UTM Zone 48N（メートル単位）
            "transform": from_origin(580000.0, 2330000.0, 100.0, 100.0),
            "nodata": target.NODATA,
        }
        with rasterio.open(raster_path, "w", **profile) as destination:
            destination.write(counts, 1)
            destination.write(counts, 2)

        with pytest.raises(ValueError, match="地理座標系"):
            target.load_population_raster(raster_path)

    def test_rejects_missing_crs(self, tmp_path: Path) -> None:
        """CRS が未定義のラスタは位置が確定しないため弾く。"""
        raster_path = tmp_path / "no_crs.tif"
        counts = np.ones((2, 2), dtype=np.float32)
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 2,
            "dtype": "float32",
            "crs": None,
            "transform": from_origin(105.0, 21.0, 0.01, 0.01),
            "nodata": target.NODATA,
        }
        with rasterio.open(raster_path, "w", **profile) as destination:
            destination.write(counts, 1)
            destination.write(counts, 2)

        with pytest.raises(ValueError, match="CRS が未定義"):
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

    def test_handles_non_square_raster(self, tmp_path: Path) -> None:
        """行数と列数が異なる場合も、セル面積のブロードキャストが破綻しない。"""
        raster_path = tmp_path / "non_square.tif"
        counts = np.full((2, 3), 10.0, dtype=np.float32)
        _write_population_raster(
            raster_path,
            counts,
            counts,
            from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG),
        )
        raster = target.load_population_raster(raster_path)
        roi_gdf = gpd.GeoDataFrame(
            geometry=[
                box(
                    105.0,
                    21.0 - 2 * COARSE_PIXEL_DEG,
                    105.0 + 3 * COARSE_PIXEL_DEG,
                    21.0,
                )
            ],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(raster, roi_gdf)

        summary = target.summarize_dataset(raster, roi_mask)

        assert summary["valid_cells"] == 6
        assert summary["total_population"] == pytest.approx(60.0)
        # 6 セル分の面積が積み上がっていること（行数と列数を取り違えていたら合わない）
        assert summary["total_area_km2"] > 0
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

    def test_survives_roi_with_no_overlapping_source_pixels(self, tmp_path: Path) -> None:
        """ROI と WorldPop 有効画素が重ならなくてもクラッシュしない。"""
        # 基準グリッドを 4x4 にし、細かい側は左上 3x3 セル分しか覆わないようにする
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        fine_counts = np.ones((30, 30), dtype=np.float32)
        coarse_counts = np.full((4, 4), 100.0, dtype=np.float32)

        fine_path = tmp_path / "fine_partial.tif"
        coarse_path = tmp_path / "coarse_wide.tif"
        _write_population_raster(fine_path, fine_counts, fine_counts, fine_transform)
        _write_population_raster(coarse_path, coarse_counts, coarse_counts, coarse_transform)
        fine = target.load_population_raster(fine_path)
        coarse = target.load_population_raster(coarse_path)

        # 細かい側が届かない 4 列目・4 行目のセルだけを ROI にする
        far_roi = gpd.GeoDataFrame(
            geometry=[
                box(
                    105.0 + 3 * COARSE_PIXEL_DEG,
                    21.0 - 4 * COARSE_PIXEL_DEG,
                    105.0 + 4 * COARSE_PIXEL_DEG,
                    21.0 - 3 * COARSE_PIXEL_DEG,
                )
            ],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(coarse, far_roi)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        assert result["roi_cells"] > 0
        assert result["comparable_cells"] == 0
        assert result["contributing_pixels_per_cell"] is None
        assert result["count_agreement"] == {"cell_count": 0}

    def test_handles_partially_covered_cells_only(self, tmp_path: Path) -> None:
        """全セルが部分被覆でも完全被覆側の統計が壊れない（空入力のガード）。"""
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        # 1 セルを埋めるには 10x10 必要なところへ 5x5 しか置かない
        fine_counts = np.ones((5, 5), dtype=np.float32)
        coarse_counts = np.full((1, 1), 100.0, dtype=np.float32)

        fine_path = tmp_path / "fine_partial_only.tif"
        coarse_path = tmp_path / "coarse_single.tif"
        _write_population_raster(fine_path, fine_counts, fine_counts, fine_transform)
        _write_population_raster(coarse_path, coarse_counts, coarse_counts, coarse_transform)
        fine = target.load_population_raster(fine_path)
        coarse = target.load_population_raster(coarse_path)

        roi_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0 - COARSE_PIXEL_DEG, 105.0 + COARSE_PIXEL_DEG, 21.0)],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(coarse, roi_gdf)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        assert result["comparable_cells"] == 1
        assert result["fully_covered_cells"] == 0
        assert result["partially_covered_cells"] == 1
        assert result["contributing_pixels_per_cell"]["max"] == 25
        # 完全被覆セルが 0 件でも統計側が例外にならないこと
        assert result["count_agreement_fully_covered_cells"] == {"cell_count": 0}

    def test_reference_grid_totals_use_the_same_cell_set(self, tmp_path: Path) -> None:
        """基準グリッド合計の分子と分母が同一セル集合になっている。

        片方だけ別条件で絞ると比の母数がずれるため、LandScan 側に nodata を混ぜて
        両者が同じセルだけを数えていることを確かめる。
        """
        coarse_transform = from_origin(105.0, 21.0, COARSE_PIXEL_DEG, COARSE_PIXEL_DEG)
        fine_transform = from_origin(105.0, 21.0, FINE_PIXEL_DEG, FINE_PIXEL_DEG)
        fine_counts = np.ones((20, 20), dtype=np.float32)  # 2x2 セル分を満たす
        coarse_counts = np.full((2, 2), 100.0, dtype=np.float32)
        coarse_counts[0, 1] = target.NODATA  # LandScan 側だけ欠測のセルを作る

        fine_path = tmp_path / "fine_full.tif"
        coarse_path = tmp_path / "coarse_with_nodata.tif"
        _write_population_raster(fine_path, fine_counts, fine_counts, fine_transform)
        _write_population_raster(coarse_path, coarse_counts, coarse_counts, coarse_transform)
        fine = target.load_population_raster(fine_path)
        coarse = target.load_population_raster(coarse_path)

        roi_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0 - 2 * COARSE_PIXEL_DEG, 105.0 + 2 * COARSE_PIXEL_DEG, 21.0)],
            crs="EPSG:4326",
        )
        roi_mask = target.build_roi_mask(coarse, roi_gdf)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        totals = result["total_population_on_reference_grid"]
        # LandScan が欠測のセルは双方から除かれる: WorldPop は 3 セル分(=300)、
        # LandScan も 3 セル分(=300)。除外が片側だけなら WorldPop は 400 になる
        assert result["comparable_cells"] == 3
        assert totals["worldpop"] == pytest.approx(300.0)
        assert totals["landscan"] == pytest.approx(300.0)

    def test_rejects_rasters_with_different_crs(self, tmp_path: Path) -> None:
        """CRS が異なるラスタ同士は、座標の対応付けが無意味になるため弾く。"""
        fine, coarse, roi_mask = self._build_rasters(tmp_path)
        # 集約は座標値をそのまま基準グリッドへ代入するため、CRS 不一致は静かに壊れる
        coarse["crs"] = CRS.from_epsg(4269)  # NAD83（同じ度単位だが別の CRS）

        with pytest.raises(ValueError, match="CRS が一致しません"):
            target.compare_on_reference_grid(fine, coarse, roi_mask)

    def test_result_is_json_serializable_without_nan(self, tmp_path: Path) -> None:
        """比較結果をそのまま save_summary に渡しても NaN ガードに掛からない。"""
        import json

        fine, coarse, roi_mask = self._build_rasters(tmp_path)

        result = target.compare_on_reference_grid(fine, coarse, roi_mask)

        json.dumps(result, ensure_ascii=False, allow_nan=False)
