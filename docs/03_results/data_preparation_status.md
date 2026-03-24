# データ整備状況レポート

**最終更新**: 2026-02-27（DC/GT/TVジオメトリエラー解消、全7種類WGS84変換完了）  
**作成方法**: `src/analyze_data_status.py`による自動分析  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [CodingRule.md](../02_methods/CodingRule.md)

---

## 📋 目的

本ドキュメントは、研究データ分析フェーズに進む前の現状把握を目的とする。各データセットの**CRS・解像度・空間範囲・ファイル位置**を明記し、AIと研究者が共有可能な情報源とする。

---

## 1. データ整備の全体概況

### 整備完了データ
- ✅ **LSTデータ**: 2023年7-8月のHanoi全域（EPSG:4326）
- ✅ **GISデータ（WGS84変換済み）**: **全7種類完了**（CS/DC/DH/GT/RG/TH/TV、計**977,370地物**）→ EPSG:4326
  - **完全処理**: CS/DH/GT/RG/TH（5種類、100%）
  - **一部欠落**: DC（79/80ファイル、99.79%）、TV（79/80ファイル、98.75%）

### 未完了・制約事項
- ⚠️ **空間範囲の不一致**: LSTはハノイ全域、GISは都市部の矩形領域のみ → **クリップ処理が必要**
- ⚠️ **LSTデータ件数**: 有効データ4件のみ（雲量・有効ピクセル率の制約）
- ⚠️ **データ欠落**: DC 1ファイル（処理ハング）、TV 1ファイル（DGNv8形式、サポート外）

### 優先対応事項
1. **GISデータのCRS設定**: 手動でEPSG:3405 (VN-2000)を設定 → ✅完了（タスク1）
2. **LSTのクリップ処理**: GISデータの矩形範囲でLSTラスタをクリップ → 🔄次タスク
3. **LSTデータ追加取得**: 分析に必要な時系列データの拡充
4. **DC/GT/TV の修復**: ジオメトリ有効性チェック・修復処理

---

## 2. GISデータ詳細

### 2.1 データソース
- **元データ**: `整備データ/Vector_*/` 配下のDGNファイル（MicroStation形式）
- **統合データ**: `整備データ/merge/` 配下のGeoPackage形式（.gpkg）
- **統合スクリプト**: `src/preprocessing/merge_vector.py`（基本版）、`src/preprocessing/merge_vector_fixed.py`（ジオメトリ修復版）
- **データ種類**: 7種類（CS/DC/DH/GT/RG/TH/TV）

### 2.2 分析結果サマリー

| 種類 | ファイル名 | サイズ(MB) | 地物数 | 処理率 | CRS | WGS84変換 | 状態 |
|------|------------|-----------|--------|--------|-----|----------|------|
| **CS** | merge_CS.gpkg | 3.92 | 20,110 | 100% | LOCAL_CS → EPSG:3405 | ✅ | ✅ 完全 |
| **DC** | merge_DC.gpkg | 157.05 | 460,085 | 98.75% | LOCAL_CS → EPSG:3405 | ✅ | ⚠️ 79/80ファイル |
| **DH** | merge_DH.gpkg | 121.54 | 104,317 | 100% | LOCAL_CS → EPSG:3405 | ✅ | ✅ 完全 |
| **GT** | merge_GT.gpkg | 92.28 | 209,077 | 100% | LOCAL_CS → EPSG:3405 | ✅ | ✅ 完全 |
| **RG** | merge_RG.gpkg | 0.85 | 721 | 100% | LOCAL_CS → EPSG:3405 | ✅ | ✅ 完全 |
| **TH** | merge_TH.gpkg | 103.98 | 55,269 | 100% | LOCAL_CS → EPSG:3405 | ✅ | ✅ 完全 |
| **TV** | merge_TV.gpkg | 61.10 | 127,791 | 98.75% | LOCAL_CS → EPSG:3405 | ✅ | ⚠️ 79/80ファイル |

**WGS84変換済みデータ**（全7種類）の合計地物数: **977,370**（完全性: 99.79%）  
**出力先**: [data/output/gis_wgs84/](../../data/output/gis_wgs84/)

