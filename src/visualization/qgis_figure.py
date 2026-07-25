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
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsMapLayer,
    QgsPalettedRasterRenderer,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor, QFont
from src.visualization import figure_layout as fl

_TMP_LAYOUT_NAME = "_gis_figure_tmp"


def _project(project: QgsProject | None) -> QgsProject:
    """明示指定がなければ現在の QGIS プロジェクトを返す。"""
    return project if project is not None else QgsProject.instance()


def _require_layer(project: QgsProject, name: str) -> QgsMapLayer:
    """名前でレイヤを取得する。見つからなければ分かりやすいエラーを送出する。"""
    layers = project.mapLayersByName(name)
    if not layers:
        raise ValueError(f"レイヤが見つかりません: {name!r}")
    return layers[0]


def _set_legend_font(
    legend: QgsLayoutItemLegend, style_enum, point_size: int, bold: bool = False
) -> None:
    """凡例スタイルのフォントサイズ・太字を設定する（QGIS 新旧 API 対応）。

    QGIS 3.40 で ``QgsLayoutItemLegend.setStyleFont`` 系が非推奨化されたため、
    まず ``QgsLegendStyle.textFormat`` / ``setTextFormat`` を用い、当該 API が無い
    古い環境では従来の ``setStyleFont`` にフォールバックする。
    """
    style = legend.style(style_enum)
    try:
        text_format = style.textFormat()
        font = text_format.font()
        font.setBold(bold)
        text_format.setFont(font)
        text_format.setSize(point_size)
        text_format.setSizeUnit(QgsUnitTypes.RenderPoints)
        style.setTextFormat(text_format)
        legend.setStyle(style_enum, style)
    except AttributeError:
        font = style.font()
        font.setPointSize(point_size)
        font.setBold(bold)
        legend.setStyleFont(style_enum, font)


def style_roi_outline(
    roi_layer: QgsVectorLayer, color: str = "255,0,0,255", width: str = "0.6"
) -> None:
    """ROI レイヤを塗りつぶしなし・指定色の外枠だけで表示する。"""
    symbol = QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": color, "outline_width": width}
    )
    roi_layer.renderer().setSymbol(symbol)
    roi_layer.triggerRepaint()


def filter_paletted_to_present(layer: QgsRasterLayer, nodata: float | None = None) -> int:
    """カテゴリ値ラスタを、データに実在するクラスだけの凡例に作り直す。

    全クラス（未使用クラス含む）を凡例に出すと巨大化するため、``gdal`` で実際の
    画素値を調べ、現れたクラスのみを残す。ラベルは英語括弧を除いた日本語のみにする。

    実在クラスはラスタ全体の画素から判定する（ROI でクリップしない）。本研究のラスタは
    概ね ROI 範囲に収まっているため、凡例と地図の内容は実用上一致する。

    Args:
        layer: ``QgsRasterLayer``（``QgsPalettedRasterRenderer`` を持つこと）。
        nodata: 無効値。指定すると凡例から除外する。

    Returns:
        残したクラス数。

    Raises:
        ValueError: ラスタソースを開けないとき。
    """
    dataset = gdal.Open(layer.source())
    if dataset is None:
        raise ValueError(f"ラスタを開けません: {layer.source()!r}")
    try:
        band = dataset.GetRasterBand(1)
        if nodata is None:
            nodata = band.GetNoDataValue()
        present = set(fl.present_class_values(band.ReadAsArray(), nodata))
    finally:
        dataset = None  # gdal データセットを明示的に解放する

    renderer = layer.renderer()
    kept = [
        QgsPalettedRasterRenderer.Class(c.value, c.color, fl.shorten_label(c.label))
        for c in renderer.classes()
        if int(round(c.value)) in present
    ]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), renderer.band(), kept))
    layer.triggerRepaint()
    return len(kept)


def set_raster_itemized_legend(layer: QgsRasterLayer) -> None:
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

    一時レイアウトはエクスポート成否に関わらず片付け、プロジェクトの ellipsoid も
    元の値へ復元する（呼び出し側のプロジェクト状態を汚さないため）。

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

    Raises:
        ValueError: データレイヤ・ROI レイヤが見つからないとき。
    """
    prj = _project(project)
    data_layer = _require_layer(prj, data_layer_name)
    roi_layer = _require_layer(prj, roi_layer_name)
    roi_ext = roi_layer.extent()
    extent = fl.roi_extent_with_margin(
        (roi_ext.xMinimum(), roi_ext.yMinimum(), roi_ext.xMaximum(), roi_ext.yMaximum()),
        roi_margin,
    )
    geom = fl.layout_geometry(extent, frame_width_mm, legend_kind, legend_h_mm)

    manager = prj.layoutManager()
    for existing in list(manager.printLayouts()):
        if existing.name() == _TMP_LAYOUT_NAME:
            manager.removeLayout(existing)

    previous_ellipsoid = prj.ellipsoid()
    prj.setEllipsoid("WGS84")  # 地理座標系でのスケールバー距離計算を有効化
    layout = QgsPrintLayout(prj)
    layout.initializeDefaults()
    layout.setName(_TMP_LAYOUT_NAME)
    page_w, page_h = geom["page"]
    layout.pageCollection().page(0).setPageSize(
        QgsLayoutSize(page_w, page_h, QgsUnitTypes.LayoutMillimeters)
    )

    try:
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
    finally:
        manager.removeLayout(layout)
        prj.setEllipsoid(previous_ellipsoid)
    return {"ok": int(result) == 0, "path": out_path}


def _add_map(
    layout: QgsPrintLayout,
    geom: dict,
    extent: tuple,
    crs: QgsCoordinateReferenceSystem,
    layers: list[QgsMapLayer],
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
    data_layer: QgsMapLayer,
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
    _set_legend_font(legend, QgsLegendStyle.SymbolLabel, legend_font_pt)
    _set_legend_font(legend, QgsLegendStyle.Title, 10, bold=True)
    legend.setBackgroundColor(QColor(255, 255, 255, 255))
    legend.setBackgroundEnabled(True)
    legend.setFrameEnabled(True)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
