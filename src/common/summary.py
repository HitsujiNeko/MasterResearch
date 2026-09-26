"""取得サマリーのJSON保存処理と来歴メタデータの生成。

複数のデータ取得スクリプトで重複していた、サマリー辞書を
日本語を含むUTF-8のJSONとして保存する処理を集約する。

あわせて、結果JSONへ付与する来歴メタデータ（どのコード・どの環境・どの入力から
生成されたか）を組み立てる関数を提供する。来歴は `provenance` キーとして
既存のサマリー辞書へ追加する想定で、既存キーのスキーマは変更しない。
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT
from src.common.paths import to_project_relative_string

logger = logging.getLogger(__name__)

# 来歴に版を記録する主要ライブラリ（importlib.metadata の配布パッケージ名）
DEFAULT_PROVENANCE_PACKAGES: tuple[str, ...] = (
    "numpy",
    "pandas",
    "scikit-learn",
    "shap",
    "geopandas",
    "rasterio",
    "shapely",
    "pyproj",
    "pyogrio",
)

# ハッシュ計算時の読み込み単位（大容量のGeoPackage・GeoTIFFでもメモリを圧迫しないため）
_HASH_CHUNK_SIZE = 1024 * 1024

# git コマンドの待ち時間の上限（秒）
_GIT_TIMEOUT_SEC = 10

# 未コミット変更の判定対象（コードのみ）。追跡中の結果JSONの更新や作業用の
# 未追跡ディレクトリでは dirty にしないため、ソースコードのディレクトリに限定する
_GIT_DIRTY_PATHSPEC = "src"


def save_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """サマリー辞書をJSONファイルとして保存する。

    `NaN` / `Infinity` は JSON の標準（RFC 8259）に無く、他言語のパーサで読めない
    ことがある。統計値の計算が破綻したまま気づかず保存されるのを防ぐため、
    書き出し時に検出して例外にする。

    Args:
        summary: 保存内容。
        summary_path: 保存先パス。

    Raises:
        ValueError: `NaN` / `Infinity` が含まれる場合。
    """
    try:
        serialized = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    except ValueError as exc:
        raise ValueError(
            f"サマリーに NaN / Infinity が含まれるため保存できません（{summary_path.name}）。"
            "統計値の計算条件（要素数・定数系列・ゼロ除算）を確認してください。"
        ) from exc

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(serialized, encoding="utf-8")


def compute_file_sha256(path: Path) -> str:
    """ファイルのSHA-256ハッシュ（16進文字列）を計算する。

    大容量ファイルでもメモリを圧迫しないよう、一定サイズずつ読み込んで計算する。

    Args:
        path: 対象ファイルのパス。

    Returns:
        SHA-256ハッシュの16進文字列。

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
    """
    if not path.is_file():
        raise FileNotFoundError(f"ハッシュ計算対象のファイルが見つかりません: {path}")

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(args: list[str], repo_root: Path) -> str | None:
    """git コマンドを実行して標準出力を返す。失敗時は `None` を返す。

    Args:
        args: `git` に続く引数。
        repo_root: コマンドを実行するディレクトリ。

    Returns:
        前後の空白を除いた標準出力。git が無い・リポジトリ外などで失敗した場合は `None`。
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def get_git_state(repo_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """現在のgitコミットハッシュとコードの未コミット変更の有無を取得する。

    `dirty` が真の場合、記録したコミットだけでは生成時のコードを復元できない。
    判定対象は `src/` 配下（未追跡ファイルを含む）に限り、結果ファイル等の
    コード以外の変更では真にしない。
    git を利用できない環境では例外にせず、値を `None` として記録する
    （来歴の取得失敗で分析結果の保存が止まるのを避けるため）。

    Args:
        repo_root: gitリポジトリのルート。

    Returns:
        `commit`（コミットハッシュ）と `dirty`（未コミット変更の有無）を持つ辞書。
    """
    commit = _run_git(["rev-parse", "HEAD"], repo_root)
    status = _run_git(["status", "--porcelain", "--", _GIT_DIRTY_PATHSPEC], repo_root)
    if commit is None or status is None:
        logger.warning("git の状態を取得できなかったため、来歴のコミット情報を空にします。")
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": status != ""}


def get_package_versions(packages: Iterable[str] = DEFAULT_PROVENANCE_PACKAGES) -> dict[str, Any]:
    """指定したライブラリのインストール済みバージョンを取得する。

    Args:
        packages: 配布パッケージ名の並び（例: `scikit-learn`）。

    Returns:
        パッケージ名をキー、バージョン文字列を値とする辞書。
        未インストールのパッケージは `None` とする。
    """
    versions: dict[str, Any] = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def describe_input_files(
    input_paths: Iterable[Path], project_root: Path = PROJECT_ROOT
) -> list[dict[str, str]]:
    """入力ファイルのパスとSHA-256ハッシュの一覧を作る。

    パスは結果JSONへ絶対パスを残さないよう、可能ならプロジェクト相対で記録する。

    Args:
        input_paths: 入力ファイルのパスの並び。
        project_root: 相対化の基準ディレクトリ。

    Returns:
        `path` と `sha256` を持つ辞書のリスト（入力順を保持する）。

    Raises:
        FileNotFoundError: 入力ファイルが存在しない場合。
    """
    return [
        {
            "path": to_project_relative_string(path, project_root),
            "sha256": compute_file_sha256(path),
        }
        for path in input_paths
    ]


def build_provenance(
    script: str,
    input_paths: Iterable[Path] = (),
    packages: Iterable[str] = DEFAULT_PROVENANCE_PACKAGES,
    repo_root: Path = PROJECT_ROOT,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    """結果JSONへ付与する来歴メタデータを組み立てる。

    記録するのはコード・環境・入力の来歴のみとし、分析の実行パラメータ
    （乱数シード・木の本数など）は各スクリプトのサマリー側で記録する。

    Args:
        script: 実行スクリプトの識別名（例: `src.analysis.diagnose_nodata_dropout`）。
        input_paths: ハッシュを記録する入力ファイルのパス。
        packages: バージョンを記録するライブラリの配布パッケージ名。
        repo_root: gitリポジトリのルート（入力パスの相対化の基準も兼ねる）。
        executed_at: 実行日時（タイムゾーン付き）。`None` の場合は現在時刻（UTC）を使う。

    Returns:
        `script`・`executed_at`・`python_version`・`platform`・`git`・`packages`・`inputs`
        を持つ辞書。

    Raises:
        ValueError: `executed_at` がタイムゾーンを持たない場合。
    """
    if executed_at is None:
        timestamp = datetime.now(timezone.utc)
    elif executed_at.tzinfo is None:
        # タイムゾーン無しの日時はUTCか現地時刻か判別できないため受け付けない
        raise ValueError("executed_at にはタイムゾーン付きの日時を指定してください。")
    else:
        timestamp = executed_at.astimezone(timezone.utc)
    return {
        "script": script,
        "executed_at": timestamp.isoformat(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "git": get_git_state(repo_root),
        "packages": get_package_versions(packages),
        "inputs": describe_input_files(input_paths, repo_root),
    }
