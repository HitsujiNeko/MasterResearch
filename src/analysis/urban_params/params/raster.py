"""ラスタをグリッドへ集約するモジュール（衛星指標 NDVI/NDBI/NDWI と共通の集約基盤）。

セル平均と有効画素率の2列を対で出すパラメータ（標高・LST・人口密度・夜間光）は
``aggregate_mean_and_valid_ratio()`` を共通の入口として使う。
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds

from src.common.array_lookup import in_lookup_range

from ..grid import GridSpec


def _validate_band_index(src: rasterio.DatasetReader, band_index: int, raster_path: Path) -> None:
    """バンド番号がラスタの実在バンドの範囲内かを検証する。

    範囲外のまま処理を進めると、素の ``IndexError`` になり原因が読み取れない。

    Args:
        src: オープン済みのrasterioデータセット。
        band_index: 対象バンド番号（1始まり）。
        raster_path: 入力ラスタのパス（エラーメッセージに含める）。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    if not 1 <= band_index <= src.count:
        raise ValueError(
            f"バンド番号が範囲外です（このラスタのバンド数は {src.count}）:"
            f" band={band_index}, path={raster_path}"
        )


def _resolve_nodata(src: rasterio.DatasetReader, band_index: int) -> float | None:
    """対象バンドのnodata値を決定する。

    GEE出力ラスタは nodata タグが ``None`` でも ``NaN`` を実値として含むため、
    浮動小数型のラスタではタグが無い場合に ``NaN`` をnodataとみなす。

    nodataは ``src.nodata``（バンド1の値）ではなく ``src.nodatavals`` から対象
    バンドの値を取る。衛星指標ラスタは1ファイルに複数バンドを持ち、バンドごとに
    nodataが異なり得るため、バンド1の値で判定すると有効画素を誤って判定する。

    Args:
        src: オープン済みのrasterioデータセット。
        band_index: 対象バンド番号（1始まり）。

    Returns:
        nodata値。判定できない場合は ``None``（全画素を有効とみなす）。
    """
    nodata = src.nodatavals[band_index - 1]
    if nodata is None and np.issubdtype(src.dtypes[band_index - 1], np.floating):
        return float("nan")
    return nodata


def _valid_pixel_mask(band: np.ndarray, nodata: float | None) -> np.ndarray:
    """画素ごとの有効・無効を表す真偽値配列を返す。

    Args:
        band: 読み込み済みのバンド配列。
        nodata: nodata値（``None`` の場合は全画素を有効とみなす）。

    Returns:
        有効画素が ``True`` の真偽値配列。
    """
    if nodata is None:
        return np.ones(band.shape, dtype=bool)

    if np.isnan(nodata):
        return ~np.isnan(band)

    valid = band != nodata
    if np.issubdtype(band.dtype, np.floating):
        # nodataタグを持つラスタでも、実値としてNaNが混じることがある。
        valid &= ~np.isnan(band)
    return valid


def _prepare_reproject_source(
    src: rasterio.DatasetReader, band_index: int, nodata: float | None
) -> Any:
    """再投影の入力（バンド参照、または実値NaNをnodataへ寄せた配列）を返す。

    GDALは ``src_nodata`` に単一値しか取れないため、nodataタグが値（非NaN）の
    ラスタに実値NaNが混じると、NaNが欠損として扱われず平均へ伝播し、1画素でも
    NaNがあるとセル平均が丸ごとNaNになる。有効画素率側（``_valid_pixel_mask()``）
    は実値NaNを無効画素として数えるため、そのままでは「有効画素」の定義が両者で
    食い違う。NaNをnodata値へ寄せることで定義を揃える。

    Args:
        src: オープン済みのrasterioデータセット。
        band_index: 対象バンド番号（1始まり）。
        nodata: ``_resolve_nodata()`` が返したnodata値。

    Returns:
        寄せる必要が無い場合はバンド参照（GDAL側のストリーミング読み）、
        必要な場合は読み込み済みの配列。
    """
    if nodata is None or np.isnan(nodata):
        # nodataがNaNの場合、実値NaNはそのままnodataとして扱われる。
        return rasterio.band(src, band_index)
    if not np.issubdtype(src.dtypes[band_index - 1], np.floating):
        # 整数型ラスタは実値NaNを持ち得ない。
        return rasterio.band(src, band_index)

    band = src.read(band_index)
    nan_mask = np.isnan(band)
    if nan_mask.any():
        band[nan_mask] = nodata
    return band


