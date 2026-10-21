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
4. 要再実行・コード変更（`stale_code`）: 記録コミットと現在の `HEAD` の間で、
   生成スクリプトまたは `src/common/` に差分がある。`git.dirty` が真、記録コミットが
   無い・ローカルに無い場合も、生成時のコードを復元できないためここに含める
5. 最新（`up_to_date`）: 上記のいずれにも当たらない

コードの差分は `git diff --name-only {記録コミット} HEAD -- {監視パス}` の木の比較で
判定する（祖先関係を問わないため、squash merge で消えた作業ブランチ上のコミットでも、
ローカルに残っていれば判定できる）。

既知の限界:

- 生成スクリプトが import する `src/common/` 以外のモジュール（`src/analysis/` の
  補助モジュール等）の変更は「コード変更」に含めない。必要なら `--extra-watch-path` で
  監視パスを追加する
- 入力のデータセット GPKG 自体を作るスクリプトの変更はたどらない（GPKG が作り直されれば
  ハッシュの不一致で検出される）
- 判定の基準は実行時にチェックアウトされている `HEAD` である

本スクリプトは結果ファイル・`docs/` を書き換えず、GitHub にも書き込まない。

終了コード: 0=判定を出力した／1=判定できない（git の `HEAD` を取得できない・走査先が無い）

実行はプロジェクトルートから行う（`src` パッケージを import するため）。

```sh
python -m scripts.check_result_staleness --output-json staleness.json --output-md staleness.md
```
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, to_project_relative_string
from src.common.summary import compute_file_sha256

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

# 生成スクリプトに加えて常に監視するパス（分析スクリプトが共通して import する処理）
DEFAULT_WATCH_PATHS: tuple[str, ...] = ("src/common",)

# git コマンドの待ち時間の上限（秒）
_GIT_TIMEOUT_SECONDS = 30


@dataclass
class StalenessResult:
    """結果ファイル1件の判定結果。

    Attributes:
        path: 結果ファイルのプロジェクト相対パス。
        reasons: 該当した分類ごとの理由（分類キー → 理由の一覧）。
        recorded_commit: 来歴に記録されたコミット（無ければ None）。
        changed_files: 記録コミットと `HEAD` の間で差分のあった監視対象ファイル。
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


def script_module_to_path(module_name: str) -> str:
    """生成スクリプトのモジュール名をリポジトリ相対のファイルパスに変換する。

    Args:
        module_name: `provenance.script` の値（例: `src.analysis.analysis_rq3_limited`）。
    Returns:
        ファイルパス（例: `src/analysis/analysis_rq3_limited.py`）。
    """
    return module_name.replace(".", "/") + ".py"


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


def check_code(
    result: StalenessResult,
    provenance: dict[str, Any],
    git: GitRepository,
    extra_watch_paths: tuple[str, ...],
) -> None:
    """生成時のコードと現在の `HEAD` の差分を判定し、理由を追加する。

    Args:
        result: 判定結果（理由の追加先）。
        provenance: 来歴の辞書。
        git: git 操作。
        extra_watch_paths: 既定に加えて監視するパス。
    """
    git_state = provenance.get("git")
    git_state = git_state if isinstance(git_state, dict) else {}
    commit = git_state.get("commit")
    if git_state.get("dirty") is True:
        result.add_reason(STATUS_STALE_CODE, "未コミットのコード変更がある状態で生成されている")
    if not isinstance(commit, str) or not commit:
        result.add_reason(STATUS_STALE_CODE, "来歴にコミットが記録されていない")
        return
    result.recorded_commit = commit
    if not git.commit_exists(commit):
        result.add_reason(
            STATUS_STALE_CODE, f"記録コミットがローカルに無い（fetch が必要か、失われた）: {commit}"
        )
        return

    script = provenance.get("script")
    watch_paths = list(DEFAULT_WATCH_PATHS) + list(extra_watch_paths)
    if isinstance(script, str) and script:
        watch_paths.insert(0, script_module_to_path(script))
    else:
        result.add_reason(STATUS_STALE_CODE, "来歴に生成スクリプトが記録されていない")
    changed = git.changed_files(commit, tuple(watch_paths))
    if changed is None:
        result.add_reason(STATUS_STALE_CODE, f"記録コミットとの差分を取得できない: {commit}")
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
        help="生成スクリプトと src/common/ に加えて差分を監視するパス（複数指定可）",
    )
    parser.add_argument("--output-json", default=None, help="判定結果（JSON）の出力先")
    parser.add_argument(
        "--output-md", default=None, help="判定結果（Markdown）の出力先。省略時は標準出力"
    )
    return parser.parse_args(argv)


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
        return 1
    git = GitRepository(project_root)
    head_commit = git.head_commit()
    if head_commit is None:
        print("git の HEAD を取得できないため、コードの差分を判定できません。", file=sys.stderr)
        return 1

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
