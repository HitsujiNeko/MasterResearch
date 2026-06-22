"""io.py（入力レイヤ・ラスタの解決と読み込み）のテスト。"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params.io import (
    find_satellite_rasters,
    iter_feature_records,
    resolve_layer_name,
)

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS, _make_layer_resource

# ---------------------------------------------------------------------------
# resolve_layer_name
# ---------------------------------------------------------------------------


def test_resolve_layer_name_preferred_exists(tmp_path: Path) -> None:
    """指定レイヤが存在すればそのまま返す。"""
    gpkg = tmp_path / "test.gpkg"
    schema = {"geometry": "Point", "properties": {}}
    with fiona.open(gpkg, "w", driver="GPKG", layer="my_layer", crs=ANALYSIS_CRS, schema=schema):
        pass

    assert resolve_layer_name(gpkg, "my_layer") == "my_layer"


def test_resolve_layer_name_fallback(tmp_path: Path) -> None:
    """指定レイヤが存在しなければ最初の通常レイヤへフォールバックする。"""
    gpkg = tmp_path / "test.gpkg"
    schema = {"geometry": "Point", "properties": {}}
    with fiona.open(gpkg, "w", driver="GPKG", layer="actual", crs=ANALYSIS_CRS, schema=schema):
        pass

    assert resolve_layer_name(gpkg, "nonexistent") == "actual"


def test_resolve_layer_name_file_not_found(tmp_path: Path) -> None:
    """存在しないファイルではFileNotFoundErrorが発生する。"""
    with pytest.raises(FileNotFoundError):
        resolve_layer_name(tmp_path / "missing.gpkg", "any")


# ---------------------------------------------------------------------------
# iter_feature_records
# ---------------------------------------------------------------------------


def test_iter_feature_records_yields_features(tmp_path: Path) -> None:
    """BBox内のフィーチャが返され、geometry=Noneのフィーチャは除外される。"""
    gpkg = tmp_path / "points.gpkg"
    schema = {"geometry": "Point", "properties": {"val": "int"}}
    with fiona.open(gpkg, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema) as dst:
        dst.write(
            {"geometry": {"type": "Point", "coordinates": (10, 70)}, "properties": {"val": 1}}
        )
        dst.write(
            {"geometry": {"type": "Point", "coordinates": (50, 50)}, "properties": {"val": 2}}
        )

    resource = _make_layer_resource(gpkg, "data")
    features = list(iter_feature_records(resource, ANALYSIS_BBOX))

    assert len(features) == 2
    assert features[0]["properties"]["val"] == 1


# ---------------------------------------------------------------------------
# find_satellite_rasters
# ---------------------------------------------------------------------------


def _write_multiband_tif(
    path: Path, descriptions: tuple[str | None, ...], shape: tuple[int, int] = (4, 4)
) -> None:
    """指定バンド説明を持つマルチバンドGeoTIFFを書き出す。"""
    transform = from_origin(0, 40, 10, 10)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=len(descriptions),
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
    ) as dst:
        for i, desc in enumerate(descriptions, start=1):
            dst.write(np.ones(shape, dtype=np.float32), i)
            dst.set_band_description(i, desc)


def test_find_satellite_rasters_by_band_description(tmp_path: Path) -> None:
    """バンド説明からNDVI・NDWIを正しく検出する。"""
    tif = tmp_path / "INDICES.tif"
    _write_multiband_tif(tif, ("NDVI", "NDWI", "OTHER"))

    result = find_satellite_rasters(tif)

    assert "NDVI" in result
    assert result["NDVI"] == (tif, 1)
    assert "NDWI" in result
    assert result["NDWI"] == (tif, 2)
    assert "OTHER" not in result


def test_find_satellite_rasters_by_filename(tmp_path: Path) -> None:
    """バンド説明が無い場合、ファイル名から指標を検出しバンド1を採用する。"""
    tif = tmp_path / "hanoi_NDBI.tif"
    _write_multiband_tif(tif, (None,))

    result = find_satellite_rasters(tif)

    assert "NDBI" in result
    assert result["NDBI"] == (tif, 1)


def test_find_satellite_rasters_nonexistent_path(tmp_path: Path) -> None:
    """存在しないパスでは空辞書を返す。"""
    result = find_satellite_rasters(tmp_path / "missing")

    assert result == {}


def test_find_satellite_rasters_duplicate_raises(tmp_path: Path) -> None:
    """同じ指標を含む複数ファイルではValueErrorが発生する。"""
    subdir = tmp_path / "rasters"
    subdir.mkdir()
    _write_multiband_tif(subdir / "file1.tif", ("NDVI",))
    _write_multiband_tif(subdir / "file2.tif", ("NDVI",))

    with pytest.raises(ValueError):
        find_satellite_rasters(subdir)
