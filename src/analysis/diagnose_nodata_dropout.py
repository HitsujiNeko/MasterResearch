"""人口・夜間光の欠測による分析セルの脱落を、原因別に切り分けて診断する。

`analysis_rq3_limited.py` は人口密度・夜間光の有効域を品質列（`VALID_POP_<ソース>_MASK` /
`VALID_NTL_MASK`）で判定するため、これらの列が0のセルは分析母集団から外れる
（品質列自体は列が非NULLかどうかから導出するため、根本の欠測はここで診断する内容と
変わらない）。その脱落が**どの原因によるものか**を、セル単位で切り分けて記録するのが
本スクリプトの責務である。

## 切り分けの設計

脱落の原因は、値が欠測である理由によって次の2つに分かれる。両者は対処が異なるため、
「欠測セル数」を1つの数字にまとめず、必ず分けて数える。

1. **ROI境界でのラスタクリップに起因する境界帯**
   人口・夜間光のラスタはROIポリゴンで切り出されており、ROI外は無効値である。入力ラスタの
   画素は解析グリッド（30m）より粗いため（LandScan 約930m・VIIRS 約460m・WorldPop 約93m）、
   **ROI境界をまたぐグリッドセルには有効画素が1つも入らない**。この脱落は陸地・水域を問わず
   ROI外周に沿った帯として現れ、水域被覆とは無関係である。
2. **データセット固有の無効値マスク**
   WorldPop は大規模水域を無効値としており、この脱落はROI内部にも分布する。

両者は「ROI境界からの距離」で判別できる。原因1であれば距離は当該ラスタの画素サイズ以内に
収まり、原因2であればROI内部深くまで分布する。この距離を全脱落セルについて算出し、
原因の切り分け根拠として記録する。

## 出力

- サマリJSON: 要因グループ別のセル数・距離分布・水域被覆、および入力ラスタの仕様
- 目視用GeoPackage: 分類済みの脱落セル（QGIS等での空間分布の確認に用いる）

## 母集団

母集団の定義は `analysis_rq3_limited.py` のフィルタとは独立で、本スクリプトは
**ROI内の全セル**（`IN_ANALYSIS_AREA` が1）を母数に取る。LSTが有効なセルに限ると脱落の規模が
観測フットプリントに依存し、観測を入れ替えるたびに数値が変わってしまう。人口・夜間光は年次
データでLSTの観測日時に紐づかないため、ROI全域で数えれば**どの観測にも適用できる**構造的な
脱落規模が得られる。観測ごとに実際へ効いた分は、群別の `lst_valid_count` として併記する。

フィルタは列を順に適用するため脱落数が適用順に依存するが、本スクリプトは原因の切り分けが
目的であり、順序に依存しない素の欠測パターンを数える。
"""

from __future__ import annotations

import argparse
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio

from src.analysis.analysis_rq3_limited import (
    DEFAULT_OUTPUT_DIR as DEFAULT_LIMITED_OUTPUT_DIR,
)
from src.analysis.analysis_rq3_limited import (
    NIGHTLIGHT_FEATURE_COLUMNS,
    POPULATION_SOURCE_COLUMNS,
    TARGET_COLUMN,
)
from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT
from src.common.paths import prepare_output_path, resolve_existing_path, to_project_relative_string
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary

logger = logging.getLogger(__name__)

# 水域被覆の分類境界。`LULC_WATER_COV >= 0.9` を「水域セル」とみなす基準は、
# 結果ドキュメントで水域セルの残存率を報告する際の基準と揃えている。
WATER_DOMINANT_THRESHOLD = 0.9

WATER_COVERAGE_COLUMN = "LULC_WATER_COV"
CELL_ID_COLUMN = "cell_id"
# データセットはジオメトリを持たない属性テーブルであり、セル中心の経緯度を列として持つ。
# 空間演算のためのセル中心点は、読み込み後にこの2列から構築する。
LON_COLUMN = "lon"
LAT_COLUMN = "lat"
# 母集団をROI内へ限定するための列。観測フットプリント（LSTの有無）ではなくこの列で
# 母数を定めることで、脱落規模が観測に依存しなくなる。
ANALYSIS_AREA_COLUMN = "IN_ANALYSIS_AREA"
# 目視確認で原因の当たりを付けるために持ち出す列。LSTと水指標は、脱落セルが水域か
# 陸地かを属性テーブル上でも判断できるようにするために含める。
CONTEXT_COLUMNS = [TARGET_COLUMN, WATER_COVERAGE_COLUMN, "NDWI"]

