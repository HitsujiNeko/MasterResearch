"""compare_air_temperature_lst.py のテスト。

ISD の気温の読み取り・最近傍時刻の選択・ERA5-Land の内挿と単位換算・LST の窓平均と
ROI 統計・対比表の行の組み立てを確認する。GEE は偽のオブジェクトに差し替える。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import src.analysis.compare_air_temperature_lst as target
from src.preprocessing.fetch_isd_hourly_hanoi import IsdStation

PASS_TIME = datetime(2022, 9, 6, 3, 23, 58, tzinfo=timezone.utc)

# テスト用ラスタの格子（EPSG:4326・0.01度・5×5画素、左上 (105.0, 21.05)）
RASTER_ORIGIN_LON = 105.0
RASTER_ORIGIN_LAT = 21.05
RASTER_RES = 0.01


def _pixel_center(row: int, col: int) -> tuple[float, float]:
    """テスト用ラスタの画素中心の (経度, 緯度) を返す。

    Args:
        row: 行番号。
        col: 列番号。

    Returns:
        画素中心の (経度, 緯度)。
    """
    return RASTER_ORIGIN_LON + (col + 0.5) * RASTER_RES, RASTER_ORIGIN_LAT - (
        row + 0.5
    ) * RASTER_RES


def _write_raster(
    path: Path, values: np.ndarray, nodata: float | None = None, crs: str = "EPSG:4326"
) -> Path:
    """テスト用の1バンド GeoTIFF（既定は EPSG:4326）を書き出す。

    Args:
        path: 保存先。
        values: 画素値（2次元）。
        nodata: nodata 値。
        crs: CRS（変換行列は経緯度の値のまま使う）。

    Returns:
        保存先のパス。
    """
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float64",
        crs=crs,
        transform=from_origin(RASTER_ORIGIN_LON, RASTER_ORIGIN_LAT, RASTER_RES, RASTER_RES),
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)
    return path


def _write_isd_csv(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """テスト用の ISD の CSV（重複列を含む実データと同じ並びの一部）を書き出す。

    Args:
        path: 保存先。
        rows: (DATE, REPORT_TYPE, TMP) の並び。

    Returns:
        保存先のパス。
    """
    lines = ['"STATION","DATE","REPORT_TYPE","CALL_SIGN","TMP","CALL_SIGN"']
    lines += [
        f'"48820099999","{date}","{report}","99999","{tmp}","99999"' for date, report, tmp in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestParseIsdTemperature:
    """ISD の TMP 列の換算。"""

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("+0285,1", 28.5),
            ("+0320,1", 32.0),
            ("-0015,1", -1.5),
            ("+0217,5", 21.7),
            ("+0300,9", 30.0),
        ],
    )
    def test_valid_values(self, field: str, expected: float) -> None:
        """10倍した摂氏の整数を摂氏に戻す（品質コードが合格なら採る）。"""
        assert target.parse_isd_temperature(field) == pytest.approx(expected)

    def test_missing_value_is_none(self) -> None:
        """欠測（+9999）は None。"""
        assert target.parse_isd_temperature("+9999,9") is None

    @pytest.mark.parametrize("quality", ["2", "3", "6", "7"])
    def test_rejected_quality_is_none(self, quality: str) -> None:
        """疑わしい・誤りの品質コードは None。"""
        assert target.parse_isd_temperature(f"+0300,{quality}") is None

    @pytest.mark.parametrize("field", ["+0300", "", "+0300,1,1"])
    def test_invalid_format_raises(self, field: str) -> None:
        """「値,品質コード」の形でなければ例外。"""
        with pytest.raises(ValueError, match="TMP"):
            target.parse_isd_temperature(field)


class TestLoadIsdTemperatures:
    """ISD の CSV の読み込み。"""

    def test_drops_missing_and_parses_utc(self, tmp_path: Path) -> None:
        """欠測行を除き、時刻を UTC のタイムゾーンつきで読む（重複列があっても読める）。"""
        path = _write_isd_csv(
            tmp_path / "isd.csv",
            [
                ("2022-09-06T03:00:00", "FM-15", "+0320,1"),
                ("2022-09-06T03:30:00", "FM-15", "+9999,9"),
                ("2022-09-06T04:00:00", "FM-12", "+0331,1"),
            ],
        )
        table = target.load_isd_temperatures(path)
        assert list(table["temperature_c"]) == pytest.approx([32.0, 33.1])
        assert list(table["report_type"]) == ["FM-15", "FM-12"]
        assert str(table["observed_at"].dt.tz) == "UTC"
        assert table["observed_at"].iloc[1] == pd.Timestamp("2022-09-06T04:00:00Z")

    def test_drops_rows_without_date(self, tmp_path: Path) -> None:
        """時刻が空の行は、許容幅の判定をすり抜けないよう除く。"""
        path = _write_isd_csv(
            tmp_path / "isd.csv",
            [("", "FM-15", "+0330,1"), ("2022-09-06T03:30:00", "FM-15", "+0320,1")],
        )
        table = target.load_isd_temperatures(path)
        assert len(table) == 1
        value = target.select_nearest_isd_value(table, PASS_TIME)
        assert value is not None
        assert value.temperature_c == pytest.approx(32.0)


class TestSelectNearestIsdValue:
    """通過時刻に最も近い観測の選択。"""

    @staticmethod
    def _table(times: list[str], values: list[float]) -> pd.DataFrame:
        """観測時刻と気温から表を作る。"""
        return pd.DataFrame(
            {
                "observed_at": pd.to_datetime(times, utc=True),
                "report_type": ["FM-15"] * len(times),
                "temperature_c": values,
            }
        )

    def test_picks_nearest_after_pass(self) -> None:
        """03:23:58 の通過なら 03:00 より 03:30 が近い（差は約 +6 分）。"""
        table = self._table(
            ["2022-09-06T03:00:00", "2022-09-06T03:30:00", "2022-09-06T04:00:00"], [32, 33, 34]
        )
        value = target.select_nearest_isd_value(table, PASS_TIME)
        assert value is not None
        assert value.temperature_c == 33
        assert value.offset_minutes == pytest.approx(6 + 2 / 60)
        assert value.observed_at == datetime(2022, 9, 6, 3, 30, tzinfo=timezone.utc)

    def test_negative_offset_when_only_before(self) -> None:
        """通過前の観測しか無ければ時刻差は負になる（3時間ごとの SYNOP を想定）。"""
        table = self._table(
            ["2022-09-06T00:00:00", "2022-09-06T03:00:00", "2022-09-06T06:00:00"], [27, 31.6, 34]
        )
        value = target.select_nearest_isd_value(table, PASS_TIME)
        assert value is not None
        assert value.temperature_c == pytest.approx(31.6)
        assert value.offset_minutes == pytest.approx(-(23 + 58 / 60))

    def test_tie_prefers_before_pass(self) -> None:
        """前後で時刻差が同じなら通過前の観測を採る。"""
        pass_time = datetime(2022, 9, 6, 3, 15, tzinfo=timezone.utc)
        table = self._table(["2022-09-06T03:30:00", "2022-09-06T03:00:00"], [33, 32])
        value = target.select_nearest_isd_value(table, pass_time)
        assert value is not None
        assert value.temperature_c == 32

    def test_offset_at_limit_is_kept(self) -> None:
        """通過時刻との差が許容幅ちょうど（90分）なら採る。"""
        pass_time = datetime(2022, 9, 6, 1, 30, tzinfo=timezone.utc)
        table = self._table(["2022-09-06T03:00:00"], [31.6])
        value = target.select_nearest_isd_value(table, pass_time)
        assert value is not None
        assert value.offset_minutes == pytest.approx(90.0)

    def test_offset_beyond_limit_is_none(self) -> None:
        """03:00 が欠けて 06:00 しか無いなど、許容幅を超える観測は欠測にする。"""
        table = self._table(["2022-09-06T00:00:00", "2022-09-06T06:00:00"], [27.0, 35.2])
        assert target.select_nearest_isd_value(table, PASS_TIME) is None

    def test_custom_limit(self) -> None:
        """許容幅を引数で狭めると、6分ずれの観測も欠測になる。"""
        table = self._table(["2022-09-06T03:30:00"], [33.0])
        assert target.select_nearest_isd_value(table, PASS_TIME, max_offset_minutes=5) is None

    def test_empty_table_is_none(self) -> None:
        """有効な観測が無ければ None。"""
        assert target.select_nearest_isd_value(self._table([], []), PASS_TIME) is None


class TestEra5Interpolation:
    """ERA5-Land の正時の選択・内挿・単位換算。"""

    def test_bracketing_hours(self) -> None:
        """03:23:58 は 03:00 と 04:00 ではさむ。"""
        before, after = target.bracketing_hours(PASS_TIME)
        assert before == datetime(2022, 9, 6, 3, tzinfo=timezone.utc)
        assert after == datetime(2022, 9, 6, 4, tzinfo=timezone.utc)

    def test_bracketing_hours_on_the_hour(self) -> None:
        """正時ちょうどなら、その正時と1時間後。"""
        before, after = target.bracketing_hours(datetime(2022, 9, 6, 3, tzinfo=timezone.utc))
        assert before == datetime(2022, 9, 6, 3, tzinfo=timezone.utc)
        assert after == datetime(2022, 9, 6, 4, tzinfo=timezone.utc)

    def test_interpolate_linear(self) -> None:
        """区間の中点・端点で正しい値になる。"""
        t0 = datetime(2022, 9, 6, 3, tzinfo=timezone.utc)
        t1 = datetime(2022, 9, 6, 4, tzinfo=timezone.utc)
        mid = datetime(2022, 9, 6, 3, 30, tzinfo=timezone.utc)
        assert target.interpolate_linear(mid, t0, 300.0, t1, 302.0) == pytest.approx(301.0)
        assert target.interpolate_linear(t0, t0, 300.0, t1, 302.0) == pytest.approx(300.0)
        assert target.interpolate_linear(t1, t0, 300.0, t1, 302.0) == pytest.approx(302.0)

    def test_interpolate_linear_rejects_outside(self) -> None:
        """区間の外・長さ0の区間は例外。"""
        t0 = datetime(2022, 9, 6, 3, tzinfo=timezone.utc)
        t1 = datetime(2022, 9, 6, 4, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="外"):
            target.interpolate_linear(
                datetime(2022, 9, 6, 5, tzinfo=timezone.utc), t0, 1.0, t1, 2.0
            )
        with pytest.raises(ValueError, match="区間"):
            target.interpolate_linear(t0, t0, 1.0, t0, 2.0)

    def test_kelvin_to_celsius(self) -> None:
        """273.15 K は 0°C。"""
        assert target.kelvin_to_celsius(273.15) == pytest.approx(0.0)
        assert target.kelvin_to_celsius(303.15) == pytest.approx(30.0)

    def test_interpolate_era5_to_pass_time(self) -> None:
        """K の値を通過時刻へ内挿して °C で返し、欠けた地点は None にする。"""
        before, after = target.bracketing_hours(PASS_TIME)
        weight = (23 * 60 + 58) / 3600
        result = target.interpolate_era5_to_pass_time(
            PASS_TIME,
            before,
            {"ROI": 300.15, "A": 301.15, "B": None},
            after,
            {"ROI": 302.15, "A": None, "B": 303.15},
        )
        assert result["ROI"] == pytest.approx(27.0 + 2.0 * weight)
        assert result["A"] is None
        assert result["B"] is None


class _FakeEeObject:
    """GEE のサーバー側オブジェクトの代わり（`getInfo` で決めた値を返す）。"""

    def __init__(self, value: Any = None) -> None:
        self._value = value

    def getInfo(self) -> Any:  # noqa: N802  GEE の API 名に合わせる
        """決めた値を返す。"""
        return self._value


def _install_fake_ee(
    monkeypatch: pytest.MonkeyPatch, size: int, roi_k: float | None, point_k: dict
) -> dict:
    """`target.ee` を偽のモジュールに差し替え、呼び出しを記録する。

    Args:
        monkeypatch: 差し替え用のフィクスチャ。
        size: 画像の枚数（0 なら画像なし）。
        roi_k: ROI 平均として返す値（K）。
        point_k: 点の (経度, 緯度) ごとに返す値（K）。含まない点は null を返す。

    Returns:
        呼び出しの記録。
    """
    recorded: dict[str, Any] = {"reducers": [], "scales": []}
    roi_marker = "ROI_GEOMETRY"

    class FakeImage:
        def select(self, band: str) -> FakeImage:
            recorded["band"] = band
            return self

        def reduceRegion(self, **kwargs: Any) -> SimpleNamespace:  # noqa: N802
            recorded["reducers"].append(kwargs["reducer"])
            recorded["scales"].append(kwargs["scale"])
            geometry = kwargs["geometry"]
            value = roi_k if geometry == roi_marker else point_k.get(geometry)
            return SimpleNamespace(get=lambda band: value)

    class FakeCollection:
        def __init__(self, collection_id: str) -> None:
            recorded["collection_id"] = collection_id

        def filterDate(self, start: Any, end: Any) -> FakeCollection:  # noqa: N802
            recorded["filter"] = (start, end)
            return self

        def size(self) -> _FakeEeObject:
            return _FakeEeObject(size)

        def first(self) -> FakeImage:
            return FakeImage()

    class FakeDate:
        def __init__(self, value: str) -> None:
            self.value = value

        def advance(self, amount: int, unit: str) -> tuple:
            return (self.value, amount, unit)

    class FakeGeometry:
        def __new__(cls, geo_interface: Any) -> str:
            return roi_marker

        @staticmethod
        def Point(coordinates: list[float]) -> tuple[float, ...]:  # noqa: N802
            return tuple(coordinates)

    def fake_dictionary(values: dict) -> _FakeEeObject:
        recorded["dictionary_keys"] = list(values)
        return _FakeEeObject(dict(values))

    fake_ee = SimpleNamespace(
        Date=FakeDate,
        ImageCollection=FakeCollection,
        Reducer=SimpleNamespace(mean=lambda: "mean", first=lambda: "first"),
        Geometry=FakeGeometry,
        Dictionary=fake_dictionary,
    )
    monkeypatch.setattr(target, "ee", fake_ee)
    return recorded


class TestFetchEra5LandValuesK:
    """ERA5-Land の1時間分の取得（GEE は偽物）。"""

    STATIONS = (
        IsdStation("A", "STATION A", 21.2, 105.8),
        IsdStation("B", "STATION B", 21.0, 105.7),
    )

    def test_returns_roi_and_station_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ROI 平均と観測所の値を返し、標本の無い観測所は None にする。"""
        recorded = _install_fake_ee(
            monkeypatch, size=1, roi_k=300.5, point_k={(105.8, 21.2): 301.0}
        )
        values = target.fetch_era5_land_values_k(
            datetime(2022, 9, 6, 3, tzinfo=timezone.utc),
            box(105.5, 20.8, 106.0, 21.3),
            self.STATIONS,
        )
        assert values == {"ROI": 300.5, "A": 301.0, "B": None}
        assert recorded["collection_id"] == "ECMWF/ERA5_LAND/HOURLY"
        assert recorded["band"] == "temperature_2m"
        # ROI は平均、観測所の点は first で、いずれもネイティブ解像度で集計する
        assert recorded["reducers"] == ["mean", "first", "first"]
        assert set(recorded["scales"]) == {target.ERA5_LAND_SCALE_METERS}
        assert recorded["dictionary_keys"] == ["ROI", "A", "B"]
        assert recorded["filter"][1] == ("2022-09-06T03:00:00+00:00", 1, "hour")

    def test_missing_image_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """対象の正時の画像が無ければ例外。"""
        _install_fake_ee(monkeypatch, size=0, roi_k=None, point_k={})
        with pytest.raises(ValueError, match="見つかりません"):
            target.fetch_era5_land_values_k(
                datetime(2022, 9, 6, 3, tzinfo=timezone.utc),
                box(105.5, 20.8, 106.0, 21.3),
                self.STATIONS,
            )


