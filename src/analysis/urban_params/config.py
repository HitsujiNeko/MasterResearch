"""都市別のレイヤ構成・パラメータセット・出力レイアウトを定義するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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

# 分析用データセットの既定の出力ルート。
DATASETS_OUTPUT_PARTS = ("data", "output", "datasets")

# 衛星指標テーブル名の接頭辞。観測ファイル単位で作るため PARAM_SETS に列挙できず、
# 結合フェーズはこの接頭辞でGIS由来のテーブルと区別する。
SATELLITE_TABLE_PREFIX = "idx_"

# LSTテーブル名の接頭辞。衛星指標と同じく観測ファイル単位で作るため PARAM_SETS に
# 列挙できない。LSTは目的変数であり、衛星指標（説明変数）の品質管理列
# （VALID_SATELLITE_MASK）の判定材料には含めないため、接頭辞を分けて区別する。
LST_TABLE_PREFIX = "lst_"

# LSTテーブルの列名。標高（ELEV_MEAN / ELEV_VALID_RATIO）と同じく、セル平均値と
# セル内有効画素率の2列を持つ。
LST_COLUMNS = ("LST", "LST_VALID_RATIO")


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
            # 人口グリッドはいずれも band 1 がカウント（人/セル）、band 2 が取得
            # スクリプトの導出した密度（人/km²）である。参照するのは band 2 のみで、
            # カウントを平均集約するとセル面積に依存した無意味な値になる。
            "worldpop2020": {
                "path": "data/gis/population/worldpop/worldpop_hanoi_2020.tif",
                "band": 2,
            },
            "landscan2020": {
                "path": "data/gis/population/landscan/landscan_hanoi_2020.tif",
                "band": 2,
            },
            "landscan2023": {
                "path": "data/gis/population/landscan/landscan_hanoi_2023.tif",
                "band": 2,
            },
            # 夜間光はいずれも band 1 が放射輝度の主バンドである。VIIRS DNB の
            # band 2（avg_radiance_masked）は背景と判定した画素を欠測にせず0へ
            # 置き換えるため使わない（欠測と実測0の区別が値の上で失われる）。
            "viirs2023": {
                "path": "data/gis/nighttime_lights/viirs_dnb/viirs_dnb_hanoi_2023.tif",
                "band": 1,
            },
            "bm2023": {
                # 1行に収めると行長上限（100）を1文字超えるため括弧で折る。
                "path": (
                    "data/gis/nighttime_lights/black_marble/black_marble_vnp46a4_hanoi_2023.tif"
                ),
                "band": 1,
            },
            # 土地被覆はデータセットごとに分類体系（クラス値の意味）が異なる
            # カテゴリラスタであり、band 1 の画素値だけでは体系を判別できない
            # （値 10・11 が両体系に存在するが意味が異なる）ため、写像表を選ぶ
            # 手がかりとして class_scheme を明示する（src.common.lulc_classes の
            # CLASS_SCHEMES のキーと対応させる）。
            "glc2022": {
                "path": "data/gis/lulc/glc_fcs30d/glc_fcs30d_hanoi_2022.tif",
                "band": 1,
                "class_scheme": "glc2022",
            },
            "esri2022": {
                "path": "data/gis/lulc/esri_10m/esri_lulc_hanoi_2022.tif",
                "band": 1,
                "class_scheme": "esri2022",
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
            ``column_suffix`` がある場合は接尾辞を付けたあとの最終的な列名を指す。
        column_suffix: 算出モジュールが返した列名へ付けるデータソース由来の接尾辞。
            空文字列（既定）なら何も付けない。**別ソース版を同一データセットへ同時に
            結合する必要があるパラメータにのみ指定する。** 算出モジュールは自分が
            どのデータソースを処理しているかを知らずに済み、接尾辞の付与は
            ``run.py`` の ``apply_column_suffix()`` が一手に担う。
    """

    module_name: str
    input_kind: Literal["layer", "raster"]
    input_key: str
    columns: tuple[str, ...]
    column_suffix: str = ""