WORLDPOP_COLUMN = POPULATION_SOURCE_COLUMNS["worldpop2020"]
LANDSCAN_2020_COLUMN = POPULATION_SOURCE_COLUMNS["landscan2020"]
LANDSCAN_2023_COLUMN = POPULATION_SOURCE_COLUMNS["landscan2023"]
NIGHTLIGHT_COLUMN = NIGHTLIGHT_FEATURE_COLUMNS[0]

# 要因グループの判定に用いる列。LandScanは2020・2023が同一のROIマスクを共有するため
# 2020を代表に取り、両者の欠測が一致するかは別途サマリへ記録する。
FACTOR_COLUMNS = {
    "worldpop": WORLDPOP_COLUMN,
    "landscan": LANDSCAN_2020_COLUMN,
    "nightlight": NIGHTLIGHT_COLUMN,
}

# 要因の組み合わせ（worldpop, landscan, nightlight の欠測有無）に対するグループ名。
DROPOUT_GROUP_NAMES = {
    (True, False, False): "worldpop_only",
    (False, True, False): "landscan_only",
    (False, False, True): "nightlight_only",
    (True, True, False): "worldpop_landscan",
    (True, False, True): "worldpop_nightlight",
    (False, True, True): "landscan_nightlight",
    (True, True, True): "all_sources",
}

DEFAULT_POPULATION_DIR = PROJECT_ROOT / "data" / "gis" / "population"
DEFAULT_RASTER_PATHS = {
    "worldpop2020": DEFAULT_POPULATION_DIR / "worldpop" / "worldpop_hanoi_2020.tif",
    "landscan2020": DEFAULT_POPULATION_DIR / "landscan" / "landscan_hanoi_2020.tif",
    "landscan2023": DEFAULT_POPULATION_DIR / "landscan" / "landscan_hanoi_2023.tif",
    "viirs_dnb": PROJECT_ROOT
    / "data"
    / "gis"
    / "nighttime_lights"
    / "viirs_dnb"
    / "viirs_dnb_hanoi_2023.tif",
}
# 出力先は Limited シナリオの分析出力（観測ごとのディレクトリ）と揃える。同じ観測の
# 診断結果が分析結果と並ぶことで、母数の突き合わせがディレクトリ内で完結する。
DEFAULT_OUTPUT_DIR = DEFAULT_LIMITED_OUTPUT_DIR

# 緯度1度あたりの距離（m）。地理座標の画素サイズをメートルへ概算するために用いる。
# 画素サイズは「脱落セルの距離分布がその画素サイズに収まるか」を見る目安であり、
# 厳密な測地計算を要しないため定数近似で足りる。
METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON_AT_EQUATOR = 111_320.0


def classify_dropout_group(
    worldpop_missing: bool, landscan_missing: bool, nightlight_missing: bool
) -> str:
    """欠測している変数の組み合わせから、要因グループ名を返す。

    Args:
        worldpop_missing: WorldPop の人口密度が欠測か。
        landscan_missing: LandScan の人口密度が欠測か。
        nightlight_missing: 夜間光が欠測か。

    Returns:
        要因グループ名。

    Raises:
        ValueError: 3つとも欠測していない場合（脱落セルではないため分類できない）。
    """
    key = (worldpop_missing, landscan_missing, nightlight_missing)
    if key not in DROPOUT_GROUP_NAMES:
        raise ValueError(
            "いずれの変数も欠測していないセルは脱落セルではないため分類できません。"
            "母集団の抽出条件を確認してください。"
        )
    return DROPOUT_GROUP_NAMES[key]