def _reproject_binary_mask_to_grid(
    mask: np.ndarray,
    src_transform: Any,
    src_crs: Any,
    grid_spec: GridSpec,
) -> np.ndarray:
    """0.0/1.0の二値マスクを ``Resampling.average`` でcoarseグリッドへ再投影する。

    ``aggregate_valid_ratio_to_grid()``・``aggregate_class_fractions_to_grid()``
    の両方が同じ再投影パラメータ（``Resampling.average``・``init_dest_nodata=False``）
    を使うため、ここへ集約した。寄与する画素が1つも無いセルは、初期値0.0
    （＝マスクの割合0）のまま残る。

    Args:
        mask: 0.0/1.0の二値マスク（``float32``）。
        src_transform: 入力ラスタのアフィン変換。
        src_crs: 入力ラスタのCRS。
        grid_spec: 再投影先のグリッド仕様。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) へ平均再投影したマスクの
        割合配列（0-1）。
    """
    dst_array = np.zeros(grid_spec.coarse_shape, dtype=np.float32)
    reproject(
        source=mask,
        destination=dst_array,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=grid_spec.coarse_transform,
        dst_crs=grid_spec.analysis_crs,
        resampling=Resampling.average,
        # 寄与する画素が1つも無いセルは、初期値0.0（＝マスクの割合0）のまま残す。
        init_dest_nodata=False,
        num_threads=2,
    )
    return dst_array


def _warn_if_all_missing(
    raster_path: Path,
    grid_spec: GridSpec,
    kind_label: str,
    overlap_reason: str,
    no_overlap_reason: str,
) -> None:
    """全セルが欠測になった場合に、原因を切り分けてから警告する。

    「グリッドと重なっていない」（都市の取り違え・切り出し範囲の誤り）のか
    「重なってはいるが有効/写像画素が無い」（雲マスクによる全面欠測・nodata値の
    取り違え）のかで対処がまったく異なるため、``raster_overlaps_grid()`` で
    切り分けてから文言を選ぶ。``aggregate_mean_and_valid_ratio()`` と
    ``aggregate_class_fractions_to_grid()`` で同一だった分岐ロジックをここへ
    集約した。重なり判定はこの異常時にしか行わない（正常な入力ではラスタを
    開き直すコストが掛からないようにするため）。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 判定先のグリッド仕様。
        kind_label: 警告文に使う入力種別のラベル（例: ``DEM``・``土地被覆``）。
        overlap_reason: 「{kind_label}ラスタは解析グリッドと重なっていますが、」に
            続く詳細文（末尾は ``:`` で終える）。
        no_overlap_reason: 「{kind_label}ラスタが解析グリッドと重なりません。」に
            続く詳細文（末尾は ``:`` で終える）。
    """
    if raster_overlaps_grid(raster_path, grid_spec):
        warnings.warn(
            f"{kind_label}ラスタは解析グリッドと重なっていますが、{overlap_reason} {raster_path}",
            stacklevel=4,
        )
    else:
        warnings.warn(
            f"{kind_label}ラスタが解析グリッドと重なりません。{no_overlap_reason} {raster_path}",
            stacklevel=4,
        )


