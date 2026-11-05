"""thesis_notation.py（原稿の表記チェック）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.thesis_notation import check_thesis_notation


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _section(tmp_path: Path, body: str) -> None:
    _write(tmp_path / "thesis" / "chapters" / "01_a" / "01_s.md", body)


def test_canonical_notation_is_not_flagged(tmp_path: Path) -> None:
    """「，」「．」と °C の表記は違反にならない。"""
    _section(tmp_path, "## 1.1　背景\n\nLST は 32.5 °C である．本研究は，Landsat 8/9 を用いる．\n")

    assert check_thesis_notation(tmp_path) == []


def test_detects_japanese_punctuation(tmp_path: Path) -> None:
    """「、」「。」を行番号つきで検出する．"""
    _section(tmp_path, "## 1.1　背景\n\n本研究は、LST を扱う。\n")

    result = check_thesis_notation(tmp_path)

    assert [(v.line, v.category, v.matched_text) for v in result] == [
        (3, "句読点", "、"),
        (3, "句読点", "。"),
    ]


def test_detects_temperature_unit_violations(tmp_path: Path) -> None:
    """数値に続く K・ケルビン・℃・度C を検出し，単語の一部の K は検出しない。"""
    _section(
        tmp_path, "LST は 305 K，300 ケルビン，30℃，30度C，300°K である．5Km と温度Cは対象外．\n"
    )

    result = check_thesis_notation(tmp_path)

    assert [v.matched_text for v in result] == ["5 K", "0 ケルビン", "℃", "0度C", "0°K"]
    assert all(v.category == "温度の単位" for v in result)


def test_ignores_comments_and_code(tmp_path: Path) -> None:
    """メタ情報欄・コードブロック・コードスパン内は対象外。"""
    _section(
        tmp_path,
        "<!--\n目安: 約34ページ程度。\n-->\n"
        "## 1.1　背景\n\n"
        "```text\nこれは、例。\n```\n"
        "記法 `、` の説明．\n",
    )

    assert check_thesis_notation(tmp_path) == []


def test_line_numbers_are_kept_after_masking(tmp_path: Path) -> None:
    """コメントを除いても，違反の行番号は元の行を指す。"""
    _section(tmp_path, "<!--\nメモ。\n-->\n本文、です．\n")

    result = check_thesis_notation(tmp_path)

    assert [v.line for v in result] == [4]


def test_metadata_yaml_skips_comments_only(tmp_path: Path) -> None:
    """YAML のコメント行は対象外で，値の行は対象。"""
    _write(tmp_path / "thesis" / "metadata.yaml", '# 説明。\ntitle: "題目、です"\n')

    result = check_thesis_notation(tmp_path)

    assert [(v.file, v.line) for v in result] == [("thesis/metadata.yaml", 2)]


def test_no_thesis_returns_empty(tmp_path: Path) -> None:
    """thesis/ が無いプロジェクトでは何も検出しない。"""
    assert check_thesis_notation(tmp_path) == []
