"""空間範囲（BBox）比較レポート生成

目的:
    - ROI（行政区画）と、測量GISデータ（merge_*_wgs84.gpkg）の空間範囲の不一致を
      数値として把握し、後続の分析（LST×都市構造パラメータ）でのマスク方針を確定する。

ポイント:
    - 現環境では GeoPandas が pyogrio 経由でGDAL dataを検出できないケースがあるため、
      **Fiona + Rasterio** のみで範囲情報を取得する。
    - ベクタは「レイヤ単位の bounds」を取得して統合する（読み込みを最小化）。

出力:
    - data/output/spatial_extent_report.json

実行:
    C:/Users/takum/miniconda3/envs/gis-env/python.exe src/analysis/analyze_spatial_extents.py

最終更新: 2026-03-03
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fiona
import rasterio


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class BBox:
    """バウンディングボックス（WGS84の経緯度を想定）"""

    minx: float
    miny: float
    maxx: float
    maxy: float

    def to_list(self) -> list[float]:
        return [self.minx, self.miny, self.maxx, self.maxy]

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            minx=min(self.minx, other.minx),
            miny=min(self.miny, other.miny),
            maxx=max(self.maxx, other.maxx),
            maxy=max(self.maxy, other.maxy),
        )


def bbox_from_fiona_bounds(bounds: tuple[float, float, float, float]) -> BBox:
    minx, miny, maxx, maxy = bounds
    return BBox(float(minx), float(miny), float(maxx), float(maxy))


def read_vector_bbox_any_layer(vector_path: Path) -> dict[str, Any]:
    """GPKG/SHP等のベクタから、レイヤごとのboundsと統合boundsを取得する。"""
    layers = fiona.listlayers(vector_path)
    layer_info: list[dict[str, Any]] = []
    union_bbox: BBox | None = None
    crs_wkt: str | None = None

    for layer in layers:
        with fiona.open(vector_path, layer=layer) as src:
            if crs_wkt is None:
                crs_wkt = src.crs_wkt

            # Fionaが提供するbounds（レイヤ全体）
            layer_bbox = bbox_from_fiona_bounds(src.bounds)
            layer_info.append(
                {
                    "layer": layer,
                    "bbox": layer_bbox.to_list(),
                }
            )
            union_bbox = layer_bbox if union_bbox is None else union_bbox.union(layer_bbox)

    if union_bbox is None:
        raise ValueError(f"レイヤが見つかりません: {vector_path}")

    return {
        "path": str(vector_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "layers": layer_info,
        "bbox_union": union_bbox.to_list(),
        "crs_wkt": crs_wkt,
    }


def read_roi_hanoi_bbox() -> dict[str, Any]:
    """ROI（hanoi_roi.shp）から 'Hà Nội' のBBoxを取得する。

    注意:
        - ROIは複数都市が同一SHPに入っている。
        - ここでは属性 `TinhThanh == 'Hà Nội'` を抽出してboundsを計算する。
    """
    roi_path = PROJECT_ROOT / "data" / "GISData" / "ROI" / "hanoi" / "hanoi_roi.shp"
    if not roi_path.exists():
        raise FileNotFoundError(f"ROIが見つかりません: {roi_path}")

    selected_bounds: BBox | None = None
    with fiona.open(roi_path) as src:
        for feat in src:
            props = feat.get("properties") or {}
            if props.get("TinhThanh") != "Hà Nội":
                continue

            geom = feat.get("geometry")
            if geom is None:
                continue

            # Fionaではgeometry毎のboundsが直接ないため、一旦shapelyは使わず
            # GeoJSON座標から簡易にmin/maxを求める。
            coords = _flatten_coords(geom.get("coordinates"))
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            feat_bbox = BBox(min(xs), min(ys), max(xs), max(ys))
            selected_bounds = feat_bbox if selected_bounds is None else selected_bounds.union(feat_bbox)

    if selected_bounds is None:
        raise ValueError("ROI内に Hà Nội が見つかりませんでした")

    return {
        "path": str(roi_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "filter": {"TinhThanh": "Hà Nội"},
        "bbox": selected_bounds.to_list(),
    }


def _flatten_coords(coords: Any) -> list[tuple[float, float]]:
    """GeoJSON coordinates を (x,y) のリストに平坦化する（Polygon/MultiPolygon対応）。"""
    out: list[tuple[float, float]] = []

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, (list, tuple)):
            if len(obj) == 2 and all(isinstance(v, (int, float)) for v in obj):
                out.append((float(obj[0]), float(obj[1])))
                return
            for item in obj:
                walk(item)

    walk(coords)
    return out


def read_lst_bbox_osaka_any() -> dict[str, Any] | None:
    """存在すれば、osakaのLST（1枚目）からBBoxを取得する（参考用）。"""
    lst_dir = PROJECT_ROOT / "data" / "output" / "LST" / "osaka"
    if not lst_dir.exists():
        return None

    tifs = sorted([p for p in lst_dir.glob("*.tif") if not p.name.endswith(".aux.xml")])
    if not tifs:
        return None

    tif_path = tifs[0]
    with rasterio.open(tif_path) as src:
        bounds = src.bounds
        crs = str(src.crs) if src.crs is not None else None

    return {
        "path": str(tif_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "bbox": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "crs": crs,
    }


def main() -> None:
    gis_dir = PROJECT_ROOT / "data" / "output" / "gis_wgs84"
    gpkg_paths = sorted(gis_dir.glob("merge_*_wgs84.gpkg"))

    report: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(PROJECT_ROOT),
        "roi_hanoi": read_roi_hanoi_bbox(),
        "gis_merge_wgs84": [],
        "lst_osaka_example": read_lst_bbox_osaka_any(),
        "notes": [
            "LSTはGEE算出時点でROI（行政区画）でクリップ済み。",
            "測量GIS（merge_*_wgs84.gpkg）はROIより狭い矩形範囲。",
            "分析対象域はGISの有効範囲内（BBoxや凸包）でLSTピクセルをマスクして定義する。",
        ],
    }

    union_bbox: BBox | None = None
    for gpkg_path in gpkg_paths:
        info = read_vector_bbox_any_layer(gpkg_path)
        report["gis_merge_wgs84"].append(info)

        bb = bbox_from_fiona_bounds(tuple(info["bbox_union"]))
        union_bbox = bb if union_bbox is None else union_bbox.union(bb)

    if union_bbox is not None:
        report["gis_bbox_union_all_layers"] = union_bbox.to_list()

    out_path = PROJECT_ROOT / "data" / "output" / "spatial_extent_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("出力:", out_path)
    print("GISファイル数:", len(gpkg_paths))


if __name__ == "__main__":
    main()
