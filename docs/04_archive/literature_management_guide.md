# 先行研究管理・活用ガイド（AI活用最適化版）

## 📋 現状分析

### 課題
1. **PDF形式の論文**: AIが直接参照できない（4ファイル： `既往研究PDF/`）
2. **Web論文**: URLはあるが、AIが常にアクセスできるとは限らない
3. **情報の分散**: 重要な知見が論文に埋もれている

### 現在の資産
- ✅ `docs/04_archive/previous_studies_report.md`: 事実整理済み（S1〜S8）
- ✅ `既往研究PDF/`: 主要論文4本（Ermida, Le Ngoc Hanh, Onačillová, Sun）

---

## 🎯 AIが先行研究を効果的に活用するための戦略

### 原則
**「AIが読める形で構造化情報を整備する」**

AIは以下の形式なら確実に参照可能：
- ✅ Markdownファイル（`.md`）
- ✅ CSVファイル（`.csv`）
- ✅ Pythonコード内のコメント
- ❌ PDFファイル（直接読めない）
- △ Web論文（アクセス制限、変更の可能性）

---

## 🗂️ 提案1: 多層構造の文献データベース

### 推奨ディレクトリ構造

```
docs/04_archive/
├── README.md                           # 現状
│
├── previous_studies_report.md          # 現状：事実整理（S1〜S8）
│
├── 01_metadata/                        # 【新規】論文メタデータ
│   ├── papers_database.csv             # 全論文の基本情報
│   └── citation_guide.md               # 引用ガイド
│
├── 02_structured_summaries/            # 【新規】構造化要約
│   ├── S1_ermida_2020.md               # 詳細要約
│   ├── S2_le_ngoc_hanh_2025.md
│   ├── S3_onacillova_2022.md
│   └── ...
│
├── 03_key_findings/                    # 【新規】重要知見の抽出
│   ├── lst_methods_comparison.md      # LST算出手法の比較
│   ├── urban_parameters_catalog.md    # 都市構造パラメータ一覧
│   └── machine_learning_approaches.md # ML手法の整理
│
└── 04_pdfs/                            # 【改名】元のPDFファイル
    ├── S1_ermida_2020.pdf              # リネーム推奨
    ├── S2_le_ngoc_hanh_2025.pdf
    └── ...
```

---

## 📄 提案2: 論文メタデータベース（CSV）

### `01_metadata/papers_database.csv`

AIが検索・フィルタリングしやすい形式で整理：

| ID | 著者 | 年 | タイトル | 主目的 | データ | 手法 | 対象地域 | URL | PDF有無 | 重要度 | RQ関連 |
|----|------|-----|---------|--------|------|------|----------|-----|---------|--------|--------|
| S1 | Ermida et al. | 2020 | GEE open-source LST | LST算出手法 | Landsat | SMW法 | グローバル | https://... | ✓ | A | 手法 |
| S2 | Le et al. | 2025 | Temp Change Da Nang | 都市化とLST | Landsat | GEE | ダナン | https://... | ✓ | B | 途上国 |

**利点**:
- AIがPandas/CSVツールで検索・集計可能
- 「RQ1に関連する論文を抽出」などの指示が可能

---

## 📝 提案3: 構造化要約テンプレート

### `02_structured_summaries/[論文ID].md` の標準フォーマット

