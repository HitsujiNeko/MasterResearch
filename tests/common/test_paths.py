"""paths.py（相対パス解決・入出力パス検証）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.paths import (
    prepare_output_path,
    resolve_existing_path,
    resolve_relative_to_project_root,
    to_project_relative_string,
)


def test_resolve_relative_to_project_root_returns_none_for_empty_string() -> None:
    """空文字は「未指定」を表し None を返す（既定値の決定は呼び出し側に委ねる）。"""
    assert resolve_relative_to_project_root("") is None


def test_resolve_relative_to_project_root_resolves_relative_path(tmp_path: Path) -> None:
    """相対パス文字列は project_root を前置して絶対化する。"""
    result = resolve_relative_to_project_root("data/output", project_root=tmp_path)

    assert result == tmp_path / "data" / "output"


def test_resolve_relative_to_project_root_keeps_absolute_path(tmp_path: Path) -> None:
    """絶対パス文字列は project_root を前置せずそのまま返す。"""
    absolute = tmp_path / "elsewhere" / "output"

    result = resolve_relative_to_project_root(str(absolute), project_root=tmp_path)

    assert result == absolute


def test_resolve_relative_to_project_root_does_not_check_existence(tmp_path: Path) -> None:
    """存在確認や親ディレクトリ作成は行わない（出力先の要否は呼び出し側の判断）。"""
    result = resolve_relative_to_project_root("not_created_yet", project_root=tmp_path)

    assert result == tmp_path / "not_created_yet"
    assert not result.exists()


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


def test_to_project_relative_string_uses_forward_slashes(tmp_path: Path) -> None:
    """区切り文字は実行 OS によらず `/` に統一する。"""
    target = tmp_path / "data" / "output" / "summary.json"

    result = to_project_relative_string(target, project_root=tmp_path)

    assert result == "data/output/summary.json"
    assert "\\" not in result


def test_to_project_relative_string_keeps_absolute_path_outside_root(tmp_path: Path) -> None:
    """project_root 外のパスは絶対パス文字列のまま返す。"""
    outside_root = tmp_path / "root"
    outside_root.mkdir()
    target = tmp_path / "elsewhere" / "summary.json"

    result = to_project_relative_string(target, project_root=outside_root)

    assert Path(result) == target.resolve()