def aggregate_raster_to_grid(
    raster_path: Path, grid_spec: GridSpec, band_index: int = 1
) -> np.ndarray:
    """ラスタをcoarseグリッドへ平均再投影し、セル平均値を返す。

    平均はセル内の**有効画素のみ**で取る。そのため、セルの一部しかラスタに
    覆われていない場合でも、完全に覆われたセルと同じ実数が返る。両者を
    区別するには ``aggregate_valid_ratio_to_grid()`` を併用する。

    無効画素の判定は ``aggregate_valid_ratio_to_grid()`` と揃えており、
    nodataタグの値に加えて実値のNaNも欠損として扱う。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 再投影先のグリッド仕様（``coarse_transform``・``analysis_crs``を使用）。
        band_index: 読み込むバンド番号（1始まり）。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) へ平均再投影したセル値配列。
        入力ラスタのnodata・範囲外セルは ``NaN``。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    dst_array = np.full(grid_spec.coarse_shape, np.nan, dtype=np.float32)

    with rasterio.open(raster_path) as src:
        _validate_band_index(src, band_index, raster_path)
        nodata = _resolve_nodata(src, band_index)

        reproject(
            source=_prepare_reproject_source(src, band_index, nodata),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=grid_spec.coarse_transform,
            dst_crs=grid_spec.analysis_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
            init_dest_nodata=True,
            num_threads=2,
        )

    return dst_array.astype(np.float32)


def aggregate_valid_ratio_to_grid(
    raster_path: Path, grid_spec: GridSpec, band_index: int = 1
) -> np.ndarray:
    """coarseセルごとの有効画素率（0-1）を返す。

    ``aggregate_raster_to_grid()`` の平均は有効画素のみで取るため、セル内の
    有効画素が1割しか無い場合でも完全に覆われたセルと同じ実数を返す。両者を
    区別できるよう、セル面積に占める有効画素の割合を別列として算出する。

    算出は「有効画素を1・nodataを0とした配列」を平均再投影することで行う。
    そのため入力ラスタの**外周より外側**（画素が1つも無い領域）が占める分は
    比率に反映されない。ラスタの矩形範囲を一部しか含まないセルでは、実際の
    被覆より高い値になり得る。現行の入力（ROIでcrop済みのDEM）では、この
    影響を受けるのは解析BBox最外周のセルに限られる。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 再投影先のグリッド仕様（``coarse_transform``・``analysis_crs``を使用）。
        band_index: 読み込むバンド番号（1始まり）。

    Returns:
        coarseグリッド (``grid_spec.coarse_shape``) の有効画素率配列（0-1）。
        ラスタ範囲外のセルは ``0.0``（``NaN`` ではない）。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    with rasterio.open(raster_path) as src:
        _validate_band_index(src, band_index, raster_path)
        nodata = _resolve_nodata(src, band_index)
        valid_mask = _valid_pixel_mask(src.read(band_index), nodata).astype(np.float32)
        dst_array = _reproject_binary_mask_to_grid(valid_mask, src.transform, src.crs, grid_spec)

    # 平均再投影の丸め誤差で 0-1 をわずかに外れることがあるため、比率として丸める。
    return np.clip(dst_array, 0.0, 1.0)


def coarse_grid_bounds(grid_spec: GridSpec) -> tuple[float, float, float, float]:
    """coarseグリッド全体の範囲を解析用CRS上の ``(minx, miny, maxx, maxy)`` で返す。

    Args:
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        coarseグリッド全体の範囲。
    """
    rows, cols = grid_spec.coarse_shape
    transform = grid_spec.coarse_transform
    minx = transform.c
    maxy = transform.f
    # ``transform.e`` は負（北が上）のため、行数を掛けて足すと下端になる。
    return minx, maxy + (rows * transform.e), minx + (cols * transform.a), maxy


def raster_overlaps_grid(raster_path: Path, grid_spec: GridSpec) -> bool:
    """ラスタの範囲がcoarseグリッドの範囲と重なるかを判定する。

    **全セルが ``NaN`` になった原因の切り分けに使う。** 「ラスタがグリッドと重なって
    いない」（都市の取り違え・切り出し範囲の誤り）と「重なってはいるが有効画素が
    1つも無い」（雲マスクによる全面欠測・nodata値の取り違え）は、対処がまったく
    異なるにもかかわらず、どちらも全セル ``NaN`` という同じ結果になる。

    判定はラスタが記録している範囲（``src.bounds``）に基づき、画素値は読まない。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 判定先のグリッド仕様。

    Returns:
        範囲が重なる場合は ``True``。接するだけ（面積ゼロの共有）は ``False``。
    """
    with rasterio.open(raster_path) as src:
        # 地理座標系から投影座標系への変換では辺が曲がるため、辺上に点を足して
        # 範囲を評価する（既定の4隅だけだと重なりを取りこぼすことがある）。
        left, bottom, right, top = transform_bounds(
            src.crs, grid_spec.analysis_crs, *src.bounds, densify_pts=21
        )

    minx, miny, maxx, maxy = coarse_grid_bounds(grid_spec)
    return left < maxx and right > minx and bottom < maxy and top > miny


