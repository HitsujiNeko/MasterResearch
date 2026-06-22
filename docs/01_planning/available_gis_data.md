# 利用可能な公開GISデータ候補

**最終更新**: 2026-06-09  
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

## 4. 使い分けの提案

### 4.1 道路

道路ネットワークは `OpenStreetMap` を第一候補とする。`highway=*` タグを使えば道路種別を抽出できるが、地区ごとに欠測や属性のばらつきがあるため、道路密度や道路近接距離は必ず欠測確認を行う。

Hanoi ROI については、Geofabrik の Vietnam extract から `highway IS NOT NULL` の道路ラインを抽出した `data/output/open_gis/hanoi_osm_roads.gpkg` を利用候補とする。今回の抽出結果では、道路ラインは `194,485` 件、ジオメトリ型は `MultiLineString` であり、道路密度指標の算出に利用できる状態である。

- 主用途: `ROAD_DEN_<scale>` などの道路密度指標の算出
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

### 4.2.2 建物データの優先順位・取得状況（2026-06-09 更新）

GBA の WFS 取得完了・Microsoft 欠落域の定量確認を経て、比較優先順位と取得状況を次のとおり更新する。

#### 候補比較表

| 項目 | GlobalBuildingAtlas (GBA) | Google Open Buildings V3 | OSM building=* |
|---|---|---|---|
| Hanoi ROI全域カバレッジ | ✅ 取得完了（3,071,511件） | ✅ Vietnam明記 | 要QA |
| Microsoft欠落域（西側）対応 | ✅ 273,742件（面積率1.25%）確認済み | ✅ 東南アジア対応 | 要QA |
| 建物高さ情報 | ✅ あり（ML推定、RMSE未確認） | ❌ なし（V3 polygon） | △ 一部のみ |
| ライセンス | CC BY-NC 4.0（学術OK） | CC BY 4.0（最も寛容） | ODbL |
| アクセス方法 | **✅ 取得済み**（GPKG出力済み）。再取得はHuggingFaceを推奨 | gsutil / Colab ノートブック | Geofabrik（取得済み） |
| 取得状況 | ✅ 採用済み（`Limited`シナリオ主ソース） | 未取得・比較候補 | 未取得・比較候補 |
| 下地データ | Google Open Buildings 由来 | — | コミュニティ編集 |
| 備考 | **WFSレート制限注意**: 1,554タイルでIPブロック（48h+）が発生。再取得はHuggingFace（タイル`e105_n25_e110_n20`、~1.78GB）推奨 | 建物高さはV3ではなく2.5D Temporalで別途取得 | 品質は地域差が大きい |

#### 優先順位・取得状況

1. `GlobalBuildingAtlas` via WFS / HuggingFace: **✅ 採用済み（`Limited`シナリオ建物主ソース）**。2026-06-09 に ROI クリップ済みで 3,071,511 件取得完了。`data/output/open_gis/hanoi_gba_buildings.gpkg` に出力済み。スクリプト: `src/preprocessing/fetch_gba_buildings_hanoi.py`（`--start-tile-index` で途中再開可能）。**再取得時は WFS でなく HuggingFace バルクDL推奨**（WFS は大量リクエスト時に IP ブロックが発生するため）。
2. `Google Open Buildings V3 Polygons`: 未取得。ライセンスがより寛容（CC BY 4.0）。建物高さ不要で面積・密度のみ算出する場合の比較候補。confidence閾値の感度分析が必要。GBA との重複率・差分を確認してから採用判断する。
3. `OSM building=*`: 未取得。Geofabrik Vietnam extract から追加取得でき、道路と同一ソースで再現性が高い。コミュニティ整備状況に依存するため、建物密度の空間偏りを QA する。
4. `Google Open Buildings 2.5D Temporal`, `GHSL`, `WSF`: 個別フットプリントではなく、built-up / building presence / height の補助変数または妥当性確認に使う。

### 4.2.3 Limited シナリオの建物データ方針（2026-06-09 更新）

**GBA の取得完了により、`Limited` シナリオの建物主ソースを `GlobalBuildingAtlas` に確定した。**

