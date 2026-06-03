# 利用可能な公開GISデータ候補

**最終更新**: 2026-06-03  
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
- 建物データは `Google Open Buildings`, `OSM building=*`, `GlobalBuildingAtlas` を比較候補に追加し、ROI 全域カバレッジ、建物数、面積率、ライセンス、取得再現性を QA してから採用する。
- `GHSL` と `World Settlement Footprint` は建物フットプリントの代替ではなく、粗い built-up / settlement extent の補助・妥当性確認用として扱う。
- 現在の `Limited` シナリオでは、Microsoft 由来の `BUILD_COV_0` / `BUILD_DEN_0` を「建物が存在しない」ではなく「Microsoft データの有効範囲外の可能性がある」と区別する必要がある。

---

## 3. 候補データ一覧

| データセット | 主な用途 | 形式 | 範囲 | 信頼性・更新メモ | URL | 適性評価 |
|---|---|---|---|---|---|---|
| OpenStreetMap / Geofabrik Vietnam extract | 道路、建物、土地利用 | `.osm.pbf`, `.gpkg`, `.shp.zip` | Vietnam 全域、全球は Planet | コミュニティ編集型のため品質は地域差がある。Geofabrik extract は再現的に取得しやすい。 | https://download.geofabrik.de/asia/vietnam.html | 道路の主ソース。建物は Microsoft 欠落域の比較候補として QA 必須。 |
| Microsoft GlobalMLBuildingFootprints | 建物フットプリント、建物密度 | 線形 GeoJSON を含む `.csv.gz`、国別・quadkey 分割 | 全球 | 1.4B 棟規模の全球データで、2014-2024 の衛星画像から抽出。2026-02-03 まで更新履歴あり。機械生成なので誤検出・地域差がある。 | https://github.com/microsoft/GlobalMLBuildingFootprints | Hanoi ROI 西側の欠落を確認済み。カバレッジ制限付き候補であり、単独の ROI 全域主ソースにはしない。 |
| Google Open Buildings V3 Polygons | 建物フットプリント、建物密度 | Earth Engine FeatureCollection、ダウンロードデータ | Africa, South Asia, South-East Asia, Latin America, Caribbean | 1.8B building detections、58M km2、V3。建物ポリゴン、confidence、Plus Code を含む。 | https://sites.research.google/open-buildings | 東南アジアを含むため、Microsoft 欠落域の第一比較候補。Hanoi ROI で取得可否と confidence 閾値の QA が必要。 |
| Google Open Buildings 2.5D Temporal | 建物存在、fractional count、高さの時系列 | Earth Engine ImageCollection、ラスタ | Africa, South Asia, South-East Asia, Latin America, Caribbean | 2016-2023 年の年次データ。4m effective spatial resolution。 | https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1 | 個別ポリゴンの代替ではなく、建物存在・高さ・時系列の補助候補。`BUILD_DEN_0` との定義差に注意。 |
| GlobalBuildingAtlas | 建物ポリゴン、高さ、LoD1 3D の候補 | ポリゴン、派生 GeoJSON、WFS、HuggingFace 配布 | 全球 | v1.0.0（2025年11月）。2.75億棟規模。WFS（`lod1_global`）はBBOX指定でHanoi ROIから直接取得可能。高さ属性あり（ML推定）。下地はGoogle Open Buildings由来。ライセンス: ODbLポリゴン＋CC BY-NC 4.0（LoD1・高さ）。学術研究用途はCC BY-NC 4.0で可。 | https://github.com/zhu-xlab/GlobalBuildingAtlas | **WFS動作確認済み（2026-06-03）**。Hanoi ROI西側（Microsoft欠落域: 105.30-105.40°E）でも建物データを確認。`height`・`region:VNM`・`source:google`を含む。建物高さが必要な場合の第一候補。 |
| GHSL Data Package 2023 / GHS-BUILT | 粗い建て込み、都市化の補助指標 | ラスタ `TIF`（ZIP 配布） | 全球 | GHSL は公開・無料データで、built-up / population / settlement model を提供する。更新頻度は irregular。建物の輪郭ではなく、粗い built-up 基盤として使うのが適切。 | https://data.jrc.ec.europa.eu/collection/ghsl/ | 建物数の代替ではないが、都市化度や built-up 比率の補助変数に有効。 |
| World Settlement Footprint 2015 / 2019 / Evolution | 住宅地・市街地の extent | ラスタ `TIF` | 全球 | WSF2015 v2 は 10m 解像度の全球 settlement mask。DLR の公式ページで 2015, 2019, Evolution, 3D が公開されている。建物や道路そのものではなく、settlement extent の指標。 | https://geoservice.dlr.de/web/maps/eoc%3Awsf | 都市化の広がりや市街地マスクの補助に有用。道路・建物の代替にはならない。 |

---

## 4. 使い分けの提案

### 4.1 道路

