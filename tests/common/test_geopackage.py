"""geopackage.py（GeoPackageの後片付け）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.common.geopackage import SIDECAR_SUFFIXES, remove_geopackage, remove_sidecar_files


def _create_geopackage_files(base_path: Path) -> None:
    """本体と全ての付随ファイルをダミーとして作成する。"""
    base_path.write_text("main", encoding="utf-8")
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{base_path}{suffix}").write_text(suffix, encoding="utf-8")


def test_remove_sidecar_files_keeps_main_file(tmp_path: Path) -> None:
    """付随ファイルだけを削除し、本体は残す。"""
    gpkg_path = tmp_path / "sample.gpkg"
    _create_geopackage_files(gpkg_path)

    remove_sidecar_files(gpkg_path)

    assert gpkg_path.exists()
    assert not any(Path(f"{gpkg_path}{suffix}").exists() for suffix in SIDECAR_SUFFIXES)


def test_remove_geopackage_removes_main_and_sidecars(tmp_path: Path) -> None:
    """本体と付随ファイルをまとめて削除する。"""
    gpkg_path = tmp_path / "sample.gpkg"
    _create_geopackage_files(gpkg_path)

    remove_geopackage(gpkg_path)

    assert not gpkg_path.exists()
    assert not any(Path(f"{gpkg_path}{suffix}").exists() for suffix in SIDECAR_SUFFIXES)


def test_remove_functions_tolerate_missing_files(tmp_path: Path) -> None:
    """対象ファイルが存在しなくても例外にならない。"""
    missing_path = tmp_path / "missing.gpkg"

    remove_sidecar_files(missing_path)
    remove_geopackage(missing_path)

    assert not missing_path.exists()


def test_remove_geopackage_keeps_unrelated_files(tmp_path: Path) -> None:
    """接尾辞が一致しない同名系のファイルは削除しない。"""
    gpkg_path = tmp_path / "sample.gpkg"
    _create_geopackage_files(gpkg_path)
    unrelated_path = tmp_path / "sample.gpkg.bak"
    unrelated_path.write_text("backup", encoding="utf-8")

    remove_geopackage(gpkg_path)

    assert unrelated_path.exists()
