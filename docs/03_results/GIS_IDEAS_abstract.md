# GIS-IDEAS 学会用アブストラクト下書き（衛星指標のみ条件の初期分析）

**最終更新**: 2026-04-21  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [analysis_rq3_satellite_only_guide.md](../02_methods/analysis_rq3_satellite_only_guide.md), [satellite_only_20230707_initial_run.md](satellite_only_20230707_initial_run.md), [previous_studies_report.md](../04_archive/previous_studies_report.md)  
**前提知識**: データ制約下での有効性評価の目的、Satellite Only 初期実行結果、LST 算出フロー

このドキュメントは2026年9月の学会 GIS-IDEAS 用に作成した研究のアブストラクトであり、
2026-04-16時点での衛星指標のみ条件の初期分析結果をもとに、アブストラクトの構成案と内容案をまとめたものである。


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

日本語: ベトナム、ハノイを対象としたデータ制約下の都市熱環境分析における衛星由来指標の有効性評価
English: Evaluating the Usefulness of Satellite-Derived Indicators for Urban Thermal Analysis under Data Constraints in Hanoi, Vietnam

### 3.2 タイトル案 B

日本語: 衛星由来指標のみで都市地表面温度をどこまで説明できるか: ベトナム・ハノイを対象とした複数観測日の評価  
English: How Far Can Satellite-Derived Indicators Alone Explain Urban Land Surface Temperature A Multi-Date Assessment in Hanoi, Vietnam

---

## 4. Abstract
日本語: 途上国都市では、建物や道路、人口など都市形態に関する詳細な地理情報システムデータが未整備であることが多く、都市熱環境の定量分析には大きな制約がある。本研究は、ベトナム・ハノイを対象として、衛星由来指標のみで地表面温度（LST）をどこまで説明できるかを検証し、データ制約下での分析可能性を評価した。Google Earth Engine を用いて Landsat 8 から LST、正規化植生指数（NDVI）、正規化市街地指数（NDBI）、正規化水指数（NDWI）を算出し、2023年と2024年において、データ品質を確保できた3観測を分析対象とした。各観測について重回帰分析と Random Forest を random split および空間交差検証で比較した。Random Forest はすべての観測で重回帰分析を上回り、空間交差検証後も R² は 0.60 以上を維持した。また、NDBI は一貫して最も強い昇温側要因であり、NDVI と NDWI は冷却側要因として機能した。以上より、詳細な地理情報システムデータが利用できない条件でも、衛星由来指標のみで LST 分布を一定程度説明できることが示された。
English: In many cities in the Global South, detailed geographic information system data on urban forms such as buildings, roads, and population remain incomplete or unavailable, which constrains quantitative analysis of urban thermal environments. This study examines how far land surface temperature (LST) can be explained using satellite-derived indicators alone in Hanoi, Vietnam, and evaluates the feasibility of analysis under data-constrained conditions. Using Google Earth Engine, we calculated LST, Normalized Numerical Growth Index (NDVI), Normalized Urban Area Index (NDBI), and Normalized Water Index (NDWI) from Landsat 8. Three observations for 2023 and 2024, for which data quality could be ensured, were selected for analysis. For each observation, 100,000 pixels were randomly sampled after quality control, and Multiple Linear Regression and Random Forest were compared under both random split and spatial cross-validation. Random Forest outperformed Multiple Linear Regression in all observations and retained R² values above 0.60 after spatial cross-validation. NDBI consistently emerged as the strongest warming-related factor, whereas NDVI and NDWI acted as cooling-related factors. These results suggest that a substantial share of LST variability can be explained using satellite-derived indicators alone under data-constrained conditions. 

---

## 5. Introduction

日本語: 都市のヒートアイランド現象を理解し、緩和策を設計するためには、LST と都市構造の関係を空間的に評価することが重要である。既往研究では、Random Forest を用いた都市構造要因の重要度評価 (Sun et al., 2019) や、熱帯都市における回帰分析と機械学習の併用 (Garzon et al., 2021) が報告されている。一方で、ベトナムを含む多くの途上国都市では、建物形状や道路ネットワークを網羅的に記述した高品質 GIS データを入手することが難しい。  
English: Spatial evaluation of the relationship between LST and urban structure is essential for understanding urban heat islands and designing mitigation strategies. Previous studies have reported the use of Random Forest to assess the importance of urban-form variables (Sun et al., 2019) and the combination of regression analysis with machine-learning algorithms in tropical cities (Garzon et al., 2021). However, in many cities in developing countries, including Vietnam, it remains difficult to obtain high-quality GIS data that comprehensively describe building geometry and road networks.

