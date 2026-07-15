"""freshness.py（冒頭「最終更新」とgit最終コミット日の乖離検出）のテスト。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.doc_checks.freshness import check_freshness


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(repo_dir: Path) -> None:
    _git(["init", "-q"], repo_dir)
    _git(["config", "user.email", "test@example.com"], repo_dir)
    _git(["config", "user.name", "Test"], repo_dir)
    _git(["config", "commit.gpgsign", "false"], repo_dir)


def _write_and_commit(repo_dir: Path, relative_path: str, content: str, commit_date: str) -> None:
    path = repo_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(["add", relative_path], repo_dir)
    _git(
        ["commit", "-q", f"--date={commit_date}T00:00:00", "-m", "test commit"],
        repo_dir,
    )


def test_no_warning_when_within_threshold(tmp_path: Path) -> None:
    """メタ情報日付と最終コミット日の乖離が閾値以内なら警告なし。"""
    _init_repo(tmp_path)
    _write_and_commit(
        tmp_path,
        "docs/a.md",
        "# タイトル\n\n**最終更新**: 2026-01-01\n",
        commit_date="2026-01-10",
    )

    result = check_freshness(project_root=tmp_path)

    assert result == []


def test_warns_when_diff_exceeds_threshold(tmp_path: Path) -> None:
    """メタ情報日付と最終コミット日の乖離が閾値を超える場合に警告する。"""
    _init_repo(tmp_path)
    _write_and_commit(
        tmp_path,
        "docs/a.md",
        "# タイトル\n\n**最終更新**: 2026-01-01\n",
        commit_date="2026-06-01",
    )

    result = check_freshness(project_root=tmp_path, threshold_days=60)

    assert len(result) == 1
    assert result[0].file == "docs/a.md"
    assert result[0].metadata_date == "2026-01-01"
    assert result[0].last_commit_date == "2026-06-01"
    assert result[0].days_diff > 60


def test_skips_file_without_metadata_date(tmp_path: Path) -> None:
    """冒頭に「最終更新」の日付がない場合は警告しない。"""
    _init_repo(tmp_path)
    _write_and_commit(
        tmp_path,
        "docs/a.md",
        "# タイトル\n\n本文のみ\n",
        commit_date="2020-01-01",
    )

    result = check_freshness(project_root=tmp_path)

    assert result == []


def test_skips_untracked_file(tmp_path: Path) -> None:
    """gitでコミットされていないファイルは最終コミット日が取得できないため警告しない。"""
    _init_repo(tmp_path)
    path = tmp_path / "docs" / "a.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# タイトル\n\n**最終更新**: 2020-01-01\n", encoding="utf-8")

    result = check_freshness(project_root=tmp_path)

    assert result == []


def test_respects_custom_threshold(tmp_path: Path) -> None:
    """threshold_days引数でしきい値を変更できる。"""
    _init_repo(tmp_path)
    _write_and_commit(
        tmp_path,
        "docs/a.md",
        "# タイトル\n\n**最終更新**: 2026-01-01\n",
        commit_date="2026-01-10",
    )

    result = check_freshness(project_root=tmp_path, threshold_days=5)

    assert len(result) == 1
