"""ラスタをグリッドへ集約するモジュール（衛星指標 NDVI/NDBI/NDWI と共通の集約基盤）。

セル平均と有効画素率の2列を対で出すパラメータ（標高・LST・人口密度・夜間光）は
``aggregate_mean_and_valid_ratio()`` を共通の入口として使う。
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds

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
    dst_array = np.zeros(grid_spec.coarse_shape, dtype=np.float32)

    with rasterio.open(raster_path) as src:
        _validate_band_index(src, band_index, raster_path)
        nodata = _resolve_nodata(src, band_index)
        valid_mask = _valid_pixel_mask(src.read(band_index), nodata).astype(np.float32)

        reproject(
            source=valid_mask,
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=grid_spec.coarse_transform,
            dst_crs=grid_spec.analysis_crs,
            resampling=Resampling.average,
            # 寄与する画素が1つも無いセルは、初期値0.0（＝有効画素なし）のまま残す。
            init_dest_nodata=False,
            num_threads=2,
        )

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
    期待と食い違う」場合に限る。

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

    if description is None:
        return

    lowered = str(description).strip().lower()
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
        # 重なり判定はこの異常時にしか行わない。正常な入力ではラスタを開き直す
        # コストが掛からないようにするためである。
        if raster_overlaps_grid(raster_path, grid_spec):
            warnings.warn(
                f"{kind_label}ラスタは解析グリッドと重なっていますが、有効画素が1つも"
                f"ありません。{mean_column} 列は全セルNaNになります。全面が雲マスク等で"
                " 欠測している観測か、nodata値の取り違えを疑ってください:"
                f" {raster_path}",
                stacklevel=3,
            )
        else:
            warnings.warn(
                f"{kind_label}ラスタが解析グリッドと重なりません。{mean_column} 列は"
                "全セルNaNになります。都市の取り違え・切り出し範囲の誤りを疑って"
                f"ください: {raster_path}",
                stacklevel=3,
            )

    return {mean_column: mean_values, ratio_column: valid_ratio}


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
