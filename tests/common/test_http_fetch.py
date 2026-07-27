"""http_fetch.py（リトライ付きHTTP取得）のテスト。

バイト列取得（`fetch_bytes_with_retry`）とJSON取得（`fetch_json_with_retry`）の双方を
対象とする。リトライ方針はバイト列側に集約されているため、JSON側のテストは
その委譲が壊れていないことも兼ねて確認する。
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from src.common import http_fetch


class _FakeResponse:
    """`urllib.request.urlopen` の戻り値を模したダミーレスポンス。

    本体はバイト列を返すだけ。JSON を返したい場合は `from_json` を使う。
    """

    def __init__(self, body: bytes) -> None:
        """レスポンス本文となるバイト列を保持する。

        Args:
            body: `read()` がそのまま返すバイト列。
        """
        self._body = body

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "_FakeResponse":
        """辞書をJSONバイト列に変換したレスポンスを作る。

        Args:
            payload: JSONへ変換する辞書。

        Returns:
            UTF-8でエンコード済みの本文を持つレスポンス。
        """
        return cls(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "_FakeResponse":
        """`with` 文で自身を返す（urlopen のコンテキストマネージャを模す）。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """後始末は不要なため何もしない。"""
        return None

    def read(self) -> bytes:
        """保持しているレスポンス本文を返す。"""
        return self._body


def test_fetch_bytes_with_retry_rejects_non_http_scheme() -> None:
    """http/https以外のURLスキームはValueErrorになる。"""
    with pytest.raises(ValueError):
        http_fetch.fetch_bytes_with_retry("file:///etc/passwd", timeout=10)


def test_fetch_bytes_with_retry_returns_binary_body_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """バイナリ（GeoTIFF・ZIP等）をデコードせずそのまま返す。"""
    binary_body = b"PK\x03\x04\x00\xff\xfe"
    monkeypatch.setattr(
        http_fetch.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse(binary_body),
    )

    result = http_fetch.fetch_bytes_with_retry("https://example.com/x.zip", timeout=10)

    assert result == binary_body


def test_fetch_bytes_with_retry_succeeds_after_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一時的な接続エラーの後に成功した場合、リトライして結果を返す。"""
    attempt_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        """初回だけ接続エラーを送出し、2回目以降は成功レスポンスを返す。

        Raises:
            urllib.error.URLError: 初回呼び出し時。
        """
        attempt_count["value"] += 1
        if attempt_count["value"] < 2:
            raise urllib.error.URLError("temporary failure")
        return _FakeResponse(b"OK")

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = http_fetch.fetch_bytes_with_retry(
        "https://example.com", timeout=10, max_retry_count=3, retry_wait_seconds=5
    )

    assert result == b"OK"
    assert sleep_calls == [5]


def test_fetch_bytes_with_retry_raises_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """リトライ上限を超えても失敗し続ける場合はRuntimeErrorになる。"""

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        """常に接続エラーを送出する。

        Raises:
            urllib.error.URLError: 毎回。
        """
        raise urllib.error.URLError("always fails")

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError):
        http_fetch.fetch_bytes_with_retry(
            "https://example.com", timeout=10, max_retry_count=2, retry_wait_seconds=1
        )


def test_fetch_json_with_retry_rejects_non_http_scheme() -> None:
    """http/https以外のURLスキームはValueErrorになる。"""
    with pytest.raises(ValueError):
        http_fetch.fetch_json_with_retry("file:///etc/passwd", timeout=10)


def test_fetch_json_with_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常応答時はそのままJSONを辞書として返す。"""
    monkeypatch.setattr(
        http_fetch.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse.from_json({"ok": True}),
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
        return _FakeResponse.from_json({"ok": True})

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = http_fetch.fetch_json_with_retry(
        "https://example.com", timeout=10, max_retry_count=3, retry_wait_seconds=5
    )

    assert result == {"ok": True}
    assert sleep_calls == [5]


def test_fetch_json_with_retry_succeeds_after_http_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 500エラー（429以外）の後に成功した場合、リトライして結果を返す。"""
    attempt_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        attempt_count["value"] += 1
        if attempt_count["value"] < 2:
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", hdrs=None, fp=None)
        return _FakeResponse.from_json({"ok": True})

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


def test_fetch_json_with_retry_attempts_max_retry_count_plus_one_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_retry_count回のリトライ後（初回+max_retry_count回試行後）にRuntimeErrorになる。"""
    attempt_count = {"value": 0}

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        attempt_count["value"] += 1
        raise urllib.error.URLError("always fails")

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError):
        http_fetch.fetch_json_with_retry(
            "https://example.com", timeout=10, max_retry_count=2, retry_wait_seconds=1
        )

    assert attempt_count["value"] == 3


def test_fetch_json_with_retry_rate_limit_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429時は指数バックオフの待機秒数（60→120→240）でリトライする。"""
    attempt_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        attempt_count["value"] += 1
        if attempt_count["value"] <= 3:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        return _FakeResponse.from_json({"ok": True})

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
