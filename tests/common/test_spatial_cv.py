"""src/common/spatial_cv.py（cell_idベースの空間ブロックCV）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from src.common.spatial_cv import (
    assign_spatial_blocks,
    compute_block_cells,
    split_by_spatial_blocks,
)


class TestComputeBlockCells:
    """compute_block_cells のテスト。"""

    def test_converts_meters_to_cells(self) -> None:
        """既定値どおり2700m・30mスケールなら90セルになる。"""
        assert compute_block_cells(block_size_m=2700, scale=30) == 90

    def test_converts_at_different_scale(self) -> None:
        """スケールが変わってもメートル単位のブロックサイズは一致させられる。"""
        assert compute_block_cells(block_size_m=2700, scale=300) == 9

    def test_raises_when_not_divisible(self) -> None:
        """block_size_mがscaleの倍数でない場合は、黙って丸めず例外にする。"""
        with pytest.raises(ValueError, match="倍数"):
            compute_block_cells(block_size_m=1000, scale=30)

    def test_raises_when_block_size_is_zero(self) -> None:
        """block_size_mが0だとブロック定義が無意味になるため例外にする。"""
        with pytest.raises(ValueError, match="正の整数"):
            compute_block_cells(block_size_m=0, scale=30)

    def test_raises_when_scale_is_negative(self) -> None:
        """scaleが負値だとゼロ除算相当の不正な計算になるため例外にする。"""
        with pytest.raises(ValueError, match="正の整数"):
            compute_block_cells(block_size_m=2700, scale=-30)


class TestAssignSpatialBlocks:
    """assign_spatial_blocks のテスト。"""

    def test_same_block_cells_get_same_block_id(self) -> None:
        """同じブロックに属するセルは同じblock_idになる。"""
        row = np.array([0, 0, 1, 1])
        col = np.array([0, 1, 0, 1])

        block_id, info = assign_spatial_blocks(row, col, block_cells=2, block_id_stride=1000)

        assert np.all(block_id == block_id[0])
        assert info["n_blocks"] == 1

    def test_counts_distinct_non_empty_blocks(self) -> None:
        """非空ブロック数はデータが実在するブロックの種類数と一致する。"""
        row = np.array([0, 3, 3, 6])
        col = np.array([0, 0, 4, 4])

        block_id, info = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)

        assert info["n_blocks"] == 4
        assert len(np.unique(block_id)) == 4

    def test_block_id_is_unique_across_row_and_col(self) -> None:
        """block_row・block_colの異なる組み合わせが同一block_idに衝突しない
        （block_id_stride が十分に大きい前提）。"""
        row = np.array([0, 1])
        col = np.array([1, 0])

        block_id, _ = assign_spatial_blocks(row, col, block_cells=1, block_id_stride=1000)

        assert block_id[0] != block_id[1]

    def test_origin_is_absolute_not_data_dependent(self) -> None:
        """ブロック原点はデータの最小値ではなく絶対インデックスを基準にする。

        row_minを引いてから割ると (2,3) は同一ブロック（0,1 -> 両方 //3 = 0）に
        なってしまうが、絶対インデックスのまま割ると異なるブロックになる。
        この違いを直接検証することで、原点がデータ非依存であることを保証する。
        """
        row = np.array([2, 3])
        col = np.array([0, 0])

        block_id, info = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)

        assert block_id[0] != block_id[1]
        assert info["n_blocks"] == 2

    def test_same_relative_layout_at_different_absolute_offset_can_differ(self) -> None:
        """同じ相対配置でも絶対位置がずれるとブロック境界の跨ぎ方が変わりうる。

        原点をデータ非依存にした結果として、run間でブロック境界がずれないことの
        裏返しの性質（データ側のオフセットにブロック定義が引きずられないこと）を
        確認する。
        """
        row_a = np.array([0, 1])  # ブロック境界(3の倍数)を跨がない
        row_b = np.array([2, 3])  # ブロック境界を跨ぐ
        col = np.array([0, 0])

        block_id_a, _ = assign_spatial_blocks(row_a, col, block_cells=3, block_id_stride=1000)
        block_id_b, _ = assign_spatial_blocks(row_b, col, block_cells=3, block_id_stride=1000)

        assert block_id_a[0] == block_id_a[1]
        assert block_id_b[0] != block_id_b[1]

    def test_raises_when_block_id_stride_too_small(self) -> None:
        """block_id_strideがblock_colの範囲より小さいと桁が溢れて衝突するため例外にする。

        row=[0,1], col=[2,0], block_cells=1, block_id_stride=2 では、
        block_row=[0,1], block_col=[2,0] となり、block_id = [0*2+2, 1*2+0] = [2, 2]
        で本来別ブロックのはずの2点が同一block_idに衝突する（ガードが無ければ
        この衝突が例外なしで発生する）。
        """
        row = np.array([0, 1])
        col = np.array([2, 0])

        with pytest.raises(ValueError, match="block_id_stride"):
            assign_spatial_blocks(row, col, block_cells=1, block_id_stride=2)


class TestSplitBySpatialBlocks:
    """split_by_spatial_blocks のテスト。"""

    def test_same_block_never_split_across_train_and_test(self) -> None:
        """同一block_idのサンプルは常に同じfold（train/testのどちらか一方）に入る。"""
        block_id = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

        folds = split_by_spatial_blocks(block_id, n_splits=5)

        for train_idx, test_idx in folds:
            train_blocks = set(block_id[train_idx])
            test_blocks = set(block_id[test_idx])
            assert train_blocks.isdisjoint(test_blocks)

    def test_every_sample_appears_in_exactly_one_test_fold(self) -> None:
        """全サンプルがちょうど1回だけいずれかのfoldのtestに現れる。"""
        block_id = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

        folds = split_by_spatial_blocks(block_id, n_splits=5)

        all_test_indices = np.concatenate([test_idx for _, test_idx in folds])
        assert sorted(all_test_indices) == list(range(len(block_id)))
        assert len(all_test_indices) == len(set(all_test_indices))

    def test_returns_requested_number_of_folds(self) -> None:
        """n_splitsで指定した数だけfoldが生成される。"""
        block_id = np.array([0, 1, 2, 3, 4])

        folds = split_by_spatial_blocks(block_id, n_splits=5)

        assert len(folds) == 5

    def test_raises_when_n_splits_exceeds_block_count(self) -> None:
        """n_splitsが非空ブロック数を上回る場合は、英語の内部例外を伝播させず
        日本語で理由を明示する。"""
        block_id = np.array([0, 0, 1, 1])

        with pytest.raises(ValueError, match="非空ブロック数"):
            split_by_spatial_blocks(block_id, n_splits=5)
