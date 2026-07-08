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

1. **小範囲bbox**(ROIの一部)で試行実行し、動作を確認する
2. [reference.md](reference.md) の検証チェックリスト(CRS・件数・カバレッジ・値域・欠損)を実施する
3. ベクタ集計値の妥当性検証が必要な場合は、QGIS MCP 突合(同一入力を QGIS ネイティブアルゴリズムに渡して結果を突き合わせる)を提案する
4. 検証結果の数値は実行出力から転記し、Issue コメントまたは PR 本文に記録する

### Step 7: ドキュメント更新・チェックリスト・コミット

1. `docs/01_planning/gis_data/gis_data_{カテゴリ}.md` に取得結果(件数・カバレッジ・注意点)を追記する
2. `docs/README.md` の変更履歴を更新する(該当する場合)
3. `docs/02_methods/CodingRule.md` の「実装前後チェックリスト」を完了する
4. `ruff check` / `ruff format`・markdownlint を実行し、ユーザー承認後にコミットする

## 注意事項

- データソースの利用規約・ライセンスを docstring と調査ドキュメントの双方に記録する
- 大容量ダウンロードを伴う実行はユーザーに確認してから行う(回線・サーバー負荷への配慮)
- 取得データは Git 管理外(`data/gis/` 等)。Google Drive への共有は別途 Drive 同期チェックの対象となる
