"""ハノイ ROI の位置図（本図＋ベトナム全図のインセット）を生成するモジュール。

ポスター・発表資料に貼る「研究対象地域はどこか」を示す図を、XYZ タイルの
ベースマップ上に描く。図の構成は次のとおり。

- 左: ROI 周辺の本図。ベースマップ・ROI 外郭・方位記号・スケールバー・経緯度目盛。
- 右上: ベトナム全図のインセット。国内での ROI の位置を示す。
- 右下: 凡例。
- 下端: ベースマップと境界データの出典表記。

座標系は Web メルカトル（EPSG:3857）で統一する。XYZ タイルがこの座標系で
配信されるため、タイルとベクタを重ねるには両者をこの座標系へそろえる必要がある。

**スケールバーは緯度補正を行う。** Web メルカトルは高緯度ほど距離が引き伸ばされる
ため、座標上の長さをそのまま地表距離として扱うと誤差が出る。

CLI として実行できる::

    python -m src.visualization.roi_location_map --output presentations/ROI.png

``--overlay`` を付けると、修士論文の図として ROI の上に要素を重ねて描く。
``survey`` は測量 GIS の有効域（都心部）、``stations`` は気温の観測所と、観測の選定に
用いた都心と郊外の距離帯（ホアンキエム湖からの距離）を重ねる::

    python -m src.visualization.roi_location_map --overlay survey \\
        --output thesis/figures/roi_survey_map.png --width-mm 150 --dpi 300
    python -m src.visualization.roi_location_map --overlay stations \\
        --output thesis/figures/stations_map.png --width-mm 150 --dpi 300
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath
from shapely.geometry import box

from src.common.config import DEFAULT_HANOI_ROI_PATH, HANOI_UTM_CRS, PROJECT_ROOT
from src.visualization import xyz_tiles

# Web メルカトル。XYZ タイルとベクタを重ねるための共通 CRS。
WEB_MERCATOR_CRS = "EPSG:3857"

# ベトナム国境（geoBoundaries ADM0）の既定パス。
DEFAULT_VIETNAM_BOUNDARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "gis"
    / "boundaries"
    / "vietnam"
    / "vietnam_Vietnam_Country_Boundary.shp"
)

# 境界データの出典表記。geoBoundaries は CC BY 4.0 のため表示義務がある。
BOUNDARY_ATTRIBUTION = "Boundaries: geoBoundaries (CC BY 4.0)"

# 投影法の注記。表示義務は無いが、図の読み方として残す。
PROJECTION_NOTE = "Projection: Web Mercator (EPSG:3857)"

# 本図の ROI 周囲に確保する余白（ROI の幅・高さに対する割合）。
MAP_MARGIN_RATIO = 0.06

# レイアウト寸法（mm）。図全体は最後に出力幅へ相似変換するため、
# ここでの絶対値ではなく比率が意味を持つ。
_MARGIN_MM = 3.0  # 図の外周余白
_TICK_GUTTER_LEFT_MM = 9.0  # 緯度目盛のラベル幅
_TICK_GUTTER_BOTTOM_MM = 6.0  # 経度目盛のラベル高さ
_MAP_HEIGHT_MM = 84.0  # 本図の描画高さ
_COLUMN_GAP_MM = 4.0  # 本図と右カラムの間隔
_RIGHT_COLUMN_MIN_MM = 28.0  # 右カラムの最小幅（凡例の文字が収まる幅）
_INSET_GAP_MM = 3.0  # インセットと凡例の間隔
_LEGEND_HEIGHT_MM = 12.0  # 凡例パネルの高さ
_CREDIT_STRIP_MM = 11.0  # 図下端の出典表記帯の高さ（3 行分）

# スケールバーに採る「切りのよい」長さ（km）。
_SCALEBAR_NICE_KM = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500)
# 本図の幅に対するスケールバーの目安の割合。
_SCALEBAR_TARGET_RATIO = 0.28

# 経緯度目盛に採る「切りのよい」間隔（度）。
_GRATICULE_NICE_DEG = (0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)

# 配色。ROI は緑の外郭とし、LST 図（暖色系）と競合させない。
ROI_EDGE_COLOR = "#1a9641"
INSET_ROI_COLOR = "#d7191c"
INSET_LAND_COLOR = "#e9e9e9"
INSET_EDGE_COLOR = "#8c8c8c"
CREDIT_TEXT_COLOR = "#555555"

# 図面文字の基準サイズ（pt）。ポスターに原寸で貼る前提で決める。
BASE_FONT_PT = 9.0

# 出典表記の文字サイズ（基準サイズに対する比）。細字の注記ではあるが、A1 ポスター
# へ縮小して貼ったときに手元で読める大きさが要る。1 行だった頃の 0.58 では、貼付幅
# で 5pt 台にしかならなかった。3 行へ分けて行長を 1/3 にしたぶん引き上げている。
# 凡例（0.85）と同程度に留め、注記が本文より目立つことは避ける。
_CREDIT_FONT_RATIO = 0.90

# 出典表記 1 行あたりの文字数の上限。上記の文字サイズで実測したところ、57 字の行が
# 表記帯の幅の 76.8% を占めた（1 字あたり約 1.35%）。帯の幅の 95% を上限とみなすと
# 70 字となる。これを超える出典表記のプロバイダを追加すると、行が帯からはみ出す。
CREDIT_MAX_LINE_CHARS = 70

# 研究対象地域の図で重ねる要素の配色。ROI（緑）と区別できる色を選ぶ。
SURVEY_EXTENT_COLOR = "#2b83ba"
BAND_COLOR = "#e66101"
STATION_COLOR = "#b2182b"

# 重ね描きの凡例 1 項目あたりに足す凡例パネルの高さと、右カラムの最小幅（mm）。
# 凡例の文言は 2 行に分けるものがあるため、1 項目を 2 行分として見積もる。
_OVERLAY_LEGEND_ROW_MM = 5.5
_OVERLAY_RIGHT_COLUMN_MIN_MM = 36.0

# 測量 GIS の有効域（都心部）の既定パス。
DEFAULT_SURVEY_EXTENT_PATH = PROJECT_ROOT / "data" / "gis" / "survey" / "hanoi_survey_extent.gpkg"


@dataclass(frozen=True)
class MapPoint:
    """図に記号と名前を描く地点。

    Attributes:
        label: 図に描く名前。
        lon: 経度（度、WGS84）。
        lat: 緯度（度、WGS84）。
    """

    label: str
    lon: float
    lat: float


@dataclass(frozen=True)
class StudyAreaOverlay:
    """研究対象地域の図で、ROI の上に重ねる要素の定義。

    各要素は省略でき、指定したものだけを描く。

    Attributes:
        survey_extent_path: 測量 GIS の有効域（都心部）のベクタファイル。``None`` で描かない。
        stations: 気温の観測所。
        center: 距離帯の中心点。``None`` で描かない。
        bands_km: 中心からの距離帯（内径 km, 外径 km）の並び。内径 0 は円板を表す。

    Raises:
        ValueError: 重ねる要素が 1 つもないとき、距離帯があるのに中心点がないとき。
    """

    survey_extent_path: Path | None = None
    stations: tuple[MapPoint, ...] = ()
    center: MapPoint | None = None
    bands_km: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        """要素の組み合わせを検査する。"""
        if self.survey_extent_path is None and not self.stations and self.center is None:
            raise ValueError("重ねる要素が 1 つも指定されていません。")
        if self.bands_km and self.center is None:
            raise ValueError("距離帯を描くには中心点が必要です。")


# ハノイの研究対象地域の図の既定値（CLI の ``--overlay`` で選ぶ）。
# survey: 測量 GIS の有効域（都心部）。
# stations: 観測所と距離帯。観測所の座標は NOAA ISD の観測所一覧（isd-history.csv）の値で、
# docs/03_results/observation_air_temperature_comparison.md 2章を正本とする。
# 中心点（ホアンキエム湖）と距離帯（都心 0〜5 km・郊外 15〜25 km）は、観測の選定で
# 都心と郊外の LST 差を求めた定義であり、
# docs/02_methods/observation_selection.md 8.2節を正本とする。
HANOI_SURVEY_OVERLAY = StudyAreaOverlay(survey_extent_path=DEFAULT_SURVEY_EXTENT_PATH)
HANOI_STATIONS_OVERLAY = StudyAreaOverlay(
    stations=(
        MapPoint("Noi Bai", lon=105.807, lat=21.221),
        MapPoint("Ha Dong", lon=105.767, lat=20.967),
    ),
    center=MapPoint("Hoan Kiem Lake", lon=105.852, lat=21.028),
    bands_km=((0.0, 5.0), (15.0, 25.0)),
)
OVERLAY_PRESETS = {"survey": HANOI_SURVEY_OVERLAY, "stations": HANOI_STATIONS_OVERLAY}

# 重ね描きの凡例の文言。右カラムに収めるため 2 行に分ける。
OVERLAY_LEGEND_LABELS = {
    "survey": "Survey GIS extent\n(city centre)",
    "stations": "Weather station\n(ISD)",
    "center": "Hoan Kiem Lake",
    "bands": "0–5 km and 15–25 km\nfrom the lake",
}


def overlay_legend_keys(overlay: StudyAreaOverlay) -> list[str]:
    """重ね描きの凡例に載せる項目を、凡例の行の順に返す。

    指定された要素だけを載せる（描かない要素を凡例に出さない）。

    Args:
        overlay: 重ねる要素の定義。

    Returns:
        :data:`OVERLAY_LEGEND_LABELS` のキーの並び。
    """
    keys = []
    if overlay.survey_extent_path is not None:
        keys.append("survey")
    if overlay.stations:
        keys.append("stations")
    if overlay.center is not None:
        keys.append("center")
    if overlay.bands_km:
        keys.append("bands")
    return keys


def overlay_legend_height_mm(item_count: int) -> float:
    """重ね描きの凡例の項目数から、凡例パネルの高さ（mm）を求める。

    Args:
        item_count: 重ね描きの凡例の項目数（ROI の行は含めない）。

    Returns:
        凡例パネルの高さ（mm）。ROI の行の分（既定の高さ）に項目ごとの高さを足す。

    Raises:
        ValueError: 項目数が負のとき。
    """
    if item_count < 0:
        raise ValueError(f"凡例の項目数が負です: {item_count}")
    return _LEGEND_HEIGHT_MM + _OVERLAY_LEGEND_ROW_MM * item_count


def band_geometries(
    center: MapPoint,
    bands_km: Sequence[tuple[float, float]],
    projected_crs: str = HANOI_UTM_CRS,
) -> gpd.GeoDataFrame:
    """中心点からの距離帯を多角形にして、Web メルカトルで返す。

    距離は投影座標系（既定は UTM 48N）で測る。観測の選定で都心と郊外を区分したときと
    同じ測り方にそろえるためである。内径が 0 の帯は円板、それ以外は穴のあいた環になる。

    Args:
        center: 距離帯の中心点。
        bands_km: （内径 km, 外径 km）の並び。
        projected_crs: 距離を測る投影座標系。

    Returns:
        列 ``inner_km``・``outer_km`` と距離帯の多角形を持つ GeoDataFrame（EPSG:3857）。

    Raises:
        ValueError: 距離帯が空のとき、内径が負のとき、外径が内径以下のとき。
    """
    if not bands_km:
        raise ValueError("距離帯が指定されていません。")
    for inner, outer in bands_km:
        if inner < 0 or outer <= inner:
            raise ValueError(f"距離帯の内径・外径が不正です: ({inner}, {outer})")

    point = (
        gpd.GeoSeries.from_xy([center.lon], [center.lat], crs="EPSG:4326")
        .to_crs(projected_crs)
        .iloc[0]
    )
    geometries = []
    for inner, outer in bands_km:
        # 円の近似の分割数を増やし、面積の誤差を小さくする（128 で 0.01% 未満）。
        disk = point.buffer(outer * 1000.0, quad_segs=128)
        if inner > 0:
            disk = disk.difference(point.buffer(inner * 1000.0, quad_segs=128))
        geometries.append(disk)
    bands = gpd.GeoDataFrame(
        {
            "inner_km": [inner for inner, _ in bands_km],
            "outer_km": [outer for _, outer in bands_km],
        },
        geometry=geometries,
        crs=projected_crs,
    )
    return bands.to_crs(WEB_MERCATOR_CRS)


def nice_scalebar_length_km(map_width_km: float) -> int:
    """本図の幅に対して見栄えのよいスケールバー長（km）を選ぶ。

    幅の ``_SCALEBAR_TARGET_RATIO`` に最も近い「切りのよい」長さを採る。

    Args:
        map_width_km: 本図が覆う地表距離（km）。

    Returns:
        スケールバーの長さ（km）。

    Raises:
        ValueError: 幅が正でないとき。
    """
    if map_width_km <= 0:
        raise ValueError(f"地図の幅が正ではありません: {map_width_km}")
    target = map_width_km * _SCALEBAR_TARGET_RATIO
    return min(_SCALEBAR_NICE_KM, key=lambda km: abs(km - target))


def graticule_ticks(minimum: float, maximum: float, target_count: int = 4) -> list[float]:
    """区間内の「切りのよい」経緯度目盛値を返す。

    目盛数が ``target_count`` に近くなる間隔を候補から選び、区間に入る値だけを返す。

    Args:
        minimum: 区間の下限（度）。
        maximum: 区間の上限（度）。
        target_count: 目安の目盛数。

    Returns:
        昇順の目盛値。区間が狭く 1 本も入らない場合は空リスト。

    Raises:
        ValueError: 区間が正でないとき、または目盛数が正でないとき。
    """
    if maximum <= minimum:
        raise ValueError(f"区間が正ではありません: ({minimum}, {maximum})")
    if target_count <= 0:
        raise ValueError(f"目盛数が正ではありません: {target_count}")

    span = maximum - minimum
    step = min(_GRATICULE_NICE_DEG, key=lambda s: abs(span / s - target_count))
    first = math.ceil(minimum / step)
    last = math.floor(maximum / step)
    # 浮動小数の丸め残りを避けるため、間隔の桁で丸めてから返す。
    digits = max(0, -math.floor(math.log10(step)) + 1)
    return [round(index * step, digits) for index in range(first, last + 1)]


def format_longitude(value: float) -> str:
    """経度を図面表記（例: ``105.6°E``）に整える。

    Args:
        value: 経度（度）。

    Returns:
        表記文字列。
    """
    hemisphere = "E" if value >= 0 else "W"
    return f"{abs(value):g}°{hemisphere}"


def format_latitude(value: float) -> str:
    """緯度を図面表記（例: ``21.0°N``）に整える。

    Args:
        value: 緯度（度）。

    Returns:
        表記文字列。
    """
    hemisphere = "N" if value >= 0 else "S"
    return f"{abs(value):g}°{hemisphere}"


def expand_extent(
    extent: tuple[float, float, float, float], ratio: float
) -> tuple[float, float, float, float]:
    """範囲の各辺に、幅・高さの割合分の余白を加える。

    Args:
        extent: ``(x_min, y_min, x_max, y_max)``。
        ratio: 余白の割合。

    Returns:
        拡張後の範囲。

    Raises:
        ValueError: 範囲の幅または高さが正でないとき、割合が負のとき。
    """
    x_min, y_min, x_max, y_max = extent
    if x_max <= x_min or y_max <= y_min:
        raise ValueError(f"範囲の幅・高さが正ではありません: {extent}")
    if ratio < 0:
        raise ValueError(f"余白の割合が負です: {ratio}")
    pad_x = (x_max - x_min) * ratio
    pad_y = (y_max - y_min) * ratio
    return x_min - pad_x, y_min - pad_y, x_max + pad_x, y_max + pad_y


def layout_rects(
    map_aspect: float,
    inset_aspect: float,
    legend_height_mm: float = _LEGEND_HEIGHT_MM,
    right_column_min_mm: float = _RIGHT_COLUMN_MIN_MM,
) -> tuple[float, float, dict[str, tuple[float, float, float, float]]]:
    """図全体の寸法と各軸の矩形（figure 座標）を計算する。

    本図とインセットは縦横比が入力データで決まるため、高さを固定して幅を導く。
    右カラムはインセットの幅と凡例の必要幅の大きい方を採る。凡例を高くすると、
    そのぶんインセットが低く（小さく）なる。

    Args:
        map_aspect: 本図の 高さ/幅。
        inset_aspect: インセットの 高さ/幅。
        legend_height_mm: 凡例パネルの高さ（mm）。
        right_column_min_mm: 右カラムの最小幅（mm）。凡例の文言が長いときに広げる。

    Returns:
        ``(図の幅mm, 図の高さmm, 軸名 -> (left, bottom, width, height) の辞書)``。
        矩形は figure 座標（0-1）。

    Raises:
        ValueError: 縦横比が正でないとき、凡例の高さが正でないとき、
            凡例が高すぎてインセットを置く高さが残らないとき。
    """
    if map_aspect <= 0 or inset_aspect <= 0:
        raise ValueError(f"縦横比が正ではありません: map={map_aspect}, inset={inset_aspect}")
    if legend_height_mm <= 0 or right_column_min_mm <= 0:
        raise ValueError(
            f"凡例の高さ・右カラムの幅が正ではありません: {legend_height_mm}, {right_column_min_mm}"
        )

    map_h = _MAP_HEIGHT_MM
    map_w = map_h / map_aspect
    inset_h = map_h - _INSET_GAP_MM - legend_height_mm
    if inset_h <= 0:
        raise ValueError(f"凡例が高すぎてインセットを置けません: {legend_height_mm} mm")
    inset_w = inset_h / inset_aspect
    right_w = max(inset_w, right_column_min_mm)

    fig_w = _MARGIN_MM + _TICK_GUTTER_LEFT_MM + map_w + _COLUMN_GAP_MM + right_w + _MARGIN_MM
    fig_h = _MARGIN_MM + _CREDIT_STRIP_MM + _TICK_GUTTER_BOTTOM_MM + map_h + _MARGIN_MM

    map_left = _MARGIN_MM + _TICK_GUTTER_LEFT_MM
    map_bottom = _MARGIN_MM + _CREDIT_STRIP_MM + _TICK_GUTTER_BOTTOM_MM
    right_left = map_left + map_w + _COLUMN_GAP_MM

    def _to_fraction(
        left: float, bottom: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        return (left / fig_w, bottom / fig_h, width / fig_w, height / fig_h)

    rects = {
        "map": _to_fraction(map_left, map_bottom, map_w, map_h),
        "inset": _to_fraction(
            right_left + (right_w - inset_w) / 2.0,
            map_bottom + map_h - inset_h,
            inset_w,
            inset_h,
        ),
        "legend": _to_fraction(right_left, map_bottom, right_w, legend_height_mm),
        "credit": _to_fraction(_MARGIN_MM, _MARGIN_MM, fig_w - 2.0 * _MARGIN_MM, _CREDIT_STRIP_MM),
    }
    return fig_w, fig_h, rects


def _halo(linewidth: float = 2.0) -> list:
    """文字・記号の可読性を確保する白フチ効果を返す。

    Args:
        linewidth: フチの太さ（pt）。

    Returns:
        ``path_effects`` に渡すリスト。
    """
    return [patheffects.withStroke(linewidth=linewidth, foreground="white")]


def _draw_north_arrow(axes: plt.Axes, font_pt: float) -> None:
    """本図の左上に方位記号を描く。

    Web メルカトルでは真北が画面上方と一致するため、単純な上向き矢印でよい。

    Args:
        axes: 本図の軸。
        font_pt: 文字サイズ（pt）。
    """
    x_center, y_base = 0.075, 0.855
    height, half_width = 0.075, 0.022
    vertices = [
        (x_center, y_base + height),
        (x_center - half_width, y_base),
        (x_center, y_base + height * 0.28),
        (x_center + half_width, y_base),
        (x_center, y_base + height),
    ]
    codes = [MplPath.MOVETO] + [MplPath.LINETO] * 3 + [MplPath.CLOSEPOLY]
    patch = PathPatch(
        MplPath(vertices, codes),
        transform=axes.transAxes,
        facecolor="black",
        edgecolor="white",
        linewidth=0.6,
        zorder=6,
    )
    axes.add_patch(patch)
    axes.text(
        x_center,
        y_base + height + 0.012,
        "N",
        transform=axes.transAxes,
        ha="center",
        va="bottom",
        fontsize=font_pt,
        fontweight="bold",
        color="black",
        zorder=6,
        path_effects=_halo(),
    )


def _draw_scalebar(axes: plt.Axes, center_latitude: float, font_pt: float) -> None:
    """本図の左下にスケールバーを描く。

    Web メルカトルの座標長は緯度 φ で ``1/cos(φ)`` 倍に伸びているため、
    地表距離 L km に対応する座標長は ``L / cos(φ)`` である。

    Args:
        axes: 本図の軸。
        center_latitude: 本図の中心緯度（度）。補正に使う。
        font_pt: 文字サイズ（pt）。
    """
    x_min, x_max = axes.get_xlim()
    y_min, y_max = axes.get_ylim()
    cos_lat = math.cos(math.radians(center_latitude))
    map_width_km = (x_max - x_min) * cos_lat / 1000.0

    bar_km = nice_scalebar_length_km(map_width_km)
    bar_span = bar_km * 1000.0 / cos_lat  # 座標上の長さ

    left = x_min + (x_max - x_min) * 0.055
    bottom = y_min + (y_max - y_min) * 0.045
    bar_height = (y_max - y_min) * 0.011

    # 2 分割の白黒バー。片側だけの単色より読み違いが起きにくい。
    for index, color in enumerate(("black", "white")):
        axes.add_patch(
            Rectangle(
                (left + bar_span / 2.0 * index, bottom),
                bar_span / 2.0,
                bar_height,
                facecolor=color,
                edgecolor="black",
                linewidth=0.5,
                zorder=6,
            )
        )
    for value, position in ((0, left), (bar_km, left + bar_span)):
        axes.text(
            position,
            bottom + bar_height * 1.6,
            f"{value}",
            ha="center",
            va="bottom",
            fontsize=font_pt * 0.8,
            zorder=6,
            path_effects=_halo(),
        )
    axes.text(
        left + bar_span * 1.05,
        bottom + bar_height * 0.5,
        "km",
        ha="left",
        va="center",
        fontsize=font_pt * 0.8,
        zorder=6,
        path_effects=_halo(),
    )


def _apply_graticule(axes: plt.Axes, font_pt: float) -> None:
    """本図に経緯度の目盛とラベルを付ける。

    軸はメルカトル座標だが、読み手に必要なのは経緯度であるため、
    目盛位置だけをメルカトルへ変換してラベルは度で書く。

    Args:
        axes: 本図の軸。
        font_pt: 文字サイズ（pt）。
    """
    x_min, x_max = axes.get_xlim()
    y_min, y_max = axes.get_ylim()
    lon_min, lat_min = xyz_tiles.mercator_to_lonlat(x_min, y_min)
    lon_max, lat_max = xyz_tiles.mercator_to_lonlat(x_max, y_max)

    lon_ticks = graticule_ticks(lon_min, lon_max)
    lat_ticks = graticule_ticks(lat_min, lat_max)
    axes.set_xticks([xyz_tiles.lonlat_to_mercator(lon, 0.0)[0] for lon in lon_ticks])
    axes.set_yticks([xyz_tiles.lonlat_to_mercator(0.0, lat)[1] for lat in lat_ticks])
    axes.set_xticklabels([format_longitude(lon) for lon in lon_ticks])
    axes.set_yticklabels([format_latitude(lat) for lat in lat_ticks])
    axes.tick_params(
        axis="both", which="major", labelsize=font_pt * 0.78, length=2.0, width=0.5, pad=1.5
    )
    for spine in axes.spines.values():
        spine.set_linewidth(0.7)
        spine.set_color("black")


def _draw_inset(
    axes: plt.Axes,
    country: gpd.GeoDataFrame,
    roi: gpd.GeoDataFrame,
    font_pt: float,
) -> None:
    """右上のインセット（ベトナム全図と ROI の位置）を描く。

    Args:
        axes: インセットの軸。
        country: 国境（Web メルカトル）。
        roi: ROI（Web メルカトル）。
        font_pt: 文字サイズ（pt）。
    """
    country.plot(ax=axes, facecolor=INSET_LAND_COLOR, edgecolor=INSET_EDGE_COLOR, linewidth=0.5)
    roi.plot(ax=axes, facecolor=INSET_ROI_COLOR, edgecolor=INSET_ROI_COLOR, linewidth=0.6)

    x_min, y_min, x_max, y_max = expand_extent(tuple(country.total_bounds), 0.04)
    axes.set_xlim(x_min, x_max)
    axes.set_ylim(y_min, y_max)
    axes.set_xticks([])
    axes.set_yticks([])
    for spine in axes.spines.values():
        spine.set_linewidth(0.7)
        spine.set_color("black")

    centroid = roi.geometry.iloc[0].centroid
    axes.annotate(
        "Hanoi",
        xy=(centroid.x, centroid.y),
        xytext=(0.50, 0.92),
        textcoords="axes fraction",
        fontsize=font_pt * 0.8,
        color=INSET_ROI_COLOR,
        fontweight="bold",
        ha="left",
        va="center",
        arrowprops={"arrowstyle": "-", "color": INSET_ROI_COLOR, "linewidth": 0.6},
    )
    axes.text(
        0.06,
        0.04,
        "Vietnam",
        transform=axes.transAxes,
        fontsize=font_pt * 0.8,
        color="#404040",
        ha="left",
        va="bottom",
    )


def _draw_overlay(axes: plt.Axes, overlay: StudyAreaOverlay, font_pt: float) -> None:
    """本図に、指定された要素（測量 GIS の有効域・距離帯・中心点・観測所）を重ねて描く。

    Args:
        axes: 本図の軸（Web メルカトル）。
        overlay: 重ねる要素の定義。
        font_pt: 文字サイズ（pt）。

    Raises:
        FileNotFoundError: 測量 GIS の有効域のファイルが存在しないとき。
        ValueError: 測量 GIS の有効域に座標系が無いとき。
    """
    if overlay.survey_extent_path is not None:
        _draw_survey_extent(axes, overlay.survey_extent_path)
    if overlay.bands_km and overlay.center is not None:
        bands = band_geometries(overlay.center, overlay.bands_km)
        bands.plot(ax=axes, facecolor=BAND_COLOR, edgecolor="none", alpha=0.10, zorder=3)
        bands.boundary.plot(ax=axes, color=BAND_COLOR, linewidth=0.8, linestyle="--", zorder=3)
    if overlay.center is not None:
        center_x, center_y = xyz_tiles.lonlat_to_mercator(overlay.center.lon, overlay.center.lat)
        axes.plot(center_x, center_y, marker="*", color="black", markersize=font_pt * 0.9, zorder=5)
    for station in overlay.stations:
        x, y = xyz_tiles.lonlat_to_mercator(station.lon, station.lat)
        axes.plot(
            x,
            y,
            marker="^",
            color=STATION_COLOR,
            markeredgecolor="white",
            markeredgewidth=0.5,
            markersize=font_pt * 0.75,
            zorder=5,
        )
        axes.annotate(
            station.label,
            xy=(x, y),
            xytext=(4, 3),
            textcoords="offset points",
            fontsize=font_pt * 0.75,
            color=STATION_COLOR,
            fontweight="bold",
            zorder=6,
            path_effects=_halo(),
        )


def _draw_survey_extent(axes: plt.Axes, extent_path: Path) -> None:
    """本図に測量 GIS の有効域を塗りつぶして描く。

    Args:
        axes: 本図の軸（Web メルカトル）。
        extent_path: 測量 GIS の有効域のベクタファイル。

    Raises:
        FileNotFoundError: ファイルが存在しないとき。
        ValueError: 座標系が無いとき。
    """
    if not extent_path.exists():
        raise FileNotFoundError(f"測量 GIS の有効域のファイルが見つかりません: {extent_path}")
    survey = gpd.read_file(extent_path)
    if survey.crs is None:
        # 座標系が無いまま変換すると位置がずれるため、推測で補わずに止める。
        raise ValueError(f"測量 GIS の有効域に座標系がありません: {extent_path}")
    survey.to_crs(WEB_MERCATOR_CRS).plot(
        ax=axes,
        facecolor=SURVEY_EXTENT_COLOR,
        edgecolor=SURVEY_EXTENT_COLOR,
        alpha=0.35,
        linewidth=0.8,
        zorder=4,
    )


def _overlay_legend_handles(overlay: StudyAreaOverlay) -> list:
    """重ね描きの凡例の記号を、:func:`overlay_legend_keys` の順に返す。

    Args:
        overlay: 重ねる要素の定義。

    Returns:
        ``legend`` に渡すハンドルのリスト。
    """
    labels = OVERLAY_LEGEND_LABELS
    handle_by_key = {
        "survey": Patch(
            facecolor=SURVEY_EXTENT_COLOR,
            edgecolor=SURVEY_EXTENT_COLOR,
            alpha=0.35,
            label=labels["survey"],
        ),
        "stations": Line2D(
            [0],
            [0],
            marker="^",
            color=STATION_COLOR,
            linestyle="none",
            markeredgecolor="white",
            label=labels["stations"],
        ),
        "center": Line2D(
            [0], [0], marker="*", color="black", linestyle="none", label=labels["center"]
        ),
        "bands": Line2D(
            [0], [0], color=BAND_COLOR, linewidth=0.8, linestyle="--", label=labels["bands"]
        ),
    }
    return [handle_by_key[key] for key in overlay_legend_keys(overlay)]


def _draw_legend_panel(
    axes: plt.Axes,
    font_pt: float,
    roi_area_km2: float | None,
    overlay: StudyAreaOverlay | None = None,
) -> None:
    """右下に凡例を描く。

    Args:
        axes: 凡例パネルの軸。
        font_pt: 文字サイズ（pt）。
        roi_area_km2: ROI 面積（km²）。``None`` なら面積行を出さない。
        overlay: 重ねる要素の定義。指定すると、その要素の凡例も載せる。
    """
    axes.set_axis_off()
    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.0)

    handles = [Line2D([0], [0], color=ROI_EDGE_COLOR, linewidth=1.6, label="Hanoi ROI")]
    if overlay is not None:
        handles.extend(_overlay_legend_handles(overlay))
    axes.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        frameon=False,
        fontsize=font_pt * 0.85,
        handlelength=1.8,
        handletextpad=0.5,
        borderpad=0.0,
        borderaxespad=0.0,
    )
    if roi_area_km2 is not None:
        axes.text(
            0.0,
            0.42,
            f"Area: {roi_area_km2:,.0f} km²",
            transform=axes.transAxes,
            fontsize=font_pt * 0.78,
            color="#404040",
            ha="left",
            va="top",
        )


def credit_lines(attribution: str) -> list[str]:
    """出典表記帯に描く行を組み立てる。

    1 行に詰めると図幅をほぼ使い切ってしまい、文字を大きくできない。1 行 1 項目に
    分けて行長を抑え、そのぶん文字サイズを確保する。表示義務のある表記（タイル
    配信元・geoBoundaries）を先に置き、義務の無い投影法の注記を最後に回す。

    Args:
        attribution: タイル配信元の表記。

    Returns:
        上から順に並べる行のリスト。

    Raises:
        ValueError: `attribution` が空のとき。出典表記は利用条件であり、
            空のまま図を出力してはならない。
    """
    if not attribution.strip():
        raise ValueError("タイル配信元の出典表記が空です。")
    return [attribution, BOUNDARY_ATTRIBUTION, PROJECTION_NOTE]


def _draw_credit_strip(axes: plt.Axes, attribution: str, font_pt: float) -> None:
    """図の下端にベースマップ・境界データの出典表記を描く。

    タイル配信元・geoBoundaries ともに出典表記が利用条件であるため省略しない。

    Args:
        axes: 出典表記帯の軸。
        attribution: タイル配信元の表記。
        font_pt: 文字サイズ（pt）。
    """
    axes.set_axis_off()
    lines = credit_lines(attribution)
    # 上の行から順に、帯の高さを行数で等分した位置へ置く。
    for index, line in enumerate(lines):
        axes.text(
            0.0,
            1.0 - (index + 0.5) / len(lines),
            line,
            transform=axes.transAxes,
            fontsize=font_pt * _CREDIT_FONT_RATIO,
            color=CREDIT_TEXT_COLOR,
            ha="left",
            va="center",
        )


def build_roi_location_map(
    output_path: Path,
    roi_path: Path = DEFAULT_HANOI_ROI_PATH,
    country_path: Path = DEFAULT_VIETNAM_BOUNDARY_PATH,
    provider_name: str = "osm",
    width_mm: float = 120.0,
    dpi: int = 400,
    margin_ratio: float = MAP_MARGIN_RATIO,
    dim_outside: bool = True,
    light_tone: bool = True,
    cache_dir: Path | None = None,
    overlay: StudyAreaOverlay | None = None,
) -> Path:
    """ROI 位置図を生成して PNG として保存する。

    ``overlay`` を渡すと、研究対象地域の図として、指定した要素（測量 GIS の有効域・
    距離帯・観測所）を重ねて描く。このとき凡例の ROI 面積の行は出さない（面積は図から算出せず、
    本文で正本の値を示すため）。

    Args:
        output_path: 出力 PNG のパス。親ディレクトリは自動作成する。
        roi_path: ROI のベクタファイル。
        country_path: 国境のベクタファイル。
        provider_name: :data:`xyz_tiles.PROVIDERS` のキー。
        width_mm: 出力画像の物理幅（mm）。ポスターへの貼付幅に合わせる。
        dpi: 出力解像度。
        margin_ratio: 本図で ROI の周囲に確保する余白の割合。
        dim_outside: ROI の外側を白く薄める（ROI を目立たせる）か。
        light_tone: ベースマップを淡色調へ落とすか。
        cache_dir: タイルキャッシュのルート。``None`` で既定値。
        overlay: 重ねる要素の定義。``None`` なら従来どおり ROI だけを描く。

    Returns:
        保存した PNG のパス。

    Raises:
        FileNotFoundError: 入力ベクタが存在しないとき。
        KeyError: ``provider_name`` が未定義のとき。
        ValueError: 出力幅・解像度が正でないとき。
    """
    for path in (roi_path, country_path):
        if not path.exists():
            raise FileNotFoundError(f"入力ファイルが見つかりません: {path}")
    if provider_name not in xyz_tiles.PROVIDERS:
        raise KeyError(
            f"未定義のタイル配信元です: {provider_name!r} (利用可能: {sorted(xyz_tiles.PROVIDERS)})"
        )
    if width_mm <= 0 or dpi <= 0:
        raise ValueError(f"出力幅・解像度が正ではありません: width_mm={width_mm}, dpi={dpi}")

    provider = xyz_tiles.PROVIDERS[provider_name]
    roi = gpd.read_file(roi_path).to_crs(WEB_MERCATOR_CRS)
    country = gpd.read_file(country_path).to_crs(WEB_MERCATOR_CRS)

    map_extent = expand_extent(tuple(roi.total_bounds), margin_ratio)
    x_min, y_min, x_max, y_max = map_extent
    map_aspect = (y_max - y_min) / (x_max - x_min)

    country_bounds = expand_extent(tuple(country.total_bounds), 0.04)
    inset_aspect = (country_bounds[3] - country_bounds[1]) / (country_bounds[2] - country_bounds[0])

    if overlay is None:
        layout_w_mm, layout_h_mm, rects = layout_rects(map_aspect, inset_aspect)
    else:
        layout_w_mm, layout_h_mm, rects = layout_rects(
            map_aspect,
            inset_aspect,
            legend_height_mm=overlay_legend_height_mm(len(overlay_legend_keys(overlay))),
            right_column_min_mm=_OVERLAY_RIGHT_COLUMN_MIN_MM,
        )
    fig_w_in = width_mm / 25.4
    fig_h_in = fig_w_in * layout_h_mm / layout_w_mm
    # レイアウト基準幅からの拡大率。文字サイズを出力幅に追随させる。
    font_pt = BASE_FONT_PT * (width_mm / layout_w_mm)

    # 本図の横ピクセル数に合わせてズームを選ぶ。引き伸ばしによる劣化を避ける。
    map_width_px = int(round(fig_w_in * dpi * rects["map"][2]))
    zoom = xyz_tiles.select_zoom(map_extent, map_width_px, provider)
    mosaic, mosaic_ext = xyz_tiles.fetch_mosaic(map_extent, zoom, provider, cache_dir)
    if light_tone:
        mosaic = xyz_tiles.apply_light_tone(mosaic)

    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=dpi)
    fig.patch.set_facecolor("white")

    axes = fig.add_axes(rects["map"])
    axes.imshow(
        np.asarray(mosaic),
        extent=(mosaic_ext[0], mosaic_ext[2], mosaic_ext[1], mosaic_ext[3]),
        interpolation="bilinear",
        zorder=1,
    )
    axes.set_xlim(x_min, x_max)
    axes.set_ylim(y_min, y_max)
    axes.set_aspect("equal")

    if dim_outside:
        outside = box(x_min, y_min, x_max, y_max).difference(roi.geometry.union_all())
        gpd.GeoSeries([outside], crs=WEB_MERCATOR_CRS).plot(
            ax=axes, facecolor="white", edgecolor="none", alpha=0.45, zorder=2
        )
    roi.boundary.plot(ax=axes, color=ROI_EDGE_COLOR, linewidth=1.6, zorder=3)
    if overlay is not None:
        _draw_overlay(axes, overlay, font_pt)
        # 距離帯が ROI の外へはみ出しても、本図の範囲は ROI に合わせたまま保つ。
        axes.set_xlim(x_min, x_max)
        axes.set_ylim(y_min, y_max)

    _apply_graticule(axes, font_pt)
    _draw_north_arrow(axes, font_pt)
    center_lat = xyz_tiles.mercator_to_lonlat(0.0, (y_min + y_max) / 2.0)[1]
    _draw_scalebar(axes, center_lat, font_pt)

    _draw_inset(fig.add_axes(rects["inset"]), country, roi, font_pt)

    # ROI 面積は投影座標系で測る。メルカトル座標のまま測ると大きく外れる。
    roi_area_km2 = float(roi.to_crs(HANOI_UTM_CRS).area.sum()) / 1.0e6 if overlay is None else None
    _draw_legend_panel(fig.add_axes(rects["legend"]), font_pt, roi_area_km2, overlay=overlay)
    _draw_credit_strip(fig.add_axes(rects["credit"]), provider.attribution, font_pt)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return output_path


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。

    Args:
        argv: コマンドライン引数。``None`` なら ``sys.argv`` を使う。

    Returns:
        終了コード（0 で正常）。
    """
    parser = argparse.ArgumentParser(description="ハノイ ROI の位置図を生成する")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "presentations" / "ROI.png",
        help="出力 PNG のパス",
    )
    parser.add_argument("--roi", type=Path, default=DEFAULT_HANOI_ROI_PATH, help="ROI のベクタ")
    parser.add_argument(
        "--country", type=Path, default=DEFAULT_VIETNAM_BOUNDARY_PATH, help="国境のベクタ"
    )
    parser.add_argument(
        "--provider",
        default="osm",
        choices=sorted(xyz_tiles.PROVIDERS),
        help="ベースマップのタイル配信元",
    )
    parser.add_argument("--width-mm", type=float, default=120.0, help="出力の物理幅（mm）")
    parser.add_argument("--dpi", type=int, default=400, help="出力解像度")
    parser.add_argument(
        "--no-dim-outside", action="store_true", help="ROI 外側を薄める処理を行わない"
    )
    parser.add_argument("--no-light-tone", action="store_true", help="ベースマップを淡色調にしない")
    parser.add_argument(
        "--overlay",
        choices=sorted(OVERLAY_PRESETS),
        default=None,
        help="ROI の上に重ねる要素（survey: 測量 GIS の有効域、stations: 観測所と距離帯）",
    )
    parser.add_argument(
        "--survey-extent",
        type=Path,
        default=None,
        help="測量 GIS の有効域のベクタ（--overlay survey のときだけ使う。省略時は既定のパス）",
    )
    args = parser.parse_args(argv)

    overlay = OVERLAY_PRESETS[args.overlay] if args.overlay is not None else None
    if args.survey_extent is not None:
        if overlay is None or overlay.survey_extent_path is None:
            parser.error("--survey-extent は --overlay survey と併せて指定してください。")
        overlay = replace(overlay, survey_extent_path=args.survey_extent)

    mpl.use("Agg")
    path = build_roi_location_map(
        output_path=args.output,
        roi_path=args.roi,
        country_path=args.country,
        provider_name=args.provider,
        width_mm=args.width_mm,
        dpi=args.dpi,
        dim_outside=not args.no_dim_outside,
        light_tone=not args.no_light_tone,
        overlay=overlay,
    )
    print(f"出力しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
