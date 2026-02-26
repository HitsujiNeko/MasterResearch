# S6: Garzón et al. (2021)

## 📌 基本情報

* **論文ID**: S6
* **著者**: Julián Garzón; Iñigo Molina; Jesús Velasco; Andrés Calabia
* **年**: 2021（Published: 22 Oct 2021）
* **タイトル**: *A Remote Sensing Approach for Surface Urban Heat Island Modeling in a Tropical Colombian City Using Regression Analysis and Machine Learning Algorithms*
* **掲載誌**: *Remote Sensing*, 13, 4256
* **DOI/URL**: [https://doi.org/10.3390/rs13214256](https://doi.org/10.3390/rs13214256)
* **PDFファイル**: `S6.pdf`（有）

---

## 🎯 研究目的

Cartago（コロンビア）の2001–2020年を対象に、Landsat/Sentinel-2由来のLSTからSUHIの時空間パターンをモデル化し、**寄与要因の重み付け（MLR係数由来）**と**重み付きNaïve Bayes（NBML）**で高温リスク域を抽出する。

---

## 🌍 研究対象

* **対象地域**: Cartago（Valle del Cauca, Colombia）
* **対象期間**: 2001–2020
* **空間スケール**: 都市スケール（市域面積 279 km²）

---

## 📊 使用データ

### 主要データ

* **衛星データ**: Landsat 5 TM / Landsat 7 ETM+ / Landsat 8 OLI-TIRS
* **シーン数**: 計37シーン（L5:2、L7:20、L8:15）
* **解像度**: VIS/NIR 30 m、TIRはセンサーにより120/60/100 m（処理はLandsatピクセルで運用）

### 補助データ

* **Sentinel-2 MSI (Level-2A)**: 11画像を用いて **Fcover（Fractional Vegetation Cover）** を取得
* **ベース地図/地形**: ESRI World Countries、コロンビアの地理院系Geoportal等（地図・地形モデル）
* **現地観測**: DS18B20温度センサ30台（LST検証、2019/1/22・2019/9/9）

---

## 🔬 手法

### 主要手法

* **LST取得**: 大気放射（上向き/下向き放射・透過率）と放射率補正を含む単一チャネル系の枠組みで算出
* **統計モデル**: PCA（時系列の主要変動抽出）＋MLR（要因の寄与・重み推定）
* **機械学習（分類）**: SVM と **重み付きNaïve Bayes（NBML）**で温度カテゴリ（SUHI強度）を分類

### 詳細

#### データ前処理（校正・大気補正）

* DN→放射輝度（USGSモデル）→大気補正は **ENVI FLAASH（MODTRAN）** を適用
* 水蒸気は標準大気モデル、AODはKaufmanの暗い植生反射アルゴリズムを採用

#### LSTと放射率（emissivity）モデルの比較

* 放射伝達の枠組み（LTOA式）を示し、放射率がLST推定に重要であることを明示
* 放射率は3方式を比較：
  1. 文献・LULC別のLSE参照値（Table 1）
  2. ASTER-GEDv3
  3. Sentinel-2由来Fcoverを用いた放射率（式(2)）
* L8はTIRS **Band10のみ**使用（Band11は不確実性が大きい）

#### 現地検証

* Landsat全期間の検証は困難で、L8の2オーバーパス（2019/1/22, 2019/9/9）のみ現地LSTで検証
* 30台のDS18B20、校正で標準偏差±0.5°C

#### SUHIモデル化フロー

1. Landsat時系列から LST と各要因（指標等）を作成
2. PCAで各変数の時系列トレンド（主要成分）を抽出
3. MLRで LSTtrend を説明し、標準化係数から要因重みを算出
4. 重みをNBMLに投入して温度カテゴリ（SUHI強度）を分類

---

## 🏙️ 都市構造の定義・パラメータ

### 使用した都市構造パラメータ（= 主に"衛星由来の代理指標"）

* **NDBI**（不透水・市街化の代理）
* **NDVI**（植生量の代理）
* **NDWI**（水分・水域/湿潤の代理、冷却要因として位置づけ）
* **PW / PUC**（距離変数）：水域への近接（PW）、都市中心への近接（PUC）。距離はEuclidean distanceで算出

> **注記**: 建物密度・道路密度・建物高さ等の"物理的都市形態"ではなく、**スペクトル指標＋距離**が中心（限定的な都市構造指標）。

---

## 📈 主な結果

### 定量的結果（LST推定の比較）

* 放射率モデルの性能（地上LSTとの回帰）：
  - **Fcoverモデル**: R² = 0.78、SD = 0.73°C（最良）
  - **ASTER-GEDv3**: R² = 0.27
  - **LSE（LULC別固定）**: R² = 0.26
* 9月2019の平均誤差：Fcover 1.14°C、ASTER-GEDv3 3.67°C、LSE 3.85°C

### 定量的結果（MLR：支配要因と係数）

* 変数選択の経緯：NDVIとGreennessが高冗長（R²=0.99）でGreenness除外、Brightnessは空間相関が低く除外、PWは有意でなく除外
* 最終MLR（トレンド同士の回帰）：
  - **LSTtrend = 0.29 + 0.48·NDBItrend + 0.21·NDVItrend − 0.61·NDWItrend − 0.51·PUC**
  - 係数の有意性：全て **p < 0.001**
  - モデル **R² = 0.82**

### 変数重要度（重み：標準化係数→寄与率）

**寄与率（標準化係数から算出）**：
1. **NDWI: 51.46%**（最大）
2. **NDBI: 21.38%**
3. **PUC: 14.32%**（都市中心距離）
4. **NDVI: 12.84%**

> **重要**: 熱帯都市Cartagoでは **NDWI（水分・湿潤指標）が最大寄与**。市街化（NDBI）も重要だが、NDWI > NDVIという関係。

### 機械学習（分類）性能

* **NBML（重み付きNaïve Bayes）**: Kappa 0.94、Overall Accuracy **0.95**
* **SVM**: Kappa 0.88、Overall Accuracy 0.88

> **重要**: MLRで得た重みをNBMLに組み込むことで、SVMより高精度にSUHI強度域を分類可能。

---

## 💡 主な結論

1. **放射率の選び方がLST精度を大きく左右**し、Sentinel-2由来Fcover放射率が最も良好（**R²=0.78**）。
2. LST/SUHIの主要因は **NDWI（湿潤）とNDBI（市街化）**で、寄与率はNDWIが最大（**51.46%**）。
3. MLRで得た重みをNBMLに組み込むことで、SVMより高精度にSUHI強度域を分類（**Accuracy 95%**）。

---

## 🔍 本研究との関連性

### RQ1（支配的説明変数は何か？）

* **関連あり（○）**：MLRで係数と寄与率を明示し、**NDWI（最大51.46%）・NDBI（21.38%）**が支配的であることを定量化。
* ただし説明変数が **NDVI/NDBI/NDWI＋距離**中心で、建物密度・道路密度などの"都市構造物理量"は未導入。
* **本研究での拡張余地**: 建物密度・道路密度・緑被率等の物理量を追加し、RF/GBDT＋SHAPで支配性を明確化。

### RQ2（集計単位・スケールで関係がどう変化？）

* **関連は限定的（△）**：本研究は主に時系列（2001–2020）をPCAで要約し、モデル化・分類する設計。
* 複数の空間集計単位（例：30m/60m/100mピクセル）を比較する主題ではない。

### RQ3（データ制約下でどこまで説明可能？）

* **関連あり（◎）**：公開衛星（Landsat＋Sentinel-2）に加え、現地観測は**2日・30点**に限定しつつ、放射率モデル比較とSUHI分類まで実施。
* **熱帯途上国都市（コロンビア）**という点でベトナム都市と類似した条件。
* **放射率推定の重要性**: Fcoverモデル（R²=0.78）が大幅に優位 → ベトナム都市でも同様の放射率推定手法が有効。

---

## 📎 重要な知見・引用候補

### 引用したい箇所

> "the factors with the highest impact are the Normalized Difference Water Index (NDWI) and the Normalized Difference Build-up Index (NDBI)."

> "the fractional vegetation cover model using Sentinel-2 data provides the best results with R² = 0.78 …"

### キーファインディング

* **放射率推定は"手法差"で精度が大きく変わる**（Fcoverが顕著に良い）。
* **"重み付き"NBML**により、温度強度域（介入・監視・強化・保全）として都市計画に接続可能な地図を生成。
* **熱帯都市では水分指標（NDWI）が最大寄与**（51.46%）→ 水域・湿潤地の重要性。

---

## 🖼️ 重要な図表

* **Figure 3**: LST推定と放射率モデル評価のフローチャート（LST算出設計の要点）
* **Figure 8**: 地上LSTと衛星LSTの回帰（FcoverがR²=0.78）
* **Table 3**: MLR係数（NDBI/NDVI/NDWI/PUC、全てp<0.001）
* **Table 5**: 重み（NDWI 51.46%など）
* **Table 6 / Figure 13**: SVM vs NBML 精度比較（NBMLが優位）

---

## ⚠️ 課題・制約（当該研究における）

1. 地上検証はLandsat全期間でなく、**L8の2オーバーパスのみ**（制約として明記）。
2. Fcover放射率は **S2とL8の同期が必要で2015年以降に限定**される（手法適用範囲の制約）。
3. MLR前提（多重共線性など）への配慮として外れ値除去・変数除外を行うが、指数系変数は相関しやすい。
4. **都市構造パラメータが限定的**：NDBI/NDVI/NDWI+距離のみで、建物密度・道路密度・建物高さ等の物理量なし。

---

## 🔖 本研究への示唆

### LST精度向上

* **Sentinel-2由来Fcover放射率**の導入を検討（R²=0.78 vs ASTER 0.27/固定値0.26の大差）
* ベトナム都市でもSentinel-2とLandsat 8の同期観測で放射率推定が可能

### 説明変数設計（RQ1拡張）

* S6は「**NDBI/NDWIが支配的**」を"寄与率（%）"で定量化
* 本研究では、これに **建物密度・道路密度・緑被率（面積率）・OSM要素**などを追加
* RF/GBDT＋SHAPで"支配性"をより都市形態寄りに説明可能

### データ制約下での適用（RQ3）

* 熱帯途上国都市（コロンビア）で、公開衛星＋限定的地上検証で高精度モデル（R²=0.82、Accuracy 95%）を実現
* ベトナム都市でも同様のアプローチが有効

### 手法選択

* MLR＋重み付きNBMLによる温度強度分類（都市計画への接続）
* 本研究ではRF/GBDTでの回帰＋SHAP解釈をベースとするが、分類タスクでの参考になる

---

## 🔖 キーワード

`SUHI`, `LST`, `Landsat`, `Sentinel-2`, `Fcover`, `Emissivity`, `PCA`, `Multiple Linear Regression`, `NDBI`, `NDWI`, `Naïve Bayes`, `Tropical City`, `Colombia`

---

## 📝 メモ（自由記述）

* RQ1に対しては、「**NDBI/NDWIが支配的**」を"寄与率（%）"で出している点が強い。本研究では、これに **建物密度・道路密度・緑被率（面積率）・OSM要素**などを追加し、RF/GBDT＋SHAPで"支配性"をより都市形態寄りに説明できる。
* LSTの精度面では、「放射率（emissivity）をどう作るか」が結果の土台になるので、ベトナム都市でも（可能なら）S2由来Fcoverや同等の放射率推定を検討する価値がある。
* **熱帯都市におけるNDWI優位性**（51.46%）は重要な発見 → ベトナム都市でも水域・湿潤地の冷却効果を重視すべき。
* 現地検証が限定的（2日・30点）でも高精度モデル構築可能 → データ制約下でのアプローチとして参考。

---

**作成日**: 2026-02-26  
**最終更新**: 2026-02-26  
**作成者**: GitHub Copilot（PDF精読はChatGPT/ScholarGPT）
