"""テスト全体で共有するヘルパー。

取得スクリプトはいずれも `src.common.raster_area.build_target_area` で取得範囲を
組み立てる。テストでは実 ROI（Git 管理外の Shapefile）に依存させたくないため、
同じシグネチャの代替をここに1つ置いて各テストから使う。

`conftest.py` ではなく通常モジュールとして置くのは、`conftest.py` が pytest に
自動読み込みされる特別なファイルであり、そこから `import` するとフィクスチャ収集の
仕組みと通常の import 経路が二重に噛み合うため。共有定数・ヘルパーは素直に
モジュールとして公開する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

# ROI（hanoi_ROI_EPSG4326.shp）の実測 BBOX。取得スクリプトのテストで共通に使う。
HANOI_ROI_BOUNDS = (105.28812456270636, 20.564469161724375, 106.02005052860555, 21.385222290909635)

FakeBuildTargetArea = Callable[[Path, "list[float] | None"], "tuple[gpd.GeoDataFrame, bool, Path]"]


def make_fake_build_target_area(
    roi_bounds: tuple[float, float, float, float] = HANOI_ROI_BOUNDS,
) -> FakeBuildTargetArea:
    """`build_target_area` の代替を作る（ROI ファイルの読み込みを伴わせない）。

    BBOX 指定時に試行実行フラグが立つ分岐は本物と同じに保つ。ここを固定値にすると
    試行実行の経路が検証できなくなるため。

    Args:
        roi_bounds: BBOX 未指定時に ROI として返す (minx, miny, maxx, maxy)。

    Returns:
        `build_target_area` と同じシグネチャの関数。
    """

    def fake(roi_path: Path, bbox: list[float] | None) -> tuple[gpd.GeoDataFrame, bool, Path]:
        geometry = box(*(bbox if bbox is not None else roi_bounds))
        return (
            gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326"),
            bbox is not None,
            Path(roi_path),
        )

    return fake