class TestReadLstWindow:
    """観測所付近の LST の窓。"""

    def test_center_window(self, tmp_path: Path) -> None:
        """内部の画素なら 3×3 を読む。"""
        values = np.arange(25, dtype=np.float64).reshape(5, 5)
        path = _write_raster(tmp_path / "lst.tif", values)
        window = target.read_lst_window(path, *_pixel_center(2, 2), size=3)
        np.testing.assert_array_equal(window, values[1:4, 1:4])

    def test_corner_window_is_truncated(self, tmp_path: Path) -> None:
        """角の画素ならラスタの内側だけ（2×2）に切り詰める。"""
        values = np.arange(25, dtype=np.float64).reshape(5, 5)
        path = _write_raster(tmp_path / "lst.tif", values)
        window = target.read_lst_window(path, *_pixel_center(0, 4), size=3)
        np.testing.assert_array_equal(window, values[0:2, 3:5])

    def test_nodata_becomes_nan(self, tmp_path: Path) -> None:
        """nodata 値は NaN にする（NaN の画素も NaN のまま）。"""
        values = np.full((5, 5), 30.0)
        values[2, 2] = -9999.0
        values[1, 1] = np.nan
        path = _write_raster(tmp_path / "lst.tif", values, nodata=-9999.0)
        window = target.read_lst_window(path, *_pixel_center(2, 2), size=3)
        assert np.isnan(window[1, 1])
        assert np.isnan(window[0, 0])
        assert np.isfinite(window).sum() == 7

    def test_non_geographic_raster_raises(self, tmp_path: Path) -> None:
        """EPSG:4326 でないラスタは、経緯度で画素を探せないため例外。"""
        path = _write_raster(tmp_path / "lst.tif", np.zeros((5, 5)), crs="EPSG:32648")
        with pytest.raises(ValueError, match="EPSG:4326"):
            target.read_lst_window(path, *_pixel_center(2, 2), size=3)

    def test_outside_raises(self, tmp_path: Path) -> None:
        """ラスタの範囲外の座標は例外。"""
        path = _write_raster(tmp_path / "lst.tif", np.zeros((5, 5)))
        with pytest.raises(ValueError, match="範囲外"):
            target.read_lst_window(path, 104.0, 21.0, size=3)

    @pytest.mark.parametrize("size", [0, 2, -3])
    def test_invalid_size_raises(self, tmp_path: Path, size: int) -> None:
        """窓の大きさが正の奇数でなければ例外。"""
        path = _write_raster(tmp_path / "lst.tif", np.zeros((5, 5)))
        with pytest.raises(ValueError, match="奇数"):
            target.read_lst_window(path, *_pixel_center(2, 2), size=size)


