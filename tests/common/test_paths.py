"""paths.py（相対パス解決・入出力パス検証）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.paths import (
    prepare_output_path,
    resolve_existing_path,
    to_project_relative_string,
)


def test_resolve_existing_path_returns_absolute_path_for_existing_file(tmp_path: Path) -> None:
    """存在するファイルの絶対パスをそのまま返す。"""
    existing_file = tmp_path / "input.csv"
    existing_file.write_text("dummy", encoding="utf-8")

    resolved = resolve_existing_path(existing_file)

    assert resolved == existing_file.resolve()


def test_resolve_existing_path_resolves_relative_path_against_project_root(
    tmp_path: Path,
) -> None:
    """相対パスは project_root 引数を基準に解決する。"""
    existing_file = tmp_path / "nested" / "input.csv"
    existing_file.parent.mkdir()
    existing_file.write_text("dummy", encoding="utf-8")

    resolved = resolve_existing_path(Path("nested") / "input.csv", project_root=tmp_path)

    assert resolved == existing_file.resolve()


def test_resolve_existing_path_raises_when_missing(tmp_path: Path) -> None:
    """存在しないパスは FileNotFoundError を送出する。"""
    missing_path = tmp_path / "does_not_exist.csv"

    with pytest.raises(FileNotFoundError):
        resolve_existing_path(missing_path)


def test_prepare_output_path_creates_parent_directory(tmp_path: Path) -> None:
    """出力先の親ディレクトリが存在しない場合は作成する。"""
    output_path = tmp_path / "nested" / "output.csv"

    resolved = prepare_output_path(output_path)

    assert resolved.parent.exists()
    assert resolved.parent.is_dir()
    assert resolved == output_path.resolve()


def test_prepare_output_path_resolves_relative_path_against_project_root(
    tmp_path: Path,
) -> None:
    """相対パスは project_root 引数を基準に解決し、親ディレクトリを作成する。"""
    output_path = Path("nested") / "output.csv"

    resolved = prepare_output_path(output_path, project_root=tmp_path)

    assert resolved == (tmp_path / "nested" / "output.csv").resolve()
    assert resolved.parent.exists()
    assert resolved.parent.is_dir()


def test_to_project_relative_string_returns_relative_path(tmp_path: Path) -> None:
    """project_root 配下のパスは相対パス文字列へ変換する。"""
    target = tmp_path / "data" / "output" / "summary.json"

    result = to_project_relative_string(target, project_root=tmp_path)

    assert Path(result) == Path("data/output/summary.json")


def test_to_project_relative_string_keeps_absolute_path_outside_root(tmp_path: Path) -> None:
    """project_root 外のパスは絶対パス文字列のまま返す。"""
    outside_root = tmp_path / "root"
    outside_root.mkdir()
    target = tmp_path / "elsewhere" / "summary.json"

    result = to_project_relative_string(target, project_root=outside_root)

    assert Path(result) == target.resolve()
