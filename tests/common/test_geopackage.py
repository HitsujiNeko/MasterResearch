"""geopackage.py（GeoPackageの後片付け）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.geopackage import (
    SIDECAR_SUFFIXES,
    remove_geopackage,
    remove_sidecar_files,
    replace_geopackage,
)


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


def test_replace_geopackage_swaps_content_and_clears_sidecars(tmp_path: Path) -> None:
    """一時ファイルの内容で出力先を差し替え、出力先の古い付随ファイルを消す。"""
    output_path = tmp_path / "output.gpkg"
    _create_geopackage_files(output_path)
    temp_path = tmp_path / "output.tmp.gpkg"
    temp_path.write_text("new", encoding="utf-8")

    replace_geopackage(temp_path, output_path)

    assert output_path.read_text(encoding="utf-8") == "new"
    assert not temp_path.exists()
    assert not any(Path(f"{output_path}{suffix}").exists() for suffix in SIDECAR_SUFFIXES)


def test_replace_geopackage_creates_output_when_absent(tmp_path: Path) -> None:
    """出力先が存在しない場合も、そのまま新規作成として差し替えられる。"""
    output_path = tmp_path / "output.gpkg"
    temp_path = tmp_path / "output.tmp.gpkg"
    temp_path.write_text("new", encoding="utf-8")

    replace_geopackage(temp_path, output_path)

    assert output_path.read_text(encoding="utf-8") == "new"


def test_replace_geopackage_wraps_failure_with_japanese_message(
    tmp_path: Path, monkeypatch
) -> None:
    """差し替えに失敗した場合は、対処を示す日本語のOSErrorに包み直す。

    Windowsで出力先をQGIS等が開いたままだと起きる状況を模す。素の
    ``PermissionError`` では原因が読み取りにくいため、案内文と一時ファイルの
    所在を添える。
    """
    output_path = tmp_path / "output.gpkg"
    output_path.write_text("original", encoding="utf-8")
    temp_path = tmp_path / "output.tmp.gpkg"
    temp_path.write_text("new", encoding="utf-8")

    def failing_replace(self: Path, target: object) -> None:
        """他プロセスがファイルを開いている状況を模す。"""
        raise PermissionError("使用中のファイルにアクセスできません")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="他のアプリケーションで開かれていないか") as error_info:
        replace_geopackage(temp_path, output_path)

    assert isinstance(error_info.value.__cause__, PermissionError)
    # 既存の出力は失われず、書き出し済みの一時ファイルも回収できるよう残す。
    assert output_path.read_text(encoding="utf-8") == "original"
    assert temp_path.exists()


def test_replace_geopackage_keeps_existing_sidecars_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """差し替えに失敗した場合、既存の付随ファイルも失われない。

    付随ファイルを差し替えの**前**に消すと、出力先をQGISが開いていて差し替えが
    失敗したときに、生きている ``-wal`` だけを失う。``-wal`` は未チェックポイントの
    トランザクションを保持するため、既存データベースの内容が巻き戻る。
    「失敗しても既存の出力はそのまま残る」という保証は本体だけでは足りない。
    """
    output_path = tmp_path / "output.gpkg"
    _create_geopackage_files(output_path)
    temp_path = tmp_path / "output.tmp.gpkg"
    temp_path.write_text("new", encoding="utf-8")

    def failing_replace(self: Path, target: object) -> None:
        """他プロセスがファイルを開いている状況を模す。"""
        raise PermissionError("使用中のファイルにアクセスできません")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="他のアプリケーションで開かれていないか"):
        replace_geopackage(temp_path, output_path)

    assert output_path.read_text(encoding="utf-8") == "main"
    for suffix in SIDECAR_SUFFIXES:
        sidecar = Path(f"{output_path}{suffix}")
        assert sidecar.read_text(encoding="utf-8") == suffix
