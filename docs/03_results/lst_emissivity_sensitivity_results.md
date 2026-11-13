# LST 算出の放射率が NDVI に依存することの感度分析 結果

**最終更新**: 2026-11-13  
**関連ドキュメント**: [limited_analysis_results.md](limited_analysis_results.md) 3.9節・8章, [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 7章, [gee_calc_LST.md](../02_methods/gee_calc_LST.md) 5.2節・8.3節, [analysis_workflow.md](../02_methods/analysis_workflow.md) 5.3.3節, [research_guide.md](../01_planning/research_guide.md)  
**対象RQ**: RQ1（どの説明変数が LST に対して支配的か）。RQ3 の2シナリオの結果を材料に用いる  
**前提知識**: SMW 法による LST の算出（[gee_calc_LST.md](../02_methods/gee_calc_LST.md)）、共通評価セル・補正 t 区間（[analysis_workflow.md](../02_methods/analysis_workflow.md) 5.3.3節）

---

## 1. 位置づけ

本研究の LST は SMW 法（S1 Ermida et al., 2020）で算出しており、地表面放射率を**同じシーンの NDVI から**求めている（FVC = ((NDVI − 0.2)/(0.86 − 0.2))²、ε = 0.99·FVC + (1 − FVC)·ε_bare。[gee_calc_LST.md](../02_methods/gee_calc_LST.md) 5.2節）。説明変数の `NDVI` が目的変数 `LST` の算出式に入るため、RQ1 で NDVI の寄与を論じると、算出式に由来する見かけの結びつきを「植生の効果」として読むおそれがある。

本ドキュメントは、放射率を NDVI に依存させない対照（ASTER GEDv3 の静的な放射率 EM0）で LST を作り直し、モデルの性能と変数の寄与・順位がどう変わるかを調べた結果を記録する。あわせて、旧採用の観測の LST がどの方式で算出されたかを確かめた結果（[limited_analysis_results.md](limited_analysis_results.md) 3.9節の記述の訂正の根拠）を記録する。

### 1.1 EM0 版の位置づけと結果の読み方

- **EM0 版は主たる LST の候補ではなく、感度分析の対照である。** EM0 は参照実装の `use_ndvi=false`（放射率を ASTER から直接得る）にあたる正式な選択肢だが、S1 の地上検証（Landsat 8 で RMSE 2.1 °C 相当）は NDVI 補正ありの構成で行われている。S6 Garzón et al. (2021) では熱帯都市の地上 LST との比較で ASTER GEDv3 の放射率が劣った（R² 0.27。Sentinel-2 由来 Fcover は 0.78）。ASTER GEDv3 は 2000〜2008 年の平均（100 m）であり、その後の市街化や観測時点の植生を反映しない
- **結果の読み方は非対称である。** EM0 版は「同じシーンの NDVI への依存」を外す代わりに「放射率の精度の低下」を持ち込む
  - EM0 版でも性能・寄与・順位がほとんど変わらない → NDVI の二重利用による水増しの懸念は小さいと言える
  - 大きく変わる → 依存の除去によるのか、EM0 の誤差によるのかを本分析だけでは区別できない
- 放射率は物理的にも植生に依存するため、物理的に妥当な放射率ほど植生と無関係にはならない。本分析が答えるのは「同じシーンの NDVI を算出式から外しても結論が保たれるか（頑健性）」である
- LST 算出アルゴリズム（SMW・RTE・Split-Window・USGS Level-2 の `ST_B10` など）の違いへの頑健性は扱わない。先行研究の算出法も大半が NDVI 由来の放射率を使うため、算出法を揃えても NDVI の二重利用の問いには答えられず、別の問いになるためである

## 2. 今回実施したこと

1. 旧採用の観測 `2023-07-07T03:23:05`（032305）の既存 LST GeoTIFF がどの方式で作られたかを、点の値の照合で確かめた（3章）
2. 主採用の観測 `2022-09-06T03:23:58`（032358）について、NDVI 版（分析に用いる LST と同じ条件）と EM0 版の LST・放射率を、現行のコードで GEE から同時に再出力した
3. 再出力した NDVI 版が既存の LST GeoTIFF と画素単位で一致することを確かめ、2 つの LST の差が放射率だけに由来することを担保した（4.1節）
4. ΔLST = LST(NDVI 版) − LST(EM0 版) の分布・NDVI 階級別の傾向・NDVI と LST の相関の変化を集計した（4章）
5. EM0 版の LST でパラメータテーブル・データセットを作り直し、衛星データのみ・衛星＋公開GISデータ（採用構成）を既存と同じ共通評価セルで実行して、NDVI 版のランと比べた（5章）

## 3. 旧採用の観測（032305）の LST の算出方式の確認

### 3.1 方法

既存の LST GeoTIFF（`data/satellite/lst/2023/LST_Landsat8_20230707_032305Z.tif`、シーン `LC08_127045_20230707`）の有効画素から 500 点を無作為に選び（乱数シード 42、画素の中心）、同じグリッド（EPSG:4326・既存 GeoTIFF のアフィン変換）で GEE から 3 方式の LST を取得して既存の値と比べた。許容差は 0.001 °C とした。

- SMW 法・NDVI 由来の放射率（分析に用いる LST の条件）
- SMW 法・ASTER GEDv3 の静的な放射率（EM0）
- Simple 法（Collection 2 Level-2 の `ST_B10` のスケーリングのみ）

値は現行のコードで算出した。既存 GeoTIFF の作成（2026-04-06）の後に雲マスクの条件が変わっている（Cirrus・Snow の追加）が、500 点のうち現行のマスクで欠測になった点はなかった。

### 3.2 結果

差は「方式 − 既存 GeoTIFF」である。

| 方式 | 比べた点 | 許容差以内の点 | 差の平均 | 差の絶対値の中央値 | 差の絶対値の最大 |
|---|---|---|---|---|---|
| SMW・NDVI 由来の放射率 | 500 | **500** | 0.000 °C | 0.000 °C | 2.8×10⁻¹³ °C |
| SMW・EM0 | 500 | 33 | +0.290 °C | 0.180 °C | 2.309 °C |
| Simple（`ST_B10`） | 500 | 0 | +8.430 °C | 8.440 °C | 16.106 °C |

**032305 の LST は SMW 法・NDVI 由来の放射率で算出されていた。** [limited_analysis_results.md](limited_analysis_results.md) 3.9節の旧記述（`ST_B10` をスケーリングしている）は誤りであり、同節を訂正した。

照合に用いたスクリプトの機能と出力は、照合を終えた時点で取り除いた（結果が週次の陳腐化チェックで要再実行と判定され続けるのを避けるため）。

Simple 法が SMW 法より平均で 8.4 °C 高い理由は調べていない（未確認。本分析の範囲外）。

## 4. 放射率による LST の差（032358）

### 4.1 再出力した NDVI 版の一致

再出力した NDVI 版は、既存の LST GeoTIFF（`data/satellite/lst/2022/LST_Landsat8_20220906_032358Z.tif`）と**有効画素の位置（3,762,674 画素）・値ともに完全に一致した**（差の絶対値の最大 0）。EM0 版との差は放射率の違いだけに由来する。

### 4.2 差の分布

集計は各ラスタで有効な画素（雲マスク・ASTER GED の欠測を除く）に限り、ROI 全体ではない。画素単位（30 m）で、分析のセル集計・欠測除去を経ていない。

| 項目 | 値 |
|---|---|
| 有効画素数 | NDVI 版 3,762,674 / EM0 版 3,764,811 |
| ΔLST の平均（標準偏差） | −0.365 °C（0.326） |
| ΔLST の中央値 [5〜95 パーセンタイル] | −0.338 [−0.880, +0.012] °C |
| ΔLST の最小 / 最大 | −41.367 / +0.775 °C |
| Δε（NDVI 版 − EM0 版）の平均 | +0.0086 |

ΔLST が負であることは、EM0 版の LST の方が高いことを意味する。

### 4.3 NDVI 階級別の差

| NDVI 階級 | 画素数 | ΔLST の中央値 | ΔLST の 5〜95 パーセンタイル | Δε の平均 |
|---|---|---|---|---|
| −1.0〜0.0 | 135,492 | 0.000 | −0.358〜0.000 | +0.0016 |
| 0.0〜0.2 | 183,123 | 0.000 | −0.041〜+0.065 | −0.0001 |
| 0.2〜0.4 | 592,305 | −0.011 | −0.077〜+0.058 | +0.0003 |
| 0.4〜0.6 | 929,253 | −0.185 | −0.353〜−0.060 | +0.0044 |
| 0.6〜0.8 | 1,585,500 | −0.539 | −0.818〜−0.322 | +0.0130 |
| 0.8〜1.0 | 336,363 | −0.854 | −1.353〜−0.600 | +0.0221 |

階級は左端のみ下限を含み、他は（下限, 上限]。**差は植生の多い画素に集中し、NDVI 0.4 以下ではほぼ 0 である。** 空間的にも、差が大きいのは西部の山地・森林と北部の植生地で、都心部はほぼ 0 である（`lst_difference_map.png`）。

