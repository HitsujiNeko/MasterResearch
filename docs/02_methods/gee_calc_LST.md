# gee_calc_LST.py 仕様（Landsat 8 LST）

**最終更新**: 2026-03-16  
**関連ドキュメント**:  
- 処理結果レポート → [calc_LST_report.md](calc_LST_report.md)  
- コーディング規約 → [CodingRule.md](CodingRule.md)  
- 実装コード → [src/gee/gee_calc_LST.py](../../src/gee/gee_calc_LST.py)  
- SMWモジュール → [src/module/lst_smw.py](../../src/module/lst_smw.py)  
- セットアップ → [setup.md](../setup.md)  
- ドキュメント全体 → [docs/README.md](../README.md)

**前提知識**: GEE Python API、Landsat 8データ構造

---

## 1. 概要
Google Earth Engine（GEE）Python APIを用いて、Landsat 8のLSTを算出する。  
`lst_method` により **Simple法** または **SMW法** を選択できるが、  
本研究では **SMW法** を使用する。

---

## 2. 入力
### 2.1 設定CSV
**ファイル**: `data/input/gee_calc_LST_info.csv`

| キー | 説明 | 例 |
|---|---|---|
| `roi_shapefile_path` | ROIのShapefile | `data/GISData/ROI/hanoi.shp` |
| `start_date` | 開始日 | `2023-07-01` |
| `end_date` | 終了日 | `2023-08-31` |
| `cloud_threshold` | 雲量閾値（現行コードでは未使用） | `30` |
| `valid_pixel_threshold` | 有効ピクセル比（%） | `50` |
| `output_epsg` | 出力EPSG | `4326` |
| `lst_method` | `simple` or `smw` | `smw` |
| `gee_project_id` | GCPプロジェクトID | `YOUR_GCP_PROJECT_ID` |
| `city_name` | 都市名（Driveフォルダ命名に使用） | `hanoi` |
| `drive_root_folder` | Driveルート名（未指定時はMasterResearch_Data） | `MasterResearch_Data` |
| `drive_export_folder` | エクスポート先フォルダ名の明示指定（任意） | `MasterResearch_Data_LST_hanoi_2023` |

### 2.2 ROI Shapefile
現行コードは `load_roi_from_shapefile_jp()` を使用し、  
`N03_001 == '大阪府'` のジオメトリを抽出する前提。  
別の地域や属性を使う場合は関数内条件の変更が必要。

---

## 3. 使用データ
- **Landsat 8 C02 T1_L2（SR）**: `LANDSAT/LC08/C02/T1_L2`
- **Landsat 8 C02 T1_TOA（B10）**: `LANDSAT/LC08/C02/T1_TOA`
- **ASTER GED v3**: `NASA/ASTER_GED/AG100_003`
- **NCEP/NCAR Reanalysis**: `NCEP_RE/surface_wv`

---

## 4. 処理フロー
1. GEE認証
2. CSV読込
3. ROI読込（Shapefile → ee.Geometry）
4. Landsat 8 SR/TOAコレクション取得
5. 雲・影・巻雲マスク（QA_PIXEL）
6. LST計算（`simple` または `smw`）
7. ROI内の統計量算出
8. CSV保存、必要に応じてGeoTIFFエクスポート

---

## 5. LST計算

### 5.1 Simple法（`lst_method="simple"`）
`ST_B10` を使用し、温度変換のみ。

$$
T_{\text{K}} = ST\_B10 \times 0.00341802 + 149.0
$$
$$
T_{\text{C}} = T_{\text{K}} - 273.15
$$

### 5.2 SMW法（`lst_method="smw"`）
Ermida et al. (2020) に準拠。

- **NDVI**: `SR_B5`/`SR_B4` を反射率スケールに変換して計算  
  `SR = SR_B* × 0.0000275 − 0.2`
- **FVC**:
  $$
  FVC = \left(\frac{NDVI - 0.2}{0.86 - 0.2}\right)^2
  $$
- **ASTER emissivity**:
  - EM_bare（植生補正あり）
  - EM0（植生補正なし）
- **emissivity選択**:
  - `use_ndvi=True` → EMd
  - `use_ndvi=False` → EM0  
  ※ `calculate_lst_smw()` の引数。既定は `True`。
- **TPW**:
  - NCEPの当日00:00〜翌日00:00（UTC）を対象
  - 近い2時刻で線形補間
  - 当日データ無しなら `-999`（後段でマスク）
  - 6 kg/m²刻みで `TPWpos` を作成
- **SMW本体**:
  $$
  LST_{\text{K}} = A \times \frac{T_b}{\varepsilon} + \frac{B}{\varepsilon} + C
  $$
  $$
  LST_{\text{C}} = LST_{\text{K}} - 273.15
  $$

---

## 6. 雲マスク（SRのみ）
`QA_PIXEL` を使用し、  
bit 3（影）、bit 4（雲）、bit 2（巻雲）が0の画素を残す。

---

## 7. 出力
### 7.1 CSV
**ファイル**: `data/output/gee_calc_LST_results.csv`

主要列:
- `mean_temp_c`, `min_temp_c`, `max_temp_c`, `std_temp_c`（摂氏）
- `valid_pixel_ratio`（%）
- `cloud_cover`（Landsatメタデータ）
- `exported`（GeoTIFF出力有無）

### 7.2 GeoTIFF
**ファイル名**: `LST_Landsat8_YYYYMMDD.tif`  
**内容**: LST（摂氏）1バンド  
**CRS**: CSVの `output_epsg` を使用

**Google Drive出力先フォルダ**:
- `drive_export_folder` が設定されている場合は、そのフォルダへ出力
- 未設定の場合は以下の規則で自動生成
  - `{drive_root_folder}_LST_{city_name}_{YYYY}`
  - 例: `MasterResearch_Data_LST_hanoi_2023`

---

## 8. 実装上の注意
- 現行実装は **Landsat 8専用**。
- LSTは **摂氏（°C）出力**。
- `cloud_threshold` は現行コードで未使用。
- `use_ndvi` を変更したい場合は `calculate_lst_smw()` 呼び出しに引数を追加する。
