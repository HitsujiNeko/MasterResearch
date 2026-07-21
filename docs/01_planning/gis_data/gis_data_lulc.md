# 土地利用データ（LULC）の調査・評価

**最終更新**: 2026-07-21  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDVI/NDBI等の衛星由来指標との違い）

---

## 1. 調査目的

本研究では都市構造パラメータとしてNDVI（植生量）・NDBI（市街化）といった衛星由来指標を既に算出しているが、これらは連続値の指標であり、「土地利用の分類（住宅地・商業地・農地・緑地等のカテゴリ）」そのものは表現できない。本資料では、Landsat由来指標を補完する**分類済み土地利用/土地被覆（LULC）データ**のオープンソース候補を調査する。

主候補の`GLC_FCS30D`はHanoi ROIでの実データ取得・確認を完了している（Section 5）。比較候補（`Dynamic World` / `Esri Sentinel-2 10m LULC`）の取得とクラス体系の対応関係の確認は未実施。

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
- **副候補（時間解像度が必要な場合）**: `Dynamic World`（Landsat観測日に近いSentinel-2シーンから取得、準リアルタイム）または`Esri Sentinel-2 10m LULC`（年次コンポジットで扱いやすい）。いずれも10mのためGLC_FCS30Dとのクロスチェック用に位置づける。
- **参考データ**: `ESA WorldCover`（静的だが分類が安定、妥当性確認用）。`OSM landuse`は面的な網羅性が未確認のため、特定施設の位置確認等の補助用途に留める。
- **不採用**: `Copernicus Global Land Cover`（解像度100mが粗すぎる）、`GlobeLand30`（アクセス手段がスクリプト化困難でライセンスも不明瞭）。
- `GLC_FCS30D` の取得スクリプトは作成済みで、Hanoi ROIでのデータ取得・確認も完了している（Section 5）。`Dynamic World` / `Esri Sentinel-2 10m LULC` の取得とクラス体系の対応関係の確認は、別タスクとして切り出す。

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

## 6. 注意点

- Dynamic Worldはタイルごとに更新頻度が異なるため、Hanoi ROI全域を同一時期のコンポジットで揃えるには、対象期間内の中央値合成（median composite）などの前処理が必要になる。
- ESA WorldCover・Dynamic World・Esri 10m LULC・GLC_FCS30Dはそれぞれクラス体系が異なる（9〜35クラス）ため、比較する際はクラスマッピング表を作成する必要がある。
- GLC_FCS30Dはファイルサイズが大きい（経度帯別ZIP、全体で194.4GB）。取得スクリプトでは、HTTP RangeでZIPの必要メンバーのみを取り出す方式で対処済み（Section 5.1）。
- GLC_FCS30D以外のデータセットは、Hanoi ROIでの取得・クラス分布確認が未実施。取得時には、GBA建物データ取得時と同様の欠測・カバレッジ確認（[gis_data_buildings.md](gis_data_buildings.md) 参照）を行うこと。

---

## 7. 参考ソース

- ESA WorldCover: <https://esa-worldcover.org/en>
- ESA WorldCover GEEカタログ（v200）: <https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200>
- Dynamic World: <https://dynamicworld.app/about/>
- Dynamic World論文（Brown et al., 2022, Scientific Data）: <https://www.nature.com/articles/s41597-022-01307-4>
- GLC_FCS30D（Zenodo v2・最新版、本研究で使用）: <https://zenodo.org/records/15063683>
- GLC_FCS30D（Zenodo 初版）: <https://zenodo.org/records/8239305>
- GLC_FCS30D論文（Zhang et al., 2024, ESSD）: <https://essd.copernicus.org/articles/16/1353/2024/>
- Esri Sentinel-2 10m LULC（AWS Open Data Registry）: <https://registry.opendata.aws/io-lulc/>
- Esri Sentinel-2 Land Cover Explorer: <https://livingatlas.arcgis.com/landcoverexplorer/>
- Copernicus Global Land Cover: <https://land.copernicus.eu/en/products/global-dynamic-land-cover>
- OpenStreetMap Wiki, Land use: <https://wiki.openstreetmap.org/wiki/Land_use>
- GlobeLand30: <http://www.globallandcover.com/>
