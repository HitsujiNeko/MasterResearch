"""都市構造パラメータ算出のオーケストレーションモジュール。

シナリオ（satellite_only / limited / full）とスケール（既定: 30/90/300m）
ごとに都市構造パラメータを算出し、CSVへ出力する。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import CRS

from src.common.geo_metadata import BBox

from .config import CITY_CONFIG, PROJECT_ROOT, SCENARIO_LAYER_KEYS
from .geometry import compute_polygon_coverage
from .grid import GridSpec, build_grid, grid_centers_wgs84
from .io import (
    LayerResource,
    bbox_from_layer,
    find_satellite_rasters,
    get_layer_resource,
    get_optional_layer_resource,
)
from .params import buildings, elevation, raster, roads


def parse_arguments() -> argparse.Namespace:
    """CLI引数を解釈して返す。"""
    parser = argparse.ArgumentParser(description="都市構造パラメータ算出（モジュール化版）")
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument("--scenario", default="limited", choices=list(SCENARIO_LAYER_KEYS.keys()))
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[30, 90, 300],
        help="出力するcoarseグリッド解像度（m）の一覧。",
    )
    parser.add_argument(
        "--fine-res", type=float, default=10.0, help="被覆率計算用の補助解像度（m）。"
    )
    parser.add_argument("--mask-layer-key", default="", choices=["", "roi", "rg", "cs"])
    parser.add_argument(
        "--satellite-dir",
        type=str,
        default="",
        help="衛星指標ラスタのファイルまたは格納ディレクトリ（任意）。複数観測がある場合はファイルを指定する。",
    )
    args = parser.parse_args()
    if any(scale <= 0 for scale in args.scales):
        parser.error("--scales には正の整数のみ指定してください。")
    args.scales = list(dict.fromkeys(args.scales))
    return args


def build_quality_columns(
    indicator_arrays: list[np.ndarray], grid_spec: GridSpec
) -> tuple[np.ndarray, np.ndarray]:
    """GIS由来の品質管理列（VALID_GIS_MASK, MISSING_REASON）を作成する。

    Args:
        indicator_arrays: 各GIS由来パラメータのcoarseグリッド配列のリスト。
            いずれか1つでも値が0より大きいセルを「GIS指標が有効」とみなす。
        grid_spec: 出力グリッドの仕様。

    Returns:
        VALID_GIS_MASK（有効セルなら1、そうでなければ0）と、
        MISSING_REASON（有効なら"none"、無効なら"no_gis_feature"）の組。
    """
    valid_gis_mask = np.zeros(grid_spec.coarse_shape, dtype=bool)
    for indicator_array in indicator_arrays:
        valid_gis_mask |= np.nan_to_num(indicator_array, nan=0.0) > 0

    missing_reason = np.where(valid_gis_mask, "none", "no_gis_feature")
    return valid_gis_mask.astype(np.int8), missing_reason


def build_satellite_quality(satellite_arrays: list[np.ndarray], grid_spec: GridSpec) -> np.ndarray:
    """衛星指標の品質列（VALID_SATELLITE_MASK）を作成する。

    Args:
        satellite_arrays: 各衛星由来パラメータのcoarseグリッド配列のリスト。
            いずれか1つでもNaNでないセルを「衛星指標が有効」とみなす。
        grid_spec: 出力グリッドの仕様。

    Returns:
        VALID_SATELLITE_MASK（有効セルなら1、そうでなければ0）。
    """
    valid_mask = np.zeros(grid_spec.coarse_shape, dtype=bool)
    for arr in satellite_arrays:
        valid_mask |= ~np.isnan(arr)
    return valid_mask.astype(np.int8)


def print_basic_summary(dataframe: pd.DataFrame) -> None:
    """主要列の簡易統計を標準出力する。

    Args:
        dataframe: 出力対象のデータフレーム。lon/lat・品質管理列以外の
            数値列について、最小・平均・最大値を表示する。
    """
    excluded_columns = {
        "lon",
        "lat",
        "IN_ANALYSIS_AREA",
        "VALID_GIS_MASK",
        "VALID_SATELLITE_MASK",
        "MISSING_REASON",
        "DATA_SOURCE",
        "SCENARIO",
    }
    numeric_columns = [column for column in dataframe.columns if column not in excluded_columns]

    print("出力行数:", len(dataframe))
    if numeric_columns:
        print(dataframe[numeric_columns].describe().loc[["min", "mean", "max"]])


def run_for_scale(
    scale: int,
    args: argparse.Namespace,
    scenario_cfg: dict[str, Any],
    analysis_crs: CRS,
    analysis_bbox: BBox,
    mask_resource: LayerResource,
    building_resource: LayerResource | None,
    road_resource: LayerResource | None,
    elevation_resource: LayerResource | None,
    raster_resources: dict[str, tuple[Path, int]],
) -> pd.DataFrame:
    """1スケール分の都市構造パラメータを算出し、データフレームを返す。

    建物・道路・標高・衛星指標の各 ``compute()`` を呼び出し、戻り値の列名に
    ``_{scale}`` サフィックスを付与したうえで、座標・品質管理列とともに
    1つのデータフレームへ統合する。

    Args:
        scale: coarseグリッド解像度（m）。出力列名のサフィックスにも使う。
        args: CLI引数（``fine_res`` 等を参照する）。
        scenario_cfg: シナリオ設定（``SCENARIO_LAYER_KEYS`` の1エントリ）。
        analysis_crs: 解析用投影座標系（例: EPSG:5897）。
        analysis_bbox: 解析範囲のBBox（``analysis_crs`` 上の座標）。
        mask_resource: 解析対象セルの判定に使う基準レイヤ。
        building_resource: 建物レイヤ（未指定シナリオでは ``None``）。
        road_resource: 道路レイヤ（未指定シナリオでは ``None``）。
        elevation_resource: 標高点レイヤ（未指定シナリオでは ``None``）。
        raster_resources: 衛星指標ラスタの辞書（指標名 -> (パス, バンド番号)）。

    Returns:
        ``IN_ANALYSIS_AREA == 1`` のセルのみを残したデータフレーム。
    """
    grid_spec = build_grid(analysis_bbox, analysis_crs, float(scale), args.fine_res)
    print(f"[scale={scale}m] coarse shape: {grid_spec.coarse_shape}")

    output_columns: dict[str, np.ndarray] = {}
    gis_quality_arrays: list[np.ndarray] = []
    satellite_quality_arrays: list[np.ndarray] = []

    for module, resource in (
        (buildings, building_resource),
        (roads, road_resource),
        (elevation, elevation_resource),
    ):
        for column_name, values in module.compute(resource, analysis_bbox, grid_spec).items():
            output_columns[f"{column_name}_{scale}"] = values
            gis_quality_arrays.append(values)

    if raster_resources:
        for column_name, values in raster.compute(raster_resources, grid_spec).items():
            output_columns[f"{column_name}_{scale}"] = values
            satellite_quality_arrays.append(values)

    lon, lat = grid_centers_wgs84(grid_spec)
    analysis_mask = compute_polygon_coverage(mask_resource, analysis_bbox, grid_spec) > 0
    valid_gis_mask, missing_reason = build_quality_columns(gis_quality_arrays, grid_spec)
    valid_sat_mask = build_satellite_quality(satellite_quality_arrays, grid_spec)

    output_data: dict[str, Any] = {
        "lon": lon.ravel(),
        "lat": lat.ravel(),
    }
    for column_name, values in output_columns.items():
        output_data[column_name] = values.ravel()
    output_data.update(
        {
            "IN_ANALYSIS_AREA": analysis_mask.astype(np.int8).ravel(),
            "VALID_GIS_MASK": valid_gis_mask.ravel(),
            "VALID_SATELLITE_MASK": valid_sat_mask.ravel(),
            "MISSING_REASON": missing_reason.ravel(),
            "DATA_SOURCE": str(scenario_cfg["data_source"]),
            "SCENARIO": args.scenario,
        }
    )

    output_df = pd.DataFrame(output_data)
    return output_df[output_df["IN_ANALYSIS_AREA"] == 1].copy()


def main() -> None:
    """都市構造パラメータ算出処理を実行する。

    CLI引数からシナリオ・都市・出力スケールを決定し、解析範囲レイヤ・
    建物・道路・標高・衛星指標の各レイヤを解決したうえで、``--scales``
    で指定したスケールごとに ``run_for_scale()`` を呼び出し、
    ``data/output/urban_params/urban_params_<scenario>_<city>_<scale>m.csv``
    へ結果を出力する。
    """
    args = parse_arguments()
    city_cfg = CITY_CONFIG[args.city]
    scenario_cfg = SCENARIO_LAYER_KEYS[args.scenario]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))

    mask_layer_key = args.mask_layer_key or str(scenario_cfg["default_mask"])
    mask_resource = get_layer_resource(city_cfg, mask_layer_key, analysis_crs)
    analysis_bbox = bbox_from_layer(mask_resource, analysis_crs)

    print("シナリオ:", args.scenario)
    print(
        "解析範囲レイヤ:", mask_layer_key, "->", mask_resource.path.name, mask_resource.layer_name
    )
    print("解析BBox:", analysis_bbox)

    building_resource = get_optional_layer_resource(city_cfg, scenario_cfg["buildings"])
    road_resource = get_optional_layer_resource(city_cfg, scenario_cfg["roads"])
    elevation_resource = get_optional_layer_resource(city_cfg, scenario_cfg["elevation"])

    raster_resources: dict[str, tuple[Path, int]] = {}
    if args.satellite_dir:
        satellite_path = (PROJECT_ROOT / args.satellite_dir).resolve()
        raster_resources = find_satellite_rasters(satellite_path)
        if raster_resources:
            print("衛星ラスタ検出:", ", ".join(sorted(raster_resources.keys())))
        else:
            print("衛星ラスタは検出されませんでした。GIS由来列のみを出力します。")

    out_dir = PROJECT_ROOT / "data" / "output" / "urban_params"
    out_dir.mkdir(parents=True, exist_ok=True)

    for scale in args.scales:
        output_df = run_for_scale(
            scale=scale,
            args=args,
            scenario_cfg=scenario_cfg,
            analysis_crs=analysis_crs,
            analysis_bbox=analysis_bbox,
            mask_resource=mask_resource,
            building_resource=building_resource,
            road_resource=road_resource,
            elevation_resource=elevation_resource,
            raster_resources=raster_resources,
        )

        out_path = out_dir / f"urban_params_{args.scenario}_{args.city}_{scale}m.csv"
        output_df.to_csv(out_path, index=False, encoding="utf-8")

        print("出力先:", out_path)
        print_basic_summary(output_df)


if __name__ == "__main__":
    main()
