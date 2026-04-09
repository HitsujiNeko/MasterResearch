# 学会用アブストラクト下書き（RQ3: Satellite Only）

**最終更新**: 2026-04-09  
**関連ドキュメント**: [research_guide.md](../01_planning/research_guide.md), [analysis_workflow.md](../02_methods/analysis_workflow.md), [analysis_rq3_satellite_only_guide.md](../02_methods/analysis_rq3_satellite_only_guide.md), [satellite_only_20230707_initial_run.md](satellite_only_20230707_initial_run.md), [previous_studies_report.md](../04_archive/previous_studies_report.md)  
**前提知識**: RQ3 の目的、Satellite Only 初期実行結果、LST 算出フロー

---

## 1. この下書きの位置づけ

本ファイルは、国際学会向けアブストラクトの下書きである。  
現時点で事実として記述できる研究成果は、RQ3 の Satellite Only シナリオに限られるため、本文はその範囲に限定して作成する。  
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

日本語: データ制約下の都市熱環境分析に向けた Satellite Only ベースラインの評価: ベトナム・ハノイを対象とした初期結果  
English: Evaluating a Satellite-Only Baseline for Urban Thermal Analysis under Data Constraints: Initial Results from Hanoi, Vietnam

### 3.2 タイトル案 B

日本語: 衛星由来指標のみで都市地表面温度をどこまで説明できるか: ハノイを対象とした RQ3 の初期評価  
English: How Far Can Satellite-Derived Indicators Explain Urban Land Surface Temperature? An Initial RQ3 Assessment in Hanoi

---

## 4. Abstract

日本語: 途上国都市では、建物や道路に関する詳細 GIS データが十分に整備されていないことが多く、都市熱環境の定量分析に制約がある。本研究は、ベトナム・ハノイを対象として、衛星由来指標のみで地表面温度（LST）をどこまで説明できるかを検証し、データ制約下での分析可能性を評価する。  
English: In many cities of the Global South, detailed GIS data on buildings and roads are not sufficiently available, which constrains quantitative analysis of urban thermal environments. This study examines how far land surface temperature (LST) can be explained using satellite-derived indicators alone in Hanoi, Vietnam, and evaluates the feasibility of urban thermal analysis under data-constrained conditions.

日本語: Google Earth Engine を用いて Landsat 8 から LST、NDVI、NDBI、NDWI を算出し、2023 年 7 月 7 日の観測のうち有効画素率が最も高いシーンを選定した。LST と指標ラスタを同一観測時刻で対応付け、品質管理後の 2,104,665 ピクセルを対象に、重回帰分析と Random Forest を random split および Spatial CV で評価した。  
English: Using Google Earth Engine, LST, NDVI, NDBI, and NDWI were derived from Landsat 8 imagery, and the scene with the highest valid-pixel ratio on 7 July 2023 was selected. The LST raster and spectral index rasters were matched by observation time, and 2,104,665 quality-controlled pixels were used to evaluate Multiple Linear Regression and Random Forest under both random split and spatial cross-validation.

日本語: Random Forest は random split で `R² = 0.7009`、Spatial CV でも `R² mean = 0.6759` を示し、Linear Regression より高い説明力を維持した。SHAP による解釈では、NDBI が最も強い昇温側要因であり、NDVI と NDWI は冷却側要因として機能した。  
English: Random Forest achieved `R² = 0.7009` under random split and retained `R² mean = 0.6759` under spatial cross-validation, outperforming Multiple Linear Regression in both settings. SHAP-based interpretation indicated that NDBI was the strongest warming-related factor, whereas NDVI and NDWI acted as cooling-related factors.

日本語: 以上より、Satellite Only 条件でも LST 分布のかなりの部分を説明できることが示された。今後は公開 GIS データを導入して Limited シナリオを構築し、さらに測量 GIS を含む Full シナリオへ拡張することで、データ可用性の違いが説明力に与える影響を比較する予定である。  
English: These results suggest that a Satellite Only setting can explain a substantial portion of LST variability even without detailed GIS layers. Future work will introduce open GIS data to build a Limited scenario and then extend the analysis to a Full scenario with survey-based GIS, enabling direct comparison of explanatory performance under different levels of data availability.

---

## 5. Introduction

日本語: 都市のヒートアイランド現象を理解し、緩和策を設計するためには、LST と都市構造の関係を空間的に評価することが重要である。しかし、ベトナムを含む多くの途上国都市では、建物形状や道路ネットワークを網羅的に記述した高品質 GIS データを入手することが難しい。  
English: Spatial evaluation of the relationship between LST and urban structure is essential for understanding urban heat islands and designing mitigation strategies. However, in many cities in developing countries, including Vietnam, it is difficult to obtain high-quality GIS data that comprehensively describe building geometry and road networks.

