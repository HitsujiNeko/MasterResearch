# 利用可能な公開GISデータ候補

**最終更新**: 2026-04-09  
**関連ドキュメント**: [research_guide.md](research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [CodingRule.md](../02_methods/CodingRule.md)  
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

- 道路データは `OpenStreetMap` が最有力である。
- 建物フットプリントは `Microsoft GlobalMLBuildingFootprints` が有力な全球候補である。
- 粗い建て込み指標や整合チェックには `GHSL` と `World Settlement Footprint` が有効である。
- ただし、どの候補も「Hanoi 全域で高品質に完結する単独データ」ではない。
- 実運用では、`OSM` を道路の主ソース、`Microsoft` を建物の主ソース、`GHSL` / `WSF` を補助ソースとして組み合わせるのが妥当である。

---

## 3. 候補データ一覧

| データセット | 主な用途 | 形式 | 範囲 | 信頼性・更新メモ | URL | 適性評価 |
|---|---|---|---|---|---|---|
| OpenStreetMap / Geofabrik Vietnam extract | 道路、建物、土地利用 | `.osm.pbf`, `.gpkg`, `.shp.zip` | Vietnam 全域、全球は Planet | Geofabrik の Vietnam extract は 2026-04-07 時点で最新ファイルが公開され、`vietnam-latest.osm.pbf` は 2026-04-07T20:20:49Z まで反映されていた。コミュニティ編集型のため品質は地域差がある。 | https://download.geofabrik.de/asia/vietnam.html | 道路の主ソースとして最有力。建物も使えるが、密度や欠測の QA が必須。 |
| Microsoft GlobalMLBuildingFootprints | 建物フットプリント、建物密度 | 線形 GeoJSON を含む `.csv.gz`、国別・quadkey 分割 | 全球 | 1.4B 棟規模の全球データで、2014-2024 の衛星画像から抽出。2026-02-03 まで更新履歴あり。機械生成なので誤検出・地域差がある。 | https://github.com/microsoft/GlobalMLBuildingFootprints | 建物面積率・建物密度の主候補。ただし Vietnam の個別カバレッジは事前確認が必要。 |
| GlobalBuildingAtlas | 建物ポリゴン、高さ、LoD1 3D の候補 | ポリゴン、派生 GeoJSON、WFS、HuggingFace 配布 | 全球 | 建物ポリゴンに加えて高さや LoD1 を扱える点が強い。一方で、配布経路と利用ライセンスが複数に分かれ、初期導入が複雑である。README では CRS の扱いにも注意が必要とされている。 | https://github.com/zhu-xlab/GlobalBuildingAtlas | 高さや 3D を使う将来拡張には有望だが、現段階の建物被覆率・建物密度算出には Microsoft より導入負荷が高い。 |
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

建物面積率や建物密度は `Microsoft GlobalMLBuildingFootprints` を第一候補とする。`OSM` の `building=*` も補助候補だが、更新密度と整備状態は地域差が大きい。

### 4.2.1 Microsoft と GlobalBuildingAtlas の比較提案

現時点では、建物データの主候補は `Microsoft GlobalMLBuildingFootprints` とする。  
`GlobalBuildingAtlas` は、建物高さや LoD1 3D を使いたくなった場合の補助候補として扱うのが妥当である。

理由は次のとおりである。

- 現在の研究で優先したいのは、建物被覆率や建物密度を安定して作れる建物フットプリントである。
- `Microsoft` は建物フットプリントを主目的としたデータであり、現段階の RQ3 / Limited シナリオに直結しやすい。
- `GlobalBuildingAtlas` は高さや LoD1 まで視野に入る点で魅力がある一方、配布経路、生成手順、ライセンスの整理が相対的に複雑である。
- 既存の研究フローでは、まず Hanoi ROI で建物ポリゴンを取得して建物面積率・建物密度を評価することが優先であり、その用途には `Microsoft` の方が導入しやすい。

したがって、当面の方針は次のとおりとする。

- 主採用: `Microsoft GlobalMLBuildingFootprints`
- 補助候補: `GlobalBuildingAtlas`
- 将来拡張: 建物高さや LoD1 3D モデルが必要になった場合に `GlobalBuildingAtlas` の再検討を行う

### 4.2.2 Hanoi ROI 取得結果を踏まえた注意点

Hanoi ROI で `Microsoft GlobalMLBuildingFootprints` を取得し、QGIS 上で確認した範囲では、建物ポリゴンのクリップ結果は概ね良好であった。一方で、属性値の利用には注意が必要である。

- `height_m = -1` は低い建物を意味する値ではなく、高さ推定が未提供であることを示すプレースホルダである。
- `confidence = -1` も低信頼度を意味する値ではなく、信頼度属性が未提供である既存データに対するプレースホルダである。
- そのため、Hanoi ROI の今回取得結果では、建物形状は利用可能だが、`height_m` と `confidence` をそのまま分析変数として使うのは適切ではない。

また、このデータは衛星・航空画像から機械学習で推定された建物フットプリントであり、測量や行政台帳のような厳密な真値ではない。特に高密度市街地では過検出や欠落が残る可能性があるため、当面の用途は建物面積率、建物密度、建物分布マスクに限定して扱うのが妥当である。

### 4.3 粗い都市化指標

`GHSL` と `WSF` は、建物輪郭の代替ではなく、粗い built-up 比率や settlement extent の比較用に向いている。RQ2 のスケール比較や、RQ3 のデータ制約シナリオの補助説明変数として使いやすい。

---

## 5. 本研究への適合性評価

### 5.1 採用候補

- `OpenStreetMap` は道路パラメータの主ソースとして採用候補。
- `Microsoft GlobalMLBuildingFootprints` は建物パラメータの主ソースとして採用候補。
- `GlobalBuildingAtlas` は建物高さや LoD1 を含む将来拡張用の補助候補。
- `GHSL` と `WSF` は補助変数・妥当性確認用の採用候補。

### 5.2 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも道路・建物の完全性を保証しない。
- `OSM` の Hanoi ROI 道路抽出結果は道路密度指標には利用可能だが、道路種別や詳細属性の完全性は別途 QA が必要である。
- `Microsoft` は全球対応だが、国や時期によってカバレッジが異なるため、Vietnam の実カバレッジ確認が必要である。
- `Microsoft` の `height_m` と `confidence` は地域や更新時期によって未提供の場合があり、Hanoi ROI の今回取得結果では `-1` が入っていたため、属性値の直接利用は避ける。
- `GlobalBuildingAtlas` は高さ・3D を扱える可能性がある一方、ライセンス条件とデータ取得経路の整理を先に行う必要がある。
- `GHSL` と `WSF` は粗い全球ラスタであり、都市構造パラメータの「精密な建物量」を直接表すものではない。
- いずれの候補も、測量データの代替ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 6. 推奨ワークフロー

1. `OpenStreetMap` で道路ネットワークを整備する。
2. `Microsoft GlobalMLBuildingFootprints` で建物フットプリントを取得する。
3. 必要なら `GlobalBuildingAtlas` を比較取得し、Microsoft との差を局所的に確認する。
4. `GHSL` と `WSF` で built-up 比率の補助指標を作る。
5. Hanoi ROI で欠測率、重複率、空間カバレッジを確認する。
6. 採用可否を `docs\02_methods\analysis_workflow.md` または関連メモに追記する。

---

## 7. 参考ソース

- OpenStreetMap Wiki, Downloading data: https://wiki.openstreetmap.org/wiki/Downloading_data
- OpenStreetMap Wiki, Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Geofabrik Vietnam extract: https://download.geofabrik.de/asia/vietnam.html
- Microsoft GlobalMLBuildingFootprints: https://github.com/microsoft/GlobalMLBuildingFootprints
- GlobalBuildingAtlas: https://github.com/zhu-xlab/GlobalBuildingAtlas
- GHSL Data Package 2023 / GHS-BUILT: https://ghsl.jrc.ec.europa.eu/documents/GHSL_data_access.pdf
- GHSL collection landing page: https://data.jrc.ec.europa.eu/collection/ghsl/
- World Settlement Footprint 2015: https://geoservice.dlr.de/web/maps/eoc%3Awsf
