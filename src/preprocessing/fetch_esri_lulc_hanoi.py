"""Esri Sentinel-2 10m Annual LULC から Hanoi ROI の年次土地被覆を取得する。

データソース: Microsoft Planetary Computer の STAC コレクション `io-lulc-annual-v02`
（Impact Observatory / Esri / Microsoft、Sentinel-2 年間コンポジットの深層学習分類）。
ライセンス: CC BY 4.0（コレクションメタデータの `license` に `CC-BY-4.0` と記載）。

制約メモ（2026-07-25 確認）:
- アイテムの `data` アセットは Azure Blob 上の COG。Blob URL への直アクセスは HTTP 409 で
  拒否されるため、Planetary Computer の SAS 署名エンドポイント（認証不要）で署名してから読む。
  SAS には有効期限があるので、署名は読み取り直前に取得し、URL 自体は保存しない。
- STAC の `datetime` 範囲検索は、対象年の 1/1 に終了する前年アイテムも返す
  （2022年で検索すると `48Q-2021` も返る）。`start_datetime` の年で厳密に絞る必要がある。
- Hanoi ROI はタイル `48Q` の 1 枚に収まる。ネイティブ CRS は EPSG:32648、解像度 10m、
  タイル全体は約 232MB。COG なので ROI の BBOX に対応する window だけを読めば足りる。
- クラス値は 0-11 のうち 3 と 6 が欠番の 10 種で、うち 0（No Data）と 10（Clouds）は無効値。
  GLC_FCS30D の 35 クラスとは体系が異なるため、比較時は共通クラスへの写像が必要になる。
- 提供年は 2017-2024 年（年次）。本スクリプトの既定は GLC_FCS30D 側と揃う 2022 年。
"""

from __future__ import annotations

import argparse
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT, WGS84_CRS
from src.common.http_fetch import fetch_json_with_retry
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "gis" / "lulc" / "esri_10m"
DEFAULT_CACHE_DIR = DEFAULT_OUTPUT_DIR / "_cache"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

DATASET_NAME = "Esri Sentinel-2 10m Annual LULC"
STAC_COLLECTION_ID = "io-lulc-annual-v02"
STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
STAC_COLLECTION_URL = (
    f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/{STAC_COLLECTION_ID}"
)
SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
DATA_ASSET_KEY = "data"

# 提供年（コレクションの時間範囲）。既定は GLC_FCS30D の年次最終年に揃える。
FIRST_YEAR = 2017
LAST_YEAR = 2024
DEFAULT_YEAR = 2022

# クラス定義（コレクションの item_assets.data.file:values から転記）。3 と 6 は欠番。
CLASS_LABELS: dict[int, str] = {
    0: "No Data",
    1: "Water",
    2: "Trees",
    4: "Flooded vegetation",
    5: "Crops",
    7: "Built area",
    8: "Bare ground",
    9: "Snow/ice",
    10: "Clouds",
    11: "Rangeland",
}

# 無効値。0 は No Data、10 は雲で地表が判定できなかった画素。
FILLED_VALUES: tuple[int, ...] = (0, 10)
# 出力 GeoTIFF の nodata。No Data と同じ 0 を使う。
OUTPUT_NODATA = 0

