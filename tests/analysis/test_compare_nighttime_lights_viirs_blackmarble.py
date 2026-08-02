"""compare_nighttime_lights_viirs_blackmarble.py（夜間光の比較スクリプト）のテスト。

実データ（Git 管理外の GeoTIFF・ROI）に依存させないため、小さな合成ラスタと
ROI を一時ディレクトリへ書き出して検証する。**グリッド原点の半画素ずれ**は本
スクリプトの中心的な前提なので、ずれたグリッドを明示的に作って確かめる。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from shapely.geometry import box

from src.analysis import compare_nighttime_lights_viirs_blackmarble as target

# 合成ラスタの格子。実データ（15 arc-sec）より粗いが、半画素ずれの検証には十分。
PIXEL_SIZE_DEG = 0.01
GRID_SHAPE = (4, 4)
REFERENCE_ORIGIN = (105.0, 21.0)
# 基準グリッドから半画素ずらした原点（実データの VIIRS / Black Marble の関係を模す）
SHIFTED_ORIGIN = (105.0 + PIXEL_SIZE_DEG / 2, 21.0 + PIXEL_SIZE_DEG / 2)


def _write_raster(
    path: Path,
    values: np.ndarray,
    origin: tuple[float, float] = REFERENCE_ORIGIN,
    band_names: tuple[str, ...] = ("avg_radiance",),
    crs: str = "EPSG:4326",
) -> Path:
    """テスト用の GeoTIFF を書き出す。

    Args:
        path: 出力パス。
        values: 2 次元（単バンド）または 3 次元（バンド, 行, 列）の配列。
        origin: 左上（北西）の座標。
        band_names: 各バンドの説明。
        crs: CRS。

    Returns:
        書き出したパス。
    """
    band_arrays = values[np.newaxis, :, :] if values.ndim == 2 else values
    count, height, width = band_arrays.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype="float32",
        crs=crs,
        transform=from_origin(origin[0], origin[1], PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
        nodata=target.NODATA,
    ) as destination:
        for index in range(count):
            destination.write(band_arrays[index].astype(np.float32), index + 1)
            destination.set_band_description(index + 1, band_names[index])
    return path


def _write_roi(path: Path, bounds: tuple[float, float, float, float]) -> Path:
    """テスト用の ROI Shapefile を書き出す。

    Args:
        path: 出力パス。
        bounds: (minx, miny, maxx, maxy)。

    Returns:
        書き出したパス。
    """
    gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326").to_file(path)
    return path


def _gradient(shape: tuple[int, int] = GRID_SHAPE) -> np.ndarray:
    """行列位置に応じて増える配列を作る（定数列にせず相関を定義可能にする）。"""
    rows, columns = shape
    return np.arange(rows * columns, dtype=np.float64).reshape(rows, columns) + 1.0


class TestResolveSummaryPath:
    """resolve_summary_path のテスト。"""

    def test_builds_default_path_from_year(self) -> None:
        """既定では年つきのファイル名になる。"""
        path = target.resolve_summary_path(2023, None)

        assert path.name == "nighttime_lights_viirs_blackmarble_hanoi_2023_summary.json"
        assert path.parent.name == "open_gis"

    def test_uses_explicit_path(self, tmp_path: Path) -> None:
        """明示指定があればそちらを使う。"""
        explicit = tmp_path / "custom.json"

        assert target.resolve_summary_path(2023, explicit) == explicit


class TestResolveInputPaths:
    """resolve_input_paths のテスト。"""

    def test_derives_input_paths_from_year(self) -> None:
        """未指定の入力パスは `--year` から解決する。

        年が出力名にしか効かないと、2023 年のデータから 2022 年と記録した
        サマリーを例外なく作れてしまう。
        """
        viirs_path, black_marble_path = target.resolve_input_paths(2022, None, None)

        assert viirs_path.name == "viirs_dnb_hanoi_2022.tif"
        assert black_marble_path.name == "black_marble_vnp46a4_hanoi_2022.tif"

    def test_different_years_resolve_to_different_inputs(self) -> None:
        """年が変われば入力ファイルも変わる。"""
        paths_2022 = target.resolve_input_paths(2022, None, None)
        paths_2023 = target.resolve_input_paths(2023, None, None)

        assert paths_2022 != paths_2023

    def test_explicit_paths_take_precedence(self, tmp_path: Path) -> None:
        """明示指定があれば年より優先する。"""
        viirs_path, black_marble_path = target.resolve_input_paths(
            2023, tmp_path / "a.tif", tmp_path / "b.tif"
        )

        assert viirs_path == tmp_path / "a.tif"
        assert black_marble_path == tmp_path / "b.tif"


class TestLoadRadianceRaster:
    """load_radiance_raster のテスト。"""

    def test_reads_band_values_and_name(self, tmp_path: Path) -> None:
        """指定バンドの値とバンド名を読み取る。"""
        raster_path = _write_raster(tmp_path / "viirs.tif", _gradient())

        raster = target.load_radiance_raster(raster_path)

        assert raster["band_name"] == "avg_radiance"
        assert raster["shape"] == GRID_SHAPE
        assert raster["values"][0, 0] == pytest.approx(1.0)

    def test_reads_requested_band_of_multiband_raster(self, tmp_path: Path) -> None:
        """多バンドラスタから主バンドだけを取り出す（バンド取り違えの検出）。"""
        stacked = np.stack([_gradient(), _gradient() * 100.0])
        raster_path = _write_raster(
            tmp_path / "multi.tif", stacked, band_names=("ntl_near_nadir", "ntl_all_angle")
        )

        raster = target.load_radiance_raster(raster_path, band=1)

        assert raster["band_name"] == "ntl_near_nadir"
        assert raster["values"][0, 0] == pytest.approx(1.0)

    def test_falls_back_to_band_number_when_description_is_absent(self, tmp_path: Path) -> None:
        """バンド説明が無いラスタでは `band_N` を名前に使う（None を残さない）。"""
        raster_path = tmp_path / "nodesc.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=GRID_SHAPE[0],
            width=GRID_SHAPE[1],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(*REFERENCE_ORIGIN, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
            nodata=target.NODATA,
        ) as destination:
            destination.write(_gradient().astype(np.float32), 1)

        raster = target.load_radiance_raster(raster_path)

        assert raster["band_name"] == "band_1"

    def test_accepts_raster_without_declared_nodata(self, tmp_path: Path) -> None:
        """nodata 未宣言のラスタは、前提どおりとみなして受け入れる。"""
        raster_path = tmp_path / "nonodata.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=GRID_SHAPE[0],
            width=GRID_SHAPE[1],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(*REFERENCE_ORIGIN, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
        ) as destination:
            destination.write(_gradient().astype(np.float32), 1)

        assert target.load_radiance_raster(raster_path)["shape"] == GRID_SHAPE

    def test_rejects_unexpected_nodata_value(self, tmp_path: Path) -> None:
        """宣言された nodata が前提と違えば読み込み時点で弾く。"""
        raster_path = tmp_path / "othernodata.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=GRID_SHAPE[0],
            width=GRID_SHAPE[1],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(*REFERENCE_ORIGIN, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
            nodata=-999.0,
        ) as destination:
            destination.write(_gradient().astype(np.float32), 1)

        with pytest.raises(ValueError, match="想定外の無効値"):
            target.load_radiance_raster(raster_path)

    def test_raises_when_band_is_missing(self, tmp_path: Path) -> None:
        """存在しないバンドを指定したら例外にする。"""
        raster_path = _write_raster(tmp_path / "viirs.tif", _gradient())

        with pytest.raises(ValueError, match="バンド 3 がありません"):
            target.load_radiance_raster(raster_path, band=3)

    def test_rejects_projected_crs(self, tmp_path: Path) -> None:
        """投影座標系のラスタは弾く。

        都心・外縁の切り分けは度前提で距離を測るため、メートル値を度として
        扱うと例外にならないまま誤ったゾーン分けになる。
        """
        raster_path = _write_raster(tmp_path / "projected.tif", _gradient(), crs="EPSG:3857")

        with pytest.raises(ValueError, match="地理座標系"):
            target.load_radiance_raster(raster_path)

    def test_rejects_raster_without_crs(self, tmp_path: Path) -> None:
        """CRS 未定義のラスタは弾く（ROI マスクが別の場所にできるため）。"""
        raster_path = tmp_path / "nocrs.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=GRID_SHAPE[0],
            width=GRID_SHAPE[1],
            count=1,
            dtype="float32",
            transform=from_origin(*REFERENCE_ORIGIN, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
        ) as destination:
            destination.write(_gradient().astype(np.float32), 1)

        with pytest.raises(ValueError, match="CRS が未定義"):
            target.load_radiance_raster(raster_path)


class TestComputeGridOffset:
    """compute_grid_offset のテスト。"""

    def test_detects_half_pixel_offset(self, tmp_path: Path) -> None:
        """半画素ずれたグリッドを 0.5 画素として検出する。"""
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))
        shifted = target.load_radiance_raster(
            _write_raster(tmp_path / "shift.tif", _gradient(), origin=SHIFTED_ORIGIN)
        )

        offset = target.compute_grid_offset(reference, shifted)

        assert offset["longitude_in_pixels"] == pytest.approx(0.5)
        # 緯度方向は transform.e が負のため、北へずれると -0.5 になる
        assert offset["latitude_in_pixels"] == pytest.approx(-0.5)

    def test_reports_zero_for_identical_grids(self, tmp_path: Path) -> None:
        """同一グリッドならずれは 0。"""
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))

        offset = target.compute_grid_offset(reference, reference)

        assert offset["longitude_in_pixels"] == pytest.approx(0.0)
        assert offset["latitude_in_pixels"] == pytest.approx(0.0)


class TestReprojectToReference:
    """reproject_to_reference のテスト。"""

    def test_identical_grid_preserves_values(self, tmp_path: Path) -> None:
        """同一グリッドへの再投影は値を変えない。"""
        values = _gradient()
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", values))
        other = target.load_radiance_raster(_write_raster(tmp_path / "other.tif", values * 2))

        result = target.reproject_to_reference(other, reference, Resampling.nearest)

        assert result == pytest.approx(values * 2)

    def test_result_matches_reference_shape(self, tmp_path: Path) -> None:
        """形状が違うラスタでも、結果は基準グリッドの形状になる。"""
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))
        smaller = target.load_radiance_raster(
            _write_raster(tmp_path / "small.tif", _gradient((3, 3)), origin=SHIFTED_ORIGIN)
        )

        result = target.reproject_to_reference(smaller, reference, Resampling.bilinear)

        assert result.shape == GRID_SHAPE

    def test_half_pixel_shift_averages_neighbouring_values(self, tmp_path: Path) -> None:
        """半画素ずれたグリッドの双一次内挿が、隣接画素の平均になる。

        本スクリプトの主指標は「半画素ずれの補正」そのものなので、内挿が正しい
        向き・重みで行われることを数値で固定する。恒等（同一グリッド）だけの
        検証では、重みが逆向きでも素通りしてしまう。

        比較側の原点を基準グリッドから南東へ半画素ずらすと、基準グリッドの
        画素中心は比較側の 4 画素のちょうど中央に来る。したがって双一次内挿の
        結果はその 4 画素の単純平均になる。
        """
        # 値が行方向・列方向に 1 ずつ増える配列（平均が解析的に求まる）
        values = np.array(
            [[1.0, 2.0, 3.0, 4.0], [2.0, 3.0, 4.0, 5.0], [3.0, 4.0, 5.0, 6.0], [4.0, 5.0, 6.0, 7.0]]
        )
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", np.zeros(GRID_SHAPE))
        )
        shifted = target.load_radiance_raster(
            _write_raster(
                tmp_path / "shift.tif",
                values,
                origin=(
                    REFERENCE_ORIGIN[0] - PIXEL_SIZE_DEG / 2,
                    REFERENCE_ORIGIN[1] + PIXEL_SIZE_DEG / 2,
                ),
            )
        )

        result = target.reproject_to_reference(shifted, reference, Resampling.bilinear)

        # 比較側の原点を北西へ半画素ずらしたので、比較側 (i,j) の画素中心は
        # 経度 105.0 + 0.01j / 緯度 21.0 − 0.01i に来る。基準側 (r,c) の中心は
        # 経度 105.0 + 0.01(c+0.5) / 緯度 21.0 − 0.01(r+0.5) なので、基準側の
        # 各画素中心は比較側 (r,c)(r,c+1)(r+1,c)(r+1,c+1) のちょうど中央にあたる。
        # (0,0): (1 + 2 + 2 + 3) / 4 = 2.0
        assert result[0, 0] == pytest.approx(2.0)
        # (1,1): (3 + 4 + 4 + 5) / 4 = 4.0
        assert result[1, 1] == pytest.approx(4.0)
        # (2,2): (5 + 6 + 6 + 7) / 4 = 6.0
        assert result[2, 2] == pytest.approx(6.0)

    def test_nearest_does_not_average_neighbouring_values(self, tmp_path: Path) -> None:
        """最近傍では平均を取らず、元の画素値がそのまま現れる。

        双一次との差が「内挿による平滑化」であることを担保する。
        """
        values = np.array(
            [[1.0, 2.0, 3.0, 4.0], [2.0, 3.0, 4.0, 5.0], [3.0, 4.0, 5.0, 6.0], [4.0, 5.0, 6.0, 7.0]]
        )
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", np.zeros(GRID_SHAPE))
        )
        shifted = target.load_radiance_raster(
            _write_raster(
                tmp_path / "shift.tif",
                values,
                origin=(
                    REFERENCE_ORIGIN[0] - PIXEL_SIZE_DEG / 2,
                    REFERENCE_ORIGIN[1] + PIXEL_SIZE_DEG / 2,
                ),
            )
        )

        result = target.reproject_to_reference(shifted, reference, Resampling.nearest)

        valid = result[result != target.NODATA]
        assert np.all(np.isin(valid, values))

    def test_nodata_is_not_mixed_into_interpolation(self, tmp_path: Path) -> None:
        """無効値は内挿へ混ぜず、無効値のまま残す。

        混ざると -9999 が薄まった中途半端な値になり、統計へ静かに入り込む。
        """
        values = np.full(GRID_SHAPE, 10.0)
        values[0, 0] = target.NODATA
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", np.full(GRID_SHAPE, 1.0))
        )
        source = target.load_radiance_raster(_write_raster(tmp_path / "src.tif", values))

        result = target.reproject_to_reference(source, reference, Resampling.bilinear)

        finite = result[result != target.NODATA]
        assert np.all(finite == pytest.approx(10.0))


class TestAlignByPixelIndex:
    """align_by_pixel_index のテスト。"""

    def test_copies_overlapping_region_only(self, tmp_path: Path) -> None:
        """重なる範囲だけを写し、残りは無効値のままにする。"""
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))
        smaller = target.load_radiance_raster(
            _write_raster(tmp_path / "small.tif", _gradient((3, 3)))
        )

        result = target.align_by_pixel_index(smaller, reference)

        assert result.shape == GRID_SHAPE
        assert result[0, 0] == pytest.approx(1.0)
        # 4 行 4 列目は比較側に存在しないため無効値
        assert result[3, 3] == target.NODATA


class TestBuildQuantileCorrespondence:
    """build_quantile_correspondence のテスト。"""

    def test_lists_percentiles_and_max(self) -> None:
        """指定分位点と最大値を両系列ぶん並べる。"""
        reference = np.arange(1.0, 101.0)

        correspondence = target.build_quantile_correspondence(reference, reference * 2)

        assert set(correspondence) == {"p50", "p90", "p95", "p99", "max"}
        assert correspondence["max"]["reference"] == pytest.approx(100.0)
        assert correspondence["max"]["comparison"] == pytest.approx(200.0)

    def test_returns_empty_for_empty_input(self) -> None:
        """有効画素が無ければ空の辞書を返す（percentile の例外を避ける）。"""
        empty = np.array([])

        assert target.build_quantile_correspondence(empty, empty) == {}


class TestCompareOnReferenceGrid:
    """compare_on_reference_grid のテスト。"""

    @staticmethod
    def _reference(tmp_path: Path) -> dict[str, object]:
        """基準グリッドのラスタを作る。"""
        return target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))

    def test_excludes_nodata_pixels_from_both_sides(self, tmp_path: Path) -> None:
        """どちらかが無効値の画素は比較対象から外す。"""
        reference = self._reference(tmp_path)
        reference["values"][0, 0] = target.NODATA
        comparison = _gradient()
        comparison[0, 1] = target.NODATA
        roi_mask = np.ones(GRID_SHAPE, dtype=bool)

        result = target.compare_on_reference_grid(
            reference, comparison, roi_mask, method="m", method_note="n"
        )

        assert result["comparable_pixels"] == GRID_SHAPE[0] * GRID_SHAPE[1] - 2
        assert result["excluded_pixels"] == 2

    def test_excludes_pixels_outside_roi(self, tmp_path: Path) -> None:
        """ROI 外の画素は比較対象に含めない。"""
        reference = self._reference(tmp_path)
        roi_mask = np.zeros(GRID_SHAPE, dtype=bool)
        roi_mask[:2, :2] = True

        result = target.compare_on_reference_grid(
            reference, _gradient(), roi_mask, method="m", method_note="n"
        )

        assert result["comparable_pixels"] == 4
        assert result["roi_pixels"] == 4

    def test_identical_series_are_perfectly_correlated(self, tmp_path: Path) -> None:
        """同じ値同士ならバイアス 0・相関 1 になる。"""
        reference = self._reference(tmp_path)
        roi_mask = np.ones(GRID_SHAPE, dtype=bool)

        result = target.compare_on_reference_grid(
            reference, _gradient(), roi_mask, method="m", method_note="n"
        )

        assert result["agreement"]["mean_bias"] == pytest.approx(0.0)
        assert result["agreement"]["pearson_r"] == pytest.approx(1.0)


def _bright_spot_values(shape: tuple[int, int], row: int, column: int) -> np.ndarray:
    """指定位置だけが突出して明るい配列を作る（最輝部を意図的に偏らせる）。"""
    values = np.ones(shape)
    values[row, column] = 1000.0
    return values


class TestComputeBrightCoreAnchor:
    """compute_bright_core_anchor のテスト。"""

    def test_anchor_follows_the_brightest_pixels_not_the_roi_centre(self, tmp_path: Path) -> None:
        """基準点は ROI の中心ではなく、最輝部に寄る。

        実データでは ROI 内画素の重心が最輝画素から約 20km 離れ、最輝画素が
        都心側・外縁側のどちらにも入らなかった。飽和は最輝部で起きるため、
        基準点が輝度側から決まることを固定する。
        """
        # 左上隅だけが明るい 10×10 のラスタ
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", _bright_spot_values((10, 10), 0, 0))
        )
        roi_mask = np.ones((10, 10), dtype=bool)

        anchor_longitude, anchor_latitude = target.compute_bright_core_anchor(reference, roi_mask)

        # 左上隅の画素中心（経度 105.005 / 緯度 20.995）付近に寄る
        assert anchor_longitude == pytest.approx(REFERENCE_ORIGIN[0] + PIXEL_SIZE_DEG / 2, abs=0.02)
        assert anchor_latitude == pytest.approx(REFERENCE_ORIGIN[1] - PIXEL_SIZE_DEG / 2, abs=0.02)


class TestBuildZoneMasks:
    """build_zone_masks のテスト。"""

    def test_splits_roi_into_inner_and_outer(self, tmp_path: Path) -> None:
        """ROI 内画素を都心側と外縁側に分ける。"""
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", _gradient((10, 10)))
        )
        roi_mask = np.ones((10, 10), dtype=bool)

        inner_mask, outer_mask, zone_note = target.build_zone_masks(reference, roi_mask)

        assert np.count_nonzero(inner_mask) > 0
        assert np.count_nonzero(outer_mask) > 0
        assert zone_note["inner_threshold_deg"] < zone_note["outer_threshold_deg"]
        assert not np.any(inner_mask & outer_mask)

    def test_brightest_pixel_belongs_to_the_inner_zone(self, tmp_path: Path) -> None:
        """最輝画素は必ず都心側ゾーンに入る（飽和を見逃さないための要件）。"""
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", _bright_spot_values((10, 10), 1, 1))
        )
        roi_mask = np.ones((10, 10), dtype=bool)

        inner_mask, outer_mask, _ = target.build_zone_masks(reference, roi_mask)

        assert inner_mask[1, 1]
        assert not outer_mask[1, 1]

    def test_raises_when_roi_has_no_pixels(self, tmp_path: Path) -> None:
        """ROI 内画素が無ければ、分位点計算へ進まず例外にする。"""
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", _gradient()))

        with pytest.raises(ValueError, match="ROI 内の画素がありません"):
            target.build_zone_masks(reference, np.zeros(GRID_SHAPE, dtype=bool))

    def test_raises_when_roi_has_no_valid_pixels(self, tmp_path: Path) -> None:
        """ROI 内が全て無効値なら、分位点計算へ進まず例外にする。

        `roi_mask` が非空でも有効画素は 0 件になりうる（ROI から外れた年・範囲の
        ラスタを渡した場合）。numpy の空配列エラーで止まると、ROI とラスタの
        位置関係が原因だと読み取れない。
        """
        reference = target.load_radiance_raster(
            _write_raster(
                tmp_path / "nodata.tif",
                np.full(GRID_SHAPE, target.NODATA, dtype=np.float32),
            )
        )

        with pytest.raises(ValueError, match="ROI 内に有効画素がありません"):
            target.build_zone_masks(reference, np.ones(GRID_SHAPE, dtype=bool))


class TestCompareSaturationByZone:
    """compare_saturation_by_zone のテスト。"""

    def test_evaluates_both_datasets_on_their_own_raw_grids(self, tmp_path: Path) -> None:
        """比較側は再投影せず、自身のグリッドの生データで評価する。

        再投影後の値で測ると内挿の平滑化が上位の値を削り、飽和指標が
        「飽和していない」方向へ歪む。生データの最大値がそのまま現れることで
        平滑化を経ていないことを担保する。
        """
        reference = target.load_radiance_raster(
            _write_raster(tmp_path / "ref.tif", _bright_spot_values((10, 10), 5, 5))
        )
        comparison_values = _bright_spot_values((10, 10), 5, 5) * 2.0
        comparison = target.load_radiance_raster(
            _write_raster(
                tmp_path / "cmp.tif",
                comparison_values,
                origin=SHIFTED_ORIGIN,
                band_names=("ntl_near_nadir",),
            )
        )
        roi_mask = np.ones((10, 10), dtype=bool)

        zones = target.compare_saturation_by_zone(reference, roi_mask, comparison, roi_mask)

        # 生データの最大値 2000 がそのまま現れる（内挿されていれば下がる）
        assert zones["inner"]["black_marble"]["statistics"]["max"] == pytest.approx(2000.0)
        assert zones["inner"]["viirs_dnb"]["statistics"]["max"] == pytest.approx(1000.0)

    def test_uses_the_same_geographic_zones_for_both_datasets(self, tmp_path: Path) -> None:
        """比較側にも基準側と同じ距離閾値を適用する（ゾーンを地理的に揃える）。"""
        values = _bright_spot_values((10, 10), 5, 5)
        reference = target.load_radiance_raster(_write_raster(tmp_path / "ref.tif", values))
        comparison = target.load_radiance_raster(
            _write_raster(tmp_path / "cmp.tif", values, band_names=("ntl_near_nadir",))
        )
        roi_mask = np.ones((10, 10), dtype=bool)

        zones = target.compare_saturation_by_zone(reference, roi_mask, comparison, roi_mask)

        # 同一グリッド・同一値なら、ゾーンの画素数も一致する
        assert zones["inner"]["viirs_dnb"]["pixels"] == zones["inner"]["black_marble"]["pixels"]
        assert zones["outer"]["viirs_dnb"]["pixels"] == zones["outer"]["black_marble"]["pixels"]


class TestSummarizeZone:
    """summarize_zone のテスト。"""

    def test_reports_spread_of_upper_values(self) -> None:
        """上位の広がり（p99 と中央値の差）を記録する。"""
        values = np.arange(1.0, 101.0)

        summary = target.summarize_zone(values)

        assert summary["pixels"] == 100
        assert summary["p99_minus_median"] == pytest.approx(
            summary["statistics"]["p99"] - summary["statistics"]["median"]
        )

    def test_returns_none_for_empty_zone(self) -> None:
        """有効画素が無ければ None（統計を捏造しない）。"""
        assert target.summarize_zone(np.array([])) is None


class TestRun:
    """run の統合テスト（合成ラスタ・合成 ROI を使う）。"""

    @staticmethod
    def _prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
        """半画素ずれた 2 つのラスタと、それを覆う ROI を用意する。"""
        viirs_path = _write_raster(tmp_path / "viirs.tif", _gradient())
        black_marble_path = _write_raster(
            tmp_path / "black_marble.tif",
            _gradient() * 1.2,
            origin=SHIFTED_ORIGIN,
            band_names=("ntl_near_nadir",),
        )
        roi_path = _write_roi(tmp_path / "roi.shp", (105.0, 20.96, 105.04, 21.0))
        return viirs_path, black_marble_path, roi_path

    def test_writes_summary_with_all_comparison_methods(self, tmp_path: Path) -> None:
        """3 通りの載せ替え方法すべてがサマリーへ載る。"""
        viirs_path, black_marble_path, roi_path = self._prepare(tmp_path)
        summary_path = tmp_path / "summary.json"

        result_path = target.run(
            year=2023,
            viirs_path=viirs_path,
            black_marble_path=black_marble_path,
            roi_path=roi_path,
            summary_path=summary_path,
        )

        summary = json.loads(result_path.read_text(encoding="utf-8"))
        assert summary["primary_comparison"]["method"] == "reproject_bilinear"
        methods = [entry["method"] for entry in summary["sensitivity_comparisons"]]
        assert methods == ["reproject_nearest", "pixel_index_without_reprojection"]

    def test_summary_records_grid_offset_and_zones(self, tmp_path: Path) -> None:
        """半画素ずれとゾーン定義を記録する（再現時に前提を追えるようにする）。"""
        viirs_path, black_marble_path, roi_path = self._prepare(tmp_path)

        result_path = target.run(
            year=2023,
            viirs_path=viirs_path,
            black_marble_path=black_marble_path,
            roi_path=roi_path,
            summary_path=tmp_path / "summary.json",
        )

        summary = json.loads(result_path.read_text(encoding="utf-8"))
        assert summary["grid_offset"]["longitude_in_pixels"] == pytest.approx(0.5)
        assert summary["saturation_by_zone"]["definition"]["inner_percentile"] == 25
        assert summary["datasets"]["black_marble_vnp46a4"]["band"] == "ntl_near_nadir"

    def test_summary_is_json_serializable_without_nan(self, tmp_path: Path) -> None:
        """サマリーが裸の NaN を含まずに JSON へ書き出せる。"""
        viirs_path, black_marble_path, roi_path = self._prepare(tmp_path)

        result_path = target.run(
            year=2023,
            viirs_path=viirs_path,
            black_marble_path=black_marble_path,
            roi_path=roi_path,
            summary_path=tmp_path / "summary.json",
        )

        json.loads(result_path.read_text(encoding="utf-8"), parse_constant=_reject_constant)

    def test_handles_real_world_shape_mismatch(self, tmp_path: Path) -> None:
        """実データと同じく「列数が 1 つ違う」形状差でも通しで動く。

        実データは VIIRS が 198×177、Black Marble が 198×176 で、半画素ずれの
        結果として列数が 1 つ食い違う。合成データを同形状だけにすると、この
        組み合わせが一度も踏まれない。
        """
        viirs_path = _write_raster(tmp_path / "viirs.tif", _gradient((8, 7)))
        black_marble_path = _write_raster(
            tmp_path / "black_marble.tif",
            _gradient((8, 6)) * 1.2,
            origin=SHIFTED_ORIGIN,
            band_names=("ntl_near_nadir",),
        )
        roi_path = _write_roi(tmp_path / "roi.shp", (105.0, 20.93, 105.06, 21.0))

        result_path = target.run(
            year=2023,
            viirs_path=viirs_path,
            black_marble_path=black_marble_path,
            roi_path=roi_path,
            summary_path=tmp_path / "summary.json",
        )

        summary = json.loads(result_path.read_text(encoding="utf-8"))
        assert summary["datasets"]["viirs_dnb"]["shape"] == [8, 7]
        assert summary["datasets"]["black_marble_vnp46a4"]["shape"] == [8, 6]
        assert summary["primary_comparison"]["comparable_pixels"] > 0

    def test_records_pixels_excluded_at_the_roi_edge(self, tmp_path: Path) -> None:
        """比較側が覆わない ROI 外縁の画素は、比較対象から外して数を残す。

        実データでは再投影の結果 217 画素がこの理由で外れている。有効域を ROI
        全体と同一視しないための記録なので、経路自体を踏んで固定する。
        """
        viirs_path = _write_raster(tmp_path / "viirs.tif", _gradient())
        # 比較側を左上 2×2 画素ぶんの範囲しか持たないラスタにする
        black_marble_path = _write_raster(
            tmp_path / "black_marble.tif",
            _gradient((2, 2)),
            band_names=("ntl_near_nadir",),
        )
        roi_path = _write_roi(tmp_path / "roi.shp", (105.0, 20.96, 105.04, 21.0))

        result_path = target.run(
            year=2023,
            viirs_path=viirs_path,
            black_marble_path=black_marble_path,
            roi_path=roi_path,
            summary_path=tmp_path / "summary.json",
        )

        comparison = json.loads(result_path.read_text(encoding="utf-8"))["primary_comparison"]
        assert comparison["excluded_pixels"] > 0
        assert comparison["comparable_pixels"] < comparison["roi_pixels"]
        assert (
            comparison["comparable_pixels"] + comparison["excluded_pixels"]
            == comparison["roi_pixels"]
        )

    def test_rejects_unexpected_nodata(self, tmp_path: Path) -> None:
        """無効値が前提と違うラスタは、統計へ混ぜる前に例外にする。

        -9999 以外の nodata を有効値として扱うと、平均・相関が静かに壊れる。
        """
        viirs_path = _write_raster(tmp_path / "viirs.tif", _gradient())
        black_marble_path = tmp_path / "bm.tif"
        with rasterio.open(
            black_marble_path,
            "w",
            driver="GTiff",
            height=GRID_SHAPE[0],
            width=GRID_SHAPE[1],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(*REFERENCE_ORIGIN, PIXEL_SIZE_DEG, PIXEL_SIZE_DEG),
            nodata=-999.0,
        ) as destination:
            destination.write(_gradient().astype(np.float32), 1)
            destination.set_band_description(1, "ntl_near_nadir")
        roi_path = _write_roi(tmp_path / "roi.shp", (105.0, 20.96, 105.04, 21.0))

        with pytest.raises(ValueError, match="想定外の無効値"):
            target.run(
                year=2023,
                viirs_path=viirs_path,
                black_marble_path=black_marble_path,
                roi_path=roi_path,
                summary_path=tmp_path / "summary.json",
            )

    def test_rejects_mismatched_crs(self, tmp_path: Path) -> None:
        """CRS が違うラスタ同士は、無意味な対応付けをせず例外にする。"""
        viirs_path = _write_raster(tmp_path / "viirs.tif", _gradient())
        black_marble_path = _write_raster(
            tmp_path / "bm.tif", _gradient(), crs="EPSG:4269", band_names=("ntl_near_nadir",)
        )
        roi_path = _write_roi(tmp_path / "roi.shp", (105.0, 20.96, 105.04, 21.0))

        with pytest.raises(ValueError, match="CRS が一致しません"):
            target.run(
                year=2023,
                viirs_path=viirs_path,
                black_marble_path=black_marble_path,
                roi_path=roi_path,
                summary_path=tmp_path / "summary.json",
            )


class TestLogResults:
    """log_results のテスト（書式指定で落ちない経路の確認）。"""

    def test_warns_when_no_comparable_pixels(self, caplog: pytest.LogCaptureFixture) -> None:
        """比較対象画素が無い場合、統計キーを参照せず警告だけ出す。

        `agreement` は件数 0 のとき `cell_count` しか持たない。書式指定で
        そのまま参照すると KeyError になるため、早期復帰を固定する。
        """
        comparisons = [{"method": "empty", "agreement": {"cell_count": 0}}]

        with caplog.at_level(logging.WARNING):
            target.log_results(comparisons, {})

        assert "比較対象画素がありません" in caplog.text

    def test_uses_correlation_note_when_correlation_is_undefined(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """相関が None のときは、書式指定せず理由をそのまま出す。"""
        comparisons = [
            {
                "method": "constant",
                "agreement": {
                    "cell_count": 3,
                    "pearson_r": None,
                    "spearman_rho": None,
                    "correlation_note": "いずれかの系列が定数のため相関を計算できない。",
                    "mean_bias": 1.0,
                    "median_bias": 1.0,
                    "root_mean_squared_error": 1.0,
                },
            }
        ]

        with caplog.at_level(logging.INFO):
            target.log_results(comparisons, {})

        assert "定数" in caplog.text

    def test_warns_when_zone_has_no_valid_pixels(self, caplog: pytest.LogCaptureFixture) -> None:
        """ゾーンに有効画素が無い場合も落ちずに警告する。"""
        saturation_by_zone = {"inner": {"viirs_dnb": None}, "outer": {}}

        with caplog.at_level(logging.WARNING):
            target.log_results([], saturation_by_zone)

        assert "有効画素がありません" in caplog.text


def _reject_constant(constant: str) -> None:
    """JSON の裸の NaN / Infinity を検出したら失敗させる。

    Args:
        constant: json が検出した定数名。

    Raises:
        AssertionError: 常に送出する。
    """
    raise AssertionError(f"JSON に RFC 8259 非準拠の定数が含まれています: {constant}")
