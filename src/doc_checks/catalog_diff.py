"""docs/README.md のカタログと実ファイルの差分を検出する。

`docs/` 配下の実ファイル一覧と `docs/README.md` の
「全ドキュメントカタログ」セクションに列挙されたリンク先パスを突合する。

ディレクトリ構造図（```text 構造```ブロック）との矛盾検出は、
ワイルドカード表記（例: `S2-S8_*.md`）や自由記述コメントを含み
決定的な突合が困難なため対象外とする（意味的判断が必要な範囲として
#126 の意味的チェックに委ねる）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT

_CATALOG_SECTION_START = "## 📊 全ドキュメントカタログ"
_SECTION_HEADING_PREFIX = "## "
_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

# カタログ掲載有無の差分検出対象外とするパス（docs/README.md 本文の既存方針に対応）
_EXCLUDED_PREFIXES = ("01_planning/gis_data/",)


@dataclass(frozen=True)
class CatalogDiffResult:
    """カタログ差分チェックの結果。"""

    missing_from_catalog: list[str]
    """実ファイルは存在するがカタログに未掲載のパス一覧。"""
    missing_file: list[str]
    """カタログに記載があるが実ファイルが存在しないパス一覧。"""

    @property
    def has_violations(self) -> bool:
        return bool(self.missing_from_catalog or self.missing_file)


def check_catalog_diff(project_root: Path = PROJECT_ROOT) -> CatalogDiffResult:
    """docs/README.md カタログと実ファイルの差分を検出する。"""
    docs_dir = project_root / "docs"
    readme_text = (docs_dir / "README.md").read_text(encoding="utf-8")

    catalog_paths = _extract_catalog_paths(readme_text)
    actual_paths = _collect_actual_doc_paths(docs_dir)

    return CatalogDiffResult(
        missing_from_catalog=sorted(actual_paths - catalog_paths),
        missing_file=sorted(catalog_paths - actual_paths),
    )


def _extract_catalog_paths(readme_text: str) -> set[str]:
    """「全ドキュメントカタログ」セクション内のリンク先パス一覧を抽出する。

    テーブル行・箇条書きのいずれの形式のリンクも対象とする
    （例: 04_archive の「構造化要約（現存ファイル）」は箇条書き）。
    """
    lines = readme_text.splitlines()
    start_index = next(
        (i for i, line in enumerate(lines) if line.strip() == _CATALOG_SECTION_START),
        None,
    )
    if start_index is None:
        raise ValueError(f"カタログセクションが見つかりません: {_CATALOG_SECTION_START}")

    section_lines: list[str] = []
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith(_SECTION_HEADING_PREFIX):
            break
        section_lines.append(line)

    paths: set[str] = set()
    for line in section_lines:
        for match in _LINK_PATTERN.finditer(line):
            target = match.group(1)
            if target.startswith("http://") or target.startswith("https://"):
                continue
            paths.add(_normalize(target))
    return {path for path in paths if not _is_excluded(path)}


def _collect_actual_doc_paths(docs_dir: Path) -> set[str]:
    """docs/ 配下の実ファイル一覧を README.md からの相対パス表記で取得する。"""
    paths: set[str] = set()
    for path in docs_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(docs_dir).as_posix()
        if _is_excluded(relative):
            continue
        paths.add(relative)
    return paths


def _normalize(target: str) -> str:
    """リンク先パスからアンカー(#...)を除去し、`./`プレフィックスを取り除く。"""
    path = target.split("#", 1)[0]
    if path.startswith("./"):
        path = path[2:]
    return path


def _is_excluded(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)
