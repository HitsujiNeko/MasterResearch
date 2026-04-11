# 作成者: GitHub Copilot
# 作成日: 2026-04-08
# 概要: RQ3の衛星データのみシナリオを対象に、ランダム分割・Spatial CV・SHAPで評価する。
"""RQ3の衛星データのみシナリオを評価するスクリプト。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONDA_ROOT = PROJECT_ROOT / ".conda"
CONDA_PATH_PREFIX = [
    str(CONDA_ROOT),
    str(CONDA_ROOT / "Library" / "bin"),
    str(CONDA_ROOT / "Scripts"),
]
os.environ["PATH"] = os.pathsep.join([*CONDA_PATH_PREFIX, os.environ.get("PATH", "")])

import matplotlib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, train_test_split
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "csv" / "analysis"
COORD_COLUMNS = ["lon", "lat"]
FEATURE_COLUMNS = ["NDVI", "NDBI", "NDWI"]
TARGET_COLUMN = "LST"
ALL_COLUMNS = [*COORD_COLUMNS, TARGET_COLUMN, *FEATURE_COLUMNS]


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        なし
    Returns:
        argparse.Namespace: 解析済みの引数オブジェクト
    """
    parser = argparse.ArgumentParser(
        description="Run Satellite Only analysis with random split, Spatial CV, and SHAP."
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "satellite_only_20230707_20230707_032329Z_dataset.csv",
    )
    parser.add_argument("--sample-size", type=int, default=100_000)
    parser.add_argument("--chunksize", type=int, default=200_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cv-splits", type=int, default=5)
    parser.add_argument("--spatial-bins", type=int, default=8)
    parser.add_argument("--shap-sample-size", type=int, default=2_000)
    parser.add_argument("--shap-background-size", type=int, default=500)
    parser.add_argument("--rf-trees", type=int, default=300)
    return parser.parse_args()


def infer_dataset_read_kwargs(dataset_path: Path) -> dict:
    """CSVヘッダー有無を判定し、読み込み引数を返す。

    Args:
        dataset_path (Path): 入力CSVのパス
    Returns:
        dict: pandas.read_csvに渡す追加引数
    """
    with dataset_path.open("r", encoding="utf-8") as file:
        first_line = file.readline().strip()

    expected_header = ",".join(ALL_COLUMNS)
    if first_line == expected_header:
        return {}

    return {"header": None, "names": ALL_COLUMNS}


def build_priority_sample(
    dataset_path: Path,
    sample_size: int,
    chunksize: int,
    random_state: int,
) -> pd.DataFrame:
    """大規模CSVから優先度サンプリングで一様サンプルを作成する。

    Args:
        dataset_path (Path): 入力CSVのパス
        sample_size (int): 最終的に抽出するサンプル数
        chunksize (int): 1回あたりの読み込み行数
        random_state (int): 乱数シード
    Returns:
        pd.DataFrame: サンプリング後のデータフレーム
    """
    rng = np.random.default_rng(random_state)
    sampled: pd.DataFrame | None = None
    csv_kwargs = infer_dataset_read_kwargs(dataset_path)

    # 全チャンクに乱数優先度を付与し、優先度上位のみ保持することで
    # メモリ使用量を抑えながら全体からの一様抽出を近似する。
    for chunk in pd.read_csv(dataset_path, usecols=ALL_COLUMNS, chunksize=chunksize, **csv_kwargs):
        chunk = chunk.copy()
        chunk["priority"] = rng.random(len(chunk))
        if sampled is None:
            sampled = chunk
        else:
            sampled = pd.concat([sampled, chunk], ignore_index=True)
        if len(sampled) > sample_size:
            sampled = sampled.nlargest(sample_size, "priority").reset_index(drop=True)

    if sampled is None or sampled.empty:
        raise ValueError(f"No valid rows found in dataset: {dataset_path}")

    return sampled.drop(columns="priority").reset_index(drop=True)


def compute_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    """回帰評価指標を計算する。

    Args:
        y_true (pd.Series): 正解値
        y_pred (np.ndarray): 予測値
    Returns:
        dict[str, float]: R2, RMSE, MAEを格納した辞書
    """
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }


