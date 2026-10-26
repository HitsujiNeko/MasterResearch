"""全シナリオ・全人口ソースで共通の評価セル集合と fold 割り当てを生成するスクリプト。

Satellite Only と Limited（人口3版）を「同じセル・同じ fold」の上で比べるため、
次の4構成の有効母集団の**積（共通部分）**を評価用の母集団とし、そこから標本を
1回だけ抽出して fold を割り当て、評価セル CSV とメタデータ JSON に保存する。

| 構成 | 有効母集団の求め方 |
|---|---|
| `satellite_only` | `analysis_rq3_satellite_only.build_valid_population` |
| `limited_{人口ソース}` | `analysis_rq3_limited.build_valid_population`（人口ソース別の品質列） |

有効条件は各スクリプトの関数をそのまま呼び、ここでは書き直さない（定義が二重に
なってずれるのを防ぐため）。入力データセットはシナリオごとに別ファイルであるため、
`cell_id` で突き合わせて積を取り、共通セル上で `LST`・`NDVI`・`NDBI` の値が
2ファイル間で一致することを検査する（ずれていると、対応のある差が別の目的変数
どうしの比較になる）。1件でも不一致があれば停止する。

共通集合を `cell_id` 順に並べてから抽出するのは、抽出結果がデータセットの行順に
依存しないようにするためである。fold は既存の分析スクリプトと同じ
`assign_canonical_blocks` と `split_by_spatial_blocks`（GroupKFold）で割り当てる。

あわせて、構成ごとに「その構成の有効母集団には含まれるが共通集合から外れたセル」
（脱落セル）の性格を集計してメタデータへ記録する。件数・LST・NDVI・建物被覆・
水域被覆と、ブロック単位の集中度（結果ドキュメントの「空間的な集中」と同じ物差し）
を、共通集合自体の同じ統計と並べて比べられるようにする。

既定値（LST 有効率の下限・標本サイズ・乱数シード・ブロックサイズ・分割数・解像度）は
両分析スクリプトの `parse_arguments([])` から読む（既定値を二重に持たないため）。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.analysis import analysis_rq3_limited as limited
from src.analysis import analysis_rq3_satellite_only as satellite_only
from src.analysis.urban_params.canonical_grid import assign_canonical_blocks
from src.common.analysis_dataset import ANALYSIS_AREA_ROI, sample_dataset
from src.common.analysis_runs import build_observation_label, validate_scale_matches_dataset
from src.common.config import PROJECT_ROOT
from src.common.evaluation_cells import (
    CELL_ID_COLUMN,
    FOLD_COLUMN,
    build_evaluation_cells,
    build_fold_labels,
    save_evaluation_set,
)
from src.common.paths import to_project_relative_string
from src.common.spatial_cv import split_by_spatial_blocks
from src.common.summary import build_provenance

SATELLITE_ONLY_CONFIGURATION = "satellite_only"
# Limited で共通集合に含める人口ソース。構成を加える場合はここへ追加する。
LIMITED_POPULATION_SOURCES = ("worldpop2020", "landscan2020", "landscan2023")
# 共通セル上で2つのデータセットの値が一致することを検査する列。
CONSISTENCY_COLUMNS = ("LST", "NDVI", "NDBI")
# 脱落セルの性格として平均を記録する列（LST は平均・標準偏差を記録する）。
DROPOUT_MEAN_COLUMNS = ("NDVI", "BUILD_COV", "LULC_WATER_COV")
WATER_COVER_COLUMN = "LULC_WATER_COV"
# 水域被覆の階級。結果ドキュメントの「水域被覆の偏り」の表と同じ区切りにする。
# （階級名, 下限（含む）, 上限（含まない））。「なし」は 0 ちょうどのみ。
WATER_COVER_CLASSES = (
    ("none", 0.0, 0.0),
    ("slight", 0.0, 0.1),
    ("partial", 0.1, 0.5),
    ("dominant", 0.5, 0.9),
    ("water", 0.9, np.inf),
)
# ブロック単位の集中度で「脱落率が高い」とみなす閾値（結果ドキュメントと同じ50%）。
BLOCK_DROPOUT_RATIO_THRESHOLD = 0.5
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "output" / "common_evaluation"
# 既定値は両分析スクリプトの引数の既定値から読む。
_SATELLITE_ONLY_DEFAULTS = satellite_only.parse_arguments([])
_LIMITED_DEFAULTS = limited.parse_arguments([])


def build_configuration_names() -> list[str]:
    """共通集合を構成する4構成の名前を、Satellite Only・Limited の順に返す。

    Returns:
        構成名のリスト（例: `["satellite_only", "limited_worldpop2020", ...]`）。
    """
    return [
        SATELLITE_ONLY_CONFIGURATION,
        *(f"limited_{source}" for source in LIMITED_POPULATION_SOURCES),
    ]


def resolve_default_output_dir(dataset_path: Path) -> Path:
    """データセット名に含まれる観測日時から、既定の出力先を求める。

    Args:
        dataset_path: Satellite Only のデータセットパス。
    Returns:
        `data/output/common_evaluation/{日付}_{時刻}`。日時が読めない場合は
        データセット名をそのまま使う。
    """
    stem = dataset_path.stem
    label = build_observation_label(stem)
    if label == stem:
        return DEFAULT_OUTPUT_ROOT / stem
    return DEFAULT_OUTPUT_ROOT / label.replace("-", "").replace(":", "").replace(" ", "_")


def resolve_cells_path(output_dir: Path, random_state: int) -> Path:
    """評価セル CSV の保存先を求める。

    比較・反復のスクリプトも同じ規則で既定の入力パスを求めるため、関数にしておく。

    Args:
        output_dir: 出力先ディレクトリ。
        random_state: 標本抽出の乱数シード。
    Returns:
        `{output_dir}/evaluation_cells_seed{random_state}.csv`。
    """
    return output_dir / f"evaluation_cells_seed{random_state}.csv"


def resolve_default_cells_path() -> Path:
    """既定の引数で生成したときの評価セル CSV のパスを求める。

    Returns:
        `parse_arguments([])` の出力先・乱数シードによる `resolve_cells_path` の値。
    """
    defaults = parse_arguments([])
    return resolve_cells_path(defaults.output_dir, defaults.random_state)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        解析結果。`output_dir` は未指定なら `resolve_default_output_dir` で補う。
    """
    parser = argparse.ArgumentParser(
        description="全シナリオ・全人口ソースで共通の評価セル集合と fold 割り当てを生成する"
    )
    parser.add_argument(
        "--satellite-only-dataset",
        type=Path,
        default=_SATELLITE_ONLY_DEFAULTS.dataset_path,
        help="Satellite Only のデータセット（既定は分析スクリプトの既定と同じ）",
    )
    parser.add_argument(
        "--limited-dataset",
        type=Path,
        default=_LIMITED_DEFAULTS.dataset_path,
        help="Limited のデータセット（既定は分析スクリプトの既定と同じ）",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="出力先ディレクトリ")
    parser.add_argument(
        "--lst-valid-ratio-threshold",
        type=float,
        default=_SATELLITE_ONLY_DEFAULTS.lst_valid_ratio_threshold,
        help="LST_VALID_RATIOの下限（両シナリオに同じ値を使う）",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=_SATELLITE_ONLY_DEFAULTS.sample_size,
        help="共通集合から抽出する標本サイズ",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=_SATELLITE_ONLY_DEFAULTS.random_state,
        help="標本抽出の乱数シード",
    )
    parser.add_argument(
        "--block-size-m",
        type=int,
        default=_SATELLITE_ONLY_DEFAULTS.block_size_m,
        help="Spatial CV のブロックサイズ（m）",
    )
    parser.add_argument(
        "--cv-splits",
        type=int,
        default=_SATELLITE_ONLY_DEFAULTS.cv_splits,
        help="Spatial CV の分割数",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=_SATELLITE_ONLY_DEFAULTS.scale,
        help="正準グリッドの解像度（m）",
    )
    args = parser.parse_args(argv)
    if args.output_dir is None:
        args.output_dir = resolve_default_output_dir(args.satellite_only_dataset)
    return args


