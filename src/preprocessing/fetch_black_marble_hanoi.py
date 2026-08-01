"""NASA Black Marble（VNP46A4）年次プロダクトから Hanoi ROI の夜間光を取得する。

データソース: NASA LAADS DAAC の ArchiveSet 5200（Black Marble Collection 2.0）
<https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/>

ライセンス: NASA オープンサイエンスポリシー（再配布・改変とも自由）。出典表記は
NASA VIIRS Land Science Team（Black Marble）に対して行う。

制約メモ（2026-07-27 確認）:
- **年次プロダクト VNP46A4 は Google Earth Engine に存在しない**。GEE で使えるのは
  日次の `NASA/VIIRS/002/VNP46A2` と `NOAA/VIIRS/001/VNP46A1` のみ。年次を使うには
  LAADS DAAC から直接取得する必要がある。
- **Earthdata の Bearer トークンが必須**。ファイル一覧 API の時点で Earthdata の
  OAuth へリダイレクト（HTTP 302）される。トークンは
  <https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token> で発行し、
  リポジトリ直下の `.env`（Git 管理外）に `EARTHDATA_TOKEN=...` として置く。
  環境変数で与えた場合はそちらが優先される。
- **データ利用許諾（ライセンス）への同意が別途必要**。未同意だと 401 ではなく
  `/profiles/licenses/...` へ 303 され、リダイレクトを辿った先の Earthdata OAuth で
  401 になる。原因が分かりにくいため `find_license_gate` で切り分けている。
  同意はブラウザで Earthdata にログインした状態で同ページを開いて行う。
- **ダウンロード URL は自前で組み立てない**。公開パス
  （`/archive/allData/...`）はライセンス同意ページへ 303 されるため、
  一覧が返す `downloadsLink`（`/api/v2/content/archives/allData/...`）を使う。
- 配布形式は HDF-EOS5（`.h5`）、10°×10° のタイル単位。h28v06 の 2023 年版は
  実測 約 120MB（製品ページの「92MB」より大きい）。
  **本環境の GDAL は HDF5 ドライバなしでビルドされている**ため、読み込みには h5py を使う。
- タイルは 10°グリッド（原点 -180E/90N、h は西→東、v は北→南）。Hanoi ROI
  （経度 105.29-106.02、緯度 20.56-21.39）は `h28v06` 1 タイルに収まる。
- 年次プロダクトの day-of-year は常に `001`。
- SDS 名・スケール係数・欠測値は**ファイルの属性から実測して適用する**（配布バージョンで
  変わりうるため、コード側で決め打ちしない）。想定した SDS が無い場合は、実在する
  SDS 名を添えて例外にする。
- ファイル内部の構造（2026-07-29 に h28v06 の 2023 年版で実測）:
  - SDS のグループは `HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields`
    （プロダクト名から連想される `VNP_Grid_DNB` ではない）
  - 合成バンドは 2400×2400 の **float32 で既に物理値**（`scale_factor = 1.0`、
    `offset = 0.0`、`_FillValue = -999.9`、単位 `nWatts/(cm^2 sr)`）
  - **オフセット属性の名前は `offset`**（CF 規約の `add_offset` ではない）
  - ルート属性に `WestBoundingCoord` 等の境界座標と `HorizontalTileNumber` /
    `VerticalTileNumber` があり、タイル番号の妥当性を突き合わせられる
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from rasterio.crs import CRS
from rasterio.transform import from_origin

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT, WGS84_CRS
from src.common.env_file import DEFAULT_ENV_FILE_PATH, resolve_secret
from src.common.http_fetch import fetch_bytes_with_retry
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.raster_area import (
    DEFAULT_RASTER_NODATA,
    build_target_area,
    clip_multiband_to_area,
    write_float_raster,
)
from src.common.raster_stats import build_multiband_pixel_statistics
from src.common.summary import save_summary

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "gis" / "nighttime_lights" / "black_marble"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"
# ダウンロードした .h5 タイルの保存先。1 タイル約 92MB のため再実行で再取得しない。
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "gis" / "raw" / "black_marble"
# トークンの変数名。環境変数またはリポジトリ直下の .env（Git 管理外）から読む。
EARTHDATA_TOKEN_ENV_VAR = "EARTHDATA_TOKEN"

LAADS_DETAILS_API_BASE = "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/details/allData"
# ライセンス未同意時のリダイレクト先に現れるパス断片
LICENSE_PATH_MARKER = "/profiles/licenses/"
LAADS_ARCHIVE_SET = "5200"
PRODUCT_NAME = "VNP46A4"
# 年次プロダクトの day-of-year は常に 001
ANNUAL_DAY_OF_YEAR = "001"

# LAADS の一覧取得は軽いが、タイル本体は 92MB 級のため別のタイムアウトを与える
LISTING_TIMEOUT_SECONDS = 120
DOWNLOAD_TIMEOUT_SECONDS = 1800

# Black Marble のタイルグリッド（10°×10°、原点は北西端の -180E / 90N）
TILE_SIZE_DEG = 10.0
GRID_ORIGIN_LON = -180.0
GRID_ORIGIN_LAT = 90.0
MAX_HORIZONTAL_INDEX = 35
MAX_VERTICAL_INDEX = 17

# HDF5 の先頭 8 バイト（署名）。取得結果・キャッシュが本当に HDF5 かの判定に使う。
# 未認証時の LAADS はログインページの HTML を HTTP 200 で返すため、内容を見ないと
# 「.h5 という名前の HTML」がキャッシュに焼き付き、トークンを直しても復旧しない。
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
# ファイル名として受け付けない文字。一覧の値をそのままキャッシュのパスに使うため、
# ディレクトリ区切り・ドライブ指定を含む名前は保存先の外へ書き出しうる。
# 実行 OS に依らず弾けるよう、`/` と `\` の両方を区切りとみなす。
UNSAFE_FILE_NAME_CHARACTERS = ("/", "\\", ":")

# HDF-EOS5 内で SDS が置かれるグループ（2026-07-29 に実ファイルで確認）
SDS_GROUP_PATH = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
# オフセット属性の名前。VNP46A4 は CF 規約の `add_offset` ではなく `offset` を使う。
# 版によって揺れうるため両方を見て、先に見つかったほうを採る。
OFFSET_ATTRIBUTE_NAMES = ("offset", "add_offset")
# ジオリファレンスの照合に使うルート属性
BOUNDING_COORD_ATTRIBUTES = {
    "west": "WestBoundingCoord",
    "east": "EastBoundingCoord",
    "north": "NorthBoundingCoord",
    "south": "SouthBoundingCoord",
}
# 属性由来と h/v 由来の境界座標の許容差（度）。15 arc-sec の 1/100 未満に相当する。
GEOREFERENCE_TOLERANCE_DEG = 1e-5

OUTPUT_NODATA = DEFAULT_RASTER_NODATA
LANDSAT_OBSERVATION_YEAR = 2023
FIRST_AVAILABLE_YEAR = 2012

RADIANCE_UNIT = "nW·cm⁻²·sr⁻¹"
# データ被覆率を代表させるバンド。Black Marble の標準的な代表値。
PRIMARY_BAND_NAME = "ntl_near_nadir"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TileFile:
    """LAADS の一覧が返すファイル情報。

    Attributes:
        name: ファイル名。
        download_url: 実際に配信される URL（一覧の `downloadsLink`）。
        size_bytes: ファイルサイズ。一覧に無ければ None。
    """

    name: str
    download_url: str
    size_bytes: int | None = None


@dataclass(frozen=True)
class TileIndex:
    """Black Marble のタイル番号（h: 西→東、v: 北→南）。"""

    horizontal: int
    vertical: int

    @property
    def name(self) -> str:
        """`h28v06` 形式のタイル名を返す。"""
        return f"h{self.horizontal:02d}v{self.vertical:02d}"


@dataclass(frozen=True)
class BandDefinition:
    """出力 GeoTIFF の 1 バンド分の定義。"""

    sds_name: str
    output_name: str
    unit: str
    description: str
    # 飽和評価の対象とするか（放射輝度バンドのみ True）
    is_radiance: bool


# 出力バンドの並び（1始まりのバンド番号に対応）
BAND_DEFINITIONS: tuple[BandDefinition, ...] = (
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free",
        output_name="ntl_near_nadir",
        unit=RADIANCE_UNIT,
        description=(
            "近直下視（視野角 0-20°）の年次夜間光。月光・大気・BRDF 補正済みで、"
            "Black Marble の標準的な代表値"
        ),
        is_radiance=True,
    ),
    BandDefinition(
        sds_name="AllAngle_Composite_Snow_Free",
        output_name="ntl_all_angle",
        unit=RADIANCE_UNIT,
        description="全視野角を用いた年次夜間光。観測数が多いぶん安定するが視野角の影響を含む",
        is_radiance=True,
    ),
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free_Num",
        output_name="near_nadir_num",
        unit="観測回数",
        description="近直下視の合成に用いた観測数。少ない画素は値の信頼度が低い",
        is_radiance=False,
    ),
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free_Std",
        output_name="near_nadir_std",
        unit=RADIANCE_UNIT,
        description="近直下視の合成に用いた観測値の標準偏差。年内のばらつきの指標",
        is_radiance=False,
    ),
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="NASA Black Marble（VNP46A4）から Hanoi ROI の夜間光を取得する。"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=LANDSAT_OBSERVATION_YEAR,
        help="取得対象年。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help=(
            "試行実行用の小範囲 BBOX（EPSG:4326）。配布はタイル単位のため"
            "ダウンロード量は減らず、クリップ範囲だけが狭くなる点に注意する。"
        ),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            "出力 GeoTIFF パス。未指定時は data/gis/nighttime_lights/black_marble/ 配下へ保存する。"
        ),
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="サマリー JSON パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="ダウンロードした .h5 タイルの保存先。既に在れば再ダウンロードしない。",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help=(
            f"Earthdata トークンだけを記載したファイル。未指定時は環境変数 "
            f"{EARTHDATA_TOKEN_ENV_VAR} を見て、無ければリポジトリ直下の .env を読む。"
        ),
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help=(
            "取得済みタイルの HDF5 構造（SDS 名・形状・属性）を出力して終了する。"
            "配布バージョンの変更で SDS 名や属性が変わっていないかの確認に使う。"
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def resolve_earthdata_token(token_file: Path | None = None) -> str:
    """Earthdata の Bearer トークンを解決する。

    優先順位は「明示指定されたファイル → 環境変数 → リポジトリ直下の `.env`」。
    明示指定を最優先にするのは、コマンドラインでの指定が利用者の意図として最も強いため。
    **トークンの値はログにも例外メッセージにも出さない**。

    Args:
        token_file: トークンだけを記載したファイル。未指定なら環境変数・`.env` を見る。

    Returns:
        トークン文字列。

    Raises:
        FileNotFoundError: 明示指定されたトークンファイルが存在しない場合。
        ValueError: どこからもトークンを取得できない、または内容が空の場合。
    """
    if token_file is not None:
        if not token_file.exists():
            raise FileNotFoundError(f"トークンファイルが見つかりません: {token_file}")
        # `.env` 側と同じく BOM 付き UTF-8 を許容する（Windows のエディタ対策）
        token = token_file.read_text(encoding="utf-8-sig").strip()
        if not token:
            raise ValueError(f"トークンファイルが空です: {token_file}")
        return token

    token = resolve_secret(
        EARTHDATA_TOKEN_ENV_VAR, dict(os.environ), env_file_path=DEFAULT_ENV_FILE_PATH
    )
    if token:
        return token

    raise ValueError(
        "Earthdata のトークンが見つかりません。"
        "<https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token> で発行し、"
        f"リポジトリ直下の .env に {EARTHDATA_TOKEN_ENV_VAR}=... を書くか、"
        f"環境変数 {EARTHDATA_TOKEN_ENV_VAR} を設定してください"
        "（--token-file でファイルを直接指定することもできます）。"
    )


def build_authorization_headers(token: str) -> dict[str, str]:
    """LAADS DAAC 用の認証ヘッダーを組み立てる。

    Args:
        token: Earthdata の Bearer トークン。

    Returns:
        Authorization ヘッダーを含む辞書。
    """
    return {"Authorization": f"Bearer {token}"}


def resolve_black_marble_tiles(
    bounds: tuple[float, float, float, float],
) -> list[TileIndex]:
    """BBOX を覆う Black Marble タイルの一覧を求める。

    タイルは 10°×10° で、原点は北西端の (-180E, 90N)。境界を「半開区間」として扱い、
    BBOX の東端・南端がちょうどタイル境界に載る場合に、重なりの無い隣のタイルを
    拾わないようにする（`ceil - 1` を使う理由）。

    Args:
        bounds: (min_lon, min_lat, max_lon, max_lat)。EPSG:4326。

    Returns:
        北西から南東の順に並べたタイル一覧。

    Raises:
        ValueError: BBOX の最小値が最大値を超えている場合、または経緯度の値域を
            外れている場合。
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    # 逆転と値域外を同じメッセージで返すと、値域は正しいのに値域の調査に向かってしまう
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError(
            "BBOX の最小値が最大値を超えています"
            f"（経度: {min_lon} > {max_lon} または 緯度: {min_lat} > {max_lat}）: {bounds}"
        )
    if not (-180.0 <= min_lon and max_lon <= 180.0 and -90.0 <= min_lat and max_lat <= 90.0):
        raise ValueError(f"BBOX が経緯度の値域を外れています: {bounds}")

    first_horizontal = math.floor((min_lon - GRID_ORIGIN_LON) / TILE_SIZE_DEG)
    last_horizontal = math.ceil((max_lon - GRID_ORIGIN_LON) / TILE_SIZE_DEG) - 1
    first_vertical = math.floor((GRID_ORIGIN_LAT - max_lat) / TILE_SIZE_DEG)
    last_vertical = math.ceil((GRID_ORIGIN_LAT - min_lat) / TILE_SIZE_DEG) - 1

    # 開始索引を先に値域へ収める。経度 180・緯度 -90 ちょうどの縮退 BBOX では
    # 索引が索引上限を 1 超えるため、ここで丸めておかないと開始 > 終了となり
    # 空リストになる（呼び出し側の tiles[0] が IndexError になる）。
    first_horizontal = min(max(first_horizontal, 0), MAX_HORIZONTAL_INDEX)
    first_vertical = min(max(first_vertical, 0), MAX_VERTICAL_INDEX)
    # 幅・高さが 0 の BBOX では ceil-1 が floor を下回るため、最低 1 タイルは残す
    last_horizontal = min(max(last_horizontal, first_horizontal), MAX_HORIZONTAL_INDEX)
    last_vertical = min(max(last_vertical, first_vertical), MAX_VERTICAL_INDEX)

    return [
        TileIndex(horizontal=horizontal, vertical=vertical)
        for vertical in range(first_vertical, last_vertical + 1)
        for horizontal in range(first_horizontal, last_horizontal + 1)
    ]


