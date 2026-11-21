"""src/analysis/compare_observations.py（観測をまたいだ結果の比較）のテスト。

合成の results.json を置き、前提の検証（シナリオ・全域・採用構成・実行条件の一致）、
誤差と SHAP を LST の標準偏差で割った値、順位の付け方、横持ちの表、シナリオ間の差、
保存物と来歴を確かめる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.analysis.compare_observations import (
    DEFAULT_RUNS,
    RESULTS_FILENAME,
    RunSpec,
    build_run_specs,
    build_scenario_diff,
    build_tables,
    main,
    rank_features,
    summarize_metrics,
    validate_run,
    validate_shared_conditions,
    widen_feature_ranks,
)
from src.common.config import PROJECT_ROOT

RUN_PARAMETERS = {
    "random_state": 42,
    "rf_trees": 300,
    "requested_sample_size": 100000,
    "scale_m": 30,
}
LIMITED_CONFIG = {
    "variable_set": "both",
    "building_height_mode": "mean",
    "water_index_mode": "none",
    "population_sources": ["worldpop2020"],
}


def _make_result(
    scenario: str = "Limited",
    lst_std: float = 2.0,
    population: int = 1000,
    cv_rf_rmse: float = 1.0,
    cv_rf_r2: float = 0.8,
    mean_abs_shap: dict[str, float] | None = None,
    permutation: dict[str, float] | None = None,
    analysis_area: str = "roi",
    block_size_m: int = 2700,
    random_state: int = 42,
    observation: str = "obs0",
) -> dict[str, Any]:
    """集計に必要な項目だけを持つ合成の results.json の内容を作る。

    入力データセットのパスには、実際の命名と同じく観測の識別子を含める。
    """
    shap_values = mean_abs_shap or {"A": 1.0, "B": 0.5, "C": 0.1}
    permutation_values = permutation or {"A": 0.3, "B": 0.4, "C": -0.01}
    result: dict[str, Any] = {
        "dataset_path": f"data/output/datasets/dataset_x_{observation}_hanoi_30m.gpkg",
        "scenario": scenario,
        "analysis_area": analysis_area,
        "sample_size": 800,
        "features": list(shap_values),
        "run_parameters": {**RUN_PARAMETERS, "random_state": random_state},
        "filter_dropout": {
            "stages": {"feature_complete": population},
            "target_distribution": {"after": {"mean": 30.0, "std": lst_std}},
        },
        "random_split": {
            "linear_regression": {"metrics": {"r2": 0.6, "rmse": 1.4, "mae": 1.1}},
            "random_forest": {
                "metrics": {"r2": 0.85, "rmse": 0.9, "mae": 0.7},
                "permutation_importance": permutation_values,
            },
        },
        "spatial_cv": {
            "cv_splits": 5,
            "block_definition": {"block_size_m": block_size_m, "n_blocks": 100},
            "linear_regression": {
                "r2_mean": 0.55,
                "r2_std": 0.02,
                "rmse_mean": 1.5,
                "mae_mean": 1.2,
            },
            "random_forest": {
                "r2_mean": cv_rf_r2,
                "r2_std": 0.01,
                "rmse_mean": cv_rf_rmse,
                "mae_mean": 0.8,
            },
        },
        "shap": {"mean_abs_shap": shap_values},
        "provenance": {"git": {"commit": "abc", "dirty": False}},
    }
    if scenario == "Limited":
        result.update(LIMITED_CONFIG)
    return result


def _write(path: Path, result: dict[str, Any]) -> Path:
    """results.json を書き出してパスを返す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return path


def _spec(tmp_path: Path, observation: str, scenario: str, **kwargs: Any) -> RunSpec:
    """合成の results.json を書き、そのランの指定を返す。"""
    label = "Limited" if scenario == "limited" else "Satellite Only"
    path = _write(
        tmp_path / observation / f"{scenario}_results.json",
        _make_result(scenario=label, observation=observation, **kwargs),
    )
    return RunSpec(observation, scenario, path)


