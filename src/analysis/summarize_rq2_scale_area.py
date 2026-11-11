"""RQ2（グリッド解像度 × 分析対象範囲）の各ランの結果を集計する。

Satellite Only・Limited の分析スクリプトが出力した results.json と fold 別指標 CSV を
読み、解像度・分析対象範囲・区画長・標本数・乱数シードの違うランを1つの比較表にまとめる。
分析そのもの（モデルの学習・SHAP の計算）は行わない。

出力（既定は ``data/output/rq2_scale_area/{観測}/``）:

- ``rq2_runs.csv``: ラン別の性能表。母数・抽出率・LST の平均と標準偏差・ブロック判定・
  ランダム分割と Spatial CV の R²・RMSE（fold 間の標準偏差つき）・Spatial CV の RMSE を
  LST の標準偏差で割った値
- ``rq2_shap_ranks.csv``: ラン別・変数別の平均絶対 SHAP、全変数の合計に対する割合、順位
- ``rq2_rank_stability_features.csv``・``rq2_rank_stability_summary.csv``: 乱数シードを
  変えた反復での変数ごとの順位の範囲と、シード42の順位との Kendall の τ
- ``rq2_scale_area_results.json``: 上の表の要約・判定基準・来歴

ランの見つけ方:
    シナリオごとの出力ディレクトリ（``SCENARIO_DIRS``）の下にある、群ごとのディレクトリ
    （``GROUP_DIR_PATTERNS``）から ``*_results.json`` を集める。解像度・範囲・区画長・
    乱数シード・標本数は、ファイル名ではなく results.json の中身から読む。出力名に
    区画長・標本数・シードが入らないため、群ごとに出力先を分けている。
    共通評価セルで回したラン（``evaluation_cells`` が空でないもの）は対象外とする。

読み方の前提:
    - 解像度をまたぐ比較の主指標は「Spatial CV の RF の RMSE ÷ フィルタ後の母数の
      LST 標準偏差」と SHAP の順位とする。集計による平滑化で LST の分散が解像度ごとに
      変わるため、°C の RMSE は同じ解像度内の範囲比較にだけ使う
    - ブロック判定の基準は ``diagnose_spatial_cv_design`` の ``MIN_BLOCKS``・
      ``MAX_FOLD_SIZE_RATIO`` を使う（Spatial CV の設計の判定と同じ値にそろえるため）
    - 都心部（``survey``）× 300m は、セル数が少なく結果が不安定なため参考値の印を付ける

実行例::

    python -m src.analysis.summarize_rq2_scale_area --observation 20220906_032358
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from scipy.stats import kendalltau

from src.analysis.diagnose_spatial_cv_design import MAX_FOLD_SIZE_RATIO, MIN_BLOCKS
from src.common.config import PROJECT_ROOT
from src.common.paths import to_project_relative_string
from src.common.summary import build_provenance, save_summary

SCRIPT_NAME = "src.analysis.summarize_rq2_scale_area"
DEFAULT_OBSERVATION = "20220906_032358"

# シナリオごとの出力ディレクトリ（出力ルート基準）
SCENARIO_DIRS: dict[str, str] = {
    "satellite_only": "satellite_only_cellbased",
    "limited": "limited",
}

# 群ごとの出力ディレクトリのパターン（シナリオの出力ディレクトリ基準。{obs} は観測）。
# main は 2,700m・シード42・既定の標本数の本体で、30m は範囲比較の通常ランを再利用する。
GROUP_DIR_PATTERNS: dict[str, tuple[str, ...]] = {
    "main": ("{obs}_area_comparison", "{obs}_rq2_scale"),
    "block13500": ("{obs}_rq2_scale_block13500",),
    "sample_matched": ("{obs}_rq2_scale_n*",),
    "seeds": ("{obs}_rq2_scale_seeds/seed*",),
}

# results.json の ``scenario`` に記録されるシナリオ名（ディレクトリとの照合に使う）
SCENARIO_LABELS: dict[str, str] = {
    "satellite_only": "Satellite Only",
    "limited": "Limited",
}
# Limited の採用構成。別の構成のランが同じディレクトリに紛れた場合に検出する
ADOPTED_LIMITED_CONFIG: dict[str, Any] = {
    "variable_set": "both",
    "building_height_mode": "mean",
    "water_index_mode": "none",
    "population_sources": ["worldpop2020"],
}

RESULTS_SUFFIX = "_results.json"
FOLDS_SUFFIX = "_spatial_cv_folds.csv"
BASELINE_SEED = 42
# 参考値として扱う組合せ（分析対象範囲, 解像度 m）
REFERENCE_ONLY_CONDITIONS: frozenset[tuple[str, int]] = frozenset({("survey", 300)})

# 来歴で監視するコード（判定基準の定数を読むスクリプト）
WATCH_PATHS = ("src/analysis/diagnose_spatial_cv_design.py",)

# ランを一意に識別する列
RUN_KEY_COLUMNS = (
    "scenario",
    "group",
    "scale_m",
    "analysis_area",
    "block_size_m",
    "random_state",
    "requested_sample_size",
)
# シードの反復で順位の安定性をまとめる単位
STABILITY_KEY_COLUMNS = ("scenario", "scale_m", "analysis_area", "block_size_m")

RUNS_FILENAME = "rq2_runs.csv"
SHAP_FILENAME = "rq2_shap_ranks.csv"
STABILITY_FEATURES_FILENAME = "rq2_rank_stability_features.csv"
STABILITY_SUMMARY_FILENAME = "rq2_rank_stability_summary.csv"
RESULTS_FILENAME = "rq2_scale_area_results.json"


@dataclass(frozen=True)
class RunFiles:
    """1ランの入力ファイルと、そのランが属するシナリオ・群。

    Attributes:
        scenario: シナリオのキー（``SCENARIO_DIRS`` のキー）。
        group: 群の名前（``GROUP_DIR_PATTERNS`` のキー）。
        results_path: results.json のパス。
        folds_path: fold 別指標 CSV のパス。
    """

    scenario: str
    group: str
    results_path: Path
    folds_path: Path


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI 引数を解釈して返す。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。
    Returns:
        解釈済みの引数。
    """
    parser = argparse.ArgumentParser(
        description="RQ2 の解像度・分析対象範囲別のランの結果を集計する。"
    )
    parser.add_argument(
        "--observation",
        default=DEFAULT_OBSERVATION,
        help="観測の識別子（YYYYMMDD_HHMMSS）。出力ディレクトリ名の接頭辞に使う。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "output",
        help="各シナリオの出力ディレクトリを含むルート。",
    )
    parser.add_argument(
        "--summary-dir",
        type=Path,
        default=None,
        help="集計結果の保存先。既定は {output-root}/rq2_scale_area/{observation}。",
    )
    return parser.parse_args(argv)


