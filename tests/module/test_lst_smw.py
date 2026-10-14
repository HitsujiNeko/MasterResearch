"""lst_smw.py（SMW 係数のセンサ別切り替え）のテスト。

GEE への接続を伴わない係数テーブルの選択のみを対象とし、`ee` の画像演算は
テスト対象外とする。係数値は参照実装（src/js/modules/SMW_coefficients.js）を
解析して突き合わせ、転記の誤りを検出する。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.module import lst_smw

# 参照実装（Ermida et al., 2020 の GEE コード）の SMW 係数ファイル
REFERENCE_JS_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "js" / "modules" / "SMW_coefficients.js"
)

# `ee.Feature(null, {'TPWpos': 0, 'A': 0.9751, 'B': -205.8929, 'C': 212.7173})` の 1 行に一致する
_FEATURE_PATTERN = re.compile(
    r"'TPWpos':\s*(\d+),\s*'A':\s*(-?[\d.]+),\s*'B':\s*(-?[\d.]+),\s*'C':\s*(-?[\d.]+)"
)


def _load_reference_coefficients(sensor: str) -> list[tuple[int, float, float, float]]:
    """参照実装の JS から、指定センサの係数テーブルを読み取る。"""
    text = REFERENCE_JS_PATH.read_text(encoding="utf-8")
    block = re.search(
        rf"exports\.coeff_SMW_{sensor}\s*=\s*ee\.FeatureCollection\(\[(.*?)\]\);",
        text,
        flags=re.DOTALL,
    )
    assert block is not None, f"参照実装に coeff_SMW_{sensor} が見つからない"
    return [
        (int(tpw_pos), float(a), float(b), float(c))
        for tpw_pos, a, b, c in _FEATURE_PATTERN.findall(block.group(1))
    ]


@pytest.mark.parametrize("sensor", ["L8", "L9"])
def test_get_smw_coefficients_matches_reference(sensor: str) -> None:
    """係数テーブルは参照実装と一致し、TPWpos 0〜9 の 10 行を昇順に持つ。"""
    coefficients = lst_smw.get_smw_coefficients(sensor)

    assert [row[0] for row in coefficients] == list(range(10))
    assert coefficients == _load_reference_coefficients(sensor)


def test_get_smw_coefficients_default_is_l8() -> None:
    """引数を省略した場合は既存の挙動どおり L8 の係数を返す。"""
    assert lst_smw.get_smw_coefficients() == lst_smw.SMW_COEFFICIENTS["L8"]


def test_get_smw_coefficients_differs_between_sensors() -> None:
    """L8 と L9 で係数が異なり、センサの取り違えが値に反映される。"""
    assert lst_smw.get_smw_coefficients("L8") != lst_smw.get_smw_coefficients("L9")


@pytest.mark.parametrize("sensor", ["L7", "Landsat8", ""])
def test_get_smw_coefficients_unknown_raises(sensor: str) -> None:
    """未定義のセンサ名は例外とし、L8 の係数で黙って計算しない。"""
    with pytest.raises(ValueError, match="未対応のセンサ"):
        lst_smw.get_smw_coefficients(sensor)
