"""catalog_diff.py（docs/README.mdカタログと実ファイルの差分検出）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.catalog_diff import check_catalog_diff

_README_TEMPLATE = """# 📚 研究ドキュメント管理

## 🗂️ ディレクトリ構造

```text
docs/
```

## 📊 全ドキュメントカタログ

### 🛠️ ルート

| ファイル名 | 概要 |
|---|---|
| [README.md](README.md) | このファイル |
{table_rows}

**構造化要約（現存ファイル）**:

{list_items}

## 🔄 ドキュメント関係図

本文
"""


def _write_readme(docs_dir: Path, table_rows: str = "", list_items: str = "") -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    content = _README_TEMPLATE.format(table_rows=table_rows, list_items=list_items)
    (docs_dir / "README.md").write_text(content, encoding="utf-8")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("dummy", encoding="utf-8")


def test_no_violations_when_catalog_matches_actual_files(tmp_path: Path) -> None:
    """カタログと実ファイルが一致していれば差分なし。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir, table_rows="| [setup.md](setup.md) | 概要 |")
    _touch(docs_dir / "setup.md")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations


def test_detects_actual_file_missing_from_catalog(tmp_path: Path) -> None:
    """実ファイルが存在するがカタログ未掲載の場合を検出する。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir)
    _touch(docs_dir / "orphan.md")

    result = check_catalog_diff(project_root=tmp_path)

    assert "orphan.md" in result.missing_from_catalog
    assert result.has_violations


def test_detects_catalog_entry_missing_actual_file(tmp_path: Path) -> None:
    """カタログに記載があるが実ファイルが存在しない場合を検出する。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir, table_rows="| [ghost.md](ghost.md) | 概要 |")

    result = check_catalog_diff(project_root=tmp_path)

    assert "ghost.md" in result.missing_file
    assert result.has_violations


def test_excludes_gis_data_directory_from_diff(tmp_path: Path) -> None:
    """01_planning/gis_data/ 配下は差分検出対象外とする。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir)
    _touch(docs_dir / "01_planning" / "gis_data" / "gis_data_roads.md")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations


def test_excludes_pdf_directory_from_diff(tmp_path: Path) -> None:
    """04_archive/04_pdfs/ 配下（論文PDF原本）は差分検出対象外とする。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir)
    _touch(docs_dir / "04_archive" / "04_pdfs" / "S1_Ermida_2020.pdf")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations


def test_excludes_all_prefixes_simultaneously(tmp_path: Path) -> None:
    """複数の除外パスが同時に存在しても、いずれも差分として検出しない。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir)
    _touch(docs_dir / "01_planning" / "gis_data" / "gis_data_roads.md")
    _touch(docs_dir / "04_archive" / "04_pdfs" / "S2_LengocHanh_2025.pdf")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations


def test_detects_non_excluded_archive_subdirectory(tmp_path: Path) -> None:
    """除外対象外の 04_archive 配下（構造化要約）は従来どおり検出する。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir)
    summary_path = "04_archive/02_structured_summaries/S1_Ermida_2020.md"
    _touch(docs_dir / summary_path)

    result = check_catalog_diff(project_root=tmp_path)

    assert summary_path in result.missing_from_catalog
    assert result.has_violations


def test_extracts_links_from_bullet_list_not_only_table_rows(tmp_path: Path) -> None:
    """テーブル行だけでなく箇条書きリンクもカタログ記載として認識する。"""
    docs_dir = tmp_path / "docs"
    _write_readme(
        docs_dir,
        list_items="- [S1_Ermida_2020.md](04_archive/02_structured_summaries/S1_Ermida_2020.md)",
    )
    _touch(docs_dir / "04_archive" / "02_structured_summaries" / "S1_Ermida_2020.md")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations


def test_ignores_external_urls_in_catalog(tmp_path: Path) -> None:
    """外部URLはカタログのリンク先パスとして扱わない（missing_fileに含めない）。"""
    docs_dir = tmp_path / "docs"
    _write_readme(docs_dir, table_rows="| [外部リンク](https://example.com/doc) | 概要 |")

    result = check_catalog_diff(project_root=tmp_path)

    assert not result.has_violations
