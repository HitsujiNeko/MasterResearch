# GitHub Copilot Instructions - 修士研究プロジェクト

> **このファイルの役割**  
> GitHub Copilotがすべての会話で自動的に読み込むプロジェクト固有の指示です。  
> プロジェクト全体に共通する原則・用語・構造を定義し、AI支援を最適化します。

---

## 🎓 研究概要

### 研究テーマ
ベトナム主要都市を対象とした地表面温度と都市構造の関係性評価に関する研究

### 研究目的
都市を構成する物理的要素が地表面温度（LST）分布に与える影響を定量的に明らかにし、ヒートアイランド現象の発生要因を空間的に把握する。また、途上国大都市におけるデータ制約下での分析手法の有効性を検証する。

### 主要なResearch Questions（RQ）
- **RQ1**: Landsat 8（30m）LSTと都市構造データを組み合わせた場合、どの説明変数がLSTに対して支配的か？
- **RQ2**: 都市構造パラメータとLSTの関係性は、空間集計単位や解析スケールの違いによってどのように変化するか？
- **RQ3**: 測量データが限定的な条件下でも、衛星データおよび公開データによりLST分布の説明はどの程度可能か？

**詳細**: [research_guide.md](docs/01_planning/research_guide.md)

---

## 🐍 コーディング規約（要約）

### 必須ルール
- **PEP 8準拠**: スペース4つインデント、タブ禁止
- **日本語コメント・docstring必須**: 初心者にも理解できる丁寧な説明
- **命名規則**: 変数・関数はスネークケース、クラスはキャメルケース
- **1関数1責務**: 処理を適切に分割
- **再現性**: パスは相対パス・`pathlib.Path`、乱数シードを設定

**詳細**: [CodingRule.md](docs/02_methods/CodingRule.md)を必ず参照

---

## 📁 ディレクトリ構造とデータパス

### プロジェクト構造
```
MasterResearch/
├── data/
│   ├── input/              # 入力データ
│   │   ├── gee_calc_LST_info.csv
│   │   └── GISData/ROI/
│   ├── output/             # 出力データ
│   │   ├── gee_calc_LST_results.csv
│   │   └── LST/*.tif
│   └── csv/analysis/       # 分析用CSV
│
├── 整備データ/              # ベトナム測量データ
│   ├── merge/*.gpkg        # 統合GeoPackage
│   └── Vector_*/           # 元データ（DGN）
│
├── src/                    # Pythonスクリプト（タイプ別フォルダ分類済み）
│   ├── preprocessing/      # データ前処理
│   │   ├── merge_vector.py / merge_vector_fixed.py
│   │   ├── append_remaining_dgn.py
│   │   ├── convert_gis_to_wgs84.py / convert_to_wgs84_ogr.py
│   │   └── organize_dgn.py / merge_map.py
│   ├── analysis/           # データ分析・EDA
│   │   ├── analyze_data_status.py
│   │   ├── analyze_gpkg.py / analyze_merged_gpkg.py
│   │   └── analyze_lst_data_detail.py
│   ├── gee/                # Google Earth Engine
│   │   └── gee_calc_LST.py
│   ├── module/             # 共有モジュール
│   │   └── lst_smw.py
│   └── js/                 # GEE用JavaScriptモジュール
│
└── docs/                   # ドキュメント（研究フェーズ別）
    ├── README.md           # ドキュメント管理の中心
    ├── 01_planning/
    │   └── research_guide.md
    ├── 02_methods/
    │   ├── calc_LST_report.md
    │   ├── gee_calc_LST.md
    │   └── CodingRule.md
    ├── 03_results/
    │   └── data_preparation_status.md
    └── 04_archive/
        ├── README.md
        └── previous_studies_report.md
```

### データパス規則
- 入力: `data/input/` または `整備データ/`
- 出力: `data/output/` 配下の適切なフォルダ
- 一時ファイル: `data/temp/`（必要に応じて作成）
- パスは `pathlib.Path` を使用

---

## 🌍 プロジェクト固有の用語集

### 地表面温度関連
- **LST** (Land Surface Temperature): 地表面温度。**本研究では必ず摂氏（°C）で出力**
- **SMW法**: Statistical Mono-Window法（Ermida et al. 2020）。本研究の標準手法
- **SUHI**: Surface Urban Heat Island（表面都市ヒートアイランド）

### 衛星由来指標
- **NDVI** (Normalized Difference Vegetation Index): 正規化植生指数。緑地の指標
- **NDBI** (Normalized Difference Built-up Index): 正規化建物指数。市街化の指標
- **NDWI** (Normalized Difference Water Index): 正規化水指数。水域の指標
- **FVC** (Fractional Vegetation Cover): 植生被覆率

### 都市構造パラメータ
本研究における**都市構造パラメータ**とは、地表面エネルギー収支および熱輸送に影響を与える要素（土地被覆・建物・道路・水域・人口集積など）の空間配置と密度を空間統計量として定量化した説明変数群を指す。

例：建物被覆率、道路密度、緑被率、水域率、主要道路距離、人口密度など

### GISデータ
- **ROI** (Region of Interest): 研究対象地域
- **GPKG**: GeoPackage形式（`.gpkg`）
- **DGN**: MicroStation形式のCADファイル（ベトナム測量データの元形式）
- **座標系**: 原則として**WGS84（EPSG:4326）**。ベトナム測量データは**VN-2000**

---

## 🔧 使用技術スタック

