"""観測の異なる分析結果を、相対的な量で1つの比較表にまとめる。

Satellite Only・Limited の分析スクリプトが出力した results.json を観測・シナリオごとに読み、
観測をまたいで比べてよい量（R²、誤差 ÷ LST の標準偏差、変数重要度の順位、
SHAP ÷ LST の標準偏差）をそろえて書き出す。分析そのもの（モデルの学習・SHAP の計算）は行わない。

出力（既定は ``data/output/observation_comparison/``）:

- ``observation_metrics.csv``: 観測 × シナリオ別の性能表。最終母数・LST の平均と標準偏差・
  ランダム分割と Spatial CV の R²・RMSE・MAE と、RMSE・MAE を LST の標準偏差で割った値
- ``observation_feature_ranks.csv``: 観測 × シナリオ × 変数別の平均絶対 SHAP・SHAP ÷ LST の
  標準偏差・SHAP の割合と順位・Permutation 重要度と順位
- ``observation_feature_ranks_wide.csv``: 上の表をシナリオ × 変数の行・観測の列に並べ替えたもの
- ``observation_scenario_diff.csv``: 観測ごとの Limited − Satellite Only の差（参考値）
- ``observation_comparison_results.json``: 上の表・比べる量の約束・来歴

読み方の前提:
    - 観測が違うと LST の分布が違うため、LST の絶対値と °C の誤差・SHAP は観測間で比べない。
      °C の値は転記の確認のために出力に残す
    - シナリオ間の差は、母数（最終母数のセル）がシナリオで異なるため参考値とする
    - 次のいずれかに当てはまるランがあれば集計しない: 観測の識別子が ``YYYYMMDD_HHMMSS`` の
      形式でない、または入力データセットのファイル名の識別子と一致しない（観測の取り違え）／
      シナリオ名の不一致／全域以外／共通評価セルのラン／Limited が採用構成でない／実行条件
      （``run_parameters``・LST の有効率の閾値・ブロック長・分割数）が全ランで一致しない／
      同じシナリオの中で説明変数の集合が観測間で一致しない

実行例::

    python -m src.analysis.compare_observations
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.analysis.summarize_rq2_scale_area import (
    ADOPTED_LIMITED_CONFIG,
    SCENARIO_LABELS,
    load_json,
    rank_shap,
    to_records,
)
from src.common.config import PRIMARY_OBSERVATION_ID, PROJECT_ROOT
from src.common.paths import to_project_relative_string
from src.common.summary import build_provenance, save_summary

SCRIPT_NAME = "src.analysis.compare_observations"

# 比較する分析対象範囲（全域）
EXPECTED_ANALYSIS_AREA = "roi"
# 観測の識別子の形式（YYYYMMDD_HHMMSS）。部分一致の照合で途中までの識別子が通らないようにする
OBSERVATION_PATTERN = re.compile(r"\d{8}_\d{6}")
METRICS_FILENAME = "observation_metrics.csv"
FEATURES_FILENAME = "observation_feature_ranks.csv"
FEATURES_WIDE_FILENAME = "observation_feature_ranks_wide.csv"
SCENARIO_DIFF_FILENAME = "observation_scenario_diff.csv"
RESULTS_FILENAME = "observation_comparison_results.json"

# 横持ちの表に観測ごとに並べる列
WIDE_VALUE_COLUMNS = ("shap_rank", "shap_over_lst_std", "permutation_rank")
# シナリオ間の差を取る列（いずれも観測をまたいで比べてよい相対的な量）
SCENARIO_DIFF_COLUMNS = (
    "population",
    "random_rf_r2",
    "random_linear_r2",
    "cv_rf_r2_mean",
    "cv_linear_r2_mean",
    "cv_rf_rmse_over_lst_std",
    "cv_linear_rmse_over_lst_std",
)


@dataclass(frozen=True)
class RunSpec:
    """比較に使う1ランの指定。

    Attributes:
        observation: 観測の識別子（``YYYYMMDD_HHMMSS``）。
        scenario: シナリオのキー（``SCENARIO_LABELS`` のキー）。
        results_path: results.json のパス（プロジェクトルート基準の相対パス可）。
    """

    observation: str
    scenario: str
    results_path: Path


# 既定の比較対象（主採用・旧採用の新世代の全域ラン・比較用の観測）。
# 旧採用の Limited は、ラン13と数値が一致し、クリーンなコミットで生成した全域ランを使う。
DEFAULT_RUNS: tuple[RunSpec, ...] = (
    RunSpec(
        PRIMARY_OBSERVATION_ID,
        "satellite_only",
        Path(
            f"data/output/satellite_only_cellbased/{PRIMARY_OBSERVATION_ID}/"
            f"dataset_satellite_only_{PRIMARY_OBSERVATION_ID}_hanoi_30m_results.json"
        ),
    ),
    RunSpec(
        PRIMARY_OBSERVATION_ID,
        "limited",
        Path(
            f"data/output/limited/{PRIMARY_OBSERVATION_ID}/"
            f"dataset_limited_{PRIMARY_OBSERVATION_ID}_hanoi_30m_both_bh_mean_wi_none_results.json"
        ),
    ),
    RunSpec(
        "20230707_032305",
        "satellite_only",
        Path(
            "data/output/satellite_only_cellbased/20230707_032305_area_comparison/"
            "dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m_results.json"
        ),
    ),
    RunSpec(
        "20230707_032305",
        "limited",
        Path(
            "data/output/limited/20230707_032305_area_comparison/"
            "dataset_limited_masksurvey_20230707_032305_hanoi_30m_both_bh_mean_wi_none_results.json"
        ),
    ),
    RunSpec(
        "20241130_032336",
        "satellite_only",
        Path(
            "data/output/satellite_only_cellbased/20241130_032336/"
            "dataset_satellite_only_20241130_032336_hanoi_30m_results.json"
        ),
    ),
    RunSpec(
        "20241130_032336",
        "limited",
        Path(
            "data/output/limited/20241130_032336/"
            "dataset_limited_20241130_032336_hanoi_30m_both_bh_mean_wi_none_results.json"
        ),
    ),
)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI 引数を解釈して返す。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。
    Returns:
        解釈済みの引数。
    """
    parser = argparse.ArgumentParser(
        description="観測の異なる分析結果を、相対的な量で比較表にまとめる。"
    )
    parser.add_argument(
        "--run",
        nargs=3,
        action="append",
        metavar=("OBSERVATION", "SCENARIO", "RESULTS_JSON"),
        default=None,
        help="比較するラン（観測・シナリオ・results.json）。繰り返し指定する。"
        " 省略時は DEFAULT_RUNS（3観測 × 2シナリオ）を使う。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "output" / "observation_comparison",
        help="集計結果の保存先。",
    )
    return parser.parse_args(argv)


