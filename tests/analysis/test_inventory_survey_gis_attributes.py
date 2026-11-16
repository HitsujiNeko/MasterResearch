"""`src.analysis.inventory_survey_gis_attributes` のテスト。

実データ（merge_*.gpkg）と同じ性質を持つ小さな合成 GeoPackage を作って検証する:
CRS なし・ジオメトリ型の混在・`Text` に UTF-8 として不正なバイト列・
座標 (500,000, 1,000,000) 付近のダミーの地物。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from src.analysis import inventory_survey_gis_attributes as inventory

# TCVN3 とみられるバイト列（実データの「H\xb5 N\xe9i」と同じ形）
NON_UTF8_TEXT_BYTES = b"H\xb5 N\xe9i"
# 実データにある ULink の形（DGN のリンク情報を JSON にしたもの）
ULINK_ODBC = '{ "32047": [ { "size": 8, "raw": [ "0x1003" ], "type": "ODBC" } ] }'
ULINK_TWO_KINDS = (
    '{ "0": [ { "size": 8, "raw": [ "0x0000" ], "type": "unknown" } ], '
    '"31225": [ { "size": 24, "raw": [ "0x100b" ], "type": "unknown" } ] }'
)
# 図郭内の基準点（EPSG:5897）
BASE_X = 585_000.0
BASE_Y = 2_330_000.0


def _make_layer_frame() -> gpd.GeoDataFrame:
    """合成レイヤの GeoDataFrame（CRS なし）を作る。

    Level 5: 面 3 件（10 m 四方・20 m 四方・ダミー位置の面）と点 1 件
    Level 7: 線 2 件（長さ 30 m・50 m）
    """
    geometries = [
        box(BASE_X, BASE_Y, BASE_X + 10, BASE_Y + 10),
        box(BASE_X + 100, BASE_Y, BASE_X + 120, BASE_Y + 20),
        box(499_999.5, 999_999.5, 500_000.5, 1_000_000.5),
        Point(BASE_X + 5, BASE_Y + 5),
        LineString([(BASE_X, BASE_Y + 50), (BASE_X + 30, BASE_Y + 50)]),
        LineString([(BASE_X, BASE_Y + 80), (BASE_X + 50, BASE_Y + 80)]),
    ]
    return gpd.GeoDataFrame(
        {
            "Type": [6, 6, 6, 17, 3, 3],
            "Level": [5, 5, 5, 5, 7, 7],
            "GraphicGroup": [0, 0, 0, 0, 12, 0],
            "ColorIndex": [10, 10, 10, 10, 11, 11],
            "Weight": [1, 1, 1, 0, 0, 0],
            "Style": [0, 0, 0, 0, 2, 2],
            "EntityNum": [None, None, None, None, 3, None],
            "MSLink": [None, None, None, None, 41, 41],
            "Text": [None, None, None, "PLACEHOLDER", "28", "28"],
            "ULink": [ULINK_ODBC, None, None, None, ULINK_TWO_KINDS, "not json"],
        },
        geometry=geometries,
        crs=None,
    )


def _write_survey_gpkg(path: Path, frame: gpd.GeoDataFrame) -> None:
    """合成レイヤを merge_*.gpkg と同じ形（型混在・CRS なし）で書き、Text を不正なバイト列にする。

    空間索引のトリガーは SQLite 単体に無い関数（ST_IsEmpty）を呼ぶため、索引なしで書く。
    """
    pyogrio.write_dataframe(
        frame,
        path,
        layer="elements",
        geometry_type="Unknown",
        promote_to_multi=False,
        layer_options={"SPATIAL_INDEX": "NO"},
    )
    # GDAL は UTF-8 で書くため、実データと同じ不正なバイト列は SQLite で直接書き込む
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE elements SET Text = CAST(? AS TEXT) WHERE Text = 'PLACEHOLDER'",
            (NON_UTF8_TEXT_BYTES,),
        )


@pytest.fixture
def survey_dir(tmp_path: Path) -> Path:
    """合成の merge_DC.gpkg・merge_TH.gpkg を置いたディレクトリ。"""
    directory = tmp_path / "survey"
    directory.mkdir()
    frame = _make_layer_frame()
    _write_survey_gpkg(directory / "merge_DC.gpkg", frame)
    _write_survey_gpkg(directory / "merge_TH.gpkg", frame.iloc[4:].reset_index(drop=True))
    return directory


@pytest.fixture
def survey_layer(survey_dir: Path) -> gpd.GeoDataFrame:
    """合成の merge_DC.gpkg を読んだもの。"""
    return inventory.read_survey_layer(survey_dir / "merge_DC.gpkg")


def test_layer_path_builds_merge_file_name(tmp_path: Path) -> None:
    assert inventory.layer_path(tmp_path, "DC") == tmp_path / "merge_DC.gpkg"


def test_layer_path_rejects_unknown_code(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="未知のレイヤ略号"):
        inventory.layer_path(tmp_path, "XX")


def test_read_survey_layer_assigns_crs_and_keeps_bytes(survey_layer: gpd.GeoDataFrame) -> None:
    assert survey_layer.crs.to_epsg() == 5897
    # 不正なバイト列が失われず、latin-1 から元のバイト列に戻せる
    text = survey_layer.loc[3, "Text"]
    assert text.encode(inventory.TEXT_READ_ENCODING) == NON_UTF8_TEXT_BYTES
    # 型の混在がそのまま読める
    assert set(survey_layer.geometry.geom_type) == {"Polygon", "Point", "LineString"}


def test_read_survey_layer_rejects_file_with_crs(tmp_path: Path) -> None:
    path = tmp_path / "merge_DC.gpkg"
    frame = _make_layer_frame().drop(index=3).set_crs("EPSG:5897")
    pyogrio.write_dataframe(
        frame, path, layer="elements", geometry_type="Unknown", promote_to_multi=False
    )
    with pytest.raises(ValueError, match="CRS"):
        inventory.read_survey_layer(path)


def test_classify_geometry_types_maps_to_classes() -> None:
    geom_types = pd.Series(["Point", "MultiLineString", "MultiPolygon", "GeometryCollection", None])
    result = inventory.classify_geometry_types(geom_types)
    assert result.tolist() == ["point", "line", "polygon", "other", "other"]


def test_flag_geometry_locations_distinguishes_four_cases() -> None:
    geometries = gpd.GeoSeries(
        [
            box(BASE_X, BASE_Y, BASE_X + 1, BASE_Y + 1),
            Polygon(),
            None,
            Point(500_000.1, 999_999.9),
            Point(100.0, 100.0),
            # ダミーの点から図郭まで伸びる線はダミーではなく範囲外
            LineString([(500_000.0, 1_000_000.0), (BASE_X, BASE_Y)]),
        ]
    )
    result = inventory.flag_geometry_locations(geometries)
    assert result.tolist() == [
        inventory.LOCATION_VALID,
        inventory.LOCATION_EMPTY,
        inventory.LOCATION_EMPTY,
        inventory.LOCATION_DUMMY,
        inventory.LOCATION_OUT_OF_EXTENT,
        inventory.LOCATION_OUT_OF_EXTENT,
    ]


def test_escape_text_and_utf8_check() -> None:
    latin1_text = NON_UTF8_TEXT_BYTES.decode(inventory.TEXT_READ_ENCODING)
    assert inventory.escape_text(latin1_text) == "H\\xb5 N\\xe9i"
    assert inventory.escape_text("28") == "28"
    assert not inventory.is_valid_utf8(latin1_text)
    # 正しい UTF-8 のバイト列（「à」）は UTF-8 として読める
    assert inventory.is_valid_utf8("à".encode().decode(inventory.TEXT_READ_ENCODING))


def test_summarize_columns_reports_nulls_and_declared_dtype(survey_layer: gpd.GeoDataFrame) -> None:
    declared = {"Level": "int32", "MSLink": "int32", "Text": "object"}
    result = inventory.summarize_columns(survey_layer, declared).set_index("column")
    assert result.loc["MSLink", "declared_dtype"] == "int32"
    assert result.loc["MSLink", "null_count"] == 4
    assert result.loc["MSLink", "null_ratio"] == pytest.approx(4 / 6)
    assert result.loc["Level", "n_unique"] == 2
    assert result.loc["Text", "n_unique"] == 2


def test_count_geometry_types(survey_layer: gpd.GeoDataFrame) -> None:
    geom_types = survey_layer.geometry.geom_type
    result = inventory.count_geometry_types(
        geom_types, inventory.classify_geometry_types(geom_types)
    )
    assert result.to_dict("records") == [
        {"geom_type": "Polygon", "geometry_class": "polygon", "count": 3},
        {"geom_type": "LineString", "geometry_class": "line", "count": 2},
        {"geom_type": "Point", "geometry_class": "point", "count": 1},
    ]


def test_summarize_levels(survey_layer: gpd.GeoDataFrame) -> None:
    classes = inventory.classify_geometry_types(survey_layer.geometry.geom_type)
    result = inventory.summarize_levels(survey_layer, classes).set_index("Level")
    assert result.loc[5, ["n_total", "n_point", "n_line", "n_polygon", "n_other"]].tolist() == [
        4,
        1,
        0,
        3,
        0,
    ]
    assert result.loc[
        7, ["n_total", "n_line", "n_text", "n_mslink", "n_entitynum", "n_ulink"]
    ].tolist() == [
        2,
        2,
        2,
        2,
        1,
        2,
    ]
    assert result.loc[7, "n_graphic_group_nonzero"] == 1
    assert result.loc[5, "n_ulink"] == 1


def test_count_value_distribution(survey_layer: gpd.GeoDataFrame) -> None:
    result = inventory.count_value_distribution(survey_layer, columns=("ColorIndex", "Style"))
    color = result[result["column"] == "ColorIndex"]
    assert color[["value", "count"]].to_dict("records") == [
        {"value": 10, "count": 4},
        {"value": 11, "count": 2},
    ]
    assert result[result["column"] == "Style"]["count"].sum() == 6


def test_count_style_combinations(survey_layer: gpd.GeoDataFrame) -> None:
    classes = inventory.classify_geometry_types(survey_layer.geometry.geom_type)
    result = inventory.count_style_combinations(survey_layer, classes)
    level7 = result[result["Level"] == 7].iloc[0]
    assert (level7["geometry_class"], level7["Type"], level7["ColorIndex"], level7["Style"]) == (
        "line",
        3,
        11,
        2,
    )
    assert level7["count"] == 2
    assert level7["n_graphic_group_nonzero"] == 1
    # Level 5 は面（Weight 1）と点（Weight 0）の 2 つの組み合わせ
    assert result[result["Level"] == 5]["count"].tolist() == [3, 1]


def test_summarize_sizes_by_level_excludes_dummy(survey_layer: gpd.GeoDataFrame) -> None:
    classes = inventory.classify_geometry_types(survey_layer.geometry.geom_type)
    locations = inventory.flag_geometry_locations(survey_layer.geometry)
    result = inventory.summarize_sizes_by_level(survey_layer, classes, locations)
    # 点は大きさを持たないため対象外
    assert set(result["geometry_class"]) == {"line", "polygon"}
    polygon = result[result["geometry_class"] == "polygon"].iloc[0]
    assert (polygon["n_features"], polygon["n_measured"], polygon["n_dummy"]) == (3, 2, 1)
    assert polygon["size_metric"] == "area_m2"
    # ダミーの面（1 m²）を除いた 100 m² と 400 m² の中央値・最大
    assert polygon["size_median"] == pytest.approx(250.0)
    assert polygon["size_max"] == pytest.approx(400.0)
    line = result[result["geometry_class"] == "line"].iloc[0]
    assert line["size_metric"] == "length_m"
    assert line["size_median"] == pytest.approx(40.0)
    assert line["size_max"] == pytest.approx(50.0)


def test_summarize_sizes_by_level_all_excluded_gives_nan() -> None:
    frame = gpd.GeoDataFrame(
        {"Level": [1]}, geometry=[box(499_999.5, 999_999.5, 500_000.5, 1_000_000.5)]
    )
    classes = inventory.classify_geometry_types(frame.geometry.geom_type)
    locations = inventory.flag_geometry_locations(frame.geometry)
    row = inventory.summarize_sizes_by_level(frame, classes, locations).iloc[0]
    assert row["n_measured"] == 0
    assert np.isnan(row["size_median"])


def test_format_example_value() -> None:
    assert inventory.format_example_value(41.0) == "41"
    assert inventory.format_example_value(np.float64(3.0)) == "3"
    assert inventory.format_example_value(2.5) == "2.5"
    assert inventory.format_example_value(NON_UTF8_TEXT_BYTES.decode("latin-1")) == "H\\xb5 N\\xe9i"


def test_summarize_attribute_examples(survey_layer: gpd.GeoDataFrame) -> None:
    result = inventory.summarize_attribute_examples(survey_layer, top_n=1, sample_size=5, seed=0)
    text7 = result[(result["Level"] == 7) & (result["column"] == "Text")].iloc[0]
    assert text7["top_values"] == "28 (2)"
    assert (text7["n_nonnull"], text7["n_unique"]) == (2, 1)
    text5 = result[(result["Level"] == 5) & (result["column"] == "Text")].iloc[0]
    assert text5["random_examples"] == "H\\xb5 N\\xe9i"
    mslink7 = result[(result["Level"] == 7) & (result["column"] == "MSLink")].iloc[0]
    assert mslink7["top_values"] == "41 (2)"
    # 値の無い組み合わせ（Level 5 の MSLink）は行を作らない
    assert result[(result["Level"] == 5) & (result["column"] == "MSLink")].empty


def test_summarize_attribute_examples_is_reproducible() -> None:
    frame = pd.DataFrame(
        {"Level": [1] * 20, "Text": [str(i) for i in range(20)], "MSLink": None, "EntityNum": None}
    )
    first = inventory.summarize_attribute_examples(frame, top_n=3, sample_size=4, seed=7)
    second = inventory.summarize_attribute_examples(frame, top_n=3, sample_size=4, seed=7)
    pd.testing.assert_frame_equal(first, second)
    assert len(first.loc[0, "random_examples"].split(inventory.VALUE_SEPARATOR)) == 4


def test_parse_ulink_linkages() -> None:
    assert inventory.parse_ulink_linkages(ULINK_ODBC) == [("32047", "ODBC")]
    assert inventory.parse_ulink_linkages(ULINK_TWO_KINDS) == [
        ("0", "unknown"),
        ("31225", "unknown"),
    ]
    assert inventory.parse_ulink_linkages("not json") == [(inventory.INVALID_JSON_LINKAGE, "")]
    assert inventory.parse_ulink_linkages("[1, 2]") == [(inventory.INVALID_JSON_LINKAGE, "")]


def test_summarize_ulink_linkages(survey_layer: gpd.GeoDataFrame) -> None:
    result = inventory.summarize_ulink_linkages(survey_layer)
    records = {
        (r["Level"], r["linkage_id"], r["linkage_type"]): r["n_features"]
        for r in result.to_dict("records")
    }
    assert records == {
        (5, "32047", "ODBC"): 1,
        (7, "0", "unknown"): 1,
        (7, "31225", "unknown"): 1,
        (7, inventory.INVALID_JSON_LINKAGE, ""): 1,
    }


def test_run_inventory_rejects_duplicate_layers(survey_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="重複"):
        inventory.run_inventory(survey_dir, tmp_path / "out", layers=["DC", "DC"])


def test_run_inventory_rejects_missing_file(survey_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="merge_GT.gpkg"):
        inventory.run_inventory(survey_dir, tmp_path / "out", layers=["GT"])


def test_main_writes_tables_and_summary(survey_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    inventory.main(
        [
            "--input-dir",
            str(survey_dir),
            "--output-dir",
            str(output_dir),
            "--layers",
            "DC",
            "TH",
            "--seed",
            "1",
        ]
    )
    for file_name in inventory.OUTPUT_TABLE_FILES.values():
        table = pd.read_csv(output_dir / file_name)
        assert table.columns[0] == "layer"
        assert set(table["layer"]) <= {"DC", "TH"}
    levels = pd.read_csv(output_dir / "levels.csv")
    assert levels.groupby("layer")["n_total"].sum().to_dict() == {"DC": 6, "TH": 2}
    # Text の不正なバイト列は ASCII に置き換えて書かれる
    examples = (output_dir / "attribute_examples.csv").read_text(encoding="utf-8")
    assert "H\\xb5 N\\xe9i" in examples

    summary = json.loads((output_dir / inventory.SUMMARY_FILE_NAME).read_text(encoding="utf-8"))
    dc = summary["layers"]["DC"]
    assert dc["n_features"] == 6
    assert dc["declared_crs"] is None
    assert dc["assigned_crs"] == "EPSG:5897"
    assert dc["location_counts"] == {"valid": 5, "dummy": 1}
    assert (dc["n_text"], dc["n_text_not_utf8"]) == (3, 1)
    assert (dc["n_ulink"], dc["n_ulink_invalid_json"]) == (3, 1)
    assert summary["conditions"]["seed"] == 1
    assert len(summary["provenance"]["inputs"]) == 2