日本語: さらに、ベトナムの Da Nang を対象とした研究では、NDVI や NDBI のみでは建物高さや人口密度を十分に表現できないことが指摘されており (Le Ngoc Hanh & Tran Thi An, 2025)、近傍効果や配置効果を含む都市構造の重要性も議論されている (Osborne & Alvares-Sanches, 2019)。本研究では、こうした制約と課題を踏まえ、データ可用性の異なる条件の比較を視野に入れつつ、本稿では 3 つの観測日時を用いて、衛星由来指標のみで LST をどこまで説明できるかを検証する。  
English: In addition, a study of Da Nang, Vietnam, noted that NDVI and NDBI alone are insufficient to represent building height and population density (Le Ngoc Hanh & Tran Thi An, 2025), while the importance of neighborhood and configuration effects has also been discussed in the literature (Osborne & Alvares-Sanches, 2019). Against these constraints and research gaps, this study considers later comparison across conditions with different levels of data availability, while the present abstract examines how far LST can be explained using satellite-derived indicators alone across three observation dates.

日本語: したがって、本稿の位置づけは、既往研究のように多様な都市構造変数を直ちに導入するのではなく、詳細 GIS データが不足している条件下で得られた事実ベースの結果を示す点にある。そのため、本稿では追加データを含む他条件の結論には踏み込まず、今回確認できた結果と今後の拡張方針に焦点を当てる。  
English: Accordingly, the contribution of this abstract is not to introduce the full range of urban-structure variables used in previous studies, but to present fact-based results obtained under conditions where detailed GIS data are unavailable. It therefore does not claim conclusions for other conditions with additional data sources and instead focuses on the findings confirmed here and on directions for future extension.

### 5.1 図表案
なし

---

## 6. Methodology

日本語: LST は Google Earth Engine（Google Earth Engine, n.d.）上で Landsat 8 データから算出し、Ermida et al. (2020) の手法を用いた。算出フローは以下のとおりである。  
- Landsat 8 の熱赤外 TOA データを用いて輝度温度を算出する。  
- 同じシーンから計算した NDVI を用いて、植生被覆率と地表面放射率を推定する。  
- 水蒸気量に応じた補正係数を適用し、地表面温度へ変換する。  
衛星指標としては、同じ Landsat 8 シーンから NDVI、NDBI、NDWI を別途算出し、LST と同一の解析範囲で出力した。定義式は以下のとおりである。  
- NDVI = (NIR - Red) / (NIR + Red)  
- NDBI = (SWIR - NIR) / (SWIR + NIR)  
- NDWI = (Green - NIR) / (Green + NIR)  
English: LST was derived from Landsat 8 imagery in Google Earth Engine (Google Earth Engine, n.d.) using the method of Ermida et al. (2020). The calculation flow was as follows.  
- Brightness temperature was derived from the Landsat 8 thermal TOA data.  
- Vegetation cover and surface emissivity were estimated from NDVI computed from the same scene.  
- Water-vapor-dependent correction coefficients were applied to derive land surface temperature.  
As satellite-derived explanatory variables, NDVI, NDBI, and NDWI were computed separately from the same Landsat 8 scene and exported over the same analysis domain as the LST data. Their definitions were as follows.  
- NDVI = (NIR - Red) / (NIR + Red)  
- NDBI = (SWIR - NIR) / (SWIR + NIR)  
- NDWI = (Green - NIR) / (Green + NIR)

日本語: 研究対象領域（ROI）は、図-1に示すベトナム・ハノイ市である。  
English: The research area of ​​interest (ROI) is Hanoi, Vietnam, as shown in Figure 1.