def build_run_specs(run_args: Sequence[Sequence[str]] | None) -> list[RunSpec]:
    """CLI の ``--run`` 指定からランの一覧を作る。

    相対パスはプロジェクトルート基準で解決する。

    Args:
        run_args: ``--run`` の値の並び（観測・シナリオ・パス）。``None`` なら既定を使う。
    Returns:
        ランの一覧。
    Raises:
        ValueError: 観測の識別子が ``YYYYMMDD_HHMMSS`` の形式でない場合、シナリオ名が
            ``SCENARIO_LABELS`` に無い場合、または観測とシナリオの組が重複する場合。
    """
    if run_args is None:
        specs = list(DEFAULT_RUNS)
    else:
        specs = [RunSpec(obs, scenario, Path(path)) for obs, scenario, path in run_args]
    resolved: list[RunSpec] = []
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        if not OBSERVATION_PATTERN.fullmatch(spec.observation):
            raise ValueError(
                f"観測の識別子は YYYYMMDD_HHMMSS の形式で指定してください: {spec.observation!r}"
            )
        if spec.scenario not in SCENARIO_LABELS:
            raise ValueError(
                f"未知のシナリオです: {spec.scenario}（{', '.join(SCENARIO_LABELS)} のいずれか）"
            )
        key = (spec.observation, spec.scenario)
        if key in seen:
            raise ValueError(f"観測とシナリオの組が重複しています: {key}")
        seen.add(key)
        path = spec.results_path
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved.append(RunSpec(spec.observation, spec.scenario, path))
    return resolved


