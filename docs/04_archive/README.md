# 04_archive - アーカイブ

**最終更新**: 2026-07-07

このフォルダには、参考資料や完了済みのドキュメント、先行研究の整理などを格納します。

## 📁 含まれるドキュメント

### 📚 先行研究管理（新構造）

```text
04_archive/
├── README.md                           # このファイル
├── literature_management_guide.md      # 文献管理・AI活用ガイド
├── previous_studies_report.md          # 先行研究の事実整理（マスター）
├── claude_project_instructions.md      # Claude Projects プロジェクト指示（コピペ用）
├── claude_project_knowledge.md         # Claude Projects ナレッジ（アップロード用）
│
├── 01_metadata/                        # 論文メタデータ
│   └── papers_database.csv             # 全論文の基本情報（CSV）
│
├── 02_structured_summaries/            # 構造化要約（S1-S8作成済み）
│   ├── S1_Ermida_2020.md
│   ├── S2_LeNgocHanh_2025.md
│   ├── S3_Onacillova_2022.md
│   ├── S4_Sun_2019.md
│   ├── S5_Osborne_2019.md
│   ├── S6_Garzon_2021.md
│   ├── S7_Derdouri_2021.md
│   └── S8_Lin_2024.md
│
├── 03_key_findings/                    # 重要知見の抽出（今後追加）
│   └── (テーマ別知見の統合)
│
├── 04_pdfs/                            # PDF原本（移動予定）
│   └── (論文PDFファイル)
│
└── templates/                          # テンプレート
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

- **[claude_project_instructions.md](claude_project_instructions.md)**: Claude Projects プロジェクト指示
  - claude.ai の文献調査用プロジェクトの「プロジェクト指示」欄にコピペする
  - リポジトリ側を正本として管理

- **[claude_project_knowledge.md](claude_project_knowledge.md)**: Claude Projects ナレッジ
  - claude.ai のプロジェクトナレッジにアップロードして常時参照させる
  - 研究概要・RQ・用語集・先行研究サマリー・分析の現在地を凝縮

- **[01_metadata/papers_database.csv](01_metadata/papers_database.csv)**: 論文データベース
  - 全論文の基本情報（CSV形式）
  - AIによる検索・集計が可能

- **[templates/structured_summary_template.md](templates/structured_summary_template.md)**: 論文要約テンプレート
  - 新しい論文を追加する際に使用

- **[02_structured_summaries/](02_structured_summaries/)**: 既存の構造化要約
  - `S1_Ermida_2020.md` から `S8_Lin_2024.md` までを保存
  - `previous_studies_report.md` の根拠資料として利用
  - 詳細比較、引用候補抽出、RQ別整理に使用

### 今後追加予定のファイル

- `02_structured_summaries/`: 未作成論文の詳細要約
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

#### 例1: 論文の統合（claude.ai → Claude Code 連携）

```text
【claude.ai（Claude Projects）】
「添付したPDFを分析して、構造化要約を作成してください」

↓ プロジェクト指示・ナレッジに従い構造化要約が生成される

【Claude Code】
「/add-paper」を実行し、生成された要約をペースト

↓ S番号採番・ファイル作成・CSV追記・README更新・コミットまで自動
```

#### 例2: 論文検索

```text
「papers_database.csvから、機械学習を使用している論文を抽出」
```

#### 例3: 横断比較

```text
「S1とS4のLST算出手法を比較して表にまとめて」
```

#### 例4: 引用文作成

```text
「S1〜S3の情報から、SMW法の利点を説明する段落を論文用に作成」
```

---

## 🔬 先行研究調査のツール使い分け

### フェーズ1: 論文検索（claude.ai）

**使用ツール**: claude.ai（Claude Projects + Web検索）、Google Scholar

**実施内容**:

```text
claude.aiに質問：
「Land Surface Temperature and urban structure relationship in
 Southeast Asian cities」で2019年以降の主要論文を10本教えて