def classify_water_class(water_coverage: float | None) -> str:
    """水域被覆率を、脱落の性格を読むための3区分へ分類する。

    `LULC_WATER_COV` 自体が欠測のセルは、水域か陸地かを判定できないため独立の区分とする
    （0 と同一視すると陸地として数えてしまう）。

    Args:
        water_coverage: セル内の水域被覆率（0-1）。欠測は `None` または `NaN`。

    Returns:
        `"water_dominant"`（0.9以上）／`"water_partial"`（0より大きく0.9未満）／
        `"water_absent"`（0）／`"water_unknown"`（欠測）のいずれか。
    """
    if water_coverage is None or (isinstance(water_coverage, float) and math.isnan(water_coverage)):
        return "water_unknown"
    if water_coverage >= WATER_DOMINANT_THRESHOLD:
        return "water_dominant"
    if water_coverage > 0.0:
        return "water_partial"
    return "water_absent"


def build_dropout_where_clause() -> str:
    """脱落セル（ROI内で、人口・夜間光のいずれかが欠測）を抽出するSQL条件を組み立てる。

    LSTの有無は条件に含めない。含めると抽出結果が観測フットプリントに左右され、観測を
    入れ替えるたびに脱落規模が変わってしまうためである。

    Returns:
        OGR の `where` に渡す条件式。
    """
    missing_conditions = " OR ".join(
        f'"{column}" IS NULL'
        for column in (
            WORLDPOP_COLUMN,
            LANDSCAN_2020_COLUMN,
            LANDSCAN_2023_COLUMN,
            NIGHTLIGHT_COLUMN,
        )
    )
    return f'"{ANALYSIS_AREA_COLUMN}" = 1 AND ({missing_conditions})'


def load_dropout_cells(dataset_path: Path, layer: str | None = None) -> gpd.GeoDataFrame:
    """データセットから脱落セルのみを読み込み、セル中心点を構築する。

    全セル（30mでは数百万件）を読むとメモリと時間を浪費するため、OGR の `where` で
    欠測セルへ絞ってから読み込む。

    データセットは**ジオメトリを持たない属性テーブル**であり、セル中心の経緯度を
    `lon` / `lat` 列として持つ。空間演算（ROI境界からの距離）に必要な点ジオメトリは、
    この2列から構築する。

    Args:
        dataset_path: データセットGeoPackageのパス。
        layer: レイヤ名。`None` の場合は最初のレイヤを使う。

    Returns:
        脱落セルのGeoDataFrame（EPSG:4326、セル中心の点ジオメトリ）。
    """
    columns = [
        CELL_ID_COLUMN,
        LON_COLUMN,
        LAT_COLUMN,
        *FACTOR_COLUMNS.values(),
        LANDSCAN_2023_COLUMN,
        *CONTEXT_COLUMNS,
    ]
    table = pyogrio.read_dataframe(
        dataset_path,
        layer=layer,
        columns=columns,
        read_geometry=False,
        where=build_dropout_where_clause(),
    )
    return gpd.GeoDataFrame(
        table,
        geometry=gpd.points_from_xy(table[LON_COLUMN], table[LAT_COLUMN]),
        crs="EPSG:4326",
    )


def count_base_cells(dataset_path: Path, layer: str | None = None) -> int:
    """脱落率の母数となる「ROI内の全セル」の件数を数える。

    Args:
        dataset_path: データセットGeoPackageのパス。
        layer: レイヤ名。`None` の場合は最初のレイヤを使う。

    Returns:
        ROI内のセル件数。
    """
    base = pyogrio.read_dataframe(
        dataset_path,
        layer=layer,
        columns=[CELL_ID_COLUMN],
        where=f'"{ANALYSIS_AREA_COLUMN}" = 1',
        read_geometry=False,
    )
    return int(len(base))


