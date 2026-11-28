"""水域率の元データの感度分析に使う派生データセットを作る。

主採用観測の衛星＋公開GISデータのデータセット（GLC 版）から、水域被覆率
`LULC_WATER_COV` だけを JRC Global Surface Water 由来の水域率に置き換えたデータセットを、
JRC の候補（月次 2021-09・Occurrence 50% 以上・25% 以上）と、他の土地被覆列の扱い
（据え置き・正規化）の組み合わせごとに 1 本ずつ書き出す。主採用のデータセットには書き込まない。

方法上の要点:
- **集約**: `compare_water_sources` と同じ関数（`aggregate_binary_water`。中身は
  `LULC_WATER_COV` と同じ `aggregate_class_fractions_to_grid`）と同じ正準グリッドを使う。
- **セルの有効条件**: 有効画素率が `MIN_VALID_RATIO` 以上のセルだけを有効とする
  （`compare_water_sources.binarize_fraction` の有効条件と同じ）。
- **共通セル集合**: GLC の `LULC_WATER_COV` が欠測でなく、JRC の全候補が有効なセル。
  派生データセットでは、この集合の外の `LULC_WATER_COV` を欠測にする。分析スクリプトは
  この列に非 NULL を要求するため、どの派生データセットでも有効母集団が同じになる。
- **構成データの扱い**: 土地被覆 7 列は和が 1 の構成データである。次の 2 通りを作る。
  - **据え置き**（主）: 水域以外の 6 列は GLC のまま。変わる列が水域だけになる。参照クラスの
    農地はモデルに入らないため、暗黙の農地率は `農地率(GLC) + 水域率(GLC) - 水域率(JRC)` となる。
    GLC で農地以外（湿地等）のセルを JRC が水域とする場合は負になる（水域と他クラスの
    二重計上）。該当セルの件数・水域セルに占める割合・GLC の優占クラスを記録する。
  - **正規化**（副）: 水域以外の 6 列を、互いの比を保って和が `1 - 水域率(JRC)` になるよう
    伸縮する。6 列の和が 0 のセル（GLC が全面水域）は比が決まらないため、残りを農地に入れる。
    水域以外の投入列も変わるため、水域データだけの違いではなくなる。
- **人口密度の補完の扱い**: 水域優位セルの 0 補完は GLC の判定のまま据え置く。JRC の水域率で
  判定した場合に補完の有無が変わるセルを数えて記録する。

実行例::

    python -m src.analysis.build_water_sensitivity_datasets
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio

from src.analysis.build_dataset import (
    WATER_DOMINANT_THRESHOLD,
    population_filled_flag_column,
    resolve_dataset_path,
)
from src.analysis.compare_water_sources import (
    CELL_ID_COLUMN,
    CITY,
    COARSE_RES_M,
    DATASET_WATER_COLUMN,
    DEFAULT_DATASET_PATH,
    DEFAULT_JRC_PATH,
    JRC_BAND_INDEX,
    MIN_VALID_RATIO,
    WATER_FRACTION_THRESHOLD,
    aggregate_binary_water,
    binarize_fraction,
    build_binary_lookup,
    build_occurrence_lookup,
    build_roi_canonical_grid,
    locate_cells,
)
from src.analysis.compare_water_sources import WATCH_PATHS as WATER_SOURCE_WATCH_PATHS
from src.analysis.urban_params.config import POPULATION_BASE_COLUMNS
from src.analysis.urban_params.params.lulc import COLUMN_TO_COMMON_CLASS
from src.analysis.urban_params.tables import write_attribute_table
from src.common.analysis_dataset import IN_ANALYSIS_AREA_COLUMN
from src.common.config import PRIMARY_OBSERVATION_ID, PROJECT_ROOT
from src.common.log_setup import configure_logging
from src.common.paths import (
    prepare_output_path,
    resolve_existing_path,
    resolve_relative_to_project_root,
    to_project_relative_string,
)
from src.common.summary import build_provenance, describe_input_files, save_summary

SCRIPT_NAME = "src.analysis.build_water_sensitivity_datasets"
# 集約・グリッド・書き出し・人口補完の定義が変わると結果が変わるため監視に加える
WATCH_PATHS: tuple[str, ...] = (
    "src/analysis/compare_water_sources.py",
    "src/analysis/build_dataset.py",
    *WATER_SOURCE_WATCH_PATHS,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "datasets"
DEFAULT_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "output"
    / "limited"
    / f"{PRIMARY_OBSERVATION_ID}_water_sensitivity"
    / "water_sensitivity_datasets_results.json"
)

CROP_COLUMN = "LULC_CROP_COV"
LULC_COLUMNS: tuple[str, ...] = tuple(COLUMN_TO_COMMON_CLASS)
NON_WATER_LULC_COLUMNS: tuple[str, ...] = tuple(
    column for column in LULC_COLUMNS if column != DATASET_WATER_COLUMN
)
# 他の土地被覆列の扱いの識別子と、派生データセット名に付ける接尾辞
COMPOSITION_FIXED = "fixed"
COMPOSITION_NORMALIZED = "normalized"
COMPOSITION_SUFFIXES: dict[str, str] = {COMPOSITION_FIXED: "", COMPOSITION_NORMALIZED: "norm"}
# 人口密度列の接頭辞（データソース識別子の前の部分）
POPULATION_DENSITY_PREFIX = f"{POPULATION_BASE_COLUMNS[0]}_"
# 共通セル集合とその外のセルの性格を比べる列（いずれも GLC 版データセットの値）
PROFILE_COLUMNS: tuple[str, ...] = ("LST", "NDVI", "BUILD_COV", DATASET_WATER_COLUMN)
# 面積率を 0 とみなす許容差。float32 の丸め（1e-7 程度）を負や正の面積と数えないための余裕
FRACTION_TOLERANCE = 1e-6
# 差し替えに使う Occurrence の閾値（%）。主は 50%
OCCURRENCE_THRESHOLDS: tuple[int, ...] = (50, 25)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaterCandidate:
    """差し替えに使う JRC の水域の定義。

    Attributes:
        key: 出力で使う識別子。
        label: 日本語の表示名。
        dataset_suffix: 派生データセット名の接尾辞。
        band_name: JRC ラスタのバンド名。
        lookup: 画素値 → 水域／非水域の引き当て表。
    """

    key: str
    label: str
    dataset_suffix: str
    band_name: str
    lookup: np.ndarray


def build_candidates() -> list[WaterCandidate]:
    """JRC の候補を作る。

    Returns:
        候補のリスト（月次・Occurrence 50%・Occurrence 25% の順）。
    """
    candidates = [
        WaterCandidate(
            key="jrc_monthly",
            label="JRC 月次 2021-09",
            dataset_suffix="waterjrcmonthly",
            band_name="monthly_water",
            lookup=build_binary_lookup([2], [1]),
        )
    ]
    candidates += [
        WaterCandidate(
            key=f"jrc_occ{threshold}",
            label=f"JRC Occurrence {threshold}% 以上",
            dataset_suffix=f"waterjrcocc{threshold}",
            band_name="occurrence",
            lookup=build_occurrence_lookup(threshold),
        )
        for threshold in OCCURRENCE_THRESHOLDS
    ]
    return candidates


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数列。None の場合は `sys.argv` を使う。

    Returns:
        解析済みの引数。
    """
    parser = argparse.ArgumentParser(
        description="水域率を JRC GSW 由来に差し替えた感度分析用データセットを作る。"
    )
    parser.add_argument(
        "--dataset-path", type=Path, default=DEFAULT_DATASET_PATH, help="GLC 版のデータセット"
    )
    parser.add_argument(
        "--jrc-path", type=Path, default=DEFAULT_JRC_PATH, help="JRC GSW ラスタ（GeoTIFF）"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="派生データセットの出力先"
    )
    parser.add_argument(
        "--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH, help="要約 JSON の出力先"
    )
    return parser.parse_args(argv)


