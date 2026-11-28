"""モジュールを import しただけで実行環境の環境変数が変わらないことのテスト。

分析・前処理のモジュールが import 時に `PATH` などを書き換えると、そのモジュールを
import する別のスクリプトやテストにも書き換えが波及し、普段の実行環境とは別の環境の
DLL が読まれる原因になる。環境の設定は `docs/setup.md` の手順に任せ、コードでは
書き換えないことを確かめる。

pytest のプロセスでは対象モジュールが既に import 済みの場合があり、import 時の
副作用を観測できないため、新しいインタプリタ（サブプロセス）で import して前後の
`os.environ` を比べる。

比べるのは、DLL・GDAL/PROJ のデータの探索先を決める環境変数（`WATCHED_KEYS`）に
限る。sklearn・joblib・pyogrio などのライブラリは import 時に自身の設定用の
環境変数（`KMP_DUPLICATE_LIB_OK`・`GDAL_CURL_CA_BUNDLE` 等）を設定するため、
全体を比べるとこのリポジトリのコードと無関係な理由で失敗する。

限界: 書き換えが「特定のディレクトリが実在するときだけ」行われる形だと、その
ディレクトリが無い作業ツリー（worktree 等）では書き換えが起きず、このテストでは
検出できない。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# import 前後で値が変わってはならない環境変数。
WATCHED_KEYS = ("PATH", "GDAL_DATA", "PROJ_LIB", "PROJ_DATA")

# 子プロセスで実行するコード。import の前後で全環境変数を比べ、差分を JSON で出力する。
CHILD_CODE = """
import importlib
import json
import os
import sys

before = dict(os.environ)
importlib.import_module(sys.argv[1])
after = dict(os.environ)
diff = {
    key: {"before": before.get(key), "after": after.get(key)}
    for key in sorted(set(before) | set(after))
    if before.get(key) != after.get(key)
}
print(json.dumps(diff, ensure_ascii=True))
"""


def _import_in_subprocess(module_name: str, removed_keys: tuple[str, ...]) -> dict:
    """新しいインタプリタでモジュールを import し、環境変数の差分を返す。

    Args:
        module_name: import するモジュール名。
        removed_keys: 子プロセスの環境から外しておく環境変数名
            （「未設定のときだけ設定する」形の書き換えを観測するため）。

    Returns:
        環境変数名をキー、import 前後の値を値とする差分の辞書（差が無ければ空）。
    """
    env = {key: value for key, value in os.environ.items() if key not in removed_keys}
    # 作業ツリー自身の src を import させる（PYTHONPATH が別のチェックアウトを
    # 指していても、子プロセスではこのリポジトリを優先する）。
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", CHILD_CODE, module_name],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # 差分の JSON は最後の行に出る（import 中の警告等が標準出力に出ても拾えるように）。
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    ("module_name", "removed_keys"),
    [
        ("src.analysis.analysis_rq3_limited", ()),
        ("src.analysis.analysis_rq3_satellite_only", ()),
    ],
)
def test_import_does_not_change_environ(module_name: str, removed_keys: tuple[str, ...]) -> None:
    """import の前後で `WATCHED_KEYS` の環境変数が変わらない。"""
    diff = _import_in_subprocess(module_name, removed_keys)

    watched_diff = {key: value for key, value in diff.items() if key in WATCHED_KEYS}
    assert watched_diff == {}
