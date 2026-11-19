"""測量GIS（merge_*.gpkg）7レイヤの属性を集計し、属性の整理に使う表を出力するスクリプト。

測量GISは CAD（DGN）由来で、属性は `Type`・`Level`・`GraphicGroup`・`ColorIndex`・
`Weight`・`Style`・`EntityNum`・`MSLink`・`Text`・`ULink` などの描画用の列しかない。
何の地物かは Level（CAD の描画層の番号）から推測するしかないため、レイヤごとに
列の一覧・ジオメトリ型別の件数・Level 別の件数・描画属性の組み合わせ・大きさ・
属性値の例を表にまとめる。

読み込み時の前提（`merge_*.gpkg` の既知の性質）:

- CRS を持たないため EPSG:5897（VN-2000 / TM-3 zone 482）を付与する。長さ・面積は
  この投影座標（メートル）のまま計算する
- ジオメトリ型が混在するため、行ごとに shapely の `geom_type` で判定する
- `Text` に UTF-8 として読めないバイト列（TCVN3 とみられる）があるため、すべての
  バイトを 1 文字に対応させる latin-1 で読み、元のバイト列を失わないようにする。
  出力では ASCII 以外のバイトを `\\xNN` の形にして残す（文字コードは未確認のため
  解読はしない）
- 一部のレイヤに座標 (500,000, 1,000,000) 付近のダミーの地物があるため、
  大きさの集計から除外し、除外件数を記録する

出力（`--output-dir` 配下）:

- `columns.csv`: 列の一覧（列名・定義上の型・欠損の割合・値の種類の数）
- `geometry_types.csv`: ジオメトリ型別の件数
- `levels.csv`: Level 別の件数（点・線・面の内訳と、属性が入っている件数）
- `value_distribution.csv`: `Type`・`ColorIndex`・`Weight`・`Style`・`GraphicGroup` の値の分布
- `style_combinations.csv`: Level × 形 × `Type`・`ColorIndex`・`Weight`・`Style` の件数
- `sizes_by_level.csv`: Level 別の線の長さ・面の面積（中央値・最大）と除外件数
- `attribute_examples.csv`: Level 別の `Text`・`MSLink`・`EntityNum` の値の例
- `ulink_linkages.csv`: Level 別の `ULink`（DGN のリンク情報）の種類別件数
- `inventory_summary.json`: レイヤ別の概要・集計条件・来歴

実行例:
    python -m src.analysis.inventory_survey_gis_attributes
    python -m src.analysis.inventory_survey_gis_attributes --layers DH TH TV
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

from src.common.config import PROJECT_ROOT
from src.common.paths import resolve_existing_path, to_project_relative_string
from src.common.summary import build_provenance, save_summary

SCRIPT_NAME = "src.analysis.inventory_survey_gis_attributes"

# 測量GISのレイヤ略号（ファイル名は merge_{略号}.gpkg）
SURVEY_LAYER_CODES: tuple[str, ...] = ("CS", "DC", "DH", "GT", "RG", "TH", "TV")
# ファイルに CRS が無いため付与する座標系（研究者が確認済みの正本）
SURVEY_CRS = "EPSG:5897"
# 文字列列を読む文字コード。すべてのバイトが 1 文字に対応するため、元のバイト列を失わない
TEXT_READ_ENCODING = "latin-1"

DEFAULT_INPUT_DIR = Path("data/gis/survey")
DEFAULT_OUTPUT_DIR = Path("data/output/survey_gis_attribute_inventory")
DEFAULT_TOP_N = 5
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_SEED = 42

# 値の分布を数える描画属性の列
STYLE_COLUMNS: tuple[str, ...] = ("Type", "ColorIndex", "Weight", "Style", "GraphicGroup")
# Level・形と組み合わせて数える描画属性の列（GraphicGroup は値の種類が多いため別に数える）
COMBINATION_COLUMNS: tuple[str, ...] = ("Type", "ColorIndex", "Weight", "Style")
# 値の例を出す列（ULink は長い JSON のため、リンクの種類別件数として別に集計する）
EXAMPLE_COLUMNS: tuple[str, ...] = ("Text", "MSLink", "EntityNum")

# ダミーの地物の判定: 範囲（外接矩形）がすべてこの点から許容幅以内に収まるもの
DUMMY_ORIGIN: tuple[float, float] = (500_000.0, 1_000_000.0)
DUMMY_TOLERANCE_M = 100.0
# ダミー以外の範囲外の地物の判定に使う範囲（xmin, ymin, xmax, ymax。EPSG:5897）。
# 80 図葉の図郭（CS: X 581,144〜589,921 / Y 2,321,788〜2,333,565）に約 5 km の余裕を
# 持たせたもの。GT には図郭の北側に約 2 km はみ出す線があるため、余裕を小さくしない
VALID_EXTENT: tuple[float, float, float, float] = (576_000.0, 2_316_000.0, 595_000.0, 2_339_000.0)

# 地物の位置の区分
LOCATION_VALID = "valid"
LOCATION_EMPTY = "empty"
LOCATION_DUMMY = "dummy"
LOCATION_OUT_OF_EXTENT = "out_of_extent"

# ジオメトリ型 → 形の区分（点・線・面）
GEOMETRY_CLASS_BY_TYPE: dict[str, str] = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "LinearRing": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}
GEOMETRY_CLASS_OTHER = "other"
GEOMETRY_CLASSES: tuple[str, ...] = ("point", "line", "polygon", GEOMETRY_CLASS_OTHER)
# 形の区分ごとの大きさの指標（点は大きさを持たないため対象外）
SIZE_METRIC_BY_CLASS: dict[str, str] = {"line": "length_m", "polygon": "area_m2"}

# 出力ファイル名（表のキー → ファイル名）
OUTPUT_TABLE_FILES: dict[str, str] = {
    "columns": "columns.csv",
    "geometry_types": "geometry_types.csv",
    "levels": "levels.csv",
    "value_distribution": "value_distribution.csv",
    "style_combinations": "style_combinations.csv",
    "sizes_by_level": "sizes_by_level.csv",
    "attribute_examples": "attribute_examples.csv",
    "ulink_linkages": "ulink_linkages.csv",
}
SUMMARY_FILE_NAME = "inventory_summary.json"
# 値の例を 1 つのセルにつなぐ区切り
VALUE_SEPARATOR = " | "
# ULink が JSON として読めなかった場合のリンク ID
INVALID_JSON_LINKAGE = "invalid_json"


def layer_path(input_dir: Path, code: str) -> Path:
    """レイヤ略号から merge_*.gpkg のパスを組み立てる。

    Args:
        input_dir: merge_*.gpkg を置いたディレクトリ。
        code: レイヤ略号（例: `DC`）。

    Returns:
        `input_dir / merge_{code}.gpkg`。

    Raises:
        ValueError: 未知のレイヤ略号の場合。
    """
    if code not in SURVEY_LAYER_CODES:
        raise ValueError(
            f"未知のレイヤ略号です: {code}（使えるのは {', '.join(SURVEY_LAYER_CODES)}）"
        )
    return input_dir / f"merge_{code}.gpkg"


def read_survey_layer(path: Path) -> gpd.GeoDataFrame:
    """測量GISの merge_*.gpkg を読み、EPSG:5897 を付与する。

    文字列列は latin-1 で読む（UTF-8 として不正なバイト列があっても失わないため）。

    Args:
        path: merge_*.gpkg のパス。

    Returns:
        CRS に EPSG:5897 を付与した GeoDataFrame。

    Raises:
        ValueError: ファイルが CRS を持っている場合（前提と違うため、付与で上書きしない）。
    """
    gdf = pyogrio.read_dataframe(path, encoding=TEXT_READ_ENCODING)
    if gdf.crs is not None:
        raise ValueError(
            f"{path.name} は CRS（{gdf.crs.to_string()}）を持っています。"
            f"CRS の無いファイルに {SURVEY_CRS} を付与する前提と違うため、中身を確認してください"
        )
    return gdf.set_crs(SURVEY_CRS)


def classify_geometry_types(geom_types: pd.Series) -> pd.Series:
    """ジオメトリ型を形の区分（point・line・polygon・other）に分ける。

    Args:
        geom_types: shapely の `geom_type`（ジオメトリが無い行は欠損）。

    Returns:
        形の区分。対応表に無い型（GeometryCollection など）と欠損は `other`。
    """
    return geom_types.map(GEOMETRY_CLASS_BY_TYPE).fillna(GEOMETRY_CLASS_OTHER)


def flag_geometry_locations(geometries: gpd.GeoSeries) -> pd.Series:
    """地物の位置を、有効・空・ダミー・範囲外に分ける。

    判定の順は 空（またはジオメトリなし）→ ダミー → 範囲外 とする。

    Args:
        geometries: EPSG:5897 のジオメトリ。

    Returns:
        `valid`・`empty`・`dummy`・`out_of_extent` のいずれか。
    """
    values = geometries.values
    bounds = shapely.bounds(values)
    is_empty = shapely.is_missing(values) | shapely.is_empty(values)
    origin_x, origin_y = DUMMY_ORIGIN
    with np.errstate(invalid="ignore"):
        is_dummy = (
            (np.abs(bounds[:, 0] - origin_x) <= DUMMY_TOLERANCE_M)
            & (np.abs(bounds[:, 2] - origin_x) <= DUMMY_TOLERANCE_M)
            & (np.abs(bounds[:, 1] - origin_y) <= DUMMY_TOLERANCE_M)
            & (np.abs(bounds[:, 3] - origin_y) <= DUMMY_TOLERANCE_M)
        )
        xmin, ymin, xmax, ymax = VALID_EXTENT
        is_inside = (
            (bounds[:, 0] >= xmin)
            & (bounds[:, 1] >= ymin)
            & (bounds[:, 2] <= xmax)
            & (bounds[:, 3] <= ymax)
        )
    flags = np.select(
        [is_empty, is_dummy, ~is_inside],
        [LOCATION_EMPTY, LOCATION_DUMMY, LOCATION_OUT_OF_EXTENT],
        default=LOCATION_VALID,
    )
    return pd.Series(flags, index=geometries.index, name="location")


def escape_text(value: str) -> str:
    """latin-1 で読んだ文字列を、ASCII 以外のバイトを `\\xNN` にした文字列へ変える。

    文字コードが未確認の値を、元のバイト列が分かる形で CSV に残すために使う。

    Args:
        value: latin-1 で読んだ文字列。

    Returns:
        ASCII だけで書かれた文字列（例: `H\\xb5 N\\xe9i`）。
    """
    return value.encode(TEXT_READ_ENCODING).decode("ascii", errors="backslashreplace")


def is_valid_utf8(value: str) -> bool:
    """latin-1 で読んだ文字列の元のバイト列が、UTF-8 として正しいかを判定する。

    Args:
        value: latin-1 で読んだ文字列。

    Returns:
        UTF-8 として読めれば True。
    """
    try:
        value.encode(TEXT_READ_ENCODING).decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def summarize_columns(gdf: pd.DataFrame, declared_dtypes: Mapping[str, str]) -> pd.DataFrame:
    """列の一覧（定義上の型・欠損の件数と割合・値の種類の数）を作る。

    Args:
        gdf: 読み込んだレイヤ（ジオメトリ列は対象外）。
        declared_dtypes: ファイルに定義された列の型（`pyogrio.read_info` の値）。
            欠損がある整数列は pandas では小数になるため、定義上の型を別に残す。

    Returns:
        `column`・`declared_dtype`・`null_count`・`null_ratio`・`n_unique` の表。
    """
    rows = []
    n_rows = len(gdf)
    for column in declared_dtypes:
        values = gdf[column]
        null_count = int(values.isna().sum())
        rows.append(
            {
                "column": column,
                "declared_dtype": declared_dtypes[column],
                "null_count": null_count,
                "null_ratio": null_count / n_rows if n_rows else np.nan,
                "n_unique": int(values.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)


def count_geometry_types(geom_types: pd.Series, geometry_classes: pd.Series) -> pd.DataFrame:
    """ジオメトリ型別の件数を数える。

    Args:
        geom_types: 行ごとのジオメトリ型（欠損は `None` として数える）。
        geometry_classes: 行ごとの形の区分。

    Returns:
        `geom_type`・`geometry_class`・`count` の表（件数の多い順）。
    """
    frame = pd.DataFrame(
        {"geom_type": geom_types.fillna("None"), "geometry_class": geometry_classes}
    )
    counts = frame.value_counts().rename("count").reset_index()
    return counts.sort_values(["count", "geom_type"], ascending=[False, True], ignore_index=True)


def summarize_levels(gdf: pd.DataFrame, geometry_classes: pd.Series) -> pd.DataFrame:
    """Level 別の件数（形の内訳と、属性が入っている件数）を数える。

    Args:
        gdf: 読み込んだレイヤ。
        geometry_classes: 行ごとの形の区分。

    Returns:
        Level ごとの `n_total`・`n_point`・`n_line`・`n_polygon`・`n_other`・`n_text`・
        `n_mslink`・`n_entitynum`・`n_ulink`・`n_graphic_group_nonzero` の表（Level 順）。
    """
    class_counts = pd.crosstab(gdf["Level"], geometry_classes).reindex(
        columns=list(GEOMETRY_CLASSES), fill_value=0
    )
    class_counts.columns = [f"n_{name}" for name in GEOMETRY_CLASSES]
    grouped = gdf.groupby("Level")
    attribute_counts = pd.DataFrame(
        {
            "n_total": grouped.size(),
            "n_text": grouped["Text"].count(),
            "n_mslink": grouped["MSLink"].count(),
            "n_entitynum": grouped["EntityNum"].count(),
            "n_ulink": grouped["ULink"].count(),
            "n_graphic_group_nonzero": grouped["GraphicGroup"].apply(count_nonzero_values),
        }
    )
    table = (
        attribute_counts[["n_total"]]
        .join(class_counts)
        .join(attribute_counts.drop(columns="n_total"))
    )
    return table.reset_index().sort_values("Level", ignore_index=True)


def is_nonzero_value(values: pd.Series) -> pd.Series:
    """値が欠損でなく、かつ 0 でないかを判定する。

    `!= 0` だけでは欠損（NaN）も「0 以外」になるため、欠損を除いて判定する。

    Args:
        values: 判定する列。

    Returns:
        行ごとの真偽値。
    """
    return values.notna() & (values != 0)


def count_nonzero_values(values: pd.Series) -> int:
    """欠損を除き、0 でない値の件数を数える。

    Args:
        values: 数える列。

    Returns:
        欠損でなく 0 でもない値の件数。
    """
    return int(is_nonzero_value(values).sum())


def count_value_distribution(
    gdf: pd.DataFrame, columns: Sequence[str] = STYLE_COLUMNS
) -> pd.DataFrame:
    """描画属性の列ごとに、値の分布を数える。

    Args:
        gdf: 読み込んだレイヤ。
        columns: 数える列。

    Returns:
        `column`・`value`・`count` の表（列ごとに件数の多い順）。
    """
    frames = []
    for column in columns:
        counts = gdf[column].value_counts(dropna=False).rename("count").rename_axis("value")
        frame = counts.reset_index()
        frame.insert(0, "column", column)
        frames.append(frame.sort_values(["count", "value"], ascending=[False, True]))
    return pd.concat(frames, ignore_index=True)


def count_style_combinations(gdf: pd.DataFrame, geometry_classes: pd.Series) -> pd.DataFrame:
    """Level・形・描画属性（Type・ColorIndex・Weight・Style）の組み合わせごとの件数を数える。

    Args:
        gdf: 読み込んだレイヤ。
        geometry_classes: 行ごとの形の区分。

    Returns:
        組み合わせごとの `count` と、そのうち `GraphicGroup` が 0 以外の件数の表
        （Level 順、同じ Level の中は件数の多い順）。
    """
    frame = gdf[["Level", *COMBINATION_COLUMNS]].copy()
    frame.insert(1, "geometry_class", geometry_classes.to_numpy())
    frame["graphic_group_nonzero"] = is_nonzero_value(gdf["GraphicGroup"]).astype(int)
    keys = ["Level", "geometry_class", *COMBINATION_COLUMNS]
    table = (
        frame.groupby(keys, dropna=False)
        .agg(
            count=("graphic_group_nonzero", "size"),
            n_graphic_group_nonzero=("graphic_group_nonzero", "sum"),
        )
        .reset_index()
    )
    return table.sort_values(["Level", "count"], ascending=[True, False], ignore_index=True)


def summarize_sizes_by_level(
    gdf: gpd.GeoDataFrame, geometry_classes: pd.Series, locations: pd.Series
) -> pd.DataFrame:
    """Level 別に線の長さ・面の面積（中央値・最大）を求める。

    空・ダミー・範囲外の地物は大きさの集計から除き、除いた件数を残す。

    Args:
        gdf: EPSG:5897 のレイヤ（長さ・面積はメートル単位になる）。
        geometry_classes: 行ごとの形の区分。
        locations: 行ごとの位置の区分（`flag_geometry_locations` の結果）。

    Returns:
        Level × 形（線・面）ごとの `n_features`・`n_measured`・`n_empty`・`n_dummy`・
        `n_out_of_extent`・`size_metric`・`size_median`・`size_max` の表。
    """
    values = gdf.geometry.values
    frame = pd.DataFrame(
        {
            "Level": gdf["Level"].to_numpy(),
            "geometry_class": geometry_classes.to_numpy(),
            "location": locations.to_numpy(),
            "length": shapely.length(values),
            "area": shapely.area(values),
        }
    )
    rows = []
    for (level, geometry_class), group in frame.groupby(["Level", "geometry_class"], sort=True):
        metric = SIZE_METRIC_BY_CLASS.get(geometry_class)
        if metric is None:
            continue
        measured = group.loc[
            group["location"] == LOCATION_VALID, "length" if geometry_class == "line" else "area"
        ]
        rows.append(
            {
                "Level": level,
                "geometry_class": geometry_class,
                "n_features": len(group),
                "n_measured": len(measured),
                "n_empty": int((group["location"] == LOCATION_EMPTY).sum()),
                "n_dummy": int((group["location"] == LOCATION_DUMMY).sum()),
                "n_out_of_extent": int((group["location"] == LOCATION_OUT_OF_EXTENT).sum()),
                "size_metric": metric,
                "size_median": float(measured.median()) if len(measured) else np.nan,
                "size_max": float(measured.max()) if len(measured) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def format_example_value(value: Any) -> str:
    """値の例を CSV に書く文字列へ変える。

    文字列は ASCII 以外のバイトを `\\xNN` にし、整数値の小数（欠損のある整数列が
    小数で読まれたもの）は整数で書く。

    Args:
        value: 列の値（欠損でないもの）。

    Returns:
        表示用の文字列。
    """
    if isinstance(value, str):
        return escape_text(value)
    if isinstance(value, float | np.floating) and float(value).is_integer():
        return str(int(value))
    return str(value)


def summarize_attribute_examples(
    gdf: pd.DataFrame,
    top_n: int = DEFAULT_TOP_N,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Level 別に、`Text`・`MSLink`・`EntityNum` の値の例を集める。

    値の例は、多い順の上位（件数つき）と、値の種類からの無作為抽出の 2 通りで残す。
    無作為抽出は値を並べ替えてから行うため、同じシードなら同じ例になる。

    Args:
        gdf: 読み込んだレイヤ。
        top_n: 多い順に残す値の数。
        sample_size: 無作為に抽出する値の数。
        seed: 無作為抽出の乱数シード。

    Returns:
        Level × 列ごとの `n_nonnull`・`n_unique`・`top_values`・`random_examples` の表
        （値のある組み合わせのみ）。
    """
    rng = np.random.default_rng(seed)
    rows = []
    for level, group in gdf.groupby("Level", sort=True):
        for column in EXAMPLE_COLUMNS:
            values = group[column].dropna()
            if values.empty:
                continue
            counts = values.value_counts()
            top_values = VALUE_SEPARATOR.join(
                f"{format_example_value(value)} ({count})"
                for value, count in counts.head(top_n).items()
            )
            uniques = np.array(sorted(counts.index, key=str), dtype=object)
            picked = rng.choice(uniques, size=min(sample_size, len(uniques)), replace=False)
            rows.append(
                {
                    "Level": level,
                    "column": column,
                    "n_nonnull": len(values),
                    "n_unique": len(counts),
                    "top_values": top_values,
                    "random_examples": VALUE_SEPARATOR.join(
                        format_example_value(v) for v in picked
                    ),
                }
            )
    return pd.DataFrame(
        rows, columns=["Level", "column", "n_nonnull", "n_unique", "top_values", "random_examples"]
    )


