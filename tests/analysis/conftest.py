"""分析パイプライン（算出フェーズ・結合フェーズ）で共通利用するフィクスチャ。

``urban_params`` の算出と ``build_dataset`` の結合は同じ入力構成（解析範囲レイヤ・
建物・道路・DEM・衛星指標・正準グリッド）を前提とするため、合成データ一式の生成を
ここへ集約する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd
import numpy as np
import pyogrio
import pytest
import rasterio
import shapely
from pyproj import CRS
from rasterio.transform import from_origin

from src.analysis import build_dataset as analysis_build_dataset
from src.analysis.urban_params import canonical_grid as urban_params_canonical_grid
from src.analysis.urban_params import config as urban_params_config
from src.analysis.urban_params import io as urban_params_io
from src.analysis.urban_params import run as urban_params_run
from src.analysis.urban_params.canonical_grid import build_canonical_grid, make_cell_id
from src.common.geo_metadata import BBox

ANALYSIS_EPSG = 3857
ANALYSIS_CRS = CRS.from_epsg(ANALYSIS_EPSG)
# 900m の約数となるスケール（正準グリッドの制約）。fine=10m で factor は 2 と 6。
SCALES = (20, 60)
FINE_RES_M = 10.0
# 解析範囲。20m では 6x6 セル、60m では 3x3 セルの正準グリッドになる。
ROI_BOUNDS = (50.0, 30.0, 150.0, 130.0)
CITY = "testcity"
SATELLITE_FILE_NAME = "INDICES_TestSat_20230707_032329Z.tif"
SATELLITE_TABLE_NAME = "idx_20230707_032329"


def rectangle(min_x: float, min_y: float, max_x: float, max_y: float) -> list[tuple[float, float]]:
    """矩形の外周リングを返す。"""
    return [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    ]


def _write_polygon_layer(path: Path, rings: list[list[tuple[float, float]]]) -> None:
    """属性を持たないポリゴンレイヤを書き出す。"""
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {}},
    ) as dst:
        for ring in rings:
            dst.write({"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})


def _write_building_layer(path: Path) -> None:
    """高さ・推定分散を持つ建物レイヤを書き出す。

    解析範囲の一部にしか建物を置かないことで、建物のあるセルと無いセルの双方を
    作る（品質管理列の検証に使う）。
    """
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "Polygon", "properties": {"height": "float", "var": "float"}},
    ) as dst:
        for bounds, height in (
            ((60.0, 40.0, 80.0, 60.0), 10.0),
            ((100.0, 90.0, 110.0, 100.0), 20.0),
        ):
            dst.write(
                {
                    "geometry": {"type": "Polygon", "coordinates": [rectangle(*bounds)]},
                    "properties": {"height": height, "var": 1.0},
                }
            )


def _write_road_layer(path: Path) -> None:
    """車道タグを持つ道路レイヤを書き出す。"""
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="data",
        crs=ANALYSIS_CRS,
        schema={"geometry": "LineString", "properties": {"highway": "str", "z_order": "int"}},
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "LineString", "coordinates": [(55.0, 60.0), (145.0, 60.0)]},
                "properties": {"highway": "residential", "z_order": 0},
            }
        )


def _write_dem(path: Path) -> None:
    """解析範囲を覆う一定標高のDEMを書き出す。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0.0, 200.0, 10.0, 10.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((20, 20), 30.0, dtype=np.float32), 1)


