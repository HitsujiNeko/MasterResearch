"""経験セミバリオグラムの算出と理論モデルの当てはめを行う共通モジュール。

計算本体は scikit-gstat（``skgstat.Variogram``）に任せ、本モジュールは
入出力の整形（ラグ境界の明示指定・ラグ表・当てはめ結果の要約）だけを担う薄い
ラッパである。経験セミバリオグラムは Matheron 推定量
（距離帯ごとに ``0.5 × (値の差)^2`` の平均）で求める。

scikit-gstat の仕様のうち、結果の読み方に効くものを以下に記す
（scikit-gstat 1.0.22 のソースで確認した）。

- ラグの区間は「下端を含み上端を含まない」（``lower <= d < upper``）。
  最初のラグの下端は 0 である
- 全ペアの距離行列を持つとメモリが標本数の2乗で増えるため、
  ``skgstat.MetricSpace(coords, max_dist=最大ラグ)`` で最大ラグ以内のペアだけを
  疎行列で持つ
- 理論モデルの ``effective_range`` は、spherical ではちょうど sill に達する距離、
  exponential では sill の 95% に達する距離（``a = r / 3``）である。
  いずれも「実用 range」として読める
- ``sill`` は nugget を除いた部分 sill（``gamma = nugget + sill × f(h)``）であり、
  全体の sill は ``sill + nugget`` である
- 当てはめはラグの中心ではなく**ラグの上端**の距離に対して行われる。
  そのため、モデルの range はラグ幅の半分程度、長めに出うる
- 当てはめの range の上限は最大ラグである。上限に張り付いた場合は
  「range は最大ラグ以上」としか言えないため、要約にその旨のフラグを立てる

距離の単位は座標の単位に従う。本研究では投影座標系（m）の座標を渡す。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import skgstat

# Matheron 推定量。経験セミバリオグラムの推定量を変えると値の意味が変わるため固定する
ESTIMATOR = "matheron"

# 当てはめる理論モデルの既定値（実用 range の定義は上記 module docstring を参照）
DEFAULT_MODELS = ("spherical", "exponential")

# 経験的な実用 range の判定に使う、全体分散に対する比のしきい値
EMPIRICAL_RANGE_RATIO = 0.95

# 当てはめの range が上限（最大ラグ）に張り付いたとみなす相対許容差
RANGE_BOUND_RTOL = 1e-3

LAG_TABLE_COLUMNS = (
    "lag_lower_m",
    "lag_upper_m",
    "lag_center_m",
    "n_pairs",
    "semivariance",
    "ratio_to_variance",
)


def build_lag_edges(lag_width_m: float, max_lag_m: float) -> np.ndarray:
    """等間隔のラグの上端の配列を作る。

    scikit-gstat に既定のビン分け（``bin_func``）を任せず、ラグの境界を明示する
    ために使う。

    Args:
        lag_width_m: ラグの幅（座標の単位。本研究では m）。
        max_lag_m: 最大ラグ（最後のラグの上端）。
    Returns:
        ``[lag_width_m, 2 × lag_width_m, ..., max_lag_m]`` の配列。
    Raises:
        ValueError: いずれかが0以下の場合。``max_lag_m`` が ``lag_width_m`` の
            整数倍でない場合（最後のラグだけ幅が違うと、ラグ間の比較が
            できなくなるため、黙って丸めない）。
    """
    if lag_width_m <= 0 or max_lag_m <= 0:
        raise ValueError(
            f"lag_width_m と max_lag_m は正の値である必要があります"
            f"（lag_width_m={lag_width_m}, max_lag_m={max_lag_m}）。"
        )
    n_lags = max_lag_m / lag_width_m
    if not np.isclose(n_lags, round(n_lags)) or round(n_lags) < 1:
        raise ValueError(
            f"max_lag_m（{max_lag_m}）は lag_width_m（{lag_width_m}）の整数倍である必要があります。"
        )
    return lag_width_m * np.arange(1, round(n_lags) + 1, dtype=float)


def compute_empirical_variogram(
    coords: np.ndarray, values: np.ndarray, lag_edges: np.ndarray
) -> skgstat.Variogram:
    """最大ラグ以内のペアだけで経験セミバリオグラムを算出する。

    Args:
        coords: 点の座標（形状 ``(n, 2)``。投影座標系）。
        values: 各点の値（形状 ``(n,)``）。
        lag_edges: ラグの上端の配列（``build_lag_edges`` の戻り値）。
    Returns:
        scikit-gstat の ``Variogram``。理論モデルは未当てはめ
        （当てはめは ``fit_variogram_model`` で行う）。
    Raises:
        ValueError: 座標と値の長さが合わない場合、値に NaN・無限大が含まれる
            場合、点が2点未満の場合（ペアを作れないため）。座標が重複する
            点がある場合（最大ラグ以内のペアを持つ疎行列は値0の要素を
            保持しない場合があり、距離0のペアが数えられるか保証できないため）。
    """
    coords = np.asarray(coords, dtype=float)
    values = np.asarray(values, dtype=float)
    lag_edges = np.asarray(lag_edges, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 2 or coords.shape[0] != values.shape[0]:
        raise ValueError(
            f"coords は (n, 2)、values は (n,) で n が一致する必要があります"
            f"（coords={coords.shape}, values={values.shape}）。"
        )
    if values.shape[0] < 2:
        raise ValueError("セミバリオグラムの算出には2点以上が必要です。")
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(coords)):
        raise ValueError("coords・values に NaN または無限大が含まれています。")
    n_unique = np.unique(coords, axis=0).shape[0]
    if n_unique != coords.shape[0]:
        raise ValueError(
            f"coords に重複する座標があります（{coords.shape[0] - n_unique}点）。"
            "距離0のペアの扱いを保証できないため、重複を除いてから渡してください。"
        )

    metric_space = skgstat.MetricSpace(coords, max_dist=float(lag_edges.max()))
    return skgstat.Variogram(
        metric_space,
        values,
        estimator=ESTIMATOR,
        bin_func=lag_edges,
        use_nugget=True,
        # 生成時に当てはめを走らせず、モデルごとに明示的に当てはめる
        fit_method=None,
    )


def build_lag_table(variogram: skgstat.Variogram, variance: float) -> pd.DataFrame:
    """経験セミバリオグラムをラグ表に整形する。

    Args:
        variogram: ``compute_empirical_variogram`` の戻り値。
        variance: 比の分母に使う全体分散（``ratio_to_variance`` 列の基準）。
    Returns:
        ``LAG_TABLE_COLUMNS`` の列を持つ DataFrame（1行1ラグ）。ペアが無い
        ラグの ``semivariance`` は NaN。
    """
    upper = np.asarray(variogram.bins, dtype=float)
    lower = np.concatenate(([0.0], upper[:-1]))
    semivariance = np.asarray(variogram.experimental, dtype=float)
    return pd.DataFrame(
        {
            "lag_lower_m": lower,
            "lag_upper_m": upper,
            "lag_center_m": (lower + upper) / 2.0,
            "n_pairs": np.asarray(variogram.bin_count, dtype=np.int64),
            "semivariance": semivariance,
            "ratio_to_variance": semivariance / variance,
        },
        columns=list(LAG_TABLE_COLUMNS),
    )


def find_empirical_range(
    lag_table: pd.DataFrame, ratio: float = EMPIRICAL_RANGE_RATIO
) -> float | None:
    """半分散が初めて全体分散の ``ratio`` 倍以上になるラグの中心距離を返す。

    理論モデルに依存しない実用 range の目安として使う。

    Args:
        lag_table: ``build_lag_table`` の戻り値。
        ratio: 全体分散に対する比のしきい値。
    Returns:
        該当ラグの中心距離。最大ラグまでに達しない場合は None
        （「最大ラグ以上」としか言えないため、値を作らない）。
    """
    reached = lag_table["ratio_to_variance"].to_numpy() >= ratio
    if not reached.any():
        return None
    return float(lag_table["lag_center_m"].to_numpy()[np.argmax(reached)])


def fit_variogram_model(variogram: skgstat.Variogram, model: str) -> dict:
    """理論モデルを当てはめ、range・sill・nugget を要約する。

    ``variogram`` のモデル設定を書き換える（モデルを順に当てはめるため）。

    Args:
        variogram: ``compute_empirical_variogram`` の戻り値。
        model: scikit-gstat の理論モデル名（例: ``"spherical"``）。
    Returns:
        ``model``・``effective_range_m``・``partial_sill``・``nugget``・
        ``total_sill``・``range_at_upper_bound``・``rmse`` を持つ辞書。
    """
    variogram.model = model
    variogram.fit_method = "trf"
    variogram.fit()
    effective_range, partial_sill, nugget = (float(v) for v in variogram.parameters)
    max_lag = float(np.max(variogram.bins))
    return {
        "model": model,
        "effective_range_m": effective_range,
        "partial_sill": partial_sill,
        "nugget": nugget,
        "total_sill": partial_sill + nugget,
        "range_at_upper_bound": bool(np.isclose(effective_range, max_lag, rtol=RANGE_BOUND_RTOL)),
        "rmse": float(variogram.rmse),
    }


def compute_semivariogram(
    coords: np.ndarray,
    values: np.ndarray,
    lag_width_m: float,
    max_lag_m: float,
    models: tuple[str, ...] = DEFAULT_MODELS,
) -> tuple[pd.DataFrame, dict]:
    """経験セミバリオグラムのラグ表と、理論モデルの当てはめ要約を作る。

    Args:
        coords: 点の座標（形状 ``(n, 2)``。投影座標系）。
        values: 各点の値（形状 ``(n,)``）。
        lag_width_m: ラグの幅。
        max_lag_m: 最大ラグ。
        models: 当てはめる理論モデル名。
    Returns:
        ラグ表（``build_lag_table``）と要約の辞書のタプル。要約には測定条件
        （点数・ラグの幅・最大ラグ・推定量・全体分散）、経験的な実用 range、
        モデルごとの当てはめ結果（``fit_variogram_model``）、および値の定義の
        注記を含める。全体分散は不偏分散（ddof=1）。
    """
    lag_edges = build_lag_edges(lag_width_m, max_lag_m)
    variogram = compute_empirical_variogram(coords, values, lag_edges)
    variance = float(np.var(np.asarray(values, dtype=float), ddof=1))
    lag_table = build_lag_table(variogram, variance)
    summary = {
        "n_points": int(len(values)),
        "lag_width_m": float(lag_width_m),
        "max_lag_m": float(max_lag_m),
        "estimator": ESTIMATOR,
        "variance": variance,
        "n_pairs_total": int(lag_table["n_pairs"].sum()),
        "empirical_range_ratio": EMPIRICAL_RANGE_RATIO,
        "empirical_range_m": find_empirical_range(lag_table),
        "models": [fit_variogram_model(variogram, model) for model in models],
        "definitions": {
            "lag_interval": "lower <= 距離 < upper",
            "empirical_range_m": (
                "半分散が初めて全体分散（不偏分散）の empirical_range_ratio 倍以上に"
                "なるラグの中心距離。最大ラグまでに達しない場合は null"
            ),
            "effective_range_m": (
                "scikit-gstat の実用 range。spherical はちょうど sill に達する距離、"
                "exponential は sill の 95% に達する距離。当てはめはラグの上端の"
                "距離に対して行う"
            ),
            "partial_sill": "nugget を除いた sill。total_sill = partial_sill + nugget",
            "range_at_upper_bound": "range が当てはめの上限（最大ラグ）に張り付いた",
            "fit_bounds": (
                "当てはめの上限は range が最大ラグ、partial_sill が経験半分散の最大値、"
                "nugget が経験半分散の最大値の0.99倍（下限はいずれも0）"
            ),
        },
    }
    return lag_table, summary
