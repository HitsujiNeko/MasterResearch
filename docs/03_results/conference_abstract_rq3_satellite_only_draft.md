# 学会用アブストラクト下書き（衛星指標のみ条件の初期分析）

**最終更新**: 2026-04-10  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [analysis_rq3_satellite_only_guide.md](../02_methods/analysis_rq3_satellite_only_guide.md), [satellite_only_20230707_initial_run.md](satellite_only_20230707_initial_run.md), [previous_studies_report.md](../04_archive/previous_studies_report.md)  
**前提知識**: データ制約下での有効性評価の目的、Satellite Only 初期実行結果、LST 算出フロー

---

## 1. この下書きの位置づけ

本ファイルは、国際学会向けアブストラクトの下書きである。  

日本語文と英語文は、比較しやすいように各段落ごとに交互に配置する。

---

## 2. Methodology 記述前のコード確認メモ

### 2.1 確認対象

- `src/gee/gee_calc_LST.py`
- `src/gee/gee_calc_satellite_indices.py`
- `src/analysis/build_satellite_only_dataset.py`
- `src/analysis/analysis_rq3_satellite_only.py`

### 2.2 確認結果

- `gee_calc_LST.py` は、ROI を読み込み、Landsat 8 から LST を算出し、ROI を対象に GeoTIFF を出力する構成になっている。
- `gee_calc_satellite_indices.py` は、NDVI・NDBI・NDWI を算出し、2026-04-09 時点で `image.clip(roi)` を通した上で Drive 出力するため、LST 側と出力範囲の整合が取れている。
- `build_satellite_only_dataset.py` は、LST と指標ラスタを同一観測時刻で対応付け、グリッド整合を確認した上でピクセル単位 CSV を作成している。
- `analysis_rq3_satellite_only.py` は、random split と Spatial CV の両方で Linear Regression と Random Forest を評価し、SHAP を出力する構成になっている。

### 2.3 本タスクに対する判断

アブストラクトの Methodology を記述する上で支障となる重大なロジック誤りは、今回の確認範囲では見当たらなかった。  
ただし、この判断はコード読解と既存出力結果の整合確認に基づくものであり、GEE 実行そのものの再テストまでは行っていない。

---

## 3. タイトル案

### 3.1 タイトル案 A

日本語: データ制約下の都市熱環境分析に向けた衛星由来指標ベースラインの評価: ベトナム・ハノイを対象とした複数観測日の初期結果  
English: Evaluating a Satellite-Derived Baseline for Urban Thermal Analysis under Data Constraints: Initial Multi-Date Results from Hanoi, Vietnam

### 3.2 タイトル案 B

日本語: 衛星由来指標のみで都市地表面温度をどこまで説明できるか: ベトナム・ハノイを対象とした複数観測日の初期評価  
English: How Far Can Satellite-Derived Indicators Alone Explain Urban Land Surface Temperature? An Initial Multi-Date Assessment in Hanoi, Vietnam

---

