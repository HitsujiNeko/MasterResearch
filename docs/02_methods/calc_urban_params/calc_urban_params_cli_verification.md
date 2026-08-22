# calc_urban_params CLI・検証

**最終更新**: 2026-08-22
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
- **`params/buildings.py`（`BUILD_COV` / `BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX`）**: 設計確定・実装済み。`hanoi_gba_buildings.gpkg`（`build_gba`、GBA、3,071,511 件）から被覆率・棟数密度・平均/最大高さを算出する。件数が多いため、本モジュールのみレイヤの一括読み込みと NumPy によるベクトル化集計を採る。`build_dc`（`merge_DC.gpkg`）は高さ属性を持たないため、高さ列は NaN になる。
- **`params/elevation.py`（`ELEV_MEAN` / `ELEV_VALID_RATIO`）**: 設計確定・実装済み。FABDEM v1.2（`fabdem_hanoi_dem.tif`、`elev_fabdem`）を coarse グリッドへ平均再投影し、セル平均標高（m）とセル内のDEM有効画素率（0-1）を算出する。`ELEV_COUNT` は出力しない。DEMラスタは `.gitignore` の対象であり、ファイルが無い場合は `FileNotFoundError` で停止する（列が黙って欠けるのを防ぐため）。
- **`params/lst.py`（`LST` / `LST_VALID_RATIO`）**: 設計確定・実装済み。LSTラスタ（`--lst-file`）を coarse グリッドへ平均再投影し、セル平均地表面温度（°C）とセル内のLST有効画素率（0-1）を算出する。目的変数であり `VALID_SATELLITE_MASK` の判定材料には含めない（[calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.3節）。集約後の有効値の中央値が摂氏として妥当な範囲（-60〜90°C）の外なら警告する（ケルビン取り違えの検知。正常なLSTを弾かない広さに取る）。
- **`params/population.py`（`POP_DEN_{データソース}` / `POP_VALID_RATIO_{データソース}`）**: 設計確定・実装済み。人口グリッド（`worldpop_hanoi_2020.tif` / `landscan_hanoi_{2020,2023}.tif`）の**密度バンド（band 2、人/km²）**を coarse グリッドへ平均再投影し、100 で割ってセル平均人口密度（人/ha）とセル内の有効画素率（0-1）を算出する。`grid.cell_area_ha()` は使わない（理由は [calc_urban_params_io_spec.md](calc_urban_params_io_spec.md) 6.4節）。3版は列名にデータソース接尾辞が付き（`run.py: apply_column_suffix()`）、同一データセットへ同時に結合できる。カウントバンド（band 1）を誤って指した場合は、バンド説明の照合で警告する（値は出力されるため統計を見ても気づけないため）。
- **`params/nightlight.py`（`NTL_MEAN` / `NTL_VALID_RATIO`）**: 設計確定・実装済み。夜間光ラスタ（`viirs_dnb_hanoi_2023.tif` / `black_marble_vnp46a4_hanoi_2023.tif`）の**主バンド（band 1）**を coarse グリッドへ平均再投影し、セル平均放射輝度（nW·cm⁻²·sr⁻¹）とセル内の有効画素率（0-1）を算出する。放射輝度は面積に比例しない強度量のため面積正規化しない。主バンド以外（`avg_radiance_masked` / `max_radiance` / `ntl_all_angle` / `cf_cvg` 等）を指した場合は、バンド説明の**完全一致**照合で警告する。部分一致では兄弟バンドが主バンドと語を共有するため素通りする。
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

11.4節はCLIが出力した値の検証であり、画像保存・目視確認は未実施のまま残っていた（#256完了条件の記載漏れ）。11.3節と同じ要領で、正準グリッド `grid_300m` に人口密度3種・夜間光2種のパラメータテーブルをベクタレイヤ結合し、5列（`POP_DEN_WORLDPOP2020` / `POP_DEN_LANDSCAN2020` / `POP_DEN_LANDSCAN2023` / `NTL_MEAN`×VIIRS DNB・Black Marble）を個別に着色表示して確認した。図は `images/urban_params/urban_params_{列名}_hanoi_300m.png` に保存している。夜間光は2データソースで列名（`NTL_MEAN`）を共有するため、ファイル名にデータソース接尾辞（`_viirs` / `_bm`）を付す。

**確認の観点**: 建物被覆率等の既存パラメータとの傾向比較ではなく、**`images/gis_data/population/`・`images/gis_data/nighttime_lights/` の入力データ実測図と分布が対応しているか**を確認した。算出結果（集約後のセル平均値）が入力（元ラスタ）を正しく反映しているかを問う検証であるため。

**分類方式**: 固定閾値・配色。`qgis/styles/population_density.qml`（人口密度、閾値は人/km²単位を人/haへ換算）・`qgis/styles/nighttime_lights_radiance.qml`（夜間光、単位はnW·cm⁻²·sr⁻¹で一致）の配色をそのまま流用し、`QgsRendererRange` を手動構築した。データセット間・実データ画像との比較で同じ色が同じ値を意味するようにするためで、Quantile等の相対分類（分布に応じて境界が変わる）では比較にならない。

この過程で、分類走査を伴う `QgsGraduatedSymbolRenderer.createRenderer(mode=Quantile)` の直接呼び出しでQGIS本体が応答不能になる事例に遭遇した。回避策・詳細は[qgis_operation_guidelines.md](../qgis_operation_guidelines.md#グラフィカルな属性分類quantile等でのクラッシュ)に記録した。

**枠線**: 既定のシンボルはセル境界に枠線が付き、300mグリッドの細かいセルでは枠線の黒がセル自体の塗り色（特に低い値の暗い色）を覆って濃く見えてしまう。枠線を`NoPen`にして解消した。

| 確認項目 | 結果 |
|---|---|
| 入力データ実測図との分布対応 | 5図とも `images/gis_data/` の実測図（`population_worldpop_hanoi_2020.png` 等）と同じ空間パターン（都心集中・道路沿いの帯状分布・周辺部の低密度）を再現している |
| WorldPop と LandScan の違い | WorldPop（居住人口）は都心により鋭く集中し、LandScan（実効人口）は業務エリア等を含みより広い範囲で高い値が分布する。人口概念の差として妥当な現れ方であり、実測図の違いとも一致する |
| VIIRS DNB と Black Marble の違い | 両者とも都心に高輝度エリアが集中し、分布パターンはおおむね一致する（11.4節の主バンド間の高い相関 r=0.976 と整合する） |

ユーザー・Claude双方で目視確認済み。
