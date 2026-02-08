# ドキュメント概要

本ドキュメントは先行研究の事実整理を目的とし、
本研究との適合性や優劣評価は行わない。

# 先行研究整理（LSTと都市構造：事実整理版）

## 0. 本ドキュメントの位置づけ

本ドキュメントは、地表面温度（LST）と都市構造に関する**先行研究の内容を事実ベースで整理**することを目的とする。
ここでは、各研究における都市構造の定義、使用データ、分析手法、主な結論を記述し、**本研究との適合性評価や研究手法の優劣判断は行わない**。

---

## 1. 先行研究一覧

| ID | 著者（年）                             | 主対象地域     | 主目的        | データ種別  |
| -- | --------------------------------- | --------- | ---------- | ------ |
| S1 | Ermida et al. (2020)              | グローバル     | LST算出手法の確立 | 衛星・再解析 |
| S2 | Le Ngoc Hanh & Tran Thi An (2025) | ベトナム（ダナン） | 都市化とLST変化  | 衛星     |
| S3 | Onačillová et al. (2022)          | 欧州都市      | 高解像度LST生成  | 衛星     |

---

## 2. 先行研究 S1

### Ermida et al. (2020)

**Google Earth Engine open-source code for Land Surface Temperature estimation from the Landsat series**

### 2.1 研究目的

Landsat系列衛星を用いた地表面温度（LST）の算出について、物理的要因（放射率・大気水蒸気量）を考慮したSMW（Statistical Mono-Window）法を、Google Earth Engine（GEE）上で再現可能な形で実装・公開することを目的とする。

### 2.2 使用データ

* Landsat 4–8（熱赤外バンド）
* ASTER GED（地表放射率）
* NCEP/NCAR 再解析データ（大気水蒸気量）

### 2.3 都市構造の扱い

本研究では都市構造や土地利用の分析は目的としておらず、都市構造に関するパラメータは導入していない。

### 2.4 分析手法

* SMW（Statistical Mono-Window）法によるLST算出
* NDVIに基づく動的放射率補正

### 2.5 主な結論

* SMW法は従来手法と比較して、大気条件の変動に対して安定したLST推定が可能である。
* GEEを用いることで広域・長期のLST算出を再現性高く実施できる。

### 2.6 当該研究における課題・制約

* LST算出手法の確立を目的としており、都市構造や土地被覆との関係分析は行われていない。
* 都市スケールでの解釈や応用は各研究に委ねられている。

---

## 3. 先行研究 S2

### Le Ngoc Hanh & Tran Thi An (2025)

**Assessment of Temperature Change in Da Nang City, Vietnam, Using Remote Sensing and Cloud-Computing Approach**

### 3.1 研究目的

ベトナム・ダナン市を対象に、長期的な地表面温度（LST）の変化傾向を把握し、都市化の進行との関係を明らかにすることを目的とする。

### 3.2 使用データ

* Landsat 5 TM / Landsat 8 OLI
* Google Earth Engine による時系列処理

### 3.3 都市構造の定義・パラメータ

本研究では都市構造を以下の指標で表現している。

* NDVI（植生量の指標）
* NDBI（都市化・不透水面の代理指標）

水域、人口密度、交通構造などの指標は使用していない。

### 3.4 分析手法

* LST算出（GEE）
* NDVI・NDBIの算出
* LSTとNDBIの相関分析
* 行政区単位での空間集計

### 3.5 主な結論

* 都市化の進行に伴いLSTが上昇する傾向が確認された。
* LSTとNDBIの間に強い正の相関が示された。

### 3.6 当該研究における課題・制約

* 都市構造をNDVI・NDBIという限られた指標で表現している。
* 水域、人口密度、交通構造など他の都市構造要素が考慮されていない。
* 相関分析が中心であり、複数要因を同時に扱った寄与度評価は行われていない。

---

## 4. 先行研究 S3

### Onačillová et al. (2022)

**Combining Landsat 8 and Sentinel-2 Data to Derive Higher Resolution LST Maps in Urban Environment**

### 4.1 研究目的

