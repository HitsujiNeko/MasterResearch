"""gee_calc_LST.py（エクスポート名のセンサ別生成・雲マスクの QA ビット）のテスト。

GEE への接続を伴わない範囲のみを対象とする。`cloud_mask` は、1 画素の QA_PIXEL 値を
持つ偽の `ee.Image` に適用し、残すか除外するかの判定を確認する。
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


class _FakePixel:
    """`ee.Image` の 1 画素を模し、整数値に対するビット演算・比較・論理積を再現する。"""

    def __init__(self, value: int) -> None:
        self.value = value

    def bitwiseAnd(self, other: int) -> "_FakePixel":
        return _FakePixel(self.value & other)

    def eq(self, other: int) -> "_FakePixel":
        return _FakePixel(int(self.value == other))

    def And(self, other: "_FakePixel") -> "_FakePixel":
        return _FakePixel(int(bool(self.value) and bool(other.value)))


class _FakeImage:
    """QA_PIXEL のみを持つ 1 画素の `ee.Image` を模し、適用したマスクを記録する。"""

    def __init__(self, qa_value: int) -> None:
        self.qa_value = qa_value
        self.selected: list = []
        self.applied_mask = None

    def select(self, name: str) -> _FakePixel:
        self.selected.append(name)
        return _FakePixel(self.qa_value)

    def updateMask(self, mask: _FakePixel) -> "_FakeImage":
        self.applied_mask = mask
        return self


@pytest.mark.parametrize(
    ("qa_value", "kept"),
    [
        (0, True),
        (1 << 3, False),  # Cloud
        (1 << 4, False),  # Cloud Shadow
        ((1 << 3) | (1 << 4), False),
        (1 << 0, True),  # Fill は除外しない
        (1 << 1, True),  # Dilated Cloud は除外しない
        (1 << 2, False),  # Cirrus
        (1 << 5, False),  # Snow
        (1 << 7, True),  # Water は除外しない
        ((1 << 5) | (1 << 6), False),  # Clear が立っていても Snow があれば除外する
        # bit 6（Clear）＋各信頼度フィールド（bit 8〜15）がすべて 01（低）
        (21824, True),
        # bit 3（Cloud）＋雲の信頼度（bit 8・9）が 11（高）＋他の信頼度が 01（低）
        (22280, False),
    ],
)
def test_cloud_mask_excludes_cirrus_cloud_shadow_snow(qa_value: int, kept: bool) -> None:
    """QA_PIXEL の bit 2（Cirrus）・3（Cloud）・4（Cloud Shadow）・5（Snow）のいずれかが
    立つ画素だけを除外する。"""
    image = _FakeImage(qa_value)

    result = calc_lst.cloud_mask(image)

    assert result is image
    assert image.selected == ["QA_PIXEL"]
    assert bool(image.applied_mask.value) is kept
