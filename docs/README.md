# 📚 研究ドキュメント管理

> **このドキュメントの役割**  
> 本ディレクトリ内のすべてのドキュメントを一元管理する**唯一の真実の情報源（Single Source of Truth）**です。  
> 新しいファイルの追加や構造変更時は、このREADMEのみを更新してください。

本ディレクトリは、修士研究に関するすべてのドキュメントを研究フェーズ別に整理しています。

---

## 🗂️ ディレクトリ構造

```
docs/
├── README.md                              # 📌 このファイル（全体ガイド）
├── setup.md                               # 🛠️ 環境構築ガイド
│
├── 01_planning/                           # 📋 研究計画フェーズ
│   ├── available_gis_data.md              # 利用可能な公開GISデータ候補の整理
│   └── research_guide.md                  # 研究計画書（RQ定義）
│
├── 02_methods/                            # 🔬 研究手法フェーズ
│   ├── analysis_workflow.md               # 分析ワークフロー仕様書（前処理→モデル→評価の全工程）
│   ├── agency_agents_minimal_set.md       # 研究専用エージェント最小セット運用ガイド
│   ├── analysis_rq3_satellite_only_guide.md # analysis_rq3_satellite_only.py 初心者向け解説
│   ├── calc_urban_params_guide.md         # calc_urban_params.py 詳細解説（Phase 2実装読解）
│   ├── gee_calc_satellite_indices.md      # 衛星指標算出仕様書（NDVI/NDBI/NDWI）
│   ├── data_management_guide.md           # データ管理方針（Git/LFS/DVC運用）
│   ├── calc_LST_report.md                 # LST算出レポート
│   ├── gee_calc_LST.md                    # LST算出仕様書
│   └── CodingRule.md                      # Pythonコーディング規約
│
├── 03_results/                            # 📊 研究結果フェーズ
│   ├── conference_abstract_rq3_satellite_only_draft.md # 学会用アブストラクト下書き
│   ├── data_preparation_status.md         # データ整備状況レポート
│   └── satellite_only_20230707_initial_run.md # Satellite Only 初期実行結果
│
└── 04_archive/                            # 📦 アーカイブ
    ├── README.md                          # 文献管理システムガイド
    ├── literature_management_guide.md     # 文献管理・AI活用ガイド
    ├── previous_studies_report.md         # 先行研究整理（S1-S8）
    ├── 01_metadata/
    │   └── papers_database.csv            # 論文メタデータ（CSV）
    └── templates/
        └── structured_summary_template.md # 論文要約テンプレート
```

---

## 📊 全ドキュメントカタログ

### 🛠️ ルート

| ファイル名 | 概要 | 主要な内容 | 更新契機 |
|-----------|------|-----------|--------|
| [README.md](README.md) | docs全体の索引 | ドキュメント構造、管理ルール、関連リンク | docs配下の重要ファイル追加・改名時 |
| [setup.md](setup.md) | 環境構築ガイド | `environment.yml` を正本としたセットアップ手順、依存確認、実行例 | 依存関係や実行手順の変更時 |

### 📋 01_planning - 研究計画

| ファイル名 | 概要 | 主要な内容 | 関連RQ |
|-----------|------|-----------|--------|
| [available_gis_data.md](01_planning/available_gis_data.md) | 公開GISデータ候補の整理 | 道路・建物・粗い built-up データの候補、更新性、適合性 | 全RQ |
| [research_guide.md](01_planning/research_guide.md) | 研究計画書 | 研究題目、背景、RQ1-3、手法概要、期待される成果 | 全RQ |

### 🔬 02_methods - 研究手法