## 4. Abstract
日本語: 途上国都市では、建物や道路、人口など都市形態に関する詳細な地理情報システムデータが未整備であることが多く、都市熱環境の定量分析には大きな制約がある。本研究は、ベトナム・ハノイを対象として、衛星由来指標のみで地表面温度（LST）をどこまで説明できるかを検証し、データ制約下での分析可能性を評価した。Google Earth Engine を用いて Landsat 8 から LST、正規化植生指数（NDVI）、正規化市街地指数（NDBI）、正規化水指数（NDWI）を算出し、2023年7月と2024年11月の3観測を分析対象とした。各観測について品質管理後のピクセルから無作為に 100,000 ピクセルを抽出し、重回帰分析と Random Forest を random split および空間交差検証で比較した。Random Forest はすべての観測で重回帰分析を上回り、空間交差検証後も R² は 0.60 以上を維持した。また、NDBI は一貫して最も強い昇温側要因であり、NDVI と NDWI は冷却側要因として機能した。以上より、詳細な地理情報システムデータが利用できない段階でも、衛星由来指標のみで LST 分布のかなりの部分を説明できることが示された。本研究は、公開地理情報や測量データを段階的に導入する今後の比較分析に向けた実用的なベースラインを提示する。
English: In many cities in the Global South, detailed geographic information system data on urban forms such as buildings, roads, and population remain incomplete or unavailable, which constrains quantitative analysis of urban thermal environments. This study examines how far land surface temperature (LST) can be explained using satellite-derived indicators alone in Hanoi, Vietnam, and evaluates the feasibility of analysis under data-constrained conditions. Using Google Earth Engine, LST, the Normalized Difference Vegetation Index (NDVI), the Normalized Difference Built-up Index (NDBI), and the Normalized Difference Water Index (NDWI) were derived from Landsat 8 imagery, and three observations from July 2023 and November 2024 were analyzed. For each observation, 100,000 pixels were randomly sampled after quality control, and Multiple Linear Regression and Random Forest were compared under both random split and spatial cross-validation. Random Forest outperformed Multiple Linear Regression in all observations and retained R² values above 0.60 after spatial cross-validation. NDBI consistently emerged as the strongest warming-related factor, whereas NDVI and NDWI acted as cooling-related factors. These results suggest that a substantial share of LST variability can be explained using satellite-derived indicators alone, even before detailed geographic information system data become available. The study provides a practical baseline for subsequent comparisons that incorporate open geographic information and survey-based data in a staged manner.

---

## 5. Introduction

日本語: 都市のヒートアイランド現象を理解し、緩和策を設計するためには、LST と都市構造の関係を空間的に評価することが重要である。既往研究では、Random Forest を用いた都市構造要因の重要度評価 (Sun et al., 2019; Ref. 3) や、熱帯都市における回帰分析と機械学習の併用 (Garzon et al., 2021; Ref. 5) が報告されている。一方で、ベトナムを含む多くの途上国都市では、建物形状や道路ネットワークを網羅的に記述した高品質 GIS データを入手することが難しい。  
English: Spatial evaluation of the relationship between LST and urban structure is essential for understanding urban heat islands and designing mitigation strategies. Previous studies have reported the use of Random Forest to assess the importance of urban-form variables (Sun et al., 2019; Ref. 3) and the combination of regression analysis with machine-learning algorithms in tropical cities (Garzon et al., 2021; Ref. 5). However, in many cities in developing countries, including Vietnam, it remains difficult to obtain high-quality GIS data that comprehensively describe building geometry and road networks.

日本語: さらに、ベトナムの Da Nang を対象とした研究では、NDVI や NDBI のみでは建物高さや人口密度を十分に表現できないことが指摘されており (Le Ngoc Hanh and Tran Thi An, 2025; Ref. 2)、近傍効果や配置効果を含む都市構造の重要性も議論されている (Osborne and Alvares-Sanches, 2019; Ref. 4)。本研究では、こうした制約と課題を踏まえ、データ可用性の異なる複数条件を段階的に比較する枠組みを採用している。本稿で報告するのは、その第一段階にあたる衛星指標のみ条件の初期分析であり、3 つの観測日時を用いて、衛星由来指標のみで LST をどこまで説明できるかを検証する。  
English: In addition, a study of Da Nang, Vietnam, noted that NDVI and NDBI alone are insufficient to represent building height and population density (Le Ngoc Hanh and Tran Thi An, 2025; Ref. 2), while the importance of neighborhood and configuration effects has also been discussed in the literature (Osborne and Alvares-Sanches, 2019; Ref. 4). Against these constraints and research gaps, this study adopts a staged framework that compares multiple analytical conditions with different levels of data availability. The present abstract reports the first-stage satellite-only baseline, which examines how far LST can be explained using satellite-derived indicators alone across three observation dates.

