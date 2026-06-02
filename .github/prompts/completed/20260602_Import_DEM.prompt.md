---
agent: agent
---

# タスク: 標高データの導入、DEMの精度確認

## 概要
標高は、都市の空間構造や地理的特徴を理解する上で重要な要素であるため、都市構造パラメータに標高データを組み込むことが求められている。

## 背景
以前、測量GISデータから標高を抽出して、CSVに追加するタスクが完了した。本タスクとは別タスクで、測量GISデータからDEMを作成する。
本タスクでは、別タスクで生成したDEMの精度を確認するための、オープンソースの標高データ（DEM）の導入を検討する。また、本タスクで入手したオープンソースのDEMは、研究における Limited シナリオで都市構造パラメータとして利用することを想定している。


## タスク詳細
以下のStepでタスクを進める。

1. オープンソースの標高データ（DEM）を調査し、利用可能なデータセットを調査する。本プロンプトファイルに、利用可能なデータセットのリストと、それぞれの特徴を記載する。

2. 手順１でまとめたオープンソースの標高データ（DEM）を入手する。その際、データの範囲は ハノイの都市圏全体をカバーするものとする。（data\GISData\ROI\hanoi\hanoi_ROI_EPSG4326.shp を参照）

3. 測量GISデータから作成したDEMの精度を確認するため、本タスクで入手したオープンソースのDEMと比較する。このステップを行う前に、ユーザーに、測量GISデータから作成したDEMについて、以下の情報を提供するように促す。
- 測量GISデータから作成したDEMのファイルパス 
- 測量GISデータから作成したDEMのCRS
- 測量GISデータから作成したDEMの解像度
- 測量GISデータから作成したDEMの範囲

4. DEMの比較結果を本タスクの完了記録に記載する。

## 調査結果（2026-05-27）

### 利用可能な公開DEM候補

1. **Copernicus DEM GLO-30**
   - 解像度は約30m。
   - Copernicus由来の全球DEMで、GEEから直接取得できる。
   - 水域平坦化などの編集済みだが、**DSM系**のため建物・植生の高さを含む可能性がある。
   - ROI切り出しが容易で、再現性のある自動取得スクリプトを組みやすい。

2. **NASADEM**
   - 解像度は約30m。
   - SRTM再処理版で、ASTER GDEM・ICESat GLAS・PRISMを補助利用してボイド低減と精度改善が行われている。
   - 全球をカバーし、GEEから直接取得できる。
   - 取得時期は主に2000年頃で、近年の都市改変は反映しない。

3. **SRTMGL1 v003**
   - 解像度は約30m。
   - 広く使われる全球DEMで、GEEから直接取得できる。
   - 取得時期は2000年頃で、NASADEMより前処理改善が少ない基準データとみなせる。

4. **FABDEM V1-2**
   - 1 arc-second（赤道付近で約30m）。
   - Copernicus DEMをベースに**建物・森林バイアス除去**を行ったDEMで、概念的には測量由来DEMとの比較に最も近い候補。
   - 一方で、配布は大容量タイルZIP単位で、運用上は取得コストが高い。
   - 今回は実行時間制約により取得対象から外し、将来の比較候補として残す。

### 今回取得対象としたデータセット

- **取得済みDEM**:
  - Copernicus DEM GLO-30
  - NASADEM
  - SRTMGL1 v003
- **今回見送り**:
  - FABDEM V1-2
- **判断方針**:
  - 最終選定はデータソース説明だけで決めず、測量由来DEMとの比較結果も含めて総合判断する。
  - FABDEM は有力候補だが、今回ターンでは実行時間制約のため取得を見送る。


注意点：
測量GISデータから作成したDEMの範囲は、ハノイのROIより小さいが、オープンソースのDEMはハノイのROI全体をカバーする必要がある。比較の際には、測量GISデータから作成したDEMをオープンソースのDEMの範囲にクリップしてから比較することが望ましい。

データの使い分け：
- 本タスクで入手したオープンソースのDEMは、研究における Limited シナリオで都市構造パラメータとして利用することを想定している。
- 別タスクで測量GISデータから作成したDEMは、研究における Full シナリオで都市構造パラメータとして利用することを想定している。

## 入力データ・入力ファイル
-　`data\GISData\ROI\hanoi\hanoi_ROI_EPSG4326.shp`: ハノイの都市圏全体をカバーするシェープファイル。入手したDEMは、このシェープファイルの範囲をカバーする必要があり、このShpファイルの範囲でDEMをクリップする。


## 想定される成果物

- `data\GISData\DEM\{Datasource}_hanoi_dem.tif`: ハノイの都市圏全体をカバーするオープンソースのDEM。入手したDEMは、このファイルパスで保存することを想定している。{Datasource}は、利用したデータセットの名前を入れることを想定している。