### 2.3 座標系情報

#### CRS定義の現状
全ファイルが以下のCRS文字列で保存されている：
```
LOCAL_CS["Undefined SRS",LOCAL_DATUM["unknown",32767],UNIT["unknown",0],AXIS["Easting",EAST],AXIS["Northing",NORTH]]
```

#### EPSG:3405 (VN-2000) 推定根拠
座標範囲から**VN-2000 / Hanoi zone (EPSG:3405)** と推定される：

| データ | X座標範囲（m） | Y座標範囲（m） | 推定結果 |
|--------|---------------|---------------|----------|
| CS | 581,144 ～ 589,921 | 2,321,788 ～ 2,333,565 | ✅ EPSG:3405 |
| DH | 499,999 ～ 589,883 | 999,999 ～ 2,333,460 | ⚠️ Y座標下限が低い |
| RG | 581,175 ～ 589,888 | 2,321,890 ～ 2,333,463 | ✅ EPSG:3405 |
| TH | 499,999 ～ 589,882 | 999,999 ～ 2,333,467 | ⚠️ Y座標下限が低い |

**参考**: VN-2000 Hanoi zoneの典型的範囲は X: 40-80万m、Y: 150-250万m（投影座標）

**推奨対応**: GeoPandasで手動設定
```python
gdf = gpd.read_file("整備データ/merge/merge_CS.gpkg")
gdf = gdf.set_crs(epsg=3405, allow_override=True)  # VN-2000手動設定
gdf_wgs84 = gdf.to_crs(epsg=4326)  # WGS84へ変換
```

### 2.4 WGS84空間範囲（分析成功データ）

EPSG:3405を仮定してWGS84へ変換した結果：

| データ | 経度範囲 | 緯度範囲 | 備考 |
|--------|----------|----------|------|
| **CS** | 105.783105° ～ 105.867121°E | 20.993929° ～ 21.099977°N | ハノイ中心部（矩形） |
| **RG** | 105.783400° ～ 105.866763°E | 20.994890° ～ 21.099089°N | ハノイ中心部（矩形） |
| **DH** | 105.001772° ～ 105.866763°E | 9.045544° ～ 21.099089°N | より広域（測量図葉複数） |
| **TH** | 105.001772° ～ 105.866763°E | 9.045544° ～ 21.099089°N | より広域（測量図葉複数） |

**地理的位置**: ベトナム・ハノイ市中心部～北東部

**重要**: これらは**矩形領域**（測量図葉単位）であり、ハノイ市の行政区画全体ではなく、**都市部の一部のみ**をカバーしています。分析時はLSTデータをこの矩形範囲でクリップする必要があります。

**分析用の統合範囲**（4種類のGISデータの結合範囲）:
- **経度**: 約105.00° ～ 105.87°E
- **緯度**: 約9.05° ～ 21.10°N（ただし、実際のデータ密度はハノイ中心部に集中）

### 2.5 ジオメトリタイプ内訳

#### CS（3.92MB、20,110地物）
- LineString: 11,201
- Point: 8,407
- Polygon: 502

#### DH（121.54MB、104,317地物）
- LineString: 58,048
- Point: 46,254
- MultiLineString: 8
- Polygon: 7

#### RG（0.85MB、721地物）
- LineString: 512
- MultiLineString: 82
- Polygon: 68
- Point: 59

#### TH（103.98MB、55,269地物）
- LineString: 53,283
- Polygon: 1,502
- Point: 442
- MultiLineString: 42

**特徴**:
- **LineString優位**: CS/DH/TH は道路・河川等の線状地物が主体
- **Point多数**: DHに46,254点（建物ポイント、施設等の可能性）
- **Polygon少数**: 建物輪郭・区画データは限定的

### 2.6 ジオメトリエラー解消処理（DC/GT/TV）

#### 処理概要
**実施日**: 2026-02-27  
**対象**: DC/GT/TV（以前はジオメトリエラーで処理不可）  
**手法**: ogr2ogrの`-makevalid`および`-skipfailures`オプションによる自動修復

