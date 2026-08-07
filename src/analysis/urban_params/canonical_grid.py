"""全シナリオ・全スケールで共通の正準グリッドを定義するモジュール。

既存の ``grid.py``（``GridSpec`` / ``build_grid()``）は解析範囲レイヤのBBoxから
グリッド原点を取るため、シナリオが変わるとセルが揃わず比較できない。本モジュールは
原点を解析範囲から独立させ、後から解析範囲を広げても既存セルの ``cell_id`` が
変わらない「結合の土台」を提供する。``grid.py`` は既存出力の互換性のため残置しており、
本モジュールはその置き換えではなく追加である。

主な仕様:
    - 原点は座標系原点 ``(0.0, 0.0)`` を ``SNAP_UNIT_M``（900m）の倍数へ
      切り下げた点。900は 10 / 30 / 90 / 300m の最小公倍数であり、補助fineグリッド
      （10m）を含む全スケールの格子が原点で揃う。
    - ``row`` / ``col`` は原点からの絶対インデックス。解析範囲のBBoxは、出力する
      セルの ``row`` / ``col`` 範囲を決めるためだけに使う。
    - ``cell_id`` は ``row * CELL_ID_STRIDE + col``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer

from src.common.geo_metadata import BBox

# グリッド原点の基準座標（解析用CRS上）。解析範囲に依存させないための定数であり、
# 実際の原点は snap_origin() で SNAP_UNIT_M の倍数へ切り下げた値を使う。
GRID_ORIGIN_X_M = 0.0
GRID_ORIGIN_Y_M = 0.0

# 原点をスナップする単位（m）。10 / 30 / 90 / 300m の最小公倍数。
SNAP_UNIT_M = 900.0

# cell_id を組み立てる際の row の桁送り幅。col はこの値未満である必要がある。
CELL_ID_STRIDE = 1_000_000

# cell_id が int64 に収まる row の上限。これを超えると桁が溢れて負値になる。
CELL_ID_MAX_ROW = int((np.iinfo(np.int64).max - (CELL_ID_STRIDE - 1)) // CELL_ID_STRIDE)

# 親セル対応づけの基準スケール（m）と、対応づける親スケール（m）。
# 300 ÷ 90 が整数にならず入れ子にならないため、90m ↔ 300m は対応づけない。
PARENT_BASE_RES_M = 30.0
PARENT_SCALES = (90, 300)


@dataclass(frozen=True)
class CanonicalGridSpec:
    """正準グリッドの仕様を保持する。

    ``row`` は**北向きを正**とする。すなわち ``row`` が増えるほど北へ進む。
    ラスタの慣習（``rasterio.transform.from_origin()`` が作る、北から南へ増える
    row）とは向きが逆である点に注意する。原点固定・非負インデックス・スケール間の
    整数除算（``row_90 = row_30 // 3``）をいずれも素直に成立させるための選択である。

    Attributes:
        analysis_crs: 解析用CRS（投影座標系）。
        to_wgs84: ``analysis_crs`` からWGS84への変換器。
        res_m: セル1辺の長さ（m）。
        origin_x: グリッド原点のX座標（``analysis_crs`` 上）。
        origin_y: グリッド原点のY座標（``analysis_crs`` 上）。
        col_min: 出力対象の最小列インデックス。
        col_max: 出力対象の最大列インデックス（**この値を範囲に含む**）。
        row_min: 出力対象の最小行インデックス。
        row_max: 出力対象の最大行インデックス（**この値を範囲に含む**）。
    """

    analysis_crs: CRS
    to_wgs84: Transformer
    res_m: float
    origin_x: float
    origin_y: float
    col_min: int
    col_max: int
    row_min: int
    row_max: int

    @property
    def n_cols(self) -> int:
        """出力対象の列数を返す。"""
        return self.col_max - self.col_min + 1

    @property
    def n_rows(self) -> int:
        """出力対象の行数を返す。"""
        return self.row_max - self.row_min + 1

    @property
    def n_cells(self) -> int:
        """出力対象のセル総数（マスク適用前）を返す。"""
        return self.n_cols * self.n_rows


def snap_origin(value: float, snap_unit_m: float = SNAP_UNIT_M) -> float:
    """座標値を ``snap_unit_m`` の倍数へ切り下げる。

    切り上げ・四捨五入ではなく切り下げに固定するのは、原点を必ず対象範囲の
    外側（またはちょうど境界）に置き、非負のインデックスを保つためである。

    **原点定数が0である現状では、この関数は ``snap_unit_m`` の値によらず0を返す**
    （0は任意の正の単位の倍数であるため）。それでもスナップを実装として持つのは、
    将来CRSや原点定数を変えたときに自動的に効かせるためである。

    Args:
        value: スナップ対象の座標値（m）。
        snap_unit_m: スナップ単位（m）。正の値である必要がある。

    Returns:
        ``snap_unit_m`` の倍数へ切り下げた座標値。

    Raises:
        ValueError: ``snap_unit_m`` が正でない場合。
    """
    if snap_unit_m <= 0:
        raise ValueError("snap_unit_m は正の値で指定してください。")
    return math.floor(value / snap_unit_m) * snap_unit_m


def build_canonical_grid(
    bbox_analysis: BBox,
    analysis_crs: CRS,
    res_m: float,
    snap_unit_m: float = SNAP_UNIT_M,
) -> CanonicalGridSpec:
    """解析BBoxと解像度から正準グリッドの仕様を構築する。

    原点は ``bbox_analysis`` に依存せず、``GRID_ORIGIN_X_M`` / ``GRID_ORIGIN_Y_M``
    を ``snap_unit_m`` の倍数へ切り下げて決める。``bbox_analysis`` は出力対象の
    ``row`` / ``col`` 範囲を決めるためだけに使う。

    ``row`` / ``col`` の範囲は ``bbox_analysis`` を必ず覆う（境界にかかるセルを
    含める）ように決める。

    Args:
        bbox_analysis: 解析用CRS上の解析範囲BBox。
        analysis_crs: 解析用CRS（投影座標系）。
        res_m: セル1辺の長さ（m）。``snap_unit_m`` の約数である必要がある。
        snap_unit_m: 原点のスナップ単位（m）。原点定数が0である現状では原点を
            動かさず、``res_m`` の妥当性判定の基準としてのみ効く
            （``snap_origin()`` の説明を参照）。

    Returns:
        構築された正準グリッドの仕様。

    Raises:
        ValueError: ``analysis_crs`` が投影座標系でない場合、``res_m`` が正でない場合、
            ``res_m`` が ``snap_unit_m`` の約数でない場合、``bbox_analysis`` の
            幅・高さが正でない場合、または解析範囲のインデックスが ``cell_id`` の
            採番範囲（``make_cell_id()`` の制約）に収まらない場合。
    """
    # 解像度・原点スナップ単位をメートルとして扱うため、地理座標系（度単位）を
    # 渡されると res_m が「度」と解釈され、黙って無意味なグリッドができる。
    if not analysis_crs.is_projected:
        raise ValueError("analysis_crs には投影座標系（メートル単位）を指定してください。")
    if res_m <= 0:
        raise ValueError("res_m は正の値で指定してください。")
    if bbox_analysis.maxx <= bbox_analysis.minx or bbox_analysis.maxy <= bbox_analysis.miny:
        raise ValueError("bbox_analysis は正の幅・高さを持つ必要があります。")

    cells_per_snap_unit = snap_unit_m / res_m
    if abs(cells_per_snap_unit - round(cells_per_snap_unit)) > 1e-9:
        raise ValueError(
            f"res_m は snap_unit_m（{snap_unit_m}m）の約数で指定してください: res_m={res_m}"
        )

    origin_x = snap_origin(GRID_ORIGIN_X_M, snap_unit_m)
    origin_y = snap_origin(GRID_ORIGIN_Y_M, snap_unit_m)

    col_min = math.floor((bbox_analysis.minx - origin_x) / res_m)
    row_min = math.floor((bbox_analysis.miny - origin_y) / res_m)
    # 上端・右端がセル境界にちょうど載る場合に、幅ゼロの余分なセルを作らないよう
    # ceil から1を引く。境界にかかるセルは含める。
    col_max = max(math.ceil((bbox_analysis.maxx - origin_x) / res_m) - 1, col_min)
    row_max = max(math.ceil((bbox_analysis.maxy - origin_y) / res_m) - 1, row_min)

    # 採番できないインデックスは仕様構築の時点で弾く。セル生成まで進んでから
    # make_cell_id() で落ちると、原因が「解析CRSと解像度の組合せ」にあることを
    # 読み取りにくいためである。判定は make_cell_id() に委ね、範囲の定義を二重に持たない。
    try:
        make_cell_id(row_min, col_min)
        make_cell_id(row_max, col_max)
    except ValueError as error:
        raise ValueError(
            "解析範囲のインデックスが cell_id の採番範囲に収まりません。"
            " 解析CRSと解像度の組合せを見直してください"
            f"（row {row_min}-{row_max} / col {col_min}-{col_max}）: {error}"
        ) from error

    to_wgs84 = Transformer.from_crs(analysis_crs, CRS.from_epsg(4326), always_xy=True)
    return CanonicalGridSpec(
        analysis_crs=analysis_crs,
        to_wgs84=to_wgs84,
        res_m=float(res_m),
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        col_min=int(col_min),
        col_max=int(col_max),
        row_min=int(row_min),
        row_max=int(row_max),
    )


def make_cell_id(row: int | np.ndarray, col: int | np.ndarray) -> int | np.ndarray:
    """行・列インデックスから ``cell_id`` を採番する。

    ``cell_id`` は ``row * CELL_ID_STRIDE + col`` で求める。式を全スケール共通と
    しているため、**``cell_id`` が一意なのは同一スケールのレイヤ内に限られる**。
    30m の ``(row=7582, col=1765)`` と 300m の ``(row=7582, col=1765)`` は同じ
    ``cell_id`` になるため、複数スケールのパラメータテーブルを結合する際は
    ``cell_id`` 単独ではなく、スケールとの複合キーを使う必要がある。

    スカラーとNumPy配列の両方を受け付ける。数百万セル分の採番を1件ずつ行わずに
    済ませるためである。

    Args:
        row: 原点からの絶対行インデックス（北向きが正）。0以上
            ``CELL_ID_MAX_ROW`` 以下の整数である必要がある。
        col: 原点からの絶対列インデックス。0以上 ``CELL_ID_STRIDE`` 未満の
            整数である必要がある。

    Returns:
        ``cell_id``。入力がいずれもスカラーの場合は ``int``、
        それ以外は ``int64`` のNumPy配列。

    Raises:
        ValueError: ``row`` / ``col`` が整数でない場合、``col`` が0未満または
            ``CELL_ID_STRIDE`` 以上の場合（桁が溢れて ``row`` と混ざるため）、
            ``row`` が0未満の場合、または ``row`` が ``CELL_ID_MAX_ROW`` を
            超える場合（``cell_id`` がint64に収まらないため）。
    """
    row_array = np.asarray(row)
    col_array = np.asarray(col)

    # 浮動小数点数は int64 への変換で黙って切り捨てられ、誤った cell_id を
    # 例外なしで返してしまうため、型の時点で弾く。
    if not (
        np.issubdtype(row_array.dtype, np.integer) and np.issubdtype(col_array.dtype, np.integer)
    ):
        raise ValueError("row と col は整数で指定してください（小数は切り捨てられるため）。")

    row_array = row_array.astype(np.int64)
    col_array = col_array.astype(np.int64)

    if np.any(col_array < 0) or np.any(col_array >= CELL_ID_STRIDE):
        raise ValueError(f"col は 0 以上 {CELL_ID_STRIDE} 未満である必要があります。")
    if np.any(row_array < 0):
        raise ValueError("row は 0 以上である必要があります。")
    if np.any(row_array > CELL_ID_MAX_ROW):
        raise ValueError(f"row は {CELL_ID_MAX_ROW} 以下である必要があります。")

    cell_id = row_array * CELL_ID_STRIDE + col_array
    if np.ndim(row) == 0 and np.ndim(col) == 0:
        return int(cell_id)
    return cell_id


def split_cell_id(cell_id: int | np.ndarray) -> tuple[int, int] | tuple[np.ndarray, np.ndarray]:
    """``cell_id`` を行・列インデックスへ分解する。

    ``make_cell_id()`` の逆変換であり、往復して元の ``(row, col)`` に戻る。

    Args:
        cell_id: ``make_cell_id()`` で採番した ``cell_id``。スカラーと
            NumPy配列の両方を受け付ける。

    Returns:
        ``(row, col)`` の組。入力がスカラーの場合は ``int`` の組、
        それ以外は ``int64`` のNumPy配列の組。

    Raises:
        ValueError: ``cell_id`` が0未満の場合。``make_cell_id()`` は非負の
            ``cell_id`` しか生成しないため、負値は入力の誤りを意味する。
    """
    cell_id_array = np.asarray(cell_id, dtype=np.int64)
    if np.any(cell_id_array < 0):
        raise ValueError("cell_id は 0 以上である必要があります。")
    row = cell_id_array // CELL_ID_STRIDE
    col = cell_id_array % CELL_ID_STRIDE
    if np.ndim(cell_id) == 0:
        return int(row), int(col)
    return row, col
