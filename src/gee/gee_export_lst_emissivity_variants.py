"""LST 算出の放射率を切り替えて 1 観測分を出力する、放射率の感度分析用スクリプト。

分析に用いる LST（SMW 法）は、放射率を同じシーンの NDVI → FVC から求める
（ε = 0.99×FVC + (1−FVC)×ε_bare）。説明変数の NDVI が目的変数の算出式に入るため、
放射率を NDVI に依存させない対照として、ASTER GEDv3 の静的な放射率（EM0）による
LST を作り、両者の差を調べる。

次の 2 つのサブコマンドを持つ。どちらも観測を UTC の観測日時で 1 つに限定し、
`gee_search_satellite_data.py`・`gee_calc_LST.py` の結果 CSV には書き込まない。

1. `export`:
   NDVI 版（`ndvi`）と EM0 版（`em0`）の LST と放射率（`EM` バンド）を、
   放射率ごとに別の Google Drive フォルダへ GeoTIFF で出力する。
   LST の出力条件（雲マスク・ROI クリップ・EPSG・30 m）は
   `gee_search_satellite_data.py` と同一で、ファイル名の形式も既存と同じにする
   （`urban_params` がファイル名からテーブル名を導くため）。
   起動したタスクの一覧は来歴つきの JSON に記録する。
2. `sample`:
   既存の LST GeoTIFF のグリッド上で、有効画素からランダムに選んだ画素中心の点について、
   SMW（NDVI 放射率）・SMW（EM0）・`simple`（Collection 2 Level-2 の `ST_B10` の
   スケーリングのみ）の 3 方式の LST を GEE から取得し、CSV に出力する。
   既存 GeoTIFF がどの方式で作られたかを、値の照合で確かめるために用いる
   （照合そのものは `src.analysis.lst_emissivity_sensitivity` で行う）。

`sample` は現行のコード（雲マスクを含む）で LST を算出する。既存 GeoTIFF の作成後に
雲マスクの条件が変わっている場合、既存で有効な画素が現行ではマスクされることがあり、
その点の値は欠測（空欄）になる。

使い方（プロジェクトルートで実行）:

    python -m src.gee.gee_export_lst_emissivity_variants export \
        --observation-datetime 2022-09-06T03:23:58
    python -m src.gee.gee_export_lst_emissivity_variants sample \
        --observation-datetime 2023-07-07T03:23:05 \
        --reference-tif data/satellite/lst/2023/LST_Landsat8_20230707_032305Z.tif

依存: earthengine-api、rasterio、numpy、pandas。GEE の認証と、設定 CSV
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
import numpy as np
import pandas as pd
import rasterio
from affine import Affine

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, resolve_existing_path, to_project_relative_string
from src.common.summary import build_provenance, save_summary
from src.gee.gee_calc_LST import (
    authenticate_gee,
    build_export_description,
    calculate_lst_simple,
    cloud_mask,
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

# 点サンプリングで比べる 3 方式の列名（列の順序は CSV の列順になる）
SAMPLE_METHOD_COLUMNS: tuple[str, ...] = ("lst_smw_ndvi", "lst_smw_em0", "lst_simple")
DEFAULT_N_POINTS = 500
DEFAULT_SEED = 42
SAMPLE_CSV_NAME = "point_samples.csv"
SAMPLE_SUMMARY_NAME = "point_samples_summary.json"
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


def read_reference_raster(reference_tif: Path) -> tuple[np.ndarray, Affine, str]:
    """既存 LST GeoTIFF の 1 バンド目の値・アフィン変換・CRS を読む。

    Args:
        reference_tif: 既存 LST GeoTIFF のパス。

    Returns:
        tuple[np.ndarray, Affine, str]: float64 の値（無効値は NaN）・変換・CRS 文字列。

    Raises:
        ValueError: CRS が未設定の場合（GEE 側で同じグリッドを指定できないため）。
    """
    with rasterio.open(reference_tif) as source:
        values = source.read(1, masked=True).astype("float64").filled(np.nan)
        transform = source.transform
        if source.crs is None:
            raise ValueError(f"参照ラスタに CRS が設定されていません: {reference_tif}")
        crs_text = source.crs.to_string()
    return values, transform, crs_text


def select_reference_pixels(
    values: np.ndarray, n_points: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """有限値の画素から、重複なしで無作為に画素を選ぶ。

    Args:
        values: 参照ラスタの値（2 次元。無効値は NaN）。
        n_points: 選ぶ画素数。
        seed: 乱数シード。

    Returns:
        tuple[np.ndarray, np.ndarray]: 選んだ画素の行・列（行優先の昇順）。

    Raises:
        ValueError: `n_points` が 1 未満、または有効画素数を超える場合。
    """
    if n_points < 1:
        raise ValueError(f"点の数は 1 以上を指定してください: {n_points}")
    valid_rows, valid_cols = np.nonzero(np.isfinite(values))
    if n_points > len(valid_rows):
        raise ValueError(
            f"点の数 {n_points} が参照ラスタの有効画素数 {len(valid_rows)} を超えています。"
        )
    rng = np.random.default_rng(seed)
    chosen = np.sort(rng.choice(len(valid_rows), size=n_points, replace=False))
    return valid_rows[chosen], valid_cols[chosen]


def build_pixel_center_points(
    rows: np.ndarray, cols: np.ndarray, transform: Affine
) -> pd.DataFrame:
    """画素の行・列から、画素中心の座標を持つ点の表を作る。

    画素の境界上の点は隣の画素に割り当てられうるため、中心を用いる。

    Args:
        rows: 画素の行。
        cols: 画素の列。
        transform: 参照ラスタのアフィン変換。

    Returns:
        pd.DataFrame: `point_id`・`row`・`col`・`x`・`y`（参照ラスタの CRS の座標）。
    """
    x_coords, y_coords = transform * (cols + 0.5, rows + 0.5)
    return pd.DataFrame(
        {
            "point_id": np.arange(len(rows), dtype="int64"),
            "row": rows.astype("int64"),
            "col": cols.astype("int64"),
            "x": np.asarray(x_coords, dtype="float64"),
            "y": np.asarray(y_coords, dtype="float64"),
        }
    )


def build_sample_image(
    raw_sr_image: ee.Image,
    collection_toa: ee.ImageCollection,
    roi: ee.Geometry,
    sensor: str,
) -> ee.Image:
    """3 方式の LST を 1 枚の画像のバンドにまとめる。

    `simple` は `gee_calc_LST.py` の `lst_method=simple` と同じく、雲マスク後の SR 画像の
    `ST_B10` をスケーリングする。

    Args:
        raw_sr_image: 未マスクの SR 画像。
        collection_toa: TOA コレクション（SR と同じセンサ）。
        roi: ROI。
        sensor: センサ名（"L8" / "L9"）。

    Returns:
        ee.Image: `SAMPLE_METHOD_COLUMNS` の名前を持つ 3 バンドの画像（°C）。
    """
    lst_ndvi = build_lst_image(raw_sr_image, collection_toa, roi, sensor=sensor, use_ndvi=True)
    lst_em0 = build_lst_image(raw_sr_image, collection_toa, roi, sensor=sensor, use_ndvi=False)
    lst_simple = calculate_lst_simple(cloud_mask(raw_sr_image))
    return (
        lst_ndvi.select("LST")
        .rename(SAMPLE_METHOD_COLUMNS[0])
        .addBands(lst_em0.select("LST").rename(SAMPLE_METHOD_COLUMNS[1]))
        .addBands(lst_simple.select("LST").rename(SAMPLE_METHOD_COLUMNS[2]))
    )


def build_points_feature_collection(points: pd.DataFrame, crs_text: str) -> ee.FeatureCollection:
    """点の表を、`point_id` を属性に持つ GEE の FeatureCollection にする。

    Args:
        points: `point_id`・`x`・`y` を持つ点の表。
        crs_text: 座標の CRS（例: `EPSG:4326`）。

    Returns:
        ee.FeatureCollection: 点の FeatureCollection。
    """
    features = [
        ee.Feature(
            ee.Geometry.Point([float(row.x), float(row.y)], crs_text),
            {"point_id": int(row.point_id)},
        )
        for row in points.itertuples(index=False)
    ]
    return ee.FeatureCollection(features)


def parse_sampled_features(
    features: list[dict[str, Any]], columns: tuple[str, ...]
) -> pd.DataFrame:
    """`reduceRegions` の結果（GeoJSON の Feature の辞書）を表にする。

    マスクされた画素では `ee.Reducer.first()` が値を返さず、属性が欠けるか null になる。
    どちらも欠測（NaN）として扱う。

    Args:
        features: `getInfo()` で得た Feature の辞書のリスト。
        columns: 取り出す値の属性名。

    Returns:
        pd.DataFrame: `point_id` と `columns` の列を持つ表（`point_id` の昇順）。

    Raises:
        ValueError: `point_id` が欠けた Feature を含む場合。
    """
    records: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties") or {}
        if properties.get("point_id") is None:
            raise ValueError("point_id を持たない Feature が含まれています。")
        record: dict[str, Any] = {"point_id": int(properties["point_id"])}
        for column in columns:
            value = properties.get(column)
            record[column] = float(value) if value is not None else np.nan
        records.append(record)
    table = pd.DataFrame.from_records(records, columns=["point_id", *columns])
    table = table.astype({"point_id": "int64", **{column: "float64" for column in columns}})
    return table.sort_values("point_id").reset_index(drop=True)


def sample_image_on_reference_grid(
    image: ee.Image, points: pd.DataFrame, crs_text: str, transform: Affine
) -> pd.DataFrame:
    """参照ラスタと同じグリッドで、点の位置の画像の値を取得する。

    Export と同じく最近傍で参照グリッドへ投影した値を得るため、`reduceRegions` に
    参照ラスタの CRS とアフィン変換をそのまま渡す。

    Args:
        image: 値を取る画像。
        points: `point_id`・`x`・`y` を持つ点の表。
        crs_text: 参照ラスタの CRS。
        transform: 参照ラスタのアフィン変換。

    Returns:
        pd.DataFrame: `point_id` と画像のバンド名の列を持つ表。
    """
    reduced = image.reduceRegions(
        collection=build_points_feature_collection(points, crs_text),
        reducer=ee.Reducer.first(),
        crs=crs_text,
        crsTransform=list(transform)[:6],
    )
    features = reduced.getInfo().get("features", [])
    return parse_sampled_features(features, SAMPLE_METHOD_COLUMNS)


def merge_points_and_samples(points: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    """点の表と取得値を `point_id` で結合する。

    Args:
        points: 点の表。
        samples: 取得値の表。

    Returns:
        pd.DataFrame: 結合した表。

    Raises:
        ValueError: 取得値の `point_id` が点の表と一致しない場合（点の取りこぼしや
            重複に気付かないまま照合するのを防ぐため）。
    """
    if sorted(points["point_id"]) != sorted(samples["point_id"]):
        raise ValueError(
            f"取得値の点（{len(samples)} 件）が要求した点（{len(points)} 件）と一致しません。"
        )
    return points.merge(samples, on="point_id", how="left", validate="one_to_one")


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


def run_sample(
    observation_datetime_utc: str,
    sensor: str,
    config_path: Path,
    reference_tif: Path,
    output_dir: Path,
    n_points: int,
    seed: int,
    overwrite: bool,
) -> tuple[Path, Path]:
    """既存 LST GeoTIFF のグリッド上の点で、3 方式の LST を取得して保存する。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        sensor: センサ名（"L8" / "L9"）。
        config_path: 設定 CSV のパス。
        reference_tif: 既存 LST GeoTIFF のパス。
        output_dir: 出力先ディレクトリ。
        n_points: 点の数。
        seed: 点の選択の乱数シード。
        overwrite: 既存の出力の上書きを許すか。

    Returns:
        tuple[Path, Path]: 点の CSV とサマリー JSON のパス。
    """
    validate_sensor(sensor)
    parse_observation_datetime(observation_datetime_utc)
    reference_path = resolve_existing_path(reference_tif)
    csv_path = prepare_output_path(output_dir / SAMPLE_CSV_NAME)
    summary_path = prepare_output_path(output_dir / SAMPLE_SUMMARY_NAME)
    ensure_writable(csv_path, overwrite)
    ensure_writable(summary_path, overwrite)

    values, transform, crs_text = read_reference_raster(reference_path)
    rows, cols = select_reference_pixels(values, n_points, seed)
    points = build_pixel_center_points(rows, cols, transform)

    _, roi, roi_path = load_gee_context(config_path)
    raw_sr_image, collection_toa = fetch_observation(observation_datetime_utc, roi, sensor)
    scene_index = get_scene_index(raw_sr_image)
    image = build_sample_image(raw_sr_image, collection_toa, roi, sensor)
    samples = sample_image_on_reference_grid(image, points, crs_text, transform)
    table = merge_points_and_samples(points, samples)
    table.to_csv(csv_path, index=False, encoding="utf-8")

    summary = {
        "observation_datetime_utc": observation_datetime_utc,
        "satellite": get_sensor_label(sensor),
        "scene_index": scene_index,
        "reference_tif": to_project_relative_string(reference_path),
        "reference_crs": crs_text,
        "reference_transform": list(transform)[:6],
        "n_points": n_points,
        "seed": seed,
        "methods": {
            "lst_smw_ndvi": "SMW 法・同じシーンの NDVI から求めた放射率（分析に用いる LST の条件）",
            "lst_smw_em0": "SMW 法・ASTER GEDv3 の静的な放射率（EM0）",
            "lst_simple": "Collection 2 Level-2 の ST_B10 のスケーリングのみ",
        },
        "missing_counts": {
            column: int(table[column].isna().sum()) for column in SAMPLE_METHOD_COLUMNS
        },
        "note": (
            "点は参照ラスタの有効画素の中心。値は現行コード（雲マスクを含む）で算出しており、"
            "参照ラスタの作成後に雲マスクが変わった場合は、マスクされた点が欠測になる。"
        ),
        "outputs": {"csv": to_project_relative_string(csv_path)},
        "provenance": build_provenance(
            SCRIPT_NAME, [reference_path, roi_path], extra_watch_paths=EXTRA_WATCH_PATHS
        ),
    }
    save_summary(summary, summary_path)
    logger.info("点の値を保存しました: %s（欠測: %s）", csv_path, summary["missing_counts"])
    return csv_path, summary_path


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作る。

    Returns:
        argparse.ArgumentParser: `export`・`sample` のサブコマンドを持つパーサー。
    """
    parser = argparse.ArgumentParser(
        description="LST の放射率を NDVI 版と ASTER 静的版（EM0）で切り替えて 1 観測分を出力する。"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--observation-datetime",
        required=True,
        help="対象観測の UTC 日時（YYYY-MM-DDTHH:MM:SS）。例: 2022-09-06T03:23:58",
    )
    common.add_argument("--sensor", default=DEFAULT_SENSOR, help="センサ名（L8 / L9）。")
    common.add_argument(
        "--config-path", type=Path, default=DEFAULT_CONFIG_PATH, help="GEE 設定 CSV のパス。"
    )
    common.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先ディレクトリ（既定: data/output/lst_emissivity_sensitivity/ 配下）。",
    )
    common.add_argument("--overwrite", action="store_true", help="既存の出力の上書きを許す。")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "export", parents=[common], help="NDVI 版・EM0 版の LST と放射率を Drive へ出力する。"
    )
    sample_parser = subparsers.add_parser(
        "sample", parents=[common], help="既存 LST のグリッド上の点で 3 方式の LST を取得する。"
    )
    sample_parser.add_argument(
        "--reference-tif", type=Path, required=True, help="照合する既存 LST GeoTIFF のパス。"
    )
    sample_parser.add_argument("--n-points", type=int, default=DEFAULT_N_POINTS, help="点の数。")
    sample_parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="点の選択の乱数シード。"
    )
    return parser


