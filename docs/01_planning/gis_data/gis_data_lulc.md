# 土地利用データ（LULC）の調査・評価

**最終更新**: 2026-07-05  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDVI/NDBI等の衛星由来指標との違い）

---

## 1. 調査目的

本研究では都市構造パラメータとしてNDVI（植生量）・NDBI（市街化）といった衛星由来指標を既に算出しているが、これらは連続値の指標であり、「土地利用の分類（住宅地・商業地・農地・緑地等のカテゴリ）」そのものは表現できない。本資料では、Landsat由来指標を補完する**分類済み土地利用/土地被覆（LULC）データ**のオープンソース候補を調査する。

Hanoi ROIでの実データ取得・採用可否の確定は、本調査を踏まえた別Issueで行う（[task-workflow](../../../.github/task-workflow.md)参照）。

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
- `GLC_FCS30D` / `Dynamic World` / `Esri Sentinel-2 10m LULC` はいずれもPythonスクリプト経由で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（本資料の完成後、優先度をユーザーに確認の上で起票）。

---

## 5. 注意点

- Dynamic Worldはタイルごとに更新頻度が異なるため、Hanoi ROI全域を同一時期のコンポジットで揃えるには、対象期間内の中央値合成（median composite）などの前処理が必要になる。
- ESA WorldCover・Dynamic World・Esri 10m LULC・GLC_FCS30Dはそれぞれクラス体系が異なる（9〜35クラス）ため、比較する際はクラスマッピング表を作成する必要がある。
- GLC_FCS30Dはファイルサイズが大きい（経度帯別ZIP、194.4GB全体）ため、Hanoi ROIを含むタイルのみを特定してダウンロードする方針を取得スクリプトで明確にする。
- いずれのデータセットも実際のHanoi ROIでの取得・クラス分布確認は未実施。取得スクリプト作成時に、GBA建物データ取得時のような欠測・カバレッジ確認（[gis_data_buildings.md](gis_data_buildings.md) 参照）を行うこと。

---

## 6. 参考ソース

- ESA WorldCover: <https://esa-worldcover.org/en>
- ESA WorldCover GEEカタログ（v200）: <https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200>
- Dynamic World: <https://dynamicworld.app/about/>
- Dynamic World論文（Brown et al., 2022, Scientific Data）: <https://www.nature.com/articles/s41597-022-01307-4>
- GLC_FCS30D（Zenodo）: <https://zenodo.org/records/8239305>
- GLC_FCS30D論文（Zhang et al., 2024, ESSD）: <https://essd.copernicus.org/articles/16/1353/2024/>
- Esri Sentinel-2 10m LULC（AWS Open Data Registry）: <https://registry.opendata.aws/io-lulc/>
- Esri Sentinel-2 Land Cover Explorer: <https://livingatlas.arcgis.com/landcoverexplorer/>
- Copernicus Global Land Cover: <https://land.copernicus.eu/en/products/global-dynamic-land-cover>
- OpenStreetMap Wiki, Land use: <https://wiki.openstreetmap.org/wiki/Land_use>
- GlobeLand30: <http://www.globallandcover.com/>