def test_default_runs_cover_three_observations_and_both_scenarios() -> None:
    """既定の比較対象は 3 観測 × 2 シナリオで、パスは観測の識別子を含む。"""
    keys = {(spec.observation, spec.scenario) for spec in DEFAULT_RUNS}
    assert keys == {
        (obs, scenario)
        for obs in ("20220906_032358", "20230707_032305", "20241130_032336")
        for scenario in ("satellite_only", "limited")
    }
    for spec in DEFAULT_RUNS:
        assert spec.observation in spec.results_path.as_posix()
        assert not spec.results_path.is_absolute()


def test_build_run_specs_resolves_relative_paths_and_rejects_duplicates() -> None:
    """相対パスはプロジェクトルート基準に解決し、重複・未知のシナリオは拒む。"""
    obs = "20220906_032358"
    specs = build_run_specs([[obs, "limited", "data/x.json"]])
    assert specs[0].results_path == PROJECT_ROOT / "data" / "x.json"
    with pytest.raises(ValueError, match="重複"):
        build_run_specs([[obs, "limited", "a.json"], [obs, "limited", "b.json"]])
    with pytest.raises(ValueError, match="未知のシナリオ"):
        build_run_specs([[obs, "full", "a.json"]])


@pytest.mark.parametrize("observation", ["20220906", "", "20220906_03235", "x20220906_032358"])
def test_build_run_specs_rejects_malformed_observation(observation: str) -> None:
    """途中までの識別子・空文字など、YYYYMMDD_HHMMSS でない観測の指定を拒む。"""
    with pytest.raises(ValueError, match="YYYYMMDD_HHMMSS"):
        build_run_specs([[observation, "limited", "a.json"]])


@pytest.mark.parametrize(
    ("scenario", "result", "message"),
    [
        ("limited", _make_result(scenario="Satellite Only"), "シナリオが指定"),
        ("limited", _make_result(analysis_area="survey"), "全域"),
        ("limited", {**_make_result(), "evaluation_cells": "cells.csv"}, "共通評価セル"),
        ("limited", {**_make_result(), "water_index_mode": "ndwi"}, "採用構成"),
    ],
)
def test_validate_run_rejects_runs_outside_the_comparison(
    scenario: str, result: dict[str, Any], message: str
) -> None:
    """シナリオ違い・全域以外・共通評価セル・採用構成以外のランを拒む。"""
    with pytest.raises(ValueError, match=message):
        validate_run(RunSpec("obs0", scenario, Path("r.json")), result)


def test_validate_run_rejects_mismatched_observation() -> None:
    """指定した観測が入力データセットのパスに無ければ（観測の取り違え）拒む。"""
    with pytest.raises(ValueError, match="観測の識別子（obs1）"):
        validate_run(RunSpec("obs1", "limited", Path("r.json")), _make_result(observation="obs0"))
    with pytest.raises(ValueError, match="観測の識別子"):
        validate_run(
            RunSpec("obs0", "limited", Path("r.json")),
            {k: v for k, v in _make_result().items() if k != "dataset_path"},
        )


def test_validate_run_accepts_satellite_only_without_limited_config() -> None:
    """Satellite Only には Limited の構成の項目が無くてよい。"""
    validate_run(
        RunSpec("obs0", "satellite_only", Path("r.json")),
        _make_result(scenario="Satellite Only"),
    )


def test_validate_shared_conditions_reports_differing_keys() -> None:
    """実行条件（乱数シード・ブロック長）が違うランがあれば、違う項目を挙げて拒む。"""
    specs = [RunSpec("a", "limited", Path("a.json")), RunSpec("b", "limited", Path("b.json"))]
    same = validate_shared_conditions(specs, [_make_result(), _make_result()])
    assert same["block_size_m"] == 2700
    assert same["cv_splits"] == 5
    assert same["random_state"] == 42
    with pytest.raises(ValueError, match="block_size_m, random_state"):
        validate_shared_conditions(
            specs, [_make_result(), _make_result(block_size_m=13500, random_state=0)]
        )