### 主要ライブラリ
- **データ分析**: NumPy, Pandas
- **地理空間データ**: GeoPandas, Shapely, Folium
- **衛星画像解析**: Google Earth Engine (ee)
- **機械学習**: scikit-learn (RandomForest, LinearRegression等)
- **可視化**: Matplotlib, Seaborn

依存関係の詳細: `environment.yml` / `docs/setup.md`（`requirements.txt` は参照用）

---

## 📋 タスク実行時の共通ルール

### 必須事項
1. **ワークスペースのファイルを適宜読み取る**: タスク実行前に関連ファイルを確認
2. **コーディング規約を遵守**: 上記Pythonコーディング規約に準拠
3. **ドキュメント参照**: `docs/` 配下の関連ドキュメントを確認
4. **再現性の確保**: 乱数シード設定、パスの相対化など
5. **実装前後チェックリストを実施**: `docs/02_methods/CodingRule.md` の「9. 実装前後チェックリスト（必須）」を完了してから最終出力する

### 推奨事項
- 処理の各段階で中間結果を保存（デバッグ用）
- 大規模データ処理時は進捗表示を追加
- 処理時間が長い場合はログ出力

### 禁止事項
- ❌ 絶対パスのハードコード（ユーザー名を含むパスなど）
- ❌ タブ文字の使用
- ❌ 日本語変数名の使用
- ❌ コメント・docstringなしのコード

---

## 📖 ドキュメント管理のルール

### Single Source of Truth原則
- **`docs/README.md`が唯一の真実の情報源**: 全ドキュメントの構造・概要はここに集約
- **サブREADMEは作成禁止**: 例外は`docs/04_archive/README.md`のみ（文献管理が複雑なため）
- **重複記述を避ける**: 同じ内容を複数ファイルに記載しない

### 新規ドキュメント作成時の必須ルール
1. **適切なフェーズフォルダに配置**:
   - `01_planning/`: 研究計画・RQ定義
   - `02_methods/`: 手法・ツール仕様
   - `03_results/`: 分析結果・図表
   - `04_archive/`: 参考資料・先行研究

2. **`docs/README.md`を必ず更新**:
   - 該当フェーズセクションにファイル情報を追加
   - 「全ドキュメントカタログ」テーブルに行を追加

3. **ドキュメント冒頭にメタ情報を記載**:
   ```markdown
   # タイトル
   
   **最終更新**: 2026-02-26  
   **関連ドキュメント**: [research_guide.md], [CodingRule.md]  
   **前提知識**: RQ1-RQ3の理解
   ```

4. **相互参照リンクを設定**: 関連ドキュメントへの相対パスリンクを追加

### ドキュメント移動・削除時の注意
- リンク切れを防ぐため、影響範囲を確認してから実施
- `docs/README.md`のパスを必ず更新
- Git履歴を保持（`git mv`を使用）

---

## 🎯 AI支援における指針

### AIに期待すること

#### 開発支援
- コード補助（Python / GIS処理）
- デバッグ・リファクタリング
- テストコード作成

#### 研究支援
- **文献調査**: 先行研究の要約、比較表作成
  - **推奨**: ChatGPTで論文分析 → GitHub Copilotで統合
  - **詳細**: `docs/04_archive/templates/chatgpt_instruction_paper_analysis.md`
- **データ分析**: EDA、統計解析、可視化
- **手法比較**: 複数手法の長所・短所の整理
- **結果解釈**: 分析結果の壁打ち、考察のブラッシュアップ
- **文章作成**: 論文・レポートの構成案、表現の改善

#### アイデア出し
- 分析手法の提案
- RQに対するアプローチの検討
- データ制約下での代替手法の提示

#### agency-agents活用方針
- `agency-agents` は必須ではなく、必要時に活用する（通常タスクは従来どおり実行可能）。
- エージェント指定がない場合は、`docs/02_methods/agency_agents_minimal_set.md` の省力運用プロトコルに従って最小セットを自動適用する。
- 研究ルールの正本は本ファイルと `docs/` 配下に置き、`agency-agents` 側へ重複記述しない。

### AIに期待しないこと（研究者の責任範囲）
- 学術的判断の最終決定
- 結果の恣意的解釈
- 結論の責任所在
- 研究倫理に関わる判断

**原則**: AIは研究補助として利用し、研究の最終的な判断・責任は研究者自身が負う。

---

## 📚 主要ドキュメントリンク

プロジェクトルートからの相対パス（研究フェーズ別に整理）：
### 研究のドキュメントの構成及び概要
- `docs\README.md`

### 01_planning - 研究計画
- **研究計画**: `docs/01_planning/research_guide.md`

### 02_methods - 研究手法
- **分析ワークフロー仕様書**: `docs/02_methods/analysis_workflow.md`（前処理→パラメータ算出→モデル→評価の全工程）
- **LST算出レポート**: `docs/02_methods/calc_LST_report.md`
- **LST算出仕様**: `docs/02_methods/gee_calc_LST.md`
- **コーディング規約**: `docs/02_methods/CodingRule.md`

### 03_results - 研究結果
- ※今後、分析結果を追加予定

### 04_archive - アーカイブ
- **先行研究整理**: `docs/04_archive/previous_studies_report.md`

### その他
- **DGNデータ確認結果**: `DGNファイル内容確定結果.md`


---

## 🔄 このファイルの更新方針

- 研究の進行に応じて随時更新
- 新しい用語や規約は追記
- 変更時は日付を記録

**最終更新**: 2026-04-02