def mask_invalid_fraction(fraction: np.ndarray, valid_ratio: np.ndarray) -> np.ndarray:
    """有効画素率が足りないセルの水域面積率を欠測にする。

    Args:
        fraction: 水域面積率（NaN は有効画素なし）。
        valid_ratio: 有効画素率。

    Returns:
        無効セルを NaN にした float32 の面積率。
    """
    _, valid = binarize_fraction(fraction, valid_ratio)
    return np.where(valid, fraction, np.nan).astype(np.float32)


def build_common_cell_mask(
    glc_water: np.ndarray, candidate_water: Mapping[str, np.ndarray]
) -> np.ndarray:
    """GLC と JRC の全候補がともに有効なセルを求める。

    Args:
        glc_water: GLC の水域率（NaN は欠測）。
        candidate_water: 候補の識別子 → 水域率（NaN は無効）。

    Returns:
        共通セル集合に入るセルを True とする配列。

    Raises:
        ValueError: 共通セルが 1 つも無い場合。
    """
    mask = ~np.isnan(glc_water)
    for values in candidate_water.values():
        mask &= ~np.isnan(values)
    if not bool(mask.any()):
        raise ValueError("GLC と JRC の全候補がともに有効なセルがありません。")
    return mask


def summarize_water_fraction(
    water: np.ndarray, glc_water: np.ndarray, cell_mask: np.ndarray
) -> dict[str, Any]:
    """セル集合の中での水域率の分布と、GLC との違いを集計する。

    Args:
        water: 水域率（NaN は無効）。
        glc_water: GLC の水域率。
        cell_mask: 集計するセル。

    Returns:
        有効セル数・水域セル数・平均・標準偏差・GLC との相関と差を持つ辞書。水域セル数と面積は
        候補自身の有効セルから、平均以下の統計は GLC とともに有効なセルから求める。
    """
    valid = cell_mask & ~np.isnan(water)
    usable = valid & ~np.isnan(glc_water)
    values = water[usable].astype(np.float64)
    reference = glc_water[usable].astype(np.float64)
    correlation: float | None = None
    if values.size > 1 and values.std() > 0 and reference.std() > 0:
        correlation = float(np.corrcoef(values, reference)[0, 1])
    water_cells = int((water[valid] >= WATER_FRACTION_THRESHOLD).sum())
    has_values = values.size > 0
    return {
        "cells": int(cell_mask.sum()),
        "valid_cells": int(valid.sum()),
        "compared_cells": int(values.size),
        "water_cells": water_cells,
        "water_area_km2": water_cells * COARSE_RES_M * COARSE_RES_M / 1e6,
        "mean": float(values.mean()) if has_values else None,
        "std": float(values.std()) if has_values else None,
        "zero_cell_ratio": float((values == 0).mean()) if has_values else None,
        "one_cell_ratio": float((values == 1).mean()) if has_values else None,
        "pearson_with_glc": correlation,
        "mean_difference_from_glc": float((values - reference).mean()) if has_values else None,
        "mean_absolute_difference_from_glc": (
            float(np.abs(values - reference).mean()) if has_values else None
        ),
        "unchanged_cell_ratio": float((values == reference).mean()) if has_values else None,
    }


