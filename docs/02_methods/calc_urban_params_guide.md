# calc_urban_params 設計再定義ガイド

**最終更新**: 2026-04-21  
**関連ドキュメント**: [analysis_workflow.md](analysis_workflow.md), [available_gis_data.md](../01_planning/available_gis_data.md), [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md), [CodingRule.md](CodingRule.md)  
**前提知識**: RQ1-RQ3、CRS（WGS84/UTM）、ラスタ/ベクタ処理の基礎

---

## 1. 本ガイドの位置づけ

本ドキュメントは、`src/analysis/calc_urban_params.py` を**ゼロから再構築**するための設計正本です。  
旧実装の読解資料ではなく、次の目的を持つ実装設計書として扱います。

- 都市構造パラメータ算出処理の責務を再定義する
- GIS由来と衛星由来の説明変数を同一フレームで扱う
- LSTとの空間整合ルール（ROI→GIS有効域）を明文化する
- 再現可能な入出力仕様を固定する
- `Limited` / `Full` の両シナリオで使える設計を明文化する

---

## 2. 再構築が必要な理由

### 2.1 既存実装・既存文書の課題

- 既存コードは探索段階の近似実装であり、研究手順としての固定仕様が不十分
- レイヤ意味（DH/THなど）と変数定義の整合が曖昧な箇所がある
- 測量由来GISを前提にした記述が多く、公開 GIS にも適用できる設計になっていない
- GIS由来のみを中心に設計され、衛星由来指標との統合設計が弱い
- データ品質管理列（欠損理由、有効フラグなど）が不足

### 2.2 再構築方針

- 「まず設計を固定し、その設計に実装を合わせる」
- 旧コードの部分修正ではなく、責務単位で作り直す
- 研究手順の根拠は `analysis_workflow.md` と整合させる

---

## 3. 用語と空間整合ルール

### 3.1 重要な前提

- LSTはGEE算出時点でROI（行政区画）にクリップ済み
- 公開 GIS は ROI 全体を覆える場合がある
- 測量GISはROI内の一部（中心部の矩形領域）である

### 3.2 分析時の空間整合

1. LSTはROIクリップ済みデータを入力する  
2. `Limited` では公開 GIS の取得範囲、`Full` では測量 GIS 有効域で分析対象を限定する  
3. その結果、LSTとの結合時には「ROI内かつシナリオごとのGIS有効域内」のセルが対象になる

> これは不整合ではなく、処理段階の違いである。

---

## 4. スコープ定義（本スクリプトが担う範囲）

### 4.1 担当範囲

- 30mグリッドの生成（計算はUTM）
- GIS由来パラメータ算出
- 衛星由来ラスタ指標の30mグリッド集約（任意入力）
- シナリオ別の分析用説明変数CSVの出力

### 4.2 非担当範囲

- LST算出（`src/gee/gee_calc_LST.py`）
- モデル構築・評価（RQ1-RQ3の回帰/ML処理）
- 可視化スクリプト

---

## 5. 入力仕様（再定義）

## 5.1 必須入力（共通）

- ROI でクリップ済みの LST ラスタ
- 30m グリッド化対象となる GIS データ一式
- 解析範囲を定義するポリゴンまたは境界データ

## 5.2 シナリオ別入力（GIS）

### 5.2.1 Limited

- OpenStreetMap / Geofabrik 由来の道路ライン
- Microsoft GlobalMLBuildingFootprints 等の建物ポリゴン
- 必要に応じて OSM 土地利用・水域ポリゴン

### 5.2.2 Full

- `data/output/gis_wgs84/merge_RG_wgs84.gpkg`（分析範囲定義）
- `data/output/gis_wgs84/merge_DC_wgs84.gpkg`（建物）
- `data/output/gis_wgs84/merge_GT_wgs84.gpkg`（道路）
- `data/output/gis_wgs84/merge_TH_wgs84.gpkg` または `merge_DH_wgs84.gpkg`（水系・標高関連、利用方法は要確認）
- `data/output/gis_wgs84/merge_TV_wgs84.gpkg`（植生・土地利用）

> DH / TH / TV のどれを水域率・標高・植生率に使うかは、`gpkgの確認結果.md` と `DGNファイル内容確定結果.md` を踏まえて最終確定する。  
> 現時点では完全確定ではなく、実装と並行して調整中である。

## 5.3 任意入力（衛星指標ラスタ）

任意で次のGeoTIFFを指定可能とする。

- NDVI
- NDBI
- NDWI
- FVC

入力が存在する指標のみ列を出力し、存在しない指標は処理を継続する。

---

## 6. 出力仕様（固定）

出力先: `data/csv/analysis/urban_params_<scenario>_<city_id>.csv`

### 6.1 必須列

