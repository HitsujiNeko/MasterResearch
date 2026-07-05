# 公園近接距離データの調査・評価

**最終更新**: 2026-07-05  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md), [gis_data_lulc.md](gis_data_lulc.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDVI/緑被率との違い）

---

## 1. 調査目的

先行研究S4（建物密度・道路密度）、S5（構成・配置の分離評価）、S6・S8（GVF/SVF等の緑被関連指標）を踏まえ、緑地の「量」（NDVI・緑被率）だけでなく、「公園という都市計画上の緑地空間までの近接性」を都市構造パラメータとして評価する。本資料では、公園ポリゴンとして識別可能なオープンソースデータ候補を調査する。

NDVI・緑被率（`GREEN_COV`）は衛星由来指標として算出済みであり、土地利用データ（[gis_data_lulc.md](gis_data_lulc.md)）の樹木・草地クラスは緑被の「量」を表す。本資料が扱うのは、それらとは異なる「計画された公園空間」としての近接性である。

Hanoi ROIでの実データ取得・採用可否の確定は、本調査を踏まえた別Issueで行う。

---

## 2. 候補データ比較表

| 項目 | OSM 公園データ（`leisure=park`等） | Chen et al. 全球都市緑地データキューブ | ESA WorldCover/Dynamic World（緑被クラス） |
|---|---|---|---|
| データ形式 | ベクタ（ポリゴン） | ラスタ | ラスタ（土地被覆の1クラス） |
| 対象概念 | 計画された公園・レクリエーション用地（都市計画上の緑地） | 都市域内の緑地（NDVI等ベースの検出、公園に限らない） | 樹木・草地全般（公園に限らない） |
| 空間解像度 | ベクタ（解像度の概念なし） | 10m | 10m（[gis_data_lulc.md](gis_data_lulc.md)参照） |
| データ時期 | 継続的にコミュニティ編集 | 2019〜2022年（4年分、10日間隔） | [gis_data_lulc.md](gis_data_lulc.md)参照 |
| ベトナム/ハノイ カバレッジ | ✅ Geofabrik Vietnam extractで取得可 | △ 対象1,028都市にハノイが含まれるか要確認 | ✅ 全球データセット（既調査済み） |
| ライセンス | ODbL 1.0 | 要確認（Figshareで無償公開、CC BY等の明示は未確認） | [gis_data_lulc.md](gis_data_lulc.md)参照 |
| 取得方法（スクリプト可否） | ✅ Geofabrik/Overpass APIで取得可（道路・水域・POIと同じ経路） | ✅ Figshare直接ダウンロード | ✅ 既調査済み |

**調査したが対象外としたもの**:

- `Copernicus Urban Atlas`（2〜4m、Green Urban Areasクラスを詳細区分）: 欧州（EEA38+英国+西バルカン諸国+トルコ）の788機能的都市圏のみが対象で、**ベトナムを含まないため対象外**。
- `World Database on Protected Areas (WDPA)`: 国立公園・自然保護区等の大規模保護区を対象としたデータベースであり、都市内の街区公園（Hoan Kiem公園等）のような都市計画上の公園を捉える設計ではない。再配布制限（部分的な再配布・派生物作成に事前許可が必要）もあり、本研究の目的・ライセンス条件のいずれにも合わないため対象外。
- `UN-Habitat「Open spaces and green areas」`（HDXで公開）: 都市単位の集計統計（緑地面積率・1人当たり緑地面積等）であり、グリッドセル単位の距離算出に必要な個別ポリゴンの空間データではないため対象外。

---

## 3. 候補データ詳細

### 3.1 OSM 公園データ

- **タグ体系**: `leisure=park`（公園）、`leisure=recreation_ground`（球技場等の運動公園）、`leisure=garden`（庭園）、`landuse=recreation_ground`（レクリエーション用地、タグ議論あり）
- **取得方法**: Geofabrik Vietnam extractから`ogr2ogr`でポリゴンレイヤを抽出。道路・水域・POIデータと同じ取得経路が使える。
- **利点**: 本研究で確立済みのOSM取得パイプラインをそのまま流用できる。先行研究でも「`leisure=park`または`landuse=grass`としてマッピングされた公園は高精度で検出できた」との報告があり、都市計画上の公園を直接表現するデータとしては最も概念に合致する。
- **懸念点**: OSMの緑地マッピングは地域・編集者によって網羅性・一貫性にばらつきがあるとされ、Hanoi ROIでの実際の入力率は未調査。

### 3.2 Chen et al. 全球都市緑地データキューブ（High-resolution greenspace dynamic data cube）

- **提供機関**: 研究グループ（Chen et al., 2024, Scientific Data）
- **データソース**: Sentinel-2（10m、約5日再訪、10日間隔コンポジット）
- **提供時期**: 2019〜2022年、世界の主要都市1,028都市を対象
- **配布形式**: Figshareで無償公開
- **懸念点**: 対象1,028都市にハノイが含まれるかは検索だけでは確認できず、取得スクリプト作成時に都市境界データ（shapefile）でハノイの有無を確認する必要がある。また、これは「緑地全般」の検出であり、公園ポリゴンのような個別施設単位の空間情報ではない点に注意（近接距離算出には緑地重心や輪郭からの距離になる）。

### 3.3 ESA WorldCover / Dynamic World（緑被クラス）

- [gis_data_lulc.md](gis_data_lulc.md) で調査済みの土地被覆データセットの樹木・草地クラスを流用する案。公園に限らず全ての緑被をカバーするため、「公園近接距離」としては概念がやや広すぎる（私有庭園・農地・道路脇の緑地帯等も含まれてしまう）。

---

## 4. 推奨方針

- **主候補**: `OSM 公園データ`。都市計画上の「公園」という概念を最も直接的に表現でき、本研究で確立済みの取得パイプライン（Geofabrik + `ogr2ogr`）をそのまま流用できる。
- **比較候補**: `Chen et al. 全球都市緑地データキューブ`。ハノイが対象都市に含まれる場合、Sentinel-2ベースの独立した緑地検出結果としてOSM公園データとのクロスチェックに使える。ただし対象都市への包含が未確認のため、取得スクリプト作成時に最初に確認する。
- **参考データ**: `ESA WorldCover/Dynamic World`の緑被クラスは、公園以外の緑被も含むため、公園近接距離の主要データとしては採用しないが、緑被率（`GREEN_COV`）の算出には引き続き利用する（[gis_data_lulc.md](gis_data_lulc.md)参照）。
- **不採用**: `Copernicus Urban Atlas`（ベトナム非対応）、`WDPA`（概念不一致・再配布制限）、`UN-Habitat統計`（都市単位の集計値でグリッド単位の距離算出に使えない）。
- `OSM 公園データ`と`Chen et al. データキューブ`はPythonスクリプト経由（`ogr2ogr` / Figshare直接DL）で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（優先度はユーザーに確認の上で起票）。

---

## 5. 注意点

- 「公園近接距離」の算出には、公園ポリゴンに対する距離変換（distance transform）またはポリゴン重心・輪郭からの最近接距離計算が必要。
- OSMの`leisure=park`と`landuse=recreation_ground`は意味が異なる（前者は主に景観的な公園、後者は運動施設寄り）ため、どちらを「公園」として含めるかを算出方法設計時に明確にする。
- いずれのデータセットも実際のHanoi ROIでの取得・値域確認は未実施。取得スクリプト作成時に、道路・建物データで実施したような欠測・カバレッジ確認（[gis_data_buildings.md](gis_data_buildings.md) 参照）を行うこと。

---

## 6. 参考ソース

- OpenStreetMap Wiki, Tag:leisure=park: <https://wiki.openstreetmap.org/wiki/Tag:leisure=park>
- OpenStreetMap Wiki, Tag:leisure=recreation_ground: <https://wiki.openstreetmap.org/wiki/Tag:leisure=recreation_ground>
- High-resolution greenspace dynamic data cube（Chen et al., 2024, Scientific Data）: <https://www.nature.com/articles/s41597-024-03746-7>
- Copernicus Urban Atlas: <https://land.copernicus.eu/en/products/urban-atlas>
- World Database on Protected Areas: <https://www.protectedplanet.net/en/thematic-areas/wdpa>
- UN-Habitat, Open spaces and green areas（HDX）: <https://data.humdata.org/dataset/open-spaces-world>