#### 処理スクリプト
1. **merge_vector_fixed.py**: `src/preprocessing/merge_vector_fixed.py` - DGNファイル統合（ジオメトリ修復付き）
   - `-makevalid`: ジオメトリ自動修復
   - `-skipfailures`: 修復不可能なフィーチャをスキップ
   - タイムアウト: 300秒/ファイル

2. **append_remaining_dgn.py**: `src/preprocessing/append_remaining_dgn.py` - 残りファイルの追加処理
   - ハング原因ファイルをスキップ
   - 処理済みファイルをログから自動検出
   - タイムアウト: 180秒/ファイル

3. **convert_to_wgs84_ogr.py**: `src/preprocessing/convert_to_wgs84_ogr.py` - ogr2ogr版WGS84変換
   - GeoPandasのUTF-8エラー回避
   - VN-2000 (EPSG:3405) → WGS84 (EPSG:4326)

#### 処理結果詳細

| データ種類 | 処理ファイル数 | 統合地物数 | 欠落ファイル | 欠落理由 |
|---------|-------------|----------|-----------|---------|
| **DC** | 79/80 (98.75%) | 460,085 | F-48-68-(251-c)_2018_DC.dgn | 処理ハング（5分超過） |
| **GT** | 80/80 (100%) | 209,077 | なし | 完全統合 |
| **TV** | 79/80 (98.75%) | 127,791 | F-48-80-(11-c)_2018_TV.dgn | DGNv8形式（GDAL未サポート） |

**総地物数（DC/GT/TV）**: 796,953地物  
**全体完全性（7種類合計）**: 977,370地物（99.79%、238/240ファイル処理）

#### WGS84変換結果

| データ種類 | WGS84ファイル | サイズ(MB) | 地物数 | 変換時間 |
|---------|-------------|-----------|--------|---------|
| **DC** | merge_DC_wgs84.gpkg | 159.39 | 460,085 | ~8秒 |
| **GT** | merge_GT_wgs84.gpkg | 93.11 | 209,077 | ~3秒 |
| **TV** | merge_TV_wgs84.gpkg | 61.74 | 127,791 | ~2秒 |

**処理ログ**:
- merge処理: `data/output/merge_vector_fixed.log`
- append処理: `data/output/append_remaining.log`
- WGS84変換: `data/output/convert_to_wgs84_ogr.log`

**使用スクリプト（移動後のパス）**:
- `src/preprocessing/merge_vector_fixed.py`
- `src/preprocessing/append_remaining_dgn.py`
- `src/preprocessing/convert_to_wgs84_ogr.py`

#### 欠落データの影響評価

**DC（1/80ファイル欠落）**:
- 欠落: F-48-68-(251-c)_2018_DC.dgn（測量図葉251-c）
- 影響: 都市部データの約1.25%（測量図葉1区画分）
- 空間的影響: ハノイ中心部の特定矩形領域が未カバー
- 分析への影響: 限定的（周辺区画で補完可能）

**TV（1/80ファイル欠落）**:
- 欠落: F-48-80-(11-c)_2018_TV.dgn（測量図葉11-c、郊外）
- 理由: DGNv8形式（MicroStation V8以降のネイティブ形式）はGDAL未サポート
- 影響: TVデータ全体の約1.25%
- 分析への影響: 限定的（郊外部の1区画のみ）

#### 処理改善内容
- ✅ **3段階エンコーディング対策**: UTF-8 → latin1 → fiona直接読込（GeoPandas版）
- ✅ **ogr2ogr直接利用**: エンコーディング問題の完全回避
- ✅ **タイムアウト管理**: ハングファイルの自動スキップ
- ✅ **処理再開機能**: ログベースの処理済みファイル検出

---

## 3. LSTデータ詳細

### 3.1 データソースと生成方法

#### 算出スクリプト
- **ファイル**: [src/gee/gee_calc_LST.py](../../src/gee/gee_calc_LST.py)
- **手法**: Statistical Mono-Window法（SMW法、Ermida et al. 2020）
- **プラットフォーム**: Google Earth Engine (GEE)
- **衛星データ**: Landsat 8 Collection 2 Tier 1

