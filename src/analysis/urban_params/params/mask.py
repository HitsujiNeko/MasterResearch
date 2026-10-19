"""解析対象域フラグ（IN_ANALYSIS_AREA）算出モジュール。

範囲レイヤのポリゴンがセルを覆うかどうかを判定し、他のパラメータと同じ枠組み
（``compute()`` の標準シグネチャ）で扱えるようにする。判定そのものは
``geometry.compute_polygon_coverage()`` に委ね、ロジックを二重に持たない。

範囲レイヤはパラメータセットで切り替える（ROI は ``mask_roi``、測量GISの有効域は
``mask_survey``）。測量GIS版の列名は ``config.PARAM_SETS`` の接尾辞宣言により
``IN_ANALYSIS_AREA_SURVEY`` となり、本モジュールは範囲の種類を知らずに済む。

**範囲レイヤは面ジオメトリのみで構成されている必要がある。** 線・点は面積を持たず
被覆の判定に寄与しないため、線主体のレイヤ（測量GISの RG 等）を渡すと、ほぼ全セルが
0 のテーブルが黙って出力される。これを防ぐため ``validate_resource()`` で入力解決の
段階に拒否する。

**このフラグは独立したテーブルとして出力し、他のパラメータテーブルには持たせない。**
全テーブルに同じ値を複製すると、パラメータ単位で独立させる狙いに反するためである。

**正準グリッドのセル集合とは判定基準が異なる点に注意する。** 正準グリッドは
「セルとマスクポリゴンの交差」でセルを選ぶのに対し、本モジュールは
``compute_polygon_coverage()`` すなわち「fineピクセル中心がポリゴン内に入るか」で
判定する。角をわずかにかすめるセルは交差するがピクセル中心は1つも入らないため、
両者は「交差 ⊇ IN_ANALYSIS_AREA」の包含関係にある。したがって**パラメータテーブル
の行集合（正準グリッド基準）は解析対象域より広く、有効域と同一視してはならない**。
"""

from __future__ import annotations

import numpy as np
import pyogrio

from ..geometry import POLYGON_GEOM_TYPES, compute_polygon_coverage
from ..grid import BBox, GridSpec
from ..io import LayerResource

# レイヤ定義のジオメトリ型がこれらの場合は、型の混在がありうるため地物を読んで確かめる。
MIXED_GEOMETRY_TYPES = frozenset({"Unknown", "GeometryCollection"})


def validate_resource(resource: LayerResource) -> None:
    """範囲レイヤが面ジオメトリのみで構成されているかを検証する。

    **``compute()`` ではなく入力解決の段階で呼ぶ。** 線・点を含むレイヤでも算出は
    例外なく終わり、値が 0 に偏るだけなので、出力を見るまで誤りに気づけない。
    呼び出しは ``run.py`` の ``build_param_tasks()`` が担う。

    まずレイヤ定義のジオメトリ型で判定し、地物は読まない（範囲レイヤの読み込みを
    算出時の1回に保つため）。定義が型の混在を許す場合（``Unknown`` 等。測量GISの
    merge ファイルが該当する）に限り、地物のジオメトリ型を読んで確かめる。その際、
    ジオメトリが欠けた地物（NULL）は判定に寄与しないため無視する。

    Args:
        resource: 解決済みの範囲レイヤ。

    Raises:
        ValueError: 面以外のジオメトリを含む場合、または地物が1件も無い場合。
    """
    location = f"{resource.path}（レイヤ: {resource.layer_name}）"
    info = pyogrio.read_info(resource.path, layer=resource.layer_name)
    if info["features"] == 0:
        raise ValueError(f"範囲レイヤに地物がありません: {location}")

    # 「Polygon Z」のような次元の付記を除いた型名で判定する。
    declared_type = str(info["geometry_type"]).split(" ")[0]
    if declared_type in POLYGON_GEOM_TYPES:
        return
    if declared_type not in MIXED_GEOMETRY_TYPES:
        _raise_non_polygon(location, f"ジオメトリ型 {info['geometry_type']}")

    # 属性列は不要であり、文字列列の文字コード不正で読み込みが失敗するのも避けられる。
    gdf = pyogrio.read_dataframe(resource.path, layer=resource.layer_name, columns=[])
    geom_types = gdf.geom_type.dropna()
    if geom_types.empty:
        raise ValueError(f"範囲レイヤに面ジオメトリがありません: {location}")
    invalid_counts = geom_types[~geom_types.isin(POLYGON_GEOM_TYPES)].value_counts()
    if not invalid_counts.empty:
        detail = ", ".join(f"{name} {count}件" for name, count in invalid_counts.items())
        _raise_non_polygon(location, detail)


def _raise_non_polygon(location: str, detail: str) -> None:
    """面以外のジオメトリを含む範囲レイヤを拒否する例外を送出する。

    Args:
        location: レイヤの所在（パスとレイヤ名）。
        detail: 検出したジオメトリ型の説明。

    Raises:
        ValueError: 常に送出する。
    """
    raise ValueError(
        "範囲レイヤには面ジオメトリ（Polygon / MultiPolygon）のみを指定してください"
        f"（{location} は {detail} を含みます）。"
        " 線・点は面積を持たず、解析対象域フラグがほぼ全セル 0 になります。"
    )


def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """解析対象域フラグを算出する。

    Args:
        resource: 範囲レイヤ（未指定の場合は ``None``）。面ジオメトリのみで
            構成されていること（入力解決時の ``validate_resource()`` が検査する）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        ``{"IN_ANALYSIS_AREA": array}`` 形式の辞書。被覆率が0より大きいセルを1、
        それ以外を0とする ``int8`` 配列。``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    coverage = compute_polygon_coverage(resource, bbox_analysis, grid_spec)
    return {"IN_ANALYSIS_AREA": (coverage > 0).astype(np.int8)}
