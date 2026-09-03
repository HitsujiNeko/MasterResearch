"""xyz_tiles.py（タイル座標計算・淡色化）のテスト。

ネットワークを伴う ``fetch_mosaic`` / ``_load_tile`` は対象外とし、
座標計算と画像加工の純関数のみを検証する。
"""

from __future__ import annotations

import pytest
from PIL import Image

from src.visualization.xyz_tiles import (
    ORIGIN_SHIFT,
    PROVIDERS,
    TileProvider,
    apply_light_tone,
    count_tiles,
    lonlat_to_mercator,
    mercator_to_lonlat,
    mosaic_extent,
    resolution_at_zoom,
    select_zoom,
    tile_range,
)

# テスト用のタイル配信元。実在の URL へはアクセスしない。
DUMMY_PROVIDER = TileProvider(
    name="dummy",
    url_template="https://example.invalid/{z}/{x}/{y}.png",
    tile_size=256,
    max_zoom=12,
    attribution="test",
)

# ハノイ ROI 相当の範囲（EPSG:3857）。
HANOI_EXTENT = (11720000.0, 2337000.0, 11801000.0, 2436000.0)


def test_lonlat_to_mercator_origin_is_zero() -> None:
    """経緯度の原点はメルカトルの原点に写る。"""
    assert lonlat_to_mercator(0.0, 0.0) == pytest.approx((0.0, 0.0), abs=1e-9)


def test_lonlat_to_mercator_dateline_is_world_edge() -> None:
    """経度180度は世界範囲の東端に写る。"""
    x, _ = lonlat_to_mercator(180.0, 0.0)
    assert x == pytest.approx(ORIGIN_SHIFT)


def test_mercator_round_trip_returns_original() -> None:
    """メルカトルへ往復しても経緯度が保たれる。"""
    lon, lat = 105.65, 20.97
    assert mercator_to_lonlat(*lonlat_to_mercator(lon, lat)) == pytest.approx((lon, lat), abs=1e-9)


def test_lonlat_to_mercator_clamps_polar_latitude() -> None:
    """極付近の緯度は丸められ、発散しない。"""
    _, y_pole = lonlat_to_mercator(0.0, 89.9)
    _, y_limit = lonlat_to_mercator(0.0, 85.051129)
    assert y_pole == pytest.approx(y_limit)


def test_resolution_at_zoom_halves_per_level() -> None:
    """ズームが1段上がると解像度は半分になる。"""
    assert resolution_at_zoom(0, 256) == pytest.approx(156543.033928, rel=1e-9)
    assert resolution_at_zoom(1, 256) == pytest.approx(resolution_at_zoom(0, 256) / 2.0)


def test_resolution_at_zoom_reflects_tile_size() -> None:
    """タイルが2倍の画素数なら解像度は半分になる。"""
    assert resolution_at_zoom(10, 512) == pytest.approx(resolution_at_zoom(10, 256) / 2.0)


def test_select_zoom_satisfies_target_width() -> None:
    """選ばれたズームはモザイク幅が目標画素数以上になる最小値である。"""
    target = 1000
    zoom = select_zoom(HANOI_EXTENT, target, DUMMY_PROVIDER)
    width_m = HANOI_EXTENT[2] - HANOI_EXTENT[0]
    assert width_m / resolution_at_zoom(zoom, DUMMY_PROVIDER.tile_size) >= target
    assert width_m / resolution_at_zoom(zoom - 1, DUMMY_PROVIDER.tile_size) < target


def test_select_zoom_caps_at_provider_max() -> None:
    """要求が過大でも配信元の最大ズームを超えない。"""
    assert select_zoom(HANOI_EXTENT, 10_000_000, DUMMY_PROVIDER) == DUMMY_PROVIDER.max_zoom