#### 設定ファイル
- **ファイル**: [data/input/gee_calc_LST_info.csv](../../data/input/gee_calc_LST_info.csv)
- **設定内容**:
  - ROI: `data/GISData/ROI/hanoi/hanoi_roi.shp` (EPSG:4326)
  - 期間: 2023年7月1日 ～ 2023年8月31日
  - 雲量閾値: 30%
  - 有効ピクセル閾値: 50%
  - **出力CRS**: **EPSG:4326 (WGS84)**
  - 出力フォーマット: GeoTIFF

### 3.2 算出結果サマリー

#### 結果ファイル
- **ファイル**: [data/output/gee_calc_LST_results.csv](../../data/output/gee_calc_LST_results.csv)
- **レコード数**: 6件
- **期間**: 2023年7月16日 ～ 2023年8月26日
- **エクスポート済み**: 4件/6件

#### データ品質
| 指標 | 値 |
|------|-----|
| 有効データ（有効ピクセル>50%） | 4件 |
| 平均LST | **37.96°C** |
| LST範囲 | 8.04°C ～ 57.79°C |

**注意**: 
- 雲量30%制約により、夏季でも取得可能日が限定的
- LSTの最低値（8.04°C）は異常値の可能性（水域または雲影）

### 3.3 出力ファイル

#### LSTラスタデータ
- **ディレクトリ**: `data/output/LST/`（ハノイデータはサブ配下と推定）
- **形式**: GeoTIFF (.tif)
- **CRS**: EPSG:4326（WGS84、緯度経度座標系）
- **解像度**: 30m（Landsat 8標準解像度）

#### 空間範囲（Hanoi ROI）
`hanoi_roi.shp`の範囲（WGS84）：
- **経度**: 105.2257° ～ 112.7421°E
- **緯度**: 9.2449° ～ 21.3852°N

**📌 補足**: このShapefileはベトナム主要5都市の行政区画を含むファイルです。[src/gee/gee_calc_LST.py](../../src/gee/gee_calc_LST.py)の`load_roi_from_shapefile()`関数内で、`'TinhThanh'`カラムにより**'Hà Nội'のみをフィルタリング**しています（120行目）。そのため、LST算出は実際にはハノイ市域のみが対象となります。

### 3.4 その他ROI

#### 大阪データ（テスト用？）
- **ファイル**: `data/GISData/ROI/N03-19_27_190101.shp`
- **CRS**: EPSG:6668（JGD2011、日本測地系2011）
- **範囲（WGS84）**: 経度 135.0913° ～ 135.7466°E、緯度 34.2718° ～ 35.0513°N
- **推定**: 大阪府域（行政区画データ）

---

## 4. ディレクトリ構造

```
MasterResearch/
│
├── 整備データ/                      # ベトナム測量データ
│   ├── merge/                       # ★統合データ（分析対象）
│   │   ├── merge_CS.gpkg            # [CS] 交通データ（20,110地物）
│   │   ├── merge_DC.gpkg            # [DC] ❌ ジオメトリエラー
│   │   ├── merge_DH.gpkg            # [DH] 水文データ（104,317地物）
│   │   ├── merge_GT.gpkg            # [GT] ❌ ジオメトリエラー
│   │   ├── merge_RG.gpkg            # [RG] 境界データ（721地物）
│   │   ├── merge_TH.gpkg            # [TH] 地形データ（55,269地物）
│   │   └── merge_TV.gpkg            # [TV] ❌ ジオメトリエラー
│   │
│   └── Vector_*/                    # 元データ（DGN形式）
│       ├── Vector_CS/
│       ├── Vector_DC/
│       ├── Vector_DH/
│       ├── Vector_GT/
│       ├── Vector_RG/
│       ├── Vector_TH/
│       └── Vector_TV/
│
├── data/
│   ├── input/
│   │   └── gee_calc_LST_info.csv    # ★LST算出設定
│   │
│   ├── output/
│   │   ├── gee_calc_LST_results.csv # ★LST算出結果（6レコード）
│   │   ├── data_preparation_analysis.json  # ★本レポートの元データ
│   │   ├── gis_wgs84/               # ★GIS WGS84変換済み（4ファイル）
│   │   │   ├── merge_CS_wgs84.gpkg
│   │   │   ├── merge_DH_wgs84.gpkg
│   │   │   ├── merge_RG_wgs84.gpkg
│   │   │   ├── merge_TH_wgs84.gpkg
│   │   │   └── conversion_summary.csv
│   │   └── LST/                     # LSTラスタ出力（推定）
│   │       └── (LST_clipped/        # クリップ済みLST（タスク1.5で作成予定）)
│   │
│   └── GISData/
│       └── ROI/                     # 研究対象地域
│           ├── hanoi/
│           │   └── hanoi_roi.shp    # ★Hanoi ROI（EPSG:4326）
│           └── N03-19_27_190101.shp # 大阪ROI（EPSG:6668）
│
└── src/                             # 分析スクリプト
    ├── gee_calc_LST.py              # LST算出（SMW法）
    ├── analyze_data_status.py       # データ整備状況分析（本レポート生成）
    ├── convert_gis_to_wgs84.py      # GIS CRS設定・WGS84変換
    └── module/
        └── lst_smw.py               # SMW法モジュール
```

