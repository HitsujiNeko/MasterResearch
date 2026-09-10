"""roi_location_map.py（ROI 位置図のレイアウト計算・注記）のテスト。

タイル取得と描画を伴う ``build_roi_location_map`` は対象外とし、
図の体裁を決める純関数のみを検証する。
"""

from __future__ import annotations

import pytest

from src.visualization.roi_location_map import (
    BOUNDARY_ATTRIBUTION,
    CREDIT_MAX_LINE_CHARS,
    PROJECTION_NOTE,
    credit_lines,
    expand_extent,
    format_latitude,
    format_longitude,
    graticule_ticks,
    layout_rects,
    nice_scalebar_length_km,
)
from src.visualization.xyz_tiles import PROVIDERS

# ハノイ ROI 相当の縦横比（高さ/幅）とベトナム全図の縦横比。
HANOI_MAP_ASPECT = 1.2
VIETNAM_INSET_ASPECT = 2.14


def test_nice_scalebar_length_picks_quarter_of_width() -> None:
    """地図幅のおよそ4分の1に近い切りのよい長さを選ぶ。"""
    # 幅91kmなら目安は約25km。
    assert nice_scalebar_length_km(91.0) == 25


def test_nice_scalebar_length_scales_with_map_width() -> None:
    """地図が広いほど長いスケールバーを選ぶ。"""
    assert nice_scalebar_length_km(1000.0) > nice_scalebar_length_km(50.0)


def test_nice_scalebar_length_returns_listed_value() -> None:
    """戻り値は候補に含まれる切りのよい値である。"""
    assert nice_scalebar_length_km(7.3) in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500)


@pytest.mark.parametrize("width_km", [0.0, -10.0])
def test_nice_scalebar_length_rejects_non_positive(width_km: float) -> None:
    """幅が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        nice_scalebar_length_km(width_km)


def test_graticule_ticks_are_inside_range_and_sorted() -> None:
    """目盛はすべて区間内にあり、昇順に並ぶ。"""
    ticks = graticule_ticks(105.245, 106.064)
    assert ticks == sorted(ticks)
    assert all(105.245 <= tick <= 106.064 for tick in ticks)


def test_graticule_ticks_use_constant_spacing() -> None:
    """目盛の間隔は一定である。"""
    ticks = graticule_ticks(20.515, 21.435)
    steps = [round(b - a, 6) for a, b in zip(ticks[:-1], ticks[1:], strict=True)]
    assert len(set(steps)) == 1


def test_graticule_ticks_respect_target_count() -> None:
    """目盛数は目安の前後に収まる。"""
    ticks = graticule_ticks(105.245, 106.064, target_count=4)
    assert 2 <= len(ticks) <= 7


def test_graticule_ticks_can_be_empty_for_narrow_range() -> None:
    """最小間隔より狭い区間では目盛が入らないことがある。"""
    assert graticule_ticks(105.201, 105.209) == []


@pytest.mark.parametrize(
    ("minimum", "maximum", "target"),
    [(1.0, 1.0, 4), (2.0, 1.0, 4), (1.0, 2.0, 0)],
)
def test_graticule_ticks_reject_invalid_input(minimum: float, maximum: float, target: int) -> None:
    """区間または目盛数が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        graticule_ticks(minimum, maximum, target_count=target)


def test_format_longitude_marks_hemisphere() -> None:
    """東経・西経が記号で書き分けられる。"""
    assert format_longitude(105.6) == "105.6°E"
    assert format_longitude(-30.0) == "30°W"


def test_format_latitude_marks_hemisphere() -> None:
    """北緯・南緯が記号で書き分けられる。"""
    assert format_latitude(21.0) == "21°N"
    assert format_latitude(-8.5) == "8.5°S"


def test_expand_extent_adds_margin_to_each_side() -> None:
    """各辺に幅・高さの割合分の余白が加わる。"""
    assert expand_extent((0.0, 0.0, 10.0, 20.0), 0.1) == pytest.approx((-1.0, -2.0, 11.0, 22.0))


def test_expand_extent_zero_ratio_is_identity() -> None:
    """割合0なら範囲は変わらない。"""
    extent = (105.0, 20.0, 106.0, 21.0)
    assert expand_extent(extent, 0.0) == pytest.approx(extent)


@pytest.mark.parametrize(
    ("extent", "ratio"),
    [
        ((0.0, 0.0, 0.0, 1.0), 0.1),  # 幅が0
        ((0.0, 0.0, 1.0, 0.0), 0.1),  # 高さが0
        ((0.0, 0.0, 1.0, 1.0), -0.1),  # 割合が負
    ],
)
def test_expand_extent_rejects_invalid_input(
    extent: tuple[float, float, float, float], ratio: float
) -> None:
    """範囲または割合が不正ならエラーになる。"""
    with pytest.raises(ValueError):
        expand_extent(extent, ratio)