def count_classes(dominant: np.ndarray) -> dict[str, int]:
    """優占クラス別の件数を数える。

    Args:
        dominant: セルごとの優占クラスの列名。

    Returns:
        土地被覆の列名 → 件数（該当の無いクラスは 0）。
    """
    return {column: int((dominant == column).sum()) for column in LULC_COLUMNS}


def summarize_composition_overlap(
    dataset: pd.DataFrame, water: np.ndarray, cell_mask: np.ndarray
) -> dict[str, Any]:
    """水域以外の 6 列を据え置いたときの、水域と他クラスの二重計上を集計する。

    Args:
        dataset: GLC 版のデータセット。
        water: 差し替え後の水域率。
        cell_mask: 集計するセル。

    Returns:
        暗黙の農地率が負になるセルの件数・割合・最小値・平均、水域セルに占める件数と割合、
        GLC の優占クラス別の件数、差し替え後だけが水域とするセルの GLC の優占クラス別の件数。
    """
    subset = dataset.loc[cell_mask, list(LULC_COLUMNS)].astype(np.float64)
    new_water = water[cell_mask].astype(np.float64)
    glc_water = subset[DATASET_WATER_COLUMN].to_numpy()
    implied = subset[CROP_COLUMN].to_numpy() + glc_water - new_water
    negative = implied < -FRACTION_TOLERANCE
    water_cells = new_water >= WATER_FRACTION_THRESHOLD
    glc_water_cells = glc_water >= WATER_FRACTION_THRESHOLD
    replaced_only = water_cells & ~glc_water_cells
    # 同率の場合は列の並びの先頭を採る（実行ごとに結果が変わらないように）
    dominant = np.asarray(LULC_COLUMNS)[np.argmax(subset.to_numpy(), axis=1)]
    negative_water_cells = int((negative & water_cells).sum())
    return {
        "definition": "暗黙の農地率 = 農地率(GLC) + 水域率(GLC) - 水域率(差し替え後)",
        "tolerance": FRACTION_TOLERANCE,
        "cells": int(implied.size),
        "negative_cells": int(negative.sum()),
        "negative_cell_ratio": float(negative.mean()) if implied.size else None,
        "minimum": float(implied.min()) if implied.size else None,
        "negative_mean": float(implied[negative].mean()) if negative.any() else None,
        "water_cells": int(water_cells.sum()),
        "negative_water_cells": negative_water_cells,
        "negative_ratio_in_water_cells": (
            negative_water_cells / int(water_cells.sum()) if water_cells.any() else None
        ),
        "negative_cells_by_glc_dominant_class": count_classes(dominant[negative]),
        "glc_only_water_cells": int((glc_water_cells & ~water_cells).sum()),
        "replaced_only_water_cells": int(replaced_only.sum()),
        "replaced_only_water_cells_by_glc_dominant_class": count_classes(dominant[replaced_only]),
    }