def compute_tile_bounds(tile: TileIndex) -> tuple[float, float, float, float]:
    """タイル番号から、そのタイルが覆う範囲を求める。

    Args:
        tile: タイル番号。

    Returns:
        (west, south, east, north)。EPSG:4326。
    """
    west = GRID_ORIGIN_LON + TILE_SIZE_DEG * tile.horizontal
    north = GRID_ORIGIN_LAT - TILE_SIZE_DEG * tile.vertical
    return (west, north - TILE_SIZE_DEG, west + TILE_SIZE_DEG, north)


def build_listing_url(year: int) -> str:
    """対象年のファイル一覧を取得する URL を組み立てる。

    Args:
        year: 取得対象年。

    Returns:
        LAADS DAAC の details API の URL。
    """
    return (
        f"{LAADS_DETAILS_API_BASE}/{LAADS_ARCHIVE_SET}/{PRODUCT_NAME}/{year}/"
        f"{ANNUAL_DAY_OF_YEAR}?fields=all&formats=json"
    )


def fetch_tile_listing(year: int, headers: dict[str, str]) -> dict[str, Any]:
    """対象年のファイル一覧を取得する。

    未認証・トークン期限切れのとき、LAADS は 401 ではなく **Earthdata のログイン
    ページへ 302 リダイレクトして HTML を返す**。そのまま JSON として解釈すると
    `Expecting value: line 1 column 1` という原因の分からない例外になるため、
    JSON でなかった場合は認証を疑う旨を添えて投げ直す。

    Args:
        year: 取得対象年。
        headers: 認証ヘッダー。

    Returns:
        一覧 API のレスポンス（JSON をパースした辞書）。

    Raises:
        RuntimeError: レスポンスが JSON として解釈できない場合。
    """
    response_body = fetch_bytes_with_retry(
        build_listing_url(year), timeout=LISTING_TIMEOUT_SECONDS, headers=headers
    )
    try:
        return json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        preview = response_body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            "LAADS の一覧が JSON で返りませんでした。"
            "Earthdata のトークンが無効・期限切れの可能性があります"
            "（未認証だとログインページへリダイレクトされ HTML が返ります）。"
            f"応答の先頭: {preview!r}"
        ) from exc