def parse_ulink_linkages(value: str) -> list[tuple[str, str]]:
    """`ULink`（DGN のリンク情報を JSON にしたもの）から、リンク ID と種類の組を取り出す。

    Args:
        value: `ULink` の文字列（例: `{"32047": [{"type": "ODBC", ...}]}`）。

    Returns:
        `(リンク ID, 種類)` の組のリスト（同じ組は 1 回だけ）。JSON として読めない場合は
        `[("invalid_json", "")]`。
    """
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [(INVALID_JSON_LINKAGE, "")]
    if not isinstance(parsed, dict):
        return [(INVALID_JSON_LINKAGE, "")]
    pairs: list[tuple[str, str]] = []
    for linkage_id, entries in parsed.items():
        entry_list = entries if isinstance(entries, list) else [entries]
        for entry in entry_list:
            linkage_type = str(entry.get("type", "")) if isinstance(entry, dict) else ""
            if (linkage_id, linkage_type) not in pairs:
                pairs.append((linkage_id, linkage_type))
    return pairs


def summarize_ulink_linkages(gdf: pd.DataFrame) -> pd.DataFrame:
    """Level 別に、`ULink` のリンク ID・種類ごとの地物数を数える。

    Args:
        gdf: 読み込んだレイヤ。

    Returns:
        `Level`・`linkage_id`・`linkage_type`・`n_features` の表。
    """
    with_ulink = gdf.loc[gdf["ULink"].notna(), ["Level", "ULink"]]
    records = [
        (level, linkage_id, linkage_type)
        for level, value in zip(with_ulink["Level"], with_ulink["ULink"], strict=True)
        for linkage_id, linkage_type in parse_ulink_linkages(value)
    ]
    frame = pd.DataFrame(records, columns=["Level", "linkage_id", "linkage_type"])
    table = frame.value_counts().rename("n_features").reset_index()
    return table.sort_values(["Level", "n_features"], ascending=[True, False], ignore_index=True)


