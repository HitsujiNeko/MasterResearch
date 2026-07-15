"""ファイル冒頭の見出し直後の行群を抽出する。

メタ情報の有無チェック・鮮度チェックなど、「冒頭見出しから数行以内」の
記載を確認する複数のチェックで共通して使用する。
"""

from __future__ import annotations

import re

_HEADING_PATTERN = re.compile(r"^#\s+\S")
_DEFAULT_LOOKAHEAD_LINES = 5


def extract_heading_window(
    text: str, lookahead_lines: int = _DEFAULT_LOOKAHEAD_LINES
) -> str | None:
    """先頭の `# 見出し` 行の直後 lookahead_lines 行を1つの文字列として返す。

    見出しが存在しない場合は None を返す。

    Args:
        text: 抽出対象の Markdown テキスト。
        lookahead_lines: 見出し直後から抽出する行数。
    Returns:
        抽出された文字列。見出しがない場合は None。
    """
    lines = text.splitlines()
    heading_index = next((i for i, line in enumerate(lines) if _HEADING_PATTERN.match(line)), None)
    if heading_index is None:
        return None
    window = lines[heading_index + 1 : heading_index + 1 + lookahead_lines]
    return "\n".join(window)