def validate_same_observation(satellite_only_path: Path, limited_path: Path) -> None:
    """2つのデータセットが同じ観測日時のものであることを検査する。

    Args:
        satellite_only_path: Satellite Only のデータセットパス。
        limited_path: Limited のデータセットパス。
    Returns:
        None
    Raises:
        ValueError: ファイル名から読める観測日時が一致しない、または読めない場合。
    """
    labels = [build_observation_label(path.stem) for path in (satellite_only_path, limited_path)]
    stems = [satellite_only_path.stem, limited_path.stem]
    if labels[0] == stems[0] or labels[1] == stems[1] or labels[0] != labels[1]:
        raise ValueError(
            f"2つのデータセットの観測日時が一致しない、または読み取れません: {stems}。"
            "同じ観測から作ったデータセットを指定してください。"
        )


def build_configuration_populations(
    satellite_only_dataframe: pd.DataFrame,
    limited_dataframe: pd.DataFrame,
    lst_valid_ratio_threshold: float,
) -> dict[str, pd.DataFrame]:
    """4構成それぞれの有効母集団を、各分析スクリプトの関数で求める。

    戻り値の各データフレームは、共通集合の生成と脱落セルの集計に使う列だけを持つ。
    Satellite Only は建物被覆・水域被覆の列を持たないため、Limited のデータセット
    から `cell_id` で引いて付ける（`attach_limited_land_cover`）。

    Args:
        satellite_only_dataframe: `satellite_only.load_scenario_dataset` の戻り値。
        limited_dataframe: `limited.load_scenario_dataset`（人口3版を指定）の戻り値。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限。
    Returns:
        構成名をキー、有効母集団（`cell_id`・`CONSISTENCY_COLUMNS`・
        `DROPOUT_MEAN_COLUMNS` の列）を値とする辞書。並びは
        `build_configuration_names` の順。
    """
    value_columns = [CELL_ID_COLUMN, *dict.fromkeys([*CONSISTENCY_COLUMNS, *DROPOUT_MEAN_COLUMNS])]
    populations: dict[str, pd.DataFrame] = {}

    satellite_population = satellite_only.build_valid_population(
        satellite_only_dataframe,
        lst_valid_ratio_threshold=lst_valid_ratio_threshold,
        required_mask_columns=satellite_only.resolve_required_mask_columns(ANALYSIS_AREA_ROI),
    )
    populations[SATELLITE_ONLY_CONFIGURATION] = attach_limited_land_cover(
        satellite_population[[CELL_ID_COLUMN, *CONSISTENCY_COLUMNS]], limited_dataframe
    )[value_columns]

    filter_columns = limited.resolve_filter_columns()
    for source in LIMITED_POPULATION_SOURCES:
        print(f"Limited（{source}）の有効母集団を求めます。")
        result = limited.build_valid_population(
            limited_dataframe,
            filter_columns=filter_columns,
            lst_valid_ratio_threshold=lst_valid_ratio_threshold,
            required_mask_columns=limited.resolve_required_mask_columns([source]),
        )
        # 補完後の全行（filled）は使わないため、母集団の必要な列だけを残す。
        populations[f"limited_{source}"] = result.population[value_columns].reset_index(drop=True)
    return populations