def inventory_layer(
    code: str, path: Path, top_n: int, sample_size: int, seed: int
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """1 レイヤを読み、すべての表とレイヤの概要を作る。

    Args:
        code: レイヤ略号。
        path: merge_*.gpkg のパス。
        top_n: 値の例として多い順に残す数。
        sample_size: 値の例として無作為に抽出する数。
        seed: 無作為抽出の乱数シード。

    Returns:
        (表のキー → 先頭に `layer` 列を足した表, レイヤの概要の辞書)。
    """
    info = pyogrio.read_info(path)
    declared_dtypes = dict(zip(info["fields"], info["dtypes"], strict=True))
    gdf = read_survey_layer(path)
    geom_types = gdf.geometry.geom_type
    geometry_classes = classify_geometry_types(geom_types)
    locations = flag_geometry_locations(gdf.geometry)

    tables = {
        "columns": summarize_columns(gdf, declared_dtypes),
        "geometry_types": count_geometry_types(geom_types, geometry_classes),
        "levels": summarize_levels(gdf, geometry_classes),
        "value_distribution": count_value_distribution(gdf),
        "style_combinations": count_style_combinations(gdf, geometry_classes),
        "sizes_by_level": summarize_sizes_by_level(gdf, geometry_classes, locations),
        "attribute_examples": summarize_attribute_examples(gdf, top_n, sample_size, seed),
        "ulink_linkages": summarize_ulink_linkages(gdf),
    }
    for table in tables.values():
        table.insert(0, "layer", code)

    texts = gdf["Text"].dropna()
    linkages = tables["ulink_linkages"]
    overview = {
        "path": to_project_relative_string(path),
        "n_features": len(gdf),
        "declared_geometry_type": info["geometry_type"],
        "declared_crs": info["crs"],
        "assigned_crs": SURVEY_CRS,
        "n_levels": int(gdf["Level"].nunique()),
        "geometry_class_counts": {k: int(v) for k, v in geometry_classes.value_counts().items()},
        "location_counts": {k: int(v) for k, v in locations.value_counts().items()},
        "n_text": len(texts),
        "n_text_not_utf8": int((~texts.map(is_valid_utf8)).sum()),
        "n_ulink": int(gdf["ULink"].notna().sum()),
        "n_ulink_invalid_json": int(
            linkages.loc[linkages["linkage_id"] == INVALID_JSON_LINKAGE, "n_features"].sum()
        ),
    }
    return tables, overview


def run_inventory(
    input_dir: Path,
    output_dir: Path,
    layers: Sequence[str] = SURVEY_LAYER_CODES,
    top_n: int = DEFAULT_TOP_N,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> Path:
    """指定したレイヤを集計し、CSV 群と来歴つきの概要 JSON を保存する。

    Args:
        input_dir: merge_*.gpkg を置いたディレクトリ。
        output_dir: 出力ディレクトリ（相対パスはプロジェクトルート基準）。
        layers: 集計するレイヤ略号。
        top_n: 値の例として多い順に残す数。
        sample_size: 値の例として無作為に抽出する数。
        seed: 無作為抽出の乱数シード。

    Returns:
        概要 JSON のパス。

    Raises:
        ValueError: レイヤ略号が重複している場合、または `top_n`・`sample_size` が 1 未満の場合。
    """
    if len(set(layers)) != len(layers):
        raise ValueError(f"レイヤ略号が重複しています: {list(layers)}")
    if top_n < 1 or sample_size < 1:
        raise ValueError(
            "top_n と sample_size は 1 以上にしてください"
            f"（top_n={top_n}, sample_size={sample_size}）"
        )
    resolved_input_dir = resolve_existing_path(input_dir)
    output_root = output_dir if output_dir.is_absolute() else PROJECT_ROOT / output_dir
    output_root.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[pd.DataFrame]] = {key: [] for key in OUTPUT_TABLE_FILES}
    overviews: dict[str, Any] = {}
    input_paths: list[Path] = []
    for code in layers:
        path = layer_path(resolved_input_dir, code)
        if not path.is_file():
            raise FileNotFoundError(f"測量GISのファイルが見つかりません: {path}")
        print(f"[{code}] 集計中: {path.name}")
        tables, overview = inventory_layer(code, path, top_n, sample_size, seed)
        for key, table in tables.items():
            collected[key].append(table)
        overviews[code] = overview
        input_paths.append(path)
        print(f"[{code}] 地物 {overview['n_features']:,} 件・Level {overview['n_levels']} 種")

    outputs: dict[str, str] = {}
    for key, file_name in OUTPUT_TABLE_FILES.items():
        table_path = output_root / file_name
        pd.concat(collected[key], ignore_index=True).to_csv(
            table_path, index=False, encoding="utf-8"
        )
        outputs[key] = to_project_relative_string(table_path)

    summary = {
        "description": (
            "測量GIS（merge_*.gpkg）の属性の集計。Level 別の件数・描画属性・大きさ・属性値の例。"
        ),
        "conditions": {
            "assigned_crs": SURVEY_CRS,
            "text_read_encoding": TEXT_READ_ENCODING,
            "text_output_note": (
                "Text の ASCII 以外のバイトは \\xNN の形で出力する"
                "（文字コードは未確認のため解読しない）"
            ),
            "dummy_origin": list(DUMMY_ORIGIN),
            "dummy_tolerance_m": DUMMY_TOLERANCE_M,
            "valid_extent": list(VALID_EXTENT),
            "size_note": (
                "長さ・面積は EPSG:5897 の座標（メートル）で計算し、空・ダミー・範囲外の地物を除く"
            ),
            "top_n": top_n,
            "sample_size": sample_size,
            "seed": seed,
        },
        "layers": overviews,
        "outputs": outputs,
        "provenance": build_provenance(SCRIPT_NAME, input_paths),
    }
    summary_path = output_root / SUMMARY_FILE_NAME
    save_summary(summary, summary_path)
    return summary_path


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作る。

    Returns:
        argparse.ArgumentParser: 入出力ディレクトリ・レイヤ・値の例の件数・シードを受けるパーサー。
    """
    parser = argparse.ArgumentParser(description="測量GIS（merge_*.gpkg）の属性を集計する。")
    parser.add_argument(
        "--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="merge_*.gpkg のディレクトリ"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="出力ディレクトリ"
    )
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=SURVEY_LAYER_CODES,
        default=list(SURVEY_LAYER_CODES),
        help="集計するレイヤ",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="多い順に残す値の例の数")
    parser.add_argument(
        "--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="無作為に抽出する値の例の数"
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="値の例を無作為抽出する乱数シード"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """コマンドラインから集計を実行する。

    Args:
        argv: コマンドライン引数（`None` なら `sys.argv` を使う）。
    """
    args = build_argument_parser().parse_args(argv)
    summary_path = run_inventory(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        layers=args.layers,
        top_n=args.top_n,
        sample_size=args.sample_size,
        seed=args.seed,
    )
    print(f"概要を保存しました: {to_project_relative_string(summary_path)}")


if __name__ == "__main__":
    main()
