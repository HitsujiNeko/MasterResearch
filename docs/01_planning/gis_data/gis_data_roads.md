# 道路データの調査・評価

**最終更新**: 2026-06-23  
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

## 2. OSM 道路データの詳細特性（2026-06-22 調査）

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

## 3. 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも道路の完全性を保証しない。
- `OSM` の Hanoi ROI 道路抽出結果は道路密度指標には利用可能だが、道路種別や詳細属性の完全性は別途 QA が必要である。
- いずれの候補も、測量データの代替真値ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 4. ワークフロー

1. `OpenStreetMap` で道路ネットワークを整備する。

---

## 5. 参考ソース

- OpenStreetMap Wiki, Downloading data: https://wiki.openstreetmap.org/wiki/Downloading_data
- OpenStreetMap Wiki, Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Geofabrik Vietnam extract: https://download.geofabrik.de/asia/vietnam.html