- 本プロンプトファイルの完了記録。完了記録には、以下の内容を記載することを想定している。
  - 入手したオープンソースのDEMのデータセット名と特徴
  - 測量GISデータから作成したDEMのファイルパス、CRS、解像度、範囲
  - オープンソースのDEMと測量GISデータから作成したDEMの比較結果（例：平均標高の差、標高の分布の違いなど）



## 受け入れ基準
- オープンソースのDEMは、ハノイの都市圏全体をカバーしていることを確認すること。
- オープンソースのDEMと測量GISデータから作成したDEMの比較結果が、完了記録に記載されていることを確認すること。
- 完了記録には、入手したオープンソースのDEMのデータセット名と特徴、測量GISデータから作成したDEMのファイルパス、CRS、解像度、範囲、オープンソースのDEMと測量GISデータから作成したDEMの比較結果が記載されていることを確認すること。

## 関連タスク
- `.github/prompts/completed/20260513_convert_elevation_to_CSV.prompt.md`: 測量由来 `merge_DH.gpkg` から標高点CSVを作成した前提タスク。Fullシナリオ側のDEM作成準備に相当する。
- `.github/prompts/active/consider_building_GISData.prompt.md`: Limitedシナリオで使う公開GIS整備タスク。今回取得した公開DEMも Limited シナリオ向け入力として整合を取る。

## 関連ファイル
- `src/gee/download_open_dem.py`: 公開DEMをGEEからROIクリップしてGeoTIFF保存する取得スクリプト。
- `src/analysis/compare_dem_rasters.py`: 測量由来DEMと公開DEMを同一グリッドで比較するスクリプト。
- `data/GISData/DEM/copernicus_glo30_hanoi_dem_clipped.tif`: ROIポリゴンで真にクリップした Copernicus DEM。
- `data/GISData/DEM/copernicus_glo30_hanoi_dem_clipped_metadata.json`: Copernicus DEM の作成日情報・CRS・解像度・範囲・基本統計の記録。
- `data/GISData/DEM/nasadem_hanoi_dem.tif`: ROIポリゴンで真にクリップした NASADEM。
- `data/GISData/DEM/srtmgl1_hanoi_dem.tif`: ROIポリゴンで真にクリップした SRTMGL1 v003。

## 参考
- `https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30`
- `https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001`
- `https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003`
- `https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn`

---

共通ルールは以下のファイルを参照すること  
.github\copilot-instructions.md

---

## 完了記録

completed に移す前に、**必ず** この欄を更新すること。

**完了日**: 2026-06-02  
**ステータス**: 一部完了（FABDEM比較追加・DEM選定更新済み）

### 実施内容
- 公開DEM候補（Copernicus DEM GLO-30 / NASADEM / SRTMGL1 / FABDEM V1-2）を調査し、本prompt内へ整理した。
- `src/gee/download_open_dem.py` を追加し、作成日系メタデータを記録しつつ、ROIポリゴンで真にクリップした公開DEMを自動取得できるようにした。
- `src/analysis/compare_dem_rasters.py` を追加し、測量由来DEMと公開DEMの差分比較をJSON/GeoTIFFで記録できるようにした。
- Copernicus DEM GLO-30 / NASADEM / SRTMGL1 v003 を取得し、ROIポリゴンで真にクリップしたGeoTIFFとメタデータJSONを保存した。
- FABDEM は取得処理を試行したが、実行時間制約により本ターンでは見送った。
- 比較対象の測量由来DEM `data/GISData/DEM/BSHorizon/DEM_10m_m05_a100_M200.tif` を基準DEMとして、Copernicus / NASADEM / SRTMGL1 の3種類との比較を実行した。
- 比較結果のJSON・差分GeoTIFF・比較一覧CSVを `data/GISData/DEM/comparison/` に保存した。

### 成果物
- `data/GISData/DEM/copernicus_glo30_hanoi_dem_clipped.tif`
- `data/GISData/DEM/copernicus_glo30_hanoi_dem_clipped_metadata.json`
- `data/GISData/DEM/nasadem_hanoi_dem.tif`
- `data/GISData/DEM/nasadem_hanoi_dem_metadata.json`
- `data/GISData/DEM/srtmgl1_hanoi_dem.tif`
- `data/GISData/DEM/srtmgl1_hanoi_dem_metadata.json`
- `data/GISData/DEM/comparison/bshorizon_vs_copernicus_summary.json`
- `data/GISData/DEM/comparison/bshorizon_vs_nasadem_summary.json`
- `data/GISData/DEM/comparison/bshorizon_vs_srtmgl1_summary.json`
- `data/GISData/DEM/comparison/bshorizon_public_dem_comparison_overview.csv`

