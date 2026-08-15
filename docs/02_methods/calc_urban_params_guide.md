# calc_urban_params 設計再定義ガイド

**最終更新**: 2026-08-15  
**関連ドキュメント**: [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md), [analysis_workflow.md](analysis_workflow.md), [available_gis_data.md](../01_planning/available_gis_data.md), [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md), [CodingRule.md](CodingRule.md)  
**前提知識**: RQ1-RQ3、CRS（WGS84/投影座標系）、ラスタ/ベクタ処理の基礎

---

## 1. 本ガイドの位置づけ

本ドキュメントは、都市構造パラメータ算出処理（`src/analysis/urban_params/` パッケージ）の設計正本です。  
次の目的を持つ実装設計書として扱います。

- 都市構造パラメータ算出処理の責務を再定義する
- GIS由来と衛星由来の説明変数を同一フレームで扱う
- LSTとの空間整合ルール（ROI→GIS有効域）を明文化する
- 再現可能な入出力仕様を固定する
- `Satellite Only` / `Limited` / `Full` の3シナリオ・複数スケール（30/90/300m）で使える設計を明文化する

### 1.1 正本の境界

説明変数をめぐる記述は3つのドキュメントに分かれる。**本ガイドが正本となるのは「採用済みパラメータの出力仕様」だけ**である。

| 内容 | 正本 |
|---|---|
| どの説明変数を採用するか（採否ステータス・概念定義・単位・根拠文献・対応RQ） | [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) |
| **採用済みパラメータの出力仕様（列名・算出方法・実装状況）** | **本ガイド 6章** |
| データソースの候補比較・空間解像度・ライセンス | [available_gis_data.md](../01_planning/available_gis_data.md) とそのカテゴリ別ドキュメント |

したがって**本ガイドには採否ステータス（採用 / 保留 / 不採用）を書かない**。採否は上記の正本を参照する。

「採否」と「設計」は独立した軸であり、「**採用済みだが設計未確定**」という状態が生じる。本ガイドで「設計未確定」と記すのは後者の軸を指し、採否が未確定であることを意味しない。

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
- 研究手順の根拠は [analysis_workflow.md](analysis_workflow.md) と整合させる。ただし**どの説明変数を扱うかの根拠は [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) を参照する**（`analysis_workflow.md` 3.1 は同ドキュメントへの参照に置き換わっている）

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

処理は**算出フェーズ**と**結合フェーズ**の2段に分かれる。

**算出フェーズ**（`src/analysis/urban_params/`）

- 正準グリッド（7.5節）に整合したマルチスケールグリッドの生成（計算は投影座標系）
- GIS由来パラメータ算出
- 衛星由来ラスタ指標のグリッド集約（任意入力）
- **パラメータセット単位の独立したテーブル**（`cell_id` キーのGeoPackage）の出力

**結合フェーズ**（`src/analysis/build_dataset.py`）

- 指定したテーブル群の `cell_id` による結合
- 結合した列からの品質管理列の導出
- 分析用データセットの出力

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

## 5.2 パラメータセット別入力（GIS）

> **本節の位置づけ**: 建物・道路・標高（`Limited`）は入力源・算出方法とも確定し、出力仕様（6章）に反映済みである。  
> 採用済みで設計が未確定なパラメータは、入力データ・算出方法をパラメータ単位で確定したうえで出力仕様へ追加する。  
> どのパラメータが採用済みかは [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) を正本とする（1.1節）。

### 5.2.0 パラメータセットの定義

「**どのパラメータを、どの入力ソースで算出するか**」の組を**パラメータセット**と呼び、`config.py` の `PARAM_SETS` に定義する。**テーブル名はパラメータセット名と一致させ、出力ファイル名・レイヤ名の双方に使う。**

| パラメータセット名 | 算出モジュール | 入力 | 出力列 |
|---|---|---|---|
| `build_gba` | `params/buildings.py` | `layers.open_buildings`（GlobalBuildingAtlas） | `BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX` |
| `build_dc` | `params/buildings.py` | `layers.dc`（測量GIS） | 同上 |
| `road_osm` | `params/roads.py` | `layers.open_roads`（OSM） | `ROAD_DEN` |
| `road_gt` | `params/roads.py` | `layers.gt`（測量GIS） | 同上 |
| `elev_fabdem` | `params/elevation.py` | `rasters.fabdem` | `ELEV_MEAN` / `ELEV_VALID_RATIO` |
| `mask_roi` | `params/mask.py` | `layers.roi` | `IN_ANALYSIS_AREA` |

**同じ列名の別ソース版を並置できる**（`build_gba` と `build_dc`、`road_osm` と `road_gt`）ことが、感度分析を「結合先の差し替えだけ」で済ませる要である。`PARAM_SETS` は各セットが返すべき列を宣言し、`compute()` の戻り値と実行時に突き合わせて、別ソース版どうしで列が食い違う状態を検知する。

**シナリオは算出側では扱わない。** シナリオは「どのテーブルを結合するか」の選択へ還元されており、`SCENARIO_TABLES`（シナリオ → 結合するテーブル名の一覧）として結合フェーズが持つ（6.6節）。

**解析範囲は当面 ROI へ一本化する。** 測量GIS（RG）を基準にするパラメータセットは設けない。RG は境界**線**主体のレイヤで 90.6% が面積ゼロであり、面積ベースの `compute_polygon_coverage()` と噛み合わないためである（7.5.6節）。**したがって `full` シナリオの有効域定義は未決のままである。**

### 5.2.1 Limited

**確定済みの入力**

- **建物ポリゴン**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas 由来）
- **道路ライン**: `data/gis/roads/hanoi_osm_roads.gpkg`（OpenStreetMap / Geofabrik 由来）
- **オープンソースDEMラスタ**: `data/gis/dem/fabdem/fabdem_hanoi_dem.tif`（FABDEM v1.2、EPSG:4326、約30m）

**設計未確定の入力**（採用済みだが入力源・算出方法が未確定）

- 植生（植生被覆率）: 土地被覆分類ラスタの植生クラス（入力源未確定。6.4節参照）
- 土地被覆クラス別面積率・人口密度・夜間光: いずれもラスタ入力。Hanoi ROI での取得は完了しているが、**同一概念に複数の候補データセットがあり、どれを入力とするかが未確定**である（候補の比較は [available_gis_data.md](../01_planning/available_gis_data.md) を参照）

> 建物データの比較候補として Microsoft GlobalMLBuildingFootprints / Google Open Buildings / OSM `building=*` を検討したが、Limited シナリオの採用は GlobalBuildingAtlas で確定している（詳細は [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md)）。  
> なお Hanoi ROI では Microsoft 建物データが西側行政区画を十分に覆っていない。比較用に用いる場合、建物データの有効カバレッジ外では被覆率・棟数密度の `0` が建物不存在を意味しない点に注意する。

### 5.2.2 Full

- `整備データ/merge/merge_RG.gpkg`（分析範囲定義）
- `整備データ/merge/merge_DC.gpkg`（建物）
- `整備データ/merge/merge_GT.gpkg`（道路）
- `整備データ/merge/merge_TH.gpkg` または `merge_DH.gpkg`（水系・標高関連、利用方法は要確認）
- `整備データ/merge/merge_TV.gpkg`（植生・土地利用）

> DH / TV のどちらを標高・植生率に使うかは、`gpkgの確認結果.md` と `DGNファイル内容確定結果.md` を踏まえて最終確定する。  
> 現時点では完全確定ではなく、実装と並行して調整中である。  
> `merge_TH.gpkg`（水系）はデータの棚卸しとして掲げるにとどめる。水域関連のパラメータは採用しておらず、算出対象ではない（1.1節）。

## 5.3 任意入力（衛星指標・LSTラスタ）

任意で次のGeoTIFFを指定可能とする。

**衛星指標**（`--satellite-file`）

- NDVI
- NDBI
- NDWI

入力が存在する指標のみ列を出力し、存在しない指標は処理を継続する。

**LST**（`--lst-file`）

- LST（地表面温度、°C）

LSTは目的変数であり、`idx_*`（説明変数）とは別のテーブル系統として出力する（6.2節・6.3節）。

**いずれも観測ファイル単位でテーブルを作るため `PARAM_SETS` に固定列挙できない。** `--satellite-file` / `--lst-file` で単一の観測ファイルを指定し、テーブル名はファイル名の観測日時から導く。

- 衛星指標: ファイル名が `INDICES_{センサ}_{YYYYMMDD}_{HHMMSS}Z.tif` に合致する場合、`idx_{YYYYMMDD}_{HHMMSS}` とする（例: `INDICES_Landsat8_20230707_032329Z.tif` → `idx_20230707_032329`）
- LST: ファイル名が `LST_{センサ}_{YYYYMMDD}_{HHMMSS}Z.tif` に合致する場合、`lst_{YYYYMMDD}_{HHMMSS}` とする（例: `LST_Landsat8_20230707_032329Z.tif` → `lst_20230707_032329`）
- **いずれも合致しない場合は日本語の `ValueError` で停止する。** ファイル名から観測を特定できないまま出力すると、どの観測のテーブルか後から判別できなくなるためである
- LSTラスタは**バンド1固定**とする。バンド数が1でない場合、またはバンド説明が設定されていて `LST` と一致しない場合（大文字小文字は無視）は日本語の `ValueError` で停止する（未設定は許容する）。指標側が `io.find_satellite_rasters()` でバンド説明を検証しているのに対し、LST側だけ無検証にしないためである

