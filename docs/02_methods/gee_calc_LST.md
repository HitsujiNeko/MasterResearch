# gee_calc_LST.py 仕様（Landsat 8 / 9 LST）

**最終更新**: 2026-10-18  
**関連ドキュメント**:  

- 処理結果レポート → [calc_LST_report.md](calc_LST_report.md)  
- コーディング規約 → [CodingRule.md](CodingRule.md)  
- 実装コード → [src/gee/gee_calc_LST.py](../../src/gee/gee_calc_LST.py)  
- SMWモジュール → [src/module/lst_smw.py](../../src/module/lst_smw.py)  
- 採用先行研究 → [previous_studies_report.md S1](../04_archive/previous_studies_report.md)  
- セットアップ → [setup.md](../setup.md)  
- ドキュメント全体 → [docs/README.md](../README.md)

**前提知識**: GEE Python API、Landsat 8 / 9データ構造

---

## 1. 概要

Google Earth Engine（GEE）Python APIを用いて、Landsat 8 / Landsat 9のLSTを算出する。  
`lst_method` により **Simple法** または **SMW法** を選択できるが、  
本研究では **SMW法** を使用する。

### 1.1 実装の由来

本研究で採用している LST 算出手法は、先行研究整理で **S1** として位置づけている  
**Ermida et al. (2020)** の SMW（Statistical Mono-Window）法である。  
本プログラムは、その先行研究で公開されている GEE JavaScript 実装を、研究用に Python へ書き直したものである。  
移植元は主に [`src/js/modules/Landsat_LST.js`](../../src/js/modules/Landsat_LST.js) を起点とする一連のモジュールであり、  
Python 側では [`src/gee/gee_calc_LST.py`](../../src/gee/gee_calc_LST.py) と [`src/module/lst_smw.py`](../../src/module/lst_smw.py) に再構成している。

特に SMW 手法は、以下の JavaScript モジュールを Python 関数へ対応づけて移植している。

- `compute_NDVI.js` → `compute_ndvi()`
- `compute_FVC.js` → `compute_fvc()`
- `compute_emissivity.js` / `ASTER_bare_emiss.js` → `get_aster_emissivity()`, `compute_emissivity()`
- `NCEP_TPW.js` → `get_atmospheric_water_vapor()`
- `SMWalgorithm.js` / `SMW_coefficients.js` → `apply_smw_algorithm()`

---

## 2. 入力

### 2.1 設定CSV

**ファイル**: `data/input/gee_calc_LST_info.csv`

| キー | 説明 | 例 |
|---|---|---|
| `roi_shapefile_path` | ROIのShapefile | `data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp` |
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
| `sensors` | 処理するセンサ（`;` 区切りで `L8` / `L9`）。列がない・空欄の場合は `L8` のみ | `L8;L9` |

### 2.2 ROI Shapefile

現行の `main()` は `load_roi_from_shapefile()` を使用し、  
`TinhThanh == 'Hà Nội'` のジオメトリを抽出する前提で実装されている。  
一方で、`load_roi_from_shapefile_jp()` もソース内に残っており、こちらは `N03_001 == '大阪府'` を前提としている。  
別の地域や属性を使う場合は、使用する関数とフィルタ条件の見直しが必要。

---

## 3. 使用データ

- **Landsat 8 C02 T1_L2（SR）**: `LANDSAT/LC08/C02/T1_L2`
- **Landsat 8 C02 T1_TOA（B10）**: `LANDSAT/LC08/C02/T1_TOA`
- **Landsat 9 C02 T1_L2（SR）**: `LANDSAT/LC09/C02/T1_L2`
- **Landsat 9 C02 T1_TOA（B10）**: `LANDSAT/LC09/C02/T1_TOA`
- **ASTER GED v3**: `NASA/ASTER_GED/AG100_003`
- **NCEP/NCAR Reanalysis**: `NCEP_RE/surface_wv`

> 注記: `NCEP_RE/surface_wv` は Earth Engine カタログ上で deprecated 扱い。  
> 本研究の SMW 再現性を優先し、現時点では同データセットを継続利用する。  
> 実装では、既知の deprecation 警告のみを限定的に抑制している。

---

## 4. 処理フロー

