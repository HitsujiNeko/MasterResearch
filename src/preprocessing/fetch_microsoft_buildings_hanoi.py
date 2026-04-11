"""
Microsoft GlobalMLBuildingFootprints から Hanoi ROI 内の建物を取得する。

本スクリプトは、Microsoft GlobalMLBuildingFootprints の配布テーブルを参照し、
Hanoi ROI に重なる quadkey のみを対象に建物データを取得する。
取得した建物は ROI でクリップし、GeoPackage とサマリー JSON に保存する。
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import math
import urllib.request
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.errors import GEOSException
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.validation import make_valid


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROI_PATH = PROJECT_ROOT / "data" / "GISData" / "ROI" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_microsoft_buildings.gpkg"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_microsoft_buildings_summary.json"
DATASET_LINKS_URL = (
    "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
)
DEFAULT_LOCATION = "Vietnam"
DEFAULT_LAYER_NAME = "buildings"
REQUEST_TIMEOUT_SECONDS = 180


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="Microsoft GlobalMLBuildingFootprints から Hanoi ROI の建物を取得する。"
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
        "--location",
        default=DEFAULT_LOCATION,
        help="dataset-links.csv の Location 列で絞り込む国名。",
    )
    parser.add_argument(
        "--layer-name",
        default=DEFAULT_LAYER_NAME,
        help="GeoPackage に保存するレイヤ名。",
    )
    parser.add_argument(
        "--limit-tiles",
        type=int,
        default=None,
        help="テスト用に対象タイル数を制限する。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def load_roi_geometry(roi_path: Path) -> tuple[gpd.GeoDataFrame, Any]:
    """ROI を読み込み、EPSG:4326 に正規化する。

    Args:
        roi_path (Path): ROI の Shapefile パス。

    Returns:
        tuple[gpd.GeoDataFrame, Any]:
            EPSG:4326 の ROI GeoDataFrame と統合ジオメトリ。
    """
    if not roi_path.exists():
        raise FileNotFoundError(f"ROI ファイルが見つかりません: {roi_path}")

    roi_gdf = gpd.read_file(roi_path)
    if roi_gdf.empty:
        raise ValueError(f"ROI ファイルに地物がありません: {roi_path}")

    if roi_gdf.crs is None:
        raise ValueError(f"ROI の CRS が未定義です: {roi_path}")

    roi_gdf = roi_gdf.to_crs(epsg=4326)
    roi_union = normalize_polygon_geometry(roi_gdf.geometry.union_all())
    if roi_union is None:
        raise ValueError(f"ROI のジオメトリを正規化できませんでした: {roi_path}")
    return roi_gdf, roi_union


def load_dataset_links() -> pd.DataFrame:
    """Microsoft の配布テーブルを読み込む。

    Returns:
        pd.DataFrame: dataset-links テーブル。
    """
    dataset_links = pd.read_csv(
        DATASET_LINKS_URL,
        dtype={
            "Location": "string",
            "QuadKey": "string",
            "Url": "string",
        },
    )
    required_columns = {"Location", "QuadKey", "Url"}
    missing_columns = required_columns.difference(dataset_links.columns)
    if missing_columns:
        raise ValueError(f"dataset-links.csv に必要列がありません: {sorted(missing_columns)}")
    dataset_links = dataset_links.dropna(subset=["Location", "QuadKey", "Url"]).copy()
    dataset_links["Location"] = dataset_links["Location"].astype(str).str.strip()
    dataset_links["QuadKey"] = dataset_links["QuadKey"].astype(str).str.strip()
    dataset_links["Url"] = dataset_links["Url"].astype(str).str.strip()
    return dataset_links


def normalize_polygon_geometry(geometry: Any) -> Any | None:
    """ポリゴン系ジオメトリを妥当化して返す。

    Args:
        geometry (Any): 入力ジオメトリ。

    Returns:
        Any | None: 正規化済みポリゴン系ジオメトリ。利用不能な場合は None。
    """
    if geometry is None or geometry.is_empty:
        return None

    normalized_geometry = geometry
    if not normalized_geometry.is_valid:
        normalized_geometry = make_valid(normalized_geometry)

    if normalized_geometry.is_empty:
        return None

    if normalized_geometry.geom_type == "GeometryCollection":
        polygon_geometries = [
            part
            for part in normalized_geometry.geoms
            if part.geom_type in {"Polygon", "MultiPolygon"} and not part.is_empty
        ]
        if not polygon_geometries:
            return None
        normalized_geometry = unary_union(polygon_geometries)

    if normalized_geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None

    if not normalized_geometry.is_valid:
        normalized_geometry = make_valid(normalized_geometry)

    if normalized_geometry.is_empty or normalized_geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None

    return normalized_geometry


def quadkey_to_tile_xy(quadkey: str) -> tuple[int, int, int]:
    """quadkey を tile x/y/zoom へ変換する。

    Args:
        quadkey (str): Microsoft/Bing 形式の quadkey。

    Returns:
        tuple[int, int, int]: tile_x, tile_y, zoom_level。
    """
    tile_x = 0
    tile_y = 0
    zoom_level = len(quadkey)

    for index, digit in enumerate(quadkey):
        mask = 1 << (zoom_level - index - 1)
        if digit == "0":
            continue
        if digit == "1":
            tile_x |= mask
            continue
        if digit == "2":
            tile_y |= mask
            continue
        if digit == "3":
            tile_x |= mask
            tile_y |= mask
            continue
        raise ValueError(f"quadkey に不正な文字があります: {quadkey}")

    return tile_x, tile_y, zoom_level


def tile_xy_to_lon_lat(tile_x: int, tile_y: int, zoom_level: int) -> tuple[float, float]:
    """tile 座標を経度・緯度へ変換する。

    Args:
        tile_x (int): x 座標。
        tile_y (int): y 座標。
        zoom_level (int): ズームレベル。

    Returns:
        tuple[float, float]: 経度、緯度。
    """
    map_size = 2**zoom_level
    lon = tile_x / map_size * 360.0 - 180.0
    mercator_y = math.pi * (1.0 - 2.0 * tile_y / map_size)
    lat = math.degrees(math.atan(math.sinh(mercator_y)))
    return lon, lat


def quadkey_to_bbox(quadkey: str) -> tuple[float, float, float, float]:
    """quadkey のタイル BBox を EPSG:4326 で返す。

    Args:
        quadkey (str): quadkey。

    Returns:
        tuple[float, float, float, float]:
            min_lon, min_lat, max_lon, max_lat。
    """
    tile_x, tile_y, zoom_level = quadkey_to_tile_xy(quadkey)
    min_lon, max_lat = tile_xy_to_lon_lat(tile_x, tile_y, zoom_level)
    max_lon, min_lat = tile_xy_to_lon_lat(tile_x + 1, tile_y + 1, zoom_level)
    return min_lon, min_lat, max_lon, max_lat


def bbox_intersects(
    left_bbox: tuple[float, float, float, float],
    right_bbox: tuple[float, float, float, float],
) -> bool:
    """2つの BBox が交差するか判定する。

    Args:
        left_bbox (tuple[float, float, float, float]): 左側 BBox。
        right_bbox (tuple[float, float, float, float]): 右側 BBox。

    Returns:
        bool: 交差する場合 True。
    """
    left_min_x, left_min_y, left_max_x, left_max_y = left_bbox
    right_min_x, right_min_y, right_max_x, right_max_y = right_bbox

    return not (
        left_max_x < right_min_x
        or right_max_x < left_min_x
        or left_max_y < right_min_y
        or right_max_y < left_min_y
    )


def filter_candidate_tiles(
    dataset_links: pd.DataFrame,
    location: str,
    roi_bounds: tuple[float, float, float, float],
    limit_tiles: int | None,
) -> pd.DataFrame:
    """ROI に重なる候補タイルだけへ絞り込む。

    Args:
        dataset_links (pd.DataFrame): 配布テーブル。
        location (str): 対象国名。
        roi_bounds (tuple[float, float, float, float]): ROI BBox。
        limit_tiles (int | None): テスト用タイル数制限。

    Returns:
        pd.DataFrame: 候補タイル一覧。
    """
    country_links = dataset_links.loc[dataset_links["Location"] == location].copy()
    if country_links.empty:
        raise ValueError(f"Location={location} の行が見つかりません。")

    country_links["QuadKey"] = country_links["QuadKey"].astype(str).str.strip()
    country_links["tile_bbox"] = country_links["QuadKey"].apply(quadkey_to_bbox)
    candidate_links = country_links.loc[
        country_links["tile_bbox"].apply(lambda bbox: bbox_intersects(bbox, roi_bounds))
    ].copy()

    if limit_tiles is not None:
        candidate_links = candidate_links.head(limit_tiles).copy()

    if candidate_links.empty:
        raise ValueError("ROI に重なる候補タイルが見つかりません。")

    return candidate_links


def iter_remote_geojsonl(url: str):
    """遠隔の .csv.gz GeoJSONL を1行ずつ返す。

    Args:
        url (str): ダウンロード URL。

    Yields:
        dict[str, Any]: GeoJSON Feature。
    """
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        with gzip.GzipFile(fileobj=response) as gz_stream:
            with io.TextIOWrapper(gz_stream, encoding="utf-8") as text_stream:
                for line in text_stream:
                    text = line.strip()
                    if not text:
                        continue
                    yield json.loads(text)


def build_feature_record(
    feature: dict[str, Any],
    roi_union: Any,
    roi_bounds: tuple[float, float, float, float],
    quadkey: str,
    source_url: str,
    location: str,
) -> dict[str, Any] | None:
    """1建物 Feature を ROI で判定し、保存用レコードへ変換する。

    Args:
        feature (dict[str, Any]): GeoJSON Feature。
        roi_union (Any): ROI 統合ジオメトリ。
        roi_bounds (tuple[float, float, float, float]): ROI BBox。
        quadkey (str): 出典 quadkey。
        source_url (str): 出典 URL。
        location (str): 対象国名。

    Returns:
        dict[str, Any] | None: 保存対象ならレコード、対象外なら None。
    """
    geometry_dict = feature.get("geometry")
    if geometry_dict is None:
        return None

    raw_geometry = normalize_polygon_geometry(shape(geometry_dict))
    if raw_geometry is None:
        return None

    if not bbox_intersects(raw_geometry.bounds, roi_bounds):
        return None

    try:
        if not raw_geometry.intersects(roi_union):
            return None
        clipped_geometry = normalize_polygon_geometry(raw_geometry.intersection(roi_union))
    except GEOSException:
        logger.warning("不正ジオメトリを検出したためスキップします: quadkey=%s", quadkey)
        return None

    if clipped_geometry is None:
        return None

    properties = feature.get("properties", {})
    record = {
        "feature_id": feature.get("id"),
        "height_m": properties.get("height"),
        "confidence": properties.get("confidence"),
        "is_clipped": not raw_geometry.equals(clipped_geometry),
        "quadkey": quadkey,
        "source_location": location,
        "source_url": source_url,
        "geometry": clipped_geometry,
    }
    return record


def write_records_to_gpkg(
    records: list[dict[str, Any]],
    output_path: Path,
    layer_name: str,
    append_mode: bool,
) -> None:
    """建物レコード群を GeoPackage に書き込む。

    Args:
        records (list[dict[str, Any]]): 保存対象レコード。
        output_path (Path): 出力 GPKG パス。
        layer_name (str): レイヤ名。
        append_mode (bool): 追記モードなら True。
    """
    if not records:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    building_gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=4326)
    mode = "a" if append_mode else "w"
    building_gdf.to_file(output_path, layer=layer_name, driver="GPKG", mode=mode)


def fetch_tile_records(
    row: pd.Series,
    roi_union: Any,
    roi_bounds: tuple[float, float, float, float],
    location: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """1タイル分の建物を取得して ROI で抽出する。

    Args:
        row (pd.Series): 配布テーブルの1行。
        roi_union (Any): ROI 統合ジオメトリ。
        roi_bounds (tuple[float, float, float, float]): ROI BBox。
        location (str): 対象国名。

    Returns:
        tuple[list[dict[str, Any]], dict[str, Any]]:
            保存用レコード一覧とタイル別サマリー。
    """
    quadkey = str(row["QuadKey"])
    source_url = str(row["Url"])
    records: list[dict[str, Any]] = []
    source_count = 0

    logger.info("取得中: quadkey=%s", quadkey)

    for feature in iter_remote_geojsonl(source_url):
        source_count += 1
        record = build_feature_record(
            feature=feature,
            roi_union=roi_union,
            roi_bounds=roi_bounds,
            quadkey=quadkey,
            source_url=source_url,
            location=location,
        )
        if record is not None:
            records.append(record)

    summary = {
        "quadkey": quadkey,
        "source_url": source_url,
        "source_feature_count": source_count,
        "matched_feature_count": len(records),
    }
    return records, summary


def save_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """サマリー JSON を保存する。

    Args:
        summary (dict[str, Any]): 保存内容。
        summary_path (Path): 保存先。
    """
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run(
    roi_path: Path,
    output_path: Path,
    summary_path: Path,
    location: str,
    layer_name: str,
    limit_tiles: int | None,
    overwrite: bool,
) -> None:
    """取得処理全体を実行する。

    Args:
        roi_path (Path): ROI パス。
        output_path (Path): 出力 GPKG。
        summary_path (Path): サマリー JSON。
        location (str): 対象国名。
        layer_name (str): 出力レイヤ名。
        limit_tiles (int | None): テスト用タイル制限。
        overwrite (bool): 上書きフラグ。
    """
    if output_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します: {output_path}。上書きする場合は --overwrite を付けてください。"
            )
        output_path.unlink()

    roi_gdf, roi_union = load_roi_geometry(roi_path)
    roi_bounds = tuple(roi_gdf.total_bounds.tolist())
    dataset_links = load_dataset_links()
    candidate_tiles = filter_candidate_tiles(
        dataset_links=dataset_links,
        location=location,
        roi_bounds=roi_bounds,
        limit_tiles=limit_tiles,
    )

    tile_summaries: list[dict[str, Any]] = []
    total_written = 0
    append_mode = False

    for _, row in candidate_tiles.iterrows():
        records, tile_summary = fetch_tile_records(
            row=row,
            roi_union=roi_union,
            roi_bounds=roi_bounds,
            location=location,
        )
        write_records_to_gpkg(
            records=records,
            output_path=output_path,
            layer_name=layer_name,
            append_mode=append_mode,
        )
        if records:
            append_mode = True
            total_written += len(records)
        tile_summaries.append(tile_summary)

    summary = {
        "roi_path": str(roi_path.relative_to(PROJECT_ROOT)),
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "summary_path": str(summary_path.relative_to(PROJECT_ROOT)),
        "location": location,
        "candidate_tile_count": int(len(candidate_tiles)),
        "written_feature_count": total_written,
        "tile_summaries": tile_summaries,
    }
    save_summary(summary, summary_path)

    logger.info("完了: 候補タイル数=%s, 出力建物数=%s", len(candidate_tiles), total_written)
    logger.info("GeoPackage: %s", output_path)
    logger.info("Summary JSON: %s", summary_path)


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    run(
        roi_path=args.roi_path,
        output_path=args.output_path,
        summary_path=args.summary_path,
        location=args.location,
        layer_name=args.layer_name,
        limit_tiles=args.limit_tiles,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
