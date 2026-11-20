"""Limited の水指数の構成どうしの性能差を、保存済みの fold 別指標から求める。

差の向きは「比べる構成 − 採用構成」（例: `ndwi` − `none`）である。

分光指数を Satellite Only と揃えた感度分析（`repeat_common_evaluation --water-index`・
`compare_common_evaluation --limited-results`）では、各構成と Satellite Only との差は
結果ファイルに保存されるが、**Limited の構成どうしの差**は保存されない。本スクリプトは
モデルを回さず、両構成の保存済みの fold 別指標を読み、その差と区間を求めて保存する。

- **反復**: 2つの反復（採用構成と比較する水指数の構成）の `_folds.csv` から Limited 側の
  fold 別指標を取り出し、シードごと・fold ごとに「比較する構成 − 採用構成」の差を求める。
  区間は反復の結果と同じ反復 k-fold の補正 t 区間（J = 分割数 × シード数）である
- **単発**: 2つの単発の比較の結果 JSON に記録された Limited の全工程ランの fold 別指標
  から、同じ差と区間（J = 分割数）を求める

差と区間の計算は `src.common.cv_paired_comparison`、シードごとの差の分布は
`repeat_common_evaluation.summarize_seed_differences` をそのまま使い、書き直さない。

比べる前に、2つの反復が同じ評価セル・シード・分割数・標本数・木の本数で、水指数以外の
Limited の構成が同じであることを確かめ、違えば止める（単発は
`compare_common_evaluation.validate_same_evaluation` で同じ評価セル・乱数シード・木の本数で
あることを、`validate_full_run_pair` で水指数以外の構成が同じであることを確かめる）。
あわせて、結果文書が述べている一致（2つの反復の Satellite Only 側の fold 別指標の一致、
反復の主シードと全工程ランの fold 別指標の一致）を検査して記録する。

入力・出力のパスは評価セル CSV と水指数の構成から名前の規則で求める（評価セルと同じ
ディレクトリ）。出力名は `water_index_comparison_{CSV の stem}_wi_{構成}_*` とする。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.analysis import analysis_rq3_limited as limited
from src.analysis.build_common_evaluation_set import resolve_default_cells_path
from src.analysis.compare_common_evaluation import (
    resolve_recorded_path,
    validate_same_evaluation,
)
from src.analysis.repeat_common_evaluation import (
    SEED_COLUMN,
    resolve_output_suffix,
    summarize_seed_differences,
)
from src.common.cv_paired_comparison import (
    FOLD_COLUMN,
    FOLD_METRIC_COLUMNS,
    TEST_SIZE_COLUMN,
    TRAIN_SIZE_COLUMN,
    compute_fold_differences,
    summarize_metric_differences,
)
from src.common.paths import to_project_relative_string
from src.common.summary import build_provenance, save_summary

SCRIPT_MODULE = "src.analysis.compare_water_index_variants"
# 差の基準側の構成（採用構成）。出力名に接尾辞が付かない構成と同じ値に固定する
# （`repeat_common_evaluation.UNSUFFIXED_WATER_INDEX_MODE` と同じ考え方）。
REFERENCE_WATER_INDEX_MODE = limited.WATER_INDEX_MODE_NONE
VARIANT_WATER_INDEX_MODES = tuple(
    mode for mode in limited.WATER_INDEX_MODES if mode != REFERENCE_WATER_INDEX_MODE
)
DEFAULT_VARIANT_WATER_INDEX_MODE = limited.WATER_INDEX_MODE_NDWI
SATELLITE_ONLY_SCENARIO = "satellite_only"
LIMITED_SCENARIO = "limited"
SCENARIO_COLUMN = "scenario"
# 反復の2つの結果で一致を求める項目（水指数以外の条件）。
REPEATED_SHARED_KEYS = ("evaluation_cells", "analysis_area", "seeds", "cv_splits", "sample_size")
REPEATED_RUN_KEYS = ("rf_trees",)
# Limited の構成のうち、水指数以外で一致を求める項目。
LIMITED_SHARED_CONFIGURATION_KEYS = ("variable_set", "building_height_mode", "population_sources")
# 監視するコード。結果に直接効く関数を呼んでいる2つのスクリプト。
WATCH_PATHS = (
    "src/analysis/repeat_common_evaluation.py",
    "src/analysis/compare_common_evaluation.py",
)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        解析結果。
    """
    parser = argparse.ArgumentParser(
        description="Limited の水指数の構成どうしの性能差を、保存済みの fold 別指標から求める"
    )
    parser.add_argument(
        "--evaluation-cells",
        type=Path,
        default=resolve_default_cells_path(),
        help="評価セル CSV（入出力のパスはこの CSV と同じディレクトリから名前の規則で求める）",
    )
    parser.add_argument(
        "--water-index",
        choices=VARIANT_WATER_INDEX_MODES,
        default=DEFAULT_VARIANT_WATER_INDEX_MODE,
        help=f"採用構成（{REFERENCE_WATER_INDEX_MODE}）と比べる水指数の構成",
    )
    parser.add_argument("--confidence", type=float, default=0.95, help="信頼係数")
    return parser.parse_args(argv)


