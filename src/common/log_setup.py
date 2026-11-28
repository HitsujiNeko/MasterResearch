"""コマンドとして実行するスクリプトのログ設定。

ログの設定はエントリポイント（コマンドとして実行するスクリプト）の `main()` の中で
1 回だけ行う（CodingRule.md 5.3）。多くのスクリプトが同じ書式を使うため、
書式と設定の呼び出しをここにまとめる。import しただけでは何も設定しない。
"""

from __future__ import annotations

import logging
from pathlib import Path

# スクリプト共通のログの書式（時刻 - レベル - メッセージ）
DEFAULT_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def configure_logging(level: int = logging.INFO, *, log_file: Path | None = None) -> None:
    """ルートロガーに共通の書式でログの出力先を設定する。

    `logging.basicConfig` と同じく、ルートロガーに既にハンドラがあるときは何もしない
    （このときはログファイルも作らない）。スクリプトの `main()` の先頭で 1 回だけ呼ぶ。

    Args:
        level: 出力するログの最低レベル
        log_file: ログを書き出すファイル。指定したときは標準エラー出力とこのファイルの
            両方に出し、親ディレクトリが無ければ作る。None のときは標準エラー出力だけに出す
    """
    if logging.getLogger().handlers:
        return
    handlers: list[logging.Handler] | None = None
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()]
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT, handlers=handlers)
