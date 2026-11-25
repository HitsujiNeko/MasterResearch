"""水域率の元データだけが異なる分析ランを、同じ評価セルで比べる。

`build_water_sensitivity_datasets` が作った派生データセット（JRC 版）と、主採用の
データセット（GLC 版）を、同じ評価セル・同じ fold で実行した `analysis_rq3_limited` の
results.json を読み、GLC 版を基準に JRC 版との差を求める（差の向きは JRC 版 − GLC 版）。

出力するもの:
- 評価指標（ランダム分割・Spatial CV）と差、Spatial CV の fold ごとの対応のある差と
  補正 t 区間、変数の寄与と順位（SHAP・Permutation 重要度・不純度重要度・標準化係数）。
  いずれも `lst_emissivity_sensitivity.compare_run_pair` を使う。
- 水域率 `LULC_WATER_COV` に絞った要約。各ランでの寄与の値・順位と、線形回帰の係数の
  符号・大きさ（二重計上の相手になりやすい湿地 `LULC_WETLAND_COV` の標準化係数も並べる）。
  係数は標準化係数に加えて、水域率が 0.1（10 ポイント）増えたときの LST の変化（°C）に
  戻した値を示す。標準化係数は説明変数の標準偏差に比例するため、水域の広さ
  （標準偏差）が違う元データどうしでは、標準化係数の差だけでは効果の大きさの差を読めない。

係数を元の単位へ戻すには学習データの標準偏差が要る。results.json には記録されていないため、
データセットと評価セルから、分析スクリプトと同じ分割（`train_test_split`・同じ乱数シード）を
再現して求める。学習行数が results.json の記録と一致することを確かめる。

精度の優劣ではなく、結論（寄与の順位・係数の符号）が水域データの選択で変わるかを見る。

実行例::

    python -m src.analysis.compare_water_sensitivity \
        --baseline {GLC 版の results.json} \
        --variant jrc_monthly {月次の results.json} \
        --variant jrc_occ50 {Occurrence 50% の results.json} \
        --variant jrc_occ25 {Occurrence 25% の results.json}
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio
from sklearn.model_selection import train_test_split

from src.analysis.compare_common_evaluation import load_result, resolve_recorded_path
from src.analysis.compare_water_sources import WATER_FRACTION_THRESHOLD
from src.analysis.lst_emissivity_sensitivity import (
    IMPORTANCE_FAMILIES,
    compare_run_pair,
    get_nested,
    rank_features,
)
from src.common.analysis_runs import RANDOM_SPLIT_TEST_FRACTION
from src.common.config import PROJECT_ROOT
from src.common.evaluation_cells import CELL_ID_COLUMN, load_evaluation_set
from src.common.paths import (
    resolve_existing_path,
    resolve_relative_to_project_root,
    to_project_relative_string,
)
from src.common.summary import build_provenance, save_summary

SCRIPT_NAME = "src.analysis.compare_water_sensitivity"
# 比較の定義は `src/common/` の外にもあるため監視に加える
WATCH_PATHS: tuple[str, ...] = (
    "src/analysis/lst_emissivity_sensitivity.py",
    "src/analysis/compare_common_evaluation.py",
    "src/analysis/compare_water_sources.py",
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "output" / "limited" / "20220906_032358_water_sensitivity"
)
OUTPUT_PREFIX = "water_sensitivity_comparison"

BASELINE_NAME = "glc"
DIFFERENCE_DIRECTION = "JRC 版 − GLC 版"
WATER_COLUMN = "LULC_WATER_COV"
WETLAND_COLUMN = "LULC_WETLAND_COV"
TARGET_COLUMN = "LST"
COEFFICIENT_FAMILY = "lr_standardized_coefficient"
# 係数を元の単位で示すときの水域率の増分（10 ポイント）
WATER_INCREMENT = 0.1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサを作る。

    Returns:
        パーサ。
    """
    parser = argparse.ArgumentParser(
        description="水域率の元データだけが異なる分析ランを、同じ評価セルで比べる。"
    )
    parser.add_argument("--baseline", type=Path, required=True, help="GLC 版の results.json")
    parser.add_argument(
        "--variant",
        nargs=2,
        action="append",
        required=True,
        metavar=("NAME", "RESULTS_JSON"),
        help="JRC 版の名前と results.json（複数指定可）",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="出力先")
    return parser