def is_safe_tile_file_name(name: str) -> bool:
    """一覧が返したファイル名を、そのままキャッシュのパスに使ってよいか判定する。

    一覧の `name` は**唯一そのままファイルシステムのパスになる外部由来の値**で、
    ディレクトリ区切りや親ディレクトリ参照を含んでいると、キャッシュ先の外へ
    100MB 超を書き出しうる。`run_inspection` の glob からも外れるため、
    取得済みのはずのファイルが見つからない状態にもなる。

    Args:
        name: 一覧が返したファイル名。

    Returns:
        安全に使えるファイル名なら True。
    """
    if name in ("", ".", ".."):
        return False
    return not any(character in name for character in UNSAFE_FILE_NAME_CHARACTERS)


def extract_listing_entries(listing: dict[str, Any]) -> list[TileFile]:
    """LAADS の一覧レスポンスからファイル情報を取り出す。

    ダウンロード URL は**自前で組み立てず、一覧が返す `downloadsLink` を使う**。
    アーカイブの公開パス（`/archive/allData/...`）はライセンス同意ページへ 303 され、
    Bearer トークンでは辿れない。実際に配信されるのは API 側の
    `/api/v2/content/archives/allData/...` で、これは一覧が教えてくれる。

    Args:
        listing: 一覧 API のレスポンス（JSON をパースした辞書）。

    Returns:
        ファイル情報のリスト。

    Raises:
        RuntimeError: 想定した構造でない場合。
    """
    entries = listing.get("content")
    if not isinstance(entries, list):
        raise RuntimeError(
            "LAADS の一覧レスポンスに content 配列がありません"
            f"（トップレベルのキー: {sorted(listing)}）。"
        )

    tile_files: list[TileFile] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("fileName")
        download_url = entry.get("downloadsLink")
        if not (isinstance(name, str) and name):
            continue
        if not is_safe_tile_file_name(name):
            # 名前はそのままキャッシュのパスになるため、保存先の外を指しうる値は使わない
            logger.warning(
                "一覧のファイル名がパスとして安全ではありません。対象から外します: %r", name
            )
            continue
        if not (isinstance(download_url, str) and download_url):
            # URL が無いと取得できない。件数だけ合っていても意味がないため落とさず記録する
            logger.warning("一覧の %s に downloadsLink がありません。対象から外します。", name)
            continue
        size_bytes = entry.get("size")
        tile_files.append(
            TileFile(
                name=name,
                download_url=download_url,
                size_bytes=int(size_bytes) if isinstance(size_bytes, int) else None,
            )
        )

    if not tile_files:
        raise RuntimeError(
            f"LAADS の一覧からファイル情報を取り出せませんでした（件数: {len(entries)}）。"
        )
    return tile_files


