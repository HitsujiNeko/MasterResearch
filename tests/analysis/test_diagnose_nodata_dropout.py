"""diagnose_nodata_dropout.py（人口・夜間光の欠測による脱落の診断）のテスト。

本スクリプトの要は「脱落の原因を2つに切り分けられること」である。すなわち、ROI境界での
ラスタクリップに由来する境界帯（陸地・水域を問わずROI外周に沿う）と、データセット固有の
無効値マスク（ROI内部にも分布する）を、ROI境界からの距離で判別できることを検証する。

分類そのものの境界値（水域被覆0・0.9・欠測）と、距離の符号（ROI内外）に重点を置く。
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from src.analysis.diagnose_nodata_dropout import (
    ANALYSIS_AREA_COLUMN,
    LANDSCAN_2020_COLUMN,
    LANDSCAN_2023_COLUMN,
    NIGHTLIGHT_COLUMN,
    TARGET_COLUMN,
    WATER_COVERAGE_COLUMN,
    WORLDPOP_COLUMN,
    add_dropout_classification,
    add_roi_edge_distance,
    build_dropout_where_clause,
    classify_dropout_group,
    classify_water_class,
    count_base_cells,
    describe_raster,
    load_dropout_cells,
    resolve_metric_crs,
    summarize_dropout,
    summarize_group_distances,
)

# ハノイROIと同じ緯度帯（北緯約21度）に置いた正方形をテスト用ROIとする。
# 投影後の距離がメートルとして解釈できることを確かめるため、実データと同じ緯度帯を使う。
ROI_MIN_LON = 105.5
ROI_MIN_LAT = 21.0
ROI_SIZE_DEG = 0.1


@pytest.fixture
def roi_geometry() -> Polygon:
    """テスト用のROI（EPSG:4326の正方形ポリゴン）を返す。"""
    return Polygon(
        [
            (ROI_MIN_LON, ROI_MIN_LAT),
            (ROI_MIN_LON + ROI_SIZE_DEG, ROI_MIN_LAT),
            (ROI_MIN_LON + ROI_SIZE_DEG, ROI_MIN_LAT + ROI_SIZE_DEG),
            (ROI_MIN_LON, ROI_MIN_LAT + ROI_SIZE_DEG),
        ]
    )


class TestClassifyDropoutGroup:
    """要因グループの分類。"""

    @pytest.mark.parametrize(
        ("worldpop", "landscan", "nightlight", "expected"),
        [
            (True, False, False, "worldpop_only"),
            (False, True, False, "landscan_only"),
            (False, False, True, "nightlight_only"),
            (True, True, False, "worldpop_landscan"),
            (True, False, True, "worldpop_nightlight"),
            (False, True, True, "landscan_nightlight"),
            (True, True, True, "all_sources"),
        ],
    )
    def test_全ての組み合わせが一意のグループ名へ分類される(
        self, worldpop: bool, landscan: bool, nightlight: bool, expected: str
    ) -> None:
        assert classify_dropout_group(worldpop, landscan, nightlight) == expected

    def test_欠測が1つも無い場合は例外になる(self) -> None:
        """脱落セルでないものが母集団へ混入した場合に、黙って分類されないことを確かめる。"""
        with pytest.raises(ValueError, match="脱落セルではない"):
            classify_dropout_group(False, False, False)


class TestClassifyWaterClass:
    """水域被覆の分類（境界値）。"""

    @pytest.mark.parametrize(
        ("coverage", "expected"),
        [
            (0.0, "water_absent"),
            (0.0001, "water_partial"),
            (0.5, "water_partial"),
            (0.8999, "water_partial"),
            (0.9, "water_dominant"),
            (1.0, "water_dominant"),
        ],
    )
    def test_被覆率が区分の境界で正しく分かれる(self, coverage: float, expected: str) -> None:
        assert classify_water_class(coverage) == expected

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_欠測は0と区別してunknownになる(self, missing: float | None) -> None:
        """水域被覆自体が欠測のセルを陸地（0）として数えないことを確かめる。"""
        assert classify_water_class(missing) == "water_unknown"


class TestBuildDropoutWhereClause:
    """脱落セル抽出のSQL条件。"""

    def test_母数はROI内であってLSTの有無に依らない(self) -> None:
        """LSTを条件に入れると、脱落規模が観測フットプリントに左右されてしまう。"""
        clause = build_dropout_where_clause()
        assert f'"{ANALYSIS_AREA_COLUMN}" = 1' in clause
        assert TARGET_COLUMN not in clause
        for column in (
            WORLDPOP_COLUMN,
            LANDSCAN_2020_COLUMN,
            LANDSCAN_2023_COLUMN,
            NIGHTLIGHT_COLUMN,
        ):
            assert f'"{column}" IS NULL' in clause


class TestLoadDropoutCells:
    """非空間テーブルからの読み込み。"""

    @pytest.fixture
    def dataset_path(self, tmp_path: Path) -> Path:
        """脱落・非脱落・LST欠測・ROI外を含む、ジオメトリを持たないGeoPackageを作る。"""
        table = pd.DataFrame(
            {
                "cell_id": [1, 2, 3, 4, 5],
                "lon": [ROI_MIN_LON + 0.01 * i for i in range(1, 6)],
                "lat": [ROI_MIN_LAT + 0.01 * i for i in range(1, 6)],
                WORLDPOP_COLUMN: [np.nan, 5.0, 5.0, np.nan, np.nan],
                LANDSCAN_2020_COLUMN: [10.0, np.nan, 10.0, 10.0, 10.0],
                LANDSCAN_2023_COLUMN: [11.0, np.nan, 11.0, 11.0, 11.0],
                NIGHTLIGHT_COLUMN: [2.0, 2.0, 2.0, 2.0, 2.0],
                # cell 4 はLSTが欠測の脱落セル（観測フットプリント外でも母数に含める）。
                TARGET_COLUMN: [32.0, 34.0, 35.0, np.nan, 33.0],
                WATER_COVERAGE_COLUMN: [0.95, 0.0, 0.0, 0.9, 0.9],
                "NDWI": [0.1, -0.5, -0.5, 0.2, 0.2],
                # cell 5 はROI外。母数からも脱落セルからも外れる。
                ANALYSIS_AREA_COLUMN: [1, 1, 1, 1, 0],
            }
        )
        path = tmp_path / "dataset.gpkg"
        pyogrio.write_dataframe(table, path, layer="cells", driver="GPKG")
        return path

    def test_ジオメトリを持たないテーブルから点ジオメトリを構築する(
        self, dataset_path: Path
    ) -> None:
        """データセットは lon/lat 列のみを持つ属性テーブルであり、点を組み立てる必要がある。"""
        cells = load_dropout_cells(dataset_path, layer="cells")
        assert isinstance(cells, gpd.GeoDataFrame)
        assert cells.crs is not None and cells.crs.to_epsg() == 4326
        assert cells.geometry.iloc[0].x == pytest.approx(ROI_MIN_LON + 0.01)

    def test_脱落していないセルとROI外セルは読み込まれない(self, dataset_path: Path) -> None:
        cells = load_dropout_cells(dataset_path, layer="cells")
        assert sorted(cells["cell_id"]) == [1, 2, 4]

    def test_LSTが欠測の脱落セルも読み込まれる(self, dataset_path: Path) -> None:
        """観測フットプリント外のセルを落とすと、脱落規模が観測依存になってしまう。"""
        cells = load_dropout_cells(dataset_path, layer="cells")
        assert 4 in set(cells["cell_id"])

    def test_母数はROI内の全セルになる(self, dataset_path: Path) -> None:
        """脱落率の分母がLST有効セルではなくROI内全セルであることを確かめる。"""
        assert count_base_cells(dataset_path, layer="cells") == 4


def _build_cells(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    """テスト用の脱落セルGeoDataFrameを組み立てる。

    Args:
        rows: `lon` / `lat` と各変数の値を持つ辞書のリスト。

    Returns:
        EPSG:4326のGeoDataFrame。
    """
    frame = pd.DataFrame(rows)
    return gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(frame["lon"], frame["lat"]), crs="EPSG:4326"
    )


class TestAddDropoutClassification:
    """欠測パターンからの列付与。"""

    def test_欠測パターンごとにグループと水域区分が付く(self) -> None:
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: np.nan,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: 11.0,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.95,
                },
                {
                    "lon": ROI_MIN_LON + 0.06,
                    "lat": ROI_MIN_LAT + 0.06,
                    WORLDPOP_COLUMN: 5.0,
                    LANDSCAN_2020_COLUMN: np.nan,
                    LANDSCAN_2023_COLUMN: np.nan,
                    NIGHTLIGHT_COLUMN: np.nan,
                    WATER_COVERAGE_COLUMN: 0.0,
                },
            ]
        )
        classified = add_dropout_classification(cells)
        assert list(classified["dropout_group"]) == ["worldpop_only", "landscan_nightlight"]
        assert list(classified["water_class"]) == ["water_dominant", "water_absent"]

    def test_LandScanの欠測が食い違う場合に警告が出る(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """2020を代表として分類するため、食い違いが黙って誤分類になることを防ぐ。"""
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: 5.0,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: np.nan,
                    NIGHTLIGHT_COLUMN: np.nan,
                    WATER_COVERAGE_COLUMN: 0.0,
                }
            ]
        )
        with caplog.at_level("WARNING"):
            add_dropout_classification(cells)
        assert "LandScan 2020 と 2023" in caplog.text

    def test_欠測が一致していれば警告は出ない(self, caplog: pytest.LogCaptureFixture) -> None:
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: np.nan,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: 11.0,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.95,
                }
            ]
        )
        with caplog.at_level("WARNING"):
            add_dropout_classification(cells)
        assert caplog.text == ""

    def test_classifies_landscan_2023_only_missing_as_landscan_dropout(self) -> None:
        """LandScan 2020は非NULLで2023だけがNULLのセルも、landscan要因として分類する。

        「landscan」の欠測判定を2020単独にすると、このセルは
        classify_dropout_group(False, False, False) を呼ぶことになり、
        「脱落セルではない」という誤ったValueErrorで診断全体が止まる
        （build_dropout_where_clause は2023単独欠測も脱落セルとして抽出しているため）。
        """
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: 5.0,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: np.nan,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.0,
                }
            ]
        )
        classified = add_dropout_classification(cells)
        assert list(classified["dropout_group"]) == ["landscan_only"]

    def test_入力のGeoDataFrameを変更しない(self) -> None:
        """呼び出し元が保持する元データを壊さないことを確かめる。"""
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: np.nan,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: 11.0,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.95,
                }
            ]
        )
        add_dropout_classification(cells)
        assert "dropout_group" not in cells.columns


class TestAddRoiEdgeDistance:
    """ROI境界からの距離。"""

    def test_ROI内は正_ROI外は負の距離になる(self, roi_geometry: Polygon) -> None:
        cells = _build_cells(
            [
                # ROI中心付近（境界から遠い）
                {"lon": ROI_MIN_LON + 0.05, "lat": ROI_MIN_LAT + 0.05},
                # ROIのすぐ外側
                {"lon": ROI_MIN_LON - 0.01, "lat": ROI_MIN_LAT + 0.05},
            ]
        )
        result = add_roi_edge_distance(cells, roi_geometry)
        assert bool(result["inside_roi"].iloc[0]) is True
        assert bool(result["inside_roi"].iloc[1]) is False
        assert result["roi_edge_distance_m"].iloc[0] > 0
        assert result["roi_edge_distance_m"].iloc[1] < 0

    def test_距離がメートル単位で妥当な大きさになる(self, roi_geometry: Polygon) -> None:
        """緯度0.05度（約5.5km）内側の点が、その程度の距離として算出されることを確かめる。

        投影の取り違え（度のまま距離を計算する等）を検出するための確認である。
        """
        cells = _build_cells([{"lon": ROI_MIN_LON + 0.05, "lat": ROI_MIN_LAT + 0.05}])
        result = add_roi_edge_distance(cells, roi_geometry)
        distance = float(result["roi_edge_distance_m"].iloc[0])
        assert 4_000 < distance < 7_000

    def test_境界上の点は距離ほぼ0になる(self, roi_geometry: Polygon) -> None:
        cells = _build_cells([{"lon": ROI_MIN_LON, "lat": ROI_MIN_LAT + 0.05}])
        result = add_roi_edge_distance(cells, roi_geometry)
        assert abs(float(result["roi_edge_distance_m"].iloc[0])) < 1.0


class TestResolveMetricCrs:
    """距離計算に用いる投影座標系の決定。"""

    def test_ROIからUTM帯が推定される(self, roi_geometry: Polygon) -> None:
        """対象都市が変わってもUTM帯が追随することを、ハノイの帯で確かめる。"""
        assert resolve_metric_crs(roi_geometry) == "EPSG:32648"

    def test_明示指定が推定より優先される(self, roi_geometry: Polygon) -> None:
        assert resolve_metric_crs(roi_geometry, "EPSG:3405") == "EPSG:3405"


class TestSummarizeGroupDistances:
    """距離分布の要約。"""

    def test_画素サイズ以内の割合が算出される(self) -> None:
        distances = pd.Series([10.0, 100.0, 500.0, 1_000.0])
        summary = summarize_group_distances(distances, {"coarse": 920.0, "fine": 92.0})
        assert summary["within_coarse_pixel_ratio"] == 0.75
        assert summary["within_fine_pixel_ratio"] == 0.25
        assert summary["max_m"] == 1_000.0

    def test_judges_by_absolute_distance_regardless_of_sign(self) -> None:
        """ROI外へわずかにはみ出したセルは境界帯の一部として画素サイズ以内に数える一方、
        ROIから大きく離れた負の距離は符号を無視せず画素サイズ「外」として扱う。

        距離が符号付きのまま `<= size` で判定すると、大きな負の距離（ROIから遠く
        離れた外側）まで無条件に「以内」と誤判定してしまう回帰を防ぐ。
        """
        distances = pd.Series([-50.0, -10.0, -5_000.0, 5_000.0])
        summary = summarize_group_distances(distances, {"coarse": 920.0})
        # -50, -10 は画素サイズ以内（境界のすぐ外側）、-5,000・5,000 は範囲外。
        assert summary["within_coarse_pixel_ratio"] == pytest.approx(2 / 4, abs=1e-4)


class TestSummarizeDropout:
    """要因グループ別サマリ。"""

    def test_空の入力では一致確認がNoneになる(self) -> None:
        """空系列の all() が True になるため、未確認をTrueと取り違えないことを確かめる。"""
        empty = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON,
                    "lat": ROI_MIN_LAT,
                    LANDSCAN_2020_COLUMN: 1.0,
                    LANDSCAN_2023_COLUMN: 1.0,
                    "dropout_group": "worldpop_only",
                    "water_class": "water_absent",
                    "inside_roi": True,
                    "roi_edge_distance_m": 0.0,
                    TARGET_COLUMN: 30.0,
                    WATER_COVERAGE_COLUMN: 0.0,
                }
            ]
        ).iloc[0:0]
        summary = summarize_dropout(empty, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["landscan_2020_2023_missing_agreement"] is None
        assert summary["dropout_cell_count"] == 0

    @pytest.fixture
    def classified_cells(self, roi_geometry: Polygon) -> gpd.GeoDataFrame:
        """境界帯型と内部マスク型の2種類を含む脱落セルを返す。"""
        cells = _build_cells(
            [
                # 境界帯型: ROI境界のすぐ内側でLandScanのみ欠測（陸地）
                {
                    "lon": ROI_MIN_LON + 0.001,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: 5.0,
                    LANDSCAN_2020_COLUMN: np.nan,
                    LANDSCAN_2023_COLUMN: np.nan,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.0,
                    TARGET_COLUMN: 34.5,
                },
                # 内部マスク型: ROI中心でWorldPopのみ欠測（水域）
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: np.nan,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: 11.0,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.95,
                    TARGET_COLUMN: 32.0,
                },
            ]
        )
        return add_roi_edge_distance(add_dropout_classification(cells), roi_geometry)

    def test_境界帯型と内部マスク型が距離で判別できる(
        self, classified_cells: gpd.GeoDataFrame
    ) -> None:
        """本スクリプトの目的である「2つの原因の切り分け」が数値で成り立つことを確かめる。"""
        summary = summarize_dropout(
            classified_cells, base_cell_count=1_000, pixel_sizes_m={"landscan": 920.0}
        )
        landscan = summary["groups"]["landscan_only"]["roi_edge_distance"]
        worldpop = summary["groups"]["worldpop_only"]["roi_edge_distance"]
        assert landscan["within_landscan_pixel_ratio"] == 1.0
        assert worldpop["within_landscan_pixel_ratio"] == 0.0

    def test_脱落率が母数に対して算出される(self, classified_cells: gpd.GeoDataFrame) -> None:
        summary = summarize_dropout(classified_cells, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["dropout_cell_count"] == 2
        assert summary["dropout_ratio"] == 0.002
        assert summary["groups"]["worldpop_only"]["dropout_ratio"] == 0.001

    def test_観測で実際に効いた分が群別に併記される(
        self, classified_cells: gpd.GeoDataFrame
    ) -> None:
        """母数はROI全域だが、当該観測での影響も読めることを確かめる。"""
        summary = summarize_dropout(classified_cells, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["dropout_lst_valid_count"] == 2
        assert summary["groups"]["worldpop_only"]["lst_valid_count"] == 1

    def test_LSTが全て欠測の群では平均がNoneになる(self, roi_geometry: Polygon) -> None:
        """LST平均が NaN のまま渡ると、サマリの保存が例外で失敗する。"""
        cells = _build_cells(
            [
                {
                    "lon": ROI_MIN_LON + 0.05,
                    "lat": ROI_MIN_LAT + 0.05,
                    WORLDPOP_COLUMN: np.nan,
                    LANDSCAN_2020_COLUMN: 10.0,
                    LANDSCAN_2023_COLUMN: 11.0,
                    NIGHTLIGHT_COLUMN: 2.0,
                    WATER_COVERAGE_COLUMN: 0.95,
                    TARGET_COLUMN: np.nan,
                }
            ]
        )
        classified = add_roi_edge_distance(add_dropout_classification(cells), roi_geometry)
        summary = summarize_dropout(classified, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["groups"]["worldpop_only"]["lst_mean_c"] is None
        assert summary["groups"]["worldpop_only"]["lst_valid_count"] == 0

    def test_LandScan2020と2023の欠測一致が記録される(
        self, classified_cells: gpd.GeoDataFrame
    ) -> None:
        summary = summarize_dropout(classified_cells, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["landscan_2020_2023_missing_agreement"] is True

    def test_水域区分の内訳が記録される(self, classified_cells: gpd.GeoDataFrame) -> None:
        summary = summarize_dropout(classified_cells, base_cell_count=1_000, pixel_sizes_m={})
        assert summary["groups"]["worldpop_only"]["water_class_counts"] == {"water_dominant": 1}
        assert summary["groups"]["landscan_only"]["water_class_counts"] == {"water_absent": 1}


class TestDescribeRaster:
    """入力ラスタの要約。"""

    def test_無効値と画素サイズと有効画素率が取得できる(self, tmp_path: Path) -> None:
        """粗い画素のラスタで、メートル換算が画素サイズの桁として妥当かを確かめる。"""
        raster_path = tmp_path / "coarse.tif"
        pixel_size_deg = 0.008333333333
        data = np.array([[1.0, 2.0], [-9999.0, -9999.0]], dtype="float32")
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(
                ROI_MIN_LON, ROI_MIN_LAT + ROI_SIZE_DEG, pixel_size_deg, pixel_size_deg
            ),
            nodata=-9999.0,
        ) as dst:
            dst.write(data, 1)

        info = describe_raster(raster_path)
        assert info["nodata"] == -9999.0
        assert info["valid_pixel_ratio"] == 0.5
        # 緯度21度で0.008333度は約860-930m。LandScanの画素サイズの桁と一致する。
        assert 800 < max(info["pixel_size_m"]) < 1_000
        assert math.isclose(info["pixel_size_deg"][0], pixel_size_deg, rel_tol=1e-9)
