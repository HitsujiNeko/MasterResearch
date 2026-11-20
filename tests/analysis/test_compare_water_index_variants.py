"""src/analysis/compare_water_index_variants.py（水指数の構成どうしの差）のテスト。

2つの反復の結果 JSON・fold 別指標 CSV と、2つの単発の比較・全工程ランの結果 JSON・
fold 別指標 CSV を一時ディレクトリに合成し、差の向き・数え方・検証・保存物を確かめる。
区間の計算そのものは tests/common/test_cv_paired_comparison.py で検証する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.analysis.compare_water_index_variants import (
    REFERENCE_WATER_INDEX_MODE,
    WATCH_PATHS,
    compute_relative_sizes,
    compute_seedwise_differences,
    count_variant_better,
    main,
    parse_arguments,
    resolve_input_paths,
    resolve_output_paths,
    validate_repeated_pair,
)
from src.common.cv_paired_comparison import FOLD_METRIC_COLUMNS, summarize_metric_differences

CELLS_NAME = "evaluation_cells_seed42.csv"
SEEDS = (42, 43)
TRAIN_SIZES = (70, 60, 70)
TEST_SIZES = (30, 40, 30)
# シードごとの標本の内容ダイジェスト（主シード 42 は全工程ランの評価セルと同じ "abc"）。
SEED_DIGESTS = {42: "abc", 43: "def"}
SEED_RECORDS = [{"seed": seed, "digest": digest} for seed, digest in SEED_DIGESTS.items()]
# fold ごとの基準の値（構成・シードごとにずらす）。
BASE_VALUES = np.array([0.50, 0.60, 0.70])


def _folds(offset: float, seed_offset: float = 0.0) -> pd.DataFrame:
    """fold 別指標の表を作る（全指標に同じ値を入れる）。"""
    folds = pd.DataFrame(
        {"fold": [1, 2, 3], "train_size": list(TRAIN_SIZES), "test_size": list(TEST_SIZES)}
    )
    for column in FOLD_METRIC_COLUMNS:
        folds[column] = BASE_VALUES + offset + seed_offset
    return folds


def _variant_offsets() -> dict[int, np.ndarray]:
    """比べる構成の採用構成からのずれ（シード・fold ごと）。R² では1行だけ負にする。"""
    return {42: np.array([0.010, 0.020, -0.005]), 43: np.array([0.015, 0.010, 0.005])}


def _repeated_fold_table(role: str) -> pd.DataFrame:
    """反復の `_folds.csv`（両シナリオ・全シード）を作る。"""
    frames = []
    for index, seed in enumerate(SEEDS):
        satellite = _folds(0.0, seed_offset=0.001 * index)
        limited = _folds(0.1, seed_offset=0.001 * index)
        if role == "variant":
            for column in FOLD_METRIC_COLUMNS:
                limited[column] = limited[column] + _variant_offsets()[seed]
        frames.append(satellite.assign(scenario="satellite_only", seed=seed))
        frames.append(limited.assign(scenario="limited", seed=seed))
    return pd.concat(frames, ignore_index=True)


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    """辞書を JSON に書いてパスを返す。"""
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_inputs(tmp_path: Path, variant_mode: str = "ndwi") -> Path:
    """両構成の反復・単発の比較・全工程ランの入力一式を書き、評価セル CSV のパスを返す。"""
    cells_path = tmp_path / CELLS_NAME
    cells_path.write_text("cell_id,block_id,fold\n1,1,1\n", encoding="utf-8")
    paths = resolve_input_paths(cells_path, variant_mode)
    modes = {"reference": REFERENCE_WATER_INDEX_MODE, "variant": variant_mode}
    for role, mode in modes.items():
        folds_csv = tmp_path / f"repeated_{role}_folds.csv"
        _repeated_fold_table(role).to_csv(folds_csv, index=False)
        _write_json(
            paths[f"repeated_{role}"],
            {
                "evaluation_cells": str(cells_path),
                "analysis_area": "full",
                "common_size": 1000,
                "seeds": list(SEEDS),
                "seed_records": SEED_RECORDS,
                "cv_splits": 3,
                "sample_size": 100,
                "rf_trees": 300,
                "limited_configuration": {
                    "variable_set": "both",
                    "building_height_mode": "mean",
                    "water_index_mode": mode,
                    "population_sources": ["worldpop2020"],
                },
                # 主結果の差（Limited − Satellite Only）は全指標で 0.1
                "seed_differences": {
                    column: {"mean": 0.1, "sd": 0.001} for column in FOLD_METRIC_COLUMNS
                },
                "outputs": {"folds_csv": str(folds_csv)},
            },
        )
        # 全工程ランの fold 別指標は、反復の主シード（42）の Limited の行と同じにする
        table = _repeated_fold_table(role)
        full_run = table[(table["scenario"] == "limited") & (table["seed"] == 42)].drop(
            columns=["scenario", "seed"]
        )
        full_run_csv = tmp_path / f"limited_{role}_spatial_cv_folds.csv"
        full_run.to_csv(full_run_csv, index=False)
        limited_result = _write_json(
            tmp_path / f"limited_{role}_results.json",
            {
                "variable_set": "both",
                "building_height_mode": "mean",
                "water_index_mode": mode,
                "population_sources": ["worldpop2020"],
                "train_size": 80,
                "test_size": 20,
                "run_parameters": {"random_state": 42, "rf_trees": 300},
                "evaluation_cells": {"digest": "abc", "path": str(cells_path)},
                "spatial_cv": {"outputs": {"fold_metrics_csv": str(full_run_csv)}},
            },
        )
        _write_json(
            paths[f"single_{role}"],
            {
                "inputs": {
                    "satellite_only_results": str(tmp_path / "satellite_only_results.json"),
                    "limited_results": str(limited_result),
                }
            },
        )
    return cells_path


class TestPaths:
    """入出力のパスの規則のテスト。"""

    def test_input_paths_follow_existing_output_names(self, tmp_path: Path) -> None:
        """採用構成は接尾辞なし、比べる構成は `_wi_{構成}` 付きの反復・単発の比較の結果。"""
        paths = resolve_input_paths(tmp_path / CELLS_NAME, "ndwi")

        assert paths["repeated_reference"].name == (
            "repeated_comparison_evaluation_cells_seed42_results.json"
        )
        assert paths["repeated_variant"].name == (
            "repeated_comparison_evaluation_cells_seed42_wi_ndwi_results.json"
        )
        assert paths["single_reference"].name == (
            "scenario_comparison_evaluation_cells_seed42_results.json"
        )
        assert paths["single_variant"].name == (
            "scenario_comparison_evaluation_cells_seed42_wi_ndwi_results.json"
        )

    def test_output_names_end_with_results_json(self, tmp_path: Path) -> None:
        """結果 JSON は陳腐化チェックの走査対象（`_results.json`）になり、CSV と重ならない。"""
        paths = resolve_output_paths(tmp_path / CELLS_NAME, "ndwi")

        assert paths["results"].name == (
            "water_index_comparison_evaluation_cells_seed42_wi_ndwi_results.json"
        )
        assert len({path for path in paths.values()}) == 3

    def test_rejects_reference_as_variant(self, tmp_path: Path) -> None:
        """採用構成どうしは比べない（引数でも関数でも止める）。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--water-index", REFERENCE_WATER_INDEX_MODE])
        with pytest.raises(ValueError, match="採用構成"):
            resolve_input_paths(tmp_path / CELLS_NAME, REFERENCE_WATER_INDEX_MODE)


