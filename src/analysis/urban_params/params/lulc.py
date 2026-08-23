"""土地被覆クラス別面積率パラメータ（LULC_*_COV / LULC_VALID_RATIO）算出モジュール。

カテゴリラスタ（GLC_FCS30D または Esri 10m LULC）の画素値を、
``src.common.lulc_classes`` の共通クラス体系へ写像したうえで、クラスごとの
面積率を coarse グリッドへ集約する。集約そのもの（二値マスクの平均集約・
正規化の分母の選び方・欠測規約）は
``params/raster.py: aggregate_class_fractions_to_grid()`` が担い、本モジュールは
「どのデータセットがどの写像表を使うか」と「共通クラスIDと列名の対応」を持つ。

出力クラスは共通クラス体系のうち**雪氷を除く7クラス**である。ベトナムの対象都市で
雪氷は構造的に出現しないため、定義から除いても実害が無い。判断根拠・列名・
欠測規約の正本は
``docs/02_methods/calc_urban_params/calc_urban_params_io_spec.md`` 6.4節。

**植生被覆率（P8）は独立した出力列を持たない。** `LULC_TREE_COV`（樹林）・
`LULC_RANGE_COV`（草地・低木）の読み替えであり、判断根拠は
``docs/01_planning/urban_structure_parameters.md`` §2.2 を正本とする。

GLC・Esriのいずれで算出しても同一の列名を返す（差し替え関係。人口密度と異なり
同一データセットへ同時に結合しないため、データソース接尾辞は付けない）。ただし
**列名の共有は測定量の等価性を主張しない**。市街地クラスはGLCの Impervious
surfaces（人工被覆）と Esri の Built area（建造環境）で定義が異なり、スケール
特性（1セルあたり画素数）も両データセットで大きく異なる（詳細は io_spec.md 6.4節）。
"""

from __future__ import annotations

import numpy as np

from src.common.lulc_classes import (
    CLASS_SCHEMES,
    COMMON_BARE,
    COMMON_BUILT,
    COMMON_CROPLAND,
    COMMON_FOREST,
    COMMON_GRASS_SHRUB,
    COMMON_WATER,
    COMMON_WETLAND,
    build_class_lookup,
)

from ..grid import BBox, GridSpec
from ..io import RasterResource
from .raster import aggregate_class_fractions_to_grid

# 出力列名 -> 共通クラスID。列の並び順は io_spec.md 6.4節の表と揃える。
# config.py の LULC_COLUMNS（列名宣言の正本）との一致は、run.py の
# validate_computed_columns() が実行時に、tests/analysis/urban_params/test_config.py
# がユニットテストで静的に突き合わせる（夜間光・人口と同じ担保方法）。
COLUMN_TO_COMMON_CLASS: dict[str, int] = {
    "LULC_WATER_COV": COMMON_WATER,
    "LULC_TREE_COV": COMMON_FOREST,
    "LULC_CROP_COV": COMMON_CROPLAND,
    "LULC_BUILT_COV": COMMON_BUILT,
    "LULC_RANGE_COV": COMMON_GRASS_SHRUB,
    "LULC_WETLAND_COV": COMMON_WETLAND,
    "LULC_BARE_COV": COMMON_BARE,
}

# セル内の有効画素率の列名。
VALID_RATIO_COLUMN = "LULC_VALID_RATIO"


def validate_resource(resource: RasterResource) -> None:
    """入力ラスタの ``class_scheme`` が既知の写像表を指しているかを検証する。

    **``compute()`` ではなく入力解決の段階で呼ぶ。** 未設定・打ち間違いは設定の
    誤りであり、他の入力検証と同じくすべてのタスク分をまとめて先に確かめた
    ほうが、スケールごとの進捗出力に紛れない。呼び出しは ``run.py`` の
    ``build_param_tasks()`` が担う。

    画素値の分布から分類体系を推定する経路は採れない（値 10・11 が GLC・Esri
    の両体系に存在するが意味が異なるため）、``class_scheme`` の明示的な宣言に
    依存する。宣言漏れのまま算出へ進むと、誤った写像表で計算しても値は出る
    ため、集約後の統計を見ても気づけない。

    Args:
        resource: 解決済みの土地被覆ラスタ。

    Raises:
        ValueError: ``class_scheme`` が空文字列、または ``CLASS_SCHEMES`` に
            無い場合。
    """
    if resource.class_scheme not in CLASS_SCHEMES:
        known = ", ".join(sorted(CLASS_SCHEMES))
        raise ValueError(
            f"土地被覆ラスタの class_scheme が未設定または未知の値です: "
            f"'{resource.class_scheme}'。config.py の rasters エントリで "
            f"CLASS_SCHEMES のいずれか（{known}）を指定してください: {resource.path}"
        )


def compute(
    resource: RasterResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """土地被覆クラス別面積率パラメータを算出する。

    Args:
        resource: 土地被覆ラスタ（未指定シナリオでは ``None``）。既知の
            ``class_scheme`` を持つこと。未設定・未知の値は入力解決時の
            ``validate_resource()`` が検査する（本関数は再検査しない）。
        bbox_analysis: 解析用CRS上の検索範囲。集約先の範囲は ``grid_spec`` が
            保持するため本関数では参照しないが、他パラメータモジュールと
            シグネチャを揃えるために受け取る。
        grid_spec: fine/coarseグリッドの仕様。coarseグリッドへ集約する。

    Returns:
        ``{"LULC_WATER_COV": array, ..., "LULC_VALID_RATIO": array}`` 形式の
        辞書（列は ``COLUMN_TO_COMMON_CLASS`` の7クラス＋有効画素率）。各面積率
        の値域は0-1で、写像できる画素が1つも無いセルは ``NaN``。
        ``LULC_VALID_RATIO`` はラスタ範囲外・写像画素が無いセルで ``0.0``
        （``NaN`` ではない）。``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    mapping = CLASS_SCHEMES[resource.class_scheme]
    class_lookup = build_class_lookup(mapping)

    # 都市とデータセットの取り違えや切り出し範囲の誤りでは、ファイルが存在するため
    # 入力解決（io.get_optional_raster_resource）を素通りし、全セルNaNの列が黙って
    # 出力される。列が残るぶん欠損に気づきにくいため、共通処理が原因を切り分けて警告する。
    fractions, valid_ratio = aggregate_class_fractions_to_grid(
        resource.path,
        grid_spec,
        resource.band_index,
        class_lookup,
        list(COLUMN_TO_COMMON_CLASS.values()),
        "土地被覆",
    )

    columns: dict[str, np.ndarray] = {
        column_name: fractions[common_class_id]
        for column_name, common_class_id in COLUMN_TO_COMMON_CLASS.items()
    }
    columns[VALID_RATIO_COLUMN] = valid_ratio
    return columns