def resolve_input_paths(cells_path: Path, water_index_mode: str) -> dict[str, Path]:
    """評価セル CSV と水指数の構成から、読み込む結果 JSON のパスを求める。

    反復は `repeat_common_evaluation`、単発の比較は分析手順書（5.3.3節）の出力名の規則
    （`scenario_comparison_{stem}{接尾辞}_results.json`）に従う。

    Args:
        cells_path: 評価セル CSV のパス。
        water_index_mode: 比べる水指数の構成（`VARIANT_WATER_INDEX_MODES` のいずれか）。
    Returns:
        `repeated_reference`・`repeated_variant`・`single_reference`・`single_variant` を
        キーとするパスの辞書。
    Raises:
        ValueError: `water_index_mode` が採用構成または対応外の場合。
    """
    if water_index_mode not in VARIANT_WATER_INDEX_MODES:
        raise ValueError(
            f"採用構成（{REFERENCE_WATER_INDEX_MODE}）以外の水指数の構成を指定してください: "
            f"{water_index_mode}"
        )
    stem = cells_path.stem
    suffixes = {
        "reference": resolve_output_suffix(REFERENCE_WATER_INDEX_MODE),
        "variant": resolve_output_suffix(water_index_mode),
    }
    paths: dict[str, Path] = {}
    for role, suffix in suffixes.items():
        paths[f"repeated_{role}"] = cells_path.with_name(
            f"repeated_comparison_{stem}{suffix}_results.json"
        )
        paths[f"single_{role}"] = cells_path.with_name(
            f"scenario_comparison_{stem}{suffix}_results.json"
        )
    return paths


def resolve_output_paths(cells_path: Path, water_index_mode: str) -> dict[str, Path]:
    """出力（結果 JSON と fold ごとの差の CSV）のパスを求める。

    Args:
        cells_path: 評価セル CSV のパス。
        water_index_mode: 比べる水指数の構成。
    Returns:
        `results`・`repeated_folds`・`single_folds` をキーとするパスの辞書。
    """
    stem = f"water_index_comparison_{cells_path.stem}{resolve_output_suffix(water_index_mode)}"
    return {
        "results": cells_path.with_name(f"{stem}_results.json"),
        "repeated_folds": cells_path.with_name(f"{stem}_repeated_folds.csv"),
        "single_folds": cells_path.with_name(f"{stem}_single_folds.csv"),
    }


def load_json(path: Path) -> dict[str, Any]:
    """結果 JSON を読む。

    Args:
        path: JSON のパス。
    Returns:
        読み込んだ辞書。
    Raises:
        FileNotFoundError: ファイルが無い場合。
    """
    if not path.is_file():
        raise FileNotFoundError(f"結果ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_repeated_pair(
    reference: Mapping[str, Any], variant: Mapping[str, Any], water_index_mode: str
) -> None:
    """2つの反復の結果が、水指数の構成だけが違う同じ条件の反復であることを確かめる。

    Args:
        reference: 採用構成の反復の結果 JSON。
        variant: 比べる構成の反復の結果 JSON。
        water_index_mode: 比べる水指数の構成。
    Returns:
        None
    Raises:
        ValueError: 評価セル・範囲・シード・分割数・標本数・木の本数・水指数以外の
            Limited の構成のいずれかが違う場合、または水指数の構成が想定と違う場合。
    """
    mismatched: dict[str, tuple[Any, Any]] = {}
    for key in (*REPEATED_SHARED_KEYS, *REPEATED_RUN_KEYS):
        if reference.get(key) != variant.get(key):
            mismatched[key] = (reference.get(key), variant.get(key))
    mismatched.update(
        find_configuration_mismatches(
            reference.get("limited_configuration", {}),
            variant.get("limited_configuration", {}),
            water_index_mode,
            prefix="limited_configuration.",
        )
    )
    if mismatched:
        raise ValueError(f"2つの反復が水指数の構成以外でも違います: {mismatched}")


