"""gee_calc_LST.py（エクスポート名のセンサ別生成）のテスト。

GEE への接続を伴わない純粋関数のみを対象とし、`ee` の画像演算は
テスト対象外とする。
"""

from __future__ import annotations

import pytest

import src.gee.gee_calc_LST as calc_lst


@pytest.mark.parametrize(
    ("prefix", "sensor", "expected"),
    [
        ("LST", "L8", "LST_Landsat8_20230707_032329Z"),
        ("LST", "L9", "LST_Landsat9_20230707_032329Z"),
        ("INDICES", "L8", "INDICES_Landsat8_20230707_032329Z"),
        ("INDICES", "L9", "INDICES_Landsat9_20230707_032329Z"),
    ],
)
def test_build_export_description_by_sensor(prefix: str, sensor: str, expected: str) -> None:
    """出力名はセンサのラベルを含み、L8 は既存運用と同じ形式を保つ。"""
    description = calc_lst.build_export_description(prefix, "2023-07-07T03:23:29", sensor)

    assert description == expected


def test_build_export_description_default_is_l8() -> None:
    """センサを省略した場合は既存の `Landsat8` 表記になる。"""
    assert (
        calc_lst.build_export_description("LST", "2024-11-30T03:23:36")
        == "LST_Landsat8_20241130_032336Z"
    )


def test_build_export_description_unknown_sensor_raises() -> None:
    """未定義のセンサ名は例外とし、誤ったラベルで出力しない。"""
    with pytest.raises(ValueError, match="未対応のセンサ"):
        calc_lst.build_export_description("LST", "2023-07-07T03:23:29", "L7")
