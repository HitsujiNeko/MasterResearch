"""冒頭「最終更新」日付と最終コミット日の乖離を警告として列挙する。

更新日の乖離は違反ではなく注意情報のため、CI を fail させない
（呼び出し側はこの結果を終了コードに反映しない運用とする）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.heading_window import extract_heading_window
from src.doc_checks.scan_targets import collect_docs_markdown_files

_META_DATE_PATTERN = re.compile(r"最終更新[^0-9]*(\d{4}-\d{2}-\d{2})")
_DEFAULT_THRESHOLD_DAYS = 60


@dataclass(frozen=True)
class FreshnessWarning:
    """冒頭「最終更新」と最終コミット日の乖離が閾値を超える1件。"""

    file: str
    metadata_date: str
    last_commit_date: str
    days_diff: int


def check_freshness(
    project_root: Path = PROJECT_ROOT,
    threshold_days: int = _DEFAULT_THRESHOLD_DAYS,
) -> list[FreshnessWarning]:
    """冒頭「最終更新」日付とgit最終コミット日の乖離を列挙する。"""
    warnings: list[FreshnessWarning] = []
    for relative_path in collect_docs_markdown_files(project_root):
        text = (project_root / relative_path).read_text(encoding="utf-8")
        metadata_date = _extract_metadata_date(text)
        if metadata_date is None:
            continue

        commit_date = _last_commit_date(project_root, relative_path)
        if commit_date is None:
            continue

        days_diff = abs((commit_date - metadata_date).days)
        if days_diff > threshold_days:
            warnings.append(
                FreshnessWarning(
                    file=relative_path.as_posix(),
                    metadata_date=metadata_date.isoformat(),
                    last_commit_date=commit_date.isoformat(),
                    days_diff=days_diff,
                )
            )
    return warnings


def _extract_metadata_date(text: str) -> date | None:
    """冒頭見出し直後の「最終更新」日付を抽出する。

    Args:
        text: 判定対象のファイル本文。
    Returns:
        抽出した日付。記載がない・解析できない場合は None。
    """
    window = extract_heading_window(text)
    if window is None:
        return None
    match = _META_DATE_PATTERN.search(window)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _last_commit_date(project_root: Path, relative_path: Path) -> date | None:
    """git履歴からファイルの最終コミット日を取得する。

    Args:
        project_root: gitコマンドを実行するリポジトリのルートディレクトリ。
        relative_path: project_root からの相対パス。
    Returns:
        最終コミット日。git履歴が取得できない場合は None。
    """
    result = subprocess.run(
        ["git", "log", "-1", "--format=%as", "--", relative_path.as_posix()],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        return None
    try:
        return date.fromisoformat(output)
    except ValueError:
        return None
