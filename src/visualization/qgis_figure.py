"""PyQGIS を用いた ROI 固定の印刷レイアウト図（スクリーンショット）生成。

**QGIS 内実行専用**。QGIS-MCP の ``execute_code`` などから、リポジトリルートを
``sys.path`` に加えたうえで import して使う。レイアウトの寸法計算は QGIS 非依存の
:mod:`src.visualization.figure_layout` に委譲し、本モジュールは PyQGIS による
レイアウト構築・PNG 出力に集中する。

想定する使い方（呼び出し側の責務）:

1. データレイヤと ROI レイヤを QGIS プロジェクトに読み込む（絶対パス）。
2. データ固有の前処理（CRS 設定・``.qml`` 適用・シンボル設定）を行う。
   - カテゴリ値ラスタは :func:`filter_paletted_to_present` で実在クラスに絞れる。
   - 連続値ラスタは :func:`set_raster_itemized_legend` で凡例を項目表示にできる。
3. :func:`build_gis_figure` を呼び、タイトル・スケールバー・凡例つき PNG を出力する。

保存機構の注意: ``get_canvas_screenshot`` は画像をインライン返却するのみでファイル
保存しない。コミット用 PNG は本モジュール（印刷レイアウト export）か
``render_map(path=...)`` で生成する。
"""

from __future__ import annotations

from osgeo import gdal

from qgis.core import (
    QgsColorRampLegendNodeSettings,
    QgsFillSymbol,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsPalettedRasterRenderer,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsUnitTypes,
)
from qgis.PyQt.QtGui import QColor, QFont
from src.visualization import figure_layout as fl

_TMP_LAYOUT_NAME = "_gis_figure_tmp"


def _project(project: QgsProject | None) -> QgsProject:
    """明示指定がなければ現在の QGIS プロジェクトを返す。"""
    return project if project is not None else QgsProject.instance()


def style_roi_outline(roi_layer, color: str = "255,0,0,255", width: str = "0.6") -> None:
    """ROI レイヤを塗りつぶしなし・指定色の外枠だけで表示する。"""
    symbol = QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": color, "outline_width": width}
    )
    roi_layer.renderer().setSymbol(symbol)
    roi_layer.triggerRepaint()


def filter_paletted_to_present(layer, nodata: float | None = None) -> int:
    """カテゴリ値ラスタを、データに実在するクラスだけの凡例に作り直す。

    全クラス（未使用クラス含む）を凡例に出すと巨大化するため、``gdal`` で実際の
    画素値を調べ、現れたクラスのみを残す。ラベルは英語括弧を除いた日本語のみにする。

    Args:
        layer: ``QgsRasterLayer``（``QgsPalettedRasterRenderer`` を持つこと）。
        nodata: 無効値。指定すると凡例から除外する。

    Returns:
        残したクラス数。
    """
    dataset = gdal.Open(layer.source())
    band = dataset.GetRasterBand(1)
    if nodata is None:
        nodata = band.GetNoDataValue()
    present = set(fl.present_class_values(band.ReadAsArray(), nodata))

    renderer = layer.renderer()
    kept = [
        QgsPalettedRasterRenderer.Class(c.value, c.color, fl.shorten_label(c.label))
        for c in renderer.classes()
        if int(round(c.value)) in present
    ]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), renderer.band(), kept))
    layer.triggerRepaint()
    return len(kept)


def set_raster_itemized_legend(layer) -> None:
    """連続値疑似カラーラスタの凡例を、連続グラデーションから項目表示に切り替える。

    地図は INTERPOLATED のまま滑らかに描画しつつ、凡例だけ ``.qml`` 定義済みの
    値（例: 標高 0/20/50/150/1269m）を個別ラベルで示す。連続グラデーション凡例では
    min/max しか読めず値域が判読しにくいため。
    """
    shader = layer.renderer().shader().rasterShaderFunction()
    settings = QgsColorRampLegendNodeSettings()
    settings.setUseContinuousLegend(False)
    shader.setLegendSettings(settings)
    layer.triggerRepaint()


def build_gis_figure(
    data_layer_name: str,
    roi_layer_name: str,
    title_text: str,
    out_path: str,
    legend_kind: str = fl.LEGEND_NONE,
    legend_cols: int = 3,
    legend_font_pt: int = 7,
    legend_h_mm: float = 55.0,
    frame_width_mm: float = 180.0,
    roi_margin: float = 0.05,
    dpi: int = 150,
    project: QgsProject | None = None,
) -> dict:
    """ROI 固定の印刷レイアウト図を組み、PNG を出力する。

    地図フレームは ROI の縦横比に一致させる（見切れ防止）。凡例が必要な図は
    ページを縦に伸ばし、地図の下に凡例帯を置く。凡例には対象データレイヤのみを残す
    （ROI 枠は除外）。

    Args:
        data_layer_name: 主題データレイヤ名（読み込み・スタイル適用済みであること）。
        roi_layer_name: ROI レイヤ名（描画範囲の基準）。
        title_text: 図タイトル。
        out_path: 出力 PNG の絶対パス。
        legend_kind: :data:`figure_layout.LEGEND_NONE` か :data:`figure_layout.LEGEND_ITEMS`。
        legend_cols: 項目凡例の段組み数。
        legend_font_pt: 項目凡例ラベルの文字サイズ(pt)。
        legend_h_mm: 項目凡例帯の高さ(mm)。
        frame_width_mm: 地図フレームの幅(mm)。
        roi_margin: ROI 範囲へ加えるマージンの割合。
        dpi: 出力解像度。
        project: 対象プロジェクト。省略時は現在のプロジェクト。

    Returns:
        ``{"ok": bool, "path": str}``。
    """
    prj = _project(project)
    prj.setEllipsoid("WGS84")  # 地理座標系でのスケールバー距離計算を有効化

    data_layer = prj.mapLayersByName(data_layer_name)[0]
    roi_layer = prj.mapLayersByName(roi_layer_name)[0]
    roi_ext = roi_layer.extent()
    extent = fl.roi_extent_with_margin(
        (roi_ext.xMinimum(), roi_ext.yMinimum(), roi_ext.xMaximum(), roi_ext.yMaximum()),
        roi_margin,
    )
    geom = fl.layout_geometry(extent, frame_width_mm, legend_kind, legend_h_mm)

    manager = prj.layoutManager()
    for layout in list(manager.printLayouts()):
        if layout.name() == _TMP_LAYOUT_NAME:
            manager.removeLayout(layout)

    layout = QgsPrintLayout(prj)
    layout.initializeDefaults()
    layout.setName(_TMP_LAYOUT_NAME)
    page_w, page_h = geom["page"]
    layout.pageCollection().page(0).setPageSize(
        QgsLayoutSize(page_w, page_h, QgsUnitTypes.LayoutMillimeters)
    )

    # ROI を上、対象データを下に。プロジェクトの他の可視レイヤは描画しない
    _add_map(layout, geom, extent, roi_layer.crs(), [roi_layer, data_layer])
    _add_title(layout, geom, title_text)
    _add_scalebar(layout, geom)
    if legend_kind == fl.LEGEND_ITEMS:
        _add_legend(layout, geom, data_layer, legend_cols, legend_font_pt)

    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = dpi
    result = exporter.exportToImage(out_path, settings)
    manager.removeLayout(layout)
    return {"ok": int(result) == 0, "path": out_path}