def build_default_output_dir(command: str, observation_datetime_utc: str) -> Path:
    """サブコマンドごとの既定の出力先ディレクトリを作る。

    Args:
        command: サブコマンド名（`export` / `sample`）。
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。

    Returns:
        Path: プロジェクト相対の出力先ディレクトリ。

    Raises:
        ValueError: 未定義のサブコマンドの場合。
    """
    token = build_observation_token(observation_datetime_utc)
    if command == "export":
        return DEFAULT_OUTPUT_ROOT / token
    if command == "sample":
        return DEFAULT_OUTPUT_ROOT / f"{token}_method_check"
    raise ValueError(f"未定義のサブコマンドです: {command}")


def main(argv: list[str] | None = None) -> None:
    """エントリーポイント。

    Args:
        argv: コマンドライン引数（None の場合は `sys.argv` を使う）。
    """
    args = build_argument_parser().parse_args(argv)
    output_dir = args.output_dir or build_default_output_dir(
        args.command, args.observation_datetime
    )
    if args.command == "export":
        run_export(
            observation_datetime_utc=args.observation_datetime,
            sensor=args.sensor,
            config_path=args.config_path,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
    else:
        run_sample(
            observation_datetime_utc=args.observation_datetime,
            sensor=args.sensor,
            config_path=args.config_path,
            reference_tif=args.reference_tif,
            output_dir=output_dir,
            n_points=args.n_points,
            seed=args.seed,
            overwrite=args.overwrite,
        )


if __name__ == "__main__":
    main()
