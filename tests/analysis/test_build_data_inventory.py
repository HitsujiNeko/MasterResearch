"""src/analysis/build_data_inventory.py（データインベントリ生成）のテスト。

PROJECT_ROOT をテスト用の一時ディレクトリに差し替え、実データに依存しない
スモークテストとして検証する。
"""

from __future__ import annotations

import json
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


def test_inspect_file_returns_metadata_for_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """単一ベクタファイルのメタデータ辞書を返す。"""
    monkeypatch.setattr(inv, "PROJECT_ROOT", tmp_path)
    vector = tmp_path / "data" / "gis" / "boundaries" / "roi.gpkg"
    _write_vector(vector)

    entry = inv.inspect_file(vector)

    assert entry is not None
    assert entry["kind"] == "vector"
    assert entry["crs"] == "EPSG:4326"
    assert entry["layers"][0]["feature_count"] == 1
    assert entry["path"].startswith("data/gis/")


def test_inspect_file_returns_none_for_unknown_suffix(tmp_path: Path) -> None:
    """対象外の拡張子は None を返す。"""
    other = tmp_path / "notes.txt"
    other.write_text("memo")
    assert inv.inspect_file(other) is None


def test_main_single_file_prints_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--path 指定時は単一ファイルのメタデータを JSON で標準出力し 0 を返す。"""
    monkeypatch.setattr(inv, "PROJECT_ROOT", tmp_path)
    vector = tmp_path / "data" / "gis" / "boundaries" / "roi.gpkg"
    _write_vector(vector)

    exit_code = inv.main(["--path", str(vector)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "vector"
    assert payload["layers"][0]["feature_count"] == 1
    # 単一ファイルモードではインベントリJSONを生成しない
    assert not (tmp_path / "data" / "output" / "data_inventory.json").exists()


def test_main_single_file_missing_returns_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """存在しないファイルを指定した場合は終了コード2を返す。"""
    exit_code = inv.main(["--path", str(tmp_path / "no_such_file.gpkg")])
    assert exit_code == 2
    assert "存在しません" in capsys.readouterr().err


def test_main_single_file_unknown_suffix_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """対象外拡張子を指定した場合は終了コード1を返す。"""
    other = tmp_path / "notes.txt"
    other.write_text("memo")
    exit_code = inv.main(["--path", str(other)])
    assert exit_code == 1
    assert "対象外" in capsys.readouterr().err