def load_evaluation_values(result: dict[str, Any]) -> tuple[pd.DataFrame, list[Path]]:
    """評価セルの水域率と LST を、評価セルの行順で読む。

    Args:
        result: 評価セルを使ったランの results.json。

    Returns:
        (`cell_id`・水域率・LST の表, 読み込んだ入力ファイルのパス)。

    Raises:
        ValueError: 評価セル CSV がランの記録と異なる場合、評価セルがデータセットに無い場合、
            または水域率・LST に欠測がある場合。
    """
    dataset_path = resolve_existing_path(resolve_recorded_path(str(result["dataset_path"])))
    cells_path = resolve_existing_path(
        resolve_recorded_path(get_nested(result, ("evaluation_cells", "path")))
    )
    evaluation_set = load_evaluation_set(cells_path)
    recorded_digest = get_nested(result, ("evaluation_cells", "digest"))
    if evaluation_set.digest != recorded_digest:
        raise ValueError(
            f"評価セル CSV がランの記録と異なります: {cells_path}"
            f"（CSV: {evaluation_set.digest}、ラン: {recorded_digest}）"
        )
    columns = [CELL_ID_COLUMN, WATER_COLUMN, TARGET_COLUMN]
    frame = pyogrio.read_dataframe(dataset_path, columns=columns, read_geometry=False)
    # 行順は標本の抽出・分割の再現に必要なため、評価セルの順にそろえる
    values = frame.set_index(CELL_ID_COLUMN).reindex(evaluation_set.cells[CELL_ID_COLUMN])
    missing = values.isna().any(axis=1)
    if bool(missing.any()):
        raise ValueError(
            f"評価セルのうち {int(missing.sum())} 件で水域率または LST が得られません: "
            f"{dataset_path.name}"
        )
    return values.reset_index(), [dataset_path, cells_path, evaluation_set.metadata_path]


def validate_same_target(baseline: pd.DataFrame, variant: pd.DataFrame, name: str) -> None:
    """2 つのランの評価セルで LST が完全に一致することを確かめる。

    派生データセットは水域列以外を変えないため、一致しなければデータセットの取り違えである。

    Args:
        baseline: GLC 版の評価セルの値。
        variant: JRC 版の評価セルの値。
        name: JRC 版の名前（エラーの表示用）。

    Raises:
        ValueError: セルの並びまたは LST が一致しない場合。
    """
    for column in (CELL_ID_COLUMN, TARGET_COLUMN):
        if not np.array_equal(baseline[column].to_numpy(), variant[column].to_numpy()):
            raise ValueError(f"評価セルの {column} が GLC 版と {name} で一致しません。")


def describe_water_effect(result: dict[str, Any], values: pd.DataFrame) -> dict[str, Any]:
    """1 つのランでの水域率の寄与・順位と、線形回帰の係数を整理する。

    Args:
        result: ランの results.json。
        values: `load_evaluation_values` の表。

    Returns:
        評価セルでの水域率の分布、寄与の種類ごとの値と順位、係数（標準化・元の単位）の辞書。

    Raises:
        ValueError: 再現した学習行数がランの記録と一致しない場合、または学習データの水域率の
            分散が 0 の場合。
    """
    train_index, _ = train_test_split(
        np.arange(len(values)),
        test_size=RANDOM_SPLIT_TEST_FRACTION,
        random_state=int(get_nested(result, ("run_parameters", "random_state"))),
    )
    if len(train_index) != int(result["train_size"]):
        raise ValueError(
            f"再現した学習行数（{len(train_index)}）がランの記録（{result['train_size']}）と"
            "一致しません。"
        )
    train = values.iloc[train_index].astype({WATER_COLUMN: np.float64, TARGET_COLUMN: np.float64})
    # 分析スクリプトの StandardScaler と同じ母標準偏差（ddof=0）を使う
    water_std = float(train[WATER_COLUMN].std(ddof=0))
    target_std = float(train[TARGET_COLUMN].std(ddof=0))
    if water_std == 0:
        raise ValueError("学習データの水域率の分散が 0 のため、係数を元の単位へ戻せません。")

    importance: dict[str, Any] = {}
    for family, (keys, by_abs) in IMPORTANCE_FAMILIES.items():
        contributions = get_nested(result, keys)
        importance[family] = {
            "value": float(contributions[WATER_COLUMN]),
            "rank": rank_features(contributions, by_abs)[WATER_COLUMN],
            "feature_count": len(contributions),
        }
    standardized = importance[COEFFICIENT_FAMILY]["value"]
    water = values[WATER_COLUMN].to_numpy(dtype=np.float64)
    return {
        "evaluation_cells": {
            "mean": float(water.mean()),
            "zero_cell_ratio": float((water == 0).mean()),
            "water_cell_ratio": float((water >= WATER_FRACTION_THRESHOLD).mean()),
        },
        "train_std": {"water": water_std, "lst": target_std},
        "importance": importance,
        "coefficient": {
            "standardized": standardized,
            "sign": int(np.sign(standardized)),
            "lst_change_c_per_increment": (standardized * target_std / water_std * WATER_INCREMENT),
            "increment": WATER_INCREMENT,
            "wetland_standardized": float(
                get_nested(result, IMPORTANCE_FAMILIES[COEFFICIENT_FAMILY][0])[WETLAND_COLUMN]
            ),
        },
    }


