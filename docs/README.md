# 📚 研究ドキュメント管理

**最終更新**: 2026-07-28  
**管理方針**: Single Source of Truth - docs配下のファイル一覧は本README「全ドキュメントカタログ」に一本化する（変更の経緯は `git log --follow docs/README.md` で確認）

> **このドキュメントの役割**  
> 本ディレクトリ内のすべてのドキュメントを一元管理する**唯一の真実の情報源（Single Source of Truth）**です。  
> 新しいファイルの追加や構造変更時は、このREADMEのみを更新してください。

本ディレクトリは、修士研究に関するすべてのドキュメントを研究フェーズ別に整理しています。

---

## 🗂️ ディレクトリ構造

フォルダ構成のみを示す。各フォルダ内のファイル一覧は「[全ドキュメントカタログ](#-全ドキュメントカタログ)」を正本とする。

```text
docs/
├── README.md                     # 📌 このファイル（全体索引）
├── setup.md                      # 🛠️ 環境構築ガイド
├── setup/                        # 🛠️ 個別ツールのセットアップガイド
├── 01_planning/                  # 📋 研究計画（RQ定義・GISデータ調査）
│   └── gis_data/                 # カテゴリ別GISデータ詳細
├── 02_methods/                   # 🔬 研究手法（仕様書・規約・運用ガイド）
├── 03_results/                   # 📊 研究結果（分析結果・学会原稿）
└── 04_archive/                   # 📦 アーカイブ・先行研究（文献管理）
    ├── 01_metadata/              # 論文メタデータ（CSV）
    ├── 02_structured_summaries/  # 論文の構造化要約
    ├── 04_pdfs/                  # 論文PDF原本（Git管理外）
    └── templates/                # 論文要約テンプレート
```

---

## 📊 全ドキュメントカタログ

> 今後追加予定のドキュメントは GitHub Issues（タスク管理の正本）で管理し、本カタログには現存ファイルのみを掲載する。

### 🛠️ ルート

| ファイル名 | 概要 | 主要な内容 | 更新契機 |
|-----------|------|-----------|--------|
| [README.md](README.md) | docs全体の索引 | ドキュメント構造、管理ルール、関連リンク | docs配下の重要ファイル追加・改名時 |
| [setup.md](setup.md) | 環境構築ガイド | `environment.yml` を正本としたセットアップ手順、依存確認、GitHub CLI セットアップ、実行例、Claude Code on the web 向けリモートセッション依存導入 | 依存関係・実行手順・ツール要件の変更時 |

### 🛠️ setup - 個別ツールのセットアップガイド

| ファイル名 | 概要 | 主要な内容 | 関連ファイル |
|-----------|------|-----------|------------|
| [qgis_mcp_setup.md](setup/qgis_mcp_setup.md) | QGIS MCP セットアップガイド | nkarasiak/qgis-mcp の導入手順、接続設定、トラブルシューティング | `.mcp.json` |

### 📋 01_planning - 研究計画

| ファイル名 | 概要 | 主要な内容 | 関連RQ |
|-----------|------|-----------|--------|
| [available_gis_data.md](01_planning/available_gis_data.md) | 公開GISデータ候補の整理（インデックス） | 評価観点、採用データ一覧、結論の要点、カテゴリ別ドキュメントへのリンク | 全RQ |
| [research_guide.md](01_planning/research_guide.md) | 研究計画書 | 研究題目、背景、RQ1-3、手法概要、期待される成果 | 全RQ |

> **注記**: `gis_data/` 配下の各カテゴリ詳細ファイルは [available_gis_data.md](01_planning/available_gis_data.md) Section 4 を索引の正本とし、本表には掲載しない（check-docs-consistency のカタログ比較対象外）。

### 🔬 02_methods - 研究手法

| ファイル名 | 概要 | 主要な内容 | 実装ファイル |
|-----------|------|-----------|------------|
| [analysis_workflow.md](02_methods/analysis_workflow.md) | 分析ワークフロー仕様書 | 前処理→都市構造パラメータ算出→モデル構築→評価の全工程定義、RQ別分析設計 | `src/` 全スクリプト |
| [analysis_rq3_satellite_only_guide.md](02_methods/analysis_rq3_satellite_only_guide.md) | RQ3衛星のみ分析コード解説 | 初心者向けに処理フロー、評価指標、Spatial CV、SHAPの読み方を整理 | `src/analysis/analysis_rq3_satellite_only.py` |
| [calc_urban_params_guide.md](02_methods/calc_urban_params_guide.md) | `urban_params` パッケージ 設計ガイド | 解析範囲設計、マルチスケールUTMグリッド化、3シナリオ・GIS/衛星指標統合、品質管理列の仕様 | `src/analysis/urban_params/` |
| [gee_calc_satellite_indices.md](02_methods/gee_calc_satellite_indices.md) | 衛星指標算出仕様書 | NDVI/NDBI/NDWI算出式、QAマスク、スケーリング、統計出力の仕様と根拠 | `src/gee/gee_calc_satellite_indices.py` |
| [data_management_guide.md](02_methods/data_management_guide.md) | データ管理ガイド | 2層運用（Git + Google Drive）、.gitignore方針、再現性確保手順 | `data/`, `.gitignore` |
| [calc_LST_report.md](02_methods/calc_LST_report.md) | LST算出レポート | SMW法の選定理由、処理結果、品質評価 | `src/gee/gee_calc_LST.py` |
| [gee_calc_LST.md](02_methods/gee_calc_LST.md) | LST算出仕様書 | gee_calc_LST.pyの詳細仕様、入出力定義 | `src/gee/gee_calc_LST.py` |
| [skill_operation_rules.md](02_methods/skill_operation_rules.md) | スキル運用ルール | 作成・変更の承認ルール（行為ベース）、`shared/` 共通リファレンス運用、プロジェクト固有ルール | `.claude/skills/` |
| [qgis_mcp_usage_guide.md](02_methods/qgis_mcp_usage_guide.md) | QGIS MCP活用ガイド | データ確認・レイヤー操作・スタイル適用・Map Theme切り替え・Processing実行のユースケース別操作例、CRS確認手順（rasterio/GeoPandas側で判定） | `qgis/` |
| [qgis_operation_guidelines.md](02_methods/qgis_operation_guidelines.md) | QGIS運用ガイドライン | QGIS-MCPの既知の制約と回避策の台帳（対象ツール／症状／回避策／最小再現手順／確認バージョン）・新規機能の採否記録・バージョン追随ポリシーと更新チェックリスト、レイヤー命名規則、CRS統一方針、保存先ルール、ラスター疑似カラースタイル作成時の注意（classificationMin/Max・マルチバンドのband）、大規模レイヤーのクラッシュ条件の切り分け、スクリーンショットの構図・命名規則、カテゴリ値ラスタの配色確認順序、execute_code/Processing実行時の注意、Python×QGISネイティブのクロスチェック手順、検証時のプロジェクト衛生 | `qgis/` |
| [claude_workflow_regression_tests.md](02_methods/claude_workflow_regression_tests.md) | Claude Code運用ルール回帰テスト項目書 | deny発火・カスタムコマンド・承認ゲート・セッション不変条件・スキル回帰の5観点のテスト項目書（正本・再利用）と実施結果記録 | `.claude/settings.json`, `.claude/commands/`, `.claude/skills/shared/` |
| [CodingRule.md](02_methods/CodingRule.md) | コーディング規約 | PEP 8準拠（ruffで自動チェック）、型ヒント、docstring規則、命名規則、再現性確保 | 全Pythonスクリプト |

### 📊 03_results - 研究結果

| ファイル名 | 概要 | 主要な内容 | 自動生成元 |
|-----------|------|-----------|-----------|
| [GIS_IDEAS_abstract.md](03_results/GIS_IDEAS_abstract.md) | GIS-IDEAS学会用アブストラクト下書き | RQ3 Satellite Only の本文案、図表案、表現上の注意点 | `docs/03_results/`, `data/output/satellite_only/`, `src/analysis/` |
| [survey_gis_data_preparation_status.md](03_results/survey_gis_data_preparation_status.md) | 測量由来GISデータ整備状況レポート | 測量由来GISの整備、内容確認、Full シナリオ接続条件 | `src/analysis/analyze_data_status.py`, `src/preprocessing/*` |
| [fig2_satellite_only_workflow.mmd](03_results/fig2_satellite_only_workflow.mmd) | RQ3図表用Mermaid図 | Satellite Only 分析フローを図2向けに整理した構成図 | `docs/03_results/`, `src/analysis/` |
| [satellite_only_analysis_results.md](03_results/satellite_only_analysis_results.md) | Satellite Only 分析結果 | 3観測日のベースライン、Spatial CV、SHAP、今後の比較方針 | `src/analysis/build_satellite_only_dataset.py`, `src/analysis/analysis_rq3_satellite_only.py` |

### 📦 04_archive - アーカイブ・先行研究

| ファイル名 | 概要 | 主要な内容 | 活用場面 |
|-----------|------|-----------|---------|
| [README.md](04_archive/README.md) | 04_archiveフォルダ案内 | フォルダ構成・ファイル一覧（詳細は literature_management_guide.md が正本） | フォルダ構成の確認時 |
| [literature_management_guide.md](04_archive/literature_management_guide.md) | 文献管理・活用ガイド | 3層構造の思想、Claude Code中心の文献調査フロー | 文献調査・論文追加時 |
| [previous_studies_report.md](04_archive/previous_studies_report.md) | 先行研究整理 | S1-S8の事実整理、手法・データ・結論 | 論文執筆、手法比較 |
| [01_metadata/papers_database.csv](04_archive/01_metadata/papers_database.csv) | 論文メタデータ | 8論文のCSVデータベース（著者、年、RQ関連度） | AI検索、フィルタリング |
| [claude_project_instructions.md](04_archive/claude_project_instructions.md) | Claude Projects プロジェクト指示 | claude.ai の文献調査用プロジェクトにコピペする指示文（正本） | Claude Projects セットアップ・指示変更時 |
| [claude_project_knowledge.md](04_archive/claude_project_knowledge.md) | Claude Projects ナレッジ | 研究概要・RQ・先行研究サマリー・分析の現在地の凝縮版 | 論文追加・分析進捗時に差し替え |
| [templates/structured_summary_template.md](04_archive/templates/structured_summary_template.md) | 論文要約テンプレート | 新規論文追加時の標準フォーマット | 論文要約作成時 |

**先行研究一覧（S1-S8）**:

- **S1**: Ermida et al. (2020) - SMW法 [本研究採用手法]
- **S2**: Le Ngoc Hanh (2025) - ベトナム・ダナン [地域参考]
- **S3**: Onačillová (2022) - 高解像度LST
- **S4**: Sun et al. (2019) - 機械学習による都市構造評価 [RQ1参考]
- **S5**: Osborne (2019) - 景観構成・配置
- **S6**: Garzón (2021) - 熱帯都市SUHI
- **S7**: Derdouri et al. (2021) - LULC変化とSUHI研究レビュー
- **S8**: Lin et al. (2024) - UFZ別2D/3D都市形態とUHI要因分析

**構造化要約（現存ファイル）**:

- [S1_Ermida_2020.md](04_archive/02_structured_summaries/S1_Ermida_2020.md)
- [S2_LeNgocHanh_2025.md](04_archive/02_structured_summaries/S2_LeNgocHanh_2025.md)
- [S3_Onacillova_2022.md](04_archive/02_structured_summaries/S3_Onacillova_2022.md)
- [S4_Sun_2019.md](04_archive/02_structured_summaries/S4_Sun_2019.md)
- [S5_Osborne_2019.md](04_archive/02_structured_summaries/S5_Osborne_2019.md)
- [S6_Garzon_2021.md](04_archive/02_structured_summaries/S6_Garzon_2021.md)
- [S7_Derdouri_2021.md](04_archive/02_structured_summaries/S7_Derdouri_2021.md)
- [S8_Lin_2024.md](04_archive/02_structured_summaries/S8_Lin_2024.md)

---

## 🔄 ドキュメント管理のルール

### ✅ 新しいドキュメントを追加する場合

1. **適切なフェーズを選択**:
   - 📋 `01_planning/`: 研究の方向性・RQ定義
   - 🔬 `02_methods/`: 手法・ツールの詳細仕様
   - 📊 `03_results/`: 分析結果・図表
   - 📦 `04_archive/`: 参考資料・先行研究

2. **このREADME.mdを更新**:
   - 「全ドキュメントカタログ」の該当フェーズの表に行を追加する
   - 新規フォルダを作成した場合のみ「ディレクトリ構造」に追記する

3. **相互参照を設定**:
   - 新規ドキュメントの冒頭に**関連ドキュメント**セクションを追加
   - 既存ドキュメントから新規ドキュメントへのリンクを追加

4. **メタ情報を記載**:

   ```markdown
   # ドキュメントタイトル
   
   **最終更新**: 2026-02-26  
   **関連ドキュメント**: [research_guide.md], [CodingRule.md]  
   **前提知識**: RQ1-RQ3の理解
   ```

### ✅ 既存ドキュメントを更新する場合

- [ ] 冒頭の「最終更新」日付を更新
- [ ] 影響を受ける関連ドキュメントを確認
- [ ] リンク切れがないか確認

### ✅ ドキュメントを移動・削除する場合

1. **リンク切れを確認**:

   ```powershell
   # 影響範囲を確認
   grep -r "旧ファイル名" docs/
   ```

2. **影響を受けるドキュメントを更新**:
   - 相互参照しているドキュメントのリンクを修正
   - このREADME.mdのパスを更新

3. **Git履歴を保持**:

   ```bash
   git mv 旧パス 新パス
   ```

### ✅ ファイル命名規則

- **小文字とアンダースコア**: `analysis_results.md`（推奨）
- **内容が分かる名前**: ❌ `doc1.md` → ✅ `rq1_variable_importance.md`
- **日付を含める場合**: `20260226_meeting_notes.md`（YYYYMMDD形式）
- **バージョン管理**: `analysis_v1.md`より Git を使用

### ✅ 定期メンテナンス

- [ ] 週次: 全ドキュメントの整合性チェック（`/check-docs-consistency` skillを使用）
- [ ] 研究フェーズ移行時: ドキュメント構成の見直し
- [ ] 論文投稿前: 全ドキュメントの整合性確認

### ❌ 禁止事項

- **サブフォルダのREADME.md作成**: このdocs/README.mdに集約
  - 例外: `04_archive/README.md`のみ（文献管理が複雑なため）
- **重複記述**: 同じ内容を複数ファイルに記載しない（Single Source of Truth原則）
- **絶対パスの使用**: 相対パスを使用し移植性を確保

---

## 💡 文献管理ワークフロー

先行研究の追加は、Claude Code 上で完結する（探索 → 精読 → 登録）。探索の起点には `/paper-scout` スキルを用いる。登録済み文献（S番号）の引用関係を OpenAlex でたどり、RQ1-3 キーワードでスコアリングした未登録の文献候補を提示する（探索と提示まで。採否・精読・登録は研究者が判断する）。精読は原典 PDF を Claude Code に渡し `Read` で直接読む。登録は `/add-paper` スキルが Crossref 書誌照合込みで行う。claude.ai（Claude Projects）は壁打ち・探索補助に限定し、構造化要約の生成・登録には用いない。
手順・思想の詳細は [literature_management_guide.md](04_archive/literature_management_guide.md) を正本として参照する。
Claude Projects のセットアップは [claude_project_instructions.md](04_archive/claude_project_instructions.md)（プロジェクト指示）・[claude_project_knowledge.md](04_archive/claude_project_knowledge.md)（ナレッジ）を正本とする。

---

## 🔗 関連ディレクトリ

プロジェクト全体のトップレベル構成と、各ディレクトリの詳細を定義する正本ドキュメントを示す。

```text
MasterResearch/
├── .claude/        # Claude Code設定・カスタムスキル
├── .github/        # タスク管理ワークフロー・CI・Issueテンプレート
├── docs/           # 📌 このディレクトリ（研究ドキュメント）
├── src/            # Pythonスクリプト（GEE・前処理・分析・共通モジュール）
├── tests/          # pytestテスト
├── data/           # 研究データ（衛星・GIS・入出力。Git管理外を含む）
├── qgis/           # QGISワークスペース（プロジェクト・スタイル・テンプレート）
├── images/         # 視覚的記録（データ取得タスクのGISスクリーンショット等。Git追跡）
└── 整備データ/     # ベトナム測量データ（統合GeoPackage）
```

| ディレクトリ | 正本ドキュメント |
|------------|----------------|
| `.claude/skills/` | [skill_operation_rules.md](02_methods/skill_operation_rules.md) |
| `.github/`（タスク管理） | [task-workflow.md](../.github/task-workflow.md) / [parallel-workflow.md](../.github/parallel-workflow.md) |
| `src/`・`tests/` | [CodingRule.md](02_methods/CodingRule.md)・`02_methods/` の各仕様書 |
| `data/` | [data_management_guide.md](02_methods/data_management_guide.md) |
| `qgis/` | [qgis_operation_guidelines.md](02_methods/qgis_operation_guidelines.md) / [qgis_mcp_usage_guide.md](02_methods/qgis_mcp_usage_guide.md) |
| `images/` | [qgis_operation_guidelines.md](02_methods/qgis_operation_guidelines.md)（スクリーンショットの扱い・保存先・命名規則） |
| `整備データ/` | [survey_gis_data_preparation_status.md](03_results/survey_gis_data_preparation_status.md) |
