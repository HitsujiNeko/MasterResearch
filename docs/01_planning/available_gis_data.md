# 利用可能な公開GISデータ候補

**最終更新**: 2026-07-26  
**関連ドキュメント**: [research_guide.md](research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md), [CodingRule.md](../02_methods/CodingRule.md)  
**前提知識**: RQ1-RQ3、都市構造パラメータの定義、GISデータのCRS・解像度・ライセンス差

---

## 1. 目的

本資料は、ベトナムの都市、または全球を対象に使える公開GISデータを整理し、本研究で都市構造パラメータの算出に使えるかを評価する。

評価観点は次の5点とする。

1. 都市構造を示す指標として算出に使えるか
2. ベトナムでの利用可能性があるか（空間的カバレッジ）
3. データの作成日・時期が明確であるか
4. 研究で必要な空間解像度に耐えるか
5. ライセンス等、研究・論文執筆に問題なく使用できるか

---

## 2. 結論の要点

- 道路データは `OpenStreetMap` / Geofabrik が現時点の主ソースである。
- `Microsoft GlobalMLBuildingFootprints` は建物フットプリント候補だが、Hanoi ROI 西側で明確なカバレッジ欠落が確認されたため、ROI 全域の建物主ソースとして単独採用しない。
- 建物データの主ソースとして `GlobalBuildingAtlas`（GBA）を WFS 経由で Hanoi ROI 全域から取得済み（2026-06-09）。行政区画ポリゴンクリップ済みで 3,071,511 件。Microsoft 欠落域（105.29–105.47°E）で 273,742 件（面積率 1.25%）を確認し、カバレッジ欠落問題を解消した。GBA を `Limited` シナリオの建物主ソースとして確定した。`Google Open Buildings`, `OSM building=*` は比較・妥当性確認候補として残す。
- `GHSL` と `World Settlement Footprint` は建物フットプリントの代替ではなく、粗い built-up / settlement extent の補助・妥当性確認用として扱う。
- `Limited` シナリオの建物データソースは GBA に移行済み（`config.py`）。Microsoft 時代のカバレッジ欠落問題は解消されたが、建物パラメータ（`BUILD_COV_<scale>` / `BUILD_DEN_<scale>`）の算出方法自体は別Issue（#7）で設計確定予定。
- 標高データは `FABDEM v1.2`（Copernicus DEM 派生の準DTM）を `Limited` シナリオの主採用候補とする（BSHorizon との比較で全指標最良）。
- 土地利用・人口密度・夜間光・水域（近接距離・面積率）・POI密度・不透水面率・公園近接距離の7カテゴリについて、オープンソースデータセット候補の調査を完了した。各カテゴリの候補比較・推奨方針は Section 4 のカテゴリ別詳細ドキュメントを参照。土地利用・人口密度以外は実データの取得・採用可否が未判断。
- 土地利用は `GLC_FCS30D`（30m）を主ソースとして採用済み。加えて比較候補の `Esri Sentinel-2 10m LULC` を取得し、一致度を評価した（全体一致率 0.6921・kappa 0.5155）。**不透水面（市街地）と判定される画素数は Esri が GLC の約1.97倍**で、GLC の不透水面はほぼ Esri の部分集合（GLC基準の一致率 97.96%）である。差の主因は郊外の農地と散在市街地の境界にあるが、**解像度差だけでなくクラス定義の差も含む**（GLC の Impervious surfaces は人工被覆、Esri の Built area は建造環境）。Esri は主ソースを置き換えるのではなく、**市街地・不透水面として抽出される範囲の解釈幅を確認する感度分析用**として採用する（詳細は [gis_data_lulc.md](gis_data/gis_data_lulc.md) Section 7）。
- 人口密度は `WorldPop`（居住人口・約93m・2020年）と `LandScan Global`（実効人口・約928m・2023年）を取得し、両者の値の違いを評価した。ROI 内総人口は `WorldPop 2020` が 8,441,385 人、`LandScan 2023` が 8,798,380 人。**年の違いと人口概念の違いを混同しないため比較は同年（2020年）同士で行い**、`WorldPop 2020` ÷ `LandScan 2020` の総人口比は 1.017、**セル単位の Pearson r = 0.8130**。集計レベルでは一致する一方、**平均バイアスが +23.3 人なのに中央値バイアスが +369.1 人**と乖離し、少数の都心セルで LandScan が大きく上回る（＝実効人口が都心へ集中する概念差）ことが確認された。**時間整合性では LandScan が優位**（WorldPop のベトナムは 2000-2020 年のみで Landsat 観測年 2023 に届かない）。両方を RQ1 の説明変数候補として投入し比較する方針（詳細は [gis_data_population.md](gis_data/gis_data_population.md) Section 6）。

