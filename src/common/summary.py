"""取得サマリーのJSON保存処理。

複数のデータ取得スクリプトで重複していた、サマリー辞書を
日本語を含むUTF-8のJSONとして保存する処理を集約する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
