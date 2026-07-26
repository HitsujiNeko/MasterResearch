"""WorldPop（居住人口）と LandScan Global（実効人口）の Hanoi ROI での値の違いを評価する。

入力は `src/preprocessing/fetch_population_hanoi.py` が出力した 2 バンド GeoTIFF
（第1バンド: 人口カウント、第2バンド: 人口密度）である。

比較設計:
- **解像度が約 10 倍違う**（WorldPop 約 92.77m / LandScan 約 927.66m）ため、粗い側の
  LandScan グリッドを基準グリッドとし、WorldPop のカウントを合計集約して突き合わせる。
  人口カウントは合計保存量なので、平均や最近傍ではなく合計で集約する。
- 集約は「WorldPop 画素の中心が入る LandScan セルへ全量を足す」方式とする。各画素が
  必ず 1 セルにだけ寄与するため、**ROI 内の総人口が集約の前後で厳密に保存される**。
  代償として、セル境界をまたぐ画素は面積按分されない（近似である）。
- **年の違いと人口概念の違いを混同しない**ため、同年（2020年）同士の比較を主指標とし、
  Landsat 観測年に対応する LandScan 2023 は参考として並べる。

注意: 両者は概念が異なる（居住人口＝夜間人口 vs 実効人口＝昼間の人口移動を考慮）ため、
差分は「どちらが正しいか」ではなく「何を測っているかの違い」として解釈する。
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from scipy import stats

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT
from src.common.paths import prepare_output_path, resolve_existing_path, to_project_relative_string
from src.common.raster_grid import compute_cell_area_km2, compute_density_array
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary

DEFAULT_POPULATION_DIR = PROJECT_ROOT / "data" / "gis" / "population"
DEFAULT_WORLDPOP_PATH = DEFAULT_POPULATION_DIR / "worldpop" / "worldpop_hanoi_2020.tif"
DEFAULT_LANDSCAN_BASE_PATH = DEFAULT_POPULATION_DIR / "landscan" / "landscan_hanoi_2020.tif"
DEFAULT_LANDSCAN_RECENT_PATH = DEFAULT_POPULATION_DIR / "landscan" / "landscan_hanoi_2023.tif"
DEFAULT_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "output"
    / "open_gis"
    / "population_worldpop_landscan_hanoi_2020_summary.json"
)

# 取得スクリプトと揃えた無効値・バンド番号
NODATA = -9999.0
COUNT_BAND = 1
DENSITY_BAND = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="WorldPop と LandScan Global の Hanoi ROI での値の違いを評価する。"
    )
    parser.add_argument(
        "--worldpop-path",
        type=Path,
        default=DEFAULT_WORLDPOP_PATH,
        help="WorldPop の 2 バンド GeoTIFF パス。",
    )
    parser.add_argument(
        "--landscan-base-path",
        type=Path,
        default=DEFAULT_LANDSCAN_BASE_PATH,
        help="WorldPop と同年の LandScan GeoTIFF パス（主比較の対象）。",
    )
    parser.add_argument(
        "--landscan-recent-path",
        type=Path,
        default=DEFAULT_LANDSCAN_RECENT_PATH,
        help="Landsat 観測年に対応する LandScan GeoTIFF パス（参考値）。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="比較サマリー JSON の出力パス。",
    )
    return parser.parse_args()


def aggregate_counts_to_reference_grid(
    source_counts: np.ndarray,
    source_transform: Any,
    reference_transform: Any,
    reference_shape: tuple[int, int],
    nodata: float = NODATA,
) -> tuple[np.ndarray, np.ndarray]:
    """細かいグリッドのカウントを、粗い基準グリッドへ合計集約する。

    各ソース画素の中心が入る基準セルへ、その画素のカウントを全量加算する。
    1 画素が必ず 1 セルにのみ寄与するため、基準グリッド内に収まる限り総和は保存される。

    Args:
        source_counts: ソースのカウント配列（nodata を含みうる）。
        source_transform: ソースのアフィン変換。
        reference_transform: 基準グリッドのアフィン変換。
        reference_shape: 基準グリッドの (行数, 列数)。
        nodata: ソースの無効値。

    Returns:
        tuple[np.ndarray, np.ndarray]:
            (基準グリッド上の合計カウント, 各基準セルへ寄与した有効ソース画素数)。

    Raises:
        ValueError: ソース配列が 2 次元でない場合。
    """
    if source_counts.ndim != 2:
        raise ValueError(f"ソース配列は 2 次元である必要があります: shape={source_counts.shape}")

    reference_height, reference_width = reference_shape
    source_height, source_width = source_counts.shape

    # ソース画素の中心座標を求める（行・列それぞれ 1 次元で足りる）
    row_indices = np.arange(source_height)
    column_indices = np.arange(source_width)
    center_latitudes = source_transform.f + source_transform.e * (row_indices + 0.5)
    center_longitudes = source_transform.c + source_transform.a * (column_indices + 0.5)

    # 基準グリッドの行・列番号へ写す（floor で「どのセルに入るか」を決める）
    reference_rows = np.floor(
        (center_latitudes - reference_transform.f) / reference_transform.e
    ).astype(np.int64)
    reference_columns = np.floor(
        (center_longitudes - reference_transform.c) / reference_transform.a
    ).astype(np.int64)

    row_grid, column_grid = np.meshgrid(reference_rows, reference_columns, indexing="ij")
    valid_mask = (
        (source_counts != nodata)
        & (row_grid >= 0)
        & (row_grid < reference_height)
        & (column_grid >= 0)
        & (column_grid < reference_width)
    )

    aggregated_counts = np.zeros(reference_shape, dtype=np.float64)
    contributing_pixels = np.zeros(reference_shape, dtype=np.int64)
    np.add.at(
        aggregated_counts,
        (row_grid[valid_mask], column_grid[valid_mask]),
        source_counts[valid_mask].astype(np.float64),
    )
    np.add.at(contributing_pixels, (row_grid[valid_mask], column_grid[valid_mask]), 1)
    return aggregated_counts, contributing_pixels


def build_paired_statistics(
    reference_values: np.ndarray,
    comparison_values: np.ndarray,
) -> dict[str, Any]:
    """同一セル上の 2 系列の一致度統計を求める。

    Args:
        reference_values: 基準側の 1 次元配列。
        comparison_values: 比較側の 1 次元配列（同じ長さ）。

    Returns:
        dict[str, Any]: 相関・誤差・バイアスの統計。

    Raises:
        ValueError: 2 系列の長さが異なる場合。
    """
    if reference_values.shape != comparison_values.shape:
        raise ValueError(
            f"2 系列の要素数が一致しません: {reference_values.shape} vs {comparison_values.shape}"
        )
    if reference_values.size == 0:
        return {"cell_count": 0}

    differences = comparison_values - reference_values
    pearson = stats.pearsonr(reference_values, comparison_values)
    spearman = stats.spearmanr(reference_values, comparison_values)
    return {
        "cell_count": int(reference_values.size),
        "pearson_r": float(pearson.statistic),
        "spearman_rho": float(spearman.statistic),
        "mean_absolute_error": float(np.mean(np.abs(differences))),
        "root_mean_squared_error": float(np.sqrt(np.mean(differences**2))),
        "mean_bias": float(np.mean(differences)),
        "median_bias": float(np.median(differences)),
    }


def load_population_raster(raster_path: Path) -> dict[str, Any]:
    """人口ラスタ（カウント・密度の 2 バンド）を読み込む。

    Args:
        raster_path: 入力 GeoTIFF パス。

    Returns:
        dict[str, Any]: 配列・変換・CRS・形状を含む辞書。

    Raises:
        ValueError: バンド数が 2 未満の場合。
    """
    with rasterio.open(raster_path) as source:
        if source.count < 2:
            raise ValueError(
                "カウントと密度の 2 バンドが必要です"
                f"（{raster_path.name} のバンド数: {source.count}）。"
            )
        return {
            "path": raster_path,
            "counts": source.read(COUNT_BAND),
            "densities": source.read(DENSITY_BAND),
            "transform": source.transform,
            "crs": source.crs,
            "shape": (int(source.height), int(source.width)),
            "resolution": [float(source.res[0]), float(source.res[1])],
        }


def build_roi_mask(raster: dict[str, Any], roi_gdf: gpd.GeoDataFrame) -> np.ndarray:
    """ラスタ格子上で ROI 内を示すマスクを作る。

    Args:
        raster: `load_population_raster` の戻り値。
        roi_gdf: ROI。

    Returns:
        np.ndarray: ROI 内を True とする真偽値配列。
    """
    roi_in_raster_crs = roi_gdf.to_crs(raster["crs"])
    return geometry_mask(
        geometries=[geometry.__geo_interface__ for geometry in roi_in_raster_crs.geometry],
        out_shape=raster["shape"],
        transform=raster["transform"],
        invert=True,
    )


def summarize_dataset(raster: dict[str, Any], roi_mask: np.ndarray) -> dict[str, Any]:
    """1 データセットの ROI 内の総人口・平均密度をまとめる。

    Args:
        raster: `load_population_raster` の戻り値。
        roi_mask: ROI 内マスク。

    Returns:
        dict[str, Any]: 総人口・有効面積・平均密度。
    """
    valid_mask = roi_mask & (raster["counts"] != NODATA)
    cell_area_km2 = compute_cell_area_km2(raster["transform"], *raster["shape"])
    broadcast_area = np.broadcast_to(cell_area_km2, raster["shape"])
    total_area_km2 = float(np.sum(broadcast_area[valid_mask]))
    total_population = float(np.sum(raster["counts"][valid_mask]))
    return {
        "path": to_project_relative_string(raster["path"]),
        "resolution_deg": raster["resolution"],
        "valid_cells": int(np.count_nonzero(valid_mask)),
        "roi_cells": int(np.count_nonzero(roi_mask)),
        "total_population": total_population,
        "total_area_km2": total_area_km2,
        "mean_density_per_km2": (total_population / total_area_km2 if total_area_km2 > 0 else None),
    }


def compare_on_reference_grid(
    worldpop: dict[str, Any],
    landscan: dict[str, Any],
    roi_mask: np.ndarray,
) -> dict[str, Any]:
    """LandScan グリッド上で WorldPop と LandScan を突き合わせる。

    Args:
        worldpop: WorldPop ラスタ。
        landscan: LandScan ラスタ（基準グリッド）。
        roi_mask: LandScan グリッド上の ROI マスク。

    Returns:
        dict[str, Any]: 集約結果と一致度統計。
    """
    aggregated_counts, contributing_pixels = aggregate_counts_to_reference_grid(
        source_counts=worldpop["counts"],
        source_transform=worldpop["transform"],
        reference_transform=landscan["transform"],
        reference_shape=landscan["shape"],
    )

    # WorldPop 側に有効画素が 1 つも無いセル（ROI 外周・水域のみ等）は比較対象から外す
    comparable_mask = roi_mask & (contributing_pixels > 0) & (landscan["counts"] != NODATA)
    landscan_counts = landscan["counts"][comparable_mask].astype(np.float64)
    worldpop_counts = aggregated_counts[comparable_mask]

    cell_area_km2 = compute_cell_area_km2(landscan["transform"], *landscan["shape"])
    aggregated_densities = compute_density_array(
        aggregated_counts.astype(np.float32), cell_area_km2, NODATA
    )
    landscan_densities = landscan["densities"][comparable_mask].astype(np.float64)
    worldpop_densities = aggregated_densities[comparable_mask].astype(np.float64)

    total_worldpop_in_roi = float(np.sum(aggregated_counts[roi_mask & (contributing_pixels > 0)]))
    return {
        "aggregation_method": (
            "WorldPop 画素の中心が入る LandScan セルへカウントを全量加算する（合計集約）。"
            "1 画素は 1 セルにのみ寄与するため総人口は保存されるが、セル境界をまたぐ画素の"
            "面積按分は行わない近似である。"
        ),
        "comparable_cells": int(np.count_nonzero(comparable_mask)),
        "roi_cells": int(np.count_nonzero(roi_mask)),
        "cells_without_worldpop_pixels": int(
            np.count_nonzero(roi_mask & (contributing_pixels == 0))
        ),
        "contributing_pixels_per_cell": {
            "min": int(np.min(contributing_pixels[comparable_mask])),
            "max": int(np.max(contributing_pixels[comparable_mask])),
            "median": float(np.median(contributing_pixels[comparable_mask])),
        },
        "total_population_on_reference_grid": {
            "worldpop": total_worldpop_in_roi,
            "landscan": float(
                np.sum(landscan["counts"][roi_mask & (landscan["counts"] != NODATA)])
            ),
        },
        "count_agreement": build_paired_statistics(landscan_counts, worldpop_counts),
        "density_agreement": build_paired_statistics(landscan_densities, worldpop_densities),
    }


def build_summary(
    worldpop_stats: dict[str, Any],
    landscan_base_stats: dict[str, Any],
    landscan_recent_stats: dict[str, Any],
    comparison: dict[str, Any],
    roi_path: Path,
    summary_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    """比較サマリーの辞書を組み立てる。

    Args:
        worldpop_stats: WorldPop の ROI 内統計。
        landscan_base_stats: 同年 LandScan の ROI 内統計。
        landscan_recent_stats: Landsat 観測年 LandScan の ROI 内統計。
        comparison: 基準グリッド上の比較結果。
        roi_path: ROI ファイルパス。
        summary_path: サマリー JSON パス。
        generated_at: 生成日時（ISO8601）。

    Returns:
        dict[str, Any]: サマリー辞書。
    """
    population_ratio = (
        worldpop_stats["total_population"] / landscan_base_stats["total_population"]
        if landscan_base_stats["total_population"] > 0
        else None
    )
    return {
        "comparison": "WorldPop（居住人口）vs LandScan Global（実効人口）",
        "generated_at": generated_at,
        "roi_path": to_project_relative_string(roi_path),
        "reference_grid": {
            "source": "LandScan Global",
            "reason": (
                "解像度が約 10 倍違うため、粗い側を基準グリッドとし細かい側を合計集約する。"
                "細かい側へ内挿するとカウントの総和が保存されない。"
            ),
        },
        "datasets": {
            "worldpop_2020": worldpop_stats,
            "landscan_2020": landscan_base_stats,
            "landscan_2023": landscan_recent_stats,
        },
        "same_year_comparison": {
            "year": 2020,
            "note": (
                "年の違いと人口概念の違いを混同しないため、同年同士を主指標とする。"
                "LandScan 2023 は Landsat 観測年に対応する参考値である。"
            ),
            "worldpop_to_landscan_population_ratio": population_ratio,
            **comparison,
        },
        "interpretation_note": (
            "WorldPop は居住人口（夜間人口）、LandScan は実効人口（昼間の人口移動を考慮）を"
            "推計しており、測っている対象が異なる。差分は精度の優劣ではなく概念差として"
            "解釈する。また WorldPop は水域等をマスクするため有効面積が LandScan より小さく、"
            "面積あたりの平均密度の比較には有効面積の違いを考慮する必要がある。"
        ),
        "outputs": {"summary": to_project_relative_string(summary_path)},
    }


def run(
    worldpop_path: Path,
    landscan_base_path: Path,
    landscan_recent_path: Path,
    roi_path: Path,
    summary_path: Path,
) -> Path:
    """比較処理全体を実行する。

    Args:
        worldpop_path: WorldPop の GeoTIFF パス。
        landscan_base_path: 同年 LandScan の GeoTIFF パス。
        landscan_recent_path: Landsat 観測年 LandScan の GeoTIFF パス。
        roi_path: ROI の Shapefile パス。
        summary_path: 比較サマリー JSON の出力パス。

    Returns:
        Path: 出力したサマリー JSON パス。
    """
    roi_gdf, _ = load_roi_geometry(resolve_existing_path(roi_path))

    worldpop = load_population_raster(resolve_existing_path(worldpop_path))
    landscan_base = load_population_raster(resolve_existing_path(landscan_base_path))
    landscan_recent = load_population_raster(resolve_existing_path(landscan_recent_path))

    worldpop_mask = build_roi_mask(worldpop, roi_gdf)
    landscan_base_mask = build_roi_mask(landscan_base, roi_gdf)
    landscan_recent_mask = build_roi_mask(landscan_recent, roi_gdf)

    worldpop_stats = summarize_dataset(worldpop, worldpop_mask)
    landscan_base_stats = summarize_dataset(landscan_base, landscan_base_mask)
    landscan_recent_stats = summarize_dataset(landscan_recent, landscan_recent_mask)

    comparison = compare_on_reference_grid(worldpop, landscan_base, landscan_base_mask)

    resolved_summary_path = prepare_output_path(summary_path)
    summary = build_summary(
        worldpop_stats=worldpop_stats,
        landscan_base_stats=landscan_base_stats,
        landscan_recent_stats=landscan_recent_stats,
        comparison=comparison,
        roi_path=roi_path,
        summary_path=resolved_summary_path,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    save_summary(summary, resolved_summary_path)

    logger.info(
        "ROI 内総人口: WorldPop 2020 = %.0f 人 / LandScan 2020 = %.0f 人 / LandScan 2023 = %.0f 人",
        worldpop_stats["total_population"],
        landscan_base_stats["total_population"],
        landscan_recent_stats["total_population"],
    )
    logger.info(
        "有効面積: WorldPop = %.2f km² / LandScan = %.2f km²（WorldPop は水域等をマスクする）",
        worldpop_stats["total_area_km2"],
        landscan_base_stats["total_area_km2"],
    )
    count_agreement = comparison["count_agreement"]
    logger.info(
        "LandScan グリッド %d セルでの一致度: Pearson r = %.4f / Spearman ρ = %.4f",
        count_agreement["cell_count"],
        count_agreement["pearson_r"],
        count_agreement["spearman_rho"],
    )
    logger.info(
        "セルあたり人口の差（WorldPop − LandScan）: 平均 %.1f 人 / 中央値 %.1f 人 / RMSE %.1f 人",
        count_agreement["mean_bias"],
        count_agreement["median_bias"],
        count_agreement["root_mean_squared_error"],
    )
    return resolved_summary_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    summary_path = run(
        worldpop_path=args.worldpop_path,
        landscan_base_path=args.landscan_base_path,
        landscan_recent_path=args.landscan_recent_path,
        roi_path=args.roi_path,
        summary_path=args.summary_path,
    )
    print(f"比較サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