@pytest.mark.parametrize(
    ("extent", "target"),
    [
        ((0.0, 0.0, 0.0, 1.0), 100),  # 幅が0
        ((1.0, 0.0, 0.0, 1.0), 100),  # 幅が負
        (HANOI_EXTENT, 0),  # 目標画素数が0
    ],
)
def test_select_zoom_rejects_invalid_input(
    extent: tuple[float, float, float, float], target: int
) -> None:
    """幅または目標画素数が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        select_zoom(extent, target, DUMMY_PROVIDER)


def test_tile_range_is_ordered_and_within_world() -> None:
    """タイル番号は昇順で、世界の範囲内に収まる。"""
    zoom = 11
    x_first, y_first, x_last, y_last = tile_range(HANOI_EXTENT, zoom, DUMMY_PROVIDER)
    assert x_first <= x_last
    assert y_first <= y_last
    assert 0 <= x_first and x_last <= 2**zoom - 1
    assert 0 <= y_first and y_last <= 2**zoom - 1


def test_mosaic_extent_contains_requested_extent() -> None:
    """モザイクの範囲は要求範囲を必ず含む。"""
    zoom = 11
    tiles = tile_range(HANOI_EXTENT, zoom, DUMMY_PROVIDER)
    x_min, y_min, x_max, y_max = mosaic_extent(tiles, zoom)
    assert x_min <= HANOI_EXTENT[0]
    assert y_min <= HANOI_EXTENT[1]
    assert x_max >= HANOI_EXTENT[2]
    assert y_max >= HANOI_EXTENT[3]


def test_mosaic_extent_of_whole_world_is_world() -> None:
    """ズーム0の1枚は世界全体を覆う。"""
    assert mosaic_extent((0, 0, 0, 0), 0) == pytest.approx(
        (-ORIGIN_SHIFT, -ORIGIN_SHIFT, ORIGIN_SHIFT, ORIGIN_SHIFT)
    )


def test_count_tiles_multiplies_both_sides() -> None:
    """枚数は縦横の枚数の積になる。"""
    assert count_tiles((3, 5, 6, 9)) == 4 * 5


def test_providers_declare_attribution() -> None:
    """全ての配信元が出典表記を持つ（表示義務があるため）。"""
    assert PROVIDERS
    for provider in PROVIDERS.values():
        assert provider.attribution.strip()


def test_apply_light_tone_keeps_size_and_mode() -> None:
    """淡色化しても画像サイズとモードは変わらない。"""
    source = Image.new("RGB", (8, 4), color=(200, 30, 30))
    result = apply_light_tone(source)
    assert result.size == source.size
    assert result.mode == "RGB"


def test_apply_light_tone_reduces_saturation() -> None:
    """彩度が下がり、RGB 各成分の差が縮まる。"""
    source = Image.new("RGB", (2, 2), color=(200, 30, 30))
    before = source.getpixel((0, 0))
    after = apply_light_tone(source).getpixel((0, 0))
    assert max(after) - min(after) < max(before) - min(before)


def test_apply_light_tone_full_lightening_is_white() -> None:
    """白へ寄せる度合いが1なら真っ白になる。"""
    source = Image.new("RGB", (2, 2), color=(10, 20, 30))
    assert apply_light_tone(source, desaturation=0.0, lightening=1.0).getpixel((0, 0)) == (
        255,
        255,
        255,
    )


def test_apply_light_tone_no_change_when_zero() -> None:
    """度合いが両方0なら元の色を保つ。"""
    source = Image.new("RGB", (2, 2), color=(10, 20, 30))
    assert apply_light_tone(source, desaturation=0.0, lightening=0.0).getpixel((0, 0)) == (
        10,
        20,
        30,
    )


@pytest.mark.parametrize(
    ("desaturation", "lightening"),
    [(-0.1, 0.3), (1.1, 0.3), (0.5, -0.1), (0.5, 1.1)],
)
def test_apply_light_tone_rejects_out_of_range(desaturation: float, lightening: float) -> None:
    """度合いが0-1の範囲外ならエラーになる。"""
    source = Image.new("RGB", (2, 2), color="white")
    with pytest.raises(ValueError):
        apply_light_tone(source, desaturation=desaturation, lightening=lightening)