REQUEST_TIMEOUT_SECONDS = 300
# window 読み出し時に BBOX の外側へ足す余白画素数。再投影時の端の欠けを防ぐ。
WINDOW_PAD_PIXELS = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="Esri Sentinel-2 10m Annual LULC から Hanoi ROI の年次土地被覆を取得する。"
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
        choices=range(FIRST_YEAR, LAST_YEAR + 1),
        metavar=f"{{{FIRST_YEAR}..{LAST_YEAR}}}",
        default=DEFAULT_YEAR,
        help=f"取得対象年（{FIRST_YEAR}-{LAST_YEAR}）。デフォルト {DEFAULT_YEAR}。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="出力 GeoTIFF パス。未指定時は data/gis/lulc/esri_10m/ 配下へ保存する。",
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
        help="ネイティブ CRS で切り出したサブセットのキャッシュ先ディレクトリ。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def search_annual_item(
    year: int,
    bounds: tuple[float, float, float, float],
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """STAC API で対象年・対象範囲のアイテムを 1 件に特定する。

    `datetime` の範囲検索は、対象年の 1/1 で終わる前年アイテムも返すため、
    `start_datetime` の年が一致するものだけに絞り込む。

    Args:
        year (int): 取得対象年。
        bounds (tuple[float, float, float, float]):
            (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
        timeout (int): タイムアウト秒数。

    Returns:
        dict[str, Any]: 特定した STAC アイテム。

    Raises:
        RuntimeError: 該当アイテムが 0 件の場合。
        NotImplementedError: ROI が複数タイルにまたがる場合。
    """
    query = {
        "collections": STAC_COLLECTION_ID,
        "bbox": ",".join(str(value) for value in bounds),
        "datetime": f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z",
        "limit": "50",
    }
    search_url = f"{STAC_SEARCH_URL}?{urllib.parse.urlencode(query)}"
    result = fetch_json_with_retry(search_url, timeout=timeout)

    matched = [
        feature
        for feature in result.get("features", [])
        if str(feature.get("properties", {}).get("start_datetime", "")).startswith(f"{year}-")
    ]
    if not matched:
        available = sorted(str(f.get("id")) for f in result.get("features", []))
        raise RuntimeError(
            f"{year} 年のアイテムが見つかりません（検索で返ったアイテム: {available}）。"
        )
    if len(matched) > 1:
        # Hanoi ROI は単一 UTM タイルに収まる。複数タイルのモザイク処理は未実装。
        raise NotImplementedError(
            f"ROI が複数タイルにまたがります（{[f['id'] for f in matched]}）。"
            "モザイク処理は未実装です。"
        )
    return matched[0]