def add_dropout_classification(cells: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """脱落セルへ要因グループ・水域区分の列を付与する。

    Args:
        cells: `load_dropout_cells` が返すGeoDataFrame。

    Returns:
        `dropout_group` / `water_class` を追加したGeoDataFrame（入力は変更しない）。
    """
    classified = cells.copy()
    landscan_2020_missing = classified[LANDSCAN_2020_COLUMN].isna()
    landscan_2023_missing = classified[LANDSCAN_2023_COLUMN].isna()
    mismatched = int((landscan_2020_missing != landscan_2023_missing).sum())
    if mismatched:
        logger.warning(
            "LandScan 2020 と 2023 で欠測パターンが %d セル食い違っています。"
            "要因グループの判定は両年のOR（どちらかが欠測なら欠測）で行うため、"
            "この食い違い自体で分類が漏れることはないが、どちらの年に起因する欠測かは"
            "本サマリからは区別できない。",
            mismatched,
        )
    # "landscan" は2020単独ではなく2020・2023のORで判定する。2020のみで判定すると、
    # 2023だけが欠測のセルが classify_dropout_group(False, False, False) になり、
    # 「脱落セルではない」という誤ったValueErrorを送出する
    # （build_dropout_where_clause は2023単独欠測も脱落セルとして抽出しているため）。
    missing = {
        name: classified[column].isna()
        for name, column in FACTOR_COLUMNS.items()
        if name != "landscan"
    }
    missing["landscan"] = landscan_2020_missing | landscan_2023_missing
    classified["dropout_group"] = [
        classify_dropout_group(bool(worldpop), bool(landscan), bool(nightlight))
        for worldpop, landscan, nightlight in zip(
            missing["worldpop"], missing["landscan"], missing["nightlight"], strict=True
        )
    ]
    classified["water_class"] = [
        classify_water_class(value) for value in classified[WATER_COVERAGE_COLUMN]
    ]
    return classified


def resolve_metric_crs(roi_geometry: Any, metric_crs: str | None = None) -> str:
    """距離計算に用いる投影座標系を決める。

    投影座標系をROIから推定することで、対象都市が変わっても適切なUTM帯が選ばれる
    （固定値を既定にすると、UTM帯の異なる都市で距離が歪む）。入出力の基準はEPSG:4326の
    ままであり、ここで得た座標系は距離計算のための一時的な変換にのみ使う。

    Args:
        roi_geometry: ROIの統合ジオメトリ（EPSG:4326）。
        metric_crs: 明示指定する投影座標系。`None` の場合はROIから推定する。

    Returns:
        投影座標系の識別子（例: `"EPSG:32648"`）。
    """
    if metric_crs is not None:
        return metric_crs
    estimated = gpd.GeoSeries([roi_geometry], crs="EPSG:4326").estimate_utm_crs()
    return str(estimated.to_string())


def add_roi_edge_distance(
    cells: gpd.GeoDataFrame, roi_geometry: Any, metric_crs: str | None = None
) -> gpd.GeoDataFrame:
    """各セルについて、ROI境界からの距離（m）とROI内外の別を付与する。

    距離はROIの**境界線**からの距離であり、ROI内側・外側のいずれでも正の値になる。
    内外を区別できるよう、ROI外のセルには負号を付けた列（`roi_edge_distance_m`）と、
    内外の別（`inside_roi`）の両方を持たせる。

    Args:
        cells: 脱落セルのGeoDataFrame（EPSG:4326）。
        roi_geometry: ROIの統合ジオメトリ（EPSG:4326）。
        metric_crs: 距離計算に用いる投影座標系。`None` の場合はROIから推定する。

    Returns:
        `roi_edge_distance_m` / `inside_roi` を追加したGeoDataFrame（入力は変更しない）。
    """
    resolved_crs = resolve_metric_crs(roi_geometry, metric_crs)
    projected = cells.to_crs(resolved_crs)
    roi_projected = gpd.GeoSeries([roi_geometry], crs="EPSG:4326").to_crs(resolved_crs).iloc[0]
    distance = projected.geometry.distance(roi_projected.boundary)
    inside = projected.geometry.within(roi_projected)

    result = cells.copy()
    result["inside_roi"] = inside.to_numpy()
    result["roi_edge_distance_m"] = np.where(inside, distance, -distance).round(1)
    return result


def describe_raster(raster_path: Path) -> dict[str, Any]:
    """入力ラスタの無効値・画素サイズ・有効画素率を要約する。

    画素サイズのメートル換算は、脱落セルの距離分布が画素サイズに収まるかを見る目安として
    用いるため、ラスタ中心の緯度による定数近似で足りる（厳密な測地計算は行わない）。

    Args:
        raster_path: ラスタのパス。

    Returns:
        無効値・画素サイズ（度・m）・有効画素率などの要約。
    """
    with rasterio.open(raster_path) as src:
        bounds = src.bounds
        center_lat = (bounds.bottom + bounds.top) / 2.0
        pixel_size_x_deg = abs(src.transform.a)
        pixel_size_y_deg = abs(src.transform.e)
        pixel_size_x_m = (
            pixel_size_x_deg * METERS_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(center_lat))
        )
        pixel_size_y_m = pixel_size_y_deg * METERS_PER_DEGREE_LAT
        valid_mask = src.read_masks(1)
        valid_ratio = float(np.count_nonzero(valid_mask) / valid_mask.size)
        return {
            "path": to_project_relative_string(raster_path),
            "crs": str(src.crs),
            "width": int(src.width),
            "height": int(src.height),
            "nodata": None if src.nodata is None else float(src.nodata),
            "pixel_size_deg": [pixel_size_x_deg, pixel_size_y_deg],
            "pixel_size_m": [round(pixel_size_x_m, 1), round(pixel_size_y_m, 1)],
            "valid_pixel_ratio": round(valid_ratio, 4),
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        }


