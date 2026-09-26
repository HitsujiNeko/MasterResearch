"""分析ランの実行パラメータを `results.json` 用の辞書へまとめる共通モジュール。

RQ3のシナリオ別エントリ（Satellite Only / Limited）は、`main()` で組み立てる
結果辞書の `run_parameters` キーへ本モジュールの戻り値を格納する。両シナリオで
キー名・階層を一致させるため、辞書の組み立てをここに一本化する。

**記録範囲の判断**:

- 記録する: 結果ファイルの他のキーからは読み取れず、かつ分析出力を左右する設定。
  CLI引数では乱数シード（`--random-state`）・RF決定木本数（`--rf-trees`）・
  要求サンプル数（`--sample-size`。0は全件）・正準グリッドの解像度（`--scale`）・
  SHAPの要求サンプル数（`--shap-sample-size` / `--shap-background-size`）。
  CLIで変更できない固定値では、ランダム分割の評価データ割合・RFの
  `min_samples_leaf`・Permutation重要度の反復回数。固定値はコード変更で
  変わりうるため、既定値の変更と同じく結果ファイルからの監査対象に含める。
- 記録しない（重複を避ける）: 既存キーに既に記録されている設定
  （`lst_valid_ratio_threshold`・`spatial_cv.cv_splits`・
  `spatial_cv.block_definition.block_size_m`、Limitedの変数構成等）。
  同じ値を2箇所に持つと、片方だけ更新された場合に食い違うため。
- 記録しない（出力に影響しない）: RF・Permutation重要度の `n_jobs`。
  乱数シード固定の下では並列数を変えても結果は変わらないため。
- 記録しない（範囲外）: 入出力パス（既存の `dataset_path` 等に記録済み）、
  gitコミット・ライブラリ版・入力ハッシュ等の来歴情報（別の仕組みで扱う）。
- 適用範囲: モデル学習まで行うフル実行の `results.json` のみ。Limitedの
  `--diagnose-only` が出力する診断JSONには付与しない（RFを学習しないため
  `rf_trees` 等が意味を持たない）。ただし乱数シード・サンプル数・解像度は
  サンプリングを通じて診断出力（相関・VIF等）にも影響するため、診断JSONからは
  これらを再現・監査できない点に注意する。

`requested_*` は指定値であり、実際に使われた件数（`sample_size`・
`shap.sample_size`・`shap.background_size`）はデータ件数で頭打ちになるため
一致しないことがある。両者を区別できるよう、キー名に `requested_` を付ける。
"""

from __future__ import annotations

import argparse

from src.common.analysis_runs import RANDOM_SPLIT_TEST_FRACTION
from src.common.regression_models import PERMUTATION_N_REPEATS, RF_MIN_SAMPLES_LEAF


def build_run_parameters(
    *,
    random_state: int,
    rf_trees: int,
    requested_sample_size: int,
    scale_m: int,
    requested_shap_sample_size: int,
    requested_shap_background_size: int,
) -> dict[str, int | float]:
    """分析ランの実行パラメータ辞書を作る。

    値を記録するだけで、分析処理には一切関与しない（同じ引数なら分析出力は
    本関数の有無で変わらない）。

    Args:
        random_state: 乱数シード（`--random-state`）。
        rf_trees: ランダムフォレストの決定木本数（`--rf-trees`）。
        requested_sample_size: 要求サンプル数（`--sample-size`。0は全件）。
        scale_m: 正準グリッドの解像度（m。`--scale`）。
        requested_shap_sample_size: SHAP評価サンプルの要求数（`--shap-sample-size`）。
        requested_shap_background_size: SHAP背景データの要求数
            （`--shap-background-size`）。
    Returns:
        `results.json` の `run_parameters` に格納する辞書。CLI引数由来の値と、
        CLIで変更できない固定値（ランダム分割の評価割合・RFの
        `min_samples_leaf`・Permutation重要度の反復回数）を同じ階層に持つ。
    """
    return {
        "random_state": int(random_state),
        "rf_trees": int(rf_trees),
        "requested_sample_size": int(requested_sample_size),
        "scale_m": int(scale_m),
        "requested_shap_sample_size": int(requested_shap_sample_size),
        "requested_shap_background_size": int(requested_shap_background_size),
        "random_split_test_fraction": float(RANDOM_SPLIT_TEST_FRACTION),
        "rf_min_samples_leaf": int(RF_MIN_SAMPLES_LEAF),
        "permutation_n_repeats": int(PERMUTATION_N_REPEATS),
    }


def build_run_parameters_from_args(args: argparse.Namespace) -> dict[str, int | float]:
    """解析済みのCLI引数から実行パラメータ辞書を作る。

    両シナリオの `parse_arguments` が共通して持つ引数名（`random_state`・
    `rf_trees`・`sample_size`・`scale`・`shap_sample_size`・
    `shap_background_size`）を読み、`build_run_parameters` へ渡す。

    Args:
        args: 各シナリオの `parse_arguments` の戻り値。
    Returns:
        `build_run_parameters` の戻り値。
    Raises:
        ValueError: 必要な引数が `args` に存在しない場合。
    """
    required = (
        "random_state",
        "rf_trees",
        "sample_size",
        "scale",
        "shap_sample_size",
        "shap_background_size",
    )
    missing = [name for name in required if not hasattr(args, name)]
    if missing:
        raise ValueError(f"実行パラメータの記録に必要な引数がありません: {missing}")
    return build_run_parameters(
        random_state=args.random_state,
        rf_trees=args.rf_trees,
        requested_sample_size=args.sample_size,
        scale_m=args.scale,
        requested_shap_sample_size=args.shap_sample_size,
        requested_shap_background_size=args.shap_background_size,
    )