- `data/output/open_gis/hanoi_gba_buildings.gpkg`（3,071,511 件、ROI クリップ済み）を建物フットプリントの正本として使う。
- Microsoft 欠落域（105.29–105.47°E）では GBA に 273,742 件の実データが存在することを確認済み。GBA を使うことで Microsoft のカバレッジ欠落問題は解消される。
- `BUILD_COV_0`, `BUILD_DEN_0` などの建物系パラメータは GBA を主ソースとして再算出する。
- Microsoft は「Hanoi 中心部から東側の補助的な比較データ」として保持するが、主ソースとしては使わない。
- `BUILD_COV_0 = 0`, `BUILD_DEN_0 = 0` を「建物なし」と解釈する前に、そのセルが GBA の有効カバレッジ内かを確認する（GBA は ROI 行政区画クリップ済みのため境界付近には注意）。

### 4.3 粗い都市化指標

`GHSL` と `WSF` は、建物輪郭の代替ではなく、粗い built-up 比率や settlement extent の比較用に向いている。RQ2 のスケール比較や、RQ3 のデータ制約シナリオの補助説明変数として使いやすい。

---

## 5. 本研究への適合性評価

### 5.1 採用候補

- `OpenStreetMap` は道路パラメータの主ソースとして採用候補。
- `Microsoft GlobalMLBuildingFootprints` はカバレッジ制限付き建物候補。Hanoi ROI 全域の単独主ソースにはしない。
- `Google Open Buildings V3 Polygons` は Microsoft 欠落域を補えるか確認する第一候補。
- `OSM building=*` は再現性の高い比較候補。
- `GlobalBuildingAtlas` は建物高さや LoD1 を含む建物主ソースとして採用済み（`Limited` シナリオ、2026-06-09 取得完了）。
- `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` は補助変数・妥当性確認用の採用候補。

### 5.2 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも道路・建物の完全性を保証しない。
- `OSM` の Hanoi ROI 道路抽出結果は道路密度指標には利用可能だが、道路種別や詳細属性の完全性は別途 QA が必要である。
- `Microsoft` は全球対応だが、Hanoi ROI では西側欠落が確認されたため、ROI 全域の建物ゼロ値をそのまま解釈してはならない。
- `Microsoft` の `height_m` と `confidence` は地域や更新時期によって未提供の場合があり、Hanoi ROI の今回取得結果では `-1` が入っていたため、属性値の直接利用は避ける。
- `Google Open Buildings` は confidence 閾値により建物数と面積率が変わるため、閾値感度分析を行う。
- `GlobalBuildingAtlas` の WFS は大量リクエスト（~1,554 タイル）時に IP レート制限（48 時間以上のブロック）が発生する場合がある。再取得が必要な場合は HuggingFace（`zhu-xlab/GBA.LoD1`、タイル `e105_n25_e110_n20`、約 1.78GB GeoJSON）によるバルクDL を使うこと。スクリプト `src/preprocessing/fetch_gba_buildings_hanoi.py` には `--start-tile-index` で途中再開機能を実装済み。
- `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` は建物ポリゴンそのものではなく、`BUILD_DEN_0` と同じ定義ではない。
- いずれの候補も、測量データの代替真値ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 6. 推奨ワークフロー（2026-06-09 更新）

1. `OpenStreetMap` で道路ネットワークを整備する。
2. Microsoft 建物データのカバレッジ欠落を QA 結果として固定し、現行 `hanoi_microsoft_buildings.gpkg` の有効範囲を明示する（保留扱い確定）。
3. ~~`GlobalBuildingAtlas` を WFS で Hanoi ROI から取得する。~~ **✅ 完了（2026-06-09）**。行政区画ポリゴンクリップ済みで 3,071,511 件取得。出力: `data/output/open_gis/hanoi_gba_buildings.gpkg`。スクリプト: `src/preprocessing/fetch_gba_buildings_hanoi.py`（`--start-tile-index` で途中再開可能）。**再取得時は WFS ではなく HuggingFace バルクDL を推奨**（WFS は IP ブロックが発生したため）。
4. ~~GBA 取得後、Microsoft 欠落域（105.29–105.47°E）での建物数・面積率を比較し、カバレッジ改善を定量確認する。~~ **✅ 完了（2026-06-09）**。Microsoft 欠落域で 273,742 件・面積率 1.25% を確認（ゼロでなく実データあり）。GBA を `Limited` シナリオ建物主ソースとして確定。
5. 必要に応じて `Google Open Buildings V3 Polygons` を Geofabrik の代替または補完データとして取得し、GBA と比較する。
6. Geofabrik Vietnam extract から `building=*` を抽出し、GBA / Google と密度・面積率を比較する。
7. `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` で built-up / building presence の補助指標を作る。
8. 各候補について欠測率、重複率、空間カバレッジ、建物数、建物面積率を同一 ROI グリッドで比較する。
9. 採用可否を [analysis_workflow.md](../02_methods/analysis_workflow.md) と [calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md) に反映する。