def summarize_group_distances(
    distances: pd.Series, pixel_sizes_m: dict[str, float]
) -> dict[str, Any]:
    """要因グループのROI境界距離を、原因の切り分けに使える形へ要約する。

    「距離が入力ラスタの画素サイズ以内に収まる割合」を出すことで、その脱落がROI境界での
    クリップに由来するか（原因1）、データセット固有の無効値マスクに由来するか（原因2）を
    数値で判別できるようにする。

    Args:
        distances: ROI境界からの距離（m、ROI外は負）。
        pixel_sizes_m: ラスタ名と画素サイズ（m）の対応。

    Returns:
        分位点・最大値と、ラスタ画素サイズ以内に収まる割合。
    """
    # 距離の絶対値で判定する。距離はROI外で負になるため（Args参照）、符号を無視しないと
    # ROIから大きく離れた外側のセルまで「画素サイズ以内」に含めてしまう
    # （例: 距離-5000mの画素サイズ920m以内判定は、絶対値なら False になるべきだが
    # 符号付きのままでは -5000 <= 920 が True になり誤って含まれる）。
    within_pixel = {
        f"within_{name}_pixel_ratio": round(float((distances.abs() <= size).mean()), 4)
        for name, size in pixel_sizes_m.items()
    }
    return {
        "p10_m": round(float(distances.quantile(0.10)), 1),
        "median_m": round(float(distances.median()), 1),
        "p90_m": round(float(distances.quantile(0.90)), 1),
        "max_m": round(float(distances.max()), 1),
        **within_pixel,
    }


