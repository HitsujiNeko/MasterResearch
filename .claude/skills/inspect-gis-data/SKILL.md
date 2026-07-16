---
name: inspect-gis-data
description: "新規取得・受領したGISデータ1ファイルの定型確認（メタデータ抽出→QGIS表示→確認チェックリスト→所見テンプレート出力）を一体実行する。「このGISデータの中身を確認して」「新しいデータをQGISで見て所見をまとめて」「gpkg/tif/shpの内容を調べて」「#116のinspect-gis-data」などデータの内容確認タスクで使用する。"
---

# GISデータ内容確認スキル

新規に取得・受領したGISデータ（ラスタ/ベクタ）1ファイルの内容確認を、定型手順で進める。
`/new-data-script`（取得）→ **本スキル（内容確認）** → docs 記録、というデータ処理の鎖のうち、
これまで手作業だった「内容確認」を型化する。

**責任分界**: 本スキルは事実の抽出・提示・所見の整形までを担う。
**「分析に使えるか」の最終判断は研究者が行う**。スキルが可否を断定しない。

所見テンプレート・確認チェックリストの詳細・QGIS操作の対応表は [reference.md](reference.md) を参照する。

## 実行手順

以下のチェックリストをコピーして進捗を追跡する:

```text
- [ ] Step 1: メタデータ抽出・提示
- [ ] Step 2: QGIS 表示（ROI と重ね合わせ）
- [ ] Step 3: 確認チェックリストの提示・目視所見の聞き取り
- [ ] Step 4: 所見の定型出力・配置先の提案
```

### Step 1: メタデータ抽出・提示

対象ファイルのメタデータを、#114 のインベントリスクリプトの単一ファイルモードで抽出する
（**メタデータ抽出はこのCLIに一本化し、スキル内で再実装しない**）。

```bash
# conda環境 masterresearch の python（フルパス）で実行する。
# 例: {conda}/envs/masterresearch/python.exe -m src.analysis.build_data_inventory --path {対象ファイル}
{conda環境masterresearchのpython} -m src.analysis.build_data_inventory --path {対象ファイル}
```

- 出力される JSON（CRS・レイヤ・ジオメトリ種別・地物数・属性スキーマ・bbox・サイズ）を読み取り、
  ユーザーに要点を表形式で提示する（[reference.md](reference.md) の「メタデータ提示フォーマット」に従う）
- **注意**: DGN 由来 GPKG など一部データは JSON の `crs` が空文字・`geometry_type` が `Unknown` になる。
  これは異常ではなくデータの特性であり、Step 2/3 で `get_layer_crs` と目視により確定する

### Step 2: QGIS 表示（ROI と重ね合わせ）

QGIS MCP で対象レイヤを読み込み、ROI と重ねて表示する。命名規則・CRS 方針は
[qgis_operation_guidelines.md](../../../docs/02_methods/qgis_operation_guidelines.md) に従う。
操作の詳細は [reference.md](reference.md) の「QGIS 操作対応表」を参照する。

1. `ping` で QGIS 接続を確認する
2. `add_vector_layer` / `add_raster_layer` で対象を**絶対パス**指定で読み込む
3. ROI（既定: `data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp`。対象都市が異なる場合はユーザーに確認）を
   読み込み、`ROI` グループに配置する
4. `get_layer_crs` で対象レイヤの CRS を確認する。
   - **CRS が未定義**（`authid`・`proj4` が空）の場合、データは正しい位置に描画されず ROI と重ならない。
     想定される CRS（ベトナム測量データは VN-2000 / UTM zone 48N = `EPSG:3405`）を
     `set_layer_crs` で設定してから重ねる（`set_layer_crs` は再投影せず解釈を変えるだけ）。
     設定前に代表点を `transform_coordinates` で EPSG:4326 に変換し、ROI 域内に落ちるかで
     CRS 推定の妥当性を確認するとよい
   - VN-2000 等の投影座標系は、プロジェクト CRS（EPSG:4326）のオンザフライ変換で ROI と重なる
     （データは恒久再投影しない。プロジェクト CRS は EPSG:4326 のまま維持）
5. **ROI レイヤにズーム**して `get_canvas_screenshot` で描画を取得し、カバレッジを目視提示する。
   対象レイヤ全体にズームすると、外れ値ジオメトリがある場合に実データが1点に潰れて見えないため、
   まず ROI 基準で重なりを確認する（下記 Step 3 のジオメトリ確認と連動）
6. 大規模レイヤ（数十万件〜）を扱う場合は、レイヤ追加ごとに `save_project` でこまめに保存する
   （[qgis_operation_guidelines.md](../../../docs/02_methods/qgis_operation_guidelines.md) のクラッシュ対策）

### Step 3: 確認チェックリストの提示・目視所見の聞き取り

[reference.md](reference.md) の「確認チェックリスト」を提示し、ユーザーの目視所見を聞き取る。観点:

- **カバレッジ**: データの範囲は ROI を覆うか（一部か・全域か・ROI 外か）
- **属性**: 分析に利用可能な値を持つ属性はどれか（標高値・区分コード・名称など）
- **CRS**: CRS は正しく認識されているか（未定義・想定外の座標系でないか）
- **ジオメトリ**: 不正ジオメトリ・想定外のジオメトリ種別混在はないか

**スキルは可否を断定しない**。事実（何が見えるか）を整理し、判断材料をユーザーに示すに留める。

### Step 4: 所見の定型出力・配置先の提案

聞き取った所見を [reference.md](reference.md) の「所見テンプレート」に整形して出力し、配置先を提案する。

- 配置先は `docs/` のデータ調査ドキュメント形式に合わせる（測量データなら
  `docs/03_results/survey_gis_data_preparation_status.md`、公開GISなら
  `docs/01_planning/gis_data/gis_data_{カテゴリ}.md` 等。既存の該当ドキュメントを確認して提案）
- 配置（ファイルへの追記・新規作成）はユーザーの承認を得てから行う

## 注意事項

- メタデータ抽出は Step 1 の CLI に一本化する。スキル内に抽出ロジックを再実装しない
- QGIS のパス指定は絶対パス（相対パスは未保存プロジェクトで読み込み失敗する）
- `remove_layer` は元に戻せない。確認後のレイヤ整理はユーザーに確認してから行う
- 所見の最終的な学術的判断（分析採否・手法選択）は研究者の責任範囲とする
