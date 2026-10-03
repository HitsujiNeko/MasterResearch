""".claude/hooks/dangerous_command_guard.py（危険な git/gh 操作の PreToolUse hook）のテスト。

対象は ``src`` パッケージ外のスクリプトのため、ファイルパスを指定して読み込む。
判定関数の単体テストに加え、hook としての終了コード（CLI）と、Python を実行できない
場合に拒否側へ倒すラッパー（.sh）の挙動を確認する。ラッパーのテストは bash が無い
環境では skip する。
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOK_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
SCRIPT_PATH = HOOK_DIR / "dangerous_command_guard.py"
WRAPPER_PATH = HOOK_DIR / "dangerous_command_guard.sh"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("dangerous_command_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()


def _blocked(command: str, tool: str = "Bash") -> bool:
    """コマンドが拒否されるか。"""
    return target.inspect_command(command, tool) is not None


# --- 回帰テスト項目書 観点1 の 3 形式（直接形・引数順変化形・すり抜け形） ---------------

# ルールグループごとの危険操作（git の引数部分、または gh の全体）
GIT_DANGEROUS = {
    "A_push_force": ["push --force", "push origin main --force", "push -f origin main"],
    "B_push_delete": ["push origin --delete feature", "push --delete origin feature"],
    "C_reset_hard": ["reset --hard HEAD~1", "reset --soft HEAD~1 --hard"],
    "D_clean": ["clean -f -d -x", "clean -fdx"],
}
GH_DANGEROUS = {
    "E_pr_merge": ["gh pr merge 99999", "gh pr merge 99999 --squash"],
    "F_repo_delete": ["gh repo delete owner/no-such-repo --yes"],
}

# 2026-07-08 にすり抜けを確認した 3 手法（サブシェル・git -C・変数展開）を含む形
BASH_EVASIONS = [
    "git {op}",
    "(cd /tmp/repo && git {op})",
    "git -C /tmp/repo {op}",
    "echo hello && git {op}",
    "true; git {op}",
    "$(git {op})",
    "`git {op}`",
    'bash -c "git {op}"',
    "sh -c 'cd /tmp/repo && git {op}'",
    "eval 'git {op}'",
    "{{ git {op}; }}",
    "if true; then git {op}; fi",
    "env GIT_TRACE=1 git {op}",
    "command git {op}",
    "/usr/bin/git {op}",
    "\\git {op}",
    "'git' {op}",
    "git --no-pager -c core.pager=cat --git-dir=.git {op}",
]
POWERSHELL_EVASIONS = [
    "git {op}",
    "Set-Location C:\\repo; git {op}",
    "git -C C:\\repo {op}",
    "(git {op})",
    "& git {op}",
    "& 'C:\\Program Files\\Git\\cmd\\git.exe' {op}",
    "& {{ git {op} }}",
    "Invoke-Expression 'git {op}'",
    'iex "git {op}"',
    'powershell -NoProfile -Command "git {op}"',
    'cmd /c "git {op}"',
    "git.exe {op}",
]


def _git_cases(evasions: list[str]) -> list[str]:
    return [form.format(op=op) for ops in GIT_DANGEROUS.values() for op in ops for form in evasions]


@pytest.mark.parametrize("command", _git_cases(BASH_EVASIONS))
def test_blocks_dangerous_git_in_bash(command: str) -> None:
    """git の危険操作を、直接形・引数順変化形・すり抜け形のいずれでも拒否する（Bash）。"""
    assert _blocked(command, "Bash")


@pytest.mark.parametrize("command", _git_cases(POWERSHELL_EVASIONS))
def test_blocks_dangerous_git_in_powershell(command: str) -> None:
    """git の危険操作を、直接形・引数順変化形・すり抜け形のいずれでも拒否する（PowerShell）。"""
    assert _blocked(command, "PowerShell")


@pytest.mark.parametrize(
    "command",
    [
        form.replace("git {op}", gh)
        for cmds in GH_DANGEROUS.values()
        for gh in cmds
        for form in ["git {op}", "echo hello && git {op}", "(git {op})", 'bash -c "git {op}"']
    ]
    + ["gh -R owner/repo pr merge 1", "gh pr -R owner/repo merge 1", "gh --repo=o/r pr merge"],
)
def test_blocks_dangerous_gh(command: str) -> None:
    """gh pr merge・gh repo delete を拒否する（-R/--repo の位置を問わない）。"""
    assert _blocked(command, "Bash")
    assert _blocked(command, "PowerShell")


# --- 変数展開など静的に判定できない形 ----------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'FLAG="--force"; git push origin main $FLAG',
        "F=-f; git push origin main $F",
        "FLAG=--force; git push origin main ${FLAG}",
        "MODE=--hard; git reset $MODE HEAD~1",
        "OPT=-fdx; git clean $OPT",
        'S=merge; gh pr "$S" 1',
        "G=git; $G push --force",
        "git push origin main $(echo --force)",
        "python -c \"import os; os.system('git push --force')\"",
        'eval "git push origin main $FLAG --force"',
        "echo 'git push --force' > x.sh && bash x.sh",
        "echo 'git push --force' | bash",
        "F=force; git push origin main --$F",
    ],
)
def test_blocks_dynamic_forms_with_danger_words(command: str) -> None:
    """変数展開等を含み、かつ危険語を含むコマンドは安全側で拒否する（Bash）。"""
    assert _blocked(command, "Bash")


@pytest.mark.parametrize(
    "command",
    [
        "$f = '--force'; git push origin main $f",
        "$args = @('push', '-f'); git @args",
        "& $git push --force",
        "Start-Process git -ArgumentList 'push','--force'",
        "Start-Process -FilePath git -ArgumentList 'reset --hard'",
        "$p = Start-Process git -ArgumentList 'clean','-fdx' -Wait -PassThru",
        "$out = git push --force",
        "powershell -EncodedCommand "
        + base64.b64encode("git push --force".encode("utf-16-le")).decode(),
    ],
)
def test_blocks_dynamic_forms_in_powershell(command: str) -> None:
    """PowerShell の変数・スプラッティング・Start-Process・-EncodedCommand を拒否する。"""
    assert _blocked(command, "PowerShell")


# --- 短縮オプション・省略形・refspec ----------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git push -uf origin main",
        "git push -fu origin main",
        "git push origin +main",
        "git push origin +HEAD:main",
        "git push origin :feature",
        "git push -d origin feature",
        "git push --mirror origin",
        "git push --prune origin",
        "git push --forc origin main",
        "git push origin main --force-with-lease=main",
        "git push --del origin feature",
        "git reset --har HEAD",
        "git clean -X",
        "git clean --force",
        "git clean -ffd",
        "git push $'--force'",
        "git push $'\\x2d\\x2dforce'",
        'git push "--force"',
        "git push --fo''rce",
        "git push \\\n  --force",
    ],
)
def test_blocks_option_variants(command: str) -> None:
    """結合した短縮オプション・長いオプションの省略形・+/: refspec・引用符の分割を拒否する。"""
    assert _blocked(command, "Bash")


def test_blocks_backtick_escape_in_powershell() -> None:
    """PowerShell のバッククォートでエスケープしたオプションも拒否する。"""
    assert _blocked("git push origin main `-`-force", "PowerShell")


def test_blocks_heredoc_fed_to_shell() -> None:
    """ヒアドキュメントで bash に渡したコマンドも検査する。"""
    assert _blocked("bash <<'EOF'\ngit push --force\nEOF", "Bash")


def test_blocks_unparsable_command_with_danger_words() -> None:
    """引用符が閉じていない等で解析できない場合も、危険語を含めば拒否する。"""
    assert _blocked("git push --force 'unterminated", "Bash")


# --- 誤検知しないこと ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "git push -u origin 299/add-dangerous-command-guard-hook",
        "git push --force-if-includes origin main",
        "git push origin HEAD:refs/heads/feature",
        "git push origin $BRANCH",
        'git push -u origin "$(git branch --show-current)"',
        "git -C /tmp/repo log --oneline",
        "git reset --soft HEAD~1",
        "git reset HEAD file.txt",
        "git clean -n",
        "git clean -fdn",
        "git clean --dry-run -fdx",
        "git log --grep=force",
        'git commit -m "docs: git push --force を禁止する"',
        "git commit -F msg.txt",
        "echo 'git push --force'",
        "grep -n 'reset --hard' docs/README.md",
        "gh pr view 5 --json mergeable,mergedAt",
        "gh pr create --title t --body-file body.md",
        "gh pr list --search 'is:merged'",
        "gh repo view",
        "git merge origin/main",
        "git branch -d old-feature",
        "rm -rf build && git status",
        "cd /tmp/repo && git log HEAD@{1}",
        "git commit -m \"$(cat <<'EOF'\nfix: avoid git push --force\n\ndon't (really)\nEOF\n)\"",
        "cat <<'EOF' > notes.md\ngit reset --hard は使わない\nEOF",
        "python scripts/change_category.py --expect S",
        "for f in *.py; do ruff check $f; done",
    ],
)
def test_allows_safe_bash_commands(command: str) -> None:
    """正当な操作・危険語を文字列として含むだけのコマンドは許可する（Bash）。"""
    assert not _blocked(command, "Bash")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git -C C:\\repo log --oneline",
        "git commit -m @'\nfix: git push --force を禁止する\n'@",
        "$b = git branch --show-current; git push -u origin $b",
        "Get-Content x.txt | Select-String 'reset --hard'",
        "Remove-Item -Recurse -Force build",
        "gh pr view 5",
    ],
)
def test_allows_safe_powershell_commands(command: str) -> None:
    """正当な操作・危険語を文字列として含むだけのコマンドは許可する（PowerShell）。"""
    assert not _blocked(command, "PowerShell")


def test_ignores_other_tools_and_empty_command() -> None:
    """Bash・PowerShell 以外のツールと空のコマンドは検査しない。"""
    assert target.inspect_command("git push --force", "Read") is None
    assert target.inspect_command("   ", "Bash") is None


def test_reason_names_the_operation() -> None:
    """拒否理由に検出した操作が含まれる。"""
    assert "git push" in target.inspect_command("git push -f", "Bash")
    assert "reset --hard" in target.inspect_command("git reset --hard", "Bash")


# --- CLI（hook としての終了コード） ------------------------------------------------


def _run_cli(stdin: str) -> subprocess.CompletedProcess[bytes]:
    """判定スクリプトを hook と同じく標準入力つきで実行する。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=stdin.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )


