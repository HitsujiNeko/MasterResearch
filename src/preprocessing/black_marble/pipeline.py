"""Black Marble の取得から検証・保存までの処理全体。

認証 → 一覧取得 → タイル取得 → GeoTIFF 変換 → ROI クリップ → 統計・サマリー保存
の順に各モジュールを呼び出す。取得済みタイルの構造確認（`run_inspection`）もここに置く。
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.common.config import PROJECT_ROOT, WGS84_CRS
from src.common.paths import prepare_output_path
from src.common.raster_area import build_target_area, clip_multiband_to_area
from src.common.raster_stats import build_multiband_pixel_statistics
from src.common.summary import save_summary
from src.preprocessing.black_marble.auth import (
    build_authorization_headers,
    resolve_earthdata_token,
)
from src.preprocessing.black_marble.conversion import (
    describe_hdf5_structure,
    write_tile_geotiff,
)
from src.preprocessing.black_marble.download import download_tile
from src.preprocessing.black_marble.listing import (
    extract_listing_entries,
    fetch_tile_listing,
    select_tile_files,
)
from src.preprocessing.black_marble.product import (
    ANNUAL_DAY_OF_YEAR,
    BAND_DEFINITIONS,
    FIRST_AVAILABLE_YEAR,
    OUTPUT_NODATA,
    PRIMARY_BAND_NAME,
    PRODUCT_NAME,
)
from src.preprocessing.black_marble.report import build_summary, log_results
from src.preprocessing.black_marble.tile_grid import resolve_black_marble_tiles

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "gis" / "nighttime_lights" / "black_marble"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"


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
        saturation_bands=[
            band.output_name for band in BAND_DEFINITIONS if band.is_saturation_target
        ],
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
