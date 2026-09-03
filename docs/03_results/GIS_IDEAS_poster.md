# GIS-IDEAS ポスター原稿（Limited シナリオ・日英対訳）

**最終更新**: 2026-09-03  
**関連ドキュメント**: [limited_analysis_results.md](limited_analysis_results.md), [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd), [fig3_limited_workflow.mmd](fig3_limited_workflow.mmd), [observation_selection.md](../02_methods/observation_selection.md), [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md), [GIS_IDEAS_abstract.md](GIS_IDEAS_abstract.md), [research_guide.md](../01_planning/research_guide.md)  
**前提知識**: RQ3（データ制約下での有効性評価）の位置づけ、Limited シナリオの分析条件、Spatial CV の読み方

---

## 0. この原稿の位置づけ

本ファイルは GIS-IDEAS 学会のポスター（**A1 縦**）に載せる文章の原稿である。**ポスター面に載るのは英語のみ**であり、日本語は内容を理解して質疑に答えるための対訳である。

**本原稿は実物の pptx と 1 対 1 で対応させる。** ポスターを組み替えたら本原稿も同じ構成へ直す。pptx は `presentations/`（Git 管理外）に置くため PR には乗らず、本原稿が文章の正本になる。

**数値の丸めをそろえる。** R² と重要度は小数第 3 位、RMSE（°C）と VIF は第 2 位、割合は出所の桁数のままとする。第 2 位までにすると変数セット比較の差（`both` 0.760 と `spectral` 0.747）が潰れるためである。

**数値の出所を各パネルに明記する。** 断りのない数値はすべて [limited_analysis_results.md](limited_analysis_results.md) の**ラン1（主結果）**に由来し、節番号を併記する。同ドキュメントおよび `data/output/limited/20230707_032305/` の CSV / JSON に無い数値は書かない。

### 0.1 テンプレートの実測値

`presentations/GIS-IDEAS-2026_poster_template.pptx` を OOXML から採寸した実測値である。

| 項目 | 実測値 |
|---|---|
| スライド寸法 | 593.7 × 841.0 mm（A1 縦） |
| 本文の上端 | **y = 57.8 mm**（上部装飾バンドとロゴの下にある全幅の区切り線） |
| 本文の下端 | **y = 790.5 mm**（ID 欄。その下に大学名・会期のフッタ） |
| 左右余白 | テンプレートは規定していない（区切り線が全幅に渡る） |
| タイトル枠 | テンプレートに無い。タイトル・著者名は自前で置く |

### 0.2 版面

左右余白 20mm・パネル間 12mm。本文 20pt、パネル見出し 26pt、キーメッセージ 22pt、キャプション 14pt。

| 位置 | # | パネル | 幅 | 高さ | 主な内容 |
|---|---|---|---|---|---|
| 全幅 | 1 | Background | 553.7 mm | 56 mm | 散文 |
| 全幅 | 2 | Study area and datasets | 553.7 mm | 142 mm | ROI 位置図（120 × 97 mm）・LST 図（67 × 97 mm）・データセット一覧表（341 mm 幅） |
| 全幅 | 3 | From datasets to urban parameters | 553.7 mm | 148 mm | ワークフロー図（542 × 48 mm）・定義・算出済みラスタ 6 点（各 41 mm 幅） |
| 左列 | 4 | Results | 270.9 mm | 152 mm | 表 2 点と読み方 |
| 左列 | 6 | Conclusions and limitations | 270.9 mm | 86.5 mm | 箇条書き |
| 右列 | 5 | Variable importance | 270.9 mm | 250.5 mm | SHAP 図（204 × 144 mm）・順位表 |

**体裁は内容に合わせて使い分ける。** 背景は文脈をつなぐ必要があるため散文、データと結果は表、限界は箇条書き、手法は図で示す。パネルの大きさも内容に応じて変える。

---

## 1. タイトル・著者

