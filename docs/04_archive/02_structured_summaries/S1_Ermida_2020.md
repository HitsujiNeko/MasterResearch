# S1: Ermida et al. (2020)

**最終更新**: 2026-02-26  
**分析者**: ChatGPT（PDF精読版）  
**本研究との関連度**: 中（※LST推定"手法基盤"として重要。都市構造×LSTの説明変数比較そのものではない）

---

## 1. 基本情報

| 項目 | 内容 |
|------|------|
| **著者** | Sofia L. Ermida; Pedro Soares; Victor Mantas; Frank-M. Göttsche; Isabel F. Trigo |
| **発表年** | 2020 |
| **タイトル** | Google Earth Engine Open-Source Code for Land Surface Temperature Estimation from the Landsat Series |
| **掲載誌** | Remote Sensing, 12(9), 1471 |
| **DOI/URL** | https://doi.org/10.3390/rs12091471 |
| **引用数** | 取得不可（PDF精読環境の制約） |

---

## 2. 研究目的

Google Earth Engine（GEE）上で、Landsat 4/5/7/8のLSTを一貫した枠組みで算出できるオープンソース実装を提供し、ローカル保存や重い前処理を避けつつ、LST解析を再現可能にすること。GEE上で高解像度LSTが未整備である点を補う狙い。

---

## 3. 対象地域・期間

- **対象地域**: グローバルに適用可能（入力ROIに依存）。手法検証は主にSURFRAD/BSRN/KITの12観測点（米国・欧州等）を使用
- **対象期間**: NCEP/NCAR再解析TCWVは1948–現在、6時間・2.5°で利用し、Landsat撮像時刻へ補間
- **空間範囲**: ユーザー指定ROI（論文は手法論中心のため固定km²の提示はなし）

---

## 4. 使用データ

| データ名 | 種別 | 空間解像度 | 時間解像度 | 用途 |
|----------|------|-----------|-----------|------|
| Landsat 4/5/7/8（TOA BT / SR等） | ラスタ | 熱赤外は主に30m格子で出力 | 16日程度 | LST算出の基礎（BT, NDVI等） |
| NCEP/NCAR Reanalysis（TCWV） | ラスタ/再解析 | **2.5°** | 6時間（00/06/12/18UTC） | SMW係数クラス割当・大気水蒸気入力 |
| ASTER GEDv3（放射率） | ラスタ | 100m | 2000–2008の平均（静的） | 放射率の基礎。NDVIで植生動態補正 |
| in situ LST（SURFRAD/BSRN/KIT） | 観測 | 点 | 連続/サイト依存 | 検証（12サイト） |

---

## 5. 都市構造パラメータ

| パラメータ名 | 定義・算出方法 | データソース | 本研究RQとの関連 |
|-------------|---------------|-------------|-----------------|
| NDVI（放射率補正用） | NDVI→FVC（閾値NDVIbare=0.2, NDVIveg=0.86）→放射率補正 | Landsat NDVI + ASTER GEDv3 | RQ1: △（説明変数というよりLST推定の内部処理） |
| （都市形状/建物/道路等） | 扱わない | — | RQ1/RQ2: - |

**注記**: 本論文は「都市構造×LSTの支配変数」を比較する研究ではなく、**LST推定手法（GEE実装）**が主眼。

---

## 6. 分析手法

### 6.1 LST算出手法

**SMW（Single-Channel / Statistical Mono-Window）アルゴリズム**（CM-SAFで開発・利用）

- 1本のTIRチャネルのTOA輝度温度Tbと放射率εから、線形式でLSTを推定：  
  **LST = Ai·Tb/ε + Bi·(1/ε) + Ci**
  
- 係数(Ai,Bi,Ci)はTCWV（0–6cmを0.6cm刻み、10クラス）別に回帰で推定

- 実装では、TCWV（NCEP/NCAR）に基づき係数クラスを割当、放射率はASTER GEDv3＋NDVI補正

### 6.2 統計評価

