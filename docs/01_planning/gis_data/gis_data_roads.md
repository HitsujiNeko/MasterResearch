# 道路データの調査・評価

**最終更新**: 2026-06-24  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義

---

## 1. 採用データと用途

道路ネットワークは `OpenStreetMap` を第一候補とする。`highway=*` タグを使えば道路種別を抽出できるが、地区ごとに欠測や属性のばらつきがあるため、道路密度や道路近接距離は必ず欠測確認を行う。

Hanoi ROI については、Geofabrik の Vietnam extract から `highway IS NOT NULL` の道路ラインを抽出した `data/output/open_gis/hanoi_osm_roads.gpkg` を利用候補とする。今回の抽出結果では、道路ラインは `194,485` 件、ジオメトリ型は `MultiLineString` であり、道路密度指標の算出に利用できる状態である。

- 主用途: `ROAD_DEN_<scale>` などの道路密度指標の算出
- 補助用途: 道路近接距離、主要道路と生活道路の粗い区分、都市構造の説明変数作成
- 主な利用列: `highway`, `name`, `z_order`, `other_tags`, `geometry`

ただし、現段階では道路中心線の存在を使った密度指標を主用途とし、車線数や幅員のような精密な道路仕様の代替としては扱わない方が妥当である。

---

## 2. OpenStreetMap 道路データの詳細仕様

本研究で道路データの主ソースとして採用した OpenStreetMap（OSM）について、データの特性・制限・引用方法を記録する。

### 2.1 データセット概要

| 項目 | 内容 |
|---|---|
| 正式名称 | OpenStreetMap |
| データ提供元 | OpenStreetMap コミュニティ（ボランティアによる編集） |
| 本研究での配布元 | Geofabrik GmbH（Vietnam extract） |
| データ作成時期 | 2004年プロジェクト開始、継続的に編集中。本研究で使用した extract は 2026-04-08 時点のスナップショット（`vietnam-260408.osm.pbf`） |
| 配布形式 | `.osm.pbf`（Protobuf Binary Format）、`.shp.zip`（Shapefile）、`.gpkg`（ogr2ogr 変換後） |
| ライセンス | Open Data Commons Open Database License (ODbL 1.0) |
| 引用要件 | "© OpenStreetMap contributors" の帰属表示が必要。学術利用可 |
| 配布 URL | https://download.geofabrik.de/asia/vietnam.html |

### 2.2 タグ体系（`highway=*`）

OSM の道路データは `highway` キーで分類される。本研究に関連する主要な値を以下に示す。

| 分類 | `highway` タグ | 意味 |
|---|---|---|
| **幹線道路** | `motorway` / `motorway_link` | 高速道路・ランプ |
| | `trunk` / `trunk_link` | 国道級幹線 |
| | `primary` / `primary_link` | 主要地方道 |
| | `secondary` / `secondary_link` | 一般県道級 |
| **一般車道** | `tertiary` / `tertiary_link` | 地区幹線 |
| | `residential` | 住宅地内道路 |
| | `unclassified` | 分類未定の車道 |
| | `living_street` | 生活道路 |
| **サービス道路** | `service` | 敷地内通路・路地等（`service=alley/driveway/parking_aisle` で細分化） |
| **非車道** | `footway`, `path`, `pedestrian`, `cycleway`, `steps`, `corridor` | 歩行者・自転車用 |
| **特殊・未確定** | `track`, `construction`, `proposed` | 農道・工事中・計画中 |

本研究の ROAD_DEN 算出では、車道（幹線道路＋一般車道＋サービス道路）のみをホワイトリスト方式で対象とし、非車道・特殊道路は除外する（`src/analysis/urban_params/params/roads.py` の `VEHICLE_ROAD_TAGS` を参照）。

### 2.3 カバレッジ特性

