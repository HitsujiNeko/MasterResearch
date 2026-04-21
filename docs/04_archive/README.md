# 04_archive - アーカイブ

このフォルダには、参考資料や完了済みのドキュメント、先行研究の整理などを格納します。

## 📁 含まれるドキュメント

### 📚 先行研究管理（新構造）

```
04_archive/
├── README.md                           # このファイル
├── literature_management_guide.md      # 文献管理・AI活用ガイド
├── previous_studies_report.md          # 先行研究の事実整理（マスター）
│
├── 01_metadata/                        # 論文メタデータ
│   └── papers_database.csv             # 全論文の基本情報（CSV）
│
├── 02_structured_summaries/            # 構造化要約（S1-S6作成済み）
│   ├── S1_Ermida_2020.md
│   ├── S2_LeNgocHanh_2025.md
│   ├── S3_Onacillova_2022.md
│   ├── S4_Sun_2019.md
│   ├── S5_Osborne_2019.md
│   └── S6_Garzon_2021.md
│
├── 03_key_findings/                    # 重要知見の抽出（今後追加）
│   └── (テーマ別知見の統合)
│
├── 04_pdfs/                            # PDF原本（移動予定）
│   └── (論文PDFファイル)
│
└── templates/                          # テンプレート
    ├── chatgpt_instruction_paper_analysis.md
    └── structured_summary_template.md  # 論文要約テンプレート
```

### 現在のファイル
- **[previous_studies_report.md](previous_studies_report.md)**: 先行研究の事実整理（S1〜S8）
  - マスタードキュメントとして維持
  - 概要把握・一覧表示に使用

- **[literature_management_guide.md](literature_management_guide.md)**: 文献管理・AI活用ガイド
  - PDFをAIが活用するための戦略
  - 推奨ディレクトリ構造
  - ベストプラクティス

- **[01_metadata/papers_database.csv](01_metadata/papers_database.csv)**: 論文データベース
  - 全論文の基本情報（CSV形式）
  - AIによる検索・集計が可能

- **[templates/structured_summary_template.md](templates/structured_summary_template.md)**: 論文要約テンプレート
  - 新しい論文を追加する際に使用

- **[templates/chatgpt_instruction_paper_analysis.md](templates/chatgpt_instruction_paper_analysis.md)**: ChatGPT用指示書
  - ChatGPTに論文分析を依頼する際の標準プロンプト
  - 構造化要約を自動生成

- **[02_structured_summaries/](02_structured_summaries/)**: 既存の構造化要約
  - `S1_Ermida_2020.md` から `S6_Garzon_2021.md` までを保存
  - `previous_studies_report.md` の根拠資料として利用
  - 詳細比較、引用候補抽出、RQ別整理に使用

### 今後追加予定のファイル
- `02_structured_summaries/`: 未作成論文の詳細要約
  - `S7_Zhong_2024.md`
  - `S8_Tanoori_2024.md`
  - 新規追加論文（S9以降）
- `03_key_findings/`: テーマ別知見の統合
  - `urban_parameters_catalog.md`（都市構造パラメータ一覧）
  - `lst_methods_comparison.md`（LST算出手法の比較）
  - `machine_learning_approaches.md`（機械学習手法の整理）
- `old_versions/`: 過去のバージョンのドキュメント
- `supplementary_materials/`: 補足資料
- `meeting_notes/`: ミーティング記録

## 🎯 このフォルダの目的

研究の背景資料や参考文献を整理し、**AIが効果的に活用できる形式**で管理する：
- 先行研究の整理（事実ベース）
- 論文メタデータのデータベース化
- 重要知見の構造化
- PDFをMarkdownに変換して再利用性向上

## 📚 先行研究整理の活用

### 3層構造による情報管理

| 層 | ファイル | 目的 | AI活用 |
|----|---------|------|--------|
| **概要層** | `previous_studies_report.md` | 事実整理、一覧表示 | 全体把握 |
| **メタ層** | `01_metadata/papers_database.csv` | 検索・フィルタリング | データ分析 |
| **詳細層** | `02_structured_summaries/*.md` | 個別論文の深掘り | 引用・参照 |
| **統合層** | `03_key_findings/*.md` | テーマ別知見の統合 | 横断比較 |

### AIとの対話例

#### 例1: 論文の統合（ChatGPT → GitHub Copilot連携）
```
【ChatGPT】
「templates/chatgpt_instruction_paper_analysis.md の指示に従って、
 添付したPDFを分析してください」

↓ 構造化要約が生成される

【GitHub Copilot】
「S9_Zhang_2023.md を papers_database.csv と 
 previous_studies_report.md に統合してください」
```

#### 例2: 論文検索
```
「papers_database.csvから、機械学習を使用している論文を抽出」
```

#### 例3: 横断比較
```
「S1とS4のLST算出手法を比較して表にまとめて」
```

#### 例4: 引用文作成
```
「S1〜S3の情報から、SMW法の利点を説明する段落を論文用に作成」
```

---

## 🔬 先行研究調査のツール使い分け

### フェーズ1: 論文検索（ChatGPT + ScholarGPT）
**使用ツール**: ChatGPT（ScholarGPT機能）、Google Scholar