def find_population_suffixes(columns: Sequence[str]) -> list[str]:
    """データセットの列名から、人口密度のデータソースの接尾辞を取り出す。

    Args:
        columns: データセットの列名。

    Returns:
        接尾辞のリスト（例: `WORLDPOP2020`）。

    Raises:
        ValueError: 人口密度の列が無い場合、または補完のフラグ列が無い場合。
    """
    suffixes = [
        column.removeprefix(POPULATION_DENSITY_PREFIX)
        for column in columns
        if column.startswith(POPULATION_DENSITY_PREFIX)
    ]
    if not suffixes:
        raise ValueError("データセットに人口密度の列がありません。")
    missing = [
        population_filled_flag_column(suffix)
        for suffix in suffixes
        if population_filled_flag_column(suffix) not in columns
    ]
    if missing:
        raise ValueError(f"データセットに人口補完のフラグ列がありません: {missing}")
    return suffixes


def summarize_population_fill(
    density: np.ndarray,
    filled_flag: np.ndarray,
    glc_water: np.ndarray,
    water: np.ndarray,
    cell_mask: np.ndarray,
) -> dict[str, int]:
    """人口密度の 0 補完の判定が、水域率の差し替えで変わるセルを数える。

    元の欠測は「補完後も欠測のセル」と「補完のフラグが立ったセル」の和として復元する。

    Args:
        density: 補完後の人口密度（NaN は補完されなかった欠測）。
        filled_flag: 補完のフラグ（1 = 0 で補完した）。
        glc_water: GLC の水域率。
        water: 差し替え後の水域率（NaN は無効。水域優位と判定しない）。
        cell_mask: 集計するセル。

    Returns:
        元の欠測セル数、双方の判定による補完セル数、食い違うセル数を持つ辞書。

    Raises:
        ValueError: フラグが GLC の判定（`WATER_DOMINANT_THRESHOLD`）と一致しない場合。
            別の下限で作ったデータセットでは食い違いの数を正しく求められないため。
    """
    filled = filled_flag == 1
    originally_missing = np.isnan(density) | filled
    # NaN との比較は False になる（水域優位と判定しない）
    glc_filled = originally_missing & (glc_water >= WATER_DOMINANT_THRESHOLD)
    if not np.array_equal(glc_filled, filled):
        raise ValueError(
            "人口補完のフラグが GLC の水域優位の判定と一致しません"
            f"（不一致 {int((glc_filled != filled).sum())} 件）。"
            f"下限 {WATER_DOMINANT_THRESHOLD} で作ったデータセットを指定してください。"
        )
    replaced_filled = originally_missing & (water >= WATER_DOMINANT_THRESHOLD)
    return {
        "originally_missing_cells": int((originally_missing & cell_mask).sum()),
        "glc_filled_cells": int((glc_filled & cell_mask).sum()),
        "replaced_filled_cells": int((replaced_filled & cell_mask).sum()),
        "glc_only_filled_cells": int((glc_filled & ~replaced_filled & cell_mask).sum()),
        "replaced_only_filled_cells": int((replaced_filled & ~glc_filled & cell_mask).sum()),
    }


