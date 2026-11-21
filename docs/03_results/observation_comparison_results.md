# 3 観測の分析結果の比較（主採用・旧採用・比較用の観測）

**最終更新**: 2026-11-21  
**関連ドキュメント**: [observation_selection.md](../02_methods/observation_selection.md)（8.4・8.5・9.1節）, [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md)（8.5節）, [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md)（7.5節）, [survey_area_comparison_results.md](survey_area_comparison_results.md), [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md)（2.1節）, [analysis_workflow.md](../02_methods/analysis_workflow.md)  
**前提知識**: [observation_selection.md](../02_methods/observation_selection.md) 8.5節（主採用と比較用の観測、観測どうしで比べる量）、[limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) 8.5節（主採用と旧採用の比較の読み方と物差し）  
**対象RQ**: RQ1（支配的な説明変数）・RQ3（データ制約下での有効性評価）

---

## 1. 位置づけ

比較用の観測 `2024-11-30T03:23:36`（以下 032336。11月・乾季）で、主採用の観測と同じ構成の分析を行った。そのうえで、主採用 `2022-09-06T03:23:58`（以下 032358。9月・雨季）と旧採用 `2023-07-07T03:23:05`（以下 032305。7月・雨季）を加えた 3 観測の結果を、相対的な量で比べる。3 件とも Landsat 8 であり、センサ間の系統差は比較に入らない（[observation_selection.md](../02_methods/observation_selection.md) 8.5節）。

