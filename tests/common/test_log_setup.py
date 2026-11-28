"""log_setup.py（スクリプト共通のログ設定）のテスト。"""

from __future__ import annotations

import logging

import pytest

from src.common import log_setup
from src.common.log_setup import DEFAULT_LOG_FORMAT, configure_logging


def test_default_log_format() -> None:
    """共通の書式が、移行前の各スクリプトと同じ「時刻 - レベル - メッセージ」である。"""
    assert DEFAULT_LOG_FORMAT == "%(asctime)s - %(levelname)s - %(message)s"


def test_configure_logging_passes_defaults_to_basic_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既定では INFO と共通の書式で basicConfig を呼ぶ。"""
    calls: list[dict] = []
    monkeypatch.setattr(log_setup.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    configure_logging()

    assert calls == [{"level": logging.INFO, "format": DEFAULT_LOG_FORMAT, "handlers": None}]


def test_configure_logging_passes_level_and_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """レベルとハンドラの指定をそのまま basicConfig に渡す。"""
    calls: list[dict] = []
    monkeypatch.setattr(log_setup.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))
    handler = logging.NullHandler()

    configure_logging(logging.DEBUG, handlers=[handler])

    assert calls == [{"level": logging.DEBUG, "format": DEFAULT_LOG_FORMAT, "handlers": [handler]}]


def test_configure_logging_sets_up_root_logger_once() -> None:
    """ハンドラの無いルートロガーに 1 つだけ出力先を付け、2 回目は何もしない。"""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    try:
        configure_logging()
        configure_logging()

        assert len(root.handlers) == 1
        assert root.level == logging.INFO
        assert root.handlers[0].formatter._fmt == DEFAULT_LOG_FORMAT
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
