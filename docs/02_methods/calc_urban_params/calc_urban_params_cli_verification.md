# calc_urban_params CLI・検証

**最終更新**: 2026-08-23
**関連ドキュメント**: [calc_urban_params_guide.md](../calc_urban_params_guide.md)（ハブ・索引）, [calc_urban_params_io_spec.md](calc_urban_params_io_spec.md), [calc_urban_params_processing_design.md](calc_urban_params_processing_design.md)
**前提知識**: [calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 5章・6章、[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7章（処理設計）

> 本ファイルは [calc_urban_params_guide.md](../calc_urban_params_guide.md) の10章・11章を分割したものである。全体の索引・位置づけはハブを参照。

---

## 索引

| 節 | 1行要約 |
|---|---|
| 10.1 算出フェーズ | `python -m src.analysis.urban_params` のCLIオプション |
| 10.2 結合フェーズ | `build_dataset.py` のCLIオプション |
| 10.3 現在の実装状況 | 実装済み・未実装の機能一覧 |
| 11.1 ユニットテスト | `pytest` によるテスト方針 |
| 11.2 旧 wide CSV との値照合（`verify_values.py`） | 旧原点との差異と照合方法 |
| 11.3 QGIS での目視確認 | 結合結果・分布の妥当性確認 |
| 11.4 人口密度・夜間光のCLI検証結果 | 15組み合わせの行数・値域・有効画素率の実測 |
| 11.5 人口密度・夜間光の目視確認（画像保存） | 5列を着色表示し画像として保存、分布の妥当性確認 |
| 11.6 土地被覆クラス別面積率のCLI検証結果 | 6組み合わせの行数・構成比・スケール間挙動・有効画素率の実測 |
| 11.7 土地被覆クラス別面積率の目視確認（画像保存） | 16列を着色表示し画像として保存、分布の妥当性確認 |

---

## 10. CLI仕様

**前提**: 先に正準グリッドを生成しておく（[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7.5.7節）。パラメータテーブルの行集合はこのグリッドを正本とする。

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
- `--params`: 算出するパラメータセット名の一覧（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 5.2.0節）。テーブル名としてそのまま使う
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
- **`params/buildings.py`（`BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX`）**: 設計確定・実装済み。`hanoi_gba_buildings.gpkg`（`build_gba`、GBA、3,071,511 件）から被覆率・棟数密度・平均/最大高さを算出する。件数が多いため、本モジュールのみレイヤの一括読み込みと NumPy によるベクトル化集計を採る。`build_dc`（`merge_DC.gpkg`）は高さ属性を持たないため、高さ列は NaN になる。**高さ2列（`BUILD_H_MEAN` / `BUILD_H_MAX`）の帰属方式は 2026-08 に重心方式単独から重なりベースと重心方式の併用へ変更した**（詳細は [gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md) 3.2節）。
- **`params/elevation.py`（`ELEV_MEAN` / `ELEV_VALID_RATIO`）**: 設計確定・実装済み。FABDEM v1.2（`fabdem_hanoi_dem.tif`、`elev_fabdem`）を coarse グリッドへ平均再投影し、セル平均標高（m）とセル内のDEM有効画素率（0-1）を算出する。`ELEV_COUNT` は出力しない。DEMラスタは `.gitignore` の対象であり、ファイルが無い場合は `FileNotFoundError` で停止する（列が黙って欠けるのを防ぐため）。
- **`params/lst.py`（`LST` / `LST_VALID_RATIO`）**: 設計確定・実装済み。LSTラスタ（`--lst-file`）を coarse グリッドへ平均再投影し、セル平均地表面温度（°C）とセル内のLST有効画素率（0-1）を算出する。目的変数であり `VALID_SATELLITE_MASK` の判定材料には含めない（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.3節）。集約後の有効値の中央値が摂氏として妥当な範囲（-60〜90°C）の外なら警告する（ケルビン取り違えの検知。正常なLSTを弾かない広さに取る）。
- **`params/population.py`（`POP_DEN_{データソース}` / `POP_VALID_RATIO_{データソース}`）**: 設計確定・実装済み。人口グリッド（`worldpop_hanoi_2020.tif` / `landscan_hanoi_{2020,2023}.tif`）の**密度バンド（band 2、人/km²）**を coarse グリッドへ平均再投影し、100 で割ってセル平均人口密度（人/ha）とセル内の有効画素率（0-1）を算出する。`grid.cell_area_ha()` は使わない（理由は [calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節）。3版は列名にデータソース接尾辞が付き（`run.py: apply_column_suffix()`）、同一データセットへ同時に結合できる。カウントバンド（band 1）を誤って指した場合は、バンド説明の照合で警告する（値は出力されるため統計を見ても気づけないため）。
- **`params/nightlight.py`（`NTL_MEAN` / `NTL_VALID_RATIO`）**: 設計確定・実装済み。夜間光ラスタ（`viirs_dnb_hanoi_2023.tif` / `black_marble_vnp46a4_hanoi_2023.tif`）の**主バンド（band 1）**を coarse グリッドへ平均再投影し、セル平均放射輝度（nW·cm⁻²·sr⁻¹）とセル内の有効画素率（0-1）を算出する。放射輝度は面積に比例しない強度量のため面積正規化しない。主バンド以外（`avg_radiance_masked` / `max_radiance` / `ntl_all_angle` / `cf_cvg` 等）を指した場合は、バンド説明の**完全一致**照合で警告する。部分一致では兄弟バンドが主バンドと語を共有するため素通りする。
- **`params/mask.py`（`IN_ANALYSIS_AREA`）**: 設計確定・実装済み。ROI ポリゴンの被覆率が0より大きいセルを1とする。
- **`params/lulc.py`（`LULC_{クラス}_COV` / `LULC_VALID_RATIO`）**: 設計確定・実装済み。土地被覆ラスタ（`glc_fcs30d_hanoi_2022.tif` / `esri_lulc_hanoi_2022.tif`、パラメータセット `lulc_glc2022` / `lulc_esri2022`）の画素値を共通クラス体系（[src/common/lulc_classes.py](../../../src/common/lulc_classes.py)）へ写像し、雪氷を除く7クラスの面積率とセル内有効画素率を算出する。クラスごとの二値マスクを1クラスずつ`Resampling.average`で再投影し、クリップ前の合計を分母に正規化する（詳細は[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7.2節）。データセット（GLC/Esri）の識別は画素値からは行えないため、`RasterResource.class_scheme` の明示的な宣言に依存し、未設定・未知の値は `params/lulc.py: validate_resource()` が入力解決の段階で停止する。`GIS_INDICATOR_MODULES` には加えない（7クラスの和が有効セルで必ず1になるため、`VALID_GIS_MASK` 本来の意味が失われる）。
- 衛星指標・LSTは `INDICES_*.tif` / `LST_*.tif` のバンド説明（衛星指標: NDVI, NDBI, NDWI／LST: LST）から検出・検証する。
- 実行には `fiona`, `pyogrio`, `rasterio`, `shapely`, `pyproj` を含む `environment.yml` 相当の Python 環境が必要である。
- **旧 wide CSV（`data/output/urban_params/*.csv`）は残置する。** 再生成の手段は持たない（旧原点での算出は `verify_values.py` が担う）。

---

## 11. 検証項目（最低限）

- 各スケール（30/90/300m）のパラメータテーブルが、正準グリッドの該当レイヤと**同じ行数**で出力される
- 入力した衛星指標（`NDVI` 等）が出力され、値が妥当な範囲に収まる
- 結合したデータセットの `lon`, `lat` がハノイ近傍範囲に入る
- 同じコマンドを2回実行しても行数が倍にならない（追記経路を持たないこと）
- `BUILD_H_MEAN` / `BUILD_H_MAX` の欠測が GeoPackage の NULL として保持される（新方式では有効高さを持つ建物が1棟も無いセルに限られる想定。詳細は [gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md) 3.4節）
- 衛星指標テーブルが観測日時つきの名前（`idx_20230707_032329` 等）で出力される
- QGIS で正準グリッドのレイヤ（`grid_30m` 等）にベクタレイヤ結合で繋ぎ、`BUILD_COV` で着色表示して分布が妥当である
- GIS由来パラメータ（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節）を追加する際は、被覆率（0-1）・密度（負値なし）・有効カバレッジ内かどうかの確認を、各パラメータのサブIssueで検証項目として追加する

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
  - この件数は算出時に自動で出力される（`run.py: summarize_valid_ratio()`）。`_VALID_RATIO` を**含む**列を対象とするため、`ELEV_VALID_RATIO` や接尾辞つきの `POP_VALID_RATIO_{データソース}` も同時に報告される（末尾一致で判定していた時期は接尾辞つきの列を取りこぼしていた）。min/mean/max だけでは分布の偏りが読めないため、`describe()` とは別に件数を出す
- 結合後のデータセットで `VALID_SATELLITE_MASK` が `NDVI`/`NDBI`/`NDWI` のみから決まり、`LST` の有無で変わらない（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.3節）
- `IN_ANALYSIS_AREA == 1` のセルにおける `LST` 非 NULL 件数を記録する

**人口密度（`POP_DEN_{データソース}` / `POP_VALID_RATIO_{データソース}`）の検証観点**

- `POP_DEN` を100倍した値（人/km²）が、入力データセットの密度統計と整合する。**単位を誤ると値が2桁ずれるが、密度としてはどちらもあり得る大きさになるため、出力を眺めるだけでは気づけない**
- 値 `0` が実測値として保持され、`NaN`（有効画素なし）と区別される
- `POP_VALID_RATIO` が 0-1 に収まり、`POP_DEN` が `NaN` のセルで `0.0` になっている（両列の整合）
- 部分被覆セルの件数をスケール別に記録する。WorldPop は大規模水域を無効画素とするため件数が無視できない
- **スケール間で最大値の挙動を確認する。** 真の集約が成立する入力では集約によりピークが平滑化されて最大値が下がり、内挿にとどまる入力では画素値がそのまま複写されるため変化しない。解像度と解析スケールの関係を、画素数の計算とは独立に出力側から確かめる手段になる

**夜間光強度（`NTL_MEAN` / `NTL_VALID_RATIO`）の検証観点**

- 値域が入力ラスタの主バンド統計と整合する。面積正規化していないこと（強度量であるため）を値の水準で確認する
- 値 `0` が実測値として保持される（Black Marble の `ntl_near_nadir` は ROI 内の最小値が 0.000）
- 全解析スケールで最大値が変化しない（どのスケールでも内挿であることの確認。RQ2 を割り当てない根拠と対応する）
- `NTL_VALID_RATIO` はほぼ定数列（ROI 全域で 1.0）であり、1.0 未満のセルは解析BBox最外周に限られる

**土地被覆クラス別面積率（`LULC_{クラス}_COV` / `LULC_VALID_RATIO`）の検証観点**

- `IN_ANALYSIS_AREA == 1` のセルで7クラスの面積率の合計が1.0である（`np.isclose`。float32の丸めが残るため厳密一致では判定しない）
- 入力ラスタのクラス構成比（写像画素を母数とした画素数比）と、有効セルの面積率の加重平均が同水準である。市街地はソース間で定義差（GLCのImpervious surfacesは人工被覆、Esriの Built areaは建造環境）により値が大きく異なるが、これは実装の誤りではない
- スケール間の挙動がデータセットの画素実寸から予想される特性と整合する。GLCは1セルあたり画素数が少ないため30mで面積率が実質的に0/1の二値へ近づき、90m・300mで中間値が増える。Esriは1セルあたり画素数が多いため30mでも中間値を持つ
- `LULC_VALID_RATIO` の分布（1.0未満・0.5未満の件数）をスケール別に記録する（`run.py: summarize_valid_ratio()` が自動出力する）
- 30mで `LULC_VALID_RATIO == 0` のセル数（寄与画素が1つも無く全クラスNaNになったセル）を記録する。GLCは1セルあたりの画素数が少ないため、この経路で寄与画素ゼロのセルが大量発生しないかが実測リスクである
- 裸地クラスなど、ROI内で0画素のデータセットがあっても列は出力され値が`0.0`になる（列構成をデータで変えていないことの確認）
- 警告（グリッド非重複・全面欠測・`class_scheme` 未設定）が発生しないこと
- `build_dataset.py` の結合が `ValueError: テーブルの種別を判別できません` にならず完走し、`VALID_GIS_MASK` の分布が土地被覆の追加前後で変わらない（`GIS_INDICATOR_MODULES` に含めていないことの確認）

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

正準グリッドと旧グリッドはセルが対応しない（[calc_urban_params_processing_design.md](calc_urban_params_processing_design.md) 7.5.1節）ため、再設計後の出力と旧 CSV をセル単位で照合することはできない。そこで**検証専用に旧BBox原点の `GridSpec` を構築**し、再設計後の算出経路（`PARAM_SETS` による入力解決・io層のキャッシュ・列検証）を通した結果を旧 CSV と全列照合する。`GridSpec` と解析BBoxだけを旧仕様へ差し替える形にしているのは、`compute()` を直接呼ぶだけでは再設計で新たに入った要素を何も検証しないためである。

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

- **NaN 同士は一致として扱う。** 照合対象列（`BUILD_COV` / `BUILD_DEN` / `ROAD_DEN`）の欠測規約が維持されていることを確認する必要があるため（`BUILD_H_MEAN` / `BUILD_H_MAX` は帰属方式変更により照合対象から除外済み。上記「照合対象は建物2種と道路の3列」を参照）
- **旧 CSV の保存精度（float32）へ揃えてから比較する。** 旧 CSV は float32 の値を「float32 として往復できる最短の10進表記」で保存しており、float64 として読むと元の float32 との間に最大で float32 の半 ULP のずれ（値1.0付近で約6e-8、値680付近で約3e-5）が残る。これは算出値の差ではなく表記の丸めによる差である

照合対象は建物2種（`BUILD_COV` / `BUILD_DEN`）と道路の3列とする（2026-08 に建物4列から変更）。標高は旧 CSV の生成後に算出内容が変わっており（`ELEV_VALID_RATIO` が未収録）、値の同一性を問える状態にない。**`BUILD_H_MEAN` / `BUILD_H_MAX` も同じ理由で除外した。** 帰属方式を重心方式単独から重なりベースと重心方式の併用へ変更したため（[gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md) 3.2節）、この2列は旧 CSV と**設計上必ず不一致になる**。照合対象に残すと検証が常に失敗するため、`verify_values.py` の `COMPARED_COLUMNS` から外した。上表（2026-08-12実測）の「全5列一致」は帰属方式変更前の記録であり、`BUILD_H_MEAN` / `BUILD_H_MAX` を含めた最後の完全一致結果として残す。`BUILD_COV` / `BUILD_DEN` は変更していないため、3列照合は引き続き有効である。

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

- `BUILD_H_MEAN` / `BUILD_H_MAX`: NULL は 7,567 セル（19.8%）で、**2列の NULL が完全に一致**する（食い違い0件）。同一の除外条件で動いていることを示す（**この実測は帰属方式変更前（重心方式単独）の記録**。重なりベース化後の300mでは NULL 7,457 セルに変化したが、2列の NULL 完全一致という性質は変更後も維持されている。詳細は [gis_data_buildings.md](../../01_planning/gis_data/gis_data_buildings.md) 3.4節）
- `ELEV_MEAN` が NULL の 12 セルは**すべて `ELEV_VALID_RATIO = 0.0`**（違反0件）。11章の「両列の整合」を満たす
- `IN_ANALYSIS_AREA = 0` は**ちょうど 35 セル**で、すべて ROI 境界上にある。[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.1節の「交差 ⊇ `IN_ANALYSIS_AREA`」と一致する

> **QGIS-MCP の制約**: `add_table_join` は結合を登録するが結合レイヤの参照を解決しないため、`layer.resolveReferences(QgsProject.instance())` を呼ぶまで結合フィールドが現れない。

### 11.4 人口密度・夜間光の CLI 検証結果（2026-08-20）

5つのパラメータセットを3スケールで算出し、15組み合わせすべてを確認した。

```bash
python -m src.analysis.urban_params --city hanoi \
  --params pop_worldpop2020 pop_landscan2020 pop_landscan2023 ntl_viirs2023 ntl_bm2023 \
  --scales 30 90 300
```

**行数**: 30m 3,739,454 / 90m 417,694 / 300m 38,235。3スケールとも既存テーブル（`elev_fabdem`）と一致した。

**値域の整合**: `POP_DEN` を100倍した値が入力データセットの密度統計と一致した。単位換算の妥当性を実データで裏づけている。

| 入力 | 30m の最大値（人/ha） | ×100（人/km²） | [gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.1節 |
|---|---|---|---|
| WorldPop 2020 | 685.655518 | 68,565.6 | 68,565.6 |
| LandScan 2020 | 830.982178 | 83,098.2 | 83,098.2 |
| LandScan 2023 | 969.472900 | 96,947.3 | 96,947.3 |

夜間光も同様に一致した（VIIRS DNB は最大 96.099991 に対し記録 96.100、Black Marble は 213.979843 に対し 213.980、平均 6.72 に対し 6.712）。Black Marble の最小値は 0.000 のままであり、**実測値の0が欠測に落ちていない**ことを確認した。

**集約と内挿の差が最大値の挙動に現れた**（11章の検証観点に対応）。

| 入力 | 30m | 90m | 300m | 解釈 |
|---|---|---|---|---|
| WorldPop 2020 | 685.66 | 680.96 | 671.11 | **減少** — 集約でピークが平滑化される |
| LandScan 2020/2023 | 830.98 / 969.47 | 同左 | 同左 | **不変** — 画素値がそのまま複写される |
| VIIRS DNB | 96.099991 | 96.099991 | 96.099991 | 不変 |
| Black Marble | 213.979843 | 213.979843 | 213.979843 | 不変 |

真の集約が成立するのは WorldPop の 300m だけであるという画素数の計算（[urban_structure_parameters.md](../../01_planning/urban_structure_parameters.md) §1.4）と独立に一致する。

**有効画素率の分布**（`1.0` 未満／`0.5` 未満のセル数の割合）。

| 入力 | 30m | 90m | 300m |
|---|---|---|---|
| WorldPop 2020 | 3.8% / 3.1% | 5.9% / 3.5% | **13.7% / 4.7%** |
| LandScan 2020/2023 | 1.6% / 1.5% | 2.2% / 1.8% | 4.6% / 2.8% |
| VIIRS DNB | 1.0% / 0.9% | 1.7% / 1.2% | 4.8% / 2.5% |
| Black Marble | 1.0% / 0.9% | 1.7% / 1.2% | 4.7% / 2.5% |

WorldPop が一貫して高いのは、大規模水域を無効画素とするためである（無効画素の83%が水域）。300m では 13.7% のセルが部分被覆であり、**`POP_DEN` を「セル全体の平均密度」として読むと過大評価になる**。セル全体を母数とする密度が必要な場合は `POP_DEN × POP_VALID_RATIO` を用いる。

**欠測と警告**: 全15組み合わせで、グリッド非重複・全面欠測・バンド取り違えのいずれの警告も発生しなかった。

> **この検証で発見した不具合**: 当初、人口の有効画素率が上表のように報告されず、夜間光の分だけが出力されていた。`summarize_valid_ratio()` が `_VALID_RATIO` で**終わる**列を対象としており、データソース接尾辞が付いた `POP_VALID_RATIO_WORLDPOP2020` を取りこぼしていたためである。列自体は正常に出力されるため、欠測ではなく「サマリーが出ない」という気づきにくい形で現れた。判定を部分一致へ変更して解消している。

### 11.5 人口密度・夜間光の目視確認（画像保存）（2026-08-22）

11.4節はCLIが出力した値の検証であり、画像保存・目視確認は当時の完了条件に含まれておらず未実施のまま残っていた。11.3節と同じ要領で、正準グリッド `grid_300m` に人口密度3種・夜間光2種のパラメータテーブルをベクタレイヤ結合し、5列（`POP_DEN_WORLDPOP2020` / `POP_DEN_LANDSCAN2020` / `POP_DEN_LANDSCAN2023` / `NTL_MEAN`×VIIRS DNB・Black Marble）を個別に着色表示して確認した。図は `images/urban_params/urban_params_{列名}_hanoi_300m.png` に保存している。夜間光は2データソースで列名（`NTL_MEAN`）を共有するため、ファイル名にデータソース接尾辞（`_viirs` / `_bm`）を付す。

**確認の観点**: 建物被覆率等の既存パラメータとの傾向比較ではなく、**`images/gis_data/population/`・`images/gis_data/nighttime_lights/` の入力データ実測図と分布が対応しているか**を確認した。算出結果（集約後のセル平均値）が入力（元ラスタ）を正しく反映しているかを問う検証であるため。

**分類方式**: 固定閾値・配色。`qgis/styles/population_density.qml`（人口密度、閾値は人/km²単位を人/haへ換算）・`qgis/styles/nighttime_lights_radiance.qml`（夜間光、単位はnW·cm⁻²·sr⁻¹で一致）の配色をそのまま流用し、`QgsRendererRange` を手動構築した。データセット間・実データ画像との比較で同じ色が同じ値を意味するようにするためで、Quantile等の相対分類（分布に応じて境界が変わる）では比較にならない。

この過程で、分類走査を伴う `QgsGraduatedSymbolRenderer.createRenderer(mode=Quantile)` の直接呼び出しでQGIS本体が応答不能になる事例に遭遇した。回避策・詳細は[qgis_operation_guidelines.md](../qgis_operation_guidelines.md#グラフィカルな属性分類quantile等でのクラッシュ)に記録した。

**枠線**: 既定のシンボルはセル境界に枠線が付き、300mグリッドの細かいセルでは枠線の黒がセル自体の塗り色（特に低い値の暗い色）を覆って濃く見えてしまう。枠線を`NoPen`にして解消した。

| 確認項目 | 結果 |
|---|---|
| 入力データ実測図との分布対応 | 5図とも `images/gis_data/` の実測図（`population_worldpop_hanoi_2020.png` 等）と同じ空間パターン（都心集中・道路沿いの帯状分布・周辺部の低密度）を再現している |
| WorldPop と LandScan の300m集約後の見え方の違い | 元解像度の実測図（[gis_data_population.md](../../01_planning/gis_data/gis_data_population.md) 6.6節）では都心集中がLandScanの方がWorldPopより急峻だが、300m集約図では逆にLandScanの高い値の面積がWorldPopより広く見える。矛盾ではなく、11.4節の「集約と内挿の差」に対応する現象である。WorldPopは300mへの真の集約でピークが平滑化される（減少）のに対し、LandScanは1kmという粗い元解像度のため300mでも実質的に内挿（画素値がそのまま複写）となり、都心の高い値が面的にそのまま広がって見える |
| VIIRS DNB と Black Marble の違い | 両者とも都心に高輝度エリアが集中し、分布パターンはおおむね一致する（主バンド間の高い相関 Pearson r=0.976 と整合する。[gis_data_nighttime_lights.md](../../01_planning/gis_data/gis_data_nighttime_lights.md) 5.3節） |

ユーザー・Claude双方で目視確認済み。

### 11.6 土地被覆クラス別面積率の CLI 検証結果（2026-08-23）

```bash
python -m src.analysis.urban_params --city hanoi --params lulc_glc2022 lulc_esri2022 --scales 30 90 300
```

**行数**: 30m 3,739,454 / 90m 417,694 / 300m 38,235。3スケールとも既存テーブル（`elev_fabdem`）と一致した。

**値域と構成制約**: 全スケール・全列で面積率は0-1に収まった。`IN_ANALYSIS_AREA == 1` のセルで7クラスの面積率合計が `np.isclose` で1.0と一致することを確認した（実装が「構成として」保証する性質であり、単体テスト・CLI実測の双方で崩れていない）。

**入力ラスタのクラス構成比との整合**（30m、写像画素を母数とした画素数比 vs 有効セルの面積率の加重平均）。

| クラス | GLC 画素数比 | GLC 面積率(mean) | Esri 画素数比 | Esri 面積率(mean) |
|---|---|---|---|---|
| 農地 | 65.56% | 65.52% | 41.99% | 41.95% |
| 市街地 | 19.99% | 19.95% | 39.27% | 39.22% |
| 樹林 | 6.68% | 6.71% | 7.85% | 7.87% |
| 水域 | 5.50% | 5.54% | 9.63% | 9.70% |
| 湿地 | 1.77% | 1.78% | 0.06% | 0.06% |
| 草地・低木 | 0.50% | 0.50% | 1.04% | 1.04% |
| 裸地 | 0.00% | 0.00% | 0.15% | 0.15% |

いずれも画素数比と面積率の加重平均が同水準であり、集約が入力のクラス構成を正しく反映していることを確認した。**市街地はソース間で 20.0% 対 39.2% と大きく異なる**が、これは[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節が述べる定義差（GLCの Impervious surfacesは人工被覆、Esriの Built areaは建造環境）の現れであり、実装の誤りではない。

**スケール間の挙動**（`LULC_BUILT_COV` が1画素でも市街地を含むセルのうち、値が中間（0.05-0.95）であるセルの割合）。セル全体（値0のセルを含む）で割合を取ると、市街地が存在しないセルが多数を占めて指標が支配されてしまうため、母数を「市街地が存在するセル」に絞った。

| データセット | 30m | 90m | 300m |
|---|---|---|---|
| GLC | 43.4% | 67.5% | 69.2% |
| Esri | 16.9% | 37.6% | 66.9% |

両データセットとも、スケールが粗くなるほど中間値の割合が増える。**Esriは30mでも中間値を持ち**（0%ではない）、[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節が述べる「Esriは30mでも真の集約が成立する」というスケール特性の差と整合する。**ただし、GLCとEsriの相対比較では、1セルあたり画素数が少ないGLCの方が中間値の割合が高いという、画素実寸のみからの単純な予測（画素数が少ないほど二値化しやすい）とは逆の結果になった。** 市街地クラスの境界形状・GLC_FCS30D自体の分類過程（30m解像度での分類に伴う平滑化の可能性）が影響していると考えられるが、本検証（市街地クラス・単一都市）だけでは原因を特定できない。GLC/Esriの二値化傾向の優劣を主張する根拠としては使わず、両データセットともスケールとともに中間値が増えるという共通傾向の確認にとどめる。

**`LULC_VALID_RATIO` の分布**（1.0未満・0.5未満のセル数の割合、`run.py: summarize_valid_ratio()` の自動出力）。

| データセット | 30m | 90m | 300m |
|---|---|---|---|
| GLC | 0.6% / 0.3% | 2.2% / 0.8% | 8.6% / 2.5% |
| Esri | 0.6% / 0.3% | 2.0% / 0.8% | 7.3% / 2.4% |

**30mで `LULC_VALID_RATIO == 0` のセル数**（寄与画素が1つも無く全クラスNaNになったセル）: GLC 1,893件（0.0506%）、Esri 697件（0.0186%）。GLCは1セルあたり1.08画素と実測リスクとして最も懸念していた条件だが、大量発生には至らなかった。GLCはFABDEMとtransformが完全一致（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節）で`ELEV_VALID_RATIO`の30m実測が破綻していないことと整合する。

**裸地クラス**: GLCは全セル`0.0`（mean/maxとも0.0）、Esriは`0.0`以外を持つセルが存在する（mean 0.0015、max 1.0）。列構成をデータで変えていないことを確認した。

**欠測と警告**: 6組み合わせ（2データセット×3スケール）すべてで、グリッド非重複・全面欠測・`class_scheme`未設定の警告はいずれも発生しなかった。

**結合フェーズへの影響確認**:

```bash
# 基準（土地被覆なし）
python -m src.analysis.build_dataset --city hanoi --scenario limited --scale 300
# 土地被覆あり
python -m src.analysis.build_dataset --city hanoi --scenario limited --tables lulc_glc2022 --scale 300 --name limited_with_lulc
```

結合は `ValueError: テーブルの種別を判別できません` にならず完走した（`lulc_glc2022` が `PARAM_SETS` 経由で読み飛ばし側へ分岐している）。`VALID_GIS_MASK` の分布は追加前後で完全に一致した（`0` が4,101セル・`1` が34,134セルで同一）。`GIS_INDICATOR_MODULES` に `lulc` を加えていないことの効果を実データで確認した。

**個別セル単位の検算**: 上記はいずれもROI全体の統計・分布での確認であり、個々のセルの値が元ラスタと対応しているかは別途確認が必要である（レビュー時の指摘）。GLC 30mの1セル（`cell_id=7598001935`、都心近郊、`LULC_BUILT_COV`が中間的な値を持つセルを選定）について、2種類の経路で確認した。

1. **元ラスタからの画素カウント（クロスチェック）**: `rasterio` でセル範囲を直接切り出し、`build_class_lookup()` で写像してクラスごとに画素を数えた。算出パイプラインの再投影・集約ロジックは経由しないが、写像表自体は本番と共通の `build_class_lookup()` を使うため、写像表そのものの不具合は検出できない。結果は水域14.4%・農地56.1%・市街地29.5%となり、本番出力（水域17.7%・農地51.8%・市街地30.5%）との差は3〜4ポイントに達した。原因を調べたところ、GLCの画素（約28.0m×29.8m）は300mグリッドの正確な約数でないため、**手動で切り出した矩形はセル境界をまたぐ画素を完全カウントしてしまい**、`Resampling.average` による実際の面積按分とはズレる。これは検算方法自体の限界であり、実装の誤りではない
2. **単セル再実行による一貫性確認**: `aggregate_class_fractions_to_grid()`（本番と同一の関数）を、対象セルの範囲だけを覆う1x1の `GridSpec` で呼び出し、本番実行（38,235セル一括処理）の出力と突き合わせた。差は水域0.14ポイント・農地0.32ポイント・市街地0.18ポイントで、樹林・草地低木・湿地・裸地は完全一致した。差は浮動小数点の丸め・グリッド原点の微差の範囲に収まる

方法1では矩形切り出しと再投影の境界処理差を確認した。方法2では一括実行と単セル実行の出力整合性を確認した。集約アルゴリズムそのものの独立検証（写像表・集約ロジックの双方を本番実装から切り離した参照実装との突き合わせ）は今回行っていない。

### 11.7 土地被覆クラス別面積率の目視確認（画像保存）（2026-08-23）

正準グリッド `grid_300m` に `lulc_glc2022` / `lulc_esri2022` をそれぞれベクタレイヤ結合し、7クラス＋`LULC_VALID_RATIO`の全16列（2データセット×8列）を個別に着色表示して確認した。図は `images/urban_params/lulc/urban_params_lulc_{列名}_{ソース}_hanoi_300m.png` に保存している。他パラメータの図が `images/urban_params/` 直下にフラット配置なのに対し、LULCは16枚と枚数が多いため `lulc/` サブディレクトリへ集約する（ユーザー判断）。

**分類方式**: 固定閾値・共通クラスの代表色。列ごとに共通クラス体系の代表色（水域=青、樹林=緑、農地=黄、市街地=赤、草地低木=橙、湿地=青緑、裸地=茶、`LULC_VALID_RATIO`=灰）を割り当て、白から代表色へのグラデーションで塗り分けた。代表色は `qgis/styles/lulc_glc_fcs30d.qml` の主要クラス配色に準拠する。生成はヘッドレスPyQGIS（`QgsGraduatedSymbolRenderer` を手動構築）で行った。

> **初版のレビューで指摘を受けて配色を改訂した。** 白から代表色への単純な線形補間では、農地（`#ffff64`）・草地低木（`#ffb432`）のように明度の高い代表色で0.0-0.2と0.8-1.0の差が判別しづらかった。終点の代表色をあらかじめHSVの明度で0.5以下に制限してから補間することでコントラストを強め、7クラスの面積率列は5段階均等閾値（0.0-0.2/…/0.8-1.0）のまま視認性を改善した。`LULC_VALID_RATIO` は実データが96.5%のセルで0.8-1.0に集中するため（11.6節）、均等閾値では判別できず、上位を細分化した非線形閾値（0.0-0.5/0.5-0.8/0.8-0.9/0.9-0.95/0.95-1.0）へ変更した。

> **ヘッドレス生成時の注意（ROIレイヤの塗り重なり）**: 段彩を `grid_layer` に設定したにもかかわらず、生成した図が意図しない単色（実行のたびに異なるランダム色）で塗りつぶされる事象が発生した。原因は `src/visualization/qgis_figure.py: style_roi_outline()` の呼び出し漏れで、ROIレイヤがデフォルトの不透明な塗りつぶしシンボルのまま `data_layer` の**上**に重なって描画されていた（`_add_map()` はROIを上・データを下の順で描画する）。ROIレイヤは必ず `style_roi_outline()` で「塗りなし・外枠のみ」にしてから渡すこと。

| 確認項目 | 結果 |
|---|---|
| 入力データ実測図との分布対応 | 16図とも `images/gis_data/lulc/` の実測図（`lulc_glc_fcs30d_hanoi.png` / `lulc_esri_10m_hanoi.png`）と対応する空間パターンを再現している。`LULC_WATER_COV` では紅河が明瞭な帯として現れ、11.3節の「紅河の位置が独立に一致する」という確認方法と同様に結合の空間的正しさを裏づける |
| `LULC_BUILT_COV` の都心集中 | GLC・Esriとも都心部で値が高く、周辺部で低い。Esriは全体的に赤みが強く、11.6節のクラス構成比（市街地 GLC 20.0% / Esri 39.2%）と整合する |
| `LULC_TREE_COV` の空間分布 | ハノイ西部・南部の山地・丘陵地に集中し、平野部中心では低い。土地被覆としての樹林の実際の立地と整合する |
| `LULC_BARE_COV`（GLC） | 全セル最も薄い色（0.0-0.2）で塗られる。**配色の問題ではなく実データがそうである**（CLI実測で全セル`0.0`。GLCの写像表に裸地画素が存在しない） |
| `LULC_BARE_COV`（Esri） | ほぼ全域が最も薄い色だが、左上（三峰山系付近）と中央に少数のセルで濃い階級が現れる。実データで非ゼロは38,223セル中384件（1.0%）のみであり、300mグリッド上では点在する程度にしか見えないのが実態である |
| `LULC_VALID_RATIO` | 非線形閾値でもなお、ほぼ全域が最上位階級（0.95-1.0）で塗られる。**配色の問題ではなく実データがそうである**（30mで有効画素率1.0未満のセルはGLC 0.6%・Esri 0.6%と少数、300mでも96.5%が0.8-1.0に収まる。11.6節） |
| `LULC_BUILT_COV` と `BUILD_COV` の大小関係 | `LULC_BUILT_COV ≥ BUILD_COV` が一般に成り立つという[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節の記述を、`build_gba` テーブルとの突き合わせで確認した。GLCは違反（`LULC_BUILT_COV < BUILD_COV`）が38,214セル中7,707件（20.2%）、Esriは38,223セル中4,139件（10.8%）で残るが、差の平均はGLC +0.12・Esri +0.31とLULC側が明確に高く、違反セルでの逆転幅も平均−0.01程度とわずかである。「一般に成り立つ」（常に成り立つではない）という記述と整合する |

ユーザー・Claude双方で目視確認済み。
