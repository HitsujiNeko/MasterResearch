"""外部依存のヘルスチェック。

作業を始めてから認証切れや環境の不整合に気づく手戻りを防ぐため、次の4項目を判定する。

1. NASA Earthdata トークンの有効期限（`EARTHDATA_TOKEN`）
2. Google Earth Engine（GEE）の認証状態
3. OSGeo4W 同梱の PROJ データベース（`proj.db`）の整合性
4. ruff のローカル版と CI 固定版（`.github/workflows/ci.yml`）の一致

**問題のある項目（期限切れ・期限間近・不一致・判定不能）だけを標準出力に出す**。
全項目に問題が無ければ1行の「問題なし」だけを出す。終了コードは問題あり=1／問題なし=0。
GitHub などの外部サービスには書き込まない。

秘密情報の扱い:

- トークンの値は出力にもログにも出さない。扱うのは有効期限などのメタ情報のみ
- JWT の署名は検証しない（有効期限の目安を読むだけで、認証には使わないため）
- Earthdata トークンの有効期限の正本は LAADS DAAC プロフィールページの `Expires at`
  （docs/02_methods/data_management_guide.md 7.2節）。ここで読む JWT の `exp` は、
  その期限を定期的に気づくための目安として扱う

実行はプロジェクトルートから行う（`src` パッケージを import するため）。

```sh
python -m scripts.check_external_deps
```
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.common.env_file import DEFAULT_ENV_FILE_PATH, resolve_secret

# 判定結果の区分
STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"

# 出力時の並び順（深刻なものを先に出す）
_STATUS_ORDER = {STATUS_FAIL: 0, STATUS_WARN: 1, STATUS_UNKNOWN: 2, STATUS_OK: 3}

# 項目名（判定関数と、予期しない例外を UNKNOWN にする main とで共有する）
CHECK_NAME_EARTHDATA = "Earthdata トークン"
CHECK_NAME_GEE = "GEE 認証"
CHECK_NAME_PROJ_DB = "OSGeo4W の proj.db"
CHECK_NAME_RUFF = "ruff の版"

EARTHDATA_TOKEN_ENV_VAR = "EARTHDATA_TOKEN"
EARTHDATA_TOKEN_URL = "https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token"

# 期限間近とみなす残り日数の既定値（月1回の実行で次回までに失効しないよう余裕を見る）
DEFAULT_WARN_DAYS = 45

DEFAULT_GEE_CONFIG_PATH = PROJECT_ROOT / "data" / "input" / "gee_calc_LST_info.csv"

# OSGeo4W のインストール先の探索候補（CodingRule 7章の例外: 外部ツールの探索パス）
OSGEO4W_ROOT_CANDIDATES: tuple[Path, ...] = (Path("C:/OSGeo4W"), Path("C:/OSGeo4W64"))

CI_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
ENVIRONMENT_YML_PATH = PROJECT_ROOT / "environment.yml"
PRE_COMMIT_CONFIG_PATH = PROJECT_ROOT / ".pre-commit-config.yaml"

# 外部コマンドのタイムアウト秒数
_GEE_TIMEOUT_SECONDS = 90
_COMMAND_TIMEOUT_SECONDS = 60

# 失敗理由として表示するエラー文の最大文字数
_MAX_ERROR_SUMMARY_LENGTH = 200

# 子プロセスで GEE の初期化だけを試すコード。`ee.Authenticate()` はブラウザ認証が開いて
# 無人実行が止まるため呼ばない
_GEE_PROBE_CODE = "import sys, ee; ee.Initialize(project=sys.argv[1]); print('ok')"

# subprocess.run と同じ呼び出し形の関数（テストで差し替える）
CommandRunner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class CheckResult:
    """1項目の判定結果。

    Attributes:
        name: 項目名。
        status: 判定区分（OK／WARN／FAIL／UNKNOWN）。
        message: 判定の説明。秘密情報の値は含めない。
    """

    name: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# 共通処理
# ---------------------------------------------------------------------------
def summarize_error(text: str) -> str:
    """エラー出力から、表示用の短い要約（最後の空でない行）を取り出す。

    Args:
        text: 標準エラー等の出力。
    Returns:
        最後の空でない行を上限文字数で切り詰めた文字列。空なら「（出力なし）」。
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "（出力なし）"
    last_line = lines[-1]
    if len(last_line) > _MAX_ERROR_SUMMARY_LENGTH:
        return last_line[: _MAX_ERROR_SUMMARY_LENGTH - 3] + "..."
    return last_line


