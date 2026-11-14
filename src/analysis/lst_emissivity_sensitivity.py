"""LST 算出の放射率が NDVI に依存することの感度分析（差の集計）。

分析に用いる LST（SMW 法・同じシーンの NDVI から求めた放射率。以下 NDVI 版）と、
ASTER GEDv3 の静的な放射率（EM0）による LST（以下 EM0 版）を比べる。
GEE からの出力は `src.gee.gee_export_lst_emissivity_variants` で行い、本スクリプトは
ダウンロード後のファイルと分析ランの結果だけを読む（GEE には接続しない）。

次の 2 つのサブコマンドを持つ。

1. `lst-diff`:
   (a) 再出力した NDVI 版が既存 GeoTIFF と画素単位で一致するか（有効画素の位置と値）、
   (b) ΔLST = LST(NDVI 版) − LST(EM0 版) と Δε = ε(NDVI 版) − ε(EM0 版) の分布、
   (c) NDVI 階級別の ΔLST、NDVI と LST の画素単位の相関（NDVI 版・EM0 版）、
   (d) ΔLST の空間分布図と NDVI 階級別の図、を出力する。
2. `compare-runs`:
   同じ評価セルで NDVI 版・EM0 版の LST を目的変数にした分析ランの結果
   （results.json）の組を比べる。差の向きは **EM0 版 − NDVI 版**。
   評価指標（ランダム分割・Spatial CV）、Spatial CV の fold ごとの対応のある差と
   補正 t 区間、変数の寄与（SHAP・Permutation 重要度・不純度重要度・標準化係数）と
   その順位、目的変数の分布を出す。

EM0 版は放射率の精度が NDVI 版より高いことを意味しない（ASTER GEDv3 は 2000〜2008 年の
平均で、観測時点の植生・市街化を反映しない）。EM0 版でも結論が変わらなければ NDVI の
二重利用の影響は小さいと言えるが、大きく変わった場合は、依存の除去によるのか EM0 の
誤差によるのかを本分析だけでは区別できない。

使い方（プロジェクトルートで実行）:

    python -m src.analysis.lst_emissivity_sensitivity lst-diff \
        --observation-datetime 2022-09-06T03:23:58
    python -m src.analysis.lst_emissivity_sensitivity compare-runs \
        --observation-datetime 2022-09-06T03:23:58 \
        --pair limited {NDVI 版の results.json} {EM0 版の results.json} \
        --pair satellite_only {NDVI 版の results.json} {EM0 版の results.json}
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 - バックエンド設定の後に読み込む
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from affine import Affine  # noqa: E402
from scipy import stats  # noqa: E402

from src.analysis.compare_common_evaluation import (  # noqa: E402
    load_result,
    resolve_recorded_path,
    validate_same_evaluation,
)
from src.common.config import PROJECT_ROOT  # noqa: E402
from src.common.cv_paired_comparison import (  # noqa: E402
    compute_fold_differences,
    summarize_metric_differences,
)
from src.common.paths import resolve_existing_path, to_project_relative_string  # noqa: E402
from src.common.summary import build_provenance, save_summary  # noqa: E402
from src.gee.gee_calc_LST import build_export_description  # noqa: E402
from src.gee.gee_export_lst_emissivity_variants import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    build_export_plan,
    build_observation_token,
)
from src.module.landsat_sensor import DEFAULT_SENSOR  # noqa: E402

SCRIPT_NAME = "src.analysis.lst_emissivity_sensitivity"
LST_ROOT = Path("data") / "satellite" / "lst"
INDICES_ROOT = Path("data") / "satellite" / "indices"
NDVI_BAND_NAME = "NDVI"

# 再現の許容差（°C）。GeoTIFF は float64 で、同じ計算なら差は丸め誤差の範囲に収まる
DEFAULT_TOLERANCE_C = 1e-3
# NDVI 階級の境界（左端の階級のみ下限を含み、他は (下限, 上限]）
DEFAULT_NDVI_BINS: tuple[float, ...] = (-1.0, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
DESCRIBE_PERCENTILES: tuple[int, ...] = (1, 5, 25, 50, 75, 95, 99)
# 上位変数の比較に用いる順位の数
TOP_K = 5
# |ΔLST| の大きい画素を数える閾値（°C）と、放射率・NDVI の内訳を記録する閾値
LARGE_DIFFERENCE_THRESHOLDS_C: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 10.0)
LARGE_DIFFERENCE_DETAIL_THRESHOLD_C = 3.0

DIFFERENCE_DIRECTION = "EM0 版 − NDVI 版"
DELTA_DIRECTION = "NDVI 版 − EM0 版"

# 比べる変数の寄与の種類 -> (results.json 内の位置, 絶対値で順位を付けるか)
IMPORTANCE_FAMILIES: dict[str, tuple[tuple[str, ...], bool]] = {
    "shap_mean_abs": (("shap", "mean_abs_shap"), False),
    "rf_permutation_importance": (
        ("random_split", "random_forest", "permutation_importance"),
        False,
    ),
    "rf_impurity_importance": (("random_split", "random_forest", "feature_importance"), False),
    "lr_standardized_coefficient": (
        ("random_split", "linear_regression", "standardized_coefficients"),
        True,
    ),
}
RANDOM_SPLIT_MODELS: tuple[str, ...] = ("linear_regression", "random_forest")
RANDOM_SPLIT_METRICS: tuple[str, ...] = ("r2", "rmse", "mae")
SPATIAL_CV_METRICS: tuple[str, ...] = ("r2_mean", "rmse_mean", "mae_mean")
# 結果に影響する src/common の外のコード（来歴の監視対象に加える）
EXTRA_WATCH_PATHS: tuple[str, ...] = (
    "src/analysis/compare_common_evaluation.py",
    "src/gee/gee_export_lst_emissivity_variants.py",
)


# ---------------------------------------------------------------------------
# 共通: ラスタの読み込みと記述統計
# ---------------------------------------------------------------------------


def read_band(raster_path: Path, band_name: str | None = None) -> tuple[np.ndarray, Affine, str]:
    """ラスタの 1 バンドを float64（無効値は NaN）で読む。

    Args:
        raster_path: ラスタのパス。
        band_name: バンドの説明（GeoTIFF のバンド名）。None なら 1 バンド目。

    Returns:
        tuple[np.ndarray, Affine, str]: 値・アフィン変換・CRS 文字列。

    Raises:
        ValueError: 指定したバンド名が無い場合、または CRS が未設定の場合。
    """
    with rasterio.open(raster_path) as source:
        band_index = 1
        if band_name is not None:
            if band_name not in source.descriptions:
                raise ValueError(
                    f"バンド {band_name} がありません: {raster_path}（{source.descriptions}）"
                )
            band_index = source.descriptions.index(band_name) + 1
        if source.crs is None:
            raise ValueError(f"CRS が設定されていません: {raster_path}")
        values = source.read(band_index, masked=True).astype("float64").filled(np.nan)
        return values, source.transform, source.crs.to_string()


def load_aligned_bands(
    sources: dict[str, tuple[Path, str | None]],
) -> tuple[dict[str, np.ndarray], Affine, str]:
    """複数のラスタのバンドを読み、同じグリッドであることを確かめる。

    Args:
        sources: 名前 -> (パス, バンド名) の辞書。

    Returns:
        tuple[dict[str, np.ndarray], Affine, str]: 名前 -> 値、共通のアフィン変換・CRS。

    Raises:
        ValueError: 形状・アフィン変換・CRS のいずれかが一致しない場合（画素の対応が
            取れないまま差を取るのを防ぐため）。
    """
    arrays: dict[str, np.ndarray] = {}
    grid: tuple[tuple[int, ...], Affine, str] | None = None
    first_name = ""
    for name, (path, band_name) in sources.items():
        values, transform, crs_text = read_band(path, band_name)
        current = (values.shape, transform, crs_text)
        if grid is None:
            grid, first_name = current, name
        elif current != grid:
            raise ValueError(
                f"{name} のグリッド（形状・変換・CRS）が {first_name} と一致しません: "
                f"{current} != {grid}"
            )
        arrays[name] = values
    if grid is None:
        raise ValueError("読み込むラスタが指定されていません。")
    return arrays, grid[1], grid[2]


def describe_values(values: np.ndarray) -> dict[str, float | int | None]:
    """1 次元の値の件数・平均・標準偏差・最小・最大・分位点を求める。

    差は負にもなるため、下側の分位点（1・5・25 %）も含める。

    Args:
        values: 有限値の 1 次元配列。

    Returns:
        dict[str, float | int | None]: `count`・`mean`・`std`・`min`・`max`・`p{n}`。
            値が 0 件の場合は `count` 以外を None にする。
    """
    summary: dict[str, float | int | None] = {"count": int(values.size)}
    keys = ["mean", "std", "min", "max", *[f"p{p}" for p in DESCRIBE_PERCENTILES]]
    if values.size == 0:
        summary.update(dict.fromkeys(keys))
        return summary
    percentiles = np.percentile(values, DESCRIBE_PERCENTILES)
    summary.update(
        {
            "mean": float(np.mean(values, dtype=np.float64)),
            "std": float(np.std(values, dtype=np.float64)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            **{f"p{p}": float(value) for p, value in zip(DESCRIBE_PERCENTILES, percentiles)},
        }
    )
    return summary


# ---------------------------------------------------------------------------
# lst-diff: NDVI 版の再現確認と ΔLST の集計
# ---------------------------------------------------------------------------


def summarize_reproduction(
    reference: np.ndarray, reproduced: np.ndarray, tolerance: float
) -> dict[str, Any]:
    """再出力したラスタが既存のラスタと画素単位で一致するかを集計する。

    Args:
        reference: 既存のラスタの値（無効値は NaN）。
        reproduced: 再出力したラスタの値（無効値は NaN）。
        tolerance: 一致とみなす差の絶対値の上限。

    Returns:
        dict[str, Any]: 有効画素の位置の一致（両方・片方のみの画素数）、両方有効な画素の
            差の絶対値の統計、許容差を超えた画素数、`reproduced`（有効画素の位置が完全に
            一致し、すべての差が許容差以内か）。
    """
    reference_valid = np.isfinite(reference)
    reproduced_valid = np.isfinite(reproduced)
    both = reference_valid & reproduced_valid
    abs_diff = np.abs(reproduced[both] - reference[both])
    only_reference = int((reference_valid & ~reproduced_valid).sum())
    only_reproduced = int((~reference_valid & reproduced_valid).sum())
    exceeding = int((abs_diff > tolerance).sum())
    return {
        "tolerance": tolerance,
        "valid_reference": int(reference_valid.sum()),
        "valid_reproduced": int(reproduced_valid.sum()),
        "valid_both": int(both.sum()),
        "valid_only_reference": only_reference,
        "valid_only_reproduced": only_reproduced,
        "abs_difference": describe_values(abs_diff),
        "n_exceeding_tolerance": exceeding,
        "reproduced": bool(
            both.any() and only_reference == 0 and only_reproduced == 0 and exceeding == 0
        ),
    }


def summarize_valid_coverage(arrays: dict[str, np.ndarray]) -> dict[str, int]:
    """各ラスタの有効画素数を数える（EM0 版で欠測が増えていないかの確認用）。

    Args:
        arrays: 名前 -> 値の辞書。

    Returns:
        dict[str, int]: 名前 -> 有効画素数。
    """
    return {name: int(np.isfinite(values).sum()) for name, values in arrays.items()}


def compute_difference(minuend: np.ndarray, subtrahend: np.ndarray) -> np.ndarray:
    """両方が有効な画素だけで差を取る（どちらかが無効なら NaN）。

    Args:
        minuend: 引かれる側。
        subtrahend: 引く側。

    Returns:
        np.ndarray: 差（`minuend − subtrahend`）。
    """
    difference = np.full(minuend.shape, np.nan, dtype="float64")
    valid = np.isfinite(minuend) & np.isfinite(subtrahend)
    difference[valid] = minuend[valid] - subtrahend[valid]
    return difference


def pearson_on_common(x: np.ndarray, y: np.ndarray) -> dict[str, float | int | None]:
    """両方が有効な画素で Pearson の相関係数を求める。

    Args:
        x: 1 つ目の値。
        y: 2 つ目の値。

    Returns:
        dict[str, float | int | None]: `r` と `count`。2 画素未満、または値が一定の場合は
            `r` を None にする。
    """
    valid = np.isfinite(x) & np.isfinite(y)
    count = int(valid.sum())
    if count < 2:
        return {"r": None, "count": count}
    x_valid = x[valid]
    y_valid = y[valid]
    if np.std(x_valid) == 0 or np.std(y_valid) == 0:
        return {"r": None, "count": count}
    return {"r": float(np.corrcoef(x_valid, y_valid)[0, 1]), "count": count}


def summarize_by_ndvi_class(
    ndvi: np.ndarray,
    delta_lst: np.ndarray,
    delta_emissivity: np.ndarray,
    bins: Sequence[float] = DEFAULT_NDVI_BINS,
) -> pd.DataFrame:
    """NDVI の階級ごとに ΔLST と Δε を集計する。

    階級は左端のみ下限を含み、他は (下限, 上限] とする。NDVI・ΔLST のどちらかが無効な
    画素と、NDVI が階級の範囲外の画素は数えない。

    Args:
        ndvi: NDVI。
        delta_lst: ΔLST（°C）。
        delta_emissivity: Δε。
        bins: 階級の境界（昇順・2 個以上）。

    Returns:
        pd.DataFrame: 階級ごとの `ndvi_lower`・`ndvi_upper`・`count`・ΔLST の平均・中央値・
            5/95 パーセンタイル・Δε の平均。画素が無い階級は統計を NaN にする。

    Raises:
        ValueError: 境界が 2 個未満、または狭義の昇順でない場合。
    """
    edges = np.asarray(bins, dtype="float64")
    if edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError(f"NDVI 階級の境界は 2 個以上の狭義の昇順にしてください: {bins}")
    valid = np.isfinite(ndvi) & np.isfinite(delta_lst)
    ndvi_valid = ndvi[valid]
    lst_valid = delta_lst[valid]
    emissivity_valid = delta_emissivity[valid]
    rows: list[dict[str, Any]] = []
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        lower_ok = ndvi_valid >= lower if index == 0 else ndvi_valid > lower
        in_class = lower_ok & (ndvi_valid <= upper)
        lst_class = lst_valid[in_class]
        emissivity_class = emissivity_valid[in_class]
        emissivity_class = emissivity_class[np.isfinite(emissivity_class)]
        has_values = lst_class.size > 0
        rows.append(
            {
                "ndvi_lower": float(lower),
                "ndvi_upper": float(upper),
                "count": int(lst_class.size),
                "delta_lst_mean": float(np.mean(lst_class)) if has_values else np.nan,
                "delta_lst_median": float(np.median(lst_class)) if has_values else np.nan,
                "delta_lst_p5": float(np.percentile(lst_class, 5)) if has_values else np.nan,
                "delta_lst_p95": float(np.percentile(lst_class, 95)) if has_values else np.nan,
                "delta_emissivity_mean": (
                    float(np.mean(emissivity_class)) if emissivity_class.size else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_large_differences(
    delta_lst: np.ndarray,
    em0_emissivity: np.ndarray,
    ndvi: np.ndarray,
    thresholds: Sequence[float] = LARGE_DIFFERENCE_THRESHOLDS_C,
    detail_threshold: float = LARGE_DIFFERENCE_DETAIL_THRESHOLD_C,
) -> dict[str, Any]:
    """|ΔLST| の大きい画素の数と、その画素の EM0・NDVI の分布を求める。

    EM0 の異常値（ASTER GEDv3 側の値）が大きな差を生んでいないかを確かめるための集計。

    Args:
        delta_lst: ΔLST（°C。無効値は NaN）。
        em0_emissivity: EM0 版の放射率。
        ndvi: NDVI。
        thresholds: 画素数を数える |ΔLST| の閾値（°C）。
        detail_threshold: EM0・NDVI の分布を記録する |ΔLST| の閾値（°C）。

    Returns:
        dict[str, Any]: 閾値ごとの画素数（`counts_above_c`）と、`detail_threshold` を超える
            画素の EM0・NDVI の記述統計。
    """
    abs_delta = np.abs(delta_lst)
    valid = np.isfinite(abs_delta)
    counts = {
        f"{threshold:g}": int((abs_delta[valid] > threshold).sum()) for threshold in thresholds
    }
    detail = valid.copy()
    detail[valid] = abs_delta[valid] > detail_threshold
    em0_values = em0_emissivity[detail]
    ndvi_values = ndvi[detail]
    return {
        "counts_above_c": counts,
        "valid_pixels": int(valid.sum()),
        "detail_threshold_c": detail_threshold,
        "detail_em0_emissivity": describe_values(em0_values[np.isfinite(em0_values)]),
        "detail_ndvi": describe_values(ndvi_values[np.isfinite(ndvi_values)]),
    }


def table_to_json_records(table: pd.DataFrame) -> list[dict[str, Any]]:
    """表を JSON に保存できる行の辞書のリストにする（NaN は None にする）。

    画素の無い階級の統計は NaN になるが、`save_summary` は NaN を拒否する
    （JSON の標準に無いため）。CSV 用の表は変えず、JSON に入れるときだけ変換する。

    Args:
        table: 変換する表。

    Returns:
        list[dict[str, Any]]: 行ごとの辞書。欠測値は None。
    """
    return table.astype(object).where(pd.notna(table), None).to_dict(orient="records")


def save_difference_map(delta_lst: np.ndarray, transform: Affine, output_path: Path) -> None:
    """ΔLST の空間分布図を保存する（色の範囲は |ΔLST| の 99 パーセンタイルで対称にする）。

    Args:
        delta_lst: ΔLST（°C。無効値は NaN）。
        transform: アフィン変換（地理座標系）。
        output_path: 出力 PNG のパス。
    """
    finite = np.abs(delta_lst[np.isfinite(delta_lst)])
    limit = float(np.percentile(finite, 99)) if finite.size else 1.0
    limit = limit if limit > 0 else 1.0
    height, width = delta_lst.shape
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    fig, ax = plt.subplots(figsize=(7, 7.5))
    image = ax.imshow(
        delta_lst,
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
        extent=(left, right, bottom, top),
        interpolation="nearest",
    )
    fig.colorbar(image, ax=ax, shrink=0.8, label="ΔLST (NDVI-based − EM0) [°C]")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("LST difference by emissivity (NDVI-based − ASTER EM0)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_ndvi_class_plot(class_table: pd.DataFrame, output_path: Path) -> None:
    """NDVI 階級別の ΔLST（中央値と 5〜95 パーセンタイル）の図を保存する。

    Args:
        class_table: `summarize_by_ndvi_class` の戻り値。
        output_path: 出力 PNG のパス。
    """
    labels = [
        f"{row.ndvi_lower:.1f}–{row.ndvi_upper:.1f}\n(n={row.count:,})"
        for row in class_table.itertuples(index=False)
    ]
    positions = np.arange(len(class_table))
    medians = class_table["delta_lst_median"].to_numpy()
    lower_error = medians - class_table["delta_lst_p5"].to_numpy()
    upper_error = class_table["delta_lst_p95"].to_numpy() - medians
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.errorbar(
        positions, medians, yerr=[lower_error, upper_error], fmt="o", capsize=4, color="tab:blue"
    )
    ax.axhline(0.0, color="grey", linewidth=0.8)
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlabel("NDVI class")
    ax.set_ylabel("ΔLST (NDVI-based − EM0) [°C]")
    ax.set_title("ΔLST by NDVI class (median, 5–95th percentile)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# compare-runs: 分析ランの比較
# ---------------------------------------------------------------------------


def get_nested(result: dict[str, Any], keys: Sequence[str]) -> Any:
    """入れ子の辞書から値を取り出す。

    Args:
        result: results.json の辞書。
        keys: 取り出すキーの並び。

    Returns:
        Any: 取り出した値。

    Raises:
        KeyError: キーが無い場合（どの位置が無いかを示す）。
    """
    value: Any = result
    for depth, key in enumerate(keys):
        if not isinstance(value, dict) or key not in value:
            raise KeyError(f"results.json に {'.'.join(keys[: depth + 1])} がありません。")
        value = value[key]
    return value


def rank_features(values: dict[str, float], by_abs: bool) -> dict[str, int]:
    """寄与の大きい順に 1 から順位を付ける（同値は特徴量名の順）。

    Args:
        values: 特徴量 -> 寄与。
        by_abs: 絶対値で順位を付けるか（標準化係数など符号を持つ値に用いる）。

    Returns:
        dict[str, int]: 特徴量 -> 順位。
    """
    ordered = sorted(
        values, key=lambda name: (-(abs(values[name]) if by_abs else values[name]), name)
    )
    return {name: rank for rank, name in enumerate(ordered, start=1)}


def compare_importance(
    baseline: dict[str, float], variant: dict[str, float], by_abs: bool, top_k: int = TOP_K
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """2 つのランの変数の寄与と順位を比べる。

    Args:
        baseline: NDVI 版の特徴量 -> 寄与。
        variant: EM0 版の特徴量 -> 寄与。
        by_abs: 絶対値で順位を付けるか。
        top_k: 上位として比べる順位の数。

    Returns:
        tuple[pd.DataFrame, dict[str, Any]]: 特徴量ごとの表（寄与・差・順位・順位の変化）と、
            順位の Spearman 相関・上位 k の一覧と一致の有無の要約。

    Raises:
        ValueError: 2 つのランの特徴量の集合が一致しない場合。
    """
    if set(baseline) != set(variant):
        raise ValueError(
            f"2 つのランの特徴量が一致しません: {sorted(set(baseline) ^ set(variant))}"
        )
    baseline_rank = rank_features(baseline, by_abs)
    variant_rank = rank_features(variant, by_abs)
    features = sorted(baseline, key=lambda name: baseline_rank[name])
    table = pd.DataFrame(
        {
            "feature": features,
            "baseline": [float(baseline[name]) for name in features],
            "variant": [float(variant[name]) for name in features],
            "baseline_rank": [baseline_rank[name] for name in features],
            "variant_rank": [variant_rank[name] for name in features],
        }
    )
    table["difference"] = table["variant"] - table["baseline"]
    table["rank_change"] = table["variant_rank"] - table["baseline_rank"]
    baseline_top = [name for name in features if baseline_rank[name] <= top_k]
    variant_top = sorted(
        (name for name in variant if variant_rank[name] <= top_k), key=variant_rank.get
    )
    rho = stats.spearmanr(table["baseline_rank"], table["variant_rank"]).statistic
    summary = {
        "rank_by_abs": by_abs,
        "spearman_rank_correlation": float(rho),
        "top_k": top_k,
        "baseline_top": baseline_top,
        "variant_top": variant_top,
        "top_same_order": baseline_top == variant_top,
        "top_same_set": set(baseline_top) == set(variant_top),
    }
    return table, summary


def compare_metrics(baseline: dict[str, Any], variant: dict[str, Any]) -> pd.DataFrame:
    """ランダム分割と Spatial CV の評価指標を並べ、差（EM0 版 − NDVI 版）を求める。

    Args:
        baseline: NDVI 版の results.json。
        variant: EM0 版の results.json。

    Returns:
        pd.DataFrame: `evaluation`・`model`・`metric`・`baseline`・`variant`・`difference`。
    """
    rows: list[dict[str, Any]] = []
    for model in RANDOM_SPLIT_MODELS:
        for metric in RANDOM_SPLIT_METRICS:
            keys = ("random_split", model, "metrics", metric)
            rows.append(
                {
                    "evaluation": "random_split",
                    "model": model,
                    "metric": metric,
                    "baseline": float(get_nested(baseline, keys)),
                    "variant": float(get_nested(variant, keys)),
                }
            )
        for metric in SPATIAL_CV_METRICS:
            keys = ("spatial_cv", model, metric)
            rows.append(
                {
                    "evaluation": "spatial_cv",
                    "model": model,
                    "metric": metric,
                    "baseline": float(get_nested(baseline, keys)),
                    "variant": float(get_nested(variant, keys)),
                }
            )
    table = pd.DataFrame(rows)
    table["difference"] = table["variant"] - table["baseline"]
    return table


def validate_same_features(baseline: dict[str, Any], variant: dict[str, Any]) -> None:
    """2 つのランが同じ説明変数（順序を含む）で学習されたことを確かめる。

    Args:
        baseline: NDVI 版の results.json。
        variant: EM0 版の results.json。

    Raises:
        ValueError: `features` が一致しない場合（変数の違いが差に混ざるのを防ぐため）。
    """
    if baseline.get("features") != variant.get("features"):
        raise ValueError(
            "2 つのランの説明変数が一致しません: "
            f"{baseline.get('features')} != {variant.get('features')}"
        )


def summarize_target_distribution(result: dict[str, Any]) -> dict[str, Any]:
    """目的変数（LST）の分布（欠測除去後）を取り出す。

    Args:
        result: results.json。

    Returns:
        dict[str, Any]: `filter_dropout.target_distribution.after`。
    """
    return get_nested(result, ("filter_dropout", "target_distribution", "after"))


def compare_run_pair(
    name: str, baseline_path: Path, variant_path: Path
) -> tuple[dict[str, Any], dict[str, pd.DataFrame], list[Path]]:
    """1 シナリオの NDVI 版・EM0 版のランを比べる。

    Args:
        name: シナリオの名前（出力の識別用）。
        baseline_path: NDVI 版の results.json のパス。
        variant_path: EM0 版の results.json のパス。

    Returns:
        tuple[dict[str, Any], dict[str, pd.DataFrame], list[Path]]: 要約、表
            （`metrics`・`importance`・`folds`）、来歴に記録する入力ファイルのパス。
    """
    baseline = load_result(baseline_path)
    variant = load_result(variant_path)
    validate_same_evaluation(baseline, variant)
    validate_same_features(baseline, variant)

    metrics = compare_metrics(baseline, variant)
    baseline_folds_path = resolve_recorded_path(
        get_nested(baseline, ("spatial_cv", "outputs", "fold_metrics_csv"))
    )
    variant_folds_path = resolve_recorded_path(
        get_nested(variant, ("spatial_cv", "outputs", "fold_metrics_csv"))
    )
    folds = compute_fold_differences(
        pd.read_csv(baseline_folds_path), pd.read_csv(variant_folds_path)
    )

    importance_tables: list[pd.DataFrame] = []
    importance_summary: dict[str, Any] = {}
    for family, (keys, by_abs) in IMPORTANCE_FAMILIES.items():
        table, summary = compare_importance(
            get_nested(baseline, keys), get_nested(variant, keys), by_abs
        )
        table.insert(0, "family", family)
        importance_tables.append(table)
        importance_summary[family] = summary

    summary = {
        "baseline_results": to_project_relative_string(baseline_path),
        "variant_results": to_project_relative_string(variant_path),
        "baseline_dataset": baseline.get("dataset_path"),
        "variant_dataset": variant.get("dataset_path"),
        "evaluation_cells_digest": baseline["evaluation_cells"]["digest"],
        "features": baseline.get("features"),
        "metrics": metrics.to_dict(orient="records"),
        "spatial_cv_paired": summarize_metric_differences(folds),
        "importance": importance_summary,
        "target_distribution": {
            "baseline": summarize_target_distribution(baseline),
            "variant": summarize_target_distribution(variant),
        },
    }
    tables = {
        "metrics": metrics.assign(scenario=name),
        "importance": pd.concat(importance_tables, ignore_index=True).assign(scenario=name),
        "folds": folds.assign(scenario=name),
    }
    inputs = [baseline_path, variant_path, baseline_folds_path, variant_folds_path]
    return summary, tables, inputs


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------


def build_reference_paths(observation_datetime_utc: str, sensor: str) -> dict[str, Path]:
    """観測日時から、既存 LST・指標・再出力した LST と放射率のパスを作る。

    Args:
        observation_datetime_utc: UTC の観測日時（`YYYY-MM-DDTHH:MM:SS` 形式）。
        sensor: センサ名（"L8" / "L9"）。

    Returns:
        dict[str, Path]: `reference_lst`・`indices`・`ndvi_lst`・`ndvi_emissivity`・
            `em0_lst`・`em0_emissivity` のプロジェクト相対パス。
    """
    year = observation_datetime_utc[:4]
    paths = {
        "reference_lst": LST_ROOT
        / year
        / f"{build_export_description('LST', observation_datetime_utc, sensor)}.tif",
        "indices": INDICES_ROOT
        / year
        / f"{build_export_description('INDICES', observation_datetime_utc, sensor)}.tif",
    }
    for entry in build_export_plan(observation_datetime_utc, sensor):
        paths[f"{entry['variant']}_lst"] = Path(entry["local_lst_path"])
        paths[f"{entry['variant']}_emissivity"] = Path(entry["local_emissivity_path"])
    return paths


def run_lst_diff(
    paths: dict[str, Path], output_dir: Path, tolerance: float, bins: Sequence[float]
) -> Path:
    """NDVI 版の再現確認と ΔLST・Δε の集計を行い、結果と図を保存する。

    Args:
        paths: `build_reference_paths` の戻り値。
        output_dir: 出力先ディレクトリ。
        tolerance: 再現の許容差（°C）。
        bins: NDVI 階級の境界。

    Returns:
        Path: 結果 JSON のパス。
    """
    resolved = {name: resolve_existing_path(path) for name, path in paths.items()}
    sources: dict[str, tuple[Path, str | None]] = {
        name: (path, NDVI_BAND_NAME if name == "indices" else None)
        for name, path in resolved.items()
    }
    arrays, transform, crs_text = load_aligned_bands(sources)
    delta_lst = compute_difference(arrays["ndvi_lst"], arrays["em0_lst"])
    delta_emissivity = compute_difference(arrays["ndvi_emissivity"], arrays["em0_emissivity"])
    ndvi = arrays["indices"]
    class_table = summarize_by_ndvi_class(ndvi, delta_lst, delta_emissivity, bins)

    output_root = output_dir if output_dir.is_absolute() else PROJECT_ROOT / output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    class_csv = output_root / "lst_difference_by_ndvi_class.csv"
    class_table.to_csv(class_csv, index=False, encoding="utf-8")
    map_png = output_root / "lst_difference_map.png"
    class_png = output_root / "lst_difference_by_ndvi_class.png"
    save_difference_map(delta_lst, transform, map_png)
    save_ndvi_class_plot(class_table, class_png)

    result = {
        "description": "放射率（NDVI 由来・ASTER EM0）による LST の差の集計。",
        "delta_direction": DELTA_DIRECTION,
        "grid": {"crs": crs_text, "transform": list(transform)[:6], "shape": list(ndvi.shape)},
        "inputs": {name: to_project_relative_string(path) for name, path in resolved.items()},
        "reproduction_ndvi_vs_reference": summarize_reproduction(
            arrays["reference_lst"], arrays["ndvi_lst"], tolerance
        ),
        "valid_pixels": summarize_valid_coverage(
            {name: arrays[name] for name in ("reference_lst", "ndvi_lst", "em0_lst", "indices")}
        ),
        "delta_lst_c": describe_values(delta_lst[np.isfinite(delta_lst)]),
        "delta_emissivity": describe_values(delta_emissivity[np.isfinite(delta_emissivity)]),
        "correlation_with_ndvi": {
            "lst_ndvi_version": pearson_on_common(ndvi, arrays["ndvi_lst"]),
            "lst_em0_version": pearson_on_common(ndvi, arrays["em0_lst"]),
            "delta_lst": pearson_on_common(ndvi, delta_lst),
        },
        "ndvi_classes": table_to_json_records(class_table),
        "large_differences": summarize_large_differences(delta_lst, arrays["em0_emissivity"], ndvi),
        "note": (
            "統計は ROI 全体ではなく、各ラスタで有効な画素（雲マスク・ASTER GED の欠測を除く）"
            "に限る。相関は画素単位（30 m）で、分析のセル集計・欠測除去を経ていない。"
        ),
        "outputs": {
            "ndvi_class_csv": to_project_relative_string(class_csv),
            "map_png": to_project_relative_string(map_png),
            "ndvi_class_png": to_project_relative_string(class_png),
        },
        "provenance": build_provenance(
            SCRIPT_NAME, list(resolved.values()), extra_watch_paths=EXTRA_WATCH_PATHS
        ),
    }
    result_path = output_root / "lst_difference_results.json"
    save_summary(result, result_path)
    return result_path


def run_compare_runs(pairs: Sequence[tuple[str, Path, Path]], output_dir: Path) -> Path:
    """シナリオごとに NDVI 版・EM0 版のランを比べ、結果を保存する。

    Args:
        pairs: (シナリオ名, NDVI 版の results.json, EM0 版の results.json) の並び。
        output_dir: 出力先ディレクトリ。

    Returns:
        Path: 結果 JSON のパス。

    Raises:
        ValueError: シナリオ名が重複している場合。
    """
    names = [name for name, _, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError(f"シナリオ名が重複しています: {names}")
    output_root = output_dir if output_dir.is_absolute() else PROJECT_ROOT / output_dir
    output_root.mkdir(parents=True, exist_ok=True)

    scenarios: dict[str, Any] = {}
    tables: dict[str, list[pd.DataFrame]] = {"metrics": [], "importance": [], "folds": []}
    inputs: list[Path] = []
    for name, baseline_path, variant_path in pairs:
        summary, pair_tables, pair_inputs = compare_run_pair(
            name, resolve_existing_path(baseline_path), resolve_existing_path(variant_path)
        )
        scenarios[name] = summary
        for key, table in pair_tables.items():
            tables[key].append(table)
        inputs.extend(pair_inputs)

    outputs: dict[str, str] = {}
    for key, frames in tables.items():
        table_path = output_root / f"run_comparison_{key}.csv"
        pd.concat(frames, ignore_index=True).to_csv(table_path, index=False, encoding="utf-8")
        outputs[f"{key}_csv"] = to_project_relative_string(table_path)
    result = {
        "description": "NDVI 版・EM0 版の LST を目的変数にした分析ランの比較（同じ評価セル）。",
        "difference_direction": DIFFERENCE_DIRECTION,
        "scenarios": scenarios,
        "interpretation_note": (
            "EM0 版でも性能・寄与・順位がほとんど変わらなければ、NDVI の二重利用の影響は"
            "小さいと言える。大きく変わった場合は、依存の除去によるのか EM0 の誤差によるのかを"
            "本比較だけでは区別できない。"
        ),
        "outputs": outputs,
        "provenance": build_provenance(SCRIPT_NAME, inputs, extra_watch_paths=EXTRA_WATCH_PATHS),
    }
    result_path = output_root / "run_comparison_results.json"
    save_summary(result, result_path)
    return result_path


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作る。

    Returns:
        argparse.ArgumentParser: `lst-diff`・`compare-runs` を持つパーサー。
    """
    parser = argparse.ArgumentParser(
        description="LST 算出の放射率が NDVI に依存することの感度分析（差の集計）。"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--observation-datetime",
        required=True,
        help="対象観測の UTC 日時（YYYY-MM-DDTHH:MM:SS）。入出力の既定パスに用いる。",
    )
    common.add_argument("--sensor", default=DEFAULT_SENSOR, help="センサ名（L8 / L9）。")
    common.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先ディレクトリ（既定: data/output/lst_emissivity_sensitivity/ 配下）。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    diff_parser = subparsers.add_parser(
        "lst-diff", parents=[common], help="NDVI 版の再現確認と ΔLST を集計する。"
    )
    diff_parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_C,
        help="再出力と既存 GeoTIFF の一致とみなす差の絶対値の上限（°C）。",
    )
    diff_parser.add_argument(
        "--ndvi-bins",
        type=float,
        nargs="+",
        default=list(DEFAULT_NDVI_BINS),
        help="NDVI 階級の境界（昇順）。",
    )
    compare_parser = subparsers.add_parser(
        "compare-runs", parents=[common], help="NDVI 版・EM0 版の分析ランを比べる。"
    )
    compare_parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        required=True,
        metavar=("SCENARIO", "BASELINE_RESULTS", "EM0_RESULTS"),
        help="シナリオ名と、NDVI 版・EM0 版の results.json。シナリオごとに繰り返す。",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """エントリーポイント。

    Args:
        argv: コマンドライン引数（None の場合は `sys.argv` を使う）。
    """
    args = build_argument_parser().parse_args(argv)
    token = build_observation_token(args.observation_datetime)
    if args.command == "lst-diff":
        output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / token
        result_path = run_lst_diff(
            build_reference_paths(args.observation_datetime, args.sensor),
            output_dir,
            args.tolerance,
            args.ndvi_bins,
        )
    else:
        output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / token
        pairs = [(name, Path(baseline), Path(variant)) for name, baseline, variant in args.pair]
        result_path = run_compare_runs(pairs, output_dir)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    printable = {key: value for key, value in result.items() if key != "provenance"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
