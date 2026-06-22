# calc_urban_params 設計再定義ガイド

**最終更新**: 2026-06-14  
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

> **本節の位置づけ**: 本節で挙げる建物・道路・水域・植生・標高のGIS入力は、いずれも入力データ・算出方法が確定していない検討中の案である。  
> 現時点で設計確定済みなのは衛星由来指標（5.3節）のみであり、GIS由来パラメータは各パラメータ単位の別Issueで入力源・算出方法を確定したうえで出力仕様（6章）に追加する。

### 5.2.1 Limited

- OpenStreetMap / Geofabrik 由来の道路ライン
- Microsoft GlobalMLBuildingFootprints / Google Open Buildings / OSM `building=*` / GlobalBuildingAtlas 等の建物ポリゴン
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

出力先: `data/csv/analysis/urban_params_<scenario>_<city_id>_<scale>m.csv`

`<scale>` は coarseグリッド解像度（m）で、既定では `30` / `90` / `300` の3ファイルを出力する。  
各パラメータ列には `_<scale>`（例: `NDVI_30`）のサフィックスを付与する。旧実装の `_0` サフィックスは廃止した。

> **設計確定状況**: 現時点で出力仕様として設計確定済みなのは、座標列・衛星由来指標（6.2節）・品質管理列（6.3節）のみである。  
> 建物・道路・水域・植生・標高などGIS由来パラメータ（`BUILD_COV` 等、6.4節）は検討中の案であり、各パラメータの入力データ・算出方法を別Issueで個別に確定したうえで本仕様へ追加する。`params/buildings.py` 等のstubモジュールは追加時の実装場所を確保する足場であり、列構成そのものを確定したものではない。

### 6.1 必須列

- `lon`, `lat`（coarseセル中心座標、WGS84）

### 6.2 条件付き列（衛星由来、設計確定済み）

- `NDVI_<scale>`, `NDBI_<scale>`, `NDWI_<scale>`, `FVC_<scale>`（`--satellite-dir` で入力がある指標のみ出力）

### 6.3 品質管理列

- `IN_ANALYSIS_AREA`（解析範囲レイヤ内のセルか）
- `VALID_GIS_MASK`（少なくとも1つのGIS指標が有効なセル。`satellite_only` では常に0）
- `VALID_SATELLITE_MASK`（少なくとも1つの衛星指標がNaNでないセル。`--satellite-dir` 未指定時は常に0）
- `MISSING_REASON`（GIS指標の主要欠損理由。`none` / `no_gis_feature`）
- `DATA_SOURCE`（`satellite` / `open_gis` / `survey_gis`）
- `SCENARIO`（`satellite_only` / `limited` / `full`）

`satellite_only` シナリオでは、GIS由来パラメータ（6.4節）は出力されず、`lon`, `lat`, 衛星指標列、品質管理列のみとなる。

### 6.4 検討中のGIS由来パラメータ（別Issueで設計確定）

以下は入力データ・算出方法が未確定の案であり、各パラメータ単位の別Issueで設計確定後に出力仕様へ追加する。

- `BUILD_COV_<scale>`（建物被覆率, 0-1）・`BUILD_DEN_<scale>`（建物数密度, 棟数/ha）: Issue #7で検討
- `ROAD_DEN_<scale>`（道路密度, m/ha）: 別Issueで検討
- `WATER_COV_<scale>`（水域被覆率, 0-1）・`GREEN_COV_<scale>`（植生被覆率, 0-1）: 入力源未確定。サブIssue起案が必要
- `ELEV_MEAN_<scale>`（標高平均）・`ELEV_COUNT_<scale>`（標高値の有効点数）: 算出方法未確定。別Issueで検討

> `BUILD_DEN` / `ROAD_DEN` を追加する場合、スケール間（30/90/300m）で値の意味を揃えるため面積あたり（/ha）に正規化する案がある。算出には `grid.cell_area_ha()` を使用する想定。

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
| `BUILD_COV_<scale>`, `BUILD_DEN_<scale>` | `params/buildings.py: compute()`（現状stub・空dict） | 未確定。Issue #7で設計・実装予定 |
| `ROAD_DEN_<scale>` | `params/roads.py: compute()`（現状stub・空dict） | 未確定。別Issueで設計・実装予定 |
| `ELEV_MEAN_<scale>`, `ELEV_COUNT_<scale>` | `params/elevation.py: compute()`（現状stub・空dict） | 未確定。別Issueで設計・実装予定 |
| `WATER_COV_<scale>`, `GREEN_COV_<scale>` | （未割当） | 未確定。stubモジュールも未作成。入力源確定後にサブIssue起案が必要 |

---

## 7. 処理設計（モジュール構成・関数責務）

`src/analysis/urban_params/` パッケージは責務ごとにモジュールを分割している。

```
src/analysis/urban_params/
  __init__.py
  __main__.py        # python -m src.analysis.urban_params のエントリーポイント
  config.py           # CITY_CONFIG, SCENARIO_LAYER_KEYS
  grid.py             # BBox, GridSpec, build_grid, transform_bbox, grid_centers_wgs84, cell_area_ha
  geometry.py         # ジオメトリ投影・ラスタ化・被覆率/密度算出の共通処理
  io.py               # LayerResource, レイヤ・ラスタの解決と読み込み
  params/
    raster.py         # 衛星指標（NDVI/NDBI/NDWI/FVC）のグリッド集約
    buildings.py       # 建物パラメータ（BUILD_COV/BUILD_DEN等。実装はIssue #7）
    roads.py            # 道路パラメータ（ROAD_DEN。実装は別Issue）
    elevation.py       # 標高パラメータ（ELEV_MEAN/ELEV_COUNT。実装は別Issue）
  run.py              # main(): シナリオ・マルチスケール出力のオーケストレーション
```