日本語: したがって、本稿の位置づけは、既往研究のように多様な都市構造変数を直ちに導入する段階ではなく、詳細 GIS データが不足している都市でも成立する再現可能な分析ベースラインを提示する点にある。そのため、本稿では追加データを含む後続条件の結論には踏み込まず、現時点で確認できた事実ベースの結果と今後の拡張方針に焦点を当てる。  
English: Accordingly, the contribution of this abstract is not to introduce the full range of urban-structure variables used in previous studies from the outset, but to establish a reproducible analytical baseline that remains feasible even when detailed GIS data are unavailable. It therefore does not claim conclusions for later-stage conditions with additional data sources and instead focuses on the fact-based findings currently available and on directions for future extension.

### 5.1 図表案

- 図1案: 研究全体の 3 シナリオ構成図


---

## 6. Methodology

日本語: LST は Google Earth Engine 上で Landsat 8 データから算出し、Ermida et al. (2020; Ref. 1) の手法を用いた。算出フローは以下のとおりである。  
- Landsat 8 の熱赤外 TOA データを用いて輝度温度を算出する。  
- 同じシーンから計算した NDVI を用いて、植生被覆率と地表面放射率を推定する。  
- 水蒸気量に応じた補正係数を適用し、地表面温度へ変換する。  
衛星指標としては、同じ Landsat 8 シーンから NDVI、NDBI、NDWI を別途算出し、LST と同一の解析範囲で出力した。  
English: LST was derived from Landsat 8 imagery in Google Earth Engine using the method of Ermida et al. (2020; Ref. 1). The calculation flow was as follows.  
- Brightness temperature was derived from the Landsat 8 thermal TOA data.  
- Vegetation cover and surface emissivity were estimated from NDVI computed from the same scene.  
- Water-vapor-dependent correction coefficients were applied to derive land surface temperature.  
As satellite-derived explanatory variables, NDVI, NDBI, and NDWI were computed separately from the same Landsat 8 scene and exported over the same analysis domain as the LST data.

日本語: 研究対象領域は、ベトナム・ハノイ市の行政区画ポリゴンを用いて定義した ROI 全体である。  
English: The study area was the full ROI defined by the administrative boundary polygon of Hanoi, Vietnam.

日本語: 観測日時の選定では、2023-2024 年の候補シーンを比較したうえで、`2023-07-07T03:23:29Z`、`2023-07-23T03:23:09Z`、`2024-11-30T03:23:36Z` を採用した。各観測について LST ラスタと指標ラスタを同一グリッド上で対応付け、`LST = 15-65°C`、各指標 = `-1.1 to 1.1` の品質条件を満たすピクセルのみを分析対象とした。  
English: Observation times were selected by comparing candidate scenes from 2023-2024, and `2023-07-07T03:23:29Z`, `2023-07-23T03:23:09Z`, and `2024-11-30T03:23:36Z` were adopted for analysis. For each observation, the LST and index rasters were matched on the same grid, and only pixels satisfying the quality conditions of `LST = 15-65°C` and each index = `-1.1 to 1.1` were retained for analysis.

日本語: モデル比較では、説明変数を NDVI、NDBI、NDWI、目的変数を LST とし、Multiple Linear Regression と Random Forest を適用した。この構成は、都市熱環境研究における Random Forest の変数重要度評価 (Sun et al., 2019; Ref. 3) と、回帰分析および機械学習の併用 (Garzon et al., 2021; Ref. 5) を参考にした。評価は random split と Spatial CV の両方で行い、後者では経度・緯度を分位で区切った空間ブロックを用いた 5-fold 検証により、空間自己相関による過大評価を抑えた。  
English: For model comparison, NDVI, NDBI, and NDWI were used as explanatory variables and LST as the target variable, and both Multiple Linear Regression and Random Forest were applied. This setup was informed by prior urban thermal studies that used Random Forest to assess variable importance (Sun et al., 2019; Ref. 3) and that combined regression analysis with machine-learning algorithms in tropical cities (Garzon et al., 2021; Ref. 5). Performance was evaluated under both random split and spatial cross-validation, with the latter using 5-fold validation based on quantile-defined spatial blocks of longitude and latitude in order to reduce overestimation caused by spatial autocorrelation.

