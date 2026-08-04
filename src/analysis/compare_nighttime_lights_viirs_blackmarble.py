"""VIIRS DNB 年次コンポジットと NASA Black Marble（VNP46A4）の Hanoi ROI での違いを評価する。

入力は `src/preprocessing/fetch_viirs_dnb_hanoi.py` と
`src/preprocessing/fetch_black_marble_hanoi.py` が出力した多バンド GeoTIFF で、
比較は主バンド同士（VIIRS の `avg_radiance` と Black Marble の `ntl_near_nadir`）で行う。
どちらも単位は nW·cm⁻²·sr⁻¹ である。

比較設計:

- **解像度は両者とも 15 arc-sec で同じだが、グリッド原点が半画素ずれる**
  （VIIRS は画素中心が整数度グリッド、Black Marble はタイル境界が整数度）。そのため
  粗い側へ寄せる必要はなく、**Black Marble を VIIRS グリッドへ再投影して重ねる**
  だけでよい。解像度が同じなので再投影はずれの補正にとどまる。
- 再投影の方法によって結論が変わらないことを確認できるよう、**3 通りを併記する**。
  ①双一次内挿（主指標）②最近傍（内挿による平滑化の影響を見る）③再投影なしの
  索引対応（半画素ずれを無視した場合に何が起きるかを示す対照）。
  ③は地理的に正しくない対応付けであり、**採用しない方法を数値で示すために置く**。
- 解像度の刻みは VIIRS 側が丸め値（0.0041666667）、Black Marble 側が 1/240 の
  厳密値で、**厳密には一致しない**。177 画素ぶん累積しても差は 1e-8 度未満で
  実害は無いが、アフィン変換の等値比較は行わない。

飽和の評価: 夜間光は都心部で値が上限へ張り付き、密集市街地内の空間パターンを
識別できなくなることが知られている。上位分位点の詰まり具合（p99/max）に加え、
**最輝部の近傍と外縁で値の広がりを比較する**。飽和していれば都心側の分布が上端に
集中して広がりを失うため、分位点の差として現れる。

- ゾーンの基準点は **ROI の重心ではなく、基準データセットで放射輝度が上位 1% に
  入る画素の重心**（＝最輝部の中心）にする。Hanoi ROI では両者が約 20km 離れ、
  ROI 重心を使うと**最輝画素がどちらのゾーンにも入らなかった**。飽和は最輝部で
  こそ起きるため、輝度側から都心を定める。
- 飽和は**両データセットとも自身のグリッドの生データ（再投影なし）で評価する**。
  再投影後の値で測ると内挿の平滑化が上位の値を削り、飽和指標が「飽和していない」
  方向へ歪む（実データでは Black Marble の p99/max が 0.211 → 0.294 と上振れした）。
  ゾーンの地理的範囲は、基準側で決めた距離閾値を比較側にも適用して揃える。

注意: 両者は同じ VIIRS DNB センサーの観測に基づくが、合成アルゴリズムが異なる
（Black Marble は月光・大気・BRDF 補正を施し、視野角を近直下視に限定する）。
差分はセンサー差ではなく**処理の違い**として解釈する。
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

from src.common.config import DEFAULT_HANOI_ROI_PATH, LANDSAT_OBSERVATION_YEAR, PROJECT_ROOT
from src.common.paired_stats import build_paired_statistics
from src.common.paths import prepare_output_path, resolve_existing_path, to_project_relative_string
from src.common.raster_area import DEFAULT_RASTER_NODATA
from src.common.raster_stats import build_band_statistics, build_saturation_indicators
from src.common.roi import build_raster_roi_mask, load_roi_geometry
from src.common.summary import save_summary

DEFAULT_NIGHTTIME_LIGHTS_DIR = PROJECT_ROOT / "data" / "gis" / "nighttime_lights"
DEFAULT_VIIRS_DIR = DEFAULT_NIGHTTIME_LIGHTS_DIR / "viirs_dnb"
DEFAULT_BLACK_MARBLE_DIR = DEFAULT_NIGHTTIME_LIGHTS_DIR / "black_marble"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

NODATA = DEFAULT_RASTER_NODATA
# 主バンド（放射輝度）は両データセットとも第1バンド
RADIANCE_BAND = 1
RADIANCE_UNIT = "nW·cm⁻²·sr⁻¹"

# 分位点対応表に載せる分位点
COMPARISON_PERCENTILES = (50, 90, 95, 99)
# 都心・外縁の切り分けに使う距離の分位点。基準点からの距離が下位 25% を都心、
# 上位 25%（＝第3四分位以上）を外縁とする。固定の半径を決め打ちしないため。
INNER_ZONE_PERCENTILE = 25
OUTER_ZONE_PERCENTILE = 75
# 都心の基準点を決めるための輝度分位点（上位 1% の画素の重心を最輝部とみなす）
BRIGHT_CORE_PERCENTILE = 99

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="VIIRS DNB と NASA Black Marble の Hanoi ROI での違いを評価する。"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=LANDSAT_OBSERVATION_YEAR,
        help="比較対象年（サマリーへの記録と既定の出力名に使う）。",
    )
    parser.add_argument(
        "--viirs-path",
        type=Path,
        default=None,
        help="VIIRS DNB の GeoTIFF パス（基準グリッド）。未指定時は --year から解決する。",
    )
    parser.add_argument(
        "--black-marble-path",
        type=Path,
        default=None,
        help="Black Marble VNP46A4 の GeoTIFF パス。未指定時は --year から解決する。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="比較サマリー JSON の出力パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    return parser.parse_args()


def resolve_input_paths(
    year: int, viirs_path: Path | None, black_marble_path: Path | None
) -> tuple[Path, Path]:
    """入力 GeoTIFF のパスを解決する。

    **未指定時は `--year` から取得スクリプトの命名規則で組み立てる**。年を出力名
    にしか効かせないと、2023 年のデータから `..._2022_summary.json`（`"year": 2022`）
    を例外なく生成できてしまい、記録と中身が食い違う。

    Args:
        year: 比較対象年。
        viirs_path: 指定された VIIRS DNB のパス。
        black_marble_path: 指定された Black Marble のパス。

    Returns:
        (VIIRS DNB のパス, Black Marble のパス)。
    """
    resolved_viirs = viirs_path or (DEFAULT_VIIRS_DIR / f"viirs_dnb_hanoi_{year}.tif")
    resolved_black_marble = black_marble_path or (
        DEFAULT_BLACK_MARBLE_DIR / f"black_marble_vnp46a4_hanoi_{year}.tif"
    )
    return resolved_viirs, resolved_black_marble


def resolve_summary_path(year: int, summary_path: Path | None) -> Path:
    """比較サマリー JSON の保存先を解決する。

    Args:
        year: 比較対象年。
        summary_path: 指定されたパス。未指定なら既定の場所へ。

    Returns:
        保存先パス。
    """
    resolved = summary_path or (
        DEFAULT_SUMMARY_DIR / f"nighttime_lights_viirs_blackmarble_hanoi_{year}_summary.json"
    )
    return prepare_output_path(resolved)


def load_radiance_raster(raster_path: Path, band: int = RADIANCE_BAND) -> dict[str, Any]:
    """夜間光ラスタの放射輝度バンドを読み込む。

    Args:
        raster_path: 入力 GeoTIFF パス。
        band: 読み出すバンド番号（1 始まり）。

    Returns:
        配列・変換・CRS・形状・バンド名を含む辞書。

    Raises:
        ValueError: 指定バンドが存在しない場合、CRS が未定義の場合、
            地理座標系でない場合、または宣言された無効値が本モジュールの前提
            （`NODATA`）と異なる場合。
    """
    with rasterio.open(raster_path) as source:
        if source.count < band:
            raise ValueError(
                f"バンド {band} がありません（{raster_path.name} のバンド数: {source.count}）。"
            )
        if source.crs is None:
            raise ValueError(f"ラスタの CRS が未定義です: {raster_path.name}")
        # 本研究の入出力は EPSG:4326 基準。投影座標系のラスタを渡されると、
        # 度前提の距離計算（都心・外縁の切り分け）が例外にならないまま誤る
        if not CRS.from_user_input(source.crs).is_geographic:
            raise ValueError(
                "地理座標系（度単位）のラスタのみに対応しています"
                f"（{raster_path.name} の CRS: {source.crs.to_string()}）。"
            )
        # 無効値の解釈を読み込み時に 1 箇所へ固定する。宣言された nodata が前提と
        # 違うまま通すと、その画素が有効値として統計・相関へ静かに混ざる
        # （例: nodata が -999 のラスタでは -999 が実測値として平均に入る）
        declared_nodata = float(source.nodata) if source.nodata is not None else None
        if declared_nodata is not None and declared_nodata != NODATA:
            raise ValueError(
                f"想定外の無効値です（{raster_path.name} の nodata: {declared_nodata}、"
                f"本スクリプトの前提: {NODATA}）。取得スクリプトが書き出したラスタか"
                "確認してください。"
            )
        descriptions = source.descriptions
        return {
            "path": raster_path,
            "values": source.read(band).astype(np.float64),
            "band_name": descriptions[band - 1] if descriptions[band - 1] else f"band_{band}",
            "transform": source.transform,
            "crs": source.crs,
            "shape": (int(source.height), int(source.width)),
            "resolution": [float(source.res[0]), float(source.res[1])],
        }


def describe_raster(raster: dict[str, Any], roi_mask: np.ndarray) -> dict[str, Any]:
    """1 データセットの ROI 内の記述統計と飽和指標をまとめる。

    Args:
        raster: `load_radiance_raster` の戻り値。
        roi_mask: ROI 内マスク。

    Returns:
        パス・グリッド諸元・記述統計・飽和指標を含む辞書。
    """
    valid_mask = roi_mask & (raster["values"] != NODATA)
    values = raster["values"][valid_mask]
    return {
        "path": to_project_relative_string(raster["path"]),
        "band": raster["band_name"],
        "unit": RADIANCE_UNIT,
        "shape": list(raster["shape"]),
        "resolution_deg": raster["resolution"],
        "origin": [float(raster["transform"].c), float(raster["transform"].f)],
        "roi_pixels": int(np.count_nonzero(roi_mask)),
        "valid_pixels": int(np.count_nonzero(valid_mask)),
        "statistics": build_band_statistics(values),
        "saturation": build_saturation_indicators(values),
    }


def compute_grid_offset(reference: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    """2 つのグリッドの原点ずれを、画素サイズに対する割合として求める。

    「半画素ずれる」という前提を数値で裏付け、サマリーに残すために使う。

    Args:
        reference: 基準グリッドのラスタ。
        comparison: 比較側のラスタ。

    Returns:
        原点差（度）と、画素サイズに対する割合。
    """
    reference_transform = reference["transform"]
    comparison_transform = comparison["transform"]
    longitude_difference = float(comparison_transform.c - reference_transform.c)
    latitude_difference = float(comparison_transform.f - reference_transform.f)
    return {
        "longitude_deg": longitude_difference,
        "latitude_deg": latitude_difference,
        "longitude_in_pixels": longitude_difference / float(reference_transform.a),
        "latitude_in_pixels": latitude_difference / float(reference_transform.e),
        "note": (
            "割合の絶対値が 0.5 前後であれば半画素ずれを意味する。VIIRS DNB は画素中心"
            "が整数度グリッドに載り、Black Marble はタイル境界が整数度に載るため生じる。"
            "緯度側は北向きを正とするアフィン変換の係数（transform.e）が負のため、"
            "北へずれると符号が負になる（例: -0.5）。"
        ),
    }


def reproject_to_reference(
    source: dict[str, Any],
    reference: dict[str, Any],
    resampling: Resampling,
) -> np.ndarray:
    """比較側ラスタを基準グリッドへ再投影する。

    解像度は両者とも 15 arc-sec で等しいため、実質的には原点の半画素ずれの補正になる。
    無効値は `src_nodata` / `dst_nodata` として渡し、内挿へ混ぜない。

    Args:
        source: 再投影するラスタ。
        reference: 基準グリッドのラスタ。
        resampling: 再投影の方法。

    Returns:
        基準グリッド上の配列（無効画素は NODATA）。
    """
    destination = np.full(reference["shape"], NODATA, dtype=np.float64)
    reproject(
        source=source["values"],
        destination=destination,
        src_transform=source["transform"],
        src_crs=source["crs"],
        dst_transform=reference["transform"],
        dst_crs=reference["crs"],
        src_nodata=NODATA,
        dst_nodata=NODATA,
        resampling=resampling,
    )
    return destination


def align_by_pixel_index(source: dict[str, Any], reference: dict[str, Any]) -> np.ndarray:
    """再投影せず、行列の索引だけで比較側を基準グリッドへ重ねる。

    **地理的に正しくない対応付け**で、採用しない方法の影響を数値で示すために置く。
    形状が違う場合は左上を合わせて重なる範囲だけを使い、残りは無効値で埋める。

    Args:
        source: 比較側のラスタ。
        reference: 基準グリッドのラスタ。

    Returns:
        基準グリッド上の配列（重ならない部分は NODATA）。
    """
    destination = np.full(reference["shape"], NODATA, dtype=np.float64)
    overlap_rows = min(reference["shape"][0], source["shape"][0])
    overlap_columns = min(reference["shape"][1], source["shape"][1])
    destination[:overlap_rows, :overlap_columns] = source["values"][:overlap_rows, :overlap_columns]
    return destination


def build_quantile_correspondence(
    reference_values: np.ndarray, comparison_values: np.ndarray
) -> dict[str, Any]:
    """両系列の分位点を並べ、上端の詰まり具合を比べられる表を作る。

    Args:
        reference_values: 基準側の 1 次元配列。
        comparison_values: 比較側の 1 次元配列。

    Returns:
        分位点ごとの両系列の値と最大値。有効画素が無い場合は空の辞書。
    """
    if reference_values.size == 0 or comparison_values.size == 0:
        return {}
    correspondence = {
        f"p{percentile}": {
            "reference": float(np.percentile(reference_values, percentile)),
            "comparison": float(np.percentile(comparison_values, percentile)),
        }
        for percentile in COMPARISON_PERCENTILES
    }
    correspondence["max"] = {
        "reference": float(np.max(reference_values)),
        "comparison": float(np.max(comparison_values)),
    }
    return correspondence


def compare_on_reference_grid(
    reference: dict[str, Any],
    comparison_values: np.ndarray,
    roi_mask: np.ndarray,
    method: str,
    method_note: str,
) -> dict[str, Any]:
    """基準グリッド上で 2 系列を突き合わせる。

    Args:
        reference: 基準グリッドのラスタ。
        comparison_values: 基準グリッドへ載せ替えた比較側の配列。
        roi_mask: 基準グリッド上の ROI マスク。
        method: 載せ替えの方法名。
        method_note: 方法の説明。

    Returns:
        比較画素数と一致度統計・分位点対応。
    """
    comparable_mask = roi_mask & (reference["values"] != NODATA) & (comparison_values != NODATA)
    reference_series = reference["values"][comparable_mask]
    comparison_series = comparison_values[comparable_mask]
    return {
        "method": method,
        "method_note": method_note,
        "comparable_pixels": int(np.count_nonzero(comparable_mask)),
        "roi_pixels": int(np.count_nonzero(roi_mask)),
        # 再投影で ROI 外縁の画素が無効化されると比較の母数が減る。ROI 全体と
        # 同一視しないよう、除外された画素数も残す
        "excluded_pixels": int(np.count_nonzero(roi_mask & ~comparable_mask)),
        "agreement": build_paired_statistics(reference_series, comparison_series),
        "quantiles": build_quantile_correspondence(reference_series, comparison_series),
    }


def build_zone_masks(
    reference: dict[str, Any], roi_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """最輝部の中心からの距離で、都心側と外縁側の画素マスクを作る。

    基準点は `compute_bright_core_anchor` が求める **基準データセットの ROI 内で
    放射輝度が上位 1% に入る画素の重心（＝最輝部の中心）**であり、ROI の重心でも
    ROI 内画素中心の平均座標でもない。ROI の重心は行政界の形で決まるため市街地の
    最輝部から外れることがあり、実際に Hanoi ROI では最輝画素が都心側・外縁側の
    どちらのゾーンにも入らなかった。飽和は最輝部でこそ起きるため、輝度側から
    都心を定めている。

    飽和は都心部で起きるため、ROI 全体の統計だけでは「都心の値の広がりが失われて
    いるか」が見えない。固定半径を決め打ちせず、**ROI 内画素の距離分布の四分位**で
    切る（ROI の形が変わっても意味が保たれるため）。

    経度方向の 1 度は緯度方向より短いため、緯度の余弦で経度差を縮めてから距離を
    測る（度をそのまま二乗和すると東西方向を過大評価する）。距離は順位付けにしか
    使わないため、正確な測地距離までは求めない。

    Args:
        reference: 基準グリッドのラスタ。
        roi_mask: ROI 内マスク。

    Returns:
        (都心側マスク, 外縁側マスク, 切り分けの記録)。

    Raises:
        ValueError: ROI 内画素が 1 つも無い場合。
    """
    if not np.any(roi_mask):
        raise ValueError("ROI 内の画素がありません。ROI とラスタの位置関係を確認してください。")

    anchor = compute_bright_core_anchor(reference, roi_mask)
    distances = compute_anchor_distances(reference, anchor)
    roi_distances = distances[roi_mask]
    inner_threshold = float(np.percentile(roi_distances, INNER_ZONE_PERCENTILE))
    outer_threshold = float(np.percentile(roi_distances, OUTER_ZONE_PERCENTILE))

    inner_mask, outer_mask = build_zone_masks_for_raster(
        reference, roi_mask, anchor, inner_threshold, outer_threshold
    )
    zone_note = {
        "anchor_lonlat": list(anchor),
        "anchor_percentile": BRIGHT_CORE_PERCENTILE,
        "inner_percentile": INNER_ZONE_PERCENTILE,
        "outer_percentile": OUTER_ZONE_PERCENTILE,
        "inner_threshold_deg": inner_threshold,
        "outer_threshold_deg": outer_threshold,
        "note": (
            "基準点は、基準データセットの ROI 内で放射輝度が上位 "
            f"{100 - BRIGHT_CORE_PERCENTILE}% に入る画素の重心（＝最輝部の中心）。"
            "ROI の重心を使うと市街地の最輝部から外れ、飽和が最も起きやすい場所が"
            "どちらのゾーンにも入らないことがあるため、輝度側から決めている。"
            "距離は経度差に緯度の余弦を掛けて等方に近づけたうえで求め、その四分位で"
            "都心側・外縁側に分ける。閾値は基準データセット側で決め、比較側にも同じ"
            "距離閾値を適用する（ゾーンを地理的に一致させ、母集団の違いを持ち込まない"
            "ため）。**inner_threshold_deg / outer_threshold_deg の単位は度であり、"
            "投影座標系による測地距離ではない**。本研究は面積・距離の算出に投影座標系"
            "を用いる方針だが、ここでの距離は画素を重心からの遠近で順位付けし分位点で"
            "切るためだけに使い、絶対値を解釈しないため度のままとしている。"
        ),
    }
    return inner_mask, outer_mask, zone_note


def pixel_center_coordinates(raster: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """ラスタの各画素中心の経度・緯度を求める。

    Args:
        raster: `load_radiance_raster` の戻り値。

    Returns:
        (経度の格子, 緯度の格子)。いずれもラスタと同じ形状。
    """
    height, width = raster["shape"]
    transform = raster["transform"]
    latitudes = transform.f + transform.e * (np.arange(height) + 0.5)
    longitudes = transform.c + transform.a * (np.arange(width) + 0.5)
    latitude_grid, longitude_grid = np.meshgrid(latitudes, longitudes, indexing="ij")
    return longitude_grid, latitude_grid


def compute_bright_core_anchor(
    reference: dict[str, Any], roi_mask: np.ndarray
) -> tuple[float, float]:
    """最輝部（上位分位点に入る画素）の重心を、ゾーン分けの基準点として求める。

    ROI の重心は行政界の形で決まり、市街地の位置とは無関係になりうる。実際に
    Hanoi ROI では ROI 内画素の重心が最輝画素から約 20km 離れ、最輝画素が都心側・
    外縁側のどちらのゾーンにも入らなかった。飽和は最輝部でこそ起きるため、
    **輝度そのものから都心を定める**。

    Args:
        reference: 基準グリッドのラスタ。
        roi_mask: ROI 内マスク。

    Returns:
        (経度, 緯度)。

    Raises:
        ValueError: ROI 内に有効画素が 1 つも無い場合。
    """
    valid_mask = roi_mask & (reference["values"] != NODATA)
    # ROI 内が全て無効値だと、この先の分位点計算が numpy の空配列エラーになる。
    # 呼び出し元の「ROI 内の画素がありません」ガードと粒度を揃えて先に弾く
    if not np.any(valid_mask):
        raise ValueError(
            "ROI 内に有効画素がありません。ラスタの無効値と ROI の位置関係を確認してください。"
        )
    threshold = float(np.percentile(reference["values"][valid_mask], BRIGHT_CORE_PERCENTILE))
    bright_mask = valid_mask & (reference["values"] >= threshold)
    longitude_grid, latitude_grid = pixel_center_coordinates(reference)
    return (
        float(np.mean(longitude_grid[bright_mask])),
        float(np.mean(latitude_grid[bright_mask])),
    )


def compute_anchor_distances(raster: dict[str, Any], anchor: tuple[float, float]) -> np.ndarray:
    """基準点から各画素中心までの距離（度）を求める。

    経度方向の 1 度は緯度方向より短いため、基準点の緯度の余弦で経度差を縮めてから
    測る（度をそのまま二乗和すると東西方向を過大評価する）。

    Args:
        raster: `load_radiance_raster` の戻り値。
        anchor: 基準点の (経度, 緯度)。

    Returns:
        ラスタと同じ形状の距離配列。
    """
    anchor_longitude, anchor_latitude = anchor
    longitude_grid, latitude_grid = pixel_center_coordinates(raster)
    longitude_scale = float(np.cos(np.deg2rad(anchor_latitude)))
    return np.hypot(
        (longitude_grid - anchor_longitude) * longitude_scale,
        latitude_grid - anchor_latitude,
    )


def build_zone_masks_for_raster(
    raster: dict[str, Any],
    roi_mask: np.ndarray,
    anchor: tuple[float, float],
    inner_threshold: float,
    outer_threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """与えられた距離閾値で、任意のラスタ格子上にゾーンマスクを作る。

    閾値を引数で受け取るのは、**基準側で決めた同じ地理的範囲を比較側にも適用する**
    ため。ラスタごとに分位点を取り直すと、グリッドが違うだけでゾーンの範囲が
    ずれてしまう。

    Args:
        raster: 対象ラスタ。
        roi_mask: そのラスタ格子上の ROI マスク。
        anchor: 基準点の (経度, 緯度)。
        inner_threshold: 都心側とみなす距離の上限。
        outer_threshold: 外縁側とみなす距離の下限。

    Returns:
        (都心側マスク, 外縁側マスク)。
    """
    distances = compute_anchor_distances(raster, anchor)
    return roi_mask & (distances <= inner_threshold), roi_mask & (distances >= outer_threshold)


def summarize_zone(values: np.ndarray) -> dict[str, Any] | None:
    """1 つのゾーンにおける値の広がりをまとめる。

    Args:
        values: ゾーン内の有効画素（1 次元）。

    Returns:
        記述統計・飽和指標と、上位の広がり（p99 と中央値の差）。画素が無ければ None。
    """
    statistics = build_band_statistics(values)
    if statistics is None:
        return None
    return {
        "pixels": int(values.size),
        "statistics": statistics,
        "saturation": build_saturation_indicators(values),
        # 飽和すると上位が最大値へ集まり、この差が小さくなる
        "p99_minus_median": statistics["p99"] - statistics["median"],
    }


def compare_saturation_by_zone(
    reference: dict[str, Any],
    reference_roi_mask: np.ndarray,
    comparison: dict[str, Any],
    comparison_roi_mask: np.ndarray,
) -> dict[str, Any]:
    """都心側と外縁側で、両データセットの値の広がりを比べる。

    **両データセットとも自身のグリッド上の生データで評価する**。飽和はソース
    データの性質であり、再投影後の値で測ると内挿の平滑化が上位の値を削って
    「飽和していない」方向へ結果を歪める（実データでは Black Marble の
    p99/max が 0.211 → 0.294 と上振れした）。ゾーンの地理的範囲は基準側で
    決めた距離閾値を共有することで揃える。

    Args:
        reference: 基準データセットのラスタ。
        reference_roi_mask: 基準グリッド上の ROI マスク。
        comparison: 比較データセットのラスタ（再投影しない生データ）。
        comparison_roi_mask: 比較側グリッド上の ROI マスク。

    Returns:
        ゾーンごと・データセットごとの広がりの記録。
    """
    inner_mask, outer_mask, zone_note = build_zone_masks(reference, reference_roi_mask)
    anchor = (zone_note["anchor_lonlat"][0], zone_note["anchor_lonlat"][1])
    comparison_inner, comparison_outer = build_zone_masks_for_raster(
        comparison,
        comparison_roi_mask,
        anchor,
        zone_note["inner_threshold_deg"],
        zone_note["outer_threshold_deg"],
    )

    zones: dict[str, Any] = {"definition": zone_note}
    for zone_name, reference_zone, comparison_zone in (
        ("inner", inner_mask, comparison_inner),
        ("outer", outer_mask, comparison_outer),
    ):
        reference_valid = reference_zone & (reference["values"] != NODATA)
        comparison_valid = comparison_zone & (comparison["values"] != NODATA)
        zones[zone_name] = {
            "viirs_dnb": summarize_zone(reference["values"][reference_valid]),
            "black_marble": summarize_zone(comparison["values"][comparison_valid]),
        }
    zones["evaluated_on"] = (
        "両データセットとも自身のグリッド上の生データ（再投影なし）。内挿は上位の"
        "値を削り、飽和指標を「飽和していない」方向へ歪めるため。"
    )
    zones["interpretation_note"] = (
        "飽和していれば都心側で上位の値が最大値へ張り付き、p99_minus_median が"
        "外縁側と比べて相対的に小さくなる（値の広がりが失われる）。"
    )
    return zones


def build_summary(
    year: int,
    viirs_stats: dict[str, Any],
    black_marble_stats: dict[str, Any],
    grid_offset: dict[str, Any],
    comparisons: list[dict[str, Any]],
    saturation_by_zone: dict[str, Any],
    roi_path: Path,
    summary_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    """比較サマリーの辞書を組み立てる。

    Args:
        year: 比較対象年。
        viirs_stats: VIIRS DNB の ROI 内統計。
        black_marble_stats: Black Marble の ROI 内統計。
        grid_offset: グリッド原点のずれ。
        comparisons: 載せ替え方法ごとの比較結果（先頭が主指標）。
        saturation_by_zone: 都心・外縁での広がりの比較。
        roi_path: ROI ファイルパス。
        summary_path: サマリー JSON パス。
        generated_at: 生成日時（ISO8601）。

    Returns:
        サマリー辞書。
    """
    return {
        "comparison": "VIIRS DNB 年次コンポジット vs NASA Black Marble VNP46A4",
        "generated_at": generated_at,
        "year": year,
        "roi_path": to_project_relative_string(roi_path),
        "unit": RADIANCE_UNIT,
        "reference_grid": {
            "source": "VIIRS DNB",
            "reason": (
                "解像度は両者とも 15 arc-sec で等しく、粗い側へ寄せる必要がない。"
                "原点が半画素ずれるだけなので、片方を基準にして再投影で重ねる。"
                "VIIRS DNB を基準にしたのは、Black Marble が VIIRS DNB 観測の"
                "補正版であり、素の観測側を基準に置くほうが解釈しやすいため。"
            ),
        },
        "grid_offset": grid_offset,
        "datasets": {"viirs_dnb": viirs_stats, "black_marble_vnp46a4": black_marble_stats},
        "primary_comparison": comparisons[0],
        "sensitivity_comparisons": comparisons[1:],
        "method_sensitivity_note": (
            "載せ替え方法を変えた結果を併記している。双一次内挿と最近傍の差が小さければ、"
            "結論は再投影方法に依存しない。索引対応（再投影なし）は半画素ずれを無視した"
            "誤った対応付けで、採用しない方法の影響を示すために置いている。"
        ),
        "saturation_by_zone": saturation_by_zone,
        "interpretation_note": (
            "両者は同じ VIIRS DNB センサーの観測に基づくが、Black Marble は月光・大気・"
            "BRDF 補正を施し視野角を近直下視に限定するため、差分はセンサー差ではなく"
            "処理の違いとして解釈する。値の大小は「どちらが正しいか」を意味しない。"
        ),
        "outputs": {"summary": to_project_relative_string(summary_path)},
    }


def run(
    year: int,
    viirs_path: Path | None,
    black_marble_path: Path | None,
    roi_path: Path,
    summary_path: Path | None,
) -> Path:
    """比較処理全体を実行する。

    Args:
        year: 比較対象年。
        viirs_path: VIIRS DNB の GeoTIFF パス。未指定なら年から解決する。
        black_marble_path: Black Marble の GeoTIFF パス。未指定なら年から解決する。
        roi_path: ROI の Shapefile パス。
        summary_path: 比較サマリー JSON の出力パス。

    Returns:
        出力したサマリー JSON パス。

    Raises:
        ValueError: 2 つのラスタの CRS が一致しない場合。
    """
    # サマリーへ記録するパスは、読み込みに使ったものと同一にする
    resolved_roi_path = resolve_existing_path(roi_path)
    roi_gdf, _ = load_roi_geometry(resolved_roi_path)

    viirs_input_path, black_marble_input_path = resolve_input_paths(
        year, viirs_path, black_marble_path
    )
    viirs = load_radiance_raster(resolve_existing_path(viirs_input_path))
    black_marble = load_radiance_raster(resolve_existing_path(black_marble_input_path))
    if viirs["crs"] != black_marble["crs"]:
        raise ValueError(
            "2 つのラスタの CRS が一致しません"
            f"（{viirs['crs'].to_string()} vs {black_marble['crs'].to_string()}）。"
        )

    viirs_mask = build_raster_roi_mask(
        roi_gdf=roi_gdf, crs=viirs["crs"], shape=viirs["shape"], transform=viirs["transform"]
    )
    black_marble_mask = build_raster_roi_mask(
        roi_gdf=roi_gdf,
        crs=black_marble["crs"],
        shape=black_marble["shape"],
        transform=black_marble["transform"],
    )

    bilinear_values = reproject_to_reference(black_marble, viirs, Resampling.bilinear)
    nearest_values = reproject_to_reference(black_marble, viirs, Resampling.nearest)
    index_values = align_by_pixel_index(black_marble, viirs)

    comparisons = [
        compare_on_reference_grid(
            viirs,
            bilinear_values,
            viirs_mask,
            method="reproject_bilinear",
            method_note=(
                "Black Marble を VIIRS グリッドへ双一次内挿で再投影する（主指標）。"
                "解像度が等しいため、実質は原点の半画素ずれの補正である。"
            ),
        ),
        compare_on_reference_grid(
            viirs,
            nearest_values,
            viirs_mask,
            method="reproject_nearest",
            method_note=(
                "同じ再投影を最近傍で行う。内挿による平滑化が結論へ影響していないかを見る。"
            ),
        ),
        compare_on_reference_grid(
            viirs,
            index_values,
            viirs_mask,
            method="pixel_index_without_reprojection",
            method_note=(
                "再投影せず行列の索引だけで重ねる。半画素ずれを無視した誤った対応付けで、"
                "採用しない方法の影響を数値で示すために置いている。"
            ),
        ),
    ]

    # 飽和はソースデータの性質なので、再投影後ではなく双方の生データで評価する
    saturation_by_zone = compare_saturation_by_zone(
        viirs, viirs_mask, black_marble, black_marble_mask
    )

    resolved_summary_path = resolve_summary_path(year, summary_path)
    summary = build_summary(
        year=year,
        viirs_stats=describe_raster(viirs, viirs_mask),
        black_marble_stats=describe_raster(black_marble, black_marble_mask),
        grid_offset=compute_grid_offset(viirs, black_marble),
        comparisons=comparisons,
        saturation_by_zone=saturation_by_zone,
        roi_path=resolved_roi_path,
        summary_path=resolved_summary_path,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    save_summary(summary, resolved_summary_path)

    log_results(comparisons, saturation_by_zone)
    return resolved_summary_path


def log_results(comparisons: list[dict[str, Any]], saturation_by_zone: dict[str, Any]) -> None:
    """比較結果の要点をログへ出力する。

    Args:
        comparisons: 載せ替え方法ごとの比較結果。
        saturation_by_zone: 都心・外縁での広がりの比較。
    """
    for comparison in comparisons:
        agreement = comparison["agreement"]
        if agreement.get("cell_count", 0) == 0:
            logger.warning("%s: 比較対象画素がありません。", comparison["method"])
            continue
        correlation_note = agreement.get("correlation_note")
        correlation_text = (
            correlation_note
            if correlation_note is not None
            else (
                f"Pearson r = {agreement['pearson_r']:.4f} / "
                f"Spearman ρ = {agreement['spearman_rho']:.4f}"
            )
        )
        logger.info(
            "%s（%d画素）: %s / 平均バイアス %.3f / 中央値 %.3f / RMSE %.3f",
            comparison["method"],
            agreement["cell_count"],
            correlation_text,
            agreement["mean_bias"],
            agreement["median_bias"],
            agreement["root_mean_squared_error"],
        )

    for zone_name in ("inner", "outer"):
        zone = saturation_by_zone.get(zone_name, {})
        for dataset_name, zone_stats in zone.items():
            if zone_stats is None:
                logger.warning("%s / %s: 有効画素がありません。", zone_name, dataset_name)
                continue
            logger.info(
                "%s / %s: 中央値 %.3f p99 %.3f max %.3f（p99−中央値 = %.3f）",
                zone_name,
                dataset_name,
                zone_stats["statistics"]["median"],
                zone_stats["statistics"]["p99"],
                zone_stats["statistics"]["max"],
                zone_stats["p99_minus_median"],
            )


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    summary_path = run(
        year=args.year,
        viirs_path=args.viirs_path,
        black_marble_path=args.black_marble_path,
        roi_path=args.roi_path,
        summary_path=args.summary_path,
    )
    print(f"比較サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
