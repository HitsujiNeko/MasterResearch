# 土地利用データ（LULC）の調査・評価

**最終更新**: 2026-08-22  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDVI/NDBI等の衛星由来指標との違い）

---

## 1. 調査目的

本研究では都市構造パラメータとしてNDVI（植生量）・NDBI（市街化）といった衛星由来指標を既に算出しているが、これらは連続値の指標であり、「土地利用の分類（住宅地・商業地・農地・緑地等のカテゴリ）」そのものは表現できない。本資料では、Landsat由来指標を補完する**分類済み土地利用/土地被覆（LULC）データ**のオープンソース候補を調査する。

主候補の`GLC_FCS30D`はHanoi ROIでの実データ取得・確認を完了している（Section 5）。比較候補のうち`Esri Sentinel-2 10m LULC`も取得を完了し、`GLC_FCS30D`とのクラス体系の対応関係・空間的一致度を評価した（Section 6・Section 7）。`Dynamic World`の取得は未実施。

---

## 2. 候補データ比較表

| 項目 | ESA WorldCover | Dynamic World V1 | GLC_FCS30D | Esri Sentinel-2 10m LULC | Copernicus GLC-100m | OSM landuse | GlobeLand30 |
|---|---|---|---|---|---|---|---|
| 空間解像度 | 10m | 10m | **30m**（本研究グリッドと一致） | 10m | 100m | ベクタ（ポリゴン） | 30m |
| データ時期 | 2020・2021年の2時点のみ | 2015-06-27〜現在、継続更新 | 1985〜2022年（2000年以降は年次） | 2017〜2024年（年次） | 2015〜2019年（更新停止） | 継続的にコミュニティ編集 | 2000・2010・2020年（3時点） |
| 更新頻度 | 静的（更新停止） | 準リアルタイム（2〜5日） | 年次 | 年次 | 停止済み | リアルタイム編集 | 10年おき |
| ベトナム/ハノイ カバレッジ | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット（粗い） | △ landuseタグの入力率は地域依存 | ✅ 全球データセット（アクセスに難あり） |
| ライセンス | CC BY 4.0 | CC BY 4.0 | CC BY 4.0 | CC BY 4.0 | CC BY 4.0 | ODbL 1.0 | 非商用限定・登録制（詳細不明瞭） |
| 分類数 | 11クラス | 9クラス（確率値あり） | 35クラス（詳細分類） | 9クラス | 23クラス | タグ体系（自由記述に近い） | 10クラス |
| 取得方法（スクリプト可否） | ✅ AWS Open Data / GEE経由でスクリプト取得可 | ✅ GEE経由でスクリプト取得可 | ✅ Zenodo直接ダウンロード（GEE不要、`requests`等で取得可） | ✅ AWS Open Data Registry / Microsoft Planetary Computer STAC APIでスクリプト取得可（GEE不要） | ✅ スクリプト取得可（解像度不足のため不採用） | ✅ Geofabrik/Overpass APIでスクリプト取得可（道路データと同じ取得経路） | ❌ ログイン必須のポータル経由（手動DL相当） |

---

## 3. 候補データ詳細

### 3.1 ESA WorldCover

- **正式名称**: ESA WorldCover 10m
- **提供機関**: European Space Agency (ESA) + VITO
- **データソース**: Sentinel-1（SAR）+ Sentinel-2（光学）
- **提供時期**: v100（2020年版、2021年10月公開）、v200（2021年版、2022年10月公開、アルゴリズム改良版）
- **懸念点**: 2020年・2021年の2時点のみで、それ以降のバージョンは公開されていない（2026年7月時点で2022年以降の更新なし）。

### 3.2 Dynamic World V1

- **正式名称**: Dynamic World
- **提供機関**: Google + World Resources Institute + National Geographic Society
- **データソース**: Sentinel-2 L1C（雲量35%以下のシーン）を深層学習モデルで分類
- **提供時期**: 2015-06-27〜現在。地域によって2〜5日間隔で更新される準リアルタイムデータセット
- **分類**: water, flooded vegetation, built area, trees, crops, bare ground, grass, shrub/scrub, snow/ice の9クラス（各クラスの確率値も提供）
- **利点**: 本研究で使用するLandsat 8観測日と同時期のSentinel-2シーンから土地利用を抽出できるため、LST算出日との時間整合性が高い。

### 3.3 GLC_FCS30D（Global Land Cover with Fine Classification System, Dynamic）

