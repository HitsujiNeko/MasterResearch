"""log_setup.py（スクリプト共通のログ設定）のテスト。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.common import log_setup
from src.common.log_setup import DEFAULT_LOG_FORMAT, configure_logging


@contextmanager
def empty_root_logger() -> Iterator[logging.Logger]:
    """ハンドラの無いルートロガーにし、抜けるときに元のハンドラ・レベルへ戻す。

    pytest はテスト本体の実行直前にログの取り込み用のハンドラをルートロガーに付ける
    （そのままでは configure_logging が何もしない）ため、フィクスチャではなく
    テスト本体の中で使う。
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_default_log_format() -> None:
    """共通の書式が、移行前の各スクリプトと同じ「時刻 - レベル - メッセージ」である。"""
    assert DEFAULT_LOG_FORMAT == "%(asctime)s - %(levelname)s - %(message)s"


def test_configure_logging_passes_defaults_to_basic_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既定では INFO と共通の書式で、標準エラー出力だけに出す設定を basicConfig に渡す。"""
    calls: list[dict] = []
    monkeypatch.setattr(log_setup.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    with empty_root_logger():
        configure_logging()

    assert calls == [{"level": logging.INFO, "format": DEFAULT_LOG_FORMAT, "handlers": None}]


def test_configure_logging_sets_up_root_logger_once() -> None:
    """ハンドラの無いルートロガーに 1 つだけ出力先を付け、2 回目は何もしない。"""
    with empty_root_logger() as root:
        configure_logging(logging.DEBUG)
        configure_logging()

        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG
        assert root.handlers[0].formatter._fmt == DEFAULT_LOG_FORMAT


def test_configure_logging_writes_to_log_file(tmp_path: Path) -> None:
    """log_file を指定すると、親ディレクトリを作り、ファイルと標準エラー出力の両方に出す。"""
    log_file = tmp_path / "data" / "output" / "script.log"

    with empty_root_logger() as root:
        configure_logging(log_file=log_file)
        logging.getLogger("test_log_setup").info("書き出しの確認")
        handler_types = [type(handler) for handler in root.handlers]

    # ハンドラは empty_root_logger を抜けるときに閉じられ、内容がファイルに書き出される
    assert handler_types == [logging.FileHandler, logging.StreamHandler]
    assert "INFO - 書き出しの確認" in log_file.read_text(encoding="utf-8")


def test_configure_logging_does_nothing_when_already_configured(tmp_path: Path) -> None:
    """ルートロガーにハンドラがあるとき（pytest の実行中など）は、ログファイルも作らない。"""
    log_file = tmp_path / "data" / "output" / "script.log"
    handlers_before = logging.getLogger().handlers[:]
    assert handlers_before  # pytest がログの取り込み用のハンドラを付けている

    configure_logging(log_file=log_file)

    assert logging.getLogger().handlers == handlers_before
    assert not (tmp_path / "data").exists()