| ファイル名 | 概要 | 主要な内容 | 実装ファイル |
|-----------|------|-----------|------------|
| [analysis_workflow.md](02_methods/analysis_workflow.md) | 分析ワークフロー仕様書 | 前処理→都市構造パラメータ算出→モデル構築→評価の全工程定義、RQ別分析設計 | `src/` 全スクリプト |
| [agency_agents_minimal_set.md](02_methods/agency_agents_minimal_set.md) | 研究専用エージェント最小セット運用ガイド | 選抜6エージェント、固有文脈テンプレート、工程別呼び出し順、品質チェック表 | `agency-agents/`, `docs/` |
| [analysis_rq3_satellite_only_guide.md](02_methods/analysis_rq3_satellite_only_guide.md) | RQ3衛星のみ分析コード解説 | 初心者向けに処理フロー、評価指標、Spatial CV、SHAPの読み方を整理 | `src/analysis/analysis_rq3_satellite_only.py` |
| [calc_urban_params_guide.md](02_methods/calc_urban_params_guide.md) | `calc_urban_params.py` 詳細解説 | 解析範囲設計、UTMグリッド化、被覆率/密度算出、近似と制約、改良方針 | `src/analysis/calc_urban_params.py` |
| [gee_calc_satellite_indices.md](02_methods/gee_calc_satellite_indices.md) | 衛星指標算出仕様書 | NDVI/NDBI/NDWI算出式、QAマスク、スケーリング、統計出力の仕様と根拠 | `src/gee/gee_calc_satellite_indices.py` |
| [data_management_guide.md](02_methods/data_management_guide.md) | データ管理ガイド | 2層運用（Git + Google Drive）、.gitignore方針、再現性確保手順 | `data/`, `.gitignore` |
| [calc_LST_report.md](02_methods/calc_LST_report.md) | LST算出レポート | SMW法の選定理由、処理結果、品質評価 | `src/gee/gee_calc_LST.py` |
| [gee_calc_LST.md](02_methods/gee_calc_LST.md) | LST算出仕様書 | gee_calc_LST.pyの詳細仕様、入出力定義 | `src/gee/gee_calc_LST.py` |
| [CodingRule.md](02_methods/CodingRule.md) | コーディング規約 | PEP 8準拠、docstring規則、命名規則、再現性確保 | 全Pythonスクリプト |

### 📊 03_results - 研究結果

| ファイル名 | 概要 | 主要な内容 | 自動生成元 |
|-----------|------|-----------|-----------|
| [conference_abstract_rq3_satellite_only_draft.md](03_results/conference_abstract_rq3_satellite_only_draft.md) | 学会用アブストラクト下書き | RQ3 Satellite Only の本文案、図表案、表現上の注意点 | `docs/03_results/`, `data/csv/analysis/`, `src/analysis/` |
| [data_preparation_status.md](03_results/data_preparation_status.md) | データ整備状況レポート | GIS/LSTデータのCRS・解像度・空間範囲、次ステップ | `src/analyze_data_status.py` |
| [satellite_only_20230707_initial_run.md](03_results/satellite_only_20230707_initial_run.md) | Satellite Only 初期実行結果 | RQ3の初期ベースライン、Spatial CV、SHAP、結果解釈 | `src/analysis/build_satellite_only_dataset.py`, `src/analysis/analysis_rq3_satellite_only.py` |

**今後追加予定**:
- RQ1分析結果: 変数重要度ランキング、モデル性能
- RQ2分析結果: 空間スケール別の比較
- 図表集: 論文用図表の一覧

### 📦 04_archive - アーカイブ・先行研究

| ファイル名 | 概要 | 主要な内容 | 活用場面 |
|-----------|------|-----------|---------|
| [README.md](04_archive/README.md) | 文献管理システムガイド | 文献データベースの構造、AI活用方法 | 文献追加時 |
| [literature_management_guide.md](04_archive/literature_management_guide.md) | 文献管理詳細ガイド | PDFのMarkdown変換戦略、ベストプラクティス | 論文要約作成時 |
| [previous_studies_report.md](04_archive/previous_studies_report.md) | 先行研究整理 | S1-S8の事実整理、手法・データ・結論 | 論文執筆、手法比較 |
| [01_metadata/papers_database.csv](04_archive/01_metadata/papers_database.csv) | 論文メタデータ | 8論文のCSVデータベース（著者、年、RQ関連度） | AI検索、フィルタリング |
| [templates/structured_summary_template.md](04_archive/templates/structured_summary_template.md) | 論文要約テンプレート | 新規論文追加時の標準フォーマット | 論文要約作成時 |

**先行研究一覧（S1-S8）**:
- **S1**: Ermida et al. (2020) - SMW法 [本研究採用手法]
- **S2**: Le Ngoc Hanh (2025) - ベトナム・ダナン [地域参考]
- **S3**: Onačillová (2022) - 高解像度LST
- **S4**: Sun et al. (2019) - 機械学習による都市構造評価 [RQ1参考]
- **S5**: Osborne (2019) - 景観構成・配置
- **S6**: Garzón (2021) - 熱帯都市SUHI
- **S7**: Zhong (2024) - AutoMLダウンスケーリング
- **S8**: Tanoori (2024) - ML手法比較