def attach_limited_land_cover(
    population: pd.DataFrame, limited_dataframe: pd.DataFrame
) -> pd.DataFrame:
    """Satellite Only の母集団へ、Limited のデータセットの建物被覆・水域被覆を付ける。

    Args:
        population: `cell_id` を持つデータフレーム。
        limited_dataframe: Limited のデータセット（`cell_id`・`BUILD_COV`・
            `LULC_WATER_COV` を持つ）。
    Returns:
        `population` の行順のまま、2列を左結合したデータフレーム。Limited 側に
        無いセルは欠測（NaN）になる。
    """
    land_cover_columns = [
        column for column in DROPOUT_MEAN_COLUMNS if column not in population.columns
    ]
    return population.merge(
        limited_dataframe[[CELL_ID_COLUMN, *land_cover_columns]],
        on=CELL_ID_COLUMN,
        how="left",
        validate="one_to_one",
    )


def intersect_cell_ids(populations: Mapping[str, pd.DataFrame]) -> np.ndarray:
    """全構成の有効母集団に共通する cell_id を、昇順で返す。

    Args:
        populations: `build_configuration_populations` の戻り値。
    Returns:
        共通する cell_id の昇順配列（int64）。
    Raises:
        ValueError: 構成が1つも無い場合。
    """
    if not populations:
        raise ValueError("共通集合を取る構成がありません。")
    common: np.ndarray | None = None
    for population in populations.values():
        cell_ids = population[CELL_ID_COLUMN].to_numpy(dtype=np.int64)
        common = cell_ids if common is None else np.intersect1d(common, cell_ids)
    return np.unique(common).astype(np.int64)


