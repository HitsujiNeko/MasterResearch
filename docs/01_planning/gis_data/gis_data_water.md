# 水域データ（近接距離・面積率）の調査・評価

**最終更新**: 2026-11-10  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [gis_data_lulc.md](gis_data_lulc.md), [urban_structure_parameters.md](../urban_structure_parameters.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDWIとの違い）

---

## 1. 調査目的

本資料の作成時点で算出済みだった水域関連の指標は、衛星由来のNDWI（水域・湿潤域指標）のみである。その後、衛星由来のMNDWIと、土地被覆（GLC_FCS30D）由来の水域被覆率 `LULC_WATER_COV` が `Limited` シナリオに入った（[urban_structure_parameters.md](../urban_structure_parameters.md) §2.2・§3.2）。NDWI・MNDWIは連続値・単一時点の分光指標であり、水域の物理的な広がりや位置関係を直接表すものではない。都市構造パラメータとしては、以下の2種類の水域関連指標が候補となる。

- **水域近接距離**（`WATER_DIST`等）: 最近接の水域までの距離。先行研究S5（最近接の潮汐水域までの距離）・S6（`PW`。最終モデルには残っていない）・S8（`DFW`）で扱われる距離変数に相当。
- **水域面積率**（`WATER_COV`）: グリッド内の水域面積割合。

両指標は同じ水域データソース（水域ポリゴン/マスク）を元に、異なる算出方法（距離変換 vs 面積集計）を適用して得られるため、本資料では候補データの調査を1ファイルにまとめ、推奨方針のみ指標ごとに分けて記載する。

Hanoi ROI では JRC Global Surface Water を取得済みである（6章）。水域被覆率の現行の元データ（GLC_FCS30D 由来の `LULC_WATER_COV`）との一致度を7章に記録する。採否は [urban_structure_parameters.md](../urban_structure_parameters.md) を正本とし、本資料では扱わない。

---

## 2. 候補データ比較表

| 項目 | JRC Global Surface Water (GSW) | OSM 水域データ（`natural=water`/`waterway`） | HydroLAKES / HydroRIVERS | ESA WorldCover 水域クラス | OSM Water Layer（東大版ラスタ） |
|---|---|---|---|---|---|
| データ形式 | ラスタ（複数の主題図レイヤ） | ベクタ（ポリゴン/ライン） | ベクタ（ポリゴン/ライン） | ラスタ（土地被覆の1クラス） | ラスタ（OSMから生成） |
| 空間解像度 | **約30m**（EPSG:4326。本研究の30mグリッドとは格子が異なる） | ベクタ（解像度の概念なし） | ベクタ（湖沼は10ha以上のみ収録） | 10m | 約90m（3 arc-sec） |
| データ時期 | GEE の v1.4 は1984〜2021年（月次履歴は1984年3月〜2021年12月）。2022年以降は未収録（3.1節） | 継続的にコミュニティ編集 | 基準年は2016年前後（HydroLAKES v1.0時点） | 2020・2021年の2時点 | OSMの抽出時点（更新は不定期） |
| 恒常水域/季節水域の区別 | ✅ occurrence/seasonality/recurrenceレイヤで区別可能 | △ タグでは区別されない | △ 湖沼データのみ、季節変動は非対応 | ❌ 区別なし（Permanent water bodiesクラスのみ） | ❌ 区別なし |
| ベトナム/ハノイ カバレッジ | ✅ 全球データセット | ✅ Geofabrik Vietnam extractで取得可（道路と同じ経路） | △ 10ha未満の小規模な池・湖は収録対象外 | ✅ 全球データセット | ✅ 全球データセット |
| ライセンス | 無償公開（Copernicus Programme規則） | ODbL 1.0 | CC BY 4.0 | CC BY 4.0 | 要確認（OSM由来のため実質ODbL相当） |
| 取得方法（スクリプト可否） | ✅ GEE/Planetary Computer/JRCポータル直接DL | ✅ Geofabrik/Overpass API | ✅ HydroSHEDSポータル直接DL | ✅ GEE/AWS Open Data | ✅ 直接ダウンロード（東大サーバー） |

---

## 3. 候補データ詳細

### 3.1 JRC Global Surface Water (GSW)

- **提供機関**: European Commission Joint Research Centre (JRC)
- **データソース**: Landsat時系列を解析し、水域の出現頻度・季節性・変遷を定量化
- **版と収録期間（2026-10-31 に GEE で確認）**: GEE で使える最新版は **v1.4**（`JRC/GSW1_4/*`）で、`JRC/GSW1_5` は存在しない。年次の水域分類（`YearlyHistory`）は **1984〜2021年**（38枚）、月次の水域履歴（`MonthlyHistory`）は **1984年3月〜2021年12月**（454枚）。**主採用観測の年（2022年）は含まれない**ため、観測年に最も近い2021年を使う。JRC のデータポータルで2022年以降を含む後続版が配布されているかは**未確認**
- **主題図レイヤ**: Occurrence（出現頻度）、Recurrence（再現性）、Seasonality（季節性）、Transitions（変遷分類）、Maximum Water Extent（最大水域範囲）等
- **解像度**: 約30m（EPSG:4326・0.00026949度。GLC_FCS30D と同じ画素サイズ）。本研究の解析グリッド（投影座標系の30m正準グリッド）とは格子が一致しないため、セルへの集約が必要
- **利点**: 40年分のLandsatアーカイブに基づくため、恒常水域と季節水域（雨季の一時的な冠水域等）を区別できる。ベトナムのモンスーン気候下では、季節的に冠水する水田・低地と恒常的な湖沼を区別できる点が重要。
- **配布形式**: GEEカタログ（`JRC/GSW1_4/GlobalSurfaceWater`等）、Microsoft Planetary Computer、JRCデータポータル直接ダウンロード

### 3.2 OpenStreetMap 水域データ（`natural=water`, `waterway=*`）

- **データソース**: OSMコミュニティ編集
- **タグ体系**: `natural=water`（湖沼等の水域ポリゴン）、`waterway=river/canal/stream`（河川・水路のライン）
- **配布形式**: Geofabrik Vietnam extractから`ogr2ogr`で抽出（道路データ [gis_data_roads.md](gis_data_roads.md) と同じ取得経路）
- **利点**: Hoan Kiem湖やTay湖のような都市中心部の著名な湖沼が個別ポリゴンとして命名・記録されている可能性が高く、JRC GSW（30mラスタ）では捉えにくい小規模な池・水路も含まれうる。
- **懸念点**: `landuse`タグと同様、`water`関連タグの網羅性はコミュニティ編集に依存し、Hanoi ROIでの実際の入力率は未調査。

### 3.3 HydroLAKES / HydroRIVERS

- **提供機関**: HydroSHEDS（McGill大学等の研究グループ）
- **内容**: HydroLAKESは全球の湖沼・貯水池（約140万件）のポリゴン、HydroRIVERSは全球の河川ネットワーク（約850万リーチ、総延長約3,590万km）
- **懸念点**: HydroLAKESは**表面積10ha以上の水域のみを収録**しており、都市内の小規模な池・調整池は対象外になる可能性が高い。Hanoi中心部の小規模水域を捉えるには、OSMデータとの併用が必要。

### 3.4 ESA WorldCover 水域クラス

- [gis_data_lulc.md](gis_data_lulc.md) で調査済みの土地被覆データセットの「Permanent water bodies」クラスを流用する案。解像度10mだが、恒常水域と季節水域を区別しない。

### 3.5 OSM Water Layer（東京大学版ラスタ）

- **提供機関**: 東京大学（山田研究室）
- **内容**: OSMの`planet.pbf`から抽出した水域ポリゴンを約90m（3 arc-sec）グリッドのラスタ化したデータセット
- **位置づけ**: OSMベクタデータをすでにラスタ化した簡易版。本研究では独自に`ogr2ogr`でOSM抽出済みのため、追加採用の必要性は低い。

---

## 4. 推奨方針: 水域近接距離（`WATER_DIST`）

- **主候補**: `JRC Global Surface Water`。約30mの解像度で、40年分のLandsat時系列から恒常水域と季節水域を区別できる点が、モンスーン気候のハノイでは特に重要。ただし本研究の30mグリッドとは格子が一致しないため、セルへの集約が要る（3.1節）
- **補完候補**: `OSM 水域データ`。JRC GSW（30mラスタ）では捉えにくい都市中心部の小規模な池・水路までの距離を補完する。距離算出はラスタよりベクタの方が正確なため、小規模水域の近接距離はOSMベクタの方が適する場合がある。
- **参考データ**: `HydroLAKES`は10ha以上の水域のみのため、大規模湖沼（Tay湖等）までの距離の検証用に位置づける。

## 5. 推奨方針: 水域面積率（`WATER_COV`）

- **主候補**（調査時点の評価）: `JRC Global Surface Water`。恒常水域と季節水域を区別して面積率を出せる。ただし本研究の30mグリッドとは格子が一致しないため、セルへの集約が要る。なお、取得後の比較（7章）で決めた方針は、P7 のクラス列 `LULC_WATER_COV` の元データについてのもの（GLC_FCS30D を継続し、JRC は感度分析に使う。7.7節）であり、本節の `WATER_COV`（P11）の採否は変えていない。P11 の見直しでは7章を判断材料にする
- **補完候補**: `OSM 水域データ`。JRC GSWが30mグリッドで捉えきれない小規模水域の面積を補完する場合に使う。ただし面積率算出でベクタとラスタを混在させると二重カウント等の不整合が生じうるため、採用する場合は算出ロジックを明確に設計する必要がある。
- **不採用**: `ESA WorldCover水域クラス`は恒常/季節の区別がなく、JRC GSWで代替可能なため優先度は低い。

---

## 6. Hanoi ROIでの取得結果（JRC Global Surface Water）

### 6.1 取得元と取得方法

- **スクリプト**: `src/preprocessing/fetch_jrc_gsw_hanoi.py`（`python -m src.preprocessing.fetch_jrc_gsw_hanoi`）
- **取得元**: GEE の `JRC/GSW1_4/*`（v1.4。3.1節）。ネイティブ格子（EPSG:4326・0.00026949度）のまま ROI の BBox で取得し、ROI ポリゴンでクリップした
- **取得レイヤ**（主採用観測 2022-09-06 を基準に選択）:

| バンド | 内容 | 選んだ期間 | 無効値（255）の意味 |
|---|---|---|---|
| `occurrence` | 水域出現頻度（%、0〜100） | 1984年3月〜2021年12月（全期間） | 全期間を通じて有効な観測が無い画素 |
| `yearly_water_class` | 年次の水域分類（1: 非水域、2: 季節水域、3: 恒常水域） | 2021年（2022年は収録外のため最も近い年） | その年に観測が無い画素 |
| `monthly_water` | 月次の水域履歴（1: 非水域、2: 水域） | 2021年9月（季節を合わせるため観測日と同じ暦月） | その月に観測が無い画素 |

- **値の扱いで注意した点**（GEE で実測して確認）:
  - Occurrence は「一度も水域にならなかった画素」がマスクされている。そのまま取得すると「非水域」と「観測なし」が区別できないため、マスクを 0 で埋め、`JRC/GSW1_4/Metadata` の `valid_obs` が 0 の画素だけを無効にした
  - **年次画像も、水域になったことのない画素がマスクされている**（中心部の 0.1 度四方で約74%）。マスクを無効扱いにすると年次の有効域が約26%まで狭まるため、マスクは非水域（1）として埋め、値 0（観測なし）だけを無効にした。この補完により、水域になったことがなく当年に観測も無い画素も有効な非水域として数えられ、6.2節の年次の有効画素率（99.1%）にはその分が含まれる
  - 資産ごとに格子の原点が異なる（Occurrence は北緯84度、年次は北緯78度）が、差は画素のちょうど整数倍で、画素の境界は一致する（取得時に検査している）
- **出力**: `data/gis/water/jrc_gsw/jrc_gsw_hanoi_y2021_m202109.tif`（uint8・3バンド・Git管理外）、サマリー `data/output/open_gis/jrc_gsw_hanoi_y2021_m202109_summary.json`（来歴つき）

### 6.2 カバレッジ

ROI 内の画素数は 4,015,081（GLC_FCS30D の 4,015,086 とほぼ同じ格子）。有効画素率の分母は ROI 内の画素数である。

| バンド | 有効画素率 | 備考 |
|---|---|---|
| Occurrence | 100% | 水域になったことのある画素 884,457（出現頻度 50% 以上は 157,426） |
| 年次 2021 | 99.1% | 無効 36,748 画素 |
| 月次 2021-09 | **92.6%** | 無効 297,352 画素。**縞状の欠測が全域に広がる**（Landsat 7 の走査線欠損と見られるが未確認）。都心部にも塊状の欠測がある |

---

## 7. 水域データの一致度（GLC・Esri・JRC・MNDWI、主採用観測 2022-09-06）

Limited シナリオの水域被覆率 `LULC_WATER_COV` は GLC_FCS30D の水域クラス（210）から算出している（[urban_structure_parameters.md](../urban_structure_parameters.md) §2.2）。GLC と Esri の比較（[gis_data_lulc.md](gis_data_lulc.md) 7章）で水域の IoU が 0.40 にとどまったため、水域判定専用の JRC GSW と観測日の MNDWI を加えて、同じグリッド上で一致度を比べた。

### 7.1 方法

- **スクリプト**: `src/analysis/compare_water_sources.py`（`python -m src.analysis.compare_water_sources`）
- **比較の土台**: 主採用観測のデータセット `dataset_limited_20220906_032358_hanoi_30m.gpkg` の **30m 正準グリッド**（解析CRS EPSG:5897）。`IN_ANALYSIS_AREA == 1` の **3,736,107 セル**を対象にした
- **集約**: 各ラスタをセル内の水域面積率へ集約する。`LULC_WATER_COV` と同じ関数（`aggregate_class_fractions_to_grid()`・`Resampling.average`）を使い、グリッドもデータセットと同じく ROI の BBox から作った。**検算として、GLC の再集約値はデータセットの `LULC_WATER_COV` と全セルで一致した**（最大絶対差 0、NaN の不一致 0）
- **セルの判定**: 有効画素率 0.5 以上のセルを有効とし、水域面積率 0.5 以上のセルを水域とする（この2つの閾値の感度は見ていない）
- **各データの水域の定義**:

| 識別子 | 水域の定義 |
|---|---|
| GLC | GLC_FCS30D 2022 のクラス 210 |
| Esri | Esri 10m LULC 2022 のクラス 1（Water） |
| JRC Occurrence | 出現頻度が閾値以上の画素。**主は 50%**、感度として 25・75・90% |
| JRC 年次（季節＋恒常／恒常のみ） | 2021年の waterClass が 2・3／3 のみ |
| JRC 月次 | 2021年9月の water が 2 |
| MNDWI | 観測日のセル MNDWI が閾値以上。**主は 0**（Xu, 2006 の標準閾値）、感度として −0.20〜+0.30（0.05刻み）と大津の閾値 |

- **指標**: IoU、各データ基準の一致率（A 基準＝A が水域としたセルのうち B も水域とした割合）、画素数比、Cohen's kappa、水域面積率どうしの相関。真値が無いため、**精度ではなく一致度**として扱う。比較は**両者とも有効なセル**に限るため、ペアごとに対象セル数が異なる
- **MNDWI は独立な参照ではない**。LST と同じ観測画像から算出しており、観測日の水域の目安として使う
- **出力**（来歴つき）: `data/output/open_gis/water_sources_agreement_hanoi_20220906_results.json`・`_pairwise.csv`・`_threshold_sensitivity.csv`・`_confusion.csv`。セル単位の水域マスク `data/gis/water/comparison/water_masks_hanoi_20220906.tif`（EPSG:5897・Git管理外。QGIS で背景地図と重ねて確認する用）。結果 JSON は分析結果の陳腐化チェックの対象である

### 7.2 各データの水域の量

面積は投影座標系（EPSG:5897）の 30m セル（900 m²）の個数から求めた。有効セルの範囲はデータごとに異なる（月次・MNDWI は欠測がある）ため、面積の大小には有効域の違いも含まれる。有効セル率の分母は分析対象のセルであり、6.2節の有効画素率（分母は ROI 内の画素）とは分母が異なる（JRC 月次は 92.5% と 92.6%）。

| データ | 有効セル率 | 水域セル数 | 水域面積（km²） | GLC との比 |
|---|---|---|---|---|
| GLC 2022 | 99.8% | 201,788 | 181.6 | 1.00 |
| Esri 2022 | 99.8% | 356,984 | 321.3 | 1.77 |
| JRC Occurrence 25% 以上 | 99.8% | 226,942 | 204.2 | 1.12 |
| JRC Occurrence 50% 以上 | 99.8% | 145,371 | 130.8 | 0.72 |
| JRC Occurrence 75% 以上 | 99.8% | 92,082 | 82.9 | 0.46 |
| JRC Occurrence 90% 以上 | 99.8% | 47,555 | 42.8 | 0.24 |
| JRC 年次 2021（季節＋恒常） | 99.1% | 420,103 | 378.1 | 2.08 |
| JRC 年次 2021（恒常のみ） | 99.1% | 100,573 | 90.5 | 0.50 |
| JRC 月次 2021-09 | 92.5% | 193,182 | 173.9 | 0.96 |
| MNDWI 0 以上 | 93.5% | 387,102 | 348.4 | 1.92 |

**水域の面積は、データと定義の選び方で GLC の 0.24〜2.08 倍の幅で変わる**。GLC は、狭い JRC Occurrence 50% 以上・恒常水域と、広い Esri・MNDWI・JRC 年次（季節＋恒常）の中間にある。

### 7.3 ペアごとの一致度

GLC と各データ（主な閾値）:

| GLC と比べた相手 | 対象セル | IoU | kappa | GLC 基準の一致率 | 相手基準の一致率 | 画素数比（相手/GLC） |
|---|---|---|---|---|---|---|
| JRC 月次 2021-09 | 3,454,652 | **0.536** | **0.680** | 0.712 | 0.683 | 1.04 |
| JRC Occurrence 50% 以上 | 3,727,543 | 0.490 | 0.641 | 0.565 | 0.786 | 0.72 |
| MNDWI 0 以上 | 3,489,453 | 0.431 | 0.572 | 0.916 | 0.449 | 2.04 |
| JRC 年次（恒常のみ） | 3,699,529 | 0.421 | 0.577 | 0.444 | 0.891 | 0.50 |
| Esri 2022 | 3,727,994 | 0.397 | 0.536 | 0.786 | 0.444 | 1.77 |
| JRC 年次（季節＋恒常） | 3,699,529 | 0.392 | 0.529 | 0.870 | 0.417 | 2.09 |

- GLC と Esri の IoU（0.397）は、GLC の格子で比べた既存の結果（[gis_data_lulc.md](gis_data_lulc.md) 7.3節の 0.3979）とほぼ同じである。比較の土台を正準グリッドへ変えても結論は変わらない
- **GLC は、比べたデータのうち JRC 月次（2021年9月。観測日と暦月がそろう）と最もよく一致する**（IoU 0.536・kappa 0.680・画素数比 1.04）。なお年の近さでは Esri 2022・MNDWI（2022-09-06）の方が GLC 2022 に近い
- **恒常的な水域は、どのデータでも水域とされる**。JRC 年次の恒常水域のうち、GLC は 89.1%、Esri は 98.5%、MNDWI は 98.2% を水域としている（各ペアの「恒常のみ」基準の一致率）
- JRC どうし（Occurrence 50% 以上と月次）の IoU も 0.575 にとどまる。**同じ Landsat 由来でも、「長期の出現頻度」と「観測月の水域」では範囲が大きく異なる**

水域面積率（連続値）どうしの比較（両者とも有効なセル）:

| ペア | Pearson r | 平均絶対差 | 平均差（後者 − 前者） |
|---|---|---|---|
| GLC – JRC 月次 | 0.748 | 0.034 | +0.003 |
| GLC – JRC Occurrence 50% 以上 | 0.705 | 0.032 | −0.016 |
| GLC – Esri | 0.623 | 0.065 | +0.041 |
| JRC Occurrence 50% 以上 – JRC 月次 | 0.768 | 0.027 | +0.018 |

### 7.4 閾値の感度

JRC Occurrence の閾値と IoU:

| 閾値 | 対 GLC | 対 Esri | 対 JRC 月次 | 対 MNDWI 0 以上 |
|---|---|---|---|---|
| 25% 以上 | **0.510** | **0.436** | **0.608** | **0.424** |
| 50% 以上（主） | 0.490 | 0.356 | 0.575 | 0.320 |
| 75% 以上 | 0.383 | 0.246 | 0.429 | 0.223 |
| 90% 以上 | 0.217 | 0.131 | 0.233 | 0.120 |

MNDWI の閾値と IoU（抜粋）:

| 閾値 | 対 GLC | 対 Esri | 対 JRC Occurrence 50% 以上 | 対 JRC 月次 |
|---|---|---|---|---|
| −0.20 | 0.306 | 0.429 | 0.221 | 0.331 |
| −0.10 | 0.375 | **0.453** | 0.272 | 0.404 |
| −0.05（大津の閾値 −0.050 と同等） | 0.405 | 0.452 | 0.296 | 0.437 |
| 0.00（主） | 0.431 | 0.446 | 0.320 | 0.469 |
| +0.10 | 0.475 | 0.426 | 0.372 | 0.530 |
| +0.15 | **0.488** | 0.410 | 0.398 | 0.555 |
| +0.20 | **0.488** | 0.387 | 0.418 | **0.569** |
| +0.30 | 0.446 | 0.322 | **0.433** | 0.550 |

- Occurrence は閾値を下げるほど他データとの一致が上がり、試した範囲では **25% が最良**である（50% では季節水域の多くが落ちる）。25% は試した範囲の下端のため、それより低い閾値でさらに一致が上がる可能性は確かめていない
- MNDWI 0 以上は水域を広く取りすぎる（GLC の 1.92 倍）。GLC・JRC 月次との一致は **+0.15〜+0.20** で最大になる。JRC Occurrence 50% 以上との一致は試した範囲の上端（+0.30）で最大であり、範囲の外にさらに一致の高い閾値がある可能性は確かめていない。大津の閾値（−0.050）は Esri との一致は良いが、GLC・JRC との一致は低い
- 閾値を調整しても、GLC との IoU は最大で 0.510（Occurrence 25% 以上）・0.488（MNDWI +0.15〜+0.20）にとどまる。**閾値の調整だけでは食い違いは解消しない**

### 7.5 食い違いの内訳

食い違うセル（片方だけが水域）を、GLC・Esri の優占クラス（セル内で面積率が最大の共通クラス）別に数えた（`_confusion.csv`）。水域と判定した側の当事者を参照にする組み合わせは、ほぼ全件が水域になり情報が無いため数えない（非水域と判定した側の当事者が何と分類したかは数える）。

| 食い違い | 参照データの優占クラス（上位） |
|---|---|
| Esri のみ水域（GLC は非水域） | GLC の **農地 150,130**・湿地 36,112・樹林 7,840 |
| MNDWI 0 以上のみ水域（GLC は非水域） | GLC の **農地 167,982**・湿地 42,157 |
| GLC のみ水域（JRC Occurrence 50% 以上は非水域） | Esri の水域 47,591・**農地 36,512** |
| JRC 月次のみ水域（GLC は非水域） | GLC の農地 30,450・**湿地 29,419** |

- **食い違いの主因は季節的な水域である**。GLC の水域セルの 43%（87,560 セル）は JRC Occurrence 50% 以上では水域にならず、Esri・MNDWI は GLC が農地としたセルの一部を水域とする。水田・養殖池の冠水状態の扱いの差と考えられる（地物は未確認）
- **GLC が「湿地」としたセルの多数を、他データは水域とする**（JRC 月次 29,419・Esri 36,112・MNDWI 42,157 セル）。`LULC_WATER_COV` と `LULC_WETLAND_COV` の境界も、データによって揺れる

### 7.6 食い違う場所

- 図（`src/visualization/water_source_disagreement_map.py` で生成。Git 追跡）:
  - `images/gis_data/water/water_sources_disagreement_hanoi_20220906_overview.png`: GLC・Esri・JRC Occurrence 50% 以上・MNDWI 0 以上のうち、何種類が水域としたか（全域）。JRC 月次は縞状の欠測が全域に広がるため除いた
  - `images/gis_data/water/water_sources_disagreement_hanoi_20220906_zoom.png`: 3地点（各 6km 四方）で、GLC と各データの食い違いを5区分で示した
- 地点ごとの所見:
  - **都心の湖沼（ホアンキエム湖周辺）**: どのデータも湖沼をよく捉える。JRC Occurrence では湖の縁が「GLC のみ水域」になり、範囲がやや狭い
  - **紅河の河道と砂州（タイ湖の北東）**: 河道中央の砂州は、Esri・JRC・MNDWI が水域、GLC が非水域とする。河岸沿いの細い帯は GLC だけが水域とする
  - **南部郊外（食い違いの集中区画、東経 105.827 度・北緯 20.716 度）**: 「Esri のみ」「MNDWI のみ」「GLC のみ」の水域セルを 4.5km 区画ごとに数えた試算（一時的な集計で、出力には残していない）で、いずれも最も集中した区画の中心を選んだ（図の窓は 6km 四方）。GLC が水域としたセルの多くを JRC Occurrence は水域としない一方、Esri・MNDWI は GLC より広く水域とする。区画状の形から水田・養殖池と考えられるが、**背景地図での確認は未実施**である（OpenStreetMap はこの一帯の地物がほとんど描かれていない）

### 7.7 本研究への含意と水域マスクの元データの方針

- **`LULC_WATER_COV` の値はデータの選択に敏感である**。水域の面積はデータと定義で GLC の 0.24〜2.08 倍変わり、差の主因は季節的な水域（水田・養殖池・砂州）の扱いである。主採用観測（9月・雨季）では冠水した農地が多く、観測日に近い判定ほど水域が広がる
- GLC は複数データの中間に位置し、比べたデータのうち JRC 月次（観測日と暦月がそろう）と最もよく一致する。GLC を誤りとする根拠は得られなかった
- **方針（研究者判断、2026-11-01）**: **P7 のクラス列 `LULC_WATER_COV` の元データは GLC_FCS30D を継続**し、**水域率を JRC（月次または Occurrence）で差し替えた感度分析を後続タスクで追加**する。差し替え後の Limited・共通評価の再実行は本比較の対象外とした
- 後続の P11・P12 の採否の見直し（[urban_structure_parameters.md](../urban_structure_parameters.md) §1.5）では、本章の一致度と、GLC の「湿地」との境界の揺れを判断材料にする

---

## 8. 注意点

- 「最近接水域までの距離」を算出するには、水域ポリゴン/マスクに対する距離変換（distance transform）処理が必要。JRC GSWの場合はどの主題図レイヤ（Occurrence何%以上を「水域」とみなすか等の閾値）を採用するかで距離・面積の算出結果が変わるため、閾値の根拠を明記する必要がある。
- ハノイは雨季に水田・低地が季節的に冠水するため、恒常水域のみで算出するか、季節水域も含めるかで結果が大きく変わりうる。RQ1-RQ3のどの分析に使うかに応じて使い分けを検討する。
- 近接距離と面積率で同一データソース（JRC GSW）を使う場合、取得スクリプトは共通化できる（同じ水域マスクから距離変換と面積集計をそれぞれ実行する）。
- `JRC Global Surface Water` は取得済み（6章）。`OSM水域データ`・`HydroLAKES` 等は未取得で、必要になった時点で取得を検討する。
- JRC GSW の月次・年次は2021年までしか無く、主採用観測（2022年）とは1年ずれる。観測日の水域の目安として使う場合は、この時間差と月次の縞状の欠測（6.2節）を考慮する。

---

## 9. 参考ソース

- JRC Global Surface Water: <https://global-surface-water.appspot.com/>
- Pekel, J.-F., Cottam, A., Gorelick, N., Belward, A. S. (2016). High-resolution mapping of global surface water and its long-term changes. *Nature*, 540, 418–422.
- Xu, H. (2006). Modification of normalised difference water index (NDWI) to enhance open water features in remotely sensed imagery. *International Journal of Remote Sensing*, 27(14), 3025–3033.
- JRC GSW GEEカタログ: <https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater>
- JRC GSW（Planetary Computer）: <https://planetarycomputer.microsoft.com/dataset/jrc-gsw>
- OpenStreetMap Wiki, Tag:natural=water: <https://wiki.openstreetmap.org/wiki/Tag:natural=water>
- OpenStreetMap Wiki, Key:waterway: <https://wiki.openstreetmap.org/wiki/Key:waterway>
- HydroSHEDS（HydroLAKES/HydroRIVERS）: <https://www.hydrosheds.org/>
- OSM Water Layer（東京大学）: <https://hydro.iis.u-tokyo.ac.jp/~yamadai/OSM_water/>