---

## 🔄 ドキュメント関係図

```mermaid
graph TB
    A[research_guide.md<br/>研究計画書] --> B[calc_LST_report.md<br/>LST算出レポート]
    A --> C[previous_studies_report.md<br/>先行研究整理]
    
    B --> D[gee_calc_LST.md<br/>LST算出仕様]
    D --> E[src/gee/gee_calc_LST.py<br/>実装コード]
    
    C --> F[papers_database.csv<br/>論文DB]
    C --> G[literature_management_guide.md<br/>文献管理ガイド]
    
    E --> H[CodingRule.md<br/>コーディング規約]
    E --> J[src/analyze_data_status.py<br/>データ分析]
    
    J --> K[data_preparation_status.md<br/>データ整備状況]
    
    A -.RQ1-3定義.-> I[03_results/<br/>分析結果]
    B -.LSTデータ.-> K
    K --> I
    
    style A fill:#e1f5ff,stroke:#0066cc
    style B fill:#fff4e1,stroke:#cc8800
    style C fill:#f0f0f0,stroke:#666
    style I fill:#e1ffe1,stroke:#00cc00
    style K fill:#e1ffe1,stroke:#00cc00
```

**凡例**:
- 🔵 青: 研究計画
- 🟡 黄: 研究手法
- ⚪ 灰: アーカイブ
- 🟢 緑: 研究結果（今後）

---


## 📋 [01_planning](01_planning/) - 研究計画フェーズ

### 🎯 目的
研究の方向性を定め、RQ（Research Questions）を明確化する

### 📄 ドキュメント詳細

#### [available_gis_data.md](01_planning/available_gis_data.md)
**公開GISデータ候補の整理** - 道路・建物・built-up データの候補を、更新性と研究適合性つきで比較

**主要セクション**:
- 道路・建物・粗い built-up 指標の候補整理
- ベトナムと全球のカバレッジ比較
- 研究への適合性と注意点

**関連ドキュメント**:
- 研究計画 → [research_guide.md](01_planning/research_guide.md)
- 手法仕様 → [analysis_workflow.md](02_methods/analysis_workflow.md)

#### [research_guide.md](01_planning/research_guide.md)
**研究計画書** - 本研究の全体像を定義

**主要セクション**:
- 研究題目: ベトナム主要都市における地表面温度と都市構造の関係性評価
- 研究背景: 途上国大都市のデータ制約、ヒートアイランド現象
- **Research Questions**:
  - **RQ1**: どの説明変数がLSTに支配的か？
  - **RQ2**: 空間集計単位の違いによる影響は？
  - **RQ3**: データ制約下での説明可能性は？
- 研究手法: SMW法、衛星データ、公開データ、機械学習
- 期待される成果: データ制約下での分析手法の有効性検証

**関連ドキュメント**: 
- 手法詳細 → [calc_LST_report.md](02_methods/calc_LST_report.md)
- 先行研究 → [previous_studies_report.md](04_archive/previous_studies_report.md)

### 📝 今後追加予定
- `literature_review.md`: 詳細な文献レビュー
- `timeline.md`: 研究スケジュール

---


## 🔬 [02_methods](02_methods/) - 研究手法フェーズ

### 🎯 目的
研究で使用する具体的な手法やツールを詳細に記録し、再現性を確保する

### 📄 ドキュメント詳細

#### [calc_LST_report.md](02_methods/calc_LST_report.md)
**Landsat 8 LST算出レポート** - SMW法による地表面温度算出の実施報告

**主要セクション**:
- LST算出手法の選定理由（SMW法 vs 他手法）
- 処理結果: 2015-2024年のLSTデータ
- 品質評価: RMSE、欠損率、雲被覆率
- 次のステップ: 都市構造パラメータとの統合分析

**実装コード**: [src/gee/gee_calc_LST.py](../src/gee/gee_calc_LST.py)

**関連ドキュメント**:
- 手法の理論的背景 → [previous_studies_report.md S1](04_archive/previous_studies_report.md)
- 実装仕様 → [gee_calc_LST.md](02_methods/gee_calc_LST.md)

#### [gee_calc_LST.md](02_methods/gee_calc_LST.md)
**gee_calc_LST.pyの仕様書** - LST算出スクリプトの詳細仕様

