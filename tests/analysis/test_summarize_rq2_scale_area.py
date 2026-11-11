"""src/analysis/summarize_rq2_scale_area.py（RQ2 の解像度・範囲別の集計）のテスト。

群ごとの出力ディレクトリに合成の results.json と fold 別指標 CSV を置き、ランの収集・
ブロック判定・SHAP の順位・シード間の順位の安定性（Kendall の τ）・RMSE と LST 標準偏差の
比・保存物を確かめる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scipy.stats import kendalltau

from src.analysis.diagnose_spatial_cv_design import MAX_FOLD_SIZE_RATIO, MIN_BLOCKS
from src.analysis.summarize_rq2_scale_area import (
    RESULTS_FILENAME,
    RunFiles,
    build_tables,
    discover_run_files,
    judge_block_design,
    main,
    rank_shap,
    resolve_folds_path,
    summarize_rank_stability,
    summarize_run,
    to_records,
    validate_run_config,
)

OBSERVATION = "20220906_032358"
SHAP_BASE = {"A": 3.0, "B": 2.0, "C": 1.0}


def _make_result(
    scale_m: int = 30,
    analysis_area: str = "roi",
    random_state: int = 42,
    block_size_m: int = 2700,
    requested_sample_size: int = 100000,
    population: int = 1000,
    sample_size: int = 800,
    lst_std: float = 2.0,
    n_blocks: int = 20,
    rf_rmse: float = 1.0,
    mean_abs_shap: dict[str, float] | None = None,
    evaluation_cells: str | None = None,
    scenario: str = "Limited",
) -> dict[str, Any]:
    """集計に必要な項目だけを持つ合成の results.json の内容を作る（既定は Limited の採用構成）。"""
    metrics = {"r2": 0.7, "rmse": 1.1, "mae": 0.9}
    cv_metrics = {
        "r2_mean": 0.6,
        "r2_std": 0.05,
        "rmse_mean": 1.2,
        "rmse_std": 0.1,
        "mae_mean": 1.0,
        "mae_std": 0.1,
    }
    return {
        "scenario": scenario,
        "variable_set": "both",
        "building_height_mode": "mean",
        "water_index_mode": "none",
        "population_sources": ["worldpop2020"],
        "analysis_area": analysis_area,
        "evaluation_cells": evaluation_cells,
        "sample_size": sample_size,
        "features": list((mean_abs_shap or SHAP_BASE).keys()),
        "run_parameters": {
            "scale_m": scale_m,
            "random_state": random_state,
            "requested_sample_size": requested_sample_size,
        },
        "filter_dropout": {
            "stages": {"feature_complete": population},
            "target_distribution": {"after": {"mean": 30.0, "std": lst_std}},
        },
        "random_split": {
            "linear_regression": {"metrics": metrics},
            "random_forest": {"metrics": {**metrics, "r2": 0.8, "rmse": 0.9}},
        },
        "spatial_cv": {
            "cv_splits": 5,
            "linear_regression": cv_metrics,
            "random_forest": {**cv_metrics, "rmse_mean": rf_rmse},
            "block_definition": {"block_size_m": block_size_m, "n_blocks": n_blocks},
        },
        "shap": {"mean_abs_shap": dict(mean_abs_shap or SHAP_BASE)},
    }


def _write_run(
    directory: Path,
    name: str,
    result: dict[str, Any],
    test_sizes: tuple[int, ...] = (100, 100, 100, 100, 100),
) -> Path:
    """results.json と fold 別指標 CSV を書き、results.json のパスを返す。"""
    directory.mkdir(parents=True, exist_ok=True)
    results_path = directory / f"{name}_results.json"
    results_path.write_text(json.dumps(result), encoding="utf-8")
    folds = pd.DataFrame(
        {
            "fold": range(1, len(test_sizes) + 1),
            "train_size": [400] * len(test_sizes),
            "test_size": list(test_sizes),
        }
    )
    folds.to_csv(resolve_folds_path(results_path), index=False)
    return results_path


def test_validate_run_config_accepts_expected_runs(tmp_path: Path) -> None:
    """ディレクトリの想定どおりのシナリオ・構成なら通す（Satellite Only は構成を問わない）。"""
    limited_files = RunFiles("limited", "main", tmp_path / "a_results.json", tmp_path / "a.csv")
    validate_run_config(limited_files, _make_result())
    satellite_files = RunFiles(
        "satellite_only", "main", tmp_path / "b_results.json", tmp_path / "b.csv"
    )
    validate_run_config(satellite_files, _make_result(scenario="Satellite Only"))


@pytest.mark.parametrize(
    ("scenario_dir", "overrides", "message"),
    [
        ("satellite_only", {}, "シナリオ"),
        ("limited", {"scenario": "Satellite Only"}, "シナリオ"),
        ("limited", {"water_index_mode": "ndwi"}, "採用構成"),
        ("limited", {"population_sources": ["landscan2020"]}, "採用構成"),
    ],
)
def test_validate_run_config_rejects_misplaced_runs(
    tmp_path: Path, scenario_dir: str, overrides: dict[str, Any], message: str
) -> None:
    """別シナリオ・Limited の別構成のランは、集計に混ぜないよう例外にする。"""
    files = RunFiles(scenario_dir, "main", tmp_path / "a_results.json", tmp_path / "a.csv")
    with pytest.raises(ValueError, match=message):
        validate_run_config(files, {**_make_result(), **overrides})


def test_build_tables_rejects_misplaced_scenario(tmp_path: Path) -> None:
    """Limited のランが Satellite Only のディレクトリにあると、集計の前に止める。"""
    _write_run(
        tmp_path / "satellite_only_cellbased" / f"{OBSERVATION}_rq2_scale",
        "a90",
        _make_result(scale_m=90),
    )
    with pytest.raises(ValueError, match="シナリオ"):
        build_tables(discover_run_files(tmp_path, OBSERVATION))


def test_judge_block_design_uses_shared_criteria() -> None:
    """判定基準は Spatial CV の設計の判定と同じ値で、境界の値は成立とする。"""
    passed = judge_block_design(MIN_BLOCKS, [100, 120, int(100 * MAX_FOLD_SIZE_RATIO)])
    assert passed["block_design_ok"] is True
    assert passed["fold_test_size_ratio"] == pytest.approx(MAX_FOLD_SIZE_RATIO)

    too_few = judge_block_design(MIN_BLOCKS - 1, [100, 100])
    assert too_few["meets_min_blocks"] is False
    assert too_few["block_design_ok"] is False

    unbalanced = judge_block_design(MIN_BLOCKS, [100, 151])
    assert unbalanced["meets_fold_size_ratio"] is False
    assert unbalanced["block_design_ok"] is False


@pytest.mark.parametrize("sizes", [[], [0, 10]])
def test_judge_block_design_rejects_invalid_sizes(sizes: list[int]) -> None:
    """fold が無い場合・テストセル数が0の場合は比を求められないため例外にする。"""
    with pytest.raises(ValueError):
        judge_block_design(10, sizes)


def test_rank_shap_share_and_ties() -> None:
    """割合は合計に対する比で、同値の変数は小さい方の順位にそろう。"""
    ranked = rank_shap({"A": 1.0, "B": 3.0, "C": 1.0, "D": 0.0})
    by_feature = ranked.set_index("feature")
    assert by_feature.loc["B", "shap_rank"] == 1
    assert by_feature.loc["A", "shap_rank"] == 2
    assert by_feature.loc["C", "shap_rank"] == 2
    assert by_feature.loc["D", "shap_rank"] == 4
    assert by_feature["shap_share"].sum() == pytest.approx(1.0)
    assert by_feature.loc["B", "shap_share"] == pytest.approx(0.6)
    assert ranked["feature"].tolist() == ["B", "A", "C", "D"]


@pytest.mark.parametrize("values", [{}, {"A": -1.0, "B": 2.0}, {"A": 0.0}])
def test_rank_shap_rejects_invalid_values(values: dict[str, float]) -> None:
    """変数が無い・負の値・合計0の場合は割合を求められないため例外にする。"""
    with pytest.raises(ValueError):
        rank_shap(values)


def test_summarize_run_ratio_and_reference_flag(tmp_path: Path) -> None:
    """RMSE ÷ LST 標準偏差・抽出率・参考値の印・ブロック判定を1行にまとめる。"""
    result = _make_result(
        scale_m=300,
        analysis_area="survey",
        population=1000,
        sample_size=1000,
        lst_std=2.0,
        rf_rmse=1.5,
        n_blocks=12,
    )
    files = RunFiles("limited", "main", tmp_path / "x_results.json", tmp_path / "x.csv")
    folds = pd.DataFrame({"test_size": [100, 110, 120, 130, 140]})
    row = summarize_run(files, result, folds)
    assert row["cv_rf_rmse_over_lst_std"] == pytest.approx(0.75)
    assert row["cv_linear_rmse_over_lst_std"] == pytest.approx(0.6)
    assert row["sampling_ratio"] == pytest.approx(1.0)
    assert row["reference_only"] is True
    assert row["fold_test_size_ratio"] == pytest.approx(1.4)
    assert row["block_design_ok"] is True

    roi_row = summarize_run(files, _make_result(scale_m=300, analysis_area="roi"), folds)
    assert roi_row["reference_only"] is False


def test_summarize_run_rejects_fold_count_mismatch(tmp_path: Path) -> None:
    """fold 数が cv_splits と食い違う場合は、別のランの CSV を読んだ恐れがあり例外にする。"""
    files = RunFiles("limited", "main", tmp_path / "x_results.json", tmp_path / "x.csv")
    with pytest.raises(ValueError, match="cv_splits"):
        summarize_run(files, _make_result(), pd.DataFrame({"test_size": [100, 100]}))


def test_summarize_run_rejects_non_positive_std(tmp_path: Path) -> None:
    """LST の標準偏差が0では比を求められないため例外にする。"""
    files = RunFiles("limited", "main", tmp_path / "x_results.json", tmp_path / "x.csv")
    folds = pd.DataFrame({"test_size": [100] * 5})
    with pytest.raises(ValueError, match="標準偏差"):
        summarize_run(files, _make_result(lst_std=0.0), folds)


def test_discover_run_files_groups_and_skips_evaluation_cells(tmp_path: Path) -> None:
    """群ごとのディレクトリからランを集め、共通評価セルのランは除く。"""
    limited_root = tmp_path / "limited"
    _write_run(limited_root / f"{OBSERVATION}_area_comparison", "a30", _make_result())
    _write_run(
        limited_root / f"{OBSERVATION}_area_comparison",
        "a30_eval",
        _make_result(evaluation_cells="cells.csv"),
    )
    _write_run(limited_root / f"{OBSERVATION}_rq2_scale", "a90", _make_result(scale_m=90))
    _write_run(
        limited_root / f"{OBSERVATION}_rq2_scale_block13500",
        "b30",
        _make_result(block_size_m=13500),
    )
    _write_run(
        limited_root / f"{OBSERVATION}_rq2_scale_n38000",
        "c30",
        _make_result(requested_sample_size=38000),
    )
    _write_run(
        limited_root / f"{OBSERVATION}_rq2_scale_seeds" / "seed43",
        "d30",
        _make_result(random_state=43),
    )
    # 別の観測のディレクトリは拾わない
    _write_run(limited_root / "20230707_032305_rq2_scale", "other", _make_result())

    found = discover_run_files(tmp_path, OBSERVATION)
    groups = sorted((files.group, files.results_path.name) for files in found)
    assert groups == [
        ("block13500", "b30_results.json"),
        ("main", "a30_results.json"),
        ("main", "a90_results.json"),
        ("sample_matched", "c30_results.json"),
        ("seeds", "d30_results.json"),
    ]
    assert all(files.scenario == "limited" for files in found)


def test_discover_run_files_requires_folds_csv(tmp_path: Path) -> None:
    """fold 別指標 CSV が無いランは集計できないため例外にする。"""
    results_path = _write_run(
        tmp_path / "limited" / f"{OBSERVATION}_rq2_scale", "a90", _make_result()
    )
    resolve_folds_path(results_path).unlink()
    with pytest.raises(FileNotFoundError):
        discover_run_files(tmp_path, OBSERVATION)


def test_build_tables_rejects_duplicate_conditions(tmp_path: Path) -> None:
    """同じ条件のランが2本あると、どちらを採るか決まらないため例外にする。"""
    directory = tmp_path / "limited" / f"{OBSERVATION}_rq2_scale"
    _write_run(directory, "first", _make_result(scale_m=90))
    _write_run(directory, "second", _make_result(scale_m=90))
    with pytest.raises(ValueError, match="重複"):
        build_tables(discover_run_files(tmp_path, OBSERVATION))


def _write_seed_runs(tmp_path: Path) -> None:
    """都心部 90m でシード42（本体）と43・44（反復）のランを書く。"""
    root = tmp_path / "limited"
    shap_by_seed = {
        42: {"A": 3.0, "B": 2.0, "C": 1.0},
        43: {"A": 3.0, "B": 1.0, "C": 2.0},
        44: {"A": 1.0, "B": 2.0, "C": 3.0},
    }
    rmse_by_seed = {42: 1.0, 43: 1.2, 44: 1.4}
    for seed, shap_values in shap_by_seed.items():
        directory = (
            root / f"{OBSERVATION}_rq2_scale"
            if seed == 42
            else root / f"{OBSERVATION}_rq2_scale_seeds" / f"seed{seed}"
        )
        _write_run(
            directory,
            "survey90",
            _make_result(
                scale_m=90,
                analysis_area="survey",
                random_state=seed,
                rf_rmse=rmse_by_seed[seed],
                mean_abs_shap=shap_values,
            ),
        )
    # 標本数を変えた群は順位の安定性に混ぜない
    _write_run(
        root / f"{OBSERVATION}_rq2_scale_n500",
        "survey90",
        _make_result(scale_m=90, analysis_area="survey", requested_sample_size=500),
    )


def test_summarize_rank_stability_tau_and_rank_range(tmp_path: Path) -> None:
    """シード42との τ・変数ごとの順位の範囲・シード間の RMSE のばらつきを求める。"""
    _write_seed_runs(tmp_path)
    runs, shap_ranks = build_tables(discover_run_files(tmp_path, OBSERVATION))
    features, summary = summarize_rank_stability(runs, shap_ranks)

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["n_seeds"] == 3
    expected_taus = [
        kendalltau([3.0, 2.0, 1.0], [3.0, 1.0, 2.0])[0],
        kendalltau([3.0, 2.0, 1.0], [1.0, 2.0, 3.0])[0],
    ]
    assert row["kendall_tau_min"] == pytest.approx(min(expected_taus))
    assert row["kendall_tau_mean"] == pytest.approx(sum(expected_taus) / 2)
    assert row["kendall_tau_min"] == pytest.approx(-1.0)
    assert row["top1_seed42"] == "A"
    assert row["top1_same_count"] == 1
    assert row["cv_rf_rmse_mean_over_seeds"] == pytest.approx(1.2)
    assert row["cv_rf_rmse_sd_over_seeds"] == pytest.approx(0.2)

    by_feature = features.set_index("feature")
    assert by_feature.loc["A", "rank_seed42"] == 1
    assert by_feature.loc["A", "rank_range"] == 2
    assert by_feature.loc["B", "rank_min"] == 2
    assert by_feature.loc["B", "rank_max"] == 3
    assert row["max_rank_range"] == 2


def test_summarize_rank_stability_requires_baseline(tmp_path: Path) -> None:
    """シード42の本体が無い条件では、比べる基準が無いため例外にする。"""
    _write_run(
        tmp_path / "limited" / f"{OBSERVATION}_rq2_scale_seeds" / "seed43",
        "survey90",
        _make_result(scale_m=90, analysis_area="survey", random_state=43),
    )
    _write_run(
        tmp_path / "limited" / f"{OBSERVATION}_rq2_scale_seeds" / "seed44",
        "survey90",
        _make_result(scale_m=90, analysis_area="survey", random_state=44),
    )
    runs, shap_ranks = build_tables(discover_run_files(tmp_path, OBSERVATION))
    # 本体が無いため対象ランはシードの反復だけになり、シード42の列が無い
    with pytest.raises(ValueError, match="シード42"):
        summarize_rank_stability(runs, shap_ranks)


def _write_seed_runs_with_shap(tmp_path: Path, shap_by_seed: dict[int, dict[str, float]]) -> None:
    """都心部 90m で、シードごとに指定した平均絶対 SHAP のランを書く。"""
    root = tmp_path / "limited"
    for seed, shap_values in shap_by_seed.items():
        directory = (
            root / f"{OBSERVATION}_rq2_scale"
            if seed == 42
            else root / f"{OBSERVATION}_rq2_scale_seeds" / f"seed{seed}"
        )
        _write_run(
            directory,
            "survey90",
            _make_result(
                scale_m=90,
                analysis_area="survey",
                random_state=seed,
                mean_abs_shap=shap_values,
            ),
        )


def test_summarize_rank_stability_rejects_mismatched_features(tmp_path: Path) -> None:
    """シード間で変数の集合が違う条件は、順位を比べられないため例外にする。"""
    _write_seed_runs_with_shap(
        tmp_path,
        {
            42: {"A": 3.0, "B": 2.0, "C": 1.0},
            43: {"A": 3.0, "B": 2.0},
        },
    )
    runs, shap_ranks = build_tables(discover_run_files(tmp_path, OBSERVATION))
    with pytest.raises(ValueError, match="変数がそろっていません"):
        summarize_rank_stability(runs, shap_ranks)


def test_summarize_rank_stability_handles_tied_top1(tmp_path: Path) -> None:
    """1位が同値で複数あるときは変数名を | でつなぎ、組が同じシードだけを一致と数える。"""
    _write_seed_runs_with_shap(
        tmp_path,
        {
            42: {"A": 2.0, "B": 2.0, "C": 1.0},
            43: {"A": 2.0, "B": 2.0, "C": 1.0},
            44: {"A": 3.0, "B": 2.0, "C": 1.0},
        },
    )
    runs, shap_ranks = build_tables(discover_run_files(tmp_path, OBSERVATION))
    _, summary = summarize_rank_stability(runs, shap_ranks)

    row = summary.iloc[0]
    assert row["top1_seed42"] == "A|B"
    # シード43 は同じ組（A と B の同値）、シード44 は A 単独の1位のため一致しない
    assert row["top1_same_count"] == 1


def test_summarize_rank_stability_empty_without_seed_runs(tmp_path: Path) -> None:
    """シードの反復が無ければ空の表を返す。"""
    _write_run(tmp_path / "limited" / f"{OBSERVATION}_rq2_scale", "a90", _make_result())
    runs, shap_ranks = build_tables(discover_run_files(tmp_path, OBSERVATION))
    features, summary = summarize_rank_stability(runs, shap_ranks)
    assert features.empty
    assert summary.empty


def test_to_records_replaces_nan_with_none() -> None:
    """欠損は JSON に書けるよう None に置き換える。"""
    frame = pd.DataFrame({"a": [1.0, float("nan")], "b": ["x", "y"]})
    assert to_records(frame) == [{"a": 1.0, "b": "x"}, {"a": None, "b": "y"}]


def test_main_writes_outputs_with_provenance(tmp_path: Path) -> None:
    """CSV 4種と、来歴・判定から外れたランを記録した results.json を保存する。"""
    _write_seed_runs(tmp_path)
    _write_run(
        tmp_path / "satellite_only_cellbased" / f"{OBSERVATION}_rq2_scale",
        "survey300",
        _make_result(
            scale_m=300,
            analysis_area="survey",
            n_blocks=MIN_BLOCKS - 1,
            scenario="Satellite Only",
        ),
    )
    summary_dir = tmp_path / "summary"
    main(["--output-root", str(tmp_path), "--summary-dir", str(summary_dir)])

    for name in (
        "rq2_runs.csv",
        "rq2_shap_ranks.csv",
        "rq2_rank_stability_features.csv",
        "rq2_rank_stability_summary.csv",
    ):
        assert (summary_dir / name).is_file()
    saved = json.loads((summary_dir / RESULTS_FILENAME).read_text(encoding="utf-8"))
    assert saved["n_runs"] == 5
    assert saved["runs_by_group"] == {"main": 2, "seeds": 2, "sample_matched": 1}
    assert saved["criteria"]["min_blocks"] == MIN_BLOCKS
    assert saved["block_design_failed_runs"] == [
        {
            "scenario": "satellite_only",
            "group": "main",
            "scale_m": 300,
            "analysis_area": "survey",
            "block_size_m": 2700,
            "random_state": 42,
            "requested_sample_size": 100000,
        }
    ]
    assert saved["provenance"]["script"] == "src.analysis.summarize_rq2_scale_area"
    # 入力は各ランの results.json と fold 別指標 CSV（5ラン × 2ファイル）
    assert len(saved["provenance"]["inputs"]) == 10
    runs = pd.read_csv(summary_dir / "rq2_runs.csv")
    assert runs.loc[runs["scenario"] == "satellite_only", "reference_only"].tolist() == [True]
