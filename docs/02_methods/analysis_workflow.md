# 分析ワークフロー仕様書

**最終更新**: 2026-03-03  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [data_preparation_status.md](../03_results/data_preparation_status.md), [CodingRule.md](CodingRule.md)  
**前提知識**: RQ1–RQ3の理解（research_guide.md § 3–5 参照）

---

## 概要

本ドキュメントは、「ベトナム主要都市を対象とした地表面温度と都市構造の関係性評価」における  
**データ前処理 → 都市構造パラメータ算出 → モデル構築 → 評価・可視化** の全工程を定義する。

実装を始める前に各工程の入出力・手法選定の根拠を明確にし、  
再現性のある研究プロセスを確立することを目的とする。

### 現在の優先実行範囲（2026-04-06）

現時点では、GIS データ整備と Full / Limited シナリオの仕様確定が未完了である。  
そのため、本ドキュメント上の実装優先度は **RQ3 の Satellite Only シナリオを先に成立させること** とする。

1. 2023-07-07 のうち、LST・衛星指標の両方で有効画素率が最も高い観測を選定する。
2. 選定観測の LST / NDVI / NDBI / NDWI を同一グリッド上で結合し、ピクセル単位の分析用 CSV を構築する。
3. Satellite Only 条件で MLR と Random Forest を実行し、R² / RMSE / MAE と変数重要度を確認する。
4. Full / Limited シナリオは、GIS データ整備および OSM 処理仕様の確定後に再開する。

今回追加した実装:
- `src/analysis/build_satellite_only_dataset.py`
- `src/analysis/analysis_rq3_satellite_only.py`

---

## フロー全体像