def test_layout_rects_returns_positive_figure_size() -> None:
    """図の寸法は正の値になる。"""
    width, height, _ = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    assert width > 0
    assert height > 0


def test_layout_rects_keeps_all_axes_inside_figure() -> None:
    """すべての軸が figure の内側（0-1）に収まる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    assert set(rects) == {"map", "inset", "legend", "credit"}
    for left, bottom, width, height in rects.values():
        assert 0.0 <= left and 0.0 <= bottom
        assert width > 0 and height > 0
        assert left + width <= 1.0 + 1e-9
        assert bottom + height <= 1.0 + 1e-9


def test_layout_rects_places_right_column_beside_map() -> None:
    """インセットと凡例は本図の右側に置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    map_right = rects["map"][0] + rects["map"][2]
    assert rects["inset"][0] >= map_right
    assert rects["legend"][0] >= map_right


def test_layout_rects_stacks_legend_below_inset() -> None:
    """凡例はインセットの下に、重ならずに置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    legend_top = rects["legend"][1] + rects["legend"][3]
    assert legend_top <= rects["inset"][1] + 1e-9


def test_layout_rects_places_credit_below_map() -> None:
    """出典表記は本図より下に置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    credit_top = rects["credit"][1] + rects["credit"][3]
    assert credit_top <= rects["map"][1] + 1e-9


def test_layout_rects_widens_figure_for_wider_map() -> None:
    """本図が横長になるほど図全体も広くなる。"""
    narrow, _, _ = layout_rects(1.5, VIETNAM_INSET_ASPECT)
    wide, _, _ = layout_rects(0.8, VIETNAM_INSET_ASPECT)
    assert wide > narrow


@pytest.mark.parametrize(("map_aspect", "inset_aspect"), [(0.0, 2.0), (1.2, 0.0), (-1.0, 2.0)])
def test_layout_rects_rejects_non_positive_aspect(map_aspect: float, inset_aspect: float) -> None:
    """縦横比が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        layout_rects(map_aspect, inset_aspect)


# ベースマップ配信元の出典表記の一例（OpenStreetMap タイル）。
BASEMAP_ATTRIBUTION = "Basemap: © OpenStreetMap contributors"


def test_credit_lines_keeps_required_attributions() -> None:
    """表示義務のある2つの出典表記がいずれも含まれる。"""
    joined = "\n".join(credit_lines(BASEMAP_ATTRIBUTION))
    assert BASEMAP_ATTRIBUTION in joined
    assert BOUNDARY_ATTRIBUTION in joined


def test_credit_lines_puts_licence_text_before_projection_note() -> None:
    """表示義務のある表記を先に、義務の無い投影法の注記を後に置く。"""
    lines = credit_lines(BASEMAP_ATTRIBUTION)
    assert lines == [BASEMAP_ATTRIBUTION, BOUNDARY_ATTRIBUTION, PROJECTION_NOTE]


def test_credit_lines_are_much_shorter_than_single_line_form() -> None:
    """最長の行が、1行にまとめた場合の半分より短い。

    行長が縮むぶんだけ文字を大きくできる、というのが複数行に分ける理由である。
    ここが満たせなくなるほど行が伸びたら、文字サイズの前提も見直す必要がある。
    """
    lines = credit_lines(BASEMAP_ATTRIBUTION)
    single_line_length = sum(len(line) for line in lines)
    assert max(len(line) for line in lines) < single_line_length / 2


@pytest.mark.parametrize("attribution", ["", "   "])
def test_credit_lines_rejects_empty_attribution(attribution: str) -> None:
    """出典表記が空ならエラーになる（利用条件を満たせないため）。"""
    with pytest.raises(ValueError):
        credit_lines(attribution)


@pytest.mark.parametrize("provider_name", sorted(PROVIDERS))
def test_credit_lines_fit_within_strip_for_every_provider(provider_name: str) -> None:
    """どのタイル配信元でも、出典表記の各行が表記帯の幅に収まる。

    出典表記の文字列はプロバイダごとに長さが違う。長いものを追加したときに
    帯からはみ出すのを、文字数の上限で検出する。
    """
    lines = credit_lines(PROVIDERS[provider_name].attribution)
    assert max(len(line) for line in lines) <= CREDIT_MAX_LINE_CHARS