---

## 6. 出力仕様

### 6.0 出力構成の全体像

```text
[算出フェーズ] パラメータセット単位
  data/output/params/{city}/{scale}m/{テーブル名}.gpkg
    例: data/output/params/hanoi/30m/build_gba.gpkg
        data/output/params/hanoi/30m/road_osm.gpkg
        data/output/params/hanoi/30m/idx_20230707_032329.gpkg
        data/output/params/hanoi/30m/lst_20230707_032329.gpkg

[結合フェーズ] 分析用データセット
  data/output/datasets/dataset_{name}_{city}_{scale}m.gpkg
    例: data/output/datasets/dataset_limited_hanoi_30m.gpkg
```

**パラメータごとに別ファイルとする。** 再計算が独立し、並列実行で書き込みが競合せず、QGIS で個別に開けるためである。

**スケールは列名のサフィックスではなくディレクトリ階層で表現する。** ファイル自体がスケール別に分かれるため冗長であり、結合時に列名がスケールへ依存すると扱いにくい。旧実装の `_<scale>` サフィックス（`BUILD_COV_30` 等）は廃止した。

### 6.1 パラメータテーブル（算出フェーズの出力）

| 項目 | 内容 |
|---|---|
| 形式 | **ジオメトリを持たない属性のみの GeoPackage** |
| レイヤ名 | テーブル名（＝パラメータセット名）と同一 |
| 行集合 | 正準グリッドGeoPackageの該当レイヤが持つ `cell_id` の集合（実測: `grid_30m` 3,739,454 件 / `grid_90m` 417,694 件 / `grid_300m` 38,235 件） |
| 列 | `cell_id`（int64・キー）＋ 当該パラメータの列のみ |

**テーブルは `lon` / `lat` を持たない。** 座標は正準グリッドのレイヤが保持しており、全テーブルに複製するとパラメータ単位で独立させる狙いに反するためである。

**行集合を有効域と同一視してはならない。** 正準グリッドのセル集合は「セルとマスクポリゴンの交差」で選ばれるのに対し、`IN_ANALYSIS_AREA` は「fineピクセル中心がポリゴン内に入るか」で判定する。両者は「交差 ⊇ `IN_ANALYSIS_AREA`」の包含関係にあり、テーブルには解析対象域外のセルも含まれる（実測: 300mで 38,235 セル中 35 セルが `IN_ANALYSIS_AREA = 0`）。有効域の判定には `mask_roi` テーブルの `IN_ANALYSIS_AREA` を使う。

**欠測は GeoPackage の NULL として保持される。** CSV で空文字になり型が揺れる問題は解消した。

### 6.2 条件付きテーブル（衛星由来・LST由来、設計確定済み）

- `idx_{YYYYMMDD}_{HHMMSS}.gpkg`: `NDVI` / `NDBI` / `NDWI`（`--satellite-file` で入力がある指標のみ）
- `lst_{YYYYMMDD}_{HHMMSS}.gpkg`: `LST`（セル平均・°C）/ `LST_VALID_RATIO`（セル内有効画素率、0-1）（`--lst-file` 指定時のみ）

観測日別にテーブルを分けるため、複数観測を同型で並置できる。LSTは目的変数であり、6.3節の品質管理列の判定材料には含めない。

### 6.3 品質管理列（結合フェーズで導出）

品質管理列は**パラメータテーブルには持たせず、結合したパラメータ列から導出する**。

- `IN_ANALYSIS_AREA`（解析範囲レイヤ内のセルか）: **独立したテーブル `mask_roi`** として出力する。全テーブルに複製するとパラメータ単位で独立させる狙いに反するため
- `VALID_GIS_MASK`（少なくとも1つのGIS指標が有効なセル）
  - **判定材料に標高由来の列（`ELEV_MEAN` / `ELEV_VALID_RATIO`）は含めない。** 判定は「値が0より大きいセルを有効」とみなすが、これは被覆率・密度のような「地物の量」を前提とした基準である。標高は連続量であり `0` は「データが無い」ではなく海抜0mを意味するため、この基準の適用自体が不適切である。有効画素率も「DEMが覆っているか」を表す指標であり、建物・道路データの有無とは別の軸である。加えて標高を含めるとROI内のほぼ全セルが有効となり、本列が「建物・道路データが存在するか」という本来の意味を失う
  - 解析対象域フラグ（`IN_ANALYSIS_AREA`）も判定材料に含めない。有効域の定義であって地物の量ではないため
- `VALID_SATELLITE_MASK`（少なくとも1つの衛星指標がNaNでないセル）。**LST（`lst_*`）は判定材料に含めない。** LSTは目的変数であり、説明変数（衛星指標）の品質管理列に混ぜると目的変数と説明変数の有効性が区別できなくなるためである
- `MISSING_REASON`（GIS指標の主要欠損理由。`none` / `no_gis_feature` / `missing_gis_data`）

#### `MISSING_REASON` は NULL と 0 を区別する

| 値 | 意味 | 判定 |
|---|---|---|
| `none` | 有効なGIS指標がある | いずれかの判定材料が0より大きい |
| `no_gis_feature` | データを見たうえで地物が無かった（**観測結果**） | 判定材料に1つでも値があり、いずれも0以下 |
| `missing_gis_data` | そのセルの値がそもそも得られていない（**データ側の欠落**） | 判定材料が**すべて** NULL |

**分ける理由**: 結合フェーズでは左結合を使うため、テーブルに存在しない `cell_id` の列が NULL になる。両者を同じ値にまとめると、結合したテーブルの世代違いや算出範囲の不足が「地物が無い地域」に化けて分析へ流れ込む。前者は0として扱ってよいが、後者はテーブルを算出し直すべき状態であり、対処が異なる。

**判定は結合した全 GIS 列をまたいで行うため、複数テーブルを結合した場合の検知範囲は限られる。** `missing_gis_data` になるのは判定材料が**すべて** NULL のセルだけである。したがって `road_osm` が最新で `build_gba` だけが古い、といった**テーブル単位の世代違いは捕まらない**（建物4列が NULL でも `ROAD_DEN` に値があれば `no_gis_feature` になる）。この列が確実に捕まえるのは「結合した GIS テーブルのすべてがそのセルを持たない」場合に限る。

なお `missing_gis_data` は結果側の表示であって原因を示さない。**テーブル単位の世代違いの切り分けには、結合時に出力される突合件数を使う**（`build_dataset.report_match_counts()` は、テーブル側の一致件数と**土台側で値が付く件数**の両方をテーブルごとに報告し、後者が土台の行数に満たない場合に警告する。部分的に stale なテーブルは一致0件にならないため、0件だけを検知していると見逃す）。

**`DATA_SOURCE` / `SCENARIO` は廃止した。** テーブル名（`build_gba` 等）と結合対象の選択が同じ情報を持つためである。

#### データセットのスキーマは結合対象によって変わる

**判定材料となる列が1つも無い場合、対応する品質管理列は付与しない。** 全セル0の列を出すと「データを確認したうえで無効と判定した」ように読めてしまうためである。

| 結合対象 | 付与される品質管理列 |
|---|---|
| 建物・道路を含む | `VALID_GIS_MASK` / `MISSING_REASON` |
| 衛星指標を含む | `VALID_SATELLITE_MASK` |
| `mask_roi` のみ・標高のみ | いずれも付与されない |

旧 wide CSV は常に全列を持っていたため、**列の存在を前提にした下流のコードは修正が必要である。**

### 6.4 GIS由来パラメータ

#### 確定済みパラメータ

- **`ROAD_DEN`（道路密度, m/ha）**: 設計確定・実装済
  - **入力**: `data/gis/roads/hanoi_osm_roads.gpkg`（OSM Geofabrik 由来）
  - **フィルタリング**: ホワイトリスト方式。motorway〜living_street + service を含め、非車道（footway, steps, path 等）・track・construction・proposed・特殊用途を除外。z_order < 0（トンネル・地下道）も除外
  - **算出方法**: `compute_line_length()` でセル内ライン総延長（m/cell）を算出し、`cell_area_ha()` で面積正規化
  - **詳細**: [gis_data_roads.md](../01_planning/gis_data/gis_data_roads.md) セクション 2

- **建物パラメータ4種**: 設計確定・実装済
  - **入力**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas 由来）
  - `BUILD_COV`（建物被覆率, 0-1）: fine グリッドへラスタ化し coarse セルへ平均集約
  - `BUILD_DEN`（建物棟数密度, 棟/ha）: 重心が属するセルごとの棟数を `cell_area_ha()` で正規化
  - `BUILD_H_MEAN` / `BUILD_H_MAX`（建物高さ, m）: 重心が属するセルごとの有効高さの平均・最大
  - **高さの除外条件**: 推定分散または高さ自体が負・欠測の建物を高さ集計から除外（被覆率・棟数密度からは除外しない）
  - **欠測規約**: セル内に有効高さの建物が無い場合、高さは 0.0 ではなく **NaN**
  - **解釈上の注意**: `BUILD_COV = 0` は建物の不存在を意味しない（30m では建物のあるセルの14%が該当）。建物の有無は `BUILD_DEN` で判定する
  - **詳細**: [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) セクション 3

