"""urban_params/__main__.py（``python -m src.analysis.urban_params`` の入口）のテスト。"""

from __future__ import annotations

import runpy
import sys

import pytest

from src.analysis.urban_params import run


def test_module_execution_calls_run_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m`` で実行すると run.main を 1 回呼ぶ。"""
    calls: list[str] = []
    monkeypatch.setattr(run, "main", lambda: calls.append("called"))
    monkeypatch.delitem(sys.modules, "src.analysis.urban_params.__main__", raising=False)

    runpy.run_module("src.analysis.urban_params", run_name="__main__")

    assert calls == ["called"]
