"""論文原稿の表記規約からの機械的な逸脱を検出する。

対象は `thesis/chapters/` 配下の `.md` と `thesis/metadata.yaml` の値の行。
規約（`docs/02_methods/thesis_writing_guide.md` の4章・5章）のうち、
機械的に判定できるものだけを検出する。

- 句読点は「，」「．」を使う（「、」「。」は使わない）
- LST の単位は °C（数値に続く K・ケルビン、℃、度C は使わない）

HTML コメント（節のメタ情報欄）・コードブロック・コードスパン・YAML のコメント行は
規約の対象外（記録や記法の説明に使うため）として検査から除く。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT

_CHAPTERS_DIR = Path("thesis") / "chapters"
_METADATA_FILE = Path("thesis") / "metadata.yaml"

_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCED_CODE_PATTERN = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")

_PUNCTUATION_PATTERN = re.compile(r"[、。]")
# 数値に続く K（単位としての K）。英単語の一部（例: 5Km）は除く
_TEMPERATURE_UNIT_PATTERN = re.compile(r"℃|\d\s?度\s?C|\d\s?ケルビン|\d\s?°?K(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class NotationViolation:
    """検出された表記の逸脱1件。"""

    file: str
    line: int
    category: str
    matched_text: str


def check_thesis_notation(project_root: Path = PROJECT_ROOT) -> list[NotationViolation]:
    """原稿の句読点・温度の単位の逸脱を検出する。

    Args:
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        検出結果（ファイルパス・行番号の昇順）。原稿が無ければ空リスト。
    """
    violations: list[NotationViolation] = []
    for path in _collect_targets(project_root):
        relative = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        masked = _mask_yaml(text) if path.suffix == ".yaml" else _mask_markdown(text)
        for line_number, line in enumerate(masked.splitlines(), start=1):
            violations.extend(_check_line(relative, line_number, line))
    return violations


def _collect_targets(project_root: Path) -> list[Path]:
    """検査対象ファイルをパス昇順で返す。"""
    targets: list[Path] = []
    chapters_dir = project_root / _CHAPTERS_DIR
    if chapters_dir.exists():
        targets.extend(chapters_dir.rglob("*.md"))
    metadata = project_root / _METADATA_FILE
    if metadata.exists():
        targets.append(metadata)
    return sorted(targets, key=lambda p: p.as_posix())


def _blank_keep_newlines(match: re.Match[str]) -> str:
    """一致範囲を改行だけ残して空にする（行番号を保つため）。"""
    return "\n" * match.group(0).count("\n")


def _mask_markdown(text: str) -> str:
    """HTML コメント・コードブロック・コードスパンを除く（行数は保つ）。"""
    text = _HTML_COMMENT_PATTERN.sub(_blank_keep_newlines, text)
    text = _FENCED_CODE_PATTERN.sub(_blank_keep_newlines, text)
    return _INLINE_CODE_PATTERN.sub("", text)


def _mask_yaml(text: str) -> str:
    """YAML のコメント行を空にする（行数は保つ）。"""
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def _check_line(file: str, line_number: int, line: str) -> list[NotationViolation]:
    """1行分のテキストを検査する。"""
    results = [
        NotationViolation(file, line_number, "句読点", match.group(0))
        for match in _PUNCTUATION_PATTERN.finditer(line)
    ]
    results.extend(
        NotationViolation(file, line_number, "温度の単位", match.group(0))
        for match in _TEMPERATURE_UNIT_PATTERN.finditer(line)
    )
    return results
