"""コマンドとして実行するスクリプトのログ設定。

ログの設定はエントリポイント（コマンドとして実行するスクリプト）の `main()` の中で
1 回だけ行う（CodingRule.md 5.3）。多くのスクリプトが同じ書式を使うため、
書式と設定の呼び出しをここにまとめる。import しただけでは何も設定しない。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

# スクリプト共通のログの書式（時刻 - レベル - メッセージ）
DEFAULT_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def configure_logging(
    level: int = logging.INFO,
    *,
    handlers: Iterable[logging.Handler] | None = None,
) -> None:
    """ルートロガーに共通の書式でログの出力先を設定する。

    `logging.basicConfig` と同じく、ルートロガーに既にハンドラがあるときは何もしない。
    スクリプトの `main()` の先頭で 1 回だけ呼ぶ。

    Args:
        level: 出力するログの最低レベル
        handlers: 出力先のハンドラ。None のときは標準エラー出力に出す
    """
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT, handlers=handlers)