class TestDifferences:
    """差の向き・数え方のテスト。"""

    def test_difference_is_variant_minus_reference_per_seed(self) -> None:
        """差は「比べる構成 − 採用構成」で、シードごとに fold を対応させる。"""
        reference = _repeated_fold_table("reference")
        variant = _repeated_fold_table("variant")

        differences = compute_seedwise_differences(
            reference[reference["scenario"] == "limited"].drop(columns="scenario"),
            variant[variant["scenario"] == "limited"].drop(columns="scenario"),
        )

        expected = np.concatenate([_variant_offsets()[seed] for seed in SEEDS])
        np.testing.assert_allclose(differences["rf_r2"], expected)
        assert differences["seed"].tolist() == [42, 42, 42, 43, 43, 43]

    def test_rejects_different_seeds(self) -> None:
        """シードの集合が違えば止める。"""
        reference = _folds(0.0).assign(seed=42)
        variant = _folds(0.0).assign(seed=43)

        with pytest.raises(ValueError, match="シード"):
            compute_seedwise_differences(reference, variant)

    def test_count_uses_metric_direction(self) -> None:
        """R² は差が正、RMSE・MAE は差が負を「比べる構成が良い」とし、0は数えない。"""
        differences = pd.DataFrame({"rf_r2": [0.01, -0.01, 0.0], "rf_rmse": [-0.02, 0.01, 0.0]})

        counts = count_variant_better(differences, ["rf_r2", "rf_rmse"])

        assert counts["rf_r2"] == {"n_variant_better": 1, "n_total": 3}
        assert counts["rf_rmse"] == {"n_variant_better": 1, "n_total": 3}

    def test_relative_sizes_handle_zero_denominator(self) -> None:
        """主結果の差・sd に対する比を求め、分母が0なら None にする。"""
        sizes = compute_relative_sizes(
            {"rf_rmse": {"mean": -0.0075, "sd": 0.0015}, "rf_r2": {"mean": 0.002, "sd": 0.0}},
            {"rf_rmse": {"mean": -0.25}, "rf_r2": {"mean": 0.0}},
        )

        assert sizes["rf_rmse"]["ratio_to_main_difference"] == pytest.approx(0.03)
        assert sizes["rf_rmse"]["ratio_to_seed_sd"] == pytest.approx(5.0)
        assert sizes["rf_r2"] == {"ratio_to_main_difference": None, "ratio_to_seed_sd": None}