---

## 7. GlobalBuildingAtlas 詳細仕様

本研究の `Limited` シナリオで建物主ソースとして採用した GlobalBuildingAtlas（GBA）について、データの特性・制限・引用方法を記録する。

### 7.1 データセット概要

| 項目 | 内容 |
|---|---|
| 正式名称 | GlobalBuildingAtlas (GBA) |
| バージョン | v1.0.0（2025年11月公開） |
| 規模 | 約 2.75 億棟（全球） |
| 提供機関 | Chair of Remote Sensing Technology, Technical University of Munich (TUM) / zhu-xlab グループ |
| 配布形式 | WFS（GeoServer）、HuggingFace（5°×5° GeoJSON タイル）、GitHub |
| ライセンス | CC BY-NC 4.0（非商用・帰属表示必須） |
| GitHub | https://github.com/zhu-xlab/GlobalBuildingAtlas |
| 論文 DOI | https://doi.org/10.5194/essd-17-6647-2025 |

### 7.2 データの構成とフットプリントのソース

GBA は **建物フットプリント（ポリゴン）** と **ML 推定建物高さ** を組み合わせた全球 LoD1 建物モデルである。

**フットプリントのソース**:
- 地域によって複数ソースを統合している。東南アジア（ベトナム含む）は **Google Open Buildings V3** が主ソースである。WFS レスポンスの `source` 属性に `google` と格納されていることで確認できる。
- フットプリントの検出精度は元ソース（Google Open Buildings 等）の機械学習モデルに依存する。

**建物高さ（`height` 属性）**:
- 衛星画像から機械学習で推定した値であり、現地測量値ではない。
- 推定アルゴリズムの詳細は論文（Zhu et al., 2025）を参照。
- ハノイ ROI での高さ推定精度（RMSE 等）は本研究では未検証。

**LoD1 モデルとは**:
- Level of Detail 1（LoD1）= フットプリントポリゴンを**単一の代表高さで押し出した箱型 3D モデル**。
- 屋根の形状（切妻・寄棟等）や階別の形状変化は表現しない。
- 本研究では建物フットプリント面積・建物密度・建物高さ（`height`）の算出に利用する。

### 7.3 WFS エンドポイント情報

| 項目 | 値 |
|---|---|
| エンドポイント URL | `https://tubvsig-so2sat-vm1.srv.mwn.de/geoserver/ows` |
| レイヤー名 | `global3D:lod1_global` |
| プロトコル | WFS 2.0.0 (OGC) |
| Native CRS | EPSG:3857（Web メルカトル） |
| BBOX 指定 | EPSG:3857 に変換して指定する必要がある（EPSG:4326 のまま渡すと座標系ずれが生じる） |
| 最大取得件数 / リクエスト | 50,000 件（`count` パラメータ上限） |

### 7.4 今回の取得処理の内容（Hanoi ROI）

スクリプト `src/preprocessing/fetch_gba_buildings_hanoi.py` で実施した主な処理：

