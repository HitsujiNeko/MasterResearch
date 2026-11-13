"""LST 算出の放射率を切り替えて 1 観測分を出力する、放射率の感度分析用スクリプト。

分析に用いる LST（SMW 法）は、放射率を同じシーンの NDVI → FVC から求める
（ε = 0.99×FVC + (1−FVC)×ε_bare）。説明変数の NDVI が目的変数の算出式に入るため、
放射率を NDVI に依存させない対照として、ASTER GEDv3 の静的な放射率（EM0）による
LST を作り、両者の差を調べる。

観測を UTC の観測日時で 1 つに限定し、NDVI 版（`ndvi`）と EM0 版（`em0`）の LST と
放射率（`EM` バンド）を、放射率ごとに別の Google Drive フォルダへ GeoTIFF で出力する。
LST の出力条件（雲マスク・ROI クリップ・EPSG・30 m）は `gee_search_satellite_data.py` と
同一で、ファイル名の形式も既存と同じにする（`urban_params` がファイル名からテーブル名を
導くため）。起動したタスクの一覧は来歴つきの JSON に記録する。
`gee_search_satellite_data.py`・`gee_calc_LST.py` の結果 CSV には書き込まない。

使い方（プロジェクトルートで実行）:

    python -m src.gee.gee_export_lst_emissivity_variants --observation-datetime 2022-09-06T03:23:58

依存: earthengine-api。GEE の認証と、設定 CSV
（`data/input/gee_calc_LST_info.csv`）の `gee_project_id`・`roi_shapefile_path`・
`output_epsg` を用いる。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import ee

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, resolve_existing_path
from src.common.summary import build_provenance, save_summary
from src.gee.gee_calc_LST import (
    authenticate_gee,
    build_export_description,
    load_config,
    load_roi_from_shapefile,
)
from src.gee.gee_search_satellite_data import (
    build_lst_image,
    export_indices_to_drive,
    export_lst_to_drive,
    get_raw_landsat_collections,
)
from src.module.landsat_sensor import DEFAULT_SENSOR, get_sensor_label, validate_sensor

SCRIPT_NAME = "src.gee.gee_export_lst_emissivity_variants"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"
DEFAULT_OUTPUT_ROOT = Path("data") / "output" / "lst_emissivity_sensitivity"
# ダウンロードした GeoTIFF の配置先（既存の data/satellite/lst/ を上書きしないよう分ける）
LOCAL_PLACEMENT_ROOT = Path("data") / "satellite" / "lst_emissivity_sensitivity"
DRIVE_FOLDER_PREFIX = "MasterResearch_Data_LST_emissivity"
OBSERVATION_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# 放射率の種類 -> `calculate_lst_smw` の use_ndvi。ndvi が分析に用いる LST の算出条件
EMISSIVITY_VARIANTS: dict[str, bool] = {"ndvi": True, "em0": False}
EMISSIVITY_BAND = "EM"
LST_FILE_PREFIX = "LST"
EMISSIVITY_FILE_PREFIX = "EMIS"

EXPORT_SUMMARY_NAME = "export_tasks.json"

# 出力値に影響するが src/common の外にあるコード（来歴の監視対象に加える）
EXTRA_WATCH_PATHS: tuple[str, ...] = (
    "src/gee/gee_calc_LST.py",
    "src/gee/gee_search_satellite_data.py",
    "src/module/lst_smw.py",
    "src/module/landsat_sensor.py",
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_observation_datetime(observation_datetime_utc: str) -> dt.datetime:
    """観測日時の文字列を検証し、datetime に変換する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        dt.datetime: タイムゾーンなしの datetime（UTC として扱う）。

    Raises:
        ValueError: 形式が `YYYY-MM-DDTHH:MM:SS` でない場合。
    """
    try:
        return dt.datetime.strptime(observation_datetime_utc, OBSERVATION_DATETIME_FORMAT)
    except ValueError as error:
        raise ValueError(
            "観測日時は YYYY-MM-DDTHH:MM:SS 形式（UTC）で指定してください: "
            f"{observation_datetime_utc}"
        ) from error


def build_observation_time_window(observation_datetime_utc: str) -> tuple[str, str]:
    """観測日時の秒を含む 1 秒間の範囲（開始を含み終了を含まない）を作る。

    GEE の `system:time_start` はミリ秒を持つが、観測日時は秒で切り捨てて表記している
    （`gee_search_satellite_data.py` の書式と同じ）。そのため [観測日時, 観測日時+1秒) で
    絞り込むと、表記と同じ観測だけが残る。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        tuple[str, str]: `filterDate` に渡す開始・終了の ISO 形式文字列。
    """
    start = parse_observation_datetime(observation_datetime_utc)
    end = start + dt.timedelta(seconds=1)
    return start.isoformat(), end.isoformat()


def build_observation_day_range(observation_datetime_utc: str) -> tuple[str, str]:
    """観測日時を含む UTC の 1 日の範囲（当日, 翌日）を作る。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        tuple[str, str]: 当日と翌日の ISO 形式日付。
    """
    observation_date = parse_observation_datetime(observation_datetime_utc).date()
    return observation_date.isoformat(), (observation_date + dt.timedelta(days=1)).isoformat()


def build_observation_token(observation_datetime_utc: str) -> str:
    """観測日時から出力名に使う `YYYYMMDD_HHMMSS` を作る。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        str: `YYYYMMDD_HHMMSS` 形式の文字列。
    """
    return parse_observation_datetime(observation_datetime_utc).strftime("%Y%m%d_%H%M%S")


def build_variant_drive_folder(observation_datetime_utc: str, variant: str) -> str:
    """放射率の種類ごとの Google Drive の出力先フォルダ名を作る。

    NDVI 版と EM0 版は同じファイル名で出力するため、フォルダで区別する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        variant: 放射率の種類（`EMISSIVITY_VARIANTS` のキー）。

    Returns:
        str: Drive のフォルダ名。

    Raises:
        ValueError: 未定義の放射率の種類の場合。
    """
    validate_variant(variant)
    token = build_observation_token(observation_datetime_utc)
    return f"{DRIVE_FOLDER_PREFIX}_{variant}_{token}"


def validate_variant(variant: str) -> None:
    """放射率の種類が定義済みか確かめる。

    Args:
        variant: 放射率の種類。

    Raises:
        ValueError: `EMISSIVITY_VARIANTS` にない場合。
    """
    if variant not in EMISSIVITY_VARIANTS:
        raise ValueError(
            f"未定義の放射率の種類です: {variant}（定義済み: {', '.join(EMISSIVITY_VARIANTS)}）"
        )


def build_export_plan(observation_datetime_utc: str, sensor: str) -> list[dict[str, Any]]:
    """放射率の種類ごとの出力先・ファイル名・ダウンロード後の配置先をまとめる。

    LST のファイル名は既存（`LST_Landsat8_YYYYMMDD_HHMMSSZ`）と同じ形式にし、
    配置先のディレクトリで放射率の種類を区別する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        sensor: センサ名（"L8" / "L9"）。

    Returns:
        list[dict[str, Any]]: 放射率の種類ごとの辞書のリスト。各辞書は `variant`・
            `use_ndvi`・`drive_folder`・`lst_file_prefix`・`emissivity_file_prefix`・
            `local_lst_path`・`local_emissivity_path`（プロジェクト相対・`/` 区切り）を持つ。

    Raises:
        ValueError: 観測日時の形式が不正な場合、または未定義のセンサ名の場合。
    """
    validate_sensor(sensor)
    year = observation_datetime_utc[:4]
    lst_file_prefix = build_export_description(LST_FILE_PREFIX, observation_datetime_utc, sensor)
    emissivity_file_prefix = build_export_description(
        EMISSIVITY_FILE_PREFIX, observation_datetime_utc, sensor
    )
    plan: list[dict[str, Any]] = []
    for variant, use_ndvi in EMISSIVITY_VARIANTS.items():
        local_dir = LOCAL_PLACEMENT_ROOT / variant / year
        plan.append(
            {
                "variant": variant,
                "use_ndvi": use_ndvi,
                "drive_folder": build_variant_drive_folder(observation_datetime_utc, variant),
                "lst_file_prefix": lst_file_prefix,
                "emissivity_file_prefix": emissivity_file_prefix,
                "local_lst_path": (local_dir / f"{lst_file_prefix}.tif").as_posix(),
                "local_emissivity_path": (local_dir / f"{emissivity_file_prefix}.tif").as_posix(),
            }
        )
    return plan


def select_observation_image(
    collection_sr_raw: ee.ImageCollection, observation_datetime_utc: str
) -> ee.Image:
    """未マスクの SR コレクションから、観測日時が一致する 1 シーンを取り出す。

    Args:
        collection_sr_raw: 未マスクの SR コレクション。
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        ee.Image: 一致したシーンの未マスク SR 画像。

    Raises:
        ValueError: 一致するシーンが 0 件または 2 件以上の場合（観測を 1 つに
            特定できないまま出力すると、別の観測の LST を比べてしまうため）。
    """
    start, end = build_observation_time_window(observation_datetime_utc)
    matched = collection_sr_raw.filterDate(start, end)
    match_count = int(matched.size().getInfo())
    if match_count != 1:
        raise ValueError(
            f"観測日時 {observation_datetime_utc} に一致するシーンが {match_count} 件です"
            "（1 件である必要があります）。観測日時・センサを確認してください。"
        )
    return ee.Image(matched.first())


def fetch_observation(
    observation_datetime_utc: str, roi: ee.Geometry, sensor: str
) -> tuple[ee.Image, ee.ImageCollection]:
    """観測日時の 1 シーン（未マスク SR）と、同日の TOA コレクションを取得する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        roi: ROI。
        sensor: センサ名（"L8" / "L9"）。

    Returns:
        tuple[ee.Image, ee.ImageCollection]: 未マスク SR 画像と TOA コレクション。
    """
    day_start, day_end = build_observation_day_range(observation_datetime_utc)
    collection_toa, collection_sr_raw = get_raw_landsat_collections(
        day_start, day_end, roi, sensor=sensor
    )
    raw_sr_image = select_observation_image(collection_sr_raw, observation_datetime_utc)
    return raw_sr_image, collection_toa


def get_scene_index(raw_sr_image: ee.Image) -> str:
    """シーンの `system:index` を取得する（結果の記録で観測を特定するため）。

    Args:
        raw_sr_image: SR 画像。

    Returns:
        str: `system:index`。
    """
    return ee.String(raw_sr_image.get("system:index")).getInfo()


def ensure_writable(path: Path, overwrite: bool) -> None:
    """既存の出力を黙って上書きしないよう確かめる。

    Args:
        path: 出力先のパス。
        overwrite: 上書きを許すか。

    Raises:
        FileExistsError: 出力先が存在し、上書きが許されていない場合。
    """
    if path.exists() and not overwrite:
        raise FileExistsError(f"出力先が既に存在します（上書きは --overwrite）: {path}")


def load_gee_context(config_path: Path) -> tuple[dict[str, Any], ee.Geometry, Path]:
    """設定 CSV を読み、GEE を初期化して ROI を読み込む。

    Args:
        config_path: 設定 CSV のパス。

    Returns:
        tuple[dict[str, Any], ee.Geometry, Path]: 設定・ROI・ROI のパス。

    Raises:
        ValueError: プロジェクト ID または ROI のパスが設定されていない場合。
    """
    config = load_config(str(config_path))
    gee_project_id = str(config.get("gee_project_id") or "").strip()
    if not gee_project_id or gee_project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError("GCPプロジェクトIDが設定されていません。設定CSVを確認してください。")
    roi_path_text = str(config.get("roi_shapefile_path") or "").strip()
    if not roi_path_text:
        raise ValueError("設定CSVに roi_shapefile_path がありません。")

    # 設定 CSV の区切りは Windows 形式のため、どの OS でも読めるよう `/` に揃えてから解決する
    roi_path = resolve_existing_path(Path(roi_path_text.replace("\\", "/")))
    authenticate_gee(project_id=gee_project_id)
    roi = load_roi_from_shapefile(str(roi_path))
    return config, roi, roi_path


def run_export(
    observation_datetime_utc: str,
    sensor: str,
    config_path: Path,
    output_dir: Path,
    overwrite: bool,
) -> Path:
    """NDVI 版・EM0 版の LST と放射率を Drive へ出力し、タスクの一覧を記録する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        sensor: センサ名（"L8" / "L9"）。
        config_path: 設定 CSV のパス。
        output_dir: タスクの一覧 JSON の出力先ディレクトリ。
        overwrite: 既存の JSON の上書きを許すか。

    Returns:
        Path: タスクの一覧 JSON のパス。
    """
    plan = build_export_plan(observation_datetime_utc, sensor)
    summary_path = prepare_output_path(output_dir / EXPORT_SUMMARY_NAME)
    ensure_writable(summary_path, overwrite)

    config, roi, roi_path = load_gee_context(config_path)
    output_epsg = int(config.get("output_epsg", 4326))
    raw_sr_image, collection_toa = fetch_observation(observation_datetime_utc, roi, sensor)
    scene_index = get_scene_index(raw_sr_image)

    for entry in plan:
        lst_image = build_lst_image(
            raw_sr_image, collection_toa, roi, sensor=sensor, use_ndvi=entry["use_ndvi"]
        )
        export_lst_to_drive(
            image=lst_image,
            roi=roi,
            output_epsg=output_epsg,
            folder_name=entry["drive_folder"],
            description=entry["lst_file_prefix"],
            observation_datetime_utc=observation_datetime_utc,
        )
        # 放射率も LST と同じ条件（クリップ・EPSG・30 m）で出力する。関数名は指標用だが、
        # 指定バンドを選んで出力する処理は同一のため再利用する
        export_indices_to_drive(
            image=lst_image,
            roi=roi,
            output_epsg=output_epsg,
            folder_name=entry["drive_folder"],
            description=entry["emissivity_file_prefix"],
            observation_datetime_utc=observation_datetime_utc,
            band_names=[EMISSIVITY_BAND],
        )
        logger.info(
            "出力タスクを起動しました: %s -> Drive フォルダ %s（ダウンロード後の配置先: %s, %s）",
            entry["variant"],
            entry["drive_folder"],
            entry["local_lst_path"],
            entry["local_emissivity_path"],
        )

    summary = {
        "observation_datetime_utc": observation_datetime_utc,
        "satellite": get_sensor_label(sensor),
        "scene_index": scene_index,
        "output_epsg": output_epsg,
        "scale_m": 30,
        "emissivity_band": EMISSIVITY_BAND,
        "exports": plan,
        "note": (
            "Drive からのダウンロードと local_*_path への配置は手作業。"
            "ndvi は分析に用いる LST と同じ算出条件、em0 は ASTER GEDv3 の静的な放射率による対照。"
        ),
        "provenance": build_provenance(
            SCRIPT_NAME, [roi_path], extra_watch_paths=EXTRA_WATCH_PATHS
        ),
    }
    save_summary(summary, summary_path)
    logger.info("タスクの一覧を保存しました: %s", summary_path)
    return summary_path


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作る。

    Returns:
        argparse.ArgumentParser: 引数のパーサー。
    """
    parser = argparse.ArgumentParser(
        description="LST の放射率を NDVI 版と ASTER 静的版（EM0）で切り替えて 1 観測分を出力する。"
    )
    parser.add_argument(
        "--observation-datetime",
        required=True,
        help="対象観測の UTC 日時（YYYY-MM-DDTHH:MM:SS）。例: 2022-09-06T03:23:58",
    )
    parser.add_argument("--sensor", default=DEFAULT_SENSOR, help="センサ名（L8 / L9）。")
    parser.add_argument(
        "--config-path", type=Path, default=DEFAULT_CONFIG_PATH, help="GEE 設定 CSV のパス。"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="タスクの一覧 JSON の出力先（既定: lst_emissivity_sensitivity/{観測日時}）。",
    )
    parser.add_argument("--overwrite", action="store_true", help="既存の出力の上書きを許す。")
    return parser


def main(argv: list[str] | None = None) -> None:
    """エントリーポイント。

    Args:
        argv: コマンドライン引数（None の場合は `sys.argv` を使う）。
    """
    args = build_argument_parser().parse_args(argv)
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / build_observation_token(
        args.observation_datetime
    )
    run_export(
        observation_datetime_utc=args.observation_datetime,
        sensor=args.sensor,
        config_path=args.config_path,
        output_dir=output_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