都市域において、Landsat 8（30m）のLSTをSentinel-2（10m）データを用いて高解像度化し、詳細な温度分布を把握することを目的とする。

### 4.2 使用データ

* Landsat 8（熱赤外バンド）
* Sentinel-2 MSI

### 4.3 都市構造の定義・パラメータ

本研究では、都市構造パラメータそのものを主対象とはせず、以下を補助的に利用している。

* NDVI（ダウンスケーリング用補助変数）

建物、水域、人口などの都市構造指標は直接的には用いていない。

### 4.4 分析手法

* Landsat–Sentinel統合によるダウンスケーリング
* 回帰モデルを用いた高解像度LST推定

### 4.5 主な結論

* 都市内部におけるLSTの空間的不均一性を高解像度で表現可能である。
* 緑地や市街地の温度差が視覚的に明瞭となった。

### 4.6 当該研究における課題・制約

* 主目的がLSTの高解像度化であり、都市構造要因の定量的評価は行われていない。
* Sentinel-2データに依存するため、利用可能地域や時期に制約がある。
* 処理工程が多く、計算コストや汎用性の面で課題が残る。

---

了解しました。
では、**既存の「S1〜S3（事実整理フォーマット）」と完全に同じ思想・粒度**で、先ほど挙げた追加候補研究を **S4以降として追記**します。
※以下は **評価・優劣判断を行わない「事実整理」**に徹しています。

---

# 先行研究整理（追記分：S4–S8）

（LSTと都市構造：事実整理版・追補）

---

## S4. Sun et al. (2019)

### Sun et al. (2019)

**Quantifying the effects of urban form on land surface temperature in subtropical high-density urban areas using machine learning**

### S4.1 研究目的

高密度都市において、都市形態（urban form）が地表面温度（LST）に与える影響を定量的に評価することを目的とする。特に、複数の都市構造指標を同時に考慮した場合の影響度を明らかにすることを主眼とする。

### S4.2 使用データ

* Landsat 衛星データ（LST）
* 都市土地利用データ
* 建物密度、道路密度、緑地率等の都市構造指標

### S4.3 都市構造の定義・パラメータ

本研究では都市構造を以下のような**物理的・空間的指標**で定義している。

* 建物被覆率
* 建物密度
* 道路密度
* 緑地率

NDVI・NDBIに限定せず、都市形態を直接表す指標を複数導入している。

### S4.4 分析手法

* ランダムフォレスト回帰モデル
* 変数重要度（Variable Importance）の算出
* ブロックスケールでの空間集計

### S4.5 主な結論

* 都市形態指標はLSTに対して異なる影響度を持つことが示された。
* 緑地関連指標と建物関連指標の影響が空間的に異なる傾向が確認された。

### S4.6 当該研究における課題・制約

* 対象都市は限定されており、他地域への一般化には注意が必要である。
* 時系列変化よりも単年度解析に重点が置かれている。