def sign_asset_href(href: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
    """Blob の URL に SAS トークンを付与した署名済み URL を得る。

    署名済み URL には有効期限があるため、読み取り直前に呼び、戻り値を保存しない。

    Args:
        href (str): 署名前のアセット URL。
        timeout (int): タイムアウト秒数。

    Returns:
        str: 署名済み URL。

    Raises:
        RuntimeError: 応答に署名済み URL が含まれない場合。
    """
    sign_url = f"{SAS_SIGN_URL}?{urllib.parse.urlencode({'href': href})}"
    signed = fetch_json_with_retry(sign_url, timeout=timeout)
    if "href" not in signed:
        raise RuntimeError(f"SAS 署名の応答に href がありません: {sorted(signed)}")
    return str(signed["href"])


def padded_window(
    bounds: tuple[float, float, float, float],
    source_crs: Any,
    source_transform: Any,
    source_width: int,
    source_height: int,
    pad_pixels: int = WINDOW_PAD_PIXELS,
) -> Window:
    """ROI の BBOX を覆う読み出し window を、余白付き・整数画素で求める。

    余白を足すのは、後段の再投影で ROI 境界の画素が欠けないようにするため。
    ラスタ範囲外へはみ出さないよう、ソースの寸法でクリップする。

    Args:
        bounds (tuple[float, float, float, float]):
            (min_lon, min_lat, max_lon, max_lat) in EPSG:4326。
        source_crs (Any): ソースラスタの CRS。
        source_transform (Any): ソースラスタのアフィン変換。
        source_width (int): ソースラスタの幅（画素）。
        source_height (int): ソースラスタの高さ（画素）。
        pad_pixels (int): 四方に足す余白画素数。

    Returns:
        Window: 読み出す window。

    Raises:
        ValueError: BBOX がソースラスタと重ならない場合。
    """
    bounds_in_source = transform_bounds(WGS84_CRS, source_crs, *bounds)
    raw_window = from_bounds(*bounds_in_source, transform=source_transform)

    col_off = int(np.floor(raw_window.col_off)) - pad_pixels
    row_off = int(np.floor(raw_window.row_off)) - pad_pixels
    col_end = int(np.ceil(raw_window.col_off + raw_window.width)) + pad_pixels
    row_end = int(np.ceil(raw_window.row_off + raw_window.height)) + pad_pixels

    col_off = max(col_off, 0)
    row_off = max(row_off, 0)
    col_end = min(col_end, source_width)
    row_end = min(row_end, source_height)

    if col_end <= col_off or row_end <= row_off:
        raise ValueError(f"ROI の BBOX がソースラスタと重なりません: {bounds}")

    return Window(
        col_off=col_off,
        row_off=row_off,
        width=col_end - col_off,
        height=row_end - row_off,
    )


def fetch_native_subset(
    signed_url: str,
    bounds: tuple[float, float, float, float],
    cache_path: Path,
) -> Path:
    """COG から ROI の BBOX 相当の window のみを読み、ネイティブ CRS のまま保存する。

    キャッシュが既に存在する場合は再取得しない。タイル全体（約232MB）は読まない。

    Args:
        signed_url (str): 署名済みの COG URL。
        bounds (tuple[float, float, float, float]): ROI の BBOX（EPSG:4326）。
        cache_path (Path): 保存先パス。

    Returns:
        Path: 保存したファイルのパス。
    """
    if cache_path.exists():
        logger.info("キャッシュ済みのサブセットを使います: %s", cache_path)
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(f"/vsicurl/{signed_url}") as source:
        window = padded_window(
            bounds=bounds,
            source_crs=source.crs,
            source_transform=source.transform,
            source_width=source.width,
            source_height=source.height,
        )
        logger.info(
            "COG から window を読み出します: %d x %d 画素（タイル全体 %d x %d）",
            window.width,
            window.height,
            source.width,
            source.height,
        )
        subset = source.read(1, window=window)
        profile = source.profile.copy()
        profile.update(
            driver="GTiff",
            count=1,
            width=window.width,
            height=window.height,
            transform=source.window_transform(window),
            nodata=OUTPUT_NODATA,
        )

    # 途中で失敗した不完全なキャッシュを残さないよう一時ファイルへ書く
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".part")
    try:
        with rasterio.open(temporary_path, "w", **profile) as destination:
            destination.write(subset, 1)
        temporary_path.replace(cache_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    logger.info("サブセットを保存しました: %s", cache_path)
    return cache_path


def reproject_to_wgs84(subset_path: Path, output_path: Path) -> Path:
    """ネイティブ CRS のサブセットを EPSG:4326 へ最近傍で再投影する。

    土地被覆はカテゴリ値のため、線形補間は使わず最近傍のみを使う。
    解像度は `calculate_default_transform` に委ね、ネイティブの 10m 相当を保つ。

    Args:
        subset_path (Path): 入力（ネイティブ CRS）の GeoTIFF パス。
        output_path (Path): 出力（EPSG:4326）の GeoTIFF パス。

    Returns:
        Path: 出力パス。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(subset_path) as source:
        transform, width, height = calculate_default_transform(
            source.crs, WGS84_CRS, source.width, source.height, *source.bounds
        )
        profile = source.profile.copy()
        profile.update(
            crs=WGS84_CRS,
            transform=transform,
            width=width,
            height=height,
            nodata=OUTPUT_NODATA,
        )
        with rasterio.open(output_path, "w", **profile) as destination:
            reproject(
                source=rasterio.band(source, 1),
                destination=rasterio.band(destination, 1),
                src_transform=source.transform,
                src_crs=source.crs,
                dst_transform=transform,
                dst_crs=WGS84_CRS,
                src_nodata=OUTPUT_NODATA,
                dst_nodata=OUTPUT_NODATA,
                resampling=Resampling.nearest,
            )
    return output_path


def clip_to_roi(raster_path: Path, roi_gdf: gpd.GeoDataFrame, output_path: Path) -> dict[str, Any]:
    """ラスタを ROI ポリゴンでクリップして GeoTIFF に保存する。

    Args:
        raster_path (Path): 入力 GeoTIFF パス。
        roi_gdf (gpd.GeoDataFrame): ROI（EPSG:4326）。
        output_path (Path): 出力 GeoTIFF パス。

    Returns:
        dict[str, Any]: 出力ラスタの諸元（CRS・解像度・bounds・画素数）。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(raster_path) as source:
        roi_in_source_crs = roi_gdf.to_crs(source.crs)
        clipped_array, clipped_transform = mask(
            source,
            shapes=[geometry.__geo_interface__ for geometry in roi_in_source_crs.geometry],
            crop=True,
            indexes=[1],
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
    nodata（0）で埋まる。この余白を「欠測」と数えると有効カバレッジを ROI 全体と
    取り違えるため、`roi_mask` で ROI 内外を分けて集計する。有効画素率の分母は
    **ROI 内の画素数** であり、ラスタ全体の画素数ではない。

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
    item: dict[str, Any],
    roi_path: Path,
    roi_bounds: tuple[float, float, float, float],
    raster_profile: dict[str, Any],
    class_distribution: dict[str, Any],
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    署名済み URL は有効期限つきのため記録しない（期限切れの URL を出典として残さないため）。

    Args:
        year (int): 取得対象年。
        item (dict[str, Any]): 使用した STAC アイテム。
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
    properties = item.get("properties", {})
    return {
        "dataset": DATASET_NAME,
        "stac_collection": STAC_COLLECTION_ID,
        "stac_item_id": item.get("id"),
        "source": STAC_COLLECTION_URL,
        "asset_href": item.get("assets", {}).get(DATA_ASSET_KEY, {}).get("href"),
        "asset_note": (
            "アセットの Blob URL は直アクセスできない（HTTP 409）。"
            "Planetary Computer の SAS 署名エンドポイントで署名してから読み取る。"
            "署名済み URL は有効期限つきのため記録しない。"
        ),
        "license": "CC BY 4.0",
        "retrieved_at": retrieved_at,
        "year": year,
        "item_start_datetime": properties.get("start_datetime"),
        "item_end_datetime": properties.get("end_datetime"),
        "native_crs": (f"EPSG:{properties['proj:epsg']}" if properties.get("proj:epsg") else None),
        "resampling_note": (
            "ネイティブ CRS（UTM）から EPSG:4326 への再投影は、カテゴリ値のため"
            "最近傍（nearest）で行う。線形補間は使わない。"
        ),
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
            "ROI 内の無効値（0: No Data、10: Clouds）は filled_pixels として別に集計する。"
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
    output_stem = f"esri_lulc_hanoi_{year}"
    resolved_output_path = output_path or (DEFAULT_OUTPUT_DIR / f"{output_stem}.tif")
    resolved_summary_path = summary_path or (DEFAULT_SUMMARY_DIR / f"{output_stem}_summary.json")
    return resolved_output_path, resolved_summary_path


def run(
    roi_path: Path,
    year: int,
    output_path: Path | None,
    summary_path: Path | None,
    cache_dir: Path,
    overwrite: bool,
) -> tuple[Path, Path]:
    """取得から検証・保存までの処理全体を実行する。

    Args:
        roi_path (Path): ROI の Shapefile パス。
        year (int): 取得対象年。
        output_path (Path | None): 出力 GeoTIFF パス。
        summary_path (Path | None): サマリー JSON パス。
        cache_dir (Path): サブセットのキャッシュ先ディレクトリ。
        overwrite (bool): 既存出力を上書きするか。

    Returns:
        tuple[Path, Path]: (出力 GeoTIFF パス, サマリー JSON パス)。

    Raises:
        FileExistsError: 出力ファイルが既に存在し overwrite が False の場合。
        RuntimeError: STAC アイテムに data アセットが無い場合。
    """
    resolved_output_path, resolved_summary_path = resolve_output_paths(
        year=year, output_path=output_path, summary_path=summary_path
    )
    # GeoTIFF とサマリーJSONは対で更新するため、どちらか一方でも既存なら止める
    for existing_path in (resolved_output_path, resolved_summary_path):
        if existing_path.exists() and not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します: {existing_path}。"
                "上書きする場合は --overwrite を指定してください。"
            )

    roi_gdf, _ = load_roi_geometry(roi_path)
    roi_bounds = tuple(float(value) for value in roi_gdf.total_bounds)
    logger.info("ROI BBOX: %s", roi_bounds)

    item = search_annual_item(year=year, bounds=roi_bounds)
    logger.info("STAC アイテムを特定しました: %s", item.get("id"))

    assets = item.get("assets", {})
    if DATA_ASSET_KEY not in assets:
        raise RuntimeError(
            f"STAC アイテムに {DATA_ASSET_KEY!r} アセットがありません: {sorted(assets)}"
        )
    signed_url = sign_asset_href(assets[DATA_ASSET_KEY]["href"])

    cache_path = cache_dir / f"{item['id']}_native_subset.tif"
    subset_path = fetch_native_subset(
        signed_url=signed_url, bounds=roi_bounds, cache_path=cache_path
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    # 再投影の中間生成物はキャッシュ側へ置き、data/gis の成果物は ROI クリップ済みのみとする
    reprojected_path = cache_path.with_name(f"{cache_path.stem}_wgs84.tif")
    reproject_to_wgs84(subset_path=subset_path, output_path=reprojected_path)
    raster_profile = clip_to_roi(
        raster_path=reprojected_path, roi_gdf=roi_gdf, output_path=resolved_output_path
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
        item=item,
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
    if class_distribution["unknown_class_values"]:
        # 分類体系にない値は、アセットの取り違えなど読み違いの一次シグナルになる
        logger.warning(
            "分類体系（9クラス）にないクラス値を検出しました: %s。取得元データを確認してください。",
            class_distribution["unknown_class_values"],
        )
    for class_entry in class_distribution["classes"]:
        logger.info(
            "  %3d %-20s %10d 画素 (%.2f%%)",
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
        overwrite=args.overwrite,
    )
    print(f"GeoTIFF を保存しました: {output_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
