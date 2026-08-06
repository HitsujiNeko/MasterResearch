# 水域データ（近接距離・面積率）の調査・評価

**最終更新**: 2026-08-06  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDWIとの違い）

---

## 1. 調査目的

本研究で算出済みの水域関連の指標は、衛星由来のNDWI（水域・湿潤域指標）のみである。NDWIは連続値・単一時点の分光指標であり、水域の物理的な広がりや位置関係を直接表すものではない。都市構造パラメータとしては、以下の2種類の水域関連指標が候補となる。

- **水域近接距離**（`WATER_DIST`等）: 最近接の水域までの距離。先行研究S3・S5・S6で扱われる`PW`（距離変数）に相当。
- **水域面積率**（`WATER_COV`）: グリッド内の水域面積割合。

両指標は同じ水域データソース（水域ポリゴン/マスク）を元に、異なる算出方法（距離変換 vs 面積集計）を適用して得られるため、本資料では候補データの調査を1ファイルにまとめ、推奨方針のみ指標ごとに分けて記載する。

Hanoi ROIでの実データは未取得である。採否は [urban_structure_parameters.md](../urban_structure_parameters.md) を正本とし、本資料では扱わない。

---

## 2. 候補データ比較表

| 項目 | JRC Global Surface Water (GSW) | OSM 水域データ（`natural=water`/`waterway`） | HydroLAKES / HydroRIVERS | ESA WorldCover 水域クラス | OSM Water Layer（東大版ラスタ） |
|---|---|---|---|---|---|
| データ形式 | ラスタ（複数の主題図レイヤ） | ベクタ（ポリゴン/ライン） | ベクタ（ポリゴン/ライン） | ラスタ（土地被覆の1クラス） | ラスタ（OSMから生成） |
| 空間解像度 | **30m**（本研究グリッドと一致） | ベクタ（解像度の概念なし） | ベクタ（湖沼は10ha以上のみ収録） | 10m | 約90m（3 arc-sec） |
| データ時期 | 1984〜2024年（月次履歴あり） | 継続的にコミュニティ編集 | 基準年は2016年前後（HydroLAKES v1.0時点） | 2020・2021年の2時点 | OSMの抽出時点（更新は不定期） |
| 恒常水域/季節水域の区別 | ✅ occurrence/seasonality/recurrenceレイヤで区別可能 | △ タグでは区別されない | △ 湖沼データのみ、季節変動は非対応 | ❌ 区別なし（Permanent water bodiesクラスのみ） | ❌ 区別なし |
| ベトナム/ハノイ カバレッジ | ✅ 全球データセット | ✅ Geofabrik Vietnam extractで取得可（道路と同じ経路） | △ 10ha未満の小規模な池・湖は収録対象外 | ✅ 全球データセット | ✅ 全球データセット |
| ライセンス | 無償公開（Copernicus Programme規則） | ODbL 1.0 | CC BY 4.0 | CC BY 4.0 | 要確認（OSM由来のため実質ODbL相当） |
| 取得方法（スクリプト可否） | ✅ GEE/Planetary Computer/JRCポータル直接DL | ✅ Geofabrik/Overpass API | ✅ HydroSHEDSポータル直接DL | ✅ GEE/AWS Open Data | ✅ 直接ダウンロード（東大サーバー） |

---

## 3. 候補データ詳細

### 3.1 JRC Global Surface Water (GSW)

- **提供機関**: European Commission Joint Research Centre (JRC)
- **データソース**: Landsat時系列（1984〜2024年）を解析し、水域の出現頻度・季節性・変遷を定量化
- **主題図レイヤ**: Occurrence（出現頻度）、Recurrence（再現性）、Seasonality（季節性）、Transitions（変遷分類）、Maximum Water Extent（最大水域範囲）等
- **解像度**: 30m（**本研究の解析グリッドとネイティブ解像度が一致**）
- **利点**: 40年分のLandsatアーカイブに基づくため、恒常水域と季節水域（雨季の一時的な冠水域等）を区別できる。ベトナムのモンスーン気候下では、季節的に冠水する水田・低地と恒常的な湖沼を区別できる点が重要。
- **配布形式**: GEEカタログ（`JRC/GSW1_4/GlobalSurfaceWater`等）、Microsoft Planetary Computer、JRCデータポータル直接ダウンロード

### 3.2 OpenStreetMap 水域データ（`natural=water`, `waterway=*`）

- **データソース**: OSMコミュニティ編集
- **タグ体系**: `natural=water`（湖沼等の水域ポリゴン）、`waterway=river/canal/stream`（河川・水路のライン）
- **配布形式**: Geofabrik Vietnam extractから`ogr2ogr`で抽出（道路データ [gis_data_roads.md](gis_data_roads.md) と同じ取得経路）
- **利点**: Hoan Kiem湖やTay湖のような都市中心部の著名な湖沼が個別ポリゴンとして命名・記録されている可能性が高く、JRC GSW（30mラスタ）では捉えにくい小規模な池・水路も含まれうる。
- **懸念点**: `landuse`タグと同様、`water`関連タグの網羅性はコミュニティ編集に依存し、Hanoi ROIでの実際の入力率は未調査。

