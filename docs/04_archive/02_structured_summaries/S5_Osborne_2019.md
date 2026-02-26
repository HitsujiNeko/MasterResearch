# S5: Osborne & Alvares-Sanches (2019)

**最終更新**: 2026-02-26  
**分析者**: ChatGPT（PDF精読版）  
**本研究との関連度**: 高（※RQ2スケール依存性への直接的貢献）

---

## 1. 基本情報

| 項目 | 内容 |
|------|------|
| **著者** | Patrick E. Osborne; Tatiana Alvares-Sanches |
| **発表年** | 2019 |
| **タイトル** | Quantifying how landscape composition and configuration affect urban land surface temperatures using machine learning and neutral landscapes |
| **掲載誌** | Computers, Environment and Urban Systems, 76, 80–90 |
| **DOI/URL** | https://doi.org/10.1016/j.compenvurbsys.2019.04.003 |
| **引用数** | 取得不可（PDF精読環境の制約） |

---

## 2. 研究目的

都市の土地被覆の「**構成（composition）**」と「**配置（configuration）**」の両方がLSTに与える影響を、(1) 機械学習で学習したLST予測モデル と (2) **中立景観（neutral landscapes）**による仮想実験を組み合わせて定量化する。特に、配置変更で平均気温は変わらなくても極値や避暑域が変わる点を検証する。

---

## 3. 対象地域・期間

- **対象地域**: Southampton（英国）
- **対象期間**: 複数季節（Landsat 7 ETM+の複数シーンを用いて月別LST→平均LSTを作成）
- **空間スケール**: 都市〜都市内部（30mピクセル＋近傍リング）

---

## 4. 使用データ

| データ名 | 種別 | 空間解像度 | 時間解像度 | 用途 |
|----------|------|-----------|-----------|------|
| Landsat 7 ETM+ | ラスタ | 30m | 複数シーン（月別） | LST算出 |
| Ordnance Survey MasterMap | ベクタ | 1m→30mに集約 | 静的 | 土地被覆割合（建物・道路等） |
| DTM（地形） | ラスタ | 5m | 静的 | 標高・傾斜・方位 |
| 距離変数 | 派生 | 30m | - | 水域距離、都市中心距離 |

---

## 5. 都市構造パラメータ

この論文の"都市構造"は、**建物高さ等の3Dではなく、景観生態学的な構成・配置＋近傍（隣接）効果**として定義される。

| パラメータ名 | 定義・算出方法 | データソース | 本研究RQとの関連 |
|-------------|---------------|-------------|-----------------|
| **構成（composition）** | 30mピクセル内の土地被覆割合（NAT, BUILD, HARD, MIXED） | OS MasterMap | RQ1: ◎（主要変数） |
| **配置（configuration / adjacency）** | 30mピクセル周囲のリング（30–60m/60–90m/90–120m）での土地被覆割合 | OS MasterMap | **RQ2: ◎◎（スケール設計の核心）** |
| 距離変数 | 水域距離、都市中心（建物重心）距離 | 派生 | RQ1: ○ |
| 景観指標 | CONTAGION / CLUMPY（FRAGSTATS） | 派生 | RQ2: ○ |

**重要**: 本研究は「同じ構成比でも配置でLST極値が変わる」ことを、仮想実験で切り分ける設計。

---

## 6. 分析手法

### 6.1 LST算出手法

- 輝度温度BTから放射率補正を含む式でLST算出（Artis & Carnahan, 1982）
- 放射率εは土地被覆クラス別に文献値を割り当て、1m土地被覆→30m平均放射率を作成

### 6.2 統計・機械学習手法

**決定木＋確率的勾配ブースティング（generalized boosted regression; Rのgbm）**

- **10-fold CV**で最適化
- **訓練データ内相関**: 0.955
- **独立テスト相関**: **0.956**（n=102,935）
- 最終パラメータ例：trees=5600、bag fraction=0.5、tree complexity=5、learning rate=0.01

### 6.3 仮想実験設計

**中立景観（Landscape Generator）**で「構成固定・配置変更」の15ケースを生成し、学習済みモデルへ投入

**アルゴリズム概要**:
1. Landsat BT → 放射率εを用いてLST算出（Artis & Carnahan式）
2. 30mピクセルの土地被覆割合（建物/硬質/自然/混合）＋**近傍リング（30–60m等）**を算出
3. 勾配ブースティング回帰で平均LST（複数月平均）を学習（CV最適化）
4. Landscape Generatorで「構成固定・配置変更」の中立景観(15ケース)を生成
5. 中立景観の説明変数を再計算し、学習モデルでLST・UHI指標を予測
6. 配置指標（CONTAGION/CLUMPY）とUHI指標の関係を評価

### 6.4 空間集計単位

- **30mピクセル**基準
- **近傍リング**: 30–60m / 60–90m / 90–120m

---

## 7. 主要結果

### 7.1 定量的結果

- **モデル性能**: テストデータ相関 **0.956**（n=102,935）
- **隣接効果が強い**: 30m解像度では immediate（当該ピクセル）より **adjacency（周辺）が強い**と結論
- **配置操作の効果**:
  - 都市平均はほぼ一定（16.9–17.1°C）
  - 局所最小は**0.9°C**変化
  - 局所最大は**4.2°C**変化
- **建物表面の冷却余地**: 配置変更で建物の平均LSTを最大**2.1°C低減可能**
- **最適配置**: 自然被覆≈60% かつ 7–8パッチ/km²付近が最大冷却

