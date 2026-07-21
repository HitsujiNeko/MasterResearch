"""
GLC_FCS30D（30m 全球土地被覆動態プロダクト）から Hanoi ROI の年次土地被覆を取得する。

データソース: Zenodo record 15063683（DOI: 10.5281/zenodo.15063683、v2）
ライセンス: CC BY 4.0。ただし User Guides に「科学論文で利用する場合は事前に
提供者へ連絡し、謝辞または共著を検討することを推奨する」との Data Use Policy が
記載されているため、論文利用時は研究者自身が対応要否を判断すること。

制約メモ（2026-07-21 確認）:
- 配布は経度10度帯ごとの ZIP（36分割）。Hanoi を含む ZIP は約 6.39GB あるが、
  Zenodo は HTTP Range（206 応答・accept-ranges: bytes）に対応するため、
  ZIP の中央ディレクトリのみを読み、必要なメンバーだけを取り出せる。
- GDAL の `/vsizip//vsicurl/` は使えない。Zenodo の配信 URL が `/content` で終わり
  拡張子を持たないため、GDAL が ZIP として認識できず開けない。
- ZIP 内のタイルは 5 度 x 5 度で、タイル名は「左上隅」の座標を表す
  （実測: E105N20 の bounds は経度 105-110・緯度 15-20）。
- 年次版メンバーは 23 バンドで、バンド 1 から順に 2000, 2001, ... 2022 年に対応する。
  2023 年以降のマップは存在しない。
- Zenodo からの実効ダウンロード速度は約 0.3MB/s と遅く、年次メンバー（約 197MB）の
  取得には 10 分前後かかる。取り出したメンバーはキャッシュして再取得を避ける。
- クラス値は 35 種類（10-220）で、0 と 250 は Filled value（無効値）。
"""

from __future__ import annotations

import argparse
import io
import logging
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT, WGS84_CRS
from src.common.http_fetch import fetch_json_with_retry
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "gis" / "lulc" / "glc_fcs30d"
DEFAULT_CACHE_DIR = DEFAULT_OUTPUT_DIR / "_cache"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

# Zenodo のレコード ID（v2）。初版は 8239305 だが、こちらが最新版。
DEFAULT_ZENODO_RECORD_ID = "15063683"
ZENODO_API_URL_TEMPLATE = "https://zenodo.org/api/records/{record_id}"

DATASET_NAME = "GLC_FCS30D"
DATASET_VERSION = "v2"
DATASET_DOI = "10.5281/zenodo.15063683"

# 年次版メンバーのバンド構成（バンド1 = 2000年）
ANNUAL_FIRST_YEAR = 2000
ANNUAL_LAST_YEAR = 2022
DEFAULT_YEAR = ANNUAL_LAST_YEAR

# タイルの1辺（度）と、ZIP の経度帯の幅（度）
TILE_SIZE_DEG = 5
ZIP_LONGITUDE_SPAN_DEG = 10

# Filled value（無効値）。User Guides 記載。
FILLED_VALUES: tuple[int, ...] = (0, 250)
# 出力 GeoTIFF の nodata。Filled value と同じ 0 を使う。
OUTPUT_NODATA = 0

# GLC_FCS30D の分類体系（35クラス）。User Guides の LC id と対応する。
CLASS_LABELS: dict[int, str] = {
    10: "Rainfed cropland",
    11: "Herbaceous cover cropland",
    12: "Tree or shrub cover (Orchard) cropland",
    20: "Irrigated cropland",
    51: "Open evergreen broadleaved forest",
    52: "Closed evergreen broadleaved forest",
    61: "Open deciduous broadleaved forest",
    62: "Closed deciduous broadleaved forest",
    71: "Open evergreen needle-leaved forest",
    72: "Closed evergreen needle-leaved forest",
    81: "Open deciduous needle-leaved forest",
    82: "Closed deciduous needle-leaved forest",
    91: "Open mixed leaf forest",
    92: "Closed mixed leaf forest",
    120: "Shrubland",
    121: "Evergreen shrubland",
    122: "Deciduous shrubland",
    130: "Grassland",
    140: "Lichens and mosses",
    150: "Sparse vegetation",
    152: "Sparse shrubland",
    153: "Sparse herbaceous",
    181: "Swamp",
    182: "Marsh",
    183: "Flooded flat",
    184: "Saline",
    185: "Mangrove",
    186: "Salt marsh",
    187: "Tidal flat",
    190: "Impervious surfaces",
    200: "Bare areas",
    201: "Consolidated bare areas",
    202: "Unconsolidated bare areas",
    210: "Water body",
    220: "Permanent ice and snow",
}