def summarize_metric_dicts(metric_dicts: list[dict[str, float]]) -> dict[str, float]:
    """評価指標辞書の平均と標準偏差を集計する。

    Args:
        metric_dicts (list[dict[str, float]]): foldごとの評価指標辞書
    Returns:
        dict[str, float]: 各指標の平均・標準偏差を含む辞書
    """
    summary: dict[str, float] = {}
    for metric_name in metric_dicts[0]:
        values = np.array([metrics[metric_name] for metrics in metric_dicts], dtype=np.float64)
        summary[f"{metric_name}_mean"] = float(values.mean())
        summary[f"{metric_name}_std"] = float(values.std(ddof=0))
    return summary


def compute_vif(dataframe: pd.DataFrame) -> dict[str, float]:
    """説明変数ごとのVIFを計算する。

    Args:
        dataframe (pd.DataFrame): 説明変数のみを含むデータフレーム
    Returns:
        dict[str, float]: 変数名をキー、VIFを値とする辞書
    """
    vif_values: dict[str, float] = {}
    for column in dataframe.columns:
        y = dataframe[column]
        x = dataframe.drop(columns=column)
        model = LinearRegression()
        model.fit(x, y)
        r_squared = model.score(x, y)
        if r_squared >= 0.999999:
            vif_values[column] = float("inf")
            continue
        vif_values[column] = float(1.0 / (1.0 - r_squared))
    return vif_values


def fit_linear_regression(
    x_train: pd.DataFrame,
    x_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
) -> tuple[dict[str, object], dict[str, float], np.ndarray]:
    """標準化した線形回帰モデルを学習し、評価結果を返す。

    Args:
        x_train (pd.DataFrame): 学習用説明変数
        x_test (pd.DataFrame): 評価用説明変数
        y_train (pd.Series): 学習用目的変数
        y_test (pd.Series): 評価用目的変数
    Returns:
        tuple[dict[str, object], dict[str, float], np.ndarray]:
            評価結果辞書、標準化係数、予測値
    """
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
        feature: float(coef)
        for feature, coef in zip(FEATURE_COLUMNS, model.coef_, strict=True)
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
) -> tuple[RandomForestRegressor, dict[str, object], dict[str, float], dict[str, float], np.ndarray]:
    """ランダムフォレスト回帰を学習し、評価と重要度を返す。

    Args:
        x_train (pd.DataFrame): 学習用説明変数
        x_test (pd.DataFrame): 評価用説明変数
        y_train (pd.Series): 学習用目的変数
        y_test (pd.Series): 評価用目的変数
        random_state (int): 乱数シード
        n_estimators (int): 決定木本数
    Returns:
        tuple[RandomForestRegressor, dict[str, object], dict[str, float], dict[str, float], np.ndarray]:
            学習済みモデル、評価結果、不純度ベース重要度、Permutation重要度、予測値
    """
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
        for feature, score in zip(FEATURE_COLUMNS, model.feature_importances_, strict=True)
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
        for feature, score in zip(FEATURE_COLUMNS, permutation.importances_mean, strict=True)
    }

    result = {
        "metrics": compute_metrics(y_test, y_pred),
        "feature_importance": impurity_importance,
        "permutation_importance": permutation_scores,
    }
    return model, result, impurity_importance, permutation_scores, y_pred


def build_spatial_groups(dataframe: pd.DataFrame, spatial_bins: int) -> tuple[pd.Series, dict[str, int]]:
    """経度・緯度の分位ビンから空間グループIDを作成する。

    Args:
        dataframe (pd.DataFrame): 座標列を含むデータフレーム
        spatial_bins (int): 経度・緯度それぞれの分割数
    Returns:
        tuple[pd.Series, dict[str, int]]: グループID列とグループ情報
    """
    # 経度・緯度を分位で離散化して格子ブロックを作る。
    # 同一ブロック内を同じgroupとしてSpatial CVでリークを抑える。
    lon_bins = pd.qcut(dataframe["lon"], q=spatial_bins, labels=False, duplicates="drop")
    lat_bins = pd.qcut(dataframe["lat"], q=spatial_bins, labels=False, duplicates="drop")

    lon_codes = lon_bins.astype(int)
    lat_codes = lat_bins.astype(int)
    lat_multiplier = int(lat_codes.max()) + 1
    groups = lon_codes * lat_multiplier + lat_codes

    info = {
        "lon_bins": int(lon_codes.max()) + 1,
        "lat_bins": int(lat_codes.max()) + 1,
        "n_groups": int(groups.nunique()),
    }
    return groups, info


