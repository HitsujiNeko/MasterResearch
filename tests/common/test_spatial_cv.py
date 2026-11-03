"""src/common/spatial_cv.py（cell_idベースの空間ブロックCV）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from src.common.spatial_cv import (
    apply_spatial_buffer,
    assign_spatial_blocks,
    compute_block_cells,
    split_by_spatial_blocks,
    thin_training_folds,
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

    def test_raises_when_n_splits_is_less_than_two(self) -> None:
        """n_splitsが2未満だとtrain/testに分割できないため例外にする。"""
        block_id = np.array([0, 0, 1, 1, 2, 2])

        with pytest.raises(ValueError, match="2以上"):
            split_by_spatial_blocks(block_id, n_splits=1)


def _grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    """n×n の正準グリッドの row / col（サンプル順は行優先）を作る。"""
    row, col = np.divmod(np.arange(n * n), n)
    return row, col


class TestApplySpatialBuffer:
    """apply_spatial_buffer のテスト。"""

    def test_zero_buffer_returns_identical_folds(self) -> None:
        """緩衝帯0では既存のfoldと完全に一致する（既存ランとの互換）。"""
        row, col = _grid(12)
        block_id, _ = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)
        folds = split_by_spatial_blocks(block_id, n_splits=4)

        buffered, info = apply_spatial_buffer(folds, row, col, scale=30, buffer_m=0)

        for (train, test), (b_train, b_test) in zip(folds, buffered, strict=True):
            np.testing.assert_array_equal(b_train, train)
            np.testing.assert_array_equal(b_test, test)
        assert all(fold["n_excluded"] == 0 for fold in info)

    def test_excludes_cells_closer_than_buffer_and_keeps_exact_distance(self) -> None:
        """評価セルからの距離が緩衝帯未満の学習セルだけを除き、ちょうど等しいセルは残す。

        1行5セル（30m間隔）で中央を評価セルにし、緩衝帯60mを適用する。
        距離30mの隣接セルは除き、距離60mの両端は残す。
        """
        row = np.zeros(5, dtype=int)
        col = np.arange(5)
        folds = [(np.array([0, 1, 3, 4]), np.array([2]))]

        buffered, info = apply_spatial_buffer(folds, row, col, scale=30, buffer_m=60)

        np.testing.assert_array_equal(buffered[0][0], [0, 4])
        assert info[0] == {"n_train_before": 4, "n_train_after": 2, "n_excluded": 2, "n_test": 1}

    def test_uses_euclidean_distance_for_diagonal_cells(self) -> None:
        """斜め隣（30√2≈42.4m）は緩衝帯45mで除き、緩衝帯42mでは残す。"""
        row = np.array([0, 1])
        col = np.array([0, 1])
        folds = [(np.array([1]), np.array([0]))]

        with pytest.raises(ValueError, match="学習セルが0"):
            apply_spatial_buffer(folds, row, col, scale=30, buffer_m=45)
        buffered, _ = apply_spatial_buffer(folds, row, col, scale=30, buffer_m=42)
        np.testing.assert_array_equal(buffered[0][0], [1])

    def test_does_not_change_test_side_and_keeps_train_order(self) -> None:
        """評価側は変えず、学習側は元の順序を保った部分集合になる。"""
        row, col = _grid(12)
        block_id, _ = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)
        folds = split_by_spatial_blocks(block_id, n_splits=4)

        buffered, info = apply_spatial_buffer(folds, row, col, scale=30, buffer_m=61)

        for (train, test), (b_train, b_test), fold in zip(folds, buffered, info, strict=True):
            np.testing.assert_array_equal(b_test, test)
            np.testing.assert_array_equal(b_train, train[np.isin(train, b_train)])
            assert fold["n_train_after"] + fold["n_excluded"] == fold["n_train_before"]
            assert fold["n_excluded"] > 0
            # 残った学習セルはどの評価セルからも61m以上離れている
            d = np.hypot(
                (row[b_train, None] - row[None, b_test]) * 30,
                (col[b_train, None] - col[None, b_test]) * 30,
            )
            assert d.min() >= 61

    def test_raises_on_negative_buffer(self) -> None:
        """負の緩衝帯は意味を持たないため例外にする。"""
        with pytest.raises(ValueError, match="0以上"):
            apply_spatial_buffer([], np.array([]), np.array([]), scale=30, buffer_m=-1)

    def test_raises_on_non_positive_scale(self) -> None:
        """scaleが0以下だと距離を計算できないため例外にする。"""
        with pytest.raises(ValueError, match="正の値"):
            apply_spatial_buffer([], np.array([]), np.array([]), scale=0, buffer_m=30)


class TestThinTrainingFolds:
    """thin_training_folds のテスト。"""

    def test_thins_to_requested_sizes_keeping_order_and_test(self) -> None:
        """学習側を指定件数の順序を保った部分集合にし、評価側は変えない。"""
        row, col = _grid(12)
        block_id, _ = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)
        folds = split_by_spatial_blocks(block_id, n_splits=4)
        sizes = [len(train) // 2 for train, _ in folds]

        thinned, info = thin_training_folds(folds, sizes, seed=0)

        for (train, test), (t_train, t_test), size, fold in zip(
            folds, thinned, sizes, info, strict=True
        ):
            np.testing.assert_array_equal(t_test, test)
            assert len(t_train) == size
            np.testing.assert_array_equal(t_train, train[np.isin(train, t_train)])
            assert fold == {
                "n_train_before": len(train),
                "n_train_after": size,
                "n_excluded": len(train) - size,
                "n_test": len(test),
            }

    def test_is_reproducible_with_seed(self) -> None:
        """同じシードなら同じ間引きになる。"""
        folds = [(np.arange(10), np.array([10, 11]))]
        first, _ = thin_training_folds(folds, [4], seed=3)
        second, _ = thin_training_folds(folds, [4], seed=3)
        np.testing.assert_array_equal(first[0][0], second[0][0])

    def test_matches_buffer_sizes(self) -> None:
        """緩衝帯を適用したときの学習セル数に合わせた対照を作れる。"""
        row, col = _grid(12)
        block_id, _ = assign_spatial_blocks(row, col, block_cells=3, block_id_stride=1000)
        folds = split_by_spatial_blocks(block_id, n_splits=4)
        _, buffer_info = apply_spatial_buffer(folds, row, col, scale=30, buffer_m=61)

        _, info = thin_training_folds(
            folds, [fold["n_train_after"] for fold in buffer_info], seed=0
        )

        assert [fold["n_train_after"] for fold in info] == [
            fold["n_train_after"] for fold in buffer_info
        ]

    @pytest.mark.parametrize("size", [0, 11])
    def test_raises_on_invalid_size(self, size: int) -> None:
        """件数が1未満、または元の学習セル数を超える場合は例外にする。"""
        with pytest.raises(ValueError, match="以下である必要"):
            thin_training_folds([(np.arange(10), np.array([10]))], [size], seed=0)

    def test_raises_on_length_mismatch(self) -> None:
        """件数の指定がfold数と合わない場合は例外にする。"""
        with pytest.raises(ValueError, match="一致しません"):
            thin_training_folds([(np.arange(10), np.array([10]))], [5, 5], seed=0)
