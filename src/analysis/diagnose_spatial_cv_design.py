"""Spatial CV の空間ブロック設計（ブロックサイズ・緩衝帯）を診断する。

ブロックサイズを広げると R² が下がる原因には、空間リーク（評価セルのすぐ隣の
学習セルから値を覗ける効果）の除去と、空間的非定常性（保留域が大きな連続地域に
なり外挿になる効果）の2つが混ざる。これを次の2軸の掃引で切り分ける。

- ブロックサイズを固定して**緩衝帯**（評価セルから距離 b 未満の学習セルを除く）を
  広げる → 保留域の大きさは変えずに、評価セルと学習セルの最短距離だけを広げる
- 緩衝帯を固定して**ブロックサイズ**を広げる → 保留域を広げる

サブコマンドは2つある。

1. ``semivariogram``: LST（°C）の経験セミバリオグラムを部分標本で複数本求め、
   空間自己相関の距離スケール（実用 range）の目安を得る。母集団は共通評価セル集合
   （``--evaluation-cells``）か、データセットの Limited の有効母集団（``--dataset``。
   評価セルの無い旧観測の追試用）のどちらか
2. ``sweep``: 共通評価セル集合から ``build_common_evaluation_set`` と同じ手順で標本を
   抽出し、ブロックサイズ × 緩衝帯 × シードの各設定で、Satellite Only と Limited の
   採用構成（各分析スクリプトの既定値）の線形回帰・RF を Spatial CV で評価する。
   out-of-fold 残差からは、距離帯ごとの Moran's I（輪帯・累積）と残差の
   セミバリオグラムを求める。緩衝帯は空間リークと同時に学習量も減らすため、
   緩衝帯なしで学習セルを「緩衝帯 b をかけたときと同じ件数」までランダムに間引いた
   対照（``--thinning-buffers-m``）も評価できる

標本の抽出はブロックの割り当てより前に行われる（``draw_evaluation_cells``）ため、
同じシードならブロックサイズを変えても同じセルの標本になる。ブロックサイズ間の比較は
同じ標本の上で行える。緩衝帯0・保存済みの評価セルと同じブロックサイズ・シードの
設定は、評価セルの内容ダイジェストが保存時と一致することを確かめる。

設定ごとの途中結果を保存し、中断しても続きから再開できる（完了印に記録した実行条件と
標本のダイジェストがすべて一致する設定は計算し直さない。``repeat_common_evaluation`` と
同じ方式）。最終結果は、途中結果の保存先にある**今回と同じ実行条件の完了済み設定すべて**を
集計する（格子の一部だけを足す実行を複数回に分けても、1つの結果にまとまる）。
残差の部分標本は再集計できるよう保存するが、行数が多いため git では追跡しない
（``.gitignore``）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.analysis import analysis_rq3_limited as limited  # noqa: E402
from src.analysis import analysis_rq3_satellite_only as satellite_only  # noqa: E402
from src.analysis import repeat_common_evaluation as repeat  # noqa: E402
from src.analysis.build_common_evaluation_set import (  # noqa: E402
    draw_evaluation_cells,
    resolve_default_cells_path,
)
from src.analysis.urban_params.canonical_grid import SNAP_UNIT_M, split_cell_id  # noqa: E402
from src.common.analysis_runs import validate_fold_test_sizes  # noqa: E402
from src.common.config import PROJECT_ROOT  # noqa: E402
from src.common.evaluation_cells import (  # noqa: E402
    BLOCK_ID_COLUMN,
    CELL_ID_COLUMN,
    FOLD_COLUMN,
    compute_evaluation_cells_digest,
    folds_from_labels,
    load_evaluation_set,
    select_evaluation_rows,
)
from src.common.paths import to_project_relative_string  # noqa: E402
from src.common.regression_models import fit_linear_regression, fit_random_forest  # noqa: E402
from src.common.residual_autocorrelation import BAND_TYPES, compute_moran_correlogram  # noqa: E402
from src.common.semivariogram import build_lag_edges, compute_semivariogram  # noqa: E402
from src.common.spatial_cv import apply_spatial_buffer, thin_training_folds  # noqa: E402
from src.common.summary import (  # noqa: E402
    CODE_WATCH_PATHS,
    DEFAULT_PROVENANCE_PACKAGES,
    build_provenance,
    describe_code_files,
    save_summary,
    script_module_to_path,
)

SCRIPT_MODULE = "src.analysis.diagnose_spatial_cv_design"
SCENARIOS = repeat.SCENARIOS
MODELS = ("linear", "rf")
OUTPUT_ROOT = PROJECT_ROOT / "data" / "output" / "spatial_cv_design"

# 掃引の既定値（実行前に1設定の所要時間を測って確定する）
DEFAULT_BLOCK_SIZES_M = (2700, 5400, 8100, 13500, 21600)
DEFAULT_BUFFERS_M = (0, 900, 2700)
DEFAULT_FIRST_SEED = 42
DEFAULT_N_SEEDS = 2

# ラグ・距離帯の刻みは正準グリッドの原点のスナップ単位（900m）にそろえる
LAG_WIDTH_M = SNAP_UNIT_M
DEFAULT_LST_MAX_LAG_M = 40_500.0
DEFAULT_LST_SAMPLE_SIZE = 10_000
DEFAULT_LST_REPEATS = 3
DEFAULT_RESIDUAL_SAMPLE_SIZE = 5_000
DEFAULT_RESIDUAL_MAX_LAG_M = 13_500.0
# 累積の距離帯は遠いほどペア数が急増するため、輪帯より短い距離までに限る
DEFAULT_CUMULATIVE_MAX_LAG_M = 4_500.0
DEFAULT_PERMUTATIONS = 99

# ブロック設計の判定基準（docs/03_results/survey_area_comparison_results.md と同じ）
MIN_BLOCKS = 10
MAX_FOLD_SIZE_RATIO = 1.5

# 来歴で監視するコード（共通集合の求め方・特徴量の処理を repeat_common_evaluation から呼ぶ）
DIAGNOSE_WATCH_PATHS = (
    *repeat.REPEAT_WATCH_PATHS,
    "src/analysis/repeat_common_evaluation.py",
)
PROVENANCE_PACKAGES = (*DEFAULT_PROVENANCE_PACKAGES, "esda", "libpysal", "scikit-gstat", "scipy")
RUN_CONDITIONS_KEY = "run_conditions"
# 設定を識別する列（シードを除く）。学習量の対照でない設定の thinned_to_buffer_m は 0
CONFIG_KEYS = ("block_size_m", "buffer_m", "thinned_to_buffer_m")
# 集計結果の configs に残す完了印の項目
CONFIG_RECORD_KEYS = (
    "seed",
    *CONFIG_KEYS,
    "block_design",
    "buffer",
    "elapsed_seconds",
)
# Limited の採用構成・フィルタの既定値（分析スクリプトの引数の既定値）
_LIMITED_DEFAULTS = limited.parse_arguments([])


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        解析結果（`command` にサブコマンド名を持つ）。
    """
    parser = argparse.ArgumentParser(description="Spatial CV のブロック設計を診断する")
    subparsers = parser.add_subparsers(dest="command", required=True)

    semivariogram = subparsers.add_parser(
        "semivariogram", help="LST の経験セミバリオグラムを部分標本で複数本求める"
    )
    source = semivariogram.add_mutually_exclusive_group()
    source.add_argument(
        "--evaluation-cells",
        type=Path,
        default=None,
        help="共通評価セル CSV（既定。母集団は共通集合）",
    )
    source.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Limited のデータセット（母集団はその有効母集団。評価セルの無い観測の追試用）",
    )
    semivariogram.add_argument("--sample-size", type=int, default=DEFAULT_LST_SAMPLE_SIZE)
    semivariogram.add_argument("--repeats", type=int, default=DEFAULT_LST_REPEATS)
    semivariogram.add_argument("--first-seed", type=int, default=DEFAULT_FIRST_SEED)
    semivariogram.add_argument("--max-lag-m", type=float, default=DEFAULT_LST_MAX_LAG_M)
    semivariogram.add_argument("--output-dir", type=Path, default=None)

    sweep = subparsers.add_parser("sweep", help="ブロックサイズ × 緩衝帯 × シードを掃引する")
    sweep.add_argument("--evaluation-cells", type=Path, default=resolve_default_cells_path())
    sweep.add_argument("--block-sizes-m", type=int, nargs="+", default=list(DEFAULT_BLOCK_SIZES_M))
    sweep.add_argument("--buffers-m", type=float, nargs="+", default=list(DEFAULT_BUFFERS_M))
    sweep.add_argument(
        "--thinning-buffers-m",
        type=float,
        nargs="*",
        default=[],
        help="学習量の対照: 緩衝帯なしで、この緩衝帯をかけたときと同じ学習セル数まで間引く",
    )
    sweep.add_argument("--first-seed", type=int, default=DEFAULT_FIRST_SEED)
    sweep.add_argument("--n-seeds", type=int, default=DEFAULT_N_SEEDS)
    sweep.add_argument(
        "--rf-trees",
        type=int,
        default=_LIMITED_DEFAULTS.rf_trees,
        help="RF の決定木本数（既定は分析スクリプトの既定値）",
    )
    sweep.add_argument("--residual-sample-size", type=int, default=DEFAULT_RESIDUAL_SAMPLE_SIZE)
    sweep.add_argument("--residual-max-lag-m", type=float, default=DEFAULT_RESIDUAL_MAX_LAG_M)
    sweep.add_argument("--cumulative-max-lag-m", type=float, default=DEFAULT_CUMULATIVE_MAX_LAG_M)
    sweep.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    sweep.add_argument("--output-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "semivariogram" and args.dataset is None and args.evaluation_cells is None:
        args.evaluation_cells = resolve_default_cells_path()
    if args.command == "sweep" and args.n_seeds < 1:
        parser.error(f"--n-seeds は1以上にしてください: {args.n_seeds}")
    return args


def resolve_observation_dir_name(text: str) -> str:
    """観測日時を含む文字列から、出力ディレクトリ名（``YYYYMMDD_HHMMSS``）を求める。

    Args:
        text: ``2022-09-06 03:23:58`` 形式の観測日時、または
            ``dataset_limited_20230707_032305_hanoi_30m`` のようなファイル名。
    Returns:
        ``20220906_032358`` 形式の文字列。
    Raises:
        ValueError: 観測日時を読み取れない場合。
    """
    digits = re.sub(r"[-: ]", "", text) if re.fullmatch(r"[\d\- :]+", text) else text
    match = re.search(r"(\d{8})_?(\d{6})", digits)
    if match is None:
        raise ValueError(f"観測日時を読み取れません: {text}")
    return f"{match.group(1)}_{match.group(2)}"


def cell_coordinates(cell_ids: np.ndarray, scale: float) -> np.ndarray:
    """cell_id から正準グリッドのセル中心間距離を保つ座標（m）を求める。

    x を列方向、y を行方向とする（距離だけを使うため、原点と向きは問わない）。

    Args:
        cell_ids: cell_id の配列。
        scale: 正準グリッドの解像度（m/セル）。
    Returns:
        形状 ``(n, 2)`` の座標配列。
    """
    row, col = split_cell_id(np.asarray(cell_ids, dtype=np.int64))
    return np.column_stack((col, row)).astype(float) * scale


def draw_subsample_indices(n_total: int, sample_size: int, seed: int) -> np.ndarray:
    """非復元の部分標本の位置を昇順で求める。

    Args:
        n_total: 母集団の件数。
        sample_size: 部分標本の件数（``n_total`` 以上なら全件）。
        seed: 乱数シード。
    Returns:
        昇順の位置の配列。
    """
    if sample_size >= n_total:
        return np.arange(n_total)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n_total, size=sample_size, replace=False))