*Sun, Y. et al. (2019). Remote Sensing, 11(8), 959.*
[https://www.mdpi.com/2072-4292/11/8/959](https://www.mdpi.com/2072-4292/11/8/959)

---

## S5. Osborne & Alvares-Sanches (2019)

### Osborne & Alvares-Sanches (2019)

**Quantifying how landscape composition and configuration affect urban land surface temperatures using machine learning and neutral landscapes**

### S5.1 研究目的

都市域における土地利用の「構成（composition）」および「配置（configuration）」がLSTに与える影響を明らかにすることを目的とする。

### S5.2 使用データ

* リモートセンシング由来のLST
* 土地利用・土地被覆（LULC）データ

### S5.3 都市構造の定義・パラメータ

都市構造を以下の2側面で整理している。

* **構成**：土地利用種別の割合
* **配置**：パッチサイズ、分断度、隣接関係などの景観指標

### S5.4 分析手法

* 機械学習モデル
* 中立景観モデル（Neutral Landscape Models）
* シナリオ比較分析

### S5.5 主な結論

* 都市の土地利用配置はLST分布に影響を及ぼす。
* 同一構成比であっても配置の違いによりLSTが異なることが示された。

### S5.6 当該研究における課題・制約

* 景観指標の算出に専門的処理が必要である。
* 都市計画データとの直接的な接続は行われていない。

*Osborne, P.E., & Alvares-Sanches, T. (2019). Computers, Environment and Urban Systems.*
[https://www.sciencedirect.com/science/article/pii/S0198971518303806](https://www.sciencedirect.com/science/article/pii/S0198971518303806)

---

## S6. Garzón et al. (2021)

### Garzón et al. (2021)

**A remote sensing approach for surface urban heat island modeling in a tropical Colombian city using regression analysis and machine learning algorithms**

### S6.1 研究目的

熱帯都市を対象として、地表面温度および表面都市ヒートアイランド（SUHI）を説明する要因を抽出することを目的とする。

### S6.2 使用データ

* Landsat 衛星データ
* 土地利用・土地被覆データ

### S6.3 都市構造の定義・パラメータ

* NDVI
* NDBI
* 土地利用区分

### S6.4 分析手法

* 重回帰分析
* 複数の機械学習モデルによる比較

### S6.5 主な結論

* 都市化指標とLSTの関係が熱帯都市においても確認された。
* 手法によって説明力に差が生じることが示された。

### S6.6 当該研究における課題・制約

* 都市構造パラメータは比較的限定的である。
* 高解像度な建物形態指標は用いられていない。

*Garzón, J. et al. (2021). Remote Sensing, 13(21), 4256.*
[https://www.mdpi.com/2072-4292/13/21/4256](https://www.mdpi.com/2072-4292/13/21/4256)

---

## S7. Zhong et al. (2024)

### Zhong et al. (2024)

**Downscaled high spatial resolution images from automated machine learning for assessment of urban structure effects on land surface temperatures**

### S7.1 研究目的

都市構造がLSTに与える影響を高解像度で評価するため、AutoMLを用いたLSTダウンスケーリング手法を構築することを目的とする。

### S7.2 使用データ

* Landsat LST
* Sentinel 系衛星データ
* 都市関連補助データ

### S7.3 都市構造の定義・パラメータ

* 建物被覆
* 植生指標
* 不透水面関連指標

### S7.4 分析手法

* Automated Machine Learning（AutoML）
* ダウンスケーリングモデル

### S7.5 主な結論

* AutoMLにより高解像度LST推定が可能である。
* 都市構造とLSTの関係が詳細に可視化された。

### S7.6 当該研究における課題・制約

* 処理フローが複雑で計算コストが高い。
* 都市構造要因の解釈性は限定的である。

*Zhong, X. et al. (2024). Building and Environment.*
[https://www.sciencedirect.com/science/article/pii/S0360132324007765](https://www.sciencedirect.com/science/article/pii/S0360132324007765)

---

## S8. Tanoori et al. (2024)

### Tanoori et al. (2024)

**Machine learning for urban heat island (UHI) analysis: Predicting land surface temperature (LST) in urban environments**

### S8.1 研究目的

都市環境において、複数の機械学習手法を用いてLSTを推定し、都市ヒートアイランド現象の要因を分析することを目的とする。

### S8.2 使用データ

* リモートセンシング由来LST
* 土地利用・都市化指標

### S8.3 都市構造の定義・パラメータ

* 土地利用区分
* 都市化指標（不透水面等）

### S8.4 分析手法

* 複数機械学習モデルの比較
* モデル性能評価

### S8.5 主な結論

* 都市構造要因を用いたLST推定が可能である。
* 手法ごとに予測精度が異なる。

### S8.6 当該研究における課題・制約

* 都市構造パラメータの定義は比較的抽象的である。
* 寄与度の厳密な因果解釈は行われていない。

*Tanoori, G. et al. (2024). Urban Climate.*
[https://www.sciencedirect.com/science/article/pii/S2212095524001585](https://www.sciencedirect.com/science/article/pii/S2212095524001585)

---

## 追記後の整理上のポイント（事実整理）

* S4以降では、**都市構造を複数の物理指標として導入**する研究が確認される
* 機械学習を用いた研究では、**寄与度評価や変数重要度算出**が行われる例がある
* 一方で、途上国都市やデータ制約下での体系的整理は限定的である

---
