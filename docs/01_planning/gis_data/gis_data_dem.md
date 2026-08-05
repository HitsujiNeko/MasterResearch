# 標高データ（DEM）候補の調査・選定ガイド

**最終更新**: 2026-08-05  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、分析シナリオ（Satellite Only / Limited / Full）の定義

---

## 1. 目的

本資料は、研究の各シナリオで利用するDEMを選定するために、オープンソースDEMの特性を調査・比較した結果をまとめる。

特に以下の2点を目的とする。

1. 候補DEMのセンサー特性・DSM/DTM分類・熱帯都市域での精度特性を整理する。
2. 測量由来DEM（BSHorizon）との比較結果をもとに、Limitedシナリオで採用するDEMを選定する根拠を示す。

---

## 2. シナリオ別DEMの位置づけ

| シナリオ | 使用DEM | 出典 | 備考 |
|---|---|---|---|
| **Full** | 測量由来DEM（BSHorizon） | `data/gis/dem/bshorizon/DEM_10m_m05_a100_M200.tif` | 10m解像度、EPSG:5897、有効カバレッジはROIより小さい |
| **Limited** | **FABDEM v1.2**（本資料で選定・採用確定） | GEE経由で取得済み | ハノイROI全域をカバー。`ELEV_MEAN_<scale>` として実装済み |
| **Satellite Only** | DEMなし（衛星指標のみ） | — | — |

---

## 3. DEMのDSM/DTM特性

### 3.1 用語の定義

- **DSM（Digital Surface Model）**: 地表面の物体（建物・植生）を含む高さを表す。センサーが最初に捉えた反射面（ファーストリターン）を測定する。
- **DTM（Digital Terrain Model）**: 建物・植生を除去した純粋な地形面を表す。本来の地形高度が必要な場合に適する。

### 3.2 センサー種別とDSM/DTM分類

| データセット | DSM/DTM | センサー | 波長帯 | 植生透過性 | 垂直基準面 |
|---|---|---|---|---|---|
| Copernicus DEM GLO-30 | DSM | TanDEM-X（X帯SAR） | 3.1cm | 低い（キャノピー上面で散乱） | EGM2008 |
| NASADEM | DSM | SRTM再処理（C帯SAR） | 5.6cm | 中程度（X帯より透過性高い） | EGM96 |
| SRTMGL1 v003 | DSM | SRTM原版（C帯SAR） | 5.6cm | 中程度（NASADEMと同センサー） | EGM96 |
| TanDEM-X（DLR） | DSM | X帯SAR | 3.1cm | 低い（GLO-30と同一ミッション） | EGM2008 |
| ASTER GDEM v3 | DSM | 光学ステレオ（VNIR） | 可視/NIR | なし（雲・植生の影響を直接受ける） | EGM96 |
| FABDEM v1.2 | 準DTM | Copernicus派生（ML補正） | — | 機械学習で建物・森林バイアスを除去 | EGM2008（継承） |

---

## 4. 候補データの特性比較

### 4.1 主要候補（GEE取得済み）

#### Copernicus DEM GLO-30

- **運用機関**: DLR（ドイツ航空宇宙センター）＋Airbus Defence and Space。ESA/Copernicus経由で配布。
- **原データ**: TanDEM-X衛星（X帯SAR干渉計）。2010年12月〜2015年1月に観測。
  - GEEカタログに「The WorldDEM product is based on the radar satellite data acquired during the TanDEM-X Mission」と明記されている。
- **空間解像度**: 約30m（1 arc-second）
- **垂直基準面**: EGM2008（注：0mは平均海面と一致しない）
- **GEE Asset ID**: `COPERNICUS/DEM/GLO30`
- **処理パイプライン**:
  1. TanDEM-XのSAR干渉計データからWorldDEM™を生成。
  2. 水域（海岸・湖・河川）の平坦化処理。
  3. 海岸線・空港・不自然な地形構造のマニュアル編集。
  4. コヒーレンスに基づく高さ誤差推定（HEMバンド）。
  - ボイド補完に他データソースは使用していない（TanDEM-Xのみ）。
