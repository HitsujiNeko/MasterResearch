# calc_urban_params 設計再定義ガイド

**最終更新**: 2026-08-05  
**関連ドキュメント**: [analysis_workflow.md](analysis_workflow.md), [available_gis_data.md](../01_planning/available_gis_data.md), [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md), [CodingRule.md](CodingRule.md)  
**前提知識**: RQ1-RQ3、CRS（WGS84/UTM）、ラスタ/ベクタ処理の基礎

---

## 1. 本ガイドの位置づけ

本ドキュメントは、都市構造パラメータ算出処理（`src/analysis/urban_params/` パッケージ）の設計正本です。  
次の目的を持つ実装設計書として扱います。

- 都市構造パラメータ算出処理の責務を再定義する
- GIS由来と衛星由来の説明変数を同一フレームで扱う
- LSTとの空間整合ルール（ROI→GIS有効域）を明文化する
- 再現可能な入出力仕様を固定する
- `Satellite Only` / `Limited` / `Full` の3シナリオ・複数スケール（30/90/300m）で使える設計を明文化する

> 旧実装 `src/analysis/calc_urban_params.py`（30m・単一シナリオの探索版）はfrozenとして残置されており、新規実装・実行はすべて `src/analysis/urban_params/` パッケージ（`python -m src.analysis.urban_params`）を使用する。

---

## 2. 再構築が必要な理由

### 2.1 既存実装・既存文書の課題

- 既存コードは探索段階の近似実装であり、研究手順としての固定仕様が不十分
- レイヤ意味（DH/THなど）と変数定義の整合が曖昧な箇所がある
- 測量由来GISを前提にした記述が多く、公開 GIS にも適用できる設計になっていない
- GIS由来のみを中心に設計され、衛星由来指標との統合設計が弱い
- データ品質管理列（欠損理由、有効フラグなど）が不足

### 2.2 再構築方針

- 「まず設計を固定し、その設計に実装を合わせる」
- 旧コードの部分修正ではなく、責務単位で作り直す
- 研究手順の根拠は `analysis_workflow.md` と整合させる

---

## 3. 用語と空間整合ルール

### 3.1 重要な前提

- LSTはGEE算出時点でROI（行政区画）にクリップ済み
- 公開 GIS は ROI 全体を覆える場合があるが、データセットごとに有効カバレッジが異なる
- 測量GISはROI内の一部（中心部の矩形領域）である

### 3.2 分析時の空間整合

1. LSTはROIクリップ済みデータを入力する  
2. `Limited` では公開 GIS の有効カバレッジ、`Full` では測量 GIS 有効域で分析対象を限定する  
3. その結果、LSTとの結合時には「ROI内かつシナリオごとのGIS有効域内」のセルが対象になる

> これは不整合ではなく、処理段階の違いである。

---

## 4. スコープ定義（本スクリプトが担う範囲）

### 4.1 担当範囲

- 30mグリッドの生成（計算はUTM）
- GIS由来パラメータ算出
- 衛星由来ラスタ指標の30mグリッド集約（任意入力）
- シナリオ別の分析用説明変数CSVの出力

### 4.2 非担当範囲

- LST算出（`src/gee/gee_calc_LST.py`）
- モデル構築・評価（RQ1-RQ3の回帰/ML処理）
- 可視化スクリプト

---

## 5. 入力仕様（再定義）

## 5.1 必須入力（共通）

- ROI でクリップ済みの LST ラスタ
- 30m グリッド化対象となる GIS データ一式
- 解析範囲を定義するポリゴンまたは境界データ

## 5.2 シナリオ別入力（GIS、検討中）

> **本節の位置づけ**: 本節で挙げる水域・植生のGIS入力は、入力データ・算出方法が確定していない検討中の案である。  
> 建物・道路・標高（Limited）は入力源・算出方法とも確定し、出力仕様（6章）に反映済みである。残るパラメータは各パラメータ単位の別Issueで確定したうえで出力仕様へ追加する。

### 5.2.1 Limited

- OpenStreetMap / Geofabrik 由来の道路ライン
- Microsoft GlobalMLBuildingFootprints / Google Open Buildings / OSM `building=*` / GlobalBuildingAtlas 等の建物ポリゴン
- **オープンソースDEMラスタ**（`data/gis/dem/fabdem/fabdem_hanoi_dem.tif`、FABDEM v1.2、EPSG:4326、約30m）
- 必要に応じて OSM 土地利用・水域ポリゴン