class TestReadLstInRoi:
    """ROI 内の LST の読み込み。"""

    def test_only_valid_pixels_inside_roi(self, tmp_path: Path) -> None:
        """画素中心が ROI 内の画素だけを採り、NaN を除く。"""
        values = np.arange(25, dtype=np.float64).reshape(5, 5)
        values[0, 0] = np.nan
        path = _write_raster(tmp_path / "lst.tif", values)
        # 左上 2×2 画素（行0〜1・列0〜1）を覆う ROI
        roi = gpd.GeoDataFrame(geometry=[box(105.0, 21.03, 105.02, 21.05)], crs="EPSG:4326")
        selected = target.read_lst_in_roi(path, roi)
        assert sorted(selected.tolist()) == [1.0, 5.0, 6.0]

    def test_roi_crs_is_transformed(self, tmp_path: Path) -> None:
        """投影座標系の ROI もラスタの CRS へ変換して重ねる。"""
        values = np.arange(25, dtype=np.float64).reshape(5, 5)
        path = _write_raster(tmp_path / "lst.tif", values)
        roi = gpd.GeoDataFrame(geometry=[box(105.0, 21.03, 105.02, 21.05)], crs="EPSG:4326").to_crs(
            "EPSG:32648"
        )
        selected = target.read_lst_in_roi(path, roi)
        assert sorted(selected.tolist()) == [0.0, 1.0, 5.0, 6.0]


