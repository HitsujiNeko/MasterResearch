"""測量GIS（CS の図郭内枠）からハノイの測量GIS有効域ポリゴンを生成する。

測量GISの有効域は「CS レイヤの Level 5 に描かれた図郭内枠（80図葉）の和集合」と
定義する。図郭内枠は各図葉で測量図面が実際に描かれた範囲そのものであり、RG の
境界線（区・坊の行政界で、範囲の縁で途切れて開いている）や外接矩形・凸包のような
近似よりも正確に測量範囲を表すためである。

処理の流れ:

1. CS レイヤから Level 5 の長い線（図郭内枠の4辺）だけを選ぶ。同じ Level には
   目盛りなどの短い線（約25 m）も含まれるため、長さで除く
2. 線を面化（polygonize）し、面積で図葉面を選ぶ（線どうしの間にできる細い面を除く）
3. 図葉面の和集合を取り、図葉間のわずかな隙間をクロージング（膨張→収縮）で埋めて
   単一ポリゴンにする
4. 図葉数・部分数・穴の有無・クロージングによる面積変化を検証し、想定外なら例外にする

入力の場所・レイヤ名・CRS は ``src.analysis.urban_params.config`` の ``cs`` 設定を
正本として参照する（測量GISの merge ファイルは CRS 情報を持たないため、CRS は
設定値を付与する）。出力は gitignore 対象の ``data/gis/survey/`` に保存する。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from src.analysis.urban_params.config import CITY_CONFIG
from src.common.config import PROJECT_ROOT
from src.common.geopackage import remove_geopackage, replace_geopackage
from src.common.paths import prepare_output_path, resolve_existing_path

# 入力（CS レイヤ）の設定。パス・レイヤ名・CRS を二重に持たないよう、パラメータ算出の
# レイヤ設定から取る。
CS_LAYER_CONFIG = CITY_CONFIG["hanoi"]["layers"]["cs"]

DEFAULT_INPUT_PATH = PROJECT_ROOT / CS_LAYER_CONFIG["path"]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "gis" / "survey" / "hanoi_survey_extent.gpkg"

# 出力レイヤ名。パラメータ算出側の設定キー（survey_extent）と揃える。
OUTPUT_LAYER_NAME = "survey_extent"

# 図郭内枠が描かれている CS の Level。Level 7 は図郭外枠で、隣接図葉と重なるため使わない。
INNER_FRAME_LEVEL = 5

# 図郭内枠の辺とみなす線の最小長（m）。内枠の辺は約1,082 m / 1,153 m、同じ Level の
# 目盛り線は約25 m であり、その間のどこで切っても結果は変わらない。
MIN_FRAME_LINE_LENGTH_M = 300.0

# 図葉面とみなす面の最小面積（m²）。図葉1枚は約1.248 km²、図葉間の隙間にできる細い面は
# 数 m² であり、桁が大きく離れているため 0.1 km² で区切る。
MIN_SHEET_AREA_M2 = 1.0e5

# 想定する図葉数（8列 × 10行）。欠けや重複を検知するために照合する。
EXPECTED_SHEET_COUNT = 80

# 図葉間の隙間を埋めるクロージングの半径（m）。実データの隙間は半径 0.5 m 以上で
# 埋まることを確認しており、余裕を持たせて 1 m とする。
CLOSING_RADIUS_M = 1.0

# クロージングによる面積変化の許容比率。隙間の合計は数 m² で全体（約99.9 km²）に
# 比べて無視できるため、これを超える変化は図葉どうしの離れすぎなど想定外の状態とみなす。
MAX_CLOSING_AREA_CHANGE_RATIO = 1.0e-3


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="測量GIS（CS の図郭内枠）から測量GIS有効域ポリゴンを生成する。"
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="CS レイヤの GeoPackage パス（既定: パラメータ算出の cs 設定）",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力先の GeoPackage パス",
    )
    return parser.parse_args()


def read_cs_lines(input_path: Path, layer: str, crs_epsg: int) -> gpd.GeoDataFrame:
    """CS レイヤを ``Level`` 列のみで読み込み、CRS を付与する。

    文字列列（``Text`` 等）には UTF-8 として解釈できないバイト列が含まれ、全列を
    読むと失敗するため、判定に使う ``Level`` 列だけを読む。

    Args:
        input_path: CS レイヤの GeoPackage パス。
        layer: レイヤ名。
        crs_epsg: 付与する CRS の EPSG コード（merge ファイルは CRS 情報を持たない）。

    Returns:
        ``Level`` 列とジオメトリを持つ GeoDataFrame。
    """
    gdf = pyogrio.read_dataframe(input_path, layer=layer, columns=["Level"])
    return assign_crs(gdf, crs_epsg)


def assign_crs(gdf: gpd.GeoDataFrame, crs_epsg: int) -> gpd.GeoDataFrame:
    """CRS 情報を持たないレイヤにだけ CRS を付与する。

    入力がすでに CRS を持つ場合に黙って上書きすると、座標値と CRS が食い違った
    まま処理が進むため、設定値と異なる CRS を持つ場合は例外にする。

    Args:
        gdf: 対象のレイヤ。
        crs_epsg: 付与する（または一致を求める）CRS の EPSG コード。

    Returns:
        CRS が ``crs_epsg`` に設定された GeoDataFrame。

    Raises:
        ValueError: 入力が ``crs_epsg`` 以外の CRS を持つ場合。
    """
    if gdf.crs is None:
        return gdf.set_crs(epsg=crs_epsg)
    if gdf.crs.to_epsg() != crs_epsg:
        raise ValueError(
            f"入力レイヤの CRS が想定と異なります（入力: {gdf.crs.to_string()} /"
            f" 想定: EPSG:{crs_epsg}）。座標系を確認してください。"
        )
    return gdf


def select_inner_frame_lines(
    gdf: gpd.GeoDataFrame,
    level: int = INNER_FRAME_LEVEL,
    min_length: float = MIN_FRAME_LINE_LENGTH_M,
) -> gpd.GeoSeries:
    """図郭内枠の辺にあたる線を選ぶ。

    Args:
        gdf: ``Level`` 列を持つ CS レイヤ。
        level: 図郭内枠が描かれている Level。
        min_length: 図郭内枠の辺とみなす線の最小長（m）。

    Returns:
        図郭内枠の辺の LineString 列。

    Raises:
        ValueError: 条件に合う線が1本も無い場合。
    """
    is_frame = (
        (gdf["Level"] == level)
        & (gdf.geom_type == "LineString")
        & (gdf.geometry.length >= min_length)
    )
    lines = gdf.geometry[is_frame]
    if lines.empty:
        raise ValueError(
            "図郭内枠の線が見つかりません"
            f"（Level {level}・長さ {min_length} m 以上の LineString）。"
            " 入力レイヤが CS であるか確認してください。"
        )
    return lines


def polygonize_sheets(
    lines: gpd.GeoSeries,
    min_area: float = MIN_SHEET_AREA_M2,
) -> list[Polygon]:
    """図郭内枠の線を面化し、図葉面だけを返す。

    隣接図葉の内枠どうしはわずかに離れたり交わったりしているため、まず線を和集合して
    交点で分割（ノード化）してから面化する。その際に隙間や重なりの部分にも細い面が
    できるため、面積で図葉面だけを選ぶ。

    Args:
        lines: 図郭内枠の辺の線。
        min_area: 図葉面とみなす最小面積（m²）。

    Returns:
        図葉面のリスト。
    """
    faces = polygonize(unary_union(lines.to_numpy()))
    return [face for face in faces if face.area >= min_area]


def close_gaps(geometry: BaseGeometry, radius: float = CLOSING_RADIUS_M) -> BaseGeometry:
    """クロージング（膨張→収縮）で図葉間の細い隙間を埋める。

    角を丸めないよう ``mitre`` 結合を使う（図葉の四隅は直角であり、丸めると外周の
    角が削れる）。

    Args:
        geometry: 図葉面の和集合。
        radius: 膨張・収縮の半径（m）。この2倍未満の幅の隙間が埋まる。

    Returns:
        隙間を埋めたジオメトリ。
    """
    return geometry.buffer(radius, join_style="mitre").buffer(-radius, join_style="mitre")


def validate_extent(
    extent: BaseGeometry,
    sheet_count: int,
    union_area: float,
    expected_sheet_count: int = EXPECTED_SHEET_COUNT,
    max_area_change_ratio: float = MAX_CLOSING_AREA_CHANGE_RATIO,
) -> Polygon:
    """生成した有効域が想定どおりかを検証する。

    Args:
        extent: クロージング後の有効域。
        sheet_count: 面化で得た図葉数。
        union_area: クロージング前の図葉面の和集合の面積（m²）。
        expected_sheet_count: 想定する図葉数。
        max_area_change_ratio: クロージングによる面積変化の許容比率。

    Returns:
        検証済みの単一ポリゴン。

    Raises:
        ValueError: 図葉数の不一致・複数部分・穴あり・面積変化の超過のいずれかの場合。
    """
    if sheet_count != expected_sheet_count:
        raise ValueError(
            f"図葉数が想定と異なります（検出: {sheet_count} / 想定: {expected_sheet_count}）。"
            " 図郭内枠の線の欠けや選別条件を確認してください。"
        )
    if isinstance(extent, MultiPolygon):
        raise ValueError(
            f"有効域が {len(extent.geoms)} 部分に分かれています。"
            " 図葉間の隙間がクロージング半径より広い可能性があります。"
        )
    if not isinstance(extent, Polygon):
        raise ValueError(f"有効域がポリゴンではありません（型: {extent.geom_type}）。")
    if extent.interiors:
        raise ValueError(
            f"有効域に穴が {len(extent.interiors)} 個あります。"
            " 図葉の欠けや、クロージング半径より広い隙間の可能性があります。"
        )
    area_change_ratio = abs(extent.area - union_area) / union_area
    if area_change_ratio > max_area_change_ratio:
        raise ValueError(
            f"クロージングによる面積変化が大きすぎます（変化率: {area_change_ratio:.2e} /"
            f" 許容: {max_area_change_ratio:.2e}）。"
            "図葉どうしが離れすぎていないか確認してください。"
        )
    return extent


def build_survey_extent(
    cs_gdf: gpd.GeoDataFrame,
    expected_sheet_count: int = EXPECTED_SHEET_COUNT,
) -> gpd.GeoDataFrame:
    """CS レイヤから測量GIS有効域の1行 GeoDataFrame を組み立てる。

    Args:
        cs_gdf: ``Level`` 列と CRS を持つ CS レイヤ。
        expected_sheet_count: 想定する図葉数。

    Returns:
        有効域ポリゴン1件と、図葉数（``sheet_count``）・面積（``area_km2``）を持つ
        GeoDataFrame。CRS は入力と同じ。
    """
    lines = select_inner_frame_lines(cs_gdf)
    sheets = polygonize_sheets(lines)
    union = unary_union(sheets)
    extent = validate_extent(
        close_gaps(union),
        sheet_count=len(sheets),
        union_area=union.area,
        expected_sheet_count=expected_sheet_count,
    )
    return gpd.GeoDataFrame(
        {"sheet_count": [len(sheets)], "area_km2": [extent.area / 1.0e6]},
        geometry=[extent],
        crs=cs_gdf.crs,
    )


def write_extent(extent_gdf: gpd.GeoDataFrame, output_path: Path, layer: str) -> None:
    """有効域を一時ファイル経由で GeoPackage に書き出す。

    書き出しに失敗しても既存の出力を壊さないよう、一時ファイルへ書いてから差し替える。

    Args:
        extent_gdf: 書き出す有効域。
        output_path: 出力先の GeoPackage パス（親ディレクトリは作成済みであること）。
        layer: レイヤ名。
    """
    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    remove_geopackage(temp_path)
    try:
        pyogrio.write_dataframe(extent_gdf, temp_path, layer=layer, driver="GPKG")
    except BaseException:
        # 中断（KeyboardInterrupt）も含めて書きかけを残さない。
        remove_geopackage(temp_path)
        raise
    replace_geopackage(temp_path, output_path)


def summarize(extent_gdf: gpd.GeoDataFrame) -> list[str]:
    """ログに出す要約行を作る。

    Args:
        extent_gdf: ``build_survey_extent()`` の戻り値。

    Returns:
        表示用の文字列のリスト。
    """
    extent = extent_gdf.geometry.iloc[0]
    return [
        f"図葉数: {int(extent_gdf['sheet_count'].iloc[0])}",
        # 「²」は cp932 で表せず、標準出力をリダイレクトすると書き出し後に落ちるため km2 と書く。
        f"面積: {extent_gdf['area_km2'].iloc[0]:.3f} km2",
        f"部分数: 1 / 穴: {len(extent.interiors)}",
        f"CRS: {extent_gdf.crs.to_string()}",
    ]


def main() -> None:
    """測量GIS有効域ポリゴンを生成して保存する。"""
    args = parse_args()
    input_path = resolve_existing_path(args.input_path)
    output_path = prepare_output_path(args.output_path)

    cs_gdf = read_cs_lines(input_path, CS_LAYER_CONFIG["layer"], CS_LAYER_CONFIG["crs_epsg"])
    extent_gdf = build_survey_extent(cs_gdf)
    write_extent(extent_gdf, output_path, OUTPUT_LAYER_NAME)

    print("測量GIS有効域の生成が完了しました。")
    print(f"入力: {input_path}")
    print(f"出力: {output_path}（レイヤ: {OUTPUT_LAYER_NAME}）")
    for line in summarize(extent_gdf):
        print(line)


if __name__ == "__main__":
    main()