> Hanoi ROI では、現行の Microsoft 建物データが西側行政区画を十分に覆っていない。  
> そのため、Microsoft 由来の `BUILD_COV_0` / `BUILD_DEN_0` は、建物データの有効カバレッジ外では建物不存在を意味しない。

### 5.2.2 Full

- `整備データ/merge/merge_RG.gpkg`（分析範囲定義）
- `整備データ/merge/merge_DC.gpkg`（建物）
- `整備データ/merge/merge_GT.gpkg`（道路）
- `整備データ/merge/merge_TH.gpkg` または `merge_DH.gpkg`（水系・標高関連、利用方法は要確認）
- `整備データ/merge/merge_TV.gpkg`（植生・土地利用）

> DH / TH / TV のどれを水域率・標高・植生率に使うかは、`gpkgの確認結果.md` と `DGNファイル内容確定結果.md` を踏まえて最終確定する。  
> 現時点では完全確定ではなく、実装と並行して調整中である。

## 5.3 任意入力（衛星指標ラスタ）

任意で次のGeoTIFFを指定可能とする。

- NDVI
- NDBI
- NDWI
- FVC

入力が存在する指標のみ列を出力し、存在しない指標は処理を継続する。

---

## 6. 出力仕様

出力先: `data/output/urban_params/urban_params_<scenario>_<city_id>_<scale>m.csv`

`<scale>` は coarseグリッド解像度（m）で、既定では `30` / `90` / `300` の3ファイルを出力する。  
各パラメータ列には `_<scale>`（例: `NDVI_30`）のサフィックスを付与する。旧実装の `_0` サフィックスは廃止した。

> **設計確定状況**: 座標列・衛星由来指標（6.2節）・品質管理列（6.3節）に加え、GIS由来パラメータのうち `ROAD_DEN_<scale>`、建物パラメータ4種（`BUILD_COV_<scale>` / `BUILD_DEN_<scale>` / `BUILD_H_MEAN_<scale>` / `BUILD_H_MAX_<scale>`）、標高パラメータ2種（`ELEV_MEAN_<scale>` / `ELEV_VALID_RATIO_<scale>`、`limited` のみ）は確定・実装済みである（6.4節）。  
> 残るGIS由来パラメータ（水域・植生）は検討中の案であり、各パラメータの入力データ・算出方法を個別に確定したうえで本仕様へ追加する。該当するstubモジュールは追加時の実装場所を確保する足場であり、列構成そのものを確定したものではない。

### 6.1 必須列

- `lon`, `lat`（coarseセル中心座標、WGS84）

### 6.2 条件付き列（衛星由来、設計確定済み）

- `NDVI_<scale>`, `NDBI_<scale>`, `NDWI_<scale>`, `FVC_<scale>`（`--satellite-dir` で入力がある指標のみ出力）

### 6.3 品質管理列

- `IN_ANALYSIS_AREA`（解析範囲レイヤ内のセルか）
- `VALID_GIS_MASK`（少なくとも1つのGIS指標が有効なセル。`satellite_only` では常に0）
  - **判定材料に標高由来の列（`ELEV_MEAN_<scale>` / `ELEV_VALID_RATIO_<scale>`）は含めない。** 判定は「値が0より大きいセルを有効」とみなすが、これは被覆率・密度のような「地物の量」を前提とした基準である。標高は連続量であり `0` は「データが無い」ではなく海抜0mを意味するため、この基準の適用自体が不適切である。有効画素率も「DEMが覆っているか」を表す指標であり、建物・道路データの有無とは別の軸である。加えて標高を含めるとROI内のほぼ全セルが有効となり、本列が「建物・道路データが存在するか」という本来の意味を失う
- `VALID_SATELLITE_MASK`（少なくとも1つの衛星指標がNaNでないセル。`--satellite-dir` 未指定時は常に0）
- `MISSING_REASON`（GIS指標の主要欠損理由。`none` / `no_gis_feature`）
- `DATA_SOURCE`（`satellite` / `open_gis` / `survey_gis`）
- `SCENARIO`（`satellite_only` / `limited` / `full`）

