"""リトライ付きHTTP取得処理。

WFS等のリモートAPIやGEEのダウンロードURLから、一時的なエラー時にリトライしつつ
レスポンスを取得する処理を集約する。標準ライブラリの urllib のみに依存し、
requests は使わない。

バイト列を返す `fetch_bytes_with_retry` が基本形で、`fetch_json_with_retry` は
その結果をJSONとして解釈する薄いラッパーである（リトライ方針を一箇所に保つため）。
"""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# リトライしても解消しないHTTPステータス。認証・権限・不在は待っても直らないため、
# 待機を挟まず即座に投げ直す。とくに401はトークン失効で頻出し、リトライすると
# 原因の分かるメッセージが出るまで待たされる（既定では約30秒）。
PERMANENT_HTTP_STATUS_CODES = (400, 401, 403, 404, 405, 410)


def fetch_bytes_with_retry(
    url: str,
    timeout: int,
    max_retry_count: int = 3,
    retry_wait_seconds: int = 10,
    rate_limit_max_retry_count: int = 6,
    rate_limit_base_wait_seconds: int = 60,
    headers: dict[str, str] | None = None,
) -> bytes:
    """リトライ付きでURLからレスポンス本文をバイト列として取得する。

    通常のエラー（接続エラー・一時的なHTTPエラー）は max_retry_count 回まで
    retry_wait_seconds 秒間隔でリトライする。
    HTTP 429（レート制限）はRetry-Afterを返さないサーバーを想定し、
    rate_limit_base_wait_seconds 秒を起点とした指数バックオフで
    rate_limit_max_retry_count 回までリトライする（通常リトライとは別枠でカウントする）。
    **認証・権限・不在（`PERMANENT_HTTP_STATUS_CODES`）はリトライしない**。待っても
    解消せず、原因の分かるメッセージが出るまで無駄に待たせるだけのため。

    `headers` は Bearer トークン等の認証ヘッダーを要求するAPI（NASA LAADS DAAC 等）の
    ために用意している。**ヘッダーの内容はログに出力しない**（認証情報の漏洩を避けるため）。

    Args:
        url: リクエストURL。
        timeout: タイムアウト秒数。
        max_retry_count: 通常エラー時の最大リトライ回数。
        retry_wait_seconds: 通常エラー時のリトライ待機秒数。
        rate_limit_max_retry_count: HTTP 429時の最大リトライ回数。
        rate_limit_base_wait_seconds: HTTP 429時の指数バックオフ起点秒数。
        headers: リクエストに付与するHTTPヘッダー。未指定時は付与しない。

    Returns:
        レスポンス本文のバイト列。

    Raises:
        ValueError: url が http/https 以外のスキームの場合。
        RuntimeError: リトライ上限を超えてもエラーが解消しない場合、または
            リトライしても解消しないHTTPステータスが返った場合。
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"許可されていないURLスキームです: {url}")

    last_error: Exception | None = None
    generic_attempt = 0
    rate_limit_attempt = 0

    while True:
        # Request は試行ごとに作り直す。urllib はリダイレクトのループ検出状態
        # （`redirect_dict`）を Request オブジェクトへ書き込むため、使い回すと
        # 訪問済み URL が試行をまたいで累積し、リダイレクトを伴う URL では
        # 数回目のリトライが偽の「infinite loop」エラーで失敗する。
        # ヘッダーはリダイレクト時に urllib 側が引き継ぐため、作り直しても失われない。
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
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

            if exc.code in PERMANENT_HTTP_STATUS_CODES:
                # 待っても解消しない。トークン失効（401）等の原因を即座に伝える
                raise RuntimeError(
                    f"リトライしても解消しないHTTPエラーです（{exc.code}）。"
                    "認証情報・権限・URLを確認してください。"
                    f"詳細: {exc}"
                ) from exc

            generic_attempt += 1
            logger.warning(
                "HTTPエラー %d（試行 %d/%d）: %s",
                exc.code,
                generic_attempt,
                max_retry_count,
                url[:120],
            )
        # http.client.HTTPException は OSError 系ではないため個別に挙げる。
        # 大容量ダウンロードが途中で切れる IncompleteRead がこれに当たり、
        # 捕捉しないとリトライされないまま呼び出し元へ素通りする。
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as exc:
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


def fetch_json_with_retry(
    url: str,
    timeout: int,
    max_retry_count: int = 3,
    retry_wait_seconds: int = 10,
    rate_limit_max_retry_count: int = 6,
    rate_limit_base_wait_seconds: int = 60,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """リトライ付きでURLからJSONレスポンスを取得する。

    リトライ方針は `fetch_bytes_with_retry` に委ね、本関数はその結果を
    JSONとして解釈するだけにする。

    Args:
        url: リクエストURL。
        timeout: タイムアウト秒数。
        max_retry_count: 通常エラー時の最大リトライ回数。
        retry_wait_seconds: 通常エラー時のリトライ待機秒数。
        rate_limit_max_retry_count: HTTP 429時の最大リトライ回数。
        rate_limit_base_wait_seconds: HTTP 429時の指数バックオフ起点秒数。
        headers: リクエストに付与するHTTPヘッダー。未指定時は付与しない。

    Returns:
        JSONレスポンスをパースした辞書。

    Raises:
        ValueError: url が http/https 以外のスキームの場合。
        RuntimeError: リトライ上限を超えてもエラーが解消しない場合。
    """
    response_body = fetch_bytes_with_retry(
        url=url,
        timeout=timeout,
        max_retry_count=max_retry_count,
        retry_wait_seconds=retry_wait_seconds,
        rate_limit_max_retry_count=rate_limit_max_retry_count,
        rate_limit_base_wait_seconds=rate_limit_base_wait_seconds,
        headers=headers,
    )
    return json.loads(response_body.decode("utf-8"))
