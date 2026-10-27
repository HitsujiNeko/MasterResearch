"""共通評価セル集合から複数のシードで標本を抽出し直し、Spatial CV だけを反復して比べる。

共通集合（`build_common_evaluation_set` と同じ関数で求め直す）から、シードごとに
標本を抽出して fold を割り当て、Satellite Only と Limited の採用構成の Spatial CV
だけを回す（SHAP・ランダム分割・置換重要度は省く）。次の3つを出力する。

1. シナリオごとの R² のシード間の変動（fold 平均の sd・範囲）
2. シードごとの対応のある差（fold 平均どうしの差）の分布（平均・sd・2.5/97.5 パーセンタイル）
3. 反復 k-fold の補正 t 区間（Bouckaert & Frank 2004。J = k × シード数）

**区間の解釈の注意**: 反復ではシードごとに標本自体が入れ替わる（約340万セルから
10万件を抽出し直す）ため、区間には分割の違いだけでなく標本の違いも含まれる。
Bouckaert & Frank の想定（同じデータの分割し直し）とは異なる。

**シードは標本抽出と RF の `random_state` の両方に使う**（分析スクリプトの
`--random-state` が両方を変えるのと揃える）。特徴量の処理（投入列・主成分化・
分散0の列の除外）は Limited のスクリプトの関数をそのまま呼び、書き直さない。
Limited の構成（変数セット・建物高さ・水指数・人口ソース）と RF の本数は、
Limited のスクリプトの既定値（採用構成）を使う。

保存済みの評価セル（主シードの1本）と同じシードの標本は、内容ダイジェストが一致する
ことを確かめる（共通集合の求め直しと抽出が保存時と同じであることの検査）。
シードごとの途中結果を保存し、中断しても続きから再開できる（完了印のある
シードは、標本のダイジェストが一致すれば計算し直さない）。
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.analysis import analysis_rq3_limited as limited
from src.analysis import analysis_rq3_satellite_only as satellite_only
from src.analysis.build_common_evaluation_set import (
    build_configuration_populations,
    draw_evaluation_cells,
    intersect_cell_ids,
    resolve_default_cells_path,
)
from src.common.analysis_dataset import ANALYSIS_AREA_ROI
from src.common.analysis_runs import run_spatial_cv_models, validate_fold_test_sizes
from src.common.config import PROJECT_ROOT
from src.common.cv_paired_comparison import (
    FOLD_METRIC_COLUMNS,
    compute_fold_differences,
    summarize_metric_differences,
)
from src.common.evaluation_cells import (
    BLOCK_ID_COLUMN,
    FOLD_COLUMN,
    EvaluationSet,
    compute_evaluation_cells_digest,
    folds_from_labels,
    load_evaluation_set,
    select_evaluation_rows,
)
from src.common.paths import to_project_relative_string
from src.common.summary import build_provenance, save_summary

SCENARIOS = ("satellite_only", "limited")
SEED_COLUMN = "seed"
DEFAULT_FIRST_SEED = 42
DEFAULT_N_SEEDS = 20
# シード間の差の分布で示すパーセンタイル。
DIFFERENCE_PERCENTILES = (2.5, 97.5)
_LIMITED_DEFAULTS = limited.parse_arguments([])


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        解析結果。`output_dir` は未指定なら評価セルと同じディレクトリの
        `repeat_{CSV の stem}` にする。
    """
    parser = argparse.ArgumentParser(
        description="共通評価セル集合から複数シードで標本を抽出し直し、Spatial CV を反復する"
    )
    parser.add_argument(
        "--evaluation-cells",
        type=Path,
        default=resolve_default_cells_path(),
        help="主シードの評価セル CSV（共通集合の定義・設定はこのメタデータから読む）",
    )
    parser.add_argument("--first-seed", type=int, default=DEFAULT_FIRST_SEED)
    parser.add_argument("--n-seeds", type=int, default=DEFAULT_N_SEEDS)
    parser.add_argument(
        "--rf-trees",
        type=int,
        default=_LIMITED_DEFAULTS.rf_trees,
        help="RF の決定木本数（既定は分析スクリプトの既定値）",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="途中結果の保存先")
    args = parser.parse_args(argv)
    if args.n_seeds < 2:
        parser.error(
            f"--n-seeds は2以上にしてください（シード間の変動を求めるため）: {args.n_seeds}"
        )
    if args.output_dir is None:
        args.output_dir = args.evaluation_cells.with_name(f"repeat_{args.evaluation_cells.stem}")
    return args