日本語: ベトナム・ハノイにおける地表面温度と都市空間密度の関係の評価  
English: Evaluation of Relationship Between Land Surface Temperature and Urban Spatial Density in Hanoi, Vietnam

Takumi Dowaki¹, Go Yonezawa¹, Tatsuya Nemoto², Xuan Luan Truong³ and Kenji Sugimoto¹

1. Graduate School of Engineering, Osaka Metropolitan University, 3-3-138 Sugimoto Sumiyoshi-ku, Osaka-shi, 558-8585, Japan
2. Graduate School of Science, Osaka Metropolitan University, 3-3-138 Sugimoto Sumiyoshi-ku, Osaka-shi, 558-8585, Japan
3. Hanoi University of Mining and Geology, No.18 Vien Street, Duc Thang Ward, Bac Tu Liem District, Ha Noi, Vietnam

E-mail: <sr25491d@omu.ac.jp>

---

## 2. パネル本文（日英対訳）

### パネル 1: Background

日本語: 都市のヒートアイランド現象を理解し緩和策を設計するには、地表面温度（LST）と都市構造の関係を空間的に評価する必要がある。ランダムフォレストによる都市形態変数の重要度評価（Sun et al., 2019）や、熱帯都市における回帰分析と機械学習の併用（Garzón et al., 2021）が報告されている。一方でベトナムを含む多くの途上国都市では、建物形状や道路ネットワークを網羅的に記述した高品質な GIS データの入手が難しく、NDVI と NDBI だけでは建物高さや人口密度を表現できないことも指摘されている（Le Ngoc Hanh & Tran Thi An, 2025）。  
English: Understanding urban heat islands and designing mitigation measures requires a spatial evaluation of how land surface temperature (LST) relates to urban structure. Random forests have been used to rank urban-form variables (Sun et al., 2019), and regression has been combined with machine learning in tropical cities (Garzón et al., 2021). In many developing cities, including those in Vietnam, it remains difficult to obtain high-quality GIS that comprehensively describes building geometry and road networks, and NDVI and NDBI alone cannot represent building height or population density (Le Ngoc Hanh & Tran Thi An, 2025).

日本語: **本研究は、衛星データと公開 GIS の組み合わせによって都市空間密度をどこまで定量化でき、ハノイの 30m スケールの LST 分布をどこまで説明できるかを問う。**  
English: **This study asks how far satellite data combined with open GIS can quantify urban spatial density and explain the LST distribution of Hanoi at 30 m.**

> **出所**: [GIS_IDEAS_abstract.md](GIS_IDEAS_abstract.md) 5 章（Introduction）を土台に、Limited シナリオ向けへ書き換えた。引用文献は [previous_studies_report.md](../04_archive/previous_studies_report.md) を参照する。  
> **注意**: 先行研究の精度指標を本研究と横並びに比較しない。両論文とも本文と表に数値の不整合があり、**数値を引用する場合は原典の表を優先する**（同 S9.7 節・S10.8 節）。

### パネル 2: Study area and datasets

日本語: ハノイ ROI の 30m 正準グリッドは 3,739,454 セルからなり、全レイヤーを `cell_id` で結合する。観測は候補 132 件を実効 ROI カバー率で再ランキングして選び、88.7%（3 位）である。30m グリッド上で実測した LST 有効被覆率の平均は 89.26%。  
English: Hanoi ROI on a 30 m canonical grid of 3,739,454 cells; all layers join by cell_id. The scene was chosen by re-ranking 132 candidates on effective ROI coverage – 88.7% (rank 3); mean LST valid ratio on the grid is 89.26%.

本文はこの見出し脇の一文のみで、あとは図（ROI 位置図・LST 図）と表で構成する。

**データセット一覧表**

