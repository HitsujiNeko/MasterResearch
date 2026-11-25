"""compare_water_sensitivity.py（水域率の元データが異なるランの比較）のテスト。

合成のデータセット・評価セル・results.json を書き、係数を元の単位へ戻す計算は
標準化しない線形回帰の係数と突き合わせて検算する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio
import pytest
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

from src.analysis import compare_water_sensitivity as target
from src.common.analysis_runs import RANDOM_SPLIT_TEST_FRACTION
from src.common.config import PROJECT_ROOT
from src.common.evaluation_cells import (
    EVALUATION_CELLS_COLUMNS,
    METADATA_CELLS_KEY,
    METADATA_SETTING_KEYS,
    compute_evaluation_cells_digest,
    resolve_metadata_path,
)
from src.common.regression_models import fit_linear_regression

N_CELLS = 200
RANDOM_STATE = 42


def build_cells(tmp_path: Path) -> tuple[Path, pd.DataFrame, str]:
    """評価セル CSV とメタデータを書く（データセットとは異なる行順にする）。"""
    order = np.random.default_rng(1).permutation(N_CELLS) + 1
    cells = pd.DataFrame(
        {column: np.zeros(N_CELLS, np.int64) for column in EVALUATION_CELLS_COLUMNS}
    )
    cells["cell_id"] = order
    cells_path = tmp_path / "evaluation_cells_seed42.csv"
    cells.to_csv(cells_path, index=False)
    digest = compute_evaluation_cells_digest(cells)
    metadata: dict[str, Any] = {key: 1 for key in METADATA_SETTING_KEYS}
    metadata[METADATA_CELLS_KEY] = {"digest": digest}
    resolve_metadata_path(cells_path).write_text(json.dumps(metadata), encoding="utf-8")
    return cells_path, cells, digest


def build_dataset() -> pd.DataFrame:
    """水域率と NDBI から LST が決まる合成データセットを作る（評価セル外の行も含む）。"""
    rng = np.random.default_rng(0)
    water = rng.random(N_CELLS + 5)
    ndbi = rng.normal(size=N_CELLS + 5)
    lst = 30.0 + 2.0 * ndbi - 4.0 * water + rng.normal(scale=0.1, size=N_CELLS + 5)
    return pd.DataFrame(
        {
            "cell_id": np.arange(1, N_CELLS + 6),
            "LULC_WATER_COV": water.astype(np.float32),
            "LULC_WETLAND_COV": ndbi.astype(np.float32),
            "LST": lst.astype(np.float32),
        }
    )


def build_run(
    tmp_path: Path, name: str, dataset: pd.DataFrame, **overrides: Any
) -> tuple[Path, dict[str, Any]]:
    """合成データセットで線形回帰を実行し、results.json・fold CSV を書く。"""
    cells_path, cells, digest = build_cells(tmp_path)
    dataset_path = tmp_path / f"{name}.gpkg"
    pyogrio.write_dataframe(dataset, dataset_path, layer=name, driver="GPKG")
    sampled = dataset.set_index("cell_id").loc[cells["cell_id"]].reset_index()
    features = ["LULC_WATER_COV", "LULC_WETLAND_COV"]
    x_train, x_test, y_train, y_test = train_test_split(
        sampled[features],
        sampled["LST"],
        test_size=RANDOM_SPLIT_TEST_FRACTION,
        random_state=RANDOM_STATE,
    )
    linear, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
    folds_path = tmp_path / f"{name}_folds.csv"
    pd.DataFrame(
        {
            "fold": [1, 2],
            "train_size": [80, 80],
            "test_size": [20, 20],
            **{
                f"{model}_{metric}": [0.7, 0.8]
                for model in ("linear", "rf")
                for metric in ("r2", "rmse", "mae")
            },
        }
    ).to_csv(folds_path, index=False)
    importance = {"LULC_WATER_COV": 0.1, "LULC_WETLAND_COV": 1.0}
    cv = {"r2_mean": 0.7, "rmse_mean": 1.0, "mae_mean": 0.8}
    result: dict[str, Any] = {
        "dataset_path": str(dataset_path),
        "features": features,
        "train_size": len(x_train),
        "test_size": len(x_test),
        "evaluation_cells": {"path": str(cells_path), "digest": digest},
        "run_parameters": {"random_state": RANDOM_STATE, "rf_trees": 300},
        "random_split": {
            "linear_regression": linear,
            "random_forest": {
                "metrics": {"r2": 0.8, "rmse": 1.0, "mae": 0.7},
                "feature_importance": importance,
                "permutation_importance": importance,
            },
        },
        "spatial_cv": {
            "linear_regression": cv,
            "random_forest": cv,
            "outputs": {"fold_metrics_csv": str(folds_path)},
        },
        "shap": {"mean_abs_shap": importance},
        "filter_dropout": {"target_distribution": {"after": {"mean": 32.0}}},
    }
    result.update(overrides)
    result_path = tmp_path / f"{name}_results.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path, result


def test_coefficient_is_restored_to_original_units(tmp_path: Path) -> None:
    """元の単位の係数が、標準化しない線形回帰の係数 × 0.1 と一致する。"""
    dataset = build_dataset()
    _, result = build_run(tmp_path, "glc", dataset)
    values, inputs = target.load_evaluation_values(result)

    effect = target.describe_water_effect(result, values)

    cells = values["cell_id"]
    sampled = dataset.set_index("cell_id").loc[cells].astype(np.float64)
    x_train, _, y_train, _ = train_test_split(
        sampled[["LULC_WATER_COV", "LULC_WETLAND_COV"]],
        sampled["LST"],
        test_size=RANDOM_SPLIT_TEST_FRACTION,
        random_state=RANDOM_STATE,
    )
    raw = LinearRegression().fit(x_train, y_train).coef_[0]
    assert effect["coefficient"]["lst_change_c_per_increment"] == pytest.approx(raw * 0.1, rel=1e-4)
    assert effect["coefficient"]["sign"] == -1
    assert effect["importance"]["shap_mean_abs"] == {
        "value": 0.1,
        "rank": 2,
        "feature_count": 2,
    }
    assert len(inputs) == 3


def test_run_writes_comparison(tmp_path: Path) -> None:
    """水域列だけが違うランを比べ、差・水域率の要約・来歴を書く。"""
    glc_path, _ = build_run(tmp_path, "glc", build_dataset())
    variant_data = build_dataset()
    variant_data["LULC_WATER_COV"] = (variant_data["LULC_WATER_COV"] * 0.5).astype(np.float32)
    jrc_path, _ = build_run(tmp_path, "jrc", variant_data)

    result_path = target.run(glc_path, [("jrc_monthly", jrc_path)], tmp_path / "out")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    effects = result["water_effects"]
    assert list(effects) == ["glc", "jrc_monthly"]
    # 水域率を半分にすると標準化係数は変わらず、元の単位の係数は 2 倍になる
    assert effects["jrc_monthly"]["coefficient"]["standardized"] == pytest.approx(
        effects["glc"]["coefficient"]["standardized"], rel=1e-4
    )
    assert effects["jrc_monthly"]["coefficient"]["lst_change_c_per_increment"] == pytest.approx(
        2 * effects["glc"]["coefficient"]["lst_change_c_per_increment"], rel=1e-3
    )
    assert effects["jrc_monthly"]["coefficient"]["same_sign_as_baseline"] is True
    assert effects["jrc_monthly"]["evaluation_cells"]["pearson_with_glc"] == pytest.approx(1.0)
    assert "spatial_cv_paired" in result["comparisons"]["jrc_monthly"]
    table = pd.read_csv(tmp_path / "out" / "water_sensitivity_comparison_importance.csv")
    assert set(table["variant_name"]) == {"jrc_monthly"}
    # 評価セルの入力が重複して記録されないこと
    paths = [record["path"] for record in result["provenance"]["inputs"]]
    assert len(paths) == len(set(paths)) == 8


def test_run_rejects_different_target(tmp_path: Path) -> None:
    """LST が異なるデータセットのランは、取り違えとして拒否する。"""
    glc_path, _ = build_run(tmp_path, "glc", build_dataset())
    other = build_dataset()
    other["LST"] += 1.0
    jrc_path, _ = build_run(tmp_path, "jrc", other)

    with pytest.raises(ValueError, match="LST が GLC 版と"):
        target.run(glc_path, [("jrc_monthly", jrc_path)], tmp_path / "out")


def test_run_rejects_duplicate_names(tmp_path: Path) -> None:
    """ランの名前の重複と、基準と同じ名前を拒否する。"""
    for names in (["a", "a"], ["glc"]):
        with pytest.raises(ValueError, match="名前が重複"):
            target.run(tmp_path / "x", [(name, tmp_path / "x") for name in names], tmp_path)


def test_rejects_missing_water(tmp_path: Path) -> None:
    """評価セルに水域率の欠測があれば停止する（共通セルの外のセルが混ざっている）。"""
    dataset = build_dataset()
    _, result = build_run(tmp_path, "glc", dataset)
    dataset.loc[0, "LULC_WATER_COV"] = np.nan
    pyogrio.write_dataframe(dataset, tmp_path / "glc.gpkg", layer="glc", driver="GPKG")

    with pytest.raises(ValueError, match="1 件で水域率または LST"):
        target.load_evaluation_values(result)


def test_rejects_different_cells_digest(tmp_path: Path) -> None:
    """ランの記録と異なる評価セル CSV は拒否する。"""
    _, result = build_run(tmp_path, "glc", build_dataset())
    result["evaluation_cells"]["digest"] = "other"

    with pytest.raises(ValueError, match="ランの記録と異なります"):
        target.load_evaluation_values(result)


def test_rejects_train_size_mismatch_and_constant_water(tmp_path: Path) -> None:
    """学習行数が記録と合わない・水域率の分散が 0 の場合は停止する。"""
    _, result = build_run(tmp_path, "glc", build_dataset())
    values, _ = target.load_evaluation_values(result)

    with pytest.raises(ValueError, match="学習行数"):
        target.describe_water_effect({**result, "train_size": 1}, values)
    with pytest.raises(ValueError, match="分散が 0"):
        target.describe_water_effect(result, values.assign(LULC_WATER_COV=0.0))


def test_argument_parser_collects_variants() -> None:
    """--variant を複数指定でき、省略すると停止する。"""
    parser = target.build_argument_parser()
    args = parser.parse_args(["--baseline", "g", "--variant", "a", "x", "--variant", "b", "y"])

    assert args.variant == [["a", "x"], ["b", "y"]]
    with pytest.raises(SystemExit):
        parser.parse_args(["--baseline", "g"])


def test_watch_paths_exist() -> None:
    """追加監視パスはすべて実在するファイルを指す。"""
    missing = [path for path in target.WATCH_PATHS if not (PROJECT_ROOT / path).is_file()]

    assert missing == []
