# calc_urban_params 入出力仕様

**最終更新**: 2026-08-22
**関連ドキュメント**: [calc_urban_params_guide.md](../calc_urban_params_guide.md)（ハブ・索引）, [calc_urban_params_processing_design.md](calc_urban_params_processing_design.md), [calc_urban_params_cli_verification.md](calc_urban_params_cli_verification.md), [urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md), [available_gis_data.md](../../01_planning/available_gis_data.md)
**前提知識**: [calc_urban_params_guide.md](../calc_urban_params_guide.md) 1章・3章・4章（本ガイドの位置づけ・用語・スコープ）

> 本ファイルは [calc_urban_params_guide.md](../calc_urban_params_guide.md) の5章・6章を分割したものである。全体の索引・位置づけはハブを参照。

---

## 索引

| 節 | 1行要約 |
|---|---|
| 5.1 必須入力（共通） | 全パラメータセットで共通に必要な入力レイヤ |
| 5.2 パラメータセット別入力（GIS） | パラメータセットの定義・Limited/Full の入力レイヤ |
| 5.3 任意入力（衛星指標・LSTラスタ） | 衛星指標・LSTラスタのバンド仕様と検証 |
| 6.0 出力構成の全体像 | 算出フェーズ・結合フェーズそれぞれの出力構成 |
| 6.1 パラメータテーブル | 算出フェーズの出力（`cell_id` キーのGeoPackage） |
| 6.2 条件付きテーブル | 衛星由来・LST由来の条件付き出力 |
| 6.3 品質管理列 | `VALID_GIS_MASK` / `VALID_SATELLITE_MASK` / `MISSING_REASON` 等の導出規則 |
| 6.4 GIS由来パラメータ | 確定済み・実装未着手のGIS由来パラメータ一覧 |
| 6.5 出力列と算出モジュールの対応 | 列名と `params/*.py` の対応表 |
| 6.6 分析用データセット | 結合フェーズの出力（分析用データセット） |
| 6.7 新旧の差異と比較可能性（Satellite Only） | 旧経路・新経路の仕様差と比較不可の理由 |

---

## 5. 入力仕様（再定義）

### 5.1 必須入力（共通）

- ROI でクリップ済みの LST ラスタ
- 30m グリッド化対象となる GIS データ一式
- 解析範囲を定義するポリゴンまたは境界データ

### 5.2 パラメータセット別入力（GIS）

> **本節の位置づけ**: 建物・道路・標高（`Limited`）は入力源・算出方法とも確定し、出力仕様（6章）に反映済みである。  
> 採用済みで設計が未確定なパラメータは、入力データ・算出方法をパラメータ単位で確定したうえで出力仕様へ追加する。  
> どのパラメータが採用済みかは [urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md) を正本とする（[calc_urban_params_guide.md](../calc_urban_params_guide.md) 1.1節）。

#### 5.2.0 パラメータセットの定義

「**どのパラメータを、どの入力ソースで算出するか**」の組を**パラメータセット**と呼び、`config.py` の `PARAM_SETS` に定義する。**テーブル名はパラメータセット名と一致させ、出力ファイル名・レイヤ名の双方に使う。**