def test_summarize_metrics_divides_errors_by_lst_std() -> None:
    """RMSE・MAE は最終母数の LST の標準偏差で割る。°C の値も残す。"""
    row = summarize_metrics(
        RunSpec("o", "limited", PROJECT_ROOT / "data" / "r.json"),
        _make_result(lst_std=2.0, cv_rf_rmse=1.0),
    )
    assert row["cv_rf_rmse_mean"] == pytest.approx(1.0)
    assert row["cv_rf_rmse_over_lst_std"] == pytest.approx(0.5)
    assert row["cv_rf_mae_over_lst_std"] == pytest.approx(0.4)
    assert row["cv_linear_rmse_over_lst_std"] == pytest.approx(0.75)
    assert row["random_rf_rmse_over_lst_std"] == pytest.approx(0.45)
    assert row["population"] == 1000
    assert row["results_json"] == "data/r.json"
    assert row["git_dirty"] is False


@pytest.mark.parametrize(("population", "lst_std"), [(0, 2.0), (1000, 0.0)])
def test_summarize_metrics_rejects_non_positive_population_or_std(
    population: int, lst_std: float
) -> None:
    """最終母数か LST の標準偏差が正でなければ拒む（0 で割らない）。"""
    with pytest.raises(ValueError, match="正ではありません"):
        summarize_metrics(
            RunSpec("o", "limited", Path("r.json")),
            _make_result(population=population, lst_std=lst_std),
        )


def test_rank_features_ranks_shap_and_permutation_separately() -> None:
    """SHAP と Permutation は別々に順位を付け、SHAP は LST の標準偏差で割る。"""
    frame = rank_features(_make_result(), lst_std=2.0).set_index("feature")
    assert frame.loc["A", "shap_rank"] == 1
    assert frame.loc["A", "shap_over_lst_std"] == pytest.approx(0.5)
    # Permutation では B が首位、負の値の C は最下位
    assert frame.loc["B", "permutation_rank"] == 1
    assert frame.loc["C", "permutation_rank"] == 3
    assert frame["shap_share"].sum() == pytest.approx(1.0)


def test_rank_features_rejects_mismatched_features() -> None:
    """SHAP と Permutation の変数がそろわなければ拒む。"""
    with pytest.raises(ValueError, match="そろっていません"):
        rank_features(_make_result(permutation={"A": 0.1}), lst_std=2.0)


def test_build_tables_and_scenario_diff(tmp_path: Path) -> None:
    """2観測 × 2シナリオの表を作り、シナリオ間の差を観測ごとに求める。"""
    specs = [
        _spec(tmp_path, "obs1", "satellite_only", cv_rf_r2=0.7, population=1200),
        _spec(tmp_path, "obs1", "limited", cv_rf_r2=0.8, population=1000),
        _spec(tmp_path, "obs2", "satellite_only", cv_rf_r2=0.6),
        _spec(tmp_path, "obs2", "limited", cv_rf_r2=0.75),
    ]
    metrics, feature_ranks, conditions = build_tables(specs)
    assert len(metrics) == 4
    assert len(feature_ranks) == 12
    assert conditions["rf_trees"] == 300

    diff = build_scenario_diff(metrics).set_index("observation")
    assert diff.loc["obs1", "cv_rf_r2_mean_limited_minus_satellite_only"] == pytest.approx(0.1)
    assert diff.loc["obs1", "population_limited_minus_satellite_only"] == -200
    assert diff.loc["obs2", "cv_rf_r2_mean_limited_minus_satellite_only"] == pytest.approx(0.15)


