"""broken_links.py（相対パスリンク切れ検出）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.broken_links import check_broken_links


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_broken_relative_link(tmp_path: Path) -> None:
    """存在しない相対パスへのリンクを検出する。"""
    _write(tmp_path / "docs" / "a.md", "[存在しない](missing.md)")

    result = check_broken_links(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].source_file == "docs/a.md"
    assert result[0].target == "missing.md"


def test_does_not_flag_existing_relative_link(tmp_path: Path) -> None:
    """存在するファイルへのリンクは検出しない。"""
    _write(tmp_path / "docs" / "a.md", "[存在する](b.md)")
    _write(tmp_path / "docs" / "b.md", "内容")

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_ignores_external_urls(tmp_path: Path) -> None:
    """http/httpsの外部URLは検証対象外。"""
    _write(tmp_path / "docs" / "a.md", "[外部](https://example.com/not-a-real-path)")

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_checks_only_path_part_of_anchor_link(tmp_path: Path) -> None:
    """`path#anchor`形式はパス部分のみ検証し、アンカーの妥当性は問わない。"""
    _write(tmp_path / "docs" / "a.md", "[見出しへ](b.md#no-such-heading)")
    _write(tmp_path / "docs" / "b.md", "内容")

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_ignores_same_file_anchor_only_link(tmp_path: Path) -> None:
    """パス部分を持たない同一ファイル内アンカーリンクは対象外。"""
    _write(tmp_path / "docs" / "a.md", "[このページ内](#see-below)")

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_resolves_relative_to_source_file_directory(tmp_path: Path) -> None:
    """リンク先の相対パスはリンク元ファイルのディレクトリを基準に解決する。"""
    _write(tmp_path / "docs" / "sub" / "a.md", "[上へ](../README.md)")
    _write(tmp_path / "docs" / "README.md", "内容")

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_ignores_links_inside_code_fence(tmp_path: Path) -> None:
    """フェンスコードブロック内のリンク記法サンプルは検証対象外。"""
    content = "説明\n\n```markdown\n[サンプル](does-not-exist.md)\n```\n"
    _write(tmp_path / "docs" / "a.md", content)

    result = check_broken_links(project_root=tmp_path)

    assert result == []


def test_scans_claude_and_github_directories_too(tmp_path: Path) -> None:
    """.claude/・.github/配下のMarkdownも検査対象に含まれる。"""
    _write(tmp_path / ".github" / "task-workflow.md", "[存在しない](missing.md)")

    result = check_broken_links(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].source_file == ".github/task-workflow.md"