class TestValidateRepeatedPair:
    """validate_repeated_pair のテスト。"""

    def _pair(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """水指数だけが違う2つの反復の結果を作る。"""
        base = {
            "evaluation_cells": "cells.csv",
            "analysis_area": "full",
            "common_size": 1000,
            "seeds": [42, 43],
            "seed_records": SEED_RECORDS,
            "cv_splits": 5,
            "sample_size": 100,
            "rf_trees": 300,
        }
        configuration = {
            "variable_set": "both",
            "building_height_mode": "mean",
            "population_sources": ["worldpop2020"],
        }
        reference = {
            **base,
            "limited_configuration": {**configuration, "water_index_mode": "none"},
        }
        variant = {**base, "limited_configuration": {**configuration, "water_index_mode": "ndwi"}}
        return reference, variant

    def test_accepts_pair_differing_only_in_water_index(self) -> None:
        """水指数の構成だけが違えば通す。"""
        reference, variant = self._pair()

        validate_repeated_pair(reference, variant, "ndwi")

    @pytest.mark.parametrize(
        ("key", "value"),
        [("seeds", [42]), ("rf_trees", 100), ("evaluation_cells", "other.csv")],
    )
    def test_rejects_different_conditions(self, key: str, value: Any) -> None:
        """シード・木の本数・評価セルが違えば止める。"""
        reference, variant = self._pair()
        variant[key] = value

        with pytest.raises(ValueError, match=key):
            validate_repeated_pair(reference, variant, "ndwi")

    def test_rejects_different_common_size(self) -> None:
        """共通集合の母数が違えば止める。"""
        reference, variant = self._pair()
        variant["common_size"] = 999

        with pytest.raises(ValueError, match="common_size"):
            validate_repeated_pair(reference, variant, "ndwi")

    def test_rejects_different_seed_samples(self) -> None:
        """シードごとの標本のダイジェストが違えば（別の標本で回った反復）止める。"""
        reference, variant = self._pair()
        variant["seed_records"] = [{"seed": 42, "digest": "abc"}, {"seed": 43, "digest": "zzz"}]

        with pytest.raises(ValueError, match="seed_records"):
            validate_repeated_pair(reference, variant, "ndwi")

    def test_rejects_missing_seed_records(self) -> None:
        """標本のダイジェストの記録が無ければ、一致を確かめられないため止める。"""
        reference, variant = self._pair()
        del variant["seed_records"]

        with pytest.raises(ValueError, match="標本ダイジェスト"):
            validate_repeated_pair(reference, variant, "ndwi")

    def test_rejects_other_limited_configuration(self) -> None:
        """水指数以外の Limited の構成（人口ソース等）が違えば止める。"""
        reference, variant = self._pair()
        variant["limited_configuration"]["population_sources"] = ["landscan2020"]

        with pytest.raises(ValueError, match="population_sources"):
            validate_repeated_pair(reference, variant, "ndwi")

    def test_rejects_unexpected_water_index_modes(self) -> None:
        """入力の水指数の構成が想定（採用構成と指定の構成）と違えば止める。"""
        reference, variant = self._pair()

        with pytest.raises(ValueError, match="water_index_mode"):
            validate_repeated_pair(reference, variant, "mndwi")


class TestMain:
    """main() のテスト。"""

    def test_saves_differences_intervals_and_checks(self, tmp_path: Path) -> None:
        """反復・単発の差と区間・良い fold/シードの数・一致の検査・来歴を保存する。"""
        cells_path = _write_inputs(tmp_path)

        main(["--evaluation-cells", str(cells_path)])

        output_paths = resolve_output_paths(cells_path, "ndwi")
        result = json.loads(output_paths["results"].read_text(encoding="utf-8"))
        assert result["difference_direction"] == "Limited(ndwi) − Limited(none)"

        # 反復: 区間は保存した fold ごとの差から同じ関数で求めた値と一致する
        repeated_folds = pd.read_csv(output_paths["repeated_folds"])
        expected = summarize_metric_differences(repeated_folds)
        repeated = result["repeated"]
        assert repeated["repeated_kfold"]["metrics"]["rf_r2"]["corrected"] == pytest.approx(
            expected["metrics"]["rf_r2"]["corrected"]
        )
        assert repeated["repeated_kfold"]["metrics"]["rf_r2"]["n_splits"] == 6
        offsets = np.concatenate([_variant_offsets()[seed] for seed in SEEDS])
        assert repeated["repeated_kfold"]["metrics"]["rf_r2"]["mean_difference"] == pytest.approx(
            offsets.mean()
        )
        # R² は差が正の5 fold・2シードで良く、RMSE は差が負の1 fold・0シードで良い
        assert repeated["variant_better"]["folds"]["rf_r2"] == {
            "n_variant_better": 5,
            "n_total": 6,
        }
        assert repeated["variant_better"]["seeds"]["rf_r2"]["n_variant_better"] == 2
        assert repeated["variant_better"]["folds"]["rf_rmse"]["n_variant_better"] == 1
        assert repeated["relative_size"]["rf_r2"]["ratio_to_main_difference"] == pytest.approx(
            offsets.mean() / 0.1
        )

        # 単発: 全工程ランの fold 別指標（主シード）どうしの差
        single = result["single"]
        assert single["spatial_cv"]["metrics"]["rf_r2"]["n_splits"] == 3
        assert single["spatial_cv"]["metrics"]["rf_r2"]["mean_difference"] == pytest.approx(
            _variant_offsets()[42].mean()
        )
        np.testing.assert_allclose(
            pd.read_csv(output_paths["single_folds"])["rf_r2"], _variant_offsets()[42]
        )

        assert result["consistency_checks"] == {
            "repeated_satellite_only_folds_identical": True,
            "single_satellite_only_results_identical": True,
            "repeated_main_seed_matches_full_run": {"reference": True, "variant": True},
        }
        # 来歴: 結果 JSON 4・反復の CSV 2・全工程ランの JSON 2 と CSV 2・評価セル
        assert len(result["provenance"]["inputs"]) == 11
        assert set(WATCH_PATHS) <= set(result["provenance"]["code"]["watch_paths"])

    def test_records_mismatch_of_satellite_only_folds(self, tmp_path: Path) -> None:
        """2つの反復の Satellite Only 側が違えば、止めずに False で記録し、警告する。"""
        cells_path = _write_inputs(tmp_path)
        folds_csv = tmp_path / "repeated_variant_folds.csv"
        table = pd.read_csv(folds_csv)
        table.loc[table["scenario"] == "satellite_only", "rf_r2"] += 1e-6
        table.to_csv(folds_csv, index=False)

        with pytest.warns(UserWarning, match="repeated_satellite_only_folds_identical"):
            main(["--evaluation-cells", str(cells_path)])

        result = json.loads(
            resolve_output_paths(cells_path, "ndwi")["results"].read_text(encoding="utf-8")
        )
        assert result["consistency_checks"]["repeated_satellite_only_folds_identical"] is False

    def test_records_mismatch_of_full_run(self, tmp_path: Path) -> None:
        """反復の主シードと全工程ランの fold 別指標が違えば、False で記録し、警告する。"""
        cells_path = _write_inputs(tmp_path)
        full_run_csv = tmp_path / "limited_variant_spatial_cv_folds.csv"
        folds = pd.read_csv(full_run_csv)
        folds["rf_rmse"] += 1e-6
        folds.to_csv(full_run_csv, index=False)

        with pytest.warns(UserWarning, match="repeated_main_seed_matches_full_run.variant"):
            main(["--evaluation-cells", str(cells_path)])

        result = json.loads(
            resolve_output_paths(cells_path, "ndwi")["results"].read_text(encoding="utf-8")
        )
        assert result["consistency_checks"]["repeated_main_seed_matches_full_run"] == {
            "reference": True,
            "variant": False,
        }

    def test_stops_when_full_runs_use_different_cells(self, tmp_path: Path) -> None:
        """単発の全工程ランどうしの評価セルが違えば止める。"""
        cells_path = _write_inputs(tmp_path)
        limited_result = tmp_path / "limited_variant_results.json"
        data = json.loads(limited_result.read_text(encoding="utf-8"))
        data["evaluation_cells"]["digest"] = "xyz"
        _write_json(limited_result, data)

        with pytest.raises(ValueError, match="digest"):
            main(["--evaluation-cells", str(cells_path)])

    @pytest.mark.parametrize(
        ("key", "value"),
        [("water_index_mode", "mndwi"), ("population_sources", ["landscan2020"])],
    )
    def test_stops_when_full_runs_differ_in_configuration(
        self, tmp_path: Path, key: str, value: Any
    ) -> None:
        """単発の全工程ランの水指数が想定と違う、または他の構成が違えば止める。"""
        cells_path = _write_inputs(tmp_path)
        limited_result = tmp_path / "limited_variant_results.json"
        data = json.loads(limited_result.read_text(encoding="utf-8"))
        data[key] = value
        _write_json(limited_result, data)

        with pytest.raises(ValueError, match=key):
            main(["--evaluation-cells", str(cells_path)])

    def test_stops_when_full_runs_differ_from_repeated_sample(self, tmp_path: Path) -> None:
        """単発の全工程ランの評価セルが、反復の主シードの標本と違えば止める。"""
        cells_path = _write_inputs(tmp_path)
        for role in ("reference", "variant"):
            limited_result = tmp_path / f"limited_{role}_results.json"
            data = json.loads(limited_result.read_text(encoding="utf-8"))
            data["evaluation_cells"]["digest"] = "xyz"
            _write_json(limited_result, data)

        with pytest.raises(ValueError, match="反復の主シードの標本と一致しません"):
            main(["--evaluation-cells", str(cells_path)])

    def test_stops_when_input_missing(self, tmp_path: Path) -> None:
        """入力の結果 JSON が無ければ止める。"""
        cells_path = _write_inputs(tmp_path)
        resolve_input_paths(cells_path, "ndwi")["repeated_variant"].unlink()

        with pytest.raises(FileNotFoundError):
            main(["--evaluation-cells", str(cells_path)])
