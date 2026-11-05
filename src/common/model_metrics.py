"""回帰モデルの評価指標を計算する共通モジュール。

R²/RMSE/MAEの算出、fold単位の指標集計、多重共線性を確認するためのVIF計算と
相関行列の算出をまとめる。RQ3のシナリオ別分析スクリプト（Satellite Only /
Limited / Full）が共通して必要とする処理であり、シナリオ固有の特徴量名には
依存しない。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.tools import add_constant

# VIFがこの値以上なら完全共線とみなし、`inf` を返す（補助回帰の決定係数 0.999999 に
# 相当する）。完全共線でも数値誤差で有限の巨大な値（1e15 程度）になるため、閾値で
# 揃えないと「発散した」ことが結果から読み取れなくなる。
VIF_PERFECT_COLLINEARITY_THRESHOLD: float = 1e6

# 対応する相関係数の種類。VIFが線形の共線性指標であるためPearsonを主とするが、
# 被覆率型の変数（土地被覆クラス別面積率など）は細かいスケールで0へ偏りやすく、
# 線形相関だけでは関係を取りこぼしうるためSpearmanも併せて算出できるようにする。
CORRELATION_METHODS: tuple[str, ...] = ("pearson", "spearman")


def compute_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    """回帰評価指標を計算する。

    Args:
        y_true: 正解値。
        y_pred: 予測値。
    Returns:
        R2, RMSE, MAEを格納した辞書。
    """
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }


def summarize_metric_dicts(metric_dicts: list[dict[str, float]]) -> dict[str, float]:
    """評価指標辞書の平均と標準偏差を集計する。

    Args:
        metric_dicts: foldごとの評価指標辞書（`compute_metrics` の戻り値のリスト）。
    Returns:
        各指標の平均・標準偏差を含む辞書（キーは `{指標名}_mean` / `{指標名}_std`）。
    Raises:
        ValueError: `metric_dicts` が空の場合。
    """
    if not metric_dicts:
        raise ValueError("集計対象のfold評価指標が空です。CV分割数を確認してください。")

    summary: dict[str, float] = {}
    for metric_name in metric_dicts[0]:
        values = np.array([metrics[metric_name] for metrics in metric_dicts], dtype=np.float64)
        summary[f"{metric_name}_mean"] = float(values.mean())
        summary[f"{metric_name}_std"] = float(values.std(ddof=0))
    return summary


def compute_vif(dataframe: pd.DataFrame) -> dict[str, float]:
    """説明変数ごとのVIF（分散拡大係数）を計算する。

    statsmodels の `variance_inflation_factor` により、定数項つきの補助回帰から
    1/(1-R²) を求める。入力の型によらず float64 で計算する（float32 のまま回帰すると
    丸め誤差が相対 1e-6 程度の差として値に現れるため）。

    Args:
        dataframe: 説明変数のみを含むデータフレーム（2列以上必要）。
    Returns:
        変数名をキー、VIFを値とする辞書。完全共線（VIFが
        `VIF_PERFECT_COLLINEARITY_THRESHOLD` 以上）の列と、分散が0で決定係数を
        定義できない列（1行しかない場合を含む）は `float("inf")` を返す。
    Raises:
        ValueError: `dataframe` の列数が2未満の場合。VIFは対象列を残りの列に
            回帰して求めるため、比較対象となる他の列が最低1つ必要。
            また、行が無い場合、欠測・無限大を含む場合、数値に変換できない列を
            含む場合。
    """
    if dataframe.shape[1] < 2:
        raise ValueError(f"VIFの計算には説明変数が2列以上必要です（列数: {dataframe.shape[1]}）。")

    values = dataframe.to_numpy(dtype=np.float64)
    if values.shape[0] == 0 or not np.isfinite(values).all():
        raise ValueError("VIFの計算には、欠測・無限大を含まない1行以上のデータが必要です。")

    # 分散0の列は定数項と重複して設計行列のランクを落とすだけなので、他の列の補助回帰
    # からも外す。外しても他の列のVIFは変わらない。
    is_constant = np.ptp(values, axis=0) == 0
    vif_values: dict[str, float] = dict.fromkeys(dataframe.columns, float("inf"))
    if is_constant.all():
        return vif_values

    # 既定の "skip" は定数列があると定数項を追加しない。定数列は上で外しているが、
    # 補助回帰に定数項が必ず入ることを明示する。
    design = add_constant(values[:, ~is_constant], has_constant="add")
    # 設計行列の先頭は定数項なので、説明変数は1列目から対応する。
    for design_index, column in enumerate(dataframe.columns[~is_constant], start=1):
        vif = float(variance_inflation_factor(design, design_index))
        if vif < VIF_PERFECT_COLLINEARITY_THRESHOLD:
            vif_values[column] = vif
    return vif_values


def sanitize_vif_for_json(vif_values: dict[str, float]) -> dict[str, object]:
    """VIFの非有限値（Inf・NaN）をJSON書き出し可能な形に変換する。

    `compute_vif` は完全共線時に `float("inf")` を返すが、
    `src.common.summary.save_summary()` は `allow_nan=False` でInf・NaNを例外にする。
    黙って`null`へ落とすと「完全共線で発散した」のか「数値的に不安定でNaNになった」
    のかが区別できなくなるため、非有限値だった変数名を別キーに残す
    （NaNは通常発生しないが、極端な多重共線性下での数値誤差に備えて同列に扱う）。

    Args:
        vif_values: `compute_vif` の戻り値（変数名をキー、VIFを値とする辞書）。
    Returns:
        `"vif"`（非有限値を`None`に置き換えた辞書）と `"vif_non_finite_features"`
        （Inf・NaNだった変数名のリスト）を持つ辞書。
    """
    non_finite_features = [name for name, value in vif_values.items() if not math.isfinite(value)]
    sanitized_vif = {
        name: (None if not math.isfinite(value) else value) for name, value in vif_values.items()
    }
    return {"vif": sanitized_vif, "vif_non_finite_features": non_finite_features}


def compute_correlation_matrix(dataframe: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """説明変数候補どうしの相関行列を計算する。

    VIFが「ある変数を他の全変数でどれだけ説明できるか」という多変量の指標である
    のに対し、相関行列は変数対ごとの関係を示す。VIFが高いと分かっても、どの変数対が
    その原因かは相関行列を見ないと特定できないため、両者は対で使う。

    Args:
        dataframe: 相関を計算する数値列のみを含むデータフレーム（2列以上必要）。
        method: 相関係数の種類（``CORRELATION_METHODS`` のいずれか）。
    Returns:
        行・列とも `dataframe` の列名を持つ相関行列。
        **分散が0の列は相関が定義できないため、当該行・列は `NaN` になる**
        （pandasの挙動をそのまま残す。定数列が存在すること自体が診断上の情報であり、
        0などで埋めて隠すと実在する相関と区別できなくなるため）。

    Note:
        **欠測値の扱いはペアワイズ削除である**（`DataFrame.corr()` の既定挙動）。
        変数対ごとに、両方が非NULLの行だけで係数を算出するため、`dataframe` が
        欠測を含む場合は**セルごとに母数が異なる**相関行列になる。欠測率が列に
        よって大きく違うと係数どうしを直接比べられなくなるので、呼び出し側は
        欠測を含む行を落としたうえで渡すか、算出に使った母数を併せて記録する。
    Raises:
        ValueError: `dataframe` の列数が2未満の場合、数値でない列を含む場合、
            または `method` が対応外の場合。
    """
    if method not in CORRELATION_METHODS:
        supported = ", ".join(CORRELATION_METHODS)
        raise ValueError(f"対応していない相関係数の種類です: {method}（対応: {supported}）。")
    if dataframe.shape[1] < 2:
        raise ValueError(f"相関行列の計算には2列以上必要です（列数: {dataframe.shape[1]}）。")

    non_numeric_columns = [
        str(column)
        for column in dataframe.columns
        if not pd.api.types.is_numeric_dtype(dataframe[column])
    ]
    if non_numeric_columns:
        raise ValueError(f"数値でない列が含まれています: {non_numeric_columns}。")

    return dataframe.corr(method=method)