1. **タイル分割**: ROI BBOX を 0.02° × 0.02° グリッドに分割（全 1,554 タイル）し、WFS を 1 タイルずつ取得。50,000 件 / リクエスト上限によるデータ欠落を回避するため。
2. **ROI 事前フィルタ**: タイルと行政区画ポリゴンが交差しない場合はリクエスト自体をスキップ（不要リクエストを削減）。
3. **CRS 変換**: WFS レスポンス（EPSG:3857）を EPSG:4326 に変換。
4. **ROI クリップ**: 各建物ポリゴンを Hanoi 行政区画ポリゴン（`data/GISData/ROI/hanoi/hanoi_ROI_EPSG4326.shp`）でクリップ。境界を跨ぐ建物は切断して境界内の部分のみ保持。
5. **出力**: `data/output/open_gis/hanoi_gba_buildings.gpkg`（GeoPackage 形式、EPSG:4326）

**取得結果**: 3,071,511 件（2026-06-09 完了）

### 7.5 精度・制限事項

- **高さ精度未検証**: `height` 属性は ML 推定値。ハノイでのローカル精度（RMSE・バイアス）は未検証。高さを定量指標として使う場合は別途現地データとの検証が必要。
- **フットプリントの過検出・未検出**: 元ソースが機械学習検出のため、仮設構造物・農業用建屋の誤検出や小規模建物の未検出がある可能性がある。
- **GBA と Google Open Buildings の独立性**: ベトナムでは GBA フットプリントが Google Open Buildings V3 と概ね重複する。両者を独立した検証データとして扱うことはできない。
- **ROI 境界付近の部分ポリゴン**: 行政区画境界を跨ぐ建物はクリップして保持しているため、境界付近には部分的なポリゴンが含まれる。建物面積・高さ指標の算出時は境界付近の扱いに注意。
- **WFS レート制限**: 今回の 1,554 タイル取得で IP レベルのレート制限（48 時間以上のブロック）が発生した。再取得が必要な場合は WFS ではなく HuggingFace のバルクダウンロード（タイル `e105_n25_e110_n20`、約 1.78GB GeoJSON）を推奨。

### 7.6 論文への引用

論文・学位論文で本データを使用する場合は、以下の論文を引用する。

```
Zhu, X. X. et al.: GlobalBuildingAtlas: A global LoD1 building model,
Earth Syst. Sci. Data, 17, 6647–6670,
https://doi.org/10.5194/essd-17-6647-2025, 2025.
```

> **注意**: 著者リストの正式表記は論文ページ（https://essd.copernicus.org/articles/17/6647/2025/）で確認すること。上記の `Zhu, X. X. et al.` は略記であり、投稿規程に合わせて正確な著者リストを使うこと。

CC BY-NC 4.0 ライセンスの帰属表示要件として、論文本文またはデータセクションに以下のような記述を含めること：

> Building footprint and height data are from the GlobalBuildingAtlas (GBA) v1.0.0 (Zhu et al., 2025), available at https://github.com/zhu-xlab/GlobalBuildingAtlas, licensed under CC BY-NC 4.0.

### 7.7 フットプリント元ソース：Google Open Buildings V3 について

GBA のフットプリントはベトナムでは Google Open Buildings V3 由来（WFS の `source:google` 属性で確認済み）であるため、補足として概要を記録する。

Google Open Buildings V3 は Google が衛星画像から機械学習で検出した建物フットプリントデータセットである。東南アジア・アフリカ等を対象に約 18 億件を収録し、各検出に **信頼スコア（confidence: 0〜1）** を付与している点が Microsoft との主な違いである。ライセンスは CC BY 4.0（商用利用可）。

**Microsoft との主な違い**:

| 項目 | Google Open Buildings V3 | Microsoft GlobalMLBuildingFootprints |
|---|---|---|
| 学習用画像ソース | Google 衛星画像 | Bing Maps 衛星画像 |
| 信頼スコア | あり（confidence: 0〜1） | なし |
| Hanoi ROI カバレッジ | 全域 | 西側（〜105.47°E）欠落 |
| ライセンス | CC BY 4.0 | ODbL |

**本研究での注意点**:  
GBA（ベトナム）のフットプリントは Google Open Buildings V3 と概ね同一であるため、両者を**独立した検証データとして相互利用することはできない**。Microsoft は異なる衛星画像・異なるモデルで検出しているため、カバレッジが重なる ROI 東側（約 105.47°E 以東）に限り独立した比較が可能である。

---

## 8. 参考ソース

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
