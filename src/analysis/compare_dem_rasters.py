# 作成者: Codex
# 作成日: 2026-05-27
# 概要: 2枚のDEMを同一グリッドで比較し、統計サマリーと差分ラスタを出力する。

"""DEM比較スクリプト。

本スクリプトは、比較対象DEMを基準DEMのグリッドへ再投影し、
重複有効域のみを使って差分統計を算出する。

主な出力:
1. 比較サマリーJSON
2. 必要に応じて差分GeoTIFF
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from src.common.config import PROJECT_ROOT

DIFF_NODATA = -9999.0


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解釈する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(description="2枚のDEMを比較する。")
    parser.add_argument(
        "--base-dem-path",
        type=Path,
        required=True,
        help="比較の基準にするDEMパス。出力差分は base - target で計算する。",
    )
    parser.add_argument(
        "--target-dem-path",
        type=Path,
        required=True,
        help="基準DEMへ再投影して比較するDEMパス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        required=True,
        help="比較サマリーJSONの出力先。",
    )
    parser.add_argument(
        "--diff-path",
        type=Path,
        default=None,
        help="差分GeoTIFFの出力先。不要なら省略可能。",
    )
    parser.add_argument(
        "--resampling",
        choices=("nearest", "bilinear"),
        default="bilinear",
        help="再投影時の補間方法。",
    )
    return parser.parse_args()


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


def resolve_resampling(resampling_name: str) -> Resampling:
    """文字列指定をRasterioのResampling列挙へ変換する。

    Args:
        resampling_name (str): 補間方法名。

    Returns:
        Resampling: Rasterio用補間方法。
    """
    if resampling_name == "nearest":
        return Resampling.nearest
    return Resampling.bilinear


def ensure_parent_directory(path: Path) -> None:
    """保存先の親ディレクトリを作成する。

    Args:
        path (Path): 保存先ファイルパス。
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def read_raster_summary(raster_path: Path) -> dict[str, Any]:
    """ラスタのメタデータと基本統計を取得する。

    Args:
        raster_path (Path): 対象ラスタ。

    Returns:
        dict[str, Any]: メタデータと基本統計。
    """
    with rasterio.open(raster_path) as src:
        masked_array = src.read(1, masked=True).astype(np.float32)
        valid_values = masked_array.compressed()
        bounds = src.bounds
        summary = {
            "path": to_project_relative_string(raster_path),
            "crs": src.crs.to_string() if src.crs is not None else None,
            "resolution": [float(src.res[0]), float(src.res[1])],
            "width": int(src.width),
            "height": int(src.height),
            "bounds": {
                "minx": float(bounds.left),
                "miny": float(bounds.bottom),
                "maxx": float(bounds.right),
                "maxy": float(bounds.top),
            },
            "dtype": str(src.dtypes[0]),
            "nodata": None if src.nodata is None else float(src.nodata),
            "valid_pixel_count": int(valid_values.size),
        }
        if valid_values.size == 0:
            summary["statistics"] = None
        else:
            summary["statistics"] = {
                "min": float(valid_values.min()),
                "max": float(valid_values.max()),
                "mean": float(valid_values.mean()),
                "std": float(valid_values.std()),
            }
    return summary