def summarize_profile(dataset: pd.DataFrame, cell_mask: np.ndarray) -> dict[str, Any]:
    """セル集合の件数と、主な列の平均を求める。

    Args:
        dataset: GLC 版のデータセット。
        cell_mask: 集計するセル。

    Returns:
        件数と、列ごとの平均（欠測を除く。全件欠測の列は None）・欠測数を持つ辞書。
    """
    subset = dataset.loc[cell_mask, list(PROFILE_COLUMNS)].astype(np.float64)
    means = subset.mean()
    return {
        "cells": int(cell_mask.sum()),
        "means": {
            column: None if pd.isna(means[column]) else float(means[column])
            for column in PROFILE_COLUMNS
        },
        "missing_counts": {column: int(subset[column].isna().sum()) for column in PROFILE_COLUMNS},
    }


def replace_water_column(
    dataset: pd.DataFrame, water: np.ndarray, common_mask: np.ndarray
) -> pd.DataFrame:
    """水域列だけを差し替えたデータセットを作る（据え置き）。

    Args:
        dataset: GLC 版のデータセット。
        water: 差し替える水域率。
        common_mask: 共通セル集合。集合の外は欠測にする。

    Returns:
        列構成・列順・行順が同じで、`LULC_WATER_COV` だけが異なるデータセット。
    """
    result = dataset.copy()
    result[DATASET_WATER_COLUMN] = np.where(common_mask, water, np.nan).astype(np.float32)
    return result


