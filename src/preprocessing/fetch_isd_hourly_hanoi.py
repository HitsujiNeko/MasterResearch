"""NOAA ISD（Integrated Surface Database）の毎時値をハノイの観測所・観測日を指定して取得する。

採用観測（衛星通過時刻）の気温を LST と並べる対比表のための入力データを取得する。
取得した CSV の読み取り・通過時刻の値の選択は
`src.analysis.compare_air_temperature_lst` が行う。

データソース:
- NOAA NCEI Access Data Service（`dataset=global-hourly`）
  `https://www.ncei.noaa.gov/access/services/data/v1`
- 観測所一覧: `https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv`

ライセンス: 米国政府の著作物（パブリックドメイン）。出典は NOAA NCEI の ISD とする。

制約メモ（2026-10-29 確認）:
- isd-history.csv で国コード `VM` のうち ROI 内にあり、2022〜2024年に記録があるのは
  `488200-99999`（NOIBAI INTL）と `488250-99999`（HA DONG）の2か所だけである。
  `488190`（HANOI (CITY)）・`488193`（HANOI/GIALAM）は1980年代で記録が終わっている。
- 年単位のファイル（`/data/global-hourly/access/{年}/{番号}.csv`）ではなく、
  Access Data Service で日時を絞って取得する。必要なのは各観測日の数時間分だけのため。
- `DATE` 列は UTC。`TMP` 列は「10倍した摂氏の整数,品質コード」の形式（例 `+0285,1`）。
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from src.common.config import PROJECT_ROOT
from src.common.http_fetch import fetch_bytes_with_retry
from src.common.paths import prepare_output_path, resolve_relative_to_project_root

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ACCESS_DATA_SERVICE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
ISD_DATASET = "global-hourly"

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "input" / "air_temperature" / "isd"

# 取得する時間帯（UTC）。通過時刻（03:23 UTC 頃）の前後の値を拾えるよう広めに取る
DEFAULT_START_HOUR = 0
DEFAULT_END_HOUR = 6

REQUEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class IsdStation:
    """ISD の観測所の識別子と位置。

    Attributes:
        station_id: Access Data Service で指定する番号（USAF 6桁＋WBAN 5桁）。
        name: isd-history.csv の観測所名。
        latitude: 緯度（WGS84）。
        longitude: 経度（WGS84）。
    """

    station_id: str
    name: str
    latitude: float
    longitude: float


# isd-history.csv（2026-10-29 取得）の値を転記した（小数第3位まで）。毎時値の CSV の座標は
# NOIBAI INTL が 21.221192, 105.807178（転記値との差は約30m）、HA DONG が 20.9666666, 105.7666666
# （1分単位の丸めで、測器の位置の不確かさは約 ±900m）である
HANOI_ISD_STATIONS: tuple[IsdStation, ...] = (
    IsdStation(station_id="48820099999", name="NOIBAI INTL", latitude=21.221, longitude=105.807),
    IsdStation(station_id="48825099999", name="HA DONG", latitude=20.967, longitude=105.767),
)

# 採用観測（observation_selection.md 5章）の衛星通過時刻（UTC）
ADOPTED_OBSERVATION_DATETIMES: tuple[str, ...] = (
    "2022-09-06T03:23:58",
    "2023-07-07T03:23:05",
    "2024-11-30T03:23:36",
)


def build_access_data_url(
    station_id: str, target_date: date, start_hour: int, end_hour: int
) -> str:
    """観測所・日付・時間帯（UTC）を指定した Access Data Service の URL を組み立てる。

    Args:
        station_id: 観測所の番号（USAF 6桁＋WBAN 5桁）。
        target_date: 取得する日付（UTC）。
        start_hour: 取得を始める時（0〜23。その時の 00 分 00 秒から）。
        end_hour: 取得を終える時（0〜23。その時の 59 分 59 秒まで）。

    Returns:
        CSV 形式で返す URL。

    Raises:
        ValueError: 時の範囲が 0〜23 でない、または開始が終了より後の場合。
    """
    if not (0 <= start_hour <= end_hour <= 23):
        raise ValueError(f"時の範囲が不正です: start_hour={start_hour}, end_hour={end_hour}")
    day = target_date.isoformat()
    query = {
        "dataset": ISD_DATASET,
        "stations": station_id,
        "startDate": f"{day}T{start_hour:02d}:00:00",
        "endDate": f"{day}T{end_hour:02d}:59:59",
        "format": "csv",
        "includeStationName": "true",
        "includeStationLocation": "1",
    }
    return f"{ACCESS_DATA_SERVICE_URL}?{urlencode(query)}"


def build_output_path(output_dir: Path, station_id: str, target_date: date) -> Path:
    """保存先のファイルパス（`{観測所番号}_{YYYYMMDD}.csv`）を返す。

    Args:
        output_dir: 保存先ディレクトリ。
        station_id: 観測所の番号。
        target_date: 取得した日付（UTC）。

    Returns:
        保存先のパス。
    """
    return output_dir / f"{station_id}_{target_date:%Y%m%d}.csv"


def validate_isd_csv(content: bytes) -> None:
    """取得した本文が ISD の CSV（`DATE` 列と `TMP` 列を持つ）かを確かめる。

    該当データが無い場合も Access Data Service はエラーにせず空の本文や
    ヘッダーのみを返すため、保存前に中身を確かめる。

    Args:
        content: 取得した本文。

    Raises:
        ValueError: 本文が空、ヘッダーに `DATE`・`TMP` が無い、またはデータ行が無い場合。
    """
    text = content.decode("utf-8-sig").strip()
    if not text:
        raise ValueError(
            "取得した本文が空です（指定した観測所・日時のデータが無い可能性があります）"
        )
    header = [column.strip().strip('"') for column in text.splitlines()[0].split(",")]
    missing = [column for column in ("DATE", "TMP") if column not in header]
    if missing:
        raise ValueError(
            f"ISD の CSV ではありません（不足列: {missing}）: 先頭行={text.splitlines()[0][:200]}"
        )
    # ヘッダーのみの CSV を保存すると、既定では取得し直さないため欠測のまま残り続ける
    data_lines = [line for line in text.splitlines()[1:] if line.strip()]
    if not data_lines:
        raise ValueError("取得した CSV にデータ行がありません（ヘッダーのみ）")


def fetch_station_day(
    station_id: str,
    target_date: date,
    output_dir: Path,
    start_hour: int,
    end_hour: int,
    overwrite: bool,
) -> Path:
    """1観測所・1日分の毎時値を取得して CSV で保存する。

    Args:
        station_id: 観測所の番号。
        target_date: 取得する日付（UTC）。
        output_dir: 保存先ディレクトリ。
        start_hour: 取得を始める時（UTC）。
        end_hour: 取得を終える時（UTC）。
        overwrite: 既存ファイルを上書きするか。`False` で既存なら取得しない。

    Returns:
        保存した（または既存の）CSV のパス。
    """
    output_path = build_output_path(output_dir, station_id, target_date)
    if output_path.exists() and not overwrite:
        logger.info(f"既存のため取得しません: {output_path}")
        return output_path
    url = build_access_data_url(station_id, target_date, start_hour, end_hour)
    logger.info(f"取得します: {url}")
    content = fetch_bytes_with_retry(url, timeout=REQUEST_TIMEOUT_SECONDS)
    validate_isd_csv(content)
    resolved = prepare_output_path(output_path)
    resolved.write_bytes(content)
    logger.info(f"保存しました: {resolved}（{len(content)} バイト）")
    return resolved


def parse_observation_dates(observation_datetimes: list[str]) -> list[date]:
    """観測日時（ISO 8601・UTC）の文字列から、重複を除いた日付を並び順を保って返す。

    Args:
        observation_datetimes: `YYYY-MM-DDTHH:MM:SS` 形式の観測日時。

    Returns:
        日付のリスト。
    """
    dates: list[date] = []
    for value in observation_datetimes:
        target_date = datetime.fromisoformat(value).date()
        if target_date not in dates:
            dates.append(target_date)
    return dates


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数のリスト。`None` の場合は `sys.argv` を使う。

    Returns:
        解析結果。
    """
    parser = argparse.ArgumentParser(
        description="NOAA ISD の毎時値をハノイの観測所・観測日を指定して取得する"
    )
    parser.add_argument(
        "--observation-datetimes",
        nargs="+",
        default=list(ADOPTED_OBSERVATION_DATETIMES),
        help="観測日時（UTC・ISO 8601）。日付部分だけを使う。既定は採用観測3件",
    )
    parser.add_argument(
        "--station-ids",
        nargs="+",
        default=[station.station_id for station in HANOI_ISD_STATIONS],
        help="観測所の番号（USAF＋WBAN）。既定はノイバイ・ハドン",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="保存先ディレクトリ（既定: data/input/air_temperature/isd）",
    )
    parser.add_argument(
        "--start-hour", type=int, default=DEFAULT_START_HOUR, help="取得を始める時（UTC）"
    )
    parser.add_argument(
        "--end-hour", type=int, default=DEFAULT_END_HOUR, help="取得を終える時（UTC）"
    )
    parser.add_argument("--overwrite", action="store_true", help="既存ファイルを上書きする")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """エントリーポイント。

    Args:
        argv: 引数のリスト。`None` の場合は `sys.argv` を使う。
    """
    args = parse_arguments(argv)
    output_dir = (
        resolve_relative_to_project_root(args.output_dir, project_root=PROJECT_ROOT)
        or DEFAULT_OUTPUT_DIR
    )
    target_dates = parse_observation_dates(args.observation_datetimes)
    saved_paths = [
        fetch_station_day(
            station_id, target_date, output_dir, args.start_hour, args.end_hour, args.overwrite
        )
        for station_id in args.station_ids
        for target_date in target_dates
    ]
    print(f"{len(saved_paths)} 件の CSV を保存しました: {output_dir}")


if __name__ == "__main__":
    main()
