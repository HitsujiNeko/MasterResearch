# 分析ワークフロー仕様書

**最終更新**: 2026-08-06  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md), [calc_urban_params_guide.md](calc_urban_params_guide.md), [available_gis_data.md](../01_planning/available_gis_data.md), [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md), [CodingRule.md](CodingRule.md)  
**前提知識**: RQ1–RQ3の理解（research_guide.md § 3–5 参照）

---

## 概要

本ドキュメントは、「ベトナム主要都市を対象とした地表面温度と都市構造の関係性評価」における  
**データ前処理 → 都市構造パラメータ算出 → モデル構築 → 評価・可視化** の全工程を定義する。

実装を始める前に各工程の入出力・手法選定の根拠を明確にし、  
再現性のある研究プロセスを確立することを目的とする。

### 現在の優先実行範囲（2026-04-21）

研究の分析シナリオは、現在次の 3 段階で整理している。

1. `Satellite Only`: 衛星指標のみ
2. `Limited`: 衛星指標 + オープンソース GIS
3. `Full`: 衛星指標 + オープンソース GIS + 測量由来 GIS

このうち、**Satellite Only は初期成立済み**であり、2023-07-07、2023-07-23、2024-11-30 の 3 観測でベースライン結果が得られている。  
現在の優先実行範囲は、**Limited / Full に接続するための GIS データ仕様整理、公開建物データのカバレッジ QA、都市構造パラメータ算出設計の更新**である。

直近の優先事項:

1. `Satellite Only` の複数観測日結果を基準線として固定する。
2. `available_gis_data.md` を根拠に、`Limited` で使う公開 GIS の主ソース候補を比較し、建物データの有効範囲を確定する。
3. 測量由来 GIS の利用可能レイヤと制約を整理し、`Full` の入力仕様を明確化する。
4. `calc_urban_params.py` の入出力仕様を、公開 GIS / 測量 GIS のどちらにも適用できる形へ更新する。

現在の主要実装:

- `src/analysis/build_satellite_only_dataset.py`
- `src/analysis/analysis_rq3_satellite_only.py`
- `src/preprocessing/extract_geofabrik_roads_hanoi.py`
- `src/preprocessing/fetch_microsoft_buildings_hanoi.py`

---

## フロー全体像

```text
[RawData]
  │
  ├─ LSTラスタ (GeoTIFF)  ────────────────────────────────────┐
  │   Landsat 8 / SMW法 / GEE算出                             │
  │   ※GEEでROI（行政区画）クリップ済み                       │
  │                                                           │
  ├─ GISベクタ (GPKG/WGS84)                                  │
  │   公開GIS（OSM / Microsoft / Google等）または           │
  │   測量DGN → マージ済みGPKG（正本: EPSG:5897）            │
  │   ※データソースごとに空間範囲と完全性が異なる            │
  │                                                           │
  └─ 衛星指標 (GEE算出)                                      │
      NDVI / NDBI / NDWI                                    │
                                                             ▼
                                                       [Step 2]
                                                   空間範囲の整理
                                             ┌─────────────────────┐
                                             │ LST: ROI全体       │
                                             │ GIS: ROI全体または │
                                             │      中心部矩形範囲 │
                                             │ → シナリオ別に対象 │
                                             │   範囲を定義する   │
                                             └─────────────────────┘
                                                           │
                                                           ▼
                                                     [Step 3]
                                                 都市構造パラメータ算出
                                                 (ラスタ化・ゾーン統計)
                                                           │
                                                           ▼
                                                     [Step 4]
                                                   分析用データセット
                                                (LSTグリッド × 説明変数)
                                                           │
                                 ┌─────────────────────────┼─────────────────────────┐
                                 ▼                         ▼                         ▼
                               [RQ1]                   [RQ2]                     [RQ3]
                            支配的変数               空間スケール                データ制約下
                           MLR + RF/GBDT              近傍変数比較               OSM vs 測量
                           + SHAP値                                               比較評価
```

---

## Step 1: データ前処理（GISデータ）

### 1.1 処理済み状況

GIS データ前処理は、**測量由来 GIS** と **オープンソース GIS** を分けて整理する。

#### 1.1.1 測量由来 GIS（survey GIS）