```

**成果物**: 論文リスト（DOI、概要、RQ関連度付き）

### フェーズ2: 論文分析（claude.ai）

**使用ツール**: claude.ai（Claude Projects）

- プロジェクト指示: [claude_project_instructions.md](claude_project_instructions.md) をコピペ済みであること
- ナレッジ: [claude_project_knowledge.md](claude_project_knowledge.md) をアップロード済みであること

**実施内容**:

- PDFを添付または論文情報を入力し、構造化要約を生成させる

**成果物**: Markdown形式の構造化要約

### フェーズ3: プロジェクト統合（Claude Code）

**使用ツール**: Claude Code の `/add-paper` スキル

**実施内容**:

```text
/add-paper を実行し、claude.aiが生成した構造化要約をペースト
```

**成果物**:

- `02_structured_summaries/S{番号}_{著者}_{年}.md`
- 更新された papers_database.csv
- 更新された docs/README.md・04_archive/README.md

### フェーズ4: 分析・考察（Claude Code）

**使用ツール**: Claude Code

**実施内容**:

```text
「RQ1に関連する論文（S1, S4, S8）の都市構造パラメータを
 比較表にまとめてください」
```

**成果物**: 比較表、考察文

---

## 💡 ベストプラクティス

### 【推奨】claude.ai → Claude Code 連携ワークフロー

> **最も効率的な方法**: claude.aiで論文分析 → Claude Code `/add-paper` でプロジェクト統合

#### ステップ1: claude.aiで論文分析（5-10分）

1. **claude.ai の文献調査用プロジェクトを開く**（初回セットアップは [claude_project_instructions.md](claude_project_instructions.md) を参照）
2. **論文PDFを添付**、または論文情報を入力

   ```text
   【論文情報】
   - タイトル: Machine learning approach for urban heat mapping
   - 著者: Zhang et al.
   - 年: 2023
   - DOI: https://doi.org/10.1016/j.uclim.2023.101423
   ```

3. **claude.aiが構造化要約を生成** → コピー

#### ステップ2: Claude Codeで統合（2分）

1. Claude Code で `/add-paper` を実行
2. 構造化要約をペースト
3. S番号採番・ファイル作成・CSV追記・README更新・コミットまで自動実行される（ファクトチェックあり）

**完了！** 論文1本あたり **合計10分程度** で統合完了

---

### 【従来方法】手動で論文を追加する場合

1. **メタデータを追加**

   ```text
   01_metadata/papers_database.csv に1行追加
   ```

2. **構造化要約を作成**

   ```text
   templates/structured_summary_template.md をコピー
   → 02_structured_summaries/S[番号]_[著者]_[年].md として保存
   → PDFを読んで情報を記入（30-60分）
   ```

3. **PDFファイルを整理**（あれば）

   ```text
   04_pdfs/S[番号]_[著者]_[年].pdf としてリネーム
   ```

### 既存の論文を深掘りする場合

1. **テンプレートをコピー**

   ```bash
   cp templates/structured_summary_template.md 02_structured_summaries/S1_ermida_2020.md
   ```

2. **PDFまたはWebから情報を抽出**
   - 研究目的、手法、結果などを記入
   - 本研究との関連性を明記

3. **AIに活用させる**

   ```text
   「S1_ermida_2020.mdを参照して、SMW法の実装手順を説明」
   ```

## 💡 ベストプラクティス（情報管理）

### PDF vs Markdown

- ❌ **PDF**: AIが直接読めない（Claude CodeはReadツールで読めるが、毎回のコンテキスト消費が大きい）
- ✅ **Markdown**: AIが確実かつ低コストに参照可能
- **推奨**: 重要な論文はMarkdown要約を作成

### Web論文の扱い

- URLがあってもAIが常にアクセスできるとは限らない
- **推奨**: 構造化要約を作成し、Markdown化

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

**最終更新**: 2026-07-07
