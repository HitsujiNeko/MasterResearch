"""共通評価セルで評価した Satellite Only と Limited の性能差を、fold ごとの対応のある差で比べる。

両シナリオを同じ評価セル（`--evaluation-cells`）で実行した2つの results.json を読み、
次を出力する（差の向きはいずれも **Limited − Satellite Only**。R² が正なら Limited が良い）。

- **Spatial CV**: fold ごとの差 d_k（RF・線形回帰の R²・RMSE・MAE）と、平均差の
  素朴 t 区間・補正 t 区間（`src.common.cv_paired_comparison`）。補正版を主とし、
  素朴版は参考として併記する（fold どうしは学習データを共有し独立ではないため）
- **ランダム分割**: 差の点推定のみ。テスト集合が1つで fold が無く、区間を作れない

比べる前に、両者が同じ評価セル（内容ダイジェスト）・同じ乱数シードで評価された
ことと、fold ごとの学習行数・テスト行数が一致することを確かめる。

既定の入力は、既定の引数で生成した評価セルを使った両スクリプトの出力
（各スクリプトの出力名の規則から求める）である。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.analysis import analysis_rq3_limited as limited
from src.analysis import analysis_rq3_satellite_only as satellite_only
from src.analysis.build_common_evaluation_set import resolve_default_cells_path
from src.common.config import PROJECT_ROOT
from src.common.cv_paired_comparison import (
    compute_fold_differences,
    summarize_metric_differences,
)
from src.common.evaluation_cells import (
    resolve_evaluation_output_dir,
    resolve_evaluation_output_stem,
)
from src.common.paths import to_project_relative_string
from src.common.summary import build_provenance, save_summary

RANDOM_SPLIT_MODELS = ("linear_regression", "random_forest")
RANDOM_SPLIT_METRICS = ("r2", "rmse", "mae")
DIFFERENCE_DIRECTION = "Limited − Satellite Only"


def resolve_default_result_paths(cells_path: Path) -> tuple[Path, Path]:
    """既定の引数・指定の評価セルで実行した両スクリプトの results.json のパスを求める。

    Args:
        cells_path: 評価セル CSV のパス。
    Returns:
        （Satellite Only の results.json, Limited の results.json）のタプル。
    """
    satellite_defaults = satellite_only.parse_arguments([])
    satellite_stem = resolve_evaluation_output_stem(
        satellite_only.resolve_output_stem(
            satellite_defaults.dataset_path, satellite_defaults.analysis_area
        ),
        cells_path,
    )
    limited_defaults = limited.parse_arguments([])
    limited_stem = resolve_evaluation_output_stem(
        limited.resolve_output_stem(
            limited_defaults.dataset_path,
            limited_defaults.variable_set,
            limited_defaults.population_source,
            limited_defaults.require_valid_gis_mask,
            limited_defaults.building_height,
            limited_defaults.water_index,
            limited_defaults.analysis_area,
        ),
        cells_path,
    )
    return (
        resolve_evaluation_output_dir(satellite_only.DEFAULT_OUTPUT_DIR)
        / f"{satellite_stem}_results.json",
        resolve_evaluation_output_dir(limited.DEFAULT_OUTPUT_DIR) / f"{limited_stem}_results.json",
    )


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        解析結果。未指定の入出力パスは既定の評価セルから補う。
    """
    parser = argparse.ArgumentParser(
        description="共通評価セルでの Satellite Only と Limited の性能差を fold ごとに比べる"
    )
    parser.add_argument(
        "--evaluation-cells",
        type=Path,
        default=resolve_default_cells_path(),
        help="評価セル CSV（既定の入力パス・出力先を求めるのに使う）",
    )
    parser.add_argument("--satellite-only-results", type=Path, default=None)
    parser.add_argument("--limited-results", type=Path, default=None)
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            "出力 JSON（既定は評価セルと同じディレクトリの"
            "scenario_comparison_{CSV の stem}_results.json）"
        ),
    )
    parser.add_argument("--confidence", type=float, default=0.95, help="信頼係数")
    args = parser.parse_args(argv)
    default_satellite, default_limited = resolve_default_result_paths(args.evaluation_cells)
    if args.satellite_only_results is None:
        args.satellite_only_results = default_satellite
    if args.limited_results is None:
        args.limited_results = default_limited
    if args.output_path is None:
        args.output_path = args.evaluation_cells.with_name(
            f"scenario_comparison_{args.evaluation_cells.stem}_results.json"
        )
    return args