| 処理 | 入力 | 出力 | スクリプト | 状態 |
|------|------|------|-----------|------|
| DGN統合 | `整備データ/Vector_*/` | `整備データ/merge/merge_*.gpkg` | `src/preprocessing/merge_vector_fixed.py` | ✅ 完了 |
| 残ファイル追加 | `整備データ/Vector_DC/` | `整備データ/merge/merge_DC.gpkg` | `src/preprocessing/append_remaining_dgn.py` | ✅ 完了 |

**整備済みデータの現況**（詳細: [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)）

| 種類 | レイヤ内容 | 地物数 | 完全性 |
|------|-----------|--------|--------|
| CS（等高線） | 等高線（標高値） | 20,110 | 100% |
| DC（建物） | 建物ポリゴン | 460,085 | 98.75% |
| DH（標高・地形候補） | 標高点・等高線候補 | 104,317 | 100% |
| GT（道路） | 道路ライン | 209,077 | 100% |
| RG（境界） | 行政境界 | 721 | 100% |
| TH（水系候補） | 水系候補 | 55,269 | 100% |
| TV（植生） | 植生ポリゴン | 127,791 | 98.75% |

### 1.2 欠落データ（既知の制約）

| ファイル | 原因 | 影響 |
|---------|------|------|
| F-48-68-(251-c)_2018_DC.dgn | 処理ハング | DCデータの1区画欠落 |
| F-48-80-(11-c)_2018_TV.dgn | DGNv8形式（GDAL非対応） | TVデータの1区画欠落 |

#### 1.2.1 オープンソース GIS（Limited シナリオ候補）

`Limited` では、現時点で次の公開データを候補とする。

| データ | 主用途 | 現状 | 備考 |
|------|------|------|------|
| OpenStreetMap / Geofabrik | 道路、補助的な建物 | 候補確定 | 道路の主ソース。建物利用時は QA が必要 |
| Microsoft GlobalMLBuildingFootprints | 建物フットプリント | 保留 | Hanoi ROI 西側欠落（105.47°E境界）を確認済み。単独主ソースとして採用しない |
| GlobalBuildingAtlas | 建物フットプリント＋高さ（ML推定） | **採用確定・取得済み** | WFS（`lod1_global`）でHanoi ROI全域を取得済み。Microsoft欠落域でも実データを確認しカバレッジ欠落を解消。CC BY-NC 4.0（学術可）。`Limited` シナリオの建物主ソース |
| Google Open Buildings V3 | 建物フットプリント | 第2候補 | Vietnam明記。CC BY 4.0。建物高さなし（V3）。GBA代替として利用 |
| GHSL / WSF | 粗い built-up 補助指標 | 補助候補 | 精密な建物輪郭の代替ではない |

> 根拠は [available_gis_data.md](../01_planning/available_gis_data.md) に整理している。  
> Microsoft 建物データは、Hanoi ROI 西側で `105.46875E` 付近を境に欠落が確認された（現在の主ソースは GBA）。  
> `BUILD_COV = 0` / `BUILD_DEN = 0` を建物不存在として解釈する前に、建物データの有効カバレッジ内かを必ず確認する。  
> **`BUILD_COV = 0` はカバレッジが十分な領域でも建物の不存在を意味しない**。ラスタ化の解像度より小さい建物は被覆率に寄与しないため、建物の有無は `BUILD_DEN` で判定する（詳細は [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) セクション 3.5）。

---

## Step 2: データ空間範囲の整理

### 2.1 LSTデータ現況

- **算出手法**: SMW法（Ermida et al., 2020）
- **衛星**: Landsat 8（30m解像度）
- **算出ツール**: Google Earth Engine（`src/gee/gee_calc_LST.py`）
- **出力**: `data/satellite/lst/<city_id>/*.tif`（°C単位）
- **空間範囲**: **GEE算出時にROI（行政区画ポリゴン）でクリップ済み** → 追加のクリップ処理は不要
- **詳細**: [gee_calc_LST.md](gee_calc_LST.md)

### 2.2 空間範囲の構造（重要）

LST と GIS データでは空間範囲が異なる。この非対称性を理解したうえで、シナリオ別に分析範囲を決定する。

| データ | 空間範囲 | 備考 |
|--------|---------|------|
| **LST** | ROI（行政区画全体） | GEEで算出時にクリップ済み |
| **GISデータ（測量）** | ハノイ中心部の矩形範囲 | 測量図幅の格子範囲。ROIより狭い |
| **GISデータ（公開）** | ROI全体または取得範囲全体 | OSM / Microsoft / Google Open Buildings など。データごとに有効範囲が異なる |
| **衛星指標**（NDVI等） | LSTと同一（ROI全体） | GEEで同時算出 |