def select_tile_files(tile_files: list[TileFile], tiles: list[TileIndex]) -> dict[str, TileFile]:
    """ファイル一覧から、必要なタイルのファイルだけを選ぶ。

    VNP46A4 のファイル名は `VNP46A4.A{年}001.h28v06.002.{生成日時}.h5` 形式で、
    生成日時は事前に分からない。そのためタイル名を含むかどうかで選ぶ。

    Args:
        tile_files: 一覧から得た全ファイル情報。
        tiles: 必要なタイル。

    Returns:
        タイル名 -> ファイル情報。

    Raises:
        RuntimeError: 必要なタイルが一覧に無い場合、または同一タイルが複数ある場合。
    """
    selected: dict[str, TileFile] = {}
    for tile in tiles:
        matched = [tile_file for tile_file in tile_files if f".{tile.name}." in tile_file.name]
        if not matched:
            raise RuntimeError(
                f"タイル {tile.name} のファイルが一覧にありません"
                f"（一覧の件数: {len(tile_files)}）。"
            )
        if len(matched) > 1:
            # 同一タイルの再処理版が併存すると、どちらを使ったか分からなくなる
            raise RuntimeError(
                f"タイル {tile.name} のファイルが複数あります: "
                f"{sorted(tile_file.name for tile_file in matched)}。"
                "使用する版を特定できないため停止します。"
            )
        selected[tile.name] = matched[0]
    return selected


def find_license_gate(download_url: str, headers: dict[str, str]) -> str | None:
    """ダウンロードがライセンス未同意で止められていないかを調べる。

    LAADS はデータ利用許諾が未同意の製品に対し、401 ではなく
    `/profiles/licenses/...` への 303 を返す。リダイレクトを辿ると最終的に
    Earthdata の OAuth で 401 になるため、素のエラーからは原因が分からない。
    失敗時にだけ呼び、原因を切り分けるために使う。

    Args:
        download_url: 調べる URL。
        headers: 認証ヘッダー。

    Returns:
        ライセンス同意ページの URL。ライセンスが原因でなければ None。
    """

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """リダイレクトを追わず、Location をそのまま観察するためのハンドラ。"""

        def redirect_request(
            self,
            req: urllib.request.Request,
            fp: Any,
            code: int,
            msg: str,
            response_headers: Any,
            newurl: str,
        ) -> None:
            """None を返してリダイレクトの追跡を止める。

            Args:
                req: 元のリクエスト。
                fp: レスポンスのファイルオブジェクト。
                code: HTTP ステータスコード。
                msg: ステータスメッセージ。
                response_headers: レスポンスヘッダー。
                newurl: リダイレクト先 URL。

            Returns:
                常に None（urllib はこれを受けて追跡を打ち切る）。
            """
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(download_url, headers=headers)
    try:
        with opener.open(request, timeout=LISTING_TIMEOUT_SECONDS):
            return None
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") or ""
        if LICENSE_PATH_MARKER in location:
            return urllib.parse.urljoin(download_url, location)
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        # 切り分けのための補助的な確認なので、ここでの失敗は握って呼び出し元の
        # 元エラーを優先させる
        return None


def looks_like_hdf5(head: bytes) -> bool:
    """先頭バイト列が HDF5 の署名で始まるかを判定する。

    Args:
        head: ファイル・レスポンスの先頭バイト列（8 バイト以上）。

    Returns:
        HDF5 として読める見込みがあれば True。
    """
    return head.startswith(HDF5_SIGNATURE)


def download_tile(
    tile_file: TileFile,
    destination_path: Path,
    headers: dict[str, str],
) -> Path:
    """タイルファイルをダウンロードして保存する（既存ならそのまま使う）。

    1 タイル 100MB 超のため、既に取得済みなら再取得しない。書き込みは一時ファイルへ
    行ってから差し替える（中断で壊れたファイルがキャッシュに残るのを防ぐ）。

    **保存前に中身が HDF5 であることとサイズを検証する**。未認証・トークン失効時の
    LAADS は 401 ではなくログインページの HTML を HTTP 200 で返すため、内容を見ずに
    保存すると「`.h5` という名前の HTML」がキャッシュに焼き付く。以降は取得済み
    扱いで即 return するため、トークンを再発行しても HDF5 の署名エラーで失敗し
    続け、手動でキャッシュを消すまで復旧しない。同じ理由で、既にキャッシュされて
    いるファイルも署名を確認し、壊れていれば破棄して取り直す。

    失敗した場合はライセンス未同意かどうかを切り分け、該当すれば同意ページの URL を
    添えて投げ直す（リダイレクト先の 401 のままでは原因が分からないため）。

    Args:
        tile_file: 一覧から得たファイル情報。
        destination_path: 保存先パス。
        headers: 認証ヘッダー。

    Returns:
        保存したパス。

    Raises:
        RuntimeError: ダウンロードに失敗した場合、または取得した内容が HDF5 で
            ない・サイズが一覧の値と一致しない場合。
    """
    if destination_path.exists():
        with destination_path.open("rb") as cached_file:
            cached_head = cached_file.read(len(HDF5_SIGNATURE))
        if looks_like_hdf5(cached_head):
            logger.info(
                "取得済みのタイルを使います（%.1f MB）: %s",
                destination_path.stat().st_size / 1_000_000,
                destination_path.name,
            )
            return destination_path
        # 残したままだと取得済み扱いで永久に復旧しないため、捨てて取り直す
        logger.warning(
            "キャッシュが HDF5 ではありません（認証切れ時の HTML の可能性）。"
            "破棄して取り直します: %s",
            destination_path.name,
        )
        destination_path.unlink()

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    size_text = (
        "サイズ不明"
        if tile_file.size_bytes is None
        else f"約 {tile_file.size_bytes / 1_000_000:.0f} MB"
    )
    logger.info("タイルをダウンロードします（%s）: %s", size_text, destination_path.name)
    try:
        response_body = fetch_bytes_with_retry(
            tile_file.download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS, headers=headers
        )
    except RuntimeError as exc:
        license_url = find_license_gate(tile_file.download_url, headers)
        if license_url is None:
            raise
        raise RuntimeError(
            f"{PRODUCT_NAME} のデータ利用許諾が未同意のためダウンロードできません。"
            "ブラウザで Earthdata にログインした状態で次の URL を開き、"
            f"許諾に同意してから再実行してください: {license_url}"
        ) from exc

    if not looks_like_hdf5(response_body):
        preview = response_body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            "ダウンロードした内容が HDF5 ではありません。Earthdata のトークンが無効・"
            "期限切れか、データ利用許諾が未同意の可能性があります"
            "（未認証だとログインページの HTML が HTTP 200 で返ります）。"
            "壊れた内容をキャッシュへ焼き付けないよう、保存はしていません。"
            f"応答の先頭: {preview!r}"
        )
    if tile_file.size_bytes is not None and len(response_body) != tile_file.size_bytes:
        raise RuntimeError(
            "ダウンロードしたサイズが一覧の値と一致しません"
            f"（一覧: {tile_file.size_bytes} バイト、取得: {len(response_body)} バイト）。"
            "転送が途中で切れた可能性があるため、保存はしていません。"
        )

    temporary_path = destination_path.with_suffix(destination_path.suffix + ".part")
    temporary_path.write_bytes(response_body)
    temporary_path.replace(destination_path)
    logger.info("ダウンロード完了（%.1f MB）", len(response_body) / 1_000_000)
    return destination_path