REQUEST_TIMEOUT_SECONDS = 300
DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="GLC_FCS30D から Hanoi ROI の年次土地被覆を取得する。"
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_YEAR,
        help=f"取得対象年（{ANNUAL_FIRST_YEAR}-{ANNUAL_LAST_YEAR}）。デフォルト {DEFAULT_YEAR}。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="出力 GeoTIFF パス。未指定時は data/gis/lulc/glc_fcs30d/ 配下へ保存する。",
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
        help="ZIP から取り出したタイルのキャッシュ先ディレクトリ。",
    )
    parser.add_argument(
        "--record-id",
        default=DEFAULT_ZENODO_RECORD_ID,
        help="Zenodo のレコード ID。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


class HttpRangeReader(io.RawIOBase):
    """HTTP Range リクエストでランダムアクセスするファイル風オブジェクト。

    `zipfile.ZipFile` に渡すことで、巨大な ZIP をすべてダウンロードせずに
    中央ディレクトリと必要なメンバーだけを読み取れる。
    """

    def __init__(self, url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> None:
        """リモートファイルのサイズを取得して初期化する。

        Args:
            url (str): 対象ファイルの URL。
            timeout (int): タイムアウト秒数。

        Raises:
            ValueError: url が http/https 以外のスキームの場合。
            RuntimeError: サーバーが Range リクエストに対応していない場合。
        """
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"許可されていない URL スキームです: {url}")

        self.url = url
        self.timeout = timeout
        self._position = 0
        self.request_count = 0

        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
        if content_length is None:
            raise RuntimeError(f"Content-Length を取得できませんでした: {url}")
        self.size = int(content_length)

    def seekable(self) -> bool:
        """シーク可能であることを示す。"""
        return True

    def readable(self) -> bool:
        """読み取り可能であることを示す。"""
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """読み取り位置を移動する。

        Args:
            offset (int): 移動量。
            whence (int): 基準位置（io.SEEK_SET/CUR/END）。

        Returns:
            int: 移動後の位置。
        """
        if whence == io.SEEK_SET:
            new_position = offset
        elif whence == io.SEEK_CUR:
            new_position = self._position + offset
        elif whence == io.SEEK_END:
            new_position = self.size + offset
        else:
            raise ValueError(f"未対応の whence です: {whence}")

        self._position = max(0, min(new_position, self.size))
        return self._position

    def tell(self) -> int:
        """現在の読み取り位置を返す。"""
        return self._position

    def read(self, size: int = -1) -> bytes:
        """現在位置から指定バイト数を Range リクエストで読み取る。

        Args:
            size (int): 読み取るバイト数。負値または None の場合は末尾まで。

        Returns:
            bytes: 読み取ったバイト列。

        Raises:
            RuntimeError: サーバーが部分応答（206）を返さない場合。
        """
        if size is None or size < 0:
            size = self.size - self._position
        if size == 0 or self._position >= self.size:
            return b""

        end_position = min(self._position + size, self.size) - 1
        request = urllib.request.Request(
            self.url,
            headers={"Range": f"bytes={self._position}-{end_position}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status != 206:
                raise RuntimeError(
                    f"サーバーが Range リクエストに対応していません（status={response.status}）: "
                    f"{self.url}"
                )
            data = response.read()

        self.request_count += 1
        self._position += len(data)
        return data

    def readall(self) -> bytes:
        """現在位置から末尾まで読み取る。"""
        return self.read(-1)


def band_index_for_year(year: int) -> int:
    """取得対象年から年次版メンバーのバンド番号（1 始まり）を求める。

    Args:
        year (int): 対象年。

    Returns:
        int: バンド番号（2000 年が 1、2022 年が 23）。

    Raises:
        ValueError: データセットが提供しない年を指定した場合。
    """
    if not ANNUAL_FIRST_YEAR <= year <= ANNUAL_LAST_YEAR:
        raise ValueError(
            f"GLC_FCS30D の年次マップは {ANNUAL_FIRST_YEAR}-{ANNUAL_LAST_YEAR} 年のみです: {year}"
        )
    return year - ANNUAL_FIRST_YEAR + 1


def tile_names_for_bounds(bounds: tuple[float, float, float, float]) -> list[str]:
    """BBOX を覆う 5 度タイルの名称一覧を返す。

    タイル名は左上隅の座標を表す（例: E105N25 は経度 105-110・緯度 20-25）。
    BBOX の上端・右端がちょうどタイル境界に一致する場合、その先のタイルは含めない。

    Args:
        bounds (tuple[float, float, float, float]):
            (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。

    Returns:
        list[str]: タイル名のリスト（西→東、北→南の順）。

    Raises:
        ValueError: BBOX の最小値が最大値を上回る場合。
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError(f"BBOX の最小値が最大値を上回っています: {bounds}")

    # 西端タイルの左辺経度と、東端タイルの左辺経度。
    # BBOX の東端がタイル境界ちょうどの場合、その東隣のタイルは含めない
    # （ceil - TILE_SIZE_DEG がその判定を兼ねる）。
    first_left_lon = _floor_to_tile(min_lon)
    last_left_lon = max(_ceil_to_tile(max_lon) - TILE_SIZE_DEG, first_left_lon)

    # 北端タイルの上辺緯度と、南端タイルの上辺緯度。
    # BBOX の南端がタイル境界ちょうどの場合、その南隣のタイルは含めない。
    first_top_lat = _ceil_to_tile(max_lat)
    last_top_lat = min(_floor_to_tile(min_lat) + TILE_SIZE_DEG, first_top_lat)

    tile_names: list[str] = []
    top_lat = first_top_lat
    while top_lat >= last_top_lat:
        left_lon = first_left_lon
        while left_lon <= last_left_lon:
            tile_names.append(_format_tile_name(left_lon, top_lat))
            left_lon += TILE_SIZE_DEG
        top_lat -= TILE_SIZE_DEG

    return tile_names


def _floor_to_tile(value: float) -> int:
    """値を TILE_SIZE_DEG の倍数へ切り下げる（負値は南／西方向へ）。

    Args:
        value (float): 経度または緯度。

    Returns:
        int: 切り下げた値。
    """
    return int(np.floor(value / TILE_SIZE_DEG)) * TILE_SIZE_DEG


def _ceil_to_tile(value: float) -> int:
    """値を TILE_SIZE_DEG の倍数へ切り上げる（北／東方向へ）。

    Args:
        value (float): 経度または緯度。

    Returns:
        int: 切り上げた値。
    """
    return int(np.ceil(value / TILE_SIZE_DEG)) * TILE_SIZE_DEG


def _format_tile_name(left_lon: int, top_lat: int) -> str:
    """タイルの左上隅座標からタイル名を組み立てる。

    Args:
        left_lon (int): タイル左辺の経度。
        top_lat (int): タイル上辺の緯度。

    Returns:
        str: タイル名（例: "E105N25"、"W10S5"）。
    """
    lon_prefix = "E" if left_lon >= 0 else "W"
    lat_prefix = "N" if top_lat >= 0 else "S"
    return f"{lon_prefix}{abs(left_lon)}{lat_prefix}{abs(top_lat)}"


def zip_name_for_tile(tile_name: str) -> str:
    """タイル名から、そのタイルを収録する ZIP ファイル名を求める。

    ZIP は経度 10 度ごとに分割され、ファイル名にはその帯に含まれる 2 枚のタイルの
    左辺経度が絶対値の昇順で並ぶ。東経と西経で並びが異なる点に注意する
    （実データで確認済み）:

    - 東経: 経度 0-10 度の帯には左辺 0 と 5 のタイルが入るため "E0-E5"
    - 西経: 経度 -10-0 度の帯には左辺 -5 と -10 のタイルが入るため "W5-W10"

    Args:
        tile_name (str): タイル名（例: "E105N25"）。

    Returns:
        str: ZIP ファイル名。

    Raises:
        ValueError: タイル名の書式が不正な場合。
    """
    left_lon = _parse_tile_longitude(tile_name)
    absolute_lon = abs(left_lon)

    if left_lon >= 0:
        hemisphere = "E"
        band_start = (absolute_lon // ZIP_LONGITUDE_SPAN_DEG) * ZIP_LONGITUDE_SPAN_DEG
    else:
        hemisphere = "W"
        # 西経のタイル左辺は絶対値 5, 10, 15, ... となり、帯は絶対値 5 起点で区切られる
        band_start = (
            (absolute_lon - TILE_SIZE_DEG) // ZIP_LONGITUDE_SPAN_DEG
        ) * ZIP_LONGITUDE_SPAN_DEG + TILE_SIZE_DEG

    band_end = band_start + TILE_SIZE_DEG
    return f"{DATASET_NAME}_19852022maps_{hemisphere}{band_start}-{hemisphere}{band_end}.zip"


def _parse_tile_longitude(tile_name: str) -> int:
    """タイル名から左辺の経度を取り出す。

    Args:
        tile_name (str): タイル名（例: "E105N25"）。

    Returns:
        int: 左辺の経度（西経は負値）。

    Raises:
        ValueError: タイル名の書式が不正な場合。
    """
    if not tile_name or tile_name[0] not in ("E", "W"):
        raise ValueError(f"タイル名の書式が不正です: {tile_name}")

    latitude_position = -1
    for index, character in enumerate(tile_name[1:], start=1):
        if character in ("N", "S"):
            latitude_position = index
            break
    if latitude_position < 0:
        raise ValueError(f"タイル名の書式が不正です: {tile_name}")

    longitude_text = tile_name[1:latitude_position]
    if not longitude_text.isdigit():
        raise ValueError(f"タイル名の書式が不正です: {tile_name}")

    longitude = int(longitude_text)
    return longitude if tile_name[0] == "E" else -longitude


def member_name_for_tile(zip_name: str, tile_name: str) -> str:
    """ZIP 内の年次版メンバーのパスを組み立てる。

    Args:
        zip_name (str): ZIP ファイル名。
        tile_name (str): タイル名（例: "E105N25"）。

    Returns:
        str: ZIP 内のメンバーパス。
    """
    directory_name = Path(zip_name).stem
    return f"{directory_name}/{DATASET_NAME}_20002022_{tile_name}_Annual_V1.1.tif"


def resolve_zip_download_url(record_id: str, zip_name: str) -> str:
    """Zenodo のレコードから対象 ZIP のダウンロード URL を解決する。

    Args:
        record_id (str): Zenodo のレコード ID。
        zip_name (str): 対象 ZIP のファイル名。

    Returns:
        str: ダウンロード URL。

    Raises:
        RuntimeError: レコードに対象 ZIP が見つからない場合。
    """
    api_url = ZENODO_API_URL_TEMPLATE.format(record_id=record_id)
    record = fetch_json_with_retry(api_url, timeout=REQUEST_TIMEOUT_SECONDS)

    for file_entry in record.get("files", []):
        if file_entry.get("key") == zip_name:
            return file_entry["links"]["self"]

    available_names = sorted(str(entry.get("key")) for entry in record.get("files", []))
    raise RuntimeError(
        f"Zenodo レコード {record_id} に {zip_name} が見つかりません。"
        f"収録ファイル: {available_names}"
    )


def extract_tile_member(
    download_url: str,
    member_name: str,
    cache_path: Path,
) -> Path:
    """ZIP から対象メンバーのみを取り出してキャッシュへ保存する。

    キャッシュが既に存在する場合は再ダウンロードしない。

    Args:
        download_url (str): ZIP のダウンロード URL。
        member_name (str): ZIP 内のメンバーパス。
        cache_path (Path): 保存先パス。

    Returns:
        Path: 保存したファイルのパス。

    Raises:
        RuntimeError: ZIP に対象メンバーが存在しない場合。
    """
    if cache_path.exists():
        logger.info("キャッシュ済みのタイルを使います: %s", cache_path)
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    reader = HttpRangeReader(download_url)
    logger.info("ZIP の中央ディレクトリを読み込みます（全体 %.1f GB）…", reader.size / 1e9)

    with zipfile.ZipFile(reader) as zip_file:
        try:
            member_info = zip_file.getinfo(member_name)
        except KeyError as error:
            raise RuntimeError(f"ZIP に対象メンバーが見つかりません: {member_name}") from error

        logger.info(
            "対象メンバーを取得します: %s（圧縮後 %.1f MB）",
            member_name,
            member_info.compress_size / 1e6,
        )
        # 途中で失敗した場合に不完全なキャッシュを残さないよう一時ファイルへ書く
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".part")
        written_bytes = 0
        with zip_file.open(member_name) as member_stream, temporary_path.open("wb") as output_file:
            while chunk := member_stream.read(DOWNLOAD_CHUNK_BYTES):
                output_file.write(chunk)
                written_bytes += len(chunk)
                logger.info(
                    "  ダウンロード中: %.1f / %.1f MB",
                    written_bytes / 1e6,
                    member_info.file_size / 1e6,
                )
        temporary_path.replace(cache_path)

    logger.info("タイルを保存しました: %s", cache_path)
    return cache_path


def clip_band_to_roi(
    tile_path: Path,
    roi_gdf: gpd.GeoDataFrame,
    band_index: int,
    output_path: Path,
) -> dict[str, Any]:
    """タイルの対象バンドを ROI ポリゴンでクリップして GeoTIFF に保存する。

    Args:
        tile_path (Path): 入力タイルの GeoTIFF パス。
        roi_gdf (gpd.GeoDataFrame): ROI（EPSG:4326）。
        band_index (int): 読み出すバンド番号（1 始まり）。
        output_path (Path): 出力 GeoTIFF パス。

    Returns:
        dict[str, Any]: 出力ラスタの諸元（CRS・解像度・bounds・画素数）。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(tile_path) as source:
        roi_in_source_crs = roi_gdf.to_crs(source.crs)
        clipped_array, clipped_transform = mask(
            source,
            shapes=[geometry.__geo_interface__ for geometry in roi_in_source_crs.geometry],
            crop=True,
            indexes=[band_index],
            nodata=OUTPUT_NODATA,
        )
        profile = source.profile.copy()

    profile.update(
        count=1,
        height=clipped_array.shape[1],
        width=clipped_array.shape[2],
        transform=clipped_transform,
        nodata=OUTPUT_NODATA,
    )
    with rasterio.open(output_path, "w", **profile) as destination:
        destination.write(clipped_array)

    with rasterio.open(output_path) as destination:
        bounds = destination.bounds
        return {
            "crs": destination.crs.to_string() if destination.crs is not None else None,
            "dtype": str(destination.dtypes[0]),
            "width": int(destination.width),
            "height": int(destination.height),
            "resolution": [float(destination.res[0]), float(destination.res[1])],
            "bounds": {
                "minx": float(bounds.left),
                "miny": float(bounds.bottom),
                "maxx": float(bounds.right),
                "maxy": float(bounds.top),
            },
            "nodata": float(OUTPUT_NODATA),
        }


def build_class_distribution(
    array: np.ndarray,
    roi_mask: np.ndarray | None = None,
    filled_values: tuple[int, ...] = FILLED_VALUES,
) -> dict[str, Any]:
    """ROI 内のクラス値ごとの画素数と、ROI 内での有効画素率を集計する。

    ROI ポリゴンでクリップした出力は ROI の BBOX 矩形になり、ROI 外の余白は
    nodata（Filled value と同じ 0）で埋まる。この余白を「欠測」と数えると
    有効カバレッジを ROI 全体と取り違えるため、`roi_mask` で ROI 内外を分けて集計する。
    有効画素率の分母は **ROI 内の画素数** であり、ラスタ全体の画素数ではない。

    Args:
        array (np.ndarray): クラス値の配列。
        roi_mask (np.ndarray | None): ROI 内を True とする真偽値配列。
            None の場合は全画素を ROI 内として扱う。
        filled_values (tuple[int, ...]): 無効値として扱う値。

    Returns:
        dict[str, Any]: 画素統計とクラス別内訳。
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
        if class_value not in CLASS_LABELS:
            unknown_class_values.append(class_value)
        classes.append(
            {
                "value": class_value,
                "label": CLASS_LABELS.get(class_value, "Unknown"),
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


def to_project_relative_string(path: Path) -> str:
    """可能ならプロジェクト相対パスへ変換する。

    Args:
        path (Path): 変換対象パス。

    Returns:
        str: プロジェクト相対パス、または絶対パス文字列。
    """
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved_path)


def build_summary(
    year: int,
    tile_names: list[str],
    zip_name: str,
    member_name: str,
    roi_path: Path,
    roi_bounds: tuple[float, float, float, float],
    raster_profile: dict[str, Any],
    class_distribution: dict[str, Any],
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    Args:
        year (int): 取得対象年。
        tile_names (list[str]): 使用したタイル名。
        zip_name (str): 取得元 ZIP ファイル名。
        member_name (str): ZIP 内メンバーパス。
        roi_path (Path): ROI ファイルパス。
        roi_bounds (tuple[float, float, float, float]): ROI の BBOX。
        raster_profile (dict[str, Any]): 出力ラスタの諸元。
        class_distribution (dict[str, Any]): クラス分布の集計結果。
        output_path (Path): 出力 GeoTIFF パス。
        summary_path (Path): サマリー JSON パス。
        retrieved_at (str): 取得日時（ISO8601）。

    Returns:
        dict[str, Any]: サマリー辞書。
    """
    return {
        "dataset": DATASET_NAME,
        "dataset_version": DATASET_VERSION,
        "doi": DATASET_DOI,
        "source": ZENODO_API_URL_TEMPLATE.format(record_id=DEFAULT_ZENODO_RECORD_ID),
        "license": "CC BY 4.0",
        "license_note": (
            "User Guides の Data Use Policy により、科学論文での利用時は"
            "提供者への事前連絡と謝辞・共著の検討が推奨されている。"
        ),
        "retrieved_at": retrieved_at,
        "year": year,
        "year_note": (
            f"GLC_FCS30D の年次マップは {ANNUAL_FIRST_YEAR}-{ANNUAL_LAST_YEAR} 年のみ提供される。"
            "本研究の Landsat 観測年（2023年前後）とは最大で数年のずれがある。"
        ),
        "band_index": band_index_for_year(year),
        "tiles": tile_names,
        "source_zip": zip_name,
        "source_member": member_name,
        "roi_path": to_project_relative_string(roi_path),
        "roi_bbox": list(roi_bounds),
        "crs": raster_profile["crs"],
        "raster_profile": raster_profile,
        "pixel_stats": {
            "total_pixels": class_distribution["total_pixels"],
            "roi_pixels": class_distribution["roi_pixels"],
            "outside_roi_pixels": class_distribution["outside_roi_pixels"],
            "valid_pixels": class_distribution["valid_pixels"],
            "filled_pixels": class_distribution["filled_pixels"],
            "valid_pixel_ratio": class_distribution["valid_pixel_ratio"],
        },
        "class_distribution": class_distribution["classes"],
        "unknown_class_values": class_distribution["unknown_class_values"],
        "coverage_note": (
            "ROI ポリゴンで真にクリップしているため、出力は ROI の BBOX 矩形となり、"
            "ROI 外の余白は nodata（0）で埋まる。有効カバレッジは ROI 内のみで評価し、"
            "valid_pixel_ratio の分母は roi_pixels（ROI 内画素数）である。"
            "ROI 内の無効値（Filled value 0/250）は filled_pixels として別に集計する。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
    }


def resolve_output_paths(
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
) -> tuple[Path, Path]:
    """出力 GeoTIFF とサマリー JSON の保存先を解決する。

    Args:
        year (int): 取得対象年。
        output_path (Path | None): 指定された出力パス。
        summary_path (Path | None): 指定されたサマリーパス。

    Returns:
        tuple[Path, Path]: (出力 GeoTIFF パス, サマリー JSON パス)。
    """
    output_stem = f"glc_fcs30d_hanoi_{year}"
    resolved_output_path = output_path or (DEFAULT_OUTPUT_DIR / f"{output_stem}.tif")
    resolved_summary_path = summary_path or (DEFAULT_SUMMARY_DIR / f"{output_stem}_summary.json")
    return resolved_output_path, resolved_summary_path


def run(
    roi_path: Path,
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
    cache_dir: Path,
    record_id: str,
    overwrite: bool,
) -> tuple[Path, Path]:
    """取得から検証・保存までの処理全体を実行する。

    Args:
        roi_path (Path): ROI の Shapefile パス。
        year (int): 取得対象年。
        output_path (Path | None): 出力 GeoTIFF パス。
        summary_path (Path | None): サマリー JSON パス。
        cache_dir (Path): タイルのキャッシュ先ディレクトリ。
        record_id (str): Zenodo のレコード ID。
        overwrite (bool): 既存出力を上書きするか。

    Returns:
        tuple[Path, Path]: (出力 GeoTIFF パス, サマリー JSON パス)。

    Raises:
        FileExistsError: 出力ファイルが既に存在し overwrite が False の場合。
        NotImplementedError: ROI が複数タイルにまたがる場合。
    """
    band_index = band_index_for_year(year)
    resolved_output_path, resolved_summary_path = resolve_output_paths(
        year=year, output_path=output_path, summary_path=summary_path
    )
    if resolved_output_path.exists() and not overwrite:
        raise FileExistsError(
            f"出力ファイルが既に存在します: {resolved_output_path}。"
            "上書きする場合は --overwrite を指定してください。"
        )

    roi_gdf, _ = load_roi_geometry(roi_path)
    roi_bounds = tuple(float(value) for value in roi_gdf.total_bounds)
    tile_names = tile_names_for_bounds(roi_bounds)
    logger.info("ROI BBOX: %s / 必要タイル: %s", roi_bounds, tile_names)

    if len(tile_names) != 1:
        # Hanoi ROI は単一タイルに収まる。複数タイルのモザイク処理は未実装。
        raise NotImplementedError(
            f"ROI が複数タイルにまたがります（{tile_names}）。モザイク処理は未実装です。"
        )

    tile_name = tile_names[0]
    zip_name = zip_name_for_tile(tile_name)
    member_name = member_name_for_tile(zip_name, tile_name)

    download_url = resolve_zip_download_url(record_id=record_id, zip_name=zip_name)
    cache_path = cache_dir / f"{DATASET_NAME}_20002022_{tile_name}_Annual_V1.1.tif"
    tile_path = extract_tile_member(
        download_url=download_url, member_name=member_name, cache_path=cache_path
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    raster_profile = clip_band_to_roi(
        tile_path=tile_path,
        roi_gdf=roi_gdf,
        band_index=band_index,
        output_path=resolved_output_path,
    )
    if raster_profile["crs"] != WGS84_CRS:
        logger.warning("出力 CRS が %s ではありません: %s", WGS84_CRS, raster_profile["crs"])

    with rasterio.open(resolved_output_path) as destination:
        class_array = destination.read(1)
        # クリップ余白（ROI 外）を欠測と数えないよう、ROI 内のマスクを別に作る
        roi_mask = geometry_mask(
            geometries=[
                geometry.__geo_interface__ for geometry in roi_gdf.to_crs(destination.crs).geometry
            ],
            out_shape=(destination.height, destination.width),
            transform=destination.transform,
            invert=True,
        )
    class_distribution = build_class_distribution(class_array, roi_mask=roi_mask)

    summary = build_summary(
        year=year,
        tile_names=tile_names,
        zip_name=zip_name,
        member_name=member_name,
        roi_path=roi_path,
        roi_bounds=roi_bounds,
        raster_profile=raster_profile,
        class_distribution=class_distribution,
        output_path=resolved_output_path,
        summary_path=resolved_summary_path,
        retrieved_at=retrieved_at,
    )
    save_summary(summary, resolved_summary_path)

    logger.info(
        "ROI 内の有効画素率: %.4f（有効 %d / ROI 内 %d、ラスタ全体 %d）",
        class_distribution["valid_pixel_ratio"],
        class_distribution["valid_pixels"],
        class_distribution["roi_pixels"],
        class_distribution["total_pixels"],
    )
    for class_entry in class_distribution["classes"][:10]:
        logger.info(
            "  %3d %-40s %10d 画素 (%.2f%%)",
            class_entry["value"],
            class_entry["label"],
            class_entry["pixel_count"],
            class_entry["ratio"] * 100,
        )

    return resolved_output_path, resolved_summary_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    output_path, summary_path = run(
        roi_path=args.roi_path,
        year=args.year,
        output_path=args.output_path,
        summary_path=args.summary_path,
        cache_dir=args.cache_dir,
        record_id=args.record_id,
        overwrite=args.overwrite,
    )
    print(f"GeoTIFF を保存しました: {output_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