`satellite_only` シナリオでは、GIS由来パラメータ（6.4節）は出力されず、`lon`, `lat`, 衛星指標列、品質管理列のみとなる。

### 6.4 GIS由来パラメータ

#### 確定済みパラメータ

- **`ROAD_DEN_<scale>`（道路密度, m/ha）**: 設計確定・実装済
  - **入力**: `data/gis/roads/hanoi_osm_roads.gpkg`（OSM Geofabrik 由来）
  - **フィルタリング**: ホワイトリスト方式。motorway〜living_street + service を含め、非車道（footway, steps, path 等）・track・construction・proposed・特殊用途を除外。z_order < 0（トンネル・地下道）も除外
  - **算出方法**: `compute_line_length()` でセル内ライン総延長（m/cell）を算出し、`cell_area_ha()` で面積正規化
  - **詳細**: [gis_data_roads.md](../01_planning/gis_data/gis_data_roads.md) セクション 2

- **建物パラメータ4種**: 設計確定・実装済
  - **入力**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas 由来）
  - `BUILD_COV_<scale>`（建物被覆率, 0-1）: fine グリッドへラスタ化し coarse セルへ平均集約
  - `BUILD_DEN_<scale>`（建物棟数密度, 棟/ha）: 重心が属するセルごとの棟数を `cell_area_ha()` で正規化
  - `BUILD_H_MEAN_<scale>` / `BUILD_H_MAX_<scale>`（建物高さ, m）: 重心が属するセルごとの有効高さの平均・最大
  - **高さの除外条件**: 推定分散または高さ自体が負・欠測の建物を高さ集計から除外（被覆率・棟数密度からは除外しない）
  - **欠測規約**: セル内に有効高さの建物が無い場合、高さは 0.0 ではなく **NaN**
  - **解釈上の注意**: `BUILD_COV = 0` は建物の不存在を意味しない（30m では建物のあるセルの14%が該当）。建物の有無は `BUILD_DEN` で判定する
  - **詳細**: [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) セクション 3

- **`ELEV_MEAN_<scale>`（平均標高, m）**: 設計確定・実装済（`limited` シナリオのみ）
  - **入力**: `data/gis/dem/fabdem/fabdem_hanoi_dem.tif`（FABDEM v1.2、EPSG:4326、nodata `-9999`）
  - **算出方法**: 衛星指標と共通の `aggregate_raster_to_grid()` により coarse グリッドへ `Resampling.average` で再投影し、セル平均標高を得る
  - **欠測規約**: 有効カバレッジ外は **NaN**。`0` は「データが無い」ではなく**海抜0m の実測値**であり、両者を同一視しない
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は6.3節）
  - **セルの信頼度**: 平均はセル内の**有効画素のみ**で取るため、値の有無だけでは部分被覆セルを判別できない。判別には `ELEV_VALID_RATIO_<scale>` を用いる
  - **解釈上の注意**:
    - FABDEM は Copernicus GLO-30 をランダムフォレスト回帰で補正した準DTMであり、生のDSMではない。ただし高密度キャノピー・急峻地形では補正残差が残る
    - 垂直基準面は EGM2008 であり、0m は平均海面と厳密には一致しない
    - ライセンスは CC BY-NC-SA 4.0（非商用）。論文・資料への帰属文記載が必須
    - **`scale=30` では集約が実質的なリサンプリングになる**（FABDEM の画素はハノイの緯度で東西約28m・南北約30m）。「セル内の面積平均標高」とは言えないため、RQ2 のスケール間比較で30mの値を過大解釈しない
  - **詳細**: [gis_data_dem.md](../01_planning/gis_data/gis_data_dem.md)