#### 2.2.1 実測BBox（2026-03-03）

`src/analysis/analyze_spatial_extents.py` により、ROI（行政区画）とGIS（測量）データの空間範囲を確認した。
出力: `data/output/spatial_extent_report.json`

| 対象 | BBox（minLon, minLat, maxLon, maxLat） | 解釈 |
|------|----------------------------------------|------|
| ROI（Hà Nội） | [105.2881, 20.5645, 106.0201, 21.3852] | 行政区画としてのハノイ全域 |
| GIS（RG: merge_RG.gpkg をその場でWGS84換算） | [105.7834, 20.9949, 105.8668, 21.0991] | 測量図幅（中心部）の代表的範囲（分析の主要対象域） |
| GIS（CS: merge_CS.gpkg をその場でWGS84換算） | [105.7831, 20.9939, 105.8671, 21.1000] | 上と整合（中心部範囲） |

**注意（重要）**:

- 旧 `merge_DC_wgs84.gpkg` や `merge_GT_wgs84.gpkg` 等の一部レイヤでは、BBoxが不自然に広くなる（外れ値ジオメトリを含む可能性）。
- そのため、**DC/GT/TV等の「ファイル全体BBox」を分析範囲の定義に使わず**、RG/CSなど整合が取れているデータの範囲、またはROI内でのフィルタ後の範囲を用いる。
- 旧変換成果物での外れ値実例: `merge_DC_wgs84.gpkg`（elements）に **緯度9度台**の地物が混入（`feature_index: 59545`, bbox: (105.00177, 9.04560, 105.00179, 9.04561)）。

```text
行政区画ROI（全体）
┌────────────────────────────────┐
│  ～外縁部（農地・山岳）～        │
│                                │
│  ┌──────────────────────┐      │
│  │  測量図幅範囲（矩形）  │      │
│  │  = GISデータの有効域  │      │
│  │  = 分析の主要対象域   │      │
│  └──────────────────────┘      │
│                                │
└────────────────────────────────┘
```

### 2.3 分析時の空間範囲マスク方針

**分析用データセット（Step 4）構築時に、シナリオごとに空間マスク方針を切り替える。**

具体的には：

- `Satellite Only`: ROI 全体を対象にする
- `Limited`: 公開 GIS の有効カバレッジと ROI の共通部分を対象にする。建物データが ROI 全域を覆わない場合は、カバレッジマスクまたは対象範囲制限を明示する
- `Full`: RG/CS 等で定義した測量 GIS 有効域を対象にする
- 測量 GIS では、DC/GT/TV 等の外れ値ジオメトリが全体BBoxを歪める可能性があるため、「分析対象域内に限定して集計」する

**ピクセル値の区別**（GEE算出時に既に設定済み）:

| 値 | 意味 |
|----|------|
| NaN | 雲マスク（GEEのcloud_mask関数による） |
| 実数値 | 有効LST（°C）|

NoData（-9999等）は設定されていない。分析時にNaNを欠損として扱う。

---

## Step 3: 都市構造パラメータ算出

### 3.1 パラメータ一覧

都市構造パラメータは**衛星由来**と**GIS由来**に分かれる。個別のパラメータの一覧は次の2つを正本とし、**本節では再掲しない**（衛星由来／GIS由来の区分も新ドキュメントの節構成に対応する）。

| 内容 | 正本 |
|---|---|
| どの説明変数を採用するか（採否ステータス・概念定義・単位・根拠文献・対応RQ） | [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) |
| 採用済みパラメータの出力仕様（列名・算出方法・実装状況） | [calc_urban_params_guide.md](calc_urban_params_guide.md) 6章 |

データソースの候補比較・空間解像度・ライセンスは [available_gis_data.md](../01_planning/available_gis_data.md) を参照する。

> どのデータソースを採用するかはシナリオに依存する。  
> `Limited` では公開 GIS のみ、`Full` では公開 GIS と測量 GIS の両方を扱う。  
> ただし、測量GIS（DH / TV）の意味と利用方法はまだ整理途中であり、確定していない算出方法は今後の確認結果に応じて更新する。水系レイヤ（TH）は、水域関連のパラメータを採用していないため算出対象ではない。