def _write_indices_raster(path: Path) -> None:
    """NDVI/NDBI/NDWI のバンド説明を持つ衛星指標ラスタを書き出す。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=3,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0.0, 200.0, 10.0, 10.0),
        nodata=np.nan,
    ) as dst:
        for band_index, (name, value) in enumerate(
            (("NDVI", 0.4), ("NDBI", -0.1), ("NDWI", 0.2)), start=1
        ):
            dst.write(np.full((20, 20), value, dtype=np.float32), band_index)
            dst.set_band_description(band_index, name)


def _write_canonical_grid(path: Path, roi_bbox: BBox) -> dict[int, np.ndarray]:
    """各スケールの正準グリッドレイヤを書き出し、``cell_id`` を返す。

    実運用と同じく、BBox全域ではなく一部のセルだけを持つレイヤにする
    （マスク交差セルのみを出力する挙動を模す）。
    """
    cell_ids_by_scale: dict[int, np.ndarray] = {}
    for scale in SCALES:
        canonical = build_canonical_grid(roi_bbox, ANALYSIS_CRS, float(scale))
        rows = np.repeat(
            np.arange(canonical.row_min, canonical.row_max + 1, dtype=np.int64), canonical.n_cols
        )
        cols = np.tile(
            np.arange(canonical.col_min, canonical.col_max + 1, dtype=np.int64), canonical.n_rows
        )
        # 先頭2セルを除いて「マスクで一部が落ちた」状態にする。
        rows, cols = rows[2:], cols[2:]
        cell_ids = np.asarray(make_cell_id(rows, cols))

        min_x = cols * canonical.res_m
        min_y = rows * canonical.res_m
        center_lon, center_lat = canonical.to_wgs84.transform(
            min_x + (canonical.res_m / 2.0), min_y + (canonical.res_m / 2.0)
        )
        frame = gpd.GeoDataFrame(
            {
                "cell_id": cell_ids,
                "row": rows.astype(np.int32),
                "col": cols.astype(np.int32),
                "lon": np.asarray(center_lon, dtype=np.float64),
                "lat": np.asarray(center_lat, dtype=np.float64),
            },
            geometry=shapely.box(min_x, min_y, min_x + canonical.res_m, min_y + canonical.res_m),
            crs=ANALYSIS_CRS,
        )
        pyogrio.write_dataframe(frame, path, layer=f"grid_{scale}m", driver="GPKG")
        cell_ids_by_scale[scale] = cell_ids
    return cell_ids_by_scale


@pytest.fixture()
def city_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """合成データ一式と、それを指す都市設定を用意する。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_polygon_layer(data_dir / "roi.gpkg", [rectangle(*ROI_BOUNDS)])
    _write_building_layer(data_dir / "buildings.gpkg")
    _write_road_layer(data_dir / "roads.gpkg")
    _write_dem(data_dir / "dem.tif")
    _write_indices_raster(data_dir / SATELLITE_FILE_NAME)

    roi_bbox = BBox(*ROI_BOUNDS)
    cell_ids_by_scale = _write_canonical_grid(data_dir / "grid.gpkg", roi_bbox)

    city_cfg = {
        "analysis_epsg": ANALYSIS_EPSG,
        "layers": {
            "roi": {"path": "data/roi.gpkg", "layer": "data", "crs_epsg": ANALYSIS_EPSG},
            "open_buildings": {
                "path": "data/buildings.gpkg",
                "layer": "data",
                "crs_epsg": ANALYSIS_EPSG,
            },
            "open_roads": {"path": "data/roads.gpkg", "layer": "data", "crs_epsg": ANALYSIS_EPSG},
        },
        "rasters": {"fabdem": {"path": "data/dem.tif", "band": 1}},
    }

    # 入力・出力ともにテンポラリ配下で完結させる。PROJECT_ROOT は各モジュールが
    # それぞれ import しているため、参照するモジュールをすべて差し替える。
    # 1つでも漏らすと、既定パスを使うテストが実プロジェクトの data/ を参照・書き換える。
    for module in (
        urban_params_io,
        urban_params_run,
        urban_params_canonical_grid,
        urban_params_config,
        analysis_build_dataset,
    ):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(urban_params_run.CITY_CONFIG, CITY, city_cfg)

    return {
        "root": tmp_path,
        "city_cfg": city_cfg,
        "data_dir": data_dir,
        "grid_path": data_dir / "grid.gpkg",
        "grid_argument": "data/grid.gpkg",
        "output_dir": tmp_path / "out",
        "cell_ids_by_scale": cell_ids_by_scale,
    }
