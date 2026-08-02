"""ラスタ取得の対象範囲の組み立て・クリップ・被覆の判定。

ROI または試行実行用 BBOX から取得対象範囲を作る処理、その範囲でラスタを切り出す
処理、取得結果がその範囲を覆えているかを判定する処理を集約する。取得元
（GEE・HTTP 配布サイト・ローカル）に依存しないため、データソース別のモジュールからは
独立させている。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import array_bounds
from shapely.geometry import box

from src.common.config import WGS84_CRS
from src.common.paths import resolve_existing_path
from src.common.roi import load_roi_geometry

logger = logging.getLogger(__name__)

# 取得ラスタの出力 nodata。取得スクリプト間で値を揃えるためここに置く。
DEFAULT_RASTER_NODATA = -9999.0

# 被覆判定で許容する座標のずれ（度）。約 0.1mm 相当で、実質的に浮動小数点誤差のみを吸収する。
COVERAGE_TOLERANCE_DEG = 1e-9


def validate_bbox(bbox: list[float]) -> None:
    """試行実行用 BBOX の妥当性を検証する。

    min と max を逆に渡すと `shapely.box` は不正なポリゴンを作り、例外ではなく
    「空の結果」として処理が進んでしまう。取得結果が 0 件でも気づきにくいため、
    ここで弾く。

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat)。

    Raises:
        ValueError: 要素数が 4 でない場合、最小値が最大値以上の場合、
            または経緯度の値域を外れる場合。
    """
    if len(bbox) != 4:
        raise ValueError(f"BBOX は (min_lon, min_lat, max_lon, max_lat) の 4 要素です: {bbox}")

    min_lon, min_lat, max_lon, max_lat = bbox
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError(
            "BBOX の最小値は最大値より小さい必要があります"
            f"（経度: {min_lon} < {max_lon}、緯度: {min_lat} < {max_lat}）。"
        )
    if not (-180.0 <= min_lon and max_lon <= 180.0 and -90.0 <= min_lat and max_lat <= 90.0):
        raise ValueError(f"BBOX が経緯度の値域を外れています: {bbox}")


def build_target_area(
    roi_path: Path,
    bbox: list[float] | None,
) -> tuple[gpd.GeoDataFrame, bool, Path]:
    """取得対象範囲の GeoDataFrame を作る。

    `bbox` を指定した場合は試行実行用の矩形を、未指定の場合は ROI を返す。

    Args:
        roi_path: ROI の Shapefile パス。
        bbox: (min_lon, min_lat, max_lon, max_lat)。未指定なら ROI を使う。

    Returns:
        (対象範囲, 試行実行かどうか, 解決済み ROI パス)。
        サマリーへ記録するパスは、読み込みに使ったものと同一にするため
        解決済みのものを返す（実行時のカレントディレクトリに依存させない）。
    """
    if bbox is None:
        # 相対パスを実行時のカレントディレクトリに依存させないため、先に解決する
        resolved_roi_path = resolve_existing_path(roi_path)
        roi_gdf, _ = load_roi_geometry(resolved_roi_path)
        return roi_gdf, False, resolved_roi_path

    validate_bbox(bbox)
    trial_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs=WGS84_CRS)
    logger.warning("試行実行モードです（BBOX: %s）。ROI 全域ではありません。", bbox)
    # 試行実行では ROI を読まないが、記録の一貫性のため同じ解決を通す
    return trial_gdf, True, resolve_existing_path(roi_path)


def covers_requested_area(
    raster_bounds: tuple[float, float, float, float],
    requested_bounds: tuple[float, float, float, float],
    tolerance: float = COVERAGE_TOLERANCE_DEG,
) -> bool:
    """出力ラスタが、要求した範囲の BBOX を覆いきれているかを判定する。

    `valid_pixel_ratio` の分母はクリップ後の窓に含まれる画素だけを数えるため、
    データソースが要求範囲を覆っていない場合でも 1.0 になりうる。覆えていない
    ぶんは出力にも分母にも現れず、欠測として検知できないためこの判定を併記する。

    `mask(crop=True)` は要求範囲を含むように画素境界へ外向きに丸めるため、
    ソースが範囲を覆っていれば出力 BBOX は要求範囲を必ず包含する。したがって
    許容するのは座標計算の浮動小数点誤差だけでよい。画素サイズを許容量にすると、
    1 画素分の実際の欠損を「覆えている」と誤判定する。

    Args:
        raster_bounds: 出力ラスタの (minx, miny, maxx, maxy)。
        requested_bounds: 要求範囲の (minx, miny, maxx, maxy)。同じ CRS であること。
        tolerance: 許容する座標のずれ（CRS の単位。既定は度）。

    Returns:
        覆いきれていれば True。
    """
    return (
        raster_bounds[0] <= requested_bounds[0] + tolerance
        and raster_bounds[1] <= requested_bounds[1] + tolerance
        and raster_bounds[2] >= requested_bounds[2] - tolerance
        and raster_bounds[3] >= requested_bounds[3] - tolerance
    )


@dataclass(frozen=True)
class ClippedArea:
    """`read_clipped_float_array` の結果をまとめて返す。

    Attributes:
        array: クリップ後の 3 次元配列（バンド, 行, 列）。float32 で、無効値は
            すべて `nodata` に統一済み。
        transform: クリップ後のアフィン変換。
        crs: ソースの CRS（出力もこれに合わせる）。
        area_mask: 対象範囲内を True とする 2 次元マスク。
        covers_area: ソースが要求範囲を覆えていたか。
    """

    array: np.ndarray
    transform: Any
    crs: Any
    area_mask: np.ndarray
    covers_area: bool


def read_clipped_float_array(
    source_path: Path,
    area_gdf: gpd.GeoDataFrame,
    nodata: float = DEFAULT_RASTER_NODATA,
    coverage_tolerance: float = COVERAGE_TOLERANCE_DEG,
    require_geographic: bool = False,
) -> ClippedArea:
    """ラスタを対象範囲でクリップし、無効値を統一した float32 配列として読む。

    書き出しは行わない。取得スクリプトによって出力バンドの構成が異なる
    （そのまま出す／派生バンドを足す）ため、**読み取りと書き出しを分けて**
    読み取り側だけを共有する。

    「宣言した無効値がすべての無効画素を覆う」ことをここで保証する。

    - **無効値の埋め込みは float32 へ変換した後に行う**。`rasterio.mask.mask` に
      `nodata` を渡すと、ソースの dtype のまま埋めてしまう。整数のソースへ -9999 を
      渡すと回り込んで（uint16 なら 55537）別の値になり、宣言した無効値がファイル内に
      一切存在しない状態になる。統計は `area_mask` で絞るため `valid_pixel_ratio` は
      1.0 のままで、サマリーからは検知できない。
    - **ソースに含まれる NaN も `nodata` へ置き換える**。NaN を残すと `x != nodata` の
      判定をすり抜けて「有効画素」に数えられ、統計が NaN になる。その NaN はサマリー
      保存時にようやく例外になるため、GeoTIFF だけ書き終えた中途半端な状態で止まる。

    ROI ポリゴンで真にクリップするため結果は BBOX 矩形となり、範囲外の余白は nodata
    で埋まる。その余白を欠測と数えないよう、範囲内を示すマスクを併せて返す。

    Args:
        source_path: 入力 GeoTIFF パス。
        area_gdf: 取得対象範囲（CRS はソースへ変換して用いる）。
        nodata: 無効値。
        coverage_tolerance: 被覆判定で許容する座標のずれ。**単位はソースの CRS に従う**
            ため、投影座標系のソースを扱う場合は既定値（度想定）を見直すこと。
        require_geographic: True なら地理座標系（度単位）のソースのみ受け付ける。
            セル面積を「辺が度」として求める処理へ渡す場合に指定する。呼び出し側で
            別途 `rasterio.open` して検証すると同じファイルを二度開くことになるため、
            ここで開いているうちに確かめる。

    Returns:
        クリップ後の配列と、統計計算に必要なマスク・被覆判定。

    Raises:
        ValueError: ソースの CRS が未定義の場合、または `require_geographic` を
            指定したのにソースが地理座標系でない場合。
    """
    with rasterio.open(source_path) as source:
        if source.crs is None:
            raise ValueError(f"ソースラスタの CRS が未定義です: {source_path}")
        source_crs = source.crs
        # クリップより前に弾く。後段で気づくと、範囲が重ならない等の分かりにくい
        # エラーに化けて原因が読めなくなる
        if require_geographic and not CRS.from_user_input(source_crs).is_geographic:
            raise ValueError(
                "地理座標系（度単位）のラスタのみに対応しています"
                f"（検出した CRS: {source_crs.to_string()}）。"
            )
        area_in_source_crs = area_gdf.to_crs(source_crs)
        shapes = [geometry.__geo_interface__ for geometry in area_in_source_crs.geometry]
        # filled=False でマスク配列のまま受け取り、float32 化してから埋める。
        # rasterio 側は ROI 外に加えてソース自身の nodata もマスクしてくれるため、
        # 両者をまとめて出力の nodata へ統一できる。
        clipped_masked, clipped_transform = mask(source, shapes=shapes, crop=True, filled=False)

    clipped_array = np.ma.filled(clipped_masked.astype(np.float32), np.float32(nodata))
    # ソース由来の NaN も無効値として扱う（有効画素の判定をすり抜けさせない）
    clipped_array[np.isnan(clipped_array)] = np.float32(nodata)
    _, height, width = clipped_array.shape

    # ジオメトリは clipped_transform と同じソース CRS のものを使う（座標系がずれると
    # 範囲内画素数・有効率が静かに壊れるため）
    area_mask = geometry_mask(
        geometries=shapes,
        out_shape=(height, width),
        transform=clipped_transform,
        invert=True,
    )
    covers_area = covers_requested_area(
        raster_bounds=array_bounds(height, width, clipped_transform),
        requested_bounds=tuple(float(value) for value in area_in_source_crs.total_bounds),
        tolerance=coverage_tolerance,
    )
    return ClippedArea(
        array=clipped_array,
        transform=clipped_transform,
        crs=source_crs,
        area_mask=area_mask,
        covers_area=covers_area,
    )


def build_raster_profile_record(raster_path: Path) -> dict[str, Any]:
    """書き出した GeoTIFF の諸元を、サマリー記録用の辞書として読み直す。

    書き出し時の値をそのまま写すのではなくファイルから読み直すのは、
    実際に保存された内容を記録するため。

    Args:
        raster_path: 対象 GeoTIFF パス。

    Returns:
        CRS・dtype・バンド数・寸法・解像度・範囲・nodata を含む辞書。
    """
    with rasterio.open(raster_path) as raster:
        bounds = raster.bounds
        return {
            "crs": raster.crs.to_string() if raster.crs is not None else None,
            "dtype": str(raster.dtypes[0]),
            "band_count": int(raster.count),
            "width": int(raster.width),
            "height": int(raster.height),
            "resolution": [float(raster.res[0]), float(raster.res[1])],
            "bounds": {
                "minx": float(bounds.left),
                "miny": float(bounds.bottom),
                "maxx": float(bounds.right),
                "maxy": float(bounds.top),
            },
            "nodata": None if raster.nodata is None else float(raster.nodata),
        }


def write_float_raster(
    output_path: Path,
    band_arrays: dict[str, np.ndarray],
    transform: Any,
    crs: Any,
    nodata: float = DEFAULT_RASTER_NODATA,
) -> None:
    """バンド名つきの float32 GeoTIFF を書き出す。

    ソースの profile を引き継がず、**保存形式をここで明示的に決める**。引き継ぐと、
    バンド数・dtype を変えた出力とソース由来のタイル設定や photometric が
    噛み合わないことがある。一方でまったく指定しないと、ソースが圧縮されていた
    場合に出力だけ無圧縮になり、研究データが不必要に大きくなる。

    圧縮は可逆の DEFLATE に、`predictor=3`（浮動小数点用）を併用する。研究データは
    Drive 同期の対象で容量が効いてくるため、値を変えずに縮む設定を既定にする。

    Args:
        output_path: 出力パス。
        band_arrays: バンド名 -> 2 次元配列（辞書の順序がバンド順になる）。
        transform: アフィン変換。
        crs: 出力の CRS。
        nodata: 無効値。

    Raises:
        ValueError: バンドが空の場合、またはバンド間で配列の形状が揃っていない場合。
    """
    if not band_arrays:
        raise ValueError("書き出すバンドがありません。")
    # 形状が揃っていないと、先頭バンドの寸法で profile を組んだまま書き込みが失敗するか、
    # 通ってしまった場合にバンドごとに意味の違う範囲を持つ成果物になる
    shapes = {name: array.shape for name, array in band_arrays.items()}
    if len(set(shapes.values())) != 1:
        raise ValueError(f"バンド間で配列の形状が揃っていません: {shapes}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    height, width = next(iter(shapes.values()))
    profile = {
        "driver": "GTiff",
        "count": len(band_arrays),
        "dtype": "float32",
        "height": height,
        "width": width,
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        # 浮動小数点向けの予測子。可逆で、隣接画素が近い値のラスタでよく縮む
        "predictor": 3,
    }
    with rasterio.open(output_path, "w", **profile) as destination:
        for index, (name, array) in enumerate(band_arrays.items(), start=1):
            destination.write(array, index)
            destination.set_band_description(index, name)


@dataclass(frozen=True)
class ClipResult:
    """`clip_multiband_to_area` の結果をまとめて返す。

    Attributes:
        raster_profile: 書き出した GeoTIFF の諸元（サマリー記録用）。
        band_arrays: 出力バンド名 -> クリップ後の 2 次元配列。
        area_mask: 対象範囲内を True とする 2 次元マスク。
        covers_area: 出力が要求範囲を覆えているか。
    """

    raster_profile: dict[str, Any]
    band_arrays: dict[str, np.ndarray]
    area_mask: np.ndarray
    covers_area: bool


def clip_multiband_to_area(
    source_path: Path,
    area_gdf: gpd.GeoDataFrame,
    output_path: Path,
    band_names: list[str],
    nodata: float = DEFAULT_RASTER_NODATA,
    coverage_tolerance: float = COVERAGE_TOLERANCE_DEG,
) -> ClipResult:
    """多バンドラスタを対象範囲でクリップし、バンド名つきの GeoTIFF として保存する。

    ソースのバンドをそのまま出力する場合の定型処理。派生バンドを足す場合は
    `read_clipped_float_array` と `write_float_raster` を個別に使う。

    無効値の扱い（float32 化してから埋める・NaN も統一する）は
    `read_clipped_float_array` に委ねている。

    入力のバンド数と `band_names` の要素数が一致すること、および `band_names` に
    重複が無いことを要求する。どちらも、崩れるとバンド名の割り当てがずれたまま
    例外にならず、単位の異なる値に別の名前が付いた成果物が黙って出来上がるため。

    Args:
        source_path: 入力 GeoTIFF パス。
        area_gdf: 取得対象範囲（CRS はソースへ変換して用いる）。
        output_path: 出力 GeoTIFF パス。
        band_names: 入力バンド順に対応する出力バンド名（重複不可）。
        nodata: 出力の無効値。
        coverage_tolerance: 被覆判定で許容する座標のずれ。**単位はソースの CRS に従う**
            ため、投影座標系のソースを扱う場合は既定値（度想定）を見直すこと。

    Returns:
        書き出し結果と、統計計算に必要な配列・マスク。

    Raises:
        ValueError: ソースの CRS が未定義の場合、バンド数が `band_names` の要素数と
            一致しない場合、または `band_names` に重複がある場合。
    """
    duplicated = sorted({name for name in band_names if band_names.count(name) > 1})
    if duplicated:
        raise ValueError(
            f"出力バンド名が重複しています: {duplicated}。"
            "重複するとバンドと名前の対応が崩れるため停止します。"
        )

    clipped = read_clipped_float_array(
        source_path=source_path,
        area_gdf=area_gdf,
        nodata=nodata,
        coverage_tolerance=coverage_tolerance,
    )
    if clipped.array.shape[0] != len(band_names):
        raise ValueError(
            "ソースラスタのバンド数が想定と異なります"
            f"（想定 {len(band_names)}、実際 {clipped.array.shape[0]}）: {source_path}"
        )

    band_arrays = {name: clipped.array[index] for index, name in enumerate(band_names)}
    write_float_raster(
        output_path=output_path,
        band_arrays=band_arrays,
        transform=clipped.transform,
        crs=clipped.crs,
        nodata=nodata,
    )

    return ClipResult(
        raster_profile=build_raster_profile_record(output_path),
        band_arrays=band_arrays,
        area_mask=clipped.area_mask,
        covers_area=clipped.covers_area,
    )