- `lon`, `lat`（30mセル中心座標、WGS84）
- `BUILD_COV_0`（建物被覆率, 0-1）
- `BUILD_DEN_0`（建物数密度, count/cell）
- `ROAD_DEN_0`（道路密度, m/cell）
- `WATER_COV_0`（水域被覆率, 0-1）
- `GREEN_COV_0`（植生被覆率, 0-1）

### 6.2 条件付き列

- `ELEV_MEAN_0`（標高平均。算出方法は現時点で未確定）
- `ELEV_COUNT_0`（標高値の有効点数）
- `NDVI_0`, `NDBI_0`, `NDWI_0`, `FVC_0`（入力がある場合のみ）

### 6.3 品質管理列

- `VALID_GIS_MASK`（少なくとも1つのGIS指標が有効なセル）
- `MISSING_REASON`（主要欠損理由。`none` / `no_gis_feature` / `outside_mask`）
- `DATA_SOURCE`（`open_gis` / `survey_gis` 等）

---

## 7. 処理設計（関数責務）

### 7.1 Step A: 解析範囲・グリッド準備

- シナリオに応じて公開 GIS 範囲または RG レイヤのBBoxを取得
- WGS84からUTMへ投影
- 30mグリッドを作成（必要時10m補助グリッドを生成）

### 7.2 Step B: GIS由来指標

- 建物（Microsoft / OSM / DC）
  - `BUILD_COV_0`: ポリゴン被覆率（10m→30m平均）
  - `BUILD_DEN_0`: 重心のセル内カウント
- 道路（OSM / GT）
  - `ROAD_DEN_0`: セル内ライン長（m）
- 水系（OSM water / TH / DH）
  - `WATER_COV_0`: 水域被覆率
- 植生（TV / OSM landuse 等）
  - `GREEN_COV_0`: 植生被覆率
- 等高線/標高点（DH）
  - 点属性から数値標高を抽出し、セル平均を算出する案を第一候補とする

> 測量由来GISのレイヤ意味は最終的に固定し切れていない部分があるため、  
> 特に `WATER_COV_0`, `GREEN_COV_0`, `ELEV_MEAN_0` の入力源は今後の確認で更新され得る。

### 7.3 Step C: 衛星由来指標（任意）

- 各ラスタをUTM30mグリッドに再投影
- `Resampling.average` でセル平均を取得
- 有効値のみ出力列に追加

### 7.4 Step D: 品質管理・出力

- 欠損理由を列に付与
- データソース種別を列に付与
- 最終CSVをUTF-8で保存
- 処理サマリ（件数、欠損率、統計量）を標準出力

---

## 8. CRS・単位ルール

- ファイル入出力座標: WGS84（EPSG:4326）
- 距離・面積・長さ計算: UTM（都市別の適切なEPSG）
- 温度: 摂氏（LST側の仕様に従う）
- 被覆率: 0-1
- 道路密度: m/cell（30mセル）

---

## 9. 例外処理と堅牢性

- 不正ジオメトリは `make_valid` を試行し、失敗時はスキップ
- レイヤ名が設定値と不一致の場合は、候補レイヤを探索して自動解決
- 任意入力（衛星指標）が欠けていても処理継続
- シナリオごとに不足レイヤを検出し、不足分を明示して停止または継続判断する
- エラーメッセージは日本語で明示

---

## 10. CLI仕様（案）

```bash
python -m src.analysis.calc_urban_params --city hanoi \
  --scenario limited \
  --coarse-res 30 --fine-res 10 \
  --satellite-dir data/output/indices/hanoi
```

主要引数:

- `--city`: 都市ID（例: hanoi）
- `--scenario`: `limited` または `full`
- `--coarse-res`: 出力グリッド解像度（既定30m）
- `--fine-res`: 被覆率計算の補助解像度（既定10m）
- `--satellite-dir`: 任意。衛星指標ラスタの格納ディレクトリ
- `--mask-layer-key`: 解析範囲の基準レイヤ（既定 `rg`）

---

## 11. 検証項目（最低限）

- 出力CSVの必須列存在
- `BUILD_COV_0`, `WATER_COV_0`, `GREEN_COV_0` が 0-1 範囲
- `ROAD_DEN_0` が負値を持たない
- 座標列 `lon`, `lat` がハノイ近傍範囲に入る
- 欠損率サマリをログで確認
- `DATA_SOURCE` が想定シナリオと一致する

---

## 12. 今回の再構築ゴール

1. 本ガイド（設計）を正本化  
2. `calc_urban_params.py` を本ガイド準拠で再実装  
3. `Limited` / `Full` の両方に接続できる入力仕様を固定する
4. 研究者が「変数定義・計算根拠・制約」を追跡できる状態にする

---

## 13. 更新ルール

- 実装変更時は本ガイドを同時更新する
- 列名・単位・欠損規則を変更した場合は必ず履歴に残す
- `docs/README.md` のカタログ情報と齟齬を作らない
