"""分析結果の陳腐化検出。

`data/output/**/*_results.json` を走査し、各結果ファイルの来歴（`provenance`）を
現在の入力ファイル・コードと照らし合わせて、次の5分類のいずれかに判定する。
該当した理由はすべて `reasons` に残し、上に書いた分類ほど優先して主分類とする。

1. 来歴なし（`no_provenance`）: `provenance` が無い・辞書でない。結果 JSON 自体を
   解釈できない場合も、来歴を確認できないためここに含める
2. 入力欠落（`input_missing`）: `provenance.inputs[].path` のファイルが無い
   （入力の記録にパスが無い場合を含む）
3. 要再実行・入力変更（`stale_input`）: 入力ファイルの SHA-256 が記録値と一致しない
   （記録値が無い場合を含む）
4. 要再実行・コード変更（`stale_code`）: 生成時と現在の `HEAD` の間で、生成スクリプト
   または既定の監視パス（`src/common/` 等）のコードに差分がある。`git.dirty` が真の場合や、
   差分を判定する手がかり（コードのハッシュ・記録コミット）が無い場合も、生成時のコードを
   確かめられないためここに含める
5. 最新（`up_to_date`）: 上記のいずれにも当たらない

コードの差分は、来歴にコードのファイルハッシュ（`provenance.code`）があれば、それと
`HEAD` の木にあるファイルの内容（改行を LF にそろえる）のハッシュを比べて判定する
（ファイルの変更・追加・削除をすべて差分とする）。記録コミットが不要なため、squash merge で
消えた作業ブランチ上で生成した結果や、新しい clone でも判定できる。

ハッシュの記録が無い範囲（`provenance.code` を持たない旧形式の結果、および記録した範囲
（`provenance.code.watch_paths`）の配下に無い監視パス。生成後に増えた既定の監視パスや、
記録範囲外の `--extra-watch-path` が該当する）は、`git diff --name-only {記録コミット}
HEAD -- {監視パス}` の木の比較で判定する（祖先関係を問わないため、作業ブランチ上の
コミットでもローカルに残っていれば判定できる）。

既知の限界:

- ハッシュの記録が無い範囲は、記録コミットがローカルに無いとコードの差分を判定できず
  「要再実行（コード変更）」になる（理由に「記録コミットがローカルに無い」と明記する）。
  squash merge で作業ブランチを消す運用では、作業ブランチ上で生成した結果の記録コミットは
  どのブランチからもたどれず、reflog が期限切れになった後の gc で消える。新しい clone でも
  最初から無い。この理由の結果は「コードが変わった」ではなく「生成時のコードを確かめられ
  ない」と読む。コードのハッシュを持つ結果では、記録範囲の外を監視しない限り起きない
- 生成スクリプトが import するモジュールのうち、監視するのは `DEFAULT_WATCH_PATHS`
  （`src/common/` と Spatial CV のブロック分割）だけで、それ以外の補助モジュールの変更は
  「コード変更」に含めない。必要なら `--extra-watch-path` で監視パスを追加する
- 来歴のコードのハッシュ（`provenance.code`）の形式が不正な場合は、ハッシュの記録が無い
  ものとして木の比較で判定する
- 来歴に入力の記録（`inputs`）が無い・空のリストの場合は、入力を照合できないが理由は
  付けない（ほかに問題が無ければ「最新」になる）。来歴を付ける分析スクリプトはいずれも
  入力を記録するため、この形は想定していない
- 走査するのは `*_results.json` だけで、来歴を持つ他の JSON（例: NoData 脱落診断の
  `*_nodata_dropout_summary.json`）は対象外である
- 入力のデータセット GPKG 自体を作るスクリプトの変更はたどらない（GPKG が作り直されれば
  ハッシュの不一致で検出される）
- 判定の基準は実行時にチェックアウトされている `HEAD` である

本スクリプトは結果ファイル・`docs/` を書き換えず、GitHub にも書き込まない。
報告 Issue の特定・起票・コメント・close は `/check-result-staleness` スキルの手順で行う。

報告モード（`--report-output` を指定した場合）:

- `--previous-issue-json` なし: 新規起票用の Issue 本文を書き出す
- `--previous-issue-json` あり: 報告 Issue（`gh issue view {番号} --json body,comments` の
  保存ファイル）の本文とコメントに埋め込んだ不可視マーカー
  ``<!-- result-staleness-state: パス=分類 ... -->`` のうち最新のものから前回の問題
  （最新以外の結果）を復元し、新規・解消・分類変化・継続を記した差分コメントを書き出す。
  報告 Issue 自体を前回状態の正本とし、ローカルに状態ファイルを持たない

終了コード:

- 0: 判定を出力した（報告モードでは、新規起票の本文または差分コメントを書き出した）
- 1: 判定できない（git の `HEAD` を取得できない・走査先が無い）、または報告 Issue の
  保存ファイルを読めない（空・不正な JSON・マーカーが無い）。報告モードでは何も書き出さない
- 3: 報告モードで書き込む内容が無い（問題なしで報告 Issue も無い・前回から差分なし）
- 4: 報告モードで前回の問題がすべて解消した（解消一覧を書き出した。スキルは追記後に close する）

実行はプロジェクトルートから行う（`src` パッケージを import するため）。

```sh
python -m scripts.check_result_staleness --output-json staleness.json --output-md staleness.md
```
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.summary import (
    CODE_WATCH_PATHS,
    compute_code_sha256,
    compute_file_sha256,
    script_module_to_path,
)

EXIT_REPORT_WRITTEN = 0
EXIT_FAILURE = 1
EXIT_NO_CHANGE = 3
EXIT_ALL_RESOLVED = 4

# 前回の問題（結果パス → 分類）を埋め込む不可視マーカー
_MARKER_LABEL = "result-staleness-state:"
_MARKER_PATTERN = re.compile(r"<!--\s*result-staleness-state:(.*?)-->", re.DOTALL)

# パスを URL エンコードする際に残す文字（`=`・`>`・空白はエンコードされ、マーカーを壊さない）
_PATH_SAFE_CHARS = "/._()"

# 報告 Issue・コメントの識別用フッタ（スキルはこの文言で報告 Issue を特定する）
ISSUE_FOOTER = "🤖 このIssueは /check-result-staleness スキルにより作成されました。"
COMMENT_FOOTER = "🤖 このコメントは /check-result-staleness スキルにより追記されました。"

# 分類のキー（表の上から優先する順に並べる）
STATUS_NO_PROVENANCE = "no_provenance"
STATUS_INPUT_MISSING = "input_missing"
STATUS_STALE_INPUT = "stale_input"
STATUS_STALE_CODE = "stale_code"
STATUS_UP_TO_DATE = "up_to_date"

STATUS_ORDER: tuple[str, ...] = (
    STATUS_NO_PROVENANCE,
    STATUS_INPUT_MISSING,
    STATUS_STALE_INPUT,
    STATUS_STALE_CODE,
    STATUS_UP_TO_DATE,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_NO_PROVENANCE: "来歴なし",
    STATUS_INPUT_MISSING: "入力欠落",
    STATUS_STALE_INPUT: "要再実行（入力変更）",
    STATUS_STALE_CODE: "要再実行（コード変更）",
    STATUS_UP_TO_DATE: "最新",
}

# 走査する結果ファイルの既定の置き場所とファイル名のパターン
DEFAULT_RESULTS_ROOT = Path("data") / "output"
RESULTS_GLOB = "**/*_results.json"

# 生成スクリプトに加えて常に監視するパス。来歴にハッシュを記録する範囲と一致させるため、
# 定義は来歴の生成側（`src.common.summary.CODE_WATCH_PATHS`）に置く
DEFAULT_WATCH_PATHS: tuple[str, ...] = CODE_WATCH_PATHS

# git コマンドの待ち時間の上限（秒）
_GIT_TIMEOUT_SECONDS = 30


@dataclass
class StalenessResult:
    """結果ファイル1件の判定結果。

    Attributes:
        path: 結果ファイルのプロジェクト相対パス。
        reasons: 該当した分類ごとの理由（分類キー → 理由の一覧）。
        recorded_commit: 来歴に記録されたコミット（無ければ None）。
        changed_files: 生成時と `HEAD` の間で差分のあった監視対象ファイル。
    """

    path: str
    reasons: dict[str, list[str]] = field(default_factory=dict)
    recorded_commit: str | None = None
    changed_files: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """優先順位が最も高い分類（該当が無ければ最新）を返す。"""
        for status in STATUS_ORDER:
            if self.reasons.get(status):
                return status
        return STATUS_UP_TO_DATE

    def add_reason(self, status: str, reason: str) -> None:
        """分類に理由を追加する。

        Args:
            status: 分類キー。
            reason: 理由の説明（日本語）。
        """
        self.reasons.setdefault(status, []).append(reason)

    def to_dict(self) -> dict[str, Any]:
        """JSON 出力用の辞書に変換する。"""
        return {
            "path": self.path,
            "status": self.status,
            "reasons": [
                {"status": status, "reason": reason}
                for status in STATUS_ORDER
                for reason in self.reasons.get(status, [])
            ],
            "recorded_commit": self.recorded_commit,
            "changed_files": self.changed_files,
        }


class GitRepository:
    """判定に使う git 操作をまとめたもの（同じ問い合わせを繰り返さないよう結果を保持する）。

    Args:
        repo_root: git リポジトリのルート。
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._commit_exists: dict[str, bool] = {}
        self._diff_cache: dict[tuple[str, tuple[str, ...]], list[str] | None] = {}
        self._head_hash_cache: dict[tuple[str, ...], dict[str, str] | None] = {}
        self._blob_hash_cache: dict[str, str] = {}

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str] | None:
        """git コマンドを実行する。git を起動できない場合は None を返す。

        Args:
            args: `git` に続く引数。
        Returns:
            実行結果（終了コードの判定は呼び出し側で行う）。
        """
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    def head_commit(self) -> str | None:
        """現在の `HEAD` のコミットハッシュを返す（取得できなければ None）。"""
        completed = self._run(["rev-parse", "HEAD"])
        if completed is None or completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def commit_exists(self, commit: str) -> bool:
        """コミットがローカルのリポジトリに存在するかを返す。

        Args:
            commit: コミットハッシュ。
        Returns:
            存在すれば True。
        """
        if commit not in self._commit_exists:
            completed = self._run(["cat-file", "-e", f"{commit}^{{commit}}"])
            self._commit_exists[commit] = completed is not None and completed.returncode == 0
        return self._commit_exists[commit]

    def changed_files(self, commit: str, paths: tuple[str, ...]) -> list[str] | None:
        """記録コミットと `HEAD` の木を比べ、監視パス配下で差分のあるファイルを返す。

        Args:
            commit: 記録コミット。
            paths: 監視するパス（リポジトリルート基準の `/` 区切り）。
        Returns:
            差分のあったファイルのパス（ソート済み）。git の実行に失敗した場合は None。
        """
        key = (commit, paths)
        if key not in self._diff_cache:
            completed = self._run(["diff", "--name-only", commit, "HEAD", "--", *paths])
            if completed is None or completed.returncode != 0:
                self._diff_cache[key] = None
            else:
                self._diff_cache[key] = sorted(
                    line.strip() for line in completed.stdout.splitlines() if line.strip()
                )
        return self._diff_cache[key]

    def head_code_hashes(self, paths: tuple[str, ...]) -> dict[str, str] | None:
        """`HEAD` の木にある監視パス配下のファイルと、その内容のハッシュを返す。

        ハッシュは来歴の記録と同じく、改行を LF にそろえた内容から計算する
        （`compute_code_sha256`）。作業ツリーではなく `HEAD` の内容を使うのは、
        未コミットの変更を数えないという判定の基準をそろえるため。

        Args:
            paths: 監視するパス（リポジトリルート基準の `/` 区切り）。
        Returns:
            ファイルパス → SHA-256。git の実行に失敗した場合は None。
        """
        if paths not in self._head_hash_cache:
            self._head_hash_cache[paths] = self._list_head_code_hashes(paths)
        return self._head_hash_cache[paths]

    def _list_head_code_hashes(self, paths: tuple[str, ...]) -> dict[str, str] | None:
        """`head_code_hashes` の本体（キャッシュを介さずに git へ問い合わせる）。"""
        completed = self._run(["ls-tree", "-r", "-z", "HEAD", "--", *paths])
        if completed is None or completed.returncode != 0:
            return None
        blobs: dict[str, str] = {}
        for entry in completed.stdout.split("\0"):
            if not entry:
                continue
            # 形式: "{モード} {種別} {オブジェクトID}\t{パス}"
            meta, _, file_path = entry.partition("\t")
            fields = meta.split()
            # サブモジュール（commit）等はファイルの内容を持たないため対象外とする
            if len(fields) == 3 and fields[1] == "blob":
                blobs[file_path] = fields[2]
        missing = sorted({oid for oid in blobs.values() if oid not in self._blob_hash_cache})
        if missing and not self._hash_blobs(missing):
            return None
        return {file_path: self._blob_hash_cache[oid] for file_path, oid in blobs.items()}

    def _hash_blobs(self, object_ids: list[str]) -> bool:
        """git のオブジェクト（ファイルの内容）を読み、ハッシュを保持先に追加する。

        内容はバイト列のまま扱う必要があるため、`git cat-file --batch` を直接呼ぶ。

        Args:
            object_ids: 読み込むオブジェクト ID。
        Returns:
            すべて読み込めた場合は True。
        """
        try:
            completed = subprocess.run(
                ["git", "cat-file", "--batch"],
                cwd=self.repo_root,
                input="".join(f"{oid}\n" for oid in object_ids).encode("ascii"),
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        output = completed.stdout
        position = 0
        for oid in object_ids:
            # 形式: "{オブジェクトID} {種別} {サイズ}\n{内容}\n"（無ければ "... missing\n"）
            header_end = output.find(b"\n", position)
            header = output[position:header_end].split() if header_end >= 0 else []
            # 想定外の形式（読めなかったオブジェクト・壊れた出力）は例外にせず失敗として返す
            if len(header) != 3 or header[0] != oid.encode("ascii") or not header[2].isdigit():
                return False
            content_start = header_end + 1
            content_end = content_start + int(header[2])
            if content_end > len(output):
                return False
            self._blob_hash_cache[oid] = compute_code_sha256(output[content_start:content_end])
            position = content_end + 1
        return True


def resolve_input_path(recorded_path: str, data_root: Path) -> Path:
    """来歴に記録された入力パスを実ファイルのパスに解決する。

    来歴の入力パスはプロジェクト相対（ルート外のものは絶対パス）で記録されている。

    Args:
        recorded_path: `provenance.inputs[].path` の値。
        data_root: 相対パスの基準ディレクトリ。
    Returns:
        解決したパス。
    """
    path = Path(recorded_path)
    return path if path.is_absolute() else data_root / path


def hash_with_cache(path: Path, cache: dict[Path, str]) -> str:
    """ファイルの SHA-256 を計算する（同じファイルは2回計算しない）。

    大容量の GeoPackage を複数の結果ファイルが共有するため、計算結果を保持して使い回す。

    Args:
        path: 対象ファイル。
        cache: 計算済みハッシュの保持先（解決済みパス → ハッシュ）。
    Returns:
        SHA-256 の16進文字列。
    """
    key = path.resolve()
    if key not in cache:
        cache[key] = compute_file_sha256(key)
    return cache[key]


def check_inputs(
    result: StalenessResult,
    inputs: object,
    data_root: Path,
    hash_cache: dict[Path, str],
) -> None:
    """入力ファイルの欠落とハッシュの不一致を判定し、理由を追加する。

    Args:
        result: 判定結果（理由の追加先）。
        inputs: `provenance.inputs` の値。
        data_root: 入力パスの基準ディレクトリ。
        hash_cache: ハッシュの保持先。
    """
    if inputs is None:
        return
    if not isinstance(inputs, list):
        result.add_reason(STATUS_INPUT_MISSING, "来歴の入力一覧（inputs）がリストではない")
        return
    for entry in inputs:
        recorded_path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(recorded_path, str) or not recorded_path:
            result.add_reason(STATUS_INPUT_MISSING, "来歴の入力にパスが記録されていない")
            continue
        input_path = resolve_input_path(recorded_path, data_root)
        if not input_path.is_file():
            result.add_reason(STATUS_INPUT_MISSING, f"入力ファイルが無い: {recorded_path}")
            continue
        recorded_hash = entry.get("sha256")
        if not isinstance(recorded_hash, str) or not recorded_hash:
            result.add_reason(
                STATUS_STALE_INPUT, f"入力のハッシュが記録されていない: {recorded_path}"
            )
            continue
        if hash_with_cache(input_path, hash_cache) != recorded_hash.lower():
            result.add_reason(STATUS_STALE_INPUT, f"入力ファイルが変更されている: {recorded_path}")


@dataclass(frozen=True)
class CodeRecord:
    """来歴に記録されたコードのファイルハッシュ（`provenance.code`）。

    Attributes:
        watch_paths: ハッシュを取った範囲（正規化済みのパス）。
        files: ファイルパス → SHA-256（小文字）。
    """

    watch_paths: frozenset[str]
    files: dict[str, str]


def normalize_watch_path(path: str) -> str:
    """監視パスを比較用の形（`/` 区切り・末尾の `/` なし）にそろえる。

    Args:
        path: 監視パス（`--extra-watch-path` の指定値を含む）。
    Returns:
        正規化したパス。
    """
    return path.replace("\\", "/").rstrip("/")


def parse_code_record(code: object) -> CodeRecord | None:
    """`provenance.code` を解釈する。

    形式が不正な記録は、ハッシュの記録が無いもの（旧形式）として扱う（記録コミットとの
    木の比較に回り、推測でハッシュの一致・不一致を決めないため）。

    Args:
        code: `provenance.code` の値。
    Returns:
        解釈した記録。記録が無い・形式が不正な場合は None。
    """
    if not isinstance(code, dict):
        return None
    watch_paths = code.get("watch_paths")
    files = code.get("files")
    if not isinstance(watch_paths, list) or not isinstance(files, list):
        return None
    if not all(isinstance(path, str) and path for path in watch_paths):
        return None
    hashes: dict[str, str] = {}
    for entry in files:
        file_path = entry.get("path") if isinstance(entry, dict) else None
        sha256 = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(file_path, str) or not file_path:
            return None
        if not isinstance(sha256, str) or not sha256:
            return None
        hashes[file_path] = sha256.lower()
    return CodeRecord(frozenset(normalize_watch_path(path) for path in watch_paths), hashes)


def is_under_paths(file_path: str, paths: Iterable[str]) -> bool:
    """ファイルがいずれかの監視パス（ファイルそのもの、またはディレクトリの配下）に含まれるか。

    Args:
        file_path: リポジトリ相対のファイルパス。
        paths: 正規化済みの監視パス。
    Returns:
        含まれれば True。
    """
    return any(file_path == path or file_path.startswith(path + "/") for path in paths)


def describe_commit_problem(commit: str | None, git: GitRepository) -> str | None:
    """記録コミットとの木の比較ができない理由を返す。

    Args:
        commit: 記録コミット（無ければ None）。
        git: git 操作。
    Returns:
        理由の説明。比較できる場合は None。
    """
    if commit is None:
        return "来歴にコミットが記録されていない"
    if not git.commit_exists(commit):
        return f"記録コミットがローカルに無い（fetch が必要か、失われた）: {commit}"
    return None


def resolve_watch_paths(
    result: StalenessResult, script: object, extra_watch_paths: tuple[str, ...]
) -> list[str]:
    """生成スクリプト・既定の監視パス・追加の監視パスを並べる（重複は除く）。

    生成スクリプトが記録されていない場合は理由を追加し、既定と追加の監視パスだけを返す。

    Args:
        result: 判定結果（理由の追加先）。
        script: `provenance.script` の値。
        extra_watch_paths: 既定に加えて監視するパス。
    Returns:
        正規化した監視パスの一覧。
    """
    paths = list(DEFAULT_WATCH_PATHS) + list(extra_watch_paths)
    if isinstance(script, str) and script:
        paths.insert(0, script_module_to_path(script))
    else:
        result.add_reason(STATUS_STALE_CODE, "来歴に生成スクリプトが記録されていない")
    return list(dict.fromkeys(normalize_watch_path(path) for path in paths))


def compare_code_hashes(
    result: StalenessResult,
    record: CodeRecord,
    commit: str | None,
    commit_problem: str | None,
    watch_paths: list[str],
    git: GitRepository,
) -> list[str] | None:
    """コードのハッシュの記録と `HEAD` を比べ、差分のあるファイルを返す。

    記録範囲の配下にある監視パスは `HEAD` の木の内容のハッシュと比べ（変更・追加・削除を
    差分とする）、記録範囲の配下に無い監視パスだけ記録コミットとの木の比較に回す。

    Args:
        result: 判定結果（理由の追加先）。
        record: 来歴のコードのハッシュ。
        commit: 記録コミット（無ければ None）。
        commit_problem: 記録コミットとの比較ができない理由（できる場合は None）。
        watch_paths: 正規化済みの監視パス。
        git: git 操作。
    Returns:
        差分のあったファイル（ソート済み）。`HEAD` の内容を取得できない場合は None。
    """
    # 記録範囲の配下にあるパス（例: 記録済みの `src/common` に対する `src/common/x.py`）も
    # ハッシュで判定できる。記録範囲より広いパスは記録が無いファイルを含みうるため木の比較に回す
    hashed = tuple(path for path in watch_paths if is_under_paths(path, record.watch_paths))
    unhashed = tuple(path for path in watch_paths if path not in hashed)
    changed: set[str] = set()
    if hashed:
        head_hashes = git.head_code_hashes(hashed)
        if head_hashes is None:
            result.add_reason(STATUS_STALE_CODE, "HEAD のコードのハッシュを取得できない")
            return None
        recorded = {
            file_path: sha256
            for file_path, sha256 in record.files.items()
            if is_under_paths(file_path, hashed)
        }
        changed.update(
            file_path
            for file_path in recorded.keys() | head_hashes.keys()
            if recorded.get(file_path) != head_hashes.get(file_path)
        )
    if unhashed:
        if commit_problem is not None:
            result.add_reason(
                STATUS_STALE_CODE,
                f"ハッシュの記録が無い監視パスがあり（{'、'.join(unhashed)}）、{commit_problem}",
            )
        else:
            tree_changed = git.changed_files(commit, unhashed)
            if tree_changed is None:
                result.add_reason(
                    STATUS_STALE_CODE, f"記録コミットとの差分を取得できない: {commit}"
                )
            else:
                changed.update(tree_changed)
    return sorted(changed)


def check_code(
    result: StalenessResult,
    provenance: dict[str, Any],
    git: GitRepository,
    extra_watch_paths: tuple[str, ...],
) -> None:
    """生成時のコードと現在の `HEAD` の差分を判定し、理由を追加する。

    来歴にコードのハッシュがあればそれで判定し、記録コミットの有無は問わない。
    ハッシュが無い旧形式の結果は、記録コミットとの木の比較で判定する。

    Args:
        result: 判定結果（理由の追加先）。
        provenance: 来歴の辞書。
        git: git 操作。
        extra_watch_paths: 既定に加えて監視するパス。
    """
    git_state = provenance.get("git")
    git_state = git_state if isinstance(git_state, dict) else {}
    commit = git_state.get("commit")
    commit = commit if isinstance(commit, str) and commit else None
    if git_state.get("dirty") is True:
        result.add_reason(STATUS_STALE_CODE, "未コミットのコード変更がある状態で生成されている")
    result.recorded_commit = commit
    record = parse_code_record(provenance.get("code"))
    commit_problem = describe_commit_problem(commit, git)
    if record is None and commit_problem is not None:
        result.add_reason(STATUS_STALE_CODE, commit_problem)
        return

    watch_paths = resolve_watch_paths(result, provenance.get("script"), extra_watch_paths)
    if record is not None:
        changed = compare_code_hashes(result, record, commit, commit_problem, watch_paths, git)
    else:
        changed = git.changed_files(commit, tuple(watch_paths))
        if changed is None:
            result.add_reason(STATUS_STALE_CODE, f"記録コミットとの差分を取得できない: {commit}")
    if changed is None:
        return
    result.changed_files = changed
    if changed:
        result.add_reason(
            STATUS_STALE_CODE, f"生成時からコードが変更されている（{len(changed)} ファイル）"
        )


def check_result_file(
    result_path: Path,
    project_root: Path,
    data_root: Path,
    git: GitRepository,
    hash_cache: dict[Path, str],
    extra_watch_paths: tuple[str, ...] = (),
) -> StalenessResult:
    """結果ファイル1件を判定する。

    Args:
        result_path: 結果ファイルのパス。
        project_root: 出力するパスの相対化の基準。
        data_root: 入力パスの基準ディレクトリ。
        git: git 操作。
        hash_cache: ハッシュの保持先。
        extra_watch_paths: 既定に加えて監視するパス。
    Returns:
        判定結果。
    """
    result = StalenessResult(path=to_project_relative_string(result_path, project_root))
    try:
        data = json.loads(result_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        result.add_reason(STATUS_NO_PROVENANCE, f"結果 JSON を解釈できない: {exc}")
        return result
    provenance = data.get("provenance") if isinstance(data, dict) else None
    if not isinstance(provenance, dict):
        result.add_reason(STATUS_NO_PROVENANCE, "来歴（provenance）が記録されていない")
        return result
    check_inputs(result, provenance.get("inputs"), data_root, hash_cache)
    check_code(result, provenance, git, extra_watch_paths)
    return result


def find_result_files(results_root: Path) -> list[Path]:
    """走査先から結果ファイルを探す（パス順に並べる）。

    Args:
        results_root: 走査するディレクトリ。
    Returns:
        結果ファイルのパスの一覧。
    """
    return sorted(path for path in results_root.glob(RESULTS_GLOB) if path.is_file())


def count_by_status(results: list[StalenessResult]) -> dict[str, int]:
    """分類ごとの件数を数える（件数0の分類も含める）。

    Args:
        results: 判定結果の一覧。
    Returns:
        分類キー → 件数。
    """
    counts = dict.fromkeys(STATUS_ORDER, 0)
    for result in results:
        counts[result.status] += 1
    return counts


def build_report_data(
    results: list[StalenessResult],
    head_commit: str,
    results_root: str,
    checked_at: dt.datetime,
) -> dict[str, Any]:
    """機械可読の判定結果（JSON 出力の内容）を組み立てる。

    Args:
        results: 判定結果の一覧。
        head_commit: 判定の基準にした `HEAD` のコミット。
        results_root: 走査先（プロジェクト相対）。
        checked_at: 判定した日時。
    Returns:
        JSON に書き出す辞書。
    """
    return {
        "checked_at": checked_at.isoformat(),
        "head_commit": head_commit,
        "results_root": results_root,
        "counts": count_by_status(results),
        "results": [result.to_dict() for result in results],
    }


def format_markdown_report(report: dict[str, Any]) -> str:
    """判定結果を人が読む Markdown（分類別の件数表と一覧）にする。

    Args:
        report: `build_report_data` の戻り値。
    Returns:
        Markdown の本文。
    """
    counts = report["counts"]
    lines = [
        "## 分析結果の陳腐化検出",
        "",
        f"- 判定日時: {report['checked_at']}",
        f"- 基準コミット（HEAD）: `{report['head_commit']}`",
        f"- 走査先: `{report['results_root']}`（{sum(counts.values())} 件）",
        "",
        "| 分類 | 件数 |",
        "|---|---:|",
    ]
    lines.extend(f"| {STATUS_LABELS[status]} | {counts[status]} |" for status in STATUS_ORDER)
    for status in STATUS_ORDER:
        entries = [entry for entry in report["results"] if entry["status"] == status]
        if not entries:
            continue
        heading = f"{STATUS_LABELS[status]}（{len(entries)} 件）"
        if status == STATUS_UP_TO_DATE:
            # 最新の結果は対応が不要なため、折りたたんで載せる
            lines.extend(["", f"<details><summary>{heading}</summary>", ""])
            lines.extend(f"- `{entry['path']}`" for entry in entries)
            lines.extend(["", "</details>"])
            continue
        lines.extend(["", f"### {heading}", ""])
        for entry in entries:
            reasons = "／".join(item["reason"] for item in entry["reasons"])
            lines.append(f"- `{entry['path']}`: {reasons}")
    return "\n".join(lines) + "\n"


@dataclass
class StateDiff:
    """前回と今回の問題（最新以外の結果）の差分。

    Attributes:
        new: 今回新たに問題になった結果（パス → 今回の分類）。
        resolved: 前回は問題で、今回は最新になった・無くなった結果（パス → 前回の分類）。
        changed: 問題のまま分類が変わった結果（パス → (前回の分類, 今回の分類)）。
        continuing: 同じ分類のまま残っている結果（パス → 分類）。
    """

    new: dict[str, str]
    resolved: dict[str, str]
    changed: dict[str, tuple[str, str]]
    continuing: dict[str, str]

    @property
    def has_change(self) -> bool:
        """新規・解消・分類変化のいずれかがあれば True を返す。"""
        return bool(self.new or self.resolved or self.changed)


def problem_state(report: dict[str, Any]) -> dict[str, str]:
    """判定結果から問題（最新以外）の状態を取り出す。

    Args:
        report: `build_report_data` の戻り値。
    Returns:
        結果パス → 分類。
    """
    return {
        entry["path"]: entry["status"]
        for entry in report["results"]
        if entry["status"] != STATUS_UP_TO_DATE
    }


def format_state_marker(state: dict[str, str]) -> str:
    """問題の状態を埋め込んだ不可視マーカーを作る。

    Args:
        state: 結果パス → 分類。
    Returns:
        HTML コメント形式のマーカー。
    """
    tokens = " ".join(
        f"{quote(path, safe=_PATH_SAFE_CHARS)}={status}" for path, status in sorted(state.items())
    )
    return f"<!-- {_MARKER_LABEL} {tokens} -->"


def extract_latest_state(bodies: Iterable[str]) -> dict[str, str] | None:
    """本文・コメントの並びから、最後に現れたマーカーの状態を復元する。

    Args:
        bodies: Issue 本文に続けてコメント本文を古い順に並べたもの。
    Returns:
        結果パス → 分類。マーカーが1つも無ければ None。
    Raises:
        ValueError: マーカーの中身が `パス=分類` の形式でない場合。
    """
    latest: str | None = None
    for body in bodies:
        matches = _MARKER_PATTERN.findall(body or "")
        if matches:
            latest = matches[-1]
    if latest is None:
        return None
    state: dict[str, str] = {}
    for token in latest.split():
        encoded_path, separator, status = token.rpartition("=")
        if not separator or not encoded_path or status not in STATUS_ORDER:
            raise ValueError(f"マーカーの形式が不正です: {token}")
        state[unquote(encoded_path)] = status
    return state


def load_issue_bodies(issue_json_path: Path) -> list[str]:
    """`gh issue view {番号} --json body,comments` の保存ファイルから本文の並びを取り出す。

    空ファイル（空白だけのものを含む）は `gh` の失敗（認証切れ等）でリダイレクト先だけが
    作られた状態とみなし、例外にする（前回状態を復元できないまま差分を作ると、継続中の
    問題をすべて「新規」として再掲してしまうため）。

    Args:
        issue_json_path: 保存ファイルのパス。
    Returns:
        Issue 本文に続けてコメント本文を古い順に並べたリスト。
    Raises:
        ValueError: ファイルが空・JSON オブジェクトでない・`comments` がリストでない場合。
    """
    text = issue_json_path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(
            f"報告 Issue のファイルが空です（gh の失敗が疑われます）: {issue_json_path.name}"
        )
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("comments", []), list):
        raise ValueError(f"報告 Issue の JSON の形式が不正です: {issue_json_path.name}")
    bodies = [str(data.get("body") or "")]
    bodies.extend(
        str(comment.get("body") or "")
        for comment in data.get("comments", [])
        if isinstance(comment, dict)
    )
    return bodies


def diff_states(previous: dict[str, str], current: dict[str, str]) -> StateDiff:
    """前回と今回の問題の状態を比べる。

    Args:
        previous: 前回の問題（結果パス → 分類）。
        current: 今回の問題（結果パス → 分類）。
    Returns:
        差分。
    """
    return StateDiff(
        new={path: status for path, status in current.items() if path not in previous},
        resolved={path: status for path, status in previous.items() if path not in current},
        changed={
            path: (previous[path], status)
            for path, status in current.items()
            if path in previous and previous[path] != status
        },
        continuing={
            path: status for path, status in current.items() if previous.get(path) == status
        },
    )


def _format_reason_lines(report: dict[str, Any], paths: Iterable[str]) -> list[str]:
    """指定した結果の分類と理由を箇条書きにする。"""
    entries = {entry["path"]: entry for entry in report["results"]}
    lines = []
    for path in sorted(paths):
        entry = entries[path]
        reasons = "／".join(item["reason"] for item in entry["reasons"])
        lines.append(f"- `{path}`（{STATUS_LABELS[entry['status']]}）: {reasons}")
    return lines


def format_issue_body(report: dict[str, Any]) -> str:
    """新規起票する報告 Issue の本文を作る。

    Args:
        report: `build_report_data` の戻り値。
    Returns:
        Issue 本文（判定結果・前回状態のマーカー・識別用フッタ）。
    """
    return (
        format_markdown_report(report)
        + "\n"
        + format_state_marker(problem_state(report))
        + f"\n\n---\n{ISSUE_FOOTER}\n"
    )


def format_diff_comment(report: dict[str, Any], diff: StateDiff, run_date: dt.date) -> str:
    """報告 Issue に追記する差分コメントを作る（全件解消時は解消一覧になる）。

    継続中の問題は件数と一覧（折りたたみ）を載せ、マーカーには今回の問題をすべて記録する
    （最新のコメント1件で現状を復元できるようにするため）。

    Args:
        report: `build_report_data` の戻り値。
        diff: 前回との差分。
        run_date: 実行日。
    Returns:
        コメント本文。
    """
    counts = report["counts"]
    lines = [
        f"## 陳腐化検出 差分報告 ({run_date:%Y-%m-%d})",
        "",
        f"- 基準コミット（HEAD）: `{report['head_commit']}`",
        "- 今回の件数: "
        + "／".join(f"{STATUS_LABELS[status]} {counts[status]}" for status in STATUS_ORDER),
        "",
        "### 新規",
        "",
    ]
    lines.extend(_format_reason_lines(report, diff.new) or ["- なし"])
    lines.extend(["", "### 分類変化", ""])
    lines.extend(
        f"- `{path}`: {STATUS_LABELS[before]} → {STATUS_LABELS[after]}"
        for path, (before, after) in sorted(diff.changed.items())
    )
    if not diff.changed:
        lines.append("- なし")
    lines.extend(["", "### 解消", ""])
    lines.extend(
        f"- `{path}`（前回: {STATUS_LABELS[status]}）"
        for path, status in sorted(diff.resolved.items())
    )
    if not diff.resolved:
        lines.append("- なし")
    lines.extend(["", f"### 継続（{len(diff.continuing)} 件）", ""])
    if diff.continuing:
        lines.extend(["<details><summary>一覧</summary>", ""])
        lines.extend(_format_reason_lines(report, diff.continuing))
        lines.extend(["", "</details>"])
    else:
        lines.append("- なし")
    lines.extend(["", format_state_marker(problem_state(report)), "", "---", COMMENT_FOOTER])
    return "\n".join(lines) + "\n"


def build_report_text(
    report: dict[str, Any], previous: dict[str, str] | None, run_date: dt.date
) -> tuple[int, str | None]:
    """報告モードで書き出す本文と終了コードを決める。

    Args:
        report: `build_report_data` の戻り値。
        previous: 前回の問題の状態。報告 Issue が無い（新規起票の判断をする）場合は None。
        run_date: 実行日。
    Returns:
        (終了コード, 書き出す本文)。書き出す内容が無ければ本文は None。
    """
    current = problem_state(report)
    if previous is None:
        if not current:
            return EXIT_NO_CHANGE, None
        return EXIT_REPORT_WRITTEN, format_issue_body(report)
    diff = diff_states(previous, current)
    if not current:
        if not previous:
            return EXIT_NO_CHANGE, None
        return EXIT_ALL_RESOLVED, format_diff_comment(report, diff, run_date)
    if not diff.has_change:
        return EXIT_NO_CHANGE, None
    return EXIT_REPORT_WRITTEN, format_diff_comment(report, diff, run_date)


def load_previous_state(issue_json_path: Path) -> dict[str, str]:
    """報告 Issue の保存ファイルから前回の問題の状態を復元する。

    Args:
        issue_json_path: `gh issue view {番号} --json body,comments` の保存ファイル。
    Returns:
        前回の問題（結果パス → 分類）。
    Raises:
        ValueError: ファイルが不正、またはマーカーが1つも無い場合。
    """
    state = extract_latest_state(load_issue_bodies(issue_json_path))
    if state is None:
        # 本スクリプトが作る本文・コメントには必ずマーカーがあるため、無いのは本文の
        # 手動編集など想定外の状態とみなし、推測で差分を作らずに止める
        raise ValueError(f"前回状態のマーカーが見つかりません: {issue_json_path.name}")
    return state


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(description="分析結果の陳腐化を検出する")
    parser.add_argument(
        "--results-root",
        default=str(DEFAULT_RESULTS_ROOT),
        help="走査するディレクトリ（プロジェクトルート基準の相対/絶対パス）",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "来歴の入力パスの基準ディレクトリ（省略時はプロジェクトルート）。"
            "入力ファイルは読み取り（ハッシュ計算）だけに使う"
        ),
    )
    parser.add_argument(
        "--extra-watch-path",
        action="append",
        default=[],
        help="生成スクリプトと既定の監視パスに加えて差分を監視するパス（複数指定可）",
    )
    parser.add_argument("--output-json", default=None, help="判定結果（JSON）の出力先")
    parser.add_argument(
        "--output-md", default=None, help="判定結果（Markdown）の出力先。省略時は標準出力"
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help="報告モード: 新規起票の本文または差分コメントの出力先",
    )
    parser.add_argument(
        "--previous-issue-json",
        default=None,
        help="報告モード: 報告 Issue（gh issue view {番号} --json body,comments）の保存ファイル",
    )
    args = parser.parse_args(argv)
    if args.previous_issue_json and not args.report_output:
        parser.error("--previous-issue-json は --report-output と組み合わせて指定してください")
    return args