def describe_hdf5_structure(tile_path: Path) -> dict[str, Any]:
    """HDF5 タイルの構造（SDS 名・形状・属性）を読み取る。

    SDS 名や属性が配布バージョンで変わっていないかを確認するために使う。

    Args:
        tile_path: タイルファイルのパス。

    Returns:
        ルート属性と SDS ごとの情報を含む辞書。

    Raises:
        KeyError: 想定した SDS グループが無い場合。
    """
    with h5py.File(tile_path, "r") as h5_file:
        root_attributes = {key: _to_python(value) for key, value in h5_file.attrs.items()}
        if SDS_GROUP_PATH not in h5_file:
            raise KeyError(
                f"SDS グループ {SDS_GROUP_PATH!r} が見つかりません"
                f"（ルートのキー: {sorted(h5_file.keys())}）。"
            )
        group = h5_file[SDS_GROUP_PATH]
        datasets = {
            name: {
                "shape": list(dataset.shape),
                "dtype": str(dataset.dtype),
                "attributes": {key: _to_python(value) for key, value in dataset.attrs.items()},
            }
            for name, dataset in group.items()
        }
    return {"root_attributes": root_attributes, "datasets": datasets}


def _to_python(value: Any) -> Any:
    """HDF5 の属性値を JSON へ書ける Python の値に変換する。

    Args:
        value: HDF5 属性の生の値。

    Returns:
        文字列・数値・リストのいずれか。
    """
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.size == 1:
            return _to_python(value.item())
        return [_to_python(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def read_scaled_sds(
    h5_file: h5py.File,
    sds_name: str,
    nodata: float = OUTPUT_NODATA,
) -> tuple[np.ndarray, dict[str, Any]]:
    """SDS を読み、属性に従ってスケールを戻した float32 配列を返す。

    `scale_factor` / オフセット / `_FillValue` は**属性から実測して適用する**。
    換算式は `物理値 = 生値 * scale_factor + offset`（NASA 系には
    `(生値 - offset) * scale_factor` の製品もあるため明記する）。

    実ファイルで確認した値（2026-07-29、h28v06 2023年版）:

    - 合成バンド（`*_Composite_Snow_Free` / `_Std`）は既に **float32 の物理値**で、
      `scale_factor = 1.0` / `offset = 0.0` / `_FillValue = -999.9`
    - `_Num` は uint16（`_FillValue = 65535`）、`_Quality` は uint8（同 255）
    - **オフセット属性の名前は CF 規約の `add_offset` ではなく `offset`**

    属性が無い場合はスケールなし（1.0 / 0.0）・欠測なしとして続行するが、
    **その事実を戻り値の `defaulted_attributes` に残す**。属性名が版によって
    変わったことに気づかないまま換算すると、値がずれたまま最後まで通ってしまう
    （実際に `add_offset` の想定は外れていた）。呼び出し側はこれをサマリー最上位へ
    引き上げ、成果物だけを見ても検知できる状態にする。

    Args:
        h5_file: 開いた HDF5 ファイル。
        sds_name: 読み出す SDS 名。
        nodata: 出力の無効値。

    Returns:
        (スケール適用済みの 2 次元配列, 適用した属性の記録)。記録の
        `defaulted_attributes` には、属性が無く既定値で代用した項目名が入る。

    Raises:
        KeyError: SDS が存在しない場合。
    """
    group = h5_file[SDS_GROUP_PATH]
    if sds_name not in group:
        raise KeyError(
            f"SDS {sds_name!r} が見つかりません（実在する SDS: {sorted(group.keys())}）。"
        )

    dataset = group[sds_name]
    raw_values = dataset[:]
    attributes = {key: _to_python(value) for key, value in dataset.attrs.items()}

    defaulted_attributes: list[str] = []

    scale_factor = float(attributes.get("scale_factor", 1.0))
    if "scale_factor" not in attributes:
        defaulted_attributes.append("scale_factor")
        logger.warning(
            "SDS %s に scale_factor 属性がありません。スケールなし（1.0）として扱いますが、"
            "配布側の属性名が変わっている場合は値が実際と異なります。",
            sds_name,
        )

    offset_name = next((key for key in OFFSET_ATTRIBUTE_NAMES if key in attributes), None)
    add_offset = 0.0 if offset_name is None else float(attributes[offset_name])
    if offset_name is None:
        defaulted_attributes.append("offset")
        logger.warning(
            "SDS %s にオフセット属性（%s のいずれか）がありません。0 として扱います。",
            sds_name,
            " / ".join(OFFSET_ATTRIBUTE_NAMES),
        )

    fill_value = attributes.get("_FillValue")
    # 欠測判定はスケール適用前の生の値で行う（浮動小数点化で一致しなくなるのを避ける）
    fill_mask = (
        np.zeros(raw_values.shape, dtype=bool)
        if fill_value is None
        else raw_values == np.array(fill_value, dtype=raw_values.dtype)
    )
    if fill_value is None:
        defaulted_attributes.append("_FillValue")
        logger.warning("SDS %s に _FillValue 属性がありません。欠測なしとして扱います。", sds_name)

    # CF 規約の換算式。add_offset は加算side（減算する製品もあるため docstring 参照）
    scaled_values = raw_values.astype(np.float64) * scale_factor + add_offset
    scaled_values = scaled_values.astype(np.float32)
    scaled_values[fill_mask] = nodata

    applied = {
        "scale_factor": scale_factor,
        "offset": add_offset,
        "offset_attribute": offset_name,
        "fill_value": fill_value,
        "fill_pixels": int(np.count_nonzero(fill_mask)),
        "units": attributes.get("units"),
        "long_name": attributes.get("long_name"),
        "defaulted_attributes": defaulted_attributes,
    }
    return scaled_values, applied


def verify_tile_georeference(
    root_attributes: dict[str, Any],
    tile: TileIndex,
    tolerance: float = GEOREFERENCE_TOLERANCE_DEG,
) -> dict[str, Any]:
    """ファイル属性の境界座標が、タイル番号から求めた範囲と一致するか検証する。

    タイル番号だけで transform を組み立てると、ファイル名のタイル番号を読み違えても
    気づけない。属性側の境界座標と突き合わせて、両者が一致することを確認する。

    Args:
        root_attributes: HDF5 のルート属性。
        tile: タイル番号。
        tolerance: 許容する座標のずれ（度）。

    Returns:
        照合に用いた属性値と、タイル番号由来の境界の記録。

    Raises:
        KeyError: 境界座標の属性が揃っていない場合。
        ValueError: 属性とタイル番号由来の境界が許容差を超えて食い違う場合。
    """
    missing = [
        attribute_name
        for attribute_name in BOUNDING_COORD_ATTRIBUTES.values()
        if attribute_name not in root_attributes
    ]
    if missing:
        raise KeyError(
            f"境界座標の属性が見つかりません: {missing}"
            f"（実在する属性: {sorted(root_attributes)}）。"
        )

    west, south, east, north = compute_tile_bounds(tile)
    expected = {"west": west, "east": east, "north": north, "south": south}
    actual = {
        key: float(root_attributes[attribute_name])
        for key, attribute_name in BOUNDING_COORD_ATTRIBUTES.items()
    }

    mismatched = {
        key: (actual[key], expected[key])
        for key in expected
        if abs(actual[key] - expected[key]) > tolerance
    }
    if mismatched:
        raise ValueError(
            f"タイル {tile.name} の境界座標がファイル属性と一致しません"
            f"（実測 vs タイル番号由来: {mismatched}）。"
        )

    return {"tile": tile.name, "attribute_bounds": actual, "tile_index_bounds": expected}


def write_tile_geotiff(
    tile_path: Path,
    tile: TileIndex,
    destination_path: Path,
) -> tuple[Path, dict[str, Any]]:
    """HDF5 タイルを、定義した全バンドを持つ GeoTIFF へ変換する。

    HDF-EOS5 側に GDAL が読めるジオリファレンスが無いため、タイル番号と配列の形状から
    アフィン変換を組み立てる。組み立てた範囲はファイル属性と突き合わせて検証する。

    Args:
        tile_path: HDF5 タイルのパス。
        tile: タイル番号。
        destination_path: 出力 GeoTIFF パス。

    Returns:
        (出力パス, 読み取り時のメタデータ記録)。

    Raises:
        ValueError: バンド間で配列の形状が揃っていない場合。
    """
    with h5py.File(tile_path, "r") as h5_file:
        root_attributes = {key: _to_python(value) for key, value in h5_file.attrs.items()}
        georeference = verify_tile_georeference(root_attributes, tile)
        band_arrays: dict[str, np.ndarray] = {}
        band_attributes: dict[str, Any] = {}
        for band in BAND_DEFINITIONS:
            values, applied = read_scaled_sds(h5_file, band.sds_name)
            band_arrays[band.output_name] = values
            band_attributes[band.output_name] = applied

    shapes = {name: array.shape for name, array in band_arrays.items()}
    if len(set(shapes.values())) != 1:
        raise ValueError(f"バンド間で配列の形状が揃っていません: {shapes}")

    height, width = next(iter(shapes.values()))
    west, _, _, north = compute_tile_bounds(tile)
    transform = from_origin(west, north, TILE_SIZE_DEG / width, TILE_SIZE_DEG / height)

    write_float_raster(
        output_path=destination_path,
        band_arrays=band_arrays,
        transform=transform,
        crs=CRS.from_string(WGS84_CRS),
        nodata=OUTPUT_NODATA,
    )

    metadata = {
        "tile_shape": [height, width],
        "pixel_size_deg": TILE_SIZE_DEG / width,
        "georeference_check": georeference,
        "band_attributes": band_attributes,
    }
    return destination_path, metadata


def collect_attribute_warnings(tile_metadata: dict[str, Any]) -> list[str]:
    """属性が欠けて既定値で代用したバンドを、人が読める形で列挙する。

    `band_attributes` の奥に埋もれた `defaulted_attributes` を最上位へ引き上げる
    ための整形。属性名が配布バージョンで変わると、換算がずれたまま成果物が出来上がって
    しまうため、サマリーを一目見て気づける位置に無いと意味がない。

    Args:
        tile_metadata: `write_tile_geotiff` が返したメタデータ。

    Returns:
        警告文のリスト。欠落が無ければ空リスト。
    """
    warnings: list[str] = []
    for band_name, applied in sorted(tile_metadata.get("band_attributes", {}).items()):
        for attribute_name in applied.get("defaulted_attributes", []):
            warnings.append(
                f"{band_name}: SDS 属性 {attribute_name} が無く既定値で代用した"
                "（配布側の属性名が変わっていないか確認すること）"
            )
    return warnings


def resolve_output_paths(
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
    is_trial: bool = False,
) -> tuple[Path, Path]:
    """出力 GeoTIFF とサマリー JSON の保存先を解決する。

    Args:
        year: 取得対象年。
        output_path: 指定された出力パス。
        summary_path: 指定されたサマリーパス。
        is_trial: 試行実行かどうか。

    Returns:
        (出力 GeoTIFF パス, サマリー JSON パス)。
    """
    trial_suffix = "_trial" if is_trial else ""
    output_stem = f"black_marble_vnp46a4_hanoi_{year}{trial_suffix}"
    resolved_output_path = output_path or (DEFAULT_OUTPUT_ROOT / f"{output_stem}.tif")
    resolved_summary_path = summary_path or (
        DEFAULT_SUMMARY_DIR / f"nighttime_lights_{output_stem}_summary.json"
    )
    return (
        prepare_output_path(resolved_output_path),
        prepare_output_path(resolved_summary_path),
    )


def validate_year(year: int) -> None:
    """取得対象年が提供期間内かを検証する。

    Args:
        year: 取得対象年。

    Raises:
        ValueError: 提供開始年より前、または未来の年を指定した場合。
    """
    current_year = datetime.now(timezone.utc).year
    if year < FIRST_AVAILABLE_YEAR:
        raise ValueError(
            f"{PRODUCT_NAME} の提供は {FIRST_AVAILABLE_YEAR} 年からです（指定: {year}）。"
        )
    if year > current_year:
        raise ValueError(f"未来の年は取得できません（指定: {year}、現在: {current_year}）。")


def build_summary(
    year: int,
    roi_path: Path,
    is_trial: bool,
    area_bounds: tuple[float, float, float, float],
    tiles: list[TileIndex],
    tile_files: dict[str, TileFile],
    tile_metadata: dict[str, Any],
    raster_profile: dict[str, Any],
    pixel_stats: dict[str, Any],
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    Args:
        year: 取得対象年。
        roi_path: ROI ファイルパス。
        is_trial: 試行実行（BBOX 指定）かどうか。
        area_bounds: 取得対象範囲の BBOX。
        tiles: 使用したタイル。
        tile_files: タイル名 -> 実ファイル情報。
        tile_metadata: タイル読み取り時のメタデータ。
        raster_profile: 出力ラスタの諸元。
        pixel_stats: 画素統計。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        retrieved_at: 取得日時（ISO8601）。

    Returns:
        サマリー辞書。
    """
    year_note = f"{PRODUCT_NAME} の提供は {FIRST_AVAILABLE_YEAR} 年から。"
    if year == LANDSAT_OBSERVATION_YEAR:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）と一致しており、"
            "時間差はない。"
        )
    else:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）との間に "
            f"{abs(LANDSAT_OBSERVATION_YEAR - year)} 年の時間差がある。"
        )

    return {
        "dataset": f"NASA Black Marble {PRODUCT_NAME}（年次・月光/BRDF補正済み）",
        "dataset_key": "black_marble_vnp46a4",
        "archive_set": LAADS_ARCHIVE_SET,
        "source": (
            "https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/"
        ),
        "license": "NASA オープンサイエンスポリシー",
        "license_note": (
            "出典表記は NASA VIIRS Land Science Team（Black Marble）に対して行う。"
            "取得には Earthdata アカウントの Bearer トークンが必要。"
        ),
        "retrieved_at": retrieved_at,
        "year": year,
        "year_note": year_note,
        "access_note": (
            f"{PRODUCT_NAME}（年次）は Google Earth Engine に存在せず、LAADS DAAC から"
            "直接取得している。GEE で使えるのは日次の VNP46A2 / VNP46A1 のみ。"
        ),
        "tiles": [tile.name for tile in tiles],
        "tile_files": {
            tile_name: {
                "name": tile_file.name,
                "download_url": tile_file.download_url,
                "size_bytes": tile_file.size_bytes,
            }
            for tile_name, tile_file in tile_files.items()
        },
        "tile_metadata": tile_metadata,
        "grid_note": (
            "配布は 10°×10° タイル（原点 -180E/90N、15 arc-sec）。ジオリファレンスは"
            "タイル番号から組み立て、ファイルの境界座標属性と一致することを検証している。"
            "VIIRS DNB 年次コンポジットとはグリッド原点が半画素ずれるため、画素単位の"
            "突き合わせには再投影が要る。"
        ),
        "roi_path": to_project_relative_string(roi_path),
        "is_trial_run": is_trial,
        "area_bbox": list(area_bounds),
        # サマリーJSONの標準項目として最上位に置く。実体は raster_profile 側が正
        "crs": raster_profile["crs"],
        "raster_profile": raster_profile,
        "bands": {
            str(index): {
                "name": band.output_name,
                "source_sds": band.sds_name,
                "unit": band.unit,
                "description": band.description,
            }
            for index, band in enumerate(BAND_DEFINITIONS, start=1)
        },
        "pixel_stats": pixel_stats,
        # 属性欠落は band_attributes の奥に埋もれると気づけないため最上位へ引き上げる。
        # 属性名が版で変わると、換算がずれたまま成果物が出来上がってしまう
        "attribute_warnings": collect_attribute_warnings(tile_metadata),
        "scaling_note": (
            "スケール係数・オフセット・欠測値は SDS 属性から実測して適用している"
            "（tile_metadata.band_attributes に記録）。コード側では決め打ちしていない。"
            "属性が欠けていた場合は attribute_warnings に列挙する。空リストであれば、"
            "全バンドの換算がファイルの属性どおりに行われたことを意味する。"
        ),
        "saturation_note": (
            "飽和指標は放射輝度バンドについてのみ算出している。p99_to_max_ratio が 1 に"
            "近く、かつ ratio_near_max が無視できない大きさであれば、上位の値が"
            "最大値へ張り付いている（飽和が疑われる）。"
        ),
        "coverage_note": (
            "ROI ポリゴンで真にクリップしているため出力は BBOX 矩形となり、ROI 外の余白は "
            f"nodata（{OUTPUT_NODATA}）で埋まる。valid_pixel_ratio の分母 roi_pixels は"
            "**クリップ後の出力に含まれる ROI 内画素**であり、ROI 全体ではない。"
            "有効画素はバンドごとに別々に数えており、最上位の valid_pixels / "
            f"valid_pixel_ratio はデータ被覆の指標として主バンド {PRIMARY_BAND_NAME} で"
            "代表させている。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
    }


def run(
    year: int,
    roi_path: Path,
    bbox: list[float] | None,
    output_path: Path | None,
    summary_path: Path | None,
    cache_dir: Path,
    token_file: Path | None,
    overwrite: bool,
) -> tuple[Path, Path]:
    """取得から検証・保存までの処理全体を実行する。

    Args:
        year: 取得対象年。
        roi_path: ROI の Shapefile パス。
        bbox: 試行実行用 BBOX。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        cache_dir: .h5 タイルの保存先。
        token_file: Earthdata トークンのファイル。
        overwrite: 既存出力を上書きするか。

    Returns:
        (出力 GeoTIFF パス, サマリー JSON パス)。

    Raises:
        ValueError: 取得対象年が提供期間外の場合、または Earthdata のトークンを
            解決できない場合。
        FileNotFoundError: 明示指定されたトークンファイルが存在しない場合。
        FileExistsError: 出力ファイルが既に存在し overwrite が False の場合。
        NotImplementedError: 複数タイルの結合が必要な場合（現状は未対応）。
        RuntimeError: 一覧の取得・解釈、またはタイルのダウンロードに失敗した場合。
    """
    validate_year(year)
    area_gdf, is_trial, resolved_roi_path = build_target_area(roi_path=roi_path, bbox=bbox)
    area_bounds = tuple(float(value) for value in area_gdf.total_bounds)
    logger.info("取得対象範囲の BBOX: %s", area_bounds)

    resolved_output_path, resolved_summary_path = resolve_output_paths(
        year=year,
        output_path=output_path,
        summary_path=summary_path,
        is_trial=is_trial,
    )
    for existing_path in (resolved_output_path, resolved_summary_path):
        if existing_path.exists() and not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します: {existing_path}。"
                "上書きする場合は --overwrite を指定してください。"
            )

    tiles = resolve_black_marble_tiles(area_bounds)
    logger.info("必要なタイル: %s", [tile.name for tile in tiles])
    if len(tiles) > 1:
        # 結合を無言で省くと ROI の一部だけの成果物が出来るため、明示的に止める
        raise NotImplementedError(
            f"複数タイルの結合には未対応です（必要なタイル: {[tile.name for tile in tiles]}）。"
            "ROI が 1 タイルに収まらない場合はタイル結合の実装が要ります。"
        )
    tile = tiles[0]

    token = resolve_earthdata_token(token_file)
    headers = build_authorization_headers(token)

    listing = fetch_tile_listing(year, headers)
    tile_files = select_tile_files(extract_listing_entries(listing), tiles)
    tile_file = tile_files[tile.name]
    logger.info("対象ファイル: %s", tile_file.name)

    tile_path = download_tile(
        tile_file=tile_file,
        destination_path=cache_dir / tile_file.name,
        headers=headers,
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="black_marble_convert_") as temporary_dir:
        tile_geotiff_path = Path(temporary_dir) / f"{tile.name}_{year}.tif"
        _, tile_metadata = write_tile_geotiff(tile_path, tile, tile_geotiff_path)
        clip_result = clip_multiband_to_area(
            source_path=tile_geotiff_path,
            area_gdf=area_gdf,
            output_path=resolved_output_path,
            band_names=[band.output_name for band in BAND_DEFINITIONS],
            nodata=OUTPUT_NODATA,
        )

    pixel_stats = build_multiband_pixel_statistics(
        band_arrays=clip_result.band_arrays,
        area_mask=clip_result.area_mask,
        covers_area=clip_result.covers_area,
        primary_band=PRIMARY_BAND_NAME,
        nodata=OUTPUT_NODATA,
        saturation_bands=[band.output_name for band in BAND_DEFINITIONS if band.is_radiance],
    )

    if clip_result.raster_profile["crs"] != WGS84_CRS:
        logger.warning(
            "出力 CRS が %s ではありません: %s", WGS84_CRS, clip_result.raster_profile["crs"]
        )

    summary = build_summary(
        year=year,
        roi_path=resolved_roi_path,
        is_trial=is_trial,
        area_bounds=area_bounds,
        tiles=tiles,
        tile_files=tile_files,
        tile_metadata=tile_metadata,
        raster_profile=clip_result.raster_profile,
        pixel_stats=pixel_stats,
        output_path=resolved_output_path,
        summary_path=resolved_summary_path,
        retrieved_at=retrieved_at,
    )
    save_summary(summary, resolved_summary_path)

    log_results(pixel_stats)
    return resolved_output_path, resolved_summary_path


def log_results(pixel_stats: dict[str, Any]) -> None:
    """取得結果の要点をログへ出力する。

    Args:
        pixel_stats: 画素統計。
    """
    logger.info(
        "有効画素率: %.4f（有効 %d / 範囲内 %d、ラスタ全体 %d）",
        pixel_stats["valid_pixel_ratio"],
        pixel_stats["valid_pixels"],
        pixel_stats["roi_pixels"],
        pixel_stats["total_pixels"],
    )
    for band in BAND_DEFINITIONS:
        band_stats = pixel_stats[band.output_name]
        if "min" not in band_stats:
            logger.warning("バンド %s に有効画素がありません。", band.output_name)
            continue
        logger.info(
            "%s（%s）: 有効 %d 画素（%.4f） min=%.3f median=%.3f p95=%.3f p99=%.3f max=%.3f",
            band.output_name,
            band.unit,
            band_stats["valid_pixels"],
            band_stats["valid_pixel_ratio"],
            band_stats["min"],
            band_stats["median"],
            band_stats["p95"],
            band_stats["p99"],
            band_stats["max"],
        )

    for band_name, indicators in pixel_stats["saturation"].items():
        if indicators is None:
            continue
        ratio_text = (
            "算出不可"
            if indicators["p99_to_max_ratio"] is None
            else f"{indicators['p99_to_max_ratio']:.3f}"
        )
        # 近傍幅は可変なので、文言に固定値を埋め込まず実際の設定値から組み立てる
        neighborhood_percent = indicators["neighborhood_ratio"] * 100
        logger.info(
            "飽和指標 %s: p99/max=%s、最大値と同値 %d 画素、最大値の%.3g%%以内 %d 画素（%.4f）",
            band_name,
            ratio_text,
            indicators["pixels_at_max"],
            neighborhood_percent,
            indicators["pixels_near_max"],
            indicators["ratio_near_max"],
        )

    if pixel_stats["valid_pixel_ratio"] < 1.0:
        logger.warning(
            "範囲内に無効画素があります（有効率 %.4f）。データ提供範囲の限界を確認してください。",
            pixel_stats["valid_pixel_ratio"],
        )
    if not pixel_stats["covers_requested_area"]:
        logger.warning(
            "出力が要求範囲を覆いきれていません。有効率は覆えた範囲内でしか評価されていない"
            "ため、タイルの選択が正しいか確認してください。"
        )


def run_inspection(year: int, cache_dir: Path, roi_path: Path, bbox: list[float] | None) -> None:
    """取得済みタイルの HDF5 構造を出力する。

    Args:
        year: 対象年。
        cache_dir: .h5 タイルの保存先。
        roi_path: ROI の Shapefile パス。
        bbox: 試行実行用 BBOX。

    Raises:
        FileNotFoundError: 対象タイルがキャッシュに無い場合。
    """
    area_gdf, _, _ = build_target_area(roi_path=roi_path, bbox=bbox)
    tiles = resolve_black_marble_tiles(tuple(float(value) for value in area_gdf.total_bounds))
    if len(tiles) > 1:
        # 取得側は複数タイルを例外で止めるため、検査側だけ黙って絞ると挙動が食い違う
        logger.warning(
            "対象タイルが %d 枚あります（%s）。検査は先頭の %s のみ行います。",
            len(tiles),
            [tile.name for tile in tiles],
            tiles[0].name,
        )
    pattern = f"{PRODUCT_NAME}.A{year}{ANNUAL_DAY_OF_YEAR}.{tiles[0].name}.*.h5"
    matched = sorted(cache_dir.glob(pattern))
    if not matched:
        raise FileNotFoundError(
            f"検査対象のタイルがキャッシュにありません（探索: {cache_dir / pattern}）。"
            "先に --inspect なしで実行してタイルを取得してください。"
        )
    if len(matched) > 1:
        logger.warning(
            "同じタイルのファイルが %d 件あります。先頭 %s を検査します（全件: %s）。",
            len(matched),
            matched[0].name,
            [path.name for path in matched],
        )

    structure = describe_hdf5_structure(matched[0])
    print(json.dumps(structure, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    if args.inspect:
        run_inspection(
            year=args.year, cache_dir=args.cache_dir, roi_path=args.roi_path, bbox=args.bbox
        )
        return

    output_path, summary_path = run(
        year=args.year,
        roi_path=args.roi_path,
        bbox=args.bbox,
        output_path=args.output_path,
        summary_path=args.summary_path,
        cache_dir=args.cache_dir,
        token_file=args.token_file,
        overwrite=args.overwrite,
    )
    print(f"GeoTIFF を保存しました: {output_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
