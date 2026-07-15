"""CLAUDE.md 最小用語集に基づく用語の表記揺れを検出する。

対象は `docs/` 配下（`docs/04_archive/` は先行研究の引用文脈のため除外）。
検出するのは規約表記からの機械的に判定可能な逸脱（大文字小文字・区切り文字・
空白混入）のみ。「日本語訳との混在」（例: Satellite Only の代わりに
「衛星のみ」と訳す）のような意味判断を要する揺れは対象外とし、
#126 の意味的チェックに委ねる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.scan_targets import collect_docs_markdown_files

_EXCLUDED_PREFIX = "docs/04_archive/"

# Unicode対応の \b は日本語文字も「単語文字」とみなすため、
# 英字直後に日本語が続くケース（例: "RQ 1について"）で境界判定に失敗する。
# また `analysis_rq3_satellite_only.py` のようなスネークケースの識別子・
# ファイル名を誤検出しないよう、アンダースコアも境界内側の文字として扱う。
# ASCII英数字・アンダースコアのみを対象とした独自の境界で \b を代替する。
_L = r"(?<![A-Za-z0-9_])"  # 左境界
_R = r"(?![A-Za-z0-9_])"  # 右境界

# LST単位: °C 以外の表記（℃・度C・数値+ケルビン・数値+K）。
# 「ケルビン」は他システムの単位を説明する地の文（例: 「原典実装はケルビン
# だが本研究では°Cに変換」）でも使われるため、数値を伴う場合のみ誤表記とみなす。
_LST_UNIT_PATTERN = re.compile(rf"℃|度C|\d+\s?ケルビン|\d+\s?K{_R}")

# シナリオ名: 「Satellite Only」の大文字小文字・空白の揺れ
_SATELLITE_ONLY_PATTERN = re.compile(rf"(?i){_L}satellite\s+only{_R}")
# シナリオ名: 「Limited」「Full」は「シナリオ」直前に現れる場合のみ対象
# （単独の英単語として本文中に頻出するため、誤検出を避けて範囲を絞る）
_LIMITED_FULL_SCENARIO_PATTERN = re.compile(rf"(?i){_L}(Limited|Full)(?=\s?シナリオ)")

# 座標系: EPSG:NNNN 形式からの逸脱（空白・ハイフン区切り、小文字epsg等）
_EPSG_MENTION_PATTERN = re.compile(rf"(?i){_L}epsg[\s:-]*\d{{3,6}}{_R}")
_EPSG_CANONICAL_PATTERN = re.compile(r"^EPSG:\d+$")
# 座標系: WGS84 の空白混入
_WGS84_SPACED_PATTERN = re.compile(rf"(?i){_L}WGS\s+84{_R}")
# 座標系: VN-2000 のハイフン欠落・空白混入
_VN2000_VARIANT_PATTERN = re.compile(rf"(?i){_L}VN[\s-]?2000{_R}")

# RQ表記: RQ1/RQ2/RQ3 からの逸脱（空白混入・小文字）
_RQ_MENTION_PATTERN = re.compile(rf"(?i){_L}RQ\s*[123]{_R}")


@dataclass(frozen=True)
class TerminologyViolation:
    """検出された表記揺れ1件。"""

    file: str
    line: int
    category: str
    matched_text: str


def check_terminology(project_root: Path = PROJECT_ROOT) -> list[TerminologyViolation]:
    """docs/ 配下（04_archive/ 除く）の用語の表記揺れを検出する。"""
    violations: list[TerminologyViolation] = []
    for relative_path in collect_docs_markdown_files(project_root):
        posix_path = relative_path.as_posix()
        if posix_path.startswith(_EXCLUDED_PREFIX):
            continue
        text = (project_root / relative_path).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            violations.extend(_check_line(posix_path, line_number, line))
    return violations


def _check_line(file: str, line_number: int, line: str) -> list[TerminologyViolation]:
    """1行分のテキストに対して全カテゴリの表記揺れパターンを検査する。

    Args:
        file: 検査対象ファイルのプロジェクトルート相対パス。
        line_number: 行番号（1始まり）。
        line: 検査対象の行テキスト。
    Returns:
        検出された表記揺れのリスト。
    """
    results: list[TerminologyViolation] = []

    for match in _LST_UNIT_PATTERN.finditer(line):
        results.append(_violation(file, line_number, "LST単位", match.group(0)))

    for match in _SATELLITE_ONLY_PATTERN.finditer(line):
        if match.group(0) != "Satellite Only":
            results.append(_violation(file, line_number, "シナリオ名", match.group(0)))

    for match in _LIMITED_FULL_SCENARIO_PATTERN.finditer(line):
        text = match.group(1)
        if text not in ("Limited", "Full"):
            results.append(_violation(file, line_number, "シナリオ名", text))

    for match in _EPSG_MENTION_PATTERN.finditer(line):
        text = match.group(0)
        if not _EPSG_CANONICAL_PATTERN.match(text):
            results.append(_violation(file, line_number, "座標系", text))

    for match in _WGS84_SPACED_PATTERN.finditer(line):
        results.append(_violation(file, line_number, "座標系", match.group(0)))

    for match in _VN2000_VARIANT_PATTERN.finditer(line):
        if match.group(0) != "VN-2000":
            results.append(_violation(file, line_number, "座標系", match.group(0)))

    for match in _RQ_MENTION_PATTERN.finditer(line):
        text = match.group(0)
        canonical = f"RQ{text[-1]}"
        if text != canonical:
            results.append(_violation(file, line_number, "RQ表記", text))

    return results


def _violation(file: str, line: int, category: str, matched_text: str) -> TerminologyViolation:
    """TerminologyViolation を組み立てる。

    Args:
        file: 検出対象ファイルのプロジェクトルート相対パス。
        line: 検出行の行番号。
        category: 表記揺れのカテゴリ名。
        matched_text: 検出された実際の文字列。
    Returns:
        組み立てた TerminologyViolation。
    """
    return TerminologyViolation(file=file, line=line, category=category, matched_text=matched_text)
