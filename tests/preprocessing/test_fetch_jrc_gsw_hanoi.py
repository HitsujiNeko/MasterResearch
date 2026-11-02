"""fetch_jrc_gsw_hanoi.py（JRC Global Surface Water 取得スクリプト）のテスト。

ネットワーク・GEE アクセスを伴わない純粋関数を対象とする。GEE のコレクション操作は
モックに差し替えて検証する。ダウンロード後の処理（クリップ・uint8 化・統計）は、
合成した小さな GeoTIFF を用いたスモークテストで CRS・バンド構成・無効値を確認する。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.common.raster_area import DEFAULT_RASTER_NODATA
from src.preprocessing import fetch_jrc_gsw_hanoi as target

PIXEL_DEG = 0.00026949458523585647
# GSW の実測ネイティブ投影（Occurrence と年次で原点の緯度が異なる）
OCCURRENCE_PROJECTION = {
    "crs": "EPSG:4326",
    "transform": [PIXEL_DEG, 0, -180.00001488697754, 0, -PIXEL_DEG, 84.00011474509029],
}
YEARLY_PROJECTION = {
    "crs": "EPSG:4326",
    "transform": [PIXEL_DEG, 0, -180.00001488697754, 0, -PIXEL_DEG, 78.00008729939917],
}


def _write_single_band(path: Path, array: np.ndarray, west: float, north: float) -> Path:
    """単バンド float32 の GeoTIFF（EPSG:4326・無効値 -9999）を書き出す。

    Args:
        path: 出力パス。
        array: 2 次元配列。
        west: 左端の経度。
        north: 上端の緯度。

    Returns:
        書き出したパス。
    """
    height, width = array.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(4326),
        transform=from_origin(west, north, PIXEL_DEG, PIXEL_DEG),
        nodata=DEFAULT_RASTER_NODATA,
    ) as destination:
        destination.write(array.astype(np.float32), 1)
    return path


def _area_covering(west: float, north: float, width: int, height: int) -> gpd.GeoDataFrame:
    """合成ラスタ全体を覆う矩形の対象範囲を作る。

    Args:
        west: 左端の経度。
        north: 上端の緯度。
        width: 画素の列数。
        height: 画素の行数。

    Returns:
        EPSG:4326 の対象範囲。
    """
    geometry = box(west, north - height * PIXEL_DEG, west + width * PIXEL_DEG, north)
    return gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326")


class TestResolvePeriods:
    """年次・月次の年月の選択のテスト。"""

    def test_observation_year_after_coverage_falls_back_to_last_year(self) -> None:
        """2022年は収録外のため、年次は 2021 年になる。"""
        assert target.resolve_yearly_year(2022) == 2021

    def test_year_inside_coverage_is_kept(self) -> None:
        """収録範囲内の年はそのまま使う。"""
        assert target.resolve_yearly_year(2000) == 2000

    def test_year_before_coverage_falls_forward_to_first_year(self) -> None:
        """収録開始前の年は 1984 年になる。"""
        assert target.resolve_yearly_year(1980) == 1984

    def test_monthly_keeps_calendar_month(self) -> None:
        """月次は暦月を保ったまま最も近い年を選ぶ（2022-09 → 2021-09）。"""
        assert target.resolve_monthly_year_month(2022, 9) == (2021, 9)

    def test_monthly_skips_months_missing_in_first_year(self) -> None:
        """1984 年 1・2 月は存在しないため 1985 年の同月になる。"""
        assert target.resolve_monthly_year_month(1980, 2) == (1985, 2)

    def test_monthly_first_available_month_is_kept(self) -> None:
        """1984 年 3 月は収録されている。"""
        assert target.resolve_monthly_year_month(1984, 3) == (1984, 3)

    @pytest.mark.parametrize("month", [0, 13])
    def test_monthly_rejects_invalid_month(self, month: int) -> None:
        """1〜12 以外の月は拒否する。"""
        with pytest.raises(ValueError, match="月は 1〜12"):
            target.resolve_monthly_year_month(2022, month)

    def test_period_gap_mentions_selected_year(self) -> None:
        """観測年と選んだ年が違うとき、説明文に年と時間差が入る。"""
        note = target.describe_period_gap(2021, date(2022, 9, 6))

        assert "2021" in note
        assert "1 年の時間差" in note

    def test_period_gap_when_years_match(self) -> None:
        """観測年と一致する場合は時間差に触れない。"""
        assert "時間差" not in target.describe_period_gap(2015, date(2015, 1, 1))


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_default_paths_include_selected_periods(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既定のファイル名に年次の年と月次の年月が入る。"""
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_DIR", tmp_path / "gis")
        monkeypatch.setattr(target, "DEFAULT_SUMMARY_DIR", tmp_path / "output")

        output_path, summary_path = target.resolve_output_paths(2021, 2021, 9, None, None)

        assert output_path.name == "jrc_gsw_hanoi_y2021_m202109.tif"
        assert summary_path.name == "jrc_gsw_hanoi_y2021_m202109_summary.json"

    def test_trial_run_gets_distinct_filename(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """試行実行では既定ファイル名に _trial が付く（全域の成果物を上書きしない）。"""
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_DIR", tmp_path / "gis")
        monkeypatch.setattr(target, "DEFAULT_SUMMARY_DIR", tmp_path / "output")

        output_path, _ = target.resolve_output_paths(2021, 2021, 9, None, None, is_trial=True)

        assert output_path.stem.endswith("_trial")

    def test_respects_explicit_paths(self, tmp_path: Path) -> None:
        """明示した出力パスはそのまま使う。"""
        output_path, summary_path = target.resolve_output_paths(
            2021, 2021, 9, tmp_path / "a.tif", tmp_path / "b.json"
        )

        assert output_path == (tmp_path / "a.tif").resolve()
        assert summary_path == (tmp_path / "b.json").resolve()


class _FakeValue:
    """getInfo() だけを持つ値オブジェクト。"""

    def __init__(self, value: Any) -> None:
        self.value = value

    def getInfo(self) -> Any:  # noqa: N802  # GEE API 名に合わせる
        """保持している値を返す。"""
        return self.value


class _FakeCollection:
    """ee.ImageCollection を模し、適用されたフィルタを記録する。"""

    def __init__(self, matched_count: int, applied: list[tuple[str, Any]]) -> None:
        self.matched_count = matched_count
        self.applied = applied

    def filter(self, condition: tuple[str, Any]) -> _FakeCollection:
        """フィルタ条件を記録する。"""
        self.applied.append(condition)
        return self

    def size(self) -> _FakeValue:
        """件数を返す。"""
        return _FakeValue(self.matched_count)

    def first(self) -> str:
        """先頭画像の代わりに識別用の文字列を返す。"""
        return "first-image"


def _install_fake_ee(monkeypatch: pytest.MonkeyPatch, matched_count: int) -> list[tuple[str, Any]]:
    """target モジュールの ee を偽物に差し替え、適用されたフィルタの記録を返す。"""
    applied: list[tuple[str, Any]] = []

    class _FakeFilter:
        @staticmethod
        def eq(property_name: str, value: Any) -> tuple[str, Any]:
            return (property_name, value)

    monkeypatch.setattr(
        target.ee, "ImageCollection", lambda asset_id: _FakeCollection(matched_count, applied)
    )
    monkeypatch.setattr(target.ee, "Image", lambda source: source)
    monkeypatch.setattr(target.ee, "Filter", _FakeFilter)
    return applied


class TestSelectSingleImage:
    """select_single_image のテスト。"""

    def test_applies_all_conditions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """年・月の条件がすべてフィルタとして適用される。"""
        applied = _install_fake_ee(monkeypatch, matched_count=1)

        image = target.select_single_image(target.MONTHLY_ASSET_ID, {"year": 2021, "month": 9})

        assert image == "first-image"
        assert applied == [("year", 2021), ("month", 9)]

    @pytest.mark.parametrize("matched_count", [0, 2])
    def test_raises_unless_exactly_one_image(
        self, monkeypatch: pytest.MonkeyPatch, matched_count: int
    ) -> None:
        """該当が 0 枚・複数枚のときは停止する。"""
        _install_fake_ee(monkeypatch, matched_count=matched_count)

        with pytest.raises(RuntimeError, match="1 枚に定まりません"):
            target.select_single_image(target.YEARLY_ASSET_ID, {"year": 2021})


class _ExprImage:
    """ee.Image を模し、適用された演算を式の文字列として記録する。"""

    def __init__(self, expr: str, parts: list[str] | None = None) -> None:
        self.expr = expr
        self.parts = parts or []
        self.band_names: list[str] | None = None

    def select(self, name: str) -> _ExprImage:
        """バンド選択を記録する。"""
        return _ExprImage(f"{self.expr}.select({name})")

    def unmask(self, value: int) -> _ExprImage:
        """マスクの穴埋めを記録する。"""
        return _ExprImage(f"{self.expr}.unmask({value})")

    def updateMask(self, mask: _ExprImage) -> _ExprImage:  # noqa: N802  # GEE API 名に合わせる
        """マスクの適用を記録する。"""
        return _ExprImage(f"{self.expr}.updateMask({mask.expr})")

    def gt(self, value: int) -> _ExprImage:
        """比較を記録する。"""
        return _ExprImage(f"{self.expr}.gt({value})")

    def And(self, other: _ExprImage) -> _ExprImage:  # noqa: N802  # GEE API 名に合わせる
        """論理積を記録する。"""
        return _ExprImage(f"{self.expr}.And({other.expr})")

    def rename(self, names: list[str]) -> _ExprImage:
        """バンド名の付け替えを記録する。"""
        self.band_names = names
        return self

    @staticmethod
    def cat(images: list[_ExprImage]) -> _ExprImage:
        """結合する各バンドの式を記録する。"""
        return _ExprImage("cat", [image.expr for image in images])


class TestBuildJrcImage:
    """build_jrc_image のテスト（無効値の意味を揃える演算の順序を確かめる）。"""

    def test_masks_and_fill_values_per_band(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Occurrence は 0、年次は 1 で穴埋めし、観測なしと値 0 だけをマスクする。"""
        monkeypatch.setattr(target.ee, "Image", _ExprImage)
        monkeypatch.setattr(
            target,
            "select_single_image",
            lambda asset_id, conditions: _ExprImage(f"{asset_id}{sorted(conditions.items())}"),
        )

        image = target.build_jrc_image(2021, 2021, 9)

        has_obs = f"{target.METADATA_ASSET_ID}.select(valid_obs).gt(0)"
        yearly = f"{target.YEARLY_ASSET_ID}[('year', 2021)].select(waterClass).unmask(1)"
        monthly = f"{target.MONTHLY_ASSET_ID}[('month', 9), ('year', 2021)].select(water)"
        assert image.parts == [
            f"{target.GLOBAL_ASSET_ID}.select(occurrence).unmask(0).updateMask({has_obs})",
            f"{yearly}.updateMask({yearly}.gt(0).And({has_obs}))",
            f"{monthly}.updateMask({monthly}.gt(0).And({has_obs}))",
        ]
        assert image.band_names == [band.name for band in target.BAND_DEFINITIONS]


class TestCheckBandProjections:
    """check_band_projections のテスト。"""

    def test_accepts_origins_differing_by_whole_pixels(self) -> None:
        """実測の GSW のように原点が整数画素だけ異なる場合は同じ格子とみなす。"""
        target.check_band_projections(
            [OCCURRENCE_PROJECTION, YEARLY_PROJECTION, OCCURRENCE_PROJECTION]
        )

    def test_rejects_half_pixel_offset(self) -> None:
        """原点が半画素ずれている場合は停止する。"""
        shifted = {
            "crs": "EPSG:4326",
            "transform": [
                PIXEL_DEG,
                0,
                -180.00001488697754 + PIXEL_DEG / 2,
                0,
                -PIXEL_DEG,
                84.00011474509029,
            ],
        }

        with pytest.raises(ValueError, match="格子が先頭バンドと揃っていません"):
            target.check_band_projections([OCCURRENCE_PROJECTION, shifted, OCCURRENCE_PROJECTION])

    def test_rejects_different_pixel_size(self) -> None:
        """画素サイズが異なる場合は停止する。"""
        coarse = {
            "crs": "EPSG:4326",
            "transform": [PIXEL_DEG * 2, 0, -180.00001488697754, 0, -PIXEL_DEG * 2, 84.0],
        }

        with pytest.raises(ValueError, match="格子が先頭バンドと揃っていません"):
            target.check_band_projections([OCCURRENCE_PROJECTION, OCCURRENCE_PROJECTION, coarse])

    def test_rejects_different_crs(self) -> None:
        """CRS が異なる場合は停止する。"""
        other_crs = {**OCCURRENCE_PROJECTION, "crs": "EPSG:3857"}

        with pytest.raises(ValueError, match="格子が先頭バンドと揃っていません"):
            target.check_band_projections([OCCURRENCE_PROJECTION, other_crs, OCCURRENCE_PROJECTION])


class TestConvertToUint8:
    """convert_to_uint8 のテスト。"""

    def test_converts_values_and_nodata(self) -> None:
        """有効値はそのまま、無効値は 255 になる。"""
        array = np.array([[0.0, 100.0], [DEFAULT_RASTER_NODATA, 3.0]], dtype=np.float32)

        converted = target.convert_to_uint8(array, DEFAULT_RASTER_NODATA)

        assert converted.dtype == np.uint8
        assert converted.tolist() == [[0, 100], [target.OUTPUT_NODATA, 3]]

    @pytest.mark.parametrize("bad_value", [1.5, -1.0, 255.0])
    def test_rejects_values_that_cannot_be_represented(self, bad_value: float) -> None:
        """小数・負値・無効値と衝突する 255 は黙って丸めず停止する。"""
        array = np.array([[bad_value, 1.0]], dtype=np.float32)

        with pytest.raises(ValueError, match="uint8 へ変換できない値"):
            target.convert_to_uint8(array, DEFAULT_RASTER_NODATA)


class TestSummarizeOccurrence:
    """summarize_occurrence のテスト。"""

    def test_counts_within_area_only(self) -> None:
        """対象範囲外の画素は数えず、閾値は「以上」で数える。"""
        occurrence = np.array([[0, 25, 50], [90, target.OUTPUT_NODATA, 100]], dtype=np.uint8)
        area_mask = np.array([[True, True, True], [True, True, False]])

        stats = target.summarize_occurrence(occurrence, area_mask)

        assert stats["area_pixels"] == 5
        assert stats["valid_pixels"] == 4
        assert stats["valid_pixel_ratio"] == pytest.approx(0.8)
        assert stats["ever_water_pixels"] == 3
        assert stats["pixels_at_or_above_threshold"] == {"25": 3, "50": 2, "75": 1, "90": 1}

    def test_empty_area_gives_zero_ratio(self) -> None:
        """対象範囲内に画素が無い場合は有効画素率 0。"""
        occurrence = np.zeros((2, 2), dtype=np.uint8)

        stats = target.summarize_occurrence(occurrence, np.zeros((2, 2), dtype=bool))

        assert stats["valid_pixel_ratio"] == 0.0


class TestProcessDownloadedRasters:
    """process_downloaded_rasters のスモークテスト。"""

    WEST = 105.80
    NORTH = 21.10

    def _sources(self, tmp_path: Path) -> list[Path]:
        """Occurrence・年次・月次の合成ラスタ（4x3 画素）を書き出す。"""
        occurrence = np.array([[0, 10, 60, 100], [0, 0, 80, 95], [DEFAULT_RASTER_NODATA, 0, 0, 50]])
        yearly = np.array([[1, 1, 3, 3], [1, 1, 2, 3], [DEFAULT_RASTER_NODATA, 1, 1, 2]])
        monthly = np.array([[1, 1, 2, 2], [1, DEFAULT_RASTER_NODATA, 2, 2], [1, 1, 1, 2]])
        return [
            _write_single_band(tmp_path / f"{name}.tif", array, self.WEST, self.NORTH)
            for name, array in (("occ", occurrence), ("yearly", yearly), ("monthly", monthly))
        ]

    def test_writes_uint8_bands_with_descriptions(self, tmp_path: Path) -> None:
        """出力は uint8・無効値 255・EPSG:4326 で、バンド名が説明に入る。"""
        output_path = tmp_path / "out.tif"

        profile, _, covers_area = target.process_downloaded_rasters(
            self._sources(tmp_path), _area_covering(self.WEST, self.NORTH, 4, 3), output_path
        )

        with rasterio.open(output_path) as source:
            assert source.count == 3
            assert source.dtypes == ("uint8", "uint8", "uint8")
            assert source.nodata == target.OUTPUT_NODATA
            assert source.crs.to_epsg() == 4326
            assert source.descriptions == tuple(band.name for band in target.BAND_DEFINITIONS)
            assert source.read(2)[2, 0] == target.OUTPUT_NODATA
        assert profile["dtype"] == "uint8"
        assert covers_area

    def test_band_statistics_follow_band_kind(self, tmp_path: Path) -> None:
        """Occurrence は閾値別の集計、分類バンドはクラス分布で集計される。"""
        _, band_stats, _ = target.process_downloaded_rasters(
            self._sources(tmp_path), _area_covering(self.WEST, self.NORTH, 4, 3), tmp_path / "o.tif"
        )

        assert band_stats["occurrence"]["valid_pixels"] == 11
        assert band_stats["occurrence"]["pixels_at_or_above_threshold"]["50"] == 5
        assert band_stats["yearly_water_class"]["filled_pixels"] == 1
        assert band_stats["monthly_water"]["valid_pixels"] == 11

    def test_rejects_wrong_number_of_sources(self, tmp_path: Path) -> None:
        """入力ファイル数がバンド定義と合わない場合は停止する。"""
        sources = self._sources(tmp_path)[:2]

        with pytest.raises(ValueError, match="入力ファイル数"):
            target.process_downloaded_rasters(
                sources, _area_covering(self.WEST, self.NORTH, 4, 3), tmp_path / "o.tif"
            )

    def test_rejects_misaligned_band(self, tmp_path: Path) -> None:
        """1 バンドだけ格子がずれている場合は重ねずに停止する。"""
        sources = self._sources(tmp_path)
        sources[2] = _write_single_band(
            tmp_path / "shifted.tif", np.ones((3, 4)), self.WEST + PIXEL_DEG, self.NORTH
        )

        with pytest.raises(ValueError, match="格子が先頭バンドと一致しません"):
            target.process_downloaded_rasters(
                sources, _area_covering(self.WEST, self.NORTH, 5, 3), tmp_path / "o.tif"
            )


class TestBuildSummary:
    """build_summary のスキーマ検査。"""

    def test_records_periods_nodata_and_provenance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """選んだ年月・無効値・収録期間・来歴が記録される。"""
        monkeypatch.setattr(target, "build_provenance", lambda script, inputs: {"script": script})

        summary = target.build_summary(
            target_date=date(2022, 9, 6),
            yearly_year=2021,
            monthly_year=2021,
            monthly_month=9,
            roi_path=tmp_path / "roi.shp",
            is_trial=False,
            area_bounds=(105.0, 20.0, 106.0, 21.0),
            projection_info={
                "occurrence": OCCURRENCE_PROJECTION,
                "yearly_water_class": YEARLY_PROJECTION,
            },
            raster_profile={"crs": "EPSG:4326"},
            band_stats={},
            covers_area=True,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out.json",
            retrieved_at="2026-10-31T00:00:00+00:00",
        )

        assert summary["dataset_version"] == "v1.4"
        assert summary["coverage_period"]["yearly"] == "1984-2021"
        assert summary["selected_periods"]["yearly_year"] == 2021
        assert summary["selected_periods"]["monthly_month"] == 9
        assert "2021" in summary["selected_periods"]["monthly_note"]
        assert summary["nodata"] == target.OUTPUT_NODATA
        assert summary["provenance"] == {"script": target.SCRIPT_NAME}
        assert set(summary["bands"]) == {"1", "2", "3"}
        # 原点の異なるバンドの投影が潰れずに別々に残る
        assert (
            summary["native_projection"]["yearly_water_class"]["transform"][5]
            == (YEARLY_PROJECTION["transform"][5])
        )
