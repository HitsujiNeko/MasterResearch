"""分析の再現性チェック。

設定ファイル（既定は `scripts/reproducibility_targets.json`）に書いた対象構成ごとに、
分析スクリプトを一時出力先で再実行し、生成された `*_results.json` を保存済みの
結果 JSON と照合する。構成ごとに 一致/不一致・不一致のキーと値・所要時間・
ライブラリ版の差（環境ドリフトの手がかり）を出力する。

設定ファイルの形式（`targets` の各要素が1構成）:

- `name`: 構成名（一意）
- `module`: 実行するモジュール（例: `src.analysis.analysis_rq3_limited`）
- `args`: `--output-dir` 以外の CLI 引数のリスト（出力先は本スクリプトが指定する）
- `reference_results`: 照合する保存済み結果 JSON（プロジェクト相対）
- `compare_keys`（任意）: 照合するトップレベルのキー。既定は `DEFAULT_COMPARE_KEYS`
- `abs_tolerance`・`rel_tolerance`（任意）: 数値の許容誤差（`math.isclose` に渡す）

照合の規則:

- `compare_keys` 配下の値を葉まで平らにし、同じキーの値どうしを比べる
- 数値（真偽値を除く）は許容誤差つきで比べ、それ以外は完全一致を求める
- 片方にしかないキーも不一致として列挙する
- 出力ファイルの一覧（`outputs`）とパス類（キー名が `_path` で終わるもの）は、
  出力先によって必ず変わるため照合しない

安全のため、再実行の出力先（`--work-dir`）が `data/output/` の内側なら拒否する
（保存済み結果の上書きを防ぐため）。`--work-dir` を省略した場合は一時ディレクトリを作り、
終了時に削除する（`--keep-work-dir` で残せる）。

終了コード: 0=全構成が一致／1=実行できない（設定の不正・再実行の失敗・結果の欠落）／
2=不一致がある

実行はプロジェクトルートから行う（`src` パッケージを import するため）。

```sh
python -m scripts.check_reproducibility --all --output-md reproducibility.md
```
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, to_project_relative_string

EXIT_ALL_MATCH = 0
EXIT_FAILURE = 1
EXIT_MISMATCH = 2

DEFAULT_CONFIG_PATH = Path("scripts") / "reproducibility_targets.json"

# 照合するトップレベルのキーの既定値（サンプル数・分割・特徴量・評価指標）
DEFAULT_COMPARE_KEYS: tuple[str, ...] = (
    "sample_size",
    "train_size",
    "test_size",
    "features",
    "random_split",
    "spatial_cv",
)

# 数値の許容誤差の既定値（同じ環境なら一致する前提で、浮動小数点の丸め差だけを許す）
DEFAULT_ABS_TOLERANCE = 1e-9
DEFAULT_REL_TOLERANCE = 1e-6

# 再実行1構成あたりの待ち時間の上限（秒）の既定値
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60

# 照合しないキー（出力先によって必ず変わる）
_IGNORED_KEYS = frozenset({"outputs"})
_IGNORED_KEY_SUFFIX = "_path"

# 失敗時に表示するログ末尾の行数
_LOG_TAIL_LINES = 20

# 保存済み結果の置き場所（再実行の出力先として拒否する範囲）
_PROTECTED_OUTPUT_DIR = Path("data") / "output"

# 判定結果の区分
STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_ERROR = "error"

STATUS_LABELS: dict[str, str] = {
    STATUS_MATCH: "一致",
    STATUS_MISMATCH: "不一致",
    STATUS_ERROR: "実行失敗",
}


@dataclass(frozen=True)
class ReproducibilityTarget:
    """再現性チェックの対象構成。

    Attributes:
        name: 構成名。
        module: 実行するモジュール名。
        args: `--output-dir` 以外の CLI 引数。
        reference_results: 照合する保存済み結果 JSON（プロジェクト相対）。
        compare_keys: 照合するトップレベルのキー。
        abs_tolerance: 数値の絶対許容誤差。
        rel_tolerance: 数値の相対許容誤差。
    """

    name: str
    module: str
    args: tuple[str, ...]
    reference_results: str
    compare_keys: tuple[str, ...] = DEFAULT_COMPARE_KEYS
    abs_tolerance: float = DEFAULT_ABS_TOLERANCE
    rel_tolerance: float = DEFAULT_REL_TOLERANCE


@dataclass
class TargetReport:
    """対象構成1件の照合結果。

    Attributes:
        name: 構成名。
        module: 実行したモジュール名。
        status: 判定（`match`・`mismatch`・`error`）。
        elapsed_seconds: 再実行の所要時間（秒。実行していなければ None）。
        compared_count: 照合した葉の数。
        mismatches: 不一致の一覧。
        package_differences: ライブラリ版の差（保存済み側に来歴が無ければ None）。
        error: 実行失敗の説明。
        log_path: 再実行のログファイル。
    """

    name: str
    module: str
    status: str = STATUS_ERROR
    elapsed_seconds: float | None = None
    compared_count: int = 0
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    package_differences: dict[str, dict[str, Any]] | None = None
    error: str | None = None
    log_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON 出力用の辞書に変換する。"""
        return {
            "name": self.name,
            "module": self.module,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "compared_count": self.compared_count,
            "mismatches": self.mismatches,
            "package_differences": self.package_differences,
            "error": self.error,
            "log_path": self.log_path,
        }


