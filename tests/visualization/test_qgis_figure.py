"""qgis_figure.py（PyQGIS による印刷レイアウト図の生成）のテスト。

conda 環境にも CI にも ``qgis.core`` が無いため、``sys.modules`` に偽の ``qgis`` を
入れてから import し、QGIS に依存しない分岐だけを確かめる。CI の環境（requirements.txt）
には GDAL の Python バインディング（``osgeo``）も無いため、対象が使う ``gdal.Open`` の
範囲だけを rasterio で読む偽の ``osgeo.gdal`` に差し替える。

- レイヤ名の解決（名前ならプロジェクトから引き、オブジェクトならそのまま使う）
- カテゴリ値ラスタの凡例を、実際の画素値に現れるクラスだけに絞る処理

レイアウトの寸法計算は ``figure_layout.py``（``test_figure_layout.py`` で検査）にあり、
描画そのもの（印刷レイアウトの PNG 出力）は QGIS が無いと確かめられないため対象外とする。
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.transform import from_origin

import src.visualization
from tests.helpers import write_test_raster

MODULE_NAME = "src.visualization.qgis_figure"


class _AnyNameModule(types.ModuleType):
    """どの名前を引いても空のクラスを返す偽モジュール（``from ... import`` を通すため）。"""

    def __getattr__(self, name: str) -> type:
        """名前に対応する空のクラスを作って返す。"""
        if name.startswith("__"):
            raise AttributeError(name)
        dummy = type(name, (), {})
        setattr(self, name, dummy)
        return dummy


class FakePalettedRasterRenderer:
    """``QgsPalettedRasterRenderer`` を模し、バンドとクラスの一覧を持つ。"""

    class Class:
        """``QgsPalettedRasterRenderer.Class`` を模したクラス定義。"""

        def __init__(self, value: float, color: str, label: str) -> None:
            self.value = value
            self.color = color
            self.label = label

    def __init__(self, provider: Any, band: int, classes: list[Any]) -> None:
        self.provider = provider
        self._band = band
        self._classes = list(classes)

    def band(self) -> int:
        """描画に使うバンド番号を返す。"""
        return self._band

    def classes(self) -> list[Any]:
        """クラス定義の一覧を返す。"""
        return self._classes


class FakeRasterLayer:
    """``QgsRasterLayer`` を模し、ソースとレンダラを持つ。"""

    def __init__(self, source: str, renderer: FakePalettedRasterRenderer) -> None:
        self._source = source
        self._renderer = renderer
        self.repainted = False

    def source(self) -> str:
        """データソースのパスを返す。"""
        return self._source

    def renderer(self) -> FakePalettedRasterRenderer:
        """現在のレンダラを返す。"""
        return self._renderer

    def setRenderer(self, renderer: FakePalettedRasterRenderer) -> None:  # noqa: N802
        """レンダラを差し替える（QGIS の API 名に合わせる）。"""
        self._renderer = renderer

    def dataProvider(self) -> str:  # noqa: N802
        """データプロバイダの代わりに識別用の文字列を返す（QGIS の API 名に合わせる）。"""
        return "provider"

    def triggerRepaint(self) -> None:  # noqa: N802
        """再描画の要求を記録する（QGIS の API 名に合わせる）。"""
        self.repainted = True


class FakeProject:
    """``QgsProject`` を模し、名前からレイヤを引ける。"""

    current: FakeProject | None = None

    def __init__(self, layers: dict[str, Any]) -> None:
        self.layers = layers

    @classmethod
    def instance(cls) -> FakeProject | None:
        """現在のプロジェクトを返す。"""
        return cls.current

    def mapLayersByName(self, name: str) -> list[Any]:  # noqa: N802
        """名前が一致するレイヤの一覧を返す（QGIS の API 名に合わせる）。"""
        return [self.layers[name]] if name in self.layers else []


class _FakeGdalBand:
    """``gdal.Band`` のうち対象が使う 2 つのメソッドだけを、rasterio の読み取り結果で返す。"""

    def __init__(self, values: np.ndarray, nodata: float | None) -> None:
        self._values = values
        self._nodata = nodata

    def GetNoDataValue(self) -> float | None:  # noqa: N802
        """バンドの NoData 値を返す（GDAL の API 名に合わせる）。"""
        return self._nodata

    def ReadAsArray(self) -> np.ndarray:  # noqa: N802
        """画素値の配列を返す（GDAL の API 名に合わせる）。"""
        return self._values


class _FakeGdalDataset:
    """``gdal.Dataset`` のうち ``GetRasterBand`` だけを持つ。"""

    def __init__(self, band: _FakeGdalBand) -> None:
        self._band = band

    def GetRasterBand(self, index: int) -> _FakeGdalBand:  # noqa: N802
        """1 番目のバンドを返す（GDAL の API 名に合わせる）。"""
        assert index == 1
        return self._band


def _fake_gdal_open(path: str) -> _FakeGdalDataset | None:
    """``gdal.Open`` と同じく、開けないファイルなら None を返す（例外を使わない既定の動作）。"""
    try:
        with rasterio.open(path) as dataset:
            return _FakeGdalDataset(_FakeGdalBand(dataset.read(1), dataset.nodata))
    except RasterioIOError:
        return None


@pytest.fixture()
def target(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    """偽の qgis を入れて対象モジュールを import し、終わったら取り除く。"""
    qgis = types.ModuleType("qgis")
    core = _AnyNameModule("qgis.core")
    core.QgsProject = FakeProject
    core.QgsPalettedRasterRenderer = FakePalettedRasterRenderer
    pyqt = types.ModuleType("qgis.PyQt")
    qt_gui = _AnyNameModule("qgis.PyQt.QtGui")
    osgeo = types.ModuleType("osgeo")
    osgeo.gdal = types.SimpleNamespace(Open=_fake_gdal_open)
    for name, module in {
        "qgis": qgis,
        "qgis.core": core,
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtGui": qt_gui,
        "osgeo": osgeo,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(FakeProject, "current", None)
    sys.modules.pop(MODULE_NAME, None)

    yield importlib.import_module(MODULE_NAME)

    # 偽の qgis に結び付いたモジュールを、ほかのテストに残さない
    sys.modules.pop(MODULE_NAME, None)
    if hasattr(src.visualization, "qgis_figure"):
        delattr(src.visualization, "qgis_figure")


class TestResolveLayer:
    """_resolve_layer・_require_layer のテスト。"""

    def test_returns_layer_object_as_is(self, target: types.ModuleType) -> None:
        """レイヤオブジェクトを渡したら、プロジェクトを使わずそのまま返す。"""
        layer = object()

        assert target._resolve_layer(layer, None) is layer

    def test_looks_up_name_in_given_project(self, target: types.ModuleType) -> None:
        """レイヤ名を渡したら、指定したプロジェクトから引く。"""
        layer = object()
        project = FakeProject({"lst": layer})

        assert target._resolve_layer("lst", project) is layer

    def test_uses_current_project_when_not_given(self, target: types.ModuleType) -> None:
        """プロジェクトを省略したら、現在のプロジェクトから引く。"""
        layer = object()
        FakeProject.current = FakeProject({"roi": layer})

        assert target._resolve_layer("roi", None) is layer

    def test_missing_name_raises(self, target: types.ModuleType) -> None:
        """名前のレイヤが無ければ、その名前を示して例外にする。"""
        with pytest.raises(ValueError, match="'missing'"):
            target._resolve_layer("missing", FakeProject({}))


class TestFilterPalettedToPresent:
    """filter_paletted_to_present のテスト。"""

    @staticmethod
    def _make_layer(tmp_path: Path, values: np.ndarray, nodata: float | None) -> FakeRasterLayer:
        """画素値を書いたラスタと、クラス 0・1・2・3・10 を持つレイヤを作る。

        Args:
            tmp_path: 一時ディレクトリ。
            values: 画素値。
            nodata: ラスタの nodata 値。

        Returns:
            偽のラスタレイヤ。
        """
        raster = write_test_raster(
            tmp_path / "lulc.tif",
            values,
            transform=from_origin(105.0, 21.0, 0.01, 0.01),
            nodata=nodata,
        )
        renderer = FakePalettedRasterRenderer(
            "provider",
            1,
            [
                FakePalettedRasterRenderer.Class(0.0, "black", "0 無効 (No data)"),
                FakePalettedRasterRenderer.Class(1.0, "blue", "1 水域 (Water)"),
                FakePalettedRasterRenderer.Class(2.0, "red", "2 市街地 (Built area)"),
                FakePalettedRasterRenderer.Class(3.0, "green", "3 森林 (Trees)"),
                FakePalettedRasterRenderer.Class(10.0, "white", "10 雲 (Clouds)"),
            ],
        )
        return FakeRasterLayer(str(raster), renderer)

    def test_keeps_only_present_classes_with_short_labels(
        self, target: types.ModuleType, tmp_path: Path
    ) -> None:
        """画素に現れるクラスだけを残し、ラベルの英語括弧を外す。バンドの NoData は除く。"""
        layer = self._make_layer(tmp_path, np.array([[1, 2], [2, 0]], dtype=np.uint8), nodata=0.0)

        kept = target.filter_paletted_to_present(layer)

        assert kept == 2
        classes = layer.renderer().classes()
        assert [(c.value, c.color, c.label) for c in classes] == [
            (1.0, "blue", "1 水域"),
            (2.0, "red", "2 市街地"),
        ]
        assert layer.renderer().band() == 1
        assert layer.repainted is True

    def test_keeps_zero_class_when_raster_has_no_nodata(
        self, target: types.ModuleType, tmp_path: Path
    ) -> None:
        """バンドに NoData が無ければ、値 0 も実在クラスとして凡例に残す。"""
        layer = self._make_layer(tmp_path, np.array([[1, 2], [2, 0]], dtype=np.uint8), nodata=None)

        kept = target.filter_paletted_to_present(layer)

        assert kept == 3
        assert [c.value for c in layer.renderer().classes()] == [0.0, 1.0, 2.0]

    def test_explicit_nodata_overrides_band_nodata(
        self, target: types.ModuleType, tmp_path: Path
    ) -> None:
        """引数の nodata を指定すると、バンドの NoData の代わりにその値を凡例から除く。"""
        layer = self._make_layer(tmp_path, np.array([[1, 2], [2, 0]], dtype=np.uint8), nodata=None)

        kept = target.filter_paletted_to_present(layer, nodata=2)

        assert kept == 2
        assert [c.value for c in layer.renderer().classes()] == [0.0, 1.0]

    def test_excludes_filled_values(self, target: types.ModuleType, tmp_path: Path) -> None:
        """実在しても filled_values に挙げた無効値は凡例から外す。"""
        layer = self._make_layer(tmp_path, np.array([[1, 10], [3, 3]], dtype=np.uint8), nodata=None)

        kept = target.filter_paletted_to_present(layer, filled_values=(10,))

        assert kept == 2
        assert [c.value for c in layer.renderer().classes()] == [1.0, 3.0]

    def test_accepts_layer_name_with_project(
        self, target: types.ModuleType, tmp_path: Path
    ) -> None:
        """レイヤ名とプロジェクトでも呼べる。"""
        layer = self._make_layer(tmp_path, np.array([[3, 3], [3, 3]], dtype=np.uint8), nodata=None)

        kept = target.filter_paletted_to_present("lulc", project=FakeProject({"lulc": layer}))

        assert kept == 1

    def test_unreadable_source_raises(self, target: types.ModuleType, tmp_path: Path) -> None:
        """ラスタのソースを開けなければ例外にする。"""
        layer = FakeRasterLayer(
            str(tmp_path / "missing.tif"), FakePalettedRasterRenderer("provider", 1, [])
        )

        with pytest.raises(ValueError, match="ラスタを開けません"):
            target.filter_paletted_to_present(layer)
