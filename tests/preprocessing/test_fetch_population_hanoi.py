"""fetch_population_hanoi.py（WorldPop / LandScan 取得スクリプト）のテスト。

ネットワーク・GEE アクセスを伴わない純粋関数を対象とする。GEE のコレクション操作と
ダウンロードはモックに差し替えて検証する。ラスタ入出力を伴うクリップ・密度導出は、
合成した小さな GeoTIFF を用いたスモークテストで CRS・バンド構成・統計を確認する。
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

from src.preprocessing import fetch_population_hanoi as target
from tests.helpers import HANOI_ROI_BOUNDS, make_fake_build_target_area


class _FakeFilter:
    """ee.Filter.eq の戻り値を模した記録用オブジェクト。"""

    def __init__(self, property_name: str, value: Any) -> None:
        self.property_name = property_name
        self.value = value


class _FakeCollection:
    """ee.ImageCollection を模し、適用されたフィルタと件数を記録する。

    `filter()` はチェーンされるため、適用条件は呼び出し元と共有するリストへ
    追記する（新しいインスタンスを返しても記録が失われないようにするため）。
    """

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


class _FakeValue:
    """getInfo() だけを持つ値オブジェクト。"""

    def __init__(self, value: Any) -> None:
        self.value = value

    def getInfo(self) -> Any:  # noqa: N802  # GEE API 名に合わせる
        """保持している値を返す。"""
        return self.value


class _FakeImage:
    """ee.Image を模し、select / rename の呼び出しを記録する。"""

    def __init__(self, source: str) -> None:
        self.source = source
        self.selected_band: str | None = None
        self.renamed_to: str | None = None

    def select(self, band_name: str) -> _FakeImage:
        """バンド選択を記録する。"""
        self.selected_band = band_name
        return self

    def rename(self, new_name: str) -> _FakeImage:
        """リネームを記録する。"""
        self.renamed_to = new_name
        return self


def _install_fake_ee(
    monkeypatch: pytest.MonkeyPatch,
    matched_count: int,
) -> dict[str, Any]:
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


class TestResolveYear:
    """resolve_year のテスト。"""

    def test_returns_default_year_when_not_specified(self) -> None:
        """未指定ならデータセットごとの既定年を返す。"""
        assert target.resolve_year(target.DATASET_CONFIGS["worldpop"], None) == 2020
        assert target.resolve_year(target.DATASET_CONFIGS["landscan"], None) == 2023

    def test_accepts_year_within_available_range(self) -> None:
        """提供年の範囲内なら指定年をそのまま返す。"""
        assert target.resolve_year(target.DATASET_CONFIGS["landscan"], 2020) == 2020

    def test_rejects_worldpop_2023_because_not_provided(self) -> None:
        """WorldPop に 2023 年は存在しないため弾く（Landsat 観測年との時間差の根拠）。"""
        with pytest.raises(ValueError, match="2000-2020"):
            target.resolve_year(target.DATASET_CONFIGS["worldpop"], 2023)

    def test_rejects_year_before_first_year(self) -> None:
        """提供開始年より前の年は弾く。"""
        with pytest.raises(ValueError):
            target.resolve_year(target.DATASET_CONFIGS["landscan"], 1999)


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_builds_default_paths_from_dataset_and_year(self) -> None:
        """既定ではデータセット別サブディレクトリと年つきのファイル名になる。"""
        output_path, summary_path = target.resolve_output_paths(
            target.DATASET_CONFIGS["landscan"], 2023, None, None
        )

        assert output_path.parent.name == "landscan"
        assert output_path.name == "landscan_hanoi_2023.tif"
        assert summary_path.name == "population_landscan_hanoi_2023_summary.json"

    def test_respects_explicit_paths(self) -> None:
        """明示指定されたパスを優先する（相対パスはプロジェクトルート基準で解決する）。"""
        output_path, summary_path = target.resolve_output_paths(
            target.DATASET_CONFIGS["worldpop"],
            2020,
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
            target.DATASET_CONFIGS["worldpop"], 2020, None, None, is_trial=False
        )
        trial_path, trial_summary = target.resolve_output_paths(
            target.DATASET_CONFIGS["worldpop"], 2020, None, None, is_trial=True
        )

        assert trial_path.name == "worldpop_hanoi_2020_trial.tif"
        assert trial_path != production_path
        assert trial_summary != production_summary


class TestSelectPopulationImage:
    """select_population_image のテスト。"""

    def test_worldpop_filters_by_year_and_country(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WorldPop は国別×年次のコレクションのため year と country の両方で絞る。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_population_image(target.DATASET_CONFIGS["worldpop"], 2020)

        applied = {f.property_name: f.value for f in recorded["filters"]}
        # country を落とすと他国の同年画像を掴むため、両方の適用を固定する
        assert applied == {"year": 2020, "country": "VNM"}
        image = recorded["image"]
        assert image.selected_band == "population"
        assert image.renamed_to == target.BAND_COUNT_NAME

    def test_landscan_filters_by_system_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LandScan は年次1枚のため system:index で絞る。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_population_image(target.DATASET_CONFIGS["landscan"], 2023)

        applied = {f.property_name: f.value for f in recorded["filters"]}
        assert applied == {"system:index": "landscan-global-2023"}
        assert recorded["asset_id"].endswith("LANDSCAN_GLOBAL")
        assert recorded["image"].selected_band == "b1"

    def test_year_is_reflected_in_the_filter_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指定年がそのままフィルタ値になる（年の取り違えを検出する）。"""
        recorded = _install_fake_ee(monkeypatch, matched_count=1)

        target.select_population_image(target.DATASET_CONFIGS["landscan"], 2020)

        applied = {f.property_name: f.value for f in recorded["filters"]}
        assert applied["system:index"] == "landscan-global-2020"

    def test_raises_when_no_image_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """該当が 0 枚なら取り違えを防ぐため例外にする。"""
        _install_fake_ee(monkeypatch, matched_count=0)

        with pytest.raises(RuntimeError, match="該当: 0 枚"):
            target.select_population_image(target.DATASET_CONFIGS["worldpop"], 2020)

    def test_raises_when_multiple_images_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """該当が複数枚なら年の特定に失敗しているため例外にする。"""
        _install_fake_ee(monkeypatch, matched_count=3)

        with pytest.raises(RuntimeError, match="該当: 3 枚"):
            target.select_population_image(target.DATASET_CONFIGS["landscan"], 2023)


