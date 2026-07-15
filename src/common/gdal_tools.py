"""QGIS/OSGeo4W同梱のGDALツール（ogr2ogr/ogrinfo/GDAL_DATA）の探索処理を集約する。

`src/preprocessing/` 配下の複数スクリプトで重複していた
「QGIS同梱のogr2ogrをバージョン非依存に探索する」処理をここに集約する。
QGISのインストールフォルダ名（例: "QGIS 3.40.11"）を数値パースしてバージョン比較し、
指定バージョン以上のスタンドアロンQGIS、次点でOSGeo4Wを優先順位に従って探索する。
"""

from __future__ import annotations

import re
from pathlib import Path

QGIS_MIN_VERSION: tuple[int, int] = (3, 40)
DEFAULT_PROGRAM_FILES_DIR = Path(r"C:\Program Files")
DEFAULT_OSGEO4W_ROOTS: tuple[Path, ...] = (
    Path(r"C:\OSGeo4W"),
    Path(r"C:\OSGeo4W64"),
)
_QGIS_FOLDER_PATTERN = re.compile(r"QGIS (\d+)\.(\d+)(?:\.(\d+))?")


def parse_qgis_version(folder_name: str) -> tuple[int, ...] | None:
    """QGISインストールフォルダ名からバージョン番号を数値タプルとして抽出する。

    "QGIS 3.40.11" は (3, 40, 11) のように抽出し、文字列比較ではなく数値比較で
    バージョンの大小を判定できるようにする（"3.9" と "3.10" の逆転を防ぐ）。

    Args:
        folder_name: QGISインストールフォルダ名。
    Returns:
        バージョン番号の数値タプル。フォルダ名がQGISのバージョン表記と一致しない場合は None。
    """
    match = _QGIS_FOLDER_PATTERN.fullmatch(folder_name)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def find_qgis_roots(
    min_version: tuple[int, int] = QGIS_MIN_VERSION,
    program_files_dir: Path = DEFAULT_PROGRAM_FILES_DIR,
) -> list[Path]:
    """条件を満たすQGISスタンドアロンインストールのルートをバージョン降順で返す。

    Args:
        min_version: 探索対象とする最小バージョン（メジャー, マイナー）。
        program_files_dir: QGISインストール先の探索基点（テスト時は差し替え可能）。
    Returns:
        min_version 以上のQGISインストールのルートディレクトリのリスト（バージョン降順）。
    """
    if not program_files_dir.exists():
        return []

    versioned_roots: list[tuple[tuple[int, ...], Path]] = []
    for entry in program_files_dir.glob("QGIS *"):
        if not entry.is_dir():
            continue
        version = parse_qgis_version(entry.name)
        if version is None or version[:2] < min_version:
            continue
        versioned_roots.append((version, entry))
    versioned_roots.sort(key=lambda item: item[0], reverse=True)

    return [root for _, root in versioned_roots]


def _qgis_tool_paths(root: Path) -> tuple[Path, Path, Path]:
    """QGISスタンドアロン版のルートから ogr2ogr/ogrinfo/GDAL_DATA のパスを組み立てる。

    Args:
        root: QGISスタンドアロンインストールのルートディレクトリ。
    Returns:
        (ogr2ogr_path, ogrinfo_path, gdal_data_path) のタプル。
    """
    return (
        root / "bin" / "ogr2ogr.exe",
        root / "bin" / "ogrinfo.exe",
        root / "apps" / "gdal" / "share" / "gdal",
    )


def _osgeo4w_tool_paths(root: Path) -> tuple[Path, Path, Path]:
    """OSGeo4Wのルートから ogr2ogr/ogrinfo/GDAL_DATA のパスを組み立てる。

    Args:
        root: OSGeo4Wインストールのルートディレクトリ。
    Returns:
        (ogr2ogr_path, ogrinfo_path, gdal_data_path) のタプル。
    """
    return (
        root / "bin" / "ogr2ogr.exe",
        root / "bin" / "ogrinfo.exe",
        root / "share" / "gdal",
    )


def find_gdal_toolset(
    min_qgis_version: tuple[int, int] = QGIS_MIN_VERSION,
    program_files_dir: Path = DEFAULT_PROGRAM_FILES_DIR,
    osgeo4w_roots: tuple[Path, ...] = DEFAULT_OSGEO4W_ROOTS,
) -> tuple[Path, Path, Path]:
    """ogr2ogr/ogrinfo/GDAL_DATAが揃うツールセットを優先順位に従って探索する。

    QGIS min_qgis_version以上のスタンドアロンインストール（新しいバージョン優先）
    → OSGeo4W → OSGeo4W64 の順に探索し、3点セットが同一ルートに揃っている最初の
    候補を返す。PATH上の裸の ogr2ogr 等へはフォールバックしない
    （GRASS/GMT付属など非対応ドライバ構成の誤採用を避けるため）。

    Args:
        min_qgis_version: QGISスタンドアロン探索の対象とする最小バージョン（メジャー, マイナー）。
        program_files_dir: QGISインストール先の探索基点（テスト時は差し替え可能）。
        osgeo4w_roots: OSGeo4Wのインストールルート候補（テスト時は差し替え可能）。
    Returns:
        (ogr2ogr_path, ogrinfo_path, gdal_data_path) のタプル。
    Raises:
        FileNotFoundError: 条件を満たすツールセットが見つからない場合。
    """
    candidates: list[tuple[Path, Path, Path]] = [
        _qgis_tool_paths(root) for root in find_qgis_roots(min_qgis_version, program_files_dir)
    ]
    candidates.extend(_osgeo4w_tool_paths(root) for root in osgeo4w_roots)

    for ogr2ogr_path, ogrinfo_path, gdal_data_path in candidates:
        if ogr2ogr_path.exists() and ogrinfo_path.exists() and gdal_data_path.exists():
            return ogr2ogr_path, ogrinfo_path, gdal_data_path

    raise FileNotFoundError(
        "ogr2ogr/ogrinfo/GDAL_DATA が見つかりませんでした。"
        f"QGIS {min_qgis_version[0]}.{min_qgis_version[1]} 以上のスタンドアロン版、"
        "または OSGeo4W をインストールしてください。"
        f"探索対象: '{program_files_dir}\\QGIS *'"
        f"（バージョン {min_qgis_version[0]}.{min_qgis_version[1]} 以上）, "
        f"{[str(root) for root in osgeo4w_roots]}"
    )