- **`ELEV_VALID_RATIO_<scale>`（DEM有効画素率, 0-1）**: 設計確定・実装済（`limited` シナリオのみ）
  - **入力**: `ELEV_MEAN_<scale>` と同一のDEMラスタ
  - **算出方法**: 有効画素を1・nodataを0とした配列を、`ELEV_MEAN` と同じ `Resampling.average` で coarse グリッドへ再投影する
  - **必要性**: `Resampling.average` はセル内の**有効画素のみ**で平均を取るため、セルの1割しかDEMに覆われていなくても、完全に覆われたセルと同じ実数が `ELEV_MEAN` に入る。`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する（実測では `IN_ANALYSIS_AREA == 1` のうち、300mスケールで `NaN` は0.013%である一方、有効画素率99%未満は4.67%・50%未満は2.42%）
  - **欠測規約**: ラスタ範囲外のセルは `NaN` ではなく **`0.0`**（nodataで覆われたセルと同じ「有効画素なし」を意味するため揃える）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は6.3節）
  - **解釈上の注意**: 入力ラスタの外周より外側（画素が1つも無い領域）が占める分は比率に反映されないため、ラスタの矩形範囲を一部しか含まないセルでは実際の被覆より高い値になり得る。現行の入力（ROIでcrop済みのDEM）では解析BBox最外周のセルに限られる
  - **`ELEV_COUNT_<scale>`（セル内の有効点数）は出力しない**（スケールによって画素数の意味が変わり、比率のほうがスケール間で比較可能なため）

> `full` シナリオの標高は未確定である（現状は出力しない）。測量GISの `merge_DH.gpkg`（点・等高線）による標高、または FABDEM の暫定適用のいずれを採るかは別途判断する。

#### 検討中のパラメータ（別途設計確定）

以下は入力データ・算出方法が未確定の案であり、パラメータ単位で設計確定後に出力仕様へ追加する。

- `WATER_COV_<scale>`（水域被覆率, 0-1）・`GREEN_COV_<scale>`（植生被覆率, 0-1）: 入力源未確定。サブIssue起案が必要

> スケール間（30/90/300m）で値の意味を揃えるため、密度系パラメータは面積あたり（/ha）に正規化する。算出には `grid.cell_area_ha()` を使用する。

### 6.5 出力列と算出モジュールの対応

ソースコードを読まずに「どの列がどのモジュール・関数で算出されるか／設計確定状況」を確認できるよう、対応関係を以下に示す。

| 列名 | 算出モジュール・関数 | 設計確定状況 |
|---|---|---|
| `lon`, `lat` | `grid.grid_centers_wgs84()` | 確定・実装済 |
| `NDVI_<scale>`, `NDBI_<scale>`, `NDWI_<scale>`, `FVC_<scale>` | `params/raster.py: compute()` → `aggregate_raster_to_grid()` | 確定・実装済（`--satellite-dir` 指定時のみ） |
| `IN_ANALYSIS_AREA` | `geometry.compute_polygon_coverage()`（`run.run_for_scale()` 内で判定） | 確定・実装済 |
| `VALID_GIS_MASK`, `MISSING_REASON` | `run.build_quality_columns()` | 確定・実装済 |
| `VALID_SATELLITE_MASK` | `run.build_satellite_quality()` | 確定・実装済 |
| `DATA_SOURCE`, `SCENARIO` | `run.run_for_scale()` | 確定・実装済 |
| `BUILD_COV_<scale>`, `BUILD_DEN_<scale>`, `BUILD_H_MEAN_<scale>`, `BUILD_H_MAX_<scale>` | `params/buildings.py: compute()` | 確定・実装済（`limited` / `full` シナリオのみ） |
| `ROAD_DEN_<scale>` | `params/roads.py: compute()` → `geometry.compute_line_length()` / `grid.cell_area_ha()` | **確定・実装済** |
| `ELEV_MEAN_<scale>` | `params/elevation.py: compute()` → `params/raster.py: aggregate_raster_to_grid()` | **確定・実装済**（`limited` シナリオのみ） |
| `ELEV_VALID_RATIO_<scale>` | `params/elevation.py: compute()` → `params/raster.py: aggregate_valid_ratio_to_grid()` | **確定・実装済**（`limited` シナリオのみ。`ELEV_COUNT_<scale>` は出力しない） |
| `WATER_COV_<scale>`, `GREEN_COV_<scale>` | （未割当） | 未確定。stubモジュールも未作成。入力源確定後にサブIssue起案が必要 |

---

## 7. 処理設計（モジュール構成・関数責務）

`src/analysis/urban_params/` パッケージは責務ごとにモジュールを分割している。

```text
src/analysis/urban_params/
  __init__.py
  __main__.py        # python -m src.analysis.urban_params のエントリーポイント
  config.py           # CITY_CONFIG（layers/rasters）, SCENARIO_INPUT_KEYS
  grid.py             # BBox, GridSpec, build_grid, transform_bbox, grid_centers_wgs84, cell_area_ha
  geometry.py         # ジオメトリ投影・ラスタ化・被覆率/密度算出の共通処理
  io.py               # LayerResource / RasterResource, レイヤ・ラスタの解決と読み込み
  params/
    raster.py         # ラスタのグリッド集約（衛星指標 NDVI/NDBI/NDWI/FVC・有効画素率）
    buildings.py       # 建物パラメータ（BUILD_COV/BUILD_DEN/BUILD_H_MEAN/BUILD_H_MAX）
    roads.py            # 道路パラメータ（ROAD_DEN）
    elevation.py       # 標高パラメータ（ELEV_MEAN/ELEV_VALID_RATIO）
  run.py              # main(): シナリオ・マルチスケール出力のオーケストレーション
