"""http_fetch.py（リトライ付きHTTP JSON取得）のテスト。"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from src.common import http_fetch


class _FakeResponse:
    """`urllib.request.urlopen` の戻り値を模したダミーレスポンス。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_fetch_json_with_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常応答時はそのままJSONを辞書として返す。"""
    monkeypatch.setattr(
        http_fetch.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse({"ok": True}),
    )

    result = http_fetch.fetch_json_with_retry("https://example.com", timeout=10)

    assert result == {"ok": True}


def test_fetch_json_with_retry_succeeds_after_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一時的な接続エラーの後に成功した場合、リトライして結果を返す。"""
    attempt_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        attempt_count["value"] += 1
        if attempt_count["value"] < 2:
            raise urllib.error.URLError("temporary failure")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = http_fetch.fetch_json_with_retry(
        "https://example.com", timeout=10, max_retry_count=3, retry_wait_seconds=5
    )

    assert result == {"ok": True}
    assert sleep_calls == [5]


def test_fetch_json_with_retry_raises_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """リトライ上限を超えても失敗し続ける場合はRuntimeErrorになる。"""

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        raise urllib.error.URLError("always fails")

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError):
        http_fetch.fetch_json_with_retry(
            "https://example.com", timeout=10, max_retry_count=2, retry_wait_seconds=1
        )


def test_fetch_json_with_retry_rate_limit_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429時は指数バックオフの待機秒数（60→120→240）でリトライする。"""
    attempt_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        attempt_count["value"] += 1
        if attempt_count["value"] <= 3:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = http_fetch.fetch_json_with_retry(
        "https://example.com",
        timeout=10,
        rate_limit_base_wait_seconds=60,
        rate_limit_max_retry_count=6,
    )

    assert result == {"ok": True}
    assert sleep_calls == [60, 120, 240]