def _require_str(entry: dict[str, Any], key: str, label: str) -> str:
    """設定の必須の文字列項目を取り出す。"""
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: `{key}` は空でない文字列で指定してください")
    return value


def _optional_tolerance(entry: dict[str, Any], key: str, default: float, label: str) -> float:
    """設定の許容誤差を取り出す（省略時は既定値）。"""
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"{label}: `{key}` は0以上の数値で指定してください")
    return float(value)


def parse_target(entry: object, index: int) -> ReproducibilityTarget:
    """設定ファイルの1構成を検証して読み込む。

    Args:
        entry: `targets` の要素。
        index: 要素の位置（エラーメッセージ用）。
    Returns:
        対象構成。
    Raises:
        ValueError: 必須項目の欠落・型の不正・`--output-dir` の指定がある場合。
    """
    label = f"targets[{index}]"
    if not isinstance(entry, dict):
        raise ValueError(f"{label}: 構成はオブジェクトで指定してください")
    name = _require_str(entry, "name", label)
    label = f"{label}（{name}）"
    args = entry.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError(f"{label}: `args` は文字列のリストで指定してください")
    if any(arg == "--output-dir" or arg.startswith("--output-dir=") for arg in args):
        raise ValueError(
            f"{label}: `--output-dir` は本スクリプトが指定するため、args に書かないでください"
        )
    compare_keys = entry.get("compare_keys", list(DEFAULT_COMPARE_KEYS))
    if (
        not isinstance(compare_keys, list)
        or not compare_keys
        or not all(isinstance(key, str) and key for key in compare_keys)
    ):
        raise ValueError(f"{label}: `compare_keys` は空でない文字列のリストで指定してください")
    return ReproducibilityTarget(
        name=name,
        module=_require_str(entry, "module", label),
        args=tuple(args),
        reference_results=_require_str(entry, "reference_results", label),
        compare_keys=tuple(compare_keys),
        abs_tolerance=_optional_tolerance(entry, "abs_tolerance", DEFAULT_ABS_TOLERANCE, label),
        rel_tolerance=_optional_tolerance(entry, "rel_tolerance", DEFAULT_REL_TOLERANCE, label),
    )


def load_targets(config_path: Path) -> list[ReproducibilityTarget]:
    """設定ファイルから対象構成を読み込む。

    Args:
        config_path: 設定ファイルのパス。
    Returns:
        対象構成の一覧（記載順）。
    Raises:
        ValueError: JSON として読めない・`targets` が無い・構成名が重複する場合。
    """
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    entries = data.get("targets") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"設定ファイルに `targets`（リスト）がありません: {config_path.name}")
    targets = [parse_target(entry, index) for index, entry in enumerate(entries)]
    names = [target.name for target in targets]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValueError(f"構成名が重複しています: {duplicated}")
    return targets


def select_targets(
    targets: list[ReproducibilityTarget], names: list[str], select_all: bool
) -> list[ReproducibilityTarget]:
    """実行する構成を選ぶ。

    Args:
        targets: 設定ファイルの全構成。
        names: `--target` で指定された構成名。
        select_all: `--all` が指定されたか。
    Returns:
        選んだ構成（設定ファイルの記載順）。
    Raises:
        ValueError: 存在しない構成名が指定された場合。
    """
    if select_all:
        return list(targets)
    known = {target.name for target in targets}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"設定ファイルに無い構成名です: {unknown}（既知: {sorted(known)}）")
    return [target for target in targets if target.name in names]


