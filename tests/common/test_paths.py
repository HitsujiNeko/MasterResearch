"""paths.py（相対パス解決・入出力パス検証）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.paths import prepare_output_path, resolve_existing_path


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