**本ドキュメントは主結果を置き換えない。** 主結果は主採用の観測 032358 による（衛星＋公開GISデータは [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) 8章、衛星データのみは [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 7章）。032358 と 032305 の2観測の比較は両文書（8.5節・7.5節）にあり、本ドキュメントはそれに乾季の 032336 を加えて3観測に広げたものである。

**比べる量と比べない量**: 観測（季節）が違うと LST の分布が違うため、LST の絶対値と、°C を単位に持つ量（RMSE・MAE・平均絶対 SHAP）は観測間で比べない。比べるのは、R²、RMSE を各観測の LST の標準偏差で割った値、変数重要度の順位、平均絶対 SHAP を各観測の LST の標準偏差で割った値である（[observation_selection.md](../02_methods/observation_selection.md) 8.5節）。LST の標準偏差は各ランの最終母数（フィルタ後の全セル）で求めた値を使う。

---

## 2. 実行内容と数値の正本

### 2.1 032336 の指標の再エクスポート

在庫の 032336 の指標 GeoTIFF は MNDWI の無い3バンドで、都市構造パラメータの算出と衛星＋公開GISデータの分析が前提とする4指標を満たさなかった。そこで LST と指標を GEE から再エクスポートし、`data/satellite/{lst,indices}/2024/` に置いた（`.gitignore` 対象）。在庫の `data/satellite/{lst,indices}/2023/` の 032336 は、既存の参照を変えないため残した。

| 確認項目 | 結果 |
|---|---|
| 指標のバンド | 4バンド（`NDVI`・`NDBI`・`NDWI`・`MNDWI`） |
| ROI 内の有効画素率（GeoTIFF ／ 探索結果） | LST 93.97% ／ 93.94%、指標 93.97%（差 0.03 pt。許容差 1 pt 以内） |
| 在庫の `2023/` 版との一致 | LST と、指標の共通する3バンドは画素単位で完全に一致 |

有効画素率の求め方は [observation_selection.md](../02_methods/observation_selection.md) 8.4節と同じである（ROI を GeoTIFF の格子にラスタ化し、画素中心が ROI 内の画素のうち NaN でない画素の割合）。集計に使ったスクリプトはリポジトリに保存していない。

### 2.2 分析の実行条件

主採用の観測の再実行と同じ条件で、衛星データのみ（全域）と衛星＋公開GISデータの採用構成（変数セット `both`・建物高さ `mean`・水指数 `none`・GLC・WorldPop2020）を 30m で実行した。乱数シード 42・RF 300本・標本 10万件・ブロック 2,700m・5分割で、フィルタ条件・サンプリング・モデル設定は主採用の観測と同じである。分散0の列 `LULC_BARE_COV` は他の2観測と同じく除外された。**高温画素（[observation_selection.md](../02_methods/observation_selection.md) 8.4節。野焼き・火災と推定される植生地2か所 54画素を含む）は除外せず、そのまま使った**（他の2観測と同じく、外れ画素を除く処理をしていないため。研究者の決定）。

```bash
python -m src.analysis.urban_params --city hanoi --lst-file data/satellite/lst/2024/LST_Landsat8_20241130_032336Z.tif --satellite-file data/satellite/indices/2024/INDICES_Landsat8_20241130_032336Z.tif --scales 30
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20241130_032336 lst_20241130_032336 --name satellite_only_20241130_032336
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited --tables idx_20241130_032336 lst_20241130_032336 --name limited_20241130_032336
python -m src.analysis.analysis_rq3_satellite_only --dataset-path data/output/datasets/dataset_satellite_only_20241130_032336_hanoi_30m.gpkg --output-dir data/output/satellite_only_cellbased/20241130_032336 --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --rf-trees 300
python -m src.analysis.analysis_rq3_limited --dataset-path data/output/datasets/dataset_limited_20241130_032336_hanoi_30m.gpkg --output-dir data/output/limited/20241130_032336 --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --rf-trees 300 --variable-set both --building-height mean --population-source worldpop2020 --water-index none
python -m src.analysis.compare_observations
```

### 2.3 数値の正本

| 内容 | ファイル |
|---|---|
| 032336 の衛星データのみ | `data/output/satellite_only_cellbased/20241130_032336/`（接頭辞 `dataset_satellite_only_20241130_032336_hanoi_30m`） |
| 032336 の衛星＋公開GISデータ | `data/output/limited/20241130_032336/`（接頭辞 `dataset_limited_20241130_032336_hanoi_30m_both_bh_mean_wi_none`） |
| 3 観測の比較の集計 | `data/output/observation_comparison/`（`observation_metrics.csv`・`observation_feature_ranks.csv`・`observation_feature_ranks_wide.csv`・`observation_scenario_diff.csv`・`observation_comparison_results.json`） |

本ドキュメントの数値は上の集計結果から転記した。集計は [compare_observations.py](../../src/analysis/compare_observations.py) が行い、6本のランの実行条件（`run_parameters`・ブロック長・分割数）が一致すること、分析対象範囲が全域であること、衛星＋公開GISデータが採用構成であることを確かめてから集計する。

**比較に使ったラン**:

| 観測 | 衛星データのみ | 衛星＋公開GISデータ |
|---|---|---|
| 032358 | `satellite_only_cellbased/20220906_032358/`（7章の主結果） | `limited/20220906_032358/`（8章の主結果） |
| 032305 | `satellite_only_cellbased/20230707_032305_area_comparison/` の全域ラン | `limited/20230707_032305_area_comparison/` の全域ラン（`..._both_bh_mean_wi_none_results.json`） |
| 032336 | `satellite_only_cellbased/20241130_032336/` | `limited/20241130_032336/` |

032305 は新世代のラン（ROI でクリップ済み・MNDWI あり）だけを使う（[observation_selection.md](../02_methods/observation_selection.md) 9.1節）。衛星＋公開GISデータは、8.5節で比較相手としたラン13 ではなく、同じ構成の全域ランを使った。両者はランダム分割・Spatial CV の R²・RMSE・MAE、母数のファネル、SHAP 平均絶対値がすべて一致し（[limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) 8.5節）、全域ランはクリーンなコミットで生成されているためである。集計値の Spatial CV の RF R²（0.7531）はラン13 の値と一致した。

**来歴**: 032336 の2本と集計結果は、いずれも `provenance.git.dirty` が `false` で、陳腐化チェック（`scripts/check_result_staleness.py`）で「最新」と判定された（2026-11-21）。

---

## 3. 032336 の単独の結果

### 3.1 母数

| 段階 | 衛星データのみ | 衛星＋公開GISデータ |
|---|---:|---:|
| データセットの行数 | 3,739,454 | 3,739,454 |
| マスク条件を満たす | 3,736,107 | 3,682,242 |
| LST が有効 | 3,509,052 | 3,463,249 |
| 説明変数がそろう（最終母数） | 3,508,803 | 3,462,748 |
| 標本 | 100,000 | 100,000 |
| Spatial CV のブロック数 | 511 | 511 |

- 説明変数の欠測による脱落は、衛星データのみで 249セル、衛星＋公開GISデータで 501セルにとどまる
- 最終母数の LST は平均 24.99°C・標準偏差 2.02°C（衛星データのみ）、平均 25.00°C・標準偏差 2.01°C（衛星＋公開GISデータ）である。雨季の2観測（標準偏差 2.50〜2.65°C）より分布の幅が狭い

### 3.2 モデル性能

| モデル | 評価 | 衛星データのみ R² | 衛星＋公開GISデータ R² | 衛星データのみ RMSE ÷ LST の標準偏差 | 衛星＋公開GISデータ RMSE ÷ LST の標準偏差 |
|---|---|---:|---:|---:|---:|
| RF | Spatial CV | 0.7365 | 0.8062 | 0.507 | 0.438 |
| Linear | Spatial CV | 0.6318 | 0.7369 | 0.602 | 0.511 |
| RF | ランダム分割 | 0.7496 | 0.8280 | 0.500 | 0.414 |
| Linear | ランダム分割 | 0.6427 | 0.7339 | — | — |

Spatial CV の RF R² の fold 間の標準偏差は、衛星データのみで 0.029、衛星＋公開GISデータで 0.014 である。ランダム分割の Linear の RMSE ÷ LST の標準偏差は集計していない（`observation_metrics.csv` に °C の値はある）。

### 3.3 変数重要度

| 順位 | 衛星データのみ（SHAP ÷ LST の標準偏差） | 衛星＋公開GISデータ（SHAP ÷ LST の標準偏差） |
|---:|---|---|
| 1 | `NDBI` 0.434 | `NDBI` 0.479 |
| 2 | `NDVI` 0.292 | `ELEV_MEAN` 0.130 |
| 3 | `NDWI` 0.154 | `NTL_MEAN` 0.100 |
| 4 | — | `NDVI` 0.076 |
| 5 | — | `POP_DEN_WORLDPOP2020` 0.034 |
| 6 | — | `LULC_BUILT_COV` 0.024 |
| 7 | — | `BUILD_DEN` 0.023 |

- **`NDBI` がどちらのシナリオでも首位である。** Permutation 重要度（ランダム分割のテストデータでの R² の低下量）でも首位で、衛星＋公開GISデータの第2位も SHAP と同じ `ELEV_MEAN` である
- 衛星＋公開GISデータの第8位以下（`LULC_WATER_COV` 以下の7変数）は SHAP ÷ LST の標準偏差が 0.016 以下で、順位を解釈しない
- 衛星＋公開GISデータの第3・4位（`NTL_MEAN` と `NDVI`）は Permutation では順位が逆になる。SHAP ÷ LST の標準偏差の差は 0.024 で、SHAP の変動幅（4.1節）より小さいため、この2変数の順位は読まない

---

## 4. 3 観測の比較

### 4.1 差の読み方（物差し）

差の大小は [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) 8.5節と同じ物差しで読む。標本の入れ替わりだけによる変動は、R² で 0.003程度、SHAP 平均絶対値を LST の標準偏差で割った値で 0.04程度である（[limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) 2.1節の実測。旧採用の観測・衛星＋公開GISデータで測った値）。観測間では母集団そのものが違うため、この物差しは**下限**として扱う。衛星データのみ（3変数）や、乾季の観測へ当てはめるのは外挿である。

### 4.2 モデル性能

| 指標 | シナリオ | 032358（雨季） | 032305（雨季） | 032336（乾季） |
|---|---|---:|---:|---:|
| 最終母数 | 衛星データのみ | 3,491,872 | 3,317,260 | 3,508,803 |
| 最終母数 | 衛星＋公開GISデータ | 3,446,551 | 3,274,657 | 3,462,748 |
| RF R²（Spatial CV） | 衛星データのみ | 0.7475 | 0.6302 | 0.7365 |
| RF R²（Spatial CV） | 衛星＋公開GISデータ | 0.8392 | 0.7531 | 0.8062 |
| Linear R²（Spatial CV） | 衛星データのみ | 0.6855 | 0.4821 | 0.6318 |
| Linear R²（Spatial CV） | 衛星＋公開GISデータ | 0.7652 | 0.6439 | 0.7369 |
| RF の RMSE ÷ LST の標準偏差（Spatial CV） | 衛星データのみ | 0.501 | 0.602 | 0.507 |
| RF の RMSE ÷ LST の標準偏差（Spatial CV） | 衛星＋公開GISデータ | 0.398 | 0.495 | 0.438 |
| Linear の RMSE ÷ LST の標準偏差（Spatial CV） | 衛星データのみ | 0.560 | 0.714 | 0.602 |
| Linear の RMSE ÷ LST の標準偏差（Spatial CV） | 衛星＋公開GISデータ | 0.481 | 0.595 | 0.511 |

- **乾季の 032336 の説明力は、雨季の 032358 と 032305 の間にある。** 衛星＋公開GISデータの RF R²（Spatial CV）は 032358 より 0.033 低く、032305 より 0.053 高い。衛星データのみでは 032358 との差が −0.011 と小さく、032305 より 0.106 高い。いずれも R² の標本変動（0.003程度）を超える
- 都心と郊外の LST 差は 032336 が +0.28°C と3観測で最も小さい（[observation_selection.md](../02_methods/observation_selection.md) 8.4節）が、説明力は最も低くはない
- R² の差の要因は切り分けていない（6章）

### 4.3 変数重要度（衛星データのみ）

| 変数 | SHAP の順位（032358 ／ 032305 ／ 032336） | SHAP ÷ LST の標準偏差（032358 ／ 032305 ／ 032336） | Permutation の順位（同） |
|---|---|---|---|
| `NDBI` | 1 ／ 1 ／ 1 | 0.526 ／ 0.405 ／ 0.434 | 1 ／ 1 ／ 1 |
| `NDVI` | 3 ／ 2 ／ 2 | 0.112 ／ 0.194 ／ 0.292 | 3 ／ 3 ／ 2 |
| `NDWI` | 2 ／ 3 ／ 3 | 0.130 ／ 0.174 ／ 0.154 | 2 ／ 2 ／ 3 |

- **`NDBI` の首位は、3観測・SHAP と Permutation のどちらでも変わらない**
- 032336 では `NDVI` が SHAP・Permutation とも第2位で、`NDWI` との SHAP ÷ LST の標準偏差の差は 0.139 と SHAP の変動幅（0.04程度）を超える。雨季の2観測では両者の差が 0.018・0.021 と変動幅より小さく、順位を読まないとしていた（[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 7.5節）。ただし `NDVI` と `NDWI` は VIF が危険水準を超える共線な組であり（同 7.4節）、SHAP は相関する変数の間で寄与を分け合うため、2変数の寄与の分け方の違いを個別の物理的な効果として読まない

### 4.4 変数重要度（衛星＋公開GISデータ）

| 変数 | SHAP の順位（032358 ／ 032305 ／ 032336） | SHAP ÷ LST の標準偏差（032358 ／ 032305 ／ 032336） | Permutation の順位（同） |
|---|---|---|---|
| `NDBI` | 1 ／ 1 ／ 1 | 0.388 ／ 0.295 ／ 0.479 | 1 ／ 1 ／ 1 |
| `LULC_BUILT_COV` | 2 ／ 2 ／ 6 | 0.169 ／ 0.192 ／ 0.024 | 3 ／ 5 ／ 7 |
| `POP_DEN_WORLDPOP2020` | 3 ／ 3 ／ 5 | 0.128 ／ 0.141 ／ 0.034 | 5 ／ 3 ／ 5 |
| `ELEV_MEAN` | 4 ／ 4 ／ 2 | 0.122 ／ 0.135 ／ 0.130 | 2 ／ 2 ／ 2 |
| `NDVI` | 5 ／ 5 ／ 4 | 0.075 ／ 0.094 ／ 0.076 | 4 ／ 4 ／ 3 |
| `NTL_MEAN` | 6 ／ 6 ／ 3 | 0.062 ／ 0.071 ／ 0.100 | 6 ／ 6 ／ 4 |
| `BUILD_DEN` | 13 ／ 13 ／ 7 | 0.002 ／ 0.002 ／ 0.023 | 12 ／ 12 ／ 6 |

表は 032358 の SHAP の上位6変数と、032336 で第7位に入った `BUILD_DEN` に限った。全14変数は `observation_feature_ranks_wide.csv` にある。

- **`NDBI` の首位は、3観測・SHAP と Permutation のどちらでも変わらない。** 032336 の SHAP ÷ LST の標準偏差（0.479）は雨季の2観測（0.388・0.295）より大きい
- **雨季の2観測で第2・3位だった `LULC_BUILT_COV` と `POP_DEN_WORLDPOP2020` は、032336 で第6・5位に下がった。** SHAP ÷ LST の標準偏差は 032358 からそれぞれ 0.145・0.094 下がり、SHAP の変動幅（0.04程度）を超える
- **`ELEV_MEAN` は SHAP ÷ LST の標準偏差が3観測とも 0.12〜0.14 でほぼ変わらない。** 032336 で第2位に上がったのは、上位の2変数が下がったためである。Permutation では3観測とも第2位である
- `NTL_MEAN`（第6位 → 第3位）と `BUILD_DEN`（第13位 → 第7位）も順位が上がったが、SHAP ÷ LST の標準偏差の増加は 0.037・0.021 で、SHAP の変動幅と同程度かそれ未満であり、順位の変化として読まない
- `LULC_BUILT_COV` が下がり `NDBI` が上がったことは、建物・不透水面に関わる情報の寄与が、土地被覆の面積率から分光指数へ移ったように見える。SHAP は相関する変数の間で寄与を分け合うため、乾季に都市域の寄与そのものが小さくなったとは読まない。乾季に分光指数の側で何が変わったか（収穫後の裸地の NDBI など）は確かめていない（**未確認**）

### 4.5 シナリオ間の差（参考値）

| 指標（衛星＋公開GISデータ − 衛星データのみ） | 032358 | 032305 | 032336 |
|---|---:|---:|---:|
| RF R²（Spatial CV） | +0.092 | +0.123 | +0.070 |
| Linear R²（Spatial CV） | +0.080 | +0.162 | +0.105 |
| RF の RMSE ÷ LST の標準偏差（Spatial CV） | −0.102 | −0.107 | −0.069 |
| 最終母数 | −45,321 | −42,603 | −46,055 |

**この差は参考値であり、RQ3 の上乗せ効果の推定には使わない。** 2つのシナリオは最終母数が4万セル余り違い、評価するセルと fold が一致しない。032358 では両シナリオに共通する評価セルと fold で比べた結果が主結果である（[limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) 8.6節）が、032305 と 032336 では共通評価セルでの比較を行っていない。この表で言えるのは、3観測とも衛星＋公開GISデータの R² が衛星データのみを上回るという向きまでである。

---

## 5. 結果のまとめ

- **`NDBI` は、3観測・2シナリオ・SHAP と Permutation のすべてで首位である。** 3観測の範囲では、観測と重要度の指標を変えても首位は変わらなかった
- **乾季の 032336 では、衛星＋公開GISデータの第2位以下の構成が雨季と違う。** `LULC_BUILT_COV` と `POP_DEN_WORLDPOP2020` の寄与が変動幅を超えて小さくなり、`ELEV_MEAN` が第2位になった。雨季の2観測では第6位までの SHAP の順位が一致していた
- **説明力は乾季の 032336 が雨季の2観測の間にある。** 都心と郊外の LST 差が3観測で最も小さい乾季の観測でも、R² は3観測で最も低くはない

---

## 6. 読み方と限界

- **母集団の違いと観測条件の違いを切り分けていない。** 観測ごとに最終母数が違い（032305 は他の2観測より17万〜19万セル少ない）、欠けているセルの性格によって説明しやすさが変わりうる。観測条件（季節・都心と郊外の LST 差）の違いとあわせて、R² と重要度の差の要因は分離できていない。切り分けには、3観測に共通するセルへ限定した評価が要る（本ドキュメントでは行っていない）
- **観測年と都市構造データの時点のずれが観測ごとに違う。** 説明変数のデータの時点は、人口 2020年、建物の輪郭 2021〜2023年ごろ（高さは 2019年ごろの画像による。推定）、土地被覆 2022年、夜間光 2023年、道路 2026年である（[論文第2章 2.3節](../../thesis/chapters/02_study_area_data/03_open_gis_data.md)）。観測年は 032358 が 2022年、032305 が 2023年、032336 が 2024年で、データの時点とのずれは観測ごとに異なる。乾季の 032336 で都市構造の変数の順位が下がったことに、このずれがどの程度効いているかは確かめていない
- **032336 には野焼き・火災と推定される高温画素が含まれる。** 除外せずに使った（2.2節）。画素単位の平均 + 6σ（37.2°C）を超える 30m のセルは、衛星＋公開GISデータのデータセットで `LST_VALID_RATIO` が 0.5以上のセル（3,510,596セル。マスク条件を課す前）のうち 118セル（0.0034%）で、標本 10万件に入ったのは衛星データのみで1セル、衛星＋公開GISデータで2セルである。この中には埋立地・工場の屋根のセルも含まれる。標本に占める割合は小さいが、結果への影響を除外して比べたことはない（**未確認**）
- **シナリオ間の差は参考値である**（4.5節）
- **単一の乱数シードによる。** 観測ごとに1本のランであり、観測間の差の物差しは他の観測・構成で測った標本変動の外挿である（4.1節）
- **Permutation 重要度はランダム分割のテストデータで測った値である。** 空間的に分けた評価での重要度ではない