def resolve_seeds(first_seed: int, n_seeds: int) -> list[int]:
    """反復に使うシードの一覧を求める。

    Args:
        first_seed: 最初のシード。
        n_seeds: シード数。
    Returns:
        `first_seed` から連番の `n_seeds` 個のシード。
    """
    return list(range(first_seed, first_seed + n_seeds))


def resolve_limited_feature_columns() -> list[str]:
    """Limited の採用構成（スクリプトの既定値）で投入する説明変数の列名を求める。

    Returns:
        `limited.resolve_feature_columns` の戻り値。
    """
    return limited.resolve_feature_columns(
        _LIMITED_DEFAULTS.variable_set,
        _LIMITED_DEFAULTS.population_source,
        _LIMITED_DEFAULTS.building_height,
        _LIMITED_DEFAULTS.water_index,
    )


def prepare_limited_sample(
    sampled: pd.DataFrame, feature_columns: Sequence[str]
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Limited の標本に、分析スクリプトと同じ特徴量の処理を施す。

    主成分化（採用構成が主成分を使う場合）と分散0の列の除外を、Limited の
    スクリプトの関数で行う（`main()` と同じ順序）。

    Args:
        sampled: 有効母集団から選んだ標本。
        feature_columns: 投入候補の列（`resolve_limited_feature_columns`）。
    Returns:
        （処理後の標本, 投入した列, 除外した列）のタプル。
    Raises:
        ValueError: 除外の結果、説明変数が2列未満になった場合。
    """
    if _LIMITED_DEFAULTS.building_height == limited.BUILDING_HEIGHT_MODE_PC1:
        sampled, _ = limited.add_building_height_pc1(sampled)
    if _LIMITED_DEFAULTS.water_index == limited.WATER_INDEX_MODE_PC1:
        sampled, _ = limited.add_vegetation_water_pc1(sampled)
    kept, dropped = limited.drop_constant_features(sampled, feature_columns)
    if len(kept) < 2:
        raise ValueError(f"分散0の列を除外した結果、説明変数が2列未満になりました: {kept}")
    return sampled, kept, dropped


def seed_paths(output_dir: Path, seed: int) -> dict[str, Path]:
    """シードごとの途中結果のパスを求める。

    完了印（`summary`）は `_results.json` で終わらせない（陳腐化チェックの走査対象は
    最終結果だけにするため）。

    Args:
        output_dir: 途中結果の保存先。
        seed: シード。
    Returns:
        `summary`・`satellite_only`・`limited` をキーとするパスの辞書。
    """
    return {
        "summary": output_dir / f"seed{seed}_summary.json",
        "satellite_only": output_dir / f"seed{seed}_satellite_only_folds.csv",
        "limited": output_dir / f"seed{seed}_limited_folds.csv",
    }


def load_completed_seed(output_dir: Path, seed: int, digest: str) -> dict[str, Any] | None:
    """完了済みのシードの途中結果を読む（標本のダイジェストが一致する場合のみ）。

    Args:
        output_dir: 途中結果の保存先。
        seed: シード。
        digest: 今回作り直した標本の内容ダイジェスト。
    Returns:
        完了済みなら途中結果（summary と2つの fold 別指標）、未完了・不一致なら `None`。
    """
    paths = seed_paths(output_dir, seed)
    if not all(path.is_file() for path in paths.values()):
        return None
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    if summary.get("digest") != digest:
        print(f"  seed {seed}: 途中結果の標本が作り直した標本と一致しないため、計算し直します。")
        return None
    return {
        "summary": summary,
        "satellite_only": pd.read_csv(paths["satellite_only"]),
        "limited": pd.read_csv(paths["limited"]),
    }


def run_seed(
    seed: int,
    cells: pd.DataFrame,
    populations: Mapping[str, pd.DataFrame],
    limited_feature_columns: Sequence[str],
    cv_splits: int,
    rf_trees: int,
) -> dict[str, Any]:
    """1つのシードについて、両シナリオの Spatial CV を同じ標本・同じ fold で回す。

    Args:
        seed: 標本抽出と RF の乱数シード。
        cells: このシードの評価セル（`draw_evaluation_cells` の戻り値）。
        populations: `satellite_only`・`limited` をキーとする有効母集団（全列）。
        limited_feature_columns: Limited の投入候補の列。
        cv_splits: 分割数。
        rf_trees: RF の決定木本数。
    Returns:
        `satellite_only`・`limited` の fold 別指標と、投入列・除外列の辞書。
    """
    folds = folds_from_labels(cells[FOLD_COLUMN].to_numpy(), cv_splits)
    validate_fold_test_sizes(folds)
    block_ids = cells[BLOCK_ID_COLUMN].to_numpy()

    satellite_sample = select_evaluation_rows(populations["satellite_only"], cells)
    _, satellite_folds = run_spatial_cv_models(
        satellite_sample,
        satellite_only.FEATURE_COLUMNS,
        satellite_only.TARGET_COLUMN,
        block_ids,
        cv_splits,
        seed,
        rf_trees,
        folds=folds,
    )
    limited_sample, kept, dropped = prepare_limited_sample(
        select_evaluation_rows(populations["limited"], cells), limited_feature_columns
    )
    _, limited_folds = run_spatial_cv_models(
        limited_sample,
        kept,
        limited.TARGET_COLUMN,
        block_ids,
        cv_splits,
        seed,
        rf_trees,
        folds=folds,
    )
    return {
        "satellite_only": satellite_folds,
        "limited": limited_folds,
        "limited_features": kept,
        "limited_dropped_constant_features": dropped,
    }


def summarize_seed_variation(fold_table: pd.DataFrame) -> dict[str, Any]:
    """シナリオごとに、fold 平均の評価指標のシード間の変動を求める。

    Args:
        fold_table: 全シード・両シナリオの fold 別指標（`seed`・`scenario` 列を持つ）。
    Returns:
        シナリオ名 → 指標名 → 平均・sd・最小・最大の辞書。
    """
    per_seed = fold_table.groupby(["scenario", SEED_COLUMN])[list(FOLD_METRIC_COLUMNS)].mean()
    variation: dict[str, Any] = {}
    for scenario in SCENARIOS:
        values = per_seed.loc[scenario]
        variation[scenario] = {
            column: {
                "mean": float(values[column].mean()),
                "sd": float(values[column].std(ddof=1)),
                "min": float(values[column].min()),
                "max": float(values[column].max()),
            }
            for column in FOLD_METRIC_COLUMNS
        }
    return variation


def summarize_seed_differences(differences: pd.DataFrame) -> dict[str, Any]:
    """シードごとの対応のある差（fold 平均どうしの差）の分布を求める。

    Args:
        differences: 全シードの fold ごとの差（`seed` 列と指標の列を持つ）。
    Returns:
        指標名 → 平均・sd・パーセンタイルの辞書。
    """
    per_seed = differences.groupby(SEED_COLUMN)[list(FOLD_METRIC_COLUMNS)].mean()
    summary: dict[str, Any] = {}
    for column in FOLD_METRIC_COLUMNS:
        values = per_seed[column].to_numpy()
        percentiles = np.percentile(values, DIFFERENCE_PERCENTILES)
        summary[column] = {
            "mean": float(values.mean()),
            "sd": float(values.std(ddof=1)),
            **{
                f"p{percentile:g}": float(value)
                for percentile, value in zip(DIFFERENCE_PERCENTILES, percentiles, strict=True)
            },
        }
    return summary


def build_populations(evaluation_set: EvaluationSet) -> tuple[np.ndarray, dict[str, pd.DataFrame]]:
    """評価セルのメタデータに記録された定義で、共通集合と両シナリオの有効母集団を求める。

    Args:
        evaluation_set: 主シードの評価セル。
    Returns:
        （共通集合の cell_id, `satellite_only`・`limited` をキーとする有効母集団）のタプル。
    Raises:
        ValueError: 分析対象範囲が ROI 以外の場合、または求め直した共通集合の母数が
            メタデータの記録と一致しない場合。
    """
    metadata = evaluation_set.metadata
    if metadata["analysis_area"] != ANALYSIS_AREA_ROI:
        raise ValueError(f"ROI 全域以外の評価セルには対応していません: {metadata['analysis_area']}")
    satellite_path = PROJECT_ROOT / metadata["datasets"]["satellite_only"]
    limited_path = PROJECT_ROOT / metadata["datasets"]["limited"]
    threshold = metadata["lst_valid_ratio_threshold"]

    print(f"Satellite Only のデータセットを読み込みます: {satellite_path}")
    satellite_dataframe = satellite_only.load_scenario_dataset(satellite_path, ANALYSIS_AREA_ROI)
    print(f"Limited のデータセットを読み込みます: {limited_path}")
    limited_dataframe = limited.load_scenario_dataset(
        limited_path,
        [
            source.removeprefix("limited_")
            for source in metadata["configurations"]
            if source.startswith("limited_")
        ],
        ANALYSIS_AREA_ROI,
    )
    common_cell_ids = intersect_cell_ids(
        build_configuration_populations(satellite_dataframe, limited_dataframe, threshold)
    )
    if len(common_cell_ids) != metadata["common_size"]:
        raise ValueError(
            f"求め直した共通集合の母数（{len(common_cell_ids):,}）がメタデータの記録"
            f"（{metadata['common_size']:,}）と一致しません。"
        )
    populations = {
        "satellite_only": satellite_only.build_valid_population(
            satellite_dataframe,
            lst_valid_ratio_threshold=threshold,
            required_mask_columns=satellite_only.resolve_required_mask_columns(ANALYSIS_AREA_ROI),
        ),
        "limited": limited.build_valid_population(
            limited_dataframe,
            filter_columns=limited.resolve_filter_columns(),
            lst_valid_ratio_threshold=threshold,
            required_mask_columns=limited.resolve_required_mask_columns(
                _LIMITED_DEFAULTS.population_source
            ),
        ).population,
    }
    return common_cell_ids, populations


def main(argv: list[str] | None = None) -> None:
    """シードごとに Spatial CV を反復し、シード間の変動と補正 t 区間を保存する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        None
    """
    args = parse_arguments(argv)
    cells_path = args.evaluation_cells.resolve()
    evaluation_set = load_evaluation_set(cells_path)
    metadata = evaluation_set.metadata
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    seeds = resolve_seeds(args.first_seed, args.n_seeds)
    limited_feature_columns = resolve_limited_feature_columns()

    common_cell_ids, populations = build_populations(evaluation_set)
    print(f"共通集合: {len(common_cell_ids):,} セル。シード: {seeds[0]}〜{seeds[-1]}")

    fold_frames: list[pd.DataFrame] = []
    difference_frames: list[pd.DataFrame] = []
    seed_records: list[dict[str, Any]] = []
    for seed in seeds:
        started = time.perf_counter()
        cells, sample_summary = draw_evaluation_cells(
            common_cell_ids,
            sample_size=metadata["sample_size"],
            random_state=seed,
            block_size_m=metadata["block_size_m"],
            scale=metadata["scale_m"],
            cv_splits=metadata["cv_splits"],
        )
        digest = compute_evaluation_cells_digest(cells)
        if seed == metadata["random_state"] and digest != evaluation_set.digest:
            raise ValueError(
                f"seed {seed} で作り直した標本が保存済みの評価セルと一致しません"
                f"（{cells_path}）。共通集合の定義か抽出の手順が保存時と変わっています。"
            )

        completed = load_completed_seed(output_dir, seed, digest)
        if completed is None:
            outcome = run_seed(
                seed,
                cells,
                populations,
                limited_feature_columns,
                metadata["cv_splits"],
                args.rf_trees,
            )
            paths = seed_paths(output_dir, seed)
            outcome["satellite_only"].to_csv(paths["satellite_only"], index=False)
            outcome["limited"].to_csv(paths["limited"], index=False)
            summary = {
                SEED_COLUMN: seed,
                "digest": digest,
                "sample": sample_summary,
                "limited_features": outcome["limited_features"],
                "limited_dropped_constant_features": outcome["limited_dropped_constant_features"],
                "elapsed_seconds": time.perf_counter() - started,
            }
            # 完了印は fold 別指標を保存した後に書く（途中で止まったシードを完了扱いしない）。
            save_summary(summary, paths["summary"])
            completed = {
                "summary": summary,
                "satellite_only": outcome["satellite_only"],
                "limited": outcome["limited"],
            }
            print(f"  seed {seed}: 完了（{summary['elapsed_seconds']:.0f} 秒）")
        else:
            print(f"  seed {seed}: 途中結果を再利用します。")

        for scenario in SCENARIOS:
            fold_frames.append(completed[scenario].assign(scenario=scenario, seed=seed))
        difference_frames.append(
            compute_fold_differences(completed["satellite_only"], completed["limited"]).assign(
                seed=seed
            )
        )
        seed_records.append(completed["summary"])

    fold_table = pd.concat(fold_frames, ignore_index=True)
    differences = pd.concat(difference_frames, ignore_index=True)
    stem = cells_path.stem
    folds_csv = cells_path.with_name(f"repeated_comparison_{stem}_folds.csv")
    differences_csv = cells_path.with_name(f"repeated_comparison_{stem}_differences.csv")
    fold_table.to_csv(folds_csv, index=False)
    differences.to_csv(differences_csv, index=False)

    result = {
        "description": (
            "共通集合から複数シードで標本を抽出し直し、Satellite Only と Limited の"
            "Spatial CV を同じ標本・同じ fold で反復した結果。"
        ),
        "difference_direction": "Limited − Satellite Only",
        "evaluation_cells": to_project_relative_string(cells_path),
        "common_size": int(len(common_cell_ids)),
        "seeds": seeds,
        "cv_splits": metadata["cv_splits"],
        "sample_size": metadata["sample_size"],
        "rf_trees": args.rf_trees,
        "limited_configuration": {
            "variable_set": _LIMITED_DEFAULTS.variable_set,
            "building_height_mode": _LIMITED_DEFAULTS.building_height,
            "water_index_mode": _LIMITED_DEFAULTS.water_index,
            "population_sources": list(_LIMITED_DEFAULTS.population_source),
        },
        "satellite_only_features": list(satellite_only.FEATURE_COLUMNS),
        "seed_records": seed_records,
        "seed_variation": summarize_seed_variation(fold_table),
        "seed_differences": summarize_seed_differences(differences),
        "repeated_kfold": {
            **summarize_metric_differences(differences),
            "note": (
                "J = 分割数 × シード数 の fold ごとの差から求めた補正 t 区間（Bouckaert & Frank "
                "2004 の反復 k-fold の補正）。シードごとに標本自体を抽出し直しているため、区間には"
                "分割の違いだけでなく標本の違いも含まれ、同じデータの分割し直しを想定する原典とは"
                "異なる。"
            ),
        },
        "outputs": {
            "folds_csv": to_project_relative_string(folds_csv),
            "differences_csv": to_project_relative_string(differences_csv),
            "seed_intermediate_dir": to_project_relative_string(output_dir),
        },
        "notes": [
            "シードは標本抽出と RF の random_state の両方に使う。",
            "反復では Spatial CV だけを回し、SHAP・ランダム分割・置換重要度は省く。",
        ],
    }
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    result["provenance"] = build_provenance(
        "src.analysis.repeat_common_evaluation",
        input_paths=[
            PROJECT_ROOT / metadata["datasets"]["satellite_only"],
            PROJECT_ROOT / metadata["datasets"]["limited"],
            cells_path,
            evaluation_set.metadata_path,
        ],
    )
    result_path = cells_path.with_name(f"repeated_comparison_{stem}_results.json")
    save_summary(result, result_path)
    printable = {
        key: value for key, value in result.items() if key not in ("provenance", "seed_records")
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"反復結果を保存しました: {result_path}")


if __name__ == "__main__":
    main()