- **正式名称**: GLC_FCS30D
- **提供機関**: Chinese Academy of Sciences（Zhang, Liu et al.）
- **データソース**: Landsat時系列（継続変化検出法）
- **提供時期**: 1985〜2022年、2000年以降は年次更新（26時点）
- **配布形式**: Zenodo経由でZIP形式配布（DOI: 10.5281/zenodo.8239305、総容量約194.4GB、経度帯別36分割）
- **分類**: 35の詳細土地被覆サブカテゴリ（GlobeLand30の10クラスより細かい）
- **利点**: **本研究の解析グリッド（30m）とネイティブ解像度が一致**するため、10mデータのようなリサンプリングが不要。GEEを経由せずZenodoから直接ダウンロード可能（Python `requests` 等でスクリプト化しやすい）。Landsat観測年（本研究では2023年前後）に対応する年次マップを選択できる。
- **懸念点**: ファイルサイズが大きい（経度帯別分割ファイルからHanoi ROIを含むタイルのみ選択する必要がある）。

### 3.4 Esri Sentinel-2 10m Land Cover（Impact Observatory）

- **正式名称**: Sentinel-2 10m Annual Land Use Land Cover
- **提供機関**: Impact Observatory + Microsoft + Esri（National Geographic Societyの学習データ使用）
- **データソース**: Sentinel-2（年間コンポジット）を深層学習モデルで分類
- **提供時期**: 2017〜2024年、年次更新
- **配布形式**: AWS Open Data Registry（`io-lulc`）、Microsoft Planetary Computer（STAC API）、Esri ArcGIS Living Atlas
- **分類**: 9クラス（Dynamic Worldと同系統の分類体系）
- **利点**: GEEに依存せずAWS/Planetary Computer経由でスクリプト取得可能。年次コンポジットのため、Dynamic Worldのような期間集約処理が不要で扱いやすい。
- **取得状況**: Hanoi ROI・2022年での取得を完了している（Section 6）。GLC_FCS30D との一致度は Section 7。

### 3.5 Copernicus Global Land Cover (CGLS-LC100)

- **正式名称**: Copernicus Global Land Service Land Cover 100m Collection 3
- **提供機関**: Copernicus Land Monitoring Service
- **データソース**: PROBA-V衛星
- **提供時期**: 2015〜2019年（年次）。2019年以降、後継プロダクトの更新は確認できなかった
- **懸念点**: 解像度100mは本研究の30mグリッド解析に対して粗く、都市内部の土地利用の空間パターンを捉えにくい。参考データとしてのみ扱う。

### 3.6 OpenStreetMap landuse タグ

- **データソース**: OSMコミュニティ編集（`landuse=*` キー）
- **提供時期**: 継続的にリアルタイム編集
- **配布形式**: Geofabrik Vietnam extract（`.osm.pbf`）から`ogr2ogr`で`landuse IS NOT NULL`のポリゴンを抽出。道路データ（[gis_data_roads.md](gis_data_roads.md)）と同じ取得経路が使える。
- **懸念点**: `landuse`タグは道路の`highway`タグに比べて入力率・網羅性が地域差に左右されやすいとされる（一般論として、丁寧にマッピングされた地域と粗い地域の差が大きい）。Hanoi ROIでの実際の入力率は未調査であり、面的な網羅性を前提にした指標（例: 土地利用カテゴリ別面積率）には向かない可能性がある。ポイント・線的な補助情報（特定の公園・工業団地の位置確認等）としての利用が現実的。

### 3.7 GlobeLand30

- **正式名称**: GlobeLand30
- **提供機関**: National Geomatics Center of China (NGCC)
- **提供時期**: 2000年・2010年・2020年の3時点
- **懸念点**: ダウンロードに専用ポータルへのログインが必要で、ライセンスも「非商用・政府機関/NGO向けは無償」といった記載があり、学術個人利用での扱いが明確でない。スクリプトによる自動取得も難しい（ログイン画面を介する手動DL相当）。

---

## 4. 推奨方針

