"""src/analysis/build_data_inventory.py（データインベントリ生成）のテスト。

PROJECT_ROOT をテスト用の一時ディレクトリに差し替え、実データに依存しない
スモークテストとして検証する。
"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import src.analysis.build_data_inventory as inv


def _write_raster(path: Path) -> None:
    """テスト用の小さなGeoTIFFを書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(0.0, 30.0, 10.0, 10.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
    ) as dst:
        dst.write(np.ones((3, 3), dtype="float32"), 1)


def _write_vector(path: Path) -> None:
    """テスト用の小さなGPKGを書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = {"geometry": "Point", "properties": {"id": "int"}}
    with fiona.open(path, "w", driver="GPKG", layer="pts", crs="EPSG:4326", schema=schema) as dst:
        dst.write({"geometry": {"type": "Point", "coordinates": (0, 0)}, "properties": {"id": 1}})


@pytest.fixture()
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """data/gis・data/satellite を持つ一時プロジェクトルートを構築する。"""
    _write_raster(tmp_path / "data" / "satellite" / "lst" / "lst_sample.tif")
    _write_vector(tmp_path / "data" / "gis" / "boundaries" / "roi.gpkg")
    monkeypatch.setattr(inv, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_build_inventory_collects_raster_and_vector(fake_root: Path) -> None:
    """ラスタ・ベクタの両方がメタデータ付きで収集される。"""
    inventory = inv.build_inventory()

    assert inventory["file_count"] == 2
    assert inventory["error_count"] == 0

    by_kind = {f["kind"]: f for f in inventory["files"]}
    assert set(by_kind) == {"raster", "vector"}

    raster = by_kind["raster"]
    assert raster["crs"] == "EPSG:3857"
    assert raster["band_count"] == 1
    assert raster["path"].startswith("data/satellite/")
    assert raster["size_bytes"] > 0

    vector = by_kind["vector"]
    assert vector["layers"][0]["feature_count"] == 1
    assert vector["path"].startswith("data/gis/")


def test_build_inventory_skips_aux_and_unknown(fake_root: Path) -> None:
    """.aux.xml やその他拡張子は走査対象に含めない。"""
    (fake_root / "data" / "gis" / "boundaries" / "roi.gpkg.aux.xml").write_text("x")
    (fake_root / "data" / "gis" / "notes.txt").write_text("memo")

    inventory = inv.build_inventory()
    assert inventory["file_count"] == 2  # tif + gpkg のみ


def test_build_inventory_records_error_for_broken_file(fake_root: Path) -> None:
    """壊れたラスタでも例外を送出せず error として記録する。"""
    broken = fake_root / "data" / "satellite" / "lst" / "broken.tif"
    broken.write_bytes(b"not a real geotiff")

    inventory = inv.build_inventory()
    assert inventory["error_count"] == 1
    broken_entry = next(f for f in inventory["files"] if f["path"].endswith("broken.tif"))
    assert "error" in broken_entry


def test_build_inventory_for_dir_missing_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """走査対象ディレクトリが存在しない場合は空リストを返す。"""
    monkeypatch.setattr(inv, "PROJECT_ROOT", tmp_path)
    assert inv.build_inventory_for_dir(tmp_path / "data" / "gis") == []
