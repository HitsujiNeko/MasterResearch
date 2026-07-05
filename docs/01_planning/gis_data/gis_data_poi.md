# POI密度データの調査・評価

**最終更新**: 2026-07-05  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義

---

## 1. 調査目的

先行研究S8（Lin et al., 2024, 武漢）では438,700件のPOI（Point of Interest）密度を都市構造パラメータの1つとして使用しており、商業・生活利便施設の集積度は人口密度・土地利用と並ぶ人間活動指標として扱われる。本資料では、無料・オープンソースのPOIデータ候補を調査する（有料APIであるGoogle Places API等は対象外）。

Hanoi ROIでの実データ取得・採用可否の確定は、本調査を踏まえた別Issueで行う。

---

## 2. 候補データ比較表

| 項目 | OpenStreetMap POI | Overture Maps Places | Foursquare Open Source Places | GeoNames | Wikidata |
|---|---|---|---|---|---|
| データソース | コミュニティ編集（`amenity`/`shop`/`tourism`/`leisure`/`office`等のタグ） | Linux Foundation傘下のOverture Maps Foundation（Meta, Microsoft等が参加）が複数ソースを統合 | Foursquareの位置情報プラットフォームのチェックインデータ由来 | 地名辞書（gazetteer）。政府地名委員会・国連等の公的地名データを統合 | クラウドソーシングの知識ベース（Wikipediaと連携） |
| POI件数（全球） | 地域差が大きい（体系的な全球件数は未公表） | 約6,100万件 | 1億件以上 | 約1,200万件（地理的特徴）、うち478万件が居住地 | 数千万件のエンティティ（POIはその一部） |
| カテゴリ数 | タグの自由度が高く体系化されていない（`amenity`だけで100種類以上） | 体系化されたカテゴリ分類あり | 1,000種類以上の場所カテゴリ、20以上の属性 | 9の特徴クラス、645の特徴コード（地名・地形分類が中心で商業施設は手薄） | 任意（Wikidataのプロパティ体系に依存） |
| 更新頻度 | リアルタイム編集 | 定期リリース（月次〜四半期程度） | 月次更新 | 日次アップデート（`allCountries.zip`） | リアルタイム編集 |
| ライセンス | ODbL 1.0 | CDLA Permissive v2.0（OSM由来部分はODbL 1.0が適用される場合あり） | Apache License 2.0 | CC BY 4.0 | CC0（パブリックドメイン） |
| ベトナム/ハノイ カバレッジ | △ コミュニティ編集依存、地域差大 | ✅ 200カ国以上を謳うが実際のハノイでの密度は未確認 | ✅ 200カ国以上に対応を謳うが実際のハノイでの密度は未確認 | ✅ 全球データセット（地名中心、商業POIは手薄） | △ 著名な施設・ランドマークのみ収録される傾向、網羅性は低い |
| 取得方法（スクリプト可否） | ✅ Geofabrik/Overpass API、またはHOTOSM Raw Data API（下記3.6参照） | ✅ Pythonクライアント（`overturemaps download`）またはS3直接DL | ✅ S3上のParquetファイル直接DL、またはPlaces Portal経由（要サインアップ） | ✅ HTTP直接ダウンロード（`allCountries.zip`） | ✅ SPARQLエンドポイント（`query.wikidata.org`）をPythonから呼び出し可能 |

**調査したが対象外としたもの**: `Yelp Open Dataset`はAtlanta・Austin・Boston等の北米固定都市のみを対象とした非商用ライセンスのデータセットであり、ベトナム/ハノイのカバレッジがないため対象外とした。

---

## 3. 候補データ詳細

### 3.1 OpenStreetMap POI

- **タグ体系**: `amenity=*`（飲食店・病院等）、`shop=*`（小売店）、`tourism=*`（観光施設）、`leisure=*`（娯楽施設）、`office=*`（オフィス）の5種類が主要なPOIタグとして扱われる。
- **取得方法**: Geofabrik Vietnam extractから`ogr2ogr`でポイントレイヤを抽出。道路・水域データと同じ取得経路が使える。
- **利点**: 本研究で既に確立している取得パイプライン（Geofabrik + `ogr2ogr`）をそのまま流用できる。
- **懸念点**: POIタグの入力率はコミュニティ編集に依存し、`landuse`タグと同様にHanoi ROIでの実際の網羅性は未調査。特に商業施設のカテゴリ分類の粒度・一貫性はタグ付けする個人に依存する。

### 3.2 Overture Maps Places

- **提供機関**: Overture Maps Foundation（Linux Foundation傘下、Amazon・Meta・Microsoft・TomTom等が参加）
- **データソース**: 複数の商用・オープンソースを統合し、重複排除・住所正規化を実施した上で公開。
- **配布形式**: AWS/Azure上のGeoParquetファイル、公式Pythonクライアント（`overturemaps download -f geoparquet --type=place`）、DuckDBでのSQLクエリも可能。
- **利点**: 単一のOSMコミュニティ編集に依存せず、複数ソースの統合により商業施設のカバレッジがOSM単独より高い可能性がある。カテゴリ体系が統一されており分析に使いやすい。
- **懸念点**: 2023年公開の比較的新しいプロジェクトであり、ベトナム・ハノイでの実際のPOI密度・網羅性は未検証。

### 3.3 Foursquare Open Source Places

