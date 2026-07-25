"""compare_lulc_esri_glc.py（LULC 一致度比較スクリプト）のテスト。

解像度の揃え方（細分グリッド・多数決）、共通クラスへの写像、一致度指標といった
純粋関数を対象とする。ラスタ入出力を伴う処理はテスト対象外とする。
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from affine import Affine

from src.analysis import compare_lulc_esri_glc as target


class TestSubdividedTransform:
    """subdivided_transform のテスト。"""

    def test_keeps_origin_and_divides_pixel_size(self) -> None:
        """原点は変えず、画素サイズだけ 1/factor になる。"""
        transform = Affine(0.0003, 0.0, 105.0, 0.0, -0.0003, 21.0)

        result = target.subdivided_transform(transform, 3)

        assert result.c == pytest.approx(105.0)
        assert result.f == pytest.approx(21.0)
        assert result.a == pytest.approx(0.0001)
        assert result.e == pytest.approx(-0.0001)

    def test_factor_one_is_identity(self) -> None:
        """分割数 1 では元の変換と一致する。"""
        transform = Affine(0.0003, 0.0, 105.0, 0.0, -0.0003, 21.0)

        assert target.subdivided_transform(transform, 1) == transform

    def test_rejects_factor_below_one(self) -> None:
        """分割数が 1 未満なら ValueError になる。"""
        with pytest.raises(ValueError, match="1 以上"):
            target.subdivided_transform(Affine.identity(), 0)


class TestMajorityVoteBlocks:
    """majority_vote_blocks のテスト。"""

    def test_takes_most_frequent_value_in_block(self) -> None:
        """3x3 ブロック内の最頻値を採る。"""
        array = np.array(
            [
                [7, 7, 7],
                [7, 7, 1],
                [7, 1, 1],
            ],
            dtype=np.uint8,
        )

        voted, tied = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert voted.shape == (1, 1)
        assert int(voted[0, 0]) == 7
        assert not bool(tied[0, 0])

    def test_excludes_invalid_values_from_vote(self) -> None:
        """無効値は投票から除外し、有効値の中の最頻値を採る。"""
        array = np.array(
            [
                [0, 0, 0],
                [0, 0, 0],
                [0, 0, 1],
            ],
            dtype=np.uint8,
        )

        voted, _ = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert int(voted[0, 0]) == 1

    def test_block_without_valid_value_becomes_invalid(self) -> None:
        """有効値が1つも無いブロックは 0（無効）になる。"""
        array = np.zeros((3, 3), dtype=np.uint8)

        voted, tied = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert int(voted[0, 0]) == 0
        assert not bool(tied[0, 0])

    def test_tie_is_broken_by_smaller_class_value(self) -> None:
        """同数最頻の場合はクラス値の小さい方を採り、同数だったことを報告する。"""
        # 有効値は 2 が 4 個・7 が 4 個・無効値 0 が 1 個
        array = np.array(
            [
                [2, 2, 7],
                [2, 2, 7],
                [7, 7, 0],
            ],
            dtype=np.uint8,
        )

        voted, tied = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert int(voted[0, 0]) == 2
        assert bool(tied[0, 0])

    def test_handles_multiple_blocks_independently(self) -> None:
        """ブロックごとに独立して集約する（並び順が崩れない）。"""
        left = np.full((3, 3), 1, dtype=np.uint8)
        right = np.full((3, 3), 7, dtype=np.uint8)
        array = np.hstack([left, right])

        voted, _ = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert voted.shape == (1, 2)
        assert [int(value) for value in voted[0]] == [1, 7]

    def test_all_invalid_array_returns_zeros(self) -> None:
        """全画素が無効値の場合も例外にせず 0 を返す。"""
        array = np.zeros((6, 6), dtype=np.uint8)

        voted, tied = target.majority_vote_blocks(array, factor=3, invalid_values=(0,))

        assert voted.shape == (2, 2)
        assert not voted.any()
        assert not tied.any()

    def test_block_larger_than_255_pixels_does_not_overflow(self) -> None:
        """1ブロックの画素数が 255 を超えても得票数が桁溢れしない。"""
        # 16x16 = 256 票。得票数を uint8 で数えると 0 に丸まり、結果が静かに壊れる
        array = np.full((16, 16), 7, dtype=np.uint8)

        voted, _ = target.majority_vote_blocks(array, factor=16, invalid_values=(0,))

        assert int(voted[0, 0]) == 7

    def test_rejects_shape_not_divisible_by_factor(self) -> None:
        """形状が分割数で割り切れなければ ValueError になる。"""
        with pytest.raises(ValueError, match="割り切れません"):
            target.majority_vote_blocks(
                np.zeros((4, 4), dtype=np.uint8), factor=3, invalid_values=(0,)
            )


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

    def test_maps_esri_classes_to_common_scheme(self) -> None:
        """Esri の 9 クラスが共通クラスへ写像される。"""
        array = np.array([[1, 2, 5, 7, 11]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.ESRI_TO_COMMON)

        assert [int(value) for value in result[0]] == [
            target.COMMON_WATER,
            target.COMMON_FOREST,
            target.COMMON_CROPLAND,
            target.COMMON_BUILT,
            target.COMMON_GRASS_SHRUB,
        ]

    def test_unmapped_values_become_invalid(self) -> None:
        """写像表に無い値（無効値・体系外）は 0（無効）になる。"""
        array = np.array([[0, 10, 250]], dtype=np.uint8)

        result = target.map_to_common_classes(array, target.ESRI_TO_COMMON)

        assert not result.any()

    def test_built_class_maps_from_both_schemes(self) -> None:
        """不透水面は GLC 190 と Esri 7 の双方から同じ共通クラスになる。"""
        glc = target.map_to_common_classes(np.array([190], dtype=np.uint8), target.GLC_TO_COMMON)
        esri = target.map_to_common_classes(np.array([7], dtype=np.uint8), target.ESRI_TO_COMMON)

        assert int(glc[0]) == int(esri[0]) == target.COMMON_BUILT


class TestBuildConfusionMatrix:
    """build_confusion_matrix のテスト。"""

    def test_rows_are_glc_and_columns_are_esri(self) -> None:
        """行が GLC、列が Esri になる。"""
        class_values = [1, 4]
        glc = np.array([1, 1, 4], dtype=np.uint8)
        esri = np.array([1, 4, 4], dtype=np.uint8)

        confusion = target.build_confusion_matrix(glc, esri, class_values)

        assert confusion.tolist() == [[1, 1], [0, 1]]

    def test_returns_square_matrix_of_class_count(self) -> None:
        """行列の大きさは対象クラス数に一致する。"""
        class_values = sorted(target.COMMON_CLASS_LABELS)

        confusion = target.build_confusion_matrix(
            np.array([4], dtype=np.uint8), np.array([4], dtype=np.uint8), class_values
        )

        assert confusion.shape == (len(class_values), len(class_values))


class TestCohensKappa:
    """cohens_kappa のテスト。"""

    def test_perfect_agreement_gives_one(self) -> None:
        """完全一致では kappa が 1 になる。"""
        confusion = np.array([[50, 0], [0, 50]])

        assert target.cohens_kappa(confusion) == pytest.approx(1.0)

    def test_chance_level_agreement_gives_zero(self) -> None:
        """偶然と同水準の一致では kappa がほぼ 0 になる。"""
        confusion = np.array([[25, 25], [25, 25]])

        assert target.cohens_kappa(confusion) == pytest.approx(0.0)

    def test_empty_matrix_gives_zero(self) -> None:
        """総画素数 0 では 0 を返す（ゼロ除算しない）。"""
        assert target.cohens_kappa(np.zeros((2, 2), dtype=int)) == 0.0

    def test_single_class_matrix_gives_zero(self) -> None:
        """1クラスしか現れず偶然一致率が 1 の場合は 0 を返す。"""
        assert target.cohens_kappa(np.array([[10, 0], [0, 0]])) == 0.0


class TestSummarizeClasses:
    """summarize_classes のテスト。"""

    def test_computes_agreement_and_iou_per_class(self) -> None:
        """クラスごとに両基準の一致率と IoU を求める。"""
        # 共通クラス 1（水域）: GLC 10 画素・Esri 6 画素・一致 6 画素
        class_values = [1, 4]
        confusion = np.array([[6, 4], [0, 10]])

        results = target.summarize_classes(confusion, class_values)
        water = next(entry for entry in results if entry["common_class"] == 1)

        assert water["glc_pixels"] == 10
        assert water["esri_pixels"] == 6
        assert water["agreed_pixels"] == 6
        assert water["agreement_given_glc"] == pytest.approx(0.6)
        assert water["agreement_given_esri"] == pytest.approx(1.0)
        assert water["iou"] == pytest.approx(6 / 10)

    def test_absent_class_reports_none_instead_of_dividing_by_zero(self) -> None:
        """出現しないクラスは None を返す（ゼロ除算しない）。"""
        class_values = [1, 8]
        confusion = np.array([[10, 0], [0, 0]])

        results = target.summarize_classes(confusion, class_values)
        snow = next(entry for entry in results if entry["common_class"] == 8)

        assert snow["agreement_given_glc"] is None
        assert snow["iou"] is None

    def test_sorted_by_glc_pixels_descending(self) -> None:
        """GLC 画素数の降順で並ぶ。"""
        class_values = [1, 4]
        confusion = np.array([[1, 0], [0, 9]])

        results = target.summarize_classes(confusion, class_values)

        assert [entry["common_class"] for entry in results] == [4, 1]


class TestSaveConfusionCsv:
    """save_confusion_csv のテスト。"""

    def test_writes_labeled_matrix(self, tmp_path: Path) -> None:
        """行ラベル・列ヘッダつきで混同行列を書き出す。"""
        confusion_path = tmp_path / "confusion.csv"

        target.save_confusion_csv(np.array([[1, 2], [3, 4]]), [1, 4], confusion_path)

        with confusion_path.open(encoding="utf-8") as csv_file:
            rows = list(csv.reader(csv_file))

        assert rows[0][0] == "glc_common_class"
        assert rows[1][0].startswith("glc_1_")
        assert rows[1][1:] == ["1", "2"]
        assert rows[2][1:] == ["3", "4"]


class TestClassMappings:
    """クラス写像表そのものの整合性テスト。"""

    def test_all_glc_classes_are_mapped(self) -> None:
        """GLC の 35 クラスすべてに写像先がある（写像漏れを防ぐ）。"""
        from src.preprocessing.fetch_glc_fcs30d_hanoi import CLASS_LABELS as glc_labels

        assert set(glc_labels) == set(target.GLC_TO_COMMON)

    def test_all_valid_esri_classes_are_mapped(self) -> None:
        """Esri の有効クラスすべてに写像先がある（無効値は除く）。"""
        from src.preprocessing.fetch_esri_lulc_hanoi import CLASS_LABELS as esri_labels
        from src.preprocessing.fetch_esri_lulc_hanoi import FILLED_VALUES as esri_filled

        expected = set(esri_labels) - set(esri_filled)
        assert expected == set(target.ESRI_TO_COMMON)

    def test_mapping_targets_are_defined_common_classes(self) -> None:
        """写像先はすべて定義済みの共通クラスである。"""
        defined = set(target.COMMON_CLASS_LABELS)

        assert set(target.GLC_TO_COMMON.values()) <= defined
        assert set(target.ESRI_TO_COMMON.values()) <= defined

    def test_correspondence_covers_every_common_class(self) -> None:
        """対応表は共通クラスを網羅する。"""
        correspondence = target.build_class_correspondence()

        assert {entry["common_class"] for entry in correspondence} == set(
            target.COMMON_CLASS_LABELS
        )

    def test_correspondence_reports_one_to_many_for_cropland(self) -> None:
        """農地は GLC 側が 4 クラス・Esri 側が 1 クラスの多対1になる。"""
        correspondence = target.build_class_correspondence()
        cropland = next(
            entry for entry in correspondence if entry["common_class"] == target.COMMON_CROPLAND
        )

        assert len(cropland["glc_classes"]) == 4
        assert len(cropland["esri_classes"]) == 1