class TestBuildPixelStatistics:
    """build_pixel_statistics のテスト（ラスタ入出力を伴わない）。"""

    @staticmethod
    def _inputs(height: int = 2, width: int = 3) -> dict[str, np.ndarray]:
        """非正方形の入力一式を作る（行・列の取り違えを検出するため）。"""
        count_array = np.arange(height * width, dtype=np.float32).reshape(height, width)
        cell_area_km2 = np.full((height, 1), 0.5)
        density_array = target.compute_density_array(
            count_array, cell_area_km2, target.OUTPUT_NODATA
        )
        return {
            "count_array": count_array,
            "density_array": density_array,
            "cell_area_km2": cell_area_km2,
            "area_mask": np.ones((height, width), dtype=bool),
        }

    def test_handles_non_square_rasters(self) -> None:
        """行数と列数が異なっても集計できる（ブロードキャストの向きの検証）。"""
        stats = target.build_pixel_statistics(**self._inputs(height=2, width=3), covers_area=True)

        assert stats["total_pixels"] == 6
        assert stats["roi_pixels"] == 6
        # 0..5 の合計
        assert stats["total_population"] == pytest.approx(15.0)
        assert stats["total_area_km2"] == pytest.approx(6 * 0.5)

    def test_excludes_nodata_and_outside_area(self) -> None:
        """nodata と範囲外は有効画素・総人口から外れる。"""
        inputs = self._inputs(height=2, width=3)
        inputs["count_array"][0, 0] = target.OUTPUT_NODATA
        inputs["density_array"][0, 0] = target.OUTPUT_NODATA
        inputs["area_mask"][1, :] = False  # 2 行目を範囲外にする

        stats = target.build_pixel_statistics(**inputs, covers_area=True)

        assert stats["roi_pixels"] == 3
        assert stats["valid_pixels"] == 2
        assert stats["outside_roi_pixels"] == 3
        assert stats["valid_pixel_ratio"] == pytest.approx(2 / 3)
        # 1 行目の値 1, 2 のみが残る
        assert stats["total_population"] == pytest.approx(3.0)

    def test_ratio_is_zero_when_area_is_empty(self) -> None:
        """範囲内画素が 0 でもゼロ除算にならない。"""
        inputs = self._inputs()
        inputs["area_mask"][:] = False

        stats = target.build_pixel_statistics(**inputs, covers_area=True)

        assert stats["roi_pixels"] == 0
        assert stats["valid_pixel_ratio"] == 0.0
        assert stats[target.BAND_COUNT_NAME] is None

    def test_records_coverage_flag(self) -> None:
        """カバレッジ判定の結果をそのまま保持する。"""
        stats = target.build_pixel_statistics(**self._inputs(), covers_area=False)

        assert stats["covers_requested_area"] is False


