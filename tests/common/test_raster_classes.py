"""raster_classes.py（カテゴリラスタのクラス別集計）のテスト。

クラス体系に依存しない集計ロジックを対象とし、ラベル辞書・無効値は
テスト用の合成値を使う。各データセット固有の定数の配線は
それぞれの取得スクリプトのテストで確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from src.common.raster_classes import build_class_distribution

# テスト用のクラス体系（0 を無効値、1〜3 を有効クラスとする）
CLASS_LABELS = {1: "Water", 2: "Trees", 3: "Built"}
FILLED_VALUES = (0, 99)


def test_counts_classes_and_excludes_filled_values() -> None:
    """無効値は有効画素から除外して集計する。"""
    array = np.array([[1, 1, 2], [3, 0, 99]], dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=FILLED_VALUES)

    assert result["total_pixels"] == 6
    assert result["roi_pixels"] == 6
    assert result["outside_roi_pixels"] == 0
    assert result["filled_pixels"] == 2
    assert result["valid_pixels"] == 4
    assert result["valid_pixel_ratio"] == pytest.approx(4 / 6)


def test_roi_mask_excludes_clip_margin_from_coverage() -> None:
    """ROI 外のクリップ余白を欠測と数えず、有効画素率の分母も ROI 内画素数になる。

    余白（ROI 外）は nodata=0 で無効値と同値になるため、マスクなしでは
    有効カバレッジを過小評価してしまう。
    """
    array = np.array([[1, 2, 0], [3, 0, 0]], dtype=np.uint8)
    # 左2列が ROI 内、右1列は ROI 外の余白
    roi_mask = np.array([[True, True, False], [True, True, False]])

    result = build_class_distribution(
        array, CLASS_LABELS, roi_mask=roi_mask, filled_values=FILLED_VALUES
    )

    assert result["total_pixels"] == 6
    assert result["roi_pixels"] == 4
    assert result["outside_roi_pixels"] == 2
    # ROI 内の無効値は1画素のみ（余白の2画素は含めない）
    assert result["filled_pixels"] == 1
    assert result["valid_pixels"] == 3
    assert result["valid_pixel_ratio"] == pytest.approx(3 / 4)


def test_roi_mask_excludes_outside_classes_from_distribution() -> None:
    """ROI 外のクラス値はクラス分布に含めない。"""
    array = np.array([[1, 2], [3, 2]], dtype=np.uint8)
    roi_mask = np.array([[True, False], [True, False]])

    result = build_class_distribution(
        array, CLASS_LABELS, roi_mask=roi_mask, filled_values=FILLED_VALUES
    )

    assert [entry["value"] for entry in result["classes"]] == [1, 3]


def test_rejects_roi_mask_with_mismatched_shape() -> None:
    """形状が一致しない roi_mask は ValueError になる。"""
    array = np.array([[1, 2]], dtype=np.uint8)
    roi_mask = np.array([[True, True, True]])

    with pytest.raises(ValueError, match="形状が"):
        build_class_distribution(
            array, CLASS_LABELS, filled_values=FILLED_VALUES, roi_mask=roi_mask
        )


def test_ratios_sum_to_one_and_sorted_by_pixel_count() -> None:
    """クラス別比率の合計は1になり、画素数の降順で並ぶ。"""
    array = np.array([[1, 1, 1], [2, 2, 3]], dtype=np.uint8)

    classes = build_class_distribution(array, CLASS_LABELS, filled_values=FILLED_VALUES)["classes"]

    assert [entry["value"] for entry in classes] == [1, 2, 3]
    assert sum(entry["ratio"] for entry in classes) == pytest.approx(1.0)
    assert classes[0]["label"] == "Water"


def test_reports_unknown_class_values() -> None:
    """ラベル辞書にないクラス値は unknown_class_values に記録する。"""
    array = np.array([[1, 42]], dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=FILLED_VALUES)

    assert result["unknown_class_values"] == [42]
    assert any(entry["label"] == "Unknown" for entry in result["classes"])


def test_empty_filled_values_treats_all_values_as_valid() -> None:
    """空の filled_values を明示した場合はすべての値を有効画素として扱う。"""
    array = np.array([[0, 1]], dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=())

    assert result["filled_pixels"] == 0
    assert result["valid_pixels"] == 2
    assert result["unknown_class_values"] == [0]


def test_requires_filled_values_to_be_specified() -> None:
    """filled_values の指定漏れは TypeError で弾く（有効カバレッジの過大評価を防ぐ）。"""
    array = np.array([[0, 1]], dtype=np.uint8)

    with pytest.raises(TypeError):
        build_class_distribution(array, CLASS_LABELS)  # type: ignore[call-arg]


def test_all_filled_array_yields_zero_ratio_without_error() -> None:
    """全画素が無効値でも例外にならず、有効画素率は0になる。"""
    array = np.zeros((3, 3), dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=FILLED_VALUES)

    assert result["valid_pixels"] == 0
    assert result["valid_pixel_ratio"] == 0.0
    assert result["classes"] == []


def test_reports_filled_value_counts_per_value() -> None:
    """無効値ごとの内訳を返し、出現しなかった無効値も 0 として残す。"""
    array = np.array([[0, 0, 1], [2, 3, 3]], dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=(0, 99))

    assert result["filled_value_counts"] == {"0": 2, "99": 0}
    assert result["filled_pixels"] == 2


def test_filled_value_counts_respects_roi_mask() -> None:
    """無効値の内訳も ROI 内のみを数える。"""
    array = np.array([[0, 0], [1, 0]], dtype=np.uint8)
    roi_mask = np.array([[True, False], [True, False]])

    result = build_class_distribution(
        array, CLASS_LABELS, filled_values=FILLED_VALUES, roi_mask=roi_mask
    )

    # ROI 外の 0 が 2 画素あるが、内訳に含めない
    assert result["filled_value_counts"] == {"0": 1, "99": 0}
    assert result["filled_pixels"] == 1


def test_empty_array_yields_zero_ratio_without_error() -> None:
    """画素が1つもない配列でもゼロ除算にならない。"""
    array = np.array([], dtype=np.uint8)

    result = build_class_distribution(array, CLASS_LABELS, filled_values=FILLED_VALUES)

    assert result["total_pixels"] == 0
    assert result["valid_pixel_ratio"] == 0.0