def normalize_composition(
    dataset: pd.DataFrame, water: np.ndarray, common_mask: np.ndarray
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """水域列を差し替え、他の土地被覆列を伸縮して和を 1 に戻したデータセットを作る（正規化）。

    Args:
        dataset: GLC 版のデータセット。
        water: 差し替える水域率。
        common_mask: 共通セル集合。集合の外は水域列を欠測にし、他の列は変えない。

    Returns:
        (列構成・列順・行順が同じで、土地被覆 7 列だけが異なるデータセット, 集計の辞書)。
        集計は共通セル集合の全セル（分析対象範囲の外を含む）から求める。
    """
    result = replace_water_column(dataset, water, common_mask)
    others = dataset.loc[common_mask, list(NON_WATER_LULC_COLUMNS)].to_numpy(dtype=np.float64)
    remainder = 1.0 - water[common_mask].astype(np.float64)
    other_sum = others.sum(axis=1)
    undefined = other_sum <= FRACTION_TOLERANCE
    scale = np.divide(remainder, other_sum, out=np.zeros_like(remainder), where=~undefined)
    scaled = others * scale[:, np.newaxis]
    # 6 列の和が 0 のセルは比が決まらないため、残りを参照クラスの農地に入れる
    scaled[undefined] = 0.0
    scaled[undefined, NON_WATER_LULC_COLUMNS.index(CROP_COLUMN)] = remainder[undefined]
    for index, column in enumerate(NON_WATER_LULC_COLUMNS):
        values = dataset[column].to_numpy(dtype=np.float32, copy=True)
        values[common_mask] = scaled[:, index].astype(np.float32)
        result[column] = values

    before = dataset.loc[common_mask, list(LULC_COLUMNS)].astype(np.float64)
    after = result.loc[common_mask, list(LULC_COLUMNS)].astype(np.float64)
    moved_to_crop = undefined & (remainder > FRACTION_TOLERANCE)
    return result, {
        "cells": int(common_mask.sum()),
        "remainder_to_crop_cells": int(moved_to_crop.sum()),
        "remainder_to_crop_mean": (
            float(remainder[moved_to_crop].mean()) if moved_to_crop.any() else None
        ),
        "max_abs_deviation_from_one": float((after.sum(axis=1) - 1.0).abs().max()),
        "column_means_glc": {column: float(before[column].mean()) for column in LULC_COLUMNS},
        "column_means_normalized": {column: float(after[column].mean()) for column in LULC_COLUMNS},
    }


def load_base_dataset(dataset_path: Path) -> tuple[pd.DataFrame, str]:
    """GLC 版のデータセットを全列読み込む。

    Args:
        dataset_path: データセット GeoPackage（属性のみのレイヤ 1 つ）。

    Returns:
        (データフレーム, レイヤ名)。

    Raises:
        ValueError: レイヤが 1 つでない場合、必要な列が無い場合、`cell_id` が重複する場合。
    """
    layers = pyogrio.list_layers(dataset_path)
    if len(layers) != 1:
        raise ValueError(f"レイヤが 1 つではありません: {layers.tolist()}（{dataset_path}）")
    layer_name = str(layers[0][0])
    dataset = pyogrio.read_dataframe(dataset_path, layer=layer_name, read_geometry=False)
    required = {CELL_ID_COLUMN, IN_ANALYSIS_AREA_COLUMN, *LULC_COLUMNS, *PROFILE_COLUMNS}
    missing = sorted(required - set(dataset.columns))
    if missing:
        raise ValueError(f"データセットに必要な列がありません: {missing}（{dataset_path}）")
    if dataset[CELL_ID_COLUMN].duplicated().any():
        raise ValueError(f"cell_id に重複があります: {dataset_path}")
    return dataset, layer_name


def aggregate_candidates(
    cell_ids: np.ndarray, jrc_path: Path, candidates: Sequence[WaterCandidate]
) -> tuple[dict[str, np.ndarray], Path]:
    """JRC の候補を正準グリッドへ集約し、セルごとの水域率を求める。

    Args:
        cell_ids: データセットの `cell_id`。
        jrc_path: JRC GSW ラスタ。
        candidates: 集約する候補。

    Returns:
        (候補の識別子 → 水域率（無効セルは NaN）, グリッドの作成に使った ROI のパス)。
    """
    canonical_spec, roi_path = build_roi_canonical_grid()
    grid_spec, flat_indices = locate_cells(cell_ids, canonical_spec)
    result: dict[str, np.ndarray] = {}
    for candidate in candidates:
        logger.info("%s を集約します。", candidate.label)
        fraction, valid_ratio = aggregate_binary_water(
            jrc_path,
            JRC_BAND_INDEX[candidate.band_name],
            candidate.lookup,
            grid_spec,
            flat_indices,
        )
        result[candidate.key] = mask_invalid_fraction(fraction, valid_ratio)
    return result, roi_path


def build_summary(
    dataset: pd.DataFrame,
    candidates: Sequence[WaterCandidate],
    candidate_water: Mapping[str, np.ndarray],
    common_mask: np.ndarray,
) -> dict[str, Any]:
    """差し替えの影響を集計した要約を組み立てる（来歴・出力は含めない）。

    Args:
        dataset: GLC 版のデータセット。
        candidates: 候補。
        candidate_water: 候補の識別子 → 水域率。
        common_mask: 共通セル集合（分析対象範囲の外のセルも含む）。

    Returns:
        要約の辞書。集計はいずれも分析対象範囲（`IN_ANALYSIS_AREA == 1`）のセルに限る。
    """
    in_area = dataset[IN_ANALYSIS_AREA_COLUMN].to_numpy() == 1
    glc_water = dataset[DATASET_WATER_COLUMN].to_numpy(dtype=np.float32)
    common_in_area = common_mask & in_area
    glc_valid_in_area = in_area & ~np.isnan(glc_water)
    suffixes = find_population_suffixes(list(dataset.columns))

    candidate_summaries: dict[str, Any] = {}
    for candidate in candidates:
        water = candidate_water[candidate.key]
        candidate_summaries[candidate.key] = {
            "label": candidate.label,
            "in_area": summarize_water_fraction(water, glc_water, in_area),
            "common": summarize_water_fraction(water, glc_water, common_in_area),
            "composition_overlap": summarize_composition_overlap(dataset, water, common_in_area),
            "population_fill": {
                suffix: summarize_population_fill(
                    dataset[f"{POPULATION_DENSITY_PREFIX}{suffix}"].to_numpy(dtype=np.float64),
                    dataset[population_filled_flag_column(suffix)].to_numpy(),
                    glc_water,
                    water,
                    common_in_area,
                )
                for suffix in suffixes
            },
        }

    return {
        "description": "水域率を JRC GSW 由来に差し替えた感度分析用データセットの要約",
        "settings": {
            "min_valid_ratio": MIN_VALID_RATIO,
            "water_fraction_threshold": WATER_FRACTION_THRESHOLD,
            "water_dominant_threshold": WATER_DOMINANT_THRESHOLD,
            "composition": {
                COMPOSITION_FIXED: "水域以外の LULC_*_COV は GLC のまま据え置く（主）",
                COMPOSITION_NORMALIZED: (
                    "水域以外の LULC_*_COV を、比を保って和が 1 - 水域率になるよう伸縮する（副）"
                ),
            },
            "population_fill": "GLC の水域率による判定のまま据え置く",
            "scope": f"{IN_ANALYSIS_AREA_COLUMN} == 1 のセル（LST の有効性は問わない）",
        },
        "common_cells": {
            "in_area_cells": int(in_area.sum()),
            "glc_valid_cells": int(glc_valid_in_area.sum()),
            "common_cells": int(common_in_area.sum()),
            "profile_common": summarize_profile(dataset, common_in_area),
            "profile_excluded": summarize_profile(dataset, glc_valid_in_area & ~common_mask),
        },
        "glc": {
            "in_area": summarize_water_fraction(glc_water, glc_water, in_area),
            "common": summarize_water_fraction(glc_water, glc_water, common_in_area),
        },
        "candidates": candidate_summaries,
    }


def run(dataset_path: Path, jrc_path: Path, output_dir: Path, summary_path: Path) -> Path:
    """派生データセットの作成と要約の保存を行う。

    Args:
        dataset_path: GLC 版のデータセット。
        jrc_path: JRC GSW ラスタ。
        output_dir: 派生データセットの出力先。
        summary_path: 要約 JSON の出力先。

    Returns:
        要約 JSON のパス。

    Raises:
        FileNotFoundError: 入力ファイルが無い場合。
    """
    dataset_path = resolve_existing_path(dataset_path)
    jrc_path = resolve_existing_path(jrc_path)
    output_dir = resolve_relative_to_project_root(output_dir, project_root=PROJECT_ROOT)
    summary_path = prepare_output_path(summary_path)

    dataset, layer_name = load_base_dataset(dataset_path)
    logger.info("GLC 版データセット: %d 行（レイヤ %s）", len(dataset), layer_name)
    candidates = build_candidates()
    candidate_water, roi_path = aggregate_candidates(
        dataset[CELL_ID_COLUMN].to_numpy(), jrc_path, candidates
    )
    common_mask = build_common_cell_mask(
        dataset[DATASET_WATER_COLUMN].to_numpy(dtype=np.float32), candidate_water
    )
    # 集計で前提の崩れ（人口補完の下限違い等）を検出するため、書き出しより先に行う
    summary = build_summary(dataset, candidates, candidate_water, common_mask)

    output_paths: dict[str, Path] = {}
    for candidate in candidates:
        water = candidate_water[candidate.key]
        normalized, normalization = normalize_composition(dataset, water, common_mask)
        summary["candidates"][candidate.key]["normalization"] = normalization
        frames = {
            COMPOSITION_FIXED: replace_water_column(dataset, water, common_mask),
            COMPOSITION_NORMALIZED: normalized,
        }
        for composition, frame in frames.items():
            dataset_name = (
                f"{layer_name}_{candidate.dataset_suffix}{COMPOSITION_SUFFIXES[composition]}"
            )
            output_path = resolve_dataset_path(dataset_name, CITY, int(COARSE_RES_M), output_dir)
            write_attribute_table(frame, output_path, dataset_name)
            output_paths[f"{candidate.key}_{composition}"] = output_path
            logger.info("書き出しました: %s", output_path.name)

    # 派生データセットは Git 管理外のため、内容をハッシュで特定できるようにする
    output_records = describe_input_files(list(output_paths.values()))
    summary["outputs"] = {
        "datasets": dict(zip(output_paths, output_records, strict=True)),
        "summary": to_project_relative_string(summary_path),
    }
    summary["provenance"] = build_provenance(
        SCRIPT_NAME, [dataset_path, jrc_path, roi_path], extra_watch_paths=WATCH_PATHS
    )
    save_summary(summary, summary_path)
    return summary_path


def main(argv: Sequence[str] | None = None) -> None:
    """派生データセットを作る。

    Args:
        argv: 引数列。None の場合は `sys.argv` を使う。
    """
    configure_logging()
    args = parse_arguments(argv)
    summary_path = run(args.dataset_path, args.jrc_path, args.output_dir, args.summary_path)
    logger.info("要約を保存しました: %s", summary_path)


if __name__ == "__main__":
    main()