def validate_run(spec: RunSpec, result: Mapping[str, Any]) -> None:
    """1ランが比較の前提（観測・シナリオ・全域・採用構成）を満たすかを確かめる。

    観測は、results.json に記録された入力データセットのファイル名から観測の識別子を
    取り出して照合する（データセット名は ``dataset_{シナリオ}[_masksurvey]_{観測}_...`` と
    観測日時を含む命名のため）。親ディレクトリ名は見ない（ディレクトリにだけ別の観測の
    識別子がある場合に誤って一致させないため）。

    Args:
        spec: ランの指定。
        result: results.json の内容。
    Raises:
        ValueError: 入力データセットのファイル名の観測の識別子が指定と一致しない場合、
            シナリオ名が指定と合わない場合、分析対象範囲が全域でない場合、共通評価セルで
            回したランの場合、または Limited が採用構成でない場合。
    """
    dataset_path = str(result.get("dataset_path", ""))
    dataset_name = dataset_path.replace("\\", "/").rsplit("/", 1)[-1]
    found = OBSERVATION_PATTERN.findall(dataset_name)
    if found != [spec.observation]:
        raise ValueError(
            f"入力データセットのファイル名の観測の識別子（{', '.join(found) or 'なし'}）が"
            f"指定（{spec.observation}）と一致しません: {dataset_path}（{spec.results_path}）"
        )
    expected_label = SCENARIO_LABELS[spec.scenario]
    if result.get("scenario") != expected_label:
        raise ValueError(
            f"シナリオが指定（{expected_label}）と合いません: "
            f"{result.get('scenario')}（{spec.results_path}）"
        )
    if result.get("analysis_area") != EXPECTED_ANALYSIS_AREA:
        raise ValueError(
            f"分析対象範囲が全域（{EXPECTED_ANALYSIS_AREA}）ではありません: "
            f"{result.get('analysis_area')}（{spec.results_path}）"
        )
    if result.get("evaluation_cells"):
        raise ValueError(f"共通評価セルで回したランは対象外です: {spec.results_path}")
    if spec.scenario == "limited":
        for key, expected in ADOPTED_LIMITED_CONFIG.items():
            if result.get(key) != expected:
                raise ValueError(
                    f"Limited が採用構成ではありません（{key}: {result.get(key)} ≠ "
                    f"{expected}）: {spec.results_path}"
                )


def extract_shared_conditions(result: Mapping[str, Any]) -> dict[str, Any]:
    """全ランで一致を求める実行条件を取り出す。

    Args:
        result: results.json の内容。
    Returns:
        ``run_parameters`` の全項目、LST の有効率の閾値、Spatial CV のブロック長・分割数。
        閾値は ``run_parameters`` ではなく結果のトップレベルに記録されているため、
        別に取り出す（閾値が違うと母数と R² が変わるため）。
    """
    spatial_cv = result["spatial_cv"]
    conditions = dict(result["run_parameters"])
    conditions["lst_valid_ratio_threshold"] = float(result["lst_valid_ratio_threshold"])
    conditions["block_size_m"] = int(spatial_cv["block_definition"]["block_size_m"])
    conditions["cv_splits"] = int(spatial_cv["cv_splits"])
    return conditions