def _hook_input(command: str, tool: str = "Bash") -> str:
    """Claude Code が PreToolUse hook に渡す JSON を模す。"""
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"command": command, "description": "テスト"},
        }
    )


def test_cli_denies_with_exit_code_2() -> None:
    """拒否は終了コード 2 と標準エラーの理由で返す。"""
    result = _run_cli(_hook_input("git -C repo push --force", "PowerShell"))
    assert result.returncode == 2
    assert "危険操作ガード" in result.stderr.decode("utf-8")


def test_cli_allows_with_exit_code_0() -> None:
    """許可は終了コード 0 で、標準エラーに何も出さない。"""
    result = _run_cli(_hook_input("git status"))
    assert result.returncode == 0
    assert result.stderr == b""


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [("not json git push --force", 2), ("not json", 0), ("[1, 2]", 0)],
)
def test_cli_handles_invalid_input(stdin: str, expected: int) -> None:
    """入力が想定外の場合は、危険語の有無で拒否・許可を決める（異常終了しない）。"""
    assert _run_cli(stdin).returncode == expected


# --- ラッパー（.sh） ---------------------------------------------------------------


def _find_bash() -> str | None:
    """Git Bash などの bash を探す（Windows では WSL の bash を避ける）。"""
    bash = shutil.which("bash")
    if bash and os.name == "nt" and any(p in bash.lower() for p in ("system32", "windowsapps")):
        return None
    return bash


