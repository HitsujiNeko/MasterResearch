"""summary.py（サマリーJSON保存）のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

from src.common.summary import save_summary


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