日本語: さらに、Random Forest の解釈のために SHAP を用い、各指標が予測値をどの方向にどの程度変化させるかを確認した。  
English: In addition, SHAP was used to interpret the Random Forest model and to examine the direction and magnitude of each indicator's contribution to the predictions.

### 6.1 図表案
- 図2案: Hanoi ROI と対象観測日の概略図
- 図3案: LST 算出からデータセット作成、モデル評価までの処理フロー
- 表1案: 使用データ、観測日時、画素数、評価条件の一覧

---

## 7. Results

日本語: 品質管理後に残った分析対象は、`2023-07-07` が `2,104,665` ピクセル、`2023-07-23` が `3,213,377` ピクセル、`2024-11-30` が `3,779,821` ピクセルであった。LST の平均値はそれぞれ `35.7646°C`、`36.0930°C`、`24.9937°C` であり、季節差を反映していた。random split において、Random Forest の `R²` は各日で `0.7009`、`0.6445`、`0.7180` を示し、Linear Regression の `0.5310`、`0.5401`、`0.5946` を一貫して上回った。  
English: After quality control, the analysis datasets contained `2,104,665` pixels for `2023-07-07`, `3,213,377` pixels for `2023-07-23`, and `3,779,821` pixels for `2024-11-30`. The mean LST values were `35.7646°C`, `36.0930°C`, and `24.9937°C`, respectively, reflecting seasonal differences. Under random split, the Random Forest `R²` values were `0.7009`, `0.6445`, and `0.7180`, consistently exceeding the Linear Regression values of `0.5310`, `0.5401`, and `0.5946`.

日本語: Spatial CV では、Random Forest の `R² mean` は `0.6759`、`0.6032`、`0.6965` であり、Linear Regression の `0.4929`、`0.4902`、`0.5744` を各観測で上回った。random split からの低下は存在するものの、その幅は極端ではなく、衛星由来指標のみの条件で得られた説明力が単なる近接画素間のリークだけで説明されるものではないことを示唆する。  
English: Under spatial cross-validation, the Random Forest `R² mean` values were `0.6759`, `0.6032`, and `0.6965`, again exceeding the Linear Regression values of `0.4929`, `0.4902`, and `0.5744` for each observation. Although performance decreased relative to random split, the decline was not extreme, suggesting that the explanatory power observed using satellite-derived indicators alone cannot be attributed solely to leakage among neighboring pixels.

日本語: 変数重要度と SHAP の結果を総合すると、3 観測すべてで NDBI が最も支配的な昇温側要因であり、NDVI と NDWI は冷却側要因として働いた。mean absolute SHAP における NDBI は `0.8327`、`1.2505`、`0.8035` で、各観測において NDVI と NDWI を上回った。  
English: Integrating the feature-importance and SHAP results, NDBI emerged as the dominant warming-related factor in all three observations, while NDVI and NDWI acted as cooling-related factors. The mean absolute SHAP values for NDBI were `0.8327`, `1.2505`, and `0.8035`, exceeding those of NDVI and NDWI in each observation.

日本語: 一方で、NDVI と NDWI の VIF は 3 観測を通じて一貫して高く、線形回帰係数の厳密な順位解釈には注意が必要である。したがって、本稿では線形係数の大きさよりも、Random Forest と SHAP に基づく解釈を優先する。  
English: At the same time, the VIF values for NDVI and NDWI remained high across the three observations, indicating that strict ranking of the linear coefficients should be interpreted with caution. Therefore, this draft prioritizes interpretation based on Random Forest and SHAP rather than on the absolute magnitudes of the linear coefficients.

### 7.1 図表案

- 表2案: random split と Spatial CV の性能比較表
- 図4案: Linear Regression と Random Forest の性能比較棒グラフ
- 図5案: RF importance、Permutation importance、SHAP を並べた重要度比較図

