# QGIS MCP 活用ガイド

**最終更新**: 2026-07-28
**関連ドキュメント**: [qgis_mcp_setup.md](../setup/qgis_mcp_setup.md), [qgis_operation_guidelines.md](qgis_operation_guidelines.md), [data_management_guide.md](data_management_guide.md)
**前提知識**: QGIS MCPのセットアップ完了（[qgis_mcp_setup.md](../setup/qgis_mcp_setup.md)）、QGISの基本操作

---

## 概要

本ガイドは、セットアップ済みのQGIS MCPを使って実際にどのような作業ができるかを、ユースケース別の操作例で示す。接続手順やトラブルシューティングは[qgis_mcp_setup.md](../setup/qgis_mcp_setup.md)を参照し、本ガイドは「使いこなし方」に特化する。

**プロジェクト構成**: `qgis/projects/hanoi.qgz`（都市単位のプロジェクト、Git管理外）、`qgis/styles/`（再利用スタイル、Git追跡）、`qgis/templates/`（印刷レイアウトテンプレート、Git追跡）。詳細は[qgis_operation_guidelines.md](qgis_operation_guidelines.md)を参照。

---

## ユースケース1: データ確認

GISデータをQGISで目視確認したいとき。

```text
「<ABS_PATH>/data/gis/buildings/hanoi_gba_buildings.gpkg をQGISに読み込んで、
 属性フィールドとレコード数を教えて」
```

Claude Codeは`add_vector_layer`でレイヤーを読み込み、`get_layer_features`で属性・件数を確認する。ラスターの値域確認には`get_raster_info`（min/max/バンド数/extent）を使う。

**注意**: パスは絶対パスを指定する。プロジェクトに保存先パスがない状態（新規未保存プロジェクト等）で相対パスを指定すると読み込みに失敗することを確認済み。