class TestClipAndWrite:
    """clip_and_write のスモークテスト。"""

    @staticmethod
    def _write_source_raster(path: Path) -> None:
        """テスト用の 1 バンド人口カウントラスタを書き出す。"""
        pixel_size_deg = 1.0 / 120.0
        transform = from_origin(105.0, 21.1, pixel_size_deg, pixel_size_deg)
        values = np.arange(100, dtype=np.float32).reshape(10, 10)
        # データ提供範囲外を模した nodata を 1 画素だけ置く
        values[0, 0] = target.OUTPUT_NODATA
        profile = {
            "driver": "GTiff",
            "height": 10,
            "width": 10,
            "count": 1,
            "dtype": "float32",
            "crs": CRS.from_epsg(4326),
            "transform": transform,
            "nodata": target.OUTPUT_NODATA,
        }
        with rasterio.open(path, "w", **profile) as destination:
            destination.write(values, 1)

    def test_writes_two_band_output_with_density(self, tmp_path: Path) -> None:
        """カウントと密度の 2 バンドを EPSG:4326 で書き出す。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0, 105.0 + 10 / 120, 21.1)], crs="EPSG:4326"
        )

        raster_profile, pixel_stats = target.clip_and_write(
            source_path, area_gdf, tmp_path / "out.tif"
        )

        assert raster_profile["crs"] == "EPSG:4326"
        assert raster_profile["band_count"] == 2
        assert raster_profile["nodata"] == target.OUTPUT_NODATA
        # dtype・解像度が壊れると密度値と面積計算が静かにずれる
        assert raster_profile["dtype"] == "float32"
        assert raster_profile["resolution"] == pytest.approx([1.0 / 120.0, 1.0 / 120.0])
        with rasterio.open(tmp_path / "out.tif") as destination:
            assert destination.descriptions == (
                target.BAND_COUNT_NAME,
                target.BAND_DENSITY_NAME,
            )

    def test_nodata_pixels_are_excluded_from_statistics(self, tmp_path: Path) -> None:
        """nodata 画素は有効画素数・総人口の集計から外れる。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0, 105.0 + 10 / 120, 21.1)], crs="EPSG:4326"
        )

        _, pixel_stats = target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

        # 値 0-99 のうち [0,0] を nodata にしたので、総人口は 1..99 の合計
        assert pixel_stats["total_population"] == pytest.approx(sum(range(1, 100)))
        assert pixel_stats["valid_pixel_ratio"] < 1.0
        assert pixel_stats["valid_pixels"] < pixel_stats["roi_pixels"]

    def test_density_band_is_consistent_with_count(self, tmp_path: Path) -> None:
        """総人口 ÷ 総面積 が密度バンドの加重平均と整合する（単位の検証）。"""
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_gdf = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0, 105.0 + 10 / 120, 21.1)], crs="EPSG:4326"
        )

        _, pixel_stats = target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

        mean_density = pixel_stats["total_population"] / pixel_stats["total_area_km2"]
        assert mean_density > 0
        density_stats = pixel_stats[target.BAND_DENSITY_NAME]
        assert density_stats is not None
        assert density_stats["min"] <= mean_density <= density_stats["max"]

    def test_rejects_projected_source_crs(self, tmp_path: Path) -> None:
        """投影座標系のラスタは、度前提の測地計算が破綻するため弾く。"""
        source_path = tmp_path / "projected.tif"
        profile = {
            "driver": "GTiff",
            "height": 4,
            "width": 4,
            "count": 1,
            "dtype": "float32",
            "crs": CRS.from_epsg(32648),  # UTM Zone 48N（メートル単位）
            "transform": from_origin(580000.0, 2330000.0, 100.0, 100.0),
            "nodata": target.OUTPUT_NODATA,
        }
        with rasterio.open(source_path, "w", **profile) as destination:
            destination.write(np.ones((4, 4), dtype=np.float32), 1)
        area_gdf = gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.01, 21.01)], crs="EPSG:4326")

        with pytest.raises(ValueError, match="地理座標系"):
            target.clip_and_write(source_path, area_gdf, tmp_path / "out.tif")

    def test_area_mask_uses_source_crs_geometry(self, tmp_path: Path) -> None:
        """範囲マスクをソース CRS のジオメトリで作る（座標系のずれで統計が壊れないこと）。

        入力 ROI を EPSG:3857 で与えても、EPSG:4326 で与えた場合と同じ画素統計になる。
        """
        source_path = tmp_path / "source.tif"
        self._write_source_raster(source_path)
        area_wgs84 = gpd.GeoDataFrame(
            geometry=[box(105.0, 21.0, 105.0 + 10 / 120, 21.1)], crs="EPSG:4326"
        )
        area_web_mercator = area_wgs84.to_crs("EPSG:3857")

        _, stats_wgs84 = target.clip_and_write(source_path, area_wgs84, tmp_path / "a.tif")
        _, stats_mercator = target.clip_and_write(
            source_path, area_web_mercator, tmp_path / "b.tif"
        )

        assert stats_wgs84["roi_pixels"] == stats_mercator["roi_pixels"]
        assert stats_wgs84["total_population"] == pytest.approx(stats_mercator["total_population"])