---

## 8. Conclusion

日本語: 本稿で得られた初期結果は、詳細 GIS データを用いなくても、衛星由来指標のみでハノイの LST 分布のかなりの部分を複数観測日にわたって説明できることを示している。特に Random Forest は 3 観測すべてで Spatial CV 後も `R² mean > 0.60` を概ね維持しており、この条件が実用的なベースラインとして成立する可能性が高い。  
English: The initial results presented here indicate that a substantial share of LST variability in Hanoi can be explained across multiple observation dates even without detailed GIS data, using satellite-derived indicators alone. In particular, Random Forest retained approximately `R² mean > 0.60` after spatial cross-validation in all three observations, suggesting that this condition can serve as a practical analytical baseline.

日本語: 現段階での貢献は、研究全体の最終結論を提示することではなく、データ制約下でも再現可能な分析手順を複数観測日に対して先に成立させた点にある。これは、今後の公開 GIS データ併用条件や測量 GIS を含む条件との比較に向けた基礎として重要である。  
English: At this stage, the main contribution is not the final conclusion of the entire project, but rather the establishment of a reproducible analytical workflow across multiple observation dates that remains feasible under data constraints. This provides an important foundation for later comparison with conditions that incorporate open GIS data and survey-based GIS.

日本語: 今後は、OpenStreetMap や Microsoft GlobalMLBuildingFootprints などの公開 GIS データを導入し、さらに測量 GIS を含む条件と比較する予定である。また、今回の 3 観測で確認された関係が他の日付や季節でも維持されるかを検証する。  
English: Future work will introduce open GIS data sources such as OpenStreetMap and Microsoft GlobalMLBuildingFootprints and then compare the results with a condition that also includes survey-based GIS. The analysis will also test whether the relationships identified in these three observations are maintained across additional dates and seasons.

### 8.1 図表案

- 図6案: Satellite Only → Limited → Full の研究拡張ロードマップ

---

## 9. Keywords

- 日本語: 地表面温度 / English: Land surface temperature
- 日本語: 衛星指標 / English: Satellite-derived indicators
- 日本語: データ制約 / English: Data-constrained conditions
- 日本語: ハノイ / English: Hanoi
- 日本語: 空間交差検証 / English: Spatial cross-validation

---

## 10. References

1. Ermida, S. L., Soares, P., Mantas, V., Gottsche, F.-M., & Trigo, I. F. (2020). Google Earth Engine open-source code for land surface temperature estimation from the Landsat series. *Remote Sensing, 12*(9), 1471. https://doi.org/10.3390/rs12091471
2. Le Ngoc Hanh, & Tran Thi An. (2025). Assessment of temperature change in Da Nang City, Vietnam, using remote sensing and cloud-computing approach. *The GIS-IDEAS Journal, 1*(3), 16-28.
3. Sun, Y., Gao, C., Li, J., Wang, R., & Liu, J. (2019). Quantifying the effects of urban form on land surface temperature in subtropical high-density urban areas using machine learning. *Remote Sensing, 11*(8), 959. https://doi.org/10.3390/rs11080959
4. Osborne, P. E., & Alvares-Sanches, T. (2019). Quantifying how landscape composition and configuration affect urban land surface temperatures using machine learning and neutral landscapes. *Computers, Environment and Urban Systems, 76*, 80-90. https://doi.org/10.1016/j.compenvurbsys.2019.04.003
5. Garzon, J., Molina, I., Velasco, J., & Calabia, A. (2021). A remote sensing approach for surface urban heat island modeling in a tropical Colombian city using regression analysis and machine learning algorithms. *Remote Sensing, 13*(21), 4256. https://doi.org/10.3390/rs13214256

---

## 11. 仕上げ時の注意

- 他の分析条件の結果が既に得られているかのような表現は避ける。
- SHAP の解釈は寄与方向の説明に留め、因果関係として断定しない。
