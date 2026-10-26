"""src/analysis/compare_common_evaluation.py（2シナリオの対応のある差）のテスト。

2つの results.json と fold 別指標 CSV を一時ディレクトリに合成して、検証・差の向き・
保存物を確かめる。区間の計算そのものは tests/common/test_cv_paired_comparison.py で
検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.compare_common_evaluation import (
    main,
    resolve_default_result_paths,
    validate_same_evaluation,
)
from src.common.cv_paired_comparison import FOLD_METRIC_COLUMNS


def _write_result(
    tmp_path: Path, name: str, offset: float, digest: str = "abc", random_state: int = 42
) -> Path:
    """fold 別指標 CSV と results.json を書き、results.json のパスを返す。"""
    folds = pd.DataFrame({"fold": [1, 2, 3], "train_size": [70, 60, 70], "test_size": [30, 40, 30]})
    for column in FOLD_METRIC_COLUMNS:
        folds[column] = np.array([0.5, 0.6, 0.7]) + offset
    folds_path = tmp_path / f"{name}_spatial_cv_folds.csv"
    folds.to_csv(folds_path, index=False)
    cells_path = tmp_path / "evaluation_cells_seed42.csv"
    cells_path.write_text("cell_id,block_id,fold\n1,1,1\n", encoding="utf-8")
    metrics = {"r2": 0.7 + offset, "rmse": 1.0 - offset, "mae": 0.8 - offset}
    result = {
        "scenario": name,
        "features": ["A"],
        "train_size": 80,
        "test_size": 20,
        "run_parameters": {"random_state": random_state},
        "evaluation_cells": {"digest": digest, "path": str(cells_path)},
        "random_split": {
            "linear_regression": {"metrics": metrics},
            "random_forest": {"metrics": metrics},
        },
        "spatial_cv": {"outputs": {"fold_metrics_csv": str(folds_path)}},
    }
    result_path = tmp_path / f"{name}_results.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path


def _argv(tmp_path: Path, satellite: Path, limited: Path) -> list[str]:
    """main() の引数を組み立てる。"""
    return [
        "--evaluation-cells",
        str(tmp_path / "evaluation_cells_seed42.csv"),
        "--satellite-only-results",
        str(satellite),
        "--limited-results",
        str(limited),
    ]


class TestDefaultPaths:
    """既定の入力パスのテスト（各スクリプトの出力名の規則に従う）。"""

    def test_default_results_follow_evaluation_output_names(self) -> None:
        """既定は両スクリプトの _common_evaluation ディレクトリ・評価セル名付きの results.json。"""
        satellite, limited = resolve_default_result_paths(Path("x/evaluation_cells_seed42.csv"))

        assert satellite.parent.name == "20220906_032358_common_evaluation"
        assert satellite.name == (
            "dataset_satellite_only_20220906_032358_hanoi_30m_evaluation_cells_seed42_results.json"
        )
        assert limited.parent.parent.name == "limited"
        assert limited.name.endswith("_both_bh_mean_wi_none_evaluation_cells_seed42_results.json")


class TestMain:
    """main() のテスト。"""

    def test_saves_paired_differences_limited_minus_satellite(self, tmp_path: Path) -> None:
        """差は Limited − Satellite Only で、区間・ランダム分割の点推定・来歴を保存する。"""
        satellite = _write_result(tmp_path, "satellite_only", 0.0)
        limited = _write_result(tmp_path, "limited", 0.05)

        main(_argv(tmp_path, satellite, limited))

        output = tmp_path / "scenario_comparison_evaluation_cells_seed42_results.json"
        comparison = json.loads(output.read_text(encoding="utf-8"))
        rf_r2 = comparison["spatial_cv"]["metrics"]["rf_r2"]
        assert rf_r2["mean_difference"] == pytest.approx(0.05)
        assert rf_r2["n_splits"] == 3
        assert comparison["spatial_cv"]["test_train_ratio"] == pytest.approx(
            np.mean([30 / 70, 40 / 60, 30 / 70])
        )
        random_r2 = comparison["random_split"]["random_forest"]["r2"]
        assert random_r2["difference"] == pytest.approx(0.05)
        assert "fold" not in comparison["random_split"]
        folds = pd.read_csv(tmp_path / "scenario_comparison_evaluation_cells_seed42_folds.csv")
        np.testing.assert_allclose(folds["rf_r2"], 0.05)
        assert len(comparison["provenance"]["inputs"]) == 5

    def test_stops_when_evaluation_cells_differ(self, tmp_path: Path) -> None:
        """評価セルのダイジェストが違えば停止する。"""
        satellite = _write_result(tmp_path, "satellite_only", 0.0, digest="abc")
        limited = _write_result(tmp_path, "limited", 0.05, digest="xyz")

        with pytest.raises(ValueError, match="digest"):
            main(_argv(tmp_path, satellite, limited))

    def test_stops_for_result_without_evaluation_cells(self, tmp_path: Path) -> None:
        """評価セルを使わずに実行した結果は比べない。"""
        satellite = _write_result(tmp_path, "satellite_only", 0.0)
        data = json.loads(satellite.read_text(encoding="utf-8"))
        data["evaluation_cells"] = None
        satellite.write_text(json.dumps(data), encoding="utf-8")
        limited = _write_result(tmp_path, "limited", 0.05)

        with pytest.raises(ValueError, match="evaluation-cells"):
            main(_argv(tmp_path, satellite, limited))


class TestValidateSameEvaluation:
    """validate_same_evaluation のテスト。"""

    def test_rejects_different_random_state(self, tmp_path: Path) -> None:
        """乱数シードが違えば（ランダム分割の train/test が揃わない）停止する。"""
        satellite = json.loads(
            _write_result(tmp_path, "satellite_only", 0.0).read_text(encoding="utf-8")
        )
        limited = json.loads(
            _write_result(tmp_path, "limited", 0.0, random_state=7).read_text(encoding="utf-8")
        )

        with pytest.raises(ValueError, match="random_state"):
            validate_same_evaluation(satellite, limited)
