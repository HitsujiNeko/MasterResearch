"""gdal_tools.py（QGIS/OSGeo4W同梱GDALツール探索）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.gdal_tools import find_gdal_toolset, find_qgis_roots, parse_qgis_version


def _create_qgis_install(root: Path, folder_name: str, *, with_gdal_data: bool = True) -> Path:
    """テスト用にQGISスタンドアロンインストールのディレクトリ構造を作成する。"""
    install_dir = root / folder_name
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "ogr2ogr.exe").write_text("dummy", encoding="utf-8")
    (install_dir / "bin" / "ogrinfo.exe").write_text("dummy", encoding="utf-8")
    if with_gdal_data:
        (install_dir / "apps" / "gdal" / "share" / "gdal").mkdir(parents=True)
    return install_dir


def _create_osgeo4w_install(root: Path) -> Path:
    """テスト用にOSGeo4Wインストールのディレクトリ構造を作成する。"""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "ogr2ogr.exe").write_text("dummy", encoding="utf-8")
    (root / "bin" / "ogrinfo.exe").write_text("dummy", encoding="utf-8")
    (root / "share" / "gdal").mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    ("folder_name", "expected"),
    [
        ("QGIS 3.40.11", (3, 40, 11)),
        ("QGIS 3.40", (3, 40)),
        ("QGIS 3.9.2", (3, 9, 2)),
        ("QGIS 3.10.0", (3, 10, 0)),
        ("OSGeo4W", None),
        ("QGIS", None),
    ],
)
def test_parse_qgis_version(folder_name: str, expected: tuple[int, ...] | None) -> None:
    """QGISフォルダ名からバージョン番号を数値タプルとして抽出する。"""
    assert parse_qgis_version(folder_name) == expected


def test_parse_qgis_version_compares_numerically_not_lexically() -> None:
    """ "3.9" と "3.10" を文字列比較ではなく数値比較で正しく判定する。"""
    version_3_9 = parse_qgis_version("QGIS 3.9.0")
    version_3_10 = parse_qgis_version("QGIS 3.10.0")

    assert version_3_9 is not None
    assert version_3_10 is not None
    assert version_3_9 < version_3_10


def test_find_qgis_roots_selects_versions_at_or_above_minimum(tmp_path: Path) -> None:
    """min_version以上のQGISインストールのみをバージョン降順で返す。"""
    _create_qgis_install(tmp_path, "QGIS 3.34.11")
    newer = _create_qgis_install(tmp_path, "QGIS 3.42.0")
    older_match = _create_qgis_install(tmp_path, "QGIS 3.40.11")

    roots = find_qgis_roots(min_version=(3, 40), program_files_dir=tmp_path)

    assert roots == [newer, older_match]


def test_find_qgis_roots_returns_empty_list_when_no_version_matches(tmp_path: Path) -> None:
    """条件を満たすQGISインストールがない場合は空リストを返す。"""
    _create_qgis_install(tmp_path, "QGIS 3.34.11")

    roots = find_qgis_roots(min_version=(3, 40), program_files_dir=tmp_path)

    assert roots == []


def test_find_qgis_roots_returns_empty_list_when_program_files_dir_missing(
    tmp_path: Path,
) -> None:
    """探索基点のディレクトリが存在しない場合は空リストを返す。"""
    missing_dir = tmp_path / "does_not_exist"

    roots = find_qgis_roots(program_files_dir=missing_dir)

    assert roots == []


def test_find_gdal_toolset_prefers_newest_qgis_when_multiple_versions_exist(
    tmp_path: Path,
) -> None:
    """複数のQGIS 3.40以上が共存する場合、最新バージョンの3点セットを採用する。"""
    _create_qgis_install(tmp_path, "QGIS 3.40.11")
    newest = _create_qgis_install(tmp_path, "QGIS 3.42.0")

    ogr2ogr_path, ogrinfo_path, gdal_data_path = find_gdal_toolset(
        program_files_dir=tmp_path, osgeo4w_roots=()
    )

    assert ogr2ogr_path == newest / "bin" / "ogr2ogr.exe"
    assert ogrinfo_path == newest / "bin" / "ogrinfo.exe"
    assert gdal_data_path == newest / "apps" / "gdal" / "share" / "gdal"


def test_find_gdal_toolset_falls_back_to_osgeo4w_when_qgis_version_too_old(
    tmp_path: Path,
) -> None:
    """QGISが3.40未満のみの場合はOSGeo4Wにフォールバックする。"""
    _create_qgis_install(tmp_path, "QGIS 3.34.11")
    osgeo4w_root = _create_osgeo4w_install(tmp_path / "OSGeo4W")

    ogr2ogr_path, ogrinfo_path, gdal_data_path = find_gdal_toolset(
        program_files_dir=tmp_path, osgeo4w_roots=(osgeo4w_root,)
    )

    assert ogr2ogr_path == osgeo4w_root / "bin" / "ogr2ogr.exe"
    assert ogrinfo_path == osgeo4w_root / "bin" / "ogrinfo.exe"
    assert gdal_data_path == osgeo4w_root / "share" / "gdal"


def test_find_gdal_toolset_skips_qgis_install_missing_gdal_data(tmp_path: Path) -> None:
    """3点セットが揃わないQGISインストールは候補から除外し、次点に進む。"""
    _create_qgis_install(tmp_path, "QGIS 3.42.0", with_gdal_data=False)
    osgeo4w_root = _create_osgeo4w_install(tmp_path / "OSGeo4W")

    ogr2ogr_path, _, _ = find_gdal_toolset(
        program_files_dir=tmp_path, osgeo4w_roots=(osgeo4w_root,)
    )

    assert ogr2ogr_path == osgeo4w_root / "bin" / "ogr2ogr.exe"


def test_find_gdal_toolset_raises_clear_error_when_nothing_matches(tmp_path: Path) -> None:
    """該当バージョンのQGISもOSGeo4Wも見つからない場合、分かりやすいエラーを送出する。"""
    _create_qgis_install(tmp_path, "QGIS 3.34.11")

    with pytest.raises(FileNotFoundError, match="ogr2ogr/ogrinfo/GDAL_DATA"):
        find_gdal_toolset(program_files_dir=tmp_path, osgeo4w_roots=())