- **`ELEV_MEAN`（平均標高, m）**: 設計確定・実装済（パラメータセット `elev_fabdem`）
  - **入力**: `data/gis/dem/fabdem/fabdem_hanoi_dem.tif`（FABDEM v1.2、EPSG:4326、nodata `-9999`）
  - **算出方法**: 衛星指標と共通の `aggregate_raster_to_grid()` により coarse グリッドへ `Resampling.average` で再投影し、セル平均標高を得る
  - **欠測規約**: 有効カバレッジ外は **NaN**。`0` は「データが無い」ではなく**海抜0m の実測値**であり、両者を同一視しない。無効画素の判定は `ELEV_VALID_RATIO` と揃えており、nodata タグの値に加えて**実値の NaN も欠損**として扱う
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は6.3節）
  - **セルの信頼度**: 平均はセル内の**有効画素のみ**で取るため、値の有無だけでは部分被覆セルを判別できない。判別には `ELEV_VALID_RATIO` を用いる
  - **解釈上の注意**:
    - FABDEM は Copernicus GLO-30 をランダムフォレスト回帰で補正した準DTMであり、生のDSMではない。ただし高密度キャノピー・急峻地形では補正残差が残る
    - 垂直基準面は EGM2008 であり、0m は平均海面と厳密には一致しない
    - ライセンスは CC BY-NC-SA 4.0（非商用）。論文・資料への帰属文記載が必須
    - **`scale=30` では集約が実質的なリサンプリングになる**（FABDEM の画素はハノイの緯度で東西約28m・南北約30m）。「セル内の面積平均標高」とは言えないため、RQ2 のスケール間比較で30mの値を過大解釈しない
  - **詳細**: [gis_data_dem.md](../01_planning/gis_data/gis_data_dem.md)

- **`ELEV_VALID_RATIO`（DEM有効画素率, 0-1）**: 設計確定・実装済（パラメータセット `elev_fabdem`）
  - **入力**: `ELEV_MEAN` と同一のDEMラスタ
  - **算出方法**: 有効画素を1・nodataを0とした配列を、`ELEV_MEAN` と同じ `Resampling.average` で coarse グリッドへ再投影する
  - **必要性**: `Resampling.average` はセル内の**有効画素のみ**で平均を取るため、セルの1割しかDEMに覆われていなくても、完全に覆われたセルと同じ実数が `ELEV_MEAN` に入る。`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する（実測では `IN_ANALYSIS_AREA == 1` のうち、300mスケールで `NaN` は0.013%である一方、有効画素率99%未満は4.67%・50%未満は2.42%）
  - **欠測規約**: ラスタ範囲外のセルは `NaN` ではなく **`0.0`**（nodataで覆われたセルと同じ「有効画素なし」を意味するため揃える）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は6.3節）
  - **解釈上の注意**: 入力ラスタの外周より外側（画素が1つも無い領域）が占める分は比率に反映されないため、ラスタの矩形範囲を一部しか含まないセルでは実際の被覆より高い値になり得る。現行の入力（ROIでcrop済みのDEM）では解析BBox最外周のセルに限られる
  - **`ELEV_COUNT`（セル内の有効点数）は出力しない**（スケールによって画素数の意味が変わり、比率のほうがスケール間で比較可能なため）

> `full` シナリオの標高は設計未確定である（現状は出力しない）。測量GISの `merge_DH.gpkg`（点・等高線）による標高、または FABDEM の暫定適用のいずれを採るかは別途判断する。

#### 採用済み・設計未確定のパラメータ（別途設計確定）

以下は**採用済みだが**入力データ・算出方法が未確定であり、パラメータ単位で設計確定後に出力仕様へ追加する。列名は暫定であり、確定時に見直す。

- `GREEN_COV`（植生被覆率, 0-1）: 入力源未確定。stubモジュールも未作成
- 土地被覆クラス別面積率: クラス体系・出力するクラスの粒度がいずれも未確定。列名も未定
- 人口密度・夜間光強度: 候補データセットが複数あり入力が未確定。いずれも連続量ラスタのため、標高と同じラスタ集約経路（7.2節 Step B）を用いる見込み

> **採用していないパラメータは本節に列挙しない。** 採否の一覧と保留の見直し時期は [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) を正本とする（1.1節）。

> スケール間（30/90/300m）で値の意味を揃えるため、密度系パラメータは面積あたり（/ha）に正規化する。算出には `grid.cell_area_ha()` を使用する。

### 6.5 出力列と算出モジュールの対応

ソースコードを読まずに「どの列がどのモジュール・関数で算出されるか／設計確定状況」を確認できるよう、対応関係を以下に示す。

| 列名 | 出力先 | 算出モジュール・関数 | 設計確定状況 |
|---|---|---|---|
| `cell_id` | 全テーブル | `canonical_grid.make_cell_id()`（`tables.build_param_table()` が付与） | 確定・実装済 |
| `lon`, `lat` | 正準グリッド／データセット | `canonical_grid._build_cell_frame()`（結合時に `build_dataset.py` が引き継ぐ） | 確定・実装済 |
| `NDVI`, `NDBI`, `NDWI` | `idx_*` テーブル | `params/raster.py: compute()` → `aggregate_raster_to_grid()` | 確定・実装済（`--satellite-file` 指定時のみ） |
| `LST`, `LST_VALID_RATIO` | `lst_*` テーブル | `params/lst.py: compute()` → `params/raster.py: aggregate_raster_to_grid()` / `aggregate_valid_ratio_to_grid()` | 確定・実装済（`--lst-file` 指定時のみ） |
| `IN_ANALYSIS_AREA` | `mask_roi` テーブル | `params/mask.py: compute()` → `geometry.compute_polygon_coverage()` | 確定・実装済 |
| `VALID_GIS_MASK`, `MISSING_REASON` | データセット | `build_dataset.add_quality_columns()` | 確定・実装済（判定材料の列がある場合のみ付与。6.3節） |
| `VALID_SATELLITE_MASK` | データセット | `build_dataset.add_quality_columns()` | 確定・実装済（同上） |
| `BUILD_COV`, `BUILD_DEN`, `BUILD_H_MEAN`, `BUILD_H_MAX` | `build_gba` / `build_dc` テーブル | `params/buildings.py: compute()` | 確定・実装済 |
| `ROAD_DEN` | `road_osm` / `road_gt` テーブル | `params/roads.py: compute()` → `geometry.compute_line_length()` / `grid.cell_area_ha()` | **確定・実装済** |
| `ELEV_MEAN` | `elev_fabdem` テーブル | `params/elevation.py: compute()` → `params/raster.py: aggregate_raster_to_grid()` | **確定・実装済** |
| `ELEV_VALID_RATIO` | `elev_fabdem` テーブル | `params/elevation.py: compute()` → `params/raster.py: aggregate_valid_ratio_to_grid()` | **確定・実装済**（`ELEV_COUNT` は出力しない） |
| `GREEN_COV` | （未割当） | （未割当） | **採用済み・設計未確定**。stubモジュールも未作成。入力源の確定が必要 |
| 土地被覆クラス別面積率・人口密度・夜間光強度（列名未定） | （未割当） | （未割当） | **採用済み・設計未確定**。入力データセットの選定と算出方法の確定が必要 |

**`DATA_SOURCE` / `SCENARIO` は廃止した**（6.3節）。

### 6.6 分析用データセット（結合フェーズの出力）

`src/analysis/build_dataset.py` が、指定したテーブル群を `cell_id` で結合する。

| 項目 | 内容 |
|---|---|
| 出力先 | `data/output/datasets/dataset_{name}_{city}_{scale}m.gpkg` |
| レイヤ名 | データセット名（`{name}`）と同一 |
| 土台 | 正準グリッドのレイヤ（`cell_id` / `lon` / `lat`） |
| 列 | `cell_id` / `lon` / `lat` ＋ 各テーブルの列 ＋ 品質管理列（6.3節） |

結合対象の指定方法は2通りある。

- `--scenario`: `config.py` の `SCENARIO_TABLES`（シナリオ → 結合するテーブル名の一覧）を展開する
- `--tables`: テーブル名を直接指定する（別ソース版の比較・衛星指標の追加など）

| シナリオ | 結合するテーブル | `--scenario` での指定 |
|---|---|---|
| `satellite_only` | `mask_roi` | `--tables` に `idx_*` を伴う場合のみ可（下記） |
| `limited` | `mask_roi` / `build_gba` / `road_osm` / `elev_fabdem` | 可 |
| `full` | `mask_roi` / `build_dc` / `road_gt` | 可 |

衛星指標・LSTは観測ファイル単位のため `SCENARIO_TABLES` には列挙できない。結合時に観測日時つきのテーブル名（例: `idx_20230707_032329` / `lst_20230707_032329`）を `--tables` で明示する。

**`--scenario` と `--tables` は併用できる。** シナリオ展開分（先）と直接指定分（後）を連結し、重複は除く（`build_dataset.resolve_table_names()`）。併用時は `--name` を必須とする（既定名としてシナリオ名を推測しないため）。観測ファイル単位のテーブルは `SCENARIO_TABLES` に列挙できないため、シナリオ展開＋観測テーブルの追加が RQ1・RQ2 でも定型になる。

**`--scenario satellite_only` は単独では拒否する。** 衛星指標を列挙できない以上、シナリオ名だけで展開すると `mask_roi` だけの4列（`cell_id` / `lon` / `lat` / `IN_ANALYSIS_AREA`）のデータセットが `dataset_satellite_only_*.gpkg` という名前で出力される。**名前が中身を偽る**ため、`--tables` に `idx_*` を伴う場合のみ許可する。**`lst_*` の有無は解禁条件にしない。** `Satellite Only` は「衛星由来指標のみを用いる分析シナリオ」（CLAUDE.md 用語集）であり、説明変数が `idx_*` だからである。`mask_roi` + `lst_*` だけを許すと、目的変数しか持たないデータセットが `satellite_only` を名乗ることになる。

```bash
python -m src.analysis.build_dataset --city hanoi --scale 30 \
    --scenario satellite_only --tables idx_20230707_032329 lst_20230707_032329 \
    --name satellite_only_20230707_032329
