"""
GlobalBuildingAtlas (GBA) WFS から Hanoi ROI 内の建物を取得する。

WFS レイヤーのネイティブ CRS は EPSG:3857 のため、BBOX クエリには
EPSG:3857 座標を使う。ROI 全域の単一クエリはサーバー側でタイムアウトする
ため、ROI を格子状タイルに分割してタイルごとに取得する。
取得結果は EPSG:4326 の GeoPackage に保存し、サマリー JSON を出力する。
Microsoft データ欠落域（105.29–105.47°E）でのカバレッジ確認も行う。
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyproj
from shapely.geometry import box, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROI_PATH = PROJECT_ROOT / "data" / "GISData" / "ROI" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_gba_buildings.gpkg"
DEFAULT_SUMMARY_PATH = (
    PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_gba_buildings_summary.json"
)

WFS_ENDPOINT = "https://tubvsig-so2sat-vm1.srv.mwn.de/geoserver/ows"
WFS_LAYER = "global3D:lod1_global"
# このサーバーの GeoServer には以下の制約がある（動作確認済み 2026-06-03）:
#   - startIndex パラメータは 400 を返すため使用不可（ページング不可）
#   - propertyName + srsName の組み合わせも 400 になるため propertyName は省略する
#   - srsName=EPSG:4326 のみ指定すると全プロパティ + WGS84 座標で返ってくる
#   - 1 タイルあたりの建物数が count 以下になるようタイルサイズを調整する
DEFAULT_TILE_SIZE_DEG = 0.1  # タイル 1 辺のサイズ（度）。0.1° ≈ 11km
DEFAULT_MAX_COUNT = 50000  # タイルあたりの最大取得件数（超過時に警告を出す）
DEFAULT_LAYER_NAME = "buildings"
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_COUNT = 3
RETRY_WAIT_SECONDS = 10

# HTTP 429（レート制限）専用のリトライ設定。
# このサーバーは Express 製のレート制限ミドルウェアを持ち Retry-After を返さないため、
# 指数バックオフで長めに待機する（60秒 → 120秒 → … 最大 16 分、計 6 回）。
RATE_LIMIT_MAX_RETRY_COUNT = 6
RATE_LIMIT_BASE_WAIT_SECONDS = 60

# Microsoft データで建物欠落が確認されている経度範囲
MICROSOFT_MISSING_WEST = 105.29
MICROSOFT_MISSING_EAST = 105.47

# ハノイ周辺の UTM 投影（面積計算用）
HANOI_UTM_CRS = "EPSG:32648"  # UTM Zone 48N

# WFS レイヤーのネイティブ CRS（GetCapabilities で確認済み）
WFS_NATIVE_CRS = "EPSG:3857"

# EPSG:4326 → EPSG:3857 変換器（モジュールロード時に初期化）
_TRANSFORMER_4326_TO_3857 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="GlobalBuildingAtlas WFS から Hanoi ROI の建物を取得する。"
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力 GeoPackage パス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="取得サマリー JSON パス。",
    )
    parser.add_argument(
        "--layer-name",
        default=DEFAULT_LAYER_NAME,
        help="GeoPackage に保存するレイヤ名。",
    )
    parser.add_argument(
        "--tile-size",
        type=float,
        default=DEFAULT_TILE_SIZE_DEG,
        help="タイル 1 辺のサイズ（度）。デフォルト 0.1°（約 11km）。",
    )
    parser.add_argument(
        "--max-count",
        type=int,
        default=DEFAULT_MAX_COUNT,
        help="タイルあたりの最大取得件数（上限超過時に警告を出す）。",
    )
    parser.add_argument(
        "--limit-tiles",
        type=int,
        default=None,
        help="テスト用にタイル数を制限する。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    parser.add_argument(
        "--start-tile-index",
        type=int,
        default=1,
        help=(
            "再開する場合の開始タイル番号（1 始まり）。"
            "1 より大きい値を指定すると既存の出力ファイルに追記し、"
            "それより前のタイルはスキップする（中断からの再開用）。"
        ),
    )
    return parser.parse_args()


def load_roi_geometry(
    roi_path: Path,
) -> tuple[tuple[float, float, float, float], Any]:
    """ROI を読み込み、EPSG:4326 の BBOX とユニオンジオメトリを返す。

    Args:
        roi_path (Path): ROI の Shapefile パス。

    Returns:
        tuple:
            - roi_bounds (tuple[float, float, float, float]):
              (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
            - roi_union (Any): ROI の統合ジオメトリ（EPSG:4326）。
    """
    if not roi_path.exists():
        raise FileNotFoundError(f"ROI ファイルが見つかりません: {roi_path}")

    roi_gdf = gpd.read_file(roi_path).to_crs(epsg=4326)
    if roi_gdf.empty:
        raise ValueError(f"ROI に地物がありません: {roi_path}")

    roi_union = roi_gdf.geometry.union_all()
    if not roi_union.is_valid:
        roi_union = make_valid(roi_union)

    # total_bounds は (minx, miny, maxx, maxy) = (min_lon, min_lat, max_lon, max_lat)
    roi_bounds = tuple(roi_gdf.total_bounds.tolist())
    return roi_bounds, roi_union


def generate_tiles(
    roi_bounds: tuple[float, float, float, float],
    tile_size_deg: float,
) -> list[tuple[float, float, float, float]]:
    """ROI の BBOX をタイルに分割し、各タイルの BBOX リストを返す。

    Args:
        roi_bounds (tuple[float, float, float, float]):
            ROI の BBOX (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
        tile_size_deg (float): タイル 1 辺のサイズ（度）。

    Returns:
        list[tuple[float, float, float, float]]:
            タイルごとの BBOX リスト (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
    """
    min_lon, min_lat, max_lon, max_lat = roi_bounds
    tiles: list[tuple[float, float, float, float]] = []

    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        while lon < max_lon:
            tile_min_lon = lon
            tile_min_lat = lat
            tile_max_lon = min(lon + tile_size_deg, max_lon)
            tile_max_lat = min(lat + tile_size_deg, max_lat)
            tiles.append((tile_min_lon, tile_min_lat, tile_max_lon, tile_max_lat))
            lon += tile_size_deg
        lat += tile_size_deg

    return tiles


def bbox_4326_to_3857(
    bbox_4326: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """EPSG:4326 の BBOX を EPSG:3857（WFS ネイティブ CRS）に変換する。

    WFS レイヤーのネイティブ CRS が EPSG:3857 のため、BBOX クエリには
    EPSG:3857 座標を渡す必要がある。

    Args:
        bbox_4326 (tuple[float, float, float, float]):
            (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。

    Returns:
        tuple[float, float, float, float]:
            (x_min, y_min, x_max, y_max) in EPSG:3857。
    """
    min_lon, min_lat, max_lon, max_lat = bbox_4326
    x_min, y_min = _TRANSFORMER_4326_TO_3857.transform(min_lon, min_lat)
    x_max, y_max = _TRANSFORMER_4326_TO_3857.transform(max_lon, max_lat)
    return x_min, y_min, x_max, y_max


def build_wfs_url(
    bbox_3857: tuple[float, float, float, float],
    count: int,
) -> str:
    """WFS GetFeature リクエスト URL を組み立てる。

    BBOX は WFS レイヤーのネイティブ CRS（EPSG:3857）で指定し、
    出力は srsName=EPSG:4326 で WGS84 に変換させる。
    startIndex はこのサーバーでは使用不可のため省略する。

    Args:
        bbox_3857 (tuple[float, float, float, float]):
            (x_min, y_min, x_max, y_max) in EPSG:3857。
        count (int): 最大取得件数。

    Returns:
        str: WFS GetFeature リクエスト URL。
    """
    x_min, y_min, x_max, y_max = bbox_3857
    # BBOX は CRS なしで指定するとネイティブ CRS（EPSG:3857）として解釈される。
    # urlencode はコロン・カンマをエンコードして GeoServer が誤解釈するため f-string で組む。
    bbox_str = f"{x_min:.2f},{y_min:.2f},{x_max:.2f},{y_max:.2f}"
    return (
        f"{WFS_ENDPOINT}"
        f"?service=WFS"
        f"&version=2.0.0"
        f"&request=GetFeature"
        f"&typeNames={WFS_LAYER}"
        f"&bbox={bbox_str}"
        f"&count={count}"
        f"&outputFormat=application/json"
        f"&srsName=EPSG:4326"
    )


def fetch_wfs_page(url: str, timeout: int) -> tuple[list[dict[str, Any]], int]:
    """WFS から 1 ページ分の地物を取得する。

    通常のエラー（接続エラー・429 以外の HTTP エラー）は MAX_RETRY_COUNT 回まで
    RETRY_WAIT_SECONDS 秒間隔でリトライする。
    HTTP 429（レート制限）はサーバーが Retry-After を返さないため、
    RATE_LIMIT_BASE_WAIT_SECONDS 秒を起点とした指数バックオフで
    RATE_LIMIT_MAX_RETRY_COUNT 回までリトライする（通常リトライとは別枠）。

    Args:
        url (str): WFS GetFeature リクエスト URL。
        timeout (int): タイムアウト秒数。

    Returns:
        tuple:
            - features (list[dict[str, Any]]): GeoJSON Feature リスト。
            - number_matched (int): サーバー側の総件数（-1 = 不明）。

    Raises:
        RuntimeError: リトライ上限を超えてもエラーが解消しない場合。
    """
    last_error: Exception | None = None
    generic_attempt = 0
    rate_limit_attempt = 0

    while True:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            features = data.get("features") or []
            number_matched = int(data.get("numberMatched", -1))
            return features, number_matched
        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > RATE_LIMIT_MAX_RETRY_COUNT:
                    raise RuntimeError(
                        f"WFS レート制限（429）が {RATE_LIMIT_MAX_RETRY_COUNT} 回"
                        f"解消しませんでした: {exc}"
                    ) from exc
                wait_seconds = RATE_LIMIT_BASE_WAIT_SECONDS * (2 ** (rate_limit_attempt - 1))
                logger.warning(
                    "WFS レート制限 429（リトライ %d/%d）。%d 秒待機します…",
                    rate_limit_attempt,
                    RATE_LIMIT_MAX_RETRY_COUNT,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            generic_attempt += 1
            logger.warning(
                "WFS HTTP エラー %d（試行 %d/%d）: %s",
                exc.code,
                generic_attempt,
                MAX_RETRY_COUNT,
                url[:120],
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            generic_attempt += 1
            logger.warning(
                "WFS 接続エラー（試行 %d/%d）: %s",
                generic_attempt,
                MAX_RETRY_COUNT,
                exc,
            )

        if generic_attempt >= MAX_RETRY_COUNT:
            raise RuntimeError(
                f"WFS リクエストが {MAX_RETRY_COUNT} 回失敗しました: {last_error}"
            ) from last_error

        logger.info("%d 秒後にリトライします…", RETRY_WAIT_SECONDS)
        time.sleep(RETRY_WAIT_SECONDS)


def _clip_to_roi(geom: Any, roi_union: Any) -> Any | None:
    """ジオメトリを ROI ポリゴンでクリップし、ポリゴンジオメトリを返す。

    ROI と交差しない場合、またはクリップ後にポリゴンが残らない場合は None を返す。
    GeometryCollection が返された場合はポリゴン部分のみを抽出する。

    Args:
        geom (Any): クリップ対象のジオメトリ（Shapely geometry）。
        roi_union (Any): ROI の統合ジオメトリ（EPSG:4326）。

    Returns:
        Any | None: クリップ後のポリゴンジオメトリ、または None。
    """
    try:
        if not geom.intersects(roi_union):
            return None
        clipped = geom.intersection(roi_union)
    except Exception:
        return None

    if clipped.is_empty:
        return None

    if clipped.geom_type in ("Polygon", "MultiPolygon"):
        return clipped if clipped.is_valid else make_valid(clipped)

    # GeometryCollection の場合はポリゴン部分だけを取り出す
    if clipped.geom_type == "GeometryCollection":
        polygons = [
            p
            for p in clipped.geoms
            if p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty
        ]
        if not polygons:
            return None
        result = unary_union(polygons)
        return result if result.is_valid else make_valid(result)

    # 線・点になった場合は除外
    return None


def parse_feature(feature: dict[str, Any], roi_union: Any) -> dict[str, Any] | None:
    """GeoJSON Feature を保存用レコードに変換する。

    GeoServer が返すジオメトリを ROI ポリゴンでクリップする。
    ROI 外の建物・クリップ後に空になった建物は None を返す。

    Args:
        feature (dict[str, Any]): GeoJSON Feature オブジェクト。
        roi_union (Any): ROI の統合ジオメトリ（EPSG:4326）。クリップに使用する。

    Returns:
        dict[str, Any] | None: 保存用レコード、または None。
    """
    geometry_dict = feature.get("geometry")
    if geometry_dict is None:
        return None

    try:
        geom = shape(geometry_dict)
    except Exception:
        return None

    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.is_empty:
        return None

    # ROI ポリゴンでクリップ（BBOX の矩形外にはみ出た建物を除外）
    geom = _clip_to_roi(geom, roi_union)
    if geom is None:
        return None

    props = feature.get("properties") or {}
    return {
        "ogc_fid": props.get("ogc_fid"),
        "source": props.get("source"),
        "gba_id": props.get("id"),
        "height": props.get("height"),
        "var": props.get("var"),
        "region": props.get("region"),
        "geometry": geom,
    }


def fetch_tile_records(
    tile_bbox_4326: tuple[float, float, float, float],
    tile_index: int,
    max_count: int,
    roi_union: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """1 タイル分の建物を 1 リクエストで取得する。

    このサーバーの GeoServer は startIndex パラメータを受け付けないため、
    ページングは行わず 1 回の大きな count で全件取得する。
    numberReturned < numberMatched の場合、取得漏れを警告する。
    取得後に roi_union でクリップし、ROI 外の建物は除外する。

    Args:
        tile_bbox_4326 (tuple[float, float, float, float]):
            タイルの BBOX (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
        tile_index (int): タイル番号（ログ表示用）。
        max_count (int): タイルあたりの最大取得件数。
        roi_union (Any): ROI の統合ジオメトリ（EPSG:4326）。

    Returns:
        tuple:
            - records (list[dict[str, Any]]): ROI クリップ済みの有効なレコードのリスト。
            - tile_summary (dict[str, Any]): タイル別の取得サマリー。
    """
    # タイルが ROI ポリゴンと交差しない場合はリクエストをスキップ（BBOX 隅のタイル対策）
    tile_geom = box(*tile_bbox_4326)
    if not tile_geom.intersects(roi_union):
        return [], {
            "tile_index": tile_index,
            "bbox_4326": list(tile_bbox_4326),
            "server_number_matched": 0,
            "number_returned": 0,
            "record_count": 0,
            "truncated": False,
            "skipped_roi_no_overlap": True,
        }

    tile_bbox_3857 = bbox_4326_to_3857(tile_bbox_4326)
    url = build_wfs_url(tile_bbox_3857, max_count)

    features, number_matched = fetch_wfs_page(url, REQUEST_TIMEOUT_SECONDS)

    if number_matched > 0 and len(features) < number_matched:
        logger.warning(
            "タイル %d: numberMatched=%d に対し numberReturned=%d。"
            "max_count を増やすか tile_size を小さくしてください。",
            tile_index,
            number_matched,
            len(features),
        )

    records = [r for f in features if (r := parse_feature(f, roi_union)) is not None]

    tile_summary = {
        "tile_index": tile_index,
        "bbox_4326": list(tile_bbox_4326),
        "server_number_matched": number_matched,
        "number_returned": len(features),
        "record_count": len(records),
        "truncated": number_matched > 0 and len(features) < number_matched,
    }
    return records, tile_summary


def write_records_to_gpkg(
    records: list[dict[str, Any]],
    output_path: Path,
    layer_name: str,
    append_mode: bool,
) -> None:
    """建物レコードを GeoPackage に書き込む。

    メモリ効率を保つため、タイルごとに書き込む。
    最初のタイルは新規書き込みモード、以降は追記モードで保存する。

    Args:
        records (list[dict[str, Any]]): 保存対象レコード。
        output_path (Path): 出力 GPKG パス。
        layer_name (str): レイヤ名。
        append_mode (bool): 追記モードなら True、新規書き込みなら False。
    """
    if not records:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tile_gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    mode = "a" if append_mode else "w"
    tile_gdf.to_file(output_path, layer=layer_name, driver="GPKG", mode=mode)


def compute_missing_area_stats(
    gpkg_path: Path,
    layer_name: str,
    west_lon: float,
    east_lon: float,
    roi_bounds: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Microsoft 欠落域内の建物数・面積率を算出する。

    保存済み GeoPackage を読み込み、指定経度範囲に含まれる建物を
    UTM 投影で面積集計する。

    Args:
        gpkg_path (Path): 読み込む GeoPackage パス。
        layer_name (str): レイヤ名。
        west_lon (float): 欠落域の西端経度。
        east_lon (float): 欠落域の東端経度。
        roi_bounds (tuple[float, float, float, float]):
            ROI の BBOX (min_lon, min_lat, max_lon, max_lat)。

    Returns:
        dict[str, Any]: 建物数・面積・ドメイン面積・面積率。
    """
    _, min_lat, _, max_lat = roi_bounds
    missing_box = box(west_lon, min_lat, east_lon, max_lat)

    gdf = gpd.read_file(gpkg_path, layer=layer_name)

    # 欠落域に交差する建物を抽出
    gdf_in_missing = gdf[gdf.geometry.intersects(missing_box)].copy()

    # 面積計算のため UTM 投影に変換
    gdf_utm = gdf_in_missing.to_crs(HANOI_UTM_CRS)
    missing_box_utm = gpd.GeoSeries([missing_box], crs="EPSG:4326").to_crs(HANOI_UTM_CRS).iloc[0]

    total_building_area_m2 = float(gdf_utm.geometry.area.sum())
    domain_area_m2 = float(missing_box_utm.area)
    area_ratio = total_building_area_m2 / domain_area_m2 if domain_area_m2 > 0 else 0.0

    return {
        "lon_range_description": "Microsoft データ欠落域（西側）",
        "lon_range": [west_lon, east_lon],
        "building_count": int(len(gdf_in_missing)),
        "building_area_m2": total_building_area_m2,
        "domain_area_m2": domain_area_m2,
        "building_area_ratio": area_ratio,
    }


def save_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """サマリー JSON を保存する。

    Args:
        summary (dict[str, Any]): 保存内容。
        summary_path (Path): 保存先パス。
    """
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(
    roi_path: Path,
    output_path: Path,
    summary_path: Path,
    layer_name: str,
    tile_size_deg: float,
    max_count: int,
    limit_tiles: int | None,
    overwrite: bool,
    start_tile_index: int,
) -> None:
    """取得処理全体を実行する。

    1. ROI の BBOX を読み込む
    2. ROI をタイルに分割する
    3. タイルごとに WFS で建物を取得し GeoPackage に逐次書き込む
    4. Microsoft 欠落域のカバレッジ統計を算出する
    5. サマリー JSON を保存する

    start_tile_index が 1 より大きい場合は中断からの再開とみなし、
    既存の出力ファイルに追記する（それより前のタイルはスキップする）。

    Args:
        roi_path (Path): ROI の Shapefile パス。
        output_path (Path): 出力 GeoPackage パス。
        summary_path (Path): サマリー JSON パス。
        layer_name (str): GeoPackage レイヤ名。
        tile_size_deg (float): タイルサイズ（度）。
        max_count (int): タイルあたりの最大取得件数。
        limit_tiles (int | None): テスト用のタイル数上限。
        overwrite (bool): 既存ファイルを上書きするか。
        start_tile_index (int): 取得を開始するタイル番号（1 始まり）。
    """
    resuming = start_tile_index > 1

    if resuming:
        if not output_path.exists():
            raise FileNotFoundError(f"再開対象の出力ファイルが見つかりません: {output_path}")
        logger.info(
            "タイル %d から再開します（既存ファイルに追記）: %s",
            start_tile_index,
            output_path,
        )
    elif output_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します: {output_path}。"
                "上書きする場合は --overwrite を付けてください。"
            )
        output_path.unlink()
        logger.info("既存ファイルを削除しました: %s", output_path)

    roi_bounds, roi_union = load_roi_geometry(roi_path)
    logger.info("ROI BBOX (min_lon, min_lat, max_lon, max_lat): %s", roi_bounds)

    tiles = generate_tiles(roi_bounds, tile_size_deg)
    logger.info("タイル数: %d（タイルサイズ: %.2f°）", len(tiles), tile_size_deg)

    if limit_tiles is not None:
        tiles = tiles[:limit_tiles]
        logger.info("テスト用にタイルを %d 件に制限しました。", limit_tiles)

    fetch_start = datetime.now(tz=timezone.utc)
    session_count = 0
    append_mode = resuming
    tile_summaries: list[dict[str, Any]] = []

    for tile_index, tile_bbox in enumerate(tiles, start=1):
        if tile_index < start_tile_index:
            continue

        logger.info(
            "タイル %d/%d 取得中: bbox=%s",
            tile_index,
            len(tiles),
            tile_bbox,
        )
        records, tile_summary = fetch_tile_records(tile_bbox, tile_index, max_count, roi_union)

        write_records_to_gpkg(records, output_path, layer_name, append_mode)
        if records:
            append_mode = True
        session_count += len(records)
        tile_summaries.append(tile_summary)

        logger.info(
            "  → タイル %d 完了: %d 件（今回セッション累計: %d 件）",
            tile_index,
            len(records),
            session_count,
        )

    fetch_end = datetime.now(tz=timezone.utc)

    if not output_path.exists():
        logger.warning("取得できた建物データがありません。処理を終了します。")
        return

    logger.info("今回セッションの取得完了: %d 件", session_count)

    # Microsoft 欠落域のカバレッジ確認
    logger.info(
        "Microsoft 欠落域 (%.2f–%.2f°E) のカバレッジを確認中…",
        MICROSOFT_MISSING_WEST,
        MICROSOFT_MISSING_EAST,
    )
    missing_stats = compute_missing_area_stats(
        gpkg_path=output_path,
        layer_name=layer_name,
        west_lon=MICROSOFT_MISSING_WEST,
        east_lon=MICROSOFT_MISSING_EAST,
        roi_bounds=roi_bounds,
    )

    # 保存した建物全体の BBOX・件数を確認する（再開時も含めた累積の真値）
    gdf_check = gpd.read_file(output_path, layer=layer_name)
    building_bounds = gdf_check.total_bounds.tolist()
    total_count = int(len(gdf_check))

    summary = {
        "fetch_start_utc": fetch_start.isoformat(),
        "fetch_end_utc": fetch_end.isoformat(),
        "roi_path": str(roi_path.relative_to(PROJECT_ROOT)),
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "summary_path": str(summary_path.relative_to(PROJECT_ROOT)),
        "roi_bbox": list(roi_bounds),
        "building_bbox": building_bounds,
        "total_building_count": total_count,
        "session_building_count": session_count,
        "start_tile_index": start_tile_index,
        "tile_size_deg": tile_size_deg,
        "tile_count": len(tiles),
        "limit_tiles_applied": limit_tiles,
        "wfs_endpoint": WFS_ENDPOINT,
        "wfs_layer": WFS_LAYER,
        "wfs_native_crs": WFS_NATIVE_CRS,
        "max_count_per_tile": max_count,
        "tile_summaries": tile_summaries,
        "microsoft_missing_area_coverage": missing_stats,
    }
    save_summary(summary, summary_path)

    logger.info("GeoPackage: %s", output_path)
    logger.info("Summary JSON: %s", summary_path)
    logger.info("総建物数（累計）: %d 件", total_count)
    logger.info(
        "Microsoft 欠落域: 建物数=%d 件, 面積率=%.4f",
        missing_stats["building_count"],
        missing_stats["building_area_ratio"],
    )


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    run(
        roi_path=args.roi_path,
        output_path=args.output_path,
        summary_path=args.summary_path,
        layer_name=args.layer_name,
        tile_size_deg=args.tile_size,
        max_count=args.max_count,
        limit_tiles=args.limit_tiles,
        overwrite=args.overwrite,
        start_tile_index=args.start_tile_index,
    )


if __name__ == "__main__":
    main()
