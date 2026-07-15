"""Markdown ファイル間の相対パスリンク切れを検出する。

`docs/`・`.claude/`・`.github/`・リポジトリ直下の Markdown を対象に、
相対パスリンクのリンク先が実在するかを検証する。外部URL（http/https）は
対象外。`path#anchor` 形式はパス部分のみを検証し、見出しアンカーの
妥当性は検証しない（check_spec.md 項目2の方針に従う）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.scan_targets import collect_markdown_files

_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_CODE_FENCE_PATTERN = re.compile(r"```.*?```", re.DOTALL)
_EXTERNAL_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


@dataclass(frozen=True)
class BrokenLink:
    """検出されたリンク切れ1件。"""

    source_file: str
    target: str


def check_broken_links(project_root: Path = PROJECT_ROOT) -> list[BrokenLink]:
    """収集した Markdown ファイル群の相対パスリンクが解決できるか検証する。"""
    broken: list[BrokenLink] = []
    for relative_path in collect_markdown_files(project_root):
        file_path = project_root / relative_path
        text = _strip_code_fences(file_path.read_text(encoding="utf-8"))
        for target in _extract_link_targets(text):
            if _is_broken(target, file_path):
                broken.append(BrokenLink(source_file=relative_path.as_posix(), target=target))
    return broken


def _strip_code_fences(text: str) -> str:
    """フェンスコードブロック内のサンプル記法を誤検出しないよう除去する。"""
    return _CODE_FENCE_PATTERN.sub("", text)


def _extract_link_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in _LINK_PATTERN.finditer(text):
        raw = match.group(1).strip()
        if not raw:
            continue
        first_token = raw.split()[0].strip("<>")
        if first_token:
            targets.append(first_token)
    return targets


def _is_broken(target: str, source_file: Path) -> bool:
    if target.startswith("mailto:") or _EXTERNAL_SCHEME_PATTERN.match(target):
        return False
    path_part = target.split("#", 1)[0]
    if not path_part:
        return False
    resolved = (source_file.parent / path_part).resolve()
    return not resolved.exists()