def validate_full_run_pair(
    reference: Mapping[str, Any], variant: Mapping[str, Any], water_index_mode: str
) -> None:
    """単発の比較が指す Limited の全工程ラン2本が、水指数だけが違う構成であることを確かめる。

    同じ評価セル・乱数シード・木の本数であることの検査
    （`compare_common_evaluation.validate_same_evaluation`）とは別に、構成を検査する。

    Args:
        reference: 採用構成の全工程ランの結果 JSON。
        variant: 比べる構成の全工程ランの結果 JSON。
        water_index_mode: 比べる水指数の構成。
    Returns:
        None
    Raises:
        ValueError: 水指数の構成が想定と違う場合、または水指数以外の Limited の構成が
            違う場合。
    """
    mismatched = find_configuration_mismatches(reference, variant, water_index_mode)
    if mismatched:
        raise ValueError(
            f"単発の比較の Limited の全工程ランが水指数の構成以外でも違います: {mismatched}"
        )


def find_configuration_mismatches(
    reference_configuration: Mapping[str, Any],
    variant_configuration: Mapping[str, Any],
    water_index_mode: str,
    prefix: str = "",
) -> dict[str, tuple[Any, Any]]:
    """Limited の構成2つを比べ、想定と違う項目を返す。

    水指数は「採用構成・指定の構成」であること、それ以外の項目
    （`LIMITED_SHARED_CONFIGURATION_KEYS`）は一致することを求める。

    Args:
        reference_configuration: 採用構成の側の構成（`water_index_mode` 等のキーを持つ）。
        variant_configuration: 比べる構成の側の構成。
        water_index_mode: 比べる水指数の構成。
        prefix: 戻り値のキーに付ける接頭辞（どの JSON の項目かを示すため）。
    Returns:
        項目名 → （採用構成の側の値, 比べる構成の側の値）の辞書（違いが無ければ空）。
    """
    mismatched: dict[str, tuple[Any, Any]] = {}
    for key in LIMITED_SHARED_CONFIGURATION_KEYS:
        if reference_configuration.get(key) != variant_configuration.get(key):
            mismatched[f"{prefix}{key}"] = (
                reference_configuration.get(key),
                variant_configuration.get(key),
            )
    actual_modes = (
        reference_configuration.get("water_index_mode"),
        variant_configuration.get("water_index_mode"),
    )
    if actual_modes != (REFERENCE_WATER_INDEX_MODE, water_index_mode):
        mismatched[f"{prefix}water_index_mode"] = actual_modes
    return mismatched