**主要セクション**:
- 入力データ: `data/input/gee_calc_LST_info.csv`
- 出力データ: `data/output/LST/*.tif`、`gee_calc_LST_results.csv`
- 処理フロー: GEE認証 → ROI読込 → LST算出 → 品質評価
- 関数仕様: `lst_smw.apply_smw_lst()`
- エラーハンドリング: タイムアウト、雲被覆対応

**実装コード**: [src/gee/gee_calc_LST.py](../src/gee/gee_calc_LST.py)

**関連ドキュメント**:
- コーディング規約 → [CodingRule.md](02_methods/CodingRule.md)

#### [CodingRule.md](02_methods/CodingRule.md)
**Pythonコーディング規約** - プロジェクト全体で遵守すべき規約

**主要ルール**:
- PEP 8準拠（スペース4つ、タブ禁止）
- 日本語docstring必須（初心者にも理解できる説明）
- 命名規則: スネークケース（変数・関数）、キャメルケース（クラス）
- 1関数1責務
- 再現性: 相対パス、乱数シード設定

**適用範囲**: `src/`配下のすべてのPythonスクリプト

**関連ドキュメント**:
- AI指示書 → [.github/copilot-instructions.md](../.github/copilot-instructions.md)

### 📝 今後追加予定
- `urban_parameters.md`: 都市構造パラメータの定義と算出方法
- `statistical_methods.md`: 統計解析手法の詳細
- `ml_models.md`: 機械学習モデルの選定と実装

---


## 📊 [03_results](03_results/) - 研究結果フェーズ

### 🎯 目的
分析結果を体系的に整理し、論文執筆の基盤を構築する

### � ドキュメント詳細

#### [conference_abstract_rq3_satellite_only_draft.md](03_results/conference_abstract_rq3_satellite_only_draft.md)
**学会用アブストラクト下書き** - RQ3 の Satellite Only 初期結果に基づく本文案と図表案

**主要セクション**:
- Introduction / Methodology / Results / Conclusion の文案
- 掲載候補の図表セット
- 断定を避けるべき事項とタイトル案

**関連ドキュメント**:
- 初期結果 → [satellite_only_20230707_initial_run.md](03_results/satellite_only_20230707_initial_run.md)
- 研究計画 → [research_guide.md](01_planning/research_guide.md)

#### [data_preparation_status.md](03_results/data_preparation_status.md)
**データ整備状況レポート** - データ分析フェーズへの準備状況の全体把握（464行）

**主要セクション**:
- データ整備の全体概況（完了・未完了・優先対応事項）
- **GISデータ詳細**: 7種類のgpkgファイル（CS/DC/DH/GT/RG/TH/TV）
  - CRS情報: LOCAL_CS → EPSG:3405 (VN-2000)推定
  - 空間範囲: 投影座標（m）とWGS84（度）
  - ジオメトリタイプ・地物数（合計180,417地物）
- **LSTデータ詳細**: 
  - SMW法による2023年7-8月データ（有効データ4件）
  - 出力CRS: EPSG:4326、解像度30m
  - ROI情報（Hanoi、範囲要確認）
- **ディレクトリ構造**: データファイルの位置と役割
- **次ステップ**: タスク1-6（CRS設定、ROI修正、ジオメトリ修復等）

**自動生成元**: [src/analyze_data_status.py](../src/analyze_data_status.py)（GIS/LSTデータを自動分析）

**活用場面**:
- データ分析スクリプト作成時の入力データ仕様確認
- AI支援時のデータ構造把握
- 論文の「データと方法」セクション執筆

**関連ドキュメント**:
- 研究計画 → [research_guide.md](01_planning/research_guide.md)（RQ1-3の定義）
- LST詳細 → [calc_LST_report.md](02_methods/calc_LST_report.md)（SMW法の選定理由）
- コード規約 → [CodingRule.md](02_methods/CodingRule.md)（自動分析スクリプトの設計思想）

#### [satellite_only_20230707_initial_run.md](03_results/satellite_only_20230707_initial_run.md)
**Satellite Only 初期実行結果** - RQ3の初期ベースライン整理

**主要セクション**:
- 2023-07-07 観測を用いた初期分析条件
- MLR / Random Forest の性能比較
- Spatial CV による過大評価確認
- SHAP による変数重要度と寄与方向の解釈
- 今後の研究の方向性

