"""QGIS 図（スクリーンショット）の印刷レイアウト寸法を計算する純粋関数群。

PyQGIS に依存せず、レイアウトの寸法・位置（mm）だけを算出する。QGIS ランタイム
非依存なので、通常の ``pytest`` で単体検証できる。実際のレイアウト構築・PNG 出力は
:mod:`src.visualization.qgis_figure` が本モジュールの計算結果を用いて行う。

設計の要点:
- 地図フレームの縦横比を描画範囲（ROI）と一致させることで、地図の見切れを防ぐ。
- 凡例が必要な図はページ自体を縦に伸ばし、地図の下に凡例帯を置く（地図は縮めない）。
"""

from __future__ import annotations

import numpy as np

# レイアウト定数（mm）。全図で共通の体裁を保つための基準値。
SIDE_MARGIN_MM = 10.0  # 左右余白
TITLE_TOP_MM = 8.0  # タイトルの上端 y
MAP_TOP_MM = 22.0  # 地図フレームの上端 y
SCALEBAR_INSET_X_MM = 6.0  # スケールバーの地図左端からの差し込み量
SCALEBAR_INSET_Y_MM = 16.0  # スケールバーの地図下端からの差し込み量（枠内に置く）
LEGEND_GAP_MM = 6.0  # 地図下端から凡例帯までの間隔（スケールバーは枠内なので詰められる）
BOTTOM_MARGIN_MM = 8.0  # 凡例帯下端からページ下端までの余白
NONE_BOTTOM_MM = 12.0  # 凡例なし図の、地図下端からページ下端までの余白

# 凡例の種別
LEGEND_NONE = "none"  # 凡例なし（単一シンボル）
LEGEND_ITEMS = "items"  # 項目凡例（カテゴリ値・連続値ラスタ）
_LEGEND_KINDS = (LEGEND_NONE, LEGEND_ITEMS)


def roi_extent_with_margin(
    extent: tuple[float, float, float, float], ratio: float = 0.05
) -> tuple[float, float, float, float]:
    """描画範囲に上下左右へ一定割合のマージンを加えて返す。

    Args:
        extent: ``(xmin, ymin, xmax, ymax)``。
        ratio: 各辺に加えるマージンの割合（幅・高さに対する比）。

    Returns:
        マージンを加えた ``(xmin, ymin, xmax, ymax)``。

    Raises:
        ValueError: 範囲が退化している（幅・高さが 0 以下）か ``ratio`` が負のとき。
    """
    xmin, ymin, xmax, ymax = extent
    if xmax <= xmin or ymax <= ymin:
        raise ValueError(f"退化した範囲です: {extent}")
    if ratio < 0:
        raise ValueError(f"ratio は 0 以上である必要があります: {ratio}")
    dx = (xmax - xmin) * ratio
    dy = (ymax - ymin) * ratio
    return (xmin - dx, ymin - dy, xmax + dx, ymax + dy)


def map_frame_size(
    extent: tuple[float, float, float, float], frame_width_mm: float = 180.0
) -> float:
    """描画範囲の縦横比に一致する地図フレーム高さ（mm）を返す。

    フレーム幅を固定し、フレームの縦横比を範囲（地図単位）の縦横比に合わせることで、
    ``QgsLayoutItemMap.setExtent`` によるフレーム比率への自動拡張（＝ROI の見切れ）を防ぐ。

    Args:
        extent: ``(xmin, ymin, xmax, ymax)``。
        frame_width_mm: 地図フレームの幅（mm）。

    Returns:
        地図フレームの高さ（mm）。

    Raises:
        ValueError: 範囲が退化しているか、フレーム幅が 0 以下のとき。
    """
    xmin, ymin, xmax, ymax = extent
    width = xmax - xmin
    height = ymax - ymin
    if width <= 0 or height <= 0:
        raise ValueError(f"退化した範囲です: {extent}")
    if frame_width_mm <= 0:
        raise ValueError(f"frame_width_mm は正である必要があります: {frame_width_mm}")
    return frame_width_mm * (height / width)