def validate_work_dir(work_dir: Path, project_root: Path) -> None:
    """再実行の出力先が保存済み結果の置き場所（`data/output/`）の内側でないか確かめる。

    Args:
        work_dir: 出力先。
        project_root: プロジェクトルート。
    Raises:
        ValueError: 出力先が `data/output/` と同じか、その内側の場合。
    """
    protected = (project_root / _PROTECTED_OUTPUT_DIR).resolve()
    resolved = work_dir.resolve()
    if resolved == protected or resolved.is_relative_to(protected):
        raise ValueError(
            f"再実行の出力先に {_PROTECTED_OUTPUT_DIR.as_posix()}/ の内側は指定できません"
            f"（保存済み結果の上書きを防ぐため）: {resolved}"
        )


def flatten_values(value: object, prefix: str = "") -> dict[str, object]:
    """入れ子の値を葉まで平らにする（照合しないキーは除く）。

    Args:
        value: 平らにする値。
        prefix: キーの接頭辞。
    Returns:
        `a.b[0].c` 形式のキー → 葉の値。
    """
    if isinstance(value, dict):
        flat: dict[str, object] = {}
        for key, child in value.items():
            key = str(key)
            if key in _IGNORED_KEYS or key.endswith(_IGNORED_KEY_SUFFIX):
                continue
            flat.update(flatten_values(child, f"{prefix}.{key}" if prefix else key))
        return flat
    if isinstance(value, list):
        flat = {}
        for index, child in enumerate(value):
            flat.update(flatten_values(child, f"{prefix}[{index}]"))
        return flat
    return {prefix: value}


def _is_number(value: object) -> bool:
    """真偽値を除く数値かどうかを返す。"""
    return isinstance(value, int | float) and not isinstance(value, bool)


def values_match(
    reference: object, rerun: object, abs_tolerance: float, rel_tolerance: float
) -> bool:
    """葉の値どうしが一致するかを返す。

    Args:
        reference: 保存済み結果の値。
        rerun: 再実行結果の値。
        abs_tolerance: 数値の絶対許容誤差。
        rel_tolerance: 数値の相対許容誤差。
    Returns:
        一致すれば True。数値は許容誤差つき、それ以外は型と値の完全一致で判定する。
    """
    if _is_number(reference) and _is_number(rerun):
        return math.isclose(reference, rerun, rel_tol=rel_tolerance, abs_tol=abs_tolerance)
    return type(reference) is type(rerun) and reference == rerun


def compare_results(
    reference: dict[str, Any], rerun: dict[str, Any], target: ReproducibilityTarget
) -> tuple[int, list[dict[str, Any]]]:
    """保存済み結果と再実行結果を、照合するキーの範囲で比べる。

    Args:
        reference: 保存済み結果 JSON の内容。
        rerun: 再実行結果 JSON の内容。
        target: 対象構成（照合キー・許容誤差）。
    Returns:
        (照合した葉の数, 不一致の一覧)。不一致は `key`・`reference`・`rerun`・`reason` を持つ。
    """
    reference_flat: dict[str, object] = {}
    rerun_flat: dict[str, object] = {}
    for key in target.compare_keys:
        if key in reference:
            reference_flat.update(flatten_values(reference[key], key))
        if key in rerun:
            rerun_flat.update(flatten_values(rerun[key], key))
    mismatches = []
    for key in sorted(reference_flat.keys() | rerun_flat.keys()):
        if key not in rerun_flat:
            mismatches.append(
                {
                    "key": key,
                    "reference": reference_flat[key],
                    "rerun": None,
                    "reason": "再実行結果に無い",
                }
            )
        elif key not in reference_flat:
            mismatches.append(
                {
                    "key": key,
                    "reference": None,
                    "rerun": rerun_flat[key],
                    "reason": "保存済み結果に無い",
                }
            )
        elif not values_match(
            reference_flat[key], rerun_flat[key], target.abs_tolerance, target.rel_tolerance
        ):
            mismatches.append(
                {
                    "key": key,
                    "reference": reference_flat[key],
                    "rerun": rerun_flat[key],
                    "reason": "値が違う",
                }
            )
    return len(reference_flat.keys() | rerun_flat.keys()), mismatches