```

シナリオごとの入力キーは `SCENARIO_INPUT_KEYS` が保持する。ベクタレイヤ（`CITY_CONFIG["layers"]` のキー）とラスタ（`CITY_CONFIG["rasters"]` のキー）の両方を含むため、"LAYER" ではなく "INPUT" と呼ぶ。

各 `params/*.py` は共通の `compute()` シグネチャを持つ（`raster.py` のみ別シグネチャ）。

```python
def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """列名（サフィックス無し） -> coarse_shape の2次元配列、を返す。"""
```

`elevation.py` のみ第1引数が `RasterResource | None` であり、集約範囲は `grid_spec` が保持するため `bbox_analysis` は参照しない（他モジュールとシグネチャを揃えるために受け取る）。

`resource` が `None`（シナリオで入力未指定）または未実装の場合は空dict `{}` を返し、`run.py` は返り値の各キーに `_<scale>` を付与して出力列に追加する。

### 7.1 Step A: 解析範囲・グリッド準備

- シナリオに応じて公開 GIS 範囲または RG レイヤのBBoxを取得
- ROI / 公開GIS は必要時のみ解析用投影座標（既定: EPSG:5897）へ投影
- `--scales` で指定した各スケールについて、coarseグリッド（既定10m補助グリッド付き）を作成

### 7.2 Step B: GIS由来指標（水域・植生のみ検討中、6.4節参照）

> 建物・道路・標高（Limited）は6.4節の通り**設計確定・実装済み**である。本節の水域・植生の列名・入力源は検討中の案であり、6.4節の通り設計未確定である。各パラメータは別途個別に確定する。

**設計確定・実装済み**

- 建物（GBA / DC）
  - `BUILD_COV`: ポリゴン被覆率（fine→coarse平均、0-1）
  - `BUILD_DEN`: 棟数密度（棟/ha）
  - `BUILD_H_MEAN` / `BUILD_H_MAX`: セル内建物の平均・最大高さ（m）
- 道路（OSM / GT）
  - `ROAD_DEN`: 道路密度（m/ha）
- 標高（FABDEM、`limited` のみ）
  - `ELEV_MEAN`: DEMラスタを coarse グリッドへ平均再投影して得るセル平均標高（m）
  - `ELEV_VALID_RATIO`: セル内のDEM有効画素率（0-1）。`ELEV_MEAN` の平均が有効画素のみで取られるため、部分被覆セルの判別に必要（6.4節）
  - ベクタではなくラスタ入力のため、Step C（衛星指標）と同じ集約関数を用いる
  - 有効カバレッジ外は NaN（有効画素率は 0.0）。いずれも `VALID_GIS_MASK` の判定材料には含めない（6.3節）

**検討中**

- 水系（OSM water / TH / DH）
  - `WATER_COV`: 水域被覆率
- 植生（TV / OSM landuse 等）
  - `GREEN_COV`: 植生被覆率
- 測量GIS由来の標高（DH）
  - `full` シナリオ向けに、点属性から数値標高を抽出しセル平均を算出する案を第一候補とする

> 測量由来GISのレイヤ意味は最終的に固定し切れていない部分があるため、  
> 特に `WATER_COV`, `GREEN_COV`, および `full` シナリオの `ELEV_MEAN` の入力源は今後の確認で更新され得る。  
> `limited` シナリオの建物データソースは GlobalBuildingAtlas（`hanoi_gba_buildings.gpkg`）、標高は FABDEM v1.2 を使用する。

**共通基盤関数の算出手法と制約**:

| 関数 | 手法 | 制約・注意点 |
|---|---|---|
| `compute_polygon_coverage` | fineマスク（`rasterize` + `all_touched=False`）→ coarse平均 | ピクセル中心判定のため、fine解像度（10m）未満の細いポリゴンは被覆率0になり得る。`params/*.py` の本実装時に `all_touched=True` の検討が必要 |
| `compute_line_length` | 各ラインとcoarseセルポリゴンの `intersection.length` 合計 | 幾何学的に正確。半開セル矩形で境界二重計上を防止 |
| `count_polygon_centroids` | ポリゴン重心をcoarseセルへ割り当て | 重心が範囲外のポリゴンはカウントしない |

### 7.3 Step C: 衛星由来指標（任意）

- 各ラスタをUTMのcoarseグリッドに再投影
- `Resampling.average` でセル平均を取得
- 有効値のみ出力列に追加

### 7.4 Step D: 品質管理・出力

- 欠損理由を列に付与
- データソース種別・シナリオ種別を列に付与
- 最終CSVをUTF-8で保存
- 処理サマリ（件数、統計量）を標準出力

---

## 8. CRS・単位ルール

- 測量GISの正本座標: EPSG:5897
- 距離・面積・長さ計算: UTM（都市別の適切なEPSG）
- 温度: 摂氏（LST側の仕様に従う）
- 被覆率: 0-1
- 道路密度: m/ha（面積正規化、`grid.cell_area_ha()` で算出）
- 建物数密度: 棟数/ha（面積正規化）

---

## 9. 例外処理と堅牢性

- 不正ジオメトリは `make_valid` を試行し、失敗時はスキップ
- レイヤ名が設定値と不一致の場合は、候補レイヤを探索して自動解決
- 任意入力（衛星指標）が欠けていても処理継続
- シナリオごとに不足レイヤを検出し、不足分を明示して停止または継続判断する
- ラスタ設定の不備（`path` / `band` の欠落、バンド数を超えるバンド番号）は日本語の `ValueError` で停止する
- DEMが解析グリッドとまったく重ならない場合は警告する（ファイルは存在するため入力解決を素通りし、全セル `NaN` の列が黙って出力されるため）
- エラーメッセージは日本語で明示

---

## 10. CLI仕様

```bash
python -m src.analysis.urban_params --city hanoi \
  --scenario limited \
  --scales 30 90 300 --fine-res 10 \
  --satellite-dir data/satellite/indices/2023/INDICES_Landsat8_20230707_032329Z.tif
```

主要引数:

- `--city`: 都市ID（例: hanoi）
- `--scenario`: `satellite_only` / `limited` / `full`
- `--scales`: 出力するcoarseグリッド解像度（m）の一覧（既定: `30 90 300`）
- `--fine-res`: 被覆率計算の補助解像度（既定10m）
- `--satellite-dir`: 任意。衛星指標ラスタの単一ファイルまたは格納ディレクトリ
- `--mask-layer-key`: 解析範囲の基準レイヤ。未指定時は `satellite_only`/`limited` で `roi`、`full` で `rg`

### 10.1 現在の実装状況（2026-08-05）

- **`params/roads.py`（`ROAD_DEN`）**: 設計確定・実装済み。`limited` シナリオで `hanoi_osm_roads.gpkg` から車道のフィルタリング（ホワイトリスト + トンネル除外）を行い、セル内道路延長密度（m/ha）を算出する。
- **`params/buildings.py`（`BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX`）**: 設計確定・実装済み。`limited` シナリオで `hanoi_gba_buildings.gpkg`（GBA、3,071,511 件）から被覆率・棟数密度・平均/最大高さを算出する。件数が多いため、本モジュールのみレイヤの一括読み込みと NumPy によるベクトル化集計を採る。`full` シナリオの `merge_DC.gpkg` は高さ属性を持たないため、高さ列は NaN になる。
- **`params/elevation.py`（`ELEV_MEAN` / `ELEV_VALID_RATIO`）**: 設計確定・実装済み。`limited` シナリオで FABDEM v1.2（`fabdem_hanoi_dem.tif`）を coarse グリッドへ平均再投影し、セル平均標高（m）とセル内のDEM有効画素率（0-1）を算出する。`ELEV_COUNT` は出力しない。`full` / `satellite_only` では入力を与えないため列自体が出力されない。DEMラスタは `.gitignore` の対象であり、ファイルが無い場合は `FileNotFoundError` で停止する（列が黙って欠けるのを防ぐため）。
- `satellite_only` はGIS入力を使用せず、衛星指標と品質管理列のみを出力する。
- 解析範囲の外接 bbox でスケールごとにグリッドを作成した後、基準レイヤのポリゴン内セル（`IN_ANALYSIS_AREA == 1`）のみを CSV に出力する。
- 衛星指標は `INDICES_*.tif` のバンド説明（NDVI, NDBI, NDWI）から検出する。複数観測ファイルを含むディレクトリではなく、単一観測ファイルを指定する。
- 出力先は `data/output/urban_params/urban_params_<scenario>_<city_id>_<scale>m.csv` とする。
- 実行には `fiona`, `rasterio`, `shapely`, `pyproj` を含む `environment.yml` 相当の Python 環境が必要である。

---

## 11. 検証項目（最低限）

- 各スケール（30/90/300m）の出力CSVに `lon`, `lat`, 品質管理列（6.3節）が存在する
- 入力した衛星指標（`NDVI_<scale>` 等）が出力され、値が妥当な範囲に収まる
- 座標列 `lon`, `lat` がハノイ近傍範囲に入る
- `DATA_SOURCE` / `SCENARIO` が想定シナリオと一致する
- GIS由来パラメータ（6.4節）を追加する際は、被覆率（0-1）・密度（負値なし）・有効カバレッジ内かどうかの確認を、各パラメータのサブIssueで検証項目として追加する

**標高（`ELEV_MEAN_<scale>` / `ELEV_VALID_RATIO_<scale>`）の検証観点**

- 値域が入力DEMの統計範囲に収まり、平均が同水準である（集約により最小値は上がり最大値は下がるため、**特定の下限値を合格基準にしない**）
- 有効カバレッジ外が `NaN` であり、`0` で埋まっていない（値がちょうど `0` のセルが欠損由来でないこと）
- `IN_ANALYSIS_AREA == 1` のセルについて、標高が `NaN` の件数と**有効画素率の分布（1未満・0.5未満の件数）**をスケール別に記録する。DEMはROIでcrop済みのため境界セルで発生し得る。**`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する**ため、両方を有効カバレッジの議論に用いる
- `ELEV_VALID_RATIO` が 0-1 に収まり、`ELEV_MEAN` が `NaN` のセルで `0.0` になっている（両列の整合）
- `VALID_GIS_MASK` の分布が標高の追加前後で変わらない（品質判定に混入していないこと）
- スケール間（30/90/300m）で平均標高の水準が整合する

### 11.1 ユニットテスト

`tests/analysis/urban_params/` に、`grid.py` / `geometry.py` / `run.py` の主要関数（リファクタリングで `calc_urban_params.py` から移植したロジック）に対するユニットテストを配置している。

- 既知のジオメトリ・グリッドを用いて、被覆率・重心カウント・ライン密度・標高集計・品質管理列などの計算結果が期待値と一致することを検証する
- `pytest`（`environment.yml` に含まれる）で実行する

```bash
python -m pytest tests/
```

実行時は `pyproject.toml` の `[tool.pytest.ini_options]` によりリポジトリルートが `sys.path` に追加され、`src.analysis.urban_params` をインポートできる。

---

## 12. 今回の再構築ゴール

1. 本ガイド（設計）を正本化  
2. `urban_params` パッケージを本ガイド準拠で実装  
3. `Satellite Only` / `Limited` / `Full` の3シナリオに接続できる入力仕様を固定する
4. 研究者が「変数定義・計算根拠・制約」を追跡できる状態にする

---

## 13. 更新ルール

- 実装変更時は本ガイドを同時更新する
- 列名・単位・欠損規則を変更した場合は必ず履歴に残す
- `docs/README.md` のカタログ情報と齟齬を作らない