BASH = _find_bash()
requires_bash = pytest.mark.skipif(BASH is None, reason="bash が必要")


def _write_fake_python(directory: Path, exit_code: int) -> None:
    """常に指定の終了コードで終わる python3・python を作る。"""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("python3", "python"):
        fake = directory / name
        fake.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8", newline="\n")
        fake.chmod(0o755)


def _run_wrapper(stdin: str, path_dirs: list[Path], guard_python: str | None):
    """ラッパーを、PATH と CLAUDE_GUARD_PYTHON を差し替えて実行する。"""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_GUARD_PYTHON"}
    env["PATH"] = os.pathsep.join(str(d) for d in path_dirs)
    if guard_python is not None:
        env["CLAUDE_GUARD_PYTHON"] = guard_python
    return subprocess.run(
        [BASH, str(WRAPPER_PATH)],
        input=stdin.encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=60,
    )


@requires_bash
@pytest.mark.parametrize(("command", "expected"), [("git push -f", 2), ("git status", 0)])
def test_wrapper_delegates_to_python(command: str, expected: int) -> None:
    """CLAUDE_GUARD_PYTHON の Python で判定し、その終了コードを返す。"""
    result = _run_wrapper(_hook_input(command), [], sys.executable)
    assert result.returncode == expected


@requires_bash
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git -C repo push --force", 2),
        ("cd x\ngit reset --hard", 2),
        ("gh pr merge 1", 2),
        ("git status", 0),
        ("git push origin main", 0),
    ],
)
def test_wrapper_fails_closed_without_python(tmp_path: Path, command: str, expected: int) -> None:
    """Python が無い・異常終了する場合は、危険語を含むコマンドを拒否する。"""
    _write_fake_python(tmp_path / "broken", exit_code=1)
    result = _run_wrapper(_hook_input(command), [tmp_path / "broken"], str(tmp_path / "missing"))
    assert result.returncode == expected
    if expected == 2:
        assert "安全側" in result.stderr.decode("utf-8")


@requires_bash
def test_wrapper_ignores_exit_code_2_without_guard_message(tmp_path: Path) -> None:
    """Python 自身の起動エラー（終了コード 2）を拒否とみなさず、粗い判定に回す。"""
    _write_fake_python(tmp_path / "usage_error", exit_code=2)
    result = _run_wrapper(_hook_input("git status"), [tmp_path / "usage_error"], None)
    assert result.returncode == 0


@requires_bash
def test_wrapper_skips_windows_store_alias(tmp_path: Path) -> None:
    """WindowsApps 配下の python（Microsoft Store の仮エイリアス）は使わない。"""
    # 仮エイリアスが「許可」を返しても、それを採用せず粗い判定で拒否されること
    _write_fake_python(tmp_path / "WindowsApps", exit_code=0)
    result = _run_wrapper(_hook_input("git push --force"), [tmp_path / "WindowsApps"], None)
    assert result.returncode == 2