**自動生成元**: `src/analysis/build_satellite_only_dataset.py`, `src/analysis/analysis_rq3_satellite_only.py`

### �📝 今後追加予定のドキュメント

#### RQ別の分析結果
- `rq1_variable_importance.md`: RQ1結果 - 説明変数の重要度ランキング
- `rq2_spatial_scale.md`: RQ2結果 - 空間集計単位ごとの比較分析

#### 統合結果
- `analysis_summary.md`: 全分析結果の統合まとめ
- `figures_catalog.md`: 論文用図表の一覧と説明
- `discussion_draft.md`: 考察の下書き

#### 補足資料
- `model_performance.md`: 各種モデルの性能比較
- `sensitivity_analysis.md`: 感度分析結果

### 🔗 関連ドキュメント
- 研究計画 → [research_guide.md](01_planning/research_guide.md)（RQ定義）
- データソース → [calc_LST_report.md](02_methods/calc_LST_report.md)（LSTデータ）
- 先行研究比較 → [previous_studies_report.md](04_archive/previous_studies_report.md)

---


## 📦 [04_archive](04_archive/) - アーカイブ・先行研究

### 🎯 目的
参考資料や先行研究を整理し、AI支援による文献活用を可能にする

### 📄 ドキュメント詳細

#### [README.md](04_archive/README.md)
**文献管理システムガイド** - 04_archiveフォルダの構造と使い方

**主要内容**:
- 3層情報管理システム（CSV → Markdown → PDF）
- AIとの対話例
- 文献追加手順

**対象ユーザー**: 研究者本人、AI支援システム

#### [literature_management_guide.md](04_archive/literature_management_guide.md)
**文献管理・AI活用ガイド** - PDFをAIが活用するための戦略書（314行）

**主要セクション**:
- 問題: AIはPDFを直接読めない
- 解決策: Markdown構造化要約の作成
- 3層データベースコンセプト（metadata → summaries → findings）
- 論文要約作成ガイド（30-60分/論文）
- AI最適化のベストプラクティス

**関連ドキュメント**:
- テンプレート → [templates/structured_summary_template.md](04_archive/templates/structured_summary_template.md)

#### [previous_studies_report.md](04_archive/previous_studies_report.md)
**先行研究整理（マスタードキュメント）** - S1-S8の事実ベース整理

**含まれる研究**:
- **S1**: Ermida et al. (2020) - SMW法 [本研究採用]
- **S2**: Le Ngoc Hanh (2025) - ダナン都市化とLST [ベトナム事例]
- **S3**: Onačillová (2022) - 高解像度LST
- **S4**: Sun et al. (2019) - 機械学習による都市構造評価 [RQ1参考]
- **S5**: Osborne (2019) - 景観構成・配置 [RQ2参考]
- **S6**: Garzón (2021) - 熱帯都市SUHI [途上国事例]
- **S7**: Zhong (2024) - AutoML
- **S8**: Tanoori (2024) - ML手法比較

**活用場面**: 論文執筆、手法比較、関連研究の参照

**関連ドキュメント**:
- 詳細メタデータ → [01_metadata/papers_database.csv](04_archive/01_metadata/papers_database.csv)

#### [01_metadata/papers_database.csv](04_archive/01_metadata/papers_database.csv)
**論文メタデータベース（CSV）** - AI検索・フィルタリング用

**列構成**:
- ID, 著者, 年, タイトル, 掲載誌, 主目的, データ種別
- 主要手法, 対象地域, DOI_URL, PDF有無
- 重要度（A/B/C）, RQ1-3関連度（◎○△）
- キーワード, メモ

**活用方法**:
```python
import pandas as pd
df = pd.read_csv('papers_database.csv')
# RQ1に関連する論文を抽出
rq1_papers = df[df['RQ1関連'].str.contains('◎|○')]
```

#### [templates/structured_summary_template.md](04_archive/templates/structured_summary_template.md)
**論文要約テンプレート** - 新規論文追加時の標準フォーマット

**セクション構成**:
1. 基本情報（著者、年、DOI）
2. 研究目的
3. 使用データ
4. 都市構造パラメータの定義
5. 分析手法
6. 主要な結果
7. 本研究との関連性（RQ1-3）
8. 重要な引用・図表

**使用タイミング**: 新しい論文をデータベースに追加する際