| パラメータセット名 | 算出モジュール | 入力 | 出力列 |
|---|---|---|---|
| `build_gba` | `params/buildings.py` | `layers.open_buildings`（GlobalBuildingAtlas） | `BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX` |
| `build_dc` | `params/buildings.py` | `layers.dc`（測量GIS） | 同上 |
| `road_osm` | `params/roads.py` | `layers.open_roads`（OSM） | `ROAD_DEN` |
| `road_gt` | `params/roads.py` | `layers.gt`（測量GIS） | 同上 |
| `elev_fabdem` | `params/elevation.py` | `rasters.fabdem` | `ELEV_MEAN` / `ELEV_VALID_RATIO` |
| `pop_worldpop2020` | `params/population.py` | `rasters.worldpop2020`（band 2） | `POP_DEN_WORLDPOP2020` / `POP_VALID_RATIO_WORLDPOP2020` |
| `pop_landscan2020` | `params/population.py` | `rasters.landscan2020`（band 2） | `POP_DEN_LANDSCAN2020` / `POP_VALID_RATIO_LANDSCAN2020` |
| `pop_landscan2023` | `params/population.py` | `rasters.landscan2023`（band 2） | `POP_DEN_LANDSCAN2023` / `POP_VALID_RATIO_LANDSCAN2023` |
| `ntl_viirs2023` | `params/nightlight.py` | `rasters.viirs2023`（band 1） | `NTL_MEAN` / `NTL_VALID_RATIO` |
| `ntl_bm2023` | `params/nightlight.py` | `rasters.bm2023`（band 1） | 同上 |
| `lulc_glc2022` | `params/lulc.py` | `rasters.glc2022`（GLC_FCS30D 2022年、band 1、主ソース） | `LULC_WATER_COV` / `LULC_TREE_COV` / `LULC_CROP_COV` / `LULC_BUILT_COV` / `LULC_RANGE_COV` / `LULC_WETLAND_COV` / `LULC_BARE_COV` / `LULC_VALID_RATIO` |
| `lulc_esri2022` | `params/lulc.py` | `rasters.esri2022`（Esri Sentinel-2 10m LULC 2022年、band 1、感度分析用の副ソース） | 同上 |
| `mask_roi` | `params/mask.py` | `layers.roi` | `IN_ANALYSIS_AREA` |

**同じ列名の別ソース版を並置できる**（`build_gba` と `build_dc`、`road_osm` と `road_gt`、`ntl_viirs2023` と `ntl_bm2023`）ことが、感度分析を「結合先の差し替えだけ」で済ませる要である。`PARAM_SETS` は各セットが返すべき列を宣言し、`compute()` の戻り値と実行時に突き合わせて、別ソース版どうしで列が食い違う状態を検知する。

**人口の3版だけは例外で、列名にデータソース接尾辞を付けて区別する。** 差し替え候補ではなく、概念も観測年も異なる別変数であり、同一データセットへ同時に結合するためである（6.4節）。接尾辞つきの列名は `PARAM_SETS` が宣言し、付与そのものは `run.py: apply_column_suffix()` が担う。

**シナリオは算出側では扱わない。** シナリオは「どのテーブルを結合するか」の選択へ還元されており、`SCENARIO_TABLES`（シナリオ → 結合するテーブル名の一覧）として結合フェーズが持つ（6.6節）。

