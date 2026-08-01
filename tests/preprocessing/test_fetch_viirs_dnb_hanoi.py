"""fetch_viirs_dnb_hanoi.py（VIIRS DNB 年次コンポジット取得スクリプト）のテスト。

ネットワーク・GEE アクセスを伴わない純粋関数を対象とする。GEE のコレクション操作と
ダウンロードはモックに差し替えて検証する。ラスタ入出力を伴うクリップは、合成した
小さな GeoTIFF を用いたスモークテストで CRS・バンド構成・統計を確認する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.preprocessing import fetch_viirs_dnb_hanoi as target
from tests.helpers import HANOI_ROI_BOUNDS, make_fake_build_target_area

# VIIRS DNB 年次コンポジットの実測ネイティブ投影（GEE の projection().getInfo() の戻り値）
VIIRS_PROJECTION = {
    "crs": "EPSG:4326",
    "transform": [0.0041666667, 0, -180.00208333335, 0, -0.0041666667, 75.00208333335],
}


class _FakeValue:
    """getInfo() だけを持つ値オブジェクト。"""

    def __init__(self, value: Any) -> None:
        self.value = value

    def getInfo(self) -> Any:  # noqa: N802  # GEE API 名に合わせる
        """保持している値を返す。"""
        return self.value


class _FakeFilter:
    """ee.Filter.eq の戻り値を模した記録用オブジェクト。"""

    def __init__(self, property_name: str, value: Any) -> None:
        self.property_name = property_name
        self.value = value


class _FakeCollection:
    """ee.ImageCollection を模し、適用されたフィルタと件数を記録する。"""

    def __init__(self, asset_id: str, matched_count: int, applied: list[_FakeFilter]) -> None:
        self.asset_id = asset_id
        self.matched_count = matched_count
        self.applied = applied

    def filter(self, fake_filter: _FakeFilter) -> _FakeCollection:
        """フィルタ適用を共有リストへ記録し、同じ記録を持つコレクションを返す。"""
        self.applied.append(fake_filter)
        return _FakeCollection(self.asset_id, self.matched_count, self.applied)

    def size(self) -> _FakeValue:
        """件数を返す。"""
        return _FakeValue(self.matched_count)

    def first(self) -> str:
        """先頭画像の代わりに識別用の文字列を返す。"""
        return f"{self.asset_id}#first"


class _FakeImage:
    """ee.Image を模し、select の呼び出しを記録する。"""

    def __init__(self, source: str) -> None:
        self.source = source
        self.selected_sources: list[str] | None = None
        self.selected_outputs: list[str] | None = None

    def select(self, source_names: list[str], output_names: list[str]) -> _FakeImage:
        """バンド選択と改名を記録する。"""
        self.selected_sources = source_names
        self.selected_outputs = output_names
        return self


def _install_fake_ee(monkeypatch: pytest.MonkeyPatch, matched_count: int) -> dict[str, Any]:
    """target モジュールの ee を偽物に差し替え、記録用の辞書を返す。"""
    recorded: dict[str, Any] = {}

    def fake_image_collection(asset_id: str) -> _FakeCollection:
        recorded["asset_id"] = asset_id
        applied: list[_FakeFilter] = []
        recorded["filters"] = applied
        return _FakeCollection(asset_id, matched_count, applied)

    def fake_image(source: str) -> _FakeImage:
        image = _FakeImage(source)
        recorded["image"] = image
        return image

    class _FakeEeFilter:
        @staticmethod
        def eq(property_name: str, value: Any) -> _FakeFilter:
            return _FakeFilter(property_name, value)

    monkeypatch.setattr(target.ee, "ImageCollection", fake_image_collection)
    monkeypatch.setattr(target.ee, "Image", fake_image)
    monkeypatch.setattr(target.ee, "Filter", _FakeEeFilter)
    return recorded


class TestBandDefinitions:
    """バンド定義そのものの整合性を固定する。"""

    def test_output_names_are_unique(self) -> None:
        """出力バンド名が重複していない（辞書化で値が潰れるのを防ぐ）。"""
        output_names = [band.output_name for band in target.BAND_DEFINITIONS]

        assert len(output_names) == len(set(output_names))

    def test_primary_band_is_defined(self) -> None:
        """被覆率を代表させる主バンドが定義に存在する。"""
        output_names = {band.output_name for band in target.BAND_DEFINITIONS}

        assert target.PRIMARY_BAND_NAME in output_names

    def test_primary_band_is_not_the_masked_one(self) -> None:
        """主バンドは背景マスク前のバンドである（被覆率を過小評価しないため）。"""
        primary = next(
            band for band in target.BAND_DEFINITIONS if band.output_name == target.PRIMARY_BAND_NAME
        )

        assert primary.source_name == "average"


class TestResolveCollection:
    """resolve_collection のテスト。"""

    def test_landsat_observation_year_uses_v22(self) -> None:
        """本研究の観測年 2023 は V2.2 で直接取得できる。"""
        collection_config = target.resolve_collection(2023)

        assert collection_config.version_key == "v22"
        # カタログのスラッグ（DNB_ANNUAL_V22）ではなく実アセットIDであること
        assert collection_config.gee_asset_id == "NOAA/VIIRS/DNB/ANNUAL_V22"

    def test_older_years_fall_back_to_v21(self) -> None:
        """2021 年以前は V2.1 を使う。"""
        collection_config = target.resolve_collection(2021)

        assert collection_config.version_key == "v21"
        assert collection_config.gee_asset_id == "NOAA/VIIRS/DNB/ANNUAL_V21"

    def test_version_boundary_is_2022(self) -> None:
        """V2.2 と V2.1 の境界（2021/2022）で切り替わる。"""
        assert target.resolve_collection(2022).version_key == "v22"
        assert target.resolve_collection(2021).version_key == "v21"

    def test_rejects_year_before_first_available(self) -> None:
        """提供開始年より前は弾く（VIIRS DNB 年次は 2013 年から）。"""
        with pytest.raises(ValueError, match="2012 年は含まれません"):
            target.resolve_collection(2012)

    def test_rejects_year_after_last_available(self) -> None:
        """提供最終年より後も弾く。"""
        with pytest.raises(ValueError, match="2026 年は含まれません"):
            target.resolve_collection(2026)

    def test_error_message_lists_available_ranges(self) -> None:
        """例外メッセージに対応年の範囲を含める（利用者が指定し直せるように）。"""
        with pytest.raises(ValueError, match="2013-2021"):
            target.resolve_collection(1999)

    def test_error_message_attributes_the_limit_to_this_script(self) -> None:
        """「データセットに無い」ではなく「本スクリプトが対応していない」と述べる。

        対応年は定数で持っており、データセット側に新しい年が追加されても自動では
        追従しない。存在しないと断定すると、定数が古いだけの場合に誤りになる。
        """
        with pytest.raises(ValueError, match="本スクリプトが対応する"):
            target.resolve_collection(2030)

    def test_error_message_points_at_the_constant_to_update(self) -> None:
        """更新すべき箇所（COLLECTION_CONFIGS の last_year）を示す。"""
        with pytest.raises(ValueError, match="COLLECTION_CONFIGS"):
            target.resolve_collection(2030)


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_builds_default_paths_from_year(self) -> None:
        """既定では年つきのファイル名になる。"""
        output_path, summary_path = target.resolve_output_paths(2023, None, None)

        assert output_path.parent.name == "viirs_dnb"
        assert output_path.name == "viirs_dnb_hanoi_2023.tif"
        assert summary_path.name == "nighttime_lights_viirs_dnb_hanoi_2023_summary.json"

    def test_respects_explicit_paths(self) -> None:
        """明示指定されたパスを優先する（相対パスはプロジェクトルート基準で解決する）。"""
        output_path, summary_path = target.resolve_output_paths(
            2023,
            Path("data/output/custom_out.tif"),
            Path("data/output/custom_summary.json"),
        )

        assert output_path.name == "custom_out.tif"
        assert summary_path.name == "custom_summary.json"
        assert output_path.is_absolute()
        assert output_path.is_relative_to(target.PROJECT_ROOT)

    def test_trial_run_gets_distinct_filename(self) -> None:
        """試行実行では ROI 全域の成果物を上書きしないよう _trial を付ける。"""
        production_path, production_summary = target.resolve_output_paths(
            2023, None, None, is_trial=False
        )
        trial_path, trial_summary = target.resolve_output_paths(2023, None, None, is_trial=True)

        assert trial_path.name == "viirs_dnb_hanoi_2023_trial.tif"
        assert trial_path != production_path
        assert trial_summary != production_summary


class TestSelectAnnualImage:
    """select_annual_image のテスト。"""

    def test_filters_by_year_start_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """年次コンポジットは年初日の system:index で絞る。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_annual_image(target.resolve_collection(2023), 2023)

        applied = {f.property_name: f.value for f in recorded["filters"]}
        assert applied == {"system:index": "20230101"}
        assert recorded["asset_id"] == "NOAA/VIIRS/DNB/ANNUAL_V22"

    def test_year_is_reflected_in_the_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指定年がそのままインデックスになる（年の取り違えを検出する）。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_annual_image(target.resolve_collection(2019), 2019)

        applied = {f.property_name: f.value for f in recorded["filters"]}
        assert applied == {"system:index": "20190101"}

    def test_selects_and_renames_all_defined_bands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """定義した全バンドを、定義順のまま出力名へ改名して選ぶ。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_annual_image(target.resolve_collection(2023), 2023)

        image = recorded["image"]
        assert image.selected_sources == [band.source_name for band in target.BAND_DEFINITIONS]
        assert image.selected_outputs == [band.output_name for band in target.BAND_DEFINITIONS]

    def test_raises_when_no_image_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """該当が 0 枚なら取り違えを防ぐため例外にする。"""
        _install_fake_ee(monkeypatch, matched_count=0)

        with pytest.raises(RuntimeError, match="該当: 0 枚"):
            target.select_annual_image(target.resolve_collection(2023), 2023)

    def test_raises_when_multiple_images_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """該当が複数枚なら年の特定に失敗しているため例外にする。"""
        _install_fake_ee(monkeypatch, matched_count=2)

        with pytest.raises(RuntimeError, match="該当: 2 枚"):
            target.select_annual_image(target.resolve_collection(2023), 2023)


class TestBuildPixelStatistics:
    """build_pixel_statistics のテスト（ラスタ入出力を伴わない）。"""

    @staticmethod
    def _band_arrays(height: int = 2, width: int = 3) -> dict[str, np.ndarray]:
        """全バンドぶんの非正方形な配列を作る（行・列の取り違えを検出するため）。"""
        return {
            band.output_name: np.arange(height * width, dtype=np.float32).reshape(height, width)
            for band in target.BAND_DEFINITIONS
        }

    def test_handles_non_square_rasters(self) -> None:
        """行数と列数が異なっても集計できる。"""
        stats = target.build_pixel_statistics(
            band_arrays=self._band_arrays(height=2, width=3),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
        )

        assert stats["total_pixels"] == 6
        assert stats["roi_pixels"] == 6
        assert stats["valid_pixels"] == 6
        assert stats["valid_pixel_ratio"] == pytest.approx(1.0)

    def test_counts_valid_pixels_per_band(self) -> None:
        """バンドごとに別々の有効画素数を数える。

        avg_radiance_masked は背景がマスクされているだけで欠測ではないため、
        その nodata を他バンドの統計から除外してはいけない。
        """
        band_arrays = self._band_arrays(height=2, width=3)
        band_arrays["avg_radiance_masked"][0, :] = target.OUTPUT_NODATA

        stats = target.build_pixel_statistics(
            band_arrays=band_arrays,
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
        )

        # 主バンドは欠けていないため被覆率は 1.0 のまま
        assert stats["valid_pixel_ratio"] == pytest.approx(1.0)
        assert stats["avg_radiance"]["valid_pixels"] == 6
        assert stats["avg_radiance_masked"]["valid_pixels"] == 3
        assert stats["avg_radiance_masked"]["valid_pixel_ratio"] == pytest.approx(0.5)
        # マスクされたバンドの nodata が他バンドの最小値へ混ざっていないこと
        assert stats["avg_radiance"]["min"] == pytest.approx(0.0)

    def test_primary_band_drives_coverage_ratio(self) -> None:
        """主バンドの欠測は被覆率へ反映される。"""
        band_arrays = self._band_arrays(height=2, width=3)
        band_arrays[target.PRIMARY_BAND_NAME][0, :] = target.OUTPUT_NODATA

        stats = target.build_pixel_statistics(
            band_arrays=band_arrays,
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
        )

        assert stats["valid_pixels"] == 3
        assert stats["valid_pixel_ratio"] == pytest.approx(0.5)
        assert stats["primary_band"] == target.PRIMARY_BAND_NAME

    def test_excludes_pixels_outside_area(self) -> None:
        """範囲外の画素は有効画素にも分母にも入らない。"""
        stats = target.build_pixel_statistics(
            band_arrays=self._band_arrays(height=2, width=3),
            area_mask=np.array([[True, True, True], [False, False, False]]),
            covers_area=True,
        )

        assert stats["roi_pixels"] == 3
        assert stats["outside_roi_pixels"] == 3
        assert stats["valid_pixels"] == 3
        assert stats["avg_radiance"]["max"] == pytest.approx(2.0)

    def test_ratio_is_zero_when_area_is_empty(self) -> None:
        """範囲内画素が 0 でもゼロ除算にならない。"""
        stats = target.build_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.zeros((2, 3), dtype=bool),
            covers_area=True,
        )

        assert stats["roi_pixels"] == 0
        assert stats["valid_pixel_ratio"] == 0.0
        # 統計は空でも、件数のキーは残す（サマリーの形を安定させるため）
        assert stats["avg_radiance"]["valid_pixels"] == 0
        assert "min" not in stats["avg_radiance"]

    def test_saturation_is_computed_only_for_radiance_bands(self) -> None:
        """飽和指標は放射輝度バンドにのみ付く（観測回数バンドには意味がない）。"""
        stats = target.build_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
        )

        expected = {
            band.output_name for band in target.BAND_DEFINITIONS if band.is_saturation_target
        }
        assert set(stats["saturation"]) == expected
        assert "cf_cvg" not in stats["saturation"]

    def test_records_coverage_flag(self) -> None:
        """カバレッジ判定の結果をそのまま保持する。"""
        stats = target.build_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=False,
        )

        assert stats["covers_requested_area"] is False


class TestClipAndWrite:
    """clip_and_write のスモークテスト。"""

    @staticmethod
    def _write_source_raster(path: Path, band_count: int = len(target.BAND_DEFINITIONS)) -> None:
        """テスト用の多バンドラスタを書き出す。"""
        pixel_size_deg = 1.0 / 240.0
        transform = from_origin(105.0, 21.1, pixel_size_deg, pixel_size_deg)
        profile = {
            "driver": "GTiff",
            "height": 10,
            "width": 10,
            "count": band_count,
            "dtype": "float32",
            "crs": CRS.from_epsg(4326),
            "transform": transform,
            "nodata": target.OUTPUT_NODATA,
        }
        with rasterio.open(path, "w", **profile) as destination:
            for index in range(1, band_count + 1):
                values = np.full((10, 10), float(index), dtype=np.float32)
                destination.write(values, index)

    def test_writes_all_bands_with_descriptions(self, tmp_path: Path) -> None:
        """定義した全バンドを、定義順の説明つきで EPSG:4326 に書き出す。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 21.06, 105.02, 21.1)], crs="EPSG:4326")
        output_path = tmp_path / "out.tif"

        raster_profile, pixel_stats = target.clip_and_write(source_path, area_gdf, output_path)

        with rasterio.open(output_path) as destination:
            assert destination.count == len(target.BAND_DEFINITIONS)
            assert destination.crs.to_epsg() == 4326
            assert destination.descriptions == tuple(
                band.output_name for band in target.BAND_DEFINITIONS
            )
        assert raster_profile["crs"] == "EPSG:4326"
        assert raster_profile["nodata"] == target.OUTPUT_NODATA
        assert pixel_stats["valid_pixel_ratio"] == pytest.approx(1.0)

    def test_band_order_is_preserved(self, tmp_path: Path) -> None:
        """ソースのバンド順がそのまま出力バンド名へ対応する（取り違えの検出）。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 21.06, 105.02, 21.1)], crs="EPSG:4326")

        _, pixel_stats = target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

        # ソースは第 n バンドを一律 n で埋めてある
        for index, band in enumerate(target.BAND_DEFINITIONS, start=1):
            assert pixel_stats[band.output_name]["mean"] == pytest.approx(float(index))

    def test_raises_when_band_count_differs(self, tmp_path: Path) -> None:
        """バンド数が想定と違えば、名前の割り当てが信用できないため止める。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path, band_count=2)
        area_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 21.06, 105.02, 21.1)], crs="EPSG:4326")

        with pytest.raises(ValueError, match="バンド数が想定と異なります"):
            target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

    def test_detects_area_not_covered_by_source(self, tmp_path: Path) -> None:
        """ソースが要求範囲を覆っていない場合、有効率ではなく被覆判定で検知する。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        # ソースの南東側へはみ出す範囲
        area_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.2, 21.1)], crs="EPSG:4326")

        _, pixel_stats = target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

        assert pixel_stats["covers_requested_area"] is False


class TestBuildSummary:
    """build_summary のテスト。"""

    @staticmethod
    def _build(year: int) -> dict[str, Any]:
        """最小限の入力でサマリーを組み立てる。"""
        return target.build_summary(
            collection_config=target.resolve_collection(year),
            year=year,
            roi_path=Path("data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp"),
            is_trial=False,
            area_bounds=HANOI_ROI_BOUNDS,
            projection_info=VIIRS_PROJECTION,
            raster_profile={"crs": "EPSG:4326"},
            pixel_stats={"valid_pixel_ratio": 1.0},
            output_path=Path("data/gis/nighttime_lights/viirs_dnb/viirs_dnb_hanoi_2023.tif"),
            summary_path=Path("data/output/open_gis/x_summary.json"),
            retrieved_at="2026-07-27T00:00:00+00:00",
        )

    def test_records_asset_id_and_license(self) -> None:
        """アセットIDとライセンスを記録する。"""
        summary = self._build(2023)

        assert summary["gee_asset_id"] == "NOAA/VIIRS/DNB/ANNUAL_V22"
        assert summary["license"] == "パブリックドメイン"
        assert "Earth Observation Group" in summary["license_note"]

    def test_notes_no_time_gap_for_landsat_year(self) -> None:
        """観測年と一致する年では時間差なしと記録する。"""
        summary = self._build(2023)

        assert "時間差はない" in summary["year_note"]

    def test_notes_time_gap_for_other_years(self) -> None:
        """観測年と異なる年では時間差を明記する。"""
        summary = self._build(2019)

        assert "4 年の時間差" in summary["year_note"]

    def test_band_definitions_record_units_and_source_names(self) -> None:
        """バンドの単位と、由来する GEE バンド名を記録する。"""
        summary = self._build(2023)

        assert summary["bands"]["1"]["name"] == "avg_radiance"
        assert summary["bands"]["1"]["source_band"] == "average"
        assert summary["bands"]["1"]["unit"] == target.RADIANCE_UNIT
        assert summary["bands"]["3"]["unit"] == "観測回数"

    def test_records_half_pixel_offset_caveat(self) -> None:
        """他データセットとの突合時に効く半画素ずれを記録する。"""
        summary = self._build(2023)

        assert "半画素" in summary["resampling_note"]

    def test_is_json_serializable(self) -> None:
        """サマリーがそのまま JSON へ書き出せる（NaN 等が混ざらない）。"""
        json.dumps(self._build(2023), ensure_ascii=False, allow_nan=False)


class TestRunEndToEnd:
    """run の統合テスト（GEE・ネットワークはモックする）。"""

    @staticmethod
    def _install_fakes(monkeypatch: pytest.MonkeyPatch, roi_bounds: tuple) -> None:
        """範囲組み立て・GEE 認証・画像選択・ダウンロードを差し替える。"""
        monkeypatch.setattr(target, "build_target_area", make_fake_build_target_area(roi_bounds))
        monkeypatch.setattr(target, "load_gee_project_id", lambda **kwargs: "fake-project")
        monkeypatch.setattr(target, "authenticate_gee", lambda project_id: None)
        monkeypatch.setattr(target, "select_annual_image", lambda config, year: object())
        monkeypatch.setattr(
            target,
            "build_native_download_url",
            lambda image, region_geojson, nodata: (
                "https://example.invalid/download",
                VIIRS_PROJECTION,
            ),
        )

        def fake_download(download_url: str, destination_path: Path, timeout: int) -> Path:
            """対象範囲を覆う合成 GeoTIFF を書き出す。"""
            pixel_size = 0.01
            width = int(round((roi_bounds[2] - roi_bounds[0]) / pixel_size)) + 2
            height = int(round((roi_bounds[3] - roi_bounds[1]) / pixel_size)) + 2
            profile = {
                "driver": "GTiff",
                "height": height,
                "width": width,
                "count": len(target.BAND_DEFINITIONS),
                "dtype": "float32",
                "crs": CRS.from_epsg(4326),
                "transform": from_origin(
                    roi_bounds[0] - pixel_size, roi_bounds[3] + pixel_size, pixel_size, pixel_size
                ),
                "nodata": target.OUTPUT_NODATA,
            }
            with rasterio.open(destination_path, "w", **profile) as destination:
                for index in range(1, len(target.BAND_DEFINITIONS) + 1):
                    destination.write(
                        np.full((height, width), float(index) * 5.0, dtype=np.float32), index
                    )
            return destination_path

        monkeypatch.setattr(target, "download_gee_raster", fake_download)

    def test_writes_raster_and_summary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """取得から保存までを通しで実行し、GeoTIFF とサマリーが揃う。"""
        roi_bounds = (105.3, 21.0, 105.5, 21.2)
        self._install_fakes(monkeypatch, roi_bounds)
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")

        output_path, summary_path = target.run(
            year=2023,
            roi_path=roi_path,
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            config_path=tmp_path / "config.csv",
            gee_project_id="fake-project",
            overwrite=True,
        )

        with rasterio.open(output_path) as destination:
            assert destination.count == len(target.BAND_DEFINITIONS)
            assert destination.crs.to_epsg() == 4326

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["dataset_key"] == "viirs_dnb_v22"
        assert summary["year"] == 2023
        assert summary["pixel_stats"]["valid_pixel_ratio"] == pytest.approx(1.0)
        assert summary["pixel_stats"]["covers_requested_area"] is True
        assert summary["pixel_stats"]["saturation"]["avg_radiance"] is not None

    def test_trial_run_marks_summary_and_uses_distinct_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BBOX 指定時は試行実行として記録され、既定パスに _trial が付く。"""
        bbox = [105.3, 21.0, 105.4, 21.1]
        self._install_fakes(monkeypatch, tuple(bbox))
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")
        # 既定の出力ルートのままだと実成果物ディレクトリへ書き込むため、tmp_path へ閉じる
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_ROOT", tmp_path / "gis" / "viirs_dnb")

        output_path, summary_path = target.run(
            year=2023,
            roi_path=roi_path,
            bbox=bbox,
            output_path=None,
            summary_path=tmp_path / "trial_summary.json",
            config_path=tmp_path / "config.csv",
            gee_project_id="fake-project",
            overwrite=True,
        )

        assert output_path.name == "viirs_dnb_hanoi_2023_trial.tif"
        assert output_path.is_relative_to(tmp_path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["is_trial_run"] is True

    def test_rejects_unavailable_year_before_any_network_access(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """提供年外の指定は、GEE 認証まで進む前に弾く。"""

        def fail_if_called(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("提供年外の指定で GEE 認証まで進んではいけない")

        monkeypatch.setattr(target, "authenticate_gee", fail_if_called)

        with pytest.raises(ValueError, match="2012 年は含まれません"):
            target.run(
                year=2012,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "summary.json",
                config_path=tmp_path / "config.csv",
                gee_project_id="fake-project",
                overwrite=True,
            )


class TestRunOverwriteGuard:
    """run の既存ファイル保護のテスト。"""

    def test_refuses_to_overwrite_existing_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既存の出力があり --overwrite が無ければ、取得を始める前に止める。"""
        existing_output = tmp_path / "existing.tif"
        existing_output.write_bytes(b"IMPORTANT")
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )

        def fail_if_called(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("既存ファイルがある場合は GEE 認証まで進んではいけない")

        monkeypatch.setattr(target, "authenticate_gee", fail_if_called)

        with pytest.raises(FileExistsError, match="--overwrite"):
            target.run(
                year=2023,
                roi_path=roi_path,
                bbox=None,
                output_path=existing_output,
                summary_path=tmp_path / "summary.json",
                config_path=Path("dummy.csv"),
                gee_project_id="dummy-project",
                overwrite=False,
            )

        # 既存ファイルは削除されず内容も保たれる
        assert existing_output.read_bytes() == b"IMPORTANT"