```markdown
# S1: Ermida et al. (2020)

## 📌 基本情報
- **著者**: Ermida, S.L., Soares, P., Mantas, V., et al.
- **年**: 2020
- **タイトル**: Google Earth Engine open-source code for Land Surface Temperature estimation from the Landsat series
- **掲載誌**: Remote Sensing, 12(9), 1471
- **DOI/URL**: https://doi.org/10.3390/rs12091471
- **PDF**: `04_pdfs/S1_ermida_2020.pdf`

---

## 🎯 研究目的（1行）
Landsat LSTをSMW法でGEE上に実装し、再現性を確保

---

## 📊 使用データ
- Landsat 4–8（熱赤外バンド）
- ASTER GED（放射率）
- NCEP/NCAR（TPW）

---

## 🔬 手法
### 主要手法
- SMW（Statistical Mono-Window）法
- NDVIベース動的放射率補正

### アルゴリズム概要
1. Landsat TOA B10から輝度温度（Tb）算出
2. ASTERから放射率推定
3. NCEPからTPW取得・補間
4. SMW式でLST算出: LST = A×(Tb/ε) + B/ε + C

---

## 📈 主な結果
- SMW法は従来手法より大気条件変動に安定
- GEEでの広域・長期解析が可能

---

## 🔍 本研究との関連性
### RQとの対応
- **RQ全般**: 本研究のLST算出手法として採用

### 活用方法
- SMW法の実装参考
- パラメータ設定の根拠

### 差別化ポイント
- Ermida: 手法開発
- 本研究: 都市構造との関係性評価

---

## 💡 重要な知見・引用候補
> "SMW法は大気水蒸気量の変動に対してロバスト"（p.5）

> "ASTER放射率とNDVI補正の組み合わせが有効"（p.8）

---

## 📎 補足情報
### 使用した図表
- Figure 3: SMW法のフローチャート → 論文執筆時に参照
- Table 2: 係数A, B, Cの一覧 → 実装時に使用

### キーワード
`SMW`, `Landsat`, `LST`, `emissivity`, `Google Earth Engine`

---

**作成日**: 2026-02-26  
**最終更新**: 2026-02-26
```

**利点**:
- AIが論文全体を理解できる
- 「S1とS4のLST算出手法を比較して」などの指示が可能
- RQとの関連が明確

---

## 📚 提案4: 重要知見の横断整理

### `03_key_findings/urban_parameters_catalog.md`

研究テーマ別に複数論文の知見を統合：

```markdown
# 都市構造パラメータ一覧（先行研究横断整理）

## 📊 パラメータ比較表

| パラメータ | S1 | S2 | S4 | S5 | 定義 | 算出方法 |
|-----------|----|----|----|----|------|----------|
| **NDVI** | ✓ | ✓ | ✓ | ✓ | 正規化植生指数 | (NIR-Red)/(NIR+Red) |
| **NDBI** | - | ✓ | - | - | 正規化建物指数 | (SWIR-NIR)/(SWIR+NIR) |
| **建物被覆率** | - | - | ✓ | ✓ | グリッド内建物面積割合 | GISデータから算出 |
| **道路密度** | - | - | ✓ | - | グリッド内道路延長 | 道路データから算出 |

## 🔍 詳細

### NDVI（植生指数）
**使用研究**: S1, S2, S4, S5

**定義の違い**:
- S1: 放射率補正に使用（0.2〜0.86で線形補間）
- S2: 都市化指標として使用
- S4: 説明変数として直接投入

**本研究での活用方針**:
- 説明変数として使用（S4, S5に準拠）
- 放射率補正にも使用（S1に準拠）
```

**利点**:
- 「NDVIの定義を各研究で確認」などの指示が不要
- AIが横断的な知見を即座に提供

---

## 🤖 提案5: AIとの対話最適化

### A. 論文要約の作成方法

#### 方法1: 手動作成（推奨）
1. PDFを読んで重要情報を抽出
2. テンプレートに沿ってMarkdownで記述
3. `02_structured_summaries/` に保存

#### 方法2: AIアシスト作成
```
# 対話例
ユーザー: 「Ermida et al. 2020のPDFを読んだので、重要ポイントを教えます。
         以下の情報を02_structured_summaries/S1_ermida_2020.mdのテンプレートに整形してください：
         
         - 目的: SMW法をGEEで実装
         - データ: Landsat 4-8, ASTER, NCEP
         - 手法: 動的放射率補正を使用
         - 結果: 大気変動に安定
         ...」

AI: 「承知しました。テンプレートに沿って整形します」
```

### B. Web論文の活用

**Web検索可能な論文の場合**:
- AIに「この論文のURLにアクセスして要約して」は**不確実**
- **推奨**: 手動で要約を作成し、Markdown化

