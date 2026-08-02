"""ラスタの有効画素に対する記述統計と、値の飽和判定。

取得元（GEE・HTTP 配布サイト・ローカル）に依存しない画素値の集計処理を集約する。
入力は「有効画素だけを取り出した 1 次元配列」であり、どの画素を有効とみなすかの
判断は呼び出し側（データセットごとの nodata・マスクの意味づけ）に委ねる。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

# 飽和判定で「最大値の近傍」とみなす既定の相対幅。max の 1% 以内を同一水準として数える。
DEFAULT_SATURATION_NEIGHBORHOOD_RATIO = 0.01

# `build_multiband_pixel_statistics` がバンド別統計と同じ階層に置く固定キー。
# バンド名がこれらと重なると統計が上書きされるため、事前に弾く。
RESERVED_STATISTICS_KEYS = frozenset(
    {
        "total_pixels",
        "roi_pixels",
        "outside_roi_pixels",
        "valid_pixels",
        "valid_pixel_ratio",
        "primary_band",
        "covers_requested_area",
        "saturation",
    }
)


def build_band_statistics(values: np.ndarray) -> dict[str, float] | None:
    """有効画素の記述統計を求める。

    Args:
        values: 有効画素の 1 次元配列。

    Returns:
        記述統計。有効画素が無い場合は None。
    """
    if values.size == 0:
        return None
    # float32 のまま累算すると平均・標準偏差が丸め誤差を拾うため float64 で集計する
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values, dtype=np.float64)),
        "std": float(np.std(values, dtype=np.float64)),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }


def build_saturation_indicators(
    values: np.ndarray,
    neighborhood_ratio: float = DEFAULT_SATURATION_NEIGHBORHOOD_RATIO,
) -> dict[str, Any] | None:
    """値の飽和（上限への張り付き）の程度を表す指標を求める。

    夜間光は都市中心部で値が飽和し、密集市街地内の空間パターンを識別できなくなる
    ことが知られている。飽和していれば「最大値と同水準の画素」がある程度の面積を
    占め、上位分位点（p99）が最大値に肉薄する。逆に飽和していなければ、最大値は
    少数の画素にしか現れず p99 との差が大きい。

    Args:
        values: 有効画素の 1 次元配列。
        neighborhood_ratio: 最大値の近傍とみなす相対幅（max に対する割合）。

    Returns:
        飽和指標の辞書。有効画素が無い場合は None。
    """
    if values.size == 0:
        return None

    values_float64 = values.astype(np.float64)
    max_value = float(np.max(values_float64))
    p99_value = float(np.percentile(values_float64, 99))
    p999_value = float(np.percentile(values_float64, 99.9))

    at_max_count = int(np.count_nonzero(values_float64 == max_value))
    # 最大値が 0 以下（全画素が消灯・負値）の場合、相対幅の近傍は定義できない
    if max_value > 0.0:
        threshold = max_value * (1.0 - neighborhood_ratio)
        near_max_count = int(np.count_nonzero(values_float64 >= threshold))
        p99_to_max_ratio: float | None = p99_value / max_value
    else:
        near_max_count = at_max_count
        p99_to_max_ratio = None

    return {
        "max": max_value,
        "p99": p99_value,
        "p99_9": p999_value,
        # 1.0 に近いほど上位が最大値に張り付いている＝飽和が疑われる
        "p99_to_max_ratio": p99_to_max_ratio,
        "pixels_at_max": at_max_count,
        # 近傍の幅は neighborhood_ratio が可変なので、キー名に割合を埋め込まない
        "pixels_near_max": near_max_count,
        "ratio_near_max": near_max_count / values.size,
        "neighborhood_ratio": neighborhood_ratio,
    }


def build_multiband_pixel_statistics(
    band_arrays: dict[str, np.ndarray],
    area_mask: np.ndarray,
    covers_area: bool,
    primary_band: str,
    nodata: float,
    saturation_bands: Sequence[str] = (),
) -> dict[str, Any]:
    """多バンドラスタの画素統計を、バンドごとの有効画素で集計する。

    **有効画素はバンドごとに別々に数える**。品質フラグや背景マスクの都合で一部
    バンドだけ欠測になるデータセットは多く、全バンドが揃う画素だけに絞ると、
    残りのバンドの統計まで母集団が痩せてしまうため。

    最上位の `valid_pixels` / `valid_pixel_ratio` は**データ被覆の指標**として
    `primary_band` で代表させる。分母は対象範囲内の画素数（ROI 全体ではない）。

    出力キー `roi_pixels` は `area_mask` が True の画素数であり、**試行実行
    （`--bbox` 指定）では ROI ではなく指定 BBOX 内の画素数**になる。名称は既存の
    サマリー JSON との互換のため据え置いているので、試行実行かどうかは同じ
    サマリーの `is_trial_run` で判断すること。

    Args:
        band_arrays: バンド名 -> 2 次元配列。
        area_mask: 対象範囲内を True とする 2 次元マスク。
        covers_area: 出力が要求範囲を覆えているか。
        primary_band: データ被覆を代表させるバンド名。
        nodata: 無効値。
        saturation_bands: 飽和指標を算出するバンド名（値が連続量のもののみ）。

    Returns:
        画素数・バンド別統計・飽和指標を含む辞書。

    Raises:
        KeyError: `primary_band` または `saturation_bands` が `band_arrays` に無い場合。
        ValueError: バンド名が `RESERVED_STATISTICS_KEYS` と衝突する場合、
            バンド間で配列の形状が揃っていない場合、
            または `area_mask` の形状がバンドと一致しない場合。
    """
    if primary_band not in band_arrays:
        raise KeyError(f"主バンド {primary_band!r} が入力に含まれていません: {list(band_arrays)}")
    missing_saturation_bands = [name for name in saturation_bands if name not in band_arrays]
    if missing_saturation_bands:
        raise KeyError(f"飽和指標の対象バンドが入力に含まれていません: {missing_saturation_bands}")
    # バンド別統計は固定キーと同じ階層に置くため、名前が衝突すると上書きが起き、
    # 例外にならないまま統計が静かに壊れる（後段の saturation の代入が典型）。
    # 階層はサマリー JSON の既存構造なので変えず、衝突を明示的に弾く
    conflicting_band_names = sorted(set(band_arrays) & RESERVED_STATISTICS_KEYS)
    if conflicting_band_names:
        raise ValueError(
            f"バンド名が統計の予約キーと衝突しています: {conflicting_band_names}。"
            f"予約キー: {sorted(RESERVED_STATISTICS_KEYS)}"
        )

    # 形状が揃っていないと numpy の不可解な IndexError になるか、
    # 条件次第でブロードキャストされて誤った集計が静かに通る
    shapes = {name: array.shape for name, array in band_arrays.items()}
    if len(set(shapes.values())) != 1:
        raise ValueError(f"バンド間で配列の形状が揃っていません: {shapes}")
    band_shape = next(iter(shapes.values()))
    if area_mask.shape != band_shape:
        raise ValueError(
            f"area_mask の形状がバンドと一致しません（マスク {area_mask.shape}、"
            f"バンド {band_shape}）。"
        )

    area_pixel_count = int(np.count_nonzero(area_mask))
    total_pixels = int(band_arrays[primary_band].size)

    band_valid_masks = {name: area_mask & (array != nodata) for name, array in band_arrays.items()}
    primary_valid_count = int(np.count_nonzero(band_valid_masks[primary_band]))

    statistics: dict[str, Any] = {
        "total_pixels": total_pixels,
        "roi_pixels": area_pixel_count,
        "outside_roi_pixels": total_pixels - area_pixel_count,
        "valid_pixels": primary_valid_count,
        "valid_pixel_ratio": (
            primary_valid_count / area_pixel_count if area_pixel_count > 0 else 0.0
        ),
        "primary_band": primary_band,
        "covers_requested_area": covers_area,
    }

    for name, array in band_arrays.items():
        valid_values = array[band_valid_masks[name]]
        statistics[name] = {
            **(build_band_statistics(valid_values) or {}),
            "valid_pixels": int(valid_values.size),
            "valid_pixel_ratio": (
                valid_values.size / area_pixel_count if area_pixel_count > 0 else 0.0
            ),
        }

    statistics["saturation"] = {
        name: build_saturation_indicators(band_arrays[name][band_valid_masks[name]])
        for name in saturation_bands
    }
    return statistics