道路ネットワークは `OpenStreetMap` を第一候補とする。`highway=*` タグを使えば道路種別を抽出できるが、地区ごとに欠測や属性のばらつきがあるため、道路密度や道路近接距離は必ず欠測確認を行う。

Hanoi ROI については、Geofabrik の Vietnam extract から `highway IS NOT NULL` の道路ラインを抽出した `data/output/open_gis/hanoi_osm_roads.gpkg` を利用候補とする。今回の抽出結果では、道路ラインは `194,485` 件、ジオメトリ型は `MultiLineString` であり、道路密度指標の算出に利用できる状態である。

- 主用途: `ROAD_DEN_0` などの道路密度指標の算出
- 補助用途: 道路近接距離、主要道路と生活道路の粗い区分、都市構造の説明変数作成
- 主な利用列: `highway`, `name`, `z_order`, `other_tags`, `geometry`

ただし、現段階では道路中心線の存在を使った密度指標を主用途とし、車線数や幅員のような精密な道路仕様の代替としては扱わない方が妥当である。

### 4.2 建物

建物面積率や建物密度は、単一データを即採用せず、Microsoft / Google Open Buildings / OSM / GlobalBuildingAtlas を比較して決める。特に Hanoi ROI では Microsoft の西側欠落が確認されたため、Microsoft のゼロ値を建物不存在として扱ってはならない。

### 4.2.1 Microsoft GlobalMLBuildingFootprints の確認結果

Hanoi ROI で `Microsoft GlobalMLBuildingFootprints` を取得した結果、次の問題を確認した。

- ROI bbox: `105.288125, 20.564469, 106.020051, 21.385222`
- Microsoft 建物 bbox: `105.468713, 20.566427, 106.002608, 21.384685`
- ROI 西側の `105.288E` から概ね `105.469E` までに建物データがほぼ存在しない。
- 欠落境界は quadkey 境界の `105.46875E` と整合する。
- 出力済み建物数は `1,065,629` 件だが、候補 west-side quadkey は `source_feature_count > 0` に対して `matched_feature_count = 0` であり、単純な「候補タイル未選択」だけでは説明しにくい。
- 既存 CSV の経度ビン確認でも、`105.28E` から `105.45E` 付近までは `BUILD_COV_0` / `BUILD_DEN_0` がほぼゼロだった。

このため、Microsoft は「Hanoi 中心部から東側に強い建物データ」としては利用できる可能性があるが、ROI 全域の `BUILD_COV_0` / `BUILD_DEN_0` を代表するデータとしては不十分である。

### 4.2.2 代替建物データの優先順位（2026-06-03 更新）

WFS動作確認・カバレッジ検証の結果、比較優先順位を次のとおり更新する。

#### 候補比較表

| 項目 | GlobalBuildingAtlas (GBA) | Google Open Buildings V3 | OSM building=* |
|---|---|---|---|
| Hanoi ROI全域カバレッジ | ✅ WFSで確認済み | ✅ Vietnam明記 | 要QA |
| Microsoft欠落域（西側）対応 | ✅ 105.30-105.40°Eで確認済み | ✅ 東南アジア対応 | 要QA |
| 建物高さ情報 | ✅ あり（ML推定、RMSE未確認） | ❌ なし（V3 polygon） | △ 一部のみ |
| ライセンス | CC BY-NC 4.0（学術OK） | CC BY 4.0（最も寛容） | ODbL |
| アクセス方法 | WFS・BBOX指定で直接取得可 | gsutil / Colab ノートブック | Geofabrik（取得済み） |
| 下地データ | Google Open Buildings 由来 | — | コミュニティ編集 |
| 備考 | WFSが大域クエリでタイムアウトする可能性あり。ページング取得が必要 | 建物高さはV3ではなく2.5D Temporalで別途取得 | 品質は地域差が大きい |

#### 優先順位

1. `GlobalBuildingAtlas` via WFS: **建物高さが必要な場合の第一候補**。WFSでHanoi ROIをBBOX指定して直接取得可能。Microsoft欠落域でのカバレッジを確認済み。CC BY-NC 4.0（学術研究用途は可）。取得スクリプトを新規作成する。
2. `Google Open Buildings V3 Polygons`: ライセンスがより寛容（CC BY 4.0）。建物高さは不要で面積・密度のみ算出する場合の代替候補。confidence閾値の感度分析が必要。
3. `OSM building=*`: Geofabrik Vietnam extract から追加取得でき、道路と同一ソースで再現性が高い。コミュニティ整備状況に依存するため、建物密度の空間偏りを QA する。
4. `Google Open Buildings 2.5D Temporal`, `GHSL`, `WSF`: 個別フットプリントではなく、built-up / building presence / height の補助変数または妥当性確認に使う。

### 4.2.3 当面の Limited シナリオ方針

Limited では、建物データが確定するまで次のいずれかを選ぶ。