| Dataset | Epoch | Type | Parameters derived |
|---|---|---|---|
| Landsat 8 C2 L2 | 2023-07-07 | Raster 30 m | LST, NDVI, NDBI, NDWI |
| GlobalBuildingAtlas v1.0.0 | imagery 2021–2023 | Vector | Coverage, density, height |
| OpenStreetMap (Geofabrik) | 2026-04 | Vector | Road density |
| GLC_FCS30D | 2022 | Raster 30 m | Land-cover class fractions |
| WorldPop | 2020 | Raster ~92 m | Population density |
| VIIRS DNB | 2023 | Raster ~460 m | Night-time light |
| FABDEM v1.2 | Copernicus-derived | Raster 30 m | Mean elevation |

**図のキャプション**

| 図 | English | 日本語 |
|---|---|---|
| 左 | Hanoi ROI, Vietnam | ハノイ ROI（ベトナム） |
| 中 | LST (target variable) | 地表面温度（目的変数） |

> **出所**: 年代・種別は各 gis_data ドキュメント（[gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) 3 章、[gis_data_lulc.md](../01_planning/gis_data/gis_data_lulc.md)、[gis_data_population.md](../01_planning/gis_data/gis_data_population.md)、[gis_data_nighttime_lights.md](../01_planning/gis_data/gis_data_nighttime_lights.md)、[gis_data_dem.md](../01_planning/gis_data/gis_data_dem.md)、[gis_data_roads.md](../01_planning/gis_data/gis_data_roads.md)）。観測選定は [observation_selection.md](../02_methods/observation_selection.md) 3 章・5 章。  
> **補足**: FABDEM の年代は「Copernicus WorldDEM-30 由来」までしか裏を取れていないため、年を書かない。従来用いていた同日 03:23:29 の観測は実効 ROI カバー率 52.3%（12 位）にとどまり、これが観測を差し替えた直接の動機である。

### パネル 3: From datasets to urban parameters

日本語: **都市構造パラメータとは、地表面エネルギー収支を左右する要素——土地被覆・人工構造物・人口集積・地形——の空間配置と密度を、共通グリッド上の空間統計量として定量化したものである。**  
English: **Urban structure parameters quantify, as spatial statistics on a common grid, the arrangement and density of the elements that govern the surface energy balance: land cover, artificial structures, population concentration and terrain.**

日本語: すべてのレイヤーを同一の 30m 正準グリッドへ集計し、`cell_id` ごとに 1 行のデータにする。モデルへ投入する 15 のパラメータは、分光指数 3（NDVI・NDBI・NDWI）、建物被覆率・棟数密度・平均高さ、道路密度、土地被覆クラス別面積率 5、人口密度、夜間光、平均標高である。ベクタのレイヤーは連続的な密度へ変換されるため、右の地図は生の入力データではなく算出後のパラメータである。  
English: Every layer is aggregated onto the same 30 m canonical grid by zonal statistics, giving one row per cell_id. Fifteen parameters enter the models: three spectral indices (NDVI, NDBI, NDWI); building coverage, density and mean height; road density; five land-cover class fractions; population density; night-time light; and mean elevation. Vector layers become continuous densities, so the maps on the right are derived parameters, not raw source data.

**図のキャプション**

| 図 | English | 日本語 |
|---|---|---|
| 上段 | （ワークフロー図。キャプションなし） | データセットから評価までの流れ |
| 右 1 | Building coverage | 建物被覆率 |
| 右 2 | Mean building height | 平均建物高さ |
| 右 3 | Road density | 道路密度 |
| 右 4 | NDBI | 正規化建築物指数 |
| 右 5 | Population density | 人口密度 |
| 右 6 | Night-time light | 夜間光強度 |

**6 点はベクタ由来（建物・道路）とラスタ由来（分光指数・人口・夜間光）の両方から選ぶ。** ベクタが連続的な密度へ変わることを示しつつ、入力の広がりも見せるためである。