- **利用可能なバンド（GEE）**:
  - `DEM`: 標高値（主バンド）
  - `EDM`: Edit Data Mask（編集操作の記録）
  - `FLM`: Filling Mask（地形編集プロセスの記録）
  - `HEM`: Height Error Mask（標高値の標準偏差。0.09〜43.4mの範囲）
  - `WBM`: Water Body Mask（海洋・湖・河川の分類）
- **精度**:
  - HEMバンドとして誤差の空間分布が提供される（点推定値としての全体RMSEは非公表）。
- **熱帯都市域の特性**:
  - X帯SARは波長が短く植生透過性が低いため、密林・都市緑地ではキャノピー上面の高さを捉える傾向がある。
  - 熱帯都市の植生領域では系統的な正バイアス（実地形より過大な値）が生じやすい。
  - 建物はDSMに残存しており、地形面として利用する際には建物高さが混入する。
- **カバレッジ**: 全球
- **BSHorizonとの比較**: RMSE=6.99m, MAE=5.67m, 平均差=-5.48m（公開DEM > BSHorizon）
- **参考**: [GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30), [Product Handbook](https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf)

---

#### NASADEM

- **運用機関**: NASA / USGS / JPL-Caltech。NASA EOSDIS Land Processes DAAC（LP DAAC）が配布。
- **原データ**: SRTM（スペースシャトルのC帯SARレーダー）。2000年2月11〜22日の11日間のみ観測。
- **空間解像度**: 約30m（1 arc-second）
- **垂直基準面**: EGM96（ジオイド）
- **GEE Asset ID**: `NASA/NASADEM_HGT_001`
- **処理パイプライン**:
  1. SRTM原データの干渉計処理を**再処理**（位相アンラッピングの改善）。
  2. ICESat GLAS（レーザー高度計）データを地上制御点として使用し、垂直精度を向上。
  3. 残存ボイド（欠損域）を ASTER GDEM v2・ALOS PRISM（AW3D30）で補完。
  4. SRTM Water Body Dataset による水域マスクを更新。
  - NASADEMの主データはあくまでSRTM（C帯SAR）であり、ASTER GDEMはボイド補完の補助的役割。
- **利用可能なバンド（GEE）**:
  - `elevation`: 標高値（EGM96基準、ボイドなし）
  - `num`: データソースインデックス（各ピクセルがどの補助データ由来かを示す）
  - `swb`: 更新済みSRTM水域マスク（陸地/水域の区分）
- **精度**:
  - 全体のRMSEは公式ページでは非公表。SRTMの再処理改善によりNASADEMの方がSRTMGL1より精度が良い傾向。
- **熱帯都市域の特性**:
  - C帯SAR（波長5.6cm）はX帯より植生透過性が高く、熱帯域での精度はCopernicus GLO-30より良い傾向。
  - ただし、ICESat GLAS補正やASTER補完はボイド周辺域に限定的な影響を与え、全域一様ではない。
  - 取得時期は2000年であり、その後の都市開発・土地被覆変化は反映されない。