def run(baseline_path: Path, variants: Sequence[tuple[str, Path]], output_dir: Path) -> Path:
    """GLC 版と JRC 版のランを比べ、結果を保存する。

    Args:
        baseline_path: GLC 版の results.json。
        variants: (名前, JRC 版の results.json) の並び。
        output_dir: 出力先ディレクトリ。

    Returns:
        結果 JSON のパス。

    Raises:
        ValueError: 名前が重複する・基準の名前と同じ場合、または比較の前提が崩れている場合。
    """
    names = [name for name, _ in variants]
    if len(set(names)) != len(names) or BASELINE_NAME in names:
        raise ValueError(f"ランの名前が重複しています（{BASELINE_NAME} は基準の名前）: {names}")
    baseline_path = resolve_existing_path(baseline_path)
    output_root = resolve_relative_to_project_root(output_dir, project_root=PROJECT_ROOT)

    baseline = load_result(baseline_path)
    baseline_values, inputs = load_evaluation_values(baseline)
    water_effects = {BASELINE_NAME: describe_water_effect(baseline, baseline_values)}

    comparisons: dict[str, Any] = {}
    tables: dict[str, list[pd.DataFrame]] = {"metrics": [], "importance": [], "folds": []}
    for name, path in variants:
        logger.info("%s を GLC 版と比べます。", name)
        variant_path = resolve_existing_path(path)
        summary, pair_tables, pair_inputs = compare_run_pair(name, baseline_path, variant_path)
        comparisons[name] = summary
        for key, table in pair_tables.items():
            tables[key].append(table)
        variant = load_result(variant_path)
        variant_values, value_inputs = load_evaluation_values(variant)
        validate_same_target(baseline_values, variant_values, name)
        effect = describe_water_effect(variant, variant_values)
        effect["coefficient"]["same_sign_as_baseline"] = (
            effect["coefficient"]["sign"] == water_effects[BASELINE_NAME]["coefficient"]["sign"]
        )
        effect["evaluation_cells"]["pearson_with_glc"] = float(
            np.corrcoef(
                baseline_values[WATER_COLUMN].to_numpy(dtype=np.float64),
                variant_values[WATER_COLUMN].to_numpy(dtype=np.float64),
            )[0, 1]
        )
        water_effects[name] = effect
        inputs.extend([*pair_inputs, *value_inputs])

    output_root.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for key, frames in tables.items():
        table_path = output_root / f"{OUTPUT_PREFIX}_{key}.csv"
        pd.concat(frames, ignore_index=True).rename(columns={"scenario": "variant_name"}).to_csv(
            table_path, index=False, encoding="utf-8", lineterminator="\n"
        )
        outputs[f"{key}_csv"] = to_project_relative_string(table_path)
    result = {
        "description": "水域率の元データだけが異なる分析ランの比較（同じ評価セル・同じ fold）。",
        "difference_direction": DIFFERENCE_DIRECTION,
        "water_effects": water_effects,
        "comparisons": comparisons,
        "notes": [
            "どの水域データも真値ではないため、性能の優劣ではなく結論（順位・符号）の頑健性を見る。",
            "他の土地被覆 6 列の扱い（据え置き・正規化）は派生データセットによる。据え置きでは"
            "水域と他クラス（主に湿地）の二重計上が生じるため、水域と湿地の係数を合わせて読む。",
            "元の単位の係数は、標準化係数 × LST の標準偏差 ÷ 水域率の標準偏差"
            "（学習データ・母標準偏差）で求めた。",
            "target_distribution は評価セルではなく各データセットの有効母集団の分布で、"
            "GLC 版と JRC 版で母数が異なる。",
        ],
        "outputs": outputs,
        "provenance": build_provenance(
            SCRIPT_NAME, dict.fromkeys(inputs), extra_watch_paths=WATCH_PATHS
        ),
    }
    result_path = output_root / f"{OUTPUT_PREFIX}_results.json"
    save_summary(result, result_path)
    return result_path


def main(argv: Sequence[str] | None = None) -> None:
    """比較を実行する。

    Args:
        argv: 引数列。None の場合は `sys.argv` を使う。
    """
    args = build_argument_parser().parse_args(argv)
    result_path = run(
        args.baseline, [(name, Path(path)) for name, path in args.variant], args.output_dir
    )
    logger.info("比較結果を保存しました: %s", result_path)


if __name__ == "__main__":
    main()
