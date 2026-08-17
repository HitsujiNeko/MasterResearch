"""回帰モデル（線形回帰・ランダムフォレスト）の学習と評価を行う共通モジュール。

特徴量名はモジュールグローバルな定数ではなく、渡された `x_train.columns` から
取得する。これにより、シナリオ（Satellite Only / Limited / Full）ごとに
異なる特徴量集合でも同じ関数を再利用できる。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from src.common.model_metrics import compute_metrics


def _validate_matching_columns(x_train: pd.DataFrame, x_test: pd.DataFrame) -> None:
    """学習用・評価用の説明変数の列（特徴量名・順序）が一致することを確認する。

    列が食い違ったまま標準化・モデル学習を行うと、列の意味を取り違えたまま
    数値だけが計算されてしまい、原因の分かりにくい誤った結果になるため、
    処理の入口で検証する。

    Args:
        x_train: 学習用説明変数。
        x_test: 評価用説明変数。
    Raises:
        ValueError: 列（名前・順序）が一致しない場合。
    """
    if list(x_train.columns) != list(x_test.columns):
        raise ValueError(
            "x_trainとx_testの列（特徴量名・順序）が一致していません: "
            f"{list(x_train.columns)} vs {list(x_test.columns)}"
        )


def fit_linear_regression(
    x_train: pd.DataFrame,
    x_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
) -> tuple[dict[str, object], dict[str, float], np.ndarray]:
    """標準化した線形回帰モデルを学習し、評価結果を返す。

    説明変数（X）・目的変数（y）の両方を標準化する。得られる係数は
    sd(y)/sd(x) 単位の標準化偏回帰係数であり、Xのみ標準化する実装とは
    値が異なる点に注意（R²/RMSE/MAEはどちらの実装でも一致する）。

    Args:
        x_train: 学習用説明変数。
        x_test: 評価用説明変数（x_trainと同じ列・順序である必要がある）。
        y_train: 学習用目的変数。
        y_test: 評価用目的変数。
    Returns:
        評価結果辞書（`metrics` と `standardized_coefficients` を含む）、
        標準化係数辞書、予測値のタプル。
    Raises:
        ValueError: x_trainとx_testの列が一致しない場合。
    """
    _validate_matching_columns(x_train, x_test)
    feature_names = list(x_train.columns)

    x_scaler = StandardScaler()
    y_scaler = StandardScaler()

    x_train_scaled = x_scaler.fit_transform(x_train)
    x_test_scaled = x_scaler.transform(x_test)
    y_train_scaled = y_scaler.fit_transform(y_train.to_numpy().reshape(-1, 1)).ravel()

    model = LinearRegression()
    model.fit(x_train_scaled, y_train_scaled)

    y_pred_scaled = model.predict(x_test_scaled)
    y_pred = y_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).ravel()

    standardized_coefficients = {
        feature: float(coef) for feature, coef in zip(feature_names, model.coef_, strict=True)
    }
    result = {
        "metrics": compute_metrics(y_test, y_pred),
        "standardized_coefficients": standardized_coefficients,
    }
    return result, standardized_coefficients, y_pred


def fit_random_forest(
    x_train: pd.DataFrame,
    x_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    random_state: int,
    n_estimators: int,
) -> tuple[
    RandomForestRegressor, dict[str, object], dict[str, float], dict[str, float], np.ndarray
]:
    """ランダムフォレスト回帰を学習し、評価と重要度を返す。

    Args:
        x_train: 学習用説明変数。
        x_test: 評価用説明変数（x_trainと同じ列・順序である必要がある）。
        y_train: 学習用目的変数。
        y_test: 評価用目的変数。
        random_state: 乱数シード（モデル学習・permutation importance共通）。
        n_estimators: 決定木本数。
    Returns:
        学習済みモデル、評価結果、不純度ベース重要度、Permutation重要度、
        予測値のタプル。
    Raises:
        ValueError: x_trainとx_testの列が一致しない場合。
    """
    _validate_matching_columns(x_train, x_test)
    feature_names = list(x_train.columns)

    model = RandomForestRegressor(
        n_estimators=n_estimators,
        min_samples_leaf=5,
        random_state=random_state,
        n_jobs=1,
    )
    model.fit(x_train, y_train)
    y_pred = model.predict(x_test)

    impurity_importance = {
        feature: float(score)
        for feature, score in zip(feature_names, model.feature_importances_, strict=True)
    }

    permutation = permutation_importance(
        model,
        x_test,
        y_test,
        n_repeats=10,
        random_state=random_state,
        n_jobs=1,
    )
    permutation_scores = {
        feature: float(score)
        for feature, score in zip(feature_names, permutation.importances_mean, strict=True)
    }

    result = {
        "metrics": compute_metrics(y_test, y_pred),
        "feature_importance": impurity_importance,
        "permutation_importance": permutation_scores,
    }
    return model, result, impurity_importance, permutation_scores, y_pred
