"""xyz_tiles.py（タイル座標計算・淡色化）のテスト。

ネットワークを伴う ``fetch_mosaic`` は対象外とし、座標計算と画像加工の純関数を
検証する。``_load_tile`` は HTTP 取得（``fetch_bytes_with_retry``）を差し替えて
ネットワークなしに動かし、キャッシュの読み書きと画像の取り直しを検証する。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from src.common import http_fetch
from src.visualization import xyz_tiles
from src.visualization.xyz_tiles import (
    ORIGIN_SHIFT,
    PROVIDERS,
    TileProvider,
    _cache_path,
    _decode_tile,
    _load_tile,
    apply_light_tone,
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


def _png_bytes(size: tuple[int, int], color: str = "red") -> bytes:
    """指定した画素数の PNG バイト列を作る。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeFetch:
    """``fetch_bytes_with_retry`` の代役。

    ``contents`` を 1 回の呼び出しにつき 1 つずつ返す。数が足りない場合は
    最後の要素を返し続ける（取り直しの回数を数えられるようにするため）。
    要素が例外の場合は送出する。
    """

    def __init__(self, *contents: bytes | Exception) -> None:
        self._contents = list(contents)
        self.call_count = 0
        self.headers: list[dict[str, str] | None] = []
        self.sleeps: list[float] = []

    def __call__(self, url: str, **kwargs: object) -> bytes:
        self.call_count += 1
        self.headers.append(kwargs.get("headers"))  # type: ignore[arg-type]
        content = self._contents[min(self.call_count - 1, len(self._contents) - 1)]
        if isinstance(content, Exception):
            raise content
        return content


def _install_fetch(monkeypatch: pytest.MonkeyPatch, *contents: bytes | Exception) -> _FakeFetch:
    """``xyz_tiles`` が呼ぶ HTTP 取得を代役に差し替え、取り直しの待機を記録だけにする。"""
    fake = _FakeFetch(*contents)
    monkeypatch.setattr(xyz_tiles, "fetch_bytes_with_retry", fake)
    monkeypatch.setattr(xyz_tiles.time, "sleep", fake.sleeps.append)
    return fake


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_providers_use_https(name: str) -> None:
    """配信元の URL は https に限る。

    User-Agent を付けて取得するため、共通の取得関数の規則で http は拒否される。
    """
    assert PROVIDERS[name].url_template.startswith("https://")


def test_decode_tile_returns_rgb_image() -> None:
    """配信元の定義どおりの画像は RGB へ変換して返る。"""
    image = _decode_tile(_png_bytes((256, 256)), DUMMY_PROVIDER)

    assert image.size == (256, 256)
    assert image.mode == "RGB"


def test_decode_tile_rejects_non_image_content() -> None:
    """画像でない応答（エラーページ等）は読み込み時に失敗する。"""
    with pytest.raises(OSError):
        _decode_tile(b"<html><body>Rate limit exceeded</body></html>", DUMMY_PROVIDER)


def test_decode_tile_rejects_unexpected_size() -> None:
    """画素数が配信元の定義と違う画像は受け付けない。"""
    with pytest.raises(ValueError, match="画素数"):
        _decode_tile(_png_bytes((128, 128)), DUMMY_PROVIDER)


def test_load_tile_uses_common_retrying_fetch() -> None:
    """HTTP 取得は共通のリトライ付き取得を使う。"""
    assert xyz_tiles.fetch_bytes_with_retry is http_fetch.fetch_bytes_with_retry


def test_load_tile_caches_valid_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正しく取得できたタイルはキャッシュへ書かれ、次回は取りに行かない。"""
    fetch = _install_fetch(monkeypatch, _png_bytes((256, 256)))

    first = _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)
    second = _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)

    assert first.size == second.size == (256, 256)
    assert fetch.call_count == 1
    assert _cache_path(tmp_path, DUMMY_PROVIDER, 10, 3, 4).exists()
    # 配信元が要求する User-Agent を付けて取りに行く
    assert fetch.headers[0] is not None
    assert fetch.headers[0]["User-Agent"].startswith("MasterResearch-figure/")


def test_load_tile_does_not_cache_invalid_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """画像として読めない応答はキャッシュへ残さない。

    残すと次回以降はキャッシュ読み込みへ入り、再試行の対象にならないまま
    失敗し続ける（キャッシュを手で消すまで復旧しない）。
    """
    fetch = _install_fetch(monkeypatch, b"<html><body>Rate limit exceeded</body></html>")

    with pytest.raises(RuntimeError, match="タイルを取得できませんでした"):
        _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)

    assert fetch.call_count == xyz_tiles._MAX_DECODE_ATTEMPTS
    assert not _cache_path(tmp_path, DUMMY_PROVIDER, 10, 3, 4).exists()


@pytest.mark.parametrize("lon", [180.0000001, -180.0000001, 200.0, float("nan")])
def test_lonlat_to_mercator_rejects_out_of_range_longitude(lon: float) -> None:
    """経度が ±180 度の外なら、折り返した座標を返さずに ValueError にする。"""
    with pytest.raises(ValueError, match="経度"):
        lonlat_to_mercator(lon, 0.0)


@pytest.mark.parametrize("x", [ORIGIN_SHIFT * 1.05, -ORIGIN_SHIFT * 1.05, float("nan")])
def test_mercator_to_lonlat_rejects_out_of_world_x(x: float) -> None:
    """メルカトル X が世界範囲の外なら、折り返した経度を返さずに ValueError にする。"""
    with pytest.raises(ValueError, match="世界範囲"):
        mercator_to_lonlat(x, 0.0)


def test_mercator_to_lonlat_accepts_world_edge() -> None:
    """世界範囲の端（タイル境界から求めた ±ORIGIN_SHIFT）は受け付ける。"""
    edge = mosaic_extent((0, 0, 0, 0), 0)
    assert mercator_to_lonlat(edge[2], 0.0)[0] == pytest.approx(180.0)
    assert mercator_to_lonlat(edge[0], 0.0)[0] == pytest.approx(-180.0)


def test_load_tile_does_not_repeat_failed_http_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP の失敗は共通の取得側でリトライ済みのため、重ねて取り直さない。"""
    fetch = _install_fetch(monkeypatch, RuntimeError("リクエストが2回失敗しました"))

    with pytest.raises(RuntimeError, match=r"example\.invalid/10/3/4\.png.*2回失敗しました"):
        _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)

    assert fetch.call_count == 1
    assert not _cache_path(tmp_path, DUMMY_PROVIDER, 10, 3, 4).exists()


def test_load_tile_refetches_broken_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """壊れたキャッシュが残っていても、取得し直して上書きする。"""
    path = _cache_path(tmp_path, DUMMY_PROVIDER, 10, 3, 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"<html><body>Rate limit exceeded</body></html>")
    fetch = _install_fetch(monkeypatch, _png_bytes((256, 256)))

    image = _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)

    assert image.size == (256, 256)
    assert fetch.call_count == 1
    assert _decode_tile(path.read_bytes(), DUMMY_PROVIDER).size == (256, 256)


def test_load_tile_retries_until_valid_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 回目が壊れていても、再試行で取得できればその画像を返す。"""
    fetch = _install_fetch(monkeypatch, b"not an image", _png_bytes((256, 256)))

    image = _load_tile(DUMMY_PROVIDER, 10, 3, 4, tmp_path)

    assert image.size == (256, 256)
    assert fetch.call_count == 2
    # 取り直しの前に間を空ける（エラーページを返す配信元を続けて叩かない）
    assert fetch.sleeps == [xyz_tiles._RETRY_WAIT_SEC]
