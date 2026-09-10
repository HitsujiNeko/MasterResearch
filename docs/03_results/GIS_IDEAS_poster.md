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
| 全幅 | 1 | Background | 553.7 mm | 74 mm | 散文（4 行）＋研究設問の枠（22pt・2 行） |
| 全幅 | 2 | Study area and datasets | 553.7 mm | 128 mm | ROI 位置図（95 × 83 mm）・LST 図（57 × 83 mm）・データセット一覧表 |
| 全幅 | 3 | Method | 553.7 mm | 131 mm | ワークフロー図・算出方法・15 変数の内訳表（4 群）・算出済みラスタ 6 点（各 29 mm 幅） |
| 左列 | 4 | Model performance | 270.9 mm | 202 mm | キーメッセージ・モデル性能表・読み方・SHAP 依存プロット（191 × 84 mm） |
| 右列 | 5 | Variable importance | 270.9 mm | 202 mm | キーメッセージ・所見・SHAP 棒グラフ（172 × 76 mm）・順位表 |
| 全幅 | 6 | Conclusions and limitations | 553.7 mm | 59 mm | 結論 2 項目・限界 3 項目の 2 列＋次の一手 |
| 全幅 | — | 参考文献 | 496 mm | 25 mm | パネル 6 の下・テンプレートの白帯（y 781〜806 mm） |

**読み順は「全幅 → 2 列 → 全幅」にそろえる。** パネル 1〜3 を全幅で上から読み、パネル 4（左）・5（右）へ分かれ、パネル 6 で再び全幅へ戻る。左右を往復せずに読み切れる並びであり、結論が最下段の全幅に来ることで存在感も出る。

**体裁は内容に合わせて使い分ける。** 背景は文脈をつなぐ必要があるため散文、データと結果は表、限界は箇条書き、手法は図で示す。パネルの大きさも内容に応じて変える。

**紙面は満杯である。** 上記の配置で各パネルの下端に残る余白は 2〜12mm しかない。図表を 1 点足すには、同じ高さの何かを落とす必要がある（実際、SHAP 依存プロットを入れるために変数セット比較表を落とした。6 章 Q6 を参照）。

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

日本語: 都市のヒートアイランド現象を理解し緩和策を設計するには、地表面温度（LST）と都市構造の関係を空間的に評価する必要がある。ランダムフォレストによる都市形態変数の重要度評価（Sun et al., 2019）や、熱帯都市における回帰分析と機械学習の併用（Garzón et al., 2021）が報告されている。一方でベトナムを含む多くの途上国都市では、建物形状や道路ネットワークを網羅的に記述した高品質な GIS データの入手が難しい。また、NDVI と NDBI だけでは建物高さや人口密度を表現できないことが指摘されている（Le Ngoc Hanh & Tran Thi An, 2025）。  
English: Understanding urban heat islands and designing mitigation measures requires a spatial evaluation of how land surface temperature (LST) relates to urban structure. Random forests have been used to rank urban-form variables (Sun et al., 2019), and regression has been combined with machine learning in tropical cities (Garzón et al., 2021). In many developing cities, including those in Vietnam, it remains difficult to obtain high-quality GIS that comprehensively describes building geometry and road networks. NDVI and NDBI alone cannot represent building height or population density (Le Ngoc Hanh & Tran Thi An, 2025).

**GIS データの入手難と NDVI/NDBI の限界は、文を分けて書く。** 1 文にまとめて末尾へ引用を置くと、引用が前半にも掛かって読める。**Le Ngoc Hanh & Tran Thi An (2025) は GIS データの入手難については何も述べていない**（原典に GIS data・availability・road network・building geometry・data scarcity のいずれの言及も無い）。前半は本研究の前提であり、出典を伴わない。

日本語: **本研究は、衛星データと公開 GIS の組み合わせによって都市空間密度——建物・道路・土地被覆・人口が 30m セルごとにどう混在し、どれだけ詰まっているか——をどこまで定量化でき、ハノイの LST 分布をどこまで説明できるかを問う。**  
English: **This study asks how far satellite data combined with open GIS can quantify urban spatial density – the mix and packing of buildings, roads, land cover and people in each 30 m cell – and explain the LST distribution of Hanoi.**

**この一文はパネル地色より濃い枠（`#E4E8F2`）で囲み、22pt・2 行で置く。** 散文の末尾に同じ体裁で並べると読み飛ばされるためである。

**枠の中に用語の注釈を挟む。** "urban spatial density" は**この分野の標準語ではない**（引用 3 本の原典での出現回数は 0 回。使われるのは urban form＝S4 で 83 回、urban density＝S6 で 3 回、urban structure＝S2 で 1 回）。定義はパネル 3 に置いているが、読み手はタイトルとこの枠という**最も目立つ 2 箇所で、定義のないままこの語に 2 回出会う**ことになる。注釈は概念の平易な言い換えであり、枠を 2 行に収めるため 4 要素へ絞っている（標高は落とした）。**この注釈がポスター上での唯一の説明**であり、パネル 3 では定義を繰り返さない。