def summarize_dropout(
    cells: gpd.GeoDataFrame, base_cell_count: int, pixel_sizes_m: dict[str, float]
) -> dict[str, Any]:
    """分類済みの脱落セルを、要因グループ別のサマリへ集約する。

    Args:
        cells: `add_dropout_classification` と `add_roi_edge_distance` を適用したセル。
        base_cell_count: 母数（`count_base_cells` の戻り値。ROI内の全セル数
            （`IN_ANALYSIS_AREA == 1`）であり、LSTの有効・無効は問わない。
            観測フットプリントに依存しない構造的な脱落規模を得るための定義
            （モジュールdocstring「母集団」節参照）。
        pixel_sizes_m: ラスタ名と画素サイズ（m）の対応。

    Returns:
        全体・要因グループ別のサマリ。
    """
    groups: dict[str, Any] = {}
    for name, subset in cells.groupby("dropout_group", sort=True):
        water_counts = subset["water_class"].value_counts().to_dict()
        groups[str(name)] = {
            "cell_count": int(len(subset)),
            "dropout_ratio": round(len(subset) / base_cell_count, 5) if base_cell_count else 0.0,
            "outside_roi_count": int((~subset["inside_roi"]).sum()),
            "roi_edge_distance": summarize_group_distances(
                subset["roi_edge_distance_m"], pixel_sizes_m
            ),
            "water_class_counts": {str(k): int(v) for k, v in water_counts.items()},
            "water_coverage_mean": round(float(subset[WATER_COVERAGE_COLUMN].mean()), 4)
            if subset[WATER_COVERAGE_COLUMN].notna().any()
            else None,
            # 母数はROI全域だが、当該観測で実際に分析母集団から外れた分も併記する。
            # 観測を入れ替えるとこの値だけが変わり、上の cell_count は変わらない。
            "lst_valid_count": int(subset[TARGET_COLUMN].notna().sum()),
            # LSTが1セルも有効でない群では平均が NaN になり、サマリの保存が失敗する。
            "lst_mean_c": round(float(subset[TARGET_COLUMN].mean()), 3)
            if subset[TARGET_COLUMN].notna().any()
            else None,
        }

    # 空の入力に対する `all()` は True を返すため、そのまま記録すると「一致を確認した」と
    # 読めてしまう。確認できていないことを `None` で表し、確認済みの True と区別する。
    landscan_agreement = (
        None
        if cells.empty
        else bool((cells[LANDSCAN_2020_COLUMN].isna() == cells[LANDSCAN_2023_COLUMN].isna()).all())
    )
    return {
        "base_cell_count": base_cell_count,
        "dropout_cell_count": int(len(cells)),
        "dropout_ratio": round(len(cells) / base_cell_count, 5) if base_cell_count else 0.0,
        "dropout_lst_valid_count": int(cells[TARGET_COLUMN].notna().sum()),
        "landscan_2020_2023_missing_agreement": landscan_agreement,
        "water_dominant_threshold": WATER_DOMINANT_THRESHOLD,
        "groups": groups,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。

    Args:
        argv: 引数リスト。`None` の場合は `sys.argv` を使う。

    Returns:
        解釈済みの引数。
    """
    parser = argparse.ArgumentParser(
        description="人口・夜間光の欠測による分析セルの脱落を原因別に切り分けて診断する。"
    )
    parser.add_argument("--dataset", type=Path, required=True, help="データセットGeoPackageのパス")
    parser.add_argument("--layer", type=str, default=None, help="レイヤ名（既定: 最初のレイヤ）")
    parser.add_argument(
        "--roi", type=Path, default=DEFAULT_HANOI_ROI_PATH, help="ROIのShapefileパス"
    )
    parser.add_argument(
        "--metric-crs",
        type=str,
        default=None,
        help="距離計算に用いる投影座標系（既定: ROIから推定）",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="サマリ・目視用GPKGの出力先"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """脱落セルを分類し、サマリJSONと目視用GeoPackageを出力する。

    Args:
        argv: コマンドライン引数。`None` の場合は `sys.argv` を使う。
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    args = parse_args(argv)

    dataset_path = resolve_existing_path(args.dataset)
    roi_path = resolve_existing_path(args.roi)
    _, roi_geometry = load_roi_geometry(roi_path)

    logger.info("脱落セルを抽出します: %s", to_project_relative_string(dataset_path))
    base_cell_count = count_base_cells(dataset_path, args.layer)
    cells = load_dropout_cells(dataset_path, args.layer)
    logger.info("母数 %d セルのうち %d セルが脱落しています。", base_cell_count, len(cells))

    cells = add_dropout_classification(cells)
    metric_crs = resolve_metric_crs(roi_geometry, args.metric_crs)
    logger.info("距離計算に用いる投影座標系: %s", metric_crs)
    cells = add_roi_edge_distance(cells, roi_geometry, metric_crs)

    rasters = {
        name: describe_raster(resolve_existing_path(path))
        for name, path in DEFAULT_RASTER_PATHS.items()
    }
    pixel_sizes_m = {name: max(info["pixel_size_m"]) for name, info in rasters.items()}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": to_project_relative_string(dataset_path),
        "layer": args.layer,
        "roi": to_project_relative_string(roi_path),
        "metric_crs": metric_crs,
        "rasters": rasters,
        **summarize_dropout(cells, base_cell_count, pixel_sizes_m),
    }

    stem = dataset_path.stem
    summary_path = prepare_output_path(args.output_dir / f"{stem}_nodata_dropout_summary.json")
    cells_path = prepare_output_path(args.output_dir / f"{stem}_nodata_dropout_cells.gpkg")
    save_summary(summary, summary_path)
    cells.to_file(cells_path, layer="nodata_dropout", driver="GPKG")

    logger.info("サマリを保存しました: %s", to_project_relative_string(summary_path))
    logger.info("目視用GeoPackageを保存しました: %s", to_project_relative_string(cells_path))


if __name__ == "__main__":
    main()