def select_scenario_folds(fold_table: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """反復の fold 別指標の表から、1つのシナリオの行を取り出す。

    Args:
        fold_table: 反復の `_folds.csv`（`scenario`・`seed` 列を持つ）。
        scenario: シナリオ名。
    Returns:
        `scenario` 列を除き、シード・fold 番号順に並べた表。
    Raises:
        ValueError: そのシナリオの行が無い場合。
    """
    selected = fold_table[fold_table[SCENARIO_COLUMN] == scenario]
    if selected.empty:
        raise ValueError(f"fold 別指標の表に {scenario} の行がありません。")
    return (
        selected.drop(columns=SCENARIO_COLUMN)
        .sort_values([SEED_COLUMN, FOLD_COLUMN])
        .reset_index(drop=True)
    )


def compute_seedwise_differences(
    reference_folds: pd.DataFrame, variant_folds: pd.DataFrame
) -> pd.DataFrame:
    """シードごとに「比べる構成 − 採用構成」の fold ごとの差を求め、縦に連結する。

    Args:
        reference_folds: 採用構成の fold 別指標（`seed` 列を持つ）。
        variant_folds: 比べる構成の fold 別指標（`seed` 列を持つ）。
    Returns:
        `compute_fold_differences` の戻り値に `seed` 列を加えて連結した表。
    Raises:
        ValueError: 2つの表のシードの集合が違う場合（fold の不一致は
            `compute_fold_differences` が止める）。
    """
    reference_seeds = sorted(reference_folds[SEED_COLUMN].unique())
    variant_seeds = sorted(variant_folds[SEED_COLUMN].unique())
    if reference_seeds != variant_seeds:
        raise ValueError(f"2つの表のシードが違います: {reference_seeds} と {variant_seeds}")
    frames = [
        compute_fold_differences(
            reference_folds[reference_folds[SEED_COLUMN] == seed],
            variant_folds[variant_folds[SEED_COLUMN] == seed],
        ).assign(**{SEED_COLUMN: seed})
        for seed in reference_seeds
    ]
    return pd.concat(frames, ignore_index=True)


def is_metric_higher_better(metric: str) -> bool:
    """評価指標が大きいほど良い指標か（R²）を返す。RMSE・MAE は小さいほど良い。

    Args:
        metric: `FOLD_METRIC_COLUMNS` の列名。
    Returns:
        大きいほど良いなら True。
    """
    return metric.endswith("_r2")


def count_variant_better(
    differences: pd.DataFrame, metric_columns: Sequence[str] = FOLD_METRIC_COLUMNS
) -> dict[str, dict[str, int]]:
    """差（比べる構成 − 採用構成）の行のうち、比べる構成のほうが良い行の数を数える。

    R² は差が正、RMSE・MAE は差が負の行を「比べる構成が良い」とする。差がちょうど0の
    行はどちらにも数えない。

    Args:
        differences: 差の表（行が fold、またはシードごとの平均）。
        metric_columns: 数える指標の列。
    Returns:
        指標名 → `n_variant_better`・`n_total` の辞書。
    """
    counts: dict[str, dict[str, int]] = {}
    for column in metric_columns:
        values = differences[column]
        better = values > 0 if is_metric_higher_better(column) else values < 0
        counts[column] = {"n_variant_better": int(better.sum()), "n_total": int(values.size)}
    return counts


def frames_identical(left: pd.DataFrame, right: pd.DataFrame, columns: Sequence[str]) -> bool:
    """2つの fold 別指標の表が、指定した列で完全に一致するかを返す。

    Args:
        left: 1つ目の表。
        right: 2つ目の表。
        columns: 比べる列（並べ替えの後、位置どうしで比べる）。
    Returns:
        行数と各列の値がすべて一致すれば True。
    """
    sort_columns = [column for column in (SEED_COLUMN, FOLD_COLUMN) if column in columns]
    left_sorted = left.sort_values(sort_columns)[list(columns)].reset_index(drop=True)
    right_sorted = right.sort_values(sort_columns)[list(columns)].reset_index(drop=True)
    return bool(left_sorted.equals(right_sorted))


def compute_relative_sizes(
    variant_seed_differences: Mapping[str, Mapping[str, float]],
    main_seed_differences: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float | None]]:
    """構成どうしの差の大きさを、主結果の差とシード間の sd に対する比で表す。

    Args:
        variant_seed_differences: 構成どうしの差の `summarize_seed_differences` の戻り値。
        main_seed_differences: 採用構成の反復の結果 JSON の `seed_differences`
            （Limited − Satellite Only の主結果の差）。
    Returns:
        指標名 → `ratio_to_main_difference`（構成どうしの差の平均 ÷ 主結果の差の平均）・
        `ratio_to_seed_sd`（構成どうしの差の平均の絶対値 ÷ そのシード間の sd）の辞書。
        分母が0なら `None` にする。
    """
    sizes: dict[str, dict[str, float | None]] = {}
    for metric, summary in variant_seed_differences.items():
        main_mean = main_seed_differences[metric]["mean"]
        sd = summary["sd"]
        sizes[metric] = {
            "ratio_to_main_difference": summary["mean"] / main_mean if main_mean else None,
            "ratio_to_seed_sd": abs(summary["mean"]) / sd if sd else None,
        }
    return sizes