各 `params/*.py` は共通の `compute()` シグネチャを持つ（`raster.py` のみ別シグネチャ）。

```python
def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """列名（サフィックス無し） -> coarse_shape の2次元配列、を返す。"""
```

`resource` が `None`（シナリオでレイヤ未指定）または未実装の場合は空dict `{}` を返し、`run.py` は返り値の各キーに `_<scale>` を付与して出力列に追加する。

### 7.1 Step A: 解析範囲・グリッド準備

- シナリオに応じて公開 GIS 範囲または RG レイヤのBBoxを取得
- ROI / 公開GIS は必要時のみ解析用投影座標（既定: EPSG:5897）へ投影
- `--scales` で指定した各スケールについて、coarseグリッド（既定10m補助グリッド付き）を作成

### 7.2 Step B: GIS由来指標（検討中、6.4節参照）

> 本節の `BUILD_COV` 等の列名・入力源はいずれも検討中の案であり、6.4節の通り設計未確定である。各パラメータは別Issueで個別に確定する。

- 建物（Google Open Buildings / OSM / GlobalBuildingAtlas / DC）
  - `BUILD_COV`: ポリゴン被覆率（fine→coarse平均）
  - `BUILD_DEN`: 棟数密度（棟数/ha）
- 道路（OSM / GT）
  - `ROAD_DEN`: 道路密度（m/ha）
- 水系（OSM water / TH / DH）
  - `WATER_COV`: 水域被覆率
- 植生（TV / OSM landuse 等）
  - `GREEN_COV`: 植生被覆率
- 等高線/標高点（DH）
  - 点属性から数値標高を抽出し、セル平均を算出する案を第一候補とする

> 測量由来GISのレイヤ意味は最終的に固定し切れていない部分があるため、  
> 特に `WATER_COV`, `GREEN_COV`, `ELEV_MEAN` の入力源は今後の確認で更新され得る。  
> `limited` シナリオの建物データソースは GlobalBuildingAtlas（`hanoi_gba_buildings.gpkg`）を使用する。

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
- エラーメッセージは日本語で明示

---

## 10. CLI仕様

```bash
python -m src.analysis.urban_params --city hanoi \
  --scenario limited \
  --scales 30 90 300 --fine-res 10 \
  --satellite-dir data/output/indices/2023/INDICES_Landsat8_20230707_032329Z.tif
```

主要引数:

- `--city`: 都市ID（例: hanoi）
- `--scenario`: `satellite_only` / `limited` / `full`
- `--scales`: 出力するcoarseグリッド解像度（m）の一覧（既定: `30 90 300`）
- `--fine-res`: 被覆率計算の補助解像度（既定10m）
- `--satellite-dir`: 任意。衛星指標ラスタの単一ファイルまたは格納ディレクトリ
- `--mask-layer-key`: 解析範囲の基準レイヤ。未指定時は `satellite_only`/`limited` で `roi`、`full` で `rg`

### 10.1 現在の実装状況（2026-06-14）

- `config.py` の `limited` シナリオは `data/output/open_gis/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas）の `buildings` と `data/output/open_gis/hanoi_osm_roads.gpkg` の `roads` をレイヤとして解決可能だが、対応する `params/buildings.py` / `params/roads.py` がstub（空dict）のため、現段階では出力列には反映されない。
- GIS由来パラメータ（`BUILD_COV` / `BUILD_DEN` / `ROAD_DEN` / `WATER_COV` / `GREEN_COV` / `ELEV_MEAN` / `ELEV_COUNT`）は6.4節の通りいずれも設計未確定であり、`limited` / `full` シナリオでも現段階では出力されない。
- `satellite_only` はGIS入力を使用せず、衛星指標と品質管理列のみを出力する。
- `params/buildings.py` / `params/roads.py` / `params/elevation.py` は、将来パラメータ追加時の実装場所を確保するstub（空dictを返す）であり、算出方法の設計は別Issue（#7等）で行う。
- 解析範囲の外接 bbox でスケールごとにグリッドを作成した後、基準レイヤのポリゴン内セル（`IN_ANALYSIS_AREA == 1`）のみを CSV に出力する。
- 衛星指標は `INDICES_*.tif` のバンド説明（NDVI, NDBI, NDWI）から検出する。複数観測ファイルを含むディレクトリではなく、単一観測ファイルを指定する。
- 出力先は `data/csv/analysis/urban_params_<scenario>_<city_id>_<scale>m.csv` とする。
- 実行には `fiona`, `rasterio`, `shapely`, `pyproj` を含む `environment.yml` 相当の Python 環境が必要である。

---

## 11. 検証項目（最低限）

- 各スケール（30/90/300m）の出力CSVに `lon`, `lat`, 品質管理列（6.3節）が存在する
- 入力した衛星指標（`NDVI_<scale>` 等）が出力され、値が妥当な範囲に収まる
- 座標列 `lon`, `lat` がハノイ近傍範囲に入る
- `DATA_SOURCE` / `SCENARIO` が想定シナリオと一致する
- GIS由来パラメータ（6.4節）を追加する際は、被覆率（0-1）・密度（負値なし）・有効カバレッジ内かどうかの確認を、各パラメータのサブIssueで検証項目として追加する

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
