"""衛星指標ラスタ（NDVI/NDBI/NDWI/FVC）をグリッドへ集約するモジュール。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

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
    """ラスタのnodata値を決定する。

    GEE出力ラスタは nodata タグが ``None`` でも ``NaN`` を実値として含むため、
    浮動小数型のラスタではタグが無い場合に ``NaN`` をnodataとみなす。

    Args:
        src: オープン済みのrasterioデータセット。
        band_index: 対象バンド番号（1始まり）。

    Returns:
        nodata値。判定できない場合は ``None``（全画素を有効とみなす）。
    """
    nodata = src.nodata
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


def compute(
    raster_resources: dict[str, tuple[Path, int]],
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """検出済みの衛星指標ラスタをcoarseグリッドへ集約する。

    Args:
        raster_resources: ``io.find_satellite_rasters`` で検出した
            指標名（NDVI/NDBI/NDWI/FVC）からラスタパスとバンド番号への辞書。
        grid_spec: 集約先のグリッド仕様。

    Returns:
        指標名（サフィックス無し）から集約済みセル平均値配列への辞書。
    """
    output_columns: dict[str, np.ndarray] = {}
    for key, (raster_path, band_index) in raster_resources.items():
        output_columns[key] = aggregate_raster_to_grid(raster_path, grid_spec, band_index)
    return output_columns
