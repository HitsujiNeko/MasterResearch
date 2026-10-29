"""fetch_isd_hourly_hanoi.py のテスト。

通信（`fetch_bytes_with_retry`）はモックに差し替え、URL の組み立て・本文の検証・
保存と既存ファイルの扱い・観測日の抽出を確認する。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import src.preprocessing.fetch_isd_hourly_hanoi as target

VALID_CSV = (
    b'"STATION","DATE","REPORT_TYPE","TMP"\n"48820099999","2022-09-06T03:00:00","FM-15","+0320,1"\n'
)


class TestBuildAccessDataUrl:
    """Access Data Service の URL の組み立て。"""

    def test_query_has_station_and_time_range(self) -> None:
        """観測所・データセット・時間帯（UTC）が問い合わせ条件に入る。"""
        url = target.build_access_data_url("48820099999", date(2022, 9, 6), 0, 6)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == target.ACCESS_DATA_SERVICE_URL
        assert query["dataset"] == ["global-hourly"]
        assert query["stations"] == ["48820099999"]
        assert query["startDate"] == ["2022-09-06T00:00:00"]
        assert query["endDate"] == ["2022-09-06T06:59:59"]
        assert query["format"] == ["csv"]

    def test_hours_are_zero_padded(self) -> None:
        """1桁の時は2桁にそろえる。"""
        query = parse_qs(
            urlparse(target.build_access_data_url("x", date(2024, 11, 30), 3, 3)).query
        )
        assert query["startDate"] == ["2024-11-30T03:00:00"]
        assert query["endDate"] == ["2024-11-30T03:59:59"]

    @pytest.mark.parametrize(("start_hour", "end_hour"), [(-1, 6), (0, 24), (5, 4)])
    def test_invalid_hour_range_raises(self, start_hour: int, end_hour: int) -> None:
        """0〜23 の外、または開始が終了より後なら例外。"""
        with pytest.raises(ValueError, match="時の範囲"):
            target.build_access_data_url("x", date(2022, 9, 6), start_hour, end_hour)


class TestBuildOutputPath:
    """保存先のファイル名。"""

    def test_name_has_station_and_date(self, tmp_path: Path) -> None:
        """`{観測所番号}_{YYYYMMDD}.csv` になる。"""
        path = target.build_output_path(tmp_path, "48825099999", date(2023, 7, 7))
        assert path == tmp_path / "48825099999_20230707.csv"


class TestValidateIsdCsv:
    """取得した本文の検証。"""

    def test_valid_csv_passes(self) -> None:
        """`DATE`・`TMP` 列があれば通る（BOM 付きも可）。"""
        target.validate_isd_csv(VALID_CSV)
        target.validate_isd_csv(b"\xef\xbb\xbf" + VALID_CSV)

    def test_empty_body_raises(self) -> None:
        """空の本文は例外（データが無い観測所・日時）。"""
        with pytest.raises(ValueError, match="空"):
            target.validate_isd_csv(b"  \n")

    def test_missing_tmp_column_raises(self) -> None:
        """`TMP` 列が無ければ例外（エラーメッセージなど CSV でない本文）。"""
        with pytest.raises(ValueError, match="TMP"):
            target.validate_isd_csv(b'"STATION","DATE"\n"x","2022-09-06T03:00:00"\n')


class TestFetchStationDay:
    """1観測所・1日分の取得と保存。"""

    def test_saves_fetched_content(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """取得した本文をそのまま保存し、取得先 URL に観測所と日付が入る。"""
        calls: list[str] = []

        def fake_fetch(url: str, timeout: int) -> bytes:
            calls.append(url)
            return VALID_CSV

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)
        saved = target.fetch_station_day(
            "48820099999", date(2022, 9, 6), tmp_path / "isd", 0, 6, overwrite=False
        )
        assert saved.read_bytes() == VALID_CSV
        assert saved.name == "48820099999_20220906.csv"
        assert len(calls) == 1
        assert "stations=48820099999" in calls[0]

    def test_existing_file_is_not_refetched(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既存ファイルがあり上書き指定が無ければ取得しない。"""
        existing = target.build_output_path(tmp_path, "48820099999", date(2022, 9, 6))
        existing.write_bytes(b"old")

        def fail_fetch(url: str, timeout: int) -> bytes:
            raise AssertionError("取得してはいけない")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fail_fetch)
        saved = target.fetch_station_day(
            "48820099999", date(2022, 9, 6), tmp_path, 0, 6, overwrite=False
        )
        assert saved.read_bytes() == b"old"

    def test_overwrite_refetches(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """上書き指定があれば既存ファイルを取得し直す。"""
        existing = target.build_output_path(tmp_path, "48820099999", date(2022, 9, 6))
        existing.write_bytes(b"old")
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda url, timeout: VALID_CSV)
        saved = target.fetch_station_day(
            "48820099999", date(2022, 9, 6), tmp_path, 0, 6, overwrite=True
        )
        assert saved.read_bytes() == VALID_CSV

    def test_invalid_content_is_not_saved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """検証に失敗した本文はファイルを作らない。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda url, timeout: b"")
        with pytest.raises(ValueError):
            target.fetch_station_day(
                "48820099999", date(2022, 9, 6), tmp_path, 0, 6, overwrite=False
            )
        assert not target.build_output_path(tmp_path, "48820099999", date(2022, 9, 6)).exists()


class TestParseObservationDates:
    """観測日時から日付を取り出す。"""

    def test_dates_are_unique_and_ordered(self) -> None:
        """同じ日の観測は1つにまとめ、入力の順を保つ。"""
        dates = target.parse_observation_dates(
            ["2023-07-07T03:23:05", "2022-09-06T03:23:58", "2023-07-07T03:23:29"]
        )
        assert dates == [date(2023, 7, 7), date(2022, 9, 6)]

    def test_adopted_observations_give_three_dates(self) -> None:
        """採用観測3件は3つの日付になる。"""
        dates = target.parse_observation_dates(list(target.ADOPTED_OBSERVATION_DATETIMES))
        assert dates == [date(2022, 9, 6), date(2023, 7, 7), date(2024, 11, 30)]
