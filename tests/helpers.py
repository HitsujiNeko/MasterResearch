"""テスト全体で共有するヘルパー。

複数のテストファイルで同じ内容になる補助関数をここに集める。

- `load_script_module`: パッケージ外のスクリプト（`scripts/`・`.claude/hooks/`）の読み込み
- `write_test_raster`: テスト用の小さな GeoTIFF の書き出し
- `install_fake_ee_image_collection` ほか: 取得スクリプトの `ee` の差し替え
- `make_fake_build_target_area`: 取得範囲の組み立ての代替（下記）

取得スクリプトはいずれも `src.common.raster_area.build_target_area` で取得範囲を
組み立てる。テストでは実 ROI（Git 管理外の Shapefile）に依存させたくないため、
同じシグネチャの代替をここに1つ置いて各テストから使う。

`conftest.py` ではなく通常モジュールとして置くのは、`conftest.py` が pytest に
自動読み込みされる特別なファイルであり、そこから `import` するとフィクスチャ収集の
仕組みと通常の import 経路が二重に噛み合うため。共有定数・ヘルパーは素直に
モジュールとして公開する。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine
from shapely.geometry import box

# ROI（hanoi_ROI_EPSG4326.shp）の実測 BBOX。取得スクリプトのテストで共通に使う。
HANOI_ROI_BOUNDS = (105.28812456270636, 20.564469161724375, 106.02005052860555, 21.385222290909635)

FakeBuildTargetArea = Callable[[Path, "list[float] | None"], "tuple[gpd.GeoDataFrame, bool, Path]"]


def load_script_module(path: Path, name: str) -> ModuleType:
    """パッケージに属さないスクリプトをモジュールとして読み込む。

    `scripts/` や `.claude/hooks/` のスクリプトは `src` パッケージの外にあり、通常の
    `import` では読めないため、ファイルパスから読み込む。`sys.modules` に登録するのは、
    スクリプト内の `dataclass` などが自身のモジュールを名前で引けるようにするため。

    Args:
        path: スクリプトのパス。
        name: 登録するモジュール名。

    Returns:
        読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        """BBOX 指定なら BBOX を、無指定なら ROI を対象範囲として返す。

        Args:
            roi_path: ROI ファイルのパス（読み込みは行わず、そのまま返す）。
            bbox: 対象範囲の (minx, miny, maxx, maxy)。未指定なら ROI を使う。

        Returns:
            (対象範囲の GeoDataFrame, 試行実行フラグ, ROI パス)。
            試行実行フラグは BBOX を指定した場合に True。
        """
        geometry = box(*(bbox if bbox is not None else roi_bounds))
        return (
            gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326"),
            bbox is not None,
            Path(roi_path),
        )

    return fake


def write_test_raster(
    path: Path,
    values: np.ndarray,
    *,
    transform: Affine,
    crs: Any = "EPSG:4326",
    nodata: float | None = None,
    dtype: Any = None,
    band_names: tuple[str, ...] | None = None,
) -> Path:
    """テスト用の小さな GeoTIFF を書き出す。

    Args:
        path: 出力先。親ディレクトリが無ければ作る。
        values: 2 次元（単バンド）または 3 次元（バンド, 行, 列）の画素値。
        transform: 変換行列（`rasterio.transform.from_origin` などで作る）。
        crs: CRS（文字列または `rasterio.crs.CRS`）。
        nodata: nodata 値。`None` ならタグを付けない。
        dtype: 書き出すデータ型。`None` なら `values` の型をそのまま使う。
        band_names: 各バンドの説明。`None` なら付けない。

    Returns:
        書き出したパス。

    Raises:
        ValueError: `band_names` の数がバンド数と違うとき。
    """
    bands = values[np.newaxis, :, :] if values.ndim == 2 else values
    count, height, width = bands.shape
    if band_names is not None and len(band_names) != count:
        raise ValueError(f"バンドの説明の数（{len(band_names)}）がバンド数（{count}）と違います")
    out_dtype = bands.dtype if dtype is None else np.dtype(dtype)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=out_dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as destination:
        destination.write(bands.astype(out_dtype, copy=False))
        for index, name in enumerate(band_names or (), start=1):
            destination.set_band_description(index, name)
    return path


