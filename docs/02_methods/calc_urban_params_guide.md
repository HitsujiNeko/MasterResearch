# calc_urban_params.py 詳細解説

**最終更新**: 2026-03-10  
**関連ドキュメント**: [analysis_workflow.md](analysis_workflow.md), [CodingRule.md](CodingRule.md), [data_preparation_status.md](../03_results/data_preparation_status.md)  
**前提知識**: RQ1-RQ3、ベクタ/ラスタ処理、CRS（WGS84/UTM）の基本

---

## 1. このドキュメントの目的

本書は、`src/analysis/calc_urban_params.py` を「保守・改良できるレベル」で理解するための詳細ガイドです。  
単なる概要ではなく、次の観点を網羅します。

- スクリプト全体の設計意図
- 入力データの前提と制約
- 各関数の責務、入出力、処理の流れ
- 変数定義（列名）と研究設計（RQ）との対応
- 現状実装の近似・限界・改善余地

---

## 2. スクリプトの役割（研究全体の中での位置）

`calc_urban_params.py` は、Step 3（都市構造パラメータ算出）を担当します。

- 入力: 測量由来の WGS84 GPKG（DC, DH, GT, RG）
- 処理: 30m グリッド上で都市構造指標を集計
- 出力: `data/csv/analysis/urban_params_<city_id>.csv`

この出力は、後続のデータ結合（LSTとの結合）と機械学習（RQ1/RQ2/RQ3）で使う説明変数の土台です。

---

## 3. 設計思想（なぜこの実装か）

### 3.1 空間範囲の定義

- LST は GEE で ROI クリップ済み
- 測量 GIS は ROI より狭い中心部矩形
- 一部レイヤ（例: DC/GT）に外れ値ジオメトリ混入リスク

このため、分析範囲は `merge_RG_wgs84.gpkg` の BBox を基準にしています。

### 3.2 CRS 方針

- 入力/出力座標は WGS84（EPSG:4326）
- 距離・面積に関わる計算は UTM（m単位）

理由: 経緯度のまま 30m を扱うと、緯度依存で距離が歪むため。

### 3.3 30m 指標の作り方

- 被覆率（建物/水域）: 10m ラスタ化して 30m へ平均集約
- 建物密度: 建物ポリゴン重心を 30m セルへビニング
- 道路密度（実装値）: 10m ラスタ化結果から m/セルを近似

---

## 4. 入出力仕様

### 4.1 入力

`CITY_CONFIG["hanoi"]` で以下を参照します。

- `data/output/gis_wgs84/merge_RG_wgs84.gpkg`（layer: `merge_RG_wgs84`）
- `data/output/gis_wgs84/merge_DC_wgs84.gpkg`（layer: `elements`）
- `data/output/gis_wgs84/merge_DH_wgs84.gpkg`（layer: `merge_DH_wgs84`）
- `data/output/gis_wgs84/merge_GT_wgs84.gpkg`（layer: `elements`）

### 4.2 出力

- `data/csv/analysis/urban_params_hanoi.csv`
- 主な列:
  - `lon`, `lat`: 30m グリッド中心（WGS84）
  - `BUILD_COV_0`: 建物被覆率（0-1）
  - `BUILD_DEN_0`: 建物密度（棟/セル）
  - `WATER_COV_0`: 水域被覆率（0-1）
  - `ROAD_DEN_0`: 道路密度近似（m/セル）

---

## 5. 処理フロー（main の実行順）

1. CLI引数読み取り（`--city`, `--coarse-res`, `--fine-res`）
2. 都市設定読み込み（`CITY_CONFIG`）
3. RGレイヤから解析 BBox を取得
4. UTM上で fine/coarse グリッド構築
5. DC から `BUILD_COV_0`, `BUILD_DEN_0` を算出
6. DH から `WATER_COV_0` を算出
7. GT から `ROAD_DEN_0`（近似）を算出
8. グリッド中心座標（WGS84）を計算
9. DataFrame を組み立てて CSV 出力
10. min/mean/max を標準出力

---

## 6. 関数別の詳細解説

### 6.1 `BBox`（dataclass）

役割:
- BBox を型として扱うための軽量クラス

ポイント:
- `to_tuple()` で Fiona の `bbox=` 引数に渡しやすくする

---

### 6.2 `bbox_from_layer(path, layer)`

役割:
- レイヤ全体の BBox を取得

実装:
- `fiona.open(...).bounds` をそのまま利用

注意:
- 外れ値が混ざるレイヤの BBox は分析域定義に不向き
- そのため、本スクリプトでは RG を基準に限定

---

### 6.3 `build_grid(...)`

役割:
- WGS84 BBox を UTM に投影し、10m(fine) と 30m(coarse) のグリッド情報を生成

処理要点:
- BBox 四隅を投影して UTM範囲を決定
- `fine_factor = coarse_res / fine_res` を整数で検証
- fine サイズを `fine_factor` の倍数にパディング
- `from_origin` で affine transform を作成

返り値:
- `to_utm`, `to_wgs84`, `fine`, `coarse` を辞書で返却

設計上の重要点:
- fine を coarse の整数倍に揃えることで、後段の `reshape` 集約が単純・高速になる

---

### 6.4 `_iter_geoms_in_bbox(...)`

役割:
- Fiona の `bbox=` を使って空間フィルタ付きで feature を逐次走査