class TestBuildSummary:
    """build_summary のテスト。"""

    @staticmethod
    def _build(dataset_key: str, year: int) -> dict[str, Any]:
        """テスト用のサマリーを組み立てる。"""
        return target.build_summary(
            dataset_config=target.DATASET_CONFIGS[dataset_key],
            year=year,
            roi_path=Path("data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp"),
            is_trial=False,
            area_bounds=HANOI_ROI_BOUNDS,
            projection_info={
                "crs": "EPSG:4326",
                "transform": [0.00083, 0, 102.1, 0, -0.00083, 23.4],
            },
            raster_profile={"crs": "EPSG:4326"},
            pixel_stats={"valid_pixel_ratio": 1.0},
            output_path=Path("data/gis/population/x.tif"),
            summary_path=Path("data/output/open_gis/x_summary.json"),
            retrieved_at="2026-07-26T00:00:00+00:00",
        )

    def test_contains_required_keys(self) -> None:
        """検証チェックリストが要求する項目を含む。"""
        summary = self._build("worldpop", 2020)

        for key in ("dataset", "source", "license", "retrieved_at", "crs", "coverage_note"):
            assert key in summary
        assert summary["outputs"]["geotiff"].endswith("x.tif")

    def test_worldpop_year_note_mentions_time_gap(self) -> None:
        """WorldPop は 2023 年が無いため、時間差の注意を年注記に含める。"""
        summary = self._build("worldpop", 2020)

        assert "2023" in summary["year_note"]

    def test_landscan_year_note_has_no_time_gap_warning(self) -> None:
        """LandScan は 2023 年を直接取得できるため時間差の注意は付かない。"""
        summary = self._build("landscan", 2023)

        assert "時間差" not in summary["year_note"]

    def test_band_definitions_record_units(self) -> None:
        """バンドの単位（人／セル・人/km²）を記録する。"""
        summary = self._build("landscan", 2023)

        assert summary["bands"]["1"]["unit"] == "人／セル"
        assert summary["bands"]["2"]["unit"] == "人/km²"

    def test_population_concept_differs_between_datasets(self) -> None:
        """居住人口と実効人口の違いをサマリーに残す。"""
        assert "居住人口" in self._build("worldpop", 2020)["population_concept"]
        assert "実効人口" in self._build("landscan", 2023)["population_concept"]