- OSM はコミュニティ編集型であるため、**データの完全性・精度に地域差がある**。都市中心部は整備が進んでいるが、郊外・農村部では道路の欠測や属性の未入力が多い傾向がある。
- ベトナム主要都市（Hanoi, Ho Chi Minh City）については比較的整備が進んでおり、道路密度指標の算出には利用可能な水準である。ただし、道路種別の分類精度や属性（車線数・路面材質等）の入力率は低いため、これらに依存する指標の算出には適さない。
- カバレッジの定量的な評価は、対象都市ごとに Hanoi ROI と同様の抽出・集計を行い判断する。

### 2.4 更新頻度

- OSM 本体は**リアルタイムに編集**が行われる。
- Geofabrik の country extract は**日次更新**（daily snapshot）で提供される。
- 本研究では特定日付の extract を使用し、取得日を記録することで再現性を確保する（取得ファイル名に日付を含める: 例 `vietnam-260408.osm.pbf`）。

### 2.5 本研究での取得方法

Geofabrik Vietnam extract（`.osm.pbf`）を `ogr2ogr` で `lines` レイヤから `highway IS NOT NULL` の道路ラインを ROI でクリップして抽出する。出力形式は GeoPackage（`.gpkg`）。

```
ogr2ogr -f GPKG output.gpkg input.osm.pbf lines \
  -where "highway IS NOT NULL" \
  -spat <xmin> <ymin> <xmax> <ymax>
```

---

## 3. Hanoi ROI での取得結果（2026-06-22 調査）

**データソース**: Geofabrik Vietnam extract（`vietnam-260408.osm.pbf`）から `ogr2ogr` で `lines` レイヤのうち `highway IS NOT NULL` を Hanoi ROI でクリップして抽出。出力: `data/output/open_gis/hanoi_osm_roads.gpkg`（レイヤ名: `roads`）。

**ジオメトリ特性**:
- 全 194,485 件が **MultiLineString**（道路中心線）
- 道路幅の情報は含まれない（面積ベースの被覆率は直接算出不可）
- Hanoi ROI（行政区画）でクリップ済み

**highway タグ分布と総延長**:

| 分類 | highway タグ | 地物数 | 割合 | 総延長 (km) |
|---|---|---|---|---|
| **幹線道路** | motorway (+_link) | 832 | 0.4% | 407.8 |
| | trunk (+_link) | 1,719 | 0.9% | 673.3 |
| | primary (+_link) | 3,696 | 1.9% | 986.0 |
| | secondary (+_link) | 2,706 | 1.4% | 882.4 |
| **一般車道** | tertiary (+_link) | 3,964 | 2.0% | 1,689.8 |
| | residential | 100,411 | 51.6% | 18,077.0 |
| | unclassified | 1,972 | 1.0% | 974.1 |
| | living_street | 84 | 0.0% | 19.9 |
| **サービス道路** | service | 54,975 | 28.3% | 5,392.6 |
| **非車道** | footway | 15,280 | 7.9% | 1,582.8 |
| | steps | 843 | 0.4% | 11.8 |
| | path | 1,255 | 0.6% | 328.8 |
| | pedestrian | 105 | 0.1% | 9.0 |
| | cycleway | 73 | 0.0% | 16.2 |
| | corridor | 43 | 0.0% | 0.9 |
| **特殊・未確定** | track | 5,527 | 2.8% | 1,896.5 |
| | construction | 879 | 0.5% | 649.2 |
| | proposed | 103 | 0.1% | 65.5 |
| | その他 | 17 | 0.0% | 4.6 |
| **合計** | — | **194,485** | 100% | **33,668.1** |

**service サブタイプ**（other_tags 内の `service` キーで判別）:

| サブタイプ | 件数 | 割合 |
|---|---|---|
| （タグなし） | 31,514 | 57.3% |
| alley（路地） | 21,609 | 39.3% |
| driveway（進入路） | 731 | 1.3% |
| parking_aisle（駐車場通路） | 731 | 1.3% |
| その他 | 390 | 0.7% |