### 4.4 NDVI と LST の相関

| 組 | Pearson r（画素単位） |
|---|---|
| NDVI と LST（NDVI 版） | −0.224 |
| NDVI と LST（EM0 版） | −0.136 |
| NDVI と ΔLST | −0.776 |

NDVI 由来の放射率を外すと、NDVI と LST の負の相関は約 4 割弱まる。ΔLST は NDVI とほぼ比例する。

### 4.5 外れ値

|ΔLST| > 3 °C の画素は 1,164（有効画素の 0.03%）である。これらの画素では EM0 が 0.476〜0.916（中央値 0.895）と低く、NDVI は 0.617〜0.895 だった。EM0 は ASTER GEDv3 の値をそのまま用いるため、ASTER 側の異常値と考えられる（推定・未確認）。外れ値は少数であり、5章の分析で除外はしていない。

## 5. 分析ランの比較（032358・共通評価セル）

### 5.1 実行条件

- 評価セル: `data/output/common_evaluation/20220906_032358/evaluation_cells_seed42.csv`（10 万件・ブロック 2,700 m・GroupKFold 5 分割）。NDVI 版のラン（[limited_analysis_results.md](limited_analysis_results.md) 8.6節・[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md) 7章）と同じセル・同じ fold・同じ乱数シード（42）・同じ決定木本数（300）
- 衛星＋公開GISデータは採用構成（変数セット `both`・建物高さ `mean`・水指数 `none`・土地被覆 GLC・人口 WorldPop2020）
- EM0 版のデータセットは、既存と行数（3,739,454）・列・`cell_id` が一致し、異なるのは `LST` と `LST_VALID_RATIO` の 2 列だけである。EM0 版の LST の有効画素は NDVI 版を包含するため、評価セルはすべて EM0 版でも有効だった
- 差の向きは **EM0 版 − NDVI 版**

