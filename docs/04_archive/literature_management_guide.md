# 先行研究管理・活用ガイド

**最終更新**: 2026-07-22  
**関連ドキュメント**: [structured_summary_template.md](templates/structured_summary_template.md), [previous_studies_report.md](previous_studies_report.md), [claude_project_instructions.md](claude_project_instructions.md)

> **このファイルの役割**  
> 実装済みの3層構造による文献データベースの思想と、Claude Code を中心とした文献調査フローの運用ガイド。個別の登録手順は `/add-paper`・`/paper-scout` スキルが正本であり、本ガイドは全体像と役割分担を示す。

## 📋 現状

### 文献データベースの資産

- `docs/04_archive/previous_studies_report.md`: 事実整理のマスター（S1〜S8）
- `docs/04_archive/01_metadata/papers_database.csv`: 全論文の基本情報（検索・フィルタリング用）
- `docs/04_archive/02_structured_summaries/`: 個別論文の構造化要約（S1〜S8）
- `docs/04_archive/04_pdfs/`: 元の PDF ファイル（S1〜S8、`S{番号}_{著者}_{年}.pdf`）

### 前提

Claude Code は PDF を `Read` で直接読み取れる。したがって「PDF を人手で Markdown 化しないと AI が参照できない」という制約は存在しない。構造化要約は、AI が読めるようにするためではなく、**論文の要点を横断検索・比較・引用しやすい形で残す**ために作成する。

---

## 🗂️ 3層構造の思想

情報の粒度を3層に分け、目的に応じて参照先を使い分ける。

| 層 | 実体 | 粒度 | 主な用途 |
|----|------|------|----------|
| **メタデータ** | `01_metadata/papers_database.csv` | 1行で概要 | 「RQ1 関連の重要度 A を抽出」等の検索・集計 |
| **構造化要約** | `02_structured_summaries/S*.md` | 5分で全体像 | 個別論文の深掘り、要点・引用候補の確認 |
| **PDF（原典）** | `04_pdfs/S*.pdf` | 全文 | 一次確認、数値・図表の精読（Claude Code が直接 Read） |

`previous_studies_report.md` は概要把握・一覧のマスターとして維持し、`02_structured_summaries/` が個別論文の詳細を担う。

### 命名規則

- **論文 ID**: `S1`, `S2`…（既存に準拠）
- **ファイル名**: `S{番号}_{筆頭著者姓}_{出版年}`（例: `S1_Ermida_2020`）
- **フォルダ**: `01_`, `02_`, `04_`（順序を明示）

> **補足**: `03_key_findings/`（テーマ別に複数論文の知見を横断整理する層）は未実装。NDVI・建物被覆率などパラメータ横断の比較整理が必要になった段階で任意に追加する拡張であり、現時点では既定の層ではない。

---

## 🔄 文献調査フロー（Claude Code 中心）

論文の探索から登録までは Claude Code 上で完結する。claude.ai の役割は壁打ち・アイデア出しに限定する。

```text
1. 探索      /paper-scout … 登録済み論文の引用関係から未登録候補を提示
2. 精読      PDF を Claude Code に渡し Read で直接読む
3. 登録      /add-paper  … Crossref 書誌照合 → S番号採番 → 要約作成 → CSV追記 → previous_studies_report.md・README更新
```

### 各ステップ

1. **探索（`/paper-scout`）**: `papers_database.csv` の起点論文から OpenAlex で前方・後方引用をたどり、RQ キーワードでスコアリングした候補リストを得る。採否・精読・登録は研究者が判断する。
2. **精読**: 入手した PDF を `04_pdfs/` に置くか直接 Claude Code に渡し、`Read` で全文を読む。要約の作成は Claude Code が [structured_summary_template.md](templates/structured_summary_template.md) に沿って行う。
3. **登録（`/add-paper`）**: S番号採番の前に Crossref で書誌を機械照合し、転記誤りを防ぐ。要約ファイル作成・`papers_database.csv` 追記・`previous_studies_report.md`（先行研究一覧）・README 更新・コミット案提示までを一体実行する（詳細は `/add-paper` スキルが正本）。

### claude.ai の位置づけ

claude.ai（Claude Projects）は、新しい論文の知見が RQ・説明変数設計・手法選定に与える影響を整理する**壁打ち**に用いる。要点を渡して要約を整形させるような使い方は、Crossref 照合工程を通らず誤情報が混入しうるため行わない。要約の生成・登録は必ず上記フロー（Claude Code が PDF を読む＋Crossref 照合）を経る。セットアップは [claude_project_instructions.md](claude_project_instructions.md) を参照。

---

## 🤖 効果的な AI 対話例

構造化された資産を指定すると、横断的な照会に即答できる。

- **横断比較**: 「`02_structured_summaries/` を参照して、建物被覆率を使用している研究とその算出方法を一覧化して」
- **RQ 関連の抽出**: 「`papers_database.csv` から RQ1 に関連する重要度 A の研究を抽出し、手法を比較表にして」
- **引用文の作成**: 「S1〜S3 の情報から、SMW 法の利点を説明する段落を論文用に作成して」
- **原典の確認**: 「`04_pdfs/S1_Ermida_2020.pdf` を読んで、係数 A・B・C の一覧（Table 2）を転記して」

### Web 論文の扱い

URL のみで PDF が手元にない論文は、アクセス制限・ペイウォール・サイト構造変更により安定的に参照できないことがある。可能な限り PDF を入手して `04_pdfs/` に置き、原典から要約・引用する。

---

## 💡 ベストプラクティス

1. **粒度の使い分け**: 概要は CSV、全体像は構造化要約、精読は PDF。目的に応じて最小限の層を参照する。
2. **重複を作らない**: 要約テンプレートの正本は [structured_summary_template.md](templates/structured_summary_template.md)。本ガイドや個別ファイルにテンプレート全文を再掲しない。
3. **照合を省かない**: 書誌・数値は Crossref 照合と原典（PDF）で裏取りし、推測で数値を埋めない。読み取れない値は「未確認」と明記する。
4. **単位・言語**: LST は必ず摂氏（°C）。論文タイトル・著者名は原語のまま扱う。