日本語: ベトナムでは雲に覆われる日が多く、候補シーンの多くで雲マスク後の有効画素が不足したため、2023-2024 年の候補シーンについて、ROI のカバー率と雲マスク後の LST・指標の有効画素状況を比較したうえで、`2023-07-07T03:23:29Z`、`2023-07-23T03:23:09Z`、`2024-11-30T03:23:36Z` の３枚の画像を採用し、分析に用いた。LST 算出からデータセット作成、モデル評価までの処理フローは Fig. 2 に示す。  
English: Because many days in Vietnam are heavily cloud-covered and many candidate scenes did not retain enough valid pixels after cloud masking, candidate scenes from 2023-2024 were screened by comparing ROI coverage and the valid-pixel conditions of the LST and index outputs after cloud masking. Based on this screening, `2023-07-07T03:23:29Z`, `2023-07-23T03:23:09Z`, and `2024-11-30T03:23:36Z` were adopted for analysis. The overall workflow from LST derivation to model evaluation is shown in Fig. 2.
日本語: モデル比較では、説明変数を NDVI、NDBI、NDWI、目的変数を LST とし、Multiple Linear Regression と Random Forest を適用した。この構成は、都市熱環境研究における Random Forest の変数重要度評価 (Sun et al., 2019) と、回帰分析および機械学習の併用 (Garzon et al., 2021) を参考にした。評価は random split と Spatial CV の両方で行い、後者では経度・緯度を分位で区切った空間ブロックを用いた 5-fold 検証により、空間自己相関による過大評価を抑えた。  
English: For model comparison, NDVI, NDBI, and NDWI were used as explanatory variables and LST as the target variable, and both Multiple Linear Regression and Random Forest were applied. This setup was informed by prior urban thermal studies that used Random Forest to assess variable importance (Sun et al., 2019) and that combined regression analysis with machine-learning algorithms in tropical cities (Garzon et al., 2021). Performance was evaluated under both random split and spatial cross-validation, with the latter using 5-fold validation based on quantile-defined spatial blocks of longitude and latitude in order to reduce overestimation caused by spatial autocorrelation.

日本語: さらに、Random Forest の解釈のために SHAP を用い、各指標が予測値をどの方向にどの程度変化させるかを確認した。  
English: In addition, SHAP was used to interpret the Random Forest model and to examine the direction and magnitude of each indicator's contribution to the predictions.

### 6.1 図表案
- Fig. 1. 日本語: ハノイ市の研究対象領域（ROI） / English: Study area (ROI) in Hanoi, Vietnam.
- Fig. 2. 日本語: LST 算出からデータセット作成、モデル評価までの処理フロー / English: Workflow from LST derivation to dataset construction and model evaluation.
- Table 1. 日本語: 各観測日における LST および衛星指標の基礎統計 / English: Descriptive statistics of LST and satellite-derived indices for each observation.
  メモ候補: `docs/03_results/table1_word.tsv`, `data/output/gee_search_satellite_data_results.csv`, `data/csv/analysis/satellite_only_multidate_summary.csv`

---

## 7. Results

日本語: LST の平均値は `2023-07-07`、`2023-07-23`、`2024-11-30` でそれぞれ `35.7646°C`、`36.0930°C`、`24.9937°C` であり、対応する NDVI、NDBI、NDWI の平均値とあわせて Table 1 に整理した。`2023-07-07` と `2023-07-23` はいずれも約 `36°C` の近い水準を示した一方、`2024-11-30` は明確に低く、観測日の季節差が基礎統計にも表れた。3 観測日の LST 分布の違いは、バイオリンプロットとして Fig. 3 に示す。random split においては、Random Forest の `R²` は各日で `0.7009`、`0.6445`、`0.7180` を示し、Linear Regression の `0.5310`、`0.5401`、`0.5946` を一貫して上回った。この random split と Spatial CV の性能比較は Table 2 に整理し、モデル間の性能差は Fig. 4 に示す。  
English: The mean LST values for `2023-07-07`, `2023-07-23`, and `2024-11-30` were `35.7646°C`, `36.0930°C`, and `24.9937°C`, respectively, and together with the mean NDVI, NDBI, and NDWI values they are summarized in Table 1. While `2023-07-07` and `2023-07-23` showed similarly high mean temperatures of around `36°C`, `2024-11-30` was clearly cooler, indicating that seasonal differences were already visible in the descriptive statistics. These differences in LST distribution across the three observations are shown as a violin plot in Fig. 3. Under random split, the Random Forest `R²` values were `0.7009`, `0.6445`, and `0.7180`, consistently exceeding the Linear Regression values of `0.5310`, `0.5401`, and `0.5946`. The comparison between random split and spatial cross-validation is summarized in Table 2, and the performance gap between models is shown in Fig. 4.

