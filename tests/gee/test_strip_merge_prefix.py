"""`strip_merge_prefix`（観測日時指定モードの scene_index 接頭辞除去）のテスト。

`src.gee.gee_search_satellite_data` は `ee` / `pandas` / `tqdm` を
モジュール冒頭で import するため、依存をインストールしない環境では
インポート自体が失敗する。ここではそれらをスタブに差し替えてから
モジュールを読み込み、純粋関数のみを検証する（GEE への接続は伴わない）。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _stub_module(name: str) -> None:
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *args, **kwargs: None)
    sys.modules[name] = module


for _name in ("ee", "pandas", "tqdm", "geopandas", "numpy"):
    _stub_module(_name)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.gee.gee_search_satellite_data as search  # noqa: E402


@pytest.mark.parametrize(
    ("scene_index", "expected"),
    [
        # 観測日時指定モードで merge により付いた接頭辞
        ("1_LC08_127045_20240810", "LC08_127045_20240810"),
        ("2_LC08_127045_20241130", "LC08_127045_20241130"),
        ("10_LC09_127045_20220930", "LC09_127045_20220930"),
        # 日時指定なし（merge を通らない）の通常の system:index はそのまま
        ("LC08_127045_20240810", "LC08_127045_20240810"),
        ("LC09_127045_20220930", "LC09_127045_20220930"),
    ],
)
def test_strip_merge_prefix_removes_merge_origin_prefix(scene_index: str, expected: str) -> None:
    """merge 由来の連番接頭辞のみを取り除き、通常の ID は変えない。"""
    assert search.strip_merge_prefix(scene_index) == expected


def test_strip_merge_prefix_is_idempotent() -> None:
    """一度取り除いた ID に対して再度適用しても値が変わらない。"""
    stripped = search.strip_merge_prefix("1_LC08_127045_20240810")
    assert search.strip_merge_prefix(stripped) == stripped


def test_strip_merge_prefix_keeps_indices_without_underscore() -> None:
    """数字だけの ID（接頭辞と区別できない場合）でも末尾を削らない。"""
    assert search.strip_merge_prefix("12345") == "12345"