def resolve_recorded_path(recorded: str) -> Path:
    """results.json に記録されたパス（プロジェクト相対または絶対）を解決する。

    Args:
        recorded: 記録されたパス文字列。
    Returns:
        絶対パス。
    """
    path = Path(recorded)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_result(result_path: Path) -> dict[str, Any]:
    """results.json を読み、評価セルを使ったランであることを確かめる。

    Args:
        result_path: results.json のパス。
    Returns:
        読み込んだ辞書。
    Raises:
        FileNotFoundError: ファイルが無い場合。
        ValueError: 評価セルを使わずに実行した結果の場合。
    """
    if not result_path.is_file():
        raise FileNotFoundError(f"結果ファイルが見つかりません: {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("evaluation_cells"):
        raise ValueError(
            f"評価セル（--evaluation-cells）を使わずに実行した結果です: {result_path}。"
            "対応のある差は同じ評価セルで評価した結果どうしでのみ求められます。"
        )
    return result


def validate_same_evaluation(
    satellite_result: dict[str, Any], limited_result: dict[str, Any]
) -> None:
    """2つの結果が同じ評価セル・同じ乱数シードで評価されたことを確かめる。

    Args:
        satellite_result: Satellite Only の results.json。
        limited_result: Limited の results.json。
    Returns:
        None
    Raises:
        ValueError: 評価セルの内容ダイジェスト・乱数シード・ランダム分割の行数の
            いずれかが一致しない場合。
    """
    checks = {
        "evaluation_cells.digest": (
            satellite_result["evaluation_cells"]["digest"],
            limited_result["evaluation_cells"]["digest"],
        ),
        "run_parameters.random_state": (
            satellite_result["run_parameters"]["random_state"],
            limited_result["run_parameters"]["random_state"],
        ),
        "train_size": (satellite_result["train_size"], limited_result["train_size"]),
        "test_size": (satellite_result["test_size"], limited_result["test_size"]),
    }
    mismatched = {key: values for key, values in checks.items() if values[0] != values[1]}
    if mismatched:
        raise ValueError(f"2つの結果が同じ評価セル・同じ条件で評価されていません: {mismatched}")


def compare_random_split(
    satellite_result: dict[str, Any], limited_result: dict[str, Any]
) -> dict[str, Any]:
    """ランダム分割の評価指標の差（点推定のみ）を求める。

    Args:
        satellite_result: Satellite Only の results.json。
        limited_result: Limited の results.json。
    Returns:
        モデルごと・指標ごとの両者の値と差の辞書。
    """
    comparison: dict[str, Any] = {}
    for model in RANDOM_SPLIT_MODELS:
        satellite_metrics = satellite_result["random_split"][model]["metrics"]
        limited_metrics = limited_result["random_split"][model]["metrics"]
        comparison[model] = {
            metric: {
                "satellite_only": satellite_metrics[metric],
                "limited": limited_metrics[metric],
                "difference": limited_metrics[metric] - satellite_metrics[metric],
            }
            for metric in RANDOM_SPLIT_METRICS
        }
    comparison["note"] = (
        "ランダム分割はテスト集合が1つで fold が無く区間を作れないため、差の点推定のみを示す。"
    )
    return comparison


def main(argv: list[str] | None = None) -> None:
    """2つの results.json から対応のある差と信頼区間を求めて保存する。

    Args:
        argv: 引数リスト（`None` なら `sys.argv` を使う）。
    Returns:
        None
    """
    args = parse_arguments(argv)
    satellite_path = args.satellite_only_results.resolve()
    limited_path = args.limited_results.resolve()
    satellite_result = load_result(satellite_path)
    limited_result = load_result(limited_path)
    validate_same_evaluation(satellite_result, limited_result)

    satellite_folds_path = resolve_recorded_path(
        satellite_result["spatial_cv"]["outputs"]["fold_metrics_csv"]
    )
    limited_folds_path = resolve_recorded_path(
        limited_result["spatial_cv"]["outputs"]["fold_metrics_csv"]
    )
    differences = compute_fold_differences(
        pd.read_csv(satellite_folds_path), pd.read_csv(limited_folds_path)
    )
    output_path = args.output_path.resolve()
    folds_path = output_path.with_name(output_path.name.replace("_results.json", "_folds.csv"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    differences.to_csv(folds_path, index=False)

    cells_path = resolve_recorded_path(satellite_result["evaluation_cells"]["path"])
    comparison = {
        "description": "共通評価セルでの Satellite Only と Limited の性能差（対応のある差）。",
        "difference_direction": DIFFERENCE_DIRECTION,
        "inputs": {
            "satellite_only_results": to_project_relative_string(satellite_path),
            "limited_results": to_project_relative_string(limited_path),
            "evaluation_cells": to_project_relative_string(cells_path),
            "evaluation_cells_digest": satellite_result["evaluation_cells"]["digest"],
        },
        "limited_configuration": {
            key: limited_result.get(key)
            for key in (
                "variable_set",
                "building_height_mode",
                "water_index_mode",
                "population_sources",
                "features",
            )
        },
        "satellite_only_features": satellite_result.get("features"),
        "spatial_cv": {
            **summarize_metric_differences(differences, confidence=args.confidence),
            "fold_differences_csv": to_project_relative_string(folds_path),
            "interval_note": (
                "corrected は補正 t 区間（分散 (1/J + ρ)·s²、自由度 J−1、J は fold 数）で主とする。"
                "naive は fold を独立とみなした区間で、狭く出すぎるため参考値。"
            ),
        },
        "random_split": compare_random_split(satellite_result, limited_result),
    }
    print("来歴メタデータ（入力ファイルのハッシュ等）を記録します。")
    comparison["provenance"] = build_provenance(
        "src.analysis.compare_common_evaluation",
        input_paths=[
            satellite_path,
            limited_path,
            satellite_folds_path,
            limited_folds_path,
            cells_path,
        ],
    )
    save_summary(comparison, output_path)
    printable = {key: value for key, value in comparison.items() if key != "provenance"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"比較結果を保存しました: {output_path}")


if __name__ == "__main__":
    main()