# ---------------------------------------------------------------------------
# 1. Earthdata トークン
# ---------------------------------------------------------------------------
def decode_jwt_expiry(token: str) -> dt.datetime | None:
    """JWT のペイロードから有効期限（`exp`）を読む（署名は検証しない）。

    Args:
        token: JWT 文字列。
    Returns:
        有効期限（UTC のタイムゾーンつき日時）。JWT として解釈できない、または `exp` が
        無い場合は None。
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_part = parts[1]
    # base64url はパディングを省略するため、4の倍数になるよう補う
    padded = payload_part + "=" * (-len(payload_part) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    expiry = payload.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
        return None
    try:
        return dt.datetime.fromtimestamp(expiry, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def judge_token_expiry(
    expiry: dt.datetime | None, now: dt.datetime, warn_days: int, has_token: bool
) -> CheckResult:
    """Earthdata トークンの有効期限を判定する。

    Args:
        expiry: 有効期限（UTC）。読めなかった場合は None。
        now: 判定時刻（UTC のタイムゾーンつき）。
        warn_days: 期限間近とみなす残り日数。
        has_token: トークンが設定されているか。
    Returns:
        判定結果。
    """
    name = CHECK_NAME_EARTHDATA
    if not has_token:
        return CheckResult(
            name,
            STATUS_UNKNOWN,
            f"{EARTHDATA_TOKEN_ENV_VAR} が環境変数にも .env にも設定されていません",
        )
    if expiry is None:
        return CheckResult(
            name,
            STATUS_UNKNOWN,
            "トークンから有効期限を読み取れませんでした（JWT 形式でない、または exp が無い）",
        )

    expiry_text = expiry.strftime("%Y-%m-%d %H:%M UTC")
    remaining = expiry - now
    remaining_days = remaining.days
    if remaining.total_seconds() <= 0:
        return CheckResult(
            name,
            STATUS_FAIL,
            f"有効期限切れです（{expiry_text}）。{EARTHDATA_TOKEN_URL} で再発行してください",
        )
    if remaining_days < warn_days:
        return CheckResult(
            name,
            STATUS_WARN,
            f"有効期限が近づいています（{expiry_text}・残り {remaining_days} 日）。"
            f"{EARTHDATA_TOKEN_URL} で再発行してください",
        )
    return CheckResult(name, STATUS_OK, f"有効期限 {expiry_text}（残り {remaining_days} 日）")


def check_earthdata_token(
    environment: Mapping[str, str],
    env_file_path: Path,
    now: dt.datetime,
    warn_days: int,
) -> CheckResult:
    """Earthdata トークンを解決し、有効期限を判定する。

    Args:
        environment: 環境変数の辞書。
        env_file_path: `.env` のパス。
        now: 判定時刻（UTC）。
        warn_days: 期限間近とみなす残り日数。
    Returns:
        判定結果。トークンの値は含めない。
    """
    token = resolve_secret(EARTHDATA_TOKEN_ENV_VAR, dict(environment), env_file_path)
    expiry = decode_jwt_expiry(token) if token else None
    return judge_token_expiry(expiry, now, warn_days, has_token=bool(token))


# ---------------------------------------------------------------------------
# 2. GEE の認証状態
# ---------------------------------------------------------------------------
def resolve_gee_project_id(explicit_project_id: str, config_path: Path) -> str:
    """GEE プロジェクト ID を、明示指定 → 設定 CSV の順で解決する。

    Args:
        explicit_project_id: 明示指定のプロジェクト ID（空なら設定 CSV を読む）。
        config_path: GEE 設定 CSV のパス。
    Returns:
        プロジェクト ID。
    Raises:
        FileNotFoundError: 設定 CSV が無い場合。
        ValueError: プロジェクト ID が未設定の場合。
    """
    # earthengine-api の import は重いため、GEE の判定を行うときだけ読み込む
    from src.common.gee import load_gee_project_id

    return load_gee_project_id(config_path, explicit_project_id)


def judge_gee_probe(returncode: int | None, stderr: str, timed_out: bool) -> CheckResult:
    """GEE 初期化を試した子プロセスの結果を判定する。

    Args:
        returncode: 子プロセスの終了コード（タイムアウト時は None）。
        stderr: 子プロセスの標準エラー。
        timed_out: タイムアウトしたか。
    Returns:
        判定結果。
    """
    name = CHECK_NAME_GEE
    if timed_out:
        return CheckResult(
            name,
            STATUS_UNKNOWN,
            f"初期化が {_GEE_TIMEOUT_SECONDS} 秒以内に終わりませんでした（ネットワークを確認）",
        )
    if returncode == 0:
        return CheckResult(name, STATUS_OK, "ee.Initialize に成功しました")
    return CheckResult(
        name,
        STATUS_FAIL,
        f"ee.Initialize に失敗しました: {summarize_error(stderr)}。"
        "対話できる端末で earthengine authenticate を実行してください",
    )


def check_gee(
    explicit_project_id: str,
    config_path: Path,
    python_executable: str,
    runner: CommandRunner = subprocess.run,
) -> CheckResult:
    """GEE の認証状態を、子プロセスでの `ee.Initialize` により判定する。

    Args:
        explicit_project_id: 明示指定のプロジェクト ID。
        config_path: GEE 設定 CSV のパス。
        python_executable: earthengine-api が入った Python の実行ファイル。
        runner: 外部コマンドの実行関数。
    Returns:
        判定結果。
    """
    try:
        project_id = resolve_gee_project_id(explicit_project_id, config_path)
    except ImportError as exc:
        return CheckResult(
            CHECK_NAME_GEE, STATUS_UNKNOWN, f"earthengine-api を読み込めません: {exc}"
        )
    except (FileNotFoundError, ValueError) as exc:
        return CheckResult(CHECK_NAME_GEE, STATUS_UNKNOWN, str(exc))

    try:
        completed = runner(
            [python_executable, "-c", _GEE_PROBE_CODE, project_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GEE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return judge_gee_probe(None, "", timed_out=True)
    except OSError as exc:
        return CheckResult(CHECK_NAME_GEE, STATUS_UNKNOWN, f"Python を起動できませんでした: {exc}")
    return judge_gee_probe(completed.returncode, completed.stderr or "", timed_out=False)


# ---------------------------------------------------------------------------
# 3. OSGeo4W の proj.db
# ---------------------------------------------------------------------------
def find_osgeo4w_root(
    explicit_root: str,
    environment: Mapping[str, str],
    candidates: tuple[Path, ...] = OSGEO4W_ROOT_CANDIDATES,
) -> Path | None:
    """OSGeo4W のインストール先を、明示指定 → 環境変数 → 探索候補の順で決める。

    明示指定がある場合はそれだけを見る（無効でも環境変数・探索候補へは進まない）。
    指定と異なるインストール先を黙って判定すると、指定したものの結果と誤読されるため。

    Args:
        explicit_root: 明示指定のパス（空なら無視する）。
        environment: 環境変数の辞書（`OSGEO4W_ROOT` を見る）。
        candidates: 探索候補のパス。
    Returns:
        `bin/gdalsrsinfo.exe` を持つインストール先。見つからなければ None。
    """
    ordered: list[Path] = []
    if explicit_root.strip():
        explicit = Path(explicit_root.strip())
        return explicit if _has_gdalsrsinfo(explicit) else None
    if environment.get("OSGEO4W_ROOT", "").strip():
        ordered.append(Path(environment["OSGEO4W_ROOT"].strip()))
    ordered.extend(candidates)
    for root in ordered:
        if _has_gdalsrsinfo(root):
            return root
    return None


def _has_gdalsrsinfo(root: Path) -> bool:
    """インストール先に `bin/gdalsrsinfo.exe` があるかを返す。"""
    return (root / "bin" / "gdalsrsinfo.exe").exists()


def build_isolated_environment(
    osgeo4w_root: Path, environment: Mapping[str, str]
) -> dict[str, str]:
    """OSGeo4W のツールを、他の PROJ/GDAL 設定に影響されずに動かす環境変数を作る。

    conda 環境の `PROJ_LIB` 等が設定されていると、OSGeo4W 自身の proj.db ではなく
    conda 側を参照してしまい、不整合を見逃すため取り除く。

    Args:
        osgeo4w_root: OSGeo4W のインストール先。
        environment: 元の環境変数の辞書。
    Returns:
        子プロセスに渡す環境変数の辞書。
    """
    removed_keys = {"PROJ_LIB", "PROJ_DATA", "GDAL_DATA", "PATH"}
    isolated = {key: value for key, value in environment.items() if key.upper() not in removed_keys}
    system_root = environment.get("SystemRoot") or environment.get("SYSTEMROOT") or "C:/Windows"
    isolated["PATH"] = os.pathsep.join(
        [str(osgeo4w_root / "bin"), str(Path(system_root) / "System32"), system_root]
    )
    return isolated


def read_proj_db_metadata(proj_db_path: Path) -> dict[str, str]:
    """proj.db の `metadata` 表を読み取り専用で読む。

    Args:
        proj_db_path: proj.db のパス。
    Returns:
        キー -> 値 の辞書。読めなければ空の辞書。
    """
    if not proj_db_path.exists():
        return {}
    uri = f"{proj_db_path.resolve().as_uri()}?mode=ro"
    try:
        # `with sqlite3.connect()` はトランザクションを管理するだけで接続を閉じないため、
        # closing で確実に閉じる
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


def judge_proj_db(returncode: int | None, stderr: str, metadata: Mapping[str, str]) -> CheckResult:
    """OSGeo4W の `gdalsrsinfo EPSG:4326` の結果から proj.db の整合性を判定する。

    Args:
        returncode: 終了コード（タイムアウト・起動失敗時は None）。
        stderr: 標準エラー。
        metadata: proj.db の metadata 表（補足表示に使う）。
    Returns:
        判定結果。
    """
    name = CHECK_NAME_PROJ_DB
    detail_parts = []
    if metadata.get("PROJ.VERSION"):
        detail_parts.append(f"PROJ.VERSION={metadata['PROJ.VERSION']}")
    if metadata.get("DATABASE.LAYOUT.VERSION.MINOR"):
        detail_parts.append(
            f"DATABASE.LAYOUT.VERSION.MINOR={metadata['DATABASE.LAYOUT.VERSION.MINOR']}"
        )
    detail = f"（proj.db: {', '.join(detail_parts)}）" if detail_parts else ""

    if returncode is None:
        return CheckResult(name, STATUS_UNKNOWN, f"gdalsrsinfo を実行できませんでした{detail}")
    if "DATABASE.LAYOUT.VERSION" in stderr:
        return CheckResult(
            name,
            STATUS_FAIL,
            "proj.db の版が同梱の PROJ と食い違っています（CRS を指定する ogr2ogr 等が失敗する）"
            f"{detail}。OSGeo4W Setup で proj を更新するか、conda 環境の GDAL を使ってください",
        )
    if returncode != 0:
        return CheckResult(
            name,
            STATUS_FAIL,
            f"gdalsrsinfo EPSG:4326 が失敗しました: {summarize_error(stderr)}{detail}",
        )
    return CheckResult(name, STATUS_OK, f"EPSG:4326 を解決できました{detail}")


def check_proj_db(
    explicit_root: str,
    environment: Mapping[str, str],
    runner: CommandRunner = subprocess.run,
    candidates: tuple[Path, ...] = OSGEO4W_ROOT_CANDIDATES,
) -> CheckResult:
    """OSGeo4W の proj.db の整合性を、同梱ツールで EPSG:4326 を解決できるかで判定する。

    Args:
        explicit_root: OSGeo4W のインストール先の明示指定。
        environment: 環境変数の辞書。
        runner: 外部コマンドの実行関数。
        candidates: インストール先の探索候補。
    Returns:
        判定結果。
    """
    root = find_osgeo4w_root(explicit_root, environment, candidates)
    if root is None and explicit_root.strip():
        return CheckResult(
            CHECK_NAME_PROJ_DB,
            STATUS_UNKNOWN,
            "--osgeo4w-root で指定したインストール先に bin/gdalsrsinfo.exe がありません"
            f"（{explicit_root.strip()}）",
        )
    if root is None:
        return CheckResult(
            CHECK_NAME_PROJ_DB,
            STATUS_UNKNOWN,
            "OSGeo4W が見つかりません（--osgeo4w-root か環境変数 OSGEO4W_ROOT で指定できます）",
        )
    metadata = read_proj_db_metadata(root / "share" / "proj" / "proj.db")
    try:
        completed = runner(
            [str(root / "bin" / "gdalsrsinfo.exe"), "EPSG:4326", "-o", "proj4"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
            env=build_isolated_environment(root, environment),
        )
    except (OSError, subprocess.TimeoutExpired):
        return judge_proj_db(None, "", metadata)
    return judge_proj_db(completed.returncode, completed.stderr or "", metadata)


# ---------------------------------------------------------------------------
# 4. ruff の版
# ---------------------------------------------------------------------------
def parse_pinned_version(text: str, pattern: str) -> str | None:
    """設定ファイルの本文から、固定されている版を正規表現で取り出す。

    Args:
        text: 設定ファイルの本文。
        pattern: 版をグループ1に捕まえる正規表現。
    Returns:
        版の文字列。見つからなければ None。
    """
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else None


# 各設定ファイルで ruff の版を固定している書式
CI_RUFF_PATTERN = r"ruff==([0-9][0-9A-Za-z.]*)"
ENVIRONMENT_RUFF_PATTERN = r"^\s*-\s*ruff\s*=+\s*([0-9][0-9A-Za-z.]*)"
PRE_COMMIT_RUFF_PATTERN = r"ruff-pre-commit\s*\n\s*rev:\s*[\"']?v?([0-9][0-9A-Za-z.]*)"
LOCAL_RUFF_PATTERN = r"ruff\s+([0-9][0-9A-Za-z.]*)"


def judge_ruff_versions(
    ci_version: str | None,
    local_version: str | None,
    other_pins: Mapping[str, str | None],
) -> CheckResult:
    """CI 固定版を基準に、ローカル版と他の固定箇所の版の一致を判定する。

    Args:
        ci_version: CI（ci.yml）で固定している版。
        local_version: ローカルの ruff の版（取得できなければ None）。
        other_pins: その他の固定箇所の名前 -> 版（見つからなければ None）。
    Returns:
        判定結果。
    """
    name = CHECK_NAME_RUFF
    if ci_version is None:
        return CheckResult(name, STATUS_UNKNOWN, "ci.yml から ruff の固定版を読み取れませんでした")
    if local_version is None:
        return CheckResult(
            name,
            STATUS_UNKNOWN,
            f"ローカルの ruff の版を取得できませんでした（CI は {ci_version}）",
        )

    mismatches = []
    if local_version != ci_version:
        mismatches.append(f"ローカル {local_version}")
    for pin_name, version in other_pins.items():
        if version is not None and version != ci_version:
            mismatches.append(f"{pin_name} {version}")
    if mismatches:
        return CheckResult(
            name,
            STATUS_WARN,
            f"CI 固定版 {ci_version} と食い違っています: {'、'.join(mismatches)}",
        )
    return CheckResult(name, STATUS_OK, f"ローカル・CI とも {ci_version}")


def read_text_if_exists(path: Path) -> str:
    """ファイルがあれば本文を返し、無ければ空文字列を返す。

    Args:
        path: 読み込むファイルのパス。
    Returns:
        ファイルの本文。ファイルが無ければ空文字列。
    """
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_local_ruff_version(
    python_executable: str, runner: CommandRunner = subprocess.run
) -> str | None:
    """`{python} -m ruff --version` でローカルの ruff の版を取得する。

    Args:
        python_executable: ruff が入った Python の実行ファイル。
        runner: 外部コマンドの実行関数。
    Returns:
        版の文字列。取得できなければ None。
    """
    try:
        completed = runner(
            [python_executable, "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return parse_pinned_version(completed.stdout or "", LOCAL_RUFF_PATTERN)


def check_ruff(
    python_executable: str,
    runner: CommandRunner = subprocess.run,
    ci_workflow_path: Path = CI_WORKFLOW_PATH,
    environment_yml_path: Path = ENVIRONMENT_YML_PATH,
    pre_commit_config_path: Path = PRE_COMMIT_CONFIG_PATH,
) -> CheckResult:
    """ruff のローカル版と各固定箇所の版を集めて判定する。

    Args:
        python_executable: ruff が入った Python の実行ファイル。
        runner: 外部コマンドの実行関数。
        ci_workflow_path: CI ワークフローのパス。
        environment_yml_path: conda 環境定義のパス。
        pre_commit_config_path: pre-commit 設定のパス。
    Returns:
        判定結果。
    """
    ci_version = parse_pinned_version(read_text_if_exists(ci_workflow_path), CI_RUFF_PATTERN)
    other_pins = {
        "environment.yml": parse_pinned_version(
            read_text_if_exists(environment_yml_path), ENVIRONMENT_RUFF_PATTERN
        ),
        ".pre-commit-config.yaml": parse_pinned_version(
            read_text_if_exists(pre_commit_config_path), PRE_COMMIT_RUFF_PATTERN
        ),
    }
    local_version = get_local_ruff_version(python_executable, runner)
    return judge_ruff_versions(ci_version, local_version, other_pins)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def run_check(name: str, check: Callable[..., CheckResult], *args: object) -> CheckResult:
    """1項目の判定を実行し、予期しない例外は UNKNOWN の結果に置き換える。

    1項目の例外（文字コードの異なる .env による UnicodeDecodeError、PermissionError 等）で
    他の項目の報告まで失われないようにするため。例外のメッセージ本文はファイルの内容など
    秘密情報を含みうるため出さず、型名だけを示す。

    Args:
        name: 項目名（例外時の結果に使う）。
        check: 判定関数。
        *args: 判定関数に渡す引数。
    Returns:
        判定結果。
    """
    try:
        return check(*args)
    except Exception as exc:  # 項目単位で捕捉し、残りの項目を判定し続ける
        return CheckResult(
            name,
            STATUS_UNKNOWN,
            f"判定中に予期しない例外が発生しました（{type(exc).__name__}）",
        )


def format_report(results: list[CheckResult], checked_at: dt.datetime) -> str:
    """問題のある項目だけを並べた報告文を作る。

    Args:
        results: 全項目の判定結果。
        checked_at: 判定時刻（表示用。現地時刻を渡す）。
    Returns:
        報告文。問題が無ければ1行の「問題なし」。
    """
    timestamp = checked_at.strftime("%Y-%m-%d %H:%M")
    problems = sorted(
        (result for result in results if result.status != STATUS_OK),
        key=lambda result: _STATUS_ORDER[result.status],
    )
    if not problems:
        return f"外部依存のヘルスチェック（{timestamp}）: 問題なし（{len(results)} 項目）"

    lines = [
        f"外部依存のヘルスチェック（{timestamp}）: 要対応 {len(problems)} 件 / {len(results)} 項目",
        "",
    ]
    lines.extend(f"- [{result.status}] {result.name}: {result.message}" for result in problems)
    return "\n".join(lines)


def non_negative_int(value: str) -> int:
    """0 以上の整数として引数を解釈する（argparse の type 用）。

    Args:
        value: 引数の文字列。
    Returns:
        解釈した整数。
    Raises:
        argparse.ArgumentTypeError: 整数でない、または負の場合。
    """
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"整数を指定してください: {value}") from exc
    if number < 0:
        raise argparse.ArgumentTypeError(f"0 以上の整数を指定してください: {value}")
    return number


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(description="外部依存（認証・環境）のヘルスチェック")
    parser.add_argument(
        "--warn-days",
        type=non_negative_int,
        default=DEFAULT_WARN_DAYS,
        help=f"Earthdata トークンを期限間近とみなす残り日数（既定 {DEFAULT_WARN_DAYS}）",
    )
    parser.add_argument("--gee-project-id", default="", help="GEE プロジェクト ID の明示指定")
    parser.add_argument(
        "--gee-config",
        default=str(DEFAULT_GEE_CONFIG_PATH),
        help="GEE プロジェクト ID を読む設定 CSV",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE_PATH),
        help="Earthdata トークンを読む .env（環境変数が優先される）",
    )
    parser.add_argument(
        "--osgeo4w-root",
        default="",
        help="OSGeo4W のインストール先（指定時は環境変数・既定の探索先を見ない）",
    )
    parser.add_argument("--skip-gee", action="store_true", help="GEE の判定を省略する")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。問題があれば 1、無ければ 0 を返す。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = _parse_args(argv)
    environment = dict(os.environ)
    now = dt.datetime.now(dt.timezone.utc)

    results = [
        run_check(
            CHECK_NAME_EARTHDATA,
            check_earthdata_token,
            environment,
            Path(args.env_file),
            now,
            args.warn_days,
        )
    ]
    if not args.skip_gee:
        results.append(
            run_check(
                CHECK_NAME_GEE,
                check_gee,
                args.gee_project_id,
                Path(args.gee_config),
                sys.executable,
            )
        )
    results.append(run_check(CHECK_NAME_PROJ_DB, check_proj_db, args.osgeo4w_root, environment))
    results.append(run_check(CHECK_NAME_RUFF, check_ruff, sys.executable))

    print(format_report(results, now.astimezone()))
    return 1 if any(result.status != STATUS_OK for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