利点:
- 全件ロードせず、メモリ効率を保てる

---

### 6.5 `_safe_project_geometry(geom, to_utm)`

役割:
- 不正/空ジオメトリ耐性を持つ「安全な変換関数」

処理:
- `shape(geom)` 失敗ならスキップ
- empty geometry をスキップ
- invalid なら可能な場合に `make_valid`
- UTM投影失敗もスキップ

意義:
- 測量データに混入する異常地物で処理全体が止まるのを防ぐ

---

### 6.6 `rasterize_mask_from_layer(...)`

役割:
- ベクタ（ポリゴン/ライン）を fine グリッドへ 0/1 マスク化

実装の特徴:
- `chunk_size` で分割して `rasterize` を繰り返す
- `merge_alg=MergeAlg.add` で積算後、最後に `>0` で二値化

使われ方:
- 建物被覆率、水域被覆率、道路密度近似の元データ

---

### 6.7 `aggregate_mean(fine_mask, factor)`

役割:
- fine(10m) マスクを coarse(30m) に平均集約

数式イメージ:
- `coarse_cell_value = mean(fine_cell_0_1 within 3x3)`

意味:
- 0/1 の平均は面積率（被覆率）の近似になる

---

### 6.8 `count_centroids_per_cell(...)`

役割:
- 建物ポリゴンの重心を coarse セルへ割当て、棟数をカウント

処理:
- 各地物を `_safe_project_geometry` で整形
- 重心計算
- inverse affine（`~transform`）で row/col へ変換
- 範囲内のみ加算

注意:
- 「重心がどのセルに入るか」の密度定義なので、巨大建物や境界地物の表現は粗い

---

### 6.9 `approx_road_length_m(...)`

役割:
- ラインの fine マスクから道路延長（m/セル）を近似

近似方法:
- `touchした10mセル数 * 10m`

制約:
- ラインの角度やセル内通過長を厳密反映しない
- 実務上は簡便で高速、ただし厳密長が必要なら改良対象

---

### 6.10 `grid_centers_wgs84(...)`

役割:
- coarse セル中心座標を WGS84 で返す

処理:
- affine から中心座標を計算
- `np.meshgrid` で全セル展開
- UTM->WGS84 変換

用途:
- 出力 CSV の `lon`, `lat` 列

---

## 7. 出力列の意味（研究変数として）

- `BUILD_COV_0`: 即時効果の建物被覆率（0mリング相当）
- `BUILD_DEN_0`: 即時効果の建物密度
- `WATER_COV_0`: 即時効果の水域率
- `ROAD_DEN_0`: 即時効果の道路密度（近似延長）

補足:
- 列名サフィックス `_0` は、将来の近傍リング変数（`_30_60`, `_60_90`, ...）拡張と整合

---

## 8. 実行・再現手順

前提環境:
- conda `gis-env`
- `fiona`, `shapely`, `rasterio`, `pyproj`, `numpy`, `pandas`

実行コマンド:

```bash
python -m src.analysis.calc_urban_params --city hanoi
```

成功時チェック:
- `data/csv/analysis/urban_params_hanoi.csv` が生成される
- 標準出力に行数と `min/mean/max` が表示される

---

## 9. よくあるエラーと原因

### 9.1 `ModuleNotFoundError: fiona`

原因:
- 実行Pythonが `gis-env` ではない

対処:
- フルパス Python で実行

### 9.2 空ジオメトリ由来の GEOS エラー

原因:
- 入力地物の empty / invalid geometry

対処:
- `_safe_project_geometry` でスキップ（現実装で対応済み）

### 9.3 レイヤ名不一致

原因:
- GPKG の layer 名と `CITY_CONFIG` が不一致

対処:
- `fiona.listlayers(path)` で実名確認して設定更新

---

## 10. 実装上の近似・限界

- `ROAD_DEN_0` は厳密線長ではなく近似値
- `BUILD_DEN_0` は重心カウントで、面積重みではない
- 解析範囲が BBox のため、将来は凸包/ポリゴンマスク化の余地あり
- `CITY_CONFIG["osaka"]` はプレースホルダで、実データ設定未完了

---

## 11. 改良ロードマップ（優先度順）

1. 道路密度の厳密化
- 30mセルポリゴンと道路ラインの交差長を直接計算する

2. 建物密度の定義拡張
- 重心カウントに加え、建物面積密度（m2/セル）も追加

3. 分析域マスクの高度化
- RGベースのポリゴンマスク（BBoxではなく実形状）

4. 品質管理列の追加
- 各セルの有効地物数、欠損フラグ、外れ値フラグを出力

5. 都市設定の一般化
- `CITY_CONFIG` を YAML/JSON 化して都市追加を容易にする

---

## 12. コード読解の最短ルート

初見で理解する場合は、以下順で読むと効率的です。

1. `main()` の処理順（全体像）
2. `build_grid()`（座標系とグリッド設計）
3. `rasterize_mask_from_layer()` と `aggregate_mean()`（被覆率）
4. `count_centroids_per_cell()`（建物密度）
5. `approx_road_length_m()`（道路密度近似）
6. `_safe_project_geometry()`（実運用の堅牢化）

---

## 13. 参照実装

- 実装本体: `src/analysis/calc_urban_params.py`
- 手法全体: `docs/02_methods/analysis_workflow.md`
- データ整備状況: `docs/03_results/data_preparation_status.md`
