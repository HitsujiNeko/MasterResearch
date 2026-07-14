"""scan_targets.py（検査対象ファイル一覧取得）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.scan_targets import collect_markdown_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("dummy", encoding="utf-8")


def test_collect_markdown_files_includes_docs_claude_github_and_root(tmp_path: Path) -> None:
    """docs/・.claude/・.github/配下とルート直下の.mdを収集する。"""
    _touch(tmp_path / "docs" / "README.md")
    _touch(tmp_path / "docs" / "01_planning" / "research_guide.md")
    _touch(tmp_path / ".claude" / "skills" / "foo" / "SKILL.md")
    _touch(tmp_path / ".github" / "task-workflow.md")
    _touch(tmp_path / "CLAUDE.md")

    result = collect_markdown_files(project_root=tmp_path)

    assert Path("docs/README.md") in result
    assert Path("docs/01_planning/research_guide.md") in result
    assert Path(".claude/skills/foo/SKILL.md") in result
    assert Path(".github/task-workflow.md") in result
    assert Path("CLAUDE.md") in result


def test_collect_markdown_files_includes_mmd_only_under_docs(tmp_path: Path) -> None:
    """.mmdファイルはdocs/配下のみ対象とする。"""
    _touch(tmp_path / "docs" / "diagram.mmd")
    _touch(tmp_path / ".claude" / "diagram.mmd")

    result = collect_markdown_files(project_root=tmp_path)

    assert Path("docs/diagram.mmd") in result
    assert Path(".claude/diagram.mmd") not in result


def test_collect_markdown_files_excludes_worktrees_directory(tmp_path: Path) -> None:
    """.claude/worktrees/配下は除外する（ネストしたworktreeの重複走査を避けるため）。"""
    _touch(tmp_path / ".claude" / "worktrees" / "some-task" / "docs" / "README.md")
    _touch(tmp_path / ".claude" / "skills" / "foo" / "SKILL.md")

    result = collect_markdown_files(project_root=tmp_path)

    assert not any("worktrees" in path.parts for path in result)
    assert Path(".claude/skills/foo/SKILL.md") in result


def test_collect_markdown_files_ignores_root_files_outside_target_dirs(tmp_path: Path) -> None:
    """対象外ディレクトリ（例: src/）の.mdはルート直下でなければ対象外。"""
    _touch(tmp_path / "src" / "README.md")

    result = collect_markdown_files(project_root=tmp_path)

    assert Path("src/README.md") not in result


def test_collect_markdown_files_returns_sorted_unique_list(tmp_path: Path) -> None:
    """結果は重複なくパス文字列昇順でソートされる。"""
    _touch(tmp_path / "docs" / "b.md")
    _touch(tmp_path / "docs" / "a.md")

    result = collect_markdown_files(project_root=tmp_path)

    assert result == sorted(result, key=lambda path: path.as_posix())
    assert len(result) == len(set(result))
