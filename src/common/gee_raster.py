"""Google Earth Engine 由来ラスタのダウンロード処理。

GEE からラスタを取得する複数のスクリプトで重複していた、以下の処理を集約する。

- ネイティブグリッドを保ったままのダウンロード URL 生成
- ダウンロード結果（GeoTIFF 単体または ZIP）の保存

GEE 固有の事情として、`getDownloadURL` は単一バンドでも ZIP で返す場合があること、
GeoTIFF 出力ではマスク画素が 0 で書き出されて「値 0」と「データ無し」が区別できなく
なることの 2 点をここで吸収する。

取得元に依存しない処理は別モジュールにある。取得対象範囲の組み立てと被覆判定は
`src.common.raster_area`、画素統計は `src.common.raster_stats` を参照する。
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Any

import ee

from src.common.http_fetch import fetch_bytes_with_retry
from src.common.raster_area import DEFAULT_RASTER_NODATA

logger = logging.getLogger(__name__)


def build_native_download_url(
    image: ee.Image,
    region_geojson: dict[str, Any],
    nodata: float = DEFAULT_RASTER_NODATA,
) -> tuple[str, dict[str, Any]]:
    """ネイティブグリッドを保ったままダウンロードする URL を生成する。

    `scale` ではなく画像本来の `crs` / `crs_transform` を渡すことで再投影を避ける。
    再投影のリサンプリングは合計保存量（人口カウント等）を壊し、放射輝度でも
    画素値をならしてしまうため、取得段階では行わない。

    投影情報は先頭バンドから取得する。複数バンドを含む画像で
    `ee.Image.projection()` を直接呼ぶと、バンドごとに投影が異なる場合に失敗するため。

    Args:
        image: 対象画像（単一・複数バンドのいずれも可。全バンドが同一グリッドであること）。
        region_geojson: 取得範囲の GeoJSON（EPSG:4326）。
        nodata: マスク画素へ割り当てる無効値。

    Returns:
        (ダウンロード URL, 使用したネイティブ投影情報)。
    """
    projection_info = image.select(0).projection().getInfo()
    # マスク画素を明示的な nodata に置き換える（GEE は既定で 0 を書き出すため）
    unmasked_image = image.toFloat().unmask(nodata)
    download_url = unmasked_image.getDownloadURL(
        {
            "crs": projection_info["crs"],
            "crs_transform": projection_info["transform"],
            "region": region_geojson,
            "format": "GEO_TIFF",
        }
    )
    return download_url, projection_info


def download_gee_raster(download_url: str, destination_path: Path, timeout: int) -> Path:
    """ダウンロード URL から GeoTIFF を取得して保存する。

    GEE は単一バンドでも ZIP で返す場合があるため、ZIP なら中の GeoTIFF を取り出す。
    一時的な 5xx・接続エラーに備え、共通のリトライ付き取得を使う。

    Args:
        download_url: ダウンロード URL。
        destination_path: 保存先パス。
        timeout: タイムアウト秒数。

    Returns:
        保存したパス。

    Raises:
        ValueError: ZIP 内に GeoTIFF が見つからない場合。
    """
    response_body = fetch_bytes_with_retry(download_url, timeout=timeout)

    buffer = io.BytesIO(response_body)
    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as archive:
            tif_members = [
                member
                for member in archive.namelist()
                if member.lower().endswith((".tif", ".tiff"))
            ]
            if not tif_members:
                raise ValueError(f"ZIP 内に GeoTIFF がありません: {archive.namelist()}")
            if len(tif_members) > 1:
                # マルチバンドを1ファイルで要求しているため通常は 1 枚。複数返るのは
                # 前提が崩れたサインなので、黙って先頭を採用せず記録に残す
                logger.warning(
                    "ZIP 内に GeoTIFF が %d 枚あります。先頭 %s のみ使用します（全件: %s）。",
                    len(tif_members),
                    tif_members[0],
                    tif_members,
                )
            destination_path.write_bytes(archive.read(tif_members[0]))
        return destination_path

    destination_path.write_bytes(response_body)
    return destination_path