### 3.2 グリッド設計

LSTの空間解像度（30m）を基準としつつ、**30m / 90m / 300m の3スケール**でグリッドを作成し、都市構造パラメータをスケールごとに集計する。

| 項目 | 設定 |
|------|------|
| **グリッド解像度** | 30m / 90m / 300m の3スケール（既定）。スケール間の比較が RQ2 の評価軸となる |
| **CRS** | 入力/出力はWGS84（EPSG:4326）。ただし面積・長さ計算は投影座標系（m単位）で実施 |
| **集計方法** | 各グリッドセル内の面積・長さ・個数を空間集計。被覆率は補助グリッド（既定10m）を経由する |
| **出力形式** | パラメータセットごと・スケールごとの GeoPackage（`cell_id` キーの属性テーブル）。列構成は [calc_urban_params_guide.md](calc_urban_params_guide.md) 6章 |

> **スケールは列名のサフィックスではなくディレクトリ階層で表現する**（旧実装の `NDVI_30` のような `_<scale>` サフィックスは廃止した）。  
> 3スケールの選択は、Step 3.3 の近傍リング設計とは別の軸である（下記）。

### 3.3 近傍変数の設計（RQ2対応）

Osborne & Alvares 2019（[S5](../04_archive/02_structured_summaries/S5_Osborne_2019.md)）の近傍リング設計を参考に、  
各パラメータを**複数の空間スケール**で算出し、空間スケール依存性を評価する。

> **本節は未実装の設計案である（採否・詳細は未確定）。** 以下の `_0` / `_30_60` 等のリング型
> サフィックスは現行の出力仕様ではない。実装済みの出力はスケール別ディレクトリに分けた
> パラメータテーブル（列名にスケールを含まない）であり、正本は
> [calc_urban_params_guide.md](calc_urban_params_guide.md) 6章である。
> 5章の分析ケース（5.2）に現れるリング型の列名も同様に設計案として読むこと。

| スケール名 | 範囲 | 変数名サフィックス | 例（建物被覆率） |
|----------|------|-----------------|---------------|
| 即時効果 | 当該ピクセル（30m） | `_0` | `BUILD_COV_0` |
| 近傍効果1 | 30–60m リング | `_30_60` | `BUILD_COV_30_60` |
| 近傍効果2 | 60–90m リング | `_60_90` | `BUILD_COV_60_90` |
| 近傍効果3 | 90–120m リング | `_90_120` | `BUILD_COV_90_120` |

> **根拠**: S5では30m解像度において「近傍効果 > 即時効果（相関0.956）」が示されており、  
> 近傍変数の導入はRQ2（空間スケールの影響評価）の中核をなす。

**実装方針**:

- `scipy.ndimage` または `astropy.convolution` を使用したリング形状カーネルによる畳み込み
- または `rasterio` + `shapely` による距離リング内の空間集計

### 3.4 パラメータ算出スクリプト設計

| スクリプト | 処理内容 | 入力 | 出力 |
|----------|---------|------|------|
| `src/gee/gee_calc_satellite_indices.py` | 衛星由来指標（NDVI/NDBI/NDWI）の算出 | Landsat 8バンド（GEE） | `data/satellite/indices/*.tif` |
| `src/analysis/urban_params/canonical_grid.py` | 全シナリオ共通の正準グリッド生成（`cell_id` 採番） | 解析範囲レイヤ（ROI） | `data/output/grid/grid_<city_id>.gpkg`（`grid_30m` / `grid_90m` / `grid_300m`） |
| `src/analysis/urban_params/`（`python -m`） | GIS由来・衛星由来パラメータのグリッド集計。**パラメータセット単位**に出力する | 公開 GIS または `整備データ/merge/merge_*.gpkg` + 衛星指標ラスタ + 正準グリッド | `data/output/params/<city_id>/<scale>m/<テーブル名>.gpkg`（`cell_id` キーの属性テーブル） |
| `src/analysis/build_dataset.py` | 指定テーブル群の `cell_id` 結合と品質管理列の導出 | パラメータテーブル + 正準グリッド | `data/output/datasets/dataset_<name>_<city_id>_<scale>m.gpkg` |
| `src/analysis/calc_neighborhood_vars.py` | 近傍変数（30/60/90/120m）の算出。**未実装**（3.3 の設計案に対応） | パラメータテーブルまたは結合済みデータセット（`cell_id` キー） | 未定（`cell_id` キーのテーブルとする） |
| `src/analysis/merge_dataset.py` | LSTと全説明変数の結合。**未実装** | LSTクリップ + パラメータCSV | `data/output/analysis_dataset.csv` |