> **出所**: [GIS_IDEAS_abstract.md](GIS_IDEAS_abstract.md) 5 章（Introduction）を土台に、Limited シナリオ向けへ書き換えた。引用文献は [previous_studies_report.md](../04_archive/previous_studies_report.md) を参照する。  
> **原典照合（2026-09-04 実施）**: 3 件とも `docs/04_archive/04_pdfs/` の PDF 本文で確認した。<br>・**Sun et al., 2019**（Yanwei Sun, Chao Gao, Jialin Li, Run Wang, Jian Liu / Remote Sensing 11(8):959）: OLS と RF を構築し、Figure 10 で %IncMSE と IncNodePurity による**変数重要度のランキング**を提示。NDVI と建物密度が最重要。<br>・**Garzón et al., 2021**（Julián Garzón, Iñigo Molina, Jesús Velasco, Andrés Calabia / Remote Sens. 13:4256）: 熱帯コロンビア都市で PCA・MLR に SVM と Naïve Bayes を組み合わせている。<br>・**Le Ngoc Hanh & Tran Thi An, 2025**: 3.4 節 Limitations に "the exclusive use of NDVI and NDBI ... they do not capture other critical dimensions of urban dynamics, such as population density, building height, land use diversity, or socio-economic variables" とある。**著者自身の研究の限界**として書かれている点に注意する（質疑では出所をそう答える）。ポスターの記述は原典より狭い（原典は land use diversity と socio-economic variables も挙げている）。  
> **注意**: 先行研究の精度指標を本研究と横並びに比較しない。両論文とも本文と表に数値の不整合があり、**数値を引用する場合は原典の表を優先する**（同 S9.7 節・S10.8 節）。

### パネル 2: Study area and datasets

日本語: 単一の Landsat 8 シーン、2023 年 7 月 7 日・現地時刻 10:23（03:23 UTC）。実効 ROI カバー率（シーン被覆率 × 有効画素率）により、候補 132 件から選定した。  
English: A single Landsat 8 scene: 7 July 2023, 10:23 local time (03:23 UTC), selected from 132 candidates by effective ROI coverage (footprint × valid pixels).

本文はこの見出し脇の一文と、表の下の注記のみで、あとは図（ROI 位置図・LST 図）と表で構成する。

**セル数・実効 ROI カバー率・LST 有効被覆率は載せない。**

- **3,739,454 セル**は分析上の内訳にすぎず、母数はパネル 3 のワークフロー図が品質フィルタ後の 3,274,665 セルとして持っている
- **LST 有効被覆率 89.26%** は、LST 図の北東部に雲による白い抜けとして見える。ポスター表示サイズでも斑に見えるため、数字で言い直す必要がない
- **実効 ROI カバー率 88.7%（3 位）**は、順位に触れると「なぜ 1 位を使わないのか」を招く。1 位（`2024-11-30T03:23:36`・93.9%・雲量 0.02%）を見送った理由は「11 月＝乾季であり、7 月＝雨季を前提とした他の分析と季節軸が合わない」だが、**これは読み手が検証できない内部事情**であり、かつ測れる指標すべてで勝るシーンを見送ったことを自ら告知することになる。順位ではなく**選定基準そのもの**を述べる（[observation_selection.md](../02_methods/observation_selection.md) 4.2 節）