def _add_map(
    layout: QgsPrintLayout, geom: dict, extent: tuple, crs, layers: list
) -> QgsLayoutItemMap:
    """ROI 範囲を表示する地図アイテムを追加する。

    - 地図アイテムの CRS を ROI（範囲の座標系）に明示設定する。プロジェクト CRS が
      ROI と異なる（例: 測量データ用に EPSG:5897）場合でも範囲を正しく解釈させるため。
    - 描画レイヤを ``layers`` に固定する。プロジェクトの他の可視レイヤ（basemap 等）を
      混入させず、可視状態にも依存しない再現的な図にするため（``layers`` は上から順）。
    """
    x, y, w, h = geom["map"]
    item = QgsLayoutItemMap(layout)
    item.setCrs(crs)
    item.setRect(0, 0, w, h)
    item.setExtent(QgsRectangle(*extent))
    item.setLayers(layers)
    item.setBackgroundColor(QColor(255, 255, 255))
    item.setFrameEnabled(True)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    return item


def _add_title(layout: QgsPrintLayout, geom: dict, title_text: str) -> None:
    """図タイトルを追加する。"""
    x, y = geom["title"]
    label = QgsLayoutItemLabel(layout)
    label.setText(title_text)
    font = QFont()
    font.setPointSize(18)
    font.setBold(True)
    label.setFont(font)
    label.adjustSizeToText()
    layout.addLayoutItem(label)
    label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))


def _first_map(layout: QgsPrintLayout) -> QgsLayoutItemMap:
    """レイアウト内の最初の地図アイテムを返す。"""
    for item in layout.items():
        if isinstance(item, QgsLayoutItemMap):
            return item
    raise RuntimeError("地図アイテムが見つかりません")


def _add_scalebar(layout: QgsPrintLayout, geom: dict) -> None:
    """スケールバー（km 単位）を地図フレームの左下隅（枠内）に追加する。

    地図内のデータ上に重ねるため、白背景を付けて可読性を確保する。
    """
    x, y = geom["scalebar"]
    bar = QgsLayoutItemScaleBar(layout)
    bar.setLinkedMap(_first_map(layout))
    bar.setStyle("Single Box")
    bar.setUnits(QgsUnitTypes.DistanceKilometers)
    bar.setUnitLabel("km")
    bar.applyDefaultSize(QgsUnitTypes.DistanceKilometers)
    bar.setBackgroundColor(QColor(255, 255, 255, 210))
    bar.setBackgroundEnabled(True)
    layout.addLayoutItem(bar)
    bar.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))


def _add_legend(
    layout: QgsPrintLayout,
    geom: dict,
    data_layer,
    legend_cols: int,
    legend_font_pt: int,
) -> None:
    """対象データレイヤのみの項目凡例を地図の下に追加する。

    凡例モデルを対象レイヤだけで組み直す（プロジェクトのレイヤツリーに依存しない）。
    これにより ROI 枠や他の可視レイヤは凡例に出さず、対象レイヤがツリー外にあっても
    正しく凡例を生成できる。
    """
    x, y, w, h = geom["legend"]
    legend = QgsLayoutItemLegend(layout)
    legend.setLinkedMap(_first_map(layout))
    legend.setTitle("凡例")
    legend.setColumnCount(legend_cols)
    legend.setEqualColumnWidth(True)
    legend.setSplitLayer(True)
    legend.setAutoUpdateModel(False)
    root = legend.model().rootGroup()
    root.clear()
    root.addLayer(data_layer)
    symbol_font = legend.style(QgsLegendStyle.SymbolLabel).font()
    symbol_font.setPointSize(legend_font_pt)
    legend.setStyleFont(QgsLegendStyle.SymbolLabel, symbol_font)
    title_font = legend.style(QgsLegendStyle.Title).font()
    title_font.setPointSize(10)
    title_font.setBold(True)
    legend.setStyleFont(QgsLegendStyle.Title, title_font)
    legend.setBackgroundColor(QColor(255, 255, 255, 255))
    legend.setBackgroundEnabled(True)
    legend.setFrameEnabled(True)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
