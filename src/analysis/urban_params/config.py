"""都市・シナリオ別のレイヤ構成と出力レイアウトを定義するモジュール。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT  # noqa: F401  # io.py/run.py へ再エクスポート

# 衛星指標ラスタのバンド説明として検出対象とするキー一覧。
RASTER_KEYS = ("NDVI", "NDBI", "NDWI")

# パラメータテーブルの既定の出力ルート（プロジェクトルートからの相対パス要素）。
PARAMS_OUTPUT_PARTS = ("data", "output", "params")


def grid_layer_name(scale: int) -> str:
    """正準グリッドGeoPackage内のレイヤ名を返す。

    命名は ``canonical_grid.write_grid_layers()`` が書き出すレイヤ名と揃える。

    Args:
        scale: coarseグリッド解像度（m）。

    Returns:
        レイヤ名（例: ``grid_30m``）。
    """
    return f"grid_{scale}m"


def resolve_table_path(
    city: str,
    scale: int,
    table_name: str,
    base_dir: Path | None = None,
) -> Path:
    """パラメータテーブルの出力先パスを決める。

    スケールは列名のサフィックスではなく**ディレクトリ階層**で表現する。

    Args:
        city: 都市ID（例: ``hanoi``）。
        scale: coarseグリッド解像度（m）。
        table_name: パラメータセット名（例: ``build_gba``）。ファイル名にも使う。
        base_dir: 出力ルート。``None`` の場合は ``data/output/params`` を使う。

    Returns:
        ``{base_dir}/{city}/{scale}m/{table_name}.gpkg`` の絶対パス。
    """
    root = base_dir if base_dir is not None else PROJECT_ROOT.joinpath(*PARAMS_OUTPUT_PARTS)
    return root / city / f"{scale}m" / f"{table_name}.gpkg"


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
            # 現在どのシナリオからも参照していない。水域パラメータ（水域被覆率・
            # 水域近接距離）の採否が保留であり、採用時に full シナリオの参照先と
            # なるため、データカタログとして残置している。
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
            # 現在どのシナリオからも参照していない。full シナリオの標高を
            # 測量DH（点・等高線）で算出するかFABDEMの暫定適用とするかが
            # 未決のため、データカタログとして残置している。
            "dh": {
                "path": "整備データ/merge/merge_DH.gpkg",
                "layer": "elements",
                "crs_epsg": 5897,
            },
        },
        # ラスタ入力。レイヤ名・CRS変換器といったベクタ固有の設定項目を持たないため、
        # ``layers`` とは別セクションで管理する。
        "rasters": {
            "fabdem": {
                "path": "data/gis/dem/fabdem/fabdem_hanoi_dem.tif",
                "band": 1,
            },
        },
    }
}

# シナリオごとの入力キー。ベクタレイヤ（``layers`` のキー）とラスタ（``rasters`` の
# キー）の両方を含むため、"LAYER" ではなく "INPUT" と呼ぶ。
# ``green``（植生）は説明変数として採用済みだが算出方法が未確定であり、run.py は
# まだ参照しない。算出方法の確定後に参照を追加するため、キーを残置している。
SCENARIO_INPUT_KEYS: dict[str, dict[str, str | None]] = {
    "satellite_only": {
        "default_mask": "roi",
        "buildings": None,
        "roads": None,
        "green": None,
        "elevation_raster": None,
        "data_source": "satellite",
    },
    "limited": {
        "default_mask": "roi",
        "buildings": "open_buildings",
        "roads": "open_roads",
        "green": None,
        "elevation_raster": "fabdem",
        "data_source": "open_gis",
    },
    "full": {
        "default_mask": "rg",
        "buildings": "dc",
        "roads": "gt",
        "green": "tv",
        "elevation_raster": None,
        "data_source": "survey_gis",
    },
}
