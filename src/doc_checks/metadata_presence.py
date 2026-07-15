"""ファイル冒頭「最終更新」メタ情報の有無を検出する。

冒頭見出し（`# タイトル`）から5行以内に「最終更新」の記載があるかを確認する。
本文中・末尾の日付記載は「冒頭メタ情報あり」と判定しない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.scan_targets import collect_docs_markdown_files

_HEADING_PATTERN = re.compile(r"^#\s+\S")
_LOOKAHEAD_LINES = 5
_META_KEYWORD = "最終更新"

# 独自メタ形式・カタログ文書自体など、判定対象外とするファイル
_EXCLUDED_PATHS = frozenset(
    {
        "docs/README.md",
        "docs/04_archive/templates/structured_summary_template.md",
    }
)
_EXCLUDED_PATTERNS = (re.compile(r"^docs/04_archive/02_structured_summaries/S.*\.md$"),)


@dataclass(frozen=True)
class MissingMetadata:
    """冒頭メタ情報が欠落しているファイル1件。"""

    file: str


def check_metadata_presence(project_root: Path = PROJECT_ROOT) -> list[MissingMetadata]:
    """冒頭「最終更新」メタ情報が欠落しているファイルを検出する。"""
    violations: list[MissingMetadata] = []
    for relative_path in collect_docs_markdown_files(project_root):
        posix_path = relative_path.as_posix()
        if posix_path.endswith(".mmd") or _is_excluded(posix_path):
            continue
        text = (project_root / relative_path).read_text(encoding="utf-8")
        if not _has_metadata_near_heading(text):
            violations.append(MissingMetadata(file=posix_path))
    return violations


def _is_excluded(posix_path: str) -> bool:
    if posix_path in _EXCLUDED_PATHS:
        return True
    return any(pattern.match(posix_path) for pattern in _EXCLUDED_PATTERNS)


def _has_metadata_near_heading(text: str) -> bool:
    lines = text.splitlines()
    heading_index = next((i for i, line in enumerate(lines) if _HEADING_PATTERN.match(line)), None)
    if heading_index is None:
        return False
    window = lines[heading_index + 1 : heading_index + 1 + _LOOKAHEAD_LINES]
    return any(_META_KEYWORD in line for line in window)
