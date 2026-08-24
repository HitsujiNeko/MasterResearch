"""lulc_classes.py（LULC 共通クラス写像表）のテスト。

写像表そのものの網羅性・整合性と、写像を適用する関数の挙動を対象とする。
`compare_lulc_esri_glc.py` からの利用（挙動不変であること）は
`tests/analysis/test_compare_lulc_esri_glc.py` 側で確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from src.common import lulc_classes as target
from src.preprocessing.fetch_esri_lulc_hanoi import CLASS_LABELS as ESRI_CLASS_LABELS
from src.preprocessing.fetch_esri_lulc_hanoi import FILLED_VALUES as ESRI_FILLED_VALUES
from src.preprocessing.fetch_glc_fcs30d_hanoi import CLASS_LABELS as GLC_CLASS_LABELS


class TestClassMappingCoverage:
    """写像表の網羅性テスト。"""

    def test_all_glc_classes_are_mapped(self) -> None:
        """GLC の 35 クラスすべてに写像先がある（写像漏れを防ぐ）。"""
        assert set(GLC_CLASS_LABELS) == set(target.GLC_TO_COMMON)

    def test_all_valid_esri_classes_are_mapped(self) -> None:
        """Esri の写像対象 8 クラスすべてに写像先がある（無効値・Clouds は除く）。"""
        expected = set(ESRI_CLASS_LABELS) - set(ESRI_FILLED_VALUES)
        assert expected == set(target.ESRI_TO_COMMON)

    def test_mapping_targets_are_defined_common_classes(self) -> None:
        """写像先はすべて定義済みの共通クラスである。"""
        defined = set(target.COMMON_CLASS_LABELS)

        assert set(target.GLC_TO_COMMON.values()) <= defined
        assert set(target.ESRI_TO_COMMON.values()) <= defined

    def test_common_class_ids_have_no_duplicate_meaning(self) -> None:
        """共通クラスIDとラベルが1対1に対応する（重複ラベルが無い）。"""
        labels = list(target.COMMON_CLASS_LABELS.values())
        assert len(labels) == len(set(labels))


class TestClassSchemes:
    """CLASS_SCHEMES レジストリのテスト。"""

    def test_registers_both_dataset_schemes(self) -> None:
        """GLC・Esri 双方のスキーム名が登録されている。"""
        assert set(target.CLASS_SCHEMES) == {"glc2022", "esri2022"}

    def test_scheme_values_are_the_mapping_tables(self) -> None:
        """スキーム名は対応する写像表そのものを指す。"""
        assert target.CLASS_SCHEMES["glc2022"] is target.GLC_TO_COMMON
        assert target.CLASS_SCHEMES["esri2022"] is target.ESRI_TO_COMMON


class TestBuildClassLookup:
    """build_class_lookup のテスト。"""

    def test_lookup_matches_mapping_table(self) -> None:
        """添字表は写像表と同じ対応を返す。"""
        lookup = target.build_class_lookup(target.GLC_TO_COMMON)

        for source_value, common_value in target.GLC_TO_COMMON.items():
            assert int(lookup[source_value]) == common_value

    def test_values_outside_mapping_default_to_invalid(self) -> None:
        """写像表に無い添字表内の値は COMMON_INVALID になる。"""
        # GLC_TO_COMMON に無い値 210 未満で写像表に無いもの（例: 30）は0になる
        lookup = target.build_class_lookup(target.GLC_TO_COMMON)

        assert int(lookup[30]) == target.COMMON_INVALID

    def test_rejects_negative_keys(self) -> None:
        """写像表のキーに負の値が含まれると ValueError になる。

        ガードが無いと `lookup[-1] = ...` がNumPyの負インデックス解釈で添字表の
        末尾（他の正当なクラスに対応するスロット）を静かに上書きしてしまう。
        現行の GLC_TO_COMMON・ESRI_TO_COMMON は非負キーのみだが、将来この共通
        モジュールへ負のfill値をキーに持つ写像表が追加されることへの回帰テスト。
        """
        with pytest.raises(ValueError, match="負の値"):
            target.build_class_lookup({10: target.COMMON_CROPLAND, -1: target.COMMON_INVALID})


class TestMapToCommonClasses:
    """map_to_common_classes のテスト。"""

    def test_maps_glc_classes_to_common_scheme(self) -> None:
        """GLC の複数クラスが同一の共通クラスへ集約される（多対1）。"""
        array = np.array([[10, 20, 190, 210]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.GLC_TO_COMMON)

        assert [int(value) for value in result[0]] == [
            target.COMMON_CROPLAND,
            target.COMMON_CROPLAND,
            target.COMMON_BUILT,
            target.COMMON_WATER,
        ]

    def test_unmapped_values_in_range_become_invalid(self) -> None:
        """写像表に無い値（添字表の範囲内）は COMMON_INVALID になる。"""
        array = np.array([[0]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.ESRI_TO_COMMON)

        assert int(result[0, 0]) == target.COMMON_INVALID

    def test_values_outside_lookup_range_become_invalid(self) -> None:
        """添字表の範囲外の値（GLC の Filled value 250 等）は COMMON_INVALID になる。"""
        array = np.array([[250]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.GLC_TO_COMMON)

        assert int(result[0, 0]) == target.COMMON_INVALID

    def test_negative_values_become_invalid_not_negative_indexed(self) -> None:
        """負の画素値はNumPyの負インデックス解釈で誤分類されず COMMON_INVALID になる。

        符号付きdtype（int16等）の負値・未定義fill値を想定した回帰テスト。
        ガードが無いと `-11` は添字表の末尾から11番目（GLCでは画素値210＝水域）
        を参照してしまう。
        """
        array = np.array([[-11]], dtype=np.int16)

        result = target.map_to_common_classes(array, target.GLC_TO_COMMON)

        assert int(result[0, 0]) == target.COMMON_INVALID

    def test_returns_uint8_array_of_same_shape(self) -> None:
        """出力は入力と同じ形状の uint8 配列になる。"""
        array = np.array([[1, 2], [4, 5]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.ESRI_TO_COMMON)

        assert result.shape == array.shape
        assert result.dtype == np.uint8


class TestBuildClassLookupRejectsEmptyMapping:
    """空の写像表に対する境界値テスト。"""

    def test_raises_value_error_for_empty_mapping(self) -> None:
        """空の写像表は max() が失敗するため ValueError になる。"""
        with pytest.raises(ValueError):
            target.build_class_lookup({})