class TestRunEndToEnd:
    """run の統合テスト（GEE・ネットワークはモックする）。"""

    @staticmethod
    def _install_fakes(monkeypatch: pytest.MonkeyPatch, roi_bounds: tuple) -> None:
        """範囲組み立て・GEE 認証・画像選択・ダウンロードを差し替える。"""
        monkeypatch.setattr(target, "build_target_area", make_fake_build_target_area(roi_bounds))
        monkeypatch.setattr(target, "load_gee_project_id", lambda **kwargs: "fake-project")
        monkeypatch.setattr(target, "authenticate_gee", lambda project_id: None)
        monkeypatch.setattr(
            target, "select_population_image", lambda dataset_config, year: object()
        )
        monkeypatch.setattr(
            target,
            "build_native_download_url",
            lambda image, region_geojson, nodata: (
                "https://example.invalid/download",
                {"crs": "EPSG:4326", "transform": [0.01, 0, 105.0, 0, -0.01, 21.4]},
            ),
        )

        def fake_download(download_url: str, destination_path: Path, timeout: int) -> Path:
            """ROI を覆う合成 GeoTIFF を書き出す。"""
            pixel_size = 0.01
            width = int(round((roi_bounds[2] - roi_bounds[0]) / pixel_size)) + 2
            height = int(round((roi_bounds[3] - roi_bounds[1]) / pixel_size)) + 2
            profile = {
                "driver": "GTiff",
                "height": height,
                "width": width,
                "count": 1,
                "dtype": "float32",
                "crs": CRS.from_epsg(4326),
                "transform": from_origin(
                    roi_bounds[0] - pixel_size, roi_bounds[3] + pixel_size, pixel_size, pixel_size
                ),
                "nodata": target.OUTPUT_NODATA,
            }
            with rasterio.open(destination_path, "w", **profile) as destination:
                destination.write(np.full((height, width), 20.0, dtype=np.float32), 1)
            return destination_path

        monkeypatch.setattr(target, "download_gee_raster", fake_download)

    def test_writes_two_band_raster_and_summary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """取得から保存までを通しで実行し、GeoTIFF とサマリーが揃う。"""
        roi_bounds = (105.3, 21.0, 105.5, 21.2)
        self._install_fakes(monkeypatch, roi_bounds)
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")

        output_path, summary_path = target.run(
            dataset_key="worldpop",
            year=2020,
            roi_path=roi_path,
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            config_path=tmp_path / "config.csv",
            gee_project_id="fake-project",
            overwrite=True,
        )

        with rasterio.open(output_path) as destination:
            assert destination.count == 2
            assert destination.crs.to_epsg() == 4326
            assert destination.descriptions == (
                target.BAND_COUNT_NAME,
                target.BAND_DENSITY_NAME,
            )

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["dataset_key"] == "worldpop"
        assert summary["year"] == 2020
        assert summary["pixel_stats"]["valid_pixel_ratio"] == pytest.approx(1.0)
        assert summary["pixel_stats"]["covers_requested_area"] is True
        assert summary["pixel_stats"]["total_population"] > 0

    def test_trial_run_marks_summary_and_uses_distinct_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BBOX 指定時は試行実行として記録され、既定パスに _trial が付く。"""
        bbox = [105.3, 21.0, 105.4, 21.1]
        self._install_fakes(monkeypatch, tuple(bbox))
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")
        # 既定の出力ルートは data/gis/population/ で、そのまま実行すると
        # リポジトリ配下の実成果物ディレクトリへ書き込み、既存の試行成果物を
        # 上書きしてしまう。テストの副作用を tmp_path 内に閉じる
        output_root = tmp_path / "gis" / "population"
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_ROOT", output_root)

        output_path, summary_path = target.run(
            dataset_key="landscan",
            year=2023,
            roi_path=roi_path,
            bbox=bbox,
            output_path=None,
            summary_path=tmp_path / "trial_summary.json",
            config_path=tmp_path / "config.csv",
            gee_project_id="fake-project",
            overwrite=True,
        )

        assert output_path.name == "landscan_hanoi_2023_trial.tif"
        assert output_path.is_relative_to(tmp_path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["is_trial_run"] is True


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
                dataset_key="worldpop",
                year=2020,
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