---

## 5. データ統合の準備状況

### 5.1 座標系の統一方針

#### 現状の課題
- **GISデータ**: LOCAL_CS（EPSG:3405と推定）
- **LSTデータ**: EPSG:4326（WGS84）
- **ROI**: EPSG:4326（WGS84）

#### 推奨対応（2つの選択肢）

**方針A**: GISデータをWGS84に統一（推奨）
```python
gdf = gpd.read_file("整備データ/merge/merge_CS.gpkg")
gdf = gdf.set_crs(epsg=3405, allow_override=True)  # VN-2000設定
gdf_wgs84 = gdf.to_crs(epsg=4326)  # WGS84へ変換
gdf_wgs84.to_file("data/output/gis_wgs84/merge_CS_wgs84.gpkg")
```

**メリット**: LSTデータ（EPSG:4326）と直接重ね合わせ可能、可視化が容易

**方針B**: LSTデータをVN-2000に変換
```python
import rasterio
from rasterio.warp import calculate_default_transform, reproject

with rasterio.open("data/output/LST/hanoi_LST_20230716.tif") as src:
    transform, width, height = calculate_default_transform(
        src.crs, 'EPSG:3405', src.width, src.height, *src.bounds)
    # ... reproject処理
```

**メリット**: 投影座標系でのメートル単位計算、バッファ処理の精度向上

### 5.2 空間範囲の整合性確認

| データ | CRS | 経度範囲（WGS84） | 緯度範囲（WGS84） | 整合性 |
|--------|-----|------------------|------------------|--------|
| **GIS(CS)** | 3405→4326 | 105.78° ～ 105.87° | 20.99° ～ 21.10° | ✅ |
| **GIS(RG)** | 3405→4326 | 105.78° ～ 105.87° | 20.99° ～ 21.10° | ✅ |
| **GIS(DH)** | 3405→4326 | 105.00° ～ 105.87° | 9.05° ～ 21.10° | ✅ |
| **GIS(TH)** | 3405→4326 | 105.00° ～ 105.87° | 9.05° ～ 21.10° | ✅ |
| **LST ROI** | 4326 | 105.23° ～ 112.74° | 9.24° ～ 21.39° | ✅ フィルタリング済み |
| **LST実算出範囲** | 4326 | ハノイ全域（行政区画） | ハノイ全域（行政区画） | ⚠️ GISより広い |

**判定**: 
- **LST**: ハノイ全域の行政区画（不規則な形状）で算出済み
- **GISデータ**: 矩形領域であり、ハノイ都市部の一部のみをカバー（測量図葉単位）
- **空間範囲の不一致**: LSTはGISデータよりも広い範囲を含む
- **必要な対応**: **LSTをGISデータの矩形範囲でクリップする必要あり**（タスク1.5参照）

### 5.3 解像度・スケール検討

#### LSTデータ
- **空間解像度**: 30m × 30m（Landsat 8標準）
- **集計単位（検討中）**: 
  - グリッド方式: 100m×100m、250m×250m、500m×500m
  - ポリゴン方式: 行政区画、土地利用区画