def page_size(
    frame_width_mm: float,
    map_height_mm: float,
    legend_kind: str,
    legend_h_mm: float = 55.0,
) -> tuple[float, float]:
    """ページ寸法 ``(幅, 高さ)``（mm）を返す。

    凡例ありのときは地図を縮めず、地図の下に凡例帯を置く分だけページを縦に伸ばす。

    Args:
        frame_width_mm: 地図フレームの幅（mm）。
        map_height_mm: 地図フレームの高さ（mm）。
        legend_kind: :data:`LEGEND_NONE` か :data:`LEGEND_ITEMS`。
        legend_h_mm: 項目凡例帯の高さ（mm）。``legend_kind`` が items のときのみ使用。

    Returns:
        ``(page_width_mm, page_height_mm)``。

    Raises:
        ValueError: 引数が不正なとき。
    """
    if legend_kind not in _LEGEND_KINDS:
        raise ValueError(f"未知の legend_kind です: {legend_kind}")
    if frame_width_mm <= 0 or map_height_mm <= 0:
        raise ValueError("frame_width_mm・map_height_mm は正である必要があります")
    page_width = frame_width_mm + 2 * SIDE_MARGIN_MM
    map_bottom = MAP_TOP_MM + map_height_mm
    if legend_kind == LEGEND_NONE:
        page_height = map_bottom + NONE_BOTTOM_MM
    else:  # LEGEND_ITEMS
        if legend_h_mm <= 0:
            raise ValueError(f"legend_h_mm は正である必要があります: {legend_h_mm}")
        legend_y = map_bottom + LEGEND_GAP_MM
        page_height = legend_y + legend_h_mm + BOTTOM_MARGIN_MM
    return (page_width, page_height)


def layout_geometry(
    extent: tuple[float, float, float, float],
    frame_width_mm: float = 180.0,
    legend_kind: str = LEGEND_NONE,
    legend_h_mm: float = 55.0,
) -> dict:
    """各レイアウト要素の位置・サイズ（mm）とページ寸法をまとめて返す。

    :mod:`src.visualization.qgis_figure` はこの戻り値に従って印刷レイアウトを組む。

    スケールバーは地図フレームの左下隅（枠内）に置く。凡例と縦に重ならないようにし、
    かつ凡例を全幅で使えるようにするため。

    Returns:
        以下のキーを持つ辞書（値は mm）:

        - ``page``: ``(width, height)``
        - ``map``: ``(x, y, width, height)``
        - ``title``: ``(x, y)``
        - ``scalebar``: ``(x, y)``（地図フレーム内の左下）
        - ``legend``: ``(x, y, width, height)`` または ``None``（凡例なし）
    """
    if legend_kind not in _LEGEND_KINDS:
        raise ValueError(f"未知の legend_kind です: {legend_kind}")
    map_height = map_frame_size(extent, frame_width_mm)
    page = page_size(frame_width_mm, map_height, legend_kind, legend_h_mm)
    map_bottom = MAP_TOP_MM + map_height
    geometry: dict = {
        "page": page,
        "map": (SIDE_MARGIN_MM, MAP_TOP_MM, frame_width_mm, map_height),
        "title": (SIDE_MARGIN_MM, TITLE_TOP_MM),
        "scalebar": (
            SIDE_MARGIN_MM + SCALEBAR_INSET_X_MM,
            map_bottom - SCALEBAR_INSET_Y_MM,
        ),
        "legend": None,
    }
    if legend_kind == LEGEND_ITEMS:
        geometry["legend"] = (
            SIDE_MARGIN_MM,
            map_bottom + LEGEND_GAP_MM,
            frame_width_mm,
            legend_h_mm,
        )
    return geometry


def present_class_values(values, nodata: float | None = None) -> list[int]:
    """ラスタ値の配列から、実在するクラス値（整数）を昇順で返す。

    カテゴリ値ラスタの凡例を「実際にデータへ現れるクラス」だけに絞るために使う。
    ``nodata`` は除外する。

    Args:
        values: ラスタ画素値の配列（``numpy`` 配列や任意の数値イテラブル）。
        nodata: 除外する無効値。``None`` なら除外しない。

    Returns:
        実在クラス値（整数）の昇順リスト。
    """
    unique = np.unique(np.asarray(values))
    result: list[int] = []
    for value in unique:
        if nodata is not None and value == nodata:
            continue
        result.append(int(round(float(value))))
    return result


def shorten_label(label: str) -> str:
    """凡例ラベルから英語括弧部分を除き、日本語部分を返す。

    例: ``"10 天水農地 (Rainfed cropland)"`` -> ``"10 天水農地"``。
    半角スペース＋半角開き括弧 ``" ("`` を区切りとするため、日本語側の全角括弧
    ``（）`` は保持される。

    Args:
        label: 元のラベル文字列。

    Returns:
        短縮後のラベル（前後の空白は除去）。
    """
    return label.split(" (")[0].strip()