> **出所**: 定義は [research_guide.md](../01_planning/research_guide.md) §5.3 と [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) 2 章・3 章（P1〜P18）。処理条件は [limited_analysis_results.md](limited_analysis_results.md) 3.2〜3.6 節。  
> **補足**: 土地被覆の面積率は全行で合計 1.0 になるため参照クラス（農地）を除外し、裸地は定数列として除外される。結果として実効的な説明変数は 15 個になる（同 3.6 節）。

### パネル 4: Results

**モデル性能**

| Model | Random split R² | Spatial CV R² | RMSE (°C) |
|---|---|---|---|
| MLR | 0.646 | 0.645 | 1.47 |
| Random forest | 0.796 | 0.760 | 1.11 |

日本語: Spatial CV で下がるのは RF だけである。2,700m のブロックは空間自己相関を断ち切れていない（セミバリオグラムの sill は 15〜30km）ため、この R² は同一 ROI 内への内挿性能として読む。汎化性能ではない。  
English: Only the RF drops under spatial CV. Blocks of 2,700 m do not break the spatial autocorrelation (semivariogram sill 15–30 km), so read these R² as interpolation within the same ROI, not generalisation.

**変数セットの比較**

| Variable set | RF (spatial CV) | Linear (spatial CV) |
|---|---|---|
| Spectral only | 0.747 | 0.594 |
| Coverage only | 0.674 | 0.611 |
| Both | 0.760 | 0.645 |

日本語: **分光指数が上回る。ただしランダムフォレストに限る。**  
English: **Spectral indices win – for the random forest only.**

日本語: Spectral は NDVI・NDBI・NDWI、Coverage は土地被覆クラス別面積率を指し、どちらも共通ベースを含む。線形モデルでは向きが逆転するため、モデルを指定せずに主張できない。3 ランは同一のセル・標本・ブロックである。  
English: Spectral = NDVI, NDBI, NDWI; coverage = land-cover class fractions; both also carry the common base. The ordering reverses for the linear model, so the model must be named. Identical cells and blocks across the runs.

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 4.1 節・4.2 節・4.3 節・3.9 節、2 章の台帳（ラン1・3・4）。RMSE は摂氏で読む。  
> **補足**: ブロックを広げると RF の R² は単調に低下する（ランダム分割 0.7954 → 2,700m 0.7596 → 21,600m 0.5461。診断設定・RF 100 本）。線形モデルはほぼ動かず、RF が線形を上回る幅は +0.115 から +0.023 へ縮む。**RF の優位の相当部分は、非線形性の捕捉ではなく空間自己相関の利用である可能性が高い**（同 3.9 節。詳細は 6 章の想定問答 Q3）。

### パネル 5: Variable importance

日本語: **`NDBI` が支配的である。ただし首位は指標によって入れ替わる。**  
English: **NDBI dominates – but the leader depends on the measure.**

**指標別の上位 3 変数**

| Rank | SHAP | Permutation | RF impurity |
|---|---|---|---|
| 1 | NDBI 0.702 | NDBI 0.313 | Built-up cover 0.474 |
| 2 | Built-up cover 0.432 | Mean elevation 0.144 | NDBI 0.141 |
| 3 | Population 0.377 | Population 0.142 | Mean elevation 0.082 |

日本語: 単一の指標で首位を断定せず、SHAP と Permutation 重要度を主たる根拠とする。RF の不純度ベース重要度だけが建築被覆率を首位に置く。  
English: We rely on SHAP and permutation importance, not on any single measure: the RF impurity importance alone puts built-up cover first.

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 5.1 節、`..._feature_importance.csv` / `..._shap_importance.csv`。  
> **補足**: 不純度ベース重要度は取りうる値が少ない変数で挙動が変わりうる。上位 4 変数の順位は標本を変えても安定するが、第 5・6 位（`NDVI` と `NDWI`）は入れ替わるため、5 位以下の順位差は論じない（同 2.1 節）。

### パネル 6: Conclusions and limitations

日本語: **公開データだけで LST 分布の大半を説明できる。**  
English: **Open data alone explains most of the LST pattern.**

