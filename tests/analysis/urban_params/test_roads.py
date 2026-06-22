"""params/roads.py（道路パラメータ算出）のテスト。"""

from __future__ import annotations

from pathlib import Path

import fiona
import numpy as np
import pytest

from src.analysis.urban_params.grid import build_grid
from src.analysis.urban_params.params.roads import (
    VEHICLE_ROAD_TAGS,
    _is_vehicle_road,
    compute,
)

from .conftest import ANALYSIS_BBOX, ANALYSIS_CRS, _make_layer_resource


def _write_road_gpkg(
    gpkg_path: Path,
    features: list[dict],
) -> None:
    """テスト用の道路フィーチャを GPKG に書き込む。"""
    schema = {
        "geometry": "LineString",
        "properties": {
            "highway": "str",
            "z_order": "int",
        },
    }
    with fiona.open(
        gpkg_path, "w", driver="GPKG", layer="roads", crs=ANALYSIS_CRS, schema=schema
    ) as dst:
        for feat in features:
            dst.write(feat)


def _make_feature(
    coords: list[tuple[float, float]],
    highway: str,
    z_order: int = 0,
) -> dict:
    """テスト用のフィーチャ辞書を作成する。"""
    return {
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"highway": highway, "z_order": z_order},
    }


class TestIsVehicleRoad:
    """_is_vehicle_road フィルタ関数のテスト。"""

    def test_vehicle_road_tags_accepted(self) -> None:
        """ホワイトリストに含まれるタグは通過する。"""
        for tag in VEHICLE_ROAD_TAGS:
            feat = _make_feature([(0, 0), (1, 1)], highway=tag, z_order=3)
            assert _is_vehicle_road(feat) is True, f"{tag} が拒否された"

    def test_non_vehicle_tags_rejected(self) -> None:
        """ホワイトリスト外のタグは除外される。"""
        for tag in (
            "footway",
            "steps",
            "path",
            "pedestrian",
            "cycleway",
            "track",
            "construction",
            "proposed",
            "corridor",
        ):
            feat = _make_feature([(0, 0), (1, 1)], highway=tag, z_order=0)
            assert _is_vehicle_road(feat) is False, f"{tag} が通過した"

    def test_tunnel_excluded(self) -> None:
        """z_order < 0（トンネル）のフィーチャは除外される。"""
        feat = _make_feature([(0, 0), (1, 1)], highway="residential", z_order=-17)
        assert _is_vehicle_road(feat) is False

    def test_bridge_included(self) -> None:
        """z_order > 0（橋梁・高架）のフィーチャは含まれる。"""
        feat = _make_feature([(0, 0), (1, 1)], highway="primary", z_order=17)
        assert _is_vehicle_road(feat) is True

    def test_ground_level_included(self) -> None:
        """z_order = 0（地表）のフィーチャは含まれる。"""
        feat = _make_feature([(0, 0), (1, 1)], highway="service", z_order=0)
        assert _is_vehicle_road(feat) is True

    def test_missing_highway_rejected(self) -> None:
        """highway タグが存在しないフィーチャは除外される。"""
        feat = {
            "geometry": {"type": "LineString", "coordinates": [(0, 0), (1, 1)]},
            "properties": {"z_order": 3},
        }
        assert _is_vehicle_road(feat) is False

    def test_none_highway_rejected(self) -> None:
        """highway が None のフィーチャは除外される。"""
        feat = _make_feature([(0, 0), (1, 1)], highway="residential", z_order=0)
        feat["properties"]["highway"] = None
        assert _is_vehicle_road(feat) is False


class TestCompute:
    """compute() 関数のテスト。"""

    def test_returns_empty_when_resource_is_none(self) -> None:
        """resource が None の場合は空辞書を返す。"""
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)
        result = compute(None, ANALYSIS_BBOX, grid_spec)
        assert result == {}

    def test_road_den_computed(self, tmp_path: Path) -> None:
        """車道フィーチャから ROAD_DEN が算出される。"""
        gpkg_path = tmp_path / "roads.gpkg"
        _write_road_gpkg(
            gpkg_path,
            [
                _make_feature([(0, 65), (80, 65)], highway="residential", z_order=3),
            ],
        )
        resource = _make_layer_resource(gpkg_path, "roads")
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)

        result = compute(resource, ANALYSIS_BBOX, grid_spec)

        assert "ROAD_DEN" in result
        road_den = result["ROAD_DEN"]
        assert road_den.shape == grid_spec.coarse_shape
        assert road_den.dtype == np.float32
        assert road_den.sum() > 0

    def test_road_den_matches_expected_density(self, tmp_path: Path) -> None:
        """20m セル内の水平ライン 20m → 20m / 0.04ha = 500 m/ha。"""
        gpkg_path = tmp_path / "roads.gpkg"
        # セル(0, 0): x=[0, 20), y=[60, 80) の中央を通る水平線
        _write_road_gpkg(
            gpkg_path,
            [
                _make_feature([(0, 70), (20, 70)], highway="residential", z_order=3),
            ],
        )
        resource = _make_layer_resource(gpkg_path, "roads")
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)

        result = compute(resource, ANALYSIS_BBOX, grid_spec)

        # 20m セルの面積 = 400m² = 0.04 ha
        expected_den = 20.0 / 0.04
        assert result["ROAD_DEN"][0, 0] == pytest.approx(expected_den, rel=1e-4)

    def test_non_vehicle_roads_excluded(self, tmp_path: Path) -> None:
        """footway はフィルタリングで除外され ROAD_DEN に寄与しない。"""
        gpkg_path = tmp_path / "roads.gpkg"
        _write_road_gpkg(
            gpkg_path,
            [
                _make_feature([(0, 70), (20, 70)], highway="footway", z_order=0),
            ],
        )
        resource = _make_layer_resource(gpkg_path, "roads")
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)

        result = compute(resource, ANALYSIS_BBOX, grid_spec)

        assert result["ROAD_DEN"].sum() == pytest.approx(0.0)

    def test_tunnel_excluded(self, tmp_path: Path) -> None:
        """z_order < 0（トンネル）のフィーチャは除外される。"""
        gpkg_path = tmp_path / "roads.gpkg"
        _write_road_gpkg(
            gpkg_path,
            [
                _make_feature([(0, 70), (20, 70)], highway="residential", z_order=-17),
            ],
        )
        resource = _make_layer_resource(gpkg_path, "roads")
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)

        result = compute(resource, ANALYSIS_BBOX, grid_spec)

        assert result["ROAD_DEN"].sum() == pytest.approx(0.0)

    def test_mixed_features_only_vehicle_counted(self, tmp_path: Path) -> None:
        """車道・歩道・トンネルが混在する場合、車道のみが計上される。"""
        gpkg_path = tmp_path / "roads.gpkg"
        _write_road_gpkg(
            gpkg_path,
            [
                _make_feature([(0, 70), (20, 70)], highway="residential", z_order=3),
                _make_feature([(0, 50), (20, 50)], highway="footway", z_order=0),
                _make_feature([(0, 30), (20, 30)], highway="primary", z_order=-10),
            ],
        )
        resource = _make_layer_resource(gpkg_path, "roads")
        grid_spec = build_grid(ANALYSIS_BBOX, ANALYSIS_CRS, 20.0, 10.0)

        result = compute(resource, ANALYSIS_BBOX, grid_spec)

        # residential の 20m のみが計上される
        expected_den = 20.0 / 0.04  # 500 m/ha
        assert result["ROAD_DEN"].sum() == pytest.approx(expected_den, rel=1e-4)