---

## Step 4: 分析用データセット構築

### 4.1 データセット構造

分析用データセットは、LST と Step 3 で算出した都市構造パラメータをセル単位で結合したものである。**都市構造パラメータ側の列構成は [calc_urban_params_guide.md](calc_urban_params_guide.md) 6章を正本とする**。

以下は結合後のデータセットが取り得る列の一覧である。LST との結合を行う `merge_dataset.py` は未実装であり（3.4）、現時点で実在するのは `build_dataset.py` が出力するスケール別のデータセット（`LST` 列を含まない）である。

| 列名 | 型 | 内容 | 出どころ |
|------|-----|------|------|
| `cell_id` | int | 正準グリッドのセルID（`row * 1000000 + col`）。**同一スケール内でのみ一意** | 正準グリッド |
| `lon` | float | グリッドセル中心経度（WGS84） | 正準グリッド |
| `lat` | float | グリッドセル中心緯度（WGS84） | 正準グリッド |
| `LST` | float | 地表面温度（°C） | 未実装（`merge_dataset.py`） |
| `NDVI` / `NDBI` / `NDWI` | float | 衛星由来指標 | `idx_*` テーブル |
| `BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX` | float | 建物パラメータ | `build_gba` または `build_dc` テーブル |
| `ROAD_DEN` | float | 道路密度 | `road_osm` または `road_gt` テーブル |
| `ELEV_MEAN` / `ELEV_VALID_RATIO` | float | 標高パラメータ | `elev_fabdem` テーブル |
| `IN_ANALYSIS_AREA` | int | 解析範囲レイヤ内のセルか | `mask_roi` テーブル |
| `VALID_GIS_MASK` | int | 少なくとも1つのGIS指標が有効なセルか | 結合時に導出（**条件付き**） |
| `VALID_SATELLITE_MASK` | int | 少なくとも1つの衛星指標が有効なセルか | 結合時に導出（**条件付き**） |
| `MISSING_REASON` | str | GIS指標の主要欠損理由（`none` / `no_gis_feature` / `missing_gis_data`） | 結合時に導出（**条件付き**） |

**列名にスケールのサフィックスは付かない。** スケールはディレクトリ階層とファイル名で表現する。

**出力される列は結合したテーブルによって変わる。** 品質管理列は**判定材料となる列がある場合のみ付与される**（全セル0の列を出すと「確認したうえで無効と判定した」と読めてしまうため）。建物・道路を結合しなければ `VALID_GIS_MASK` / `MISSING_REASON` は付かず、衛星指標を結合しなければ `VALID_SATELLITE_MASK` は付かない。旧 wide CSV は常に全列を持っていたため、**列の存在を前提にしたコードは修正が必要である**。詳細は [calc_urban_params_guide.md](calc_urban_params_guide.md) 6.3節を正本とする。

**`MISSING_REASON` は NULL（値が得られていない = `missing_gis_data`）と0（地物が無い = `no_gis_feature`）を区別する。** 結合したテーブルの世代違いが「地物が無い地域」として分析へ流れ込むことを防ぐためである。判定基準は [calc_urban_params_guide.md](calc_urban_params_guide.md) 6.3節を正本とする。

**`DATA_SOURCE` / `SCENARIO` は廃止した。** テーブル名（`build_gba` 等）と結合対象の選択が同じ情報を持つためである。

**出力ファイル**

| 段階 | ファイル | 状況 |
|---|---|---|
| 正準グリッド | `data/output/grid/grid_<city_id>.gpkg`（`grid_30m` / `grid_90m` / `grid_300m`） | 実装済み |
| Step 3 の出力（算出） | `data/output/params/<city_id>/<scale>m/<テーブル名>.gpkg`（**パラメータセットごと・スケールごとに分かれる**） | 実装済み |
| Step 3 の出力（結合） | `data/output/datasets/dataset_<name>_<city_id>_<scale>m.gpkg`（`LST` 列を含まない） | 実装済み |
| LST 結合後 | `data/output/analysis_dataset.csv` | 未実装（`merge_dataset.py` 未作成。スケールごとに分けるかは設計時に決める） |