### 関連更新
- `.github/prompts/active/Import_DEM.prompt.md`
- `src/gee/download_open_dem.py`
- `src/analysis/compare_dem_rasters.py`

### 確認内容
- Copernicus / NASADEM / SRTMGL1 の3種類について、ROIポリゴンで真にクリップしたGeoTIFFが正常生成されることを確認した。
- 3種類ともメタデータJSONに `dataset_created_date` と `source_observation_period` を記録した。
- 3種類とも出力DEMのCRSが `EPSG:4326`、解像度が約 `0.0002694946` 度、`nodata=-9999.0` であることを確認した。
- 3種類とも `clip_method = polygon mask with crop=true` となっていることを確認した。
- BSHorizon DEM の基本情報は `CRS=EPSG:5897`、`解像度=10m`、`範囲=[581495.0, 2321995.0, 589505.0, 2333005.0]`、`nodata=-9999.0` であることを確認した。
- BSHorizon を基準に比較した結果、誤差指標では `NASADEM` が最も近く、`RMSE=4.8549m`, `MAE=3.8518m`, `mean_difference=-3.0410m` だった。
- `Copernicus DEM GLO-30` は `RMSE=6.9933m`, `MAE=5.6739m`, `mean_difference=-5.4801m`、`SRTMGL1 v003` は `RMSE=6.2397m`, `MAE=5.2208m`, `mean_difference=-4.9496m` だった。
- 相関係数は `Copernicus=0.4766`, `NASADEM=0.4629`, `SRTMGL1=0.4480` で、3種類とも中程度以下の一致にとどまった。
- `difference_definition = base_dem - target_dem` なので、平均差が負であることは公開DEMの方が BSHorizon より高めであることを示す。
- BSHorizon DEM は河川部分もカバーしているため、水面付近の低標高セルが比較結果に含まれる。公開DEM側の水域処理や表層高の性質が、平均差と分散差に影響している可能性がある。

### 追加実施内容（2026-06-02）
- TanDEM-X・ASTER GDEM v3・FABDEM v1.2 を追加候補として調査し、`docs/01_planning/dem_selection_guide.md` に詳細な特性比較を記録した。
- TanDEM-Xは Copernicus GLO-30 の原データと同一ミッションのため追加取得不要と判断。ASTER GDEM v3はベトナムのモンスーン気候により不適と判断。
- FABDEM v1.2 のライセンス（CC BY-NC-SA 4.0）を公式ページで確認し、修士論文・学術研究での利用可能性を確認した。
- `download_open_dem.py` をBristol大学直接ダウンロードからGEE経由取得に変更し、FABDEM を GEE（`projects/sat-io/open-datasets/FABDEM`）から取得した。
- `compare_dem_rasters.py` で BSHorizon vs FABDEM の比較を実施。RMSE=3.88m, MAE=3.20m, 相関係数=0.603 と、全4候補中で最も良好な精度を確認した。
- `data/GISData/DEM/comparison/bshorizon_vs_fabdem_summary.json` および差分GeoTIFF、比較一覧CSVへFABDEM行を追記した。
- Limited シナリオ用DEMの暫定採用を NASADEM から **FABDEM v1.2** に更新した。

### 追加成果物（2026-06-02）
- `data/GISData/DEM/fabdem_hanoi_dem.tif`
- `data/GISData/DEM/fabdem_hanoi_dem_metadata.json`
- `data/GISData/DEM/comparison/bshorizon_vs_fabdem_summary.json`
- `data/GISData/DEM/comparison/bshorizon_vs_fabdem_diff.tif`
- `docs/01_planning/dem_selection_guide.md`（新規作成）

### 全4候補の比較結果（BSHorizon基準、差分 = BSHorizon - 公開DEM）

| DEM | RMSE (m) | MAE (m) | 平均差 (m) | 相関係数 |
|---|---|---|---|---|
| **FABDEM v1.2** | **3.88** | **3.20** | -3.00 | **0.603** |
| NASADEM | 4.85 | 3.85 | -3.04 | 0.463 |
| SRTMGL1 v003 | 6.24 | 5.22 | -4.95 | 0.448 |
| Copernicus GLO-30 | 6.99 | 5.67 | -5.48 | 0.477 |

### 未完了・引き継ぎ事項
- BSHorizon は河川部分を含むため、必要に応じて将来は水域マスクを作成し、非水域のみの比較も追加検証する。
- FABDEM の論文使用時は必ず帰属文を記載すること: "FABDEM is produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved."
- `data/GISData/DEM/copernicus_glo30_hanoi_dem.tif` は初回取得時の矩形出力が別プロセスによりロックされており置換できなかったため、真クリップ版は `_clipped` 付きファイル名で保存している。