- **カバレッジ**: 南緯56°〜北緯60°（極域を除く）
- **BSHorizonとの比較**: RMSE=4.85m, MAE=3.85m, 平均差=-3.04m（**3候補中で最も誤差が小さい**）
- **参考**: [GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001), [NASA Earthdata](https://www.earthdata.nasa.gov/data/catalog/lpcloud-nasadem-hgt-001)

---

#### SRTMGL1 v003

- **運用機関**: NASA JPL / USGS。
- **原データ**: SRTM（C帯SAR）。NASADEMと全く同じ観測データ（2000年2月）が原点だが、後処理の度合いが異なる。
- **空間解像度**: 約30m（1 arc-second）
- **垂直基準面**: EGM96
- **GEE Asset ID**: `USGS/SRTMGL1_003`
- **処理パイプライン**:
  1. SRTM v3（SRTM Plus）としてボイドを補完した製品。
  2. ボイド補完ソース: ASTER GDEM2、GMTED2010、NED（米国標高データ）。
  3. NASADEMのような位相アンラッピング再処理や ICESat 補正は行っていない。
- **利用可能なバンド（GEE）**:
  - `elevation`: 標高値（単一バンドのみ）
- **精度**:
  - RMSEは公式ページでは非公表。NASADEMより前処理が少ないため、熱帯域ではNASADEM未満の精度となることが多い。
- **熱帯都市域の特性**:
  - NASADEMと同一のC帯SARを原データとするため、植生透過性の特性は同等。
  - ただし再処理・補正が少なく、ボイド補完の品質がNASADEMより劣る可能性がある。
  - 研究コミュニティでは、NASADEMの比較ベースラインとして使われることが多い。
- **カバレッジ**: 南緯56°〜北緯60°（極域を除く）
- **BSHorizonとの比較**: RMSE=6.24m, MAE=5.22m, 平均差=-4.95m
- **参考**: [GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003)

---

### 4.2 追加検討候補

#### TanDEM-X（DLR提供の独立製品）

- **概要**: DLRとAirbus Defence and Spaceが共同運用するX帯SAR衛星ミッション。Copernicus DEM GLO-30の原衛星データと同一ミッション。
- **GEE利用可否**: GEEには独立した30m/90m製品としては公開されていない（DLRへの個別申請が必要）。
- **判断**: Copernicus GLO-30が同一のTanDEM-X観測データを原データとして作成されており、実質的に同等プロダクトを提供している。追加取得の必要なし。
  - GEEカタログ上の明示的な記載: 「The WorldDEM product is based on the radar satellite data acquired during the TanDEM-X Mission」

---

#### ASTER GDEM v3

- **運用機関**: NASA / METI（日本経済産業省）。
- **センサー**: ASTER（Terra衛星搭載）のVNIRバンドによる光学ステレオ。複数シーン（2000〜2013年取得）をモザイク。
- **GEE Asset ID**: `projects/sat-io/open-datasets/ASTER/GDEM`（コミュニティカタログ）
- **特徴**:
  - 光学センサーのため、SARと異なり電波を使わない。雲を透過できず、雲が多い地域では雲汚染アーティファクトが混入する。
  - ベトナムはモンスーン気候で年間を通じて雲量が多く、雲汚染による異常値が深刻。
  - 熱帯・モンスーン地域では信頼性が最も低い候補であり、精度はSARベースDEMに劣る。
  - なお、NASADEMおよびSRTMGL1 v003のボイド補完に **ASTER GDEM v2** が補助利用されている（主データではなく欠損域の補完用途）。
- **判断**: ベトナムの気候条件に不適。本研究での単独採用は推奨しない。

---

#### FABDEM v1.2

- **開発機関**: ブリストル大学（Laurence Hawkerら）。
- **元データ**: Copernicus DEM GLO-30（TanDEM-X由来）をベースに、ランダムフォレスト回帰で建物・森林バイアスを除去した準DTM。
- **GEE Asset ID**: `projects/sat-io/open-datasets/FABDEM`（[GEEコミュニティカタログ](https://gee-community-catalog.org/projects/fabdem/)）
  - 既存の `src/gee/download_open_dem.py` で `--dataset fabdem` を指定するだけで取得可能。
- **ライセンス**: CC BY-NC-SA 4.0（**非商用のみ**。修士論文・学術研究は非商用に該当するため利用可能）
- **論文・資料への必須帰属文**（使用時は必ずこの文言を記載すること）:
  > "FABDEM is produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved."
- **継承（SA）条件**: FABDEMを加工して派生データセットを外部公開する場合は同一ライセンス（CC BY-NC-SA）での配布が必要。研究内での利用・論文中の図表への使用は問題なし。
- **空間解像度**: 約30m（1 arc-second）
- **カバレッジ**: 南緯60°〜北緯80°
- **処理パイプライン**:
  1. 12カ国のLiDARデータを地上真値として訓練データを構築。
  2. 森林除去用・建物除去用のランダムフォレストモデルをそれぞれ学習。
  3. 補正後の標高値にピット補填・平滑化フィルタを適用。
- **精度**（公表値、Hawker et al. 2022）:
  - 都市域: MAE 1.12m（補正前1.61m）、RMSE 2.33m
  - 森林域（52°N以南）: MAE 2.88m（補正前5.15m）、RMSE 4.96m
  - フラッドプレーンの誤差の約80%が2m以下
- **熱帯都市域の特性**:
  - 建物・植生バイアスを統計的に除去しており、候補の中で最も地形面に近い値を提供する。
  - ただし、沿岸部・急峻地形では建物アーティファクトが残存する場合がある。
  - 熱帯の高密度キャノピー（カバー率50%超）では補正精度が低下する可能性がある。
- **取得方法**: GEE経由で取得可能。`download_open_dem.py --dataset fabdem` で他のDEMと同じ手順で取得できる（タイルの手動選択不要）。Bristol大学リポジトリ（<https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn>）からの直接ダウンロードも可能だが、GEE経由の方が簡便。
- **判断**: 技術的に最も望ましい準DTM候補。取得・BSHorizonとの比較を実施のうえ（5章）、**Limitedシナリオの採用DEMとして確定**した（7章）。

---

## 5. BSHorizon DEM との比較結果

比較実施日: 2026-05-27  
比較スクリプト: `src/analysis/compare_dem_rasters.py`  
比較出力: `data/output/dem_comparison/`

### 5.1 BSHorizon DEM の基本情報

| 項目 | 値 |
|---|---|
| ファイルパス | `data/gis/dem/bshorizon/DEM_10m_m05_a100_M200.tif` |
| CRS | EPSG:5897（VN-2000 / TM-3 zone 482） |
| 解像度 | 10m × 10m |
| 範囲 | X: 581495–589505、Y: 2321995–2333005（単位: m） |
| nodata | -9999.0 |
| 有効ピクセル数 | 881,901 |
| 平均標高 | 6.95m |
| 標準偏差 | 1.98m |

### 5.2 比較結果一覧

差分定義: `BSHorizon - 公開DEM`（負値 = 公開DEMの方が高い）

| DEM | 重複ピクセル数 | 平均差 (m) | 中央値差 (m) | MAE (m) | RMSE (m) | 標準偏差差 (m) | 相関係数 | 5%ile差 | 95%ile差 |
|---|---|---|---|---|---|---|---|---|---|
| **FABDEM v1.2** | 881,901 | -3.00 | -2.71 | **3.20** | **3.88** | **2.46** | **0.603** | -7.08 | 0.40 |
| NASADEM | 881,901 | -3.04 | -3.00 | 3.85 | 4.85 | 3.78 | 0.463 | -9.11 | 2.73 |
| SRTMGL1 v003 | 881,901 | -4.95 | -4.91 | 5.22 | 6.24 | 3.80 | 0.448 | -10.99 | 0.83 |
| Copernicus GLO-30 | 881,901 | -5.48 | -4.88 | 5.67 | 6.99 | 4.34 | 0.477 | -12.68 | 0.16 |

### 5.3 解釈上の注意点

- FABDEMは相関係数0.603と他3候補（0.45〜0.48）を大きく上回り、標準偏差差も2.46mと最小。建物・森林バイアスの除去が地形一致性の向上に寄与していると考えられる。
- 相関係数がNASADEM等で0.45〜0.48程度にとどまるのは、BSHorizonの有効範囲（約8km×11km）が局所的で、30m解像度の公開DEMとは地形表現スケールが大きく異なることが一因と考えられる。
- BSHorizon DEM は河川部分を含むため、水面付近の低標高セルが比較に混入している。公開DEMの水域処理（平坦化など）の扱いが差分に影響している可能性がある。
- 平均差が負（公開DEM > BSHorizon）であることは、公開DEMが建物・植生バイアスを持つDSMであることと整合する。FABDEMは平均差が-3.00mとNASADEM（-3.04m）と近く、バイアス除去後も系統的なオフセットが残るが、散らばり（標準偏差差）は大きく改善している。

---

## 6. 選定の考え方

### 6.1 精度観点

4候補の中では **FABDEM** が最もRMSE・MAE・相関係数すべてにおいて優れており、建物・森林バイアス除去の効果が精度向上に明確に寄与している。NASADEMは純粋な公開DEMとしては最良だが、FABDEMには及ばない。

### 6.2 DSMバイアスへの対処

全候補がDSMであり、建物・植生の高さが含まれる。Limitedシナリオでの利用に際しては以下の点を明示する必要がある。

- 記述・論文中に「利用するDEMはDSMであり、地形面高さではなく建物・植生を含む表面高さを反映する」と注記する。
- Fullシナリオの測量由来DEMとの比較時は、この特性差（地形 vs 表面）を考察に組み込む。

### 6.3 FABDEMの扱い

修士論文・学術研究は非商用に該当するため、CC BY-NC-SA 4.0ライセンスのもとで利用可能。BSHorizonとの比較でRMSE=3.88m・相関係数0.603と全候補中で最良の精度を示した。地形高度としての概念的適切さと精度の両面で最も優れた候補と判断できる。

使用する場合は4.2節に記載の帰属文を論文・資料に必ず記載すること。

---

## 7. 選定結果

### 7.1 Limitedシナリオ採用DEM（確定）

| 採用 | データセット | 根拠 |
|---|---|---|
| ✅ **採用確定** | **FABDEM v1.2** | 4候補中でRMSE=3.88m・MAE=3.20m・相関係数0.603と全指標で最良。建物・森林バイアス除去により地形面に最も近い |
| 参考保存 | NASADEM | DSMとして精度2位。FABDEM比較の基準として保持 |
| 参考保存 | Copernicus GLO-30 | DSM（X帯SAR）。比較参照用 |
| 参考保存 | SRTMGL1 v003 | DSM（C帯SAR）。比較参照用 |
| ❌ 不採用 | ASTER GDEM v3 | ベトナムのモンスーン気候で雲汚染が深刻、信頼性不足 |
| ❌ 不採用（重複） | TanDEM-X（DLR独立版） | Copernicus GLO-30と同一の原データ、追加取得不要 |

> 研究者の判断により FABDEM v1.2 を採用確定した（CC BY-NC-SA 4.0・非商用・帰属文必須を了承のうえ）。  
> Limitedシナリオの `ELEV_MEAN_<scale>` として実装済みである。算出仕様は [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md) 6.4節を正本とする。

### 7.2 採用ファイルパス

```text
data/gis/dem/fabdem/fabdem_hanoi_dem.tif                    # Limitedシナリオ採用（確定）
data/gis/dem/nasadem/nasadem_hanoi_dem.tif                  # 参考保存（比較用）
data/gis/dem/copernicus_glo30/copernicus_glo30_hanoi_dem_clipped.tif  # 参考保存（比較用）
data/gis/dem/srtmgl1/srtmgl1_hanoi_dem.tif                  # 参考保存（比較用）
```

---

## 8. 今後の課題

1. **水域マスクを使った非水域のみの比較**: BSHorizonに含まれる河川セルを除外した比較を行い、水域以外での精度を再評価する。
2. **論文中の注記**: 採用したFABDEMが準DTM（DSMを機械学習で補正したもの）であり、高密度キャノピー・急峻地形では補正残差が残ることを明示する。あわせて垂直基準面がEGM2008であり0mが平均海面と一致しないことを記述する。
3. **`full` シナリオの標高**: 測量GISの `merge_DH.gpkg` による標高、またはFABDEMの暫定適用のいずれを採るかを判断する（現状 `full` では標高を出力しない）。

> **実施済み**: 「FABDEMの取得と比較」は完了した。取得（GEE経由）・BSHorizonとの比較（5章）・採用確定（7章）・`ELEV_MEAN_<scale>` としての実装まで完了している。

---

## 9. 参考リソース

- [Copernicus DEM GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30)
- [NASADEM GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001)
- [SRTMGL1 v003 GEEカタログ](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003)
- [ASTER GDEM v3 コミュニティカタログ](https://gee-community-catalog.org/projects/aster/)
- [FABDEM コミュニティカタログ](https://gee-community-catalog.org/projects/fabdem/)
- [Copernicus DEM Product Handbook](https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model)
- `src/gee/download_open_dem.py`: DEM取得スクリプト
- `src/analysis/compare_dem_rasters.py`: 比較スクリプト
- `.github/prompts/completed/20260602_Import_DEM.prompt.md`: タスクプロンプト（完了記録含む）