**z_order の仕組み**: Geofabrik の `z_order` は OSM の `highway` タグの基本優先度に `layer`・`bridge`・`tunnel` タグを加味した描画順序値である。具体的な算出式は `base_highway_order + (layer × 10) + (bridge ? +10 : 0) + (tunnel ? -10 : 0)` に近い。

| z_order の範囲 | 意味 | 件数 | 割合 |
|---|---|---|---|
| 負（< 0） | トンネル・地下道 | 599 | 0.3% |
| 0 | 地表（service, footway, track 等） | 77,718 | 40.0% |
| 3 | 地表（residential, unclassified） | 100,135 | 51.5% |
| 4–9 | 地表（tertiary 〜 motorway） | 12,004 | 6.2% |
| 10–19 | 高架・橋梁 | 1,316 | 0.7% |
| 20 以上 | 高架・橋梁（上層） | 2,713 | 1.4% |

都市構造パラメータの算出においては、トンネル・地下道（z_order < 0）は地表面温度に影響しないため除外を検討する。橋梁・高架は地表面との遮蔽関係があるため含めるのが妥当である。

**other_tags の主要キーと入力率**:

| キー | 入力率 | 備考 |
|---|---|---|
| surface | 17.6% | asphalt 63%, concrete 19%, paving_stones 8% |
| service | 12.1% | highway=service の地物のサブタイプ |
| oneway | 6.7% | 一方通行 |
| lit | 4.8% | 照明の有無 |
| lanes | 4.8% | 車線数（1: 11%, 2: 55%, 3: 22%, 4+: 12%）。入力率が低く網羅的でない |
| bridge | 2.1% | 橋梁フラグ |
| layer | 2.3% | 立体交差の層 |
| maxspeed | 1.1% | 制限速度 |

`lanes` と `surface` は入力率が低い（各 4.8%、17.6%）ため、これらの属性に依存した道路幅や舗装面積の推定は信頼性に欠ける。

---

## 4. 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも道路の完全性を保証しない。
- `OSM` の Hanoi ROI 道路抽出結果は道路密度指標には利用可能だが、道路種別や詳細属性の完全性は別途 QA が必要である。
- いずれの候補も、測量データの代替真値ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 5. ワークフロー

| # | 工程 | ステータス | 備考 |
|---|---|---|---|
| 1 | Geofabrik Vietnam extract の取得 | ✅ 完了 | `vietnam-260408.osm.pbf` を取得済み |
| 2 | Hanoi ROI での道路ライン抽出 | ✅ 完了 | `ogr2ogr` で `highway IS NOT NULL` を ROI クリップ。194,485 件を `data/output/open_gis/hanoi_osm_roads.gpkg` に出力 |
| 3 | 道路データの探索的分析 | ✅ 完了 | highway タグ分布・z_order・other_tags の入力率を集計（Section 3 参照） |
| 4 | ROAD_DEN（道路延長密度）算出ロジックの実装 | ✅ 完了 | `src/analysis/urban_params/params/roads.py` に実装（[PR #26](https://github.com/HitsujiNeko/MasterResearch/pull/26)、コミット `da0384a`）。車道タグのホワイトリスト方式 + z_order < 0 除外 |
| 5 | ROAD_DEN のスモークテスト | ✅ 完了 | `tests/analysis/urban_params/test_roads.py` に GIS 契約テストを追加済み |
| 6 | 他都市（Ho Chi Minh City 等）への道路データ取得・適用 | 未着手 | RQ2 のスケール比較時に対象都市を拡大する際に実施 |

---

## 6. 参考ソース

- OpenStreetMap Wiki, Downloading data: https://wiki.openstreetmap.org/wiki/Downloading_data
- OpenStreetMap Wiki, Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Geofabrik Vietnam extract: https://download.geofabrik.de/asia/vietnam.html
