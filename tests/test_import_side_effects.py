"""`src/` のモジュールが import 時に副作用を起こさないことのテスト。

CodingRule.md 5.2 は、import しただけで他のモジュールやテストの動作が変わる処理
（ログの設定・警告の抑止・ファイルの作成など）をモジュールの最上位に書くことを禁じている。
別プロセスで `src/` 配下の全モジュールを import し、次を確かめる。

- `src/` のコードから `logging.basicConfig` が呼ばれず、ルートロガーにハンドラが付かない
- `src/` のコードから `warnings.filterwarnings`・`warnings.simplefilter` が呼ばれない
  （ライブラリが import 時に足すフィルタは対象外とするため、呼び出し元のファイルで判定する）
- 作業ディレクトリにファイル・ディレクトリが作られない

実行環境に無いライブラリを必要とするモジュールは import できないため数えない。CI は
`requirements.txt` だけを入れるため、QGIS と GDAL の Python バインディング（`osgeo`）が無い。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.common.config import PROJECT_ROOT

# 別プロセスで実行するスクリプト。`src/` の全モジュールを import して結果を JSON で返す。
# 引数はプロジェクトルート
_CHILD_SCRIPT = r"""
import importlib
import json
import logging
import sys
import warnings
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
src_root = project_root / "src"
calls = []


def _record(function_name, original):
    # 呼び出し元が src/ 配下のファイルなら記録してから元の関数を呼ぶ
    def wrapper(*args, **kwargs):
        caller = Path(sys._getframe(1).f_code.co_filename).resolve()
        if caller.is_relative_to(src_root):
            calls.append(
                {"function": function_name, "file": caller.relative_to(project_root).as_posix()}
            )
        return original(*args, **kwargs)

    return wrapper


logging.basicConfig = _record("logging.basicConfig", logging.basicConfig)
warnings.filterwarnings = _record("warnings.filterwarnings", warnings.filterwarnings)
warnings.simplefilter = _record("warnings.simplefilter", warnings.simplefilter)

modules = sorted(
    ".".join(path.relative_to(project_root).with_suffix("").parts)
    for path in src_root.rglob("*.py")
    if path.name not in ("__init__.py", "__main__.py")
)
imported = []
missing_dependencies = {}
for module_name in modules:
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        missing_dependencies[module_name] = (error.name or "").split(".")[0]
        continue
    imported.append(module_name)

print(
    json.dumps(
        {
            "imported": imported,
            "missing_dependencies": missing_dependencies,
            "calls": calls,
            "root_handler_count": len(logging.getLogger().handlers),
        }
    )
)
"""


def _import_all_src_modules(work_dir: Path) -> dict:
    """別プロセスで `src/` の全モジュールを import し、観測した結果を返す。

    Args:
        work_dir: 子プロセスの作業ディレクトリ（ファイルが作られないことを確かめる場所）
    Returns:
        import できたモジュール・依存が無く import できなかったモジュール・
        `src/` のコードからの設定関数の呼び出し・ルートロガーのハンドラ数
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT, str(PROJECT_ROOT)],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    # 子プロセスが import の失敗などで落ちたときに原因が分かるよう、標準エラー出力を添える
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_src_modules_has_no_side_effects(tmp_path: Path) -> None:
    """`src/` の全モジュールの import で、ログ設定・警告の抑止・ファイル作成が起きない。"""
    result = _import_all_src_modules(tmp_path)

    # 確認の対象が実際に import されていること（かつて副作用のあった主要なスクリプト）
    for module_name in (
        "src.analysis.analyze_data_status",
        "src.gee.gee_calc_LST",
        "src.preprocessing.append_remaining_dgn",
        "src.preprocessing.fetch_gba_buildings_hanoi",
        "src.preprocessing.merge_vector_fixed",
    ):
        assert module_name in result["imported"]
    # 依存が無く数えなかったモジュールは、QGIS・GDAL の Python バインディングを使うものに限られる
    assert set(result["missing_dependencies"].values()) <= {"qgis", "osgeo"}
    assert result["calls"] == []
    assert result["root_handler_count"] == 0
    assert list(tmp_path.iterdir()) == []
