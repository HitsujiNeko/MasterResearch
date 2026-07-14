"""ドキュメント整合性チェックの検査対象ファイル一覧を取得する。

各チェックモジュールが個別に走査ロジックを持たないよう、
検査対象の決定（対象ディレクトリ・拡張子・除外ルール）をここに集約する。
"""

from __future__ import annotations

from pathlib import Path

from src.common.config import PROJECT_ROOT

# 再帰走査の対象ディレクトリ（プロジェクトルート直下、.md のみを対象とする）
_RECURSIVE_MARKDOWN_ONLY_DIRS = (".claude", ".github")

# 走査から除外するディレクトリ名（どの階層に出現しても配下ごと除外する）
_EXCLUDED_DIR_NAMES = frozenset({"worktrees", ".git"})


def collect_markdown_files(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """検査対象の Markdown ファイル一覧を取得する。

    対象は `docs/` 配下の `.md`/`.mmd`、`.claude/`・`.github/` 配下の `.md`、
    リポジトリ直下の `.md` の3系統。

    Args:
        project_root: 走査の基準ディレクトリ。
    Returns:
        project_root からの相対パスの一覧（重複なし・パス文字列昇順）。
    """
    files: set[Path] = set()

    docs_dir = project_root / "docs"
    if docs_dir.exists():
        files.update(_walk(docs_dir, extensions=(".md", ".mmd")))

    for dir_name in _RECURSIVE_MARKDOWN_ONLY_DIRS:
        target_dir = project_root / dir_name
        if target_dir.exists():
            files.update(_walk(target_dir, extensions=(".md",)))

    files.update(path for path in project_root.glob("*.md") if path.is_file())

    relative_paths = (path.relative_to(project_root) for path in files)
    return sorted(relative_paths, key=lambda path: path.as_posix())


def _walk(directory: Path, extensions: tuple[str, ...]) -> list[Path]:
    """directory 配下を再帰的に走査し、除外ディレクトリを除いた対象ファイルを返す。"""
    results: list[Path] = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        relative_parts = path.relative_to(directory).parts[:-1]
        if _EXCLUDED_DIR_NAMES.intersection(relative_parts):
            continue
        results.append(path)
    return results