def test_build_tables_rejects_feature_set_mismatch_within_scenario(tmp_path: Path) -> None:
    """同じシナリオで観測により説明変数が違えば（定数列の除外の違いなど）拒む。"""
    two_features = {"A": 1.0, "B": 0.5}
    specs = [
        _spec(tmp_path, "obs1", "limited"),
        _spec(
            tmp_path,
            "obs2",
            "limited",
            mean_abs_shap=two_features,
            permutation={"A": 0.3, "B": 0.4},
        ),
    ]
    with pytest.raises(ValueError, match=r"limited の説明変数が obs1 と一致しません（C）"):
        build_tables(specs)


def test_build_tables_allows_different_features_across_scenarios(tmp_path: Path) -> None:
    """シナリオが違えば説明変数の集合は違ってよい。"""
    specs = [
        _spec(
            tmp_path,
            "obs1",
            "satellite_only",
            mean_abs_shap={"A": 1.0},
            permutation={"A": 0.3},
        ),
        _spec(tmp_path, "obs1", "limited"),
    ]
    metrics, _, _ = build_tables(specs)
    assert metrics["n_features"].tolist() == [1, 3]


def test_build_scenario_diff_skips_observation_without_both_scenarios(tmp_path: Path) -> None:
    """片方のシナリオしか無い観測は差を求めない。"""
    specs = [
        _spec(tmp_path, "obs1", "satellite_only"),
        _spec(tmp_path, "obs1", "limited"),
        _spec(tmp_path, "obs2", "limited"),
    ]
    metrics, _, _ = build_tables(specs)
    assert build_scenario_diff(metrics)["observation"].tolist() == ["obs1"]


def test_widen_feature_ranks_orders_observations_and_marks_missing() -> None:
    """観測の順に列を並べ、ある観測に無い変数は欠損にする。"""
    rows = [
        {
            "observation": obs,
            "scenario": "limited",
            "feature": feature,
            "shap_rank": rank,
            "shap_over_lst_std": 0.1,
            "permutation_rank": rank,
        }
        for obs, feature, rank in (
            ("obs2", "A", 2),
            ("obs2", "B", 1),
            ("obs1", "A", 1),
            ("obs1", "B", 2),
            ("obs1", "C", 3),
        )
    ]
    wide = widen_feature_ranks(pd.DataFrame(rows), ["obs1", "obs2"])
    assert list(wide.columns[:4]) == ["scenario", "feature", "shap_rank_obs1", "shap_rank_obs2"]
    assert wide["feature"].tolist() == ["A", "B", "C"]
    assert pd.isna(wide.set_index("feature").loc["C", "shap_rank_obs2"])
    assert str(wide["shap_rank_obs1"].dtype) == "Int64"


def test_main_writes_outputs_with_provenance(tmp_path: Path) -> None:
    """CSV 4種と、実行条件・比べる量の約束・来歴を記録した JSON を保存する。"""
    runs: list[str] = []
    observations = ("20220906_032358", "20241130_032336")
    for obs in observations:
        for scenario in ("satellite_only", "limited"):
            spec = _spec(tmp_path, obs, scenario)
            runs += ["--run", obs, scenario, str(spec.results_path)]
    output_dir = tmp_path / "summary"
    main([*runs, "--output-dir", str(output_dir)])

    for name in (
        "observation_metrics.csv",
        "observation_feature_ranks.csv",
        "observation_feature_ranks_wide.csv",
        "observation_scenario_diff.csv",
    ):
        assert (output_dir / name).is_file()
    saved = json.loads((output_dir / RESULTS_FILENAME).read_text(encoding="utf-8"))
    assert saved["observations"] == list(observations)
    assert saved["n_runs"] == 4
    assert saved["shared_conditions"]["block_size_m"] == 2700
    assert "°C の RMSE・MAE・平均絶対 SHAP" in saved["comparison_rules"]["do_not_compare"]
    assert len(saved["scenario_diff"]) == 2
    assert saved["provenance"]["script"] == "src.analysis.compare_observations"
    assert len(saved["provenance"]["inputs"]) == 4