**CRSの確認はQGISでは行わない**。手順は下記「[CRSの確認手順](#crsの確認手順)」を参照する。

## ユースケース2: レイヤー操作・グループ管理

```text
「<ABS_PATH>/data/gis/roads/hanoi_osm_roads.gpkg を読み込んで
 『道路』グループに入れて」
```

`add_vector_layer` / `add_raster_layer` → `create_layer_group`（未作成の場合）→ `move_layer_to_group` の順で操作する。レイヤー削除は`remove_layer`（元に戻せないため注意）。

## ユースケース3: スタイル適用

再利用スタイル（`qgis/styles/*.qml`）を既存レイヤーに適用する場合。

```text
「GBA建物レイヤーに qgis/styles/building_coverage.qml を適用して」
```

`apply_style_qml`でベクター・ラスターどちらにも適用できる。新規にスタイルを作る場合、ベクターの単純な分類（categorized/graduated）は`set_layer_style`で十分だが、**ラスターの疑似カラー（LST・NDVI等）は`set_layer_style`では対応できないため`execute_code`でPyQGISを直接操作する**（[qgis_operation_guidelines.md](qgis_operation_guidelines.md)の注意事項を必ず参照）。

## ユースケース4: Map Theme切り替え

研究のシナリオ定義（Satellite Only / Limited / Full）に対応したMap Themeが`hanoi.qgz`に設定済み。

```text
「hanoi.qgz で Limited のMap Themeに切り替えて」
```

`apply_map_theme`で切り替える。テーマ自体の再定義・追加は、対象レイヤーグループの可視性を`execute_code`（`QgsLayerTreeGroup.setItemVisibilityChecked`）で設定してから`add_map_theme`を呼ぶ（同名テーマは上書き更新される）。

## ユースケース5: Processing実行

QGIS Processingアルゴリズムを対話的に実行したい場合。

```text
「OSM道路レイヤーにバッファ処理を500m半径で実行して」
```

`list_processing_algorithms`でアルゴリズムを検索し、`get_algorithm_help`でパラメータを確認したうえで`execute_processing`を実行する。複数レイヤーへの一括処理は`execute_processing_batch`を使う。

**注意**: `execute_processing`の`OUTPUT` / `OUTPUT_TABLE`に`memory:...`を指定すると、処理は成功しても出力レイヤが`get_layers()`に現れず`get_layer_features()`で参照できない（`Layer not found`）。後続で結果を検証・比較する場合は出力先に実ファイル（`.gpkg`等）を指定する（[qgis_operation_guidelines.md の「execute_processing の出力先は実ファイルにする」](qgis_operation_guidelines.md#execute_processing-の出力先は実ファイルにする)を参照）。

## ユースケース6: 地図の確認・出力

- 簡易確認: `get_canvas_screenshot`（現在のキャンバス描画を高速に取得、再レンダリングなし）
- 高品質レンダリング: `render_map`
- 印刷レイアウト出力: `qgis/templates/standard_a4_map.qpt`をベースにしたレイアウトを`export_layout`でPDF/画像として書き出す

**注意: `render_map`はレイヤー可視性変更を反映しないことがある**。`set_layer_visibility()`で表示/非表示を切り替え、`refreshAllLayers()`で強制リフレッシュしても、`render_map()`の出力画像が変化しない事例がある（キャッシュされた合成結果を返している可能性）。一方、`get_canvas_screenshot`や`execute_code`での`iface.mapCanvas().saveAsImage(path)`は可視性変更を正しく反映する。**特定レイヤーのみを表示した画像が必要な場合は`render_map`を使わず後者を用いる**（どうしても`render_map`を使う場合は、可視性変更が画像に反映されているか毎回目視確認する）。

---

## CRSの確認手順

**CRSの判定はQGISではなくpyogrio / rasterio側で行い、QGISは描画確認（ROIと重なるか・位置がずれていないか）に限定する。** いずれもメタデータ（ヘッダー情報）のみを読むため、大規模データでも全件読み込みは発生しない（GeoPandasでCRSを取得する場合は後述の注意点に従う。メタデータのみの読み込みではない）。

```python
import pyogrio
import rasterio

# ベクタ（Shapefile・GeoPackage 等）。メタデータのみ読む
print(pyogrio.read_info(vector_path)["crs"])

# ラスタ（GeoTIFF 等）。ヘッダーのみ読むため画素データの読み込みは発生しない
with rasterio.open(raster_path) as src:
    print(src.crs)
```

GeoPandasを使う場合は`gpd.read_file(vector_path).crs`で取得できるが、これは**全地物を読み込んでから**CRSを取り出すため、GBA建物（約307万件）や測量データのような大規模ベクタでは避ける。読み込む場合は`gpd.read_file(vector_path, rows=1).crs`のように件数を絞る。

QGIS側のCRS解決が効かない事例が実測されているためである。ROI（Shapefile）・人口密度ラスタ（GeoTIFF）のいずれでも、`get_layer_crs`が`authid=''`・`srsid=0`・`is_geographic=false`を返した。同一セッション内で`QgsCoordinateReferenceSystem("EPSG:4326")`を明示構築すると`authid='EPSG:4326'`・`isGeographic=True`が正しく返るため、QGISのCRS解決（WKT → EPSGデータベース照合）が効いていないと考えられる。同じGeoTIFFをrasterioで開くと`EPSG:4326`と正しく解決されるため、データ側の問題ではない。

**`is_geographic: false`を「投影座標系である」と読んではいけない。** 上記の事例では当該レイヤーの`mapUnits()`が`6`（Degrees）を返しており、「単位は度と分かっているのに地理座標系と判定されない」という自己矛盾した状態になっている。`is_geographic`や`authid`を根拠にCRSずれを判断すると誤検知する。

どうしてもQGIS内で確認したい場合は、`authid`ではなく`execute_code`でWKTと地図単位を直接確認する。

```python
import json

# layer は対象のレイヤー。例では現在のアクティブレイヤーを取得する
layer = iface.activeLayer()
crs = layer.crs()
print(json.dumps({"wkt": crs.toWkt(), "map_units": crs.mapUnits()}, ensure_ascii=False))
```

`toWkt()`にはEPSGデータベース照合を経ない生の座標系定義が現れるため、`authid`が空でも座標系を判別できる。

---

## 注意点: 大規模レイヤーのパフォーマンス

本研究のGBA建物データ（約307万件）や測量データ（数十万件規模のレイヤーが複数）を**対話キャンバスで同時に可視化状態にする**と、QGIS自体がクラッシュする事例が確認されている。危険な操作と安全な操作の切り分けは[qgis_operation_guidelines.md](qgis_operation_guidelines.md)の「大規模レイヤーの取り扱い」を参照。ROI固定の単発描画は今回実測した条件下では同規模のデータでも完走しているが、同規模データ全般の安全性を保証するものではない（失敗時の代替策は同ドキュメント参照）。

**実務上の対策**（対話キャンバスで作業する場合）:

- レイヤー・グループを追加するたびに`save_project`でこまめに保存する（クラッシュ時の作業ロスを最小化）
- 全レイヤーを同時に可視化する操作（`Full`テーマの確認など）は特に注意し、保存直後に行う
