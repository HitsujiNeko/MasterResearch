"""距離帯ごとの Moran's I（コレログラム）を算出する共通モジュール。

Spatial CV の out-of-fold 残差に空間構造が残っているか、どの距離まで残るかを
見るために使う。Moran's I と並べ替え検定は esda（``esda.Moran``）に任せ、
本モジュールは距離帯の空間重みの構築と結果の整形だけを担う。

距離帯は2種類を扱う。

- **輪帯**（``"ring"``）: ``lower <= 距離 < upper`` の点だけを近傍とする。
  「その距離での自己相関」を直接読め、セミバリオグラムのラグと対応する（主に使う）
- **累積**（``"cumulative"``）: ``0 < 距離 < upper`` の点をすべて近傍とする。
  ``libpysal.weights.DistanceBand`` と同じ考え方（新しい esda の correlogram と同じ
  定義）だが、遠い帯ほど近距離の寄与が混ざる。また、上端ちょうどの距離の点を
  含まない（DistanceBand は含む）点が異なる。輪帯と境界の扱いを揃えるためである

重みは二値で、esda の既定どおり行標準化して使う。近傍が1点も無い点（孤立点）は、
その距離帯の計算から除く（行標準化できず、Moran's I の分母だけに寄与して値を
歪めるため）。除いた数は結果に記録する。距離は座標の単位に従い、本研究では
投影座標系（m）の座標を渡す。

esda の並べ替え検定は numpy のグローバル乱数（``np.random``）を使うため、
本モジュールはシードを設定して呼び、呼び出し後に乱数の状態を元に戻す。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
from esda.moran import Moran
from libpysal.graph import Graph
from scipy.spatial import cKDTree

from src.common.spatial_points import validate_points

BAND_TYPES = ("ring", "cumulative")

# 並べ替え検定の回数の既定値（esda の既定と同じ）
DEFAULT_PERMUTATIONS = 999

# Moran's I を計算する最小点数（これ未満の距離帯は値を作らない）
MIN_POINTS = 3

CORRELOGRAM_COLUMNS = (
    "band_type",
    "lag_lower_m",
    "lag_upper_m",
    "n_points_used",
    "n_islands",
    "n_pairs",
    "mean_neighbors",
    "moran_i",
    "expected_i",
    "z_norm",
    "p_norm",
    "permutations",
    "z_sim",
    "p_sim",
)


def build_band_adjacency(coords: np.ndarray, lower_m: float, upper_m: float) -> sp.csr_matrix:
    """距離が ``lower_m`` 以上 ``upper_m`` 未満の点の組を1とする二値の隣接行列を作る。

    自分自身（対角）は含めない。``lower_m=0`` にすると累積の距離帯になる。

    Args:
        coords: 点の座標（形状 ``(n, 2)``）。
        lower_m: 距離帯の下端（含む）。
        upper_m: 距離帯の上端（含まない）。
    Returns:
        形状 ``(n, n)`` の対称な CSR 行列。
    Raises:
        ValueError: ``lower_m`` が負、または ``upper_m`` が ``lower_m`` 以下の場合。
    """
    if lower_m < 0 or upper_m <= lower_m:
        raise ValueError(
            f"0 <= lower_m < upper_m である必要があります（lower_m={lower_m}, upper_m={upper_m}）。"
        )
    tree = cKDTree(coords)
    pairs = tree.sparse_distance_matrix(tree, upper_m, output_type="coo_matrix")
    keep = (pairs.data >= lower_m) & (pairs.data < upper_m) & (pairs.row != pairs.col)
    n = coords.shape[0]
    return sp.csr_matrix(
        (np.ones(int(keep.sum())), (pairs.row[keep], pairs.col[keep])), shape=(n, n)
    )


def compute_band_moran(
    coords: np.ndarray,
    values: np.ndarray,
    lower_m: float,
    upper_m: float,
    permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = 0,
) -> dict:
    """1つの距離帯について、孤立点を除いた Moran's I と検定結果を求める。

    Args:
        coords: 点の座標（形状 ``(n, 2)``）。
        values: 各点の値（形状 ``(n,)``）。
        lower_m: 距離帯の下端（含む）。
        upper_m: 距離帯の上端（含まない）。
        permutations: 並べ替え検定の回数。0 なら並べ替え検定をしない。
        seed: 並べ替え検定の乱数シード。
    Returns:
        ``CORRELOGRAM_COLUMNS`` のうち ``band_type`` を除くキーを持つ辞書。
        孤立点を除いた点が ``MIN_POINTS`` 未満の場合、統計量は NaN。
        ``n_pairs`` は無向のペア数、``mean_neighbors`` は使用した点あたりの
        平均近傍数。並べ替え検定をしない場合 ``z_sim``・``p_sim`` は NaN。
    """
    coords, values = validate_points(coords, values)
    adjacency = build_band_adjacency(coords, lower_m, upper_m)
    has_neighbor = np.asarray(adjacency.sum(axis=1)).ravel() > 0
    # 近傍関係は対称なので、孤立点を除いた部分行列は残った点の近傍をすべて含む
    adjacency = adjacency[has_neighbor][:, has_neighbor]
    n_used = int(has_neighbor.sum())
    result = {
        "lag_lower_m": float(lower_m),
        "lag_upper_m": float(upper_m),
        "n_points_used": n_used,
        "n_islands": int((~has_neighbor).sum()),
        "n_pairs": int(adjacency.nnz // 2),
        "mean_neighbors": float(adjacency.nnz / n_used) if n_used else float("nan"),
        "moran_i": float("nan"),
        "expected_i": float("nan"),
        "z_norm": float("nan"),
        "p_norm": float("nan"),
        "permutations": int(permutations),
        "z_sim": float("nan"),
        "p_sim": float("nan"),
    }
    if n_used < MIN_POINTS:
        return result

    random_state = np.random.get_state()
    try:
        np.random.seed(seed)
        moran = Moran(
            values[has_neighbor],
            Graph.from_sparse(adjacency),
            transformation="r",
            permutations=permutations,
        )
    finally:
        np.random.set_state(random_state)

    result.update(
        {
            "moran_i": float(moran.I),
            "expected_i": float(moran.EI),
            "z_norm": float(moran.z_norm),
            "p_norm": float(moran.p_norm),
        }
    )
    if permutations:
        result.update({"z_sim": float(moran.z_sim), "p_sim": float(moran.p_sim)})
    return result


def compute_moran_correlogram(
    coords: np.ndarray,
    values: np.ndarray,
    lag_edges: np.ndarray,
    band_type: str = "ring",
    permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = 0,
) -> pd.DataFrame:
    """距離帯ごとの Moran's I（コレログラム）を表にする。

    Args:
        coords: 点の座標（形状 ``(n, 2)``。投影座標系）。
        values: 各点の値（例: out-of-fold 残差）。
        lag_edges: 距離帯の上端の配列（``semivariogram.build_lag_edges`` と同じ形式）。
        band_type: ``"ring"``（輪帯）または ``"cumulative"``（累積）。
        permutations: 並べ替え検定の回数。
        seed: 並べ替え検定の乱数シード（全距離帯で同じ値を使う）。
    Returns:
        ``CORRELOGRAM_COLUMNS`` の列を持つ DataFrame（1行1距離帯）。
    Raises:
        ValueError: ``band_type`` が ``BAND_TYPES`` に無い場合。
    """
    if band_type not in BAND_TYPES:
        raise ValueError(f"band_type は {BAND_TYPES} のいずれかです（指定値: {band_type}）。")
    upper_edges = np.asarray(lag_edges, dtype=float)
    if band_type == "ring":
        lower_edges = np.concatenate(([0.0], upper_edges[:-1]))
    else:
        lower_edges = np.zeros_like(upper_edges)
    rows = [
        {
            "band_type": band_type,
            **compute_band_moran(coords, values, lower, upper, permutations, seed),
        }
        for lower, upper in zip(lower_edges, upper_edges, strict=True)
    ]
    return pd.DataFrame(rows, columns=list(CORRELOGRAM_COLUMNS))
