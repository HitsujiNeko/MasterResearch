"""urban_paramsパッケージのテストで共通利用するフィクスチャ。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fiona
import pytest
from pyproj import CRS, Transformer

from src.analysis.urban_params import io as urban_params_io
from src.analysis.urban_params.io import LayerResource
from src.common.geo_metadata import BBox

# テスト用の解析範囲BBox。fine_res=10m, coarse_res=20mで factor=2 となる。
ANALYSIS_BBOX = BBox(0.0, 0.0, 80.0, 80.0)
ANALYSIS_CRS = CRS.from_epsg(3857)


def _make_layer_resource(gpkg_path: Path, layer_name: str) -> LayerResource:
    """同一CRS（恒等変換）のLayerResourceを作成する。"""
    identity = Transformer.from_crs(ANALYSIS_CRS, ANALYSIS_CRS, always_xy=True)
    return LayerResource(
        path=gpkg_path,
        layer_name=layer_name,
        source_crs=ANALYSIS_CRS,
        analysis_crs=ANALYSIS_CRS,
        to_analysis=identity,
        from_analysis=identity,
    )


@pytest.fixture()
def counting_readers(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """実際にファイルを読んだ回数を数えるフェイクを差し込む。

    キャッシュ自身が持つ ``load_counts`` とは独立に数えることで、
    「読み込みが1回で済む」ことを実装の自己申告に頼らずに確認する。
    ``test_io.py``（単体テスト）・``test_run.py``（``main()`` 経由の結合テスト）の
    双方が同じ差し替え対象・カウント方式を必要とするため、ここに集約する。

    ``features`` は2つの経路を合算する。``_iter_feature_records_uncached()``
    （キャッシュ非活性時、および全域を覆わない検索）と ``_read_full_layer_features()``
    （キャッシュ活性時に全域を覆うと判定してからの実読み込み）で、判定用に開いた
    ファイルを読み込みにも使い回すため（``iter_feature_records()`` 参照）、実読み込みが
    後者だけを通ることがある。片方だけを数えると、二重オープン解消後の実読み込みを
    取りこぼす。
    """
    counts = {"dataframe": 0, "features": 0}
    original_frame = urban_params_io._read_layer_dataframe_uncached
    original_records = urban_params_io._iter_feature_records_uncached
    original_full_layer = urban_params_io._read_full_layer_features

    def counting_frame(resource: LayerResource, columns: list[str] | None) -> Any:
        """GeoDataFrameの実読み込み回数を数える。"""
        counts["dataframe"] += 1
        return original_frame(resource, columns)

    def counting_records(resource: LayerResource, bbox_analysis: BBox) -> Any:
        """フィーチャの実読み込み回数を数える（キャッシュ非活性時・全域非対象時の経路）。"""
        counts["features"] += 1
        return original_records(resource, bbox_analysis)

    def counting_full_layer(src: Any) -> Any:
        """フィーチャの実読み込み回数を数える（キャッシュ活性時に全域を覆う経路）。"""
        counts["features"] += 1
        return original_full_layer(src)

    monkeypatch.setattr(urban_params_io, "_read_layer_dataframe_uncached", counting_frame)
    monkeypatch.setattr(urban_params_io, "_iter_feature_records_uncached", counting_records)
    monkeypatch.setattr(urban_params_io, "_read_full_layer_features", counting_full_layer)
    return counts


@pytest.fixture()
def polygon_resource(tmp_path: Path) -> LayerResource:
    """coarseセル(0, 0)を1セル分ちょうど覆うポリゴンを持つレイヤ。"""
    gpkg_path = tmp_path / "polygons.gpkg"
    schema = {"geometry": "Polygon", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


def _write_building_layer(gpkg_path: Path, records: list[dict[str, object]]) -> None:
    """建物レイヤ（高さ・推定分散つきポリゴン）を書き出す。

    Args:
        gpkg_path: 出力先のGPKGパス。
        records: ``bounds``（minx, miny, maxx, maxy）・``height``・``var`` を
            持つ辞書のリスト。``height`` と ``var`` は ``None`` を許容する。
    """
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        for record in records:
            min_x, min_y, max_x, max_y = record["bounds"]
            ring = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
                (min_x, min_y),
            ]
            dst.write(
                {
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"height": record["height"], "var": record["var"]},
                }
            )


@pytest.fixture()
def building_resource(tmp_path: Path) -> LayerResource:
    """高さの有効・無効が混在する建物レイヤ。

    coarse_res=20m のグリッド（4x4セル）を前提に、各セルの期待値が手計算で
    確かめられるよう配置している。

    - セル(0, 0): 1セルを完全に覆う1棟。高さ10m・分散1（有効）
    - セル(0, 1): 1セルを完全に覆う1棟。高さ20m・分散-1（高さは無効）
    - セル(1, 0): 1セルを完全に覆う1棟。高さ30m・分散なし（高さは無効）
    - セル(1, 1): 1/4セル分の2棟。高さ6m・分散0 と 高さ8m・分散2（いずれも有効）
    """
    gpkg_path = tmp_path / "buildings.gpkg"
    _write_building_layer(
        gpkg_path,
        [
            {"bounds": (0.0, 60.0, 20.0, 80.0), "height": 10.0, "var": 1.0},
            {"bounds": (20.0, 60.0, 40.0, 80.0), "height": 20.0, "var": -1.0},
            {"bounds": (0.0, 40.0, 20.0, 60.0), "height": 30.0, "var": None},
            {"bounds": (20.0, 40.0, 30.0, 50.0), "height": 6.0, "var": 0.0},
            {"bounds": (30.0, 50.0, 40.0, 60.0), "height": 8.0, "var": 2.0},
        ],
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def overlap_building_resource(tmp_path: Path) -> LayerResource:
    """重なりベースの高さ帰属（新方式）固有の挙動を検証するための建物レイヤ。

    coarse_res=20m のグリッド（4x4セル）に、以下の4シナリオを独立したセルへ
    配置する。既存の ``building_resource`` が使うセルとは重ならない。

    - セル(0, 0): 低い大建物（h=10.0, 20x20＝400m2）と高い小建物（h=30.0,
      4x4＝16m2）が同居する。小建物はfineセル中心 (5,65)・(15,65)・
      (5,75)・(15,75) をどれも覆わない。``BUILD_H_MAX`` の「重なり∪重心」
      合成規則（``np.fmax()``）を検証するためのケース
      （期待値: ``BUILD_H_MEAN`` = 10.0・``BUILD_H_MAX`` = 30.0）
    - セル(3, 0): 高さ12m・200m2の建物が、高さ4m・400m2の建物に完全に
      重なる。上端高さ（重なる箇所は高い方）の面積平均（期待値8.0）に
      なることを検証する。GPKGへは**高さの降順**（12.0 -> 4.0）で書き込み、
      ``rasterize_max_value_field()`` の内部ソート契約を統合レベルでも
      確認する
    - セル(2, 2): 幅2mの小規模建物（h=25.0）。fineセル中心をどれも覆わない
      ため被覆が発生せず、``BUILD_H_MEAN`` の重心方式による補完を検証する
    - セル(3, 2) / セル(3, 3): 2セルにまたがる建物（h=15.0, x[50, 70)）。
      重心はセル(3, 3)側にのみ属するが、セル(3, 2)側にも張り出した被覆
      部分に高さが入ることを検証する
    """
    gpkg_path = tmp_path / "overlap_buildings.gpkg"
    _write_building_layer(
        gpkg_path,
        [
            # セル(0,0): 低い大建物 + 高い小建物。
            {"bounds": (0.0, 60.0, 20.0, 80.0), "height": 10.0, "var": 1.0},
            {"bounds": (8.0, 68.0, 12.0, 72.0), "height": 30.0, "var": 1.0},
            # セル(3,0): 重なる2棟。高さの降順（12.0 -> 4.0）で書き込む。
            {"bounds": (0.0, 0.0, 20.0, 10.0), "height": 12.0, "var": 1.0},
            {"bounds": (0.0, 0.0, 20.0, 20.0), "height": 4.0, "var": 1.0},
            # セル(2,2): fineセル中心をどれも覆わない小規模建物。
            {"bounds": (41.0, 21.0, 43.0, 23.0), "height": 25.0, "var": 1.0},
            # セル(3,2)/(3,3): 2セルにまたがる建物。重心はセル(3,3)側。
            {"bounds": (50.0, 0.0, 70.0, 20.0), "height": 15.0, "var": 1.0},
        ],
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def edge_building_resource(tmp_path: Path) -> LayerResource:
    """重心がグリッド範囲外に出る建物1棟だけを持つレイヤ。

    x 60-100 / y 30-50 の建物。重心 (80, 40) の列添字は範囲外だが、
    x 60-80 の部分はグリッド内にあり被覆率には計上される。
    """
    gpkg_path = tmp_path / "edge_building.gpkg"
    _write_building_layer(
        gpkg_path, [{"bounds": (60.0, 30.0, 100.0, 50.0), "height": 12.0, "var": 1.0}]
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def multipolygon_building_resource(tmp_path: Path) -> LayerResource:
    """MultiPolygon の建物1件を持つレイヤ。

    coarseセル(0, 0) と (1, 1) にそれぞれ 1/4 セル分の同面積パートを持つ。
    重心は2パートの中間 (15, 60) で、セル境界（y=60）上にあり、セル(1, 0) へ帰属する。
    """
    gpkg_path = tmp_path / "multipolygon.gpkg"
    schema = {"geometry": "MultiPolygon", "properties": {"height": "float", "var": "float"}}
    part_a = [[(0.0, 70.0), (10.0, 70.0), (10.0, 80.0), (0.0, 80.0), (0.0, 70.0)]]
    part_b = [[(20.0, 40.0), (30.0, 40.0), (30.0, 50.0), (20.0, 50.0), (20.0, 40.0)]]
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "MultiPolygon", "coordinates": [part_a, part_b]},
                "properties": {"height": 12.0, "var": 1.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def mixed_geometry_building_resource(tmp_path: Path) -> LayerResource:
    """ポリゴン1件とライン1件を持つ建物レイヤ（測量GIS由来の構成を模す）。"""
    gpkg_path = tmp_path / "mixed_geometry.gpkg"
    schema = {"geometry": "Unknown", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(20, 20), (40, 40)]},
                "properties": {"height": 7.0, "var": 1.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def empty_building_resource(tmp_path: Path) -> LayerResource:
    """建物が1件も無い建物レイヤ。"""
    gpkg_path = tmp_path / "empty_buildings.gpkg"
    _write_building_layer(gpkg_path, [])
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def null_geometry_building_resource(tmp_path: Path) -> LayerResource:
    """NULLジオメトリ1件と正常なポリゴン1件を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "null_geometry.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write({"geometry": None, "properties": {"height": 99.0, "var": 1.0}})
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def negative_height_building_resource(tmp_path: Path) -> LayerResource:
    """高さが負値の建物1棟と、正常な建物1棟を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "negative_height.gpkg"
    _write_building_layer(
        gpkg_path,
        [
            {"bounds": (0.0, 60.0, 20.0, 80.0), "height": 10.0, "var": 1.0},
            {"bounds": (20.0, 60.0, 40.0, 80.0), "height": -5.0, "var": 1.0},
        ],
    )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def height_without_variance_resource(tmp_path: Path) -> LayerResource:
    """高さ属性はあるが推定分散を持たない建物レイヤ。"""
    gpkg_path = tmp_path / "height_only.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float"}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def invalid_building_resource(tmp_path: Path) -> LayerResource:
    """自己交差する不正ポリゴン1棟と、正常なポリゴン1棟を持つ建物レイヤ。"""
    gpkg_path = tmp_path / "invalid_buildings.gpkg"
    schema = {"geometry": "Polygon", "properties": {"height": "float", "var": "float"}}
    # 8の字型（自己交差）のリング。shapely の is_valid が偽になる。
    bowtie_ring = [(20.0, 40.0), (40.0, 60.0), (40.0, 40.0), (20.0, 60.0), (20.0, 40.0)]
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[(0, 60), (20, 60), (20, 80), (0, 80), (0, 60)]],
                },
                "properties": {"height": 10.0, "var": 1.0},
            }
        )
        dst.write(
            {
                "geometry": {"type": "Polygon", "coordinates": [bowtie_ring]},
                "properties": {"height": 15.0, "var": 1.0},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def centroid_polygon_resource(tmp_path: Path) -> LayerResource:
    """重心が既知の正方形ポリゴン群を持つレイヤ。

    coarse_res=20m のグリッドを前提に、通常セル・セル境界上・グリッド範囲外の
    3種類の重心を含める。
    """
    gpkg_path = tmp_path / "centroids.gpkg"
    schema = {"geometry": "Polygon", "properties": {}}
    # (重心X, 重心Y): 期待セルは (row, col) = (floor((80-y)/20), floor(x/20))
    centroids = [
        (10.0, 70.0),  # セル(0, 0)
        (30.0, 30.0),  # セル(2, 1)
        (20.0, 60.0),  # セル境界上 -> セル(1, 1)
        (70.0, 10.0),  # セル(3, 3)
        (90.0, 40.0),  # グリッド範囲外
    ]
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        for center_x, center_y in centroids:
            half = 4.0
            ring = [
                (center_x - half, center_y - half),
                (center_x + half, center_y - half),
                (center_x + half, center_y + half),
                (center_x - half, center_y + half),
                (center_x - half, center_y - half),
            ]
            dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def line_resource(tmp_path: Path) -> LayerResource:
    """解析範囲を横断するラインを持つレイヤ。"""
    gpkg_path = tmp_path / "lines.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 65), (80, 65)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def boundary_line_resource(tmp_path: Path) -> LayerResource:
    """coarseセル境界（y=60）上を走る水平ラインを持つレイヤ。"""
    gpkg_path = tmp_path / "boundary.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 60), (80, 60)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")


@pytest.fixture()
def diagonal_line_resource(tmp_path: Path) -> LayerResource:
    """対角線ライン (0, 0)→(80, 80) を持つレイヤ。"""
    gpkg_path = tmp_path / "diagonal.gpkg"
    schema = {"geometry": "LineString", "properties": {}}
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="data", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(0, 0), (80, 80)]},
                "properties": {},
            }
        )
    return _make_layer_resource(gpkg_path, "data")
