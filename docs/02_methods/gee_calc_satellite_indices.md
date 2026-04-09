# gee_calc_satellite_indices.py 仕様（Landsat 8 衛星指標）

**最終更新**: 2026-04-09  
**関連ドキュメント**:  
- [analysis_workflow.md](analysis_workflow.md)  
- [calc_urban_params_guide.md](calc_urban_params_guide.md)  
- [gee_calc_LST.md](gee_calc_LST.md)  
- [CodingRule.md](CodingRule.md)  
- [実装コード: src/gee/gee_calc_satellite_indices.py](../../src/gee/gee_calc_satellite_indices.py)

**前提知識**: Google Earth Engine Python API、Landsat Collection 2 Level-2 SR

---

## 1. 目的

本ドキュメントは、`src/gee/gee_calc_satellite_indices.py` が算出する衛星指標（NDVI/NDBI/NDWI）の処理仕様を定義する。

特に、都市構造パラメータ算出で利用する説明変数の品質を確保するため、以下を明示する。

- 指標算出式
- QAマスクの根拠
- 反射率スケーリングの根拠
- 出力統計の解釈と運用上の注意

本仕様は、恣意的な値補正ではなく、USGS/GEE公式情報に基づく前処理を原則とする。

---

## 2. 入力と出力

### 2.1 入力

- 設定CSV: `data/input/gee_calc_LST_info.csv`
  - `roi_shapefile_path`
  - `start_date`
  - `end_date`
  - `valid_pixel_threshold`
  - `output_epsg`
  - `gee_project_id`
  - `city_name`
  - `drive_root_folder`
  - `drive_export_folder`（任意）
- 画像コレクション: `LANDSAT/LC08/C02/T1_L2`

### 2.2 出力

- 統計CSV: `data/output/gee_calc_indices_results.csv`
- GeoTIFF（Google Drive）: `INDICES_Landsat8_YYYYMMDD.tif`
  - バンド: NDVI, NDBI, NDWI
  - 解像度: 30m
  - CRS: `output_epsg`（通常はEPSG:4326）

---

## 3. 指標定義

対象指標は以下の3つに固定する。

- NDVI: $(NIR - RED) / (NIR + RED)$
- NDBI: $(SWIR1 - NIR) / (SWIR1 + NIR)$
- NDWI: $(GREEN - NIR) / (GREEN + NIR)$

Landsat 8 C2 L2 の対応バンド:

- GREEN: `SR_B3`
- RED: `SR_B4`
- NIR: `SR_B5`
- SWIR1: `SR_B6`

---

## 4. 公式情報に基づく前処理仕様

### 4.1 反射率スケーリング（公式準拠）

Landsat Collection 2 Level-2 Surface Reflectance は、整数DNを以下で物理値へ変換する。

- 変換式: `reflectance = DN * 0.0000275 + (-0.2)`
- 有効DN範囲: `7273-43636`

本実装では、上記有効範囲外のDNを除外した上でスケーリングを適用する。

### 4.2 QAマスク（公式準拠）

`QA_PIXEL` と `QA_RADSAT` を使用して品質不良ピクセルを除外する。

- `QA_PIXEL` で除外するビット（Landsat 8-9 C2）
  - bit 0: Fill
  - bit 1: Dilated Cloud
  - bit 2: Cirrus
  - bit 3: Cloud
  - bit 4: Cloud Shadow
  - bit 5: Snow
- `QA_RADSAT == 0` のみ採用（飽和ピクセル除外）

### 4.3 分母ゼロ回避

正規化指標の分母がゼロ近傍の場合は数学的に不安定なため、該当画素をマスクする。

- 閾値: `abs(denominator) > 1e-6`

この処理は、値の恣意的圧縮ではなく未定義値の排除を目的とする。

---

## 5. 処理フロー

1. 設定CSV読込
2. GEE認証
3. ROI読込（Shapefile）
4. `LANDSAT/LC08/C02/T1_L2` を期間・範囲で抽出
5. QAマスク適用（`QA_PIXEL`, `QA_RADSAT`）
6. SRスケーリングと有効DN範囲マスク
7. NDVI/NDBI/NDWI算出
8. ROI統計（mean/min/max/std）算出
9. 有効ピクセル比が閾値以上のシーンのみ、ROIでクリップしたGeoTIFFをDriveへ出力
10. 全シーン結果をCSV出力

---

## 6. 都市構造パラメータ算出での利用指針

`calc_urban_params.py` で衛星由来説明変数を扱う際は、以下を前提にする。

- 本スクリプト出力は、公式QAと公式スケール係数に基づく一次品質管理済みデータである。
- GeoTIFF出力はROIでクリップしてからDriveへ渡すため、ROI外の不要領域を含めない。
- ただし、都市構造パラメータ統合時は、GIS有効域マスクとの整合を別途確認する。
- 統計列の `min/max` は外れ値に影響されやすいため、解析時には `mean/std` と併用して解釈する。

---

## 7. 実行方法

プロジェクトルートで実行する。

```powershell
python src/gee/gee_calc_satellite_indices.py
```

---

## 8. 既知の制約

- Landsat 8 (`LC08`) 固定実装であり、Landsat 9 (`LC09`) は未対応。
- 画像出力はGEEの非同期タスクであり、完了確認はGEE TasksまたはDrive側で行う必要がある。
- 期間・雲条件によっては有効画素不足で出力件数が減少する。

---

## 9. 参考資料（公式）

1. GEE Data Catalog: Landsat 8 C2 L2  
   https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2
2. USGS FAQ: Landsat Level-2 scale factor/offset  
   https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products
3. USGS: Landsat Collection 2 QA bands  
   https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands
4. USGS: Landsat 8-9 Collection 2 Level-2 Science Product Guide  
   https://www.usgs.gov/media/files/landsat-8-9-collection-2-level-2-science-product-guide