def warn_if_band_description_unexpected(
    raster_path: Path,
    band_index: int,
    expected: tuple[str, ...],
    kind_label: str,
    *,
    exact: bool = False,
) -> None:
    """バンド説明が期待するキーワードを含まない場合に警告する。

    **バンド番号の取り違えは黙って通る。** ファイルは存在し、範囲も重なり、有効画素も
    あるため、既存の警告経路はいずれも発火しない。それでいて出力される値は単位も意味も
    違う。人口ラスタは band 1 にカウント（人/セル）、band 2 に密度（人/km²）を持ち、
    カウントを集約しても密度として成立し得る大きさの値になるため、出力を眺めるだけでは
    誤りに気づけない。

    **バンド説明を持たないラスタでは何もしない。** 説明は任意のメタデータであり、
    無いことを異常として扱うと正常な入力まで警告で埋まる。照合は「説明があり、かつ
    期待と食い違う」場合に限る。未設定の説明が ``None`` で返るか空文字で返るかは
    ドライバに依存するため、**空白のみの説明も「説明が無い」として扱う**。

    受け付ける値を複数取れるようにしているのは、同じパラメータを別データセットから
    算出する場合に、正しいバンドの説明がデータセットごとに異なるためである（夜間光の
    主バンドは VIIRS DNB が ``avg_radiance``、Black Marble が ``ntl_near_nadir`` で
    共通語を持たない）。**いずれか1つに合致すれば正常とみなす。**

    照合方法は用途で選ぶ。

    - 部分一致（既定）: 同じ語を含む別バンドが存在しない場合に使う。説明の表記揺れや
      データセット追加に強い。人口は ``population_density_per_km2`` に対し ``density``
      で照合しており、将来ほかの人口グリッドを追加しても語が残れば通る。
    - 完全一致（``exact=True``）: **紛らわしい兄弟バンドが同じ語を含む場合に使う。**
      夜間光の ``avg_radiance_masked`` ・ ``max_radiance`` ・ ``ntl_all_angle`` は
      いずれも主バンドと語を共有し、値の大きさも近いため、部分一致では取り違えを
      検知できない。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        band_index: 対象バンド番号（1始まり）。
        expected: 受理するバンド説明の候補（大文字小文字は区別しない）。``exact`` が
            ``False`` なら説明に含まれるべき語として、``True`` なら説明全体と一致
            すべき名前として扱う。
        kind_label: 警告文に使う入力種別のラベル（例: ``人口``）。
        exact: ``True`` なら完全一致で照合する。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    with rasterio.open(raster_path) as src:
        _validate_band_index(src, band_index, raster_path)
        description = src.descriptions[band_index - 1]

    lowered = "" if description is None else str(description).strip().lower()
    # 空文字・空白のみの説明は「説明が無い」と同じに扱う。未設定のバンド説明を
    # ``None`` ではなく空文字で返すドライバがあり、ここで弾かないと候補のどれにも
    # 一致せず、正常な入力に対して警告が出る。
    if not lowered:
        return

    accepted = [item.lower() for item in expected]
    if exact:
        matched = lowered in accepted
    else:
        matched = any(item in lowered for item in accepted)
    if matched:
        return

    listed = " / ".join(f"'{item}'" for item in expected)
    # 候補が1件でも複数でも自然に読める文面にする（「いずれも」は1件だと不自然）。
    if exact:
        relation = f"期待するバンド説明（{listed}）と一致しません"
    else:
        relation = f"期待する語（{listed}）を含みません"
    warnings.warn(
        f"{kind_label}ラスタの band {band_index} の説明は '{description}' であり、"
        f" {relation}。バンド番号の取り違えを疑って"
        "ください。値は出力されますが、意味と単位が想定と異なります:"
        f" {raster_path}",
        stacklevel=3,
    )


def aggregate_mean_and_valid_ratio(
    raster_path: Path,
    grid_spec: GridSpec,
    band_index: int,
    mean_column: str,
    ratio_column: str,
    kind_label: str,
) -> dict[str, np.ndarray]:
    """セル平均値とセル内有効画素率の2列を対で算出する。

    標高（``ELEV_MEAN`` / ``ELEV_VALID_RATIO``）・LST（``LST`` / ``LST_VALID_RATIO``）・
    人口密度（``POP_DEN_*`` / ``POP_VALID_RATIO_*``）・
    夜間光（``NTL_MEAN`` / ``NTL_VALID_RATIO``）は
    集約の手順が同一のため、ここへ集約する。**平均はセル内の有効画素のみで取るため、
    セルの一部しか覆われていなくても値は ``NaN`` にならない。** セルの信頼度は
    有効画素率の列で判断する。``NaN`` の件数だけでは部分被覆のセルを捕捉できず、
    有効カバレッジを過大評価する。

    全セルが ``NaN`` になった場合は警告する。ファイルが存在する以上、入力解決は
    素通りし、列が残ったまま中身だけが空になるため欠損に気づきにくい。**原因が
    「グリッドと重なっていない」のか「重なってはいるが有効画素が無い」のかで対処が
    まったく異なる**ため、``raster_overlaps_grid()`` で切り分けてから文言を選ぶ。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 集約先のグリッド仕様。
        band_index: 読み込むバンド番号（1始まり）。
        mean_column: セル平均値の列名（例: ``ELEV_MEAN``）。
        ratio_column: 有効画素率の列名（例: ``ELEV_VALID_RATIO``）。
        kind_label: 警告文に使う入力種別のラベル（例: ``DEM``）。

    Returns:
        ``{mean_column: array, ratio_column: array}`` 形式の辞書。有効画素率は
        0-1で、ラスタ範囲外のセルは ``0.0``（``NaN`` ではない）。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    mean_values = aggregate_raster_to_grid(raster_path, grid_spec, band_index)
    valid_ratio = aggregate_valid_ratio_to_grid(raster_path, grid_spec, band_index)

    if not np.isfinite(mean_values).any():
        _warn_if_all_missing(
            raster_path,
            grid_spec,
            kind_label,
            f"有効画素が1つもありません。{mean_column} 列は全セルNaNになります。全面が雲マスク等で"
            " 欠測している観測か、nodata値の取り違えを疑ってください:",
            f"{mean_column} 列は全セルNaNになります。都市の取り違え・切り出し範囲の誤りを疑って"
            "ください:",
        )

    return {mean_column: mean_values, ratio_column: valid_ratio}