> **旧出力**: `data/output/urban_params/urban_params_<scenario>_<city_id>_<scale>m.csv`（wide CSV）は残置しているが、再生成の手段は持たない。再設計前後で算出値が変わっていないことは照合済みである（[calc_urban_params_guide.md](calc_urban_params_guide.md) 11.2節）。

### 4.1.1 Satellite Only の現行出力（2026-04-21）

`Satellite Only` は暫定段階を超え、複数観測日で結果を保持している。  
現時点では、GIS 由来列を含む統合版 `analysis_dataset.csv` ではなく、衛星指標のみを対象としたデータセット群を先に構築している。

| 出力 | 内容 |
|------|------|
| `data/output/satellite_only/<obs_key>/satellite_only_<date>_<obs_key>_dataset.csv` | 各観測日のピクセル単位データセット |
| `data/output/satellite_only/<obs_key>/satellite_only_<date>_<obs_key>_summary.json` | 行数、採用観測、品質フィルタ条件の記録 |
| `data/output/satellite_only/multidate/satellite_only_multidate_summary.csv` | 3観測日の要約比較 |

列構成は `lon`, `lat`, `LST`, `NDVI`, `NDBI`, `NDWI` を基本とし、  
GIS 列は Full / Limited シナリオの実装時に追加する。

> 本節は**4.1 とは別のパイプライン**の出力である。観測日ごとのピクセル単位データセット（30m 固定）であり、
> 4.1 のマルチスケール出力（`cell_id` キーのテーブル）とは生成経路が異なる。

### 4.2 品質管理

| チェック項目 | 方法 | 閾値 |
|------------|------|------|
| 雲マスク | LSTのNaN除去 | NaN を欠損として扱う |
| LST異常値 | 外れ値除去 | IQR法 or 15–65°C範囲外を除外 |
| 説明変数の欠損 | 欠損率確認 | 欠損 > 20%の変数は除外検討 |
| 多重共線性 | VIF計算 | VIF > 10の変数は除外検討 |

---

## Step 5: モデル構築・分析

### 5.1 RQ1: 支配的説明変数の特定

**目的**: どの都市構造パラメータがLSTに対して最も支配的か定量評価する。

#### 手法1: 重回帰分析（MLR）

| 項目 | 内容 |
|------|------|
| 目的変数 | LST（°C） |
| 説明変数 | 全都市構造パラメータ（标準化済み） |
| 評価指標 | 標準化回帰係数・寄与率（%）, R², VIF |
| 実装ライブラリ | `sklearn.linear_model.LinearRegression` or `statsmodels.OLS` |

> **参考**: S6[Garzón 2021]でMLR寄与率: NDWI 51.46%, NDBI 21.38%, PUC 14.32%, NDVI 12.84%（R²=0.82）

#### 手法2: Random Forest（RF）

| 項目 | 内容 |
|------|------|
| 目的変数 | LST（°C） |
| 説明変数 | 全都市構造パラメータ |
| 評価指標 | Feature Importance, R², RMSE |
| ハイパーパラメータ探索 | `GridSearchCV` or `RandomizedSearchCV` |
| 実装ライブラリ | `sklearn.ensemble.RandomForestRegressor` |
| 乱数シード | `random_state=42`（固定） |

> **参考**: S4[Sun et al. 2019]でRF変数重要度: NDVI（都市生態インフラ）・建物密度が支配的（RF R²>0.9、CV R²=0.66）

#### 手法3: SHAP値分析

| 項目 | 内容 |
|------|------|
| 対象モデル | RF（またはGBDT） |
| 算出内容 | SHAP summary plot, SHAP dependence plot |
| 評価ポイント | 各変数の正/負の寄与方向と大きさ |
| 実装ライブラリ | `shap` |

**RQ1の考察観点**:

- MLR標準化係数とRF/SHAP重要度の一致・不一致
- 非線形効果の存在有無（MLRとRFの性能差で推定）

### 5.2 RQ2: 空間スケールの影響評価

**目的**: 都市構造パラメータとLSTの関係が空間集計スケールによってどう変化するか評価する。