### 3.3 HydroLAKES / HydroRIVERS

- **提供機関**: HydroSHEDS（McGill大学等の研究グループ）
- **内容**: HydroLAKESは全球の湖沼・貯水池（約140万件）のポリゴン、HydroRIVERSは全球の河川ネットワーク（約850万リーチ、総延長約3,590万km）
- **懸念点**: HydroLAKESは**表面積10ha以上の水域のみを収録**しており、都市内の小規模な池・調整池は対象外になる可能性が高い。Hanoi中心部の小規模水域を捉えるには、OSMデータとの併用が必要。

### 3.4 ESA WorldCover 水域クラス

- [gis_data_lulc.md](gis_data_lulc.md) で調査済みの土地被覆データセットの「Permanent water bodies」クラスを流用する案。解像度10mだが、恒常水域と季節水域を区別しない。

### 3.5 OSM Water Layer（東京大学版ラスタ）

- **提供機関**: 東京大学（山田研究室）
- **内容**: OSMの`planet.pbf`から抽出した水域ポリゴンを約90m（3 arc-sec）グリッドのラスタ化したデータセット
- **位置づけ**: OSMベクタデータをすでにラスタ化した簡易版。本研究では独自に`ogr2ogr`でOSM抽出済みのため、追加採用の必要性は低い。

---

## 4. 推奨方針: 水域近接距離（`WATER_DIST`）

- **主候補**: `JRC Global Surface Water`。解像度が本研究グリッド（30m）とネイティブに一致し、40年分のLandsat時系列から恒常水域と季節水域を区別できる点が、モンスーン気候のハノイでは特に重要。
- **補完候補**: `OSM 水域データ`。JRC GSW（30mラスタ）では捉えにくい都市中心部の小規模な池・水路までの距離を補完する。距離算出はラスタよりベクタの方が正確なため、小規模水域の近接距離はOSMベクタの方が適する場合がある。
- **参考データ**: `HydroLAKES`は10ha以上の水域のみのため、大規模湖沼（Tay湖等）までの距離の検証用に位置づける。

## 5. 推奨方針: 水域面積率（`WATER_COV`）

- **主候補**: `JRC Global Surface Water`。グリッド内面積割合の算出には、ネイティブ30m解像度でセル単位のOccurrence値をそのまま利用でき、リサンプリングによる誤差が生じにくい。
- **補完候補**: `OSM 水域データ`。JRC GSWが30mグリッドで捉えきれない小規模水域の面積を補完する場合に使う。ただし面積率算出でベクタとラスタを混在させると二重カウント等の不整合が生じうるため、採用する場合は算出ロジックを明確に設計する必要がある。
- **不採用**: `ESA WorldCover水域クラス`は恒常/季節の区別がなく、JRC GSWで代替可能なため優先度は低い。

---

## 6. 注意点

- 「最近接水域までの距離」を算出するには、水域ポリゴン/マスクに対する距離変換（distance transform）処理が必要。JRC GSWの場合はどの主題図レイヤ（Occurrence何%以上を「水域」とみなすか等の閾値）を採用するかで距離・面積の算出結果が変わるため、閾値の根拠を明記する必要がある。
- ハノイは雨季に水田・低地が季節的に冠水するため、恒常水域のみで算出するか、季節水域も含めるかで結果が大きく変わりうる。RQ1-RQ3のどの分析に使うかに応じて使い分けを検討する。
- 近接距離と面積率で同一データソース（JRC GSW）を使う場合、取得スクリプトは共通化できる（同じ水域マスクから距離変換と面積集計をそれぞれ実行する）。
- いずれのデータセットも実際のHanoi ROIでの取得・値域確認は未実施。取得スクリプト作成時に確認する。`JRC Global Surface Water`と`OSM水域データ`はPythonスクリプト経由（GEE / `ogr2ogr`）で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（優先度はユーザーに確認の上で起票）。

---

## 7. 参考ソース

- JRC Global Surface Water: <https://global-surface-water.appspot.com/>
- JRC GSW GEEカタログ: <https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater>
- JRC GSW（Planetary Computer）: <https://planetarycomputer.microsoft.com/dataset/jrc-gsw>
- OpenStreetMap Wiki, Tag:natural=water: <https://wiki.openstreetmap.org/wiki/Tag:natural=water>
- OpenStreetMap Wiki, Key:waterway: <https://wiki.openstreetmap.org/wiki/Key:waterway>
- HydroSHEDS（HydroLAKES/HydroRIVERS）: <https://www.hydrosheds.org/>
- OSM Water Layer（東京大学）: <https://hydro.iis.u-tokyo.ac.jp/~yamadai/OSM_water/>
