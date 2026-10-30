"""Black Marble のテスト用に、VNP46A4 相当の小さな HDF5 タイルを書き出す。"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from src.preprocessing.black_marble import conversion, product, tile_grid

# 合成タイルの一辺の画素数（実物は 2400。テストでは小さくして扱いやすくする）
FAKE_TILE_PIXELS = 20


def write_fake_tile(
    path: Path,
    tile: tile_grid.TileIndex,
    scale_factor: float = 1.0,
    offset: float = 0.0,
    include_bounding_coords: bool = True,
    bounds_override: dict[str, float] | None = None,
    shape: tuple[int, int] = (FAKE_TILE_PIXELS, FAKE_TILE_PIXELS),
    extra_fill_positions: tuple[tuple[int, int], ...] = (),
) -> None:
    """テスト用の小さな VNP46A4 相当の HDF5 タイルを書き出す。

    **実ファイル（h28v06 の 2023 年版）の構造に合わせている**。合成バンドは
    float32 で `_FillValue = -999.9`、観測数は uint16 で 65535、オフセット属性の
    名前は `offset`（CF 規約の `add_offset` ではない）。想定に合わせた偽物にすると、
    想定違いをテストで検出できなくなる。

    Args:
        path: 出力パス。
        tile: タイル番号。
        scale_factor: SDS へ付与するスケール係数。
        offset: SDS へ付与するオフセット。実ファイルは 0.0 だが、換算式の
            符号・適用順を検証できるよう変えられるようにしている。
        include_bounding_coords: 境界座標のルート属性を付けるか。
        bounds_override: 境界座標を意図的にずらす場合の値。
        shape: 配列の形状 (行数, 列数)。既定は正方形。行と列の取り違えを
            検出したい場合に非正方形を渡す。
        extra_fill_positions: 追加で欠測にする画素の (行, 列)。ROI 内に欠測を
            置きたい場合に使う。
    """
    west, south, east, north = tile_grid.compute_tile_bounds(tile)
    bounds = bounds_override or {"west": west, "east": east, "north": north, "south": south}
    # 実ファイルに合わせた dtype と欠測値（合成バンドは float32、観測数は uint16）
    float_fill = np.float32(-999.9)
    count_fill = np.uint16(65535)

    with h5py.File(path, "w") as h5_file:
        if include_bounding_coords:
            for key, attribute_name in tile_grid.BOUNDING_COORD_ATTRIBUTES.items():
                h5_file.attrs[attribute_name] = np.float64(bounds[key])

        group = h5_file.create_group(conversion.SDS_GROUP_PATH)
        for index, band in enumerate(product.BAND_DEFINITIONS, start=1):
            is_count = band.sds_name.endswith("_Num")
            dtype = np.uint16 if is_count else np.float32
            fill_value = count_fill if is_count else float_fill
            values = np.full(shape, index * 10, dtype=dtype)
            # 1 画素だけ欠測を置き、_FillValue の扱いを検証できるようにする
            values[0, 0] = fill_value
            for row, column in extra_fill_positions:
                values[row, column] = fill_value
            dataset = group.create_dataset(band.sds_name, data=values)
            dataset.attrs["scale_factor"] = np.array([scale_factor], dtype=np.float64)
            # 実ファイルの属性名は offset（add_offset ではない）
            dataset.attrs["offset"] = np.array([offset], dtype=np.float64)
            dataset.attrs["_FillValue"] = np.array([fill_value], dtype=dtype)
            dataset.attrs["units"] = np.bytes_(b"nWatts/(cm^2 sr)")
            dataset.attrs["long_name"] = np.bytes_(band.sds_name.encode())