### 5.2 モデル性能

Spatial CV の値は fold 平均、区間は fold ごとの対応のある差の 95% 補正 t 区間（自由度 4）である。

| シナリオ | 指標 | NDVI 版 | EM0 版 | 差 [95% 補正 t 区間] |
|---|---|---|---|---|
| 衛星＋公開GISデータ | Spatial CV・RF の R² | 0.8399 | 0.8159 | −0.0240 [−0.0353, −0.0127] |
| 衛星＋公開GISデータ | Spatial CV・線形回帰の R² | 0.7662 | 0.7391 | −0.0271 [−0.0387, −0.0154] |
| 衛星＋公開GISデータ | Spatial CV・RF の RMSE | 1.0554 | 1.0786 | +0.0232 [−0.0057, +0.0521] |
| 衛星＋公開GISデータ | ランダム分割・RF の R² | 0.8517 | 0.8333 | −0.0184 |
| 衛星データのみ | Spatial CV・RF の R² | 0.7528 | 0.7209 | −0.0319 [−0.0445, −0.0193] |
| 衛星データのみ | Spatial CV・線形回帰の R² | 0.6935 | 0.6670 | −0.0265 [−0.0387, −0.0143] |
| 衛星データのみ | Spatial CV・RF の RMSE | 1.3112 | 1.3279 | +0.0167 [−0.0079, +0.0413] |
| 衛星データのみ | ランダム分割・RF の R² | 0.7550 | 0.7245 | −0.0305 |

- **R² は両シナリオ・両モデルで 0.02〜0.03 下がり、区間は 0 を含まない。** RMSE の差は区間が 0 を含む
- 目的変数の分布（欠測除去後）は、衛星＋公開GISデータで平均 32.221 → 32.586 °C・標準偏差 2.639 → 2.515 °C、衛星データのみで 32.210 → 32.574 °C・2.652 → 2.530 °C だった。EM0 版は LST の散らばりが小さく、R² の低下の一部はこれによると考えられる（推定）

### 5.3 変数の寄与と順位

順位の Spearman 相関と上位 5 変数（衛星データのみは 3 変数）を示す。

| シナリオ | 寄与の指標 | 順位の Spearman 相関 | 上位の一致 |
|---|---|---|---|
| 衛星＋公開GISデータ | 平均 \|SHAP\| | 0.978 | **順番まで同じ**（`NDBI` → `LULC_BUILT_COV` → `ELEV_MEAN` → `POP_DEN_WORLDPOP2020` → `NDVI`） |
| 衛星＋公開GISデータ | Permutation 重要度 | 0.965 | 顔ぶれは同じ。`LULC_BUILT_COV` が 5 位 → 2 位 |
| 衛星＋公開GISデータ | 不純度重要度 | 0.991 | 顔ぶれは同じ。`NDBI` と `LULC_BUILT_COV` の 1・2 位が入れ替わる |
| 衛星＋公開GISデータ | 標準化係数（絶対値） | 0.807 | 顔ぶれが変わる。`NDVI` が 11 位 → 3 位 |
| 衛星データのみ | 4 指標すべて | 1.000 | `NDBI` → `NDWI` → `NDVI` で変わらない |