- **主候補**: `GLC_FCS30D`。本研究の解析グリッド（30m）とネイティブ解像度が一致し、CC BY 4.0でZenodoから直接スクリプト取得できる（GEE不要）。年次更新のため、Landsat観測年に対応するマップを選べる。
- **副候補（クロスチェック用）**: `Esri Sentinel-2 10m LULC`。取得・一致度評価を完了し、**市街地の広がりについて両データが大きく異なる**ことを確認した（Section 7）。主候補を置き換えるのではなく、**市街地・不透水面として抽出される範囲の解釈幅を示す感度分析の材料**として位置づける。両データはクラス定義が一致しない（GLC は人工被覆、Esri は建造環境）ため、同一の物理量を測り比べたものとは読めない（Section 7.1）。
- **副候補（時間解像度が必要な場合）**: `Dynamic World`（Landsat観測日に近いSentinel-2シーンから取得、準リアルタイム）。10mのためGLC_FCS30Dとのクロスチェック用に位置づける。
- **参考データ**: `ESA WorldCover`（静的だが分類が安定、妥当性確認用）。`OSM landuse`は面的な網羅性が未確認のため、特定施設の位置確認等の補助用途に留める。
- **不採用**: `Copernicus Global Land Cover`（解像度100mが粗すぎる）、`GlobeLand30`（アクセス手段がスクリプト化困難でライセンスも不明瞭）。
- `GLC_FCS30D` と `Esri Sentinel-2 10m LULC` の取得スクリプトは作成済みで、Hanoi ROIでのデータ取得・確認も完了している（Section 5・Section 6）。`Dynamic World` の取得は別タスクとして切り出す。
- 上記2データセットを入力とする土地被覆クラス別面積率（列名・出力クラス・規約）の出力仕様の正本は [calc_urban_params_io_spec.md](../../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.4節である。

---

## 5. Hanoi ROIでの取得結果（GLC_FCS30D）

**取得日**: 2026-07-21 / **取得スクリプト**: `src/preprocessing/fetch_glc_fcs30d_hanoi.py`

### 5.1 取得元と取得方法

- **使用レコード**: Zenodo **v2**（DOI: 10.5281/zenodo.15063683、2025-03-21公開）。本資料 Section 3.3 に記載の DOI 10.5281/zenodo.8239305 は初版であり、Zenodo API で `is_last: false` を確認した。収録内容（36 ZIP）は同一だがファイルサイズが異なる
- **配布構造**: 経度10度帯ごとの36 ZIP。ZIP内のタイルは**5度四方で、タイル名は左上隅の座標**を表す（実測により確認: `E105N20` の bounds は経度105–110・緯度15–20）
- **使用タイル**: `E105N25`（経度105–110・緯度20–25）。Hanoi ROI（105.288–106.020°E, 20.564–21.385°N）は**このタイル1枚に完全に収まる**
- **取得量の削減**: 対象 ZIP は約6.39GBあるが、Zenodo が HTTP Range（206応答）に対応するため、ZIP の中央ディレクトリのみを読んで**対象メンバー（約197MB）だけを取り出す**方式とした。GDAL の `/vsizip//vsicurl/` は Zenodo の配信URLが拡張子を持たないため利用できない
- **対象年**: 2022年（年次版の最新年）。年次版は23バンドで、バンド1から順に2000〜2022年に対応する。**2023年以降のマップは存在しない**ため、本研究の Landsat 観測年（2023年前後）とは最大で数年のずれがある

### 5.2 出力

| 項目 | 内容 |
|---|---|
| GeoTIFF | `data/gis/lulc/glc_fcs30d/glc_fcs30d_hanoi_2022.tif`（Git管理外） |
| サマリーJSON | `data/output/open_gis/glc_fcs30d_hanoi_2022_summary.json` |
| QGISスタイル | `qgis/styles/lulc_glc_fcs30d.qml`（35クラスの公式配色・凡例は日英併記） |
| CRS / 型 | EPSG:4326 / uint8 |
| サイズ / 解像度 | 2717 × 3046 画素 / 0.00026949458523586°（≒30m） |

### 5.3 カバレッジ

| 指標 | 値 |
|---|---|
| ROI内画素数 | 4,015,086 |
| ROI内の有効画素数 | 4,015,086 |
| ROI内の無効値（Filled value: 0・250） | **0** |
| **ROI内の有効画素率** | **1.0000（欠測なし）** |

ROIポリゴンでクリップした出力は ROI の BBOX 矩形（8,275,982画素）となり、ROI外の余白（4,260,896画素）は nodata で埋まる。**この余白は欠測ではない**ため、有効カバレッジは ROI 内のみで評価している（余白を含めて計算すると有効画素率は約48.5%となり、実態を大きく誤る）。

### 5.4 クラス分布（2022年・ROI内）

| クラスID | クラス名 | 画素数 | 割合 |
|---|---|---|---|
| 20 | 灌漑農地（Irrigated cropland） | 2,079,643 | 51.80% |
| 190 | 不透水面（Impervious surfaces） | 802,422 | 19.99% |
| 10 | 天水農地（Rainfed cropland） | 552,026 | 13.75% |
| 52 | 常緑広葉樹林・密（Closed evergreen broadleaved forest） | 256,249 | 6.38% |
| 210 | 水域（Water body） | 220,886 | 5.50% |
| 182 | 湿原（Marsh） | 44,239 | 1.10% |
| 183 | 冠水低地（Flooded flat） | 26,543 | 0.66% |
| 72 | 常緑針葉樹林・密（Closed evergreen needle-leaved forest） | 11,542 | 0.29% |
| 130 | 草地（Grassland） | 9,099 | 0.23% |
| 120 | 低木林（Shrubland） | 5,867 | 0.15% |
| 121 | 常緑低木林（Evergreen shrubland） | 5,007 | 0.12% |
| 11 | 草本被覆農地（Herbaceous cover cropland） | 759 | 0.02% |
| 62 | 落葉広葉樹林・密（Closed deciduous broadleaved forest） | 511 | 0.01% |
| 181 | 沼沢（Swamp） | 247 | 0.01% |
| 51 | 常緑広葉樹林・疎（Open evergreen broadleaved forest） | 46 | 0.00% |

出現クラスは15種で、すべて User Guides の35クラス体系に含まれる（体系外の値は検出されなかった）。クラス名の**「疎/密」は原語の Open/Closed の訳**であり、植被率（fc）の閾値に対応する（**疎: 0.15 < fc < 0.4、密: fc > 0.4**）。

### 5.5 検証結果

- **バンドと年の対応**: 実データで検証済み。不透水面が13.67%（バンド1）→20.68%（バンド19）と単調増加し、灌漑農地が57.97%→51.68%と単調減少した。ハノイの都市化の傾向と整合し、**バンド1 = 2000年**が正しいことを確認した
- **QGISとの突合**: `native:rasterlayeruniquevaluesreport` による独立集計と、Pythonでの集計が**完全一致**（総画素数8,275,982・NoData 4,260,896・15クラスすべての画素数が一致、不一致ゼロ）
- **空間的妥当性**: ROI形状に正確にクリップされ、都心部の不透水面の集中と紅河の形状が視覚的に整合することを確認した

### 5.6 利用上の注意

- **Data Use Policy**: ライセンスは CC BY 4.0 だが、User Guides に「**科学論文で利用する場合は事前に提供者へ連絡し、謝辞または共著を検討することを推奨する**」との記載がある。論文執筆時の対応要否は研究者が判断すること
- **時系列の揺らぎ**: 不透水面率は2018年の20.68%をピークに2022年には19.99%へ減少し、同期間に水域が4.94%→5.50%へ増加している。分類の年次変動の可能性があり、**時系列比較に用いる際は注意が必要**
- **分析シナリオ上の位置づけ**: 公開GISデータであるため Limited・Full シナリオに含め、Satellite Only には含めない（QGISプロジェクトの Map Theme も同様に設定済み）

---

## 6. Hanoi ROIでの取得結果（Esri Sentinel-2 10m LULC）

**取得日**: 2026-07-25 / **取得スクリプト**: `src/preprocessing/fetch_esri_lulc_hanoi.py`

### 6.1 取得元と取得方法

- **取得元**: Microsoft Planetary Computer の STAC API（コレクション `io-lulc-annual-v02`）。`pystac_client` 等の追加依存は導入せず、標準ライブラリの `urllib`（`src/common/http_fetch.py` 経由）と `rasterio` で実装した
- **使用アイテム**: `48Q-2022`（UTM タイル 48Q・2022年）。Hanoi ROI は**このタイル1枚に完全に収まる**。ネイティブ CRS は EPSG:32648、`data` アセットは約232MBのCOG
- **署名が必須**: Blob URL への直アクセスは HTTP 409 を返す。`GET /api/sas/v1/sign` で SAS 付き URL を得てから読む。**署名済み URL は有効期限があるためサマリーには記録しない**（期限切れ URL を出典として残さないため）
- **日付フィルタ**: `datetime` の範囲検索は対象年の 1/1 に終わる前年アイテム（`48Q-2021`）も返すため、`start_datetime` の年が一致するものだけに絞り込んでいる
- **取得量の削減**: COG のため ROI の BBOX に対応する window のみを読む（232MB全体はダウンロードしない）
- **再投影**: ネイティブ UTM から EPSG:4326 へ変換する際、**カテゴリ値のため最近傍（nearest）**で再投影している（線形補間は使わない）

### 6.2 出力

| 項目 | 内容 |
|---|---|
| GeoTIFF | `data/gis/lulc/esri_10m/esri_lulc_hanoi_2022.tif`（Git管理外） |
| サマリーJSON | `data/output/open_gis/esri_lulc_hanoi_2022_summary.json` |
| QGISスタイル | `qgis/styles/lulc_esri_10m.qml`（9クラスの公式配色・凡例は日英併記） |
| スクリーンショット | `images/gis_data/lulc/lulc_esri_10m_hanoi.png` |
| CRS / 型 | EPSG:4326 / uint8 |
| サイズ / 解像度 | 7890 × 8846 画素 / 0.00009278841925655°（≒10m） |
| ライセンス | CC BY 4.0 |

**配色の出典**: 9クラスの公式配色は STAC コレクションのメタデータには含まれない（`item_assets.data.file:values` はクラス値とラベルのみ）。**ソース COG に埋め込まれた GDAL カラーテーブルを実測**して `.qml` に転記した。窓読みで保存したローカルのサブセットにはカラーテーブルが引き継がれないため、リモートの COG をヘッダーのみ読んで取得している。

### 6.3 カバレッジ

| 指標 | 値 |
|---|---|
| ROI内画素数 | 33,868,965 |
| ROI内の有効画素数 | 33,868,169 |
| ROI内の無効値（No Data: 0） | **0** |
| ROI内の無効値（Clouds: 10） | **796** |
| **ROI内の有効画素率** | **0.99998** |

無効値の内訳はサマリー JSON の `pixel_stats.filled_value_counts` に記録している（合計だけでは上表を成果物から検証できないため）。

GLC_FCS30D と同じく、ROIポリゴンでクリップした出力は ROI の BBOX 矩形（69,794,940画素）となり、ROI外の余白（35,925,975画素）は nodata（0）で埋まる。**この余白は欠測ではない**ため、有効カバレッジは ROI 内のみで評価している。No Data(0) は ROI 内には1画素も存在せず、すべて ROI 外の余白である。

**Clouds(10) の扱い**: 本データは年間コンポジット（1年分の Sentinel-2 シーンから1枚の土地被覆図を作る）であり、`10 Clouds` は**土地被覆の種類ではなく「地表面を判定できなかった画素」を表す**。取得スクリプトでは No Data(0) と同じく無効値（`FILLED_VALUES = (0, 10)`）として扱い、下記のクラス分布と有効画素数から除外している。ROI 内の該当は796画素（≒0.08 km²、ROI内画素の 0.0024%）で、分析への実質的な影響はない。

なお `images/gis_data/lulc/lulc_esri_10m_hanoi.png` の凡例は**実在クラス8種**を表示しており、Clouds(10) を含む。凡例は「ラスタに実在する画素値」で絞り込むため、無効値であっても実在すれば表示される。下記クラス分布の7クラスとの差はこの1クラス分である。

### 6.4 クラス分布（2022年・ROI内・有効画素に対する比）

| クラスID | クラス名 | 画素数 | 割合 |
|---|---|---|---|
| 5 | 農地（Crops） | 14,222,145 | 41.99% |
| 7 | 市街地（Built area） | 13,301,197 | **39.27%** |
| 1 | 水域（Water） | 3,260,319 | 9.63% |
| 2 | 樹林（Trees） | 2,657,364 | 7.85% |
| 11 | 草地・低木（Rangeland） | 353,328 | 1.04% |
| 8 | 裸地（Bare ground） | 52,054 | 0.15% |
| 4 | 冠水植生（Flooded vegetation） | 21,762 | 0.06% |

出現クラスは7種で、すべて9クラス体系に含まれる（体系外の値は検出されなかった）。**市街地 39.27% は GLC_FCS30D の不透水面 19.99%（Section 5.4）の約2倍**であり、この差の内訳は Section 7 で扱う。

---

## 7. GLC_FCS30D と Esri 10m LULC の一致度（2022年・Hanoi ROI）

**実施日**: 2026-07-25 / **比較スクリプト**: `src/analysis/compare_lulc_esri_glc.py`  
**出力**: `data/output/open_gis/lulc_esri_glc_agreement_hanoi_2022_summary.json`、`data/output/open_gis/lulc_esri_glc_confusion_hanoi_2022.csv`

どちらのデータも真値ではないため、**精度（accuracy）ではなく一致度（agreement）**として評価する。

### 7.1 クラス体系対応表

GLC_FCS30D の35クラスと Esri の9クラスは粒度が異なるため、直接比較せず**共通クラス**へ写像して比較した。GLC 側が多対1、Esri 側が1対1になる構造である。

| 共通クラス | GLC_FCS30D（35クラス体系） | Esri（9クラス体系） |
|---|---|---|
| 水域 | 210 Water body | 1 Water |
| 樹林 | 51・52・61・62・71・72・81・82・91・92（常緑/落葉 × 広葉/針葉/混交 × 疎/密） | 2 Trees |
| 農地 | 10 Rainfed・11 Herbaceous cover・12 Orchard・20 Irrigated | 5 Crops |
| 市街地（不透水面） | 190 Impervious surfaces | 7 Built area |
| 草地・低木 | 120・121・122 Shrubland 系、130 Grassland、140 Lichens and mosses、150・152・153 Sparse 系 | 11 Rangeland |
| 裸地 | 200・201・202 Bare areas 系 | 8 Bare ground |
| 湿地 | 181 Swamp・182 Marsh・183 Flooded flat・184 Saline・185 Mangrove・186 Salt marsh・187 Tidal flat | 4 Flooded vegetation |
| 雪氷 | 220 Permanent ice and snow | 9 Snow/ice |

**非対応**: Esri の 0 No Data・10 Clouds、GLC の 0・250（Filled value）は無効値として比較から除外した。写像表はスクリプト内の定数として保持しており、本表と同一内容である。

**共通クラス名は比較のための橋渡しであり、両者の定義が同一であることを意味しない**。特に以下の3組は注意を要する。

- **「市街地（不透水面）」（190 Impervious surfaces ↔ 7 Built area）**: 両者は近い概念だが**定義が一致しない**。GLC の Impervious surfaces は建物・道路・広場といった**人工被覆**を指す。一方 Esri の Built area は道路・鉄道網や密な村落を含む**建造環境（土地利用）**として定義されており、被覆としては透水面を含む区画も市街地に含まれ得る。本比較で観測した約2倍の差（7.3）は、解像度差だけでなく**この定義差も含む**。したがって本表の対応関係は「不透水面率」という単一の物理量を両データで測り比べたものとは読めない。不透水面率を都市構造パラメータとして用いる際は、どちらの定義に基づく値かを明示すること
- **「湿地 ↔ Flooded vegetation」**: 名称が近いだけで**定義が対応していない**（後述 7.4）。一致率は 0.03% で、この共通クラスでの比較は成立していない
- **「草地・低木 ↔ Rangeland」**: GLC 側が8クラスを束ねる粗い対応であり、一致率は極端に低い

### 7.2 解像度の揃え方

GLC_FCS30D（30m）のグリッドを基準とし、Esri（10m）を多数決で集約した。

1. GLC グリッドを縦横3分割した細分グリッド（≒10m、原点は GLC と一致）へ Esri を**最近傍**で再投影する
2. 各 GLC セルに対応する 3×3 = 9 サブセルの**最頻値（多数決）**を採り、GLC グリッド上の Esri クラスとする
3. 同数最頻が複数ある場合は**クラス値の小さい方**を採る（決定的にするため）。該当セルは **2,397**（比較対象の0.06%）

**この集約は近似である**（手法上の限界）。細分グリッドは GLC グリッドと厳密に3×3対応する（原点一致・整数分割）が、**Esri のソース画素とは一致しない**。

| | 画素サイズ |
|---|---|
| Esri 出力（`calculate_default_transform` が決めた10m相当） | 9.279e-05° |
| 細分セル（GLC ÷ 3） | 8.983e-05° |
| 比 | 1.033（Esri 側が約3.3%粗い） |

そのため一部のサブセルが隣接サブセルと同じソース画素を複製し、多数決の票の重みは完全には均一にならない（1ブロックが参照する実 Esri 画素は平均約8.4個。ROI 内画素数比 33,868,965 ÷ 4,015,086 = 8.435 が同じ事実を示す）。系統的に特定クラスへ偏る性質のものではないが、**「グリッド境界のズレが皆無」ではない**点は記録しておく。厳密に揃えるには再投影時に細分グリッドと同じ解像度を明示指定する必要がある。

加えて、**10mでしか現れない少数クラスは集約により失われる**ため、Esri 側の細かいクラスは過小評価される方向にバイアスがかかる。

比較対象は ROI 内 4,015,086 画素のうち **4,015,079 画素**（両者とも有効値である画素）。除外された7画素は Esri 側が共通クラスへ写像できなかった画素である。

### 7.3 空間的一致度

| 指標 | 値 |
|---|---|
| **全体一致率** | **0.6921** |
| **Cohen's kappa** | **0.5155** |
| 一致画素数 | 2,778,829 / 4,015,079 |

共通クラス別（GLC 画素数の降順）:

| 共通クラス | GLC画素数 | Esri画素数 | 一致画素数 | GLC基準の一致率 | Esri基準の一致率 | IoU | 画素数比（Esri/GLC） |
|---|---|---|---|---|---|---|---|
| 農地 | 2,632,422 | 1,686,230 | 1,595,191 | 60.60% | 94.60% | 0.5857 | 0.64 |
| 市街地（不透水面） | 802,422 | 1,577,680 | 786,048 | **97.96%** | **49.82%** | 0.4931 | **1.97** |
| 樹林 | 268,347 | 314,768 | 223,719 | 83.37% | 71.07% | 0.6225 | 1.17 |
| 水域 | 220,886 | 386,629 | 172,914 | 78.28% | 44.72% | 0.3979 | 1.75 |
| 湿地 | 71,029 | 2,497 | 22 | **0.03%** | 0.88% | 0.0003 | 0.04 |
| 草地・低木 | 19,973 | 41,126 | 935 | 4.68% | 2.27% | 0.0155 | 2.06 |
| 裸地 | 0 | 6,149 | 0 | — | 0.00% | 0.0000 | — |
| 雪氷 | 0 | 0 | 0 | — | — | — | — |

「GLC基準の一致率」は GLC がそのクラスとした画素のうち Esri も同じクラスとした割合、「Esri基準の一致率」はその逆である。**最終列は同一グリッド上の画素数比であり、厳密な面積比ではない**（基準グリッドが地理座標系 EPSG:4326 のため画素の地上面積が緯度で変わる。ROI の緯度幅では差は1%未満だが、面積として扱う場合は投影座標系で算出し直すこと）。

**不透水面（市街地）の非対称性が本比較の最大の所見**である。GLC が不透水面とした画素の **97.96%** は Esri も市街地としており、**GLC の不透水面はほぼ Esri の部分集合**になっている。逆に Esri が市街地とした画素のうち GLC も不透水面としたのは **49.82%** にとどまる。Esri の市街地は GLC の **1.97倍** の広がりを持つ。

### 7.4 差の主因（混同行列から）

| 内容 | 画素数 |
|---|---|
| GLC が農地 → Esri が市街地 | **756,445**（GLC農地の28.7%） |
| GLC が農地 → Esri が水域 | 161,994 |
| GLC が農地 → Esri が樹林 | 86,002 |
| GLC が湿地 → Esri が水域 | 39,445 |
| GLC が湿地 → Esri が農地 | 20,156 |
| GLC が樹林 → Esri が市街地 | 19,020 |

- **市街地の差の主因は農地との境界**である。GLC が農地とした画素の28.7%を Esri は市街地に分類している。ハノイ郊外は農地の中に農村集落・散在住宅が混在する景観であり、**10m の Esri はこれらを市街地として拾い、30m の GLC は周囲の農地に埋もれさせている**と解釈できる。解像度の差と、混在画素をどちらに寄せるかという分類方針の差の両方が効いていると考えられる（本データのみからは分離できない）
- **湿地はほぼ一致しない**（一致22画素、IoU 0.0003）。GLC の湿地71,029画素を Esri は水域39,445・農地20,156に振り分けている。GLC の「湿地」（Marsh・Flooded flat 等）と Esri の「Flooded vegetation」は名称が近いだけで**捉えている対象が異なる**ため、この共通クラスでの比較は成立していない
- **水域も Esri が1.75倍広い**。GLC が農地とした161,994画素を Esri は水域としており、紅河の砂州・季節的な湛水域（水田を含む）の扱いの差である可能性がある
- **裸地は GLC 側が ROI 内で0画素**のため比較が成立しない（Esri は6,149画素）

### 7.5 本研究への含意

- **市街地・不透水面として抽出される範囲は、どちらのデータを使うかで約2倍変わる**（画素数比 1.97）。都市構造パラメータとして不透水面率を用いる場合、この選択が結果に直接効く。RQ3（データ制約下での説明力の検証）の観点では、**この不確実性の幅そのものが検討対象になり得る**
- ただしこの差は**解像度差と定義差の両方を含む**（Section 7.1）。GLC の Impervious surfaces は人工被覆、Esri の Built area は建造環境という別々の概念であり、**「同一の不透水面率を2通りに測った値」ではない**。感度分析として扱う際も、両者を同じ物理量の推定値として並べないこと
- **GLC_FCS30D を主候補とする方針は維持する**（解析グリッド30mとの一致、Section 4）。ただし GLC の不透水面は「Esri の市街地の中核部分」に相当し、**郊外の散在市街地を取りこぼしている可能性**が定量的に示された
- **Esri は感度分析の材料として位置づける**。主データを置き換えるのではなく、不透水面率を両データで算出して LST との関係が変わるかを見ることで、結論の頑健性を確認できる
- **湿地・草地・低木のクラスは、両データ間で比較・代替ができない**。これらのクラスを説明変数に用いる場合、データセットを跨いだ解釈は避ける

---

## 8. 注意点

- Dynamic Worldはタイルごとに更新頻度が異なるため、Hanoi ROI全域を同一時期のコンポジットで揃えるには、対象期間内の中央値合成（median composite）などの前処理が必要になる。
- ESA WorldCover・Dynamic World・Esri 10m LULC・GLC_FCS30Dはそれぞれクラス体系が異なる（9〜35クラス）ため、比較する際はクラスマッピング表を作成する必要がある。GLC_FCS30D と Esri 10m の対応表は作成済み（Section 7.1）。**名称が近くても定義が対応しないクラスがある**ため（湿地 ↔ Flooded vegetation の例、Section 7.4）、対応表は名称の類似ではなく実データの一致度で検証すること。
- **異なる解像度のLULCを比較する際は、集約方法が結果に影響する**。本研究では30mグリッドを基準に3×3の多数決で揃えたが、10mでしか現れない少数クラスは失われる（Section 7.2）。
- GLC_FCS30Dはファイルサイズが大きい（経度帯別ZIP、全体で194.4GB）。取得スクリプトでは、HTTP RangeでZIPの必要メンバーのみを取り出す方式で対処済み（Section 5.1）。
- Esri 10m LULC は Blob URL への直アクセスができず、SAS 署名が必須である。**署名済み URL は有効期限つきのため、出典として記録してはならない**（Section 6.1）。
- `Dynamic World`・`ESA WorldCover`は、Hanoi ROIでの取得・クラス分布確認が未実施。取得時には、GBA建物データ取得時と同様の欠測・カバレッジ確認（[gis_data_buildings.md](gis_data_buildings.md) 参照）を行うこと。

---

## 9. 参考ソース

- ESA WorldCover: <https://esa-worldcover.org/en>
- ESA WorldCover GEEカタログ（v200）: <https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200>
- Dynamic World: <https://dynamicworld.app/about/>
- Dynamic World論文（Brown et al., 2022, Scientific Data）: <https://www.nature.com/articles/s41597-022-01307-4>
- GLC_FCS30D（Zenodo v2・最新版、本研究で使用）: <https://zenodo.org/records/15063683>
- GLC_FCS30D（Zenodo 初版）: <https://zenodo.org/records/8239305>
- GLC_FCS30D論文（Zhang et al., 2024, ESSD）: <https://essd.copernicus.org/articles/16/1353/2024/>
- Esri Sentinel-2 10m LULC（AWS Open Data Registry）: <https://registry.opendata.aws/io-lulc/>
- Esri Sentinel-2 10m LULC（Microsoft Planetary Computer STAC、本研究で使用）: <https://planetarycomputer.microsoft.com/dataset/io-lulc-annual-v02>
- Esri Sentinel-2 Land Cover Explorer: <https://livingatlas.arcgis.com/landcoverexplorer/>
- Copernicus Global Land Cover: <https://land.copernicus.eu/en/products/global-dynamic-land-cover>
- OpenStreetMap Wiki, Land use: <https://wiki.openstreetmap.org/wiki/Land_use>
- GlobeLand30: <http://www.globallandcover.com/>