> **本節の分析設計は未実装の設計案である。** 以下の `_0` / `_30_60` 等のリング型サフィックスは
> Step 3.3 の近傍リング設計に対応するものであり、**4.1 の実装済み列とは別**である。
> 現行の実装は 30 / 90 / 300m のグリッド解像度によるスケール比較であり、リング型変数は算出していない。

**分析設計**:

| 比較ケース | 説明変数 | 期待する検証 |
|----------|---------|------------|
| ケース1（即時効果のみ） | `*_0` 変数群 | ベースライン |
| ケース2（+30-60mリング） | `*_0` + `*_30_60` | 近傍1の効果 |
| ケース3（+60-90mリング） | 上記 + `*_60_90` | 近傍2の効果 |
| ケース4（全スケール） | 全 `*` 変数 | 最大スケールの効果 |

**評価指標**: 各ケースのR², RMSE, 変数重要度の変化

> **根拠**: S5[Osborne 2019]では「近傍リング(annuli)変数の重要度 > 即時効果、相関0.956」を示した。

### 5.3 RQ3: データ制約下での有効性評価

**目的**: 測量データ（DGN）が利用できない状況でも衛星・公開データのみで  
LST分布をどの程度説明できるかを評価する。

**比較設計**:

| シナリオ | 使用データ | 想定状況 |
|---------|---------|---------|
| Full（フルデータ） | 衛星指標 + 公開GIS + 測量GIS | 理想的な研究環境 |
| Limited（制約あり） | 衛星指標 + 公開GIS（OSM道路、GlobalBuildingAtlas建物、FABDEM標高 ほか） | 測量データ入手困難な都市 |
| Satellite Only | 衛星指標のみ | 最も制約された状況 |

**公開GISデータ取得**:

- 道路: Geofabrik / OSM の `highway=*`
- 建物: GlobalBuildingAtlas を主ソースとして採用確定。Microsoft GlobalMLBuildingFootprints / Google Open Buildings / OSM `building=*` は比較候補
- 標高・土地利用・人口密度・夜間光: いずれも取得済み（採用済み）
- 採否の一覧は [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md)、データソースの候補比較は [available_gis_data.md](../01_planning/available_gis_data.md) を参照する

**評価指標**: 各シナリオのR², RMSE, 変数重要度の変化・類似度

### 5.3.1 現時点の実行順序

RQ3 は、現在次の順で進める。

1. `Satellite Only` の複数観測日結果を基準線として固定する。
2. `Limited` のために OSM 道路と GlobalBuildingAtlas を前処理し、利用可能範囲と QA 条件を整理する。
3. `urban_params` パッケージを公開 GIS / 測量 GIS の両方に対応できる設計へ揃える。
4. `Limited` を先に実装し、その後 `Full` を実装する。

`Limited` の建物データソースは **GlobalBuildingAtlas に確定済み**である（Microsoft 単独では ROI 全域を代表できないため）。Google Open Buildings / OSM `building=*` は比較・妥当性確認の候補として残す。  
`Full` の算出手順と、両シナリオの最終変数セットは未確定である。

### 5.3.2 Satellite Only の最小評価仕様

| 項目 | 内容 |
|------|------|
| 説明変数 | `NDVI`, `NDBI`, `NDWI` |
| 目的変数 | `LST` |
| 品質管理 | NaN 除外、LST を 15–65°C に制限、指標値を -1.1〜1.1 に制限 |
| ベースラインモデル | MLR, Random Forest |
| 出力 | モデル指標 JSON、特徴量重要度 CSV、比較図 |

この最小仕様は既に実施済みであり、現在は複数観測日での比較結果を保持している。  
今後はこの基準線に対して `Limited` / `Full` の改善幅を評価する。

---

## Step 6: 評価・可視化

### 6.1 モデル評価指標

| 指標 | 用途 | 計算式 |
|------|------|--------|
| R²（決定係数） | 説明力の評価 | 1 - SS_res/SS_tot |
| RMSE | 予測精度 | √(Σ(y-ŷ)²/n) |
| MAE | 予測精度（外れ値に頑健） | Σ\|y-ŷ\|/n |
| VIF | 多重共線性の診断 | 1/(1-R²_j) |

### 6.2 可視化一覧