def _resolve(value: str, project_root: Path) -> Path:
    """相対パスをプロジェクトルート基準で解決する。"""
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。終了コードはモジュールの説明を参照。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # Windows の既定コードページでも日本語の出力が化けないようにする
            stream.reconfigure(encoding="utf-8")
    args = _parse_args(argv)
    project_root = PROJECT_ROOT
    results_root = _resolve(args.results_root, project_root)
    data_root = _resolve(args.data_root, project_root) if args.data_root else project_root
    if not results_root.is_dir():
        print(f"走査先のディレクトリがありません: {results_root}", file=sys.stderr)
        return EXIT_FAILURE
    previous: dict[str, str] | None = None
    if args.previous_issue_json:
        try:
            # 大容量の入力のハッシュ計算より先に読み、読めなければ判定せずに止める
            previous = load_previous_state(_resolve(args.previous_issue_json, project_root))
        except (OSError, ValueError) as exc:
            print(f"報告 Issue を読めませんでした: {exc}", file=sys.stderr)
            return EXIT_FAILURE
    git = GitRepository(project_root)
    head_commit = git.head_commit()
    if head_commit is None:
        print("git の HEAD を取得できないため、コードの差分を判定できません。", file=sys.stderr)
        return EXIT_FAILURE

    hash_cache: dict[Path, str] = {}
    extra_watch_paths = tuple(args.extra_watch_path)
    results = [
        check_result_file(path, project_root, data_root, git, hash_cache, extra_watch_paths)
        for path in find_result_files(results_root)
    ]
    report = build_report_data(
        results,
        head_commit,
        to_project_relative_string(results_root, project_root),
        dt.datetime.now(dt.timezone.utc),
    )
    markdown = format_markdown_report(report)
    if args.output_json:
        output_json = prepare_output_path(Path(args.output_json), project_root)
        output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.output_md:
        prepare_output_path(Path(args.output_md), project_root).write_text(
            markdown, encoding="utf-8"
        )
    else:
        print(markdown, end="")
    counts = report["counts"]
    summary = "／".join(f"{STATUS_LABELS[status]} {counts[status]}" for status in STATUS_ORDER)
    print(f"判定件数 {len(results)} 件（{summary}）", file=sys.stderr)
    if not args.report_output:
        return EXIT_REPORT_WRITTEN

    exit_code, text = build_report_text(report, previous, dt.date.today())
    if text is None:
        print("報告に書き込む内容がないため、本文は書き出しません。", file=sys.stderr)
        return exit_code
    report_path = prepare_output_path(Path(args.report_output), project_root)
    report_path.write_text(text, encoding="utf-8")
    print(f"報告本文を書き出しました（終了コード {exit_code}）: {report_path}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