def resolve_folds_path(results_path: Path) -> Path:
    """results.json に対応する fold 別指標 CSV のパスを返す。

    Args:
        results_path: ``*_results.json`` のパス。
    Returns:
        同じディレクトリの ``*_spatial_cv_folds.csv`` のパス。
    Raises:
        ValueError: 名前が ``_results.json`` で終わらない場合。
    """
    name = results_path.name
    if not name.endswith(RESULTS_SUFFIX):
        raise ValueError(f"results.json の名前ではありません: {results_path}")
    return results_path.with_name(name[: -len(RESULTS_SUFFIX)] + FOLDS_SUFFIX)


def discover_run_files(output_root: Path, observation: str) -> list[RunFiles]:
    """群ごとの出力ディレクトリから、集計対象のランのファイルを集める。

    共通評価セルで回したラン（results.json の ``evaluation_cells`` が空でないもの）は
    除く。fold 別指標 CSV が無いランは集計できないため例外にする。

    Args:
        output_root: 各シナリオの出力ディレクトリを含むルート。
        observation: 観測の識別子。
    Returns:
        シナリオ・群・パスの順に並べたランのファイルの一覧。
    Raises:
        FileNotFoundError: fold 別指標 CSV が無いランがある場合。
    """
    run_files: list[RunFiles] = []
    for scenario, scenario_dir in SCENARIO_DIRS.items():
        scenario_root = output_root / scenario_dir
        for group, patterns in GROUP_DIR_PATTERNS.items():
            directories: set[Path] = set()
            for pattern in patterns:
                directories.update(
                    path for path in scenario_root.glob(pattern.format(obs=observation))
                )
            for directory in sorted(path for path in directories if path.is_dir()):
                for results_path in sorted(directory.glob(f"*{RESULTS_SUFFIX}")):
                    result = load_json(results_path)
                    if result.get("evaluation_cells"):
                        continue
                    folds_path = resolve_folds_path(results_path)
                    if not folds_path.is_file():
                        raise FileNotFoundError(
                            f"fold 別指標 CSV が見つかりません: {folds_path}"
                            f"（results.json: {results_path}）"
                        )
                    run_files.append(RunFiles(scenario, group, results_path, folds_path))
    return run_files


