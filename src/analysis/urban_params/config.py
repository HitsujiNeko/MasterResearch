"""都市別のレイヤ構成・パラメータセット・出力レイアウトを定義するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.config import PROJECT_ROOT  # noqa: F401  # io.py/run.py へ再エクスポート

# 衛星指標ラスタのバンド説明として検出対象とするキー一覧。
RASTER_KEYS = ("NDVI", "NDBI", "NDWI")

# 解析範囲の基準レイヤ。正準グリッド（canonical_grid.py の --mask-layer-key 既定値）と
# 同じレイヤを使う必要がある。食い違うと出力対象のセル集合が対応しなくなる。
#
# 測量GIS（RG）を基準にする経路は設けない。RGは境界「線」主体のレイヤで90.6%が
# 面積ゼロであり、面積ベースの compute_polygon_coverage() と噛み合わないためである
# （現行 full シナリオの300m出力が実データ2行しかないことがその破綻を示している）。
# 測量GISから分析対象域をどう定義するかは未決であり、それまではROIへ一本化する。
ANALYSIS_EXTENT_LAYER_KEY = "roi"

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


@dataclass(frozen=True)
class ParamSet:
    """パラメータセット（どのパラメータを、どの入力ソースで算出するか）の定義。

    **テーブル名はパラメータセット名と一致させ、出力ファイル名・レイヤ名の双方に
    使う。** 同じ列名の別ソース版（例: ``build_gba`` と ``build_dc``）を並置でき、
    感度分析が結合先の差し替えだけで済むという狙いは、この命名で成立する。

    Attributes:
        module_name: ``params`` 配下のモジュール名。実体への解決は ``run.py`` が
            行う。ここでモジュールを直接参照すると、``params/*`` → ``io`` →
            ``config`` の循環importになるためである。
        input_kind: 入力の種別（``layer`` は ``CITY_CONFIG["layers"]``、
            ``raster`` は ``CITY_CONFIG["rasters"]`` を参照する）。
        input_key: 入力の設定キー。
        columns: 出力する列名。``compute()`` の戻り値がこの通りかを実行時に検証し、
            同じ列名を持つべき別ソース版どうしの食い違いを検知する。
    """

    module_name: str
    input_kind: str
    input_key: str
    columns: tuple[str, ...]


# 列名にスケールのサフィックスは付けない。ファイル自体がスケール別ディレクトリへ
# 分かれるため冗長であり、結合時に列名がスケールへ依存すると扱いにくいためである。
BUILDING_COLUMNS = ("BUILD_COV", "BUILD_DEN", "BUILD_H_MEAN", "BUILD_H_MAX")
ROAD_COLUMNS = ("ROAD_DEN",)

PARAM_SETS: dict[str, ParamSet] = {
    "build_gba": ParamSet("buildings", "layer", "open_buildings", BUILDING_COLUMNS),
    "build_dc": ParamSet("buildings", "layer", "dc", BUILDING_COLUMNS),
    "road_osm": ParamSet("roads", "layer", "open_roads", ROAD_COLUMNS),
    "road_gt": ParamSet("roads", "layer", "gt", ROAD_COLUMNS),
    "elev_fabdem": ParamSet("elevation", "raster", "fabdem", ("ELEV_MEAN", "ELEV_VALID_RATIO")),
    "mask_roi": ParamSet("mask", "layer", ANALYSIS_EXTENT_LAYER_KEY, ("IN_ANALYSIS_AREA",)),
}

# シナリオごとに結合するテーブルの一覧。シナリオは「グリッドを変えるもの」ではなく
# 「どのテーブルを結合するかの選択」へ還元したため、算出側（run.py）は参照せず、
# 結合側（build_dataset.py）が使う。
#
# 衛星指標は観測ファイル単位でテーブルを作るため、ここには列挙できない。
# 結合時に観測日時つきのテーブル名（例: idx_20230707_032329）を明示的に指定する。
SCENARIO_TABLES: dict[str, tuple[str, ...]] = {
    "satellite_only": ("mask_roi",),
    "limited": ("mask_roi", "build_gba", "road_osm", "elev_fabdem"),
    "full": ("mask_roi", "build_dc", "road_gt"),
}