def read_base_dem(base_dem_path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """基準DEMを読み込む。

    Args:
        base_dem_path (Path): 基準DEMパス。

    Returns:
        tuple[np.ndarray, dict[str, Any]]: 基準DEM配列と書き込み用プロファイル。
    """
    with rasterio.open(base_dem_path) as src:
        base_array = src.read(1, masked=True).filled(np.nan).astype(np.float32)
        profile = src.profile.copy()

    profile.update(dtype="float32", count=1, nodata=DIFF_NODATA)
    return base_array, profile


def reproject_target_to_base(
    target_dem_path: Path,
    base_profile: dict[str, Any],
    resampling: Resampling,
) -> np.ndarray:
    """比較対象DEMを基準DEMグリッドへ再投影する。

    Args:
        target_dem_path (Path): 比較対象DEM。
        base_profile (dict[str, Any]): 基準DEMのプロファイル。
        resampling (Resampling): 補間方法。

    Returns:
        np.ndarray: 基準DEMグリッドへ再投影した配列。
    """
    reprojected_array = np.full(
        (int(base_profile["height"]), int(base_profile["width"])),
        np.nan,
        dtype=np.float32,
    )

    with rasterio.open(target_dem_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=reprojected_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=base_profile["transform"],
            dst_crs=base_profile["crs"],
            dst_nodata=np.nan,
            resampling=resampling,
            init_dest_nodata=True,
        )

    return reprojected_array


def calculate_comparison_metrics(
    base_array: np.ndarray,
    target_array: np.ndarray,
) -> tuple[dict[str, Any], np.ndarray]:
    """重複有効域の差分統計を算出する。

    Args:
        base_array (np.ndarray): 基準DEM配列。
        target_array (np.ndarray): 比較対象DEM配列（基準グリッドへ再投影済み）。

    Returns:
        tuple[dict[str, Any], np.ndarray]:
            比較統計と差分配列。
    """
    overlap_mask = np.isfinite(base_array) & np.isfinite(target_array)
    diff_array = np.full(base_array.shape, np.nan, dtype=np.float32)
    diff_array[overlap_mask] = base_array[overlap_mask] - target_array[overlap_mask]

    diff_values = diff_array[overlap_mask]
    if diff_values.size == 0:
        raise ValueError("重複する有効ピクセルが存在しないため比較できません。")

    metrics = {
        "overlap_pixel_count": int(diff_values.size),
        "base_mean": float(np.nanmean(base_array[overlap_mask])),
        "target_mean": float(np.nanmean(target_array[overlap_mask])),
        "mean_difference": float(np.nanmean(diff_values)),
        "median_difference": float(np.nanmedian(diff_values)),
        "mae": float(np.nanmean(np.abs(diff_values))),
        "rmse": float(np.sqrt(np.nanmean(np.square(diff_values)))),
        "std_difference": float(np.nanstd(diff_values)),
        "min_difference": float(np.nanmin(diff_values)),
        "max_difference": float(np.nanmax(diff_values)),
        "p05_difference": float(np.nanpercentile(diff_values, 5)),
        "p95_difference": float(np.nanpercentile(diff_values, 95)),
    }

    metrics["correlation"] = calculate_safe_correlation(
        base_values=base_array[overlap_mask],
        target_values=target_array[overlap_mask],
    )

    return metrics, diff_array


def calculate_safe_correlation(
    base_values: np.ndarray,
    target_values: np.ndarray,
) -> float | None:
    """相関係数を安全に計算する。

    `np.corrcoef` は環境依存で不安定になることがあるため、
    平均・分散・共分散から手計算する。

    Args:
        base_values (np.ndarray): 基準DEMの値配列。
        target_values (np.ndarray): 比較DEMの値配列。

    Returns:
        float | None: 相関係数。計算不能な場合はNone。
    """
    if base_values.size < 2 or target_values.size < 2:
        return None

    base_float = base_values.astype(np.float64, copy=False)
    target_float = target_values.astype(np.float64, copy=False)

    base_mean = float(base_float.mean())
    target_mean = float(target_float.mean())
    base_centered = base_float - base_mean
    target_centered = target_float - target_mean

    base_std = float(np.sqrt(np.mean(np.square(base_centered))))
    target_std = float(np.sqrt(np.mean(np.square(target_centered))))
    if base_std == 0.0 or target_std == 0.0:
        return None

    covariance = float(np.mean(base_centered * target_centered))
    return covariance / (base_std * target_std)


def write_diff_raster(
    diff_array: np.ndarray,
    diff_path: Path,
    base_profile: dict[str, Any],
) -> None:
    """差分GeoTIFFを書き出す。

    Args:
        diff_array (np.ndarray): 差分配列。
        diff_path (Path): 保存先GeoTIFF。
        base_profile (dict[str, Any]): 基準DEMプロファイル。
    """
    ensure_parent_directory(diff_path)
    writable_array = np.where(np.isfinite(diff_array), diff_array, DIFF_NODATA).astype(np.float32)
    with rasterio.open(diff_path, "w", **base_profile) as dst:
        dst.write(writable_array, 1)


def write_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """比較サマリーJSONを書き出す。

    Args:
        summary (dict[str, Any]): 保存対象サマリー。
        summary_path (Path): 保存先JSON。
    """
    ensure_parent_directory(summary_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(
    base_dem_path: Path,
    target_dem_path: Path,
    summary_path: Path,
    diff_path: Path | None,
    resampling_name: str,
) -> tuple[Path, Path | None]:
    """DEM比較処理全体を実行する。

    Args:
        base_dem_path (Path): 基準DEMパス。
        target_dem_path (Path): 比較対象DEMパス。
        summary_path (Path): 比較サマリーJSONパス。
        diff_path (Path | None): 差分GeoTIFFパス。
        resampling_name (str): 補間方法名。

    Returns:
        tuple[Path, Path | None]: サマリーJSONパスと差分GeoTIFFパス。
    """
    base_array, base_profile = read_base_dem(base_dem_path)
    target_array = reproject_target_to_base(
        target_dem_path=target_dem_path,
        base_profile=base_profile,
        resampling=resolve_resampling(resampling_name),
    )
    metrics, diff_array = calculate_comparison_metrics(
        base_array=base_array,
        target_array=target_array,
    )

    if diff_path is not None:
        write_diff_raster(
            diff_array=diff_array,
            diff_path=diff_path,
            base_profile=base_profile,
        )

    summary = {
        "base_dem": read_raster_summary(base_dem_path),
        "target_dem": read_raster_summary(target_dem_path),
        "comparison": {
            "difference_definition": "base_dem - target_dem",
            "resampling": resampling_name,
            **metrics,
        },
        "diff_raster_path": None if diff_path is None else to_project_relative_string(diff_path),
    }
    write_summary(summary=summary, summary_path=summary_path)
    return summary_path, diff_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    summary_path, diff_path = run(
        base_dem_path=args.base_dem_path,
        target_dem_path=args.target_dem_path,
        summary_path=args.summary_path,
        diff_path=args.diff_path,
        resampling_name=args.resampling,
    )
    print(f"比較サマリーJSONを保存しました: {summary_path}")
    if diff_path is not None:
        print(f"差分GeoTIFFを保存しました: {diff_path}")


if __name__ == "__main__":
    main()