| 図の種類 | 用途 | 対応RQ |
|---------|------|--------|
| LST空間分布マップ | 研究対象地域のLST可視化 | - |
| SHAP Summary Plot | 変数重要度の寄与方向可視化 | RQ1 |
| Feature Importance棒グラフ | RFの変数重要度ランキング | RQ1 |
| 散布図（LST vs 各パラメータ） | 個別の関係性確認 | RQ1 |
| スケール別R²比較グラフ | 近傍スケールの効果比較 | RQ2 |
| シナリオ別性能比較 | データ制約の影響可視化 | RQ3 |

### 6.3 可視化スクリプト設計

| スクリプト | 処理内容 |
|----------|---------|
| `src/analysis/visualize_lst.py` | LSTの空間分布マップ作成 |
| `src/analysis/visualize_model_results.py` | モデル評価結果・SHAP値の可視化 |

---

## 実装スケジュール（目安）

| フェーズ | 作業内容 | スクリプト | 優先度 |
|---------|---------|----------|--------|
| **Phase 1** | GISデータ空間範囲の把握（BBox比較） | `src/analysis/analyze_spatial_extents.py` | ✅ 完了（2026-03-03） |
| **Phase 1.5** | Satellite Only データセット構築 | `src/analysis/build_satellite_only_dataset.py` | ✅ 完了 |
| **Phase 1.6** | Satellite Only ベースライン分析（3観測日） | `src/analysis/analysis_rq3_satellite_only.py` | ✅ 完了 |
| **Phase 2** | 公開 GIS 候補の取得・QA | `extract_geofabrik_roads_hanoi.py`, `fetch_microsoft_buildings_hanoi.py`, Google / OSM 建物取得スクリプト | 🔴 高 |
| **Phase 2** | 分析グリッド設計 + GIS由来パラメータ集計 | `calc_urban_params.py` | 🔴 高 |
| **Phase 3** | 近傍変数算出 | `calc_neighborhood_vars.py` | 🟡 中 |
| **Phase 4** | データセット結合・品質管理（空間範囲マスク含む） | `merge_dataset.py` | 🟡 中 |
| **Phase 5** | `Limited` シナリオ比較（RQ3） | `analysis_rq3_limited.py` など | 🔴 高 |
| **Phase 5** | `Full` シナリオ比較（RQ3） | `analysis_rq3_full.py` など | 🟡 中 |
| **Phase 6** | RQ1 / RQ2 本分析 | `analysis_rq1.py`, `analysis_rq2.py` | 🟢 後 |
| **Phase 6** | 可視化・図表作成 | `visualize_*.py` | 🟢 後 |

---

## 未確定事項・今後の検討課題

| 事項 | 現状 | 検討方向 |
|------|------|---------|
| 対象都市のROI確定 | ハノイROIは確認済み | 複数都市への拡張可否を検討 |
| LSTの日付選定 | 3観測日は確定済み | 追加観測日の拡張条件を整理する |
| 公開建物データ | GlobalBuildingAtlas を `Limited` の主ソースとして採用確定・取得済み。Microsoft は保留確定 | 比較候補（Google Open Buildings / OSM）との妥当性確認をどこまで行うかを判断する |
| 公開道路データ | OSM を主候補 | 道路種別と欠測率の QA を続ける |
| 測量 GIS の意味整理 | `gpkgの確認結果.md` と `DGNファイル内容確定結果.md` で再確認中 | DH / TV の利用方法を確定する（TH は水域パラメータ未採用のため対象外） |
| 人口密度データ | WorldPop・LandScan とも取得済み。説明変数として採用確定 | どちらを入力とするかを RQ1 のモデル構築で比較して決める。解像度が解析スケールより粗い点の扱いも整理する |
| 訓練・テスト分割 | Satellite Only では Spatial CV 実施済み | Limited / Full でも同一評価法を維持する |
| 季節変動の扱い | 夏季2観測 + 乾季1観測 | 追加季節データの取得可否を検討 |

---

> **更新ルール**: 各 Phase のスクリプトを `src/` に追加・更新したら、まずこのドキュメントの実装欄を更新する。  
> そのうえで、変更内容に応じて関連文書のみを更新する。  
>
> - 測量由来 GIS の整備状況や解釈を変えた場合: [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)  
> - `Satellite Only` の分析結果を変えた場合: [satellite_only_analysis_results.md](../03_results/satellite_only_analysis_results.md)  
> - ドキュメント構成や参照先を変えた場合: [docs/README.md](../README.md)