`NDVI` の値の変化は次のとおりである。

| シナリオ | 寄与の指標 | NDVI 版 | EM0 版 | 変化 |
|---|---|---|---|---|
| 衛星＋公開GISデータ | 平均 \|SHAP\| | 0.2373 | 0.1898 | −20% |
| 衛星＋公開GISデータ | Permutation 重要度 | 0.0825 | 0.0925 | +12% |
| 衛星＋公開GISデータ | 標準化係数 | +0.0257 | +0.1189 | 符号は正のまま増加 |
| 衛星データのみ | 平均 \|SHAP\| | 0.3202 | 0.2660 | −17% |
| 衛星データのみ | Permutation 重要度 | 0.1026 | 0.0933 | −9% |
| 衛星データのみ | 標準化係数 | −0.2631 | −0.2216 | 負のまま縮小 |

- 衛星＋公開GISデータでは、`NDBI` の平均 |SHAP| が 1.0410 → 0.8242 に下がり、`LULC_BUILT_COV` が 0.3716 → 0.5157 に上がった。順位は変わらない
- 衛星＋公開GISデータの標準化係数の `NDVI` の大きな変化は、`NDVI` が `NDBI`・土地被覆と強く相関すること（VIF。[limited_analysis_results.md](limited_analysis_results.md) 6章）による係数の不安定さを含むと考えられる（推定）

### 5.4 NDVI の SHAP 依存図の比較（目視）

各ランの `*_shap_dependence_NDVI.png` を NDVI 版と EM0 版で見比べた（数値化はしていない）。

| シナリオ | NDVI < 0.2（水域・裸地） | NDVI ≥ 0.2（植生域） |
|---|---|---|
| 衛星＋公開GISデータ | 両版とも強い負の寄与（最小 −2.5 前後）で、ほぼ変わらない | NDVI 版では NDVI が上がるにつれ寄与が +0.5 前後から −0.3 前後へ下がる（植生の冷却効果に見える傾き）。**EM0 版ではこの傾きがほぼ消え、0〜+0.2 前後で横ばいになる** |
| 衛星データのみ | 両版とも強い負の寄与で、ほぼ変わらない | 両版とも NDVI 0.75 以上で急に下がる形が残る。最小は −2.0 前後 → −1.6 前後に弱まる |

衛星＋公開GISデータの植生域での傾きの幅（約 0.8）は、4.3節の ΔLST の NDVI 0.2 → 0.85 での変化（約 0.85 °C）とほぼ同じ大きさである。**この傾きの相当部分は、LST の算出式に NDVI が入っていることで説明できる可能性がある**（推定）。一方で、EM0 の誤差が植生域の実際の冷却を見えなくした可能性も残り、本分析では区別できない（1.1節）。

## 6. 解釈と RQ1 での記述方針

### 6.1 解釈（たたき台）

- **寄与の順位は放射率の取り方によらず頑健である。** 平均 |SHAP| の上位は両シナリオとも順番まで同じで、衛星データのみでは 4 指標とも全く同じだった。1.1節の読み方に従えば、NDVI の二重利用で寄与の順位が水増しされている懸念は小さい
- **寄与の大きさ、特に植生域での NDVI の効き方は頑健でない。** 衛星＋公開GISデータでは、NDVI の植生域での負の傾きが EM0 版でほぼ消える。この傾きは植生の冷却効果として読める形だが、放射率の算出式に由来する部分を含みうる
- 水域・裸地（NDVI < 0.2）での NDVI の強い寄与と、衛星データのみでの高 NDVI 域の下がり方は、EM0 版でも残る
- R² の低下（約 0.03）と NDVI の平均 |SHAP| の低下（約 2 割）は、依存の除去によるのか EM0 の誤差によるのかを区別できない

### 6.2 RQ1 での記述方針（2026-11-13 研究者決定）

- **主たる LST は NDVI 版（SMW 法・NDVI 由来の放射率）のままとする。** S1 および多くの先行研究の構成と整合する。EM0 版を主たる LST にしない理由は 1.1節のとおり
- RQ1 では、変数の寄与の**順位**は放射率の算出方法によらず頑健であることを、本感度分析を根拠に記述する
- 一方で、**NDVI の寄与の大きさ、特に植生域で冷却効果に見える傾きは、放射率の算出方法に左右され、一部は LST の算出式に由来しうる**ことを、限界として明記する
- 植生の冷却効果の根拠として、NDVI の SHAP（寄与の大きさ・依存図の傾き）を単独で用いない