def run_spatial_cv(
    sampled: pd.DataFrame,
    cv_splits: int,
    spatial_bins: int,
    random_state: int,
    n_estimators: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    """Spatial block CVで線形回帰とRFの汎化性能を比較する。

    Args:
        sampled (pd.DataFrame): サンプリング済みデータ
        cv_splits (int): CV分割数
        spatial_bins (int): 空間ブロック分割数
        random_state (int): 乱数シード
        n_estimators (int): RFの決定木本数
    Returns:
        tuple[dict[str, object], pd.DataFrame]: 集計結果とfold別結果
    """
    groups, group_info = build_spatial_groups(sampled, spatial_bins=spatial_bins)
    x = sampled[FEATURE_COLUMNS]
    y = sampled[TARGET_COLUMN]

    splitter = GroupKFold(n_splits=cv_splits)
    fold_rows: list[dict[str, float | int]] = []
    linear_metrics: list[dict[str, float]] = []
    rf_metrics: list[dict[str, float]] = []

    for fold_index, (train_idx, test_idx) in enumerate(splitter.split(x, y, groups=groups), start=1):
        x_train = x.iloc[train_idx]
        x_test = x.iloc[test_idx]
        y_train = y.iloc[train_idx]
        y_test = y.iloc[test_idx]

        linear_result, _, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
        _, rf_result, _, _, _ = fit_random_forest(
            x_train,
            x_test,
            y_train,
            y_test,
            random_state=random_state,
            n_estimators=n_estimators,
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
        "group_definition": "quantile lon/lat blocks",
        "cv_splits": cv_splits,
        "group_info": group_info,
        "linear_regression": summarize_metric_dicts(linear_metrics),
        "random_forest": summarize_metric_dicts(rf_metrics),
    }
    return summary, pd.DataFrame(fold_rows)


def save_model_comparison_plot(
    output_path: Path,
    random_linear_metrics: dict[str, float],
    random_rf_metrics: dict[str, float],
    spatial_linear_metrics: dict[str, float],
    spatial_rf_metrics: dict[str, float],
) -> None:
    """ランダム分割とSpatial CVのモデル比較図を保存する。

    Args:
        output_path (Path): 出力画像パス
        random_linear_metrics (dict[str, float]): ランダム分割の線形回帰指標
        random_rf_metrics (dict[str, float]): ランダム分割のRF指標
        spatial_linear_metrics (dict[str, float]): Spatial CVの線形回帰指標
        spatial_rf_metrics (dict[str, float]): Spatial CVのRF指標
    Returns:
        None
    """
    metric_names = ["r2", "rmse", "mae"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    for index, metric_name in enumerate(metric_names):
        values = [
            random_linear_metrics[metric_name],
            random_rf_metrics[metric_name],
            spatial_linear_metrics[f"{metric_name}_mean"],
            spatial_rf_metrics[f"{metric_name}_mean"],
        ]
        axes[index].bar(
            ["Linear\nRandom", "RF\nRandom", "Linear\nSpatialCV", "RF\nSpatialCV"],
            values,
            color=["#4c78a8", "#f58518", "#72b7b2", "#e45756"],
        )
        axes[index].set_title(metric_name.upper())
        axes[index].grid(axis="y", alpha=0.3)

    fig.suptitle("Satellite Only Model Comparison")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_feature_importance_plot(
    output_path: Path,
    standardized_coefficients: dict[str, float],
    rf_importance: dict[str, float],
) -> None:
    """線形回帰とRFの特徴量重要度比較図を保存する。

    Args:
        output_path (Path): 出力画像パス
        standardized_coefficients (dict[str, float]): 線形回帰の標準化係数
        rf_importance (dict[str, float]): RFの特徴量重要度
    Returns:
        None
    """
    linear_values = [abs(standardized_coefficients[feature]) for feature in FEATURE_COLUMNS]
    rf_values = [rf_importance[feature] for feature in FEATURE_COLUMNS]
    x_positions = np.arange(len(FEATURE_COLUMNS))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(x_positions - width / 2, linear_values, width=width, label="|Linear coef|", color="#54a24b")
    ax.bar(x_positions + width / 2, rf_values, width=width, label="RF importance", color="#e45756")
    ax.set_xticks(x_positions, FEATURE_COLUMNS)
    ax.set_title("Satellite Only Feature Importance")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_spatial_cv_plot(output_path: Path, fold_metrics_df: pd.DataFrame) -> None:
    """Spatial CVのfold別性能推移を可視化して保存する。

    Args:
        output_path (Path): 出力画像パス
        fold_metrics_df (pd.DataFrame): fold別評価指標データ
    Returns:
        None
    """
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    metrics = [("r2", "R²"), ("rmse", "RMSE"), ("mae", "MAE")]

    for index, (metric_suffix, title) in enumerate(metrics):
        axes[index].plot(
            fold_metrics_df["fold"],
            fold_metrics_df[f"linear_{metric_suffix}"],
            marker="o",
            label="Linear",
            color="#4c78a8",
        )
        axes[index].plot(
            fold_metrics_df["fold"],
            fold_metrics_df[f"rf_{metric_suffix}"],
            marker="o",
            label="RF",
            color="#e45756",
        )
        axes[index].set_title(f"Spatial CV {title}")
        axes[index].set_xlabel("Fold")
        axes[index].grid(alpha=0.3)

    axes[0].legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def compute_shap_outputs(
    model: RandomForestRegressor,
    shap_features: pd.DataFrame,
    background_features: pd.DataFrame,
    output_dir: Path,
    output_stem: str,
) -> tuple[dict[str, object], pd.DataFrame]:
    """SHAP値を計算し、重要度表と可視化画像を保存する。

    Args:
        model (RandomForestRegressor): 学習済みRFモデル
        shap_features (pd.DataFrame): SHAP計算対象データ
        background_features (pd.DataFrame): SHAP背景データ
        output_dir (Path): 出力先ディレクトリ
        output_stem (str): 出力ファイル名の接頭辞
    Returns:
        tuple[dict[str, object], pd.DataFrame]: SHAP集計結果辞書と重要度データ
    """
    explainer = shap.TreeExplainer(model, data=background_features, feature_names=FEATURE_COLUMNS)
    shap_values = explainer(shap_features)

    # 各特徴量の寄与の大きさを比較するため、絶対SHAP値の平均を算出する。
    mean_abs_values = np.abs(shap_values.values).mean(axis=0)
    shap_importance_df = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "mean_abs_shap": mean_abs_values,
        }
    ).sort_values("mean_abs_shap", ascending=False)

    shap_importance_path = output_dir / f"{output_stem}_shap_importance.csv"
    shap_importance_df.to_csv(shap_importance_path, index=False)

    summary_path = output_dir / f"{output_stem}_shap_summary.png"
    plt.figure(figsize=(8, 5))
    shap.summary_plot(shap_values.values, shap_features, show=False)
    plt.tight_layout()
    plt.savefig(summary_path, dpi=180, bbox_inches="tight")
    plt.close()

    bar_path = output_dir / f"{output_stem}_shap_bar.png"
    plt.figure(figsize=(8, 5))
    shap.summary_plot(shap_values.values, shap_features, plot_type="bar", show=False)
    plt.tight_layout()
    plt.savefig(bar_path, dpi=180, bbox_inches="tight")
    plt.close()

    dependence_paths: dict[str, str] = {}
    for feature in FEATURE_COLUMNS:
        dependence_path = output_dir / f"{output_stem}_shap_dependence_{feature}.png"
        shap.dependence_plot(
            feature,
            shap_values.values,
            shap_features,
            show=False,
            interaction_index="auto",
        )
        plt.tight_layout()
        plt.savefig(dependence_path, dpi=180, bbox_inches="tight")
        plt.close()
        dependence_paths[feature] = str(dependence_path.relative_to(PROJECT_ROOT))

    shap_result = {
        "sample_size": int(len(shap_features)),
        "background_size": int(len(background_features)),
        "mean_abs_shap": {
            row["feature"]: float(row["mean_abs_shap"])
            for _, row in shap_importance_df.iterrows()
        },
        "outputs": {
            "shap_importance_csv": str(shap_importance_path.relative_to(PROJECT_ROOT)),
            "shap_summary_png": str(summary_path.relative_to(PROJECT_ROOT)),
            "shap_bar_png": str(bar_path.relative_to(PROJECT_ROOT)),
            "shap_dependence_png": dependence_paths,
        },
    }
    return shap_result, shap_importance_df