def load_common_lst(cells_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """共通評価セル集合の cell_id と LST（°C）を求める。

    Args:
        cells_path: 共通評価セル CSV。
    Returns:
        （``cell_id``・``LST`` 列のデータフレーム, 母集団の記録）のタプル。
    """
    evaluation_set = load_evaluation_set(cells_path)
    common_cell_ids, populations = repeat.build_populations(evaluation_set)
    population = populations["limited"]
    lst = population.loc[
        population[CELL_ID_COLUMN].isin(common_cell_ids), [CELL_ID_COLUMN, limited.TARGET_COLUMN]
    ].reset_index(drop=True)
    record = {
        "population": "common_evaluation_set",
        "evaluation_cells": to_project_relative_string(cells_path),
        "observation": evaluation_set.metadata["observation"],
        "analysis_area": evaluation_set.metadata["analysis_area"],
        "scale_m": evaluation_set.metadata["scale_m"],
        "input_paths": [
            PROJECT_ROOT / evaluation_set.metadata["datasets"]["satellite_only"],
            PROJECT_ROOT / evaluation_set.metadata["datasets"]["limited"],
            cells_path,
            evaluation_set.metadata_path,
        ],
    }
    return lst, record


def load_dataset_lst(dataset_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Limited のデータセットの有効母集団（分析スクリプトの既定のフィルタ）の LST を求める。

    Args:
        dataset_path: Limited のデータセット（GeoPackage）。
    Returns:
        （``cell_id``・``LST`` 列のデータフレーム, 母集団の記録）のタプル。
    """
    defaults = _LIMITED_DEFAULTS
    print(f"Limited のデータセットを読み込みます: {dataset_path}")
    dataframe = limited.load_scenario_dataset(
        dataset_path, defaults.population_source, defaults.analysis_area
    )
    population = limited.build_valid_population(
        dataframe,
        filter_columns=limited.resolve_filter_columns(),
        lst_valid_ratio_threshold=defaults.lst_valid_ratio_threshold,
        required_mask_columns=limited.resolve_required_mask_columns(
            defaults.population_source, defaults.analysis_area
        ),
    ).population
    lst = population[[CELL_ID_COLUMN, limited.TARGET_COLUMN]].reset_index(drop=True)
    record = {
        "population": "limited_valid_population",
        "dataset": to_project_relative_string(dataset_path),
        "observation": resolve_observation_dir_name(dataset_path.stem),
        "analysis_area": defaults.analysis_area,
        "lst_valid_ratio_threshold": defaults.lst_valid_ratio_threshold,
        "population_sources": list(defaults.population_source),
        "scale_m": defaults.scale,
        "input_paths": [dataset_path],
    }
    return lst, record


def run_lst_semivariogram(
    lst: pd.DataFrame,
    scale: float,
    sample_size: int,
    repeats: int,
    first_seed: int,
    max_lag_m: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """LST の経験セミバリオグラムを部分標本で複数本求める。

    Args:
        lst: ``cell_id``・``LST`` 列のデータフレーム（母集団）。
        scale: 正準グリッドの解像度（m/セル）。
        sample_size: 1本あたりの部分標本の件数。
        repeats: 部分標本の本数（シードは ``first_seed`` からの連番）。
        first_seed: 最初のシード。
        max_lag_m: 最大ラグ（m）。
    Returns:
        （``repeat``・``seed`` 列つきのラグ表, 要約）のタプル。要約には各本の要約と、
        経験的な実用 range・モデルの range の本間の範囲を含める。
    """
    coords = cell_coordinates(lst[CELL_ID_COLUMN].to_numpy(), scale)
    values = lst[limited.TARGET_COLUMN].to_numpy(dtype=float)
    tables = []
    runs = []
    for repeat_no in range(repeats):
        seed = first_seed + repeat_no
        started = time.perf_counter()
        index = draw_subsample_indices(len(values), sample_size, seed)
        table, summary = compute_semivariogram(coords[index], values[index], LAG_WIDTH_M, max_lag_m)
        summary["seed"] = seed
        summary["elapsed_seconds"] = time.perf_counter() - started
        print(
            f"  部分標本 {repeat_no + 1}/{repeats}（seed {seed}）: "
            f"{summary['elapsed_seconds']:.0f} 秒"
        )
        tables.append(table.assign(repeat=repeat_no + 1, seed=seed))
        runs.append(summary)

    empirical = [run["empirical_range_m"] for run in runs]
    model_ranges = {
        model["model"]: [
            run_model["effective_range_m"]
            for run in runs
            for run_model in run["models"]
            if run_model["model"] == model["model"]
        ]
        for model in runs[0]["models"]
    }
    summary = {
        "population_size": int(len(values)),
        "population_variance": float(np.var(values, ddof=1)),
        "sample_size": int(min(sample_size, len(values))),
        "repeats": runs,
        "spread": {
            "empirical_range_m": empirical,
            "effective_range_m": model_ranges,
        },
    }
    return pd.concat(tables, ignore_index=True), summary


def plot_semivariogram(lag_table: pd.DataFrame, title: str, path: Path) -> None:
    """部分標本ごとの半分散（全体分散に対する比）をラグに対して描く。

    Args:
        lag_table: ``run_lst_semivariogram`` のラグ表。
        title: 図のタイトル。
        path: 保存先（PNG）。
    Returns:
        None
    """
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for (repeat_no, seed), group in lag_table.groupby(["repeat", "seed"]):
        ax.plot(
            group["lag_center_m"] / 1000,
            group["ratio_to_variance"],
            marker="o",
            markersize=3,
            label=f"subsample {repeat_no} (seed {seed})",
        )
    ax.axhline(1.0, color="gray", linewidth=0.8)
    ax.axhline(0.95, color="gray", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Distance (km, lag center)")
    ax.set_ylabel("Semivariance / variance")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_semivariogram_command(args: argparse.Namespace) -> None:
    """``semivariogram`` サブコマンドを実行する。

    Args:
        args: ``parse_arguments`` の戻り値。
    Returns:
        None
    """
    if args.dataset is not None:
        lst, record = load_dataset_lst(args.dataset.resolve())
    else:
        lst, record = load_common_lst(args.evaluation_cells.resolve())
    output_dir = args.output_dir or OUTPUT_ROOT / resolve_observation_dir_name(
        record["observation"]
    )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"母集団: {len(lst):,} セル。部分標本 {args.sample_size:,} 件 × {args.repeats} 本")

    lag_table, summary = run_lst_semivariogram(
        lst, record["scale_m"], args.sample_size, args.repeats, args.first_seed, args.max_lag_m
    )
    lags_csv = output_dir / "lst_semivariogram_lags.csv"
    figure = output_dir / "lst_semivariogram.png"
    lag_table.to_csv(lags_csv, index=False)
    plot_semivariogram(lag_table, f"LST empirical semivariogram ({record['observation']})", figure)

    input_paths = record.pop("input_paths")
    result = {
        "description": (
            "LST（°C）の経験セミバリオグラム（Matheron 推定量）を部分標本で複数本求めた結果。"
        ),
        **record,
        "lag_width_m": LAG_WIDTH_M,
        "max_lag_m": args.max_lag_m,
        **summary,
        "outputs": {
            "lags_csv": to_project_relative_string(lags_csv),
            "figure": to_project_relative_string(figure),
        },
    }
    result["provenance"] = build_provenance(
        SCRIPT_MODULE,
        input_paths=input_paths,
        packages=PROVENANCE_PACKAGES,
        extra_watch_paths=DIAGNOSE_WATCH_PATHS,
    )
    result_path = output_dir / "lst_semivariogram_results.json"
    save_summary(result, result_path)
    print(json.dumps(summary["spread"], ensure_ascii=False, indent=2))
    print(f"セミバリオグラムを保存しました: {result_path}")


def resolve_seeds(first_seed: int, n_seeds: int) -> list[int]:
    """掃引に使うシードの一覧を求める。

    Args:
        first_seed: 最初のシード。
        n_seeds: シード数。
    Returns:
        ``first_seed`` からの連番の ``n_seeds`` 個のシード。
    """
    return list(range(first_seed, first_seed + n_seeds))


def config_key(
    seed: int, block_size_m: int, buffer_m: float, thinned_to_buffer_m: float = 0.0
) -> str:
    """設定（シード・ブロックサイズ・緩衝帯・学習量の対照）を表すファイル名用の文字列を作る。

    Args:
        seed: シード。
        block_size_m: ブロックサイズ（m）。
        buffer_m: 緩衝帯（m）。
        thinned_to_buffer_m: 学習量の対照で合わせる緩衝帯（m）。0 なら間引かない。
    Returns:
        ``seed42_block2700_buffer900`` の形式の文字列。学習量の対照では
        ``seed42_block2700_buffer0_thinned900`` のように接尾辞を付ける。
    """
    key = f"seed{seed}_block{block_size_m}_buffer{buffer_m:g}"
    return f"{key}_thinned{thinned_to_buffer_m:g}" if thinned_to_buffer_m else key


def config_paths(intermediate_dir: Path, key: str) -> dict[str, Path]:
    """設定ごとの途中結果のパスを求める。

    完了印（``summary``）は ``_results.json`` で終わらせない（陳腐化チェックの走査対象を
    最終結果だけにするため）。

    Args:
        intermediate_dir: 途中結果の保存先。
        key: ``config_key`` の戻り値。
    Returns:
        ``summary``・``folds``・``correlograms``・``residual_semivariograms``・
        ``residuals`` をキーとするパスの辞書。
    """
    return {
        "summary": intermediate_dir / f"{key}_summary.json",
        "folds": intermediate_dir / f"{key}_folds.csv",
        "correlograms": intermediate_dir / f"{key}_correlograms.csv",
        "residual_semivariograms": intermediate_dir / f"{key}_residual_semivariograms.csv",
        "residuals": intermediate_dir / f"{key}_residuals.csv",
    }


def summarize_block_design(cells: pd.DataFrame) -> dict[str, Any]:
    """標本のブロック数と fold の評価セル数の均衡を求め、判定基準と照らす。

    Args:
        cells: 評価セル（``block_id``・``fold`` 列を持つ）。
    Returns:
        非空ブロック数・fold ごとの評価セル数・最大/最小比・基準を満たすかの辞書。
    """
    fold_sizes = cells[FOLD_COLUMN].value_counts().sort_index()
    ratio = float(fold_sizes.max() / fold_sizes.min())
    n_blocks = int(cells[BLOCK_ID_COLUMN].nunique())
    return {
        "n_blocks": n_blocks,
        "fold_test_sizes": {str(int(fold)): int(size) for fold, size in fold_sizes.items()},
        "fold_size_ratio": ratio,
        "meets_min_blocks": n_blocks >= MIN_BLOCKS,
        "meets_fold_size_ratio": ratio <= MAX_FOLD_SIZE_RATIO,
    }


def evaluate_fold_models(
    sample: pd.DataFrame,
    feature_columns: Sequence[str],
    target_column: str,
    folds: Sequence[tuple[np.ndarray, np.ndarray]],
    random_state: int,
    rf_trees: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """各 fold で線形回帰・RF を学習・評価し、fold 別指標と out-of-fold 予測を返す。

    ``analysis_runs.run_spatial_cv_models`` と同じ関数・引数で学習する（緩衝帯0なら
    同じ指標になる）。残差を求めるため、予測値も返す点だけが異なる。

    Args:
        sample: 評価セルの行順にそろえた標本。
        feature_columns: 説明変数の列名。
        target_column: 目的変数の列名（LST、°C）。
        folds: (train_idx, test_idx) のリスト（行位置）。
        random_state: RF の乱数シード。
        rf_trees: RF の決定木本数。
    Returns:
        （fold 別指標, ``position``・``fold``・``observed``・``linear_pred``・
        ``rf_pred`` 列の out-of-fold 予測）のタプル。
    """
    x = sample[list(feature_columns)]
    y = sample[target_column]
    fold_rows = []
    predictions = []
    for fold_no, (train_idx, test_idx) in enumerate(folds, start=1):
        x_train, x_test = x.iloc[train_idx], x.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        linear_result, _, linear_pred = fit_linear_regression(x_train, x_test, y_train, y_test)
        _, rf_result, _, _, rf_pred = fit_random_forest(
            x_train,
            x_test,
            y_train,
            y_test,
            random_state=random_state,
            n_estimators=rf_trees,
            compute_permutation_importance=False,
        )
        fold_rows.append(
            {
                "fold": fold_no,
                "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                **{f"linear_{k}": v for k, v in linear_result["metrics"].items()},
                **{f"rf_{k}": v for k, v in rf_result["metrics"].items()},
            }
        )
        predictions.append(
            pd.DataFrame(
                {
                    "position": test_idx,
                    "fold": fold_no,
                    "observed": y_test.to_numpy(dtype=float),
                    "linear_pred": np.asarray(linear_pred, dtype=float),
                    "rf_pred": np.asarray(rf_pred, dtype=float),
                }
            )
        )
    oof = pd.concat(predictions, ignore_index=True).sort_values("position", ignore_index=True)
    return pd.DataFrame(fold_rows), oof


def analyze_residuals(
    coords: np.ndarray,
    residuals: Mapping[str, np.ndarray],
    residual_max_lag_m: float,
    cumulative_max_lag_m: float,
    permutations: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """系列ごとに、距離帯ごとの Moran's I（輪帯・累積）とセミバリオグラムを求める。

    Args:
        coords: 部分標本の座標（m）。
        residuals: 系列名（例: ``limited_rf``）→ 部分標本の値の辞書。
        residual_max_lag_m: 輪帯の Moran's I とセミバリオグラムの最大距離。
        cumulative_max_lag_m: 累積の Moran's I の最大距離。
        permutations: 並べ替え検定の回数。
        seed: 並べ替え検定の乱数シード。
    Returns:
        （コレログラム, セミバリオグラムのラグ表, 系列ごとのセミバリオグラム要約）のタプル。
    """
    max_lags = {"ring": residual_max_lag_m, "cumulative": cumulative_max_lag_m}
    correlograms = []
    lag_tables = []
    summaries = {}
    for series, values in residuals.items():
        for band_type in BAND_TYPES:
            edges = build_lag_edges(LAG_WIDTH_M, max_lags[band_type])
            correlograms.append(
                compute_moran_correlogram(
                    coords, values, edges, band_type, permutations, seed
                ).assign(series=series)
            )
        table, summary = compute_semivariogram(coords, values, LAG_WIDTH_M, residual_max_lag_m)
        lag_tables.append(table.assign(series=series))
        summaries[series] = summary
    return (
        pd.concat(correlograms, ignore_index=True),
        pd.concat(lag_tables, ignore_index=True),
        summaries,
    )


def compute_code_digest() -> str | None:
    """途中結果の再利用判定に使う、結果に効くコードの内容ダイジェストを求める。

    Returns:
        SHA-256 の16進文字列。git を利用できない場合は ``None``。
    """
    code = describe_code_files(
        [script_module_to_path(SCRIPT_MODULE), *CODE_WATCH_PATHS, *DIAGNOSE_WATCH_PATHS]
    )
    if code is None:
        return None
    files = json.dumps(code["files"], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(files.encode("utf-8")).hexdigest()


def load_completed_config(
    paths: Mapping[str, Path], digest: str, run_conditions: Mapping[str, Any]
) -> dict[str, Any] | None:
    """完了済みの設定の途中結果を読む（標本のダイジェストと実行条件が一致する場合のみ）。

    Args:
        paths: ``config_paths`` の戻り値。
        digest: 今回作り直した評価セルの内容ダイジェスト。
        run_conditions: 今回の実行条件。
    Returns:
        完了済みなら ``summary``・``folds``・``correlograms``・``residual_semivariograms`` の
        辞書、未完了・不一致なら ``None``。
    """
    if not all(paths[name].is_file() for name in ("summary", "folds", "correlograms")):
        return None
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    if run_conditions.get("code_digest") is None:
        print("    コードのダイジェストを求められないため、計算し直します。")
        return None
    if summary.get("digest") != digest or summary.get(RUN_CONDITIONS_KEY) != dict(run_conditions):
        print("    途中結果の標本または実行条件が今回と違うため、計算し直します。")
        return None
    return {
        "summary": summary,
        "folds": pd.read_csv(paths["folds"]),
        "correlograms": pd.read_csv(paths["correlograms"]),
        "residual_semivariograms": pd.read_csv(paths["residual_semivariograms"]),
    }


def run_config(
    seed: int,
    cells: pd.DataFrame,
    buffer_m: float,
    thinned_to_buffer_m: float,
    populations: Mapping[str, pd.DataFrame],
    limited_feature_columns: Sequence[str],
    args: argparse.Namespace,
    scale: float,
    cv_splits: int,
) -> dict[str, Any]:
    """1つの設定について、両シナリオの Spatial CV と残差の分析を行う。

    Args:
        seed: 標本抽出・RF・部分標本・間引き・並べ替え検定の乱数シード。
        cells: このシード・ブロックサイズの評価セル（``draw_evaluation_cells``）。
        buffer_m: 緩衝帯（m）。
        thinned_to_buffer_m: 学習量の対照で合わせる緩衝帯（m）。正の値なら、緩衝帯
            ``buffer_m`` の fold の学習側を、この緩衝帯をかけたときの fold ごとの学習セル数
            までランダムに間引く。0 なら間引かない。
        populations: ``satellite_only``・``limited`` をキーとする有効母集団。
        limited_feature_columns: Limited の投入候補の列。
        args: ``parse_arguments`` の戻り値（RF 本数・残差の分析条件）。
        scale: 正準グリッドの解像度（m/セル）。
        cv_splits: 分割数。
    Returns:
        ``folds``・``correlograms``・``residual_semivariograms``・``residuals`` の
        データフレームと、``buffer``（fold ごとの学習セル数）・``limited_features``・
        ``residual_semivariogram_summaries`` を持つ辞書。
    """
    folds = folds_from_labels(cells[FOLD_COLUMN].to_numpy(), cv_splits)
    validate_fold_test_sizes(folds)
    cell_ids = cells[CELL_ID_COLUMN].to_numpy(dtype=np.int64)
    row, col = split_cell_id(cell_ids)
    buffered_folds, buffer_info = apply_spatial_buffer(folds, row, col, scale, buffer_m)
    if thinned_to_buffer_m:
        _, matched_info = apply_spatial_buffer(folds, row, col, scale, thinned_to_buffer_m)
        buffered_folds, buffer_info = thin_training_folds(
            buffered_folds, [info["n_train_after"] for info in matched_info], seed
        )

    satellite_sample = select_evaluation_rows(populations["satellite_only"], cells)
    limited_sample, kept, _ = repeat.prepare_limited_sample(
        select_evaluation_rows(populations["limited"], cells), limited_feature_columns
    )
    scenario_inputs = {
        "satellite_only": (
            satellite_sample,
            satellite_only.FEATURE_COLUMNS,
            satellite_only.TARGET_COLUMN,
        ),
        "limited": (limited_sample, kept, limited.TARGET_COLUMN),
    }

    # 残差の部分標本は、シナリオ・モデル・緩衝帯・間引きをまたいで同じセルにそろえる
    subsample = draw_subsample_indices(len(cells), args.residual_sample_size, seed)
    fold_frames = []
    residual_values: dict[str, np.ndarray] = {}
    residual_frame = pd.DataFrame({CELL_ID_COLUMN: cell_ids[subsample]})
    for scenario, (sample, features, target) in scenario_inputs.items():
        fold_table, oof = evaluate_fold_models(
            sample, features, target, buffered_folds, seed, args.rf_trees
        )
        fold_table = fold_table.assign(scenario=scenario)
        fold_table["n_excluded"] = [info["n_excluded"] for info in buffer_info]
        fold_frames.append(fold_table)
        oof = oof.set_index("position").loc[subsample]
        for model in MODELS:
            series = f"{scenario}_{model}"
            residual_values[series] = (oof["observed"] - oof[f"{model}_pred"]).to_numpy()
            residual_frame[series] = residual_values[series]

    coords = cell_coordinates(cell_ids[subsample], scale)
    correlograms, residual_lags, residual_summaries = analyze_residuals(
        coords,
        residual_values,
        args.residual_max_lag_m,
        args.cumulative_max_lag_m,
        args.permutations,
        seed,
    )
    return {
        "folds": pd.concat(fold_frames, ignore_index=True),
        "correlograms": correlograms,
        "residual_semivariograms": residual_lags,
        "residuals": residual_frame,
        "buffer": buffer_info,
        "limited_features": kept,
        "residual_semivariogram_summaries": residual_summaries,
    }


def summarize_sweep(fold_table: pd.DataFrame) -> pd.DataFrame:
    """設定・シナリオごとに fold 平均の指標と学習セル数を集計する。

    Args:
        fold_table: 全設定の fold 別指標（``seed``・``block_size_m``・``buffer_m``・
            ``thinned_to_buffer_m``・``scenario`` 列を持つ）。
    Returns:
        設定・シナリオごとの fold 平均（R²・RMSE・MAE・学習セル数・除外数）の表。
        シード間の平均と sd は ``summarize_across_seeds`` で求める。
    """
    metric_columns = [
        column
        for column in fold_table.columns
        if column.startswith(("linear_", "rf_")) or column in ("train_size", "n_excluded")
    ]
    keys = [*CONFIG_KEYS, "scenario", "seed"]
    return fold_table.groupby(keys)[metric_columns].mean().reset_index()


def summarize_across_seeds(per_seed: pd.DataFrame) -> pd.DataFrame:
    """シード間の平均・sd を求める。

    Args:
        per_seed: ``summarize_sweep`` の戻り値。
    Returns:
        ブロックサイズ・緩衝帯・学習量の対照・シナリオごとの、各指標の平均（列名そのまま）と
        sd（``_sd`` 接尾辞。シードが1本なら NaN）の表。
    """
    keys = [*CONFIG_KEYS, "scenario"]
    metrics = [column for column in per_seed.columns if column not in (*keys, "seed")]
    grouped = per_seed.groupby(keys)[metrics]
    mean = grouped.mean()
    sd = grouped.std(ddof=1).add_suffix("_sd")
    return pd.concat([mean, sd], axis=1).reset_index()


def plot_sweep(summary: pd.DataFrame, path: Path) -> None:
    """ブロックサイズに対する out-of-fold R² を、緩衝帯ごとの線で描く。

    学習量の対照は、合わせた緩衝帯ごとの破線で描く。

    Args:
        summary: ``summarize_across_seeds`` の戻り値。
        path: 保存先（PNG）。
    Returns:
        None
    """
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, sharey=True)
    for row_no, scenario in enumerate(SCENARIOS):
        for col_no, model in enumerate(MODELS):
            ax = axes[row_no, col_no]
            data = summary[summary["scenario"] == scenario]
            for (buffer_m, thinned_m), group in data.groupby(["buffer_m", "thinned_to_buffer_m"]):
                group = group.sort_values("block_size_m")
                label = f"buffer {buffer_m:g} m"
                if thinned_m:
                    label = f"no buffer, train thinned as buffer {thinned_m:g} m"
                ax.errorbar(
                    group["block_size_m"] / 1000,
                    group[f"{model}_r2"],
                    yerr=group[f"{model}_r2_sd"].fillna(0),
                    marker="x" if thinned_m else "o",
                    linestyle="--" if thinned_m else "-",
                    capsize=3,
                    label=label,
                )
            ax.set_title(f"{scenario} / {model}")
            ax.set_xlabel("Block size (km)")
            ax.set_ylabel("Out-of-fold R2 (fold mean)")
            ax.grid(alpha=0.3)
    axes[0, 0].legend(fontsize="x-small")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def resolve_config_grid(
    buffers_m: Sequence[float], thinning_buffers_m: Sequence[float]
) -> list[tuple[float, float]]:
    """1つのシード・ブロックサイズで回す（緩衝帯, 学習量の対照で合わせる緩衝帯）の組を求める。

    Args:
        buffers_m: 緩衝帯の一覧。
        thinning_buffers_m: 学習量の対照で合わせる緩衝帯の一覧（緩衝帯なしで間引く）。
    Returns:
        ``(buffer_m, thinned_to_buffer_m)`` のリスト。緩衝帯の設定が先、対照が後。
    """
    return [(float(buffer_m), 0.0) for buffer_m in buffers_m] + [
        (0.0, float(thinned_m)) for thinned_m in thinning_buffers_m
    ]


def collect_completed_configs(
    intermediate_dir: Path, run_conditions: Mapping[str, Any]
) -> dict[str, Any]:
    """途中結果の保存先から、今回と同じ実行条件の完了済み設定をすべて集める。

    格子の一部を足す実行を複数回に分けても1つの結果にまとめるためである。実行条件
    （コード・データセットのハッシュを含む）が違う設定は集めない。

    Args:
        intermediate_dir: 途中結果の保存先。
        run_conditions: 今回の実行条件。
    Returns:
        ``folds``・``correlograms``・``residual_semivariograms``（設定の列つきの
        データフレーム）と ``records``（設定ごとの完了印の抜粋のリスト）の辞書。
    Raises:
        ValueError: 集める設定が1つも無い場合。
    """
    frames: dict[str, list[pd.DataFrame]] = {
        "folds": [],
        "correlograms": [],
        "residual_semivariograms": [],
    }
    records = []
    for summary_path in sorted(intermediate_dir.glob("*_summary.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get(RUN_CONDITIONS_KEY) != dict(run_conditions):
            continue
        paths = config_paths(intermediate_dir, summary_path.name.removesuffix("_summary.json"))
        columns = {"seed": summary["seed"], **{key: summary[key] for key in CONFIG_KEYS}}
        for name, items in frames.items():
            items.append(pd.read_csv(paths[name]).assign(**columns))
        records.append({key: summary[key] for key in CONFIG_RECORD_KEYS})
    if not records:
        raise ValueError(f"集計できる完了済みの設定がありません: {intermediate_dir}")
    return {
        **{name: pd.concat(items, ignore_index=True) for name, items in frames.items()},
        "records": records,
    }


def run_sweep_command(args: argparse.Namespace) -> None:
    """``sweep`` サブコマンドを実行する。

    Args:
        args: ``parse_arguments`` の戻り値。
    Returns:
        None
    """
    cells_path = args.evaluation_cells.resolve()
    evaluation_set = load_evaluation_set(cells_path)
    metadata = evaluation_set.metadata
    output_dir = (
        args.output_dir or OUTPUT_ROOT / resolve_observation_dir_name(metadata["observation"])
    ).resolve()
    intermediate_dir = output_dir / "sweep"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    seeds = resolve_seeds(args.first_seed, args.n_seeds)
    scale = metadata["scale_m"]
    cv_splits = metadata["cv_splits"]
    limited_feature_columns = repeat.resolve_limited_feature_columns()

    print("途中結果の再利用判定のため、コードと両データセットのハッシュを求めます。")
    run_conditions = {
        "rf_trees": int(args.rf_trees),
        "cv_splits": int(cv_splits),
        "limited_configuration": repeat.build_limited_configuration(),
        "limited_feature_columns": list(limited_feature_columns),
        "satellite_only_features": list(satellite_only.FEATURE_COLUMNS),
        "residual_sample_size": int(args.residual_sample_size),
        "residual_max_lag_m": float(args.residual_max_lag_m),
        "cumulative_max_lag_m": float(args.cumulative_max_lag_m),
        "permutations": int(args.permutations),
        "code_digest": compute_code_digest(),
        "dataset_sha256": repeat.compute_dataset_hashes(metadata),
    }
    common_cell_ids, populations = repeat.build_populations(evaluation_set)
    print(f"共通集合: {len(common_cell_ids):,} セル。シード: {seeds}")

    grid = resolve_config_grid(args.buffers_m, args.thinning_buffers_m)
    for seed in seeds:
        for block_size_m in args.block_sizes_m:
            cells, sample_summary = draw_evaluation_cells(
                common_cell_ids,
                sample_size=metadata["sample_size"],
                random_state=seed,
                block_size_m=block_size_m,
                scale=scale,
                cv_splits=cv_splits,
            )
            digest = compute_evaluation_cells_digest(cells)
            if (
                seed == metadata["random_state"]
                and block_size_m == metadata["block_size_m"]
                and digest != evaluation_set.digest
            ):
                raise ValueError(
                    f"seed {seed}・ブロック {block_size_m}m で作り直した標本が保存済みの評価セルと"
                    f"一致しません（{cells_path}）。"
                )
            design = summarize_block_design(cells)
            for buffer_m, thinned_m in grid:
                key = config_key(seed, block_size_m, buffer_m, thinned_m)
                paths = config_paths(intermediate_dir, key)
                print(f"  {key}:")
                started = time.perf_counter()
                if load_completed_config(paths, digest, run_conditions) is not None:
                    print("    途中結果を再利用します。")
                    continue
                outcome = run_config(
                    seed,
                    cells,
                    buffer_m,
                    thinned_m,
                    populations,
                    limited_feature_columns,
                    args,
                    scale,
                    cv_splits,
                )
                outcome["folds"].to_csv(paths["folds"], index=False)
                outcome["correlograms"].to_csv(paths["correlograms"], index=False)
                outcome["residual_semivariograms"].to_csv(
                    paths["residual_semivariograms"], index=False
                )
                outcome["residuals"].to_csv(paths["residuals"], index=False)
                summary = {
                    "seed": seed,
                    "block_size_m": block_size_m,
                    "buffer_m": buffer_m,
                    "thinned_to_buffer_m": thinned_m,
                    "digest": digest,
                    RUN_CONDITIONS_KEY: run_conditions,
                    "sample": sample_summary,
                    "block_design": design,
                    "buffer": outcome["buffer"],
                    "limited_features": outcome["limited_features"],
                    "residual_semivariograms": outcome["residual_semivariogram_summaries"],
                    "elapsed_seconds": time.perf_counter() - started,
                }
                # 完了印は他の途中結果を保存した後に書く（途中で止まった設定を完了扱いしない）
                save_summary(summary, paths["summary"])
                print(f"    完了（{summary['elapsed_seconds']:.0f} 秒）")

    collected = collect_completed_configs(intermediate_dir, run_conditions)
    fold_table = collected["folds"]
    per_seed = summarize_sweep(fold_table)
    summary_table = summarize_across_seeds(per_seed)
    outputs = {
        "folds_csv": output_dir / "spatial_cv_sweep_folds.csv",
        "summary_csv": output_dir / "spatial_cv_sweep_summary.csv",
        "correlograms_csv": output_dir / "spatial_cv_sweep_correlograms.csv",
        "residual_semivariograms_csv": output_dir / "spatial_cv_sweep_residual_semivariograms.csv",
        "figure": output_dir / "spatial_cv_sweep_r2.png",
    }
    fold_table.to_csv(outputs["folds_csv"], index=False)
    summary_table.to_csv(outputs["summary_csv"], index=False)
    collected["correlograms"].to_csv(outputs["correlograms_csv"], index=False)
    collected["residual_semivariograms"].to_csv(outputs["residual_semivariograms_csv"], index=False)
    plot_sweep(summary_table, outputs["figure"])

    result = {
        "description": (
            "共通評価セル集合の標本で、ブロックサイズ × 緩衝帯（と学習量の対照）× シードの"
            "各設定の Spatial CV を"
            "評価し、out-of-fold 残差の空間自己相関を測った結果。"
        ),
        "evaluation_cells": to_project_relative_string(cells_path),
        "observation": metadata["observation"],
        "analysis_area": metadata["analysis_area"],
        "common_size": int(len(common_cell_ids)),
        "sample_size": metadata["sample_size"],
        "seeds": sorted({record["seed"] for record in collected["records"]}),
        "block_sizes_m": sorted({record["block_size_m"] for record in collected["records"]}),
        "buffers_m": sorted({record["buffer_m"] for record in collected["records"]}),
        "thinned_to_buffers_m": sorted(
            {record["thinned_to_buffer_m"] for record in collected["records"]} - {0.0}
        ),
        "lag_width_m": LAG_WIDTH_M,
        "block_design_criteria": {
            "min_blocks": MIN_BLOCKS,
            "max_fold_size_ratio": MAX_FOLD_SIZE_RATIO,
        },
        RUN_CONDITIONS_KEY: {k: v for k, v in run_conditions.items() if k != "dataset_sha256"},
        "configs": collected["records"],
        # シードが1本のときの sd は NaN になる。JSON には NaN を書けないため null にする
        "summary": summary_table.astype(object)
        .where(summary_table.notna(), None)
        .to_dict(orient="records"),
        "outputs": {name: to_project_relative_string(path) for name, path in outputs.items()},
        "notes": [
            "シードは標本抽出・RF の random_state・残差の部分標本・並べ替え検定に使う。",
            (
                "緩衝帯は評価セルからのセル中心間距離が buffer_m 未満の学習セルを除く。"
                "評価側は変えない。"
            ),
            (
                "thinned_to_buffer_m が正の設定は学習量の対照: 緩衝帯なしで、その緩衝帯を"
                "かけたときと同じ fold ごとの学習セル数までランダムに間引く。"
            ),
            (
                "残差 = 観測 LST − 予測（°C）。Moran's I は二値の距離帯の重みを行標準化し、"
                "孤立点は帯ごとに除く。"
            ),
            "集計は途中結果の保存先にある、同じ実行条件の完了済み設定すべてを対象とする。",
        ],
    }
    result["provenance"] = build_provenance(
        SCRIPT_MODULE,
        input_paths=[
            PROJECT_ROOT / metadata["datasets"]["satellite_only"],
            PROJECT_ROOT / metadata["datasets"]["limited"],
            cells_path,
            evaluation_set.metadata_path,
        ],
        packages=PROVENANCE_PACKAGES,
        extra_watch_paths=DIAGNOSE_WATCH_PATHS,
    )
    result_path = output_dir / "spatial_cv_sweep_results.json"
    save_summary(result, result_path)
    print(summary_table.to_string(index=False))
    print(f"掃引結果を保存しました: {result_path}")


def main(argv: list[str] | None = None) -> None:
    """サブコマンドに応じて診断を実行する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        None
    """
    args = parse_arguments(argv)
    if args.command == "semivariogram":
        run_semivariogram_command(args)
    else:
        run_sweep_command(args)


if __name__ == "__main__":
    main()
