"""bibliography_consistency.py（papers_database.csv正本との書誌整合チェック）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.bibliography_consistency import check_bibliography_consistency

_CSV_HEADER = "ID,著者,年\n"


def _write_csv(docs_dir: Path, rows: str) -> None:
    path = docs_dir / "04_archive" / "01_metadata" / "papers_database.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_CSV_HEADER + rows, encoding="utf-8")


def _write_readme(docs_dir: Path, bullet: str) -> None:
    content = f"# 📚 研究ドキュメント管理\n\n**先行研究一覧（S1-S8）**:\n\n{bullet}\n"
    (docs_dir / "README.md").write_text(content, encoding="utf-8")


def _write_report(docs_dir: Path, row: str) -> None:
    content = f"# 先行研究整理\n\n| ID | 著者（年） |\n| -- | -- |\n{row}\n"
    path = docs_dir / "04_archive" / "previous_studies_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_summary(docs_dir: Path, filename: str, header_year: str) -> None:
    content = (
        f"# {filename[:-3]}\n\n| 項目 | 内容 |\n|------|------|\n| **発表年** | {header_year} |\n"
    )
    path = docs_dir / "04_archive" / "02_structured_summaries" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_no_mismatch_when_all_sources_agree(tmp_path: Path) -> None:
    """全ソースの発表年が正本と一致していれば不一致なし。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S1,Ermida et al.,2020\n")
    _write_readme(docs_dir, "- **S1**: Ermida et al. (2020) - SMW法")
    _write_report(docs_dir, "| S1 | Ermida et al. (2020) |")
    _write_summary(docs_dir, "S1_Ermida_2020.md", "2020")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert result == []


def test_detects_readme_year_mismatch(tmp_path: Path) -> None:
    """docs/README.mdの発表年が正本と異なる場合を検出する（S2問題の再現）。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S2,Le Ngoc Hanh & Tran Thi An,年不明\n")
    _write_readme(docs_dir, "- **S2**: Le Ngoc Hanh (2025) - ベトナム・ダナン")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].paper_id == "S2"
    assert result[0].source == "docs/README.md"
    assert result[0].canonical_year == "年不明"
    assert result[0].found_year == "2025"


def test_detects_report_year_mismatch(tmp_path: Path) -> None:
    """previous_studies_report.mdの発表年が正本と異なる場合を検出する。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S2,Le Ngoc Hanh & Tran Thi An,年不明\n")
    _write_report(docs_dir, "| S2 | Le Ngoc Hanh & Tran Thi An (2025) |")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].source == "docs/04_archive/previous_studies_report.md"
    assert result[0].found_year == "2025"


def test_detects_summary_filename_year_mismatch(tmp_path: Path) -> None:
    """構造化要約ファイル名末尾の年が正本と異なる場合を検出する。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S2,Le Ngoc Hanh & Tran Thi An,年不明\n")
    _write_summary(docs_dir, "S2_LeNgocHanh_2025.md", "年不明")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert len(result) == 1
    assert "ファイル名" in result[0].source
    assert result[0].found_year == "2025"


def test_detects_summary_header_year_mismatch(tmp_path: Path) -> None:
    """構造化要約ヘッダーの発表年が正本と異なる場合を検出する。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S1,Ermida et al.,2020\n")
    _write_summary(docs_dir, "S1_Ermida_2020.md", "2021")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert len(result) == 1
    assert "ヘッダー" in result[0].source
    assert result[0].found_year == "2021"


def test_ignores_paper_id_not_present_in_csv(tmp_path: Path) -> None:
    """正本CSVに存在しないIDはチェック対象外（KeyErrorしない）。"""
    docs_dir = tmp_path / "docs"
    _write_csv(docs_dir, "S1,Ermida et al.,2020\n")
    _write_readme(docs_dir, "- **S9**: 未登録論文 (2030) - テスト")

    result = check_bibliography_consistency(project_root=tmp_path)

    assert result == []