def main() -> None:
    """衛星データのみシナリオの分析を実行して結果を保存する。

    Args:
        なし
    Returns:
        None
    """
    args = parse_arguments()
    args.dataset_path = args.dataset_path.resolve()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = args.dataset_path.stem.removesuffix("_dataset")

    sampled = build_priority_sample(
        dataset_path=args.dataset_path,
        sample_size=args.sample_size,
        chunksize=args.chunksize,
        random_state=args.random_state,
    )

    sampled_path = args.output_dir / f"{output_stem}_sample_{args.sample_size}.csv"
    sampled.to_csv(sampled_path, index=False)

    x = sampled[FEATURE_COLUMNS]
    y = sampled[TARGET_COLUMN]
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=args.random_state,
    )

    vif = compute_vif(x)
    linear_result, standardized_coefficients, _ = fit_linear_regression(x_train, x_test, y_train, y_test)
    rf_model, rf_result, rf_importance, permutation_scores, _ = fit_random_forest(
        x_train,
        x_test,
        y_train,
        y_test,
        random_state=args.random_state,
        n_estimators=args.rf_trees,
    )

    spatial_cv_summary, spatial_cv_folds = run_spatial_cv(
        sampled=sampled,
        cv_splits=args.cv_splits,
        spatial_bins=args.spatial_bins,
        random_state=args.random_state,
        n_estimators=args.rf_trees,
    )

    feature_importance_df = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "linear_abs_standardized_coefficient": [
                abs(standardized_coefficients[feature]) for feature in FEATURE_COLUMNS
            ],
            "random_forest_importance": [rf_importance[feature] for feature in FEATURE_COLUMNS],
            "permutation_importance": [permutation_scores[feature] for feature in FEATURE_COLUMNS],
            "vif": [vif[feature] for feature in FEATURE_COLUMNS],
        }
    )
    feature_importance_path = args.output_dir / f"{output_stem}_feature_importance.csv"
    feature_importance_df.to_csv(feature_importance_path, index=False)

    spatial_cv_folds_path = args.output_dir / f"{output_stem}_spatial_cv_folds.csv"
    spatial_cv_folds.to_csv(spatial_cv_folds_path, index=False)

    comparison_plot_path = args.output_dir / f"{output_stem}_model_comparison.png"
    importance_plot_path = args.output_dir / f"{output_stem}_feature_importance.png"
    spatial_cv_plot_path = args.output_dir / f"{output_stem}_spatial_cv.png"
    save_model_comparison_plot(
        comparison_plot_path,
        linear_result["metrics"],
        rf_result["metrics"],
        spatial_cv_summary["linear_regression"],
        spatial_cv_summary["random_forest"],
    )
    save_feature_importance_plot(importance_plot_path, standardized_coefficients, rf_importance)
    save_spatial_cv_plot(spatial_cv_plot_path, spatial_cv_folds)

    shap_source = x_test.reset_index(drop=True)
    shap_sample_size = min(args.shap_sample_size, len(shap_source))
    background_size = min(args.shap_background_size, len(x_train))
    shap_features = shap_source.sample(n=shap_sample_size, random_state=args.random_state)
    background_features = x_train.sample(n=background_size, random_state=args.random_state)
    shap_result, _ = compute_shap_outputs(
        model=rf_model,
        shap_features=shap_features,
        background_features=background_features,
        output_dir=args.output_dir,
        output_stem=output_stem,
    )

    result = {
        "scenario": "Satellite Only",
        "dataset_path": str(args.dataset_path.relative_to(PROJECT_ROOT)),
        "sample_path": str(sampled_path.relative_to(PROJECT_ROOT)),
        "sample_size": int(len(sampled)),
        "train_size": int(len(x_train)),
        "test_size": int(len(x_test)),
        "features": FEATURE_COLUMNS,
        "random_split": {
            "linear_regression": linear_result,
            "random_forest": rf_result,
        },
        "spatial_cv": {
            **spatial_cv_summary,
            "outputs": {
                "fold_metrics_csv": str(spatial_cv_folds_path.relative_to(PROJECT_ROOT)),
                "spatial_cv_png": str(spatial_cv_plot_path.relative_to(PROJECT_ROOT)),
            },
        },
        "vif": vif,
        "shap": shap_result,
        "outputs": {
            "feature_importance_csv": str(feature_importance_path.relative_to(PROJECT_ROOT)),
            "model_comparison_png": str(comparison_plot_path.relative_to(PROJECT_ROOT)),
            "feature_importance_png": str(importance_plot_path.relative_to(PROJECT_ROOT)),
        },
    }

    result_path = args.output_dir / f"{output_stem}_results.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
