"""thesis_numbers.py（原稿の数値と正本の照合）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.doc_checks.thesis_numbers import (
    KIND_LEGACY_ONLY,
    KIND_NOT_IN_SOURCE,
    check_section_numbers,
    extract_numbers,
    index_source_numbers,
    main,
    number_key,
)

_SOURCE_PATH = "docs/03_results/limited_analysis_results.md"

# 旧観測（2〜7章）と主採用の観測（8章）で値が異なる正本
_SOURCE_TEXT = """# Limited 結果

## 1. 位置づけ

説明。

## 2. 旧観測の結果

旧観測の R² は 0.41、RMSE は 2.35 °C。共通の値は 0.55。

## 8. 主採用の観測の結果

主採用の R² は 0.63、RMSE は 1.82 °C。共通の値は 0.55。件数は 12,345 件。
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _section(tmp_path: Path, body: str, state: str = "執筆中") -> Path:
    header = (
        f"<!--\n見出し: 4.1\n状態: {state}\n依拠する正本:\n  - {_SOURCE_PATH} @ 1a2b3c4d5e\n-->\n"
    )
    section = tmp_path / "thesis" / "chapters" / "04_results" / "01_s.md"
    _write(section, header + body)
    _write(tmp_path / _SOURCE_PATH, _SOURCE_TEXT)
    return section


def test_number_key_ignores_commas_and_trailing_zeros() -> None:
    """桁区切りと末尾のゼロの違いは同じ値として扱う。"""
    assert number_key("1,234.50") == number_key("1234.5")


def test_extract_numbers_skips_non_target_text() -> None:
    """見出し・引用キー・図表番号・節番号・年・コードは対象外で、整数も対象外。"""
    text = (
        "## 4.1　結果\n"
        "R² は 0.63 である[@S1]．図-1 と 3.2節 と 2022 年と `9.99` と 30 m は対象外．\n"
        "![x](a.png){#fig:lst_map1.5}\n"
        "件数は 12,345 件．\n"
    )

    assert extract_numbers(text) == [(2, "0.63"), (4, "12,345")]


def test_index_source_numbers_records_chapters() -> None:
    """正本の数値が現れる章を記録する。"""
    index = index_source_numbers(_SOURCE_TEXT)

    assert index[number_key("0.41")] == {"2"}
    assert index[number_key("0.55")] == {"2", "8"}
    assert index[number_key("0.63")] == {"8"}


def test_primary_values_pass(tmp_path: Path) -> None:
    """主採用の章の値、および旧観測と共通の値は指摘しない。"""
    section = _section(tmp_path, "R² は 0.63，RMSE は 1.82 °C，共通値は 0.55，件数は 12,345 件．\n")

    assert check_section_numbers(section, tmp_path) == []


def test_detects_legacy_observation_value(tmp_path: Path) -> None:
    """旧観測の章にだけある値を混ぜた例を検出する。"""
    section = _section(tmp_path, "R² は 0.63 だが，RMSE は 2.35 °C である．\n")

    result = check_section_numbers(section, tmp_path)

    assert [(f.line, f.kind, f.number_text) for f in result] == [(7, KIND_LEGACY_ONLY, "2.35")]


def test_detects_number_not_in_source(tmp_path: Path) -> None:
    """正本のどこにも無い値（再計算した値の直書きなど）を検出する。"""
    section = _section(tmp_path, "R² は 0.64 である．\n")

    result = check_section_numbers(section, tmp_path)

    assert [(f.kind, f.number_text) for f in result] == [(KIND_NOT_IN_SOURCE, "0.64")]


def test_not_started_section_is_skipped(tmp_path: Path) -> None:
    """状態が未着手の節は照合しない。"""
    section = _section(tmp_path, "R² は 9.99 である．\n", state="未着手")

    assert check_section_numbers(section, tmp_path) == []


def test_section_without_sources_is_skipped(tmp_path: Path) -> None:
    """依拠する正本が無い節は照合しない。"""
    section = tmp_path / "thesis" / "chapters" / "90_back_matter" / "01_ack.md"
    _write(section, "<!--\n見出し: 謝辞\n状態: 執筆中\n依拠する正本:\n-->\n値は 9.99．\n")

    assert check_section_numbers(section, tmp_path) == []


def test_main_prints_warning_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """指摘があっても終了コードは0で、指摘を表示する。"""
    _section(tmp_path, "RMSE は 2.35 °C である．\n")

    code = main([], project_root=tmp_path)

    assert code == 0
    assert "旧観測のみ" in capsys.readouterr().out