**実施内容**:
```
ChatGPTに質問：
「Land Surface Temperature and urban structure relationship in 
 Southeast Asian cities」で2019年以降の主要論文を10本教えて
```

**成果物**: 論文リスト（DOI、引用数、概要付き）

### フェーズ2: 論文分析（ChatGPT）
**使用ツール**: ChatGPT + [chatgpt_instruction_paper_analysis.md](templates/chatgpt_instruction_paper_analysis.md)

**実施内容**:
- PDFを添付または論文情報を入力
- 構造化要約を自動生成

**成果物**: Markdown形式の構造化要約

### フェーズ3: プロジェクト統合（GitHub Copilot）
**使用ツール**: GitHub Copilot（VS Code内）

**実施内容**:
```
「S9の構造化要約をデータベースに統合してください」
```

**成果物**: 
- 更新された papers_database.csv
- 更新された previous_studies_report.md

### フェーズ4: 分析・考察（GitHub Copilot）
**使用ツール**: GitHub Copilot

**実施内容**:
```
「RQ1に関連する論文（S1, S4, S8）の都市構造パラメータを
 比較表にまとめてください」
```

**成果物**: 比較表、考察文

---

## 💡 ベストプラクティス

### 【推奨】ChatGPT → GitHub Copilot 連携ワークフロー

> **最も効率的な方法**: ChatGPTで論文分析 → GitHub Copilotでプロジェクト統合

#### ステップ1: ChatGPTで論文分析（5-10分）

1. **ChatGPT（修士研究プロジェクト）を開く**
2. **指示書をコピー**
   - [templates/chatgpt_instruction_paper_analysis.md](templates/chatgpt_instruction_paper_analysis.md) の「ChatGPTへの指示」セクション全体をコピー
3. **ChatGPTにペースト**
4. **論文情報を追加**
   ```
   【論文情報】
   - タイトル: Machine learning approach for urban heat mapping
   - 著者: Zhang et al.
   - 年: 2023
   - DOI: https://doi.org/10.1016/j.uclim.2023.101423
   
   （またはPDFを添付）
   ```
5. **ChatGPTが構造化要約を生成** → コピー

#### ステップ2: VS CodeでMarkdownファイル保存（1分）

1. **新規ファイル作成**
   ```
   docs/04_archive/02_structured_summaries/S9_Zhang_2023.md
   ```
2. **ChatGPTの出力をペースト** → 保存

#### ステップ3: GitHub Copilotで統合（2分）

VS Codeで以下を依頼：
```
「S9_Zhang_2023.md の内容を papers_database.csv に追加し、
 previous_studies_report.md のS9セクションを作成してください」
```

**完了！** 論文1本あたり **合計10分** で統合完了

---

### 【従来方法】手動で論文を追加する場合

1. **メタデータを追加**
   ```
   01_metadata/papers_database.csv に1行追加
   ```

2. **構造化要約を作成**
   ```
   templates/structured_summary_template.md をコピー
   → 02_structured_summaries/S[番号]_[著者]_[年].md として保存
   → PDFを読んで情報を記入（30-60分）
   ```

3. **PDFファイルを整理**（あれば）
   ```
   04_pdfs/S[番号]_[著者]_[年].pdf としてリネーム
   ```

### 新しい論文を追加する場合

1. **メタデータを追加**
   ```
   01_metadata/papers_database.csv に1行追加
   ```

2. **構造化要約を作成**
   ```
   templates/structured_summary_template.md をコピー
   → 02_structured_summaries/S[番号]_[著者]_[年].md として保存
   → PDFを読んで情報を記入
   ```

3. **PDFファイルを整理**（あれば）
   ```
   04_pdfs/S[番号]_[著者]_[年].pdf としてリネーム
   ```

### 既存の論文を深掘りする場合

1. **テンプレートをコピー**
   ```
   cp templates/structured_summary_template.md 02_structured_summaries/S1_ermida_2020.md
   ```

2. **PDFまたはWebから情報を抽出**
   - 研究目的、手法、結果などを記入
   - 本研究との関連性を明記

3. **AIに活用させる**
   ```
   「S1_ermida_2020.mdを参照して、SMW法の実装手順を説明」
   ```

## 💡 ベストプラクティス

### PDF vs Markdown
- ❌ **PDF**: AIが直接読めない
- ✅ **Markdown**: AIが確実に参照可能
- **推奨**: 重要な論文はMarkdown要約を作成

### Web論文の扱い
- URLがあってもAIが常にアクセスできるとは限らない
- **推奨**: 手動で要約を作成し、Markdown化

### 情報の粒度
1. **1行要約**: CSV（`papers_database.csv`）
2. **5分で分かる要約**: Markdown（`02_structured_summaries/`）
3. **詳細**: PDF原本

---

## 📊 関連ドキュメント

- **文献管理ガイド**: [literature_management_guide.md](literature_management_guide.md)
- **研究計画**: [../01_planning/research_guide.md](../01_planning/research_guide.md)
- **PDF原本**: `../../既往研究PDF/`（移動予定）

---

**最終更新**: 2026-04-21
