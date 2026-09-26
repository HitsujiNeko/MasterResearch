"""summary.py（サマリーJSON保存）のテスト。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.common.summary import (
    build_provenance,
    compute_file_sha256,
    describe_input_files,
    get_git_state,
    get_package_versions,
    save_summary,
)


def test_save_summary_round_trip(tmp_path: Path) -> None:
    """保存した内容を再読込すると元の辞書と一致する。"""
    summary_path = tmp_path / "summary.json"
    summary = {"count": 3, "note": "テスト"}

    save_summary(summary, summary_path)

    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary


def test_save_summary_does_not_escape_japanese(tmp_path: Path) -> None:
    """日本語が\\uXXXXへエスケープされずそのまま保存される。"""
    summary_path = tmp_path / "summary.json"
    save_summary({"note": "ハノイ"}, summary_path)

    text = summary_path.read_text(encoding="utf-8")
    assert "ハノイ" in text
    assert "\\u" not in text


def test_save_summary_creates_parent_directory(tmp_path: Path) -> None:
    """親ディレクトリが存在しない場合は自動作成する。"""
    summary_path = tmp_path / "nested" / "dir" / "summary.json"

    save_summary({"ok": True}, summary_path)

    assert summary_path.exists()


def test_save_summary_rejects_nan(tmp_path: Path) -> None:
    """NaNはJSON標準に無いため、気づかず保存されないよう例外にする。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError, match="NaN"):
        save_summary({"pearson_r": math.nan}, summary_path)


def test_save_summary_rejects_infinity(tmp_path: Path) -> None:
    """Infinityも同様に弾く（ゼロ除算の見落とし対策）。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError, match="NaN"):
        save_summary({"ratio": math.inf}, summary_path)


def test_save_summary_does_not_write_file_when_rejected(tmp_path: Path) -> None:
    """NaN検出時は書き出さず、壊れた内容のファイルを残さない。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError):
        save_summary({"value": math.nan}, summary_path)

    assert not summary_path.exists()


def test_compute_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    """チャンク読み込みでも hashlib による一括計算と同じハッシュになる。"""
    target = tmp_path / "input.bin"
    content = b"hanoi" * 500_000  # 読み込み単位（1MiB）を跨ぐサイズ
    target.write_bytes(content)

    assert compute_file_sha256(target) == hashlib.sha256(content).hexdigest()


def test_compute_file_sha256_missing_file_raises(tmp_path: Path) -> None:
    """存在しないファイルは FileNotFoundError になる。"""
    with pytest.raises(FileNotFoundError, match="見つかりません"):
        compute_file_sha256(tmp_path / "missing.gpkg")


def test_get_package_versions_marks_missing_package_as_none() -> None:
    """インストール済みは版文字列、未インストールは None になる。"""
    versions = get_package_versions(["pytest", "no-such-package-for-provenance-test"])

    assert isinstance(versions["pytest"], str)
    assert versions["no-such-package-for-provenance-test"] is None


def test_get_git_state_in_repository_returns_commit() -> None:
    """リポジトリ内では40桁のコミットハッシュと真偽値の dirty を返す。"""
    state = get_git_state()

    assert isinstance(state["commit"], str)
    assert len(state["commit"]) == 40
    assert isinstance(state["dirty"], bool)


def test_get_git_state_outside_repository_returns_none(tmp_path: Path) -> None:
    """git リポジトリ外では例外にせず None を記録する。"""
    assert get_git_state(tmp_path) == {"commit": None, "dirty": None}


def test_describe_input_files_uses_project_relative_path(tmp_path: Path) -> None:
    """入力パスは基準ディレクトリからの相対パス（/ 区切り）で記録される。"""
    target = tmp_path / "data" / "input.csv"
    target.parent.mkdir()
    target.write_text("a,b\n1,2\n", encoding="utf-8")

    described = describe_input_files([target], project_root=tmp_path)

    assert described == [
        {"path": "data/input.csv", "sha256": hashlib.sha256(b"a,b\n1,2\n").hexdigest()}
    ]


def test_build_provenance_schema_and_json_serializable(tmp_path: Path) -> None:
    """来歴は所定のキーを持ち、save_summary でそのまま保存できる。"""
    target = tmp_path / "input.csv"
    target.write_text("x\n", encoding="utf-8")
    executed_at = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

    provenance = build_provenance(
        "src.analysis.example",
        input_paths=[target],
        packages=["pytest"],
        repo_root=tmp_path,
        executed_at=executed_at,
    )

    assert set(provenance) == {
        "script",
        "executed_at",
        "python_version",
        "platform",
        "git",
        "packages",
        "inputs",
    }
    assert provenance["script"] == "src.analysis.example"
    assert provenance["executed_at"] == "2026-09-26T12:00:00+00:00"
    assert provenance["inputs"][0]["path"] == "input.csv"
    assert list(provenance["packages"]) == ["pytest"]

    # 既存のサマリーへ provenance キーとして追加して保存できる
    summary_path = tmp_path / "summary.json"
    save_summary({"count": 1, "provenance": provenance}, summary_path)
    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved["provenance"] == provenance