```
[RawData]
  │
  ├─ LSTラスタ (GeoTIFF)  ────────────────────────────────────┐
  │   Landsat 8 / SMW法 / GEE算出                             │
  │   ※GEEでROI（行政区画）クリップ済み                       │
  │                                                           │
  ├─ GISベクタ (GPKG/WGS84)                                  │
  │   測量DGN → マージ済みGPKG → WGS84変換                   │
  │   ※ROIより狭い矩形範囲（ハノイ中心部の測量図幅範囲）       │
  │                                                           │
  └─ 衛星指標 (GEE算出)                                      │
      NDVI / NDBI / NDWI                                    │
                                                             ▼
                                                       [Step 2]
                                                   空間範囲の整理
                                             ┌─────────────────────┐
                                             │ LST: ROI全体       │
                                             │ GIS: 中心部矩形範囲│
                                             │ → GIS範囲内のLSTを │
                                             │   分析対象として使用│
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

### 1.1 処理済み状況（完了）

| 処理 | 入力 | 出力 | スクリプト | 状態 |
|------|------|------|-----------|------|
| DGN統合 | `整備データ/Vector_*/` | `整備データ/merge/merge_*.gpkg` | `src/preprocessing/merge_vector_fixed.py` | ✅ 完了 |
| 残ファイル追加 | `整備データ/Vector_DC/` | `整備データ/merge/merge_DC.gpkg` | `src/preprocessing/append_remaining_dgn.py` | ✅ 完了 |
| WGS84変換 | `整備データ/merge/*.gpkg` (VN-2000 / EPSG:3405) | `data/output/gis_wgs84/merge_*_wgs84.gpkg` (WGS84) | `src/preprocessing/convert_to_wgs84_ogr.py` | ✅ 完了 |

**整備済みデータの現況**（詳細: [data_preparation_status.md](../03_results/data_preparation_status.md)）

| 種類 | レイヤ内容 | 地物数 | 完全性 |
|------|-----------|--------|--------|
| CS（等高線） | 等高線（標高値） | 20,110 | 100% |
| DC（建物） | 建物ポリゴン | 460,085 | 98.75% |
| DH（水域） | 河川・水域ポリゴン | 104,317 | 100% |
| GT（道路） | 道路ライン | 209,077 | 100% |
| RG（境界） | 行政境界 | 721 | 100% |
| TH（地形） | 地形面 | 55,269 | 100% |
| TV（植生） | 植生ポリゴン | 127,791 | 98.75% |

### 1.2 欠落データ（既知の制約）

| ファイル | 原因 | 影響 |
|---------|------|------|
| F-48-68-(251-c)_2018_DC.dgn | 処理ハング | DCデータの1区画欠落 |
| F-48-80-(11-c)_2018_TV.dgn | DGNv8形式（GDAL非対応） | TVデータの1区画欠落 |

---

## Step 2: データ空間範囲の整理

### 2.1 LSTデータ現況

- **算出手法**: SMW法（Ermida et al., 2020）
- **衛星**: Landsat 8（30m解像度）
- **算出ツール**: Google Earth Engine（`src/gee/gee_calc_LST.py`）
- **出力**: `data/output/LST/<city_id>/*.tif`（°C単位）
- **空間範囲**: **GEE算出時にROI（行政区画ポリゴン）でクリップ済み** → 追加のクリップ処理は不要
- **詳細**: [gee_calc_LST.md](gee_calc_LST.md)

### 2.2 空間範囲の構造（重要）

LSTとGISデータでは空間範囲が異なる。この非対称性を理解したうえで分析範囲を決定する。

| データ | 空間範囲 | 備考 |
|--------|---------|------|
| **LST** | ROI（行政区画全体） | GEEで算出時にクリップ済み |
| **GISデータ（測量）** | ハノイ中心部の矩形範囲 | 測量図幅の格子範囲。ROIより狭い |
| **衛星指標**（NDVI等） | LSTと同一（ROI全体） | GEEで同時算出 |

#### 2.2.1 実測BBox（2026-03-03）

`src/analysis/analyze_spatial_extents.py` により、ROI（行政区画）とGIS（測量）データの空間範囲を確認した。
出力: `data/output/spatial_extent_report.json`

| 対象 | BBox（minLon, minLat, maxLon, maxLat） | 解釈 |
|------|----------------------------------------|------|
| ROI（Hà Nội） | [105.2881, 20.5645, 106.0201, 21.3852] | 行政区画としてのハノイ全域 |
| GIS（RG: merge_RG_wgs84） | [105.7834, 20.9949, 105.8668, 21.0991] | 測量図幅（中心部）の代表的範囲（分析の主要対象域） |
| GIS（CS: merge_CS_wgs84） | [105.7831, 20.9939, 105.8671, 21.1000] | 上と整合（中心部範囲） |

**注意（重要）**:
- `merge_DC_wgs84.gpkg` や `merge_GT_wgs84.gpkg` 等の一部レイヤでは、BBoxが不自然に広くなる（外れ値ジオメトリを含む可能性）。
- そのため、**DC/GT/TV等の「ファイル全体BBox」を分析範囲の定義に使わず**、RG/CSなど整合が取れているデータの範囲、またはROI内でのフィルタ後の範囲を用いる。
- 外れ値の実例: `merge_DC_wgs84.gpkg`（elements）に **緯度9度台**の地物が混入（`feature_index: 59545`, bbox: (105.00177, 9.04560, 105.00179, 9.04561)）。

```
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

**分析用データセット（Step 4）構築時に、GISデータの有効範囲でLSTをマスクする。**

具体的には：
- まず **RG/CS等、中心部範囲として整合が取れているデータ**（例: `merge_RG_wgs84.gpkg`）から分析対象域（BBoxまたは凸包）を定義する
- その範囲内に含まれるLSTピクセルのみを分析対象として抽出する
- DC/GT/TV等は外れ値ジオメトリにより全体BBoxが広がる可能性があるため、必要に応じて「分析対象域内に限定して集計」する
- 測量データを使わない比較実験（RQ3）では、ROI全体を対象にすることも検討

**ピクセル値の区別**（GEE算出時に既に設定済み）:
| 値 | 意味 |
|----|------|
| NaN | 雲マスク（GEEのcloud_mask関数による） |
| 実数値 | 有効LST（°C）|

NoData（-9999等）は設定されていない。分析時にNaNを欠損として扱う。

---

## Step 3: 都市構造パラメータ算出

### 3.1 パラメータ一覧

都市構造パラメータは**衛星由来**と**GIS由来**の2グループに分類する。

#### グループA: 衛星由来指標（GEE算出）

| パラメータ名 | 変数名 | 算出式 | データソース | 根拠文献 |
|------------|--------|--------|------------|---------|
| NDVI | `NDVI` | (NIR−R)/(NIR+R) | Landsat 8 Band 4,5 | S2, S4 |
| NDBI | `NDBI` | (SWIR−NIR)/(SWIR+NIR) | Landsat 8 Band 5,6 | S2 |
| NDWI | `NDWI` | (G−NIR)/(G+NIR) | Landsat 8 Band 3,5 | S6 |
| 緑被率 | `GREEN_RATIO` | NDVI > 閾値（0.2）のピクセル割合 | Landsat 8 | S4 |
| 水域率 | `WATER_RATIO` | NDWI > 閾値のピクセル割合 | Landsat 8 | S6 |

> **根拠**: S2[Le Ngoc Hanh]で「NDVI/NDBIのみでは建物高さ・人口密度を捉えられない」と明記。  
> S6[Garzón 2021]ではNDWIの寄与率が51.46%と最大（MLRモデル R²=0.82）。

#### グループB: GIS由来指標（測量データ算出）

| パラメータ名 | 変数名 | 算出方法 | データソース | 根拠文献 |
|------------|--------|---------|------------|---------|
| 建物被覆率 | `BUILD_COV` | グリッド内建物面積 / グリッド面積 | DC（建物ポリゴン） | S4 |
| 建物密度 | `BUILD_DEN` | グリッド内建物ポリゴン数 | DC（建物ポリゴン） | S4 |
| 道路密度 | `ROAD_DEN` | グリッド内道路延長（m） | GT（道路ライン） | S4 |
| 主要道路距離 | `ROAD_DIST` | 最近接幹線道路までの距離（m） | GT（道路ライン） | S4 |
| 水域率 | `WATER_COV` | グリッド内水域面積 / グリッド面積 | DH（水域ポリゴン） | S6 |

> **根拠**: S4[Sun et al. 2019]ではRandom Forestにより「緑地 > 建物密度 > 道路密度」の順位を示した（R²≈0.78）。

### 3.2 グリッド設計

LSTの空間解像度に合わせ、**30m × 30m グリッド**を基本単位として都市構造パラメータを集計する。

| 項目 | 設定 |
|------|------|
| **グリッドサイズ** | 30m × 30m（LST解像度と一致） |
| **CRS** | 入力/出力はWGS84（EPSG:4326）。ただし面積・長さ計算はUTM（m単位）で実施 |
| **集計方法** | 各グリッドセル内の面積・長さ・個数を空間集計 |
| **出力形式** | GeoDataFrame（.gpkg）または numpy array |

### 3.3 近傍変数の設計（RQ2対応）

Osborne & Alvares (2019)[S5]の近傍リング設計を参考に、  
各パラメータを**複数の空間スケール**で算出し、空間スケール依存性を評価する。

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
| `src/analysis/calc_satellite_indices.py` | 衛星由来指標（NDVI/NDBI/NDWI/FVC）の算出 | Landsat 8バンド（GEE） | `data/output/indices/*.tif` |
| `src/analysis/calc_urban_params.py` | GIS由来都市構造パラメータのグリッド集計 | `gis_wgs84/*.gpkg` + グリッド | `data/csv/analysis/urban_params_<city_id>.csv` |
| `src/analysis/calc_neighborhood_vars.py` | 近傍変数（30/60/90/120m）の算出 | `urban_params.csv` | `data/csv/analysis/urban_params_with_neighbors.csv` |
| `src/analysis/merge_dataset.py` | LSTと全説明変数の結合 | LSTクリップ + パラメータCSV | `data/csv/analysis/analysis_dataset.csv` |

---

## Step 4: 分析用データセット構築

### 4.1 データセット構造

| 列名 | 型 | 内容 |
|------|-----|------|
| `lon` | float | グリッドセル中心経度（WGS84） |
| `lat` | float | グリッドセル中心緯度（WGS84） |
| `LST` | float | 地表面温度（°C） |
| `NDVI` | float | 衛星由来NDVI |
| `NDBI` | float | 衛星由来NDBI |
| `NDWI` | float | 衛星由来NDWI |
| `BUILD_COV_0` | float | 建物被覆率（即時効果） |
| `BUILD_COV_30_60` | float | 建物被覆率（近傍30-60m） |
| `BUILD_COV_60_90` | float | 建物被覆率（近傍60-90m） |
| `BUILD_COV_90_120` | float | 建物被覆率（近傍90-120m） |
| `BUILD_DEN_*` | float | 建物密度（各スケール） |
| `ROAD_DEN_*` | float | 道路密度（各スケール） |
| `WATER_COV_*` | float | 水域率（各スケール） |
| `data_source` | str | `"survey"` または `"osm"`（RQ3用） |

**出力ファイル**: `data/csv/analysis/analysis_dataset.csv`

### 4.1.1 Satellite Only の暫定出力（2026-04-06）

今回の実行では、GIS 由来列を含む統合版 `analysis_dataset.csv` ではなく、  
衛星指標のみを対象とした暫定データセットを先に構築する。

| 出力 | 内容 |
|------|------|
| `data/csv/analysis/satellite_only_20230707_<obs_key>_dataset.csv` | 2023-07-07 の選定観測に対するピクセル単位データセット |
| `data/csv/analysis/satellite_only_20230707_<obs_key>_summary.json` | 行数、採用観測、品質フィルタ条件の記録 |

列構成は `lon`, `lat`, `LST`, `NDVI`, `NDBI`, `NDWI` を基本とし、  
GIS 列は Full / Limited シナリオの実装時に追加する。

### 4.2 品質管理

| チェック項目 | 方法 | 閾値 |
|------------|------|------|
| 雲マスク | LSTのNoData除去 | NoData = -9999 |
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

> **参考**: S4[Sun et al. 2019]でRF変数重要度: 緑地 > 建物密度 > 道路密度（R²≈0.78）

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
| Full（フルデータ） | 衛星指標 + 測量GIS | 理想的な研究環境 |
| Limited（制約あり） | 衛星指標 + OSM公開データ | 測量データ入手困難な都市 |
| Satellite Only | 衛星指標のみ | 最も制約された状況 |

**OSM公開データ取得**:
- Overpass API または `osmnx` ライブラリ
- 取得対象: 建物ポリゴン（`building=*`）、道路ライン（`highway=*`）、水域（`water=*`）

**評価指標**: 各シナリオのR², RMSE, 変数重要度の変化・類似度

### 5.3.1 現時点の実行順序

RQ3 のうち、今回実行対象とするのは Satellite Only のみである。

1. `build_satellite_only_dataset.py` で 2023-07-07 の最良観測を選定する。
2. LST / NDVI / NDBI / NDWI を結合し、品質管理済み CSV を作成する。
3. `analysis_rq3_satellite_only.py` で MLR と Random Forest を実行する。
4. Full / Limited は別タスクとして保留する。

### 5.3.2 Satellite Only の最小評価仕様

| 項目 | 内容 |
|------|------|
| 説明変数 | `NDVI`, `NDBI`, `NDWI` |
| 目的変数 | `LST` |
| 品質管理 | NaN 除外、LST を 15–65°C に制限、指標値を -1.1〜1.1 に制限 |
| ベースラインモデル | MLR, Random Forest |
| 出力 | モデル指標 JSON、特徴量重要度 CSV、比較図 |

初期段階では SHAP や Spatial CV までは実施せず、  
まず「衛星指標だけでどの程度説明できるか」を定量化する。

---

## Step 6: 評価・可視化

### 6.1 モデル評価指標

| 指標 | 用途 | 計算式 |
|------|------|--------|
| R²（決定係数） | 説明力の評価 | 1 - SS_res/SS_tot |
| RMSE | 予測精度 | √(Σ(y-ŷ)²/n) |
| MAE | 予測精度（外れ値に頑健） | Σ|y-ŷ|/n |
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
| **Phase 1.5** | Satellite Only データセット構築 | `src/analysis/build_satellite_only_dataset.py` | 🔴 最優先 |
| **Phase 1.6** | Satellite Only ベースライン分析（RQ3） | `src/analysis/analysis_rq3_satellite_only.py` | 🔴 最優先 |
| **Phase 2** | 分析グリッド設計 + GIS由来パラメータ集計 | `calc_urban_params.py` | 🔴 高 |
| **Phase 2** | 衛星指標算出（GEE） | `calc_satellite_indices.py` | 🔴 高 |
| **Phase 3** | 近傍変数算出 | `calc_neighborhood_vars.py` | 🟡 中 |
| **Phase 4** | データセット結合・品質管理（空間範囲マスク含む） | `merge_dataset.py` | 🟡 中 |
| **Phase 5** | MLR / RF / SHAP分析 | `analysis_rq1.py` | 🟢 後 |
| **Phase 5** | スケール比較分析（RQ2） | `analysis_rq2.py` | 🟢 後 |
| **Phase 5** | データ制約比較（RQ3） | `analysis_rq3.py` | 🟢 後 |
| **Phase 6** | 可視化・図表作成 | `visualize_*.py` | 🟢 後 |

---

## 未確定事項・今後の検討課題

| 事項 | 現状 | 検討方向 |
|------|------|---------|
| 対象都市のROI確定 | ハノイROIは確認済み | 複数都市への拡張可否を検討 |
| LSTの日付選定 | 晴天日を目視で確認 | 雲被覆 < 10%の観測日を自動選定する処理を検討 |
| 建物高さデータ | GlobalBuildingAtlas検討中 | 入手可能性・精度を確認してから判断 |
| 人口密度データ | WorldPop検討中 | 解像度（100m）のミスマッチをどう扱うか検討 |
| 訓練・テスト分割 | 未確定 | 空間的自己相関を考慮したSpatial CV（k-fold）を検討 |
| 季節変動の扱い | 単一シーン想定 | 複数時期の比較は余力があれば検討 |

---

> **更新ルール**: 各PhaseのスクリプトをSrcに追加したら、このドキュメントの実装欄と  
> [data_preparation_status.md](../03_results/data_preparation_status.md) を合わせて更新する。