```

`SCENARIO_TABLES` にエントリを残しているのは、「衛星指標以外に何を結合するか」を記録するためである。

**結合は左結合とする。** 正準グリッドのセルを1行も落とさないためであり、あるテーブルにのみ存在しない `cell_id` の値は NULL として残る。

**単一スケールのテーブルのみを結合する。** `cell_id` は全スケール共通の式（`row * 1000000 + col`）で採番するため、**一意なのは同一スケールのレイヤ内に限られる**（7.5.3節）。`--scale` は単一指定に限り、テーブルも同じスケールのディレクトリからのみ読む。

**静かに壊れる経路を4つ塞いでいる。**

- **列名の衝突**（`build_gba` と `build_dc` の同時結合など）は、所有テーブル名つきの `ValueError` で拒否する。接尾辞を付けて黙って両方残すと、どちらがどのソースか分からなくなる
- **`cell_id` の重複**があるテーブルは、読み込みの時点で弾く。結合で行が増え、値の誤りではなく行数の誤りとして現れる
- **土台と `cell_id` が一致した件数**をテーブルごとに報告し、0件なら警告する。古い解析範囲で算出した stale なテーブルを結合しても例外にはならず、該当列が広範囲に NULL になるだけである
- **観測日時の混在**（`idx_20230707_032329` と `lst_20241130_032336` の同時結合など）は、テーブルを読み込む前に `ValueError` で拒否する（`validate_observation_consistency()`）。LSTと衛星指標が別観測から来ていると目的変数と説明変数の関係を見るという前提が崩れるが、**結合自体は `cell_id` で成立し、行数も欠損も正常に見えるため出力からは判別できない**。テーブル名が観測日時を保持しているうちに入口で止める。同種どうし（`idx_*` が2つなど）も同様に拒否する

### 6.7 新旧の差異と比較可能性（Satellite Only）

旧経路（`build_satellite_only_dataset.py`。移行に伴い削除済み）と本節冒頭の新経路（`urban_params` + `build_dataset`）は、以下の3点で仕様が異なる。**単なる集計単位の違いではないため、3点まとめて記載する。**

| 観点 | 旧経路（削除済み） | 新経路 |
|---|---|---|
| 集計単位 | ピクセル単位（1行1ピクセル、`gdal_translate` によるXYZ出力） | セル単位（`cell_id` キーの `LST` / `LST_VALID_RATIO` セル平均） |
| 行の絞り込み方 | LST・NDVI・NDBI・NDWI がすべて揃う complete case のみ | 全セル保持＋品質管理列（`LST_VALID_RATIO` / `VALID_SATELLITE_MASK`）で判断させる（6.3節） |
| 物理範囲フィルタ | LST 15〜65°C・指標 ±1.1 の範囲外を除外 | 適用しない。フィルタは下流の分析スクリプトが担う責務とする（結合フェーズが行を落とすと `MISSING_REASON` の意味が崩れるため） |

**この3点の違いにより、既存の [satellite_only_analysis_results.md](../03_results/satellite_only_analysis_results.md)（旧経路によるRQ3のベースライン結果）と、新経路で出力したデータセットは統計的に別物であり、直接比較しない。** 格子が一致せずセル単位の対応づけができないため、突合できるとしても分布統計に限られ、投じる作業量に対して得られる根拠が弱いと判断した。既存結果はピクセル単位の先行結果として保持し、新経路での RQ3 再実行は別Issueで扱う。

---

## 7. 処理設計（モジュール構成・関数責務）

`src/analysis/urban_params/` パッケージは責務ごとにモジュールを分割している。

```text
src/analysis/
  urban_params/
    __init__.py
    __main__.py       # python -m src.analysis.urban_params のエントリーポイント
    config.py         # CITY_CONFIG（layers/rasters）, PARAM_SETS, SCENARIO_TABLES, 出力パス解決
    grid.py           # GridSpec, build_grid, grid_centers_wgs84, cell_area_ha
    canonical_grid.py # 全シナリオ共通の正準グリッド（cell_id 採番・GeoPackage 出力。7.5節）
    tables.py         # 正準グリッド整合の GridSpec 構築・cell_id 付きテーブル化・書き出し（7.6節）
    geometry.py       # ジオメトリ投影・ラスタ化・被覆率/密度算出の共通処理
    io.py             # LayerResource / RasterResource, レイヤ・ラスタの解決と読み込み・キャッシュ（7.7節）
    params/
      raster.py       # ラスタのグリッド集約（衛星指標 NDVI/NDBI/NDWI・有効画素率）
      lst.py          # LSTパラメータ（LST/LST_VALID_RATIO）
      buildings.py    # 建物パラメータ（BUILD_COV/BUILD_DEN/BUILD_H_MEAN/BUILD_H_MAX）
      roads.py        # 道路パラメータ（ROAD_DEN）
      elevation.py    # 標高パラメータ（ELEV_MEAN/ELEV_VALID_RATIO）
      mask.py         # 解析対象域フラグ（IN_ANALYSIS_AREA）
    run.py            # main(): パラメータセット単位・マルチスケール出力のオーケストレーション
    verify_values.py  # 旧 wide CSV との値照合（検証専用。11.2節）
  build_dataset.py    # cell_id 結合による分析用データセット生成（6.6節）