# raster_path・band_index・class_lookupの組が同じ呼び出しでは、画素値→共通クラスID
# への写像結果（grid_specに依存しない部分）を使い回す。土地被覆パラメータは
# 30/90/300mの3スケールを同じプロセス内で順に算出するため、キャッシュが無いと
# 同じラスタの全画素読み込み・nodata判定・写像をスケール数だけ繰り返してしまう
# （ベクタレイヤ向けの ``io.layer_cache()`` に相当する、ラスタ読み込み側のキャッシュ）。
_class_mapping_cache: dict[tuple[str, int, bytes], tuple[np.ndarray, Any, Any]] = {}


def _map_raster_to_common_classes(
    raster_path: Path, band_index: int, class_lookup: np.ndarray
) -> tuple[np.ndarray, Any, Any]:
    """ラスタを読み込み、画素値を共通クラスIDへ写像した配列を返す。

    結果は ``_class_mapping_cache`` に保持し、同じ ``raster_path``・``band_index``・
    ``class_lookup`` の組で再度呼ばれた場合はラスタを開き直さない。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        band_index: 読み込むバンド番号（1始まり）。
        class_lookup: 画素値から共通クラスIDへの添字表。

    Returns:
        ``(共通クラスID配列, 入力ラスタのアフィン変換, 入力ラスタのCRS)`` のタプル。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合。
    """
    cache_key = (str(raster_path), band_index, class_lookup.tobytes())
    cached = _class_mapping_cache.get(cache_key)
    if cached is not None:
        return cached

    with rasterio.open(raster_path) as src:
        _validate_band_index(src, band_index, raster_path)
        nodata = _resolve_nodata(src, band_index)
        band = src.read(band_index)
        src_transform = src.transform
        src_crs = src.crs

    valid_mask = _valid_pixel_mask(band, nodata)
    mappable = valid_mask & in_lookup_range(band, class_lookup.size)

    common = np.zeros(band.shape, dtype=np.uint8)
    common[mappable] = class_lookup[band[mappable]]
    # band・valid_mask・mappableは共通クラス配列への写像が済めば不要になる。
    # 入力ラスタと同サイズの配列（Esriで各約70MB）を早期に解放し、以降の
    # ループ中のピークメモリへ積み上げないようにする。
    del band, valid_mask, mappable

    result = (common, src_transform, src_crs)
    _class_mapping_cache[cache_key] = result
    return result