**選定基準の名前だけを書き、その含意は書かない。** 実効 ROI カバー率への見直しは、有効画素率だけで選ぶと ROI の半分しか覆わないシーン（従来観測 `032329`・52.3%）が選ばれうる、という知見に基づく（[PR #274](https://github.com/HitsujiNeko/MasterResearch/pull/274)）。ただしこの含意をポスター面に書くと説明が一段増えるため、面には基準名のみを置き、経緯は本原稿に残す。

**観測時刻を明記する。** 午前と午後では LST の意味が変わるため、日付だけでは足りない。

**データセット一覧表**

| Data | Source | Year / date | Type | Parameters derived |
|---|---|---|---|---|
| Thermal + optical | Landsat 8 C2 L2 | 2023-07-07 | Raster 30 m | LST, NDVI, NDBI, NDWI |
| Buildings | GlobalBuildingAtlas v1.0.0 | imagery 2021–2023 | Vector | Coverage, density, height |
| Roads | OpenStreetMap (Geofabrik) | 2026-04 | Vector | Road density |
| Land cover | GLC_FCS30D | 2022 | Raster 30 m | Land-cover class fractions |
| Population | WorldPop | 2020 | Raster ~92 m | Population density |
| Night lights | VIIRS DNB | 2023 | Raster ~460 m | Night-time light |
| Elevation | FABDEM v1.2 | imagery 2010–2015 | Raster 30 m | Elevation |

**先頭に `Data` 列を置く。** `GlobalBuildingAtlas` / `GLC_FCS30D` / `FABDEM` / `VIIRS DNB` は製品名だけでは何のデータか判断できず、`Parameters derived` から逆算させるのは読み手の負担になる。製品名は `Source` 列へ移す。左 2 列は左寄せにする（語長がまちまちな列を中央寄せにすると行ごとに開始位置がずれる）。

**列見出しは `Year / date` とする。** シーン日付・撮像期間・製品年が混在する表に `Epoch` は硬い。

**FABDEM の年代は原データにさかのぼって書く。** FABDEM v1.2 は Copernicus WorldDEM-30 由来であり、その原観測は TanDEM-X の 2010 年 12 月〜2015 年 1 月である（[gis_data_dem.md](../01_planning/gis_data/gis_data_dem.md)、GEE カタログ記載）。「Copernicus-derived」では読み手に年代が伝わらないため、他行と同じ形式にそろえる。

**`Elevation` は「Mean」を付けない。** 全パラメータがセル単位の空間統計量であり、標高に平均以外の選択肢を採る予定もないためである。**`Mean building height` は「Mean」を残す**（`BUILD_H_MAX` を用いる分析バリアントが実在し、本結果は `bh_mean` を採用しているため）。

**表の下の注記**

日本語: 建物高さ・人口・土地被覆は推計されたプロダクトであり、現地の実測値ではない。本研究はそれらの当地での精度を検証していない。  
English: Building heights, population and land cover are modelled products, not field measurements; their local accuracy is not assessed in this study.

**「公開データだけで説明できる」が本研究の主張である以上、その公開データが実測ではなく推計であることは主張の一部である。** 根拠は次のとおり。

- **人口**: [gis_data_population.md](../01_planning/gis_data/gis_data_population.md) 「国勢調査（行政区画単位の集計値）を何らかの補助データで空間的に按分した推計値であり、実測データではない」。WorldPop は 2019 年ベトナム国勢調査を Random Forest で再配分している
- **建物高さ**: [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) 「衛星画像から機械学習で推定した値であり、現地測量値ではない」「ハノイ ROI での高さ推定精度（RMSE 等）は本研究では未検証」
- **土地被覆**: GLC_FCS30D は分類結果であり、同じく推計である

**図のキャプション**

| 図 | English | 日本語 |
|---|---|---|
| 左 | Hanoi ROI, Vietnam | ハノイ ROI（ベトナム） |
| 中 | LST (target variable) | 地表面温度（目的変数） |

> **出所**: 年代・種別は各 gis_data ドキュメント（[gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) 3 章、[gis_data_lulc.md](../01_planning/gis_data/gis_data_lulc.md)、[gis_data_population.md](../01_planning/gis_data/gis_data_population.md)、[gis_data_nighttime_lights.md](../01_planning/gis_data/gis_data_nighttime_lights.md)、[gis_data_dem.md](../01_planning/gis_data/gis_data_dem.md)、[gis_data_roads.md](../01_planning/gis_data/gis_data_roads.md)）。観測選定は [observation_selection.md](../02_methods/observation_selection.md) 3 章・5 章。  
> **補足**: 従来用いていた同日 03:23:29 の観測は実効 ROI カバー率 52.3%（12 位）にとどまり、これが観測を差し替えた直接の動機である。

### パネル 3: Method

日本語: **すべてのレイヤーが、ひとつの 30m グリッド上のセル単位の統計量になる。**  
English: **Every layer becomes a per-cell statistic on one 30 m grid.**

日本語: ベクタデータからは 3 種類の統計量が得られる。被覆率（ラスタ化したフットプリントから求めた、セル面積に占める割合）、密度（ha 当たりの地物数または延長）、平均建物高さである。  
English: Vector data give three kinds of statistic: coverage (share of cell area, from rasterised footprints), density (features or metres per hectare) and mean building height.

**見出しを `Method` にする。** 従来の `From datasets to urban parameters` はパラメータ算出までを指すが、ワークフロー図は Sampling・Models・Evaluation まで進んでおり、実質は手法全体である。見出しのほうを内容へ合わせる。

**概念の定義を繰り返さない。** 平易な説明はパネル 1 の研究設問の枠（`the mix and packing of buildings, roads, land cover and people in each 30 m cell`）が済ませている。本パネルの役割は「どう算出したか」であり、従来ここに置いていた 3 行の定義文は落とす。

**算出方法を明示する。** 従来は `zonal statistics` と `Vector layers become continuous densities` の 2 語しかなく、道路密度や建物系パラメータをどう作ったかが読み取れなかった。算出の型は 3 種類あるため、それを示す（[calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6 章）。

- **被覆率**（`BUILD_COV`, 0–1）: fine グリッドへラスタ化し coarse セルへ平均集約
- **密度**（`BUILD_DEN` 棟/ha, `ROAD_DEN` m/ha）: 重心が属するセルごとの棟数、またはセル内ライン総延長を、セル面積で正規化
- **平均建物高さ**（`BUILD_H_MEAN`, m）: 有効高さを fine グリッドへラスタ化し平均集約（被覆が無いセルのみ重心方式で補完）

**道路のホワイトリスト条件は紙面に載せない**（motorway〜living_street ＋ service を採用し、歩道・階段・小径・トラック・トンネルを除外）。質疑で問われた場合に答える。

**主語 `We` を使わない。** 共著論文で `we` を用いること自体は標準だが、ポスターは字数が惜しく、主語を落とせばそのぶん短くなる。パネル 5 の `We rely on ...` も `Ranking uses ...` へ改めた。

**15 変数の内訳表（パネル 5 の SHAP 図と同じ 4 群・同じ色）**

| 群 | 色 | 内訳 |
|---|---|---|
| Satellite indices (3) | `#D85A30` | NDVI, NDBI, NDWI |
| Land cover (5) | `#1D9E75` | built-up, tree, water, rangeland, wetland fractions |
| Building / road (4) | `#378ADD` | coverage, density, mean height, road density |
| Population / light / elevation (3) | `#7F77DD` | population density, night-time light, elevation |

**散文の列挙をやめ、群ごとの表にする。** 従来は 15 変数を 1 文で並べており、読み手が目で数えないと構成が掴めなかった。**この 4 群はパネル 5 の SHAP 棒グラフの凡例に既に存在する。** 同じ名前・同じ色で示すことで、読み手はパネル 3 で分類を覚え、パネル 5 の棒グラフの色でそれを再認できる。

**ワークフロー図から重複と細部を削る。**

| 箱 | 変更 | 理由 |
|---|---|---|
| Satellite and open GIS data | 7 項目の列挙を削除。`open GIS` → `open GIS data` | 列挙はパネル 2 の表が出典・年代つきで示しており完全に重複する。`Satellite and open GIS` は `and` の前後が揃わない省略形であり、`data` を補って並びを直す。**`open` は落とさない**——本研究の主張（公開データだけでどこまで説明できるか）を担う語であり、落とすと Full シナリオでも通る記述になる。あわせて OGC の旧名称 `OpenGIS` との紛らわしさも減る |
| Urban parameters | `one row per cell_id` → `one row per cell` | `cell_id` は内部の列名 |
| Sampling | `random seed 42` を削除 | 再現性の主張としても、箱の 1 行を使う価値は無い |
| Models | `15 predictors` を削除。`MLR` → `multiple linear regression (MLR)` | 内訳表が変数の数を持つ。`MLR` はポスター全体でここでしか展開されない |

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

### パネル 4: Model performance

日本語: **公開データだけで、空間交差検証の R² 0.760 に到達する。**  
English: **Open data alone reaches R² 0.760 under spatial cross-validation.**

**キーメッセージを冒頭に置く。** 本研究の中心的な答えは、従来このパネルでは**表のセルの中にしか存在せず**、文として述べられるのはパネル 6 の結論まで待つ形だった。紙面で最も重要な数字が最も弱い形に置かれていたことになる。

**順序を「キーメッセージ → 表 → 但し書き」にする。** 従来は表の直後に 3 行の但し書きが来ており、読み手が成果を知る前に限界を読む順序になっていた。

**モデル性能**

| Model | Random split R² | Spatial CV R² | RMSE (°C) |
|---|---|---|---|
| MLR | 0.646 | 0.645 | 1.47 |
| Random forest | 0.796 | 0.760 | 1.11 |

日本語: RMSE 1.11°C に対し、LST の標準偏差は 2.49°C である。この R² は同一 ROI 内への内挿性能として読む。汎化性能ではない。2,700m のブロックは空間自己相関を断ち切れていない（セミバリオグラムの sill は 15〜30km）。  
English: RMSE 1.11 °C against an LST standard deviation of 2.49 °C. Read these R² as interpolation within the same ROI, not generalisation: 2,700 m blocks do not break the spatial autocorrelation (semivariogram sill 15–30 km).

**RMSE に対比の相手を与える。** 1.47 / 1.11°C という数字だけでは良し悪しの手がかりが無い。標本 10 万件の LST 標準偏差 2.49°C（`..._sample_100000.csv` で実測）と並べると意味が出る。`1 − (1.11 / 2.49)² = 0.80` であり、ランダム分割の R² 0.796 とも整合する。

**但し書きの書き出しを変える。** 従来の `Only the RF drops under spatial CV.` は議論の途中から始まっており、読み手はまだ空間交差検証が何のためにあるかを知らない。加えてこの一文の含意（線形モデルが下がらないのは安心材料ではない）を理解するには前提が要る。結論（内挿として読む）を先に置く。

**`MLR` はパネル 3 のワークフロー図で一度だけ展開する**（`multiple linear regression (MLR) and random forest`）。この表とワークフロー図で計 2 回出るが、従来はどこでも展開されていなかった。

**NDBI の寄与の形（SHAP 依存プロット）**

日本語: 建築指数の効きは低い側で頭打ちになる。NDBI の寄与は中央値で −0.77〜+2.51°C の幅を持ち、NDBI −0.4 を下回ると下げ止まる。  
English: The built-up signal saturates at the low end: the median contribution of NDBI runs from −0.77 to +2.51 °C and stops falling below NDBI −0.4.

**この見出しはキーメッセージにしない。** 1 つのパネルに太字の主張が 2 つあると両方が弱まるため、太字はパネル冒頭の 1 つに統一し、こちらは通常の本文として置く。

**この図はポスターで唯一、「どの変数が効くか」ではなく「どう効くか」を示す。** パネル 5 の棒グラフが寄与の大きさを順位づけるのに対し、こちらは寄与の形と摂氏での大きさを示す。

**依存プロットの縦軸は外れ値（+5.5 付近の 1 点）に引き伸ばされているが、切らない。** 実質的な構造は −1〜+3 にあり図の上 3 割強が空くが、範囲を切ると「都合の悪い点を隠した」と見えるリスクのほうが大きい。

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 4.1 節・4.2 節・3.9 節、2 章の台帳（ラン1）。RMSE は摂氏で読む。  
> **依存プロットの数値の出所**: `presentations/poster_assets/shap_values_run1.csv`（Git 管理外）。分析本体は SHAP 値そのものを保存しないため、同一条件で再算出した（7 章）。24 区間の等頻度ビンごとの中央値をとり、その最小 −0.770°C・最大 +2.514°C（振れ幅 3.284°C）を上記に採った。中央値が 0 を横切るのは NDBI −0.226〜−0.205 の区間である。  
> **注意**: SHAP 値は**予測 LST への寄与**であり、観測 LST の変化量ではない。また、この非線形性をもって「RF が線形モデルを上回る理由」と読ませない（6 章 Q3 のとおり、RF の優位の相当部分は空間自己相関の利用と考えられる）。  
> **補足**: ブロックを広げると RF の R² は単調に低下する（ランダム分割 0.7954 → 2,700m 0.7596 → 21,600m 0.5461。診断設定・RF 100 本）。線形モデルはほぼ動かず、RF が線形を上回る幅は +0.115 から +0.023 へ縮む。**RF の優位の相当部分は、非線形性の捕捉ではなく空間自己相関の利用である可能性が高い**（同 3.9 節。詳細は 6 章の想定問答 Q3）。

### パネル 5: Variable importance

日本語: **`NDBI` が支配的である。ただし首位は指標によって入れ替わる。**  
English: **NDBI dominates – but the leader depends on the measure.**

日本語: 分光指数と土地被覆分類が信号を担っており、建物・道路のベクタデータの寄与は最も小さい。  
English: The spectral and land-cover proxies carry the signal; the building and road vectors contribute least.

**この所見は図に写っているが、言葉にしないと読み手が自分で読み取るしかない。** `NDBI` 0.702 に対し、建物・道路の実データは平均建物高さ 0.046・道路密度 0.026・建物被覆率 0.007 であり、**15〜100 倍の開きがある**。「公開 GIS をどこまで足せるか」を問う本研究にとって中心的な所見であるため、図任せにせず本文へ置く。

**キーメッセージの直下に置き、図より先に読ませる。** 当初は図の下へ置いたが、棒グラフの高さが 96mm から 82mm へ落ちたため移した。主張を先に述べ、図がそれを裏づける順序になる。

**原因は断定しない。** 建物高さはセルの 72.66% がゼロ補完で「有無」と「高さ」を分離できておらず（パネル 6 の限界）、寄与の小ささをデータの質だけに帰することはできない。本文は**観察事実の記述にとどめる**。

**指標別の上位 3 変数**

| Rank | SHAP | Permutation | RF impurity |
|---|---|---|---|
| 1 | NDBI 0.702 | NDBI 0.313 | Built-up cover fraction 0.474 |
| 2 | Built-up cover fraction 0.432 | Elevation 0.144 | NDBI 0.141 |
| 3 | Population density 0.377 | Population density 0.142 | Elevation 0.082 |

**変数名は棒グラフの表示名にそろえる。** 従来は棒グラフが `Built-up cover fraction` / `Population density`、順位表が `Built-up cover` / `Population` と、同じ変数を別名で書いていた。

日本語: 同じ問いに対する 3 とおりの尋ね方である。順位づけは SHAP と Permutation 重要度を併せて用いる。RF の不純度ベース指標だけが建築被覆率を首位に置く。  
English: Three ways of asking the same question. Ranking uses SHAP and permutation importance together: the RF impurity measure alone puts built-up cover first.

**注記の冒頭で「3 つは別の手法である」ことを述べる。** これを知らない読み手には順位の食い違いがノイズに見え、「単一指標で語らない」という表の主張が伝わらない。**なぜ不純度ベースを主にしないのか**（連続変数・取りうる値の多い変数へ偏る）は 1 行増えるため紙面には載せず、質疑で答える。

**棒グラフは上位 10 変数のみを描く。** 15 個すべてを並べると A1 の紙面で 1 本あたりの高さが足りない。落とす 5 本は樹木被覆率 0.011・湿地被覆率 0.009・建物被覆率 0.007・建物棟数密度 0.005・草地被覆率 0.003 であり、いずれも首位（`NDBI` 0.702）の 2% 未満で本文でも論じない。落としても「少数の変数が大半を占める」という形は残る（最下位に残る道路密度は 0.026）。

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 5.1 節、`..._feature_importance.csv` / `..._shap_importance.csv`。  
> **補足**: 不純度ベース重要度は取りうる値が少ない変数で挙動が変わりうる。上位 4 変数の順位は標本を変えても安定するが、第 5・6 位（`NDVI` と `NDWI`）は入れ替わるため、5 位以下の順位差は論じない（同 2.1 節）。

### パネル 6: Conclusions and limitations

日本語: **測量 GIS を持たない都市でも、熱の分布を捉えることはできる。**  
English: **Cities without survey GIS can still map their heat pattern.**

**キーメッセージは含意に寄せる。** 従来の「公開データだけで LST 分布の大半を説明できる」はパネル 4 のキーメッセージ（`Open data alone reaches R² 0.760 under spatial cross-validation.`）と同じことを述べており、**同じ事実が紙面に 3 回**（パネル 4 のキー・パネル 6 のキー・パネル 6 の箇条書き 1）出ていた。含意へ寄せることで重複が 2 回になり、結論パネルでの再掲という通常の範囲に収まる。

**列に見出しを付けて、結論と限界を分ける。** 従来は 2 列の分割が意味ではなく場所の都合であり、左列に結論と限界が混在していた。

**Conclusions（左列）**

1. 日本語: ランダムフォレストは公開データのみで Spatial CV の R² 0.760 に到達する。  
   English: Random forest reaches R² 0.760 under spatial CV from open data alone
2. 日本語: 信号を担うのは分光指数と土地被覆分類であり、建物・道路のベクタではない。  
   English: Spectral indices and land cover carry the signal, not the building and road vectors

**Limitations（右列）**

1. 日本語: Spatial CV の R² は内挿性能である。単一観測・ハノイ単独・30m のみの結果である。  
   English: Spatial CV R² is interpolation; single scene, Hanoi only, 30 m
2. 日本語: セルの 72.66% が建物高さ 0m の補完である。`NDVI` と `NDWI` の VIF は 32.24・34.56 に残る。  
   English: 72.66% of cells are imputed as 0 m height; NDVI and NDWI VIFs stay at 32.24 and 34.56
3. 日本語: 説明変数のレイヤーは観測と同時期ではない。人口は 2020 年、道路は 2026 年、シーンは 2023 年である。  
   English: Predictor layers are not contemporaneous: population 2020, roads 2026, scene 2023

**年代のばらつきを限界として引き受ける。** パネル 2 の表は各データの年代を正直に並べているが、**それが限界であることをどこにも書いていなかった**。表を見れば誰でも気づく点であり、先に自ら述べるほうが強い。建物高さと VIF は 1 項目へ統合して場所を作った。

**次の一手（全幅・パネル最下行）**

日本語: **次の一手: `NDWI` を SWIR 由来の MNDWI へ差し替えて `NDVI`–`NDWI` の共線性を断ち、そのうえで測量 GIS を加えた Full シナリオと比較する。**  
English: **Next: swap NDWI for the SWIR-based MNDWI to break the NDVI–NDWI collinearity, then add survey GIS (Full scenario).**

**最終行は来場者が話しかける入口になる。** 右列の限界「`NDVI` と `NDWI` の VIF」に対する直接の答えになっており、抽象的な「今後の課題」ではない。`NDVI` と `NDWI` はどちらも NIR に支配され符号が逆であるため Pearson −0.966 の**構造的**な相関を持ち、両方を投入する限り VIF は 14.96 を下回れない。MNDWI は SWIR1 を使うためこの構造を断てる（[#268](https://github.com/HitsujiNeko/MasterResearch/issues/268)）。

**枠の外へ出さない。** 当初はパネルの下の白帯へ置いたが、枠外に出ると本文の一部に見えない。パネルを 50mm から 59mm へ広げ、その 9mm はパネル 2（134→128mm）とパネル 3（134→131mm）の余白から回した。**パネル 4・5 の図の大きさは変えていない。**

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 5.1 節・3.9 節・6.5 節・1.3 節。年代は本原稿 2 章の使用データ一覧表。次の一手は [#268](https://github.com/HitsujiNeko/MasterResearch/issues/268)。  
> **補足**: 0m 補完セルと「被覆率・棟数密度がともに 0 のセル」の一致率は **100.000000%** である。この従属は VIF では検出できない（`BUILD_H_MEAN` の VIF は 1.72）。線形従属ではなく「ゼロか否か」の水準で生じているためである（同 3.9 節）。

---

### 参考文献（パネル 6 の下・全幅）

**著者・年形式で引用している以上、出典を辿れるようリストが要る。** `(Sun et al., 2019)` と書けば読み手は出典を探せる前提で読み、リストが無ければ辿れない。本ポスターは先行研究に対する位置づけで主張を立てているため、出典を欠くと土台が検証不能になる。3 件しかなく、省いて浮く場所もわずかである。

- Garzón, J. et al. (2021) A remote sensing approach for surface urban heat island modeling in a tropical Colombian city using regression analysis and machine learning algorithms. Remote Sensing 13, 4256.
- Le Ngoc Hanh & Tran Thi An (2025) Assessment of temperature change in Da Nang City, Vietnam using remote sensing and cloud-computing approach. The GIS-IDEAS Journal.
- Sun, Y. et al. (2019) Quantifying the effects of urban form on land surface temperature in subtropical high-density urban areas using machine learning. Remote Sensing 11, 959.

**置き場所はテンプレートの白帯である。** パネル 6 の下端（y 780.5mm）とフッタ紺帯の上端（y 809.8mm）のあいだに 29.3mm の白帯があり、左端は ID 円（右端 x 68.9mm）が占める。その右（x 78mm 以降）へ 11pt で置くと**パネルの高さを一切削らずに済む**。実測でフッタ帯まで 8.6mm の余裕がある。

**テンプレートに指示文は無い**（含まれる文字列は大学名・会期・`ID` の 3 つのみ）。学会側の要項に参考文献の規定があるかは**未確認**である。白帯を空けておくよう想定されている可能性は否定できないため、ID 円から 9mm 以上離している。

**著者名は et al. で詰める。** 3 件とも 1 行に収めるためであり、書誌情報は `papers_database.csv`（S6・S2・S4）と各 PDF の原本で確認済みである。

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
| ROI 位置図 | パネル 2 | `presentations/poster_assets/map_roi_location.png`（Git 管理外）。`src/visualization/roi_location_map.py` で生成（7 章） |
| LST 図 | パネル 2 | データセットから描画（7 章） |
| データセット一覧表 | パネル 2 | 本原稿 2 章 |
| ワークフロー図 | パネル 3 | [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) |
| 建物被覆率・平均建物高さ・道路密度・NDBI・人口密度・夜間光の図 | パネル 3 | データセットから描画（7 章） |
| モデル性能表 | パネル 4 | 本原稿 2 章 |
| SHAP 依存プロット（NDBI） | パネル 4 | 再算出した SHAP 値から描画（7 章） |
| SHAP 棒グラフ（上位 10 変数） | パネル 5 | `..._shap_importance.csv` から描画（7 章） |
| 指標別の上位 3 変数の表 | パネル 5 | 本原稿 2 章 |

| 参考文献 3 件 | パネル 6 の下（白帯） | 本原稿 2 章末 |

**変数セット比較表（spectral / coverage / both）はポスターに載せない。** SHAP 依存プロットと同じ高さを要し、A1 の紙面で両立しないためである。内容は 6 章 Q6 が引き受ける。

**ワークフロー図は 2 種類ある。** [fig3_limited_workflow.mmd](fig3_limited_workflow.mmd) は処理条件を追えるドキュメント用の詳細版（20 ノード・縦フロー）であり、**ポスターに載せると図中の文字が読めない**。ポスターには横流し 6 ステップの [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) を使う。

---

## 6. 想定問答（日英）

**パネルに載せなかった限定の詳細は Q3 が引き受ける。** ブロックサイズと空間自己相関の論証は短時間で追える種類ではないため独立パネルを置かず、こちらから先に提示する論点として扱う。**変数セットの比較は Q6 が引き受ける**（紙面の都合でパネルから外した。5 章を参照）。

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

### Q6. 分光指数と被覆率型変数では、どちらが効くのか

| Variable set | RF (spatial CV) | Linear (spatial CV) |
|---|---|---|
| Spectral only | 0.747 | 0.594 |
| Coverage only | 0.674 | 0.611 |
| Both | 0.760 | 0.645 |

日本語: **ランダムフォレストに限れば分光指数が上回るが、線形モデルでは向きが逆転する。** Spectral は NDVI・NDBI・NDWI、Coverage は土地被覆クラス別面積率を指し、どちらも共通ベース（建物・道路・人口・夜間光・標高）を含む。RF では spectral 0.747 > coverage 0.674、線形では coverage 0.611 > spectral 0.594 であり、**モデルを指定せずに「どちらが効く」とは言えない**。両方を入れた both が RF・線形とも最良である。3 ランは同一のセル・標本・ブロックを用いている。  
English: **For the random forest the spectral indices win, but the ordering reverses for the linear model.** Spectral = NDVI, NDBI, NDWI; coverage = land-cover class fractions; both variants also carry the common base of building, road, population, night-light and elevation variables. The RF gives spectral 0.747 > coverage 0.674, while the linear model gives coverage 0.611 > spectral 0.594, so **the claim cannot be made without naming the model**. Using both is best under either model. The three runs share identical cells, samples and blocks.

> **出所**: [limited_analysis_results.md](limited_analysis_results.md) 4.3 節・5.3 節・5.4 節、2 章の台帳（ラン1・3・4）。

---

## 7. ポスターの図の作り方

**ポスターに載せる地図と SHAP 図は、ドキュメント用の既存出力をそのまま使わない。** 理由は次の 3 点である。

- QGIS 出力（`images/` 配下）は**タイトルと凡例が日本語**であり、英語のポスターに貼れない
- 道路密度は 300m の出力しか無く、他が 30m なので粒度が揃わない
- 分析パイプラインが出力する SHAP 図は軸ラベルが列名（`LULC_BUILT_COV` 等）であり、初見の読み手が解読できない

そこで次の手順でポスター用に描き直す。

1. **地図**: `data/output/datasets/dataset_limited_20230707_032305_hanoi_30m.gpkg` から必要な列を読み、`cell_id = row × 1,000,000 + col` を行・列へ復号して 2 次元配列へ戻し、`matplotlib` で描画する。英語のカラーバーを付け、値域はパーセンタイルで切る（分光指数は 2〜98、その他は 0〜99）
2. **SHAP 棒グラフ**: `..._shap_importance.csv` の値をそのまま読み（再計算しない）、3 章の表示名で横棒グラフを描く。由来グループごとに色を分け、凡例を付ける。**上位 10 変数のみを描く**（理由は 2 章パネル 5）。**縦横比は貼付枠に寄せる**（`figsize=(11.0, 5.0)`）。9.0 × 5.0 では高さで頭打ちになり、列の左右に 80mm 以上の余白が残っていた
3. **SHAP 依存プロット**: 分析本体は SHAP 値そのものを保存せず図と平均 |SHAP| だけを出力するため、**同一条件で再算出する**。`..._sample_100000.csv` を読み、列順を `..._feature_importance.csv` から取り、`test_size=0.2` / `random_state=42` で分割、RF は 300 本・`min_samples_leaf=5`、SHAP は評価 2,000 点・背景 500 点（いずれも CLI 既定値）。得た平均 |SHAP| が `..._shap_importance.csv` と一致することを照合してから作図する
4. **ワークフロー図**: [fig4_limited_workflow_poster.mmd](fig4_limited_workflow_poster.mmd) を `mermaid-cli` で PNG へ書き出す
5. **ROI 位置図**: `python -m src.visualization.roi_location_map --output presentations/poster_assets/map_roi_location.png` を実行する。ROI（`data/gis/boundaries/hanoi/`）とベトナム国境（`data/gis/boundaries/vietnam/`・geoBoundaries ADM0）を OpenStreetMap の XYZ タイル上に重ね、方位記号・スケールバー・経緯度目盛・インセット・出典表記を付けて出力する。既定は幅 120mm・400dpi（1889 × 1667 px）

**描画時の注意（実際に踏んだ不具合）**

- **`imshow` の `origin` を明示する。** `row` は緯度と正の相関を持つ（`row` が大きいほど北）ため、既定の `origin="upper"` では**南北が反転する**。`origin="lower"` を指定する
- **小さく並べる図は凡例の文字を大きめに描く。** 31mm 幅で表示する図の凡例を既定サイズで描くと、印刷時に判読できない
- **カラーバーのラベルは図ごとに文字列長をそろえる。** ラベルが figure 幅に収まるまで自動縮小する実装にしていると、**ラベルが長い図ほど小さく描かれ、並べたときに文字サイズが不揃いになる**。小さく並べる 6 枚は変数名をポスター側のキャプションへ預け、カラーバーのラベルは単位だけ（`0–1`・`m`・`m / ha`・`persons / ha`・`nW cm⁻² sr⁻¹`）にして長さをそろえた
- **裾の重い分布は平方根スケールで描く。** 建物被覆率・棟数密度・平均建物高さ・道路密度はセルの 7 割以上がゼロ、人口密度と夜間光はごく一部に大きな値が集中する（`..._sample_100000.csv` で実測）。線形スケールでは大半のセルがカラーマップの最も淡い側へ潰れ、縮小すると**ほぼ白紙に見える**。`PowerNorm(gamma=0.5)` で低〜中間の値を広げる。正負に広がる分光指数は潰れないので線形のままとする
- **単位を確認してから凡例に書く。** 道路密度は m/ha、建物棟数密度は 棟/ha、人口密度は 人/ha である（セル当たりではない）
- **軸ラベルが figure に収まるか確かめる。** 軸ラベルは `bbox_inches="tight"` を指定しても、軸より長いと切れる（matplotlib は外接矩形の計算で軸ラベルを潰して扱うため）。カラーバーのラベルは**横**に、回転した y 軸ラベルは**縦**にはみ出す。依存プロットのように横長の図では軸の高さが低く、`Contribution to predicted LST (°C)` が 1 行では入らないため 2 行へ折り返した。判定は figure ではなく**軸**の寸法と比べる（figure と比べると x 軸ラベルのぶんを見落とす）
- **画像を枠へ収めるときは縦横比を保つ。** 高さで合わせてから幅を `min()` で切り詰めると、画像が横方向へ潰れる。両辺の比を比べて小さいほうの倍率を使う
- **ベースマップに CARTO のタイルを使わない。** `basemaps.cartocdn.com` は API キー無しの取得でタイル面に 「API KEY REQUIRED」の透かしが焼き込まれる。淡色のベースマップは OSM 標準タイルを減彩して得る
- **Web メルカトルのスケールバーは緯度補正する。** 座標上の長さは緯度 φ で `1/cos(φ)` 倍に伸びているため、そのまま地表距離として扱うとハノイ（北緯 21 度）で約 7% 過大になる

**pptx の組版**は `presentations/GIS-IDEAS-2026_poster_template.pptx` を土台に、装飾バンド・ロゴ・フッタを保持したまま図形を追記して行う。テンプレートは png の既定拡張子を宣言していないため、png を追加する場合は `[Content_Types].xml` へ `<Default Extension="png" ContentType="image/png"/>` を加える必要がある（宣言しないと PowerPoint がパッケージごと拒否する）。

**出典表記は行を分けて文字を確保する。** ROI 位置図の出典表記は、1 行に詰めると表記帯の幅を使い切り（実測 100.6%・わずかにはみ出していた）、貼付幅 120mm では 5.17pt にしかならなかった。1 行 1 項目（タイル配信元 / geoBoundaries / 投影法）の 3 行に分けて行長を抑え、そのぶん文字を大きくしている（基準サイズに対する比を 0.58 → 0.90、貼付幅で 8.02pt）。表示義務のある表記を先に置き、義務の無い投影法の注記を最後に回す。行長は同梱プロバイダの最長（Esri の 57 字）でも帯幅の 76.8% に収まる。

**再現スクリプトは ROI 位置図のみリポジトリに入れている**（`src/visualization/roi_location_map.py` と タイル取得の `src/visualization/xyz_tiles.py`）。ROI 位置図は貼付幅・配色・出典表記を作り直すたびにそろえ直す必要があり、手作業では再現できないためである。地図・SHAP 図・ワークフロー図の生成は本 Issue 限りの作業として扱い、`presentations/` が Git 管理外で PR に乗らないためスクリプトを入れていない。継続的に作り直す必要が生じた場合は同様に `src/` への配置を検討する。
