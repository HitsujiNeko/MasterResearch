# Landsat 8 LST算出レポート（GEE + Python）

**最終更新**: 2026-02-26  
**関連ドキュメント**:  
- 研究計画 → [research_guide.md](../01_planning/research_guide.md)  
- 実装仕様 → [gee_calc_LST.md](gee_calc_LST.md)  
- SMW法の原典 → [previous_studies_report.md S1](../04_archive/previous_studies_report.md)  
- 実装コード → [src/gee/gee_calc_LST.py](../../src/gee/gee_calc_LST.py)  
- ドキュメント全体 → [docs/README.md](../README.md)

**前提知識**: RQ1-RQ3の理解、GEEの基礎知識

---

## 1. 目的
Landsat 8の地表面温度（LST: Land Surface Temperature）を、Google Earth Engine（GEE）とPythonで算出する。  
本レポートはErmida et al. (2020) のSMW（Statistical Mono-Window）法に準拠した実装内容と結果の記録を目的とする。

---

## 2. 使用データ
- **Landsat 8 C02 T1_L2（SR）**: `LANDSAT/LC08/C02/T1_L2`  
  NDVI/FVC/QA_PIXEL等の計算に使用
- **Landsat 8 C02 T1_TOA（B10）**: `LANDSAT/LC08/C02/T1_TOA`  
  SMWの輝度温度（Tb）に使用
- **ASTER GED v3**: `NASA/ASTER_GED/AG100_003`  
  emissivity推定に使用
- **NCEP/NCAR Reanalysis**: `NCEP_RE/surface_wv`  
  TPW（Total Precipitable Water）に使用

---

## 3. 入力パラメータ（CSV）
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

---

## 4. 処理フロー（SMW/ Simple共通）
1. GEE認証
2. ROI読み込み（Shapefile → ee.Geometry）
3. Landsat 8 SR/TOAコレクション取得
4. 雲・影マスク（QA_PIXEL）
5. LST計算（`simple` または `smw`）→　研究では SMW法を使用
6. ROI内の統計量算出
7. CSV保存、必要に応じてGeoTIFFエクスポート

---

## 5. LST算出ロジック

### 5.1 Simple法（`lst_method="simple"`）　
Landsat 8の `ST_B10` を利用し、温度変換のみを実施。

$$
T_{\text{K}} = ST\_B10 \times 0.00341802 + 149.0
$$
$$
T_{\text{C}} = T_{\text{K}} - 273.15
$$

出力のLSTは摂氏（°C）。

---

### 5.2 SMW法（`lst_method="smw"`）
Ermida et al. (2020) に準拠したSMW法。

#### 5.2.1 NDVI
SR_B5/SR_B4を反射率にスケール変換してNDVIを計算する。

$$
NDVI = \frac{NIR - Red}{NIR + Red}
$$

スケール変換:
$$
SR = SR\_B* \times 0.0000275 - 0.2
$$

#### 5.2.2 FVC
$$
FVC = \left(\frac{NDVI - 0.2}{0.86 - 0.2}\right)^2
$$
0〜1にクリップ。

#### 5.2.3 ASTER emissivity（EM_bare / EM0）
ASTER NDVIからASTER FVCを算出し、以下で裸地emissivityを推定。

$$
\varepsilon_{\text{bare}} = \frac{\varepsilon_{\text{ASTER}} - 0.99 \times FVC_{\text{ASTER}}}{1 - FVC_{\text{ASTER}}}
$$

Landsat 8のTIRに合わせた合成:
$$
\varepsilon_{\text{bare}} = 0.6820 \times \varepsilon_{13} + 0.2578 \times \varepsilon_{14} + 0.0584
$$

さらに、植生補正を入れないEM0も同じ係数で算出する:
$$
\varepsilon_{0} = 0.6820 \times \varepsilon_{13} + 0.2578 \times \varepsilon_{14} + 0.0584
$$

#### 5.2.4 emissivity（EM）
`use_ndvi=True` の場合は動的emissivity（EMd）、`False` の場合はEM0。

$$
\varepsilon_{\text{d}} = 0.99 \times FVC + (1 - FVC) \times \varepsilon_{\text{bare}}
$$

QA_PIXELの水域（bit 7）と雪氷（bit 5）は固定値で上書き。
- 水域: 0.99
- 雪氷: 0.989

#### 5.2.5 TPW（Total Precipitable Water）
NCEPの当日00:00〜翌日00:00（UTC）のみを対象。  
取得時刻に最も近い2つのNCEP時刻を選び、線形補間する。

$$
TPW = TPW_1 \times w_2 + TPW_2 \times w_1
$$

当日にデータが存在しない場合は `-999` を設定し、後段でマスクする。

TPWは6 kg/m²刻みでビン分けし、`TPWpos` を作成。

| TPWpos | 範囲 (kg/m²) |
|---|---|
| 0 | (0, 6] |
| 1 | (6, 12] |
| 2 | (12, 18] |
| 3 | (18, 24] |
| 4 | (24, 30] |
| 5 | (30, 36] |
| 6 | (36, 42] |
| 7 | (42, 48] |
| 8 | (48, 54] |
| 9 | (54, +∞) |

#### 5.2.6 SMW LST
TPWposに対応する係数（A, B, C）を適用:

$$
LST_{\text{K}} = A \times \frac{T_b}{\varepsilon} + \frac{B}{\varepsilon} + C
$$

TPW < 0 の画素はマスク。最後に摂氏変換:

$$
LST_{\text{C}} = LST_{\text{K}} - 273.15
$$

---

## 6. 出力

### 6.1 CSV
**ファイル**: `data/output/gee_calc_LST_results.csv`

主な列:
- `mean_temp_c`, `min_temp_c`, `max_temp_c`, `std_temp_c`（摂氏）
- `valid_pixel_ratio`（%）
- `cloud_cover`（Landsatメタデータ）
- `exported`（GeoTIFFの出力有無）

### 6.2 GeoTIFF
**ファイル名**: `LST_Landsat8_YYYYMMDD.tif`  
**内容**: LST（摂氏）1バンド  
**CRS**: CSVの `output_epsg` を使用

---

## 7. 留意点
- 現行実装は **Landsat 8専用**。
- LSTは **摂氏（°C）出力**。
- `use_ndvi` は既定で `True`。ASTER EM0を使う場合は `False` を指定する。