class TestSummarizeLst:
    """LST の統計量。"""

    def test_statistics_ignore_nan(self) -> None:
        """NaN を除いて平均・最小・最大・母標準偏差と画素数を求める。"""
        summary = target.summarize_lst(np.array([[30.0, 32.0], [np.nan, 34.0]]))
        assert summary["lst_mean_c"] == pytest.approx(32.0)
        assert summary["lst_min_c"] == pytest.approx(30.0)
        assert summary["lst_max_c"] == pytest.approx(34.0)
        assert summary["lst_std_c"] == pytest.approx(np.std([30.0, 32.0, 34.0]))
        assert summary["lst_valid_pixels"] == 3

    def test_all_nan_gives_nan_and_zero(self) -> None:
        """有効画素が無ければ統計量は NaN・画素数は 0。"""
        summary = target.summarize_lst(np.full((3, 3), np.nan))
        assert math.isnan(summary["lst_mean_c"])
        assert summary["lst_valid_pixels"] == 0


class TestBuildSiteRow:
    """対比表の行の組み立て。"""

    LST_SUMMARY = {
        "lst_mean_c": 35.0,
        "lst_min_c": 34.0,
        "lst_max_c": 36.0,
        "lst_std_c": 0.5,
        "lst_valid_pixels": 9,
    }

    def test_station_row_differences(self) -> None:
        """観測所の行は LST − 観測所の気温・LST − ERA5-Land を求め、現地時刻を UTC+7 で出す。"""
        isd_value = target.NearestIsdValue(
            temperature_c=32.0,
            observed_at=datetime(2022, 9, 6, 3, 30, tzinfo=timezone.utc),
            offset_minutes=6.03,
            report_type="FM-15",
        )
        row = target.build_site_row(
            PASS_TIME,
            "48820099999",
            "NOIBAI INTL",
            (105.807, 21.221),
            self.LST_SUMMARY,
            "3x3",
            isd_value,
            31.0,
        )
        assert row["observation_datetime_utc"] == "2022-09-06T03:23:58"
        assert row["observation_local_time"] == "10:23"
        assert row["lst_minus_isd_c"] == pytest.approx(3.0)
        assert row["lst_minus_era5_land_c"] == pytest.approx(4.0)
        assert row["isd_observed_at_utc"] == "2022-09-06T03:30:00"
        assert row["longitude"] == pytest.approx(105.807)

    def test_roi_row_has_no_isd(self) -> None:
        """ROI の行は観測所の値が欠測で、LST − 観測所の気温も NaN。"""
        row = target.build_site_row(
            PASS_TIME, "ROI", "ROI", None, self.LST_SUMMARY, "ROI", None, None
        )
        assert math.isnan(row["isd_temperature_c"])
        assert math.isnan(row["lst_minus_isd_c"])
        assert math.isnan(row["lst_minus_era5_land_c"])
        assert row["isd_observed_at_utc"] == ""
        assert math.isnan(row["latitude"])