# 列名にスケールのサフィックスは付けない。ファイル自体がスケール別ディレクトリへ
# 分かれるため冗長であり、結合時に列名がスケールへ依存すると扱いにくいためである。
BUILDING_COLUMNS = ("BUILD_COV", "BUILD_DEN", "BUILD_H_MEAN", "BUILD_H_MAX")
ROAD_COLUMNS = ("ROAD_DEN",)

# 夜間光はVIIRS DNBを主候補・Black Marbleを副候補とする**差し替え関係**であり、
# 建物・道路と同じく列名を共有する（主バンド同士の相関は Pearson r = 0.976。ただし
# これはVIIRSグリッド上で両者が重なる16,579画素での値で、ROI全体の統計ではない）。
# 人口3版のように同一データセットへ同時結合する用途は無いため、接尾辞は付けない。
NIGHTLIGHT_COLUMNS = ("NTL_MEAN", "NTL_VALID_RATIO")

# 人口密度の列名（データソース接尾辞を付ける**前**の基底名）。``params/population.py``
# が返すのはこの名前であり、実際に出力される列名は接尾辞つきになる。
POPULATION_BASE_COLUMNS = ("POP_DEN", "POP_VALID_RATIO")

# 土地被覆はGLC・Esriのいずれで算出しても同じ列名を使う（差し替え関係。人口密度と
# 異なり同一データセットへ同時結合しないため接尾辞は付けない）。7クラス（雪氷を
# 除く）＋有効画素率。列名から共通クラスIDへの対応は ``params/lulc.py`` が持つ。
LULC_COLUMNS = (
    "LULC_WATER_COV",
    "LULC_TREE_COV",
    "LULC_CROP_COV",
    "LULC_BUILT_COV",
    "LULC_RANGE_COV",
    "LULC_WETLAND_COV",
    "LULC_BARE_COV",
    "LULC_VALID_RATIO",
)


def population_param_set(raster_key: str, source_suffix: str) -> ParamSet:
    """データソース接尾辞つきの列名を持つ人口パラメータセットを組み立てる。

    **人口だけは別ソース版で列名を分ける。** 建物（``build_gba`` / ``build_dc``）や
    夜間光（``ntl_viirs2023`` / ``ntl_bm2023``）は同一概念の「差し替え候補」であり、
    同じ列名にすることで感度分析が結合先の差し替えだけで済む。一方、人口の3版は
    概念（居住人口 / 実効人口）も観測年も異なる**別変数**であり、説明力の差が
    「人口概念の差」によるものか「観測年の差」によるものかを分離するには、同一
    データセットへ**同時に**結合する必要がある。列名を共有したままだと
    ``build_dataset.py`` の ``join_tables()`` が列名衝突として結合を拒否する。

    Args:
        raster_key: ``CITY_CONFIG[都市]["rasters"]`` のキー。
        source_suffix: 列名へ付けるデータソース識別子（大文字・例: ``WORLDPOP2020``）。

    Returns:
        接尾辞つきの列名を宣言したパラメータセット。
    """
    return ParamSet(
        "population",
        "raster",
        raster_key,
        tuple(f"{name}_{source_suffix}" for name in POPULATION_BASE_COLUMNS),
        column_suffix=source_suffix,
    )