### 📁 サブディレクトリ

```
04_archive/
├── 01_metadata/              # 論文メタデータ
│   └── papers_database.csv
├── 02_structured_summaries/  # 構造化要約（今後追加）
│   └── S1_Ermida_2020.md 等
├── 03_key_findings/          # テーマ別知見（今後追加）
│   ├── urban_parameters_catalog.md
│   └── lst_methods_comparison.md
├── 04_pdfs/                  # PDF原本（移動予定）
└── templates/                # テンプレート
```

### 🔗 関連ドキュメント
- 研究計画との対応 → [research_guide.md](01_planning/research_guide.md)
- 採用手法の詳細 → [calc_LST_report.md](02_methods/calc_LST_report.md)

---


## 🔄 ドキュメント管理のルール

### ✅ 新しいドキュメントを追加する場合

1. **適切なフェーズを選択**: 
   - 📋 `01_planning/`: 研究の方向性・RQ定義
   - 🔬 `02_methods/`: 手法・ツールの詳細仕様
   - 📊 `03_results/`: 分析結果・図表
   - 📦 `04_archive/`: 参考資料・先行研究

2. **このREADME.mdを更新**:
   - 該当フェーズの「ドキュメント詳細」セクションに追加
   - 「全ドキュメントカタログ」テーブルに行を追加
   - 必要に応じて「ドキュメント関係図」を更新

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

### ❌ 禁止事項

- **サブフォルダのREADME.md作成**: このdocs/README.mdに集約
  - 例外: `04_archive/README.md`のみ（文献管理が複雑なため）
- **重複記述**: 同じ内容を複数ファイルに記載しない（Single Source of Truth原則）
- **絶対パスの使用**: 相対パスを使用し移植性を確保

---

## 💡 活用のヒント

### 🔬 先行研究調査：ChatGPT → GitHub Copilot 連携ワークフロー

> **最も効率的な方法**: ChatGPTで論文分析 → GitHub Copilotでプロジェクト統合

#### フェーズ1: 論文検索（ChatGPT + ScholarGPT）
```
ChatGPTに質問：
「Land Surface Temperature and urban structure in Southeast Asian cities
 で2020年以降の主要論文を教えて。各論文のDOI、引用数、主要な手法も教えて」

→ 論文リスト（10-15本）を取得
```

#### フェーズ2: 論文分析（ChatGPT）
```
ChatGPTに依頼：
「docs/04_archive/templates/chatgpt_instruction_paper_analysis.md の
 指示に従って、以下の論文を分析してください」
 
【論文情報】
- タイトル: [論文タイトル]
- 著者: [著者名]
- DOI: [DOI]
（またはPDFを添付）

→ 構造化要約が自動生成される（5-10分）
```

#### フェーズ3: プロジェクト統合（GitHub Copilot）
```
VS Code（GitHub Copilot）に依頼：
「ChatGPTが生成したS9_Zhang_2023.md を保存しました。
 この内容を papers_database.csv に追加し、
 previous_studies_report.md を更新してください」

→ データベースが自動更新される（1-2分）
```

**所要時間**: 論文1本あたり **合計10-15分** 🚀

**詳細ガイド**: [04_archive/README.md](04_archive/README.md)（ツール使い分けセクション）

---

### 🤖 AIに質問する場合

**効果的な質問例**:
```
「research_guide.mdを参照して、RQ1に関連する分析手法を提案してください」

「previous_studies_report.mdから、都市構造パラメータの定義を抽出し、
 表形式でまとめてください」

「calc_LST_report.mdに基づいて、SMW法の処理フローを
 Mermaid図で作成してください」

「papers_database.csvから重要度Aの論文のみをフィルタリングし、
 RQ1との関連度が高い順に並べてください」
```

**NGな質問例**:
```
❌ 「先行研究を教えて」（曖昧）
✅ 「previous_studies_report.mdのS4（Sun et al. 2019）で使用された
    都市構造パラメータを箇条書きで教えて」

❌ 「LSTの計算方法は？」（文脈不明）
✅ 「gee_calc_LST.mdを参照して、SMW法の入力パラメータと
    出力フォーマットを説明して」
```

### 📖 ドキュメント間の関連を確認