class FakeEeFilter:
    """`ee.Filter.eq` の戻り値を模した記録用オブジェクト。"""

    def __init__(self, property_name: str, value: Any) -> None:
        self.property_name = property_name
        self.value = value


class FakeEeValue:
    """`getInfo()` だけを持つ値オブジェクト。"""

    def __init__(self, value: Any) -> None:
        self.value = value

    def getInfo(self) -> Any:  # noqa: N802  # GEE API 名に合わせる
        """保持している値を返す。"""
        return self.value


class FakeEeImageCollection:
    """`ee.ImageCollection` を模し、適用されたフィルタと件数を記録する。

    `filter()` はチェーンされるため、適用条件は呼び出し元と共有するリストへ
    追記する（新しいインスタンスを返しても記録が失われないようにするため）。
    """

    def __init__(self, asset_id: str, matched_count: int, applied: list[FakeEeFilter]) -> None:
        self.asset_id = asset_id
        self.matched_count = matched_count
        self.applied = applied

    def filter(self, fake_filter: FakeEeFilter) -> FakeEeImageCollection:
        """フィルタ適用を共有リストへ記録し、同じ記録を持つコレクションを返す。"""
        self.applied.append(fake_filter)
        return FakeEeImageCollection(self.asset_id, self.matched_count, self.applied)

    def size(self) -> FakeEeValue:
        """件数を返す。"""
        return FakeEeValue(self.matched_count)

    def first(self) -> str:
        """先頭画像の代わりに識別用の文字列を返す。"""
        return f"{self.asset_id}#first"


def install_fake_ee_image_collection(
    monkeypatch: pytest.MonkeyPatch,
    ee_module: Any,
    matched_count: int,
    image_factory: Callable[[str], Any],
) -> dict[str, Any]:
    """`ee` の ImageCollection・Image・Filter を偽物に差し替え、記録用の辞書を返す。

    1 枚の画像をフィルタで選ぶ取得スクリプト（人口・VIIRS DNB）に共通の差し替え。
    画像に対する操作（`select` の引数の形など）はスクリプトごとに違うため、偽の画像は
    呼び出し側が `image_factory` で渡す。

    Args:
        monkeypatch: 差し替え用のフィクスチャ。
        ee_module: 差し替える `ee` モジュール（対象スクリプトの `target.ee`）。
        matched_count: フィルタ後のコレクションが返す件数。
        image_factory: `ee.Image(source)` の代わりに呼ぶ関数。

    Returns:
        記録用の辞書。`asset_id`（コレクションの ID）・`filters`（適用された
        `FakeEeFilter` のリスト）・`image`（最後に作られた偽の画像）を持つ。
    """
    recorded: dict[str, Any] = {}

    def fake_image_collection(asset_id: str) -> FakeEeImageCollection:
        """コレクションの ID とフィルタの記録先を残す。"""
        recorded["asset_id"] = asset_id
        applied: list[FakeEeFilter] = []
        recorded["filters"] = applied
        return FakeEeImageCollection(asset_id, matched_count, applied)

    def fake_image(source: str) -> Any:
        """偽の画像を作って記録する。"""
        image = image_factory(source)
        recorded["image"] = image
        return image

    class _FakeFilterFactory:
        """`ee.Filter` を模し、`eq` で記録用オブジェクトを返す。"""

        @staticmethod
        def eq(property_name: str, value: Any) -> FakeEeFilter:
            """等価条件を記録用オブジェクトとして返す。"""
            return FakeEeFilter(property_name, value)

    monkeypatch.setattr(ee_module, "ImageCollection", fake_image_collection)
    monkeypatch.setattr(ee_module, "Image", fake_image)
    monkeypatch.setattr(ee_module, "Filter", _FakeFilterFactory)
    return recorded
