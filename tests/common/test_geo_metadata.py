"""src/common/geo_metadata.py（空間データのメタデータ読み取り）のテスト。"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from src.common.geo_metadata import (
    BBox,
    bbox_from_bounds,
    read_raster_metadata,
    read_vector_metadata,
    transform_bbox,
)


def _write_raster(path: Path, data: np.ndarray, *, nodata: float | None = None) -> None:
    """テスト用GeoTIFFを書き出す（左上原点、画素サイズ10m）。"""
    transform = from_origin(0.0, 100.0, 10.0, 10.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:3857",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def _write_vector(path: Path, layer: str = "data") -> None:
    """テスト用GPKG（2地物のポリゴン、属性2列）を書き出す。"""
    schema = {"geometry": "Polygon", "properties": {"name": "str", "value": "int"}}
    with fiona.open(path, "w", driver="GPKG", layer=layer, crs="EPSG:4326", schema=schema) as dst:
        for i in range(2):
            dst.write(
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
                    },
                    "properties": {"name": f"f{i}", "value": i},
                }
            )


# --- BBox ---------------------------------------------------------------


def test_bbox_to_list_and_union() -> None:
    """to_list と union が期待どおりに振る舞う。"""
    a = BBox(0.0, 0.0, 1.0, 1.0)
    b = BBox(0.5, -1.0, 2.0, 0.5)
    assert a.to_list() == [0.0, 0.0, 1.0, 1.0]
    assert a.union(b).to_list() == [0.0, -1.0, 2.0, 1.0]


def test_bbox_from_bounds() -> None:
    """タプルから BBox を生成できる。"""
    bbox = bbox_from_bounds((1, 2, 3, 4))
    assert bbox.to_list() == [1.0, 2.0, 3.0, 4.0]


def test_transform_bbox_identity() -> None:
    """恒等変換ではBBoxが（数値誤差の範囲で）保存される。"""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:4326", always_xy=True)
    bbox = BBox(10.0, 20.0, 11.0, 21.0)
    result = transform_bbox(bbox, transformer)
    assert result.to_list() == pytest.approx(bbox.to_list())


# --- ラスタ -------------------------------------------------------------


def test_read_raster_metadata(tmp_path: Path) -> None:
    """ラスタのCRS・解像度・バンド数・nodata・bboxを取得できる。"""
    raster = tmp_path / "r.tif"
    _write_raster(raster, np.ones((4, 5), dtype="float32"), nodata=-9999.0)

    meta = read_raster_metadata(raster)
    assert meta["crs"] == "EPSG:3857"
    assert meta["width"] == 5
    assert meta["height"] == 4
    assert meta["band_count"] == 1
    assert meta["resolution"] == pytest.approx([10.0, 10.0])
    assert meta["nodata"] == pytest.approx(-9999.0)
    # 左上(0,100)、10m×(幅5,高さ4) → 右下(50,60)
    assert meta["bbox"] == pytest.approx([0.0, 60.0, 50.0, 100.0])


def test_read_raster_metadata_nodata_none(tmp_path: Path) -> None:
    """nodata未設定のラスタでは None が返る。"""
    raster = tmp_path / "r.tif"
    _write_raster(raster, np.ones((2, 2), dtype="float32"))
    assert read_raster_metadata(raster)["nodata"] is None


# --- ベクタ -------------------------------------------------------------


def test_read_vector_metadata(tmp_path: Path) -> None:
    """ベクタのレイヤ・地物数・属性スキーマ・CRSを取得できる。"""
    vector = tmp_path / "v.gpkg"
    _write_vector(vector, layer="data")

    meta = read_vector_metadata(vector)
    assert meta["crs"] is not None and "4326" in meta["crs"]
    assert meta["bbox_union"] == pytest.approx([0.0, 0.0, 1.0, 1.0])
    assert len(meta["layers"]) == 1
    layer = meta["layers"][0]
    assert layer["layer"] == "data"
    assert layer["geometry_type"] == "Polygon"
    assert layer["feature_count"] == 2
    # fields は 属性名 -> 型文字列 の辞書（型文字列は fiona 依存のため名前と型の前方一致で確認）
    assert set(layer["fields"]) == {"name", "value"}
    assert layer["fields"]["name"].startswith("str")
    assert layer["fields"]["value"].startswith("int")
