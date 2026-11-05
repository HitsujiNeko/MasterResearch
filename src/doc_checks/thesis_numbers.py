"""論文の節の数値を、依拠する正本と照合する。

各節のメタ情報欄「依拠する正本」に挙げた Markdown の正本を読み、本文の数値が
正本に現れるかを確認する。検出するのは次の2種類である。

- 旧観測のみ: 正本のうち旧観測の章（`LEGACY_CHAPTERS` に定義）にだけ現れる数値。
  主採用の観測の値を書くべき箇所に、旧観測の値を混ぜた疑いがある
- 正本に無い: 依拠する正本のどこにも現れない数値。転記の誤り・再計算した値の直書き・
  依拠する正本の書き漏れの疑いがある

照合の対象は、小数部を持つ数値と、桁区切りのある数値に限る（整数は年・節番号・
個数など正本と無関係な値が多く、誤検出が増えるため）。見出し、引用キー、
図表のラベル、年、節番号は対象から除く。

結果は警告であり、違反とは限らない（正本に書かれていない自明な値など）。
終了コードは常に0とし、CI の fail 対象にしない。

コマンドラインからの使い方:
    python -m src.doc_checks.thesis_numbers
        状態が「未着手」でない全節を照合する
    python -m src.doc_checks.thesis_numbers {節ファイル...}
        指定した節だけ照合する
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.thesis_source_tracking import collect_section_files, parse_section_sources

# 旧観測の章（正本のパス → 章番号の集合）。正本のうち、主採用の観測以外の
# 結果を記録している章を定義する。主採用の章は、ここに無い章（8章など）とする。
LEGACY_CHAPTERS: dict[str, frozenset[str]] = {
    "docs/03_results/limited_analysis_results.md": frozenset({"2", "3", "4", "5", "6", "7"}),
}

KIND_LEGACY_ONLY = "旧観測のみ"
KIND_NOT_IN_SOURCE = "正本に無い"

_STATE_NOT_STARTED = "未着手"

_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCED_CODE_PATTERN = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")
# 引用キー・図表ラベル・参照（例: [@S1]、{#fig:lst_map}、@fig:lst_map）、URL
_REFERENCE_PATTERN = re.compile(r"\[@[^\]]*\]|\{#[^}]*\}|@(?:fig|tbl|eq):\w+|https?://\S+")
# 図表・式の番号（例: 図-1、表-2、式(3)）と、節・章の番号（例: 3.2節、第2章）
_NUMBERED_REFERENCE_PATTERN = re.compile(r"[図表]-\d+|式\(\d+\)|\d+(?:\.\d+)*\s?[節章項]|第\d+章")
_HEADING_PATTERN = re.compile(r"^#{1,6}\s")
_CHAPTER_HEADING_PATTERN = re.compile(r"^##\s+(?P<chapter>\d+)\.\s")
# 小数部を持つ数値、または3桁区切りの数値（英数字・小数点に隣接するものは除く）
_NUMBER_PATTERN = re.compile(r"(?<![\w.])(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)(?![\w])")
_NUMBER_KEY_DIGITS = 6


@dataclass(frozen=True)
class NumberFinding:
    """照合で見つかった1件。"""

    section_file: str
    line: int
    kind: str
    number_text: str
    source_paths: tuple[str, ...]


def number_key(number_text: str) -> float:
    """数値の文字列を、桁区切りと末尾のゼロの違いを吸収した照合キーにする。

    Args:
        number_text: `12.30` や `1,234.5` のような数値の文字列。
    Returns:
        照合に使う値。
    """
    return round(float(number_text.replace(",", "")), _NUMBER_KEY_DIGITS)


def extract_numbers(text: str) -> list[tuple[int, str]]:
    """本文から照合対象の数値を（行番号, 文字列）で取り出す。

    HTML コメント・コード・見出し・引用キー・図表ラベル・図表や節の番号を除く。

    Args:
        text: 節ファイルの本文。
    Returns:
        出現順の（行番号, 数値の文字列）。
    """
    text = _HTML_COMMENT_PATTERN.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = _FENCED_CODE_PATTERN.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = _INLINE_CODE_PATTERN.sub("", text)
    results: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _HEADING_PATTERN.match(line):
            continue
        line = _REFERENCE_PATTERN.sub(" ", line)
        line = _NUMBERED_REFERENCE_PATTERN.sub(" ", line)
        results.extend((line_number, m.group("number")) for m in _NUMBER_PATTERN.finditer(line))
    return results


def index_source_numbers(text: str) -> dict[float, set[str]]:
    """正本の数値を、現れる章の集合に対応付ける。

    章は `## N.` 見出しで区切り、最初の章見出しより前は章 `0` とする。

    Args:
        text: 正本（Markdown）の本文。
    Returns:
        数値の照合キー → その数値が現れる章番号の集合。
    """
    index: dict[float, set[str]] = {}
    chapter = "0"
    for line in text.splitlines():
        heading = _CHAPTER_HEADING_PATTERN.match(line)
        if heading:
            chapter = heading.group("chapter")
        for match in _NUMBER_PATTERN.finditer(line):
            index.setdefault(number_key(match.group("number")), set()).add(chapter)
    return index


def check_section_numbers(
    section_file: Path, project_root: Path = PROJECT_ROOT
) -> list[NumberFinding]:
    """1つの節の数値を、依拠する正本と照合する。

    Args:
        section_file: 節ファイルのパス（project_root からの相対、または絶対）。
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        見つかった項目。依拠する正本（Markdown）が無い節・状態が未着手の節は空リスト。
    """
    absolute = section_file if section_file.is_absolute() else project_root / section_file
    relative = absolute.relative_to(project_root).as_posix()
    text = absolute.read_text(encoding="utf-8")
    parsed = parse_section_sources(text, relative)
    if parsed.state == _STATE_NOT_STARTED:
        return []

    sources = _load_sources(project_root, [ref.path for ref in parsed.references])
    if not sources:
        return []

    findings: list[NumberFinding] = []
    source_paths = tuple(sorted(sources))
    for line_number, number_text in extract_numbers(text):
        kind = _classify(number_key(number_text), sources)
        if kind is not None:
            findings.append(NumberFinding(relative, line_number, kind, number_text, source_paths))
    return findings


def _load_sources(
    project_root: Path, reference_paths: list[str]
) -> dict[str, dict[float, set[str]]]:
    """依拠する正本（Markdown）を読み、正本のパス → 数値の索引を返す。"""
    sources: dict[str, dict[float, set[str]]] = {}
    for reference in reference_paths:
        target = project_root / reference.rstrip("/")
        if target.is_dir():
            files = sorted(target.rglob("*.md"))
        elif target.is_file() and target.suffix == ".md":
            files = [target]
        else:
            continue
        for file in files:
            sources[file.relative_to(project_root).as_posix()] = index_source_numbers(
                file.read_text(encoding="utf-8")
            )
    return sources


def _classify(key: float, sources: dict[str, dict[float, set[str]]]) -> str | None:
    """数値を正本と照合し、指摘の種別を返す（問題なければ None）。"""
    found_in_any = False
    for path, index in sources.items():
        chapters = index.get(key)
        if not chapters:
            continue
        found_in_any = True
        legacy = LEGACY_CHAPTERS.get(path)
        if legacy is None or not chapters <= legacy:
            return None
    return KIND_LEGACY_ONLY if found_in_any else KIND_NOT_IN_SOURCE


def format_finding(finding: NumberFinding) -> str:
    """指摘1件を表示用の1行にする。"""
    sources = ", ".join(finding.source_paths)
    return (
        f"{finding.section_file}:{finding.line} [{finding.kind}] {finding.number_text}"
        f"（依拠する正本: {sources}）"
    )


def main(argv: list[str] | None = None, project_root: Path = PROJECT_ROOT) -> int:
    """節の数値を照合し、結果を表示する。終了コードは常に0。"""
    parser = argparse.ArgumentParser(description="論文の節の数値を依拠する正本と照合する")
    parser.add_argument("sections", nargs="*", type=Path, help="照合する節ファイル（省略時は全節）")
    args = parser.parse_args(argv)

    sections = args.sections or collect_section_files(project_root)
    findings: list[NumberFinding] = []
    for section in sections:
        findings.extend(check_section_numbers(section, project_root))

    if findings:
        print("[WARN] 論文の数値の照合（要確認。fail 対象外）:")
        for finding in findings:
            print(f"  - {format_finding(finding)}")
    else:
        print("[OK] 照合対象の数値はすべて依拠する正本で確認できました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