```

「どのパラメータを、どの入力ソースで算出するか」は `PARAM_SETS` が保持する（5.2.0節）。シナリオは算出側では扱わず、`SCENARIO_TABLES` として結合側が持つ（6.6節）。

各 `params/*.py` は共通の `compute()` シグネチャを持つ（`raster.py` のみ別シグネチャ）。**再設計にあたって `compute()` はシグネチャ・ロジックとも変更していない。**

```python
def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """列名 -> coarse_shape の2次元配列、を返す。"""
```

`elevation.py` のみ第1引数が `RasterResource | None` であり、集約範囲は `grid_spec` が保持するため `bbox_analysis` は参照しない（他モジュールとシグネチャを揃えるために受け取る）。`raster.py` は `bbox_analysis` を取らずラスタ辞書を受け取る別シグネチャであり、`run.py` の `ParamTask` が呼び出し形を揃える。

`resource` が `None`（入力未指定）または未実装の場合は空dict `{}` を返す。

### 7.1 Step A: 解析範囲・グリッド準備

- 解析範囲レイヤ（ROI。`ANALYSIS_EXTENT_LAYER_KEY`）のBBoxを取得する。**正準グリッドと同じレイヤを使う必要がある**ため、`canonical_grid.py` の `--mask-layer-key` 既定値も同じ定数を参照する
- ROI は必要時のみ解析用投影座標（既定: EPSG:5897）へ投影する
- `--scales` で指定した各スケールについて、**正準グリッドのセル境界に載る整合BBox**（7.6節）から coarseグリッド（既定10m補助グリッド付き）を作成する
- 対象スケールのグリッドレイヤが存在するかを、**算出へ入る前にまとめて確認する**。スケールごとの処理に入ってから気づくと、先行するスケールの出力だけが残るため

### 7.2 Step B: GIS由来指標（一部は設計未確定、6.4節参照）

> 建物・道路・標高（`Limited`）は6.4節の通り**設計確定・実装済み**である。以下「設計未確定」に挙げるパラメータの列名・入力源は案であり、各パラメータを別途個別に確定する。  
> 本節は**採用済みのパラメータのみ**を扱う（1.1節）。

**設計確定・実装済み**

- 建物（GBA / DC）
  - `BUILD_COV`: ポリゴン被覆率（fine→coarse平均、0-1）
  - `BUILD_DEN`: 棟数密度（棟/ha）
  - `BUILD_H_MEAN` / `BUILD_H_MAX`: セル内建物の平均・最大高さ（m）
- 道路（OSM / GT）
  - `ROAD_DEN`: 道路密度（m/ha）
- 標高（FABDEM、パラメータセット `elev_fabdem`）
  - `ELEV_MEAN`: DEMラスタを coarse グリッドへ平均再投影して得るセル平均標高（m）
  - `ELEV_VALID_RATIO`: セル内のDEM有効画素率（0-1）。`ELEV_MEAN` の平均が有効画素のみで取られるため、部分被覆セルの判別に必要（6.4節）
  - ベクタではなくラスタ入力のため、Step C（衛星指標）と同じ集約関数を用いる
  - 有効カバレッジ外は NaN（有効画素率は 0.0）。いずれも `VALID_GIS_MASK` の判定材料には含めない（6.3節）

**設計未確定**（採用済み）

- 植生（土地被覆分類ラスタの植生クラス / 測量GIS の TV）
  - `GREEN_COV`: 植生被覆率
  - 採否の正本は本パラメータを「**土地被覆分類の植生クラスに由来する面積比**」と定義している。土地利用タグ（OSM `landuse=*` 等）を入力に用いる場合は、**どのタグを植生クラスとみなすかの分類規則を定めてから**候補に加える。規則を定めずに用いると、正本の定義とは別概念の列を出力することになる
- 土地被覆クラス別面積率（土地被覆ラスタ）
  - **カテゴリカルラスタ**のため、連続量を対象とする `Resampling.average` は使えない。クラスごとの画素割合を集約する処理を別途設計する
- 夜間光強度（ラスタ）
  - 放射輝度は面積に比例しない**強度量**であるため、標高と同じくラスタ集約経路（Step C と共通の集約関数）でセル平均を取る
- 人口密度（ラスタ）
  - **平均集約は使えない。** 候補データセットの配布値は「密度」ではなく**セルあたりの人口カウント**であり、カウントは合計保存量のため、平均や最近傍で再投影すると総人口が保存されないためである（[gis_data_population.md](../01_planning/gis_data/gis_data_population.md) 6.2節）
  - 集約先セル内のカウントを**合計**したうえで `grid.cell_area_ha()` で面積正規化する経路を別途設計する。標高・衛星指標とは集約関数を共有できない
- 入力ラスタの解像度と解析スケールの関係は**データセットによって異なる**（30m より粗く 300m より細かいものと、すべてのスケールより粗いものが候補に混在する）。細スケールで実質的な内挿になるかは入力の選定後に確定する。各候補の解像度は [available_gis_data.md](../01_planning/available_gis_data.md) のカテゴリ別ドキュメントを参照
- 測量GIS由来の標高（DH）
  - `full` シナリオ向けに、点属性から数値標高を抽出しセル平均を算出する案を第一候補とする

> 測量由来GISのレイヤ意味は最終的に固定し切れていない部分があるため、  
> 特に `GREEN_COV` および `full` シナリオの `ELEV_MEAN` の入力源は今後の確認で更新され得る。  
> `limited` シナリオの建物データソースは GlobalBuildingAtlas（`hanoi_gba_buildings.gpkg`）、標高は FABDEM v1.2 を使用する。

**共通基盤関数の算出手法と制約**:

| 関数 | 手法 | 制約・注意点 |
|---|---|---|
| `compute_polygon_coverage` | fineマスク（`rasterize` + `all_touched=False`）→ coarse平均 | ピクセル中心判定のため、fine解像度（10m）未満の細いポリゴンは被覆率0になり得る。`params/*.py` の本実装時に `all_touched=True` の検討が必要 |
| `compute_line_length` | 各ラインとcoarseセルポリゴンの `intersection.length` 合計 | 幾何学的に正確。半開セル矩形で境界二重計上を防止 |
| `count_polygon_centroids` | ポリゴン重心をcoarseセルへ割り当て | 重心が範囲外のポリゴンはカウントしない |

### 7.3 Step C: 衛星由来指標（任意）

- 各ラスタを投影座標系（`analysis_epsg`）のcoarseグリッドに再投影
- `Resampling.average` でセル平均を取得
- 有効値のみ出力列に追加

### 7.4 Step D: テーブル化・出力

- coarse配列の添字を `cell_id` へ変換し、正準グリッドの `cell_id` で行を絞り込む（7.6節）
- 属性のみの GeoPackage へ書き出す。**追記モードは持たず、常に一時ファイルへ書いてから置き換える**
- 処理サマリ（行数、統計量、入力レイヤの実読み込み回数）を標準出力

品質管理列の付与は算出フェーズでは行わない。結合フェーズ（6.3節・6.6節）が担う。

### 7.5 正準グリッド（`canonical_grid.py`）

**本節は Step A–D の処理フローとは独立している。** `canonical_grid.py` は `run.py` から呼ばれず、独自の CLI を持つ単独の生成処理である。パラメータ値を `cell_id` キーの独立したテーブルとして持つ構成の、結合の土台を定義する。

#### 7.5.1 既存 `grid.py` との関係

`grid.py` の `build_grid()` はグリッド原点を解析範囲レイヤの BBox（`minx` / `maxy`）から取る。この BBox はシナリオごとに異なる基準レイヤ（`limited` は ROI、`full` は RG）に由来するため、**シナリオが変わるとセルが揃わず比較できない**。

正準グリッドは原点を解析範囲から独立させてこれを解消する。`grid.py` は `build_grid()` の実装として引き続き使われるが、**渡す BBox を正準グリッドのセル境界に載る「整合BBox」へ差し替える**ことで、両者の格子を一致させている（7.6節）。

**解析範囲レイヤの BBox をそのまま渡した場合、両者のセルは対応しない。** 原点が異なるため格子の位相がずれる（ハノイROI・30m の実測で dx=29.97m / dy=23.23m）。旧 wide CSV はこの旧原点で生成されているため、**旧出力と再設計後の出力をセル単位で照合することはできない**（照合方法は11.2節）。

#### 7.5.2 原点とインデックス

- 座標系は実装の `analysis_epsg` に従い **EPSG:5897**（本節の記述はこのCRSを前提とする）
- 原点は座標系原点 `(0.0, 0.0)` を **900m の倍数へ切り下げ**た点。900 は 10 / 30 / 90 / 300m の最小公倍数であり、補助 fine グリッド（10m）を含む全スケールの格子が原点で揃う
- 解析範囲レイヤの BBox は、出力するセルの `row` / `col` 範囲を決めるためだけに使い、**原点の決定には使わない**
- `col = floor((x - origin_x) / res)` / `row = floor((y - origin_y) / res)`（原点からの絶対インデックス）

`row` は**北向きを正**とする。ラスタの慣習（`rasterio.transform.from_origin()` が作る、北から南へ増える row）とは向きが逆である。原点固定・非負インデックス・スケール間の整数除算（`row_90 = row_30 // 3`）をいずれも素直に成立させるための選択である。

#### 7.5.3 `cell_id` の採番

```text
cell_id = row * 1000000 + col
```

原点が解析範囲に依存しないため、**後から解析範囲を広げても既存セルの `cell_id` は変わらない**。

式を全スケール共通としているため、**`cell_id` が一意なのは同一スケールのレイヤ内に限られる**。30m の `(row=7582, col=1765)` と 300m の `(row=7582, col=1765)` は同じ `cell_id` になる。**複数スケールのパラメータテーブルを結合する際は、`cell_id` 単独ではなくスケールとの複合キーを使う。**

`col` は 1,000,000 未満、`row` は `cell_id` が int64 に収まる範囲である必要がある。範囲外の組合せはグリッド仕様の構築時点で日本語の `ValueError` になる。ハノイ ROI（EPSG:5897）の実測値は 30m で `col` 17,655–20,205・`row` 75,825–78,864 であり、上限に対して十分な余裕がある。

#### 7.5.4 親セルの対応づけ

30m レイヤのみ `parent_id_90` / `parent_id_300` を持つ。原点が全スケールで共通であるため、`parent_id_90 = (row_30 // 3) * 1000000 + (col_30 // 3)` は 90m レイヤの `cell_id` と厳密に一致する（300m も同様に `// 10`）。

親子関係は **30m 基準に限定**する。90 ÷ 30 = 3、300 ÷ 30 = 10 はいずれも整数だが、**300 ÷ 90 は整数にならず入れ子にならない**ため、90m ↔ 300m の直接の包含関係は持たせない。

ROI でクリップする場合、「30m セルが ROI と交差するならその親セルも必ず ROI と交差する」ため、`parent_id` の参照先は必ず親レイヤに存在する。逆（親セルの子 9 個・100 個がすべて残る）は境界で成立しない。

#### 7.5.5 出力

| 項目 | 内容 |
|---|---|
| 出力先 | `data/output/grid/grid_{city}.gpkg` |
| レイヤ | `grid_30m` / `grid_90m` / `grid_300m` |
| ジオメトリ | セル矩形（EPSG:5897） |

| 属性 | dtype | 内容 |
|---|---|---|
| `cell_id` | int64 | `row * 1000000 + col` |
| `row`, `col` | int32 | 原点からの絶対インデックス（デバッグ・検証用） |
| `lon`, `lat` | float64 | セル中心のWGS84座標 |
| `parent_id_90`, `parent_id_300` | int64 | 30mレイヤのみ |

出力形式に GeoPackage を採るのは、既存の `fiona` / `geopandas` / `gdal` でそのまま扱え、QGIS で確実に開いて目視検証できるためである。GeoParquet も候補として検討したが、conda 環境に Parquet ドライバ・`pyarrow` が無く依存追加が必要で、共同研究者・指導教員の環境で開ける保証もないため見送った。速度がボトルネックになった時点で再検討する。

生成物は `.gitignore` の `*.gpkg` により Git 追跡外である。

#### 7.5.6 出力範囲とマスク判定

`--extent mask`（既定）は解析範囲レイヤのジオメトリと交差するセルのみを、`--extent bbox` は BBox 全体を出力する。マスクレイヤの既定を `roi` としてよいのは、測量GISが ROI 内の一部である（3.1節）ため **ROI が全シナリオの解析範囲を包含する**からである。

判定は「セルとジオメトリの交差」を用いる。`params/mask.py` の `IN_ANALYSIS_AREA`（10m fine ピクセル中心がポリゴン内に入るかで判定）とは**一致せず、交差 ⊇ `IN_ANALYSIS_AREA` の包含関係**になる。角をわずかにかすめるセルは交差するが fine ピクセル中心が 1 つも入らないためである。正準グリッドは結合の土台として取りこぼさない安全側を採る（実測: 300mで 38,235 セル中 35 セルが `IN_ANALYSIS_AREA = 0`）。

##### マスクとして機能するのは面ジオメトリを持つレイヤに限る（既知の制約）

交差判定は線・点とも成立するため、**面ジオメトリを持たないレイヤをマスクに指定すると「範囲を面で切る」動作にならない**。既定の `roi` は単一ポリゴンのため該当しないが、測量GISのレイヤは以下の構成であり、指定しても意図した有効域は得られない。

| レイヤ | 件数 | 型の内訳 | 面積ゼロの割合 |
|---|---|---|---|
| `roi` | 1 | Polygon 1 | 0% |
| `rg` | 721 | LineString 512 / MultiLineString 82 / Polygon 68 / Point 59 | 90.6% |
| `cs` | 20,110 | LineString 11,201 / Point 8,407 / Polygon 502 | 97.5% |

RG は**境界線**であり（[survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)）、線と交差判定すると有効域の内部ではなく**境界線上のセルだけ**が選ばれる。実測でも RG の BBox 112,617 セル（30m）に対し選択は 9,835 セル（8.7%）と、面を塗った場合の値にならない。

これは正準グリッド固有の問題ではなく、**測量GISから分析対象域をどう定義するかが未決である**ことに由来する。`params/mask.py` の `compute_polygon_coverage()` も面積ベースであり同じ前提を共有する。定義が決まるまで、マスクには面ジオメトリを持つレイヤ（現状は `roi`）を使う。

**この未決が `full` シナリオの有効域定義に及ぶ。** 解析範囲を ROI へ一本化しているため、`full` に固有の有効域は現時点で定義されていない。旧実装は `rg` をマスクにしていたが、300m 出力が実データ2行しかなく既に破綻していた。

#### 7.5.7 CLI

```bash
python -m src.analysis.urban_params.canonical_grid --city hanoi --scales 30 90 300 --extent mask
```

主要引数:

- `--city`: 都市ID（既定: `hanoi`）
- `--scales`: 出力するスケール（m）。900 の約数である必要がある（既定: `30 90 300`）
- `--extent`: `mask`（既定） / `bbox`
- `--mask-layer-key`: 解析範囲の基準レイヤ（既定: `roi`）
- `--output`: 出力先。相対パスはプロジェクトルート基準
- `--block-rows`: 1ブロックあたりの**行数**（既定: 500）
- `--overwrite`: 既存の出力ファイルを削除して作り直す

30m は ROI 内でも約 374 万セルとなるため、ポリゴン生成はベクトル化し、マスク判定は空間索引を用い、行ブロック単位で生成・追記する。

**`--block-rows` は行数であり、セル数ではない。** 区切るのは行だけで列は常に全幅を展開するため、1ブロックのセル数は `block_rows × 列数` となり、メモリ使用量は解析範囲の**東西幅に比例**する。ハノイ ROI の 30m では列数が約 2,551 で、既定 500 だと 1 ブロックが約 128 万セルになる。東西に広い範囲や別都市へ移す場合は実測しながら調整する。

**追記モードのまま再実行すると `cell_id` の一意性が壊れる**ため、既存ファイルへの上書きは `--overwrite` の明示を必須とし、未指定時は `FileExistsError` で停止する。

失敗時に既存の正しい出力を失わないよう、2 段構えで守る。

1. **全スケールのグリッド仕様を、出力ファイルへ触れる前にまとめて構築する。** スケールごとに構築しながら書き出すと、不正なスケールが後ろにあった場合に手前のレイヤを書き終えてから失敗する
2. **書き出しは一時ファイルへ行い、全レイヤの完了後に置き換える。** 仕様構築の時点では検出できない失敗（マスクとの交差が 1 件も無い、書き込み中の I/O エラー、中断）があるため。`Path.replace()` は同一ディレクトリ（＝同一ファイルシステム）でアトミックに動作し、途中で失敗しても既存ファイルはそのまま残る

30m の再生成には数分・約 1.1GB を要するため、失敗時に既存出力を失う影響は小さくない。なお一時ファイルを併存させる間はディスク使用量が一時的に倍になる。

### 7.6 正準グリッドとの格子整合とテーブル化（`tables.py`）

#### 7.6.1 整合BBox

`build_grid()` は渡された BBox の `minx` / `maxy` をグリッド原点にする。したがって、**正準グリッドの `row` / `col` 範囲からセル境界にちょうど載る BBox を組み立てて渡せば、両者の格子が一致する**。

```text
minx = origin_x + col_min * res      maxx = origin_x + (col_max + 1) * res
miny = origin_y + row_min * res      maxy = origin_y + (row_max + 1) * res
```

整合BBoxの幅・高さは解像度の整数倍になるため `build_grid()` のパディングが 0 となり、`coarse_shape` が正準グリッドの `(n_rows, n_cols)` と厳密に一致する。ハノイROI・EPSG:5897 での実測は次のとおり。

| スケール | 正準 `(n_rows, n_cols)` | `coarse_shape` | `cell_id` 件数 |
|---|---|---|---|
| 30m | (3040, 2551) | 一致 | 3,739,454 |
| 90m | (1014, 851) | 一致 | 417,694 |
| 300m | (305, 256) | 一致 | 38,235 |

**`compute()` へ渡す解析BBoxも整合BBoxとする。** 整合BBoxは必ず ROI の BBox を包含するため、ROI 側を渡すと外周1セル分の帯にかかる道路を取りこぼす。建物は `grid_spec` 基準で範囲判定するため影響を受けないが、パラメータ間で範囲の意味が食い違わないよう統一する。

#### 7.6.2 添字と `cell_id` の対応

`coarse_transform` は北から南へ row が増えるのに対し、正準グリッドの `row` は北向きが正であるため反転する。

```text
canonical_row = row_max - i     （i: coarse配列の行添字）
canonical_col = col_min + j     （j: coarse配列の列添字）
cell_id = make_cell_id(canonical_row, canonical_col)
```

出力する行集合は**正準グリッド GeoPackage が持つ `cell_id` を正本**とし、マスク交差判定を再計算しない。判定ロジックが二重化すると、両者がずれたときに結合が静かに壊れるためである。行の順序もグリッドレイヤの格納順に従う。

#### 7.6.3 静かなずれを防ぐ実行時チェック

正準グリッドが別の解析範囲・別のマスクで再生成された場合、例外を出さずに対応のずれたテーブルを作ってしまう。次の3点を実行時に検証する。

- `coarse_shape` が正準グリッドの `(n_rows, n_cols)` と一致する
- 読み込んだ `cell_id` がすべて配列範囲内の `(row, col)` へ分解される
- `cell_id` に重複が無く、パラメータ列名がキー列 `cell_id` と衝突しない

#### 7.6.4 再実行時の上書き規約

**追記モードは持たない。** 追記で `cell_id` が二重化すると結合が静かに壊れるため、その経路自体を持たせない。書き出しは常に一時ファイルへ行い、完了後に `Path.replace()` で差し替える。

`canonical_grid.py` と異なり `--overwrite` を課さないのは、「1つのパラメータだけ再計算する」ことが通常運用であり、毎回フラグを要求するとパラメータ単位で独立に再計算できるという狙いと逆行するためである。失敗時に既存の出力を失わない保護は一時ファイル経由で担保する。

> **Windows での注意**: 出力先を QGIS などが開いたままだと差し替えが失敗する。素の `PermissionError` ではなく、他のアプリケーションで開かれていないかを案内する日本語メッセージへ包み直し、書き出し済みの一時ファイルは回収できるよう残す。

### 7.7 入力レイヤの読み込み1回化（`io.py`）

複数スケールを1回の実行で出力する場合、同じ入力レイヤをスケール数だけ読み直すと所要時間の支配項になる。`layer_cache()` のスコープ内では読み込み結果を再利用する。

| 入力レイヤ | 件数 | 保持コスト | 1スケールあたりの節約 |
|---|---|---|---|
| 建物（GBA） | 3,071,511 | 約 1.3 GB | 約 21 秒 |
| 道路（OSM） | 194,485 | 約 0.5 GB | 約 4 秒 |

3スケール実行で読み込み分の所要時間は 75.6 秒 → 24.9 秒（実測）、ピーク常駐メモリは約 2.0GB になる。**解析範囲を広げる場合はこの比率が変わるため、特に道路については採否を見直す。**

キャッシュキーは関数ごとに分ける。

| 関数 | キー | 条件 |
|---|---|---|
| `read_layer_dataframe()` | `(パス, レイヤ名, 読み込む列, source_crs, analysis_crs)` | BBox を取らない関数のためスケール非依存 |
| `iter_feature_records()` | `(パス, レイヤ名)` | **検索BBoxがレイヤ全体を覆うときだけ**参照・保存する |

整合BBoxはスケールごとに異なる（`maxy` が 30m: 2365950 / 90m: 2366010 / 300m: 2366100）ため、BBox をキーに含めるとスケールごとにミスして1回化できない。一方 BBox を無視したキーにすると、レイヤの一部だけを求める呼び出しへ全件を返してしまう。そこで「空間フィルタが結果に影響しない」ことを確認できたときに限りキャッシュを使う。**この判定は保存側だけでなく参照側にも必要である。**

現在の入力レイヤはいずれも ROI へクリップ済みのため全スケールでこの条件を満たす（実測で建物・道路とも 30/90/300m すべて成立）。ただし**これはデータ側の性質に依存した成立であって設計上の保証ではない**。前提が崩れた場合は再読み込みが発生して**性能が落ちるだけで、結果は変わらない**。

> **返り値を破壊的に変更してはならない。** キャッシュは読み込み結果そのものを保持し、呼び出し側へ同じオブジェクトを返す。変更すると以降のスケールが変更後のデータを受け取る。

---

## 8. CRS・単位ルール

- 測量GISの正本座標: EPSG:5897
- 距離・面積・長さ計算: 投影座標系（`analysis_epsg`。既定値はEPSG:5897／VN-2000 TM-3 zone 482。都市ごとに設定）
- 温度: 摂氏（LST側の仕様に従う）
- 被覆率: 0-1
- 道路密度: m/ha（面積正規化、`grid.cell_area_ha()` で算出）
- 建物数密度: 棟数/ha（面積正規化）

---

## 9. 例外処理と堅牢性

- 不正ジオメトリは `make_valid` を試行し、失敗時はスキップ
- レイヤ名が設定値と不一致の場合は、候補レイヤを探索して自動解決
- 任意入力（衛星指標）が欠けていても処理継続
- 入力の解決と対象スケールのグリッドレイヤの存在確認は、算出へ入る前にまとめて行い、不足があれば1件も出力せずに停止する
- ラスタ設定の不備（`path` / `band` の欠落、バンド数を超えるバンド番号）は日本語の `ValueError` で停止する
- **セル平均の列が全セル `NaN` になった場合は警告する**（DEM・LSTに共通。`params/raster.py: aggregate_mean_and_valid_ratio()`）。ファイルは存在するため入力解決を素通りし、列が残ったまま中身だけが空になる
  - **原因を2つに切り分けてから文言を選ぶ。** 「ラスタがグリッドと重なっていない」（都市の取り違え・切り出し範囲の誤り）と「重なってはいるが有効画素が1つも無い」（**全面が雲マスクの観測**・nodata値の取り違え）は、どちらも全セル `NaN` という同じ結果になる一方、対処がまったく異なる。判定は `raster_overlaps_grid()` がラスタの記録範囲とグリッド範囲の交差で行い、**画素値は読まない**
  - 切り分けは全セル `NaN` のときにしか行わない。正常な入力でラスタを開き直すコストを掛けないためである
  - **LSTでは「重なっているが全面欠測」が現実に起こり得る**（実データの有効画素率は25.4〜45.7%）。これを「重なりません」と報告すると、実際の原因（観測日の選び直し）から遠ざけてしまう
- `compute()` の戻り値が `PARAM_SETS` の宣言列と食い違う場合は、不足・余分を示して停止する（別ソース版どうしで列が揃わなくなるため）
- 出力先への差し替えに失敗した場合（QGIS等が開いたまま等）は、対処を示す日本語メッセージへ包み直し、書き出し済みの一時ファイルは回収できるよう残す
- エラーメッセージは日本語で明示

---

## 10. CLI仕様

**前提**: 先に正準グリッドを生成しておく（7.5.7節）。パラメータテーブルの行集合はこのグリッドを正本とする。

### 10.1 算出フェーズ

```bash
# パラメータセット単位（複数スケールでも入力レイヤの読み込みは1回）
python -m src.analysis.urban_params --city hanoi \
  --params build_gba road_osm elev_fabdem mask_roi \
  --scales 30 90 300 --fine-res 10

# 衛星指標（観測ファイル単位）
python -m src.analysis.urban_params --city hanoi \
  --satellite-file data/satellite/indices/2023/INDICES_Landsat8_20230707_032329Z.tif \
  --scales 30 90 300

# LST（観測ファイル単位）。衛星指標と併用する場合は両方の引数を指定する
python -m src.analysis.urban_params --city hanoi \
  --lst-file data/satellite/lst/2023/LST_Landsat8_20230707_032329Z.tif \
  --satellite-file data/satellite/indices/2023/INDICES_Landsat8_20230707_032329Z.tif \
  --scales 30 90 300
```

主要引数:

- `--city`: 都市ID（例: hanoi）
- `--params`: 算出するパラメータセット名の一覧（5.2.0節）。テーブル名としてそのまま使う
- `--satellite-file`: 任意。衛星指標ラスタの**単一ファイル**。テーブル名はファイル名の観測日時から導く
- `--lst-file`: 任意。LSTラスタの**単一ファイル**。テーブル名はファイル名の観測日時から導く
- `--scales`: 出力するcoarseグリッド解像度（m）の一覧（既定: `30 90 300`）。900 の約数である必要がある
- `--fine-res`: 被覆率計算の補助解像度（既定10m）
- `--grid`: 正準グリッドGeoPackageのパス（既定: `data/output/grid/grid_{city}.gpkg`）
- `--output-dir`: 出力ルート（既定: `data/output/params`）

`--params` / `--satellite-file` / `--lst-file` は少なくとも1つの指定が必要である。

**廃止した引数**: `--scenario`（シナリオは結合側へ移動）、`--mask-layer-key`（解析範囲は ROI へ一本化し、有効域は `mask_roi` テーブルが持つ）、`--satellite-dir`（複数観測を1テーブルへ混ぜる余地を残すため、単一観測の指定に限る）。

### 10.2 結合フェーズ

```bash
# シナリオ名で結合対象を展開する
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited

# テーブルを直接指定する（別ソース版の比較・衛星指標の追加など）
python -m src.analysis.build_dataset --city hanoi --scale 30 \
  --tables build_dc road_gt idx_20230707_032329 --name full_with_indices

# シナリオと観測ファイル単位のテーブルを併用する（satellite_only はこの形が必須）
python -m src.analysis.build_dataset --city hanoi --scale 30 \
  --scenario satellite_only --tables idx_20230707_032329 lst_20230707_032329 \
  --name satellite_only_20230707_032329
```

主要引数:

- `--scale`: 結合対象のスケール（m）。**単一指定に限る**（`cell_id` はスケール内でのみ一意のため）
- `--scenario` / `--tables`: 結合対象の指定。**併用可**（シナリオ展開＋観測ファイル単位テーブルの追加）。併用時は `--name` が必須
- `--name`: データセット名。`--scenario` 単独指定時の既定はシナリオ名、`--tables` を使う場合（併用含む）は必須
- `--params-dir` / `--grid` / `--output-dir`: 入出力ルート

### 10.3 現在の実装状況

> 本節の内容は冒頭メタ情報の「最終更新」時点のものである（見出しに日付を持たせると二重管理になり、実際に取り残されたことがあるため）。

- **`params/roads.py`（`ROAD_DEN`）**: 設計確定・実装済み。`hanoi_osm_roads.gpkg`（`road_osm`）から車道のフィルタリング（ホワイトリスト + トンネル除外）を行い、セル内道路延長密度（m/ha）を算出する。
- **`params/buildings.py`（`BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX`）**: 設計確定・実装済み。`hanoi_gba_buildings.gpkg`（`build_gba`、GBA、3,071,511 件）から被覆率・棟数密度・平均/最大高さを算出する。件数が多いため、本モジュールのみレイヤの一括読み込みと NumPy によるベクトル化集計を採る。`build_dc`（`merge_DC.gpkg`）は高さ属性を持たないため、高さ列は NaN になる。
- **`params/elevation.py`（`ELEV_MEAN` / `ELEV_VALID_RATIO`）**: 設計確定・実装済み。FABDEM v1.2（`fabdem_hanoi_dem.tif`、`elev_fabdem`）を coarse グリッドへ平均再投影し、セル平均標高（m）とセル内のDEM有効画素率（0-1）を算出する。`ELEV_COUNT` は出力しない。DEMラスタは `.gitignore` の対象であり、ファイルが無い場合は `FileNotFoundError` で停止する（列が黙って欠けるのを防ぐため）。
- **`params/lst.py`（`LST` / `LST_VALID_RATIO`）**: 設計確定・実装済み。LSTラスタ（`--lst-file`）を coarse グリッドへ平均再投影し、セル平均地表面温度（°C）とセル内のLST有効画素率（0-1）を算出する。目的変数であり `VALID_SATELLITE_MASK` の判定材料には含めない（6.3節）。集約後の有効値の中央値が摂氏として妥当な範囲（-60〜90°C）の外なら警告する（ケルビン取り違えの検知。正常なLSTを弾かない広さに取る）。
- **`params/mask.py`（`IN_ANALYSIS_AREA`）**: 設計確定・実装済み。ROI ポリゴンの被覆率が0より大きいセルを1とする。
- 衛星指標・LSTは `INDICES_*.tif` / `LST_*.tif` のバンド説明（衛星指標: NDVI, NDBI, NDWI／LST: LST）から検出・検証する。
- 実行には `fiona`, `pyogrio`, `rasterio`, `shapely`, `pyproj` を含む `environment.yml` 相当の Python 環境が必要である。
- **旧 wide CSV（`data/output/urban_params/*.csv`）は残置する。** 再生成の手段は持たない（旧原点での算出は `verify_values.py` が担う）。

---

## 11. 検証項目（最低限）

- 各スケール（30/90/300m）のパラメータテーブルが、正準グリッドの該当レイヤと**同じ行数**で出力される
- 入力した衛星指標（`NDVI` 等）が出力され、値が妥当な範囲に収まる
- 結合したデータセットの `lon`, `lat` がハノイ近傍範囲に入る
- 同じコマンドを2回実行しても行数が倍にならない（追記経路を持たないこと）
- `BUILD_H_MEAN` / `BUILD_H_MAX` の欠測が GeoPackage の NULL として保持される
- 衛星指標テーブルが観測日時つきの名前（`idx_20230707_032329` 等）で出力される
- QGIS で正準グリッドのレイヤ（`grid_30m` 等）にベクタレイヤ結合で繋ぎ、`BUILD_COV` で着色表示して分布が妥当である
- GIS由来パラメータ（6.4節）を追加する際は、被覆率（0-1）・密度（負値なし）・有効カバレッジ内かどうかの確認を、各パラメータのサブIssueで検証項目として追加する

**標高（`ELEV_MEAN` / `ELEV_VALID_RATIO`）の検証観点**

- 値域が入力DEMの統計範囲に収まり、平均が同水準である（集約により最小値は上がり最大値は下がるため、**特定の下限値を合格基準にしない**）
- `ELEV_MEAN` は有効カバレッジ外が `NaN` であり、`0` で埋まっていない（値がちょうど `0` のセルが欠損由来でないこと）
- `ELEV_VALID_RATIO` は有効画素が無いセルを `0.0` とする（`NaN` にしない。nodata で覆われたセルと範囲外セルを同じ「有効画素なし」として扱うため）
- `IN_ANALYSIS_AREA == 1` のセルについて、標高が `NaN` の件数と**有効画素率の分布（1未満・0.5未満の件数）**をスケール別に記録する。DEMはROIでcrop済みのため境界セルで発生し得る。**`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する**ため、両方を有効カバレッジの議論に用いる
- `ELEV_VALID_RATIO` が 0-1 に収まり、`ELEV_MEAN` が `NaN` のセルで `0.0` になっている（両列の整合）
- `VALID_GIS_MASK` の分布が標高の追加前後で変わらない（品質判定に混入していないこと）
- スケール間（30/90/300m）で平均標高の水準が整合する

**LST（`LST` / `LST_VALID_RATIO`）の検証観点**

- 値が摂氏として妥当な範囲に収まる（実データ実測 min 13.50 / max 63.27°C）。集約後の中央値がケルビン相当（約270〜320）でないことを確認する
- `LST` は有効カバレッジ外・雲被覆セルが `NaN` であり、`LST_VALID_RATIO` は有効画素が無いセルを `0.0` とする（`NaN` にしない、両列の整合）
- `LST_VALID_RATIO` の分布（1未満・0.5未満の件数）をスケール別に記録する。実データは雲マスクにより有効画素率が25.4〜45.7%と低いため、**`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する**
  - この件数は算出時に自動で出力される（`run.py: summarize_valid_ratio()`）。`_VALID_RATIO` で終わる列を対象とするため、`ELEV_VALID_RATIO` も同時に報告される。min/mean/max だけでは分布の偏りが読めないため、`describe()` とは別に件数を出す
- 結合後のデータセットで `VALID_SATELLITE_MASK` が `NDVI`/`NDBI`/`NDWI` のみから決まり、`LST` の有無で変わらない（6.3節）
- `IN_ANALYSIS_AREA == 1` のセルにおける `LST` 非 NULL 件数を記録する

### 11.1 ユニットテスト

`tests/analysis/urban_params/` と `tests/analysis/` に、各モジュールの主要関数に対するユニットテストを配置している。

- 既知のジオメトリ・グリッドを用いて、被覆率・重心カウント・ライン密度・標高集計などの計算結果が期待値と一致することを検証する
- 小さな合成グリッドで `compute → tables → build_dataset` のE2E検証を行う（算出したテーブルを読み直し、`cell_id` 単位で値が一致することまで確認する）
- 複数スケール実行時に入力レイヤの読み込みが1回で済むことを、**キャッシュ自身の集計とは独立したカウンタ付きフェイク**で検証する（実装の自己申告に頼らない）
- `pytest`（`environment.yml` に含まれる）で実行する

```bash
python -m pytest tests/
```

実行時は `pyproject.toml` の `[tool.pytest.ini_options]` によりリポジトリルートが `sys.path` に追加され、`src.analysis.urban_params` をインポートできる。

### 11.2 旧 wide CSV との値照合（`verify_values.py`）

再設計が**算出値を変えていない**ことは、テストではなく実データでの照合により確認する。

正準グリッドと旧グリッドはセルが対応しない（7.5.1節）ため、再設計後の出力と旧 CSV をセル単位で照合することはできない。そこで**検証専用に旧BBox原点の `GridSpec` を構築**し、再設計後の算出経路（`PARAM_SETS` による入力解決・io層のキャッシュ・列検証）を通した結果を旧 CSV と全列照合する。`GridSpec` と解析BBoxだけを旧仕様へ差し替える形にしているのは、`compute()` を直接呼ぶだけでは再設計で新たに入った要素を何も検証しないためである。

```bash
python -m src.analysis.urban_params.verify_values --city hanoi \
  --params build_gba road_osm --legacy-scenario limited --scales 30 90 300
```

**照合結果（2026-08-12・ハノイ・`limited`）**: 3スケール・5列のすべてで**不一致 0 件・最大絶対差 0**、すなわちビット単位で完全に一致した。

| スケール | 行数（旧 CSV と一致） | 座標の最大差 | 照合結果 |
|---|---|---|---|
| 30m | 3,736,071 | lon 1.4e-14 / lat 3.6e-15 度 | 全5列一致 |
| 90m | 417,310 | 同上 | 全5列一致 |
| 300m | 38,213 | 同上 | 全5列一致 |

照合上の前提が2点ある。

- **NaN 同士は一致として扱う。** `BUILD_H_MEAN` / `BUILD_H_MAX` の欠測規約が維持されていることを確認する必要があるため
- **旧 CSV の保存精度（float32）へ揃えてから比較する。** 旧 CSV は float32 の値を「float32 として往復できる最短の10進表記」で保存しており、float64 として読むと元の float32 との間に最大で float32 の半 ULP のずれ（値1.0付近で約6e-8、値680付近で約3e-5）が残る。これは算出値の差ではなく表記の丸めによる差である

照合対象は建物4種と道路の5列とする。標高は旧 CSV の生成後に算出内容が変わっており（`ELEV_VALID_RATIO` が未収録）、値の同一性を問える状態にない。

> **`verify_values.py` は検証専用であり、旧 CSV が役目を終えた時点で削除してよい。** 削除条件は (1) 再設計後の出力で分析を一巡し値の妥当性が確認できている、(2) `data/output/urban_params/*.csv` を参照する分析・ドキュメントが無くなっている、の2つをともに満たしたとき。削除時は対応するテストも併せて削除する。

### 11.3 QGIS での目視確認（結合と分布の妥当性）

正準グリッド `grid_300m`（38,235セル）にパラメータテーブル4件（`build_gba` / `road_osm` / `elev_fabdem` / `mask_roi`）を**同時に**ベクタレイヤ結合し、全8列を着色表示して確認した。図は `images/urban_params/urban_params_{列名}_hanoi_300m.png` に保存している。

| 確認項目 | 結果 |
|---|---|
| 属性のみのGeoPackageがQGISで開けるか | 4テーブルとも 38,235 件で読み込み（ジオメトリ無しレイヤ） |
| `cell_id` による結合 | 4テーブル同時結合が成立。`BUILD_COV` は 38,235 件すべて非 NULL |
| `cell_id` = `row × 1000000 + col` | 全 38,235 セルで検算一致（不一致0件） |
| QGIS 側の集計と算出時の統計 | 全8列で min / mean / max が一致 |

分布の妥当性は、`BUILD_COV` / `ROAD_DEN` / `ELEV_MEAN` の3図で**紅河の位置が独立に一致**することで確認した（建物・道路が無く、標高が低い帯として現れる）。結合が空間的に正しいことの裏付けになる。

**欠測規約と品質管理列も図と数値で確認した。**

- `BUILD_H_MEAN` / `BUILD_H_MAX`: NULL は 7,567 セル（19.8%）で、**2列の NULL が完全に一致**する（食い違い0件）。同一の除外条件で動いていることを示す
- `ELEV_MEAN` が NULL の 12 セルは**すべて `ELEV_VALID_RATIO = 0.0`**（違反0件）。11章の「両列の整合」を満たす
- `IN_ANALYSIS_AREA = 0` は**ちょうど 35 セル**で、すべて ROI 境界上にある。6.1節の「交差 ⊇ `IN_ANALYSIS_AREA`」と一致する

> **QGIS-MCP の制約**: `add_table_join` は結合を登録するが結合レイヤの参照を解決しないため、`layer.resolveReferences(QgsProject.instance())` を呼ぶまで結合フィールドが現れない。

---

## 12. 今回の再構築ゴール

1. 本ガイド（設計）を正本化  
2. `urban_params` パッケージを本ガイド準拠で実装  
3. `Satellite Only` / `Limited` / `Full` の3シナリオに接続できる入力仕様を固定する
4. 研究者が「変数定義・計算根拠・制約」を追跡できる状態にする
5. **パラメータ単位のテーブル出力へ移行し、パラメータの追加・変更がそのパラメータの再計算だけで済む構成にする**（達成。感度分析は結合先の差し替えだけで済む）

---

## 13. 更新ルール

- 実装変更時は本ガイドを同時更新する
- 列名・単位・欠損規則を変更した場合は必ず履歴に残す
- `docs/README.md` のカタログ情報と齟齬を作らない
