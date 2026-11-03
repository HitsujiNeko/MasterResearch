"""正準グリッド上で、物理的に等間隔な空間ブロックによるSpatial CV
（Group K-Fold）を構成する共通モジュール。

正準グリッドの row / col の絶対インデックスをブロックサイズ（セル数）で整数除算し、
ブロックIDを割り当てる。ブロック原点はデータに依存させない
（`(row - row_min) // block_cells` のような観測データ基準の原点を使わない）ことで、
しきい値・シナリオ・スケールを変えてもブロック境界とblock_idがずれないようにする。

`cell_id` のデコード（cell_id → row, col）はこのモジュールでは行わない。common層が
analysis層の `canonical_grid` モジュールへ依存しないようにするための意図的な分離
であり、呼び出し側（分析スクリプト）が `canonical_grid.split_cell_id()` でデコード
した row / col を渡す。同じ理由で、cell_idの桁送りに使う定数（`CELL_ID_STRIDE`）も
このモジュールでは持たず、`block_id_stride` として引数で受け取る。

`apply_spatial_buffer` は、作ったfoldの学習側から評価セルの近くのセルを除く
（緩衝帯）。ブロックサイズを広げたときの精度低下には、空間リークの除去と
保留域の拡大（空間的非定常性による外挿）の2つが混ざるため、ブロックサイズを
固定して緩衝帯だけを広げることで、前者を切り分けられるようにする。
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree
from sklearn.model_selection import GroupKFold


def compute_block_cells(block_size_m: int, scale: int) -> int:
    """ブロックサイズ（メートル）を1ブロックあたりのセル数に変換する。

    Args:
        block_size_m: ブロックの一辺の長さ（メートル）。
        scale: 正準グリッドの解像度（メートル/セル）。
    Returns:
        1ブロックあたりのセル数。
    Raises:
        ValueError: `block_size_m` または `scale` が0以下の場合（0以下だと
            ゼロ除算や無意味なブロック定義になるため）。`block_size_m` が
            `scale` の倍数でない場合。セル数指定にすると同じ既定値がスケール
            ごとに違う物理サイズになるため、メートル指定をセル数へ変換する
            時点で割り切れることを保証する。
    """
    if block_size_m <= 0 or scale <= 0:
        raise ValueError(
            f"block_size_mとscaleは正の整数である必要があります"
            f"（block_size_m={block_size_m}, scale={scale}）。"
        )
    if block_size_m % scale != 0:
        raise ValueError(
            f"block_size_m（{block_size_m}）はscale（{scale}）の倍数である必要があります。"
        )
    return block_size_m // scale


def assign_spatial_blocks(
    row: np.ndarray,
    col: np.ndarray,
    block_cells: int,
    block_id_stride: int,
) -> tuple[np.ndarray, dict[str, int]]:
    """row / col の絶対インデックスから物理的に等間隔な空間ブロックIDを割り当てる。

    Args:
        row: 正準グリッドの行インデックス（絶対インデックス。原点からのオフセットは
            適用しない）。
        col: 正準グリッドの列インデックス（絶対インデックス）。
        block_cells: 1ブロックあたりのセル数（`compute_block_cells` の戻り値）。
        block_id_stride: block_idの桁送りに使う乗数。cell_idの生成規則
            （`canonical_grid.make_cell_id`）の桁送り幅と揃えることで、
            block_row・block_colの組み合わせを一意なblock_idに変換する。
    Returns:
        block_id配列（サンプルと同じ長さ）と、
        `{"n_blocks": 非空ブロック数}` を含む統計情報の辞書。
        非空ブロック数は入力データが実際に存在するブロックの数であり、
        GroupKFoldの分割可否・fold当たりのサイズ均衡に効くのはこちらである
        （BBox全体のブロック数とは一致しない）。
    Raises:
        ValueError: block_col（`col // block_cells`）の最大値が `block_id_stride`
            以上になる場合。`block_row * block_id_stride + block_col` の桁が
            溢れてblock_row側と混ざり、本来別ブロックのセルが同一block_idに
            衝突しうるため（`canonical_grid.make_cell_id` のcol検証と同じ理由）。
    """
    block_row = row // block_cells
    block_col = col // block_cells

    if np.any(block_col >= block_id_stride):
        raise ValueError(
            f"block_col の最大値（{int(np.max(block_col))}）が block_id_stride"
            f"（{block_id_stride}）以上です。桁が溢れてblock_idが衝突するため、"
            "block_id_strideをより大きい値にしてください。"
        )

    block_id = block_row * block_id_stride + block_col

    info = {"n_blocks": int(np.unique(block_id).size)}
    return block_id, info


def split_by_spatial_blocks(
    block_id: np.ndarray, n_splits: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """空間ブロックIDでグループ化したGroup K-Foldのtrain/testインデックスを作る。

    同一ブロックに属するサンプルは常に同じfold（train または test の一方）に
    割り当てられるため、隣接セル間の空間自己相関によるリークをブロック単位で防ぐ。

    Args:
        block_id: 各サンプルが属する空間ブロックID（`assign_spatial_blocks` の戻り値）。
        n_splits: 分割数。
    Returns:
        (train_idx, test_idx) のタプルのリスト（fold順）。
    Raises:
        ValueError: `n_splits` が2未満、または非空ブロック数を上回る場合。
            前者はtrain/testに分割できず交差検証にならないため、後者は
            GroupKFoldがグループ数未満のfold数しか作れないためであり、
            いずれも英語の内部例外をそのまま伝播させず日本語で理由を明示する。
    """
    if n_splits < 2:
        raise ValueError(f"n_splitsは2以上である必要があります（n_splits={n_splits}）。")

    n_blocks = int(np.unique(block_id).size)
    if n_splits > n_blocks:
        raise ValueError(
            f"n_splits（{n_splits}）が非空ブロック数（{n_blocks}）を上回っています。"
            "ブロックサイズを小さくするか、n_splitsを減らしてください。"
        )

    # GroupKFold.split は特徴量行列の中身を使わず長さのみ参照するため、ダミー配列で足りる。
    dummy_features = np.zeros(len(block_id))
    splitter = GroupKFold(n_splits=n_splits)
    return list(splitter.split(dummy_features, groups=block_id))


def apply_spatial_buffer(
    folds: list[tuple[np.ndarray, np.ndarray]],
    row: np.ndarray,
    col: np.ndarray,
    scale: float,
    buffer_m: float,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[dict[str, int]]]:
    """各foldの学習側から、評価セルに近いセルを除いた緩衝帯付きのfoldを作る。

    ブロック境界をまたいで評価セルのすぐ隣に学習セルが残ると、空間自己相関に
    よって評価セルの値を「覗ける」（空間リーク）。評価セルまでの距離が
    ``buffer_m`` 未満の学習セルを除くことで、保留域の大きさ（ブロックサイズ）を
    変えずに、評価セルと学習セルの最短距離だけを広げる。

    距離はセル中心間のユークリッド距離（``row`` / ``col`` × ``scale``）。
    距離がちょうど ``buffer_m`` のセルは除かない。評価側（test）は変更しない。

    Args:
        folds: ``split_by_spatial_blocks`` の戻り値（(train_idx, test_idx) のリスト）。
        row: 正準グリッドの行インデックス（サンプル順）。
        col: 正準グリッドの列インデックス（サンプル順）。
        scale: 正準グリッドの解像度（メートル/セル）。
        buffer_m: 緩衝帯の幅（メートル）。0 なら ``folds`` と同じ分割を返す。
    Returns:
        緩衝帯を適用した (train_idx, test_idx) のリストと、foldごとの
        ``{"n_train_before", "n_train_after", "n_excluded", "n_test"}`` のリスト。
        学習セルの減少量を記録し、学習量の減少による精度低下と空間リークの
        除去による低下を区別できるようにする。
    Raises:
        ValueError: ``buffer_m`` が負、``scale`` が0以下の場合。緩衝帯の適用後に
            学習セルが0になるfoldがある場合（モデルを学習できないため、
            黙って空の学習集合を返さない）。
    """
    if buffer_m < 0:
        raise ValueError(f"buffer_mは0以上である必要があります（buffer_m={buffer_m}）。")
    if scale <= 0:
        raise ValueError(f"scaleは正の値である必要があります（scale={scale}）。")

    # x を列方向、y を行方向とするセル中心の座標（メートル）
    coords = np.column_stack((np.asarray(col, dtype=float), np.asarray(row, dtype=float)))
    coords *= scale

    buffered_folds = []
    fold_info = []
    for fold_no, (train_idx, test_idx) in enumerate(folds):
        if buffer_m == 0:
            keep = np.ones(len(train_idx), dtype=bool)
        else:
            # 上限を緩衝帯の幅にすると、それより遠い学習セルは探索せず inf が返る
            distance, _ = cKDTree(coords[test_idx]).query(
                coords[train_idx], k=1, distance_upper_bound=buffer_m
            )
            keep = ~(distance < buffer_m)
        kept_train_idx = train_idx[keep]
        if kept_train_idx.size == 0:
            raise ValueError(
                f"fold {fold_no} で緩衝帯（{buffer_m}m）の適用後に学習セルが0になりました。"
                "緩衝帯を狭めるか、ブロックサイズ・n_splitsを見直してください。"
            )
        buffered_folds.append((kept_train_idx, test_idx))
        fold_info.append(
            {
                "n_train_before": int(len(train_idx)),
                "n_train_after": int(kept_train_idx.size),
                "n_excluded": int(len(train_idx) - kept_train_idx.size),
                "n_test": int(len(test_idx)),
            }
        )
    return buffered_folds, fold_info
