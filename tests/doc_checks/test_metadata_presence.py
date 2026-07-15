"""metadata_presence.py（冒頭「最終更新」メタ情報の有無検出）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.metadata_presence import check_metadata_presence


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_missing_metadata(tmp_path: Path) -> None:
    """冒頭5行以内に「最終更新」がない場合を検出する。"""
    _write(tmp_path / "docs" / "a.md", "# タイトル\n\n本文のみ。\n")

    result = check_metadata_presence(project_root=tmp_path)

    assert [v.file for v in result] == ["docs/a.md"]


def test_does_not_flag_when_metadata_present_near_heading(tmp_path: Path) -> None:
    """見出し直後に「最終更新」があれば検出しない。"""
    _write(tmp_path / "docs" / "a.md", "# タイトル\n\n**最終更新**: 2026-01-01\n")

    result = check_metadata_presence(project_root=tmp_path)

    assert result == []


def test_does_not_count_metadata_in_body_or_footer(tmp_path: Path) -> None:
    """本文中・末尾の「最終更新」記載は冒頭メタ情報として扱わない。"""
    lines = ["# タイトル"] + [f"本文{i}" for i in range(10)] + ["**最終更新**: 2026-01-01"]
    _write(tmp_path / "docs" / "a.md", "\n".join(lines))

    result = check_metadata_presence(project_root=tmp_path)

    assert [v.file for v in result] == ["docs/a.md"]


def test_excludes_readme_and_structured_summaries_and_template(tmp_path: Path) -> None:
    """docs/README.md・S*.md・テンプレートは対象外。"""
    _write(tmp_path / "docs" / "README.md", "# 研究ドキュメント管理\n\n本文のみ\n")
    _write(
        tmp_path / "docs" / "04_archive" / "02_structured_summaries" / "S1_Ermida_2020.md",
        "# S1: Ermida et al. (2020)\n\n本文のみ\n",
    )
    _write(
        tmp_path / "docs" / "04_archive" / "templates" / "structured_summary_template.md",
        "# テンプレート\n\n本文のみ\n",
    )

    result = check_metadata_presence(project_root=tmp_path)

    assert result == []


def test_excludes_mmd_files(tmp_path: Path) -> None:
    """.mmdファイルは見出し構造を持たないため対象外。"""
    _write(tmp_path / "docs" / "diagram.mmd", "graph TD\nA-->B\n")

    result = check_metadata_presence(project_root=tmp_path)

    assert result == []


def test_ignores_claude_and_github_and_root_files(tmp_path: Path) -> None:
    """.claude/・.github/・リポジトリ直下のファイルはdocs/運用ルールの対象外。"""
    _write(tmp_path / ".claude" / "skills" / "foo" / "SKILL.md", "---\nname: foo\n---\n\n# foo\n")
    _write(tmp_path / ".github" / "task-workflow.md", "# タスクワークフロー\n\n本文のみ\n")
    _write(tmp_path / "AGENTS.md", "# AGENTS\n\n本文のみ\n")

    result = check_metadata_presence(project_root=tmp_path)

    assert result == []


def test_flags_file_without_any_heading(tmp_path: Path) -> None:
    """`# `見出しが存在しないファイルは欠落として検出する。"""
    _write(tmp_path / "docs" / "a.md", "見出しのない本文。\n")

    result = check_metadata_presence(project_root=tmp_path)

    assert [v.file for v in result] == ["docs/a.md"]