**研究の流れに沿って参照**:
```
1. 研究計画  → research_guide.md（RQ定義）
2. 先行研究  → previous_studies_report.md（手法調査）
3. 手法選定  → calc_LST_report.md（LST算出）
4. 実装仕様  → gee_calc_LST.md
5. コード規約 → CodingRule.md
6. 実装      → src/gee/gee_calc_LST.py
7. 結果整理  → 03_results/（今後）
```

**ドキュメント関係図を活用**:
- Mermaid図で視覚的に依存関係を把握
- 矢印の方向 = 参照の流れ

### 🔍 検索のコツ

**VS Codeでの検索**:
```
Ctrl+Shift+F で全文検索
- "RQ1" → Research Question 1 関連の記述を検索
- "SMW" → SMW法に関する記述を検索
- "都市構造パラメータ" → パラメータ定義を検索
```

**CSVデータの活用**:
```python
# 特定のキーワードで論文を検索
df = pd.read_csv('docs/04_archive/01_metadata/papers_database.csv')
ml_papers = df[df['キーワード'].str.contains('機械学習|ランダムフォレスト')]
```

---

## 🔗 関連ディレクトリ

### プロジェクト全体の構成

```
MasterResearch/
├── .github/                    # AI環境設定
│   ├── copilot-instructions.md # Copilot自動読込（最重要）
│   ├── EFFICIENCY_PROPOSAL.md  # 効率化提案
│   └── prompts/                # タスクプロンプト
│       ├── task.prompt.md      # 現在のタスク
│       └── templates/          # タスクテンプレート
│
├── docs/                       # 📌 このディレクトリ
│   └── README.md               # 📌 このファイル
│
├── src/                        # Pythonスクリプト
│   ├── gee_calc_LST.py         # LST算出メイン
│   ├── module/lst_smw.py       # SMW法モジュール
│   └── analysis_*.py           # 分析スクリプト
│
├── data/                       # データ
│   ├── input/                  # 入力データ
│   │   ├── gee_calc_LST_info.csv
│   │   └── GISData/ROI/
│   ├── output/                 # 出力データ
│   │   ├── LST/*.tif
│   │   └── gee_calc_LST_results.csv
│   └── csv/analysis/           # 分析用CSV
│
└── 整備データ/                  # ベトナム測量データ
    └── merge/*.gpkg            # 統合GeoPackage
```

### 各ディレクトリの関係

| ディレクトリ | 役割 | docs/との関係 |
|------------|------|--------------|
| `.github/` | AI支援環境 | copilot-instructions.mdがdocs/を参照 |
| `src/` | 実装コード | docs/02_methods/の仕様に基づく |
| `data/` | データ | docs/02_methods/で入出力を定義 |
| `整備データ/` | 元データ | docs/で使用方法を説明（今後） |

---

## 📋 チェックリスト

### 新規ドキュメント追加時

- [ ] 適切なフェーズフォルダに配置
- [ ] docs/README.mdを更新（このファイル）
- [ ] 冒頭にメタ情報を記載（最終更新日、関連ドキュメント）
- [ ] 相互参照リンクを設定
- [ ] 必要に応じてドキュメント関係図を更新

### ドキュメント更新時

- [ ] 最終更新日を更新
- [ ] 重要な変更は変更履歴に記録
- [ ] 影響を受ける関連ドキュメントを確認
- [ ] リンク切れがないか確認

### 定期メンテナンス

- [ ] 月1回: 全ドキュメントのリンク切れチェック
- [ ] 研究フェーズ移行時: ドキュメント構成の見直し
- [ ] 論文投稿前: 全ドキュメントの整合性確認

---

## 📝 変更履歴

| 日付 | 変更内容 | 担当 |
|------|---------|------|
| 2026-04-09 | `available_gis_data.md` と `conference_abstract_rq3_satellite_only_draft.md` を索引に追加 | AI支援 |
| 2026-04-07 | `setup.md` と `satellite_only_20230707_initial_run.md` を索引に追加 | AI支援 |
| 2026-02-26 | 案1（Single Source of Truth）実装：サブREADME削除、docs/README.md充実化 | AI支援 |
| 2026-02-26 | 提案5実装：フェーズ別ディレクトリ構造に再編 | AI支援 |
| 2026-02-XX | 初版作成 | 研究者 |

---

**最終更新**: 2026-04-09  
**管理方針**: Single Source of Truth - すべての情報をこのREADME.mdに集約  
**次回更新予定**: 03_results/に分析結果追加時
