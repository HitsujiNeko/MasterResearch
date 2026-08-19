"""RQ3のシナリオ別エントリスクリプト（Satellite Only / Limited 等）で共通する、
観測ラベル生成・スケール整合性検証・ランダム分割/Spatial CVでの学習～評価パイプライン
をまとめる共通モジュール。

特徴量列名・目的変数列名はモジュールグローバルな定数ではなく、呼び出し側から明示的に
引数で渡す（`src.common.regression_models` と同じ設計）。これにより、シナリオ
（Satellite Only / Limited / Full）ごとに異なる特徴量集合でも同じ関数を再利用できる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from src.common.model_metrics import summarize_metric_dicts
from src.common.regression_models import fit_linear_regression, fit_random_forest
from src.common.spatial_cv import split_by_spatial_blocks


def build_observation_label(output_stem: str) -> str:
    """出力接頭辞から観測日時ラベルを生成する。

    分析エントリスクリプトの `resolve_output_stem` の戻り値（例:
    `dataset_limited_20230707_032329_hanoi_30m`）に含まれる
    `{8桁の日付}_{6桁の時刻}` を `"2023-07-07 03:23:29"` のような可読な形式へ
    整形する。プロット・SHAP図のタイトルに使うためのラベルであり、ファイル名
    そのもの（`resolve_output_stem` の戻り値）とは用途が異なる。

    Args:
        output_stem: 分析エントリスクリプトの `resolve_output_stem` の戻り値。
    Returns:
        可読な観測日時ラベル。該当パターンが見つからない場合は `output_stem`
        をそのまま返す（プロットタイトルが空になるより分かりやすいため）。
    """
    match = re.search(r"(\d{8})_(\d{6})", output_stem)
    if match is None:
        return output_stem

    raw_date, raw_time = match.groups()
    date_label = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    time_label = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:6]}"
    return f"{date_label} {time_label}"


def validate_scale_matches_dataset(dataset_path: Path, scale: int) -> None:
    """`--scale` とデータセットのファイル名から読み取れる解像度の整合性を検証する。

    分析用データセットGeoPackage自体は解像度を保持しない（`cell_id` のデコード
    結果である row/col はスケール非依存の絶対インデックスであり、その物理サイズ
    はスケールに依存する）。そのため、`--dataset-path` と `--scale` の不一致は
    ファイル名の命名規則（`src.analysis.build_dataset.resolve_dataset_path` が
    付与する末尾の `_{scale}m`）でしか検出できない。不一致のまま実行すると、
    誤ったブロックサイズでSpatial CVが静かに実行されるため、ここで早期に
    検出する。

    Args:
        dataset_path: 分析用データセットGeoPackageのパス。
        scale: `--scale` で指定された正準グリッドの解像度（m）。
    Raises:
        ValueError: ファイル名末尾が `_{scale}m` と一致しない場合。
    """
    expected_suffix = f"_{scale}m"
    if not dataset_path.stem.endswith(expected_suffix):
        raise ValueError(
            f"--scale（{scale}）とデータセットのファイル名（{dataset_path.name}）が"
            f"一致しない可能性があります。ファイル名は「{expected_suffix}」で終わる"
            "ことを想定しています。正しい--scaleを指定するか、対応するデータセットを"
            "指定してください。"
        )


@dataclass(frozen=True)
class RandomSplitResult:
    """ランダム分割による学習・評価結果。

    `dict[str, object]` ではなく型付きの構造体にすることで、キー名の
    打ち間違いを実行時のKeyErrorではなく型チェッカで検出できるようにする。
    標準化係数・重要度は `linear_result` / `rf_result` の中に既に含まれており
    二重管理を避けるため、専用フィールドは持たせない
    （例: 標準化係数は `linear_result["standardized_coefficients"]` で参照する）。

    Attributes:
        x_train: 学習用説明変数。
        x_test: 評価用説明変数。
        linear_result: 線形回帰の評価結果（`metrics` と `standardized_coefficients` を含む）。
        rf_model: 学習済みランダムフォレストモデル。
        rf_result: RFの評価結果（`metrics` / `feature_importance` /
            `permutation_importance` を含む）。
    """

    x_train: pd.DataFrame
    x_test: pd.DataFrame
    linear_result: dict[str, object]
    rf_model: RandomForestRegressor
    rf_result: dict[str, object]


def run_random_split_models(
    sampled: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    random_state: int,
    rf_trees: int,
) -> RandomSplitResult:
    """ランダム分割で線形回帰・RFを学習・評価する。

    Args:
        sampled: フィルタ・サンプリング後のデータ。
        feature_columns: 説明変数の列名リスト（シナリオごとに異なる）。
        target_column: 目的変数の列名（通常 `"LST"`）。
        random_state: 乱数シード。
        rf_trees: RFの決定木本数。
    Returns:
        学習データ・評価結果・学習済みRFモデルを含む構造体。
    """
    x = sampled[feature_columns]
    y = sampled[target_column]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=random_state
    )

    linear_result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
    rf_model, rf_result, _, _, _ = fit_random_forest(
        x_train, x_test, y_train, y_test, random_state=random_state, n_estimators=rf_trees
    )
    return RandomSplitResult(
        x_train=x_train,
        x_test=x_test,
        linear_result=linear_result,
        rf_model=rf_model,
        rf_result=rf_result,
    )


def run_spatial_cv_models(
    sampled: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    block_ids: np.ndarray,
    cv_splits: int,
    random_state: int,
    rf_trees: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    """空間ブロックCVで線形回帰・RFを学習・評価する。

    Args:
        sampled: フィルタ・サンプリング後のデータ。
        feature_columns: 説明変数の列名リスト（シナリオごとに異なる）。
        target_column: 目的変数の列名（通常 `"LST"`）。
        block_ids: `assign_canonical_blocks` の戻り値（サンプルごとのblock_id）。
        cv_splits: 分割数。
        random_state: 乱数シード。
        rf_trees: RFの決定木本数。
    Returns:
        集計結果と、fold別の評価指標データフレームのタプル。
    """
    x = sampled[feature_columns]
    y = sampled[target_column]
    folds = split_by_spatial_blocks(block_ids, n_splits=cv_splits)

    fold_rows: list[dict[str, float | int]] = []
    linear_metrics: list[dict[str, float]] = []
    rf_metrics: list[dict[str, float]] = []
    for fold_index, (train_idx, test_idx) in enumerate(folds, start=1):
        x_train, x_test = x.iloc[train_idx], x.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        linear_result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
        # 各foldではmetricsしか使わないため、permutation importanceの計算は省略する。
        _, rf_result, _, _, _ = fit_random_forest(
            x_train,
            x_test,
            y_train,
            y_test,
            random_state=random_state,
            n_estimators=rf_trees,
            compute_permutation_importance=False,
        )

        linear_metrics.append(linear_result["metrics"])
        rf_metrics.append(rf_result["metrics"])
        fold_rows.append(
            {
                "fold": fold_index,
                "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                "linear_r2": linear_result["metrics"]["r2"],
                "linear_rmse": linear_result["metrics"]["rmse"],
                "linear_mae": linear_result["metrics"]["mae"],
                "rf_r2": rf_result["metrics"]["r2"],
                "rf_rmse": rf_result["metrics"]["rmse"],
                "rf_mae": rf_result["metrics"]["mae"],
            }
        )

    summary = {
        "cv_splits": cv_splits,
        "linear_regression": summarize_metric_dicts(linear_metrics),
        "random_forest": summarize_metric_dicts(rf_metrics),
    }
    return summary, pd.DataFrame(fold_rows)
