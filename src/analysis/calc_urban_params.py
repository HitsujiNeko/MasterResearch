"""都市構造パラメータ算出（Phase 2）

目的:
    測量GISデータ（WGS84変換済みGPKG）から、LST（30m）と整合する
    30mグリッド単位の都市構造パラメータを算出し、分析用CSVを生成する。

背景:
    - LSTはGEE算出時点でROI（行政区画）でクリップ済み。
    - 測量GIS（merge_*_wgs84.gpkg）はROIより狭い中心部の矩形範囲。
    - 一部レイヤ（例: DC/GT）にはROI外の外れ値ジオメトリが混入し得るため、
      解析範囲（中心部BBox）で先に空間フィルタする。

本スクリプトの方針:
    - 解析範囲は `merge_RG_wgs84.gpkg` のBBoxを基準にする（中心部範囲として整合）。
    - 30mグリッド作成・面積/長さ計算は **投影座標系（UTM）** で実施する。
      （WGS84経緯度のまま30mグリッドを作ると距離が一定にならないため）
    - 被覆率（建物/水域）は10mにオーバーサンプリングしてラスタ化→30mに集約（平均）する。
    - 密度（建物数）はポリゴン重心を30mセルにビニングしてカウントする。
    - 道路密度（m/セル）は10mグリッドにラインをラスタ化し、30mで合計して近似する。

入力:
    data/output/gis_wgs84/merge_RG_wgs84.gpkg  （解析範囲）
    data/output/gis_wgs84/merge_DC_wgs84.gpkg  （建物）
    data/output/gis_wgs84/merge_DH_wgs84.gpkg  （水域）
    data/output/gis_wgs84/merge_GT_wgs84.gpkg  （道路）

出力:
    data/csv/analysis/urban_params_<city_id>.csv

実行例:
    C:/Users/takum/miniconda3/envs/gis-env/python.exe src/analysis/calc_urban_params.py --city hanoi

最終更新: 2026-03-03
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import MergeAlg
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

try:
    # shapely >= 2.0
    from shapely import make_valid as _shapely_make_valid
except Exception:  # pragma: no cover
    _shapely_make_valid = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class BBox:
    """BBox（minx, miny, maxx, maxy）"""

    minx: float
    miny: float
    maxx: float
    maxy: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.minx, self.miny, self.maxx, self.maxy)


CITY_CONFIG: dict[str, dict[str, Any]] = {
    "hanoi": {
        "utm_epsg": 32648,  # UTM Zone 48N
        "rg": {
            "path": "data/output/gis_wgs84/merge_RG_wgs84.gpkg",
            "layer": "merge_RG_wgs84",
        },
        "dc": {
            "path": "data/output/gis_wgs84/merge_DC_wgs84.gpkg",
            "layer": "elements",
        },
        "dh": {
            "path": "data/output/gis_wgs84/merge_DH_wgs84.gpkg",
            "layer": "merge_DH_wgs84",
        },
        "gt": {
            "path": "data/output/gis_wgs84/merge_GT_wgs84.gpkg",
            "layer": "elements",
        },
    },
    "osaka": {
        "utm_epsg": 32653,  # UTM Zone 53N
        "rg": {
            "path": "data/output/gis_wgs84/merge_RG_wgs84.gpkg",
            "layer": "merge_RG_wgs84",
        },
        "dc": None,
        "dh": None,
        "gt": None,
    },
}


def bbox_from_layer(path: Path, layer: str) -> BBox:
    """レイヤ全体のBBoxを取得する（Fionaのboundsを利用）。"""
    with fiona.open(path, layer=layer) as src:
        minx, miny, maxx, maxy = src.bounds
    return BBox(float(minx), float(miny), float(maxx), float(maxy))


def build_grid(
    bbox_wgs84: BBox,
    utm_crs: CRS,
    coarse_res_m: float,
    fine_res_m: float,
) -> dict[str, Any]:
    """解析範囲BBoxから、投影系でfine/coarseグリッドを構築する。"""
    wgs84 = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84, utm_crs, always_xy=True)

    # BBox4隅を投影
    corners = [
        (bbox_wgs84.minx, bbox_wgs84.miny),
        (bbox_wgs84.minx, bbox_wgs84.maxy),
        (bbox_wgs84.maxx, bbox_wgs84.miny),
        (bbox_wgs84.maxx, bbox_wgs84.maxy),
    ]
    xs, ys = zip(*[to_utm.transform(x, y) for x, y in corners])
    minx_m, maxx_m = min(xs), max(xs)
    miny_m, maxy_m = min(ys), max(ys)

    # fine grid を coarse grid の整数倍にする（padding）
    fine_factor = int(round(coarse_res_m / fine_res_m))
    if fine_factor <= 0 or abs(coarse_res_m - fine_factor * fine_res_m) > 1e-6:
        raise ValueError("coarse_res_m は fine_res_m の整数倍である必要があります")

    width_f = int(math.ceil((maxx_m - minx_m) / fine_res_m))
    height_f = int(math.ceil((maxy_m - miny_m) / fine_res_m))

    # 3の倍数にパディング（coarseへ集約しやすくする）
    pad_x = (-width_f) % fine_factor
    pad_y = (-height_f) % fine_factor
    width_f += pad_x
    height_f += pad_y

    # transform: 左上基準
    transform_f = from_origin(minx_m, maxy_m, fine_res_m, fine_res_m)

    width_c = width_f // fine_factor
    height_c = height_f // fine_factor
    transform_c = from_origin(minx_m, maxy_m, coarse_res_m, coarse_res_m)

    return {
        "utm_crs": utm_crs,
        "to_utm": to_utm,
        "to_wgs84": Transformer.from_crs(utm_crs, CRS.from_epsg(4326), always_xy=True),
        "fine": {
            "res": fine_res_m,
            "factor": fine_factor,
            "width": width_f,
            "height": height_f,
            "transform": transform_f,
        },
        "coarse": {
            "res": coarse_res_m,
            "width": width_c,
            "height": height_c,
            "transform": transform_c,
        },
    }


def _iter_geoms_in_bbox(path: Path, layer: str, bbox_wgs84: BBox) -> Iterable[dict[str, Any]]:
    """bboxで空間フィルタしつつgeometryを逐次取得する。"""
    with fiona.open(path, layer=layer, bbox=bbox_wgs84.to_tuple()) as src:
        for feat in src:
            geom = feat.get("geometry")
            if geom is None:
                continue
            yield geom


def _safe_project_geometry(geom: dict[str, Any], to_utm: Transformer):
    """geometryをShapelyへ変換し、必要に応じてmake_validしてUTMへ投影する。

    注意:
        測量データ由来で空ジオメトリや不正ジオメトリが混ざることがあるため、
        例外や empty geometry をすべてスキップできるようにする。
    """
    try:
        shp = shape(geom)
    except Exception:
        return None

    if getattr(shp, "is_empty", False):
        return None

    # is_valid はGEOS依存で例外を投げることがあるため、失敗したらスキップ
    try:
        is_valid = bool(getattr(shp, "is_valid", True))
    except Exception:
        return None

    if not is_valid and _shapely_make_valid is not None:
        try:
            shp = _shapely_make_valid(shp)
        except Exception:
            return None

    if getattr(shp, "is_empty", False):
        return None

    try:
        shp_utm = shp_transform(to_utm.transform, shp)
    except Exception:
        return None

    if getattr(shp_utm, "is_empty", False):
        return None

    return shp_utm


def rasterize_mask_from_layer(
    path: Path,
    layer: str,
    bbox_wgs84: BBox,
    to_utm: Transformer,
    out_shape: tuple[int, int],
    out_transform: rasterio.Affine,
    chunk_size: int = 5000,
) -> np.ndarray:
    """ポリゴン/ラインを10mグリッド上にラスタ化して0/1マスクを作る（chunk処理）。"""
    out = np.zeros(out_shape, dtype=np.uint8)

    shapes: list[tuple[Any, int]] = []
    for geom in _iter_geoms_in_bbox(path, layer, bbox_wgs84):
        shp_utm = _safe_project_geometry(geom, to_utm)
        if shp_utm is None:
            continue
        shapes.append((shp_utm, 1))

        if len(shapes) >= chunk_size:
            rasterize(
                shapes,
                out=out,
                transform=out_transform,
                fill=0,
                default_value=1,
                dtype=np.uint8,
                merge_alg=MergeAlg.add,
                all_touched=False,
            )
            shapes.clear()

    if shapes:
        rasterize(
            shapes,
            out=out,
            transform=out_transform,
            fill=0,
            default_value=1,
            dtype=np.uint8,
            merge_alg=MergeAlg.add,
            all_touched=False,
        )

    # addで積算しているため、1以上を1に丸める
    out = (out > 0).astype(np.uint8)
    return out


def aggregate_mean(fine_mask: np.ndarray, factor: int) -> np.ndarray:
    """fine(10m)の0/1マスクを、coarse(30m)へ平均で集約する（被覆率近似）。"""
    h, w = fine_mask.shape
    h2 = h // factor
    w2 = w // factor
    reshaped = fine_mask.reshape(h2, factor, w2, factor)
    return reshaped.mean(axis=(1, 3)).astype(np.float32)


def count_centroids_per_cell(
    path: Path,
    layer: str,
    bbox_wgs84: BBox,
    to_utm: Transformer,
    coarse_transform: rasterio.Affine,
    coarse_shape: tuple[int, int],
) -> np.ndarray:
    """ポリゴン重心を30mセルにビニングしてカウント（建物密度）。"""
    out = np.zeros(coarse_shape, dtype=np.int32)

    inv = ~coarse_transform
    with fiona.open(path, layer=layer, bbox=bbox_wgs84.to_tuple()) as src:
        for feat in src:
            geom = feat.get("geometry")
            if geom is None:
                continue
            shp_utm = _safe_project_geometry(geom, to_utm)
            if shp_utm is None:
                continue
            c = shp_utm.centroid
            if getattr(c, "is_empty", False):
                continue
            col_f, row_f = inv * (c.x, c.y)
            col = int(math.floor(col_f))
            row = int(math.floor(row_f))
            if 0 <= row < coarse_shape[0] and 0 <= col < coarse_shape[1]:
                out[row, col] += 1

    return out


def approx_road_length_m(
    fine_line_mask: np.ndarray,
    fine_res_m: float,
    factor: int,
) -> np.ndarray:
    """ラインの10mラスタ化結果から、30mセルごとの道路延長（近似）を計算する。

    注意:
        10mセルにラインが乗っているか（0/1）を合計して * fine_res_m としているため、
        線の向き・セル内の通過長により誤差が出る（探索段階の近似）。
    """
    h, w = fine_line_mask.shape
    h2 = h // factor
    w2 = w // factor
    reshaped = fine_line_mask.reshape(h2, factor, w2, factor)
    touched_count = reshaped.sum(axis=(1, 3)).astype(np.float32)
    return touched_count * float(fine_res_m)


def grid_centers_wgs84(
    coarse_transform: rasterio.Affine,
    coarse_shape: tuple[int, int],
    to_wgs84: Transformer,
) -> tuple[np.ndarray, np.ndarray]:
    """coarseセル中心の経緯度配列を返す。"""
    rows, cols = coarse_shape

    # セル中心（投影座標）
    col_idx = np.arange(cols) + 0.5
    row_idx = np.arange(rows) + 0.5
    xs = coarse_transform.c + col_idx * coarse_transform.a
    ys = coarse_transform.f + row_idx * coarse_transform.e

    # mesh
    xx, yy = np.meshgrid(xs, ys)
    lon, lat = to_wgs84.transform(xx, yy)
    return lon.astype(np.float64), lat.astype(np.float64)


def main() -> None:
    parser = argparse.ArgumentParser(description="都市構造パラメータ算出（30mグリッド）")
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument("--coarse-res", type=float, default=30.0)
    parser.add_argument("--fine-res", type=float, default=10.0)
    args = parser.parse_args()

    cfg = CITY_CONFIG[args.city]
    utm_crs = CRS.from_epsg(int(cfg["utm_epsg"]))

    # 解析範囲BBox（WGS84）はRGから取得
    rg_path = PROJECT_ROOT / cfg["rg"]["path"]
    rg_layer = cfg["rg"]["layer"]
    bbox_wgs84 = bbox_from_layer(rg_path, rg_layer)
    print("解析BBox（WGS84）:", bbox_wgs84)

    grid = build_grid(bbox_wgs84, utm_crs, args.coarse_res, args.fine_res)

    fine = grid["fine"]
    coarse = grid["coarse"]
    to_utm = grid["to_utm"]
    to_wgs84 = grid["to_wgs84"]

    fine_shape = (int(fine["height"]), int(fine["width"]))
    coarse_shape = (int(coarse["height"]), int(coarse["width"]))

    print("fine grid:", fine_shape, "res=", fine["res"], "m")
    print("coarse grid:", coarse_shape, "res=", coarse["res"], "m")

    factor = int(fine["factor"])

    # DC（建物）
    dc_cfg = cfg.get("dc")
    if dc_cfg is None:
        raise ValueError(f"city={args.city} はDC設定がありません")

    dc_path = PROJECT_ROOT / dc_cfg["path"]
    dc_layer = dc_cfg["layer"]

    print("[1/4] 建物被覆率（近似）を計算中...")
    build_mask_10m = rasterize_mask_from_layer(
        dc_path,
        dc_layer,
        bbox_wgs84,
        to_utm,
        fine_shape,
        fine["transform"],
        chunk_size=4000,
    )
    build_cov_30m = aggregate_mean(build_mask_10m, factor)

    print("[2/4] 建物密度（棟/セル）を計算中...")
    build_den_30m = count_centroids_per_cell(
        dc_path,
        dc_layer,
        bbox_wgs84,
        to_utm,
        coarse["transform"],
        coarse_shape,
    ).astype(np.float32)

    # DH（水域）
    dh_cfg = cfg.get("dh")
    if dh_cfg is None:
        raise ValueError(f"city={args.city} はDH設定がありません")

    dh_path = PROJECT_ROOT / dh_cfg["path"]
    dh_layer = dh_cfg["layer"]

    print("[3/4] 水域被覆率（近似）を計算中...")
    water_mask_10m = rasterize_mask_from_layer(
        dh_path,
        dh_layer,
        bbox_wgs84,
        to_utm,
        fine_shape,
        fine["transform"],
        chunk_size=4000,
    )
    water_cov_30m = aggregate_mean(water_mask_10m, factor)

    # GT（道路）
    gt_cfg = cfg.get("gt")
    if gt_cfg is None:
        raise ValueError(f"city={args.city} はGT設定がありません")

    gt_path = PROJECT_ROOT / gt_cfg["path"]
    gt_layer = gt_cfg["layer"]

    print("[4/4] 道路延長（近似, m/セル）を計算中...")
    road_mask_10m = rasterize_mask_from_layer(
        gt_path,
        gt_layer,
        bbox_wgs84,
        to_utm,
        fine_shape,
        fine["transform"],
        chunk_size=6000,
    )
    road_len_30m = approx_road_length_m(road_mask_10m, fine["res"], factor)

    # グリッド中心の経緯度
    lon, lat = grid_centers_wgs84(coarse["transform"], coarse_shape, to_wgs84)

    df = pd.DataFrame(
        {
            "lon": lon.ravel(),
            "lat": lat.ravel(),
            "BUILD_COV_0": build_cov_30m.ravel(),
            "BUILD_DEN_0": build_den_30m.ravel(),
            "WATER_COV_0": water_cov_30m.ravel(),
            "ROAD_DEN_0": road_len_30m.ravel(),
        }
    )

    out_dir = PROJECT_ROOT / "data" / "csv" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"urban_params_{args.city}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8")

    print("出力:", out_path)
    print("行数:", len(df))
    print(df.describe().loc[["min", "mean", "max"]])


if __name__ == "__main__":
    main()