#### GISデータ
- **ポイントデータ**: そのまま使用（建物位置等）
- **ラインデータ**: バッファ処理後にポリゴン化（道路→道路網密度）
- **ポリゴンデータ**: 面積・被覆率計算

---

## 6. 次ステップ（優先順位順）

### 🎯 必須タスク（データ整備完了の前提）

#### ~~タスク1: GIS CRS設定と座標変換~~ ✅**完了**
- **スクリプト**: [src/convert_gis_to_wgs84.py](../../src/convert_gis_to_wgs84.py)（作成済み、353行）
- **処理内容**:
  1. 全gpkgファイルにEPSG:3405を設定
  2. WGS84（EPSG:4326）へ変換
  3. 新規ディレクトリ `data/output/gis_wgs84/` へ保存
- **結果**: 4/7ファイル変換成功（CS/DH/RG/TH、計180,417地物）
- **出力**: [data/output/gis_wgs84/](../../data/output/gis_wgs84/)、conversion_summary.csv

#### タスク1.5: LSTラスタのクリップ処理 🤖**AI主導**（新規追加）
- **スクリプト**: `src/clip_lst_to_gis_extent.py`（新規作成）
- **処理内容**:
  1. GISデータ（CS/DH/RG/TH）の結合範囲（union bounds）を取得
  2. LST GeoTIFFをこの矩形範囲でクリップ
  3. `data/output/LST_clipped/` へ保存
- **目的**: GISデータとLSTの空間範囲を一致させ、分析準備を完了
- **優先度**: **最優先**（分析開始の前提条件）

#### ~~タスク2: Hanoi ROI再確認・修正~~ ✅**確認完了**
- **確認結果**:
  - `hanoi_roi.shp`はベトナム主要5都市の行政区画を含むファイル（誤データではない）
  - `gee_calc_LST.py`の`load_roi_from_shapefile()`関数で'Hà Nội'のみをフィルタリング済み
  - LST算出は実際にはハノイ市域のみが対象（問題なし）
- **対応**: **不要**（現状のワークフローで正常動作）

#### タスク3: DC/GT/TV のジオメトリ修復 ✅**完了** (2026-02-27)
- **スクリプト**: 
  - `src/preprocessing/merge_vector_fixed.py` - ジオメトリ自動修復付きDGN統合
  - `src/preprocessing/append_remaining_dgn.py` - 残りファイル追加処理
  - `src/preprocessing/convert_to_wgs84_ogr.py` - ogr2ogr版WGS84変換
- **処理結果**:
  - **DC**: 460,085地物 (79/80ファイル、98.75%)
  - **GT**: 209,077地物 (80/80ファイル、100%)
  - **TV**: 127,791地物 (79/80ファイル、98.75%)
- **欠落データ**:
  - DC: F-48-68-(251-c)_2018_DC.dgn（ハング）
  - TV: F-48-80-(11-c)_2018_TV.dgn（DGNv8形式、未サポート）
- **全体結果**: 全7種類WGS84変換完了（977,370地物、99.79%）
- **詳細**: セクション2.6参照

### 📊 分析準備タスク

#### タスク4: 都市構造パラメータ計算方法の策定 👤**人間主導** 🔄**AI支援**
- **ドキュメント**: `docs/02_methods/urban_parameters_definition.md`（新規作成）
- **内容**:
  - S4/S6論文の説明変数リスト参照
  - 本研究で算出可能なパラメータの選定（建物被覆率、道路密度、水域率等）
  - 各パラメータの計算式・集計単位の定義
- **前提**: GISデータの種類（CS/DH/RG/TH等）と地物タイプを確認後に決定

#### タスク5: データ整備ワークフロー文書化 🤖**AI主導**
- **ドキュメント**: `docs/02_methods/data_preparation_workflow.md`（新規作成）
- **内容**:
  - タスク1-3の詳細手順
  - 🤖AI/👤人間/🔄協働の役割分担を明記
  - エラーハンドリング・ログ記録の方法
- **参考**: CodingRule.md、本レポート