def aggregate_class_fractions_to_grid(
    raster_path: Path,
    grid_spec: GridSpec,
    band_index: int,
    class_lookup: np.ndarray,
    class_values: Sequence[int],
    kind_label: str,
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """カテゴリラスタ（土地被覆等）をクラス別面積率へ集約する。

    クラスごとに二値マスク（当該クラスへ写像される画素を1、それ以外を0とした
    ``float32`` 配列）を1クラスずつ作り、``aggregate_valid_ratio_to_grid()`` と
    同じ ``Resampling.average``・``init_dest_nodata=False`` で coarse グリッドへ
    再投影する。得られる値は「セル内の全寄与画素に占める当該クラスの割合」であり、
    ``class_values`` 全クラス分を合計すると「``class_values`` のいずれかへ写像
    される画素の割合」（``fraction_sum``）になる。出力の面積率は ``fraction_sum``
    （クリップ前の値）を分母として正規化するため、有効セルでの合計は構成として
    厳密に1になる（float32の丸めは残るため、呼び出し側の検証は ``np.isclose`` で
    行うこと）。クリップ後の値を分母にすると、丸め誤差で総和が1をわずかに超えた
    セルだけ分母が1.0へ切り詰められ、合計が1を超えてしまうため使わない。

    **7クラス分のマスクを同時に保持しない。** 大きなラスタ（Esri: 約6,980万画素）
    で float32 マスクを7枚同時に持つと約1.95 GBに達し、これ自体がメモリの
    ピークになる。1クラスずつ生成・再投影してから破棄することで、ピークを
    共通クラス配列（uint8）＋マスク1枚＋coarse出力配列に抑える。同じ理由で、
    画素値から共通クラスIDへの写像も添字表引きで1回に畳み、以降はスカラ比較
    （``common == class_value``）で済ませる。

    nodata画素は「共通クラス配列でIDを0（``COMMON_INVALID`` 相当）にする」
    ことで全マスクから除外する。``reproject()`` に ``src_nodata`` を渡さない
    のは、渡すとクラスごとに寄与画素の集合が変わり、``fraction_sum`` を分母に
    した「和が1」という性質が崩れるためである
    （``aggregate_valid_ratio_to_grid()`` が ``src_nodata`` を渡さないのも同じ
    理由による）。

    **ラスタの読み込み・写像は ``_map_raster_to_common_classes()`` がキャッシュ
    する。** 土地被覆パラメータは同じプロセス内で複数スケール（例: 30/90/300m）
    を順に算出するため、``raster_path``・``band_index``・``class_lookup`` の組が
    同じ呼び出しでは、ラスタを開き直さず前回の写像結果を使い回す。

    全セルが欠測になった場合は警告する。判定は ``(fraction_sum > 0).any()`` が
    偽であることとし、``aggregate_mean_and_valid_ratio()`` と同様に
    ``raster_overlaps_grid()`` で「グリッドと重なっていない」のか「重なっては
    いるが写像できる画素が無い」のかを切り分けてから文言を選ぶ。

    Args:
        raster_path: 入力ラスタファイルの絶対パス。
        grid_spec: 集約先のグリッド仕様。
        band_index: 読み込むバンド番号（1始まり）。
        class_lookup: 画素値から共通クラスIDへの添字表（呼び出し元が構築して
            渡す。本関数は添字表を引くだけで、写像表そのものには依存しない）。
        class_values: 出力する共通クラスID（対応する列を持たせたいクラスのみ。
            例: 雪氷を除く7クラス）。重複を含めてはならない（含めると
            ``fraction_sum`` が二重計上され、正規化後の全クラスの面積率が
            縮小する）。
        kind_label: 警告文に使う入力種別のラベル（例: ``土地被覆``）。

    Returns:
        ``(正規化済みクラス別面積率, 有効画素率)`` のタプル。
        - 正規化済みクラス別面積率: ``{共通クラスID: 配列}``。写像できる画素が
          1つも無いセルは ``NaN``。
        - 有効画素率: 0-1にクリップした ``fraction_sum``。ラスタ範囲外・写像
          画素が無いセルは ``0.0``（``NaN`` ではない）。

    Raises:
        ValueError: ``band_index`` がラスタのバンド数の範囲外の場合、または
            ``class_values`` に重複がある場合。
    """
    if len(class_values) != len(set(class_values)):
        raise ValueError(
            "class_values に重複した共通クラスIDが含まれています（fraction_sum が"
            f"二重計上され、正規化後の面積率が壊れるため禁止する）: {list(class_values)}"
        )

    common, src_transform, src_crs = _map_raster_to_common_classes(
        raster_path, band_index, class_lookup
    )

    fraction_sum = np.zeros(grid_spec.coarse_shape, dtype=np.float32)
    raw_fractions: dict[int, np.ndarray] = {}
    for class_value in class_values:
        class_mask = (common == class_value).astype(np.float32)
        dst_array = _reproject_binary_mask_to_grid(class_mask, src_transform, src_crs, grid_spec)
        raw_fractions[class_value] = dst_array
        fraction_sum += dst_array

    valid_ratio = np.clip(fraction_sum, 0.0, 1.0)

    normalized_fractions: dict[int, np.ndarray] = {}
    for class_value, fraction in raw_fractions.items():
        normalized_fractions[class_value] = np.divide(
            fraction,
            fraction_sum,
            out=np.full(grid_spec.coarse_shape, np.nan, dtype=np.float32),
            where=fraction_sum > 0,
        )

    if not (fraction_sum > 0).any():
        _warn_if_all_missing(
            raster_path,
            grid_spec,
            kind_label,
            "対象クラスへ写像できる画素が1つもありません。各クラスの面積率列は全セルNaNに"
            "なります。nodata値・写像表の取り違えを疑ってください:",
            "各クラスの面積率列は全セルNaNになります。都市の取り違え・切り出し範囲の誤りを"
            "疑ってください:",
        )

    return normalized_fractions, valid_ratio


def compute(
    raster_resources: dict[str, tuple[Path, int]],
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """検出済みの衛星指標ラスタをcoarseグリッドへ集約する。

    Args:
        raster_resources: ``io.find_satellite_rasters`` で検出した
            指標名（NDVI/NDBI/NDWI）からラスタパスとバンド番号への辞書。
        grid_spec: 集約先のグリッド仕様。

    Returns:
        指標名（サフィックス無し）から集約済みセル平均値配列への辞書。
    """
    output_columns: dict[str, np.ndarray] = {}
    for key, (raster_path, band_index) in raster_resources.items():
        output_columns[key] = aggregate_raster_to_grid(raster_path, grid_spec, band_index)
    return output_columns