日本語: 本研究では、この制約を前提として、データ可用性の異なる複数シナリオを段階的に比較する枠組みを採用している。本稿で報告するのは、その第一段階にあたる RQ3 の Satellite Only シナリオであり、衛星由来指標のみで LST をどこまで説明できるかを初期的に検証する。  
English: This study adopts a staged framework that compares multiple scenarios with different levels of data availability. The present abstract reports the first stage, namely the Satellite Only scenario of Research Question 3, which provides an initial assessment of how far LST can be explained using satellite-derived indicators alone.

日本語: 本シナリオの位置づけは、最終結論を与えることではなく、詳細 GIS データが不足している都市でも成立する再現可能な分析ベースラインを示すことである。そのため、本稿では RQ1 や RQ2 の結論には踏み込まず、現時点で得られている事実ベースの結果と今後の拡張方針に焦点を当てる。  
English: The purpose of this scenario is not to provide the final conclusion of the entire study, but to establish a reproducible analytical baseline that remains feasible even when detailed GIS data are unavailable. Therefore, this abstract does not claim conclusions for RQ1 or RQ2 and instead focuses on the fact-based findings currently available and on the directions for future extension.

### 5.1 図表案

- 図1案: 研究全体の 3 シナリオ構成図
- 図2案: Hanoi ROI と対象観測日の概略図

---

## 6. Methodology

日本語: LST は Landsat 8 データを用いて Google Earth Engine 上で算出し、Ermida et al. (2020) に基づく SMW 法を採用した。衛星指標としては、同じ Landsat 8 シーンから NDVI、NDBI、NDWI を算出し、LST と同一の ROI 範囲で出力した。  
English: LST was derived from Landsat 8 imagery in Google Earth Engine using the SMW approach based on Ermida et al. (2020). As satellite-derived explanatory variables, NDVI, NDBI, and NDWI were computed from the same Landsat 8 scenes and exported over the same ROI as the LST data.

日本語: 2023 年 7 月 7 日の観測候補の中から、LST と指標の両方で有効画素率が最も高く、雲量も小さい `2023-07-07T03:23:29Z` のシーンを選定した。その後、LST ラスタと指標ラスタを同一グリッド上で対応付け、`LST = 15-65°C`、各指標 = `-1.1 to 1.1` の品質条件を満たすピクセルのみを分析対象とした。  
English: From the candidate observations on 7 July 2023, the scene acquired at `2023-07-07T03:23:29Z` was selected because it provided the highest valid-pixel ratios for both LST and the spectral indices while maintaining low cloud cover. The LST and index rasters were then matched on the same grid, and only pixels satisfying the quality conditions of `LST = 15-65°C` and each index = `-1.1 to 1.1` were retained for analysis.

日本語: モデル比較では、説明変数を NDVI、NDBI、NDWI、目的変数を LST とし、Multiple Linear Regression と Random Forest を適用した。評価は random split と Spatial CV の両方で行い、後者では経度・緯度を分位で区切った空間ブロックを用いて、空間自己相関による過大評価を抑えた。  
English: For model comparison, NDVI, NDBI, and NDWI were used as explanatory variables and LST as the target variable, and both Multiple Linear Regression and Random Forest were applied. Performance was evaluated under both random split and spatial cross-validation, with the latter using quantile-based spatial blocks defined by longitude and latitude in order to reduce overestimation caused by spatial autocorrelation.

日本語: さらに、Random Forest の解釈のために SHAP を用い、各指標が予測値をどの方向にどの程度変化させるかを確認した。現段階では 1 都市 1 観測による初期結果であり、建物密度や道路密度などの GIS 由来都市構造パラメータはまだ導入していない。  
English: In addition, SHAP was used to interpret the Random Forest model and to examine the direction and magnitude of each indicator's contribution to the predictions. At the current stage, the analysis remains an initial result based on one city and one observation, and GIS-derived urban-structure parameters such as building density and road density have not yet been incorporated.

### 6.1 図表案

- 図3案: LST 算出からデータセット作成、モデル評価までの処理フロー
- 表1案: 使用データ、観測日時、画素数、評価条件の一覧

---

## 7. Results