日本語: Spatial CV では、Random Forest の `R² mean` は `0.6759`、`0.6032`、`0.6965` であり、Linear Regression の `0.4929`、`0.4902`、`0.5744` を各観測で上回った。random split からの低下は存在するものの、その幅は極端ではなく、空間的に独立した条件でも一定の説明力が保たれた。したがって、衛星由来指標のみの条件で得られた説明力は、単なる近接画素間のリークだけで説明されるものではないことが示唆される。  
English: Under spatial cross-validation, the Random Forest `R² mean` values were `0.6759`, `0.6032`, and `0.6965`, again exceeding the Linear Regression values of `0.4929`, `0.4902`, and `0.5744` for each observation. Although performance decreased relative to random split, the decline was not extreme, and a meaningful level of explanatory power was retained under spatially independent evaluation. This suggests that the explanatory performance obtained using satellite-derived indicators alone cannot be attributed solely to leakage among neighboring pixels.

日本語: 線形回帰係数と Random Forest 重要度を比較すると、3 観測すべてで NDBI が支配的な昇温側要因として位置づけられ、NDVI と NDWI がそれに続いた。これらの重要度比較は Fig. 5 に示す。さらに SHAP の結果でも、NDBI の寄与は全観測で一貫して大きく、mean absolute SHAP は `0.8327`、`1.2505`、`0.8035` を示し、各観測において NDVI と NDWI を上回った。SHAP による寄与の大きさと方向は Fig. 6 に示す。  
English: Comparing the linear coefficients and Random Forest importance, NDBI was positioned as the dominant warming-related factor in all three observations, followed by NDVI and NDWI. These comparisons of feature importance are shown in Fig. 5. The SHAP results likewise indicated that the contribution of NDBI remained consistently large across all observations, with mean absolute SHAP values of `0.8327`, `1.2505`, and `0.8035`, exceeding those of NDVI and NDWI in each case. The magnitude and direction of the SHAP-based contributions are shown in Fig. 6.

日本語: ただし、Fig. 5 に含まれる線形回帰係数の解釈については、NDVI と NDWI の VIF が 3 観測を通じて一貫して高かったため、多重共線性の影響に注意が必要である。そのため、本稿では線形係数の厳密な順位づけは補助的に扱い、主な解釈は Random Forest と SHAP に基づいて行う。  
English: However, the linear coefficients included in Fig. 5 should be interpreted with caution because the VIF values for NDVI and NDWI remained consistently high across the three observations, indicating possible multicollinearity. For this reason, the strict ranking of the linear coefficients is treated as supplementary, and the main interpretation is based on Random Forest and SHAP.

### 7.1 図表案

- Table 2. 日本語: random split と空間交差検証におけるモデル性能比較 / English: Model performance under random split and spatial cross-validation.
- Fig. 3. 日本語: 3観測日におけるLST分布の比較 / English: Comparison of LST distributions across the three observations.
  メモ候補: `data/csv/analysis/satellite_only_multidate_lst_violin.png`, `data/csv/analysis/satellite_only_20230707_20230707_032329Z_sample_100000.csv`, `data/csv/analysis/satellite_only_20230723_20230723_032309Z_sample_100000.csv`, `data/csv/analysis/satellite_only_20241130_20241130_032336Z_sample_100000.csv`, `data/csv/analysis/satellite_only_multidate_summary.csv`, `src/analysis/visualize_lst_multidate.py`
- Fig. 4. 日本語: 重回帰分析と Random Forest の性能比較 / English: Performance comparison between Multiple Linear Regression and Random Forest.
- Fig. 5. 日本語: 線形回帰係数と Random Forest 重要度の比較 / English: Comparison of linear coefficients and Random Forest importance across observations.
- Fig. 6. 日本語: SHAP による指標寄与の比較 / English: Comparison of SHAP-based feature contributions across observations.