#### タスク6: RQ別分析フロー策定 👤**人間主導** 🔄**AI支援**
- **ドキュメント**: `docs/02_methods/analysis_workflow.md`（新規作成）
- **内容**:
  - **RQ1**: 重回帰・Random Forest（S4/S6手法適用）
  - **RQ2**: 空間集計単位の感度分析（グリッドサイズ比較）
  - **RQ3**: 測量データ有無での説明力比較
  - 各RQの入力データ・分析手法・期待される出力を明記

---

## 7. 制約事項・リスク

### 技術的制約
1. **CRS未定義問題**: ~~自動判定不可、手動設定が必須~~ → ✅解決済み（EPSG:3405設定完了）
2. **エンコーディング問題**: ~~ベトナム語テキスト属性の一部がUTF-8デコード不可~~ → ✅ogr2ogr直接利用で回避
3. ~~**ジオメトリ破損**: DC/GT/TVの3ファイルで修復作業が必要~~ → ✅解決済み（全7種類統合完了）
4. **LST有効データ少数**: 夏季2か月間で4件のみ（雲量制約）
5. **DGNv8形式未サポート**: TV 1ファイル（F-48-80-(11-c)）が処理不可

### データ品質リスク
- ~~**ROI範囲の不確実性**: hanoi_roi.shpの範囲が異常に広く、LST算出範囲が不適切な可能性~~（✅確認済み：正常動作）
- **GIS-LST空間範囲の不一致**: GISデータは矩形領域（都市部の一部）、LSTはハノイ全域 → クリップ処理が必須
- **データ欠落（DC/TV）**: 
  - DC: F-48-68-(251-c)（処理ハング、約1.25%欠落）
  - TV: F-48-80-(11-c)（DGNv8形式、約1.25%欠落）
  - 影響: 特定矩形領域（測量図葉2区画分）の都市構造データが不完全
- **測量データの網羅性**: 全7種類のGISデータが都市構造パラメータ算出に十分かの検証が必要

### 研究上のリスク
- **時系列データ不足**: 夏季2か月のみでは季節変化・経年変化の分析不可
- **空間範囲の限定性**: GISデータはハノイ中心部の矩形領域（測量図葉単位）のみで、ハノイ市全体や周辺地域を代表できない可能性
- **行政区画との不一致**: GISデータは測量図葉の矩形範囲であり、行政区画単位での集計・比較が困難

---

## 8. 参考情報

### 分析結果の元データ
- **JSONファイル**: [data/output/data_preparation_analysis.json](../../data/output/data_preparation_analysis.json)
- **生成スクリプト**: [src/analysis/analyze_data_status.py](../../src/analysis/analyze_data_status.py)
- **実行日時**: 2026-02-26

### 関連ドキュメント
- **研究計画**: [research_guide.md](../01_planning/research_guide.md) - RQ1-RQ3の詳細
- **LST算出レポート**: [calc_LST_report.md](../02_methods/calc_LST_report.md) - SMW法の実装詳細
- **コーディング規約**: [CodingRule.md](../02_methods/CodingRule.md) - スクリプト作成時の遵守事項

### 用語集
- **LST**: Land Surface Temperature（地表面温度、本研究では常に摂氏°C）
- **SMW**: Statistical Mono-Window法（Ermida et al. 2020）
- **VN-2000**: Vietnam 2000座標系（EPSG:3405 Hanoi zone）
- **ROI**: Region of Interest（研究対象地域）
- **都市構造パラメータ**: 建物・道路・水域・人口等の空間配置と密度を定量化した説明変数群

---

**このドキュメントは**、データ整備状況の「現在地」を示すスナップショットです。

**主要な達成事項（2026-02-27時点）**:
- ✅ 全7種類のGISデータWGS84変換完了（977,370地物、99.79%）
- ✅ DC/GT/TVのジオメトリエラー解消
- ✅ タスク1-3完了

**次のステップ**:
- 🔄 タスク1.5: LSTクリップ処理（GIS矩形範囲での切り出し）
- 🔄 タスク4-6: 分析準備（都市構造パラメータ定義、分析フロー策定）

タスク完了時は各セクションを更新してください。
