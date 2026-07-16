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
    python -m src.analysis.build_data_inventory
"""

from __future__ import annotations

import json
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
        POSIX 区切り（``/``）の相対パス文字列。
    """
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


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
        kind = _classify(path)
        if kind is None:
            continue

        entry = _common_file_info(path)
        entry["kind"] = kind
        try:
            if kind == "raster":
                entry.update(read_raster_metadata(path))
            else:
                entry.update(read_vector_metadata(path))
        except Exception as exc:  # noqa: BLE001 - 1ファイルの失敗で全体を止めない
            entry["error"] = f"{type(exc).__name__}: {exc}"

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


def main() -> None:
    """インベントリを生成し data/output/data_inventory.json に書き出す。"""
    inventory = build_inventory()

    out_path = PROJECT_ROOT / "data" / "output" / "data_inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    print("出力:", out_path)
    print("ファイル数:", inventory["file_count"])
    print("読み込み失敗:", inventory["error_count"])


if __name__ == "__main__":
    main()
