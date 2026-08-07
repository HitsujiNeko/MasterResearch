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

実行例::

    python -m src.analysis.urban_params.canonical_grid --city hanoi
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import geopandas as gpd
import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from src.common.geo_metadata import BBox

from .config import CITY_CONFIG, PROJECT_ROOT
from .io import bbox_from_layer, get_layer_resource, read_layer_dataframe

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

# row / col 列の dtype と、そこに収まるインデックスの上限。
INDEX_DTYPE = np.int32
INDEX_MAX = int(np.iinfo(INDEX_DTYPE).max)

# 親セル対応づけの基準スケール（m）と、対応づける親スケール（m）。
# 300 ÷ 90 が整数にならず入れ子にならないため、90m ↔ 300m は対応づけない。
PARENT_BASE_RES_M = 30.0
PARENT_SCALES = (90, 300)

# 1ブロックあたりの行数の既定値。30mスケールではROI内でも約374万セルとなるため、
# 行ブロック単位で生成・書き出しを行いメモリ使用量を抑える。
DEFAULT_BLOCK_ROWS = 500


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


def is_supported_resolution(res_m: float, snap_unit_m: float = SNAP_UNIT_M) -> bool:
    """解像度が正準グリッドで扱えるか（``snap_unit_m`` の約数か）を返す。

    約数でない解像度は原点で格子が揃わず、スケール間の入れ子も成立しない。
    CLIの引数検証と ``build_canonical_grid()`` の双方から使い、判定を一箇所に保つ。

    Args:
        res_m: 判定するセル1辺の長さ（m）。
        snap_unit_m: 原点のスナップ単位（m）。

    Returns:
        正の値かつ ``snap_unit_m`` の約数であれば ``True``。
    """
    if res_m <= 0 or snap_unit_m <= 0:
        return False
    cells_per_snap_unit = snap_unit_m / res_m
    return abs(cells_per_snap_unit - round(cells_per_snap_unit)) <= 1e-9


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

    if not is_supported_resolution(res_m, snap_unit_m):
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
    # row / col の制約は軸ごとに独立で範囲も単調なため、両端の2点で必要十分である。
    try:
        make_cell_id(row_min, col_min)
        make_cell_id(row_max, col_max)
    except ValueError as error:
        raise ValueError(
            "解析範囲のインデックスが cell_id の採番範囲に収まりません。"
            " 解析CRSと解像度の組合せを見直してください"
            f"（row {row_min}-{row_max} / col {col_min}-{col_max}）: {error}"
        ) from error

    # row / col は INDEX_DTYPE で出力する。make_cell_id() が許す上限
    # （int64 基準）より狭いため、採番は通るのに属性列だけが黙って折り返す
    # 範囲が生じる。ここで併せて弾き、検証範囲と出力 dtype の辻褄を合わせる。
    if row_max > INDEX_MAX or col_max > INDEX_MAX:
        raise ValueError(
            f"解析範囲のインデックスが row / col 列の上限（{INDEX_MAX}）を超えます。"
            f" 解析CRSと解像度の組合せを見直してください（row {row_max} / col {col_max}）。"
        )

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
    # 例外なしで返してしまうため、型の時点で弾く。ただし空配列は要素が無く
    # 切り捨ても起きないため通す（np.asarray([]) の dtype は float64 になる）。
    if (row_array.size > 0 or col_array.size > 0) and not (
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
        ValueError: ``cell_id`` が整数でない場合（小数は切り捨てられるため）、
            または0未満の場合。``make_cell_id()`` は非負の整数 ``cell_id`` しか
            生成しないため、いずれも入力の誤りを意味する。
    """
    cell_id_array = np.asarray(cell_id)
    # make_cell_id() と同じ理由で小数を弾き、逆変換として非対称にならないようにする。
    if cell_id_array.size > 0 and not np.issubdtype(cell_id_array.dtype, np.integer):
        raise ValueError("cell_id は整数で指定してください（小数は切り捨てられるため）。")

    cell_id_array = cell_id_array.astype(np.int64)
    if np.any(cell_id_array < 0):
        raise ValueError("cell_id は 0 以上である必要があります。")
    row = cell_id_array // CELL_ID_STRIDE
    col = cell_id_array % CELL_ID_STRIDE
    if np.ndim(cell_id) == 0:
        return int(row), int(col)
    return row, col


def _parent_id_columns(rows: np.ndarray, cols: np.ndarray, res_m: float) -> dict[str, np.ndarray]:
    """基準スケールのセルに対する親セルの ``cell_id`` 列を作る。

    原点が全スケールで共通であるため、``row // factor`` / ``col // factor`` で
    得た親インデックスから採番した値は、親スケールのレイヤの ``cell_id`` と
    厳密に一致する。

    Args:
        rows: 基準スケールの行インデックス配列。
        cols: 基準スケールの列インデックス配列。
        res_m: 基準スケールのセル1辺の長さ（m）。

    Returns:
        ``parent_id_90`` / ``parent_id_300`` をキーとする配列の辞書。
    """
    columns: dict[str, np.ndarray] = {}
    for parent_scale in PARENT_SCALES:
        factor = int(round(parent_scale / res_m))
        columns[f"parent_id_{parent_scale}"] = make_cell_id(rows // factor, cols // factor)
    return columns


def _build_cell_frame(
    grid_spec: CanonicalGridSpec,
    row_indices: np.ndarray,
    col_indices: np.ndarray,
) -> gpd.GeoDataFrame:
    """行・列インデックスの直積からセルポリゴンのGeoDataFrameを作る。

    数百万セルを扱うため、ポリゴン生成（``shapely.box()``）と座標変換の双方を
    配列単位で行い、1セルずつのPythonループを避ける。

    Args:
        grid_spec: 正準グリッドの仕様。
        row_indices: 対象の行インデックス配列。
        col_indices: 対象の列インデックス配列。

    Returns:
        ``cell_id`` / ``row`` / ``col`` / ``lon`` / ``lat`` とセル矩形を持つ
        GeoDataFrame。``grid_spec`` の解像度が ``PARENT_BASE_RES_M`` と一致する
        場合は ``parent_id_90`` / ``parent_id_300`` も含む。
    """
    col_grid, row_grid = np.meshgrid(col_indices, row_indices)
    rows = row_grid.ravel()
    cols = col_grid.ravel()

    res_m = grid_spec.res_m
    min_x = grid_spec.origin_x + (cols * res_m)
    min_y = grid_spec.origin_y + (rows * res_m)
    geometries = shapely.box(min_x, min_y, min_x + res_m, min_y + res_m)

    half_res = res_m / 2.0
    center_lon, center_lat = grid_spec.to_wgs84.transform(min_x + half_res, min_y + half_res)

    data: dict[str, np.ndarray] = {
        "cell_id": make_cell_id(rows, cols),
        "row": rows.astype(INDEX_DTYPE),
        "col": cols.astype(INDEX_DTYPE),
        "lon": np.asarray(center_lon, dtype=np.float64),
        "lat": np.asarray(center_lat, dtype=np.float64),
    }
    # 親子対応は基準スケール（30m）にのみ持たせる。300 ÷ 90 が整数にならず
    # 入れ子にならないため、90m / 300m レイヤには親を持たせない。
    if math.isclose(res_m, PARENT_BASE_RES_M):
        data.update(_parent_id_columns(rows, cols, res_m))

    return gpd.GeoDataFrame(data, geometry=geometries, crs=grid_spec.analysis_crs)


def _filter_by_mask(cells: gpd.GeoDataFrame, mask_geometries: np.ndarray) -> gpd.GeoDataFrame:
    """マスクポリゴンと交差するセルだけを残す。

    判定は「セルとジオメトリの交差」であり、``run.py`` の ``IN_ANALYSIS_AREA``
    （10mピクセル中心がポリゴン内に入るかで判定）とは一致しない。角をわずかに
    かすめるセルは交差するが、ピクセル中心は1つも入らないためである。両者は
    「交差 ⊇ IN_ANALYSIS_AREA」の包含関係にあり、正準グリッドは結合の土台として
    取りこぼさない安全側を採る。

    **マスクとして機能するのは面ジオメトリを持つレイヤに限る。** 交差判定は線・点
    とも成立するため、測量GISのような線主体のレイヤを渡すと「範囲を面で切る」
    動作にならず、線上のセルだけが選ばれる。測量GISから分析対象域をどう定義するかは
    未決であり、それまでは面を持つレイヤ（現状はROI）を使う。詳細は設計正本を参照。

    Args:
        cells: 判定対象のセルを持つGeoDataFrame。
        mask_geometries: マスクポリゴンの配列（``cells`` と同じCRS）。

    Returns:
        いずれかのマスクポリゴンと交差するセルのみを残したGeoDataFrame。
    """
    if len(cells) == 0 or len(mask_geometries) == 0:
        return cells.iloc[0:0].reset_index(drop=True)

    # query() は (2, N) を返し、0行目がマスク側・1行目がセル側の位置を指す。
    # 複数のマスクポリゴンに跨るセルが重複するため一意化する。
    _, cell_positions = cells.sindex.query(mask_geometries, predicate="intersects")
    return cells.iloc[np.unique(cell_positions)].reset_index(drop=True)


def iter_cell_blocks(
    grid_spec: CanonicalGridSpec,
    block_rows: int = DEFAULT_BLOCK_ROWS,
    mask_geometries: np.ndarray | None = None,
) -> Iterator[gpd.GeoDataFrame]:
    """行ブロック単位でセルのGeoDataFrameを生成する。

    30mスケールではROI内でも約374万セルとなり、全セルを一度にメモリへ載せると
    負荷が大きい。行を ``block_rows`` 件ずつに区切って生成・マスク判定し、
    呼び出し側が逐次書き出せるようにする。

    **区切るのは行だけで、列は常に全幅を展開する。** したがって1ブロックのセル数は
    ``block_rows * grid_spec.n_cols`` であり、メモリ使用量は解析範囲の東西幅に
    比例する。既定値は東西幅の広い範囲や細かい解像度では大きくなりすぎるため、
    範囲を変えるときは実測しながら ``block_rows`` を調整する
    （ハノイROI・30mでは ``n_cols`` が約2,551で、既定500だと1ブロック約128万セル）。

    マスクを適用すると**空のブロックが生じうる**。ブロック数を ``block_rows`` と
    行数のみから決まる予測可能な値に保つため、空ブロックもそのまま返す。

    Args:
        grid_spec: 正準グリッドの仕様。
        block_rows: 1ブロックあたりの行数（セル数ではない。上記参照）。
        mask_geometries: マスクポリゴンの配列（``grid_spec.analysis_crs`` 上）。
            ``None`` の場合はBBox全体のセルを返す。

    Yields:
        ブロック1つ分のセルを持つGeoDataFrame。行インデックスの昇順に返す。

    Raises:
        ValueError: ``block_rows`` が正でない場合。
    """
    if block_rows <= 0:
        raise ValueError("block_rows は正の整数で指定してください。")

    col_indices = np.arange(grid_spec.col_min, grid_spec.col_max + 1, dtype=np.int64)
    for row_start in range(grid_spec.row_min, grid_spec.row_max + 1, block_rows):
        row_stop = min(row_start + block_rows - 1, grid_spec.row_max)
        row_indices = np.arange(row_start, row_stop + 1, dtype=np.int64)

        cells = _build_cell_frame(grid_spec, row_indices, col_indices)
        if mask_geometries is not None:
            cells = _filter_by_mask(cells, mask_geometries)
        yield cells


def write_grid_layers(
    bbox_analysis: BBox,
    analysis_crs: CRS,
    output_path: Path,
    scales: Sequence[int],
    mask_geometries: np.ndarray | None = None,
    block_rows: int = DEFAULT_BLOCK_ROWS,
    overwrite: bool = False,
) -> dict[str, int]:
    """各スケールの正準グリッドを1つのGeoPackageへレイヤとして書き出す。

    追記モードのまま再実行すると既存レイヤに行が積み増しされ ``cell_id`` の
    一意性が壊れるため、既存ファイルへの上書きは ``overwrite`` の明示を必須とする。

    **全スケールの仕様を構築し終えてからファイルへ触れる。** スケールごとに
    構築しながら書き出すと、不正なスケールが後ろにあった場合に手前のレイヤを
    書き終えてから失敗し、``overwrite`` 指定時は既存の正しい出力を消した後に
    半端なファイルだけが残る。``build_canonical_grid()`` は安価な純関数のため、
    先に全件を構築して検証を前倒しできる。

    Args:
        bbox_analysis: 出力対象のインデックス範囲を決める解析範囲BBox。
        analysis_crs: 解析用CRS（投影座標系）。
        output_path: 出力先のGeoPackageパス。
        scales: 出力するスケール（m）の一覧。レイヤ名は ``grid_{scale}m``。
        mask_geometries: マスクポリゴンの配列。``None`` の場合はBBox全体を出力する。
        block_rows: 1ブロックあたりの行数（セル数ではない。
            ``iter_cell_blocks()`` の説明を参照）。
        overwrite: ``True`` の場合、既存の出力ファイルを削除して作り直す。

    Returns:
        レイヤ名から書き出したセル数への辞書。

    Raises:
        ValueError: いずれかのスケールでグリッド仕様を構築できない場合、
            ``scales`` が空の場合、または書き出すセルが1件も無い場合
            （マスクとBBoxのCRSが食い違っている等、設定ミスの可能性が高いため）。
        FileExistsError: 出力ファイルが既に存在し ``overwrite`` が ``False`` の場合。
    """
    if not scales:
        raise ValueError("scales には少なくとも1つのスケールを指定してください。")

    # ファイルへ触れる前に全スケールを構築し、不正なスケールをここで検出する。
    grid_specs = {
        f"grid_{scale}m": build_canonical_grid(bbox_analysis, analysis_crs, float(scale))
        for scale in scales
    }
    for layer_name, grid_spec in grid_specs.items():
        print(
            f"[{layer_name}] 対象範囲: row {grid_spec.row_min}-{grid_spec.row_max} / "
            f"col {grid_spec.col_min}-{grid_spec.col_max}（最大 {grid_spec.n_cells:,} セル）",
            flush=True,
        )

    # 基準スケールのレイヤは parent_id を持つ。親スケールを同時に出力しないと
    # 参照先の無い値になるため警告する（出力自体は妨げない）。
    base_layer_name = f"grid_{int(PARENT_BASE_RES_M)}m"
    if base_layer_name in grid_specs:
        missing_parents = [
            f"grid_{parent_scale}m"
            for parent_scale in PARENT_SCALES
            if f"grid_{parent_scale}m" not in grid_specs
        ]
        if missing_parents:
            print(
                f"警告: {base_layer_name} の parent_id が指す"
                f" {' / '.join(missing_parents)} を同時に出力しません。"
                " 参照先の無い値になります。",
                flush=True,
            )

    if output_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"出力ファイルが既に存在します。作り直す場合は overwrite を指定してください: "
                f"{output_path}"
            )
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cell_counts: dict[str, int] = {}
    for layer_name, grid_spec in grid_specs.items():
        written = 0
        for block_index, cells in enumerate(
            iter_cell_blocks(grid_spec, block_rows, mask_geometries), start=1
        ):
            if len(cells) == 0:
                continue
            # 最初に書き出すブロックだけレイヤを作り直し、以降は追記する。
            # 空ブロックが先行しうるため、判定にはブロック番号ではなく書き出し実績を使う。
            cells.to_file(
                output_path,
                layer=layer_name,
                driver="GPKG",
                mode="w" if written == 0 else "a",
            )
            written += len(cells)
            # 30mスケールは数分かかるため、リダイレクト時もブロックごとに進捗が届くよう
            # 明示的にフラッシュする（既定のブロックバッファリングでは終了時までまとまる）。
            print(
                f"[{layer_name}] ブロック{block_index}まで完了: 累計 {written:,} セル",
                flush=True,
            )

        if written == 0:
            raise ValueError(
                f"{layer_name} に書き出すセルがありません。"
                f" マスクと解析範囲のCRS・位置関係を確認してください。"
            )
        cell_counts[layer_name] = written

    return cell_counts


def parse_arguments() -> argparse.Namespace:
    """CLI引数を解釈して返す。

    Returns:
        解釈済みの引数。``--scales`` は重複を除いた昇順の一覧に正規化する。
    """
    parser = argparse.ArgumentParser(
        description="正準グリッドの生成（cell_id 付きセルポリゴンのGeoPackage出力）"
    )
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[30, 90, 300],
        help="出力するスケール（m）の一覧。900の約数である必要がある。",
    )
    parser.add_argument(
        "--extent",
        default="mask",
        choices=["mask", "bbox"],
        help="mask: 解析範囲ポリゴンと交差するセルのみ出力する。bbox: BBox全体を出力する。",
    )
    # 有効な値は都市ごとに異なり、--city の解釈後でないと決まらないため
    # choices では列挙できない。候補はハードコードせず CITY_CONFIG から導き、
    # 解釈後に検証する（下部参照）。
    parser.add_argument(
        "--mask-layer-key",
        default="roi",
        help="解析範囲の基準レイヤ。CITY_CONFIG の layers のキーを指定する"
        "（例: roi / rg / cs）。BBoxと（--extent mask 時の）マスクの両方に使う。",
    )
    parser.add_argument(
        "--output",
        default="",
        help="出力先のGeoPackageパス。相対パスはプロジェクトルート基準。"
        " 既定は data/output/grid/grid_{city}.gpkg。",
    )
    parser.add_argument(
        "--block-rows",
        type=int,
        default=DEFAULT_BLOCK_ROWS,
        help="1ブロックあたりの行数（セル数ではない）。1ブロックのセル数は"
        " 行数×列数となり、列数は解析範囲の東西幅で決まる。小さくするとメモリ使用量が減る。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを削除して作り直す。",
    )

    args = parser.parse_args()
    if any(scale <= 0 for scale in args.scales):
        parser.error("--scales には正の整数のみ指定してください。")

    # 判定は is_supported_resolution() に委ね、約数の規則を二重に持たない。
    unsupported = [scale for scale in args.scales if not is_supported_resolution(float(scale))]
    if unsupported:
        parser.error(
            f"--scales には {SNAP_UNIT_M:.0f}m の約数のみ指定してください"
            f"（指定値: {', '.join(str(scale) for scale in unsupported)}）。"
        )

    if args.block_rows <= 0:
        parser.error("--block-rows には正の整数を指定してください。")

    # 候補は都市設定から導く。読み込み時にも実在確認は行われるが、そこまで進むと
    # トレースバックになり有効な候補も示されないため、CLIの段階で弾く。
    layer_keys = list(CITY_CONFIG[args.city]["layers"])
    if args.mask_layer_key not in layer_keys:
        parser.error(
            f"--mask-layer-key には {args.city} の layers のキーを指定してください"
            f"（指定値: {args.mask_layer_key} / 候補: {', '.join(layer_keys)}）"
        )

    args.scales = sorted(dict.fromkeys(args.scales))
    return args


def resolve_output_path(output_argument: str, city: str) -> Path:
    """CLIの ``--output`` から出力先の絶対パスを決める。

    Args:
        output_argument: ``--output`` の値。空文字の場合は既定パスを使う。
        city: 都市ID。既定パスのファイル名に使う。

    Returns:
        出力先の絶対パス。相対パスはプロジェクトルート基準で解決する。
    """
    if not output_argument:
        return PROJECT_ROOT / "data" / "output" / "grid" / f"grid_{city}.gpkg"

    output_path = Path(output_argument)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    return output_path


def _drop_zero_area_parts(geometry: BaseGeometry | None) -> BaseGeometry | None:
    """ジオメトリから面積を持たない部分（線・点）を取り除く。

    ``make_valid()`` は自己交差の形状によって ``GeometryCollection`` を返し、
    スパイク状のはみ出しが面積ゼロの線分として残ることがある。線分もセルと
    交差するため、そのまま使うと**実データがまったく無いセルまでマスクに
    入ってしまう**。面積を持つ部分だけを残してこれを防ぐ。

    Args:
        geometry: 判定対象のジオメトリ。

    Returns:
        面積を持つ部分のみのジオメトリ。面積を持つ部分が無ければ ``None``。
        ``GeometryCollection`` 以外はそのまま返す。
    """
    if geometry is None or geometry.geom_type != "GeometryCollection":
        return geometry

    areal_parts = [part for part in geometry.geoms if part.area > 0]
    if not areal_parts:
        return None
    return shapely.union_all(areal_parts)


def prepare_mask_geometries(geometries: gpd.GeoSeries) -> np.ndarray:
    """マスクポリゴンを交差判定に使える状態へ整える。

    NULLジオメトリを除き、不正ジオメトリは ``make_valid()`` で修復する。
    自己交差などの不正ポリゴンは交差判定で例外になりうるためである。ROIは整備済み
    だが、測量GIS（RG / CS）を基準レイヤに指定する経路では起こりうる。設計正本の
    「不正ジオメトリは make_valid を試行し、失敗時はスキップ」に従う。

    除外が発生した場合は件数を標準出力へ報告する。マスクが減れば解析範囲もその分
    狭まるため、有効域が黙って縮むのを避ける。

    Args:
        geometries: マスクレイヤのジオメトリ（解析用CRSへ投影済み）。

    Returns:
        交差判定に使えるジオメトリの配列。NULLと、修復しても空になったものは除く。
    """
    input_count = len(geometries)
    usable = geometries[geometries.notna()]

    invalid_count = int((~usable.is_valid).sum())
    if invalid_count > 0:
        # 既に妥当なジオメトリに対しては make_valid() は実質的な変更を加えない。
        usable = usable.make_valid()
        # 修復の副産物として残る面積ゼロの部分を落とす（下記関数の説明を参照）。
        usable = gpd.GeoSeries(
            [_drop_zero_area_parts(geometry) for geometry in usable],
            index=usable.index,
            crs=usable.crs,
        )
        print(f"不正なマスクジオメトリを修復しました: {invalid_count} 件", flush=True)

    usable = usable[usable.notna() & ~usable.is_empty]

    dropped_count = input_count - len(usable)
    if dropped_count > 0:
        print(
            f"マスクジオメトリを {dropped_count} 件除外しました"
            f"（NULLまたは修復不能。入力 {input_count} 件）。解析範囲がその分狭まります。",
            flush=True,
        )
    return usable.to_numpy()


def main() -> None:
    """正準グリッドを生成してGeoPackageへ出力する。

    CLI引数から都市・スケール・出力範囲を決定し、解析範囲レイヤからBBoxと
    （``--extent mask`` の場合は）マスクポリゴンを取得したうえで、スケールごとの
    レイヤをGeoPackageへ書き出す。
    """
    args = parse_arguments()
    city_cfg = CITY_CONFIG[args.city]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))

    mask_resource = get_layer_resource(city_cfg, args.mask_layer_key, analysis_crs)
    bbox_analysis = bbox_from_layer(mask_resource, analysis_crs)

    print("都市:", args.city)
    print("解析CRS:", analysis_crs.to_string())
    print(
        "解析範囲レイヤ:",
        args.mask_layer_key,
        "->",
        mask_resource.path.name,
        mask_resource.layer_name,
    )
    print("解析BBox:", bbox_analysis)
    print("出力範囲:", args.extent)

    mask_geometries: np.ndarray | None = None
    if args.extent == "mask":
        # 属性列は判定に使わないため、ジオメトリのみ読み込む。
        mask_gdf = read_layer_dataframe(mask_resource, columns=[])
        mask_geometries = prepare_mask_geometries(mask_gdf.geometry)
        print("マスクポリゴン数:", len(mask_geometries))

    output_path = resolve_output_path(args.output, args.city)
    cell_counts = write_grid_layers(
        bbox_analysis=bbox_analysis,
        analysis_crs=analysis_crs,
        output_path=output_path,
        scales=args.scales,
        mask_geometries=mask_geometries,
        block_rows=args.block_rows,
        overwrite=args.overwrite,
    )

    print("出力先:", output_path)
    for layer_name, cell_count in cell_counts.items():
        print(f"  {layer_name}: {cell_count:,} セル")


if __name__ == "__main__":
    main()