### 7.2 変数重要度

| 順位 | 変数名 | 備考 |
|------|--------|------|
| 1 | **NAT** | 自然被覆割合（当該ピクセル） |
| 2 | **NAT_ANN12** | 自然被覆割合（30–60mリング） |
| 3以下 | BUILD, BUILD_ANN12等 | 建物被覆及びその近傍 |

**重要**: Table 2で説明変数一覧＋重要度を明示（NAT, NAT_ANN12等が上位）

### 7.3 主要な発見

- **"完全ランドシェアリング（完全ランダム混在）"**は最大LSTを下げる一方、最小LSTが上がり「涼しい避難場所」が減る（トレードオフ）
- 建物クラスタを強く集約すると、建物ピクセルの平均LSTが上昇（19.7→20.8°C）
- **30mでは隣接（annuli）効果が即時効果より強い**（都市内部の温度は"周囲の構成"に強く依存）
- 配置を変えても都市平均LSTはほぼ変わらないが、極値・島（hot/cold islands）・避暑域が大きく変わる

---

## 8. 本研究との関連性

| Research Question | 関連度 | 詳細 |
|-------------------|--------|------|
| **RQ1** | **○** | "どの説明変数が支配的か"を、GBMの重要度・近傍変数で示す。特にNATと周辺NATが主要。 |
| **RQ2** | **◎◎** | **30mピクセル＋30–60m/60–90m/90–120mリングでスケール（近傍範囲）を明示的に扱う。RQ2の核心的参考文献。** |
| **RQ3** | **△** | 本研究は高品質なOSデータ依存。ただし「衛星＋公開/入手可能な地物データ→ML→政策示唆」という枠組みは参考になる。 |

---

## 9. 限界・課題

- 事例都市が1都市（Southampton）であり、一般化は追加検証が必要
- 高品質な地物データ（OS MasterMap等）に依存し、途上国で同等データがない場合の適用に工夫が必要
- LSTは30m基準であり、街区・建物スケールの詳細温熱には限界（ただし近傍効果で補う設計）

---

## 10. 本研究への示唆

### 直接的な活用方法

**"近傍（annuli）説明変数"の導入**:
- 建物密度・道路密度・NDVI等を、30m/60m/90m/120m近傍で再計算
- 重要度比較（RF/GBM/SHAP）へ展開可能

**スケール比較の設計**:
- **RQ2の「集計単位・解析スケール」で、S5の"リング設計"は強いテンプレになる**

### 差別化ポイント

| 項目 | S5（先行研究） | 本研究 |
|------|---------------|--------|
| 対象地域 | 1都市（英国） | ベトナム主要都市（途上国） |
| 手法 | 中立景観による仮想実験 | データ制約下での実証分析 |
| データ | OS MasterMap（高品質） | OpenStreetMap＋公開データ |
| 新規性 | 配置効果の分離 | 複数都市・複数スケール比較（RQ2） |

**代替案**: 途上国のデータ制約下では、OS MasterMap相当の代替として **OpenStreetMap（建物/道路）＋Sentinel/Landsat指標（NDVI/NDBI等）**で"近傍変数"を再現し、RF/GBM/SHAPで重要度比較する設計が現実的。

---

## 11. 重要な引用・図表

### 引用すべき記述

> "The model achieved a correlation … 0.956 … In contrast to other studies, we found adjacency effects to be stronger … at 30 m resolution."（Abstract）

> "When we manipulated landscape configuration, the average city temperature remained the same but the local minima varied by 0.9 °C and the maxima by 4.2 °C."（Abstract）

> "In our city, maximum cooling was achieved when ~60% of land was left natural and distributed in 7–8 patches km⁻²…"（Abstract）

### 参考にすべき図表

- **Figure 3**: 解析フロー（LST作成→ML→中立景観→予測）
- **Table 2**: 説明変数一覧＋重要度（NAT, NAT_ANN12等が上位）
- **Table 3**: 月別LSTとUHI指標（例：最小/最大/ホットアイランド面積など）
- **Table 4**: 15中立景観の平均/範囲/島数（平均16.9–17.1°C、完全ランダムで最大が低い等）
- **Table 5**: 配置指標（CONTAGION/CLUMPY）とUHI指標の相関
- **Figure 7**: 建物ピクセルの平均LSTが配置でどう変わるか（最大2.1°C差）

---

## 12. メタ情報

- **重要度**: A（RQ2スケール依存性の核心文献）
- **データ入手可能性**: 部分的（Landsatは可、OS MasterMapは英国特有）
- **再現可能性**: 高（手法詳細・パラメータ明示）
- **キーワード**: LST; UHI; landscape composition; landscape configuration; adjacency effects; boosted regression trees; neutral landscapes; FRAGSTATS; CONTAGION; CLUMPY
- **作成日**: 2026-02-26
- **分析ツール**: ChatGPT (ScholarGPT)

---

## 📌 PDF精読による重要な発見

### RQ2への直接的貢献

**「同心リング（30–60m等）を説明変数化」＋「都市全体の平均は変わらないが極値が変わる」**という視点は、ベトナム主要都市でも非常に効く設計。

### 近傍効果の定量化

30m解像度では**当該ピクセルより周辺ピクセル（30–60m等）の方が影響が強い**という発見は、都市計画上の示唆が大きい。

### 構成と配置の分離

中立景観による仮想実験で、同じ構成比でも配置次第でLST極値が大きく変わることを実証。本研究の新規性（RQ2）を際立たせる対比になる。