- **提供機関**: Foursquare
- **データソース**: Foursquareの位置情報プラットフォーム（チェックイン・検索データ）に基づく独自収集データ
- **配布形式**: AWS S3上のParquetファイル、または Foursquare Places Portal（要サインアップ、アクセストークン発行）
- **利点**: 1億件以上・1,000種類以上のカテゴリを持つ大規模データセットで、Apache 2.0という商用利用も含め最も寛容なライセンス。
- **懸念点**: チェックインアプリの利用者層に依存したデータのため、Hanoi等の非英語圏都市でのカバレッジがOSMやOvertureと同等かは不明。Places Portal経由の場合はサインアップ・トークン発行が必要になる可能性がある（完全に無人でスクリプト化できるか要確認）。

### 3.4 GeoNames

- **提供機関**: GeoNames（コミュニティ + 各国政府地名委員会・国連等の公的データを統合）
- **データソース**: 地名辞書（gazetteer）。9つの特徴クラス・645の特徴コードに分類され、居住地・地形・水域・行政区画等を幅広くカバーする。
- **懸念点**: 商業施設（店舗・飲食店等）よりも地名・居住地・地形の網羅性に重点があり、都市内の細かいPOI密度（商業集積）を表すデータとしては情報量が手薄。都市の主要拠点（駅・病院・学校等の公共施設）の位置確認には有用。

### 3.5 Wikidata

- **提供機関**: Wikimedia Foundation
- **データソース**: クラウドソーシングの知識ベース。SPARQLクエリで地理座標を持つエンティティ（施設・建造物等）を抽出できる。
- **懸念点**: 百科事典的に「特筆性」のある施設（著名な建造物・観光地・大規模施設等）のみが登録される傾向にあり、一般的な商業施設（小規模な店舗・飲食店等）の網羅性は低い。POI密度を面的に評価する用途には不向きで、著名施設の位置確認等の補助用途に限られる。

### 3.6 HOTOSM Raw Data API（OSM取得の代替アクセス手段）

- **提供機関**: Humanitarian OpenStreetMap Team (HOT)
- **位置づけ**: 新規のデータソースではなく、OSMデータを取得するための代替API。GeoJSON/Shapefile/GeoPackage等の複数形式に対応し、`amenity`/`man_made`/`shop`/`tourism`タグに一致するPOIを抽出する専用エクスポート機能を持つ。
- **利点**: **エリアごとのデータ完全性メトリクス（data completeness metrics）を提供する機能がある**。これにより、Hanoi ROIにおけるOSM POIタグの網羅性を定量的に確認できる可能性があり、3.1で述べた「網羅性未確認」という懸念点に対処する手段になりうる。
- **取得方法**: Export Tool APIをプログラムから呼び出し可能（<https://export.hotosm.org/en/v3/learn/api>）。

---

## 4. 推奨方針

- **主候補**: `OpenStreetMap POI`。本研究で確立済みの取得パイプライン（Geofabrik + `ogr2ogr`）をそのまま流用でき、追加の学習コストが低い。取得時は`HOTOSM Raw Data API`のデータ完全性メトリクス機能を使い、Hanoi ROIでのタグ網羅性を確認することを推奨する。
- **比較候補**: `Overture Maps Places`。複数ソースを統合しているためOSM単独よりカバレッジが高い可能性があり、POI密度の妥当性確認（クロスチェック）に有用。取得も`overturemaps`公式クライアントで容易。
- **参考候補**: `Foursquare Open Source Places`。ライセンスが最も寛容で件数も多いが、Hanoiでのカバレッジ実績が不明なため、OSM・Overtureで十分な密度が得られない場合の補完候補として位置づける。
- **補助候補（限定用途）**: `GeoNames`（公共施設の位置確認）、`Wikidata`（著名施設の位置確認）。いずれも面的なPOI密度指標としては網羅性が不足するため、主要な算出データとしては採用しない。
- OSM/Overture/Foursquare/GeoNames/WikidataはいずれもPythonスクリプト経由で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（優先度はユーザーに確認の上で起票。OSMとOvertureの両方を取得し件数・カバレッジを比較する案も含めて相談する）。

---

## 5. 注意点

- POIの「密度」をどう定義するか（全カテゴリ合算 vs カテゴリ別、点密度 vs 最近接距離）は、算出方法設計時に別途検討が必要。
- OSM・Overture・Foursquareのいずれも、Hanoi ROIでの実際のPOI件数・カテゴリ分布は未確認。取得スクリプト作成時に、道路・建物データで実施したような欠測・カバレッジ確認（[gis_data_buildings.md](gis_data_buildings.md) 参照）を行うこと。
- Overture Maps PlacesはOSM由来のデータを含む場合ODbLが適用されるため、実際に採用するデータの出自属性（`sources`フィールド等）を確認し、ライセンス表記を正しく行う必要がある。

---

## 6. 参考ソース

- OpenStreetMap Wiki, Key:amenity: <https://wiki.openstreetmap.org/wiki/Key:amenity>
- Overture Maps Foundation: <https://overturemaps.org/>
- Overture Maps Places Guide: <https://docs.overturemaps.org/guides/places/>
- Overture Maps ライセンス: <https://docs.overturemaps.org/attribution/>
- Foursquare Open Source Places: <https://opensource.foursquare.com/os-places/>
- GeoNames: <https://www.geonames.org/export/>
- Wikidata Query Service: <https://query.wikidata.org/>
- HOTOSM Raw Data API: <https://hotosm.github.io/raw-data-api/>
- 先行研究S8（Lin et al., 2024）構造化要約: [S8_Lin_2024.md](../../04_archive/02_structured_summaries/S8_Lin_2024.md)