## 7. データと出力

| 区分 | パス |
|---|---|
| 再出力した LST・放射率（Git 管理外） | `data/satellite/lst_emissivity_sensitivity/{ndvi,em0}/2022/` |
| 出力タスクの記録 | `data/output/lst_emissivity_sensitivity/20220906_032358/export_tasks.json` |
| LST の差の集計（数値の正本） | `data/output/lst_emissivity_sensitivity/20220906_032358/lst_difference_results.json`・`lst_difference_by_ndvi_class.csv` |
| LST の差の図 | 同ディレクトリの `lst_difference_map.png`・`lst_difference_by_ndvi_class.png` |
| ランの比較（数値の正本） | 同ディレクトリの `run_comparison_results.json`・`run_comparison_metrics.csv`・`run_comparison_importance.csv`・`run_comparison_folds.csv` |
| EM0 版のラン | `data/output/limited/20220906_032358_common_evaluation_lst_em0/`・`data/output/satellite_only_cellbased/20220906_032358_common_evaluation_lst_em0/` |
| EM0 版のパラメータテーブル・データセット（Git 管理外） | `data/output/params_lst_em0/hanoi/30m/`・`data/output/datasets/dataset_{limited,satellite_only}_20220906_032358_lstem0_hanoi_30m.gpkg` |

再現手順:

```bash
python -m src.gee.gee_export_lst_emissivity_variants --observation-datetime 2022-09-06T03:23:58
# Drive から data/satellite/lst_emissivity_sensitivity/{ndvi,em0}/2022/ へ配置（手作業）
python -m src.analysis.lst_emissivity_sensitivity lst-diff --observation-datetime 2022-09-06T03:23:58
python -m src.analysis.urban_params --city hanoi --lst-file data/satellite/lst_emissivity_sensitivity/em0/2022/LST_Landsat8_20220906_032358Z.tif --scales 30 --output-dir data/output/params_lst_em0
# data/output/params/hanoi/30m/ から mask_roi・build_gba・road_osm・elev_fabdem・lulc_glc2022・ntl_viirs2023・pop_worldpop2020・pop_landscan2020・pop_landscan2023・idx_20220906_032358 を data/output/params_lst_em0/hanoi/30m/ へコピー
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited --tables idx_20220906_032358 lst_20220906_032358 --name limited_20220906_032358_lstem0 --params-dir data/output/params_lst_em0
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20220906_032358 lst_20220906_032358 --name satellite_only_20220906_032358_lstem0 --params-dir data/output/params_lst_em0
python -m src.analysis.analysis_rq3_satellite_only --dataset-path data/output/datasets/dataset_satellite_only_20220906_032358_lstem0_hanoi_30m.gpkg --output-dir data/output/satellite_only_cellbased/20220906_032358_common_evaluation_lst_em0 --evaluation-cells data/output/common_evaluation/20220906_032358/evaluation_cells_seed42.csv
python -m src.analysis.analysis_rq3_limited --dataset-path data/output/datasets/dataset_limited_20220906_032358_lstem0_hanoi_30m.gpkg --output-dir data/output/limited/20220906_032358_common_evaluation_lst_em0 --evaluation-cells data/output/common_evaluation/20220906_032358/evaluation_cells_seed42.csv
python -m src.analysis.lst_emissivity_sensitivity compare-runs --observation-datetime 2022-09-06T03:23:58 --pair limited {NDVI 版の results.json} {EM0 版の results.json} --pair satellite_only {NDVI 版の results.json} {EM0 版の results.json}
```

## 8. 次のステップ

- 修士論文の RQ1 の章で、6.2節の方針に沿って NDVI の寄与と限界を記述する
- 植生の効果を NDVI 以外の変数（土地被覆の樹木被覆率など）で示せるかは未検討である。衛星＋公開GISデータでは `LULC_TREE_COV` の寄与が小さく（平均 |SHAP| 0.02 前後）、現状では代わりの根拠にならない
- ASTER GEDv3 の異常値（4.5節）の確認、EM0 以外の NDVI に依存しない放射率（土地被覆クラス別の放射率・Sentinel-2 Fcover など）による確認は行っていない。前者は依存を `LULC_*` へ移すだけで、後者は別センサの植生量に依存するため、いずれも NDVI の二重利用の問いへの答えは限られる（1.1節）
