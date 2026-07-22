# 04_archive - アーカイブ

**最終更新**: 2026-07-22

このフォルダには、参考資料や完了済みのドキュメント、先行研究の整理などを格納します。文献管理の思想・運用フローの詳細は [literature_management_guide.md](literature_management_guide.md) を正本とし、本 README はフォルダ構成の案内に徹する。

## 📁 フォルダ構成

```text
04_archive/
├── README.md                           # このファイル
├── literature_management_guide.md      # 文献管理・活用ガイド（思想・フローの正本）
├── previous_studies_report.md          # 先行研究の事実整理（S1〜S8、マスター）
├── claude_project_instructions.md      # Claude Projects プロジェクト指示（コピペ用）
├── claude_project_knowledge.md         # Claude Projects ナレッジ（アップロード用）
│
├── 01_metadata/
│   └── papers_database.csv             # 全論文の基本情報（CSV）
│
├── 02_structured_summaries/            # 構造化要約（S1〜S8）
│   ├── S1_Ermida_2020.md
│   ├── S2_LeNgocHanh_2025.md
│   ├── S3_Onacillova_2022.md
│   ├── S4_Sun_2019.md
│   ├── S5_Osborne_2019.md
│   ├── S6_Garzon_2021.md
│   ├── S7_Derdouri_2021.md
│   └── S8_Lin_2024.md
│
├── 04_pdfs/                            # PDF原本（S1〜S8）
│   └── S{番号}_{著者}_{年}.pdf
│
└── templates/
    └── structured_summary_template.md  # 論文要約テンプレート（正本）
```

> **補足**: `03_key_findings/`（テーマ別に複数論文の知見を横断整理する層）は未実装。必要になった段階で任意に追加する拡張であり、現時点では存在しない。

## 📄 ファイル一覧

| ファイル | 役割 |
|----------|------|
| [previous_studies_report.md](previous_studies_report.md) | 先行研究の事実整理（S1〜S8）。概要把握・一覧のマスター |
| [literature_management_guide.md](literature_management_guide.md) | 3層構造の思想と Claude Code 中心の文献調査フロー |
| [claude_project_instructions.md](claude_project_instructions.md) | claude.ai 文献調査用プロジェクトの「プロジェクト指示」欄にコピペする指示文（正本） |
| [claude_project_knowledge.md](claude_project_knowledge.md) | claude.ai プロジェクトナレッジにアップロードする凝縮版（研究概要・RQ・先行研究サマリー） |
| [01_metadata/papers_database.csv](01_metadata/papers_database.csv) | 全論文の基本情報（検索・集計用） |
| [02_structured_summaries/](02_structured_summaries/) | 個別論文の構造化要約（S1〜S8）。詳細比較・引用候補抽出に使用 |
| [04_pdfs/](04_pdfs/) | 論文 PDF 原本（S1〜S8）。Claude Code が `Read` で直接精読 |
| [templates/structured_summary_template.md](templates/structured_summary_template.md) | 構造化要約の標準フォーマット（正本） |

## 🎯 このフォルダの目的

研究の背景資料・先行研究を、AI が横断検索・比較・引用しやすい形で整理する。

- 先行研究の事実整理（`previous_studies_report.md`）
- 論文メタデータのデータベース化（`01_metadata/`）
- 個別論文の構造化要約（`02_structured_summaries/`）と PDF 原典（`04_pdfs/`）

## 🔄 文献の追加・活用

論文の探索から登録までは Claude Code 上で完結する（`/paper-scout` → PDF を直接 `Read` → `/add-paper`）。claude.ai の役割は壁打ち・探索補助に限定する。手順とAI対話例は [literature_management_guide.md](literature_management_guide.md) を参照。

## 📊 関連ドキュメント

- **文献管理・活用ガイド**: [literature_management_guide.md](literature_management_guide.md)
- **研究計画**: [../01_planning/research_guide.md](../01_planning/research_guide.md)

---

**最終更新**: 2026-07-22