PARAM_SETS: dict[str, ParamSet] = {
    "build_gba": ParamSet("buildings", "layer", "open_buildings", BUILDING_COLUMNS),
    "build_dc": ParamSet("buildings", "layer", "dc", BUILDING_COLUMNS),
    "road_osm": ParamSet("roads", "layer", "open_roads", ROAD_COLUMNS),
    "road_gt": ParamSet("roads", "layer", "gt", ROAD_COLUMNS),
    "elev_fabdem": ParamSet("elevation", "raster", "fabdem", ("ELEV_MEAN", "ELEV_VALID_RATIO")),
    # 人口は3版を並置する。WorldPopは居住人口・約92.77m、LandScanは実効人口・約928mで
    # 概念と解像度が異なる。LandScan 2020 は「対照」であり、2023との比較で人口概念を
    # 固定して観測年だけを変えられる（WorldPopはベトナムの提供が2020年までのため、
    # 居住人口側で年を振ることはできない）。3版とも同時に結合できるよう列名を分ける。
    "pop_worldpop2020": population_param_set("worldpop2020", "WORLDPOP2020"),
    "pop_landscan2020": population_param_set("landscan2020", "LANDSCAN2020"),
    "pop_landscan2023": population_param_set("landscan2023", "LANDSCAN2023"),
    "ntl_viirs2023": ParamSet("nightlight", "raster", "viirs2023", NIGHTLIGHT_COLUMNS),
    "ntl_bm2023": ParamSet("nightlight", "raster", "bm2023", NIGHTLIGHT_COLUMNS),
    # 主ソース（GLC_FCS30D）・副ソース（Esri 10m LULC）。位置づけは
    # gis_data_lulc.md 4章を参照。同時結合しないため列名は共有する。
    "lulc_glc2022": ParamSet("lulc", "raster", "glc2022", LULC_COLUMNS),
    "lulc_esri2022": ParamSet("lulc", "raster", "esri2022", LULC_COLUMNS),
    "mask_roi": ParamSet("mask", "layer", ANALYSIS_EXTENT_LAYER_KEY, ("IN_ANALYSIS_AREA",)),
}

# シナリオごとに結合するテーブルの一覧。シナリオは「グリッドを変えるもの」ではなく
# 「どのテーブルを結合するかの選択」へ還元したため、算出側（run.py）は参照せず、
# 結合側（build_dataset.py）が使う。
#
# 衛星指標・LSTは観測ファイル単位でテーブルを作るため、ここには列挙できない。
# 結合時に観測日時つきのテーブル名（例: idx_20230707_032329 / lst_20230707_032329）を
# 明示的に指定する。
#
# ``satellite_only`` はそのためシナリオ名だけでは完成しない。エントリを残すのは
# 「衛星指標以外に何を結合するか」を記録するためであり、``--scenario`` での単独指定は
# build_dataset.py が明示的に拒否する（mask_roi だけのデータセットが「衛星のみ」を
# 名乗って出力されるのを防ぐため）。``--tables`` に idx_* を伴う場合のみ、
# ``--scenario satellite_only`` との併用を許可する（Satellite Only は衛星由来指標
# （idx_*）を用いるシナリオであり、lst_* の有無は解禁条件にしない。lst_* だけを許すと
# 目的変数しか持たないデータセットが「衛星のみ」を名乗ることになるため）。
SATELLITE_ONLY_SCENARIO = "satellite_only"

#
# ``limited`` は「衛星データ＋公開GIS」のシナリオであり、土地被覆・人口密度・夜間光は
# いずれも公開GISに属するため、ここへ列挙する。**土地被覆・夜間光は主ソースのみを
# 列挙する**（``lulc_glc2022`` / ``ntl_viirs2023``）。副ソース（``lulc_esri2022`` /
# ``ntl_bm2023``）は列名を共有する差し替え関係であり、同一データセットへ同時結合すると
# ``join_tables()`` が列名衝突として拒否するためである。副ソースでの感度分析は
# ``--tables`` で全テーブルを明示列挙した別データセットとして生成する
# （``--scenario`` を併用するとシナリオ展開分の主ソースが混入して衝突する）。
# 人口3版は列名に接尾辞が付いて衝突しないため、3版とも同時に結合する。
SCENARIO_TABLES: dict[str, tuple[str, ...]] = {
    SATELLITE_ONLY_SCENARIO: ("mask_roi",),
    "limited": (
        "mask_roi",
        "build_gba",
        "road_osm",
        "elev_fabdem",
        "lulc_glc2022",
        "ntl_viirs2023",
        "pop_worldpop2020",
        "pop_landscan2020",
        "pop_landscan2023",
    ),
    "full": ("mask_roi", "build_dc", "road_gt"),
}
