# 利用可能な公開GISデータ候補

**最終更新**: 2026-06-24  
**関連ドキュメント**: [research_guide.md](research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md), [CodingRule.md](../02_methods/CodingRule.md)  
**前提知識**: RQ1-RQ3、都市構造パラメータの定義、GISデータのCRS・解像度・ライセンス差

---

## 1. 目的

本資料は、ベトナムの都市、または全球を対象に使える公開GISデータを整理し、本研究で都市構造パラメータの算出に使えるかを評価する。

評価観点は次の4点とする。

1. 道路・建物の抽出に使えるか
2. ベトナムでの利用可能性があるか
3. 更新頻度と再現性が十分か
4. 研究で必要な空間解像度に耐えるか

---

## 2. 結論の要点

- 道路データは `OpenStreetMap` / Geofabrik が現時点の主ソースである。
- `Microsoft GlobalMLBuildingFootprints` は建物フットプリント候補だが、Hanoi ROI 西側で明確なカバレッジ欠落が確認されたため、ROI 全域の建物主ソースとして単独採用しない。
- 建物データの主ソースとして `GlobalBuildingAtlas`（GBA）を WFS 経由で Hanoi ROI 全域から取得済み（2026-06-09）。行政区画ポリゴンクリップ済みで 3,071,511 件。Microsoft 欠落域（105.29–105.47°E）で 273,742 件（面積率 1.25%）を確認し、カバレッジ欠落問題を解消した。GBA を `Limited` シナリオの建物主ソースとして確定した。`Google Open Buildings`, `OSM building=*` は比較・妥当性確認候補として残す。
- `GHSL` と `World Settlement Footprint` は建物フットプリントの代替ではなく、粗い built-up / settlement extent の補助・妥当性確認用として扱う。
- `Limited` シナリオの建物データソースは GBA に移行済み（`config.py`）。Microsoft 時代のカバレッジ欠落問題は解消されたが、建物パラメータ（`BUILD_COV_<scale>` / `BUILD_DEN_<scale>`）の算出方法自体は別Issue（#7）で設計確定予定。

---

## 3. 候補データ一覧

| データセット | 主な用途 | 形式 | 範囲 | 信頼性・更新メモ | URL | 適性評価 |
|---|---|---|---|---|---|---|
| OpenStreetMap / Geofabrik Vietnam extract | 道路、建物、土地利用 | `.osm.pbf`, `.gpkg`, `.shp.zip` | Vietnam 全域、全球は Planet | コミュニティ編集型のため品質は地域差がある。Geofabrik extract は再現的に取得しやすい。 | https://download.geofabrik.de/asia/vietnam.html | 道路の主ソース。建物は Microsoft 欠落域の比較候補として QA 必須。 |
| Microsoft GlobalMLBuildingFootprints | 建物フットプリント、建物密度 | 線形 GeoJSON を含む `.csv.gz`、国別・quadkey 分割 | 全球 | 1.4B 棟規模の全球データで、2014-2024 の衛星画像から抽出。2026-02-03 まで更新履歴あり。機械生成なので誤検出・地域差がある。 | https://github.com/microsoft/GlobalMLBuildingFootprints | Hanoi ROI 西側の欠落を確認済み。カバレッジ制限付き候補であり、単独の ROI 全域主ソースにはしない。 |
| Google Open Buildings V3 Polygons | 建物フットプリント、建物密度 | Earth Engine FeatureCollection、ダウンロードデータ | Africa, South Asia, South-East Asia, Latin America, Caribbean | 1.8B building detections、58M km2、V3。建物ポリゴン、confidence、Plus Code を含む。 | https://sites.research.google/open-buildings | 東南アジアを含むため、Microsoft 欠落域の第一比較候補。Hanoi ROI で取得可否と confidence 閾値の QA が必要。 |
| Google Open Buildings 2.5D Temporal | 建物存在、fractional count、高さの時系列 | Earth Engine ImageCollection、ラスタ | Africa, South Asia, South-East Asia, Latin America, Caribbean | 2016-2023 年の年次データ。4m effective spatial resolution。 | https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1 | 個別ポリゴンの代替ではなく、建物存在・高さ・時系列の補助候補。`BUILD_DEN_<scale>` との定義差に注意。 |
| GlobalBuildingAtlas | 建物ポリゴン、高さ、LoD1 3D | ポリゴン、派生 GeoJSON、WFS、HuggingFace 配布 | 全球 | v1.0.0（2025年11月）。2.75億棟規模。WFS（`lod1_global`）はBBOX指定でHanoi ROIから直接取得可能。高さ属性あり（ML推定）。下地はGoogle Open Buildings由来。ライセンス: ODbLポリゴン＋CC BY-NC 4.0（LoD1・高さ）。学術研究用途はCC BY-NC 4.0で可。 | https://github.com/zhu-xlab/GlobalBuildingAtlas | **✅ 取得完了（2026-06-09）**。行政区画ポリゴンクリップ済みで3,071,511件取得。Microsoft欠落域（105.29–105.47°E）で273,742件（面積率1.25%）を確認。`height`（ML推定）・`region:VNM`・`source:google`属性含む。`Limited`シナリオの建物主ソースとして採用。出力: `data/output/open_gis/hanoi_gba_buildings.gpkg`。**WFS注意**: 1,554タイル取得でIPレート制限（48h+ブロック）が発生。再取得時はHuggingFace（`zhu-xlab/GBA.LoD1`、タイル`e105_n25_e110_n20`、約1.78GB GeoJSON）によるバルクDLを推奨。 |
| GHSL Data Package 2023 / GHS-BUILT | 粗い建て込み、都市化の補助指標 | ラスタ `TIF`（ZIP 配布） | 全球 | GHSL は公開・無料データで、built-up / population / settlement model を提供する。更新頻度は irregular。建物の輪郭ではなく、粗い built-up 基盤として使うのが適切。 | https://data.jrc.ec.europa.eu/collection/ghsl/ | 建物数の代替ではないが、都市化度や built-up 比率の補助変数に有効。 |
| World Settlement Footprint 2015 / 2019 / Evolution | 住宅地・市街地の extent | ラスタ `TIF` | 全球 | WSF2015 v2 は 10m 解像度の全球 settlement mask。DLR の公式ページで 2015, 2019, Evolution, 3D が公開されている。建物や道路そのものではなく、settlement extent の指標。 | https://geoservice.dlr.de/web/maps/eoc%3Awsf | 都市化の広がりや市街地マスクの補助に有用。道路・建物の代替にはならない。 |

---

## 4. カテゴリ別詳細ドキュメント

各データカテゴリの詳細（データ仕様・取得結果・注意点・ワークフロー・参考ソース）は以下のファイルを参照。

| カテゴリ | ファイル |
|---|---|
| 道路 | [gis_data_roads.md](gis_data/gis_data_roads.md) |
| 建物 | [gis_data_buildings.md](gis_data/gis_data_buildings.md) |
| 標高（DEM） | [gis_data_dem.md](gis_data/gis_data_dem.md) |
