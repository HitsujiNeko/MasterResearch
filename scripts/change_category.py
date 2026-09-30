"""変更区分（R／S）を差分パスから判定する。

task-workflow.md「変更区分（唯一の定義）」のうち、パスで決まる区分表（R・S の対象）の正本。
規則は本ファイルの ``RULES`` にのみ持ち、文書側には要約とリンクだけを置く。
D（非実質）は変更内容で決まるため判定しない。出力するのは「パスから見た下限の区分」（S か R）。

使い方:
    python scripts/change_category.py                   # origin/main...HEAD の差分を判定
    python scripts/change_category.py --base main       # 比較基準を変える
    python scripts/change_category.py src/a.py tests/b.py  # 予定の変更パスを判定
    python scripts/change_category.py --expect S        # 確定済みの区分と照合する

終了コード:
    0: 成功（``--expect`` 指定時は期待した区分以内）
    2: 実行エラー（git の失敗・比較基準なし・差分 0 件・引数不正・絶対パス・``..`` を含むパス・
       想定外の例外）
    3: ``--expect`` より重い区分のパスがある
    （1 は使わない。Python 自体の起動失敗・構文エラーも 1 で終わるため、区分違反と区別できない）

conda 環境の外（``python`` / ``python3``）でも動くよう、標準ライブラリのみを使い、
``src`` パッケージを import しない。git の fetch は行わない（読み取り専用）。
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from collections.abc import Sequence
from typing import NamedTuple

# 終了コード（1 は Python の起動失敗等と重なるため使わない）
EXIT_OK = 0
EXIT_ERROR = 2
EXIT_HEAVIER = 3

# 区分の重さ（大きいほど重い）
CATEGORY_WEIGHT = {"S": 1, "R": 2}

# どの規則にも一致しないパスの区分と根拠（安全側の既定値）
DEFAULT_CATEGORY = "R"
DEFAULT_REASON = "未列挙（既定 R）"

# 既定の比較基準
DEFAULT_BASE = "origin/main"

# パスの区分表（区分, パターン, 説明）
# 照合は fnmatch.fnmatchcase（大文字小文字を区別）。``*`` は ``/`` にも一致するため、
# ``src/analysis/*`` で配下全体を表す。複数の規則に一致した場合は重い方（R > S）を採る。
RULES: tuple[tuple[str, str, str], ...] = (
    # --- R: 結果影響 ---
    ("R", "src/analysis/*", "分析コード"),
    ("R", "src/common/*", "共通モジュール"),
    ("R", "src/preprocessing/*", "前処理コード"),
    ("R", "src/gee/*", "GEE 処理コード"),
    ("R", "src/module/*", "処理モジュール"),
    ("R", "src/visualization/*", "可視化コード"),
    ("R", "src/js/*", "JavaScript コード"),
    ("R", "src/fortran/*", "Fortran コード"),
    ("R", "data/input/*", "git 管理下の入力データ"),
    ("R", "data/output/*", "git 管理下の出力データ"),
    ("R", "images/*", "図"),
    ("R", "qgis/styles/*", "QGIS スタイル"),
    ("R", "environment.yml", "依存定義"),
    ("R", "requirements.txt", "依存定義"),
    ("R", "pyproject.toml", "依存定義"),
    ("R", "docs/01_planning/*", "研究計画文書"),
    ("R", "docs/02_methods/analysis_workflow.md", "手法文書"),
    ("R", "docs/02_methods/calc_urban_params*", "手法文書"),
    ("R", "docs/02_methods/gee_calc_*", "手法文書"),
    ("R", "docs/02_methods/calc_LST_report.md", "手法文書"),
    ("R", "docs/02_methods/observation_selection.md", "手法文書"),
    ("R", "docs/02_methods/analysis_rq3_*", "手法文書"),
    ("R", "docs/02_methods/data_management_guide.md", "手法文書"),
    ("R", "docs/03_results/*", "結果文書"),
    # --- S: 支援・運用 ---
    ("S", ".claude/*", "Claude Code 設定・コマンド・スキル"),
    ("S", ".github/*", "ワークフロー・テンプレート"),
    ("S", "CLAUDE.md", "AI 向け指示書"),
    ("S", "AGENTS.md", "AI 向け指示書"),
    ("S", "docs/02_methods/CodingRule.md", "運用文書"),
    ("S", "docs/02_methods/skill_operation_rules.md", "運用文書"),
    ("S", "docs/02_methods/claude_workflow_regression_tests.md", "運用文書"),
    ("S", "docs/02_methods/qgis_*", "運用文書"),
    ("S", "docs/README.md", "文書カタログ"),
    ("S", "docs/setup*", "環境構築文書"),
    ("S", "docs/04_archive/*", "参考資料"),
    ("S", "README.md", "リポジトリ README"),
    ("S", "src/doc_checks/*", "文書整合性チェック"),
    ("S", "src/literature/*", "文献管理"),
    ("S", "scripts/*", "補助スクリプト"),
    ("S", "tests/*", "テストのみの変更"),
    ("S", ".pre-commit-config.yaml", "ツール設定"),
    ("S", ".markdownlint*", "ツール設定"),
    ("S", ".coderabbit.yaml", "ツール設定"),
    ("S", ".mcp.json", "ツール設定"),
    ("S", ".vscode/*", "ツール設定"),
    ("S", ".gitignore", "ツール設定"),
    ("S", ".gitattributes", "ツール設定"),
    ("S", ".env.example", "ツール設定"),
)

# 絶対パスの判定（POSIX の先頭 / と Windows のドライブレター）
_ABSOLUTE_PATH_PATTERN = re.compile(r"^(/|[A-Za-z]:)")


class ChangeCategoryError(Exception):
    """判定を続行できない実行エラー（終了コード 2 に対応する）。"""


class PathResult(NamedTuple):
    """1 パスの判定結果。"""

    category: str
    path: str
    reason: str


def normalize_path(path: str) -> str:
    """リポジトリ相対パスを照合用の形（区切り ``/``・先頭 ``./`` なし）に正規化する。

    末尾の ``/``（ディレクトリ指定）は残す。``src/analysis/`` は ``src/analysis/*`` に一致する。
    前後の空白は除かない（git が返す実在のパスを書き換えて軽い区分の規則に一致させないため）。
    コマンドライン引数の空白除去は呼び出し側で行う。

    Args:
        path: 入力パス（``\\`` 区切りでもよい）。

    Returns:
        正規化したパス。

    Raises:
        ChangeCategoryError: 空のパス、絶対パス、または ``..`` を含むパスの場合。
    """
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ChangeCategoryError(f"空のパスは判定できません: {path!r}")
    if _ABSOLUTE_PATH_PATTERN.match(normalized):
        raise ChangeCategoryError(f"リポジトリ相対パスを指定してください（絶対パス）: {path}")
    # scripts/../src/x.py のようなパスが軽い区分の規則に一致するのを防ぐ
    if ".." in normalized.split("/"):
        raise ChangeCategoryError(f"「..」を含むパスは判定できません: {path}")
    return normalized


def classify_path(path: str) -> PathResult:
    """正規化済みのパス 1 件の区分を判定する。

    一致した規則のうち最も重い区分を採り、同じ区分では先に定義された規則を根拠とする。
    どの規則にも一致しない場合は既定の R とする。

    Args:
        path: ``normalize_path`` で正規化済みのパス。

    Returns:
        判定結果。
    """
    best: tuple[str, str, str] | None = None
    for category, pattern, description in RULES:
        if not fnmatch.fnmatchcase(path, pattern):
            continue
        if best is None or CATEGORY_WEIGHT[category] > CATEGORY_WEIGHT[best[0]]:
            best = (category, pattern, description)
    if best is None:
        return PathResult(DEFAULT_CATEGORY, path, DEFAULT_REASON)
    category, pattern, description = best
    return PathResult(category, path, f"{pattern}: {description}")


def get_diff_paths(base: str, cwd: str | None = None) -> list[str]:
    """``{base}...HEAD`` の変更パスを git から取得する。

    リネーム元を見落とさないよう ``--no-renames`` を付ける。``-z`` はパスを加工せずに出力する
    ため、日本語パスも 8 進エスケープされない（``core.quotepath`` の指定は不要）。

    Args:
        base: 比較基準（例: ``origin/main``）。
        cwd: git を実行するディレクトリ（省略時はカレントディレクトリ）。

    Returns:
        変更パスの一覧（git の出力順）。

    Raises:
        ChangeCategoryError: git が見つからない、または git diff が失敗した場合。
    """
    command = ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"]
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
    except FileNotFoundError as error:
        raise ChangeCategoryError("git コマンドが見つかりません") from error
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ChangeCategoryError(
            f"git diff に失敗しました（比較基準: {base}）。"
            f"比較基準が存在するか確認してください（git fetch の実行漏れ等）。\n{stderr}"
        )
    output = completed.stdout.decode("utf-8", errors="replace")
    return [path for path in output.split("\0") if path]


def classify_paths(paths: Sequence[str]) -> list[PathResult]:
    """複数パスを正規化・重複除去して判定し、R を先にした順で返す。

    Args:
        paths: 判定するパスの一覧。

    Returns:
        判定結果（R → S の順。同じ区分内は入力順）。

    Raises:
        ChangeCategoryError: 正規化できないパスが含まれる場合。
    """
    unique_paths = list(dict.fromkeys(normalize_path(path) for path in paths))
    results = [classify_path(path) for path in unique_paths]
    return sorted(results, key=lambda result: -CATEGORY_WEIGHT[result.category])


def overall_category(results: Sequence[PathResult]) -> str:
    """判定結果全体の区分（最も重い区分）を返す。

    Args:
        results: 判定結果（1 件以上）。

    Returns:
        ``"R"`` または ``"S"``。
    """
    return max((result.category for result in results), key=CATEGORY_WEIGHT.__getitem__)


def format_report(results: Sequence[PathResult]) -> list[str]:
    """判定結果を 1 パス 1 行の表示用テキストにする（最終行は全体の区分）。

    Args:
        results: ``classify_paths`` の戻り値。

    Returns:
        出力行の一覧。
    """
    lines = [f"{result.category}  {result.path}  [{result.reason}]" for result in results]
    count_r = sum(1 for result in results if result.category == "R")
    count_s = len(results) - count_r
    lines.append(f"全体: {overall_category(results)}（R {count_r} 件 / S {count_s} 件）")
    return lines


def check_expected(results: Sequence[PathResult], expected: str) -> tuple[int, list[str]]:
    """確定済みの区分と判定結果を照合し、終了コードと表示メッセージを返す。

    - R: 常に 0
    - S: R のパスがあれば 3（``EXIT_HEAVIER``）
    - D: 0。D は内容で決まるため、R のパスを「内容確認が必要」として列挙する

    Args:
        results: ``classify_paths`` の戻り値。
        expected: 確定済みの区分（``"R"`` / ``"S"`` / ``"D"``）。

    Returns:
        (終了コード, メッセージ行の一覧)。
    """
    r_paths = [result.path for result in results if result.category == "R"]
    if expected == "S" and r_paths:
        messages = ["確定済みの区分 S より重い R のパスがあります。区分の確定をやり直してください:"]
        return EXIT_HEAVIER, messages + [f"  {path}" for path in r_paths]
    if expected == "D":
        messages = ["区分 D はパスではなく変更内容で決まるため、パスからは判定しません。"]
        if r_paths:
            messages.append(
                "以下の R のパスは、変更が D の定義（挙動・出力を変えない）に収まるか内容を"
                "確認してください:"
            )
            messages.extend(f"  {path}" for path in r_paths)
        else:
            messages.append("R のパスはありません。")
        messages.append("S のパスも、変更が D の定義に収まるか内容を確認してください。")
        return EXIT_OK, messages
    return EXIT_OK, [f"確定済みの区分 {expected} と矛盾するパスはありません。"]


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作る。"""
    parser = argparse.ArgumentParser(
        description="変更区分（R／S）を差分パスから判定する（D は内容で決まるため判定しない）。",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "判定するパス（予定の変更ファイル）。ディレクトリは末尾に / を付ける"
            "（付けないと未列挙として既定 R になる）。省略時は git の差分を判定する"
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help=f"git 差分の比較基準（既定: {DEFAULT_BASE}）。パス指定とは併用できない",
    )
    parser.add_argument(
        "--expect",
        choices=("R", "S", "D"),
        default=None,
        help="確定済みの区分。これより重いパスがあれば終了コード 3",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """判定を実行して結果を標準出力に書き、終了コードを返す。

    Args:
        argv: コマンドライン引数（省略時は ``sys.argv[1:]``）。

    Returns:
        終了コード（0 / 3。実行エラーは例外で呼び出し側に伝える）。

    Raises:
        ChangeCategoryError: 判定を続行できない場合。
    """
    args = build_parser().parse_args(argv)
    if args.paths and args.base is not None:
        raise ChangeCategoryError("パス指定と --base は併用できません")
    if args.paths:
        # コマンドライン引数の前後の空白は入力の揺れとして除く（git のパスは加工しない）
        paths = [path.strip() for path in args.paths]
    else:
        base = args.base if args.base is not None else DEFAULT_BASE
        paths = get_diff_paths(base)
        if not paths:
            raise ChangeCategoryError(f"差分がありません（比較基準: {base}...HEAD）")

    results = classify_paths(paths)
    for line in format_report(results):
        print(line)
    if args.expect is None:
        return EXIT_OK
    exit_code, messages = check_expected(results, args.expect)
    print()
    for message in messages:
        print(message)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """エントリーポイント。実行エラーは標準エラーに出して終了コード 2 を返す。

    想定外の例外も 2 とし、実行エラーの終了コードを 1 つにまとめる。
    """
    try:
        return run(argv)
    except ChangeCategoryError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as error:
        # 実行エラーを 2 にまとめるため、想定外の例外も広く捕捉する
        print(f"エラー: 想定外のエラーで判定できませんでした: {error!r}", file=sys.stderr)
        return EXIT_ERROR


def _configure_utf8_output() -> None:
    """標準出力・標準エラーを UTF-8 にする（Windows で cp932 になり文字化けするのを防ぐ）。

    PowerShell 5.1 の既定（cp932）で受け取ると表示は文字化けするが、判定結果は終了コードで
    返すため、呼び出し側は出力の文字列に依存しない。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    _configure_utf8_output()
    sys.exit(main())
