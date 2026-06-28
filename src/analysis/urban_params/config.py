"""都市・シナリオ別のレイヤ構成を定義するモジュール。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 衛星指標ラスタのバンド説明として検出対象とするキー一覧。
RASTER_KEYS = ("NDVI", "NDBI", "NDWI", "FVC")

CITY_CONFIG: dict[str, dict[str, Any]] = {
    "hanoi": {
        "analysis_epsg": 5897,
        "layers": {
            "roi": {
                "path": "data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp",
                "layer": "hanoi_ROI_EPSG4326",
                "crs_epsg": 4326,
            },
            "open_buildings": {
                "path": "data/gis/buildings/hanoi_gba_buildings.gpkg",
                "layer": "buildings",
                "crs_epsg": 4326,
            },
            "open_roads": {
                "path": "data/gis/roads/hanoi_osm_roads.gpkg",
                "layer": "roads",
                "crs_epsg": 4326,
            },
            "rg": {
                "path": "整備データ/merge/merge_RG.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "cs": {
                "path": "整備データ/merge/merge_CS.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "dc": {
                "path": "整備データ/merge/merge_DC.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "gt": {
                "path": "整備データ/merge/merge_GT.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "th": {
                "path": "整備データ/merge/merge_TH.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "tv": {
                "path": "整備データ/merge/merge_TV.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
            "dh": {
                "path": "整備データ/merge/merge_DH.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
        },
    }
}

SCENARIO_LAYER_KEYS: dict[str, dict[str, str | None]] = {
    "satellite_only": {
        "default_mask": "roi",
        "buildings": None,
        "roads": None,
        "water": None,
        "green": None,
        "elevation": None,
        "data_source": "satellite",
    },
    "limited": {
        "default_mask": "roi",
        "buildings": "open_buildings",
        "roads": "open_roads",
        "water": None,
        "green": None,
        "elevation": None,
        "data_source": "open_gis",
    },
    "full": {
        "default_mask": "rg",
        "buildings": "dc",
        "roads": "gt",
        "water": "th",
        "green": "tv",
        "elevation": "dh",
        "data_source": "survey_gis",
    },
}
