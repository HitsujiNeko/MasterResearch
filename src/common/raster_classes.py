"""カテゴリラスタのクラス別集計処理。

複数の土地被覆データ取得スクリプトで重複していた、
ROI 内のクラス値ごとの画素数と有効画素率を集計する処理を集約する。
クラス体系（ラベル辞書・無効値）はデータセットごとに異なるため引数で受け取る。
"""

from __future__ import annotations

from typing import Any

import numpy as np


def build_class_distribution(
    array: np.ndarray,
    class_labels: dict[int, str],
    *,
    filled_values: tuple[int, ...],
    roi_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """ROI 内のクラス値ごとの画素数と、ROI 内での有効画素率を集計する。

    ROI ポリゴンでクリップした出力は ROI の BBOX 矩形になり、ROI 外の余白は
    nodata で埋まる。この余白を「欠測」と数えると有効カバレッジを ROI 全体と
    取り違えるため、`roi_mask` で ROI 内外を分けて集計する。有効画素率の分母は
    **ROI 内の画素数** であり、ラスタ全体の画素数ではない。

    Args:
        array: クラス値の配列。
        class_labels: クラス値からラベルへの対応表。ここに無い値は
            `unknown_class_values` として報告する。
        filled_values: 無効値として扱う値。省略すると nodata を有効画素として
            数えて有効カバレッジを過大評価してしまうため、必須のキーワード引数と
            している（無効値を持たないデータでは空タプルを明示的に渡す）。
        roi_mask: ROI 内を True とする真偽値配列。
            None の場合は全画素を ROI 内として扱う。

    Returns:
        画素統計とクラス別内訳。
            - total_pixels: ラスタ全体（ROI の BBOX 矩形）の画素数
            - roi_pixels: ROI 内の画素数
            - outside_roi_pixels: ROI 外（クリップ余白）の画素数
            - filled_pixels: ROI 内の無効値画素数
            - valid_pixels: ROI 内の有効画素数
            - valid_pixel_ratio: ROI 内での有効画素率（ROI 内画素が0の場合は0.0）
            - classes: クラスごとの value / label / pixel_count / ratio のリスト
              （画素数の降順、ROI 内のみ）
            - unknown_class_values: 分類体系にないクラス値のリスト

    Raises:
        ValueError: roi_mask の形状が array と一致しない場合。
    """
    total_pixels = int(array.size)
    if roi_mask is None:
        roi_values = array
    else:
        if roi_mask.shape != array.shape:
            raise ValueError(
                f"roi_mask の形状が array と一致しません: {roi_mask.shape} != {array.shape}"
            )
        roi_values = array[roi_mask]

    roi_pixels = int(roi_values.size)
    values, counts = np.unique(roi_values, return_counts=True)

    filled_pixels = int(
        sum(int(count) for value, count in zip(values, counts) if int(value) in filled_values)
    )
    valid_pixels = roi_pixels - filled_pixels

    classes: list[dict[str, Any]] = []
    unknown_class_values: list[int] = []
    for value, count in zip(values, counts):
        class_value = int(value)
        if class_value in filled_values:
            continue
        if class_value not in class_labels:
            unknown_class_values.append(class_value)
        classes.append(
            {
                "value": class_value,
                "label": class_labels.get(class_value, "Unknown"),
                "pixel_count": int(count),
                "ratio": (int(count) / valid_pixels) if valid_pixels > 0 else 0.0,
            }
        )
    classes.sort(key=lambda item: item["pixel_count"], reverse=True)

    return {
        "total_pixels": total_pixels,
        "roi_pixels": roi_pixels,
        "outside_roi_pixels": total_pixels - roi_pixels,
        "filled_pixels": filled_pixels,
        "valid_pixels": valid_pixels,
        "valid_pixel_ratio": (valid_pixels / roi_pixels) if roi_pixels > 0 else 0.0,
        "classes": classes,
        "unknown_class_values": sorted(unknown_class_values),
    }