class TestBuildObservationRows:
    """1観測分の行（ROI と観測所）の組み立て。"""

    def test_rows_for_roi_and_stations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ROI と観測所の行を作り、ISD の CSV が無い観測所は欠測にする。"""
        lon_a, lat_a = _pixel_center(2, 2)
        lon_b, lat_b = _pixel_center(0, 0)
        stations = (
            IsdStation("A", "STATION A", lat_a, lon_a),
            IsdStation("B", "STATION B", lat_b, lon_b),
        )
        monkeypatch.setattr(target, "HANOI_ISD_STATIONS", stations)
        lst_path = _write_raster(tmp_path / "lst.tif", np.full((5, 5), 35.0))
        isd_dir = tmp_path / "isd"
        isd_dir.mkdir()
        _write_isd_csv(isd_dir / "A_20220906.csv", [("2022-09-06T03:30:00", "FM-15", "+0320,1")])
        roi = gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.05, 21.05)], crs="EPSG:4326")

        rows = target.build_observation_rows(
            "2022-09-06T03:23:58", lst_path, roi, isd_dir, {"ROI": 30.0, "A": 31.0, "B": None}
        )

        assert [row["site_id"] for row in rows] == ["ROI", "A", "B"]
        assert rows[0]["lst_valid_pixels"] == 25
        assert rows[0]["lst_minus_era5_land_c"] == pytest.approx(5.0)
        assert rows[1]["lst_valid_pixels"] == 9
        assert rows[1]["lst_minus_isd_c"] == pytest.approx(3.0)
        assert rows[1]["lst_minus_era5_land_c"] == pytest.approx(4.0)
        assert rows[2]["lst_valid_pixels"] == 4
        assert math.isnan(rows[2]["isd_temperature_c"])
        assert math.isnan(rows[2]["era5_land_temperature_c"])


class TestAdoptedObservations:
    """採用観測と LST の対応。"""

    def test_every_observation_has_lst_path(self) -> None:
        """採用観測3件すべてに LST GeoTIFF の相対パスがあり、ファイル名に観測時刻が入る。"""
        for observation in target.ADOPTED_OBSERVATION_DATETIMES:
            relative = target.LST_RELATIVE_PATHS[observation]
            stamp = datetime.fromisoformat(observation).strftime("%Y%m%d_%H%M%S")
            assert f"{stamp}Z.tif" in relative
