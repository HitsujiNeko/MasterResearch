"""HDF5（HDF-EOS5）タイルの読み込みと GeoTIFF への変換。

**本環境の GDAL は HDF5 ドライバなしでビルドされている**ため、h5py で読む。
SDS 名・スケール係数・欠測値はファイルの属性から実測して適用する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from rasterio.crs import CRS
from rasterio.transform import from_origin

from src.common.config import WGS84_CRS
from src.common.raster_area import write_float_raster
from src.preprocessing.black_marble.product import BAND_DEFINITIONS, OUTPUT_NODATA
from src.preprocessing.black_marble.tile_grid import (
    TILE_SIZE_DEG,
    TileIndex,
    compute_tile_bounds,
    verify_tile_georeference,
)

logger = logging.getLogger(__name__)

# HDF-EOS5 内で SDS が置かれるグループ（2026-07-29 に実ファイルで確認）
SDS_GROUP_PATH = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
# オフセット属性の名前。VNP46A4 は CF 規約の `add_offset` ではなく `offset` を使う。
# 版によって揺れうるため両方を見て、先に見つかったほうを採る。
OFFSET_ATTRIBUTE_NAMES = ("offset", "add_offset")


def describe_hdf5_structure(tile_path: Path) -> dict[str, Any]:
    """HDF5 タイルの構造（SDS 名・形状・属性）を読み取る。

    SDS 名や属性が配布バージョンで変わっていないかを確認するために使う。

    Args:
        tile_path: タイルファイルのパス。

    Returns:
        ルート属性と SDS ごとの情報を含む辞書。

    Raises:
        KeyError: 想定した SDS グループが無い場合。
    """
    with h5py.File(tile_path, "r") as h5_file:
        root_attributes = {key: _to_python(value) for key, value in h5_file.attrs.items()}
        if SDS_GROUP_PATH not in h5_file:
            raise KeyError(
                f"SDS グループ {SDS_GROUP_PATH!r} が見つかりません"
                f"（ルートのキー: {sorted(h5_file.keys())}）。"
            )
        group = h5_file[SDS_GROUP_PATH]
        datasets = {
            name: {
                "shape": list(dataset.shape),
                "dtype": str(dataset.dtype),
                "attributes": {key: _to_python(value) for key, value in dataset.attrs.items()},
            }
            for name, dataset in group.items()
        }
    return {"root_attributes": root_attributes, "datasets": datasets}


def _to_python(value: Any) -> Any:
    """HDF5 の属性値を JSON へ書ける Python の値に変換する。

    Args:
        value: HDF5 属性の生の値。

    Returns:
        文字列・数値・リストのいずれか。
    """
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.size == 1:
            return _to_python(value.item())
        return [_to_python(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def is_fill_value_representable(fill_value: Any, dtype: np.dtype) -> bool:
    """`_FillValue` を、SDS の型でそのまま表現できるかを判定する。

    欠測判定は生の値どうしの比較で行うため、`_FillValue` を配列の型へ合わせる。
    このとき **整数型は範囲外の値を例外にせず黙って巻き戻す**（`-999.9` を
    `uint16` にすると `64537`）。一致が 0 件になるだけで警告も出ないため、
    配布バージョンが変わって型が食い違うと、`65535` のような番兵値が実測値と
    して統計・飽和指標に混入する。

    浮動小数点型は丸めが起きるだけで、欠測画素も同じ丸めを経た値を持つため
    比較は成立する。よって検査は整数型に限る。

    Args:
        fill_value: 属性から読んだ `_FillValue`。
        dtype: SDS の配列の型。

    Returns:
        その型で表現できれば True。
    """
    if not np.issubdtype(dtype, np.integer):
        return True
    try:
        cast_value = np.array(fill_value).astype(dtype)
        return float(cast_value) == float(fill_value)
    except (TypeError, ValueError, OverflowError):
        # 配列・文字列など、そもそも数値として扱えない値
        return False


def read_scaled_sds(
    h5_file: h5py.File,
    sds_name: str,
    nodata: float = OUTPUT_NODATA,
) -> tuple[np.ndarray, dict[str, Any]]:
    """SDS を読み、属性に従ってスケールを戻した float32 配列を返す。

    `scale_factor` / オフセット / `_FillValue` は**属性から実測して適用する**。
    換算式は `物理値 = 生値 * scale_factor + offset`（NASA 系には
    `(生値 - offset) * scale_factor` の製品もあるため明記する）。

    実ファイルで確認した値（2026-07-29、h28v06 2023年版）:

    - 合成バンド（`*_Composite_Snow_Free` / `_Std`）は既に **float32 の物理値**で、
      `scale_factor = 1.0` / `offset = 0.0` / `_FillValue = -999.9`
    - `_Num` は uint16（`_FillValue = 65535`）、`_Quality` は uint8（同 255）
    - **オフセット属性の名前は CF 規約の `add_offset` ではなく `offset`**

    属性が無い場合はスケールなし（1.0 / 0.0）・欠測なしとして続行するが、
    **その事実を戻り値の `defaulted_attributes` に残す**。属性名が版によって
    変わったことに気づかないまま換算すると、値がずれたまま最後まで通ってしまう
    （実際に `add_offset` の想定は外れていた）。呼び出し側はこれをサマリー最上位へ
    引き上げ、成果物だけを見ても検知できる状態にする。

    属性はあるが配列の型で表現できない `_FillValue`（整数型への範囲外の値は
    黙って巻き戻る）も、同じく欠測なしとして続行し `unusable_attributes` に残す。

    Args:
        h5_file: 開いた HDF5 ファイル。
        sds_name: 読み出す SDS 名。
        nodata: 出力の無効値。

    Returns:
        (スケール適用済みの 2 次元配列, 適用した属性の記録)。記録の
        `defaulted_attributes` には、属性が無く既定値で代用した項目名が入る。
        `unusable_attributes` には、属性はあるが適用できなかった項目名が入る。

    Raises:
        KeyError: SDS が存在しない場合。
    """
    group = h5_file[SDS_GROUP_PATH]
    if sds_name not in group:
        raise KeyError(
            f"SDS {sds_name!r} が見つかりません（実在する SDS: {sorted(group.keys())}）。"
        )

    dataset = group[sds_name]
    raw_values = dataset[:]
    attributes = {key: _to_python(value) for key, value in dataset.attrs.items()}

    defaulted_attributes: list[str] = []

    scale_factor = float(attributes.get("scale_factor", 1.0))
    if "scale_factor" not in attributes:
        defaulted_attributes.append("scale_factor")
        logger.warning(
            "SDS %s に scale_factor 属性がありません。スケールなし（1.0）として扱いますが、"
            "配布側の属性名が変わっている場合は値が実際と異なります。",
            sds_name,
        )

    offset_name = next((key for key in OFFSET_ATTRIBUTE_NAMES if key in attributes), None)
    add_offset = 0.0 if offset_name is None else float(attributes[offset_name])
    if offset_name is None:
        defaulted_attributes.append("offset")
        logger.warning(
            "SDS %s にオフセット属性（%s のいずれか）がありません。0 として扱います。",
            sds_name,
            " / ".join(OFFSET_ATTRIBUTE_NAMES),
        )

    fill_value = attributes.get("_FillValue")
    unusable_attributes: list[str] = []
    # 欠測判定はスケール適用前の生の値で行う（浮動小数点化で一致しなくなるのを避ける）
    if fill_value is None:
        fill_mask = np.zeros(raw_values.shape, dtype=bool)
        defaulted_attributes.append("_FillValue")
        logger.warning("SDS %s に _FillValue 属性がありません。欠測なしとして扱います。", sds_name)
    elif not is_fill_value_representable(fill_value, raw_values.dtype):
        # 巻き戻った値で比較しても意味が無いため、欠測なしとして扱ったうえで記録する
        fill_mask = np.zeros(raw_values.shape, dtype=bool)
        unusable_attributes.append("_FillValue")
        logger.warning(
            "SDS %s の _FillValue（%r）を配列の型（%s）で表現できません。"
            "欠測なしとして扱います（番兵値が実測値として混入する恐れがあります）。",
            sds_name,
            fill_value,
            raw_values.dtype,
        )
    else:
        fill_mask = raw_values == np.array(fill_value, dtype=raw_values.dtype)

    # CF 規約の換算式。add_offset は加算side（減算する製品もあるため docstring 参照）
    scaled_values = raw_values.astype(np.float64) * scale_factor + add_offset
    scaled_values = scaled_values.astype(np.float32)
    scaled_values[fill_mask] = nodata

    applied = {
        "scale_factor": scale_factor,
        "offset": add_offset,
        "offset_attribute": offset_name,
        "fill_value": fill_value,
        "fill_pixels": int(np.count_nonzero(fill_mask)),
        "units": attributes.get("units"),
        "long_name": attributes.get("long_name"),
        "defaulted_attributes": defaulted_attributes,
        "unusable_attributes": unusable_attributes,
    }
    return scaled_values, applied


def write_tile_geotiff(
    tile_path: Path,
    tile: TileIndex,
    destination_path: Path,
) -> tuple[Path, dict[str, Any]]:
    """HDF5 タイルを、定義した全バンドを持つ GeoTIFF へ変換する。

    HDF-EOS5 側に GDAL が読めるジオリファレンスが無いため、タイル番号と配列の形状から
    アフィン変換を組み立てる。組み立てた範囲はファイル属性と突き合わせて検証する。

    Args:
        tile_path: HDF5 タイルのパス。
        tile: タイル番号。
        destination_path: 出力 GeoTIFF パス。

    Returns:
        (出力パス, 読み取り時のメタデータ記録)。

    Raises:
        ValueError: バンド間で配列の形状が揃っていない場合。
    """
    with h5py.File(tile_path, "r") as h5_file:
        root_attributes = {key: _to_python(value) for key, value in h5_file.attrs.items()}
        georeference = verify_tile_georeference(root_attributes, tile)
        band_arrays: dict[str, np.ndarray] = {}
        band_attributes: dict[str, Any] = {}
        for band in BAND_DEFINITIONS:
            values, applied = read_scaled_sds(h5_file, band.sds_name)
            band_arrays[band.output_name] = values
            band_attributes[band.output_name] = applied

    shapes = {name: array.shape for name, array in band_arrays.items()}
    if len(set(shapes.values())) != 1:
        raise ValueError(f"バンド間で配列の形状が揃っていません: {shapes}")

    height, width = next(iter(shapes.values()))
    west, _, _, north = compute_tile_bounds(tile)
    transform = from_origin(west, north, TILE_SIZE_DEG / width, TILE_SIZE_DEG / height)

    write_float_raster(
        output_path=destination_path,
        band_arrays=band_arrays,
        transform=transform,
        crs=CRS.from_string(WGS84_CRS),
        nodata=OUTPUT_NODATA,
    )

    metadata = {
        "tile_shape": [height, width],
        "pixel_size_deg": TILE_SIZE_DEG / width,
        "georeference_check": georeference,
        "band_attributes": band_attributes,
    }
    return destination_path, metadata
