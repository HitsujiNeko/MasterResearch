"""論文の節が依拠する正本の更新を検出する（論文の追従チェック）。

`thesis/chapters/` の各ファイル冒頭のメタ情報欄（HTML コメント）にある
「依拠する正本:」の各行 `- {パス} @ {ハッシュ}` を読み、記録されたハッシュと
正本の現在の内容のハッシュ（HEAD 時点の git の blob ハッシュ。ディレクトリを
正本とした場合は tree ハッシュ）を比較する。
一致しない節を「要見直し」として列挙する。

ハッシュにコミットハッシュではなく blob ハッシュを使うのは、squash merge により
執筆ブランチ上のコミットハッシュがマージ後の履歴から消えるためである
（blob ハッシュはファイルの内容だけで決まり、どのブランチで記録しても比較できる）。

論文の追従待ちは違反ではなく注意情報のため、CI を fail させない
（呼び出し側はこの結果を終了コードに反映しない運用とする）。

コマンドラインからの使い方:
    python -m src.doc_checks.thesis_source_tracking
        検出結果を表示する
    python -m src.doc_checks.thesis_source_tracking --stamp {節ファイル...}
        指定した節の正本のハッシュを現在の値に書き換える（執筆時・見直し後の記録）
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT

# 論文の原稿を置くディレクトリ（プロジェクトルートからの相対パス）
THESIS_CHAPTERS_DIR = Path("thesis") / "chapters"

# 記録・表示に使う短縮ハッシュの桁数
SHORT_HASH_LENGTH = 10

# 検出結果の種別
KIND_UPDATED = "正本が更新された"
KIND_MISSING = "正本が見つからない"
KIND_NO_HASH = "ハッシュ未記録"
KIND_MALFORMED = "書式不正"

# 本文が無く追従の対象にならない節の状態（この状態の節は検査しない）
UNSTARTED_STATE = "未着手"

_STATE_PATTERN = re.compile(r"^状態\s*[:：]\s*(?P<state>\S+)\s*$")
_SOURCES_KEY_PATTERN = re.compile(r"^依拠する正本\s*[:：]\s*$")
_ENTRY_PATTERN = re.compile(r"^\s+-\s+(?P<path>\S+)(?:\s+@\s+(?P<hash>[0-9a-fA-F]{7,40}))?\s*$")
_ENTRY_LINE_PATTERN = re.compile(r"^\s+-\s")
_PLACEHOLDER_PATTERN = re.compile(r"^\s+-\s+（.*）\s*$")


@dataclass(frozen=True)
class SourceReference:
    """節ファイルに記録された依拠する正本の1件。"""

    section_file: str
    line: int
    path: str
    recorded_hash: str | None


@dataclass(frozen=True)
class TrackingFinding:
    """追従チェックで見つかった1件（要見直し・未記録・書式不正）。"""

    section_file: str
    line: int
    kind: str
    source_path: str
    recorded_hash: str | None = None
    current_hash: str | None = None

    @property
    def diff_command(self) -> str | None:
        """正本の変更内容を確認するコマンドを返す（正本が更新された場合のみ）。"""
        if self.kind != KIND_UPDATED or self.recorded_hash is None or self.current_hash is None:
            return None
        return f"git diff {self.recorded_hash} {self.current_hash}"


@dataclass(frozen=True)
class _ParsedSection:
    """1つの節ファイルを解析した結果。"""

    references: list[SourceReference]
    malformed: list[TrackingFinding]
    state: str | None = None


def collect_section_files(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """検査対象の節ファイル（`thesis/chapters/` 配下の `.md`）を列挙する。

    Args:
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        project_root からの相対パスの一覧（パス文字列昇順）。
    """
    chapters_dir = project_root / THESIS_CHAPTERS_DIR
    if not chapters_dir.exists():
        return []
    return sorted(
        (path.relative_to(project_root) for path in chapters_dir.rglob("*.md")),
        key=lambda path: path.as_posix(),
    )


def parse_section_sources(text: str, section_file: str) -> _ParsedSection:
    """節ファイル冒頭のメタ情報欄から「依拠する正本」を抽出する。

    メタ情報欄はファイル先頭の HTML コメント（`<!--` 〜 `-->`）とする。
    「依拠する正本:」の行に続く字下げされた `- ` 行を1件ずつ読む。
    `- （執筆時に記入）` のような全角括弧だけのプレースホルダは無視する。
    あわせて「状態:」の値も読む。

    Args:
        text: 節ファイルの本文。
        section_file: 結果に記録する節ファイルのパス（表示用）。
    Returns:
        抽出した正本の一覧、書式に合わない行の一覧、状態。
    """
    references: list[SourceReference] = []
    malformed: list[TrackingFinding] = []
    state: str | None = None

    lines = text.splitlines()
    if not lines or not lines[0].lstrip("﻿").startswith("<!--"):
        return _ParsedSection(references, malformed)

    in_sources = False
    for index, line in enumerate(lines[1:], start=2):
        if line.strip().startswith("-->"):
            break
        state_match = _STATE_PATTERN.match(line)
        if state_match:
            state = state_match.group("state")
            in_sources = False
            continue
        if _SOURCES_KEY_PATTERN.match(line):
            in_sources = True
            continue
        if not in_sources:
            continue
        if not _ENTRY_LINE_PATTERN.match(line):
            # 字下げされた `- ` 以外の行が来たら「依拠する正本」の欄は終わり
            in_sources = False
            continue
        if _PLACEHOLDER_PATTERN.match(line):
            continue
        match = _ENTRY_PATTERN.match(line)
        if match is None:
            malformed.append(
                TrackingFinding(
                    section_file=section_file,
                    line=index,
                    kind=KIND_MALFORMED,
                    source_path=line.strip(),
                )
            )
            continue
        recorded_hash = match.group("hash")
        references.append(
            SourceReference(
                section_file=section_file,
                line=index,
                path=match.group("path"),
                recorded_hash=recorded_hash.lower() if recorded_hash else None,
            )
        )
    return _ParsedSection(references, malformed, state)


def resolve_object_hashes(
    project_root: Path,
    paths: Iterable[str],
    revision: str = "HEAD",
) -> dict[str, str]:
    """指定したパスの、あるリビジョン時点の git オブジェクトのハッシュを取得する。

    ファイルは blob、ディレクトリは tree のハッシュを返す。tree のハッシュは
    配下のいずれかのファイルが変わると変わるため、ディレクトリ単位の正本にも使える。

    Args:
        project_root: git リポジトリのルートディレクトリ。
        paths: リポジトリルートからの相対パス（`/` 区切り。末尾の `/` は無視する）。
        revision: 比較の基準とするリビジョン。
    Returns:
        入力どおりのパス → 完全なハッシュ。リビジョンに存在しないパスは含まない。
    """
    requested = {path: path.rstrip("/") for path in paths}
    lookup_paths = sorted({path for path in requested.values() if path})
    if not lookup_paths:
        return {}
    # -z で出力するとパスが引用符でエスケープされない（日本語のパスに対応するため）
    result = subprocess.run(
        ["git", "ls-tree", "-z", "--full-tree", revision, "--", *lookup_paths],
        cwd=project_root,
        capture_output=True,
        check=True,
    )
    found: dict[str, str] = {}
    for record in result.stdout.decode("utf-8").split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        object_type, object_hash = meta.split()[1:3]
        if object_type in ("blob", "tree"):
            found[path] = object_hash
    return {path: found[lookup] for path, lookup in requested.items() if lookup in found}


def check_thesis_source_tracking(
    project_root: Path = PROJECT_ROOT,
    revision: str = "HEAD",
) -> list[TrackingFinding]:
    """論文の各節が依拠する正本の更新を検出する。

    状態が「未着手」の節は、追従すべき本文が無いため検査しない。

    Args:
        project_root: プロジェクトのルートディレクトリ（git リポジトリ）。
        revision: 正本の現在の版とみなすリビジョン。
    Returns:
        要見直し・ハッシュ未記録・書式不正の一覧（節ファイル・行の順）。
    """
    parsed_sections = [
        parsed
        for parsed in (
            parse_section_sources(
                (project_root / section_file).read_text(encoding="utf-8"),
                section_file.as_posix(),
            )
            for section_file in collect_section_files(project_root)
        )
        if parsed.state != UNSTARTED_STATE
    ]
    references = [ref for parsed in parsed_sections for ref in parsed.references]
    current_hashes = resolve_object_hashes(project_root, (ref.path for ref in references), revision)

    findings = [finding for parsed in parsed_sections for finding in parsed.malformed]
    for ref in references:
        finding = _compare_reference(ref, current_hashes.get(ref.path))
        if finding is not None:
            findings.append(finding)
    return sorted(findings, key=lambda finding: (finding.section_file, finding.line))


def _compare_reference(
    ref: SourceReference,
    current_hash: str | None,
) -> TrackingFinding | None:
    """記録されたハッシュと現在のハッシュを比較し、要対応なら1件を返す。

    Args:
        ref: 節ファイルに記録された正本。
        current_hash: 正本の現在の完全なハッシュ。存在しない場合は None。
    Returns:
        要対応の場合は検出結果、一致する場合は None。
    """
    if current_hash is None:
        kind = KIND_MISSING
    elif ref.recorded_hash is None:
        kind = KIND_NO_HASH
    elif current_hash.startswith(ref.recorded_hash):
        return None
    else:
        kind = KIND_UPDATED
    return TrackingFinding(
        section_file=ref.section_file,
        line=ref.line,
        kind=kind,
        source_path=ref.path,
        recorded_hash=ref.recorded_hash,
        current_hash=current_hash[:SHORT_HASH_LENGTH] if current_hash else None,
    )


def stamp_section_sources(
    section_file: Path,
    project_root: Path = PROJECT_ROOT,
    revision: str = "HEAD",
) -> list[str]:
    """節ファイルの「依拠する正本」のハッシュを現在の値に書き換える。

    改行コードを含め、該当行以外の内容は変更しない。
    リビジョンに存在しない正本の行は書き換えず、そのパスを返す。

    Args:
        section_file: 書き換える節ファイル（絶対パス、または project_root からの相対パス）。
        project_root: プロジェクトのルートディレクトリ（git リポジトリ）。
        revision: 記録するハッシュの基準とするリビジョン。
    Returns:
        リビジョンに見つからず書き換えなかった正本のパスの一覧。
    """
    target = section_file if section_file.is_absolute() else project_root / section_file
    raw_text = target.read_bytes().decode("utf-8")
    parsed = parse_section_sources(raw_text, section_file.as_posix())
    current_hashes = resolve_object_hashes(
        project_root, (ref.path for ref in parsed.references), revision
    )

    # 改行コードを保持するため、行末の改行を残したまま行単位で置き換える
    lines = raw_text.splitlines(keepends=True)
    not_found: list[str] = []
    for ref in parsed.references:
        current_hash = current_hashes.get(ref.path)
        if current_hash is None:
            not_found.append(ref.path)
            continue
        original = lines[ref.line - 1]
        body = original.rstrip("\r\n")
        newline = original[len(body) :]
        indent = body[: len(body) - len(body.lstrip())]
        lines[ref.line - 1] = f"{indent}- {ref.path} @ {current_hash[:SHORT_HASH_LENGTH]}{newline}"
    target.write_bytes("".join(lines).encode("utf-8"))
    return not_found


def format_finding(finding: TrackingFinding) -> str:
    """検出結果1件を表示用の1行にする。

    Args:
        finding: 検出結果。
    Returns:
        `{節ファイル}:{行} [{種別}] {正本}` に、ハッシュと差分確認コマンドを添えた文字列。
    """
    text = f"{finding.section_file}:{finding.line} [{finding.kind}] {finding.source_path}"
    if finding.kind == KIND_UPDATED:
        text += f" 記録={finding.recorded_hash} 現在={finding.current_hash}"
        text += f"（差分: {finding.diff_command}）"
    return text


def main(argv: list[str] | None = None, project_root: Path = PROJECT_ROOT) -> int:
    """検出結果を表示する。`--stamp` 指定時は節ファイルのハッシュを書き換える。

    Args:
        argv: コマンドライン引数（None の場合は sys.argv を使う）。
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        終了コード。検出のみの場合は常に0、`--stamp` で正本が見つからない行があれば1。
    """
    parser = argparse.ArgumentParser(description="論文の節が依拠する正本の更新を検出する")
    parser.add_argument(
        "--stamp",
        nargs="+",
        type=Path,
        metavar="SECTION_FILE",
        help="指定した節ファイルの正本のハッシュを HEAD 時点の値に書き換える",
    )
    args = parser.parse_args(argv)

    if args.stamp:
        exit_code = 0
        for section_file in args.stamp:
            not_found = stamp_section_sources(section_file, project_root)
            for path in not_found:
                exit_code = 1
                print(f"[NG] {section_file.as_posix()}: 正本が HEAD に見つからない: {path}")
            if not not_found:
                print(f"[OK] {section_file.as_posix()}: 正本のハッシュを記録しました")
        return exit_code

    findings = check_thesis_source_tracking(project_root)
    if not findings:
        print("[OK] 論文の各節が依拠する正本に更新はありません。")
    for finding in findings:
        print(f"  - {format_finding(finding)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