def validate_shared_conditions(
    specs: Sequence[RunSpec], results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """全ランの実行条件が一致することを確かめる。

    Args:
        specs: ランの指定。
        results: 各ランの results.json の内容（``specs`` と同じ順）。
    Returns:
        一致した実行条件。
    Raises:
        ValueError: ランが無い場合、または実行条件が一致しないランがある場合。
    """
    if not results:
        raise ValueError("比較するランがありません。")
    baseline = extract_shared_conditions(results[0])
    for spec, result in zip(specs[1:], results[1:], strict=True):
        conditions = extract_shared_conditions(result)
        if conditions != baseline:
            differing = sorted(
                key
                for key in set(baseline) | set(conditions)
                if baseline.get(key) != conditions.get(key)
            )
            raise ValueError(
                f"実行条件が先頭のラン（{specs[0].results_path}）と一致しません"
                f"（{', '.join(differing)}）: {spec.results_path}"
            )
    return baseline


def summarize_metrics(spec: RunSpec, result: Mapping[str, Any]) -> dict[str, Any]:
    """1ランの results.json から、性能表の1行を作る。

    誤差は最終母数（``feature_complete``）の LST の標準偏差で割る。

    Args:
        spec: ランの指定。
        result: results.json の内容。
    Returns:
        性能表の1行（列名から値への辞書）。
    Raises:
        ValueError: 最終母数または LST の標準偏差が正でない場合。
    """
    stages = result["filter_dropout"]["stages"]
    target_after = result["filter_dropout"]["target_distribution"]["after"]
    population = int(stages["feature_complete"])
    lst_std = float(target_after["std"])
    if population <= 0 or lst_std <= 0:
        raise ValueError(
            f"最終母数（{population}）または LST の標準偏差（{lst_std}）が正ではありません: "
            f"{spec.results_path}"
        )
    random_split = result["random_split"]
    spatial_cv = result["spatial_cv"]
    git = result.get("provenance", {}).get("git", {})

    row: dict[str, Any] = {
        "observation": spec.observation,
        "scenario": spec.scenario,
        "population": population,
        "sample_size": int(result["sample_size"]),
        "lst_mean": float(target_after["mean"]),
        "lst_std": lst_std,
        "n_features": len(result["features"]),
        "n_blocks": int(spatial_cv["block_definition"]["n_blocks"]),
    }
    for model_key, model_name in (("random_forest", "rf"), ("linear_regression", "linear")):
        metrics = random_split[model_key]["metrics"]
        cv = spatial_cv[model_key]
        row[f"random_{model_name}_r2"] = float(metrics["r2"])
        row[f"random_{model_name}_rmse"] = float(metrics["rmse"])
        row[f"random_{model_name}_mae"] = float(metrics["mae"])
        row[f"random_{model_name}_rmse_over_lst_std"] = float(metrics["rmse"]) / lst_std
        row[f"cv_{model_name}_r2_mean"] = float(cv["r2_mean"])
        row[f"cv_{model_name}_r2_std"] = float(cv["r2_std"])
        row[f"cv_{model_name}_rmse_mean"] = float(cv["rmse_mean"])
        row[f"cv_{model_name}_mae_mean"] = float(cv["mae_mean"])
        row[f"cv_{model_name}_rmse_over_lst_std"] = float(cv["rmse_mean"]) / lst_std
        row[f"cv_{model_name}_mae_over_lst_std"] = float(cv["mae_mean"]) / lst_std
    row["git_commit"] = git.get("commit")
    row["git_dirty"] = git.get("dirty")
    row["results_json"] = to_project_relative_string(spec.results_path)
    return row


def rank_features(result: Mapping[str, Any], lst_std: float) -> pd.DataFrame:
    """1ランの変数別の SHAP と Permutation 重要度を、順位つきでまとめる。

    順位はいずれも値の大きい順に1から振り、同値は小さい方の順位にそろえる。
    Permutation 重要度は負になりうるが、そのまま順位を付ける。

    Args:
        result: results.json の内容。
        lst_std: 最終母数の LST の標準偏差（°C）。
    Returns:
        ``feature``・``mean_abs_shap``・``shap_over_lst_std``・``shap_share``・``shap_rank``・
        ``permutation_importance``・``permutation_rank`` 列のデータフレーム（SHAP の順位の昇順）。
    Raises:
        ValueError: SHAP と Permutation 重要度の変数がそろわない場合。
    """
    shap_frame = rank_shap(result["shap"]["mean_abs_shap"])
    permutation = result["random_split"]["random_forest"]["permutation_importance"]
    if set(permutation) != set(shap_frame["feature"]):
        raise ValueError("SHAP と Permutation 重要度の変数がそろっていません。")
    shap_frame["shap_over_lst_std"] = shap_frame["mean_abs_shap"] / lst_std
    shap_frame["permutation_importance"] = shap_frame["feature"].map(permutation).astype(float)
    shap_frame["permutation_rank"] = (
        shap_frame["permutation_importance"].rank(ascending=False, method="min").astype(int)
    )
    columns = [
        "feature",
        "mean_abs_shap",
        "shap_over_lst_std",
        "shap_share",
        "shap_rank",
        "permutation_importance",
        "permutation_rank",
    ]
    return shap_frame[columns]


def validate_feature_sets(specs: Sequence[RunSpec], results: Sequence[Mapping[str, Any]]) -> None:
    """同じシナリオの中で、観測をまたいで説明変数の集合が一致することを確かめる。

    分散0の列の除外は観測ごとに決まるため、変数の数が観測で変わりうる。変数の数が
    違うランどうしの順位は並べて比べられないため、集計の前に止める。

    Args:
        specs: ランの指定。
        results: 各ランの results.json の内容（``specs`` と同じ順）。
    Raises:
        ValueError: 同じシナリオで説明変数の集合が先頭のランと一致しないランがある場合。
    """
    baselines: dict[str, tuple[RunSpec, set[str]]] = {}
    for spec, result in zip(specs, results, strict=True):
        features = set(result["features"])
        if spec.scenario not in baselines:
            baselines[spec.scenario] = (spec, features)
            continue
        base_spec, base_features = baselines[spec.scenario]
        if features != base_features:
            differing = sorted(features ^ base_features)
            raise ValueError(
                f"{spec.scenario} の説明変数が {base_spec.observation} と一致しません"
                f"（{', '.join(differing)}）: {spec.results_path}"
            )


def build_tables(
    specs: Sequence[RunSpec],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """全ランの性能表・変数別の順位表と、一致を確かめた実行条件を作る。

    Args:
        specs: ランの指定（パスは解決済み）。
    Returns:
        性能表、変数別の順位表、実行条件。
    Raises:
        ValueError: 前提を満たさないランがある場合、実行条件が一致しない場合、または
            同じシナリオで説明変数の集合が観測間で一致しない場合。
    """
    results = [load_json(spec.results_path) for spec in specs]
    for spec, result in zip(specs, results, strict=True):
        validate_run(spec, result)
    shared_conditions = validate_shared_conditions(specs, results)
    validate_feature_sets(specs, results)

    metric_rows: list[dict[str, Any]] = []
    feature_frames: list[pd.DataFrame] = []
    for spec, result in zip(specs, results, strict=True):
        row = summarize_metrics(spec, result)
        metric_rows.append(row)
        features = rank_features(result, row["lst_std"])
        features.insert(0, "scenario", spec.scenario)
        features.insert(0, "observation", spec.observation)
        feature_frames.append(features)
    metrics = pd.DataFrame(metric_rows)
    feature_ranks = pd.concat(feature_frames, ignore_index=True)
    return metrics, feature_ranks, shared_conditions


def widen_feature_ranks(feature_ranks: pd.DataFrame, observations: Sequence[str]) -> pd.DataFrame:
    """変数別の順位表を、シナリオ × 変数の行・観測の列に並べ替える。

    列名は ``{値の列}_{観測}``。ある観測に無い変数は欠損になる。

    Args:
        feature_ranks: 変数別の順位表。
        observations: 列に並べる観測の順。
    Returns:
        横持ちの表（シナリオ・先頭の観測の SHAP の順位・変数名の順）。
    """
    wide = feature_ranks.pivot(
        index=["scenario", "feature"], columns="observation", values=list(WIDE_VALUE_COLUMNS)
    )
    wide.columns = [f"{value}_{observation}" for value, observation in wide.columns]
    ordered = [f"{value}_{obs}" for value in WIDE_VALUE_COLUMNS for obs in observations]
    wide = wide.reindex(columns=ordered).reset_index()
    # 欠損を含みうるため、順位の列は欠損を許す整数型にする（CSV で 1.0 と出さない）
    rank_columns = [column for column in ordered if "_rank_" in column]
    wide[rank_columns] = wide[rank_columns].astype("Int64")
    sort_key = f"shap_rank_{observations[0]}"
    return wide.sort_values(["scenario", sort_key, "feature"], na_position="last").reset_index(
        drop=True
    )


def build_scenario_diff(metrics: pd.DataFrame) -> pd.DataFrame:
    """観測ごとに Limited − Satellite Only の差を求める（参考値）。

    両シナリオがそろう観測だけを対象とする。

    Args:
        metrics: 性能表。
    Returns:
        ``observation`` と ``SCENARIO_DIFF_COLUMNS`` の差の列を持つデータフレーム。
    """
    indexed = metrics.set_index(["observation", "scenario"])
    rows: list[dict[str, Any]] = []
    for observation in metrics["observation"].drop_duplicates():
        if (observation, "limited") not in indexed.index or (
            observation,
            "satellite_only",
        ) not in indexed.index:
            continue
        limited = indexed.loc[(observation, "limited")]
        satellite = indexed.loc[(observation, "satellite_only")]
        row: dict[str, Any] = {"observation": observation}
        for column in SCENARIO_DIFF_COLUMNS:
            row[f"{column}_limited_minus_satellite_only"] = limited[column] - satellite[column]
        rows.append(row)
    return pd.DataFrame(rows)


def build_summary(
    metrics: pd.DataFrame,
    scenario_diff: pd.DataFrame,
    shared_conditions: Mapping[str, Any],
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """集計結果 JSON の本体（来歴を除く）を組み立てる。

    Args:
        metrics: 性能表。
        scenario_diff: シナリオ間の差の表。
        shared_conditions: 全ランで一致した実行条件。
        output_paths: 出力した CSV の種類からパスへの辞書。
    Returns:
        集計結果の辞書。
    """
    return {
        "observations": metrics["observation"].drop_duplicates().tolist(),
        "n_runs": int(len(metrics)),
        "shared_conditions": dict(shared_conditions),
        "analysis_area": EXPECTED_ANALYSIS_AREA,
        "limited_config": dict(ADOPTED_LIMITED_CONFIG),
        "comparison_rules": {
            "compare": [
                "R²（ランダム分割・Spatial CV）",
                "RMSE・MAE ÷ 最終母数の LST の標準偏差",
                "SHAP・Permutation 重要度の順位",
                "平均絶対 SHAP ÷ 最終母数の LST の標準偏差",
            ],
            "do_not_compare": [
                "LST の絶対値（平均・標準偏差）",
                "°C の RMSE・MAE・平均絶対 SHAP",
            ],
            "note": (
                "観測が違うと LST の分布が違うため、°C の値は観測間で比べない"
                "（転記の確認用に残す）。シナリオ間の差は最終母数がシナリオで異なるため"
                "参考値とする。"
            ),
        },
        "metrics": to_records(metrics),
        "scenario_diff": to_records(scenario_diff),
        "outputs": {key: to_project_relative_string(path) for key, path in output_paths.items()},
    }


def main(argv: Sequence[str] | None = None) -> None:
    """ランを読み、表と集計結果 JSON を保存する。

    Args:
        argv: CLI 引数列。``None`` の場合は ``sys.argv`` を使う。
    """
    args = parse_arguments(argv)
    specs = build_run_specs(args.run)
    output_dir: Path = args.output_dir
    print(f"比較するラン: {len(specs)} 本")
    metrics, feature_ranks, shared_conditions = build_tables(specs)
    observations = metrics["observation"].drop_duplicates().tolist()
    feature_wide = widen_feature_ranks(feature_ranks, observations)
    scenario_diff = build_scenario_diff(metrics)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "metrics_csv": output_dir / METRICS_FILENAME,
        "feature_ranks_csv": output_dir / FEATURES_FILENAME,
        "feature_ranks_wide_csv": output_dir / FEATURES_WIDE_FILENAME,
        "scenario_diff_csv": output_dir / SCENARIO_DIFF_FILENAME,
    }
    metrics.to_csv(output_paths["metrics_csv"], index=False, encoding="utf-8")
    feature_ranks.to_csv(output_paths["feature_ranks_csv"], index=False, encoding="utf-8")
    feature_wide.to_csv(output_paths["feature_ranks_wide_csv"], index=False, encoding="utf-8")
    scenario_diff.to_csv(output_paths["scenario_diff_csv"], index=False, encoding="utf-8")

    summary = build_summary(metrics, scenario_diff, shared_conditions, output_paths)
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    summary["provenance"] = build_provenance(
        SCRIPT_NAME,
        input_paths=[spec.results_path for spec in specs],
        extra_watch_paths=("src/analysis/summarize_rq2_scale_area.py",),
    )
    results_path = output_dir / RESULTS_FILENAME
    save_summary(summary, results_path)
    print(f"集計結果を保存しました: {results_path}")


if __name__ == "__main__":
    main()
