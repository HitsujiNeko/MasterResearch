"""リトライ付きHTTP JSON取得処理。

WFS等のリモートAPIから一時的なエラー時にリトライしつつJSONレスポンスを
取得する処理を集約する。標準ライブラリの urllib のみに依存し、requests は使わない。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def fetch_json_with_retry(
    url: str,
    timeout: int,
    max_retry_count: int = 3,
    retry_wait_seconds: int = 10,
    rate_limit_max_retry_count: int = 6,
    rate_limit_base_wait_seconds: int = 60,
) -> dict[str, Any]:
    """リトライ付きでURLからJSONレスポンスを取得する。

    通常のエラー（接続エラー・HTTP 429以外のHTTPエラー）は max_retry_count 回まで
    retry_wait_seconds 秒間隔でリトライする。
    HTTP 429（レート制限）はRetry-Afterを返さないサーバーを想定し、
    rate_limit_base_wait_seconds 秒を起点とした指数バックオフで
    rate_limit_max_retry_count 回までリトライする（通常リトライとは別枠でカウントする）。

    Args:
        url: リクエストURL。
        timeout: タイムアウト秒数。
        max_retry_count: 通常エラー時の最大リトライ回数。
        retry_wait_seconds: 通常エラー時のリトライ待機秒数。
        rate_limit_max_retry_count: HTTP 429時の最大リトライ回数。
        rate_limit_base_wait_seconds: HTTP 429時の指数バックオフ起点秒数。

    Returns:
        JSONレスポンスをパースした辞書。

    Raises:
        ValueError: url が http/https 以外のスキームの場合。
        RuntimeError: リトライ上限を超えてもエラーが解消しない場合。
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"許可されていないURLスキームです: {url}")

    last_error: Exception | None = None
    generic_attempt = 0
    rate_limit_attempt = 0

    while True:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > rate_limit_max_retry_count:
                    raise RuntimeError(
                        f"レート制限（429）が{rate_limit_max_retry_count}回"
                        f"解消しませんでした: {exc}"
                    ) from exc
                wait_seconds = rate_limit_base_wait_seconds * (2 ** (rate_limit_attempt - 1))
                logger.warning(
                    "レート制限429（リトライ %d/%d）。%d秒待機します…",
                    rate_limit_attempt,
                    rate_limit_max_retry_count,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            generic_attempt += 1
            logger.warning(
                "HTTPエラー %d（試行 %d/%d）: %s",
                exc.code,
                generic_attempt,
                max_retry_count,
                url[:120],
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            generic_attempt += 1
            logger.warning(
                "接続エラー（試行 %d/%d）: %s",
                generic_attempt,
                max_retry_count,
                exc,
            )

        if generic_attempt > max_retry_count:
            raise RuntimeError(
                f"リクエストが{max_retry_count}回失敗しました: {last_error}"
            ) from last_error

        logger.info("%d秒後にリトライします…", retry_wait_seconds)
        time.sleep(retry_wait_seconds)