1. GEE認証
2. CSV読込
3. ROI読込（Shapefile → ee.Geometry）
4. 設定の `sensors` に従い、センサごとに SR/TOA コレクションを取得（以降の手順をセンサごとに行い、結果は観測日時の順に並べて保存する）
5. SR と TOA を同一シーンの `system:index` で対応付け
6. 雲・影マスク（QA_PIXEL）
7. LST計算（`simple` または `smw`）
8. ROI内の統計量算出
9. CSV保存、必要に応じてGeoTIFFエクスポート

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
bit 2（Cirrus）・bit 3（Cloud）・bit 4（Cloud Shadow）・bit 5（Snow）がすべて 0 の画素を残す。

ビット定義は USGS の [Landsat Collection 2 Quality Assessment Bands](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)（Landsat 8-9 QA_PIXEL Bit Index）による。
Dilated Cloud（bit 1）・Fill（bit 0）と `QA_RADSAT` は用いない（衛星指標側の `cloud_mask_sr` はこれらも除外する）。

原典 JavaScript 実装の SR マスク（`cloudmask.js` の `sr`）は bit 3・bit 4 のみを用いる。
bit 2・bit 5 を加えるのは原典からの意図的な差分であり、根拠は 8.1 に記す。

---

## 7. 出力

### 7.1 CSV

**ファイル**: `data/output/gee_calc_LST_results.csv`

主要列:

- `satellite`（`Landsat8` / `Landsat9`）
- `mean_temp_c`, `min_temp_c`, `max_temp_c`, `std_temp_c`（摂氏）
- `valid_pixel_ratio`（%）
- `cloud_cover`（Landsatメタデータ）
- `exported`（GeoTIFF出力有無）

### 7.2 GeoTIFF

**ファイル名**: `LST_{センサ}_YYYYMMDD_HHMMSSZ.tif`（センサは `Landsat8` / `Landsat9`、観測日時 UTC）  
**内容**: LST（摂氏）1バンド  
**CRS**: CSVの `output_epsg` を使用

**Google Drive出力先フォルダ**:

- `drive_export_folder` が設定されている場合は、そのフォルダへ出力
- 未設定の場合は以下の規則で自動生成
  - `{drive_root_folder}_LST_{city_name}_{YYYY}`
  - 例: `MasterResearch_Data_LST_hanoi_2023`

---

## 8. 実装上の注意

- 対応センサは **Landsat 8 と Landsat 9**。センサは設定の `sensors` 列で選び、SMW 係数はセンサ別に切り替える（8.2 参照）。
- LSTは **摂氏（°C）出力**。
- `cloud_threshold` は現行コードで未使用。
- `use_ndvi` を変更したい場合は `calculate_lst_smw()` 呼び出しに引数を追加する。

### 8.1 原典実装からの意図的な差分

- 原典 JavaScript 実装の `LST` バンドはケルビンだが、本研究では **摂氏（°C）へ変換して出力**する。
- 雲マスクに **bit 2（Cirrus）と bit 5（Snow）を加える**（原典は bit 3・bit 4 のみ）。原典の条件では、
  LST 最小値が -102.2°C となる観測があった。原典のマスクを通った異常画素（LST < -20°C）を調べると、Snow・Cirrus の
  フラグが立っており（異常画素が300画素以上の4観測で、Snow が約 50〜100%、Cirrus が 50〜99%）、
  Cloud の信頼度に「高」は無かった（Cloud フラグ自体は、原典のマスクを通った画素なので定義上 0 である）。
  対象地域（ハノイ）で雪は考えにくいため、低温の雲が雪・氷と判定されたと考えられる（推定）。
  検証の結果と候補ごとの比較は [observation_selection.md](observation_selection.md) 7.5 に記す。
  Dilated Cloud（bit 1）は加えない。bit 1 を加えると閾値未満の画素が残る異常観測は7件から5件に減るが、
  -102.2°C の観測では閾値未満の画素が 161,982 → 145,707 画素にしか減らず、主な異常は解消しなかった。

### 8.2 原典実装に合わせて維持している点

- SMW の係数テーブル（A, B, C）は原典（`SMW_coefficients.js`）のセンサ別の値（`coeff_SMW_L8` / `coeff_SMW_L9`）をそのまま用い、`lst_smw.SMW_COEFFICIENTS` でセンサごとに切り替える。
- ASTER 放射率の補間係数（c13, c14, c）は Landsat 8 の値を Landsat 9 にも用いる。原典の `compute_emissivity.js` は L4/L5/L7 以外を Landsat 8 の係数で処理し、`Landsat_LST.js` は Landsat 9 もこの経路で処理するため。
- `TPW` は **当日 UTC の NCEP データ**のみを対象にし、最も近い2時刻で線形補間する。
- SR と TOA の対応付けは、**同一シーンの `system:index`** を基準に行う。
