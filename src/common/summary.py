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

    Args:
        summary: 保存内容。
        summary_path: 保存先パス。
    """
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