- **回帰（係数キャリブレーション）**: 放射伝達シミュレーションに基づく回帰で係数推定
- **検証統計**: ロバスト統計（median error=µ、precision=σ、RMSE）を使用

### 6.3 空間単位

- 30mピクセル基準（例：検証で半径30mの抽出領域を用いる図示あり）

---

## 7. 主要結果

### 7.1 定量的結果

- **12観測点での検証**: Landsat 5/7/8の全体RMSEが約**2.0–2.1 K**、全体の精度（bias相当）は0.5K / -0.1K / 0.2K と報告
- **サイト別**: （一部サイトを除き）RMSEが概ね**1.4–2.5Kの範囲**と記述
- 極端に湿潤（TCWV>5cm）条件でLandsat 8の方がやや良い傾向を示唆

### 7.2 主要な発見

- GEE上でLandsat LSTを一貫手順で生成できる公開リポジトリを提供
- 入力（TCWV・放射率等）はGEEカタログ由来で完結し、ローカル処理負担を軽減
- SMWは放射率に明示的依存を持ち、TCWVクラス別係数で大気水蒸気影響を扱う
- 放射率はASTER GEDv3の静的値に対し、NDVI/FVCで植生動態補正を行う

---

## 8. 本研究との関連性

| Research Question | 関連度 | 詳細 |
|-------------------|--------|------|
| **RQ1** | **○** | Landsat 8 LSTを得る際の**推定誤差水準（Kオーダ）**と、放射率・TCWVの扱い（ASTER＋NDVI補正、NCEP/NCAR）が明確。RQ1で「都市構造変数の支配性」を議論する前提として、目的変数LSTの生成・不確実性管理の根拠になる。 |
| **RQ2** | **△** | 集計単位そのものを比較する研究ではないが、ピクセル/近傍抽出（30m相当）の扱いが示され、LSTの空間代表性・検証の難しさの議論に接続可能。 |
| **RQ3** | **○** | 「公開データ＋衛星＋GEE」で完結する設計思想は、測量データ制約下での再現可能分析に合致。 |

---

## 9. 限界・課題

- **NCEP/NCARのTCWVは2.5°と粗く**、地域内でほぼ一定になる旨の記述あり（表示省略の理由）
- ASTER GEDv3は2000–2008平均であり、植生変動はNDVI補正で対応する前提
- 検証においてサイトの空間代表性（SURFRAD等）に限界があることを議論

---

## 10. 本研究への示唆

- 目的変数LSTの作り方（SMW+TCWV+放射率補正）を固定し、都市構造変数比較（RQ1）に集中できる
- **2.5°TCWVの粗さが熱帯・沿岸（ベトナム）でどう効くかは、感度分析や別TCWVデータ検討の動機になる**

---

## 11. 重要な引用・図表

### 引用すべき記述

> "The LST values are estimated using the SMW algorithm… water vapor… from NCEP/NCAR… emissivity from the ASTER GEDv3… NDVI-based correction…"

### 参考にすべき図表

- **Figure 1**: GEE処理チェーン（TCWV→放射率→SMW適用の流れ）
- **Table 3**: サイト別検証統計（µ, σ, RMSE, N）

---

## 12. メタ情報

- **重要度**: A（LST生成の根幹）
- **データ入手可能性**: 可（GEEリポジトリ公開）
- **再現可能性**: 高（コード公開・GEE完結）
- **キーワード**: Landsat; LST; Google Earth Engine; SMW; TCWV; NCEP/NCAR; ASTER GEDv3; emissivity; validation
- **作成日**: 2026-02-26
- **分析ツール**: ChatGPT (ScholarGPT)

---

## 📌 PDF精読による重要な修正点

1. **手法名の確認**: SMW（Statistical Mono-Window）法が正式名称
2. **RMSE修正**: 1.3K→**2.0–2.1K**（より正確な全体値）
3. **TCWV粗さ**: **2.5°の空間解像度**という重要な限界を明記
4. **RQ1関連度**: ◎→○に修正（手法基盤としての位置づけ）