**解析範囲は当面 ROI へ一本化する。** 測量GIS（RG）を基準にするパラメータセットは設けない。RG は境界**線**主体のレイヤで 90.6% が面積ゼロであり、面積ベースの `compute_polygon_coverage()` と噛み合わないためである（[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7.5.6節）。**したがって `full` シナリオの有効域定義は未決のままである。**

#### 5.2.1 Limited

**確定済みの入力**

- **建物ポリゴン**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas 由来）
- **道路ライン**: `data/gis/roads/hanoi_osm_roads.gpkg`（OpenStreetMap / Geofabrik 由来）
- **オープンソースDEMラスタ**: `data/gis/dem/fabdem/fabdem_hanoi_dem.tif`（FABDEM v1.2、EPSG:4326、約30m）
- **人口ラスタ**: `data/gis/population/worldpop/worldpop_hanoi_2020.tif` / `data/gis/population/landscan/landscan_hanoi_2020.tif` / `data/gis/population/landscan/landscan_hanoi_2023.tif`（いずれも **band 2** の密度バンド、EPSG:4326。3版は差し替え候補ではなく別変数として並置する。6.4節）
- **夜間光ラスタ**: `data/gis/nighttime_lights/viirs_dnb/viirs_dnb_hanoi_2023.tif`（主候補）／`data/gis/nighttime_lights/black_marble/black_marble_vnp46a4_hanoi_2023.tif`（副候補）。いずれも **band 1**、EPSG:4326（6.4節）
- **土地被覆ラスタ**: `data/gis/lulc/glc_fcs30d/glc_fcs30d_hanoi_2022.tif`（GLC_FCS30D 2022年、主ソース）／`data/gis/lulc/esri_10m/esri_lulc_hanoi_2022.tif`（Esri Sentinel-2 10m LULC 2022年、感度分析用の副ソース）。いずれも **band 1**、EPSG:4326。植生（植生被覆率）は独立入力を持たず、土地被覆クラス別面積率の樹林・草地低木クラスの読み替えである（6.4節）

> 建物データの比較候補として Microsoft GlobalMLBuildingFootprints / Google Open Buildings / OSM `building=*` を検討したが、Limited シナリオの採用は GlobalBuildingAtlas で確定している（詳細は [gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md)）。  
> なお Hanoi ROI では Microsoft 建物データが西側行政区画を十分に覆っていない。比較用に用いる場合、建物データの有効カバレッジ外では被覆率・棟数密度の `0` が建物不存在を意味しない点に注意する。

#### 5.2.2 Full

- `整備データ/merge/merge_RG.gpkg`（分析範囲定義）
- `整備データ/merge/merge_DC.gpkg`（建物）
- `整備データ/merge/merge_GT.gpkg`（道路）
- `整備データ/merge/merge_TH.gpkg` または `merge_DH.gpkg`（水系・標高関連、利用方法は要確認）
- `整備データ/merge/merge_TV.gpkg`（植生・土地利用）

> DH / TV のどちらを標高・植生率に使うかは、`gpkgの確認結果.md` と `DGNファイル内容確定結果.md` を踏まえて最終確定する。  
> 現時点では完全確定ではなく、実装と並行して調整中である。  
> `merge_TH.gpkg`（水系）はデータの棚卸しとして掲げるにとどめる。水域関連のパラメータは採用しておらず、算出対象ではない（[calc_urban_params_guide.md](../calc_urban_params_guide.md) 1.1節）。

### 5.3 任意入力（衛星指標・LSTラスタ）

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
  - **詳細**: [gis_data_roads.md](../../01_planning/gis_data/gis_data_roads.md) セクション 2

- **建物パラメータ4種**: 設計確定・実装済
  - **入力**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GlobalBuildingAtlas 由来）
  - `BUILD_COV`（建物被覆率, 0-1）: fine グリッドへラスタ化し coarse セルへ平均集約
  - `BUILD_DEN`（建物棟数密度, 棟/ha）: 重心が属するセルごとの棟数を `cell_area_ha()` で正規化
  - `BUILD_H_MEAN` / `BUILD_H_MAX`（建物高さ, m）: 重心が属するセルごとの有効高さの平均・最大
  - **高さの除外条件**: 推定分散または高さ自体が負・欠測の建物を高さ集計から除外（被覆率・棟数密度からは除外しない）
  - **欠測規約**: セル内に有効高さの建物が無い場合、高さは 0.0 ではなく **NaN**
  - **解釈上の注意**: `BUILD_COV = 0` は建物の不存在を意味しない（30m では建物のあるセルの14%が該当）。建物の有無は `BUILD_DEN` で判定する
  - **詳細**: [gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md) セクション 3

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
  - **詳細**: [gis_data_dem.md](../../01_planning/gis_data/gis_data_dem.md)

- **`ELEV_VALID_RATIO`（DEM有効画素率, 0-1）**: 設計確定・実装済（パラメータセット `elev_fabdem`）
  - **入力**: `ELEV_MEAN` と同一のDEMラスタ
  - **算出方法**: 有効画素を1・nodataを0とした配列を、`ELEV_MEAN` と同じ `Resampling.average` で coarse グリッドへ再投影する
  - **必要性**: `Resampling.average` はセル内の**有効画素のみ**で平均を取るため、セルの1割しかDEMに覆われていなくても、完全に覆われたセルと同じ実数が `ELEV_MEAN` に入る。`NaN` の件数だけでは部分被覆セルを捕捉できず、有効カバレッジを過大評価する（実測では `IN_ANALYSIS_AREA == 1` のうち、300mスケールで `NaN` は0.013%である一方、有効画素率99%未満は4.67%・50%未満は2.42%）
  - **欠測規約**: ラスタ範囲外のセルは `NaN` ではなく **`0.0`**（nodataで覆われたセルと同じ「有効画素なし」を意味するため揃える）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は6.3節）
  - **解釈上の注意**: 入力ラスタの外周より外側（画素が1つも無い領域）が占める分は比率に反映されないため、ラスタの矩形範囲を一部しか含まないセルでは実際の被覆より高い値になり得る。現行の入力（ROIでcrop済みのDEM）では解析BBox最外周のセルに限られる
  - **`ELEV_COUNT`（セル内の有効点数）は出力しない**（スケールによって画素数の意味が変わり、比率のほうがスケール間で比較可能なため）

- **`POP_DEN_{データソース}`（人口密度, 人/ha）**: 設計確定・実装済（パラメータセット `pop_worldpop2020` / `pop_landscan2020` / `pop_landscan2023`）
  - **入力**: `data/gis/population/worldpop/worldpop_hanoi_2020.tif`、`data/gis/population/landscan/landscan_hanoi_2020.tif`、`data/gis/population/landscan/landscan_hanoi_2023.tif`。いずれも **band 2**（`population_density_per_km2`、EPSG:4326、nodata `-9999`）
  - **算出方法**: 標高・LSTと共通の `aggregate_mean_and_valid_ratio()` により coarse グリッドへ `Resampling.average` で再投影し、得られたセル平均密度（人/km²）を **100 で割って人/ha** とする
  - **`grid.cell_area_ha()` は使わない**: 密度バンドは取得スクリプトが行ごとに WGS84 楕円体上の実面積で算出している（[gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.2節）。平面セル面積で割り直すと、実面積に基づく値を近似で上書きすることになる。1 km² = 100 ha の定数換算で足りる
  - **カウントバンド（band 1）を合計集約する経路は採らない**: カウントは合計保存量であり合計集約を要するが、本経路が集約するのは合計保存量ではない密度であり平均集約が妥当である。本研究はセル単位の密度のみを説明変数に用いるため、人口総数を保存する利点も活かせない
  - **列名にデータソース接尾辞を付ける**: `POP_DEN_WORLDPOP2020` / `POP_DEN_LANDSCAN2020` / `POP_DEN_LANDSCAN2023`。3版は差し替え候補ではなく、概念（居住人口／実効人口）も観測年も異なる**別変数**であり、説明力の差を分離するには同一データセットへ同時に結合する必要がある。列名を共有すると `build_dataset.py` の `join_tables()` が列名衝突として結合を拒否する。付与は `run.py: apply_column_suffix()` が担い、算出モジュールは自分がどのデータセットを処理しているかを知らない
  - **欠測規約**: 有効カバレッジ外は **NaN**。`0` は「データが無い」ではなく**人口ゼロの実測値**であり、両者を同一視しない
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**。連続量であり「0より大きければ有効」という基準が成り立たないためで、標高と同じ理由である（6.3節）
  - **セルの信頼度**: 平均はセル内の**有効画素のみ**で取るため、値の有無だけでは部分被覆セルを判別できない。判別には `POP_VALID_RATIO_{データソース}` を用いる
  - **解釈上の注意**:
    - WorldPop は**居住人口**、LandScan は**実効人口**（昼間の人口移動を考慮）であり概念が異なる。集計レベルでは一致するが、セル単位では都心で LandScan が大きく上回る（[gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.5節）
    - **真の集約が成立するのは WorldPop の 300m のみ**である。ハノイの緯度での画素実寸から求めた1セルあたり画素数は、WorldPop（約 86.7m × 92.3m）が 30m で 0.11・90m で 1.01・300m で 11.3、LandScan（約 866.6m × 922.6m）は 300m でも 0.11 にとどまる。WorldPop の 90m は実質的なリサンプリング、30m は1画素が約9セルへ広がる内挿であり、隣接セルが同じ値を共有する
    - この差は出力値にも現れる。`POP_DEN` の最大値は WorldPop が 685.66 → 680.96 → 671.11 人/ha とスケールとともに減少する（集約でピークが平滑化される）のに対し、LandScan は3スケールとも変化しない（2020 は 830.98 人/ha、2023 は 969.47 人/ha のまま。画素値がそのまま複写される）
    - RQ2 は **WorldPop にのみ**割り当てる（[urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md) §1.4・§2.1）
  - **詳細**: [gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.7節

- **`POP_VALID_RATIO_{データソース}`（人口ラスタ有効画素率, 0-1）**: 設計確定・実装済（`POP_DEN_{データソース}` と同じパラメータセット）
  - **入力**: `POP_DEN_{データソース}` と同一のラスタ・同一バンド
  - **算出方法**: 有効画素を1・nodataを0とした配列を、`POP_DEN` と同じ `Resampling.average` で coarse グリッドへ再投影する
  - **必要性**: WorldPop は大規模水域を無効画素とするため（無効画素の83%が水域。[gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.4節）、部分被覆セルが無視できない割合で生じる。実測では有効画素率が 1.0 未満のセルが 30m で 3.8%・90m で 5.9%・**300m で 13.7%**、0.5 未満のセルが 300m で 4.7% である（2026-08-20 の CLI 検証）
  - **セル全体を母数とする密度**: `POP_DEN × POP_VALID_RATIO` で得られる。平均は有効画素のみで取るため、水域が大半を占めるセルでも陸地部分の密度がそのまま `POP_DEN` に入る
  - **欠測規約**: ラスタ範囲外のセルは `NaN` ではなく **`0.0`**（`ELEV_VALID_RATIO` と揃える）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**
  - **解釈上の注意**: 入力ラスタの外周より外側が占める分は比率に反映されないため、ラスタの矩形範囲を一部しか含まないセルでは実際の被覆より高い値になり得る（`ELEV_VALID_RATIO` と同じ制限）

- **`NTL_MEAN`（夜間光強度, nW·cm⁻²·sr⁻¹）**: 設計確定・実装済（パラメータセット `ntl_viirs2023` / `ntl_bm2023`）
  - **入力**: `data/gis/nighttime_lights/viirs_dnb/viirs_dnb_hanoi_2023.tif`（**band 1** = `avg_radiance`）および `data/gis/nighttime_lights/black_marble/black_marble_vnp46a4_hanoi_2023.tif`（**band 1** = `ntl_near_nadir`）。いずれも EPSG:4326、nodata `-9999`
  - **算出方法**: 標高・人口と共通の `aggregate_mean_and_valid_ratio()` により coarse グリッドへ `Resampling.average` で再投影し、セル平均放射輝度を得る
  - **面積正規化しない**: 放射輝度は面積に比例しない**強度量**であり、人口密度のように /ha へ割ると意味を失う
  - **列名は2版で共有する**: VIIRS DNB を主候補・Black Marble を副候補とする**差し替え関係**であり（主バンド同士の Pearson r = 0.976）、感度分析は結合先テーブルの差し替えだけで済む。人口密度と異なりデータソース接尾辞は付けない
  - **VIIRS DNB の band 2（`avg_radiance_masked`）は使わない**: 背景と判定された画素の扱いは配布データ側に依存し、本ファイル・本ROIでは **0 として現れた**（[gis_data_nighttime_lights.md](../../01_planning/gis_data/gis_data_nighttime_lights.md) 5.1節）。0で現れる限り「電力由来の光が検出されなかった」ことと「観測できなかった」ことの区別が値の上で失われる
  - **欠測規約**: 有効カバレッジ外は **NaN**。`0` は実測値であり欠測ではない（Black Marble の `ntl_near_nadir` は ROI 内の最小値が 0.000 で、実際に0を含む）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（人口密度と同じ理由）
  - **解釈上の注意**:
    - **全解析スケールで実質的な内挿になる**。ハノイの緯度での画素実寸は約 433.3m × 461.3m（約 0.200 km²）で、1セルあたり画素数は 30m で 0.005・90m で 0.041・300m でも 0.450 にとどまる。`NTL_MEAN` の最大値は3スケールとも変化しない（VIIRS 96.10 / Black Marble 213.98）
    - このため **RQ2 は割り当てない**（[urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md) §1.4・§2.1）
    - ROI内に飽和は認められない（両データセットとも p99/max が 0.21〜0.35）。都心部でも階調を説明変数として利用できる
  - **詳細**: [gis_data_nighttime_lights.md](../../01_planning/gis_data/gis_data_nighttime_lights.md) 4.1節

- **`NTL_VALID_RATIO`（夜間光ラスタ有効画素率, 0-1）**: 設計確定・実装済（`NTL_MEAN` と同じパラメータセット）
  - **入力**: `NTL_MEAN` と同一のラスタ・同一バンド
  - **算出方法**: `POP_VALID_RATIO_{データソース}` と同一
  - **ほぼ定数列になる**: 両データセットとも ROI 全域で有効画素率 1.0 であり、1.0 未満のセルは解析BBox最外周に限られる（30m で 1.0%・300m で 4.8%）。説明変数としての情報量は乏しい。それでも出力するのは、集約関数が2列を対で返すため片方を捨てるほうが実装が増えること、および将来の入力差し替え時にカバレッジ低下を検知できることによる
  - **欠測規約・解釈上の注意**: `POP_VALID_RATIO_{データソース}` と同一

- **`LULC_{クラス}_COV`（土地被覆クラス別面積率, 0-1）**: 設計確定・実装未着手（パラメータセット `lulc_glc2022` / `lulc_esri2022`）
  - **入力**: `data/gis/lulc/glc_fcs30d/glc_fcs30d_hanoi_2022.tif`（GLC_FCS30D 2022年、band 1、主ソース）／`data/gis/lulc/esri_10m/esri_lulc_hanoi_2022.tif`（Esri Sentinel-2 10m LULC 2022年、band 1、感度分析用の副ソース）。主ソース・副ソースの位置づけは [gis_data_lulc.md](../../01_planning/gis_data/gis_data_lulc.md) §4 を踏襲する
  - **出力クラス**: 共通クラス体系のうち**雪氷を除く7クラス**（判断日 2026-08-21）。写像表は `src/analysis/compare_lulc_esri_glc.py` の定数として実データで検証済みである

    | 列名 | クラス | GLCクラスID | Esriクラス値 |
    |---|---|---|---|
    | `LULC_WATER_COV` | 水域 | 210 | 1 |
    | `LULC_TREE_COV` | 樹林 | 51・52・61・62・71・72・81・82・91・92 | 2 |
    | `LULC_CROP_COV` | 農地 | 10・11・12・20 | 5 |
    | `LULC_BUILT_COV` | 市街地（不透水面） | 190 | 7 |
    | `LULC_RANGE_COV` | 草地・低木 | 120・121・122・130・140・150・152・153 | 11 |
    | `LULC_WETLAND_COV` | 湿地 | 181〜187 | 4 |
    | `LULC_BARE_COV` | 裸地 | 200・201・202 | 8 |

    `LULC_RANGE_COV` の列名は rangeland（草地・低木を含む牧草・粗放利用地の総称）に由来する。**ROI 内で0画素のクラス（裸地）も列としては出力する。** 出現クラスに応じて列構成を変えると、都市が変わるたびにスキーマが変化して都市間比較ができなくなるためである。
  - **採用しなかった代替案**:

    | 案 | 却下理由 |
    |---|---|
    | GLC 35クラス（または ROI 出現15クラス）をそのまま出力 | 微小クラスが情報を持たず列数だけが増える（ROI 出現15クラスのうち9クラスが1%未満・最小0.00%＝46画素）。Esri との対応も付かない |
    | 主要4クラス（農地・市街地・樹林・水域）に絞る | 和が1にならなくなるため構成制約は消えるが、湿地（GLC 1.77%）・草地低木を捨てる根拠が無く恣意的である |

  - **母数**: セル内の「上記7クラスへ写像される画素」。7クラスの和は定義により厳密に1になる。母数から外れる画素は nodata（GLC の Filled value 0・250、Esri の 0 No Data・10 Clouds）・雪氷（GLC 220 / Esri 9。ベトナムの対象都市で構造的に出現し得ないため定義から除く）・共通クラスへ写像できない画素であり、いずれも同一に「無効」として扱う
  - **写像される画素が1つも無いセルの規約**: 各クラス面積率は **NaN**（比が定義できないため）、`LULC_VALID_RATIO` は **0.0**（`ELEV_VALID_RATIO` と揃える）
  - **面積率の `0` の意味**: そのクラスが存在しないという実測値であり、欠測ではない
  - **構成制約（和=1）への対処**: 本パラメータテーブル（算出フェーズ）は7クラスすべてを出力する。構成制約の解消（参照クラスの除外）は分析フェーズの責務とし、判断根拠は [urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md) §2.2 を正本とする
  - **P8 植生被覆率との関係**: P8 は独立した出力列を持たない。`LULC_TREE_COV`・`LULC_RANGE_COV` の読み替えである。判断根拠は urban_structure_parameters.md §2.2 を正本とする
  - **P11 水域被覆率・P14 不透水面率（保留）との関係**: `LULC_WATER_COV`・`LULC_BUILT_COV` は概念的に重なるが、P11・P14 は専用プロダクト由来の独立パラメータであり定義が異なる。詳細は urban_structure_parameters.md §2.2 を正本とする
  - **`BUILD_COV` との区別**: `LULC_BUILT_COV` は土地被覆分類上の市街地（不透水面）クラスの面積率であり、建物ポリゴンから算出する `BUILD_COV`（建物被覆率）とは入力データも対象物も異なる。市街地/不透水面は建物のほか道路・駐車場等の人工被覆も含むため、`LULC_BUILT_COV ≥ BUILD_COV` が一般に成り立つ
  - **列名共有（データソース接尾辞を付けない）**: GLC・Esri のいずれで算出しても同じ列名（`LULC_{クラス}_COV`）を用いる。同一データセットへ同時に結合しないため `join_tables()` の列名衝突が起きず、感度分析は結合先テーブルの差し替えだけで完結する。人口密度のように接尾辞を付けるのは「概念も観測年も異なる別変数を同時に投入する」場合に限られるが、GLC と Esri は同時投入を意図していない
  - **列名共有は測定量の等価性を主張しない**:
    - **クラス別に代替可能性が成立しない。** 湿地は GLC 基準の一致率 0.03%、草地・低木は 4.68%、裸地は GLC 側 ROI 内0画素であり、これらのクラスをデータセット跨ぎで解釈してはならない
    - **市街地は定義が異なる。** GLC の Impervious surfaces は人工被覆、Esri の Built area は建造環境であり、同じ物理量の2通りの推定値ではない
    - **スケール特性も異なる。** GLC の画素実寸はハノイの緯度で約 28.0m × 29.8m（約 836 m²）で、1セルあたり画素数は 30m で 1.08・90m で 9.69・300m で 108 にとどまる（FABDEM と transform が完全一致）。**30m スケールでは面積率が実質的に 0/1 の二値に近づく。** 一方 Esri の画素実寸は約 9.65m × 10.27m（約 99 m²）で 1セルあたり画素数は 30m で 9.08・90m で 81.7・300m で 908 であり、**30m でも真の集約が成立する。** 同じ列名を共有していても 30m での値の性質は両者で大きく異なる
    - 面積率は画素数比として算出してよい。基準グリッドは投影座標系だが入力ラスタは EPSG:4326 であり画素の地上面積は緯度で変わるが、ROI の緯度幅では差は1%未満である
  - **見直し余地**: 建物フットプリントを基準とした市街地クラスの妥当性検証の結果によって GLC と Esri を同時併存させる必要が生じた場合は、`run.py: apply_column_suffix()` による接尾辞方式へ後付けで切り替えられる（人口密度で実装済みの機構）。列の再設計は不要である。この検証が対象とするのは市街地クラスのみであり、他クラスの代替可能性は検証後も未検証のまま残る。主ソース選択・参照クラス選定（urban_structure_parameters.md §2.2）も、多重共線性の最終診断の結果しだいで見直す余地がある
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**。7クラスの和が有効セルで必ず1になるため、判定材料に含めると ROI 内のほぼ全セルが有効と判定され、本列群の「建物・道路データが当該セルに存在するか」という本来の意味が失われる。実装上は `build_dataset.py` の `GIS_INDICATOR_MODULES`（現在 `{"buildings", "roads"}`）に `lulc` を加えないことで実現する
  - **集約経路（実装方法）**: 本節は出力仕様のみを定める。集約経路（クラス別バイナリマスクの平均集約等）の確定は後続タスクへ送る
  - **詳細**: [gis_data_lulc.md](../../01_planning/gis_data/gis_data_lulc.md)

- **`LULC_VALID_RATIO`（土地被覆データ有効画素率, 0-1）**: 設計確定・実装未着手（`LULC_{クラス}_COV` と同じパラメータセット）
  - **入力**: `LULC_{クラス}_COV` と同一のラスタ
  - **定義**: セル内の全画素のうち、出力7クラスへ写像される画素の割合（`ELEV_VALID_RATIO` / `POP_VALID_RATIO_{データソース}` / `NTL_VALID_RATIO` の前例に倣う）
  - **母数を「有効画素」ではなく「出力7クラスへ写像される画素」とする理由**: 雪氷を定義から外したため、「有効画素」を母数にすると雪氷や写像不能画素が分母にだけ入って和が1未満になる経路が無言で残る（Esri 側には共通クラスへ写像できなかった画素が実在する）。母数を写像先クラスに閉じることで「和 = 1」を定義により保証する。代償として本列は nodata と雪氷を区別しないが、対象都市で雪氷は構造的に出現しないため実害が無い
  - **セル全体を母数とする面積率**: `クラス面積率 × LULC_VALID_RATIO` で得られる（`POP_DEN` と同じ関係）
  - **欠測規約**: ラスタ範囲外のセルは `NaN` ではなく **`0.0`**（`ELEV_VALID_RATIO` と揃える）
  - **品質管理列との関係**: `VALID_GIS_MASK` の判定材料に**含めない**（理由は上記 `LULC_{クラス}_COV` と同一）

> `full` シナリオの標高は設計未確定である（現状は出力しない）。測量GISの `merge_DH.gpkg`（点・等高線）による標高、または FABDEM の暫定適用のいずれを採るかは別途判断する。

> スケール間（30/90/300m）で値の意味を揃えるため、密度系パラメータは面積あたり（/ha）に正規化する。算出には `grid.cell_area_ha()` を使用する。**例外は `POP_DEN_{データソース}`** であり、入力の密度バンドが取得時に楕円体実面積で算出済みであるため、平面セル面積ではなく定数（1 km² = 100 ha）で換算する（同節の該当項目を参照）。

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
| `POP_DEN_{データソース}`, `POP_VALID_RATIO_{データソース}` | `pop_worldpop2020` / `pop_landscan2020` / `pop_landscan2023` テーブル | `params/population.py: compute()` → `params/raster.py: aggregate_mean_and_valid_ratio()`（接尾辞は `run.py: apply_column_suffix()` が付与） | **確定・実装済** |
| `NTL_MEAN`, `NTL_VALID_RATIO` | `ntl_viirs2023` / `ntl_bm2023` テーブル | `params/nightlight.py: compute()` → `params/raster.py: aggregate_mean_and_valid_ratio()` | **確定・実装済** |
| `LULC_WATER_COV`, `LULC_TREE_COV`, `LULC_CROP_COV`, `LULC_BUILT_COV`, `LULC_RANGE_COV`, `LULC_WETLAND_COV`, `LULC_BARE_COV`, `LULC_VALID_RATIO` | `lulc_glc2022` / `lulc_esri2022` テーブル | `params/lulc.py`（未作成）→ 集約経路は後続タスクで確定 | **設計確定・実装未着手** |

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

**単一スケールのテーブルのみを結合する。** `cell_id` は全スケール共通の式（`row * 1000000 + col`）で採番するため、**一意なのは同一スケールのレイヤ内に限られる**（[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7.5.3節）。`--scale` は単一指定に限り、テーブルも同じスケールのディレクトリからのみ読む。

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

**この3点の違いにより、既存の [satellite_only_analysis_results.md](../../03_results/satellite_only_analysis_results.md)（旧経路によるRQ3のベースライン結果）と、新経路で出力したデータセットは統計的に別物であり、直接比較しない。** 格子が一致せずセル単位の対応づけができないため、突合できるとしても分布統計に限られ、投じる作業量に対して得られる根拠が弱いと判断した。既存結果はピクセル単位の先行結果として保持する。新経路での RQ3 再実行は実施済みであり、結果は [satellite_only_analysis_results_cellbased.md](../../03_results/satellite_only_analysis_results_cellbased.md) を参照。
