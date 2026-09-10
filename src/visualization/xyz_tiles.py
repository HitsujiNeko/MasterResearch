"""XYZ タイル（スリッピーマップ）を取得してベースマップ画像を組み立てるモジュール。

図のベースマップに Web タイルを敷くために使う。タイル座標の計算（純関数）と
HTTP 取得（副作用あり）を分離してあり、前者は QGIS・ネットワークに依存しない。

座標系は Web メルカトル（EPSG:3857）を前提とする。XYZ タイルはこの座標系で
正方格子に切られているため、取得範囲・解像度の計算がすべて割り算で済む。

**取得したタイルはローカルにキャッシュする。** タイル配信元の利用規約は大量の
反復取得を禁じているため、同じ図を描き直すたびに取りに行かない設計とする。

出典表記の義務: 各プロバイダの ``attribution`` を図面上に必ず表示する。
"""

from __future__ import annotations

import io
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageOps

from src.common.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Web メルカトルの世界範囲の半分（m）。原点からの距離であり、
# x, y ともに [-ORIGIN_SHIFT, +ORIGIN_SHIFT] に収まる。
ORIGIN_SHIFT = 20037508.342789244

# タイル取得時の HTTP 設定。User-Agent は配信元が要求するため必ず入れる。
_USER_AGENT = "MasterResearch-figure/1.0 (academic use; contact via repository)"
_REQUEST_TIMEOUT_SEC = 20.0
_MAX_RETRY = 3
_RETRY_WAIT_SEC = 1.0

# 既定のタイルキャッシュ先。data/gis/ は Git 管理外のため成果物を汚さない。
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "gis" / "raw" / "xyz_tiles"


@dataclass(frozen=True)
class TileProvider:
    """XYZ タイル配信元の定義。

    Attributes:
        name: キャッシュディレクトリ名にも使う識別子。
        url_template: ``{z}`` ``{x}`` ``{y}`` を含む URL テンプレート。
        tile_size: 1 タイルの一辺のピクセル数。高解像度（@2x）配信では 512。
        max_zoom: 配信元が提供する最大ズームレベル。
        attribution: 図面へ表示する出典表記。省略してはならない。
    """

    name: str
    url_template: str
    tile_size: int
    max_zoom: int
    attribution: str


# 利用可能なタイル配信元。学術ポスター用途では出典表記を条件に利用できる。
#
# CARTO の basemaps.cartocdn.com は 2025 年以降 API キー無しの利用でタイル面に
# "API KEY REQUIRED" の透かしが焼き込まれるため、ここでは採用しない。淡色の
# ベースマップは OSM 標準タイルを :func:`apply_light_tone` で減彩して得る。
PROVIDERS: dict[str, TileProvider] = {
    "osm": TileProvider(
        name="osm",
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_size=256,
        max_zoom=19,
        attribution="Basemap: © OpenStreetMap contributors",
    ),
    "esri_light_gray": TileProvider(
        name="esri_light_gray",
        url_template=(
            "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/"
            "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        tile_size=256,
        max_zoom=16,
        attribution="Basemap: Esri, HERE, Garmin, © OpenStreetMap contributors",
    ),
}


def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    """経緯度（EPSG:4326）を Web メルカトル（EPSG:3857）へ変換する。

    Args:
        lon: 経度（度）。
        lat: 緯度（度）。±85.051129 度を超える値は極付近で発散するため丸める。

    Returns:
        ``(x, y)`` メートル。
    """
    lat = max(min(lat, 85.051129), -85.051129)
    x = math.radians(lon) * ORIGIN_SHIFT / math.pi
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) * ORIGIN_SHIFT / math.pi
    return x, y


def mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Web メルカトル（EPSG:3857）を経緯度（EPSG:4326）へ戻す。

    Args:
        x: メルカトル X（m）。
        y: メルカトル Y（m）。

    Returns:
        ``(lon, lat)`` 度。
    """
    lon = math.degrees(x * math.pi / ORIGIN_SHIFT)
    lat = math.degrees(2.0 * math.atan(math.exp(y * math.pi / ORIGIN_SHIFT)) - math.pi / 2.0)
    return lon, lat


def resolution_at_zoom(zoom: int, tile_size: int) -> float:
    """指定ズームでの 1 ピクセルあたりのメルカトル距離（m）を返す。

    赤道での値であり、実際の地表距離は緯度 φ において ``cos(φ)`` 倍になる。

    Args:
        zoom: ズームレベル。
        tile_size: 1 タイルの一辺のピクセル数。

    Returns:
        メルカトル m/px。
    """
    return 2.0 * ORIGIN_SHIFT / (tile_size * 2**zoom)


def select_zoom(
    extent: tuple[float, float, float, float],
    target_width_px: int,
    provider: TileProvider,
) -> int:
    """描画幅を満たす最小のズームレベルを選ぶ。

    出力画像より粗いタイルを引き伸ばすとぼやけるため、モザイクの横ピクセル数が
    ``target_width_px`` 以上になる最小のズームを採る。過剰なズームは取得タイル数を
    4 倍ずつ増やすだけなので選ばない。

    Args:
        extent: ``(x_min, y_min, x_max, y_max)`` メルカトル m。
        target_width_px: 出力画像上での地図の横ピクセル数。
        provider: タイル配信元。

    Returns:
        ズームレベル（0 以上 ``provider.max_zoom`` 以下）。

    Raises:
        ValueError: 範囲の幅が正でない、または目標ピクセル数が正でないとき。
    """
    x_min, _, x_max, _ = extent
    if x_max <= x_min:
        raise ValueError(f"範囲の幅が正ではありません: {extent}")
    if target_width_px <= 0:
        raise ValueError(f"目標ピクセル数が正ではありません: {target_width_px}")

    width_m = x_max - x_min
    for zoom in range(provider.max_zoom + 1):
        if width_m / resolution_at_zoom(zoom, provider.tile_size) >= target_width_px:
            return zoom
    return provider.max_zoom


def tile_range(
    extent: tuple[float, float, float, float], zoom: int, provider: TileProvider
) -> tuple[int, int, int, int]:
    """範囲を覆うタイル番号の閉区間を返す。

    Args:
        extent: ``(x_min, y_min, x_max, y_max)`` メルカトル m。
        zoom: ズームレベル。
        provider: タイル配信元。

    Returns:
        ``(x_first, y_first, x_last, y_last)``。いずれも閉区間（両端を含む）。
    """
    x_min, y_min, x_max, y_max = extent
    span = 2.0 * ORIGIN_SHIFT / 2**zoom  # タイル 1 枚のメルカトル幅
    limit = 2**zoom - 1

    def _clamp(value: int) -> int:
        return max(0, min(value, limit))

    x_first = _clamp(math.floor((x_min + ORIGIN_SHIFT) / span))
    x_last = _clamp(math.ceil((x_max + ORIGIN_SHIFT) / span) - 1)
    # タイル Y は北が 0 なので、メルカトル Y の大小と向きが逆になる。
    y_first = _clamp(math.floor((ORIGIN_SHIFT - y_max) / span))
    y_last = _clamp(math.ceil((ORIGIN_SHIFT - y_min) / span) - 1)
    return x_first, y_first, max(x_first, x_last), max(y_first, y_last)


def mosaic_extent(tiles: tuple[int, int, int, int], zoom: int) -> tuple[float, float, float, float]:
    """タイル番号の閉区間から、モザイク画像が覆うメルカトル範囲を返す。

    Args:
        tiles: ``tile_range`` の戻り値。
        zoom: ズームレベル。

    Returns:
        ``(x_min, y_min, x_max, y_max)`` メルカトル m。
    """
    x_first, y_first, x_last, y_last = tiles
    span = 2.0 * ORIGIN_SHIFT / 2**zoom
    x_min = x_first * span - ORIGIN_SHIFT
    x_max = (x_last + 1) * span - ORIGIN_SHIFT
    y_max = ORIGIN_SHIFT - y_first * span
    y_min = ORIGIN_SHIFT - (y_last + 1) * span
    return x_min, y_min, x_max, y_max


def count_tiles(tiles: tuple[int, int, int, int]) -> int:
    """タイル番号の閉区間に含まれるタイル枚数を返す。

    Args:
        tiles: ``tile_range`` の戻り値。

    Returns:
        枚数。
    """
    x_first, y_first, x_last, y_last = tiles
    return (x_last - x_first + 1) * (y_last - y_first + 1)


def _cache_path(cache_dir: Path, provider: TileProvider, zoom: int, x: int, y: int) -> Path:
    """タイル 1 枚のキャッシュ先パスを組み立てる。"""
    return cache_dir / provider.name / str(zoom) / str(x) / f"{y}.png"


def _decode_tile(content: bytes, provider: TileProvider) -> Image.Image:
    """応答本文（またはキャッシュの中身）をタイル画像として読み、妥当性を確かめる。

    HTTP のステータスが 200 でも、配信元がエラーページや利用制限の HTML を返す
    ことがある。**キャッシュへ書く前に必ずここを通す。** 画像でないものを書くと、
    次回以降は再試行ループの外側（`_load_tile` 冒頭のキャッシュ読み込み）へ入る
    ため、キャッシュを手で消すまで復旧しない。

    Args:
        content: 応答本文、またはキャッシュファイルの中身。
        provider: タイル配信元。``tile_size`` を期待する画素数として使う。

    Returns:
        RGB 変換済みのタイル画像。

    Raises:
        OSError: 画像として読めないとき（``PIL`` が送出する）。
        ValueError: 画素数が配信元の定義と一致しないとき。
    """
    with Image.open(io.BytesIO(content)) as image:
        # ``Image.open`` は遅延読み込みのため、ここで ``load()`` して途中で切れた
        # 画素データを検出する。開けただけでは壊れているかどうか分からない。
        image.load()
        expected = (provider.tile_size, provider.tile_size)
        if image.size != expected:
            raise ValueError(
                f"タイルの画素数が配信元の定義と一致しません: {image.size} != {expected}"
            )
        return image.convert("RGB")


def _load_tile(
    session: requests.Session,
    provider: TileProvider,
    zoom: int,
    x: int,
    y: int,
    cache_dir: Path,
) -> Image.Image:
    """タイル 1 枚をキャッシュまたはネットワークから読み込む。

    Args:
        session: 接続を使い回す ``requests`` セッション。
        provider: タイル配信元。
        zoom: ズームレベル。
        x: タイル X 番号。
        y: タイル Y 番号。
        cache_dir: キャッシュのルート。

    Returns:
        RGB 変換済みのタイル画像。

    Raises:
        RuntimeError: 規定回数の再試行後も取得できなかったとき。
    """
    path = _cache_path(cache_dir, provider, zoom, x, y)
    if path.exists():
        try:
            return _decode_tile(path.read_bytes(), provider)
        except Exception as error:  # noqa: BLE001 - 壊れ方を問わず取得し直す
            # 壊れたキャッシュが残っていても、取得し直して上書きすれば復旧できる。
            # ここで失敗させると、キャッシュを手で消すまで図を描けなくなる。
            logger.warning(
                "キャッシュのタイルを読めなかったため取得し直します: %s (%s)", path, error
            )

    url = provider.url_template.format(z=zoom, x=x, y=y)
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRY):
        try:
            response = session.get(url, timeout=_REQUEST_TIMEOUT_SEC)
            response.raise_for_status()
            tile = _decode_tile(response.content, provider)
        except Exception as error:  # noqa: BLE001 - 再試行のため種類を問わず捕捉する
            last_error = error
            if attempt < _MAX_RETRY - 1:
                time.sleep(_RETRY_WAIT_SEC * (attempt + 1))
            continue
        # タイル画像として読めたものだけをキャッシュへ書く（`_decode_tile` 参照）。
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return tile
    raise RuntimeError(f"タイルを取得できませんでした: {url}") from last_error


def fetch_mosaic(
    extent: tuple[float, float, float, float],
    zoom: int,
    provider: TileProvider,
    cache_dir: Path | None = None,
) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """範囲を覆うタイルを取得し、1 枚のモザイク画像に貼り合わせる。

    戻り値の範囲は入力範囲そのものではなく、タイル境界に合わせて外側へ広がった
    範囲である。``matplotlib`` の ``imshow`` へはこの範囲を渡し、表示範囲の切り取りは
    軸の ``set_xlim`` / ``set_ylim`` に任せる。

    Args:
        extent: ``(x_min, y_min, x_max, y_max)`` メルカトル m。
        zoom: ズームレベル。
        provider: タイル配信元。
        cache_dir: キャッシュのルート。``None`` なら :data:`DEFAULT_CACHE_DIR`。

    Returns:
        ``(モザイク画像, モザイクのメルカトル範囲)``。
    """
    cache_dir = DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    tiles = tile_range(extent, zoom, provider)
    x_first, y_first, x_last, y_last = tiles
    size = provider.tile_size
    mosaic = Image.new(
        "RGB",
        ((x_last - x_first + 1) * size, (y_last - y_first + 1) * size),
        color="white",
    )

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    try:
        for x in range(x_first, x_last + 1):
            for y in range(y_first, y_last + 1):
                tile = _load_tile(session, provider, zoom, x, y, cache_dir)
                mosaic.paste(tile, ((x - x_first) * size, (y - y_first) * size))
    finally:
        session.close()

    return mosaic, mosaic_extent(tiles, zoom)


def apply_light_tone(
    image: Image.Image, desaturation: float = 0.65, lightening: float = 0.28
) -> Image.Image:
    """タイル画像を淡色（ライトグレー）調へ変換する。

    彩度の高い標準スタイルのままだと、上に重ねる ROI 外郭や凡例より地図が目立って
    しまう。図の主役は ROI であるため、ベースマップは灰色寄り・明るめに落とす。

    Args:
        image: 変換前の RGB 画像。
        desaturation: グレースケールへ寄せる度合い（0 で原色、1 で完全なグレー）。
        lightening: 白へ寄せる度合い（0 で変化なし、1 で真っ白）。

    Returns:
        変換後の RGB 画像。

    Raises:
        ValueError: 度合いが 0-1 の範囲外のとき。
    """
    for name, value in (("desaturation", desaturation), ("lightening", lightening)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} は 0-1 の範囲で指定してください: {value}")

    source = image.convert("RGB")
    gray = ImageOps.grayscale(source).convert("RGB")
    toned = Image.blend(source, gray, desaturation)
    white = Image.new("RGB", source.size, color="white")
    return Image.blend(toned, white, lightening)