1. 日本語: ランダムフォレストは公開データのみで Spatial CV の R² 0.760 に到達する。  
   English: Random forest reaches R² 0.760 under spatial CV from open data alone.
2. 日本語: セルの 72.66% が建物高さ 0m の補完であり、「建物の有無」と「高さ」を分離できていない。  
   English: 72.66% of cells are imputed as 0 m height: presence and height are not separable.
3. 日本語: `NDVI` と `NDWI` の VIF は 32.24・34.56 と危険水準に残る。  
   English: NDVI and NDWI VIFs remain hazardous at 32.24 and 34.56.
4. 日本語: Spatial CV の R² は内挿性能である。単一観測・ハノイ単独・30m のみの結果である。  
   English: Spatial CV R² is interpolation; single scene, Hanoi only, 30 m.

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 5.1 節・3.9 節・6.5 節・1.3 節。  
> **補足**: 0m 補完セルと「被覆率・棟数密度がともに 0 のセル」の一致率は **100.000000%** である。この従属は VIF では検出できない（`BUILD_H_MEAN` の VIF は 1.72）。線形従属ではなく「ゼロか否か」の水準で生じているためである（同 3.9 節）。

---

## 3. 変数の表示名

**ポスターの図表では列名をそのまま出さず、下表の表示名を使う。** 初見の読み手が列名を解読できないためである。SHAP 図・重要度表・本文で表記を揃える。

| 列名 | 表示名（English） | 日本語 | 由来グループ |
|---|---|---|---|
| `NDVI` | NDVI (vegetation index) | 正規化植生指数 | Satellite index |
| `NDBI` | NDBI (built-up index) | 正規化建築物指数 | Satellite index |
| `NDWI` | NDWI (water index) | 正規化水指数 | Satellite index |
| `LULC_BUILT_COV` | Built-up cover fraction | 市街地被覆率 | Land cover |
| `LULC_TREE_COV` | Tree cover fraction | 樹林被覆率 | Land cover |
| `LULC_WATER_COV` | Water cover fraction | 水域被覆率 | Land cover |
| `LULC_RANGE_COV` | Rangeland cover fraction | 草地低木被覆率 | Land cover |
| `LULC_WETLAND_COV` | Wetland cover fraction | 湿地被覆率 | Land cover |
| `BUILD_COV` | Building coverage | 建物被覆率 | Building / road |
| `BUILD_DEN` | Building density | 建物棟数密度 | Building / road |
| `BUILD_H_MEAN` | Mean building height | 平均建物高さ | Building / road |
| `ROAD_DEN` | Road density | 道路密度 | Building / road |
| `POP_DEN_WORLDPOP2020` | Population density | 人口密度 | Population / light / terrain |
| `NTL_MEAN` | Night-time light | 夜間光強度 | Population / light / terrain |
| `ELEV_MEAN` | Mean elevation | 平均標高 | Population / light / terrain |