def load_json(path: Path) -> dict[str, Any]:
    """UTF-8 の JSON ファイルを読む。

    Args:
        path: JSON ファイルのパス。
    Returns:
        読み込んだ辞書。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run_config(run_files: RunFiles, result: Mapping[str, Any]) -> None:
    """results.json のシナリオと構成が、置かれたディレクトリの想定と合うかを確かめる。

    出力名には構成の一部しか入らないため、別のシナリオ・別の構成のランが同じ
    ディレクトリに紛れても、条件の重複が無ければ気づけない。集計に混ぜる前に止める。

    Args:
        run_files: ランのファイルとシナリオ・群。
        result: results.json の内容。
    Raises:
        ValueError: シナリオ名が一致しない場合、または Limited が採用構成でない場合。
    """
    expected = SCENARIO_LABELS[run_files.scenario]
    actual = result.get("scenario")
    if actual != expected:
        raise ValueError(
            f"シナリオが一致しません（想定 {expected!r}・記録 {actual!r}）: "
            f"{run_files.results_path}"
        )
    if run_files.scenario != "limited":
        return
    mismatched = {
        key: result.get(key)
        for key, value in ADOPTED_LIMITED_CONFIG.items()
        if result.get(key) != value
    }
    if mismatched:
        raise ValueError(
            f"Limited の採用構成ではないランです（{mismatched}）: {run_files.results_path}"
        )


def judge_block_design(n_blocks: int, fold_test_sizes: Sequence[int]) -> dict[str, Any]:
    """非空ブロック数と fold のテストセル数の均衡を、判定基準と照らす。

    Args:
        n_blocks: 非空ブロック数。
        fold_test_sizes: fold ごとのテストセル数。
    Returns:
        テストセル数の最小・最大・最大/最小比と、各基準・総合の判定の辞書。
    Raises:
        ValueError: fold が無い場合、またはテストセル数に0以下がある場合。
    """
    if len(fold_test_sizes) == 0:
        raise ValueError("fold のテストセル数がありません。")
    smallest = int(min(fold_test_sizes))
    largest = int(max(fold_test_sizes))
    if smallest <= 0:
        raise ValueError(f"テストセル数が0以下の fold があります（最小 {smallest}）。")
    ratio = largest / smallest
    meets_min_blocks = n_blocks >= MIN_BLOCKS
    meets_fold_ratio = ratio <= MAX_FOLD_SIZE_RATIO
    return {
        "fold_test_size_min": smallest,
        "fold_test_size_max": largest,
        "fold_test_size_ratio": ratio,
        "meets_min_blocks": meets_min_blocks,
        "meets_fold_size_ratio": meets_fold_ratio,
        "block_design_ok": meets_min_blocks and meets_fold_ratio,
    }


def summarize_run(
    run_files: RunFiles, result: Mapping[str, Any], folds: pd.DataFrame
) -> dict[str, Any]:
    """1ランの results.json と fold 別指標から、性能表の1行を作る。

    Args:
        run_files: ランのファイルとシナリオ・群。
        result: results.json の内容。
        folds: fold 別指標（``test_size`` 列を持つ）。
    Returns:
        性能表の1行（列名から値への辞書）。
    Raises:
        ValueError: fold 数が ``spatial_cv.cv_splits`` と一致しない場合、または
            フィルタ後の母数・LST の標準偏差が正でない場合。
    """
    run_parameters = result["run_parameters"]
    spatial_cv = result["spatial_cv"]
    random_split = result["random_split"]
    stages = result["filter_dropout"]["stages"]
    target_after = result["filter_dropout"]["target_distribution"]["after"]

    cv_splits = int(spatial_cv["cv_splits"])
    if len(folds) != cv_splits:
        raise ValueError(
            f"fold 数（{len(folds)}）が cv_splits（{cv_splits}）と一致しません: "
            f"{run_files.folds_path}"
        )
    population = int(stages["feature_complete"])
    lst_std = float(target_after["std"])
    if population <= 0 or lst_std <= 0:
        raise ValueError(
            f"フィルタ後の母数（{population}）または LST の標準偏差（{lst_std}）が"
            f"正ではありません: {run_files.results_path}"
        )
    scale_m = int(run_parameters["scale_m"])
    analysis_area = str(result["analysis_area"])
    n_blocks = int(spatial_cv["block_definition"]["n_blocks"])
    sample_size = int(result["sample_size"])
    linear_cv = spatial_cv["linear_regression"]
    rf_cv = spatial_cv["random_forest"]

    row: dict[str, Any] = {
        "scenario": run_files.scenario,
        "group": run_files.group,
        "scale_m": scale_m,
        "analysis_area": analysis_area,
        "block_size_m": int(spatial_cv["block_definition"]["block_size_m"]),
        "random_state": int(run_parameters["random_state"]),
        "requested_sample_size": int(run_parameters["requested_sample_size"]),
        "population": population,
        "sample_size": sample_size,
        "sampling_ratio": sample_size / population,
        "lst_mean": float(target_after["mean"]),
        "lst_std": lst_std,
        "n_features": len(result["features"]),
        "n_blocks": n_blocks,
        **judge_block_design(n_blocks, folds["test_size"].astype(int).tolist()),
        "reference_only": (analysis_area, scale_m) in REFERENCE_ONLY_CONDITIONS,
        "random_linear_r2": float(random_split["linear_regression"]["metrics"]["r2"]),
        "random_linear_rmse": float(random_split["linear_regression"]["metrics"]["rmse"]),
        "random_rf_r2": float(random_split["random_forest"]["metrics"]["r2"]),
        "random_rf_rmse": float(random_split["random_forest"]["metrics"]["rmse"]),
        "cv_linear_r2_mean": float(linear_cv["r2_mean"]),
        "cv_linear_r2_std": float(linear_cv["r2_std"]),
        "cv_linear_rmse_mean": float(linear_cv["rmse_mean"]),
        "cv_linear_rmse_std": float(linear_cv["rmse_std"]),
        "cv_rf_r2_mean": float(rf_cv["r2_mean"]),
        "cv_rf_r2_std": float(rf_cv["r2_std"]),
        "cv_rf_rmse_mean": float(rf_cv["rmse_mean"]),
        "cv_rf_rmse_std": float(rf_cv["rmse_std"]),
        "cv_linear_rmse_over_lst_std": float(linear_cv["rmse_mean"]) / lst_std,
        "cv_rf_rmse_over_lst_std": float(rf_cv["rmse_mean"]) / lst_std,
        "results_json": to_project_relative_string(run_files.results_path),
    }
    return row


def rank_shap(mean_abs_shap: Mapping[str, float]) -> pd.DataFrame:
    """平均絶対 SHAP から、変数ごとの割合と順位を求める。

    順位は値の大きい順に1から振り、同値は小さい方の順位にそろえる（``method="min"``）。

    Args:
        mean_abs_shap: 変数名から平均絶対 SHAP への辞書。
    Returns:
        ``feature``・``mean_abs_shap``・``shap_share``・``shap_rank`` 列のデータフレーム
        （順位の昇順）。
    Raises:
        ValueError: 変数が無い場合、負の値がある場合、または合計が0の場合。
    """
    if not mean_abs_shap:
        raise ValueError("平均絶対 SHAP の変数がありません。")
    frame = pd.DataFrame(
        {"feature": list(mean_abs_shap.keys()), "mean_abs_shap": list(mean_abs_shap.values())}
    )
    frame["mean_abs_shap"] = frame["mean_abs_shap"].astype(float)
    if (frame["mean_abs_shap"] < 0).any():
        raise ValueError("平均絶対 SHAP に負の値があります。")
    total = float(frame["mean_abs_shap"].sum())
    if total <= 0:
        raise ValueError("平均絶対 SHAP の合計が0です。")
    frame["shap_share"] = frame["mean_abs_shap"] / total
    frame["shap_rank"] = frame["mean_abs_shap"].rank(ascending=False, method="min").astype(int)
    return frame.sort_values(["shap_rank", "feature"]).reset_index(drop=True)


def build_tables(run_files: Sequence[RunFiles]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """全ランの性能表と SHAP の順位表を作る。

    Args:
        run_files: 集計対象のランのファイル。
    Returns:
        性能表と SHAP の順位表（いずれも ``RUN_KEY_COLUMNS`` をキー列に持つ）。
    Raises:
        ValueError: ランが無い場合、キー列が重複するランがある場合、またはシナリオ・
            構成がディレクトリの想定と合わないランがある場合。
    """
    if not run_files:
        raise ValueError("集計対象のランが見つかりません。")
    run_rows: list[dict[str, Any]] = []
    shap_frames: list[pd.DataFrame] = []
    for files in run_files:
        result = load_json(files.results_path)
        validate_run_config(files, result)
        folds = pd.read_csv(files.folds_path)
        row = summarize_run(files, result, folds)
        run_rows.append(row)
        shap_frame = rank_shap(result["shap"]["mean_abs_shap"])
        for column in RUN_KEY_COLUMNS:
            shap_frame.insert(RUN_KEY_COLUMNS.index(column), column, row[column])
        shap_frames.append(shap_frame)
    runs = pd.DataFrame(run_rows)
    duplicated = runs.duplicated(list(RUN_KEY_COLUMNS), keep=False)
    if duplicated.any():
        listed = runs.loc[duplicated, ["results_json"]].to_string(index=False)
        raise ValueError(f"条件が重複するランがあります:\n{listed}")
    runs = runs.sort_values(list(RUN_KEY_COLUMNS)).reset_index(drop=True)
    shap_ranks = (
        pd.concat(shap_frames, ignore_index=True)
        .sort_values([*RUN_KEY_COLUMNS, "shap_rank", "feature"])
        .reset_index(drop=True)
    )
    return runs, shap_ranks


def select_seed_runs(runs: pd.DataFrame, shap_ranks: pd.DataFrame) -> pd.DataFrame:
    """順位の安定性に使うランの SHAP の行を選ぶ。

    シードの反復（``seeds`` 群）と、同じ条件の本体（``main`` 群のシード42）を対象とする。
    本体と標本数の指定がそろうものに限る（標本数を変えた群は混ぜない）。

    Args:
        runs: 性能表。
        shap_ranks: SHAP の順位表。
    Returns:
        対象ランの SHAP の行。
    """
    seed_runs = runs[runs["group"] == "seeds"]
    if seed_runs.empty:
        return shap_ranks.iloc[0:0]
    conditions = seed_runs[[*STABILITY_KEY_COLUMNS, "requested_sample_size"]].drop_duplicates()
    baseline = runs[(runs["group"] == "main") & (runs["random_state"] == BASELINE_SEED)].merge(
        conditions, on=[*STABILITY_KEY_COLUMNS, "requested_sample_size"]
    )
    selected = pd.concat([baseline, seed_runs], ignore_index=True)
    return shap_ranks.merge(selected[list(RUN_KEY_COLUMNS)], on=list(RUN_KEY_COLUMNS))


def summarize_rank_stability(
    runs: pd.DataFrame, shap_ranks: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """シードを変えた反復で、SHAP の順位がどれだけ入れ替わるかをまとめる。

    条件（``STABILITY_KEY_COLUMNS``）ごとに、変数別の順位の最小・最大・範囲と割合の平均、
    シードごとのシード42との Kendall の τ（平均絶対 SHAP の並びの一致度。τ-b）を求める。

    Args:
        runs: 性能表。
        shap_ranks: SHAP の順位表。
    Returns:
        変数別の表と条件別の要約表。シードの反復が無ければ空のデータフレーム。
    Raises:
        ValueError: 条件にシード42のランが無い場合、またはシード間で変数がそろわない場合。
    """
    selected = select_seed_runs(runs, shap_ranks)
    if selected.empty:
        return pd.DataFrame(), pd.DataFrame()
    feature_rows: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    for key, group in selected.groupby(list(STABILITY_KEY_COLUMNS), sort=True):
        condition = dict(zip(STABILITY_KEY_COLUMNS, key, strict=True))
        shap_wide = group.pivot(index="feature", columns="random_state", values="mean_abs_shap")
        if BASELINE_SEED not in shap_wide.columns:
            raise ValueError(f"シード{BASELINE_SEED}のランがありません: {condition}")
        if shap_wide.isna().any().any():
            raise ValueError(f"シード間で変数がそろっていません: {condition}")
        rank_wide = group.pivot(index="feature", columns="random_state", values="shap_rank")
        share_wide = group.pivot(index="feature", columns="random_state", values="shap_share")
        features = pd.DataFrame(
            {
                "feature": rank_wide.index,
                "rank_seed42": rank_wide[BASELINE_SEED].astype(int).to_numpy(),
                "rank_min": rank_wide.min(axis=1).astype(int).to_numpy(),
                "rank_max": rank_wide.max(axis=1).astype(int).to_numpy(),
                "share_mean": share_wide.mean(axis=1).to_numpy(),
                "share_min": share_wide.min(axis=1).to_numpy(),
                "share_max": share_wide.max(axis=1).to_numpy(),
            }
        )
        features["rank_range"] = features["rank_max"] - features["rank_min"]
        for column, value in reversed(condition.items()):
            features.insert(0, column, value)
        feature_rows.append(features.sort_values(["rank_seed42", "feature"]))

        baseline_values = shap_wide[BASELINE_SEED]
        baseline_top = rank_wide.index[rank_wide[BASELINE_SEED] == 1].tolist()
        taus: list[float] = []
        top1_same = 0
        other_seeds = [seed for seed in shap_wide.columns if seed != BASELINE_SEED]
        for seed in other_seeds:
            tau, _ = kendalltau(baseline_values.to_numpy(), shap_wide[seed].to_numpy())
            taus.append(float(tau))
            seed_top = rank_wide.index[rank_wide[seed] == 1].tolist()
            top1_same += int(seed_top == baseline_top)
        condition_runs = runs.merge(
            group[list(RUN_KEY_COLUMNS)].drop_duplicates(), on=list(RUN_KEY_COLUMNS)
        )
        tau_series = pd.Series(taus, dtype=float)
        summary_rows.append(
            {
                **condition,
                "n_seeds": int(shap_wide.shape[1]),
                "n_features": int(shap_wide.shape[0]),
                "top1_seed42": "|".join(baseline_top),
                "top1_same_count": top1_same,
                "kendall_tau_min": float(tau_series.min()) if taus else None,
                "kendall_tau_mean": float(tau_series.mean()) if taus else None,
                "max_rank_range": int(features["rank_range"].max()),
                "cv_rf_rmse_mean_over_seeds": float(condition_runs["cv_rf_rmse_mean"].mean()),
                "cv_rf_rmse_sd_over_seeds": float(condition_runs["cv_rf_rmse_mean"].std(ddof=1))
                if len(condition_runs) > 1
                else None,
                "cv_rf_r2_mean_over_seeds": float(condition_runs["cv_rf_r2_mean"].mean()),
                "cv_rf_r2_sd_over_seeds": float(condition_runs["cv_rf_r2_mean"].std(ddof=1))
                if len(condition_runs) > 1
                else None,
            }
        )
    return pd.concat(feature_rows, ignore_index=True), pd.DataFrame(summary_rows)


def to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """データフレームを JSON に書ける辞書の並びへ変換する。

    欠損（``NaN``）は ``None`` に置き換える（``save_summary`` は ``NaN`` を拒むため）。

    Args:
        frame: 変換するデータフレーム。
    Returns:
        行ごとの辞書の並び。
    """
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def build_summary(
    runs: pd.DataFrame,
    stability_summary: pd.DataFrame,
    observation: str,
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """集計結果 JSON の本体（来歴を除く）を組み立てる。

    Args:
        runs: 性能表。
        stability_summary: 順位の安定性の条件別の要約表。
        observation: 観測の識別子。
        output_paths: 出力した CSV の種類からパスへの辞書。
    Returns:
        集計結果の辞書。
    """
    excluded = runs.loc[~runs["block_design_ok"], list(RUN_KEY_COLUMNS)]
    return {
        "observation": observation,
        "n_runs": int(len(runs)),
        "runs_by_group": {
            str(group): int(count) for group, count in runs["group"].value_counts().items()
        },
        "criteria": {
            "min_blocks": MIN_BLOCKS,
            "max_fold_size_ratio": MAX_FOLD_SIZE_RATIO,
            "reference_only_conditions": [
                {"analysis_area": area, "scale_m": scale}
                for area, scale in sorted(REFERENCE_ONLY_CONDITIONS)
            ],
            "baseline_seed": BASELINE_SEED,
            "note": (
                "ブロック判定は非空ブロック数が min_blocks 以上、かつ fold のテストセル数の"
                "最大/最小が max_fold_size_ratio 以下のとき成立。満たさないランは評価対象から外す。"
                "解像度をまたぐ比較は cv_rf_rmse_over_lst_std（Spatial CV の RF の RMSE ÷ "
                "フィルタ後の母数の LST 標準偏差）と SHAP の順位を主とする。"
            ),
        },
        "block_design_failed_runs": to_records(excluded),
        "rank_stability": to_records(stability_summary),
        "outputs": {key: to_project_relative_string(path) for key, path in output_paths.items()},
    }


def main(argv: Sequence[str] | None = None) -> None:
    """ランを集め、表と集計結果 JSON を保存する。

    Args:
        argv: CLI 引数列。``None`` の場合は ``sys.argv`` を使う。
    """
    args = parse_arguments(argv)
    output_root: Path = args.output_root
    summary_dir: Path = args.summary_dir or output_root / "rq2_scale_area" / args.observation

    run_files = discover_run_files(output_root, args.observation)
    print(f"集計対象のラン: {len(run_files)} 本")
    runs, shap_ranks = build_tables(run_files)
    stability_features, stability_summary = summarize_rank_stability(runs, shap_ranks)

    summary_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "runs_csv": summary_dir / RUNS_FILENAME,
        "shap_ranks_csv": summary_dir / SHAP_FILENAME,
        "rank_stability_features_csv": summary_dir / STABILITY_FEATURES_FILENAME,
        "rank_stability_summary_csv": summary_dir / STABILITY_SUMMARY_FILENAME,
    }
    runs.to_csv(output_paths["runs_csv"], index=False, encoding="utf-8")
    shap_ranks.to_csv(output_paths["shap_ranks_csv"], index=False, encoding="utf-8")
    stability_features.to_csv(
        output_paths["rank_stability_features_csv"], index=False, encoding="utf-8"
    )
    stability_summary.to_csv(
        output_paths["rank_stability_summary_csv"], index=False, encoding="utf-8"
    )

    summary = build_summary(runs, stability_summary, args.observation, output_paths)
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    input_paths = [path for files in run_files for path in (files.results_path, files.folds_path)]
    summary["provenance"] = build_provenance(
        SCRIPT_NAME, input_paths=input_paths, extra_watch_paths=WATCH_PATHS
    )
    results_path = summary_dir / RESULTS_FILENAME
    save_summary(summary, results_path)
    failed = summary["block_design_failed_runs"]
    print(f"ブロック判定を満たさないラン: {len(failed)} 本")
    print(f"集計結果を保存しました: {results_path}")


if __name__ == "__main__":
    main()
