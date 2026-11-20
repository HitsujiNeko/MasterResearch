<!--
見出し: 2.3　公開GISデータ
状態: 初稿
依拠する正本:
  - docs/01_planning/available_gis_data.md @ b215285e88
  - docs/01_planning/urban_structure_parameters.md @ d3016a99cd
  - docs/01_planning/gis_data/ @ 58a227611f
-->

## 2.3　公開GISデータ

### 2.3.1　採用したデータセット

衛星＋公開GISデータのシナリオでは，全球または広域で公開され，測量データを持たない都市でも入手できる GIS データを，説明変数の算出に用いる．採用したデータセットを @tbl:open_gis_data に，ROI での分布を @fig:osm_roads〜@fig:viirs_dnb に示す．

| 対象 | データセット | 算出する変数 | 形式・解像度 | 時点 | ライセンス |
|----|------------|----------|--------|----------|-------|
| 道路 | OpenStreetMap（Geofabrik の Vietnam 抽出データ）[@osm_geofabrik_vietnam] | 道路密度 | 道路中心線（ベクタ） | 2026 年 4 月 8 日時点 | ODbL 1.0 |
| 建物 | GlobalBuildingAtlas（GBA）v1.0.0[@zhu2025_gba] | 建物被覆率・棟数密度・建物高さ | 建物ポリゴン（ベクタ） | 輪郭は 2021〜2023 年ごろ，高さは 2019 年ごろの画像による（推定） | CC BY-NC 4.0 |
| 標高 | FABDEM v1.2[@hawker2022_fabdem] | 平均標高 | ラスタ・約 30 m | — | CC BY-NC-SA 4.0 |
| 土地被覆 | GLC_FCS30D[@zhang2024_glc_fcs30d] | 土地被覆クラス別面積率 | ラスタ・30 m | 2022 年 | CC BY 4.0 |
| 人口 | WorldPop（100 m の人口）[@worldpop_global_100m] | 人口密度 | ラスタ・約 93 m | 2020 年 | CC BY 4.0 |
| 夜間光 | VIIRS DNB 年次合成 V2.2[@elvidge2021_viirs_vnl] | 夜間光強度 | ラスタ・約 460 m | 2023 年 | [要出典] |