def compare_common_values(
    left: pd.DataFrame,
    right: pd.DataFrame,
    common_cell_ids: np.ndarray,
    columns: Sequence[str] = CONSISTENCY_COLUMNS,
) -> dict[str, Any]:
    """共通セル上で、2つの母集団の値が一致するかを列ごとに数える。

    許容誤差は浮動小数の丸めのみとし、`numpy.isclose` の既定
    （rtol=1e-05, atol=1e-08）を使う。

    Args:
        left: 一方の母集団（例: Satellite Only）。
        right: もう一方の母集団（例: Limited）。
        common_cell_ids: 比べるセルの cell_id。
        columns: 比べる列。
    Returns:
        比べた行数・列ごとの不一致件数・列ごとの最大絶対差を持つ辞書。
    """
    left_values = left.set_index(CELL_ID_COLUMN).loc[common_cell_ids, list(columns)]
    right_values = right.set_index(CELL_ID_COLUMN).loc[common_cell_ids, list(columns)]
    mismatch_counts: dict[str, int] = {}
    max_abs_difference: dict[str, float | None] = {}
    for column in columns:
        a = left_values[column].to_numpy(dtype=float)
        b = right_values[column].to_numpy(dtype=float)
        mismatch_counts[column] = int(np.sum(~np.isclose(a, b)))
        max_abs_difference[column] = float(np.max(np.abs(a - b))) if len(a) else None
    return {
        "compared_rows": int(len(common_cell_ids)),
        "columns": list(columns),
        "mismatch_counts": mismatch_counts,
        "max_abs_difference": max_abs_difference,
        "tolerance": "numpy.isclose の既定（rtol=1e-05, atol=1e-08）",
    }


def require_consistent_values(consistency: Mapping[str, Any]) -> None:
    """`compare_common_values` の結果に不一致が1件でもあれば停止する。

    Args:
        consistency: `compare_common_values` の戻り値。
    Returns:
        None
    Raises:
        ValueError: いずれかの列に不一致がある場合。
    """
    mismatched = {
        column: count for column, count in consistency["mismatch_counts"].items() if count > 0
    }
    if mismatched:
        raise ValueError(
            f"共通セル上で2つのデータセットの値が一致しません（不一致件数: {mismatched}、"
            f"最大絶対差: {consistency['max_abs_difference']}）。同じ観測・同じ衛星指標から"
            "作ったデータセットか確認してください。"
        )