- Microsoft の有効範囲に分析対象を限定し、`DATA_SOURCE` とカバレッジマスクで範囲制限を明示する。
- Google Open Buildings または OSM 建物を取得し、Microsoft と比較した上で ROI 全域の建物主ソースを差し替える。
- Microsoft / Google / OSM のいずれも単独で不十分な場合は、重複除去ルールを定義したハイブリッド建物データを作る。

どの場合も、`BUILD_COV_0 = 0` と `BUILD_DEN_0 = 0` を「建物なし」と解釈する前に、そのセルが建物データの有効カバレッジ内かを確認する。

### 4.3 粗い都市化指標

`GHSL` と `WSF` は、建物輪郭の代替ではなく、粗い built-up 比率や settlement extent の比較用に向いている。RQ2 のスケール比較や、RQ3 のデータ制約シナリオの補助説明変数として使いやすい。

---

## 5. 本研究への適合性評価

### 5.1 採用候補

- `OpenStreetMap` は道路パラメータの主ソースとして採用候補。
- `Microsoft GlobalMLBuildingFootprints` はカバレッジ制限付き建物候補。Hanoi ROI 全域の単独主ソースにはしない。
- `Google Open Buildings V3 Polygons` は Microsoft 欠落域を補えるか確認する第一候補。
- `OSM building=*` は再現性の高い比較候補。
- `GlobalBuildingAtlas` は建物高さや LoD1 を含む将来拡張・比較候補。
- `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` は補助変数・妥当性確認用の採用候補。

### 5.2 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも道路・建物の完全性を保証しない。
- `OSM` の Hanoi ROI 道路抽出結果は道路密度指標には利用可能だが、道路種別や詳細属性の完全性は別途 QA が必要である。
- `Microsoft` は全球対応だが、Hanoi ROI では西側欠落が確認されたため、ROI 全域の建物ゼロ値をそのまま解釈してはならない。
- `Microsoft` の `height_m` と `confidence` は地域や更新時期によって未提供の場合があり、Hanoi ROI の今回取得結果では `-1` が入っていたため、属性値の直接利用は避ける。
- `Google Open Buildings` は confidence 閾値により建物数と面積率が変わるため、閾値感度分析を行う。
- `GlobalBuildingAtlas` は高さ・3D を扱える可能性がある一方、ライセンス条件とデータ取得経路の整理を先に行う必要がある。
- `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` は建物ポリゴンそのものではなく、`BUILD_DEN_0` と同じ定義ではない。
- いずれの候補も、測量データの代替真値ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 6. 推奨ワークフロー（2026-06-03 更新）

1. `OpenStreetMap` で道路ネットワークを整備する。
2. Microsoft 建物データのカバレッジ欠落を QA 結果として固定し、現行 `hanoi_microsoft_buildings.gpkg` の有効範囲を明示する（保留扱い確定）。
3. **`GlobalBuildingAtlas` を WFS で Hanoi ROI（BBOX: 105.288, 20.564, 106.020, 21.385）から取得する**。取得スクリプトを `src/preprocessing/fetch_gba_buildings_hanoi.py` として作成し、ページング処理で全件取得する。
4. GBA 取得後、Microsoft 欠落域（105.29–105.47°E）での建物数・面積率を比較し、カバレッジ改善を定量確認する。
5. 必要に応じて `Google Open Buildings V3 Polygons` を Geofabrik の代替または補完データとして取得し、GBA と比較する。
6. Geofabrik Vietnam extract から `building=*` を抽出し、GBA / Google と密度・面積率を比較する。
7. `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` で built-up / building presence の補助指標を作る。
8. 各候補について欠測率、重複率、空間カバレッジ、建物数、建物面積率を同一 ROI グリッドで比較する。
9. 採用可否を [analysis_workflow.md](../02_methods/analysis_workflow.md) と [calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md) に反映する。

---

## 7. 参考ソース

- OpenStreetMap Wiki, Downloading data: https://wiki.openstreetmap.org/wiki/Downloading_data
- OpenStreetMap Wiki, Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Geofabrik Vietnam extract: https://download.geofabrik.de/asia/vietnam.html
- Microsoft GlobalMLBuildingFootprints: https://github.com/microsoft/GlobalMLBuildingFootprints
- Google Open Buildings: https://sites.research.google/open-buildings
- Google Open Buildings V3 Polygons: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons
- Google Open Buildings 2.5D Temporal: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1
- GlobalBuildingAtlas: https://github.com/zhu-xlab/GlobalBuildingAtlas
- GlobalBuildingAtlas paper: https://essd.copernicus.org/articles/17/6647/2025/
- GHSL Data Package 2023 / GHS-BUILT: https://ghsl.jrc.ec.europa.eu/documents/GHSL_data_access.pdf
- GHSL collection landing page: https://data.jrc.ec.europa.eu/collection/ghsl/
- World Settlement Footprint 2015: https://geoservice.dlr.de/web/maps/eoc%3Awsf
