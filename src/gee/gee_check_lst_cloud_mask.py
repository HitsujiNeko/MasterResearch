"""LST の雲マスクで除外する QA ビットを検証する Google Earth Engine スクリプト。

`gee_search_satellite_data.py` の探索結果で LST 最小値が極端に低い観測があり、
雲の取り残しが疑われる。本スクリプトはその原因となる QA ビットを特定し、
マスク条件を変えた場合の影響を比較するために、次の2つの CSV を出力する。

1. 異常画素の QA ビット集計（`lst_cloud_mask_anomaly_qa_bits.csv`）:
   変更前のマスク（bit 3: Cloud, bit 4: Cloud Shadow）を通った画素のうち、
   LST が閾値を下回る画素について、QA_PIXEL のフラグ（bit 0〜7）・
   信頼度フィールド（bit 8〜15、2 ビットずつ）・QA_RADSAT の該当画素数を数える。
2. マスク候補ごとの影響比較（`lst_cloud_mask_variant_comparison.csv`）:
   候補ごとに有効画素率・LST の実効 ROI カバー率・LST の統計量・
   閾値を下回る画素数を出す。

LST は 1 シーンにつき 1 回だけ、QA マスクをかけない SR から計算し、各候補の
マスクを後からかけて集計する。SMW の計算（NDVI・FVC・放射率・SMW 式）は画素ごとに
閉じており、TPW は NCEP 由来で SR のマスクに依存しないため、本番（マスク後に
LST を計算）と同じ値になる。

対象シーンは既存の探索結果 CSV とランキング CSV から選ぶ（既定: LST 最小値が閾値未満の
観測、ランキング上位 20 件、採用観測）。`--scene-indices` で個別に指定することもできる。

依存: earthengine-api, pandas, `src.gee.gee_calc_LST`, `src.module.lst_smw`
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import argparse
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import ee
import pandas as pd
from tqdm import tqdm

from src.common.config import PROJECT_ROOT
from src.gee.gee_calc_LST import (
    authenticate_gee,
    get_matching_toa_image,
    load_config,
    load_roi_from_shapefile,
)
from src.gee.gee_calc_satellite_indices import to_float_or_nan
from src.module.landsat_sensor import get_collection_id
from src.module.lst_smw import calculate_lst_smw

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_search_info_2022to2024.csv"
DEFAULT_RESULTS_CSV = PROJECT_ROOT / "data" / "output" / "gee_search_satellite_data_results.csv"
DEFAULT_RANKING_CSV = PROJECT_ROOT / "data" / "output" / "gee_search_observation_ranking.csv"
DEFAULT_ANOMALY_CSV = PROJECT_ROOT / "data" / "output" / "lst_cloud_mask_anomaly_qa_bits.csv"
DEFAULT_VARIANT_CSV = PROJECT_ROOT / "data" / "output" / "lst_cloud_mask_variant_comparison.csv"
DEFAULT_THRESHOLD_C = -20.0
DEFAULT_TOP_N = 20
DEFAULT_ADOPTED_OBSERVATIONS = ("2023-07-07T03:23:05",)
REDUCE_SCALE_M = 30
REDUCE_MAX_PIXELS = 1e9

# QA_PIXEL のフラグ（1 ビット）。USGS「Landsat Collection 2 Quality Assessment Bands」の
# Landsat 8-9 QA_PIXEL Bit Index による。
QA_PIXEL_FLAG_BITS: dict[str, int] = {
    "fill": 0,
    "dilated_cloud": 1,
    "cirrus": 2,
    "cloud": 3,
    "cloud_shadow": 4,
    "snow": 5,
    "clear": 6,
    "water": 7,
}

# QA_PIXEL の信頼度フィールド（2 ビット、値 0〜3）の開始ビット。
QA_PIXEL_CONFIDENCE_FIELDS: dict[str, int] = {
    "cloud_confidence": 8,
    "cloud_shadow_confidence": 10,
    "snow_ice_confidence": 12,
    "cirrus_confidence": 14,
}
CONFIDENCE_LEVELS = (0, 1, 2, 3)

SCENE_ID_PREFIX_TO_SENSOR = {"LC08": "L8", "LC09": "L9"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskVariant:
    """比較するマスク候補の定義。

    Attributes:
        name: 候補名（CSV の `variant` 列に用いる）。
        bits: 除外する QA_PIXEL のビット番号。いずれかが立つ画素を除外する。
        require_radsat_zero: True の場合は QA_RADSAT が 0 以外の画素も除外する。
    """

    name: str
    bits: tuple[int, ...]
    require_radsat_zero: bool = False


# 比較するマスク候補。先頭の current は変更前の条件（原典 cloudmask.js の sr と同じ）で、
# 検証時点の本番マスクを指す。検証の結果、本番の `cloud_mask` には plus_cirrus_snow を採用した。
# plus_snow・plus_cirrus_snow は、異常画素に Snow（bit 5）が立っていたことを受けて、
# Snow だけで足りるか・Cirrus も要るかを切り分けるために加える。
# indices_equivalent は衛星指標側の `cloud_mask_sr` と同じ条件。
MASK_VARIANTS: tuple[MaskVariant, ...] = (
    MaskVariant("current", (3, 4)),
    MaskVariant("plus_dilated", (1, 3, 4)),
    MaskVariant("plus_cirrus", (2, 3, 4)),
    MaskVariant("plus_dilated_cirrus", (1, 2, 3, 4)),
    MaskVariant("plus_snow", (3, 4, 5)),
    MaskVariant("plus_cirrus_snow", (2, 3, 4, 5)),
    MaskVariant("indices_equivalent", (0, 1, 2, 3, 4, 5), require_radsat_zero=True),
)
CURRENT_VARIANT_NAME = "current"

SCENE_META_COLUMNS = (
    "scene_index",
    "observation_datetime_utc",
    "satellite",
    "selection_reason",
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description=(
            "LST の雲マスクで除外する QA ビットを検証し、異常画素の QA ビット集計と"
            "マスク候補ごとの影響比較を CSV に出力する。"
        )
    )
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--results-csv-path",
        type=Path,
        default=DEFAULT_RESULTS_CSV,
        help="対象シーンの選定に使う探索結果CSV。",
    )
    parser.add_argument(
        "--ranking-csv-path",
        type=Path,
        default=DEFAULT_RANKING_CSV,
        help="対象シーンの選定に使うランキングCSV。",
    )
    parser.add_argument("--anomaly-csv-path", type=Path, default=DEFAULT_ANOMALY_CSV)
    parser.add_argument("--variant-csv-path", type=Path, default=DEFAULT_VARIANT_CSV)
    parser.add_argument(
        "--threshold-c",
        type=float,
        default=DEFAULT_THRESHOLD_C,
        help="異常画素と見なす LST の閾値（°C）。この値未満を異常とする。",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="対象に含めるランキング上位の件数。",
    )
    parser.add_argument(
        "--adopted-observations",
        nargs="*",
        default=list(DEFAULT_ADOPTED_OBSERVATIONS),
        help="対象に含める採用観測の観測日時（UTC）。",
    )
    parser.add_argument(
        "--scene-indices",
        nargs="*",
        default=None,
        help="対象シーンを system:index で直接指定する（指定時は既定の選び方を使わない）。",
    )
    return parser.parse_args()


def build_qa_bit_mask(bits: tuple[int, ...]) -> int:
    """QA_PIXEL の判定に使うビットマスク値を作る。

    Args:
        bits: 判定対象のビット番号（0〜15）。

    Returns:
        int: 指定ビットを立てた整数（例: (3, 4) → 24）。

    Raises:
        ValueError: ビット番号が空、または 0〜15 の範囲外の場合。
    """
    if not bits:
        raise ValueError("判定対象のビットが指定されていません")
    for bit in bits:
        if not 0 <= bit <= 15:
            raise ValueError(f"QA_PIXEL のビット番号は 0〜15 です: {bit}")
    mask_value = 0
    for bit in bits:
        mask_value |= 1 << bit
    return mask_value


def sensor_from_scene_index(scene_index: str) -> str:
    """system:index（例: `LC09_127045_20220930`）からセンサ名を返す。

    Args:
        scene_index: Landsat Collection 2 の system:index。

    Returns:
        str: センサ名（"L8" / "L9"）。

    Raises:
        ValueError: 接頭辞が LC08 / LC09 以外の場合。
    """
    prefix = scene_index.split("_", 1)[0]
    if prefix not in SCENE_ID_PREFIX_TO_SENSOR:
        raise ValueError(f"未対応のシーンIDです（LC08 / LC09 のみ対応）: {scene_index}")
    return SCENE_ID_PREFIX_TO_SENSOR[prefix]


def select_target_scenes(
    results_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    threshold_c: float,
    top_n: int,
    adopted_observations: list[str] | tuple[str, ...],
    scene_indices: list[str] | None = None,
) -> pd.DataFrame:
    """検証の対象シーンを選び、選定理由を付けて返す。

    既定では、LST 最小値が閾値未満の観測・ランキング上位 `top_n` 件・採用観測の
    和集合を対象とする。`scene_indices` を指定した場合はそれだけを対象とする。

    Args:
        results_df: 探索結果CSV（`scene_index` / `observation_datetime_utc` /
            `lst_min_temp_c` などを含む）。
        ranking_df: ランキングCSV（実効ROIカバー率の降順）。
        threshold_c: 異常と見なす LST の閾値（°C）。
        top_n: 対象に含めるランキング上位の件数。
        adopted_observations: 採用観測の観測日時（UTC）。
        scene_indices: 対象を直接指定する system:index。None なら既定の選び方を使う。

    Returns:
        pd.DataFrame: 探索結果CSVの行に `selection_reason`（`;` 区切り）を加えたもの。
            観測日時・system:index の昇順。

    Raises:
        ValueError: 指定した system:index・採用観測が探索結果CSVに無い場合。
    """
    reasons: dict[str, list[str]] = {}

    def _add(scene_ids: Iterable[str], reason: str) -> None:
        """シーンに選定理由を追加する。"""
        for scene_id in scene_ids:
            reasons.setdefault(scene_id, []).append(reason)

    known_scene_ids = set(results_df["scene_index"])
    if scene_indices is not None:
        missing = sorted(set(scene_indices) - known_scene_ids)
        if missing:
            raise ValueError(f"探索結果CSVに無い system:index です: {', '.join(missing)}")
        _add(scene_indices, "specified")
    else:
        below = results_df.loc[results_df["lst_min_temp_c"] < threshold_c, "scene_index"]
        _add(below, "lst_min_below_threshold")
        _add(ranking_df["scene_index"].head(top_n), f"ranking_top{top_n}")
        adopted_mask = results_df["observation_datetime_utc"].isin(adopted_observations)
        missing_adopted = sorted(
            set(adopted_observations)
            - set(results_df.loc[adopted_mask, "observation_datetime_utc"])
        )
        if missing_adopted:
            raise ValueError(f"探索結果CSVに無い採用観測です: {', '.join(missing_adopted)}")
        _add(results_df.loc[adopted_mask, "scene_index"], "adopted")

    selected = results_df[results_df["scene_index"].isin(reasons)].copy()
    selected["selection_reason"] = selected["scene_index"].map(lambda s: ";".join(reasons[s]))
    return selected.sort_values(["observation_datetime_utc", "scene_index"]).reset_index(drop=True)


def anomaly_band_names() -> list[str]:
    """異常画素の QA ビット集計で用いるバンド名（＝出力列名）を返す。

    Returns:
        list[str]: フラグ・信頼度フィールドの各値・QA_RADSAT のバンド名。
    """
    names = list(QA_PIXEL_FLAG_BITS)
    for field in QA_PIXEL_CONFIDENCE_FIELDS:
        names.extend(f"{field}_{level}" for level in CONFIDENCE_LEVELS)
    names.append("radsat_nonzero")
    return names


def to_count(value: Any) -> int:
    """GEE の集計値（None・小数を含む）を画素数の整数に変換する。

    Args:
        value: `reduceRegion` の結果値。

    Returns:
        int: 画素数。None・NaN は 0 とする。
    """
    if value is None:
        return 0
    value = float(value)
    if math.isnan(value):
        return 0
    return int(round(value))


def build_anomaly_row(
    scene: dict[str, Any], anomaly_sums: dict[str, Any], threshold_c: float
) -> dict[str, Any]:
    """1 シーン分の異常画素 QA ビット集計の行を作る。

    Args:
        scene: 対象シーンの情報（`SCENE_META_COLUMNS` を含む）。
        anomaly_sums: `reduceRegion(sum)` の結果。`anomaly_pixels` と
            `anomaly_band_names()` の各キーを持つ。
        threshold_c: 異常と見なした LST の閾値（°C）。

    Returns:
        dict[str, Any]: CSV の 1 行。
    """
    row: dict[str, Any] = {column: scene[column] for column in SCENE_META_COLUMNS}
    row["threshold_c"] = threshold_c
    row["anomaly_pixels"] = to_count(anomaly_sums.get("anomaly_pixels"))
    for name in anomaly_band_names():
        row[name] = to_count(anomaly_sums.get(name))
    return row


def merge_variant_results(counts: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    """画素数と統計量の集計結果を 1 つの辞書にまとめる。

    `count` 単独の `reduceRegion` はキーがバンド名だけになるため、`{バンド名}_count`
    に揃えてから、統計量（`{バンド名}_{mean|min|max|stdDev}`）と合わせる。

    Args:
        counts: `reduceRegion(count)` の結果（キーはバンド名）。
        stats: `reduceRegion(mean/min/max/stdDev)` の結果。

    Returns:
        dict[str, Any]: `build_variant_rows()` に渡す辞書。
    """
    merged = {f"{band}_count": value for band, value in counts.items()}
    merged.update(stats)
    return merged


def build_variant_rows(
    scene: dict[str, Any], variant_stats: dict[str, Any], threshold_c: float
) -> list[dict[str, Any]]:
    """1 シーン分のマスク候補ごとの影響比較の行を作る。

    有効画素率・実効ROIカバー率は `gee_search_satellite_data.py` と同じ定義
    （有効画素率 0-100、実効ROIカバー率 = シーン被覆率 × 有効画素率）とする。
    衛星指標側の実効ROIカバー率は探索結果CSVの値を用いる（指標側のマスクは変えないため）。

    Args:
        scene: 対象シーンの情報（`SCENE_META_COLUMNS`・`scene_coverage_ratio`・
            `indices_effective_roi_coverage` を含む）。
        variant_stats: `reduceRegion` の結果。`lst__total_count` と、候補ごとの
            `lst__{name}_{count|mean|min|max|stdDev}`・`below__{name}_count` を持つ。
        threshold_c: 異常と見なした LST の閾値（°C）。

    Returns:
        list[dict[str, Any]]: 候補ごとの CSV の行（`MASK_VARIANTS` の順）。
    """
    total_pixels = to_count(variant_stats.get("lst__total_count"))
    scene_coverage_ratio = float(scene["scene_coverage_ratio"])
    indices_effective = float(scene["indices_effective_roi_coverage"])
    rows = []
    for variant in MASK_VARIANTS:
        prefix = f"lst__{variant.name}"
        valid_pixels = to_count(variant_stats.get(f"{prefix}_count"))
        valid_ratio = valid_pixels / total_pixels * 100.0 if total_pixels > 0 else 0.0
        lst_effective = scene_coverage_ratio * valid_ratio
        row: dict[str, Any] = {column: scene[column] for column in SCENE_META_COLUMNS}
        row.update(
            {
                "variant": variant.name,
                "mask_bits": ";".join(str(bit) for bit in variant.bits),
                "require_radsat_zero": variant.require_radsat_zero,
                "threshold_c": threshold_c,
                "lst_total_pixels": total_pixels,
                "lst_valid_pixels": valid_pixels,
                "lst_valid_pixel_ratio": valid_ratio,
                "scene_coverage_ratio": scene_coverage_ratio,
                "lst_effective_roi_coverage": lst_effective,
                "indices_effective_roi_coverage": indices_effective,
                "effective_roi_coverage": min(lst_effective, indices_effective),
                "lst_mean_temp_c": to_float_or_nan(variant_stats.get(f"{prefix}_mean")),
                "lst_min_temp_c": to_float_or_nan(variant_stats.get(f"{prefix}_min")),
                "lst_max_temp_c": to_float_or_nan(variant_stats.get(f"{prefix}_max")),
                "lst_std_temp_c": to_float_or_nan(variant_stats.get(f"{prefix}_stdDev")),
                "below_threshold_pixels": to_count(
                    variant_stats.get(f"below__{variant.name}_count")
                ),
            }
        )
        rows.append(row)
    return rows


def build_variant_mask(raw_sr_image: ee.Image, variant: MaskVariant) -> ee.Image:
    """マスク候補の判定画像（1=残す, 0=除外）を作る。

    Args:
        raw_sr_image: 未マスクの SR 画像。
        variant: マスク候補。

    Returns:
        ee.Image: 判定画像。
    """
    qa = raw_sr_image.select("QA_PIXEL")
    keep = qa.bitwiseAnd(build_qa_bit_mask(variant.bits)).eq(0)
    if variant.require_radsat_zero:
        keep = keep.And(raw_sr_image.select("QA_RADSAT").eq(0))
    return keep


def build_unmasked_lst(raw_sr_image: ee.Image, roi: ee.Geometry, sensor: str) -> ee.Image:
    """QA マスクをかけない SR から LST バンド（°C）を作る。

    Args:
        raw_sr_image: 未マスクの SR 画像。
        roi: ROI。
        sensor: センサ名（"L8" / "L9"）。SMW 係数の選択に用いる。

    Returns:
        ee.Image: `LST` バンドのみの画像。
    """
    scene_index = raw_sr_image.get("system:index")
    collection_toa = ee.ImageCollection(get_collection_id(sensor, "toa")).filter(
        ee.Filter.eq("system:index", scene_index)
    )
    toa_image = get_matching_toa_image(raw_sr_image, collection_toa)
    return calculate_lst_smw(raw_sr_image, toa_image, roi, sensor=sensor).select("LST")


def compute_scene_summary(
    scene_index: str, roi: ee.Geometry, threshold_c: float
) -> dict[str, dict[str, Any]]:
    """1 シーンについて候補ごとの集計と異常画素の QA ビット集計を GEE で行う。

    Args:
        scene_index: system:index。
        roi: ROI。
        threshold_c: 異常と見なす LST の閾値（°C）。

    Returns:
        dict[str, dict[str, Any]]: `variant`（候補ごとの統計）と `anomaly`
            （異常画素のビット別画素数）の 2 つの辞書。
    """
    sensor = sensor_from_scene_index(scene_index)
    raw_sr_image = ee.Image(f"{get_collection_id(sensor, 'sr')}/{scene_index}")
    lst = build_unmasked_lst(raw_sr_image, roi, sensor)

    # 候補ごとの LST と閾値未満の画素。先頭は本番の total_pixels と同じ定義（unmask 後の数）
    variant_bands = [lst.unmask().rename("lst__total")]
    for variant in MASK_VARIANTS:
        keep = build_variant_mask(raw_sr_image, variant)
        variant_lst = lst.updateMask(keep)
        variant_bands.append(variant_lst.rename(f"lst__{variant.name}"))
        variant_bands.append(
            variant_lst.lt(threshold_c).selfMask().rename(f"below__{variant.name}")
        )
    variant_image = ee.Image.cat(variant_bands)
    # 画素数は本番の calculate_pixel_stats と同じく count 単独で数える。
    # mean 等と組み合わせると ROI 縁の画素の扱いが変わり、画素数が本番と一致しないため
    variant_counts = variant_image.reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=roi,
        scale=REDUCE_SCALE_M,
        maxPixels=REDUCE_MAX_PIXELS,
    )
    # 統計量は本番の extract_statistics と同じ reducer の組み合わせで、候補の LST バンドだけに求める
    # （unmask 済みの lst__total は画素数にのみ使う）
    variant_lst_bands = [f"lst__{variant.name}" for variant in MASK_VARIANTS]
    variant_stats = variant_image.select(variant_lst_bands).reduceRegion(
        reducer=ee.Reducer.mean()
        .combine(ee.Reducer.min(), "", True)
        .combine(ee.Reducer.max(), "", True)
        .combine(ee.Reducer.stdDev(), "", True),
        geometry=roi,
        scale=REDUCE_SCALE_M,
        maxPixels=REDUCE_MAX_PIXELS,
    )

    # 変更前のマスクを通った画素のうち LST が閾値未満の画素（異常画素）の QA ビット
    current = MASK_VARIANTS[0]  # 先頭は変更前の条件（CURRENT_VARIANT_NAME）
    anomaly_mask = lst.lt(threshold_c).And(build_variant_mask(raw_sr_image, current))
    qa = raw_sr_image.select("QA_PIXEL")
    anomaly_bands = [lst.multiply(0).add(1).rename("anomaly_pixels")]
    for name, bit in QA_PIXEL_FLAG_BITS.items():
        anomaly_bands.append(qa.rightShift(bit).bitwiseAnd(1).rename(name))
    for field, start_bit in QA_PIXEL_CONFIDENCE_FIELDS.items():
        field_value = qa.rightShift(start_bit).bitwiseAnd(3)
        for level in CONFIDENCE_LEVELS:
            anomaly_bands.append(field_value.eq(level).rename(f"{field}_{level}"))
    anomaly_bands.append(raw_sr_image.select("QA_RADSAT").neq(0).rename("radsat_nonzero"))
    # 画素数として数えるため、ROI 縁の画素を面積で重み付けしない sum を用いる
    anomaly_sums = (
        ee.Image.cat(anomaly_bands)
        .updateMask(anomaly_mask)
        .reduceRegion(
            reducer=ee.Reducer.sum().unweighted(),
            geometry=roi,
            scale=REDUCE_SCALE_M,
            maxPixels=REDUCE_MAX_PIXELS,
        )
    )

    # 3 つの集計を 1 回の往復で取得する
    summary = ee.Dictionary(
        {"counts": variant_counts, "stats": variant_stats, "anomaly": anomaly_sums}
    ).getInfo()
    return {
        "variant": merge_variant_results(summary["counts"], summary["stats"]),
        "anomaly": summary["anomaly"],
    }


def save_rows(rows: list[dict[str, Any]], output_path: Path) -> None:
    """行のリストを UTF-8 の CSV に保存する。

    Args:
        rows: CSV の行。
        output_path: 出力先。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False, encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    """対象シーンを選び、シーンごとに集計して 2 つの CSV に保存する。

    中断に備え、1 シーン処理するごとに CSV を上書き保存する。

    Args:
        args: `parse_arguments()` の結果。

    Raises:
        ValueError: 設定CSVに GCP プロジェクトID・ROI が無い場合。
    """
    config = load_config(str(args.config_path))
    gee_project_id = config.get("gee_project_id")
    if not gee_project_id or gee_project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError("GCPプロジェクトIDが設定されていません。設定CSVを確認してください。")
    roi_path_text = str(config.get("roi_shapefile_path") or "").strip()
    if not roi_path_text:
        raise ValueError("設定CSVに roi_shapefile_path がありません。")

    results_df = pd.read_csv(args.results_csv_path)
    ranking_df = pd.read_csv(args.ranking_csv_path)
    targets = select_target_scenes(
        results_df,
        ranking_df,
        threshold_c=args.threshold_c,
        top_n=args.top_n,
        adopted_observations=args.adopted_observations,
        scene_indices=args.scene_indices,
    )
    logger.info("対象シーン数: %s", len(targets))

    authenticate_gee(project_id=gee_project_id)
    roi = load_roi_from_shapefile(roi_path_text)

    anomaly_rows: list[dict[str, Any]] = []
    variant_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for scene in tqdm(targets.to_dict("records"), desc="QAビット検証中"):
        scene_index = scene["scene_index"]
        try:
            summary = compute_scene_summary(scene_index, roi, args.threshold_c)
        except Exception as error:
            logger.error("集計に失敗しました（scene_index=%s）: %s", scene_index, error)
            failures.append(scene_index)
            continue
        anomaly_row = build_anomaly_row(scene, summary["anomaly"], args.threshold_c)
        anomaly_rows.append(anomaly_row)
        new_variant_rows = build_variant_rows(scene, summary["variant"], args.threshold_c)
        variant_rows.extend(new_variant_rows)
        save_rows(anomaly_rows, args.anomaly_csv_path)
        save_rows(variant_rows, args.variant_csv_path)
        current_row = new_variant_rows[0]
        logger.info(
            "%s: 異常画素=%s, current の最小値=%.1f°C・有効画素率=%.1f%%",
            scene_index,
            anomaly_row["anomaly_pixels"],
            current_row["lst_min_temp_c"],
            current_row["lst_valid_pixel_ratio"],
        )

    logger.info("完了: 成功 %s 件・失敗 %s 件", len(anomaly_rows), len(failures))
    if failures:
        logger.warning("失敗したシーン: %s", ", ".join(failures))
    logger.info("異常画素の QA ビット集計: %s", args.anomaly_csv_path)
    logger.info("マスク候補ごとの影響比較: %s", args.variant_csv_path)


def main() -> None:
    """エントリポイント。"""
    run(parse_arguments())


if __name__ == "__main__":
    main()
