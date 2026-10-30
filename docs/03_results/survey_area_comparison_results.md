# ハノイ都心部（測量GIS範囲）と全域の分析結果の比較（Satellite Only・Limited）

**最終更新**: 2026-10-30  
**関連ドキュメント**: [limited_analysis_results.md](limited_analysis_results.md) 8章, [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md), [analysis_workflow.md](../02_methods/analysis_workflow.md) 5.3.3節, [calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.6節, [calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節, [observation_selection.md](../02_methods/observation_selection.md) 7.6節・8章・9.1節, [research_guide.md](../01_planning/research_guide.md)  
**前提知識**: Satellite Only・Limited の処理条件（両結果ドキュメントの3節）、Spatial CV のブロック定義、共通評価セルと補正 t 区間（analysis_workflow.md 5.3.3節）  
**対象RQ**: RQ2（解析範囲による関係の変化）・RQ3（データ制約下での有効性評価）

---

## 0. 要旨（全域との違い）

ハノイ都心部（測量GIS範囲・約100 km²）に絞った結果を、山地・農地・郊外を含む ROI 全域の結果と比べた。観測・格子・乱数シード・サンプル数・検証方法はそろえている。**主採用の観測 `2022-09-06T03:23:58Z`（032358）での結果を7章に、旧採用の観測 `2023-07-07T03:23:05Z`（032305）での結果を2〜5章に記録する。** 観測が異なるため、LST の絶対値と °C の誤差は観測をまたいで比べない（1章・7.7節）。

### 主採用の観測（032358・7章）

全域ランは主結果を再現している（7.2節）。違いは次の5点にまとめられる。

1. **都心部は暑く、温度差も大きい。** LST の平均は全域 32.2°C に対し 34.9°C、標準偏差は 2.6°C に対し 3.6°C である。032305 と同じ向きである（7.3節）
2. **R² は上がるが、予測誤差は下がらない。** 衛星指標だけのモデルの Spatial CV の RMSE は、RF で 1.33°C → 1.39°C、線形で 1.49°C → 1.60°C とむしろ増える。公開GISを加えたモデルも RF は 1.05°C → 1.10°C とほぼ変わらず、線形だけが 1.27°C → 1.14°C に下がる。032305 では公開GISを加えたモデルの RF の誤差が都心部で下がっていたが、主採用の観測ではこの向きは再現しなかった（7.4節・7.7節）
3. **同じセル・同じ分割で比べると、都心部でも公開GISを加える効果ははっきり正である。** 共通評価セルで20シード反復した結果、Limited は Satellite Only より誤差（RMSE）が RF で 0.29°C（補正 t 区間 [0.19, 0.39]）、線形で 0.46°C（同 [0.33, 0.60]）小さく、100個の fold すべてで上回った。全域（RF 0.25°C・線形 0.19°C）と比べると、線形では都心部の効果がはっきり大きい。RF では °C の差は都心部のほうがやや大きいが、LST の標準偏差で割るとむしろ小さく、範囲による違いは明確でない（7.6節）
4. **効く要因の顔ぶれが変わる。** 全域では `NDBI` が1位・標高が4位だが、都心部では建物被覆率（`LULC_BUILT_COV`）が1位に上がり、標高は7位に下がる。標高が下がるのは都心部の標高がほぼ一定なためである。032305 と同じ向きである（7.5節）
5. **都心部の結果は不確かさが大きい。** 検証用の空間ブロックは24個で、R² の fold 間の標準偏差は Limited で全域の約4〜12倍ある。標本の引き直しと fold の組み方の違いで、Satellite Only の RF の R² は 0.83 から 0.77 に下がる（RMSE はほぼ同じ）。都心部の比較は R² ではなく RMSE で行う（7.4節・7.8節）

この主採用の観測での都心部の結果（7章）が、測量GISを加える Full シナリオと比べるときの基準になる。

### 旧採用の観測（032305・2〜5章）

Limited の全域ランは既存のラン12・13 を数値まで再現している（3.3節）。Satellite Only の全域ランは、既存結果と指標の世代が異なり直接比較できないため、本比較の基準として新たに取ったものである（3.1節）。違いは次の5点にまとめられる。

1. **都心部は暑く、温度差も大きい。** LST の平均は全域 35.5°C に対し 37.8°C、標準偏差は 2.5°C に対し 3.7°C である。「都心部は均質で温度差が小さい」という事前の想定とは逆だった（4.1節）
2. **R²（当てはまりの良さ）は見かけ上上がるため、誤差（RMSE）で比べた。** 衛星指標だけのモデルは R² が上がる（RF 0.63 → 0.84）が、予測誤差はほぼ変わらない（1.52°C → 1.46°C。線形は 1.80°C のまま）。都心部で衛星指標だけの説明力が高まったわけではない。公開GISを加えたモデルは、誤差が実際に下がる（RF 1.24°C → 1.12°C）（4.2節・5.1節）
3. **公開GIS（建物・人口・夜間光等）を加える効果は、都心部のほうが大きい。** 衛星指標だけのモデルからの誤差の減少は、線形で全域 −0.32°C に対し都心部 −0.57°C である。母数がわずかに異なるため参考値である（5.2節）
4. **効く要因の顔ぶれが変わる。** 全域では衛星から見た市街地らしさ（`NDBI`）が1位、標高が4位だが、都心部では建物被覆率・人口密度・`NDBI`・夜間光が上位を占める。標高が外れるのは都心部に山が無く標高がほぼ一定なためであり、「都心では標高が効かない」という意味ではない（4.3節・5.3節）
5. **都心部の結果は不確かさが大きい。** 検証用の空間ブロックは24個にとどまり（全域は約500個）、事前の判定基準は満たしたが、分割ごとの結果のばらつき（R² の fold 間の標準偏差）は、Limited で全域の約4倍ある（3.5節・5.5節）

都心部の温度差が大きい理由（密集市街地と水域の混在）は分布の要約値からの推測であり、地図での確認はしていない（**未確認**）。032305 の結果は Full シナリオの基準には使わない（1章）。

---

## 1. 位置づけ

Full シナリオ（測量GISを追加）は測量GISのある範囲でしか成立しない。一方、既存の Satellite Only・Limited の結果は ROI 全域で得たものであり、そのまま Full と並べると「データの違い」と「範囲の違い」が混ざる。本ドキュメントは、**Satellite Only・Limited を測量GIS範囲に絞って回し直し、同じデータセットから回した全域の結果と比べる**ことで、範囲の違いだけによる差を切り分ける。ここで得た測量GIS範囲の結果は、Full シナリオと比較するときの基準になる。

**本ドキュメントは2つの観測の結果を記録する。2〜5章は旧採用の観測 `2023-07-07T03:23:05Z`（032305）、7章は主採用の観測 `2022-09-06T03:23:58Z`（032358）による。** 主採用が変わった経緯は [observation_selection.md](../02_methods/observation_selection.md) 8章にある。**Full シナリオと比べる基準は7章の結果とする。** 2〜5章と7章の数値は観測（日時・LST の分布）が異なるため、LST の絶対値・°C の誤差を直接比べない。比べるのは、変数の重要度の順位、LST の標準偏差で割った誤差、全域との差の向きに限る（7.7節）。7章の全域ランは、032358 の全域の主結果（[limited_analysis_results.md](limited_analysis_results.md) 8章・[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 7章）を再現している（7.2節）。

**本ドキュメントの「測量GIS範囲」の結果は、ハノイ都心部に絞った分析結果である。** 山地・農地・郊外を含む ROI 全域の結果とは、対象とする地域の性格が異なる（4節）。

**有効カバレッジを ROI と同一視しない。** 本ドキュメントでいう「測量GIS範囲」は `IN_ANALYSIS_AREA_SURVEY = 1` のセル（30m で 111,448 セル・約100 km²）であり、ROI の解析対象域（`IN_ANALYSIS_AREA = 1`）の約3%にあたるハノイ都心部である。結果 JSON の `analysis_area`（`"roi"` / `"survey"`）と `required_mask_columns` に、どちらの範囲で絞ったかが記録されている。

### 1.1 数値の正本

本節は2〜5章（032305）の数値の正本である。7章（032358）の正本は7.1節に示す。数値は次の2ディレクトリのファイルを正本とする。いずれも Git 管理下にある（サンプルCSV `*_sample_*.csv` と実行ログ `logs/*.log` のみ管理外）。ファイルの種別（`_results.json`・`_feature_importance.csv`・`_shap_importance.csv`・`_spatial_cv_folds.csv`）は両結果ドキュメントの1.1節と同じである。

| シナリオ | 構成 | 全域（roi）の接頭辞 | 測量GIS範囲（survey）の接頭辞 |
|---|---|---|---|
| Satellite Only | NDVI・NDBI・NDWI | `dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m` | 左に `_area_survey` を付けたもの |
| Limited | 採用構成（Limited のラン13・`--water-index none`） | `dataset_limited_masksurvey_20230707_032305_hanoi_30m_both_bh_mean_wi_none` | 同上 |
| Limited | 水指数 `ndwi`（Limited のラン12） | `dataset_limited_masksurvey_20230707_032305_hanoi_30m_both_bh_mean` | 同上 |

- Satellite Only: `data/output/satellite_only_cellbased/20230707_032305_area_comparison/`
- Limited: `data/output/limited/20230707_032305_area_comparison/`

**全域ランと測量GIS範囲ランを同じディレクトリに置いている。** 出力名は範囲が `roi` のとき何も付けず、それ以外のとき末尾に `_area_{範囲}` を付ける規則（`src.common.analysis_dataset.analysis_area_output_part`）で区別している。データセット名の `masksurvey` は「`mask_survey` テーブルを結合した」の意であり、範囲を表すものではない。

---

## 2. 実施したこと

1. `mask_survey` を結合したデータセットを2つ新たに生成した（既存のデータセットは上書きしていない）
2. 6ランを実行した（2シナリオ・3構成 × 2範囲）
3. 全域の Limited 2ランで既存結果の再現を確認してから、測量GIS範囲のランに進んだ（3.3節）
4. 測量GIS範囲で Spatial CV のブロックが十分かを、実行前に固定した基準で判定した（3.5節）

データセットの生成コマンド:

```bash
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited --tables idx_20230707_032305 lst_20230707_032305 mask_survey --name limited_masksurvey_20230707_032305
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20230707_032305 lst_20230707_032305 mask_survey --name satellite_only_masksurvey_20230707_032305
```

分析の実行コマンド（`{area}` は `roi` / `survey`、`{wi}` は `none`（ラン13相当）/ `ndwi`（ラン12相当））。既定値と同じ値も、将来の既定変更に備えてすべて明示している:

```bash
python -m src.analysis.analysis_rq3_satellite_only --dataset-path data/output/datasets/dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m.gpkg --output-dir data/output/satellite_only_cellbased/20230707_032305_area_comparison --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --analysis-area {area}
python -m src.analysis.analysis_rq3_limited --dataset-path data/output/datasets/dataset_limited_masksurvey_20230707_032305_hanoi_30m.gpkg --output-dir data/output/limited/20230707_032305_area_comparison --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --variable-set both --building-height mean --population-source worldpop2020 --water-index {wi} --analysis-area {area}
```

6ランとも同一のコミットから実行し、結果 JSON の `provenance.git.dirty` はいずれも `false` である。

---

## 3. データと処理条件

### 3.1 入力テーブルの前提

- **`idx_20230707_032305`** は新世代（ROI でクリップ済み・MNDWI 列あり）であり、Limited のラン12〜15 と同じテーブルである（[limited_analysis_results.md](limited_analysis_results.md) 1.4節）
- **`lst_20230707_032305`** は LST の雲マスクに Cirrus・Snow を加える変更より前に生成したテーブルを、再生成せずに使っている。雲マスク変更後の再探索で、採用観測 2023-07-07T03:23:05 の有効画素率・LST 統計量は変更前とすべて一致したと記録されているため（[observation_selection.md](../02_methods/observation_selection.md) 7.6節）、影響はない見込みである。テーブル自体を作り直して突き合わせてはいない
- **`mask_survey`** は CS の図郭内枠から定義した有効域によるもので、30m で `IN_ANALYSIS_AREA_SURVEY = 1` が 111,448 セルである（[calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節）。今回のデータセットでも同数であることを確認した

**Satellite Only の全域ランは、既存の Satellite Only 結果（[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md)）とは数値を直接比較しない。** 既存結果は旧世代の指標から作ったデータセットに基づき、再生成しても再現できないためである（同ドキュメント3.1節）。本ドキュメントの比較では、新データセットの全域ランを基準として新たに取った。

### 3.2 範囲の絞り込みと境界セルの扱い

- 全域ランは従来どおり `IN_ANALYSIS_AREA == 1` で、測量GIS範囲ランはさらに `IN_ANALYSIS_AREA_SURVEY == 1` で絞る。それ以外のフィルタ条件（`LST_VALID_RATIO >= 0.5`・非NULL要求の列・Limited の人口/夜間光の有効域品質列）は両範囲で同じである
- **境界にかかる部分被覆セルは除外せず、そのまま使う。** `IN_ANALYSIS_AREA_SURVEY = 1` は「セル内の fine ピクセル中心が1つでも有効域に入る」ことを意味するため境界セルを含むが、30m での面積換算の超過は約0.4%にとどまる（[calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.6節）。境界セルの被覆率を表す列の追加は、この大きさに見合わないと判断した
- **90m・300m で使う場合は再検討が要る。** 超過は 90m で約1.8%、300m で約8% に広がる（[calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節）

### 3.3 全域ランによる再現確認（Limited）

データセットの再生成で結果がずれていないことを、測量GIS範囲のランより前に次の3基準で確認した（1つでも満たさなければ測量GIS範囲のランに進まない、と実行前に決めていた）。既存結果は `data/output/limited/20230707_032305_water_index/` のラン12・13 である。

| 基準 | ラン13相当（`none`） | ラン12相当（`ndwi`） |
|---|---|---|
| フィルタ後の母数が 3,274,657 で一致 | 一致 | 一致 |
| 10万件サンプルの `cell_id` 集合が既存のサンプルCSVと一致 | 100,000件すべて共通 | 100,000件すべて共通 |
| Spatial CV の R²（線形・RF）が小数4桁で一致 | 0.6439・0.7531（6桁まで一致） | 0.6496・0.7604（6桁まで一致） |

全域ランは既存のラン12・13 を再現している。したがって本ドキュメントの全域と測量GIS範囲の差は、範囲の違いによるものとして読める。

### 3.4 サンプル数と抽出率

| ラン | フィルタ後の母数 | サンプル数 | 抽出率 |
|---|---:|---:|---:|
| Satellite Only・全域 | 3,317,260 | 100,000 | 3.0% |
| Satellite Only・測量GIS範囲 | 111,446 | 100,000 | 89.7% |
| Limited・全域 | 3,274,657 | 100,000 | 3.1% |
| Limited・測量GIS範囲 | 110,534 | 100,000 | 90.5% |

- **測量GIS範囲の母数は10万件を上回ったため、実際に10万件を抽出している。** 抽出率は全域（約3%）と測量GIS範囲（約90%）で大きく異なる。測量GIS範囲のサンプルはほぼ全数に近い
- 母数はいずれも測量GIS範囲のセル数（111,448）以下に収まっている。Limited が Satellite Only より約900セル少ないのは、人口・夜間光の有効域品質列で絞られるためである
- 測量GIS範囲では LST の欠測による脱落がほとんどない（`mask_passed` から `feature_complete` までで Satellite Only は2セル、Limited も2セルの脱落）。全域では雲域等により約40万セルが脱落する

### 3.5 Spatial CV のブロックの判定

ブロック長 2,700m・5分割は全域と同じにした。測量GIS範囲は約100 km² と狭く、ブロック数が少なすぎると fold が偏る。`split_by_spatial_blocks` は分割数が非空ブロック数を上回るときしか例外を出さないため、次の基準を**実行前に固定**して判定した。

- (a) 非空ブロック数（結果 JSON の `spatial_cv.block_definition.n_blocks`）が 10 以上（分割数5 × 2。各 fold に平均2ブロック以上入る）
- (b) fold ごとのテストセル数（`*_spatial_cv_folds.csv` の `test_size`）の最大/最小が 1.5 以下

| ラン | 非空ブロック数 | fold のテストセル数 | 最大/最小 | 判定 |
|---|---:|---|---:|---|
| Satellite Only・全域 | 503 | 19,999〜20,001 | 1.000 | 成立 |
| Satellite Only・測量GIS範囲 | 24 | 19,609〜21,281 | 1.085 | 成立 |
| Limited ラン13相当・全域 | 502 | 19,999〜20,001 | 1.000 | 成立 |
| Limited ラン13相当・測量GIS範囲 | 24 | 19,683〜21,116 | 1.073 | 成立 |
| Limited ラン12相当・全域 | 502 | 19,999〜20,001 | 1.000 | 成立 |
| Limited ラン12相当・測量GIS範囲 | 24 | 19,683〜21,116 | 1.073 | 成立 |

**基準は成立したが、測量GIS範囲では fold 間のばらつきが大きい。** fold 間の R² の標準偏差（結果 JSON の `spatial_cv.*.r2_std`。母標準偏差）は、全域の 0.02〜0.04 に対し、測量GIS範囲の Limited で 0.09〜0.12（採用構成で線形 0.117・RF 0.092）、Satellite Only で 0.04〜0.05 である。24ブロックを5つに分けるため、1 fold が数ブロックで構成され、どのブロックがテスト側に入るかの影響を受けやすい。測量GIS範囲の Spatial CV の平均値は、全域より不確かさが大きい数値として扱う。ブロック長の短縮（1,800m 等）は、基準が成立したため行っていない。

---

## 4. 結果

### 4.1 目的変数（LST）の分布

フィルタ後の母数全体（結果 JSON の `filter_dropout.target_distribution.after`）の値。単位は °C。

| ラン | 平均 | 標準偏差 |
|---|---:|---:|
| Satellite Only・全域 | 35.49 | 2.52 |
| Satellite Only・測量GIS範囲 | 37.84 | 3.72 |
| Limited・全域 | 35.52 | 2.50 |
| Limited・測量GIS範囲 | 37.89 | 3.70 |

**測量GIS範囲の LST は、全域より平均が約2.4°C 高く、標準偏差も約1.5倍大きい。** 計画の段階では「都心部は山間部・農地を含まないため LST の分散が小さくなる」と想定していたが、実測は逆だった。測量GIS範囲は高温の密集市街地と低温の水域（Limited のフィルタ後の母数で、`LULC_WATER_COV` の平均が全域 0.054 に対し 0.138）を併せ持ち、一方の全域は農地が支配的で LST が中位に集まる、と考えられる。この解釈は分布の要約値からの推測であり、空間分布は確認していない（**未確認**）。

### 4.2 モデル性能

RMSE の単位は °C。Spatial CV は5 fold の平均（R² は ± fold 間の標準偏差）。

| ラン | 範囲 | ランダム分割 線形 R² / RMSE | ランダム分割 RF R² / RMSE | Spatial CV 線形 R² / RMSE | Spatial CV RF R² / RMSE |
|---|---|---|---|---|---|
| Satellite Only | 全域 | 0.4920 / 1.7727 | 0.6404 / 1.4914 | 0.4821±0.0188 / 1.7977 | 0.6302±0.0364 / 1.5161 |
| Satellite Only | 測量GIS範囲 | 0.7716 / 1.7843 | 0.8576 / 1.4089 | 0.7546±0.0501 / 1.7981 | 0.8359±0.0375 / 1.4649 |
| Limited ラン13相当 | 全域 | 0.6536 / 1.4675 | 0.7995 / 1.1164 | 0.6439±0.0247 / 1.4862 | 0.7531±0.0250 / 1.2374 |
| Limited ラン13相当 | 測量GIS範囲 | 0.8991 / 1.1791 | 0.9621 / 0.7225 | 0.8176±0.1169 / 1.2310 | 0.8509±0.0920 / 1.1179 |
| Limited ラン12相当 | 全域 | 0.6594 / 1.4552 | 0.8031 / 1.1063 | 0.6496±0.0273 / 1.4742 | 0.7604±0.0229 / 1.2191 |
| Limited ラン12相当 | 測量GIS範囲 | 0.8993 / 1.1777 | 0.9617 / 0.7264 | 0.8178±0.1162 / 1.2310 | 0.8518±0.0915 / 1.1149 |

### 4.3 変数の寄与（SHAP 平均絶対値の上位）

フル表は1.1節のファイルを正本とする。ここでは順位の比較に必要な上位のみを載せる。

| ラン | 1位 | 2位 | 3位 | 4位 |
|---|---|---|---|---|
| Satellite Only・全域 | NDBI | NDVI | NDWI | — |
| Satellite Only・測量GIS範囲 | NDBI | NDVI | NDWI | — |
| Limited ラン13相当・全域 | NDBI | LULC_BUILT_COV | POP_DEN_WORLDPOP2020 | ELEV_MEAN |
| Limited ラン13相当・測量GIS範囲 | LULC_BUILT_COV | POP_DEN_WORLDPOP2020 | NDBI | NTL_MEAN |
| Limited ラン12相当・全域 | NDBI | LULC_BUILT_COV | POP_DEN_WORLDPOP2020 | ELEV_MEAN |
| Limited ラン12相当・測量GIS範囲 | LULC_BUILT_COV | POP_DEN_WORLDPOP2020 | NDBI | NTL_MEAN |

- Limited では、測量GIS範囲で `LULC_BUILT_COV` が1位に上がり（RF 重要度も 0.48 → 0.78）、`ELEV_MEAN` が上位から外れて `NTL_MEAN` が入る。採用構成（ラン13相当）と `ndwi`（ラン12相当）で順位は変わらない
- Satellite Only は両範囲で順位が同じである
- **SHAP 平均絶対値の大きさは範囲間で直接比べない。** 値は LST の単位（°C）で表され、目的変数の分散が大きい測量GIS範囲では全体に大きくなるため、順位の比較にとどめる

### 4.4 多重共線性と説明変数の分布

VIF は結果 JSON の `vif`、標準偏差・0の割合は10万件サンプル（`*_sample_100000.csv`。Git 管理外のため、確認には再実行が要る）から求めた。

- **採用構成（ラン13相当）の VIF は、測量GIS範囲で最大 4.90（`NDBI`）** であり、全域（最大 3.24）より上がるが、危険水準（10）には達しない
- **ラン12相当の `NDVI`・`NDWI` は両範囲とも危険水準である**（全域 32.2・34.5、測量GIS範囲 38.5・44.8）。Satellite Only も同様（全域 26.5・24.8、測量GIS範囲 34.1・31.5）。この2列の係数・寄与を個別に解釈しない方針（[limited_analysis_results.md](limited_analysis_results.md) 6.5節）は、測量GIS範囲でも変わらない
- 測量GIS範囲でほぼ一定になる変数（Limited のサンプル）:

| 変数 | 全域 標準偏差 | 全域 0の割合 | 測量GIS範囲 標準偏差 | 測量GIS範囲 0の割合 |
|---|---:|---:|---:|---:|
| `LULC_TREE_COV` | 0.2158 | 93.4% | 0.0342 | 99.7% |
| `LULC_RANGE_COV` | 0.0571 | 98.7% | 0.0466 | 99.0% |
| `LULC_WETLAND_COV` | 0.1118 | 97.6% | 0.0670 | 98.7% |
| `ELEV_MEAN`（m） | 67.00 | 0.0% | 3.12 | 0.0% |

- 被覆率型3列は全域でも0に偏っていたが、測量GIS範囲では非0のセルが 0.3〜1.3% しか残らない。`ELEV_MEAN` は山地を含まないため標準偏差が約20分の1になる
- 逆に、建物・道路・人口・夜間光は測量GIS範囲で変動が大きくなる（例: `POP_DEN_WORLDPOP2020` の標準偏差 57.9 → 192.0、`LULC_BUILT_COV` の0の割合 71.0% → 29.7%）
- `LULC_BARE_COV` は両範囲とも定数列として投入から外れている（`dropped_constant_features`）。ハノイROIの GLC_FCS30D に裸地画素が無く全セルで0になるためであり、既存の Limited のランと同じ扱いである（[limited_analysis_results.md](limited_analysis_results.md) 3.6節）

---

## 5. 結果の解釈

### 5.1 範囲間の精度比較は RMSE を主、R² を従とする

**R² は目的変数の分散に依存するため、範囲間の比較は RMSE で行う。** 本ドキュメントでは、測量GIS範囲のほうが LST の分散が大きい（4.1節）ため、RMSE が同じでも R² は上がる。計画の段階では分散が小さくなる（R² が下がる）向きを想定していたが、実測は逆向きだった。比較を RMSE で行うという方針は、向きによらず変わらない。

- **Satellite Only は、範囲を絞っても予測誤差が変わらない。** Spatial CV の RMSE は線形 1.798 → 1.798、RF 1.516 → 1.465 であり、線形の R² が 0.48 → 0.75 に上がるのは、ほぼ分散の違いによる。「測量GIS範囲では分光指数だけで LST をよく説明できる」と読んではならない
- **Limited は、測量GIS範囲で予測誤差が下がる。** Spatial CV の RMSE は線形 1.486 → 1.231、RF 1.237 → 1.118（採用構成）。ただし測量GIS範囲の Spatial CV は fold 間のばらつきが大きく（3.5節）、この差がブロックの割り方に対して頑健かは確認していない
- **ランダム分割と Spatial CV の差が、測量GIS範囲で広がる。** Limited 採用構成の RF の RMSE は、全域で 1.116（ランダム分割）→ 1.237（Spatial CV）、測量GIS範囲で 0.723 → 1.118 である。測量GIS範囲ではセルが密に隣接しており、ランダム分割は近傍セルを学習側に含みやすい。範囲間の比較には Spatial CV の値を使う

### 5.2 都市構造変数の上乗せ効果（Satellite Only との差）

ラン12相当は分光指数ブロックが Satellite Only と同じ3列（NDVI・NDBI・NDWI）であるため、両者の差を「同じ分光指数に公開GIS由来の都市構造変数を加えた効果」として読める（RQ3）。Spatial CV の RMSE（°C）で比べる。

| 範囲 | Satellite Only 線形 / RF | Limited ラン12相当 線形 / RF | 差（線形 / RF） |
|---|---|---|---|
| 全域 | 1.798 / 1.516 | 1.474 / 1.219 | −0.324 / −0.297 |
| 測量GIS範囲 | 1.798 / 1.465 | 1.231 / 1.115 | −0.567 / −0.350 |

- **都市構造変数を加えることによる誤差の減少は、測量GIS範囲のほうが大きい**（特に線形）。測量GIS範囲では建物・道路・人口・夜間光の変動が大きく（4.4節）、分光指数だけでは捉えにくい差を説明していると考えられる
- **母数が揃っていないため、この差は参考値である。** Limited は、人口・夜間光の有効域品質列（`VALID_POP_WORLDPOP2020_MASK`・`VALID_NTL_MASK`）が `== 1` であることを追加で要求し、非NULLを要求する列も多い（MNDWI を含む分光指数4列・土地被覆等）。そのため母数が異なる（全域で 3,317,260 対 3,274,657、測量GIS範囲で 111,446 対 110,534）。測量GIS範囲の差（912セル）は、`mask_passed` の段階の差（111,448 対 110,536）と一致し、すべて有効域品質列によるものである。同じセル上の比較ではない

### 5.3 変数の寄与の変化

- 測量GIS範囲では、Limited の寄与の上位が「建物被覆（`LULC_BUILT_COV`）・人口・夜間光」に移り、全域で上位だった `ELEV_MEAN` が下がる。`ELEV_MEAN` が下がるのは、測量GIS範囲に山地が無く標高の変動がほぼ無いためであり（4.4節）、都心部で標高が LST に効かないことを示すものではない
- `NDBI` は全域で1位、測量GIS範囲で3位である。建物被覆率と人口が同時に入るとき、都心部では分光指数の情報がそれらと重なる、と考えられる（**未確認**。共線性は VIF 4.90 で危険水準ではない）

### 5.4 解釈を保留する変数

測量GIS範囲でほぼ一定になる `LULC_TREE_COV`・`LULC_RANGE_COV`・`LULC_WETLAND_COV`（非0が 0.3〜1.3%）と、変動が小さい `ELEV_MEAN`（標準偏差 3.1 m）は、**測量GIS範囲での係数・寄与を解釈しない。** `drop_constant_features` は分散が厳密に0の列しか除かないため、これらは投入されたままになり、少数の非0セルに係数が引きずられうる。寄与はいずれも小さく（SHAP 平均絶対値で `ELEV_MEAN` は 0.13、被覆率型3列は 0.001 以下）、性能の比較には影響しない見込みである。

### 5.5 限界

- **ハノイROI・30m・単一観測（旧採用の 032305）の結果である。** 測量GIS範囲は約100 km² のハノイ都心部1か所であり、他の範囲・都市への一般化はしない。主採用の観測（032358）では全域の R² が大きく変わっており（[limited_analysis_results.md](limited_analysis_results.md) 8.5節）、測量GIS範囲の結果も観測によって変わりうる。主採用の観測での結果は7章にある
- **抽出密度の差が Spatial CV に与える影響は未評価である。** 抽出率は全域で約3%、測量GIS範囲で約90%と異なる（3.4節）。測量GIS範囲では隣接セルがほぼすべてサンプルに入るため、ブロック境界をはさんだ近傍セルが学習側に入る割合も全域より高く、Spatial CV でも境界での情報の漏れが強まりうる。全域でも、別 fold の隣接セルを持つ境界セルは約4%あるが、それが R² をどれだけ押し上げているかは未評価である（[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 4.5節）。測量GIS範囲での割合も測っていない
- **測量GIS範囲の Spatial CV は24ブロックに依存する。** 判定基準は満たしたが、fold 間のばらつきが大きい（3.5節）
- **全域と測量GIS範囲は母集団の性格が異なる。** 測量GIS範囲は全域の部分集合だが、土地被覆・標高・人口の分布が大きく異なり（4.4節）、抽出率も異なる（3.4節）。両範囲の差を「範囲の広さ」だけの効果とは読まない

---

## 6. 今後の方向性

- **主採用の観測での回し直し（実施済み・7章）**: Satellite Only と Limited の採用構成（ラン13相当）を、主採用の観測 032358 で全域・測量GIS範囲の両方について回し直した。測量GIS範囲では共通評価セルによる比較も行った。ラン12相当（水指数 `ndwi`）は回していない（7.1節）
- **Full シナリオとの比較**: 7章の測量GIS範囲の結果を基準に、測量GIS由来の建物・道路を加えた Full シナリオを同じ範囲・同じ条件で評価する。Full も7章と同じ評価セル（`data/output/common_evaluation/20220906_032358_area_survey/evaluation_cells_seed42.csv`）で回せば、Limited・Satellite Only と同じセル・同じ分割で比べられる。ただし Full の有効母集団が共通集合をすべて含むかは未確認である
- **他スケールへの展開**: 90m・300m では境界セルの超過が大きく（3.2節）、ブロック数もさらに減るため、境界セルの扱いとブロック長を改めて検討する
- **Spatial CV の頑健性**: Satellite Only と Limited の差については、測量GIS範囲でも20シードの反復で頑健さを確かめた（7.6.3節）。一方、各シナリオの性能そのものと、全域と測量GIS範囲の違い（7.4節・7.6.4節）は fold の組み方に左右されやすく、区間も求めていない。ブロックの割り当てを変えた繰り返し等での確認は残る

---

## 7. 主採用の観測（2022-09-06）での比較

主採用の観測 `2022-09-06T03:23:58Z`（032358）で、全域と測量GIS範囲の比較を回し直した。2〜5章（032305）と同じ手順に加えて、測量GIS範囲では Satellite Only と Limited を**同じセル・同じ分割**で比べる共通評価セルを使った。全域の共通評価セルによる比較は [limited_analysis_results.md](limited_analysis_results.md) 8.6節にあり、本章はその測量GIS範囲版にあたる。

### 7.1 実行内容と数値の正本

1. `mask_survey` を結合したデータセットを2つ生成した（いずれも 3,739,454 行。既存のデータセットは上書きしていない）
2. 通常ランを4本実行した（Satellite Only と Limited の採用構成 × 全域・測量GIS範囲）。**Limited のラン12相当（水指数 `ndwi`）は回していない。** 主採用の観測の全域では未実行のため再現確認の相手がなく、Full シナリオと比べる基準は採用構成で足りるためである
3. 全域の2ランで主結果の再現を確認してから、測量GIS範囲のランに進んだ（7.2節）
4. 測量GIS範囲で、4構成共通の評価セルを作り、両シナリオを同じセル・同じ分割で実行した。単発の比較に加えて、20シード（42〜61）で反復した（7.6節）

データセットの生成と通常ランのコマンド（`{area}` は `roi` / `survey`）:

```bash
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited --tables idx_20220906_032358 lst_20220906_032358 mask_survey --name limited_masksurvey_20220906_032358
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20220906_032358 lst_20220906_032358 mask_survey --name satellite_only_masksurvey_20220906_032358
python -m src.analysis.analysis_rq3_satellite_only --dataset-path data/output/datasets/dataset_satellite_only_masksurvey_20220906_032358_hanoi_30m.gpkg --output-dir data/output/satellite_only_cellbased/20220906_032358_area_comparison --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --analysis-area {area}
python -m src.analysis.analysis_rq3_limited --dataset-path data/output/datasets/dataset_limited_masksurvey_20220906_032358_hanoi_30m.gpkg --output-dir data/output/limited/20220906_032358_area_comparison --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --variable-set both --building-height mean --population-source worldpop2020 --water-index none --analysis-area {area}
```

共通評価セルの生成・比較・反復のコマンドは [analysis_workflow.md](../02_methods/analysis_workflow.md) 5.3.3節の「分析対象範囲」の例のとおりである。両シナリオの評価セルのランは、上の通常ランのコマンド（`--analysis-area survey`）に `--evaluation-cells data/output/common_evaluation/20220906_032358_area_survey/evaluation_cells_seed42.csv` を加えて実行した。反復は `python -m src.analysis.repeat_common_evaluation --evaluation-cells {同じ CSV} --n-seeds 20` である。

| 内容 | ファイル |
|---|---|
| 通常ラン（全域・測量GIS範囲） | `data/output/satellite_only_cellbased/20220906_032358_area_comparison/`・`data/output/limited/20220906_032358_area_comparison/`。出力名の規則は1.1節と同じ（接頭辞の観測が `20220906_032358` に変わり、Limited は `_both_bh_mean_wi_none` のみ） |
| 評価セルと共通集合のメタデータ | `data/output/common_evaluation/20220906_032358_area_survey/evaluation_cells_seed42.csv`・`evaluation_cells_seed42_results.json` |
| 両シナリオの評価セルのラン（シード42） | 通常ランと同じ2ディレクトリ。出力名の末尾が `_area_survey_evaluation_cells_seed42` |
| 単発の比較 | `data/output/common_evaluation/20220906_032358_area_survey/scenario_comparison_evaluation_cells_seed42_results.json`・`_folds.csv` |
| 20シードの反復 | 同じディレクトリの `repeated_comparison_evaluation_cells_seed42_results.json`・`_folds.csv`・`_differences.csv`（シードごとの途中結果は `repeat_evaluation_cells_seed42/`） |

いずれも `provenance.git.dirty` は `false` で記録されている。サンプル CSV（`*_sample_*.csv`）と実行ログは Git 管理外である。

### 7.2 全域ランの再現確認とブロック判定

3.3節と同じ3基準で、全域ランが主結果（`data/output/limited/20220906_032358/`・`data/output/satellite_only_cellbased/20220906_032358/`）を再現するかを、測量GIS範囲のランより前に確認した。

| 基準 | Satellite Only | Limited（採用構成） |
|---|---|---|
| フィルタ後の母数が一致 | 3,491,872 で一致 | 3,446,551 で一致 |
| 10万件サンプルの `cell_id` 集合が既存のサンプル CSV と一致 | 100,000件すべて共通 | 100,000件すべて共通 |
| Spatial CV の R²（線形・RF）が小数4桁で一致 | 0.6855・0.7475 | 0.7652・0.8392 |

ブロックの判定（3.5節と同じ基準: (a) 非空ブロック数 10 以上、(b) fold のテストセル数の最大/最小 1.5 以下）:

| ラン | 非空ブロック数 | fold のテストセル数 | 最大/最小 | 判定 |
|---|---:|---|---:|---|
| Satellite Only・全域 | 509 | 20,000（全 fold） | 1.000 | 成立 |
| Satellite Only・測量GIS範囲 | 24 | 19,609〜21,308 | 1.087 | 成立 |
| Limited・全域 | 506 | 20,000（全 fold） | 1.000 | 成立 |
| Limited・測量GIS範囲 | 24 | 19,645〜21,196 | 1.079 | 成立 |
| 共通評価セル・測量GIS範囲 | 24 | 19,645〜21,196 | 1.079 | 成立 |

### 7.3 母数と LST の分布

| ラン | フィルタ後の母数 | 抽出率 | LST 平均（°C） | LST 標準偏差（°C） |
|---|---:|---:|---:|---:|
| Satellite Only・全域 | 3,491,872 | 2.9% | 32.21 | 2.65 |
| Satellite Only・測量GIS範囲 | 111,278 | 89.9% | 34.91 | 3.60 |
| Limited・全域 | 3,446,551 | 2.9% | 32.22 | 2.64 |
| Limited・測量GIS範囲 | 110,376 | 90.6% | 34.95 | 3.57 |

- **測量GIS範囲の LST は、全域より平均が約2.7°C 高く、標準偏差は約1.36倍である。** 032305 でも測量GIS範囲のほうが平均が高く標準偏差が大きく、向きは同じである（観測をまたいでは差の向きのみを比べ、°C の値は比べない）。Limited のフィルタ後の母数での `LULC_WATER_COV` の平均も、全域 0.053 に対し測量GIS範囲 0.137 と、032305（0.054・0.138）とほぼ同じである
- **測量GIS範囲のサンプルはほぼ全数である**（抽出率約90%）
- 測量GIS範囲での LST の欠測・有効率不足による脱落は、Satellite Only で 145セル、Limited で 135セルである（`mask_passed` → `target_available`）。032305（1セル）より多いが、母数の0.2%未満にとどまる

### 7.4 モデル性能（通常ラン）

RMSE の単位は °C。Spatial CV は5 fold の平均（R² は ± fold 間の標準偏差）。右端の列は Spatial CV の RF の RMSE をフィルタ後の母数の LST 標準偏差で割った値で、観測をまたぐ比較（7.7節）に使う。

| ラン | 範囲 | ランダム分割 線形 R² / RMSE | ランダム分割 RF R² / RMSE | Spatial CV 線形 R² / RMSE | Spatial CV RF R² / RMSE | RF RMSE ÷ LST 標準偏差 |
|---|---|---|---|---|---|---:|
| Satellite Only | 全域 | 0.6883 / 1.4737 | 0.7543 / 1.3084 | 0.6855±0.0060 / 1.4850 | 0.7475±0.0144 / 1.3288 | 0.501 |
| Satellite Only | 測量GIS範囲 | 0.8165 / 1.5344 | 0.8645 / 1.3185 | 0.7819±0.0426 / 1.5984 | 0.8311±0.0449 / 1.3934 | 0.387 |
| Limited | 全域 | 0.7660 / 1.2613 | 0.8569 / 0.9863 | 0.7652±0.0183 / 1.2699 | 0.8392±0.0068 / 1.0518 | 0.398 |
| Limited | 測量GIS範囲 | 0.9025 / 1.1146 | 0.9572 / 0.7388 | 0.8494±0.0695 / 1.1425 | 0.8519±0.0792 / 1.1026 | 0.308 |

- **Satellite Only は、範囲を絞ると予測誤差がむしろ増える。** Spatial CV の RMSE は線形 1.485 → 1.598、RF 1.329 → 1.393 である。R² が上がるのは LST の分散が大きいためであり、5.1節の読み方がそのまま当てはまる
- **Limited は、線形では誤差が下がるが、RF ではほぼ変わらない。** Spatial CV の RMSE は線形 1.270 → 1.142、RF 1.052 → 1.103 である。RF の増加（0.05°C）は、測量GIS範囲での RMSE の fold 間の標準偏差（0.07°C）より小さく、増えたとも下がったとも言えない。032305 では RF も 1.237 → 1.118 と下がっていた（7.7節）
- **ランダム分割と Spatial CV の差は、測量GIS範囲で広がる。** Limited の RF の RMSE は、全域で 0.986 → 1.052、測量GIS範囲で 0.739 → 1.103 である。5.1節と同じ向きである
- **測量GIS範囲の R² は fold の組み方で大きく変わる。** Satellite Only の通常ランと評価セルのラン（7.6節）は、どちらも同じ範囲の母集団の約9割を抽出した標本だが、標本の引き直し（評価セルは共通集合から外れた902セルを除く母集団から抽出）と fold の組み方が異なる。Spatial CV の RF の R² は 0.831 と 0.771 で 0.06 違うが、RMSE は 1.393 と 1.387 でほぼ同じである。fold ごとの RMSE と R² から逆算したテスト側の LST の標準偏差は、通常ランで 2.9〜4.0°C、評価セルで 2.1〜4.3°C であり、ばらつきの小さいブロックが同じ fold に集まると、その fold の R² が下がる。24ブロックしかない測量GIS範囲では、R² の値そのものを範囲間・ラン間で比べない
- Limited の通常ランと評価セルのランは、fold ごとの指標まで一致した。共通集合が Limited の有効母集団と一致し（7.6.1節）、同じシードで同じ標本・同じ fold が選ばれるためである

### 7.5 変数の寄与（SHAP 平均絶対値の上位）

| ラン | 1位 | 2位 | 3位 | 4位 |
|---|---|---|---|---|
| Satellite Only・全域 | NDBI | NDWI | NDVI | — |
| Satellite Only・測量GIS範囲 | NDBI | NDVI | NDWI | — |
| Limited・全域 | NDBI | LULC_BUILT_COV | POP_DEN_WORLDPOP2020 | ELEV_MEAN |
| Limited・測量GIS範囲 | LULC_BUILT_COV | NDBI | POP_DEN_WORLDPOP2020 | NDVI |

- **Limited では、測量GIS範囲で `LULC_BUILT_COV` が1位に上がる**（RF 重要度も 0.32 → 約0.7）。`ELEV_MEAN` は4位から7位に下がり、`NTL_MEAN` は5位である。標高が下がる理由は5.3節と同じ（測量GIS範囲に山地が無い）と考えられるが、主採用の観測で `ELEV_MEAN` の標準偏差は測っていない
- **Satellite Only では `NDVI` と `NDWI` の順位が範囲で入れ替わる**が、両者の VIF は危険水準（全域で `NDVI` 36.6、測量GIS範囲で `NDWI` 23.1 が最大）であり、2列の順位を個別に解釈しない（4.4節と同じ方針）
- Limited の VIF は測量GIS範囲でも最大 5.68（`LULC_WATER_COV`）で、危険水準（10）には達しない
- SHAP 平均絶対値の大きさは、4.3節と同じ理由で範囲間で直接比べない

### 7.6 Satellite Only と Limited の比較（共通評価セル）

通常ランでは、Satellite Only と Limited の母数が測量GIS範囲で 902セル食い違い、10万件の標本も fold も別になる。24ブロックしかない測量GIS範囲では fold の組み方で R² が大きく揺れる（7.4節）ため、差に fold の当たり外れが混ざる。そこで、全域（[limited_analysis_results.md](limited_analysis_results.md) 8.6節）と同じ設計で、**両シナリオに共通するセルから評価セルと fold 割り当てを1つに固定した。** 差の向きはすべて **Limited − Satellite Only** である（R² は正、RMSE・MAE は負なら Limited が良い）。

#### 7.6.1 共通集合と評価セル

| 構成 | 有効母集団 | 共通集合から外れたセル |
|---|---:|---:|
| Satellite Only | 111,278 | 902（0.81%） |
| Limited × WorldPop2020（採用構成） | 110,376 | 0 |
| Limited × LandScan2020 | 111,278 | 902（0.81%） |
| Limited × LandScan2023 | 111,278 | 902（0.81%） |
| **共通集合** | **110,376** | — |

- **共通集合は Limited（WorldPop2020）の有効母集団と一致した。** 2つのデータセット間で `LST`・`NDVI`・`NDBI` の値は共通集合の全セルで一致した（不一致0件）
- **外れた 902セルは、低温で水域寄りのセルである。** LST の平均は 30.0°C（共通集合 34.9°C）、`LULC_WATER_COV` の平均は 0.294（同 0.137）、`NDVI` の平均は 0.125（同 0.328）である。24ブロック中17ブロックに散らばり、脱落率が50%を超えるブロックは無い。全域（8.6.2節）と同じく、比較の母集団は Satellite Only 単独の母集団より水域の少ない側に寄っている。これらのセルが WorldPop2020 の有効域から外れる理由は確かめていない（**未確認**）
- 評価セルは共通集合から10万件（90.6%）を抽出し（乱数シード42）、2,700m ブロック・GroupKFold 5分割で fold を割り当てた。非空ブロック数は24、fold ごとのテスト行数は 19,645〜21,196 である

#### 7.6.2 単発の比較（シード42）

| 指標（Spatial CV、5 fold の平均） | Satellite Only | Limited | 差 | 補正 t 区間（95%） | 素朴な t 区間（参考） |
|---|---|---|---|---|---|
| RF R² | 0.7710 | 0.8519 | **+0.0808** | [+0.0057, +0.1559] | [+0.0308, +0.1309] |
| 線形 R² | 0.7110 | 0.8494 | **+0.1384** | [+0.0162, +0.2605] | [+0.0569, +0.2198] |
| RF RMSE（°C） | 1.3869 | 1.1026 | −0.2843 | [−0.3697, −0.1989] | [−0.3413, −0.2274] |
| RF MAE（°C） | 1.0796 | 0.8353 | −0.2444 | [−0.3405, −0.1482] | [−0.3085, −0.1803] |
| 線形 RMSE（°C） | 1.5956 | 1.1425 | −0.4531 | [−0.6598, −0.2463] | [−0.5909, −0.3152] |
| 線形 MAE（°C） | 1.2809 | 0.8842 | −0.3967 | [−0.5769, −0.2164] | [−0.5168, −0.2765] |

区間は fold ごとの差（J = 5・自由度4）から求めた。ρ（テスト行数 ÷ 学習行数の平均）は 0.25、補正係数は 0.45 である。ランダム分割の差（点推定のみ）は、RF R² +0.0944・線形 R² +0.0876、RF RMSE −0.5835・線形 RMSE −0.4213（°C）である。

- **5つの fold すべてで Limited が上回った**（RF R² の fold ごとの差は +0.039〜+0.129）。ただし差の fold 間のばらつきが全域（+0.080〜+0.093）よりずっと大きく、補正 t 区間の下限は0に近い
- **RMSE の区間は0から十分に離れている。** R² の区間が広いのは、fold ごとのテスト側の LST の分散が大きく異なり（7.4節）、R² の差も fold によって大きく変わるためと考えられる

#### 7.6.3 20シードの反復

共通集合からシード 42〜61 で標本を抽出し直し、両シナリオの Spatial CV だけを回した。シード42の fold ごとの差は、7.6.2節の単発の比較と一致した（最大の差 3×10⁻¹⁶）。

| 指標（Spatial CV） | シードごとの差：平均 / sd / 2.5〜97.5パーセンタイル | 反復 k-fold の補正 t 区間（95%） |
|---|---|---|
| RF R² | +0.0765 / 0.0057 / +0.0664〜+0.0848 | [+0.0398, +0.1132] |
| 線形 R² | +0.1338 / 0.0097 / +0.1134〜+0.1471 | [+0.0792, +0.1884] |
| RF RMSE（°C） | −0.2905 / 0.0135 / −0.3159〜−0.2715 | [−0.3879, −0.1931] |
| RF MAE（°C） | −0.2476 / 0.0124 / −0.2709〜−0.2320 | [−0.3315, −0.1637] |
| 線形 RMSE（°C） | −0.4620 / 0.0187 / −0.4909〜−0.4410 | [−0.5950, −0.3290] |

- 区間の求め方と読み方は全域（8.6.4節）と同じである（J = 100・自由度99・ρ = 0.25・補正係数 0.26）。シードごとに標本自体を抽出し直しているため、区間には標本の違いも含まれる
- **20シード・100個の fold のすべてで Limited が上回った**（RF R² の fold ごとの差は +0.035〜+0.154、RF RMSE の差は −0.548〜−0.090°C）。補正 t 区間の下限も、単発（RF R² +0.006）より0から離れた
- 各シナリオの Spatial CV の RF R²（シードごとの5 fold 平均）は、20シードの平均で Satellite Only 0.777（sd 0.012）、Limited 0.853（sd 0.012）である
- **測量GIS範囲では抽出率が約90%のため、シード間で標本の大部分が重なる。** 20シードの反復が表す「標本の違い」は、全域（抽出率約3%）より小さい範囲の入れ替えにとどまる

#### 7.6.4 全域との比較

全域の値は [limited_analysis_results.md](limited_analysis_results.md) 8.6.4節（同じ観測・同じ設計の20シード反復）による。「÷ LST 標準偏差」は、差を各範囲の共通集合の LST 標準偏差（全域 2.64°C・測量GIS範囲 3.57°C）で割った値である。

| 範囲 | RF RMSE の差（°C） | ÷ LST 標準偏差 | 線形 RMSE の差（°C） | ÷ LST 標準偏差 | RF R² の差 | 線形 R² の差 |
|---|---:|---:|---:|---:|---:|---:|
| 全域 | −0.252 | −0.095 | −0.187 | −0.071 | +0.086 | +0.074 |
| 測量GIS範囲 | −0.291 | −0.081 | −0.462 | −0.129 | +0.076 | +0.134 |

- **線形モデルでは、公開GISを加える効果は都心部のほうがはっきり大きい。** °C でも、LST の標準偏差で割っても、R² でも、測量GIS範囲の差は全域の約1.8〜2.5倍である。032305 の参考比較（5.2節。母数が揃っていない）で見た向きが、同じセル上の比較でも確かめられた
- **RF では、範囲による違いは明確でない。** °C の差は測量GIS範囲のほうがやや大きいが、LST の標準偏差で割ると全域のほうが大きく、R² の差も全域のほうが大きい。測量GIS範囲では LST の分散が大きいため、どの尺度で比べるかで向きが変わる
- **範囲間の差には区間を求めていない。** 全域と測量GIS範囲の評価セルは別の標本であり、対応のある比較になっていない。測量GIS範囲の補正 t 区間の幅は、全域の約3〜5倍ある
- 差が「公開GISを加えた効果」だけではない点（Satellite Only は `NDWI` を含み、Limited は除外）は、全域（8.6.5節）と同じである

### 7.7 旧採用（032305）との比較

観測が異なるため、相対的な量（LST の標準偏差で割った誤差・変数の重要度の順位・全域との差の向き）だけを比べる。032305 の値は2〜5章の採用構成（ラン13相当）による。

| 観点 | 032305（2〜5章） | 032358（7章） | 一致 |
|---|---|---|---|
| 測量GIS範囲の LST（全域との差の向き） | 平均が高く、標準偏差が約1.48倍 | 平均が高く、標準偏差が約1.36倍 | 一致 |
| Spatial CV の RF RMSE ÷ LST 標準偏差（Satellite Only 全域 → 測量GIS範囲） | 0.602 → 0.394 | 0.501 → 0.387 | 向きは一致（下がる） |
| 同（Limited 全域 → 測量GIS範囲） | 0.495 → 0.302 | 0.398 → 0.308 | 向きは一致（下がる） |
| Satellite Only の RMSE（°C）の変化（全域 → 測量GIS範囲） | RF −3%・線形 ±0% | RF +5%・線形 +8% | 下がらない点は一致 |
| Limited の RMSE（°C）の変化（全域 → 測量GIS範囲） | RF −10%・線形 −17% | RF +5%・線形 −10% | **RF は不一致** |
| Limited の SHAP 上位（全域） | NDBI・LULC_BUILT_COV・POP_DEN_WORLDPOP2020・ELEV_MEAN | 同じ | 一致 |
| Limited の SHAP 上位（測量GIS範囲） | LULC_BUILT_COV・POP_DEN_WORLDPOP2020・NDBI・NTL_MEAN | LULC_BUILT_COV・NDBI・POP_DEN_WORLDPOP2020・NDVI | 1位と `ELEV_MEAN` の後退は一致 |
| 公開GISを加える効果（線形）の範囲による違い | 測量GIS範囲で大きい（参考比較） | 測量GIS範囲で大きい（共通評価セル） | 一致 |

- **観測をまたいで再現した点**: 都心部は全域より LST の分散が大きく、R² は見かけ上上がる。衛星指標だけのモデルの誤差は都心部で下がらない。都心部では建物被覆率が最も効き、標高は効かなくなる。線形モデルでは公開GISを加える効果が都心部で大きい
- **再現しなかった点**: 032305 では、公開GISを加えたモデルの RF の誤差が都心部で約1割下がっていたが、032358 では下がらなかった。032305 の要旨2点目（「公開GISを加えたモデルは誤差が実際に下がる」）は、RF については主採用の観測では成り立たない。どちらの観測でも測量GIS範囲の RMSE の fold 間のばらつきは大きく、この違いが観測の違いによるものか、fold の組み方の揺れによるものかは切り分けていない（**未確認**）
- RMSE ÷ LST 標準偏差は、Spatial CV の fold 平均の RMSE を母数全体の標準偏差で割った値である。fold ごとのテスト側の分散で割る R² とは一致しない

### 7.8 読み方と限界

- **ハノイROI・30m・単一観測（032358）・測量GIS範囲1か所の結果である。** 観測による違いは 032305 との相対的な比較（7.7節）でしか見ていない
- **測量GIS範囲の Spatial CV は24ブロックに依存し、R² は fold の組み方で 0.06 程度動く**（7.4節）。範囲間・ラン間の比較は RMSE で行い、Satellite Only と Limited の差は共通評価セル（7.6節）の値を主とする
- **比較の母集団は、低温で水域寄りの 902セルを含まない**（7.6.1節）。通常ランの Satellite Only の母集団はこれらを含む
- **抽出密度の差が Spatial CV に与える影響は未評価である**（5.5節と同じ）。測量GIS範囲のサンプルはほぼ全数で、ブロック境界をはさんだ近傍セルが学習側に入りやすい
- **補正 t 区間の式の確認範囲は全域と同じである**（[limited_analysis_results.md](limited_analysis_results.md) 8.6.5節）