**単位**（凡例に表示する）: 建物被覆率・土地被覆率は 0–1、建物棟数密度は 棟/ha、道路密度は m/ha、人口密度は 人/ha、建物高さと標高は m、LST は °C、分光指数は無次元。出所は [calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6 章。

---

## 4. 用語対訳表

ポスター本文・図表・口頭説明で用語を揺らさないための対訳表である。定義の正本は各参照先とする。

| 日本語 | English | 補足 |
|---|---|---|
| 地表面温度 | Land Surface Temperature (LST) | 本研究では必ず摂氏（°C）で扱う |
| 都市構造パラメータ | urban structure parameters | 定義は [research_guide.md](../01_planning/research_guide.md) §5.3 |
| 都市空間密度 | urban spatial density | タイトルの用語。上記パラメータが表す密度の総称 |
| 研究対象地域 | Region of Interest (ROI) | 分析対象域の基準となる空間範囲 |
| 有効カバレッジ／有効域 | effective coverage / effective area | 実際に信頼して使えるデータ範囲。**ROI 全体と同一視しない** |
| 実効 ROI カバー率 | effective ROI coverage | シーン被覆率・LST 有効率・指標有効率から算出する観測選定の指標 |
| 正準グリッド | canonical grid | 全レイヤーを載せる共通の 30m 格子。`cell_id` で結合する |
| 母数 | population size (after filtering) | 品質フィルタ通過後のセル数。標本サイズとは別 |
| 標本統制 | sample control | 比較するランどうしで母数と抽出標本が一致している状態 |
| 空間交差検証 | spatial cross-validation (Spatial CV) | 空間ブロックを分割単位とする交差検証 |
| 内挿性能 | interpolation performance | 同一 ROI 内・空間的に近い場所への予測性能 |
| 分光指数 | spectral indices | NDVI・NDBI・NDWI |
| 被覆率型変数 | coverage-type variables | 土地被覆クラス別の面積率 |
| 品質マスク | validity mask | 有効域を明示する列（人口・夜間光）。補完はしない |
| 衛星データのみ | Satellite Only | 衛星由来指標のみを用いる分析シナリオ |
| 衛星＋公開GIS | Limited | 衛星データと公開 GIS のみを用いる分析シナリオ（本ポスター） |
| 測量GISを含む | Full | 衛星・公開 GIS・測量 GIS を用いる分析シナリオ |

---

## 5. 掲載する図表

| 図表 | 配置 | ファイル・出所 |
|---|---|---|
| ROI 位置図 | パネル 2 | `presentations/ROI.png`（Git 管理外）。`src/visualization/roi_location_map.py` で生成（7 章） |
| LST 図 | パネル 2 | データセットから描画（7 章） |
| データセット一覧表 | パネル 2 | 本原稿 2 章 |
| ワークフロー図 | パネル 3 | [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) |
| 建物被覆率・平均建物高さ・道路密度・NDBI・人口密度・夜間光の図 | パネル 3 | データセットから描画（7 章） |
| モデル性能表・変数セット比較表 | パネル 4 | 本原稿 2 章 |
| SHAP 棒グラフ | パネル 5 | `..._shap_importance.csv` から描画（7 章） |
| 指標別の上位 3 変数の表 | パネル 5 | 本原稿 2 章 |

**ワークフロー図は 2 種類ある。** [fig3_limited_workflow.mmd](fig3_limited_workflow.mmd) は処理条件を追えるドキュメント用の詳細版（20 ノード・縦フロー）であり、**ポスターに載せると図中の文字が読めない**。ポスターには横流し 6 ステップの [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) を使う。

---

## 6. 想定問答（日英）

**パネルに載せなかった限定の詳細は Q3 が引き受ける。** ブロックサイズと空間自己相関の論証は短時間で追える種類ではないため独立パネルを置かず、こちらから先に提示する論点として扱う。

### Q1. なぜ観測 1 日だけなのか

日本語: 実効 ROI カバー率で 132 件を再ランキングし、ROI をほぼ覆う観測が限られることを確認したためである。採用観測は 88.7%（3 位）であり、複数日を同等の品質でそろえることが難しい。季節差の評価は今後の課題として明示している。  
English: We re-ranked 132 candidate scenes by effective ROI coverage and found that few scenes cover nearly the whole ROI. The chosen scene reaches 88.7% (rank 3), and matching several dates at comparable quality is difficult. Assessing seasonal differences is stated as future work.

### Q2. なぜハノイ単独なのか

日本語: 本研究の目的は、データ制約下で公開データがどこまで使えるかを 1 都市で徹底的に検証することにある。他都市への一般化は主張しておらず、限界として明記している。  
English: The aim is to test exhaustively, in a single city, how far open data can go under data constraints. We make no claim of generalisation to other cities, and state this explicitly as a limitation.

### Q3. 2,700m のブロックで空間自己相関を断ち切れているのか

日本語: 断ち切れていない。ブロックサイズを変えて out-of-fold R² を測ると、RF は 0.7954（ランダム分割）→ 0.7596（2,700m）→ 0.7417（5,400m）→ 0.6806（8,100m）→ 0.5461（21,600m）と単調に低下する。LST のセミバリオグラムでも 2,700m 地点のセミバリアンスは全体分散の 69% にとどまり、sill に達するのは 15〜30km である。線形モデルはブロックを変えてもほぼ動かないのに対し RF だけが下がり、RF が線形を上回る幅も +0.115 から +0.023 へ縮む。**RF の優位の相当部分は、非線形性の捕捉ではなく空間自己相関の利用である可能性が高い。** したがって本研究の Spatial CV の R² は内挿性能として読む。なお低下のすべてが空間リークの除去とは限らず、空間的非定常性が混在する（fold 間 sd は 0.045 から 0.205 へ膨らむため、大きいブロックでの個々の数値は信頼できない）。信頼できるのは単調に低下するという傾向である。ブロックサイズ自体の見直しは、独立した方法論の課題として分けている。  
English: No. As the block size grows, the out-of-fold R² of the RF declines monotonically: 0.7954 (random split) → 0.7596 (2,700 m) → 0.7417 (5,400 m) → 0.6806 (8,100 m) → 0.5461 (21,600 m). The LST semivariogram agrees: at 2,700 m the semivariance is only 69% of the total variance, and the sill is reached at 15–30 km. The linear model barely moves across block sizes while only the RF declines, and the margin of the RF over the linear model narrows from +0.115 to +0.023. **A substantial part of the advantage of the RF is therefore likely to come from exploiting spatial autocorrelation rather than from capturing non-linearity.** We accordingly read our spatial CV R² as interpolation performance. Not all of the decline is removal of spatial leakage, however: spatial non-stationarity is mixed in, and the between-fold sd grows from 0.045 to 0.205, so individual values at large blocks are unreliable. What is reliable is the monotonic trend. Revising the block size itself is treated as a separate methodological question.

### Q4. 建物高さの寄与が小さいのはなぜか

日本語: 建物が無いセルへ 0m を補完しており、補完済みセルが標本の 72.66% を占める。補完の判定条件が被覆率と棟数密度であるため、高さ列のゼロ部分は他の建物変数から完全に決まる。**「有無」と「高さ」を分離できていないことによるものであり、高さが無関係であることを示すものではない。** 建物がある場合の高さは平均 5.73m・中央値 4.82m である。  
English: Cells without buildings are imputed with 0 m, and such cells make up 72.66% of the sample. Because the imputation rule keys on building coverage and density, the zero part of the height column is fully determined by the other building variables. **This reflects an inability to separate presence from height, not evidence that height is irrelevant.** Where buildings exist, the mean height is 5.73 m and the median 4.82 m.

### Q5. NDVI と NDWI の VIF が高いまま両方を投入しているのはなぜか

日本語: 両者はどちらも近赤外に支配され符号が逆であるため、Pearson −0.972 という構造的な相関を持つ。RF は共線性の影響を受けにくく、SHAP による寄与の解釈を優先した。ただし**線形モデルの係数は共線性の影響下にある**。共線性の解消（1 本に絞る・主成分化する）は未実施の課題として明示している。  
English: Both are dominated by the near-infrared band with opposite signs, giving a structural correlation of Pearson −0.972. The RF is relatively robust to collinearity, and we prioritised interpreting contributions through SHAP. **The linear coefficients, however, are affected by collinearity.** Resolving it, by keeping a single index or combining the two into a principal component, is stated as unfinished work.

---

## 7. ポスターの図の作り方

**ポスターに載せる地図と SHAP 図は、ドキュメント用の既存出力をそのまま使わない。** 理由は次の 3 点である。

- QGIS 出力（`images/` 配下）は**タイトルと凡例が日本語**であり、英語のポスターに貼れない
- 道路密度は 300m の出力しか無く、他が 30m なので粒度が揃わない
- 分析パイプラインが出力する SHAP 図は軸ラベルが列名（`LULC_BUILT_COV` 等）であり、初見の読み手が解読できない

そこで次の手順でポスター用に描き直す。

1. **地図**: `data/output/datasets/dataset_limited_20230707_032305_hanoi_30m.gpkg` から必要な列を読み、`cell_id = row × 1,000,000 + col` を行・列へ復号して 2 次元配列へ戻し、`matplotlib` で描画する。英語のカラーバーを付け、値域は 1〜99 パーセンタイルで切る
2. **SHAP 図**: `..._shap_importance.csv` の値をそのまま読み（再計算しない）、3 章の表示名で横棒グラフを描く。由来グループごとに色を分け、凡例を付ける
3. **ワークフロー図**: [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) を `mermaid-cli` で PNG へ書き出す
4. **ROI 位置図**: `python -m src.visualization.roi_location_map --output presentations/ROI.png` を実行する。ROI（`data/gis/boundaries/hanoi/`）とベトナム国境（`data/gis/boundaries/vietnam/`・geoBoundaries ADM0）を OpenStreetMap の XYZ タイル上に重ね、方位記号・スケールバー・経緯度目盛・インセット・出典表記を付けて出力する。既定は幅 120mm・400dpi（1889 × 1574 px）

**描画時の注意（実際に踏んだ不具合）**

- **`imshow` の `origin` を明示する。** `row` は緯度と正の相関を持つ（`row` が大きいほど北）ため、既定の `origin="upper"` では**南北が反転する**。`origin="lower"` を指定する
- **小さく並べる図は凡例の文字を大きめに描く。** 48mm 幅で表示する図の凡例を既定サイズで描くと、印刷時に判読できない
- **単位を確認してから凡例に書く。** 道路密度は m/ha、建物棟数密度は 棟/ha、人口密度は 人/ha である（セル当たりではない）
- **カラーバーのラベルが figure に収まるか確かめる。** カラーバーのラベルは軸ラベルであり、figure より横に長いと `bbox_inches="tight"` を指定しても両端が切れる（matplotlib は外接矩形の計算で軸ラベルの幅を潰して扱うため）。収まるまで文字サイズを段階的に下げ、**保存後に画像の左右端へインクが残っていないかを機械的に確認する**
- **ベースマップに CARTO のタイルを使わない。** `basemaps.cartocdn.com` は API キー無しの取得でタイル面に 「API KEY REQUIRED」の透かしが焼き込まれる。淡色のベースマップは OSM 標準タイルを減彩して得る
- **Web メルカトルのスケールバーは緯度補正する。** 座標上の長さは緯度 φ で `1/cos(φ)` 倍に伸びているため、そのまま地表距離として扱うとハノイ（北緯 21 度）で約 7% 過大になる

**pptx の組版**は `presentations/GIS-IDEAS-2026_poster_template.pptx` を土台に、装飾バンド・ロゴ・フッタを保持したまま図形を追記して行う。テンプレートは png の既定拡張子を宣言していないため、png を追加する場合は `[Content_Types].xml` へ `<Default Extension="png" ContentType="image/png"/>` を加える必要がある（宣言しないと PowerPoint がパッケージごと拒否する）。

**再現スクリプトは ROI 位置図のみリポジトリに入れている**（`src/visualization/roi_location_map.py` と タイル取得の `src/visualization/xyz_tiles.py`）。ROI 位置図は貼付幅・配色・出典表記を作り直すたびにそろえ直す必要があり、手作業では再現できないためである。地図・SHAP 図・ワークフロー図の生成は本 Issue 限りの作業として扱い、`presentations/` が Git 管理外で PR に乗らないためスクリプトを入れていない。継続的に作り直す必要が生じた場合は同様に `src/` への配置を検討する。
