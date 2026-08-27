"""ジオメトリ処理・ラスタ化・グリッドへの集約を扱うモジュール。"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
from pyproj import Transformer
from rasterio.enums import MergeAlg
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import box as shapely_box
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from src.common.geo_metadata import BBox

from .grid import GridSpec
from .io import LayerResource, iter_feature_records

try:
    from shapely import make_valid as shapely_make_valid
except Exception:  # pragma: no cover
    shapely_make_valid = None


def project_geometry_safe(
    geometry: dict[str, Any], to_analysis: Transformer
) -> BaseGeometry | None:
    """ジオメトリを安全に解析用CRSへ投影する。失敗時はNoneを返す。

    GeoJSON形式のジオメトリ辞書をshapelyオブジェクトへ変換し、不正な
    ジオメトリは ``make_valid`` で修復したうえで解析用CRSへ投影する。
    変換・修復・投影のいずれかで例外が発生した場合や、結果が空ジオメトリ
    になった場合は ``None`` を返し、呼び出し側でそのフィーチャをスキップ
    できるようにする。

    Args:
        geometry: フィーチャの ``geometry`` フィールド（GeoJSON形式の辞書）。
        to_analysis: 入力CRSから解析用CRSへの変換器。

    Returns:
        投影済みのshapelyジオメトリ。処理に失敗した場合は ``None``。
    """
    try:
        geom = shape(geometry)
    except Exception:
        return None

    if getattr(geom, "is_empty", False):
        return None

    try:
        is_valid = bool(getattr(geom, "is_valid", True))
    except Exception:
        return None

    if not is_valid and shapely_make_valid is not None:
        try:
            geom = shapely_make_valid(geom)
        except Exception:
            return None

    if getattr(geom, "is_empty", False):
        return None

    try:
        projected = shp_transform(to_analysis.transform, geom)
    except Exception:
        return None

    if getattr(projected, "is_empty", False):
        return None

    return projected


# ポリゴン系とみなすジオメトリ種別。1件ずつの判定（``geometry_is_polygon()``）と
# GeoSeries への一括判定の双方から参照し、判定基準が分岐しないようにする。
POLYGON_GEOM_TYPES = frozenset({"Polygon", "MultiPolygon"})


def geometry_is_polygon(projected_geom: Any) -> bool:
    """ポリゴン系ジオメトリかを判定する。

    Args:
        projected_geom: 判定対象のshapelyジオメトリ。

    Returns:
        ``Polygon`` または ``MultiPolygon`` であれば ``True``。
    """
    return projected_geom.geom_type in POLYGON_GEOM_TYPES


def geometry_is_line(projected_geom: Any) -> bool:
    """ライン系ジオメトリかを判定する。

    Args:
        projected_geom: 判定対象のshapelyジオメトリ。

    Returns:
        ``LineString`` または ``MultiLineString`` であれば ``True``。
    """
    return projected_geom.geom_type in {"LineString", "MultiLineString"}


def geometry_is_point(projected_geom: Any) -> bool:
    """ポイント系ジオメトリかを判定する。

    Args:
        projected_geom: 判定対象のshapelyジオメトリ。

    Returns:
        ``Point`` または ``MultiPoint`` であれば ``True``。
    """
    return projected_geom.geom_type in {"Point", "MultiPoint"}


def rasterize_binary_mask(
    geometries: Iterable[Any],
    out_shape: tuple[int, int],
    out_transform: Affine,
    chunk_size: int = 5000,
) -> np.ndarray:
    """ジオメトリ群を0/1マスクへラスタ化する。

    メモリ使用量を抑えるため、ジオメトリを ``chunk_size`` 件ずつまとめて
    ``rasterize`` を呼び出す。

    Args:
        geometries: ラスタ化対象のジオメトリ群（解析用CRS上）。
        out_shape: 出力マスクの形状 (行数, 列数)。
        out_transform: 出力マスクのアフィン変換（fineグリッド用）。
        chunk_size: 一度に ``rasterize`` へ渡すジオメトリ数。

    Returns:
        ジオメトリが存在するセルを1、それ以外を0とする ``uint8`` 配列。
    """
    out_array = np.zeros(out_shape, dtype=np.uint8)
    chunk: list[tuple[Any, int]] = []

    for geom in geometries:
        chunk.append((geom, 1))
        if len(chunk) >= chunk_size:
            rasterize(
                chunk,
                out=out_array,
                transform=out_transform,
                fill=0,
                default_value=1,
                dtype=np.uint8,
                merge_alg=MergeAlg.replace,
                all_touched=False,
            )
            chunk.clear()

    if chunk:
        rasterize(
            chunk,
            out=out_array,
            transform=out_transform,
            fill=0,
            default_value=1,
            dtype=np.uint8,
            merge_alg=MergeAlg.replace,
            all_touched=False,
        )

    return (out_array > 0).astype(np.uint8)


def rasterize_max_value_field(
    geometries: np.ndarray,
    values: np.ndarray,
    out_shape: tuple[int, int],
    out_transform: Affine,
    nodata: float,
    chunk_size: int = 5000,
) -> np.ndarray:
    """ジオメトリ群を属性値でfineグリッドへ焼き、重なりは最大値を残す。

    「値の昇順で渡すこと」を呼び出し側の義務にすると、忘れても例外が出ずに
    誤った値が返ってしまう（``rasterio`` 1.4.3で実測確認: 重なる2棟を降順に
    渡すと最大値ではなく最後に焼いた値が残る）。そのためソートは本関数の
    内部で行い、「最大値を焼く」という契約を関数名とシグネチャで表す。

    Args:
        geometries: ラスタ化対象のジオメトリ配列（解析用CRS上）。``(geom,
            value)`` のタプル列ではなく配列で受けることで、大量件数でも
            タプル生成のオーバーヘッドを避ける。
        values: 各ジオメトリの値配列（``geometries`` と同じ長さ）。非有限値
            （NaN・inf）の要素は焼かない。
        out_shape: 出力配列の形状 (行数, 列数)。
        out_transform: 出力配列のアフィン変換（fineグリッド用）。
        nodata: いずれのジオメトリにも覆われないセルに残す番兵値。
            ``values`` の値域の下限未満である必要がある（衝突すると
            未被覆セルと実データを区別できなくなる）。
        chunk_size: 一度に ``rasterize`` へ渡すジオメトリ数。

    Returns:
        セルを覆うジオメトリのうち最大の値を持つ ``float32`` 配列。
        いずれのジオメトリにも覆われないセルは ``nodata`` のまま残る。
    """
    values_array = np.asarray(values, dtype=np.float64)
    finite_mask = np.isfinite(values_array)
    finite_geometries = np.asarray(geometries, dtype=object)[finite_mask]
    finite_values = values_array[finite_mask]

    # 値の昇順に安定ソートしてから merge_alg=replace で焼くことで、
    # 後から焼いた（＝より大きい）値が残る。安定ソートでないと同値の
    # 要素の順序が入力ごとに変わりうる。チャンク分割をまたいでも順序が
    # 保たれるよう、ソートはチャンク分割の前に全体へ対して行う。
    order = np.argsort(finite_values, kind="stable")
    sorted_geometries = finite_geometries[order]
    sorted_values = finite_values[order]

    # fill は指定しない。out= を渡すと fill 引数は無視されることを
    # rasterio 1.4.3で実測確認しているため、事前充填で番兵値を敷く。
    out_array = np.full(out_shape, nodata, dtype=np.float32)
    chunk: list[tuple[Any, float]] = []

    for geom, value in zip(sorted_geometries, sorted_values):
        chunk.append((geom, float(value)))
        if len(chunk) >= chunk_size:
            rasterize(
                chunk,
                out=out_array,
                transform=out_transform,
                merge_alg=MergeAlg.replace,
                all_touched=False,
            )
            chunk.clear()

    if chunk:
        rasterize(
            chunk,
            out=out_array,
            transform=out_transform,
            merge_alg=MergeAlg.replace,
            all_touched=False,
        )

    return out_array


def aggregate_mean_max_from_fine_values(
    fine_values: np.ndarray,
    factor: int,
    nodata: float,
) -> tuple[np.ndarray, np.ndarray]:
    """fine値配列をcoarseへ平均・最大集約する。

    coarseセルごとに、値が入ったfineセル（``nodata`` でないセル）の平均と
    最大を返す。値が入ったfineセルが1つも無いcoarseセルは、平均・最大とも
    ``NaN`` とする。

    **入力の ``fine_values`` を破壊的に消費する。** 内部でin-place演算に
    よるクリップを行うため、呼び出し後に元の配列を集約前の値として
    再利用してはならない（``rasterize_max_value_field()`` の戻り値をそのまま
    渡し、以降参照しない使い方を前提とする）。

    Args:
        fine_values: fineグリッドの値配列 (行数, 列数)。``nodata`` で
            未被覆セルを表す。
        factor: coarse解像度がfine解像度の何倍かを示す整数。
        nodata: 未被覆セルを表す番兵値。``fine_values`` の値域の下限未満
            である必要がある。

    Returns:
        (平均, 最大) の組（いずれもcoarseグリッド形状の ``float32`` 配列）。
        値が入ったfineセルが1つも無いcoarseセルはいずれも ``NaN``。
    """
    rows, cols = fine_values.shape
    coarse_rows = rows // factor
    coarse_cols = cols // factor
    reshaped = fine_values.reshape(coarse_rows, factor, coarse_cols, factor)

    # 置換前に有効マスクを取る。置換後に「nodataより大きい」で数えると
    # 分母が全fineセル数になり、平均が過小になる。
    valid = reshaped > nodata
    counts = valid.sum(axis=(1, 3))

    # ブロック最大は置換前に取る。番兵値は値域の下限未満（関数の前提）で
    # 常に有効値より小さいため、未被覆セルが混ざっていても直接取れる。
    # 有効値が負の場合でも成り立つ（0以上を仮定しない）。
    maxima = reshaped.max(axis=(1, 3))

    # nodataセルだけを0.0へ置換する（in-place。このあと fine_values /
    # reshaped は書き換わる）。有効値は負でも変更しない。np.maximum() で
    # 全体を0以上にクリップすると、有効な負値まで0.0に化けて平均が誤る
    # ため使わない。np.where() で中間配列を作らないことで、fine解像度分の
    # メモリ増加を避ける。
    np.copyto(reshaped, 0.0, where=~valid)
    # 300mはfactor=30で1ブロック900要素になるため、float32累算の丸めを
    # 避けるためdtype=np.float64を明示する。
    sums = reshaped.sum(axis=(1, 3), dtype=np.float64)

    has_value = counts > 0
    mean_values = np.where(has_value, sums / np.maximum(counts, 1), np.nan)
    max_values = np.where(has_value, maxima, np.nan)
    return mean_values.astype(np.float32), max_values.astype(np.float32)


def iter_projected_geometries(
    resource: LayerResource,
    bbox_analysis: BBox,
    geometry_filter: Any,
) -> Iterable[Any]:
    """条件に合うジオメトリだけを逐次投影して返す。

    Args:
        resource: フィーチャを読み込む対象レイヤ。
        bbox_analysis: 解析用CRS上の検索範囲。
        geometry_filter: 投影済みジオメトリを受け取り、採用するかどうかを
            ``bool`` で返す判定関数（例: ``geometry_is_polygon``）。

    Yields:
        投影済みかつ ``geometry_filter`` を満たすジオメトリ。
    """
    for feature in iter_feature_records(resource, bbox_analysis):
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if geometry_filter(projected):
            yield projected


def aggregate_mean_from_fine_mask(fine_mask: np.ndarray, factor: int) -> np.ndarray:
    """fineマスクをcoarseへ平均集約し、被覆率を返す。

    Args:
        fine_mask: fineグリッドの0/1マスク (行数, 列数)。
        factor: coarse解像度がfine解像度の何倍かを示す整数。

    Returns:
        coarseグリッドへ平均集約した被覆率（0-1）。
    """
    rows, cols = fine_mask.shape
    coarse_rows = rows // factor
    coarse_cols = cols // factor
    reshaped = fine_mask.reshape(coarse_rows, factor, coarse_cols, factor)
    return reshaped.mean(axis=(1, 3)).astype(np.float32)


def aggregate_sum_from_fine_mask(fine_mask: np.ndarray, factor: int) -> np.ndarray:
    """fineマスクをcoarseへ合計集約する。

    Args:
        fine_mask: fineグリッドの0/1マスク (行数, 列数)。
        factor: coarse解像度がfine解像度の何倍かを示す整数。

    Returns:
        coarseグリッドへ合計集約した値（セルあたりの該当fineセル数）。
    """
    rows, cols = fine_mask.shape
    coarse_rows = rows // factor
    coarse_cols = cols // factor
    reshaped = fine_mask.reshape(coarse_rows, factor, coarse_cols, factor)
    return reshaped.sum(axis=(1, 3)).astype(np.float32)


def compute_polygon_coverage(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> np.ndarray:
    """ポリゴン系地物の被覆率（0-1）をcoarseグリッドで算出する。

    Args:
        resource: ポリゴンレイヤ。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) のポリゴン被覆率（0-1）。
    """
    fine_mask = rasterize_binary_mask(
        geometries=iter_projected_geometries(
            resource=resource,
            bbox_analysis=bbox_analysis,
            geometry_filter=geometry_is_polygon,
        ),
        out_shape=grid_spec.fine_shape,
        out_transform=grid_spec.fine_transform,
    )
    return aggregate_mean_from_fine_mask(fine_mask, grid_spec.factor)


def count_polygon_centroids(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> np.ndarray:
    """ポリゴン重心をcoarseセルへ割り当て、セルごとの件数を返す。

    Args:
        resource: ポリゴンレイヤ。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) のセルごとの重心数。
        範囲外の重心はカウントしない。
    """
    counts = np.zeros(grid_spec.coarse_shape, dtype=np.int32)
    inverse_transform = ~grid_spec.coarse_transform

    for feature in iter_feature_records(resource, bbox_analysis):
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if not geometry_is_polygon(projected):
            continue

        centroid = projected.centroid
        if getattr(centroid, "is_empty", False):
            continue

        col_f, row_f = inverse_transform * (centroid.x, centroid.y)
        col = int(math.floor(col_f))
        row = int(math.floor(row_f))

        if 0 <= row < grid_spec.coarse_shape[0] and 0 <= col < grid_spec.coarse_shape[1]:
            counts[row, col] += 1

    return counts.astype(np.float32)


def centroid_cell_indices(
    xs: np.ndarray,
    ys: np.ndarray,
    grid_spec: GridSpec,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """重心座標の配列から、属するcoarseセルの行・列添字を一括算出する。

    ``count_polygon_centroids()`` が1件ずつ行う「逆アフィン変換 → 切り捨て →
    範囲判定」と同じ処理を、NumPyのベクトル演算で一括に行う。件数が多い
    レイヤでの逐次処理のオーバーヘッドを避けるために用いる。

    Args:
        xs: 重心のX座標配列（解析用CRS上）。
        ys: 重心のY座標配列（解析用CRS上）。``xs`` と同じ形状であること。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        (行添字, 列添字, 有効マスク) の組。有効マスクは、座標が有限値で
        かつ添字がcoarseグリッドの範囲内である要素を ``True`` とする。
        マスクが ``False`` の要素の添字は意味を持たないため、集計前に
        マスクで絞り込む必要がある。

    Raises:
        ValueError: ``xs`` と ``ys`` の形状が一致しない場合。
    """
    x_array = np.asarray(xs, dtype=np.float64)
    y_array = np.asarray(ys, dtype=np.float64)
    if x_array.shape != y_array.shape:
        raise ValueError(
            f"xs と ys は同じ形状で指定してください: xs={x_array.shape}, ys={y_array.shape}"
        )

    # 非有限値は逆変換の前に0へ置換し、有効マスク側で除外する
    # （np.floor(nan) の整数変換が未定義になるのを避けるため）。
    finite_mask = np.isfinite(x_array) & np.isfinite(y_array)
    safe_x = np.where(finite_mask, x_array, 0.0)
    safe_y = np.where(finite_mask, y_array, 0.0)

    inverse_transform = ~grid_spec.coarse_transform
    col_float = inverse_transform.a * safe_x + inverse_transform.b * safe_y + inverse_transform.c
    row_float = inverse_transform.d * safe_x + inverse_transform.e * safe_y + inverse_transform.f

    rows = np.floor(row_float).astype(np.int64)
    cols = np.floor(col_float).astype(np.int64)

    n_rows, n_cols = grid_spec.coarse_shape
    inside_mask = finite_mask & (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
    return rows, cols, inside_mask


_CELL_EPS = 1e-9


def _coarse_cell_box(grid_spec: GridSpec, row: int, col: int) -> Any:
    """coarseセル1つ分の半開矩形ポリゴンを返す。

    右辺・上辺を微小量（``_CELL_EPS``）縮小することで、隣接セルとの
    共有境界上にあるラインが片側セルにのみ計上されるようにする。

    Args:
        grid_spec: fine/coarseグリッドの仕様。
        row: coarseグリッドの行インデックス。
        col: coarseグリッドの列インデックス。

    Returns:
        指定セルの半開矩形（右辺・上辺を ``_CELL_EPS`` 縮小済み）。
    """
    t = grid_spec.coarse_transform
    x0 = t.c + col * t.a
    x1 = t.c + (col + 1) * t.a
    y_top = t.f + row * t.e
    y_bot = t.f + (row + 1) * t.e
    x_min, x_max = min(x0, x1), max(x0, x1)
    y_min, y_max = min(y_bot, y_top), max(y_bot, y_top)
    return shapely_box(x_min, y_min, x_max - _CELL_EPS, y_max - _CELL_EPS)


def compute_line_length(
    resource: LayerResource,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
    feature_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> np.ndarray:
    """ライン系地物のセル内総延長（m/cell）を算出する。

    各ラインとcoarseセルポリゴンの ``intersection`` 長を合計することで、
    斜め線や同一セル内の複数道路も正確にカウントする。

    QGISの ``native:sumlinelengths`` との比較検証済み。ハノイ中心部のテスト
    領域（300mグリッド49セル）でセルごとの相対誤差はすべて1%未満（最大絶対
    誤差1.3cm）であり、算出結果は同等と確認されている。

    Args:
        resource: ラインレイヤ。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。
        feature_filter: フィーチャ辞書を受け取り、処理対象なら ``True`` を
            返す関数。``None`` の場合はすべてのライン地物を処理する。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) のセル内ライン総延長（m）。
    """
    length_array = np.zeros(grid_spec.coarse_shape, dtype=np.float64)
    rows, cols = grid_spec.coarse_shape
    inverse_transform = ~grid_spec.coarse_transform

    for feature in iter_feature_records(resource, bbox_analysis):
        if feature_filter is not None and not feature_filter(feature):
            continue
        projected = project_geometry_safe(feature["geometry"], resource.to_analysis)
        if projected is None:
            continue
        if not geometry_is_line(projected):
            continue

        bminx, bminy, bmaxx, bmaxy = projected.bounds
        c0, r0 = inverse_transform * (bminx, bmaxy)
        c1, r1 = inverse_transform * (bmaxx, bminy)

        r_start = max(0, int(math.floor(min(r0, r1) - _CELL_EPS)))
        r_end = min(rows, int(math.ceil(max(r0, r1) + _CELL_EPS)))
        c_start = max(0, int(math.floor(min(c0, c1) - _CELL_EPS)))
        c_end = min(cols, int(math.ceil(max(c0, c1) + _CELL_EPS)))

        for r in range(r_start, r_end):
            for c in range(c_start, c_end):
                cell_box = _coarse_cell_box(grid_spec, r, c)
                try:
                    isect = projected.intersection(cell_box)
                    if not isect.is_empty:
                        length_array[r, c] += isect.length
                except Exception as exc:
                    warnings.warn(
                        f"ライン intersection 失敗 (row={r}, col={c}): {exc}",
                        stacklevel=2,
                    )
                    continue

    return length_array.astype(np.float32)