---

## 3. 採用データ一覧

都市構造パラメータの算出候補として採用したデータを以下に示す。各データの詳細な調査結果・比較検討・注意点はカテゴリ別ドキュメント（Section 4）を参照。

なお `GLC_FCS30D` は CC BY 4.0 だが、提供元の User Guides に「科学論文で利用する場合は事前に提供者へ連絡し、謝辞または共著を検討することを推奨する」との Data Use Policy がある（詳細は [gis_data_lulc.md](gis_data/gis_data_lulc.md) Section 5.6）。

| データセット | カテゴリ | 主な用途 | 形式 | 空間解像度 | ライセンス | URL |
|---|---|---|---|---|---|---|
| OpenStreetMap / Geofabrik Vietnam extract | 道路 | 道路密度指標の算出 | `.osm.pbf`, `.gpkg` | 道路中心線（ベクタ） | ODbL | <https://download.geofabrik.de/asia/vietnam.html> |
| GlobalBuildingAtlas (GBA) v1.0.0 | 建物 | 建物面積率・建物密度・建物高さの算出 | ポリゴン（WFS / GeoJSON） | 建物ポリゴン（ベクタ） | CC BY-NC 4.0 | <https://github.com/zhu-xlab/GlobalBuildingAtlas> |
| FABDEM v1.2 | 標高（DEM） | 地形高度の算出（準DTM） | ラスタ `TIF` | 約30m（1 arc-second） | CC BY-NC-SA 4.0 | <https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn> |
| GLC_FCS30D v2（2022年） | 土地利用（LULC） | 土地利用カテゴリ別面積率の算出（主ソース） | ラスタ `TIF` | 30m | CC BY 4.0（利用時の注意は下記） | <https://zenodo.org/records/15063683> |
| Esri Sentinel-2 10m Annual LULC（2022年） | 土地利用（LULC） | 市街地・不透水面の抽出範囲の解釈幅を確認する感度分析（主ソースの代替ではない） | ラスタ `TIF`（COG） | 10m | CC BY 4.0 | <https://planetarycomputer.microsoft.com/dataset/io-lulc-annual-v02> |

---

## 4. カテゴリ別詳細ドキュメント

各データカテゴリの詳細（データ仕様・取得結果・注意点・ワークフロー・参考ソース）は以下のファイルを参照。

| カテゴリ | ファイル |
|---|---|
| 道路 | [gis_data_roads.md](gis_data/gis_data_roads.md) |
| 建物 | [gis_data_buildings.md](gis_data/gis_data_buildings.md) |
| 標高（DEM） | [gis_data_dem.md](gis_data/gis_data_dem.md) |
| 土地利用（LULC） | [gis_data_lulc.md](gis_data/gis_data_lulc.md) |
| 人口密度 | [gis_data_population.md](gis_data/gis_data_population.md) |
| 夜間光 | [gis_data_nighttime_lights.md](gis_data/gis_data_nighttime_lights.md) |
| 水域（近接距離・面積率） | [gis_data_water.md](gis_data/gis_data_water.md) |
| POI密度 | [gis_data_poi.md](gis_data/gis_data_poi.md) |
| 不透水面率 | [gis_data_impervious.md](gis_data/gis_data_impervious.md) |
| 公園近接距離 | [gis_data_park_proximity.md](gis_data/gis_data_park_proximity.md) |