def compare_packages(
    reference: dict[str, Any], rerun: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    """保存済み結果と再実行結果の来歴に記録されたライブラリ版の差を返す。

    Args:
        reference: 保存済み結果 JSON の内容。
        rerun: 再実行結果 JSON の内容。
    Returns:
        版が違うライブラリ名 → `reference`・`rerun` の版。どちらかに来歴の版の記録が
        無ければ比較できないため None。
    """

    def packages_of(data: dict[str, Any]) -> dict[str, Any] | None:
        provenance = data.get("provenance")
        packages = provenance.get("packages") if isinstance(provenance, dict) else None
        return packages if isinstance(packages, dict) else None

    reference_packages = packages_of(reference)
    rerun_packages = packages_of(rerun)
    if reference_packages is None or rerun_packages is None:
        return None
    return {
        name: {"reference": reference_packages.get(name), "rerun": rerun_packages.get(name)}
        for name in sorted(reference_packages.keys() | rerun_packages.keys())
        if reference_packages.get(name) != rerun_packages.get(name)
    }


def build_command(target: ReproducibilityTarget, output_dir: Path) -> list[str]:
    """再実行のコマンドを組み立てる（現在の Python で `-m` 実行する）。

    Args:
        target: 対象構成。
        output_dir: 再実行の出力先。
    Returns:
        コマンドの引数リスト。
    """
    return [sys.executable, "-m", target.module, *target.args, "--output-dir", str(output_dir)]


def find_rerun_result(output_dir: Path) -> Path:
    """再実行の出力先から結果 JSON を1件だけ探す。

    Args:
        output_dir: 再実行の出力先。
    Returns:
        結果 JSON のパス。
    Raises:
        ValueError: 結果 JSON が無い、または複数ある場合。
    """
    found = sorted(output_dir.glob("*_results.json"))
    if len(found) != 1:
        names = [path.name for path in found]
        raise ValueError(
            f"再実行の結果 JSON がちょうど1件ではありません（{len(found)} 件: {names}）"
        )
    return found[0]


def _read_log_tail(log_path: Path) -> str:
    """ログファイルの末尾を読む（失敗時の説明用）。"""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-_LOG_TAIL_LINES:])


