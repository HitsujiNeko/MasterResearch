"""CLAUDE.md 最小用語集に基づく用語の表記揺れを検出する。

対象は `docs/` 配下（`docs/04_archive/` は先行研究の引用文脈のため除外）。
検出するのは規約表記からの機械的に判定可能な逸脱（大文字小文字・区切り文字・
空白混入）と、分析シナリオの旧呼び名の残りのみ。

分析シナリオは論文・ドキュメントでの呼び名（衛星データのみ／衛星＋公開GISデータ／
測量建物置き換え）に改めており、旧呼び名（Satellite Only・Limited シナリオ・
Full シナリオ）が本文に残っていれば「シナリオ名（旧呼び名）」として検出する。
コード上の識別子や出力値の引用はインラインコード（バックティック）やコードブロックで
書く規約のため、インラインコードとフェンス付きコードブロックの中は検出しない。
コードブロックの判定は CommonMark に合わせ、閉じていないブロックは文書末まで続くとみなす。
提出済み資料（`docs/03_results/GIS_IDEAS_*.md`）も当時の記録として対象外とする。
新しい呼び名の表記揺れ（「衛星＋公開GIS」のような短縮等）は意味判断を要するため
対象外とし、`check-docs-consistency` スキルの意味的チェックに委ねる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.scan_targets import collect_docs_markdown_files

_EXCLUDED_PREFIX = "docs/04_archive/"
# シナリオ名（旧呼び名）の検出だけを除外するファイル（提出済み資料）
_SCENARIO_EXCLUDED_PREFIX = "docs/03_results/GIS_IDEAS_"

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

# シナリオ名（旧呼び名）: 「Satellite Only」とその大文字小文字・空白の揺れ。
# 新しい英語表記「Satellite only」とは大文字の O/o だけで分かれるため、
# 大文字小文字を区別して「Satellite only」と完全一致するものだけを許容する。
_SATELLITE_ONLY_PATTERN = re.compile(rf"(?i){_L}satellite\s+only{_R}")
_SATELLITE_ONLY_NEW_ENGLISH = "Satellite only"
# シナリオ名（旧呼び名）: 「Limited」「Full」は「シナリオ」直前に現れる場合のみ対象
# （単独の英単語として本文中に頻出するため、誤検出を避けて範囲を絞る）。
# 「Limited・Full シナリオ」のような並記では、先頭の語も「シナリオ」に掛かるため検出する
_LIMITED_FULL_SCENARIO_PATTERN = re.compile(
    rf"(?i){_L}(Limited|Full)(?=(?:\s?[・/／]\s?(?:Limited|Full))*\s?シナリオ)"
)
# インラインコード（同じ数のバックティックで囲まれた範囲）
_INLINE_CODE_PATTERN = re.compile(r"(`+)(.+?)\1")
# フェンス付きコードブロックのフェンス行（字下げ3文字まで・``` か ~~~ を3つ以上）。
# group(1) がフェンス記号の並び、group(2) がその後ろ（info string）
_FENCE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_SCENARIO_CATEGORY = "シナリオ名（旧呼び名）"

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
        scenario_target = not posix_path.startswith(_SCENARIO_EXCLUDED_PREFIX)
        lines = text.splitlines()
        in_code_block = _code_block_mask(lines)
        for line_number, (line, in_block) in enumerate(zip(lines, in_code_block), start=1):
            # コードブロック内（出力例・CLI 例）はインラインコードと同じくシナリオ名を検査しない
            check_scenario = scenario_target and not in_block
            violations.extend(
                _check_line(posix_path, line_number, line, check_scenario=check_scenario)
            )
    return violations


def _code_block_mask(lines: list[str]) -> list[bool]:
    """各行がフェンス付きコードブロック（フェンス行を含む）に属するかを判定する。

    CommonMark に合わせ、ブロックは開始フェンスと同じ記号で長さが同じか長く、
    info string を持たないフェンス行でだけ閉じる。閉じていないブロックは文書末まで続く。
    バッククォートの開始フェンスは、info string にバッククォートを含む場合はフェンスとみなさない。

    Args:
        lines: 文書の行のリスト。
    Returns:
        行ごとの真偽値のリスト（True はコードブロック内）。
    """
    mask: list[bool] = []
    open_fence: str | None = None
    for line in lines:
        match = _FENCE_PATTERN.match(line)
        if open_fence is None:
            is_open = match is not None and not (
                match.group(1).startswith("`") and "`" in match.group(2)
            )
            if is_open:
                open_fence = match.group(1)
            mask.append(is_open)
            continue
        mask.append(True)
        if (
            match is not None
            and match.group(1)[0] == open_fence[0]
            and len(match.group(1)) >= len(open_fence)
            # CommonMark で閉じフェンスの後ろに許されるのは半角空白とタブだけ
            and match.group(2).strip(" \t") == ""
        ):
            open_fence = None
    return mask


def _check_line(
    file: str, line_number: int, line: str, *, check_scenario: bool = True
) -> list[TerminologyViolation]:
    """1行分のテキストに対して全カテゴリの表記揺れパターンを検査する。

    Args:
        file: 検査対象ファイルのプロジェクトルート相対パス。
        line_number: 行番号（1始まり）。
        line: 検査対象の行テキスト。
        check_scenario: シナリオ名（旧呼び名）を検査するか。提出済み資料と
            フェンス付きコードブロック内の行では False。
    Returns:
        検出された表記揺れのリスト。
    """
    results: list[TerminologyViolation] = []

    for match in _LST_UNIT_PATTERN.finditer(line):
        results.append(_violation(file, line_number, "LST単位", match.group(0)))

    if check_scenario:
        results.extend(_check_scenario_names(file, line_number, line))

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


def _check_scenario_names(file: str, line_number: int, line: str) -> list[TerminologyViolation]:
    """インラインコードの外側に残ったシナリオの旧呼び名を検出する。

    Args:
        file: 検査対象ファイルのプロジェクトルート相対パス。
        line_number: 行番号（1始まり）。
        line: 検査対象の行テキスト。
    Returns:
        検出された旧呼び名のリスト。
    """
    # インラインコードは同じ長さの空白に置き換え、識別子・出力値の引用を検出から外す
    masked = _INLINE_CODE_PATTERN.sub(lambda m: " " * len(m.group(0)), line)
    results: list[TerminologyViolation] = []

    for match in _SATELLITE_ONLY_PATTERN.finditer(masked):
        if match.group(0) != _SATELLITE_ONLY_NEW_ENGLISH:
            results.append(_violation(file, line_number, _SCENARIO_CATEGORY, match.group(0)))

    for match in _LIMITED_FULL_SCENARIO_PATTERN.finditer(masked):
        results.append(_violation(file, line_number, _SCENARIO_CATEGORY, match.group(1)))

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
