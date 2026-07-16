"""data/ 配下GISデータのインベントリを自動生成するスクリプト。

目的:
    - `data/` は Git 管理外のため、リポジトリだけでは手元にどのデータがあるか分からない。
      `data/gis/` と `data/satellite/` を走査し、各ファイルのメタデータ（CRS・空間範囲・
      解像度・レイヤ構成・地物数・サイズ・更新日時）を JSON に出力する。
    - 手保守の台帳ではなく、スクリプトで再生成する成果物として設計する（陳腐化しない）。

方針:
    - 読み込みは**メタデータのみ**とし、全画素・全地物は読み込まない。
    - 1ファイルの読み込み失敗で全体を止めず、`error` として記録して継続する。
    - メタデータ読み取りは `src.common.geo_metadata` に集約した共通処理を用いる。

出力:
    - data/output/data_inventory.json（Git 追跡対象・軽量）

実行:
    # 全走査してインベントリJSONを生成する（従来どおり）
    python -m src.analysis.build_data_inventory
    # 単一ファイルのメタデータのみを標準出力する（内容確認用）
    python -m src.analysis.build_data_inventory --path data/gis/survey/merge_DH.gpkg
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT
from src.common.geo_metadata import read_raster_metadata, read_vector_metadata

# 走査対象ディレクトリ（PROJECT_ROOT からの相対）
TARGET_DIRS = ("data/gis", "data/satellite")

# ラスタ・ベクタとして扱う拡張子（いずれも小文字で比較）
RASTER_SUFFIXES = {".tif", ".tiff"}
VECTOR_SUFFIXES = {".gpkg", ".shp", ".geojson", ".gml"}

# 走査対象外とする拡張子（サイドカー等）
SKIP_SUFFIXES = {".aux.xml"}


def _relative_path(path: Path) -> str:
    """PROJECT_ROOT 基準の相対パスを POSIX 区切りで返す。

    Args:
        path: 対象ファイルの絶対パス。
    Returns:
        POSIX 区切り（``/``）の相対パス文字列。PROJECT_ROOT 配下でない場合は
        絶対パスを POSIX 区切りで返す。
    """
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        # PROJECT_ROOT 外のファイルを単一指定した場合は絶対パスで返す
        return path.as_posix()
    return str(rel).replace("\\", "/")


def _common_file_info(path: Path) -> dict[str, Any]:
    """全ファイル共通のメタデータ（相対パス・サイズ・更新日時）を返す。

    Args:
        path: 対象ファイルのパス。
    Returns:
        path・size_bytes・modified_at を持つ辞書。
    """
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "path": _relative_path(path),
        "size_bytes": stat.st_size,
        "modified_at": modified,
    }


def _classify(path: Path) -> str | None:
    """ファイルの種別を判定する。

    Args:
        path: 対象ファイルのパス。
    Returns:
        ラスタなら "raster"、ベクタなら "vector"、対象外なら None。
    """
    name_lower = path.name.lower()
    if any(name_lower.endswith(suffix) for suffix in SKIP_SUFFIXES):
        return None
    suffix = path.suffix.lower()
    if suffix in RASTER_SUFFIXES:
        return "raster"
    if suffix in VECTOR_SUFFIXES:
        return "vector"
    return None


def inspect_file(path: Path) -> dict[str, Any] | None:
    """単一ファイルのメタデータを抽出する。

    全走査（``build_inventory_for_dir``）と単一ファイル確認（``--path``）の
    双方から呼ぶ共通の抽出処理。メタデータ読み取りの実体は
    ``src.common.geo_metadata`` に一本化し、本関数はその呼び分けのみを担う。

    Args:
        path: 対象ファイルのパス。
    Returns:
        メタデータ辞書（相対パス・サイズ・更新日時・``kind`` と空間メタデータ）。
        ラスタ・ベクタいずれの対象拡張子でもない場合は ``None``。
        読み取りに失敗した場合は ``error`` キーを含む辞書を返す（例外は送出しない）。
    """
    kind = _classify(path)
    if kind is None:
        return None

    entry = _common_file_info(path)
    entry["kind"] = kind
    try:
        if kind == "raster":
            entry.update(read_raster_metadata(path))
        else:
            entry.update(read_vector_metadata(path))
    except Exception as exc:  # noqa: BLE001 - 1ファイルの失敗で全体を止めない
        entry["error"] = f"メタデータ読み取り失敗 ({type(exc).__name__}): {exc}"

    return entry


def build_inventory_for_dir(base_dir: Path) -> list[dict[str, Any]]:
    """1つのディレクトリ配下を再帰走査し、対象ファイルのメタデータ一覧を返す。

    Args:
        base_dir: 走査対象ディレクトリ（存在しない場合は空リストを返す）。
    Returns:
        ファイルごとのメタデータ辞書のリスト（相対パス昇順）。
    """
    if not base_dir.exists():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        entry = inspect_file(path)
        if entry is None:
            continue
        entries.append(entry)

    return entries


def build_inventory() -> dict[str, Any]:
    """走査対象ディレクトリ全体のインベントリ辞書を構築する。"""
    inventory: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "project_root": str(PROJECT_ROOT),
        "target_dirs": list(TARGET_DIRS),
        "files": [],
    }

    for rel_dir in TARGET_DIRS:
        base_dir = PROJECT_ROOT / rel_dir
        inventory["files"].extend(build_inventory_for_dir(base_dir))

    inventory["file_count"] = len(inventory["files"])
    inventory["error_count"] = sum(1 for f in inventory["files"] if "error" in f)
    return inventory


def _print_single_file(path: Path) -> int:
    """単一ファイルのメタデータを JSON で標準出力する（内容確認用）。

    インベントリJSONは生成せず、指定ファイル1件のメタデータのみを出力する。

    Args:
        path: 対象ファイルのパス（相対指定はカレントディレクトリ基準で解決する）。
    Returns:
        終了コード（0: 成功、1: 対象外の拡張子、2: ファイルが存在しない）。
    """
    resolved = path.resolve()
    if not resolved.exists():
        print(f"ファイルが存在しません: {path}", file=sys.stderr)
        return 2

    entry = inspect_file(resolved)
    if entry is None:
        print(
            f"対象外の拡張子です（ラスタ/ベクタではありません）: {path}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """インベントリ生成、または単一ファイルのメタデータ出力を行う。

    Args:
        argv: コマンドライン引数（省略時は ``sys.argv`` を使用）。
    Returns:
        終了コード（0: 成功、1以上: 失敗）。
    """
    parser = argparse.ArgumentParser(
        description=(
            "data/ 配下GISデータのインベントリ生成、または単一ファイルのメタデータ出力を行う。"
        )
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help=(
            "指定した単一ファイルのメタデータのみを JSON で標準出力する"
            "（data_inventory.json は生成しない）。省略時は全走査してインベントリを生成する。"
        ),
    )
    args = parser.parse_args(argv)

    if args.path is not None:
        return _print_single_file(args.path)

    # 従来どおり全走査してインベントリJSONを出力する
    inventory = build_inventory()

    out_path = PROJECT_ROOT / "data" / "output" / "data_inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    print("出力:", out_path)
    print("ファイル数:", inventory["file_count"])
    print("読み込み失敗:", inventory["error_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
