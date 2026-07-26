"""地理座標系ラスタのセル面積計算と、面積あたり量への換算処理。

人口カウント（人／セル）のように「セルあたりの合計量」で配布されるラスタを、
面積あたりの密度（人/km² 等）へ換算する処理を集約する。

EPSG:4326 のセル面積は緯度によって変わるため、定数で割ると低緯度・高緯度で
系統的な誤差が生じる。本モジュールは WGS84 楕円体上の実面積を用いる。
"""

from __future__ import annotations

import numpy as np
from affine import Affine
from pyproj import Geod


def compute_cell_area_km2(transform: Affine, height: int, width: int) -> np.ndarray:
    """地理座標系（度単位）グリッドの各行のセル面積（km²）を求める。

    経度方向に等間隔な格子ではセル面積は緯度のみに依存するため、行ごとに 1 回だけ
    WGS84 楕円体上の面積を計算し、列方向はブロードキャストで扱う。

    Args:
        transform: ラスタのアフィン変換（度単位の地理座標系）。
        height: 行数。
        width: 列数（引数の妥当性検証にのみ使う）。

    Returns:
        形状 (height, 1) のセル面積（km²）。列方向へブロードキャストして使う。

    Raises:
        ValueError: 行数・列数が正でない場合、またはグリッドが north-up でない場合。
    """
    if height <= 0 or width <= 0:
        raise ValueError(f"ラスタの寸法が不正です: height={height}, width={width}")
    # 回転・スキューのあるグリッドでは「行＝一定緯度」が成り立たず、行単位の面積計算が
    # 破綻する。GEE 出力は常に north-up だが、前提が崩れたら黙って誤った値を返さない
    if transform.b != 0.0 or transform.d != 0.0:
        raise ValueError(
            "回転・スキューのあるグリッドには対応していません"
            f"（transform.b={transform.b}, transform.d={transform.d}）。"
        )

    geodesic = Geod(ellps="WGS84")
    pixel_width_deg = abs(transform.a)
    row_indices = np.arange(height)
    top_latitudes = transform.f + transform.e * row_indices
    bottom_latitudes = transform.f + transform.e * (row_indices + 1)

    cell_areas_km2 = np.empty((height, 1), dtype=np.float64)
    for row_index, (top_latitude, bottom_latitude) in enumerate(
        zip(top_latitudes, bottom_latitudes)
    ):
        longitudes = [0.0, pixel_width_deg, pixel_width_deg, 0.0]
        latitudes = [top_latitude, top_latitude, bottom_latitude, bottom_latitude]
        area_m2, _ = geodesic.polygon_area_perimeter(longitudes, latitudes)
        cell_areas_km2[row_index, 0] = abs(area_m2) / 1_000_000.0
    return cell_areas_km2


def compute_density_array(
    count_array: np.ndarray,
    cell_area_km2: np.ndarray,
    nodata: float,
) -> np.ndarray:
    """セルあたりの合計量から、面積あたりの密度（単位/km²）を求める。

    nodata 画素は密度側でも nodata のまま残す（0 と混同しないため）。

    Args:
        count_array: セルあたりの合計量の 2 次元配列。
        cell_area_km2: 形状 (height, 1) のセル面積（km²）。
        nodata: 無効値。

    Returns:
        密度（単位/km²）の 2 次元配列（float32）。
    """
    valid_mask = count_array != nodata
    density_array = np.full(count_array.shape, nodata, dtype=np.float32)
    density_array[valid_mask] = (
        count_array.astype(np.float64) / np.broadcast_to(cell_area_km2, count_array.shape)
    )[valid_mask].astype(np.float32)
    return density_array
