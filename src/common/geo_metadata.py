"""空間データ（ラスタ・ベクタ）のメタデータ読み取りを集約するモジュール。

`src/analysis/analyze_spatial_extents.py`（空間範囲レポート）と
`src/analysis/build_data_inventory.py`（データインベントリ生成）の双方で
必要になった「fiona + rasterio でメタデータのみを読む」処理をここへ集約する。

方針:
    - 現環境では GeoPandas / pyogrio が GDAL data を検出できないケースがあるため、
      **fiona + rasterio** のみを用いる。
    - ベクタは全地物を読み込まず、レイヤ単位のメタデータ（bounds・地物数・スキーマ）を取得する。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
import rasterio
from pyproj import Transformer


@dataclass(frozen=True)
class BBox:
    """バウンディングボックス（座標系は文脈に依存）。

    Attributes:
        minx: 最小X座標（または経度）。
        miny: 最小Y座標（または緯度）。
        maxx: 最大X座標（または経度）。
        maxy: 最大Y座標（または緯度）。
    """

    minx: float
    miny: float
    maxx: float
    maxy: float

    def to_list(self) -> list[float]:
        """リスト形式へ変換する。

        Returns:
            ``[minx, miny, maxx, maxy]`` の順のリスト。
        """
        return [self.minx, self.miny, self.maxx, self.maxy]

    def to_tuple(self) -> tuple[float, float, float, float]:
        """タプル形式へ変換する（Fionaのbbox引数などで使用）。

        Returns:
            ``(minx, miny, maxx, maxy)`` の順のタプル。
        """
        return (self.minx, self.miny, self.maxx, self.maxy)

    def union(self, other: "BBox") -> "BBox":
        """別のBBoxとの和（両方を包含する最小のBBox）を返す。

        Args:
            other: 統合対象のBBox。
        Returns:
            両方を包含する最小のBBox。
        """
        return BBox(
            minx=min(self.minx, other.minx),
            miny=min(self.miny, other.miny),
            maxx=max(self.maxx, other.maxx),
            maxy=max(self.maxy, other.maxy),
        )


def bbox_from_bounds(bounds: tuple[float, float, float, float]) -> BBox:
    """境界タプルからBBoxを生成する。

    Args:
        bounds: ``(minx, miny, maxx, maxy)`` の順のタプル。
    Returns:
        生成したBBox。
    """
    minx, miny, maxx, maxy = bounds
    return BBox(float(minx), float(miny), float(maxx), float(maxy))


def transform_bbox(bbox: BBox, transformer: Transformer) -> BBox:
    """BBoxを別CRSへ変換する。

    4隅を変換し、その min/max で新しいBBoxを構成する。

    Args:
        bbox: 変換元のBBox。
        transformer: 変換に用いる pyproj Transformer（always_xy=True 前提）。
    Returns:
        変換後のBBox。
    """
    corners = [
        (bbox.minx, bbox.miny),
        (bbox.minx, bbox.maxy),
        (bbox.maxx, bbox.miny),
        (bbox.maxx, bbox.maxy),
    ]
    x_coords, y_coords = zip(*[transformer.transform(x, y) for x, y in corners])
    return BBox(min(x_coords), min(y_coords), max(x_coords), max(y_coords))


def read_vector_metadata(vector_path: Path) -> dict[str, Any]:
    """ベクタ（GPKG/SHP等）のレイヤごとメタデータを取得する。

    全地物は読み込まず、レイヤ単位の bounds・地物数・ジオメトリ種別・属性スキーマ・
    CRS を取得する。統合 bounds（全レイヤの union）も併せて返す。

    Args:
        vector_path: 対象ベクタファイルのパス。
    Returns:
        以下のキーを持つ辞書。
            layers: レイヤごとの情報リスト
                （layer, geometry_type, feature_count, bbox, fields）。
                fields は 属性名 -> 型文字列 の辞書（fiona スキーマ由来）。
            crs: 先頭レイヤのCRS文字列（取得できない場合は None）
            bbox_union: 全レイヤを包含するBBox（[minx, miny, maxx, maxy]、無い場合 None）
    """
    layers = fiona.listlayers(vector_path)
    layer_info: list[dict[str, Any]] = []
    union_bbox: BBox | None = None
    crs_str: str | None = None

    for layer in layers:
        with fiona.open(vector_path, layer=layer) as src:
            if crs_str is None and src.crs is not None:
                crs_str = src.crs.to_string()

            layer_bbox = bbox_from_bounds(src.bounds)
            union_bbox = layer_bbox if union_bbox is None else union_bbox.union(layer_bbox)

            schema = src.schema or {}
            geometry_type = schema.get("geometry")
            fields = dict(schema.get("properties") or {})

            layer_info.append(
                {
                    "layer": layer,
                    "geometry_type": geometry_type,
                    "feature_count": len(src),
                    "bbox": layer_bbox.to_list(),
                    "fields": fields,
                }
            )

    return {
        "layers": layer_info,
        "crs": crs_str,
        "bbox_union": union_bbox.to_list() if union_bbox is not None else None,
    }


def read_raster_metadata(raster_path: Path) -> dict[str, Any]:
    """ラスタ（GeoTIFF等）のメタデータを取得する。

    画素値は読み込まず、CRS・bounds・解像度・バンド数・nodata・サイズを取得する。

    Args:
        raster_path: 対象ラスタファイルのパス。
    Returns:
        crs, bbox, resolution, width, height, band_count, nodata, dtype を持つ辞書。
    """
    with rasterio.open(raster_path) as src:
        bounds = src.bounds
        res = src.res
        return {
            "crs": str(src.crs) if src.crs is not None else None,
            "bbox": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "resolution": [float(res[0]), float(res[1])],
            "width": int(src.width),
            "height": int(src.height),
            "band_count": int(src.count),
            "nodata": None if src.nodata is None else float(src.nodata),
            "dtype": src.dtypes[0] if src.dtypes else None,
        }