def summarize_repeated(
    reference: Mapping[str, Any],
    variant: Mapping[str, Any],
    reference_fold_table: pd.DataFrame,
    variant_fold_table: pd.DataFrame,
    confidence: float,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, bool]]:
    """2つの反復の fold 別指標から、構成どうしの差の要約と一致の検査結果を求める。

    Args:
        reference: 採用構成の反復の結果 JSON。
        variant: 比べる構成の反復の結果 JSON。
        reference_fold_table: 採用構成の反復の `_folds.csv`。
        variant_fold_table: 比べる構成の反復の `_folds.csv`。
        confidence: 信頼係数。
    Returns:
        （fold ごとの差の表, 要約の辞書, 一致の検査結果の辞書）のタプル。
    """
    differences = compute_seedwise_differences(
        select_scenario_folds(reference_fold_table, LIMITED_SCENARIO),
        select_scenario_folds(variant_fold_table, LIMITED_SCENARIO),
    )
    seed_differences = summarize_seed_differences(differences)
    per_seed = differences.groupby(SEED_COLUMN)[list(FOLD_METRIC_COLUMNS)].mean()
    summary = {
        "repeated_kfold": {
            **summarize_metric_differences(differences, confidence=confidence),
            "note": (
                "J = 分割数 × シード数 の fold ごとの差から求めた補正 t 区間。反復の結果と同じく、"
                "シードごとに標本自体を抽出し直しているため、区間には標本の違いも含まれる。"
            ),
        },
        "seed_differences": seed_differences,
        "variant_better": {
            "folds": count_variant_better(differences),
            "seeds": count_variant_better(per_seed),
        },
        "relative_size": compute_relative_sizes(seed_differences, reference["seed_differences"]),
    }
    key_and_metric_columns = [
        SEED_COLUMN,
        FOLD_COLUMN,
        TRAIN_SIZE_COLUMN,
        TEST_SIZE_COLUMN,
        *FOLD_METRIC_COLUMNS,
    ]
    checks = {
        "repeated_satellite_only_folds_identical": frames_identical(
            select_scenario_folds(reference_fold_table, SATELLITE_ONLY_SCENARIO),
            select_scenario_folds(variant_fold_table, SATELLITE_ONLY_SCENARIO),
            key_and_metric_columns,
        ),
    }
    return differences, summary, checks


def check_main_seed_matches_full_run(
    fold_table: pd.DataFrame, full_run_folds: pd.DataFrame, main_seed: int
) -> bool:
    """反復の主シードの Limited の fold 別指標が、全工程ランの fold 別指標と一致するかを返す。

    Args:
        fold_table: 反復の `_folds.csv`。
        full_run_folds: 同じ構成の全工程ランの fold 別指標。
        main_seed: 主シード（全工程ランの乱数シード）。
    Returns:
        fold 番号・行数・指標がすべて一致すれば True。
    """
    limited_folds = select_scenario_folds(fold_table, LIMITED_SCENARIO)
    main_seed_folds = limited_folds[limited_folds[SEED_COLUMN] == main_seed].drop(
        columns=SEED_COLUMN
    )
    columns = [FOLD_COLUMN, TRAIN_SIZE_COLUMN, TEST_SIZE_COLUMN, *FOLD_METRIC_COLUMNS]
    return frames_identical(main_seed_folds, full_run_folds, columns)


