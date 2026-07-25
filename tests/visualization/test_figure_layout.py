"""figure_layout.py（QGIS非依存のレイアウト計算）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from src.visualization.figure_layout import (
    LEGEND_ITEMS,
    LEGEND_NONE,
    MAP_TOP_MM,
    NONE_BOTTOM_MM,
    SIDE_MARGIN_MM,
    layout_geometry,
    map_frame_size,
    page_size,
    present_class_values,
    roi_extent_with_margin,
    shorten_label,
)

# ハノイ ROI + 5%マージン相当の代表的な描画範囲（EPSG:4326）
HANOI_EXTENT = (105.2515, 20.5235, 106.0566, 21.4262)


def test_roi_extent_with_margin_expands_each_side() -> None:
    """各辺に幅・高さの割合分だけマージンが加わる。"""
    result = roi_extent_with_margin((0.0, 0.0, 10.0, 20.0), ratio=0.1)
    assert result == pytest.approx((-1.0, -2.0, 11.0, 22.0))


def test_roi_extent_with_margin_zero_ratio_is_identity() -> None:
    """ratio=0 なら範囲は変わらない。"""
    extent = (105.0, 20.0, 106.0, 21.0)
    assert roi_extent_with_margin(extent, ratio=0.0) == pytest.approx(extent)


@pytest.mark.parametrize(
    "extent",
    [(0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 0.0), (1.0, 1.0, 0.0, 0.0)],
)
def test_roi_extent_with_margin_rejects_degenerate(extent) -> None:
    """退化した範囲は ValueError。"""
    with pytest.raises(ValueError):
        roi_extent_with_margin(extent)


def test_roi_extent_with_margin_rejects_negative_ratio() -> None:
    """負の ratio は ValueError。"""
    with pytest.raises(ValueError):
        roi_extent_with_margin((0.0, 0.0, 1.0, 1.0), ratio=-0.1)


def test_map_frame_size_matches_extent_aspect() -> None:
    """フレーム高さは幅×(範囲高さ/範囲幅)。縦横比が範囲に一致する。"""
    # 幅2・高さ1 の範囲 → フレーム幅180 なら高さ90
    assert map_frame_size((0.0, 0.0, 2.0, 1.0), frame_width_mm=180.0) == pytest.approx(90.0)


def test_map_frame_size_square_extent() -> None:
    """正方形の範囲ではフレームも正方形。"""
    assert map_frame_size((0.0, 0.0, 1.0, 1.0), frame_width_mm=180.0) == pytest.approx(180.0)


def test_map_frame_size_hanoi_aspect() -> None:
    """ハノイ範囲でフレーム縦横比が範囲の縦横比に一致する（見切れ防止の核）。"""
    xmin, ymin, xmax, ymax = HANOI_EXTENT
    frame_w = 180.0
    frame_h = map_frame_size(HANOI_EXTENT, frame_w)
    assert frame_w / frame_h == pytest.approx((xmax - xmin) / (ymax - ymin))


def test_map_frame_size_rejects_bad_input() -> None:
    """退化範囲・非正のフレーム幅は ValueError。"""
    with pytest.raises(ValueError):
        map_frame_size((0.0, 0.0, 0.0, 1.0), frame_width_mm=180.0)
    with pytest.raises(ValueError):
        map_frame_size((0.0, 0.0, 1.0, 1.0), frame_width_mm=0.0)


def test_page_size_none_legend() -> None:
    """凡例なし: ページ高さ = 地図上端 + 地図高さ + 下部余白。"""
    width, height = page_size(180.0, 202.0, LEGEND_NONE)
    assert width == pytest.approx(180.0 + 2 * SIDE_MARGIN_MM)
    assert height == pytest.approx(MAP_TOP_MM + 202.0 + NONE_BOTTOM_MM)


def test_page_size_items_legend_is_taller_than_none() -> None:
    """項目凡例ありは、同じ地図高さの凡例なしよりページが高い。"""
    _, none_h = page_size(180.0, 202.0, LEGEND_NONE)
    _, items_h = page_size(180.0, 202.0, LEGEND_ITEMS, legend_h_mm=55.0)
    assert items_h > none_h


def test_page_size_rejects_unknown_kind() -> None:
    """未知の legend_kind は ValueError。"""
    with pytest.raises(ValueError):
        page_size(180.0, 202.0, "bogus")


@pytest.mark.parametrize(
    ("frame_w", "map_h", "kind", "legend_h"),
    [
        (0.0, 202.0, LEGEND_NONE, 55.0),
        (180.0, 0.0, LEGEND_NONE, 55.0),
        (180.0, 202.0, LEGEND_ITEMS, 0.0),
    ],
)
def test_page_size_rejects_nonpositive_dimensions(frame_w, map_h, kind, legend_h) -> None:
    """フレーム幅・地図高さ・凡例帯高さが 0 以下なら ValueError。"""
    with pytest.raises(ValueError):
        page_size(frame_w, map_h, kind, legend_h)


def test_layout_geometry_rejects_unknown_kind() -> None:
    """layout_geometry も未知の legend_kind を弾く。"""
    with pytest.raises(ValueError):
        layout_geometry(HANOI_EXTENT, legend_kind="bogus")


def test_layout_geometry_none_has_no_legend() -> None:
    """凡例なしでは legend は None、page は page_size と一致する。"""
    geom = layout_geometry(HANOI_EXTENT, frame_width_mm=180.0, legend_kind=LEGEND_NONE)
    assert geom["legend"] is None
    map_h = map_frame_size(HANOI_EXTENT, 180.0)
    assert geom["map"] == pytest.approx((SIDE_MARGIN_MM, MAP_TOP_MM, 180.0, map_h))
    assert geom["page"] == pytest.approx(page_size(180.0, map_h, LEGEND_NONE))


def test_layout_geometry_items_has_legend_rect() -> None:
    """項目凡例では legend が (x, y, w, h) を持ち、地図の下に置かれる。"""
    geom = layout_geometry(
        HANOI_EXTENT, frame_width_mm=180.0, legend_kind=LEGEND_ITEMS, legend_h_mm=55.0
    )
    assert geom["legend"] is not None
    legend_x, legend_y, legend_w, legend_h = geom["legend"]
    map_x, map_y, map_w, map_h = geom["map"]
    assert legend_x == pytest.approx(map_x)
    assert legend_w == pytest.approx(map_w)
    assert legend_h == pytest.approx(55.0)
    assert legend_y > map_y + map_h  # 地図の下端より下にある


def test_layout_geometry_scalebar_inside_map() -> None:
    """スケールバーは地図フレームの内側（下端より上）に置かれ、凡例と重ならない。"""
    geom = layout_geometry(
        HANOI_EXTENT, frame_width_mm=180.0, legend_kind=LEGEND_ITEMS, legend_h_mm=55.0
    )
    map_x, map_y, map_w, map_h = geom["map"]
    sb_x, sb_y = geom["scalebar"]
    legend_y = geom["legend"][1]
    assert map_y < sb_y < map_y + map_h  # 地図フレームの内側
    assert sb_y < legend_y  # 凡例より上（重ならない）


def test_present_class_values_excludes_nodata_and_sorts() -> None:
    """nodata を除外し、実在クラス値を昇順の整数で返す。"""
    values = np.array([[0, 10, 20], [10, 190, 0], [210, 20, 20]])
    assert present_class_values(values, nodata=0) == [10, 20, 190, 210]


def test_present_class_values_keeps_all_without_nodata() -> None:
    """nodata=None なら全クラスを残す。"""
    values = np.array([0, 0, 5, 5, 12])
    assert present_class_values(values, nodata=None) == [0, 5, 12]


def test_present_class_values_skips_nan() -> None:
    """NaN は nodata 指定の有無に関わらず除外される。"""
    values = np.array([10.0, np.nan, 20.0, np.nan])
    assert present_class_values(values, nodata=None) == [10, 20]


def test_present_class_values_rounds_floats() -> None:
    """浮動小数のクラス値は四捨五入して整数化する。"""
    values = np.array([9.6, 9.6, 20.4])
    assert present_class_values(values, nodata=None) == [10, 20]


def test_shorten_label_removes_english_parenthetical() -> None:
    """半角スペース＋半角括弧以降を除き、日本語の全角括弧は残す。"""
    assert shorten_label("10 天水農地 (Rainfed cropland)") == "10 天水農地"
    assert (
        shorten_label("12 樹木・低木被覆農地（果樹園） (Tree or shrub cover (Orchard))")
        == "12 樹木・低木被覆農地（果樹園）"
    )


def test_shorten_label_without_parenthetical_is_unchanged() -> None:
    """英語括弧がなければそのまま返す。"""
    assert shorten_label("190 不透水面") == "190 不透水面"
