---
name: new-data-script
description: "公開GISデータの取得スクリプトを定型手順で作成する。データ取得系Issue（土地利用・人口密度・夜間光・水域・POI・不透水面率・公園等）に着手する際、Issue確認→設計→scaffold実装→テスト→検証→ドキュメント更新までを型に沿って実行する。「データ取得スクリプトを作って」「#73に着手」などデータ取得タスクの開始時に使用する。"
---

# データ取得スクリプト作成スキル

公開GISデータの取得スクリプト作成を、既存実装から抽出した「型」に沿って進める。
scaffold構成・検証チェックリスト・参照実装の対応は [reference.md](reference.md) を参照。

## 実行手順

以下のチェックリストをコピーして進捗を追跡する:

```text
- [ ] Step 1: Issue・データ調査ドキュメントの確認
- [ ] Step 2: データソース区分の判定・参照実装の選択
- [ ] Step 3: 設計の提示・ユーザー確認
- [ ] Step 4: scaffold に沿った実装
- [ ] Step 5: テストコードの作成・実行
- [ ] Step 6: 試行実行と検証
- [ ] Step 7: ドキュメント更新・チェックリスト・コミット
```

### Step 1: Issue・データ調査ドキュメントの確認

1. `gh issue view {番号}` で対象Issueの要件・完了条件を確認する
2. 対応する `docs/01_planning/gis_data/gis_data_{カテゴリ}.md` を読み、採用データセット・仕様・ライセンス・注意点を確認する
3. Issueと調査ドキュメントに齟齬があれば、実装前にユーザーに確認する

### Step 2: データソース区分の判定・参照実装の選択

[reference.md](reference.md) の対応表から、データソース区分(GEE / HTTP・WFS / ローカル変換)に応じた参照実装を選び、**必ず Read して構造を踏襲する**。新規の設計判断は、参照実装との差分としてのみ行う。

### Step 3: 設計の提示・ユーザー確認

実装前に以下を提示し、ユーザーの確認を得る:

- 入力(データソースURL / GEEアセットID / ローカルファイル)と取得方法
- 出力パス(`data/gis/{カテゴリ}/` の GPKG/GeoTIFF + `data/output/open_gis/` のサマリーJSON)
- 想定される制約(レート制限・ページング・タイル分割の要否)と対策
- ROI・CRSの扱い(入出力 EPSG:4326、面積・距離計算は UTM: EPSG:32648)

### Step 4: scaffold に沿った実装

[reference.md](reference.md) の scaffold 構成に従って実装する。要点:

- docstring 冒頭にデータソースと**確認日付きの制約メモ**を記載する
- `PROJECT_ROOT` 起点の相対パス・argparse・logging・リトライを標準装備する
- `src/common/` の共通モジュール(config・roi・summary・http_fetch・gee)を利用し、同等機能を自前実装しない
- 1関数1責務・型ヒント・日本語docstring(CodingRule 準拠)

### Step 5: テストコードの作成・実行

1. `tests/{preprocessing|gee}/test_{スクリプト名}.py` を作成する
2. 対象は純粋関数(bbox計算・タイル分割・属性変換・サマリー生成等)を中心とし、ネットワーク・GEE呼び出しはモックする
3. conda環境のフルパスで pytest を実行し、通過を確認する

### Step 6: 試行実行と検証

QGIS-MCP を使う工程（下記 3・4）に入る前に、**[qgis_operation_guidelines.md](../../../docs/02_methods/qgis_operation_guidelines.md) と [qgis_mcp_usage_guide.md](../../../docs/02_methods/qgis_mcp_usage_guide.md) を読み込む**（スタイル作成の注意・クロスチェック手順・各ツールの落とし穴・検証時のプロジェクト衛生を含む）。

1. **小範囲bbox**(ROIの一部)で試行実行し、動作を確認する
2. [reference.md](reference.md) の検証チェックリスト(CRS・件数・カバレッジ・値域・欠損)を実施する
3. スタイル(`.qml`)作成の要否を [qgis_operation_guidelines.md の判定表](../../../docs/02_methods/qgis_operation_guidelines.md#スタイル作成要否の判定表)で判定する。**必須と判定された場合は QGIS 表示の有無に関わらず**分類スタイルを適用し `qgis/styles/{カテゴリ}_{データセット}.qml` に保存する。保存後は同ガイドラインの確認手順(プロジェクトを開き直して凡例を確認)を実施する
4. **取得した空間データを ROI と重ねた QGIS スクリーンショットを取得・保存する**。`inspect-gis-data` の `get_canvas_screenshot` を ROI 基準でズームして取得し、`images/gis_data/{カテゴリ}/{カテゴリ}_{データセット}_{ROI}.png` に保存する（対象範囲・命名・`.qml` との2軸関係は [qgis_operation_guidelines.md の「スクリーンショット（視覚的検証記録）の扱い」](../../../docs/02_methods/qgis_operation_guidelines.md#データ取得タスクにおけるスクリーンショット視覚的検証記録の扱い)を参照。空間データ全般が対象で、非空間データは対象外）
5. ベクタ集計値の妥当性検証が必要な場合は、QGIS MCP 突合を提案する。実施する場合は [qgis_operation_guidelines.md のクロスチェック定型手順](../../../docs/02_methods/qgis_operation_guidelines.md#python-自前実装と-qgis-ネイティブアルゴリズムの突合クロスチェック)に従う(同一入力を QGIS ネイティブアルゴリズムに渡し、結果を実ファイル出力のうえ突き合わせる)
6. 検証結果の数値は実行出力から転記し、Issue コメントまたは PR 本文に記録する

### Step 7: ドキュメント更新・チェックリスト・コミット

1. `docs/01_planning/gis_data/gis_data_{カテゴリ}.md` に取得結果(件数・カバレッジ・注意点)を追記する
2. `docs/02_methods/CodingRule.md` の「実装前後チェックリスト」を完了する
3. 成果物: 取得スクリプト・テスト・サマリーJSON・調査ドキュメント追記。
   - **空間データを取得した場合は QGIS スクリーンショット（`images/gis_data/{カテゴリ}/*.png`）を必須成果物に含める**（データ型で分岐しない。非空間データは対象外 — [「スクリーンショット（視覚的検証記録）の扱い」](../../../docs/02_methods/qgis_operation_guidelines.md#データ取得タスクにおけるスクリーンショット視覚的検証記録の扱い)参照）
   - 判定表で**必須と判定されるデータ型**では `qgis/styles/{カテゴリ}_{データセット}.qml` を必須成果物に含める(任意判定で作成した場合も同様に含める。`.qgz` は完了条件に含めない — [判定表の後段](../../../docs/02_methods/qgis_operation_guidelines.md#qgis-プロジェクトqgzへの追加は完了条件に含めない)参照)
4. `ruff check` / `ruff format`・markdownlint を実行し、セルフレビュー(`/self-review`)の所見つきレビューを提示のうえ、ユーザー承認後にコミットする

## 注意事項

- データソースの利用規約・ライセンスを docstring と調査ドキュメントの双方に記録する
- 大容量ダウンロードを伴う実行はユーザーに確認してから行う(回線・サーバー負荷への配慮)
- 取得データは Git 管理外(`data/gis/` 等)。Google Drive への共有は別途 Drive 同期チェックの対象となる