**理由**:
- アクセス制限、ペイウォール
- サイト構造の変更
- 安定性・再現性の問題

### C. 効果的なAI対話例

#### 例1: 横断比較
```
「urban_parameters_catalog.mdを参照して、
 建物被覆率を使用している研究とその算出方法を一覧化」
```

#### 例2: RQ関連研究の抽出
```
「papers_database.csvから、RQ1に関連する研究（重要度A）を抽出して、
 それぞれの手法を比較表にして」
```

#### 例3: 引用文作成
```
「S1〜S3の情報から、SMW法の利点を説明する段落を論文用に作成」
```

---

## 🚀 実装ロードマップ

### Phase 1: 基盤整備（優先度：高）
- [ ] フォルダ構造の作成（`01_metadata/`, `02_structured_summaries/`, `03_key_findings/`, `04_pdfs/`）
- [ ] `papers_database.csv` の作成（S1〜S8の基本情報）
- [ ] PDFファイルのリネーム（S1_ermida_2020.pdf など）

### Phase 2: 構造化要約（優先度：高）
- [ ] テンプレートの作成
- [ ] 主要4論文（PDF有）の要約作成
  - [ ] S1: Ermida et al. (2020)
  - [ ] S2: Le Ngoc Hanh (2025)
  - [ ] S3: Onačillová et al. (2022)
  - [ ] S4: Sun et al. (2019)（PDFがあれば）

### Phase 3: 知見の統合（優先度：中）
- [ ] `urban_parameters_catalog.md` 作成
- [ ] `lst_methods_comparison.md` 作成
- [ ] `machine_learning_approaches.md` 作成

### Phase 4: 継続的更新（優先度：低）
- [ ] 新しい論文の追加
- [ ] RQとの関連性の更新

---

## 💡 ベストプラクティス

### 1. 情報の粒度
- **メタデータ**: 1行で概要が分かる（CSV）
- **要約**: 5分で全体像が分かる（構造化Markdown）
- **詳細**: 必要時にPDFを参照

### 2. 命名規則
- **論文ID**: `S1`, `S2`...（既存に準拠）
- **ファイル名**: `S1_ermida_2020.md`（著者名_年）
- **フォルダ**: `01_`, `02_`（順序を明示）

### 3. AI活用の鉄則
- ❌ 「このPDFを読んで」→ 不可能
- ✅ 「S1_ermida_2020.mdを参照して」→ 確実
- ✅ 「papers_database.csvから抽出して」→ 効率的

---

## 🔄 既存ファイルとの統合

### `previous_studies_report.md` との関係
- **既存ファイル**: 事実整理の**マスター**として維持
- **新規ファイル**: より詳細・構造化された情報
- **役割分担**:
  - `previous_studies_report.md`: 概要把握、一覧表示
  - `02_structured_summaries/`: 個別論文の深掘り
  - `03_key_findings/`: テーマ別知見の統合

---

## 📊 期待される効果

| 項目 | Before | After | 効果 |
|-----|--------|-------|------|
| **AI参照性** | PDFは不可 | Markdownで確実 | **100%参照可能** |
| **検索効率** | 手動でPDF検索 | CSV/MD検索 | **秒単位で情報取得** |
| **横断比較** | 手動で整理 | AI自動集計 | **大幅な時間短縮** |
| **論文執筆** | PDFから手動引用 | MD参照で自動生成 | **品質向上** |

---

## 🎯 まとめ

### 最優先で実装すべきこと
1. **`papers_database.csv`** の作成（30分）
2. **主要4論文の構造化要約**（各1時間）
3. **フォルダ構造の整備**（10分）

### AI活用の鍵
**「PDF → Markdown変換」の労力を惜しまない**
- 一度構造化すれば、AIが永続的に活用可能
- 論文執筆時の効率が劇的に向上
- 研究の再現性・引用精度が向上

---

**作成日**: 2026-02-26  
**関連**: [previous_studies_report.md](previous_studies_report.md)
