"""landsat_sensor.py（Landsat 8 / 9 のセンサ定義）のテスト。"""

from __future__ import annotations

import pytest

from src.module import landsat_sensor


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("L8", ["L8"]),
        ("L9", ["L9"]),
        ("L8;L9", ["L8", "L9"]),
        ("L9;L8", ["L9", "L8"]),
        (" l8 ; l9 ", ["L8", "L9"]),
        ("L8;L9;L8", ["L8", "L9"]),
        ("L8;", ["L8"]),
    ],
)
def test_parse_sensors_valid_values(value: str, expected: list[str]) -> None:
    """`;` 区切りの値を、前後の空白・大小文字・重複を吸収して順序どおりに解釈する。"""
    assert landsat_sensor.parse_sensors(value) == expected


@pytest.mark.parametrize("value", [None, float("nan"), "", "   ", ";"])
def test_parse_sensors_missing_defaults_to_l8(value: object) -> None:
    """列の欠損（None / NaN）・空欄は既定の L8 とし、既存設定の挙動を変えない。"""
    assert landsat_sensor.parse_sensors(value) == ["L8"]


@pytest.mark.parametrize("value", ["L7", "L8;L10", "Landsat8", "LC09"])
def test_parse_sensors_unknown_raises(value: str) -> None:
    """未定義のセンサ名を含む場合は黙って無視せず例外とする。"""
    with pytest.raises(ValueError, match="未対応のセンサ"):
        landsat_sensor.parse_sensors(value)


@pytest.mark.parametrize(("sensor", "expected"), [("L8", "Landsat8"), ("L9", "Landsat9")])
def test_get_sensor_label(sensor: str, expected: str) -> None:
    """出力ファイル名用のラベルは既存の `Landsat8` 表記と同じ形式とする。"""
    assert landsat_sensor.get_sensor_label(sensor) == expected


def test_get_sensor_label_unknown_raises() -> None:
    """未定義のセンサ名は例外とする。"""
    with pytest.raises(ValueError, match="未対応のセンサ"):
        landsat_sensor.get_sensor_label("L7")


@pytest.mark.parametrize(
    ("sensor", "level", "expected"),
    [
        ("L8", "toa", "LANDSAT/LC08/C02/T1_TOA"),
        ("L8", "sr", "LANDSAT/LC08/C02/T1_L2"),
        ("L9", "toa", "LANDSAT/LC09/C02/T1_TOA"),
        ("L9", "sr", "LANDSAT/LC09/C02/T1_L2"),
    ],
)
def test_get_collection_id(sensor: str, level: str, expected: str) -> None:
    """センサと処理レベルから GEE のコレクション ID（Collection 2 Tier 1）を得る。"""
    assert landsat_sensor.get_collection_id(sensor, level) == expected


def test_get_collection_id_unknown_level_raises() -> None:
    """未定義の処理レベルは例外とする。"""
    with pytest.raises(ValueError, match="未対応の処理レベル"):
        landsat_sensor.get_collection_id("L8", "l1")