def main(argv: list[str] | None = None) -> None:
    """2つの構成の保存済みの fold 別指標から、構成どうしの差と区間を求めて保存する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        None
    """
    args = parse_arguments(argv)
    cells_path = args.evaluation_cells.resolve()
    input_paths = resolve_input_paths(cells_path, args.water_index)
    output_paths = resolve_output_paths(cells_path, args.water_index)
    results = {role: load_json(path) for role, path in input_paths.items()}

    # 反復: 条件の一致を確かめてから、Limited 側の fold 別指標どうしの差を求める。
    validate_repeated_pair(
        results["repeated_reference"], results["repeated_variant"], args.water_index
    )
    repeated_folds_paths = {
        role: resolve_recorded_path(results[f"repeated_{role}"]["outputs"]["folds_csv"])
        for role in ("reference", "variant")
    }
    repeated_fold_tables = {role: pd.read_csv(path) for role, path in repeated_folds_paths.items()}
    repeated_differences, repeated_summary, checks = summarize_repeated(
        results["repeated_reference"],
        results["repeated_variant"],
        repeated_fold_tables["reference"],
        repeated_fold_tables["variant"],
        args.confidence,
    )

    # 単発: 単発の比較に記録された Limited の全工程ランの fold 別指標どうしの差を求める。
    limited_result_paths = {
        role: resolve_recorded_path(results[f"single_{role}"]["inputs"]["limited_results"])
        for role in ("reference", "variant")
    }
    limited_results = {role: load_json(path) for role, path in limited_result_paths.items()}
    validate_same_evaluation(limited_results["reference"], limited_results["variant"])
    validate_full_run_pair(
        limited_results["reference"], limited_results["variant"], args.water_index
    )
    full_run_folds_paths = {
        role: resolve_recorded_path(result["spatial_cv"]["outputs"]["fold_metrics_csv"])
        for role, result in limited_results.items()
    }
    full_run_folds = {role: pd.read_csv(path) for role, path in full_run_folds_paths.items()}
    single_differences = compute_fold_differences(
        full_run_folds["reference"], full_run_folds["variant"]
    )

    main_seed = int(limited_results["reference"]["run_parameters"]["random_state"])
    checks.update(
        {
            "single_satellite_only_results_identical": (
                results["single_reference"]["inputs"]["satellite_only_results"]
                == results["single_variant"]["inputs"]["satellite_only_results"]
            ),
            "repeated_main_seed_matches_full_run": {
                role: check_main_seed_matches_full_run(
                    repeated_fold_tables[role], full_run_folds[role], main_seed
                )
                for role in ("reference", "variant")
            },
        }
    )

    for key in ("repeated_folds", "single_folds"):
        output_paths[key].parent.mkdir(parents=True, exist_ok=True)
    repeated_differences.to_csv(output_paths["repeated_folds"], index=False)
    single_differences.to_csv(output_paths["single_folds"], index=False)

    reference_repeated = results["repeated_reference"]
    comparison = {
        "description": (
            "Limited の水指数の構成どうしの性能差（同じ評価セル・同じ fold での対応のある差）。"
            "保存済みの fold 別指標から求め、モデルは回し直していない。"
        ),
        "difference_direction": (
            f"Limited({args.water_index}) − Limited({REFERENCE_WATER_INDEX_MODE})"
        ),
        "water_index": {"reference": REFERENCE_WATER_INDEX_MODE, "variant": args.water_index},
        "inputs": {
            **{role: to_project_relative_string(path) for role, path in input_paths.items()},
            **{
                f"single_{role}_limited_results": to_project_relative_string(path)
                for role, path in limited_result_paths.items()
            },
        },
        "evaluation_cells": reference_repeated["evaluation_cells"],
        "analysis_area": reference_repeated["analysis_area"],
        "seeds": reference_repeated["seeds"],
        "main_seed": main_seed,
        "cv_splits": reference_repeated["cv_splits"],
        "sample_size": reference_repeated["sample_size"],
        "rf_trees": reference_repeated["rf_trees"],
        "repeated": repeated_summary,
        "single": {
            "spatial_cv": summarize_metric_differences(
                single_differences, confidence=args.confidence
            ),
            "variant_better": {"folds": count_variant_better(single_differences)},
        },
        "consistency_checks": checks,
        "outputs": {
            "repeated_folds_csv": to_project_relative_string(output_paths["repeated_folds"]),
            "single_folds_csv": to_project_relative_string(output_paths["single_folds"]),
        },
        "notes": [
            "relative_size.ratio_to_main_difference は、構成どうしの差の平均を、採用構成の反復の"
            "主結果の差（Limited − Satellite Only のシードごとの差の平均）で割った値。",
            "relative_size.ratio_to_seed_sd は、構成どうしの差の平均の絶対値を、そのシード間の"
            " sd で割った値。",
            "variant_better は R² では差が正、RMSE・MAE では差が負の数で、差が0の行は数えない。",
        ],
    }
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    comparison["provenance"] = build_provenance(
        SCRIPT_MODULE,
        input_paths=[
            *input_paths.values(),
            *repeated_folds_paths.values(),
            *limited_result_paths.values(),
            *full_run_folds_paths.values(),
            cells_path,
        ],
        extra_watch_paths=WATCH_PATHS,
    )
    save_summary(comparison, output_paths["results"])
    printable = {key: value for key, value in comparison.items() if key != "provenance"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"構成どうしの比較結果を保存しました: {output_paths['results']}")


if __name__ == "__main__":
    main()