: 衛星＋公開GISデータのシナリオで用いる公開 GIS データ {#tbl:open_gis_data}

GIS データの時点は，2020 年（人口）から 2026 年（道路）までばらつき，時点が主採用の観測（2022 年）と確実に一致するのは土地被覆だけである．この時点のずれは，結果を解釈する際の制約となる．各データから変数を算出する方法と，データごとの有効域の扱いは第3章で述べる．

**道路**には OpenStreetMap を用いる．OpenStreetMap は利用者の編集によって作られるため，完全性と精度には地域差がある．ハノイは比較的整備が進んでいるが，車線数や路面の材質などの属性は入力率が低いため，属性に依存する指標には用いない．ROI 内の道路は 194,485 本，総延長は 33,668.1 km であり（@fig:osm_roads），本数の 51.6% を住宅地の道路（総延長 18,077.0 km）が占める．道路密度の算出には，このうち幹線道路・一般の車道・サービス道路の中心線だけを用い，歩道や自転車道，農道や工事中の道路は除く．

![OpenStreetMap の道路（ROI 内の全種別）](images/gis_data/roads/roads_osm_hanoi.png){#fig:osm_roads width=60%}

**建物**には GBA を用いる．GBA は建物の輪郭（フットプリント）と機械学習で推定した高さを組み合わせた全球の建物データであり，ベトナムの輪郭は Google Open Buildings V3 に由来する．ROI 内の建物は 3,071,511 件で（@fig:gba_buildings），輪郭の面積の中央値は 51.8 m² と小さく，80.7% が 100 m² 未満である．輪郭と高さは元にした衛星画像の時点が異なり，高さは現地の測量値ではなく衛星画像からの推定値である．高さは 0.0062〜169.42 m に分布し，建物として成り立たない 1 m 未満の値が 80,332 件（2.6%）含まれる．ハノイでの高さの精度は確かめていない．

![GBA の建物の輪郭](images/gis_data/buildings/buildings_gba_hanoi.png){#fig:gba_buildings width=60%}

**標高**には FABDEM を用いる（@fig:fabdem）．FABDEM は，Copernicus DEM から建物と森林による高さの偏りを機械学習で除いた，地表面に近い標高データ（準 DTM）である．ハノイ中心市街地の一部（約 8 km × 11 km）を覆う 10 m の標高データ（BSHorizon DEM）と比べた結果，比べた 4 つの公開標高データのうち誤差が最も小さく（RMSE 3.88 m，MAE 3.20 m），相関が最も高かった（相関係数 0.603．他の 3 つは 0.45〜0.48）ため採用した．ただし，偏りを除いた後も BSHorizon DEM より平均で約 3 m 高く，高密度の樹冠や急峻な地形では補正の残差が残る．高さの基準は EGM2008 であり，0 m は平均海面と一致しない．FABDEM の利用条件に従い，次の帰属表示を記す．FABDEM is produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.

![FABDEM の標高](images/gis_data/dem/dem_fabdem_hanoi.png){#fig:fabdem width=60%}

**土地被覆**には GLC_FCS30D を用いる（@fig:glc_fcs30d）．GLC_FCS30D は Landsat の時系列から作られた土地被覆図であり，35 の詳細なクラスを持つ．解像度が分析グリッドの最小単位（30 m）と一致し，主採用の観測と同じ 2022 年の図を使える．ROI 内に欠測はなく，15 のクラスが現れる．ROI では，灌漑農地が 51.80%，不透水面が 19.99%，天水農地が 13.75%，密な常緑広葉樹林が 6.38%，水域が 5.50% を占める．不透水面は中心市街地に集まり，郊外は農地が大半を占める．なお，年ごとの図を比べると，不透水面の割合は 2018 年の 20.68% から 2022 年の 19.99% へ減っており，分類が年によって揺らいでいる可能性がある．

![GLC_FCS30D の土地被覆（2022 年）](images/gis_data/lulc/lulc_glc_fcs30d_hanoi.png){#fig:glc_fcs30d width=60%}

**人口**には WorldPop を用いる（@fig:worldpop）．WorldPop は国勢調査の人口を，衛星画像から得た土地利用などの情報を手がかりに格子へ配分した居住人口のデータであり，本研究では居住域に限らず全陸域に配分する版を用いる．このため，農地など人の住まない土地にも人口密度の値が入る．ROI 内の総人口は 8,441,385 人で，人口密度の平均は 2,586.5 人/km²，中央値は 1,232.4 人/km²，最大値は 68,565.6 人/km² である．本研究で取得に用いた Google Earth Engine の収録では，ベトナムの WorldPop は 2020 年までしかなく，主採用の観測とは 2 年の差がある．大規模な水域の画素は無効値となっており，ROI 内の有効画素率は 0.9723 である．

![WorldPop の人口密度（2020 年）](images/gis_data/population/population_worldpop_hanoi_2020.png){#fig:worldpop width=60%}

**夜間光**には，Suomi NPP 衛星の VIIRS Day/Night Band（DNB）による夜間光の年次合成（V2.2．米国海洋大気庁が提供し，Colorado School of Mines の Earth Observation Group が処理したもの）を用いる（@fig:viirs_dnb）．2023 年の合成を用い，ROI 内に欠測はない．年次合成の元になる雲のない観測は，ROI 内の画素あたり 51〜96 回ある．放射輝度（nW·cm⁻²·sr⁻¹）の中央値は 2.717，95 パーセンタイルは 21.348，最大値は 96.100 であり，中心市街地でも値の飽和は認められない．画素は約 460 m で分析に用いるどのグリッドよりも粗く，セルの値は実質的に内挿になる．

![VIIRS DNB の夜間光（2023 年の年次合成）](images/gis_data/nighttime_lights/nighttime_lights_viirs_dnb_hanoi_2023.png){#fig:viirs_dnb width=60%}

### 2.3.2　感度分析に用いるデータセット

主な分析とは別に，データの選び方によって結果が変わるかを確かめる感度分析のため，次の 4 つのデータセットを取得している．これらは主な分析の説明変数には用いない．

- **土地被覆**: Esri の Sentinel-2 10 m 土地被覆図（2022 年）[@karra2021_esri_lulc]．市街地として抽出される範囲の解釈の幅を確かめるために用いる
- **水域**: JRC Global Surface Water v1.4[@pekel2016_jrc_gsw]．Landsat の時系列から水域の出現頻度と季節性を求めたデータで，収録は 2021 年までである．土地被覆から求める水域の面積率を差し替えるために用いる
- **人口**: LandScan Global（2020 年・2023 年）[@lebakula2025_landscan]．居住人口ではなく，日中の移動も含めてその場所にいる人口（実効人口）を推計したデータで，解像度は約 928 m である．人口の概念と年の違いによる影響を確かめるために用いる
- **夜間光**: NASA の Black Marble（年次の VNP46A4，2023 年）[@roman2018_black_marble]．月光や観測角度の影響を補正した夜間光のデータであり，VIIRS DNB と差し替えるために用いる

これらを用いた感度分析の結果は，結果の章で述べる．
