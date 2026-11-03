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
import posixpath
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
KIND_NO_SOURCES = "正本未記入"
KIND_MALFORMED = "書式不正"

# 本文が無く追従の対象にならない節の状態（この状態の節は検査しない）
UNSTARTED_STATE = "未着手"

_BOM = chr(0xFEFF)
_COMMENT_END = "-->"
_STATE_PATTERN = re.compile(r"^状態\s*[:：]\s*(?P<state>\S+)\s*$")
_SOURCES_KEY_PATTERN = re.compile(r"^依拠する正本\s*[:：]\s*(?P<rest>.*)$")
_ENTRY_PATTERN = re.compile(r"^\s*-\s+(?P<path>\S+)(?:\s+@\s+(?P<hash>[0-9a-fA-F]{7,40}))?\s*$")
_ENTRY_LINE_PATTERN = re.compile(r"^\s*-\s")
_DRIVE_LETTER_PATTERN = re.compile(r"^[A-Za-z]:")
_PLACEHOLDER_PATTERN = re.compile(r"^\s*-\s+（.*）\s*$")


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

    section_file: str
    references: list[SourceReference]
    malformed: list[TrackingFinding]
    state: str | None = None
    placeholder_line: int | None = None


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
    「依拠する正本:」の行に続く `- ` 行を1件ずつ読む（空行は読み飛ばし、
    `- ` で始まらない行が来たら欄の終わりとする）。
    `- （執筆時に記入）` のような全角括弧だけのプレースホルダは正本として扱わず、
    残っていることだけを記録する。あわせて「状態:」の値も読む。

    Args:
        text: 節ファイルの本文。
        section_file: 結果に記録する節ファイルのパス（表示用）。
    Returns:
        抽出した正本の一覧、書式に合わない行の一覧、状態、プレースホルダの行番号。
    """
    references: list[SourceReference] = []
    malformed: list[TrackingFinding] = []
    state: str | None = None
    placeholder_line: int | None = None

    lines = text.splitlines()
    first_line = lines[0].lstrip(_BOM) if lines else ""
    # 1行で閉じたコメント（`<!-- ... -->`）は「依拠する正本」の欄を持たない
    if not first_line.startswith("<!--") or _COMMENT_END in first_line:
        return _ParsedSection(section_file, references, malformed)

    in_sources = False
    for index, raw_line in enumerate(lines[1:], start=2):
        # 行の途中で `-->` が現れた場合も、そこまでをメタ情報欄として読む
        line, comment_end, _ = raw_line.partition(_COMMENT_END)
        is_last_line = bool(comment_end)
        if not line.strip():
            if is_last_line:
                break
            continue
        state_match = _STATE_PATTERN.match(line)
        sources_match = _SOURCES_KEY_PATTERN.match(line)
        if state_match:
            state = state_match.group("state")
            in_sources = False
        elif sources_match:
            in_sources = True
            if sources_match.group("rest").strip():
                # 「依拠する正本: docs/a.md」のような1行書きは書式に合わない
                malformed.append(_malformed(section_file, index, line))
        elif in_sources:
            if not _ENTRY_LINE_PATTERN.match(line):
                # `- ` で始まらない行が来たら「依拠する正本」の欄は終わり
                in_sources = False
            elif _PLACEHOLDER_PATTERN.match(line):
                placeholder_line = index
            elif (match := _ENTRY_PATTERN.match(line)) is None:
                malformed.append(_malformed(section_file, index, line))
            else:
                recorded_hash = match.group("hash")
                references.append(
                    SourceReference(
                        section_file=section_file,
                        line=index,
                        path=match.group("path"),
                        recorded_hash=recorded_hash.lower() if recorded_hash else None,
                    )
                )
        if is_last_line:
            break
    return _ParsedSection(section_file, references, malformed, state, placeholder_line)


def _malformed(section_file: str, line_number: int, line: str) -> TrackingFinding:
    """書式不正の検出結果を1件作る。

    Args:
        section_file: 節ファイルのパス（表示用）。
        line_number: 書式に合わない行の行番号。
        line: 書式に合わない行の内容。
    Returns:
        書式不正の検出結果。
    """
    return TrackingFinding(
        section_file=section_file,
        line=line_number,
        kind=KIND_MALFORMED,
        source_path=line.strip(),
    )


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
        paths: リポジトリルートからの相対パス
            （`./` や末尾の `/`、`\\` 区切りは正規化して照合する）。
        revision: 比較の基準とするリビジョン。
    Returns:
        入力どおりのパス → 完全なハッシュ。リビジョンに存在しないパスは含まない。
    Raises:
        RuntimeError: git が無い・リポジトリ外・リビジョンが無いなどで git の実行に失敗した場合
            （「正本が見つからない」と区別できなくなるため、空の結果にせず例外にする）。
    """
    requested = {path: _normalize_source_path(path) for path in paths}
    lookup_paths = sorted({path for path in requested.values() if path})
    if not lookup_paths:
        return {}
    # -z で出力するとパスが引用符でエスケープされない（日本語のパスに対応するため）。
    # --literal-pathspecs で `:(exclude)` などの特殊記法を解釈させず、
    # 1件の記述ミスで全節の検査が止まらないようにする
    try:
        result = subprocess.run(
            [
                "git",
                "--literal-pathspecs",
                "ls-tree",
                "-z",
                "--full-tree",
                revision,
                "--",
                *lookup_paths,
            ],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", None)
        detail = stderr.decode("utf-8", errors="replace").strip() if stderr else str(error)
        raise RuntimeError(
            f"正本のハッシュを取得できませんでした（{project_root} の {revision}）: {detail}"
        ) from error
    found: dict[str, str] = {}
    for record in result.stdout.decode("utf-8").split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        object_type, object_hash = meta.split()[1:3]
        if object_type in ("blob", "tree"):
            found[path] = object_hash
    return {path: found[lookup] for path, lookup in requested.items() if lookup in found}


def _normalize_source_path(path: str) -> str:
    """正本のパスを git の出力（`/` 区切り・ルートからの相対）と照合できる形にする。

    Args:
        path: 節ファイルに記録されたパス。
    Returns:
        正規化したパス。リポジトリの外を指す・絶対パス（ドライブレター付きを含む）・
        空になる場合は空文字列（照合せず「正本が見つからない」として扱う）。
    """
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if (
        normalized in (".", "..", "")
        or normalized.startswith(("../", "/"))
        or _DRIVE_LETTER_PATTERN.match(normalized)
    ):
        return ""
    return normalized


def check_thesis_source_tracking(
    project_root: Path = PROJECT_ROOT,
    revision: str = "HEAD",
) -> list[TrackingFinding]:
    """論文の各節が依拠する正本の更新を検出する。

    状態が「未着手」の節は、追従すべき本文が無いため検査しない。
    それ以外の状態で、正本が1件も無くプレースホルダが残っている節は「正本未記入」とする
    （依拠する正本が無い節は、プレースホルダの行を消して明示する運用とする）。

    Args:
        project_root: プロジェクトのルートディレクトリ（git リポジトリ）。
        revision: 正本の現在の版とみなすリビジョン。
    Returns:
        要見直し・ハッシュ未記録・正本未記入・書式不正の一覧（節ファイル・行の順）。
    Raises:
        RuntimeError: git の実行に失敗した場合。
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
    findings.extend(
        TrackingFinding(
            section_file=parsed.section_file,
            line=parsed.placeholder_line,
            kind=KIND_NO_SOURCES,
            source_path="（依拠する正本が未記入）",
        )
        for parsed in parsed_sections
        if not parsed.references and parsed.placeholder_line is not None
    )
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


@dataclass(frozen=True)
class StampResult:
    """`--stamp` で1つの節ファイルを処理した結果。"""

    stamped: int
    not_found: list[str]
    malformed: list[TrackingFinding]

    @property
    def is_ok(self) -> bool:
        """1件以上を記録でき、記録できなかった行が無いかを返す。"""
        return self.stamped > 0 and not self.not_found and not self.malformed


def stamp_section_sources(
    section_file: Path,
    project_root: Path = PROJECT_ROOT,
    revision: str = "HEAD",
) -> StampResult:
    """節ファイルの「依拠する正本」のハッシュを現在の値に書き換える。

    改行コードを含め、該当行以外の内容は変更しない。内容が変わらない場合は書き込まない。
    リビジョンに存在しない正本の行と書式に合わない行は書き換えず、結果として返す。

    Args:
        section_file: 書き換える節ファイル（絶対パス、または project_root からの相対パス）。
        project_root: プロジェクトのルートディレクトリ（git リポジトリ）。
        revision: 記録するハッシュの基準とするリビジョン。
    Returns:
        記録した件数、見つからなかった正本のパス、書式不正の行。
    Raises:
        FileNotFoundError: 節ファイルが存在しない場合。
    """
    target = section_file if section_file.is_absolute() else project_root / section_file
    if not target.is_file():
        raise FileNotFoundError(f"節ファイルが見つかりません: {target}")
    raw_text = target.read_bytes().decode("utf-8")
    parsed = parse_section_sources(raw_text, section_file.as_posix())
    current_hashes = resolve_object_hashes(
        project_root, (ref.path for ref in parsed.references), revision
    )

    # 改行コードを保持するため、行末の改行を残したまま行単位で置き換える
    lines = raw_text.splitlines(keepends=True)
    not_found: list[str] = []
    stamped = 0
    for ref in parsed.references:
        current_hash = current_hashes.get(ref.path)
        if current_hash is None:
            not_found.append(ref.path)
            continue
        lines[ref.line - 1] = _stamp_line(lines[ref.line - 1], ref.path, current_hash)
        stamped += 1
    new_text = "".join(lines)
    if new_text != raw_text:
        target.write_bytes(new_text.encode("utf-8"))
    return StampResult(stamped=stamped, not_found=not_found, malformed=parsed.malformed)


def _stamp_line(original: str, path: str, current_hash: str) -> str:
    """正本の1行を `- {パス} @ {ハッシュ}` に書き換える。

    字下げ・行末の改行・行末で閉じるコメント（`-->` 以降）はそのまま残す。

    Args:
        original: 改行を含む元の行。
        path: 記録された正本のパス（書かれていたとおりに残す）。
        current_hash: 正本の現在の完全なハッシュ。
    Returns:
        書き換えた行（改行を含む）。
    """
    # 改行の判定は splitlines と揃える（行番号の数え方を解析側と一致させるため）
    split_lines = original.splitlines()
    content = split_lines[0] if split_lines else ""
    newline = original[len(content) :]
    entry, comment_end, rest = content.partition(_COMMENT_END)
    indent = entry[: len(entry) - len(entry.lstrip())]
    stamped = f"{indent}- {path} @ {current_hash[:SHORT_HASH_LENGTH]}"
    if comment_end:
        stamped += f" {comment_end}{rest}"
    return stamped + newline


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


def _stamp_and_report(section_file: Path, project_root: Path) -> bool:
    """1つの節ファイルに `--stamp` を実行し、結果を表示する。

    Args:
        section_file: 書き換える節ファイル。
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        記録が成功した（1件以上記録し、記録できなかった行が無い）場合は True。
    """
    label = section_file.as_posix()
    try:
        result = stamp_section_sources(section_file, project_root)
    except (FileNotFoundError, RuntimeError) as error:
        print(f"[NG] {error}")
        return False
    for path in result.not_found:
        print(f"[NG] {label}: 正本が HEAD に見つからない: {path}")
    for finding in result.malformed:
        print(f"[NG] {label}:{finding.line}: 書式不正のため記録しなかった: {finding.source_path}")
    if result.stamped == 0 and not result.not_found and not result.malformed:
        print(f"[NG] {label}: 記録する正本がありません（「依拠する正本」にパスを書いてください）")
    if result.stamped > 0 and not result.is_ok:
        print(f"  （{label}: 上記以外の {result.stamped} 件はハッシュを記録しました）")
    if result.is_ok:
        print(f"[OK] {label}: 正本のハッシュを記録しました（{result.stamped} 件）")
    return result.is_ok


def main(argv: list[str] | None = None, project_root: Path = PROJECT_ROOT) -> int:
    """検出結果を表示する。`--stamp` 指定時は節ファイルのハッシュを書き換える。

    Args:
        argv: コマンドライン引数（None の場合は sys.argv を使う）。
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        終了コード。検出のみの場合は0（git の実行に失敗した場合は1）。
        `--stamp` では、記録できなかった行がある・記録する正本が1件も無い・
        節ファイルが無い場合に1。
    """
    parser = argparse.ArgumentParser(description="論文の節が依拠する正本の更新を検出する")
    parser.add_argument(
        "--stamp",
        nargs="+",
        type=Path,
        metavar="SECTION_FILE",
        help="指定した節ファイル（リポジトリルートからの相対パス）の正本のハッシュを"
        " HEAD 時点の値に書き換える",
    )
    args = parser.parse_args(argv)

    if args.stamp:
        results = [_stamp_and_report(section_file, project_root) for section_file in args.stamp]
        return 0 if all(results) else 1

    try:
        findings = check_thesis_source_tracking(project_root)
    except RuntimeError as error:
        print(f"[NG] {error}")
        return 1
    if not findings:
        print("[OK] 論文の各節が依拠する正本に更新はありません。")
    for finding in findings:
        print(f"  - {format_finding(finding)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