日本語: 品質管理後に残った分析対象は 2,104,665 ピクセルであり、LST の平均値は `35.7646°C` であった。random split において、Linear Regression は `R² = 0.5310`、`RMSE = 1.4417`、`MAE = 1.0621` を示し、Random Forest は `R² = 0.7009`、`RMSE = 1.1514`、`MAE = 0.8555` を示した。  
English: After quality control, the analysis dataset contained 2,104,665 pixels, with a mean LST of `35.7646°C`. Under random split, Linear Regression produced `R² = 0.5310`, `RMSE = 1.4417`, and `MAE = 1.0621`, whereas Random Forest achieved `R² = 0.7009`, `RMSE = 1.1514`, and `MAE = 0.8555`.

日本語: Spatial CV では、Linear Regression が `R² mean = 0.4929`、Random Forest が `R² mean = 0.6759` を示した。random split からの低下は存在するものの、その幅は極端ではなく、Satellite Only 条件で得られた説明力が単なる近接画素間のリークだけで説明されるものではないことを示唆する。  
English: Under spatial cross-validation, Linear Regression yielded `R² mean = 0.4929`, while Random Forest retained `R² mean = 0.6759`. Although performance decreased relative to random split, the decline was not extreme, suggesting that the explanatory power observed in the Satellite Only setting cannot be attributed solely to leakage among neighboring pixels.

日本語: 変数重要度と SHAP の結果を総合すると、NDBI が最も支配的な昇温側要因であり、NDVI と NDWI は冷却側要因として働いた。具体的には、mean absolute SHAP は `NDBI = 0.8327`、`NDVI = 0.5441`、`NDWI = 0.4261` であった。  
English: Integrating the feature-importance and SHAP results, NDBI emerged as the dominant warming-related factor, while NDVI and NDWI acted as cooling-related factors. Specifically, the mean absolute SHAP values were `0.8327` for NDBI, `0.5441` for NDVI, and `0.4261` for NDWI.

日本語: 一方で、NDVI と NDWI の VIF はそれぞれ `20.2073`、`19.1795` と高く、線形回帰係数の厳密な順位解釈には注意が必要である。したがって、本稿では線形係数の大きさよりも、Random Forest と SHAP に基づく解釈を優先する。  
English: At the same time, the VIF values for NDVI and NDWI were high, at `20.2073` and `19.1795`, respectively, indicating that strict ranking of the linear coefficients should be interpreted with caution. Therefore, this draft prioritizes interpretation based on Random Forest and SHAP rather than on the absolute magnitudes of the linear coefficients.

### 7.1 図表案

- 表2案: random split と Spatial CV の性能比較表
- 図4案: Linear Regression と Random Forest の性能比較棒グラフ
- 図5案: RF importance、Permutation importance、SHAP を並べた重要度比較図

---

## 8. Conclusion

日本語: 本稿で得られた初期結果は、詳細 GIS データを用いなくても、衛星由来指標のみでハノイの LST 分布のかなりの部分を説明できることを示している。特に Random Forest は Spatial CV でも高い説明力を維持しており、Satellite Only シナリオが実用的なベースラインとして成立する可能性が高い。  
English: The initial results presented here indicate that a substantial share of LST variability in Hanoi can be explained even without detailed GIS data, using satellite-derived indicators alone. In particular, Random Forest maintained strong explanatory performance under spatial cross-validation, suggesting that the Satellite Only scenario can serve as a practical analytical baseline.

日本語: 現段階での貢献は、研究全体の最終結論を提示することではなく、データ制約下でも再現可能な分析手順を先に成立させた点にある。これは、今後の Limited シナリオおよび Full シナリオの比較に向けた基礎として重要である。  
English: At this stage, the main contribution is not the final conclusion of the entire project, but rather the establishment of a reproducible analytical workflow that remains feasible under data constraints. This provides an important foundation for later comparison with the Limited and Full scenarios.

日本語: 今後は、OpenStreetMap や Microsoft GlobalMLBuildingFootprints などの公開 GIS データを導入して Limited シナリオを構築し、さらに測量 GIS を含む Full シナリオと比較する予定である。また、複数日・複数季節への拡張を通じて、今回確認された関係の安定性も検証する。  
English: Future work will introduce open GIS data sources such as OpenStreetMap and Microsoft GlobalMLBuildingFootprints to build the Limited scenario and then compare it with the Full scenario that includes survey-based GIS. The analysis will also be extended to multiple dates and seasons in order to test the stability of the relationships identified in this initial result.

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

- RQ1 と RQ2 の結果が既に得られているかのような表現は避ける。
- Limited / Full シナリオの性能値は書かない。
- 今回の結果は 2023-07-07 の単観測に基づく初期結果であることを維持する。
- SHAP の解釈は寄与方向の説明に留め、因果関係として断定しない。
