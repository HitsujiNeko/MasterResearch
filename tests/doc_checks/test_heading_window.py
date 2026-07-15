"""heading_window.py（冒頭見出し直後の行群抽出）のテスト。"""

from __future__ import annotations

from src.doc_checks.heading_window import extract_heading_window


def test_returns_lines_after_heading() -> None:
    """見出し直後のlookahead行を結合して返す。"""
    text = "# タイトル\n\n**最終更新**: 2026-01-01\n本文\n"

    window = extract_heading_window(text)

    assert window is not None
    assert "**最終更新**: 2026-01-01" in window


def test_returns_none_when_no_heading() -> None:
    """見出しが存在しない場合はNoneを返す。"""
    text = "見出しのない本文。\n"

    assert extract_heading_window(text) is None


def test_respects_lookahead_lines_limit() -> None:
    """lookahead_linesを超える行は含めない。"""
    lines = ["# タイトル"] + [f"本文{i}" for i in range(10)]
    text = "\n".join(lines)

    window = extract_heading_window(text, lookahead_lines=2)

    assert window == "本文0\n本文1"