def run_target(
    target: ReproducibilityTarget,
    work_dir: Path,
    project_root: Path,
    timeout_seconds: float,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> TargetReport:
    """対象構成を再実行し、保存済み結果と照合する。

    子プロセスの出力は `{work_dir}/{構成名}.log` に書き出す（長時間処理の事後診断用）。

    Args:
        target: 対象構成。
        work_dir: 再実行の出力先の親ディレクトリ。
        project_root: 子プロセスの作業ディレクトリ・保存済み結果の基準。
        timeout_seconds: 待ち時間の上限（秒）。
        runner: 子プロセスの実行関数（テストで差し替える）。
    Returns:
        照合結果。
    """
    report = TargetReport(name=target.name, module=target.module)
    reference_path = project_root / target.reference_results
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        report.error = f"保存済み結果を読めない: {target.reference_results}（{exc}）"
        return report

    output_dir = work_dir / target.name
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / f"{target.name}.log"
    report.log_path = log_path.as_posix()
    started = time.perf_counter()
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            completed = runner(
                build_command(target, output_dir),
                cwd=project_root,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
    except subprocess.TimeoutExpired:
        report.elapsed_seconds = time.perf_counter() - started
        report.error = f"再実行が {timeout_seconds:g} 秒以内に終わらなかった"
        return report
    except OSError as exc:
        report.error = f"再実行を起動できない: {exc}"
        return report
    report.elapsed_seconds = time.perf_counter() - started
    if completed.returncode != 0:
        report.error = (
            f"再実行が終了コード {completed.returncode} で失敗した。ログ末尾:\n"
            f"{_read_log_tail(log_path)}"
        )
        return report

    try:
        rerun = json.loads(find_rerun_result(output_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report.error = f"再実行の結果 JSON を読めない: {exc}"
        return report
    report.compared_count, report.mismatches = compare_results(reference, rerun, target)
    report.package_differences = compare_packages(reference, rerun)
    report.status = STATUS_MISMATCH if report.mismatches else STATUS_MATCH
    return report


def _format_value(value: object) -> str:
    """Markdown の表に載せる値を短く整える。"""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + "..."


def format_markdown_report(reports: list[TargetReport], checked_at: dt.datetime) -> str:
    """照合結果を人が読む Markdown にする。

    Args:
        reports: 構成ごとの照合結果。
        checked_at: 実行日時。
    Returns:
        Markdown の本文。
    """
    lines = [
        "## 分析の再現性チェック",
        "",
        f"- 実行日時: {checked_at.isoformat()}",
        "",
        "| 構成 | 判定 | 照合した値 | 不一致 | 所要時間 |",
        "|---|---|---:|---:|---:|",
    ]
    for report in reports:
        elapsed = "-" if report.elapsed_seconds is None else f"{report.elapsed_seconds:.1f} 秒"
        lines.append(
            f"| {report.name} | {STATUS_LABELS[report.status]} | {report.compared_count} "
            f"| {len(report.mismatches)} | {elapsed} |"
        )
    for report in reports:
        lines.extend(["", f"### {report.name}", "", f"- モジュール: `{report.module}`"])
        if report.error:
            lines.extend(["- 実行失敗:", "", "```text", report.error, "```"])
            continue
        if report.mismatches:
            lines.extend(["", "| キー | 保存済み | 再実行 | 理由 |", "|---|---|---|---|"])
            lines.extend(
                f"| `{item['key']}` | {_format_value(item['reference'])} "
                f"| {_format_value(item['rerun'])} | {item['reason']} |"
                for item in report.mismatches
            )
        if report.package_differences is None:
            lines.append("- ライブラリ版の差: 比較不能（来歴にライブラリ版の記録が無い）")
        elif report.package_differences:
            differences = "、".join(
                f"{name} {versions['reference']} → {versions['rerun']}"
                for name, versions in report.package_differences.items()
            )
            lines.append(f"- ライブラリ版の差: {differences}")
        else:
            lines.append("- ライブラリ版の差: なし")
    return "\n".join(lines) + "\n"


def decide_exit_code(reports: list[TargetReport]) -> int:
    """照合結果から終了コードを決める（実行失敗を不一致より優先する）。

    Args:
        reports: 構成ごとの照合結果。
    Returns:
        終了コード。
    """
    statuses = {report.status for report in reports}
    if STATUS_ERROR in statuses:
        return EXIT_FAILURE
    if STATUS_MISMATCH in statuses:
        return EXIT_MISMATCH
    return EXIT_ALL_MATCH


def _positive_float(value: str) -> float:
    """正の数として引数を解釈する（argparse の type 用）。"""
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"数値を指定してください: {value}") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError(f"正の数を指定してください: {value}")
    return number


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(description="分析を再実行して保存済み結果と照合する")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--target", action="append", help="実行する構成名（複数指定可）")
    selection.add_argument("--all", action="store_true", help="設定ファイルの全構成を実行する")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="対象構成の設定ファイル")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="再実行の出力先（data/output/ の内側は不可）。省略時は一時ディレクトリ",
    )
    parser.add_argument(
        "--keep-work-dir",
        action="store_true",
        help="--work-dir 省略時に作った一時ディレクトリを終了後も残す",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="1構成あたりの待ち時間の上限（秒）",
    )
    parser.add_argument("--output-json", default=None, help="照合結果（JSON）の出力先")
    parser.add_argument(
        "--output-md", default=None, help="照合結果（Markdown）の出力先。省略時は標準出力"
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
    try:
        targets = select_targets(
            load_targets(_resolve(args.config, project_root)), args.target or [], args.all
        )
        if args.work_dir:
            work_dir = _resolve(args.work_dir, project_root)
            validate_work_dir(work_dir, project_root)
            created_temp = False
        else:
            work_dir = Path(tempfile.mkdtemp(prefix="reproducibility_"))
            created_temp = True
    except (OSError, ValueError) as exc:
        print(f"再現性チェックを開始できません: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    reports: list[TargetReport] = []
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, target in enumerate(targets, start=1):
            print(f"[{index}/{len(targets)}] {target.name} を再実行します…", file=sys.stderr)
            report = run_target(target, work_dir, project_root, args.timeout)
            elapsed = "-" if report.elapsed_seconds is None else f"{report.elapsed_seconds:.1f} 秒"
            print(
                f"[{index}/{len(targets)}] {target.name}: {STATUS_LABELS[report.status]}"
                f"（所要時間 {elapsed}）",
                file=sys.stderr,
            )
            reports.append(report)
    finally:
        if created_temp and not args.keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
            # 削除したログを指さないよう、ログのパスを消しておく
            for report in reports:
                report.log_path = None
        else:
            print(f"再実行の出力先: {work_dir}", file=sys.stderr)

    checked_at = dt.datetime.now(dt.timezone.utc)
    markdown = format_markdown_report(reports, checked_at)
    if args.output_json:
        data = {
            "checked_at": checked_at.isoformat(),
            "work_dir": to_project_relative_string(work_dir, project_root),
            "targets": [report.to_dict() for report in reports],
        }
        prepare_output_path(Path(args.output_json), project_root).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.output_md:
        prepare_output_path(Path(args.output_md), project_root).write_text(
            markdown, encoding="utf-8"
        )
    else:
        print(markdown, end="")
    return decide_exit_code(reports)


if __name__ == "__main__":
    raise SystemExit(main())