---

## 8. Conclusion

日本語: 本研究で得られた結果は、 GIS データを用いなくても、衛星由来指標のみでハノイの LST 分布を複数観測日にわたって一定程度説明できることを示している。特に Random Forest は 3 観測すべてで Spatial CV 後も `R² mean > 0.60` を概ね維持しており、この条件は今後ほかのデータ条件と比較する際の有効な参照点となる可能性が高い。  
English: The results presented here indicate that a substantial share of LST variability in Hanoi can be explained across multiple observation dates even without detailed GIS data, using satellite-derived indicators alone. In particular, Random Forest retained approximately `R² mean > 0.60` after spatial cross-validation in all three observations, suggesting that this condition can provide a useful reference point for comparison with other data conditions.

日本語: 本稿の主な貢献は、研究全体の最終結論を提示することではなく、データ制約下でも再現可能な分析手順を複数観測日に適用し、その説明力を示した点にある。これは、今後の研究方針であるオープンソースで公開されるGIS データや測量データ由来の GISデータ を都市構造に関する指標として導入する条件との比較に向けて重要である。  
English: The main contribution of this paper is not to present the final conclusion of the overall project, but to demonstrate a reproducible analytical workflow and its explanatory performance across multiple observation dates under data-constrained conditions. This is important for comparing with the conditions for introducing open-source GIS data and GIS data derived from survey data as indicators of urban structure, which is a future research direction.

日本語: 今後は、OpenStreetMap や Microsoft GlobalMLBuildingFootprints などの公開 GIS データを導入し、さらに測量 GIS を含む条件と比較する予定である。また、今回の 3 観測で確認された関係が他の日付や季節でも維持されるかを検証する。  
English: Future work will introduce open GIS data sources such as OpenStreetMap and Microsoft GlobalMLBuildingFootprints and then compare the results with a condition that also includes survey-based GIS. The analysis will also test whether the relationships identified in these three observations are maintained across additional dates and seasons.
---

## 9. Keywords

- 日本語: 地表面温度 / English: Land surface temperature
- 日本語: 衛星指標 / English: Satellite-derived indicators
- 日本語: データ制約 / English: Data-constrained conditions
- 日本語: ハノイ / English: Hanoi
- 日本語: 空間交差検証 / English: Spatial cross-validation

---

## 10. References

Ermida, S. L., Soares, P., Mantas, V., Göttsche, F.-M., Trigo, I. F., 2020. Google Earth Engine Open-Source Code for Land Surface Temperature Estimation from the Landsat Series. Remote Sensing,12 (9), 1471.
https://doi.org/10.3390/rs12091471.

Garzon, J., Molina, I., Velasco, J., & Calabia, A. (2021). A remote sensing approach for surface urban heat island modeling in a tropical Colombian city using regression analysis and machine learning algorithms. Remote Sensing, 13(21), 4256. https://doi.org/10.3390/rs13214256

Google Earth Engine. (n.d.). Google Earth Engine. Google. Retrieved April 11, 2026, from https://earthengine.google.com/

Le Ngoc Hanh, & Tran Thi An. (2025). Assessment of temperature change in Da Nang City, Vietnam, using remote sensing and cloud-computing approach. The GIS-IDEAS Journal, 1(3), 16-28.

Osborne, P. E., & Alvares-Sanches, T. (2019). Quantifying how landscape composition and configuration affect urban land surface temperatures using machine learning and neutral landscapes. *Computers, Environment and Urban Systems, 76*, 80-90. https://doi.org/10.1016/j.compenvurbsys.2019.04.003

Sun, Y., Gao, C., Li, J., Wang, R., & Liu, J. (2019). Quantifying the effects of urban form on land surface temperature in subtropical high-density urban areas using machine learning. Remote Sensing, 11(8), 959. https://doi.org/10.3390/rs11080959

---

## 11. 仕上げ時の注意

- 他の分析条件の結果が既に得られているかのような表現は避ける。
- SHAP の解釈は寄与方向の説明に留め、因果関係として断定しない。