def draw_evaluation_cells(
    common_cell_ids: np.ndarray,
    sample_size: int,
    random_state: int,
    block_size_m: int,
    scale: int,
    cv_splits: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """共通集合から標本を抽出し、空間ブロックと fold を割り当てる。

    分析スクリプトと同じ順序（抽出 → 抽出後の標本へのブロック割り当て → GroupKFold）
    で行う。ブロック割り当てを抽出より先にすると各ブロックのセル数が不均等に減り、
    fold のサイズ均衡が崩れるため（分析スクリプトの `build_filtered_sample` 参照）。

    Args:
        common_cell_ids: 共通集合の cell_id（昇順）。
        sample_size: 標本サイズ（0で全件）。
        random_state: 乱数シード。
        block_size_m: ブロックの一辺の長さ（m）。
        scale: 正準グリッドの解像度（m/セル）。
        cv_splits: 分割数。
    Returns:
        評価セル（`build_evaluation_cells` の戻り値）と、標本の概要
        （行数・非空ブロック数・fold ごとの行数）の辞書のタプル。
    """
    common = pd.DataFrame({CELL_ID_COLUMN: np.sort(common_cell_ids)})
    sampled = sample_dataset(common, sample_size=sample_size, random_state=random_state)
    cell_ids = sampled[CELL_ID_COLUMN].to_numpy(dtype=np.int64)
    block_ids, block_info = assign_canonical_blocks(cell_ids, block_size_m, scale)
    folds = split_by_spatial_blocks(block_ids, n_splits=cv_splits)
    cells = build_evaluation_cells(cell_ids, block_ids, build_fold_labels(folds, len(cell_ids)))
    fold_sizes = cells[FOLD_COLUMN].value_counts().sort_index()
    summary = {
        "row_count": int(len(cells)),
        "n_blocks": int(block_info["n_blocks"]),
        "fold_sizes": {str(int(fold)): int(size) for fold, size in fold_sizes.items()},
    }
    return cells, summary


def classify_water_cover(values: pd.Series) -> dict[str, int]:
    """水域被覆を `WATER_COVER_CLASSES` の階級に分けて件数を数える。

    Args:
        values: 水域被覆（0〜1。欠測を含みうる）。
    Returns:
        階級名をキー、件数を値とする辞書（欠測は `missing`）。
    """
    counts: dict[str, int] = {}
    for name, lower, upper in WATER_COVER_CLASSES:
        if upper == lower:
            mask = values == lower
        elif lower == 0.0:
            mask = (values > lower) & (values < upper)
        else:
            mask = (values >= lower) & (values < upper)
        counts[name] = int(mask.sum())
    counts["missing"] = int(values.isna().sum())
    return counts


def summarize_cell_values(values: pd.DataFrame) -> dict[str, Any]:
    """セル群の件数・LST（°C）の平均と標準偏差・各列の平均・水域被覆の階級別件数を求める。

    Args:
        values: `LST` と `DROPOUT_MEAN_COLUMNS` を持つデータフレーム。
    Returns:
        集計結果の辞書。値が無い列の平均は `None` とし、欠測件数を併記する。
    """

    def _mean(series: pd.Series) -> float | None:
        """欠測を除いた平均（値が1つも無ければ None）。"""
        return None if series.dropna().empty else float(series.mean())

    lst = values["LST"]
    return {
        "count": int(len(values)),
        "lst_mean_c": _mean(lst),
        "lst_sd_c": None if lst.dropna().size < 2 else float(lst.std(ddof=1)),
        "means": {column: _mean(values[column]) for column in DROPOUT_MEAN_COLUMNS},
        "missing_counts": {
            column: int(values[column].isna().sum()) for column in DROPOUT_MEAN_COLUMNS
        },
        "water_cover_classes": classify_water_cover(values[WATER_COVER_COLUMN]),
    }


def summarize_block_concentration(
    population_cell_ids: np.ndarray,
    dropped_mask: np.ndarray,
    block_size_m: int,
    scale: int,
) -> dict[str, int]:
    """脱落セルがブロック単位でどれだけ集中しているかを数える。

    脱落率はブロックごとに「その構成の有効母集団のうち脱落したセルの割合」とする。

    Args:
        population_cell_ids: 構成の有効母集団の cell_id。
        dropped_mask: `population_cell_ids` と位置対応の、脱落したかどうか。
        block_size_m: ブロックの一辺の長さ（m）。
        scale: 正準グリッドの解像度（m/セル）。
    Returns:
        非空ブロック数・脱落セルを含むブロック数・脱落率が
        `BLOCK_DROPOUT_RATIO_THRESHOLD` を超えるブロック数の辞書。
    """
    block_ids, block_info = assign_canonical_blocks(population_cell_ids, block_size_m, scale)
    dropped_ratio = pd.Series(dropped_mask.astype(float)).groupby(block_ids).mean()
    return {
        "n_blocks": int(block_info["n_blocks"]),
        "blocks_with_dropout": int((dropped_ratio > 0).sum()),
        "blocks_over_50pct": int((dropped_ratio > BLOCK_DROPOUT_RATIO_THRESHOLD).sum()),
    }


def summarize_dropout(
    population: pd.DataFrame,
    common_cell_ids: np.ndarray,
    block_size_m: int,
    scale: int,
) -> dict[str, Any]:
    """構成の有効母集団のうち、共通集合から外れたセルの性格を集計する。

    Args:
        population: 構成の有効母集団（`build_configuration_populations` の値）。
        common_cell_ids: 共通集合の cell_id。
        block_size_m: ブロックの一辺の長さ（m）。
        scale: 正準グリッドの解像度（m/セル）。
    Returns:
        母数・脱落件数・脱落率・脱落セルの値の集計・ブロック単位の集中度の辞書。
    """
    cell_ids = population[CELL_ID_COLUMN].to_numpy(dtype=np.int64)
    dropped_mask = ~np.isin(cell_ids, common_cell_ids)
    dropped_count = int(dropped_mask.sum())
    return {
        "population_size": int(len(population)),
        "dropped_count": dropped_count,
        "dropped_ratio": dropped_count / len(population) if len(population) else None,
        "dropped": summarize_cell_values(population.loc[dropped_mask]),
        "block_concentration": summarize_block_concentration(
            cell_ids, dropped_mask, block_size_m, scale
        ),
    }


def build_metadata(
    args: argparse.Namespace,
    populations: Mapping[str, pd.DataFrame],
    common_cell_ids: np.ndarray,
    consistency: Mapping[str, Any],
    sample_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """メタデータ JSON の内容（来歴を除く）を組み立てる。

    Args:
        args: `parse_arguments` の戻り値。
        populations: `build_configuration_populations` の戻り値。
        common_cell_ids: 共通集合の cell_id。
        consistency: `compare_common_values` の戻り値。
        sample_summary: `draw_evaluation_cells` の戻り値の2つ目。
    Returns:
        メタデータの辞書（`save_evaluation_set` が評価セルの情報を加える）。
    """
    satellite_population = populations[SATELLITE_ONLY_CONFIGURATION]
    common_values = satellite_population.loc[
        satellite_population[CELL_ID_COLUMN].isin(common_cell_ids)
    ]
    return {
        "description": (
            "Satellite Only と Limited（人口3版）の有効母集団の積を評価用の母集団とし、"
            "そこから抽出した標本と fold 割り当て。"
        ),
        "observation": build_observation_label(args.satellite_only_dataset.stem),
        "analysis_area": ANALYSIS_AREA_ROI,
        "datasets": {
            "satellite_only": to_project_relative_string(args.satellite_only_dataset),
            "limited": to_project_relative_string(args.limited_dataset),
        },
        "lst_valid_ratio_threshold": args.lst_valid_ratio_threshold,
        "configurations": {
            SATELLITE_ONLY_CONFIGURATION: {
                "required_mask_columns": list(
                    satellite_only.resolve_required_mask_columns(ANALYSIS_AREA_ROI)
                ),
                "non_null_columns": [*satellite_only.FEATURE_COLUMNS, satellite_only.TARGET_COLUMN],
                "population_size": int(len(satellite_population)),
            },
            **{
                f"limited_{source}": {
                    "required_mask_columns": list(limited.resolve_required_mask_columns([source])),
                    "non_null_columns": [*limited.resolve_filter_columns(), limited.TARGET_COLUMN],
                    "building_height_zero_fill": True,
                    "population_size": int(len(populations[f"limited_{source}"])),
                }
                for source in LIMITED_POPULATION_SOURCES
            },
        },
        "common_size": int(len(common_cell_ids)),
        "value_consistency": dict(consistency),
        "sample_size": args.sample_size,
        "random_state": args.random_state,
        "block_size_m": args.block_size_m,
        "cv_splits": args.cv_splits,
        "scale_m": args.scale,
        "sample": dict(sample_summary),
        "dropout": {
            "common": summarize_cell_values(common_values),
            **{
                name: summarize_dropout(population, common_cell_ids, args.block_size_m, args.scale)
                for name, population in populations.items()
            },
        },
        "notes": [
            "dropout の各構成は、その構成の有効母集団に含まれるが共通集合から外れたセルの集計。"
            "common は共通集合自体（Satellite Only のデータセットの LST・NDVI）の集計。",
            "Satellite Only の BUILD_COV・LULC_WATER_COV は Limited のデータセットから cell_id で"
            "引いた値で、引けないセルは missing_counts に数える。",
            "block_concentration の脱落率は、構成の有効母集団に対するブロック単位の割合。",
            "LST の単位は °C。",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    """共通評価セル集合を生成し、評価セル CSV とメタデータ JSON を保存する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        None
    """
    args = parse_arguments(argv)
    args.satellite_only_dataset = args.satellite_only_dataset.resolve()
    args.limited_dataset = args.limited_dataset.resolve()
    args.output_dir = args.output_dir.resolve()
    validate_same_observation(args.satellite_only_dataset, args.limited_dataset)
    validate_scale_matches_dataset(args.satellite_only_dataset, args.scale)
    validate_scale_matches_dataset(args.limited_dataset, args.scale)

    print(f"Satellite Only のデータセットを読み込みます: {args.satellite_only_dataset}")
    satellite_dataframe = satellite_only.load_scenario_dataset(
        args.satellite_only_dataset, ANALYSIS_AREA_ROI
    )
    print(f"Limited のデータセットを読み込みます: {args.limited_dataset}")
    limited_dataframe = limited.load_scenario_dataset(
        args.limited_dataset, list(LIMITED_POPULATION_SOURCES), ANALYSIS_AREA_ROI
    )

    populations = build_configuration_populations(
        satellite_dataframe, limited_dataframe, args.lst_valid_ratio_threshold
    )
    del satellite_dataframe, limited_dataframe
    for name, population in populations.items():
        print(f"  {name}: 有効母集団 {len(population):,} セル")

    common_cell_ids = intersect_cell_ids(populations)
    print(f"共通集合: {len(common_cell_ids):,} セル")
    if len(common_cell_ids) == 0:
        raise ValueError("共通集合が空です。各構成の有効条件とデータセットを確認してください。")

    consistency = compare_common_values(
        populations[SATELLITE_ONLY_CONFIGURATION],
        populations[f"limited_{LIMITED_POPULATION_SOURCES[0]}"],
        common_cell_ids,
    )
    print(f"共通セル上の値の不一致件数: {consistency['mismatch_counts']}")
    require_consistent_values(consistency)

    cells, sample_summary = draw_evaluation_cells(
        common_cell_ids,
        sample_size=args.sample_size,
        random_state=args.random_state,
        block_size_m=args.block_size_m,
        scale=args.scale,
        cv_splits=args.cv_splits,
    )
    print(f"標本: {sample_summary}")

    metadata = build_metadata(args, populations, common_cell_ids, consistency, sample_summary)
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    metadata["provenance"] = build_provenance(
        "src.analysis.build_common_evaluation_set",
        input_paths=[args.satellite_only_dataset, args.limited_dataset],
    )
    cells_path = resolve_cells_path(args.output_dir, args.random_state)
    saved = save_evaluation_set(cells, cells_path, metadata)
    print(
        json.dumps(
            {key: value for key, value in saved.items() if key != "provenance"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"評価セルを保存しました: {cells_path}")


if __name__ == "__main__":
    main()
