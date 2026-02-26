# 研究環境の効率化提案書

## 📋 現状分析

### 現在の構成
```
.github/
  └── prompts/
      ├── task.prompt.md          # 現在のタスク指示
      ├── completed/              # 完了済みタスク
      └── CodingRule.md          # コーディング規約（参照）

docs/                             # 研究ドキュメント
```

### 課題
1. **コンテキストの重複**: 毎回、タスクプロンプト内で同じルールや背景を記述
2. **知識の分散**: 研究ガイド、コーディング規約、タスクが別々のファイルに分散
3. **タスク管理の非効率性**: 完了・未完了の管理が手動
4. **AI活用の限定性**: GitHub Copilotの高度な機能を活用しきれていない

---

## 🚀 提案1: `.github/copilot-instructions.md` の導入（最重要）

### 効果
GitHub Copilotが**すべての会話で自動的に読み込む**プロジェクト固有の指示ファイルです。

### 導入メリット
✅ タスクプロンプトから共通ルールを削除可能  
✅ 研究の背景・目的を常にAIが理解  
✅ コーディング規約を自動適用  
✅ プロジェクト固有の用語をAIが正確に理解  

### 推奨構成
```markdown
# プロジェクト概要
- 研究テーマ
- 主要なRQ（Research Questions）
- 使用技術スタック

# コーディング方針
- Python規約の要約
- ファイル命名規則
- ディレクトリ構造

# 用語集
- LST、NDVI、SMW法などの定義

# データパス規則
- 入力データの場所
- 出力先の規則

# 禁止事項
- やってはいけないこと
```

---

## 🚀 提案2: プロンプトファイル構造の再設計

### 新しい構造
```
.github/
  ├── copilot-instructions.md      # 【新規】常時読み込まれるコンテキスト
  │
  ├── prompts/
  │   ├── active/                  # 【新規】アクティブなタスク
  │   │   └── current_task.md
  │   │
  │   ├── templates/               # 【新規】タスクテンプレート
  │   │   ├── data_analysis.md
  │   │   ├── gis_processing.md
  │   │   └── model_development.md
  │   │
  │   └── completed/               # 完了済みタスク（既存）
  │
  ├── workflows/                   # 【新規】よく使うワークフロー
  │   ├── create_new_task.md
  │   └── data_pipeline.md
  │
  └── references/                  # 【新規】クイックリファレンス
      ├── quick_commands.md
      └── troubleshooting.md
```

### タスクプロンプトのスリム化例

**Before（現状）:**
```markdown
# タスク実行時の共通ルール
ワークスペースの任意のファイルを、適宜読み取りタスクを実行してください。
必ずコーディング規約を遵守してください。
.github\prompts\CodingRule.md
```

**After（改善後）:**
```markdown
# タスク: GPKG属性翻訳スクリプト作成

## 目的
ベトナム語の地理空間データ属性を日本語に翻訳

## 入力
- `整備データ/merge_*.gpkg`（7ファイル）

## 出力
- 翻訳済みCSV（属性名・属性値の対応表）
- オプション: 翻訳済みGPKG

## 特記事項
- 翻訳方法は実装前に相談
```

※共通ルールは `copilot-instructions.md` に移動

---

## 🚀 提案3: タスク管理の自動化

### GitHub Issues / Projects の活用
研究タスクをIssueとして管理し、プロンプトファイルと連携

```markdown
<!-- Issue テンプレート例 -->
## タスク概要
[簡潔な説明]

## 関連ファイル
- [ ] プロンプトファイル: `.github/prompts/active/task_xxx.md`
- [ ] 実装スクリプト: `src/xxx.py`
- [ ] ドキュメント: `docs/xxx.md`

## チェックリスト
- [ ] 要件定義完了
- [ ] 実装完了
- [ ] テスト完了
- [ ] ドキュメント更新
```

---

## 🚀 提案4: AI支援スニペット・テンプレート集

### よく使うコード構造のテンプレート化

**例: GISデータ処理テンプレート**
```python
# templates/gis_analysis_template.py
"""
GISデータ解析テンプレート

使用方法:
1. INPUT_PATH, OUTPUT_PATHを設定
2. process_data()内に処理ロジックを実装
3. main()で実行

作成日: YYYY-MM-DD
作成者: [名前]
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# 定数定義
INPUT_PATH = Path("data/input")
OUTPUT_PATH = Path("data/output")

def load_data(file_path):
    """データ読み込み"""
    pass

def process_data(gdf):
    """データ処理（ここを実装）"""
    pass

def save_results(gdf, output_path):
    """結果保存"""
    pass

def main():
    """メイン処理"""
    pass

if __name__ == "__main__":
    main()
```

---

## 🚀 提案5: ドキュメント構造の最適化

### 研究フェーズ別のドキュメント整理

```
docs/
  ├── 01_planning/              # 【新規】計画フェーズ
  │   ├── research_guide.md
  │   └── literature_review.md
  │
  ├── 02_methods/               # 【新規】手法フェーズ
  │   ├── gee_calc_LST.md
  │   ├── calc_LST_report.md
  │   └── CodingRule.md
  │
  ├── 03_results/               # 【新規】結果フェーズ
  │   └── analysis_results.md
  │
  └── 04_archive/               # 【新規】アーカイブ
      └── previous_studies_report.md
```

---

## 🚀 提案6: クイックコマンド集の作成

### AI対話を効率化するコマンド集

```markdown
# .github/references/quick_commands.md

## よく使うAI指示

### データ分析系
- `@workspace GPKGファイルを読み込んで属性を確認`
- `@workspace NDVIを計算するスクリプトを作成（コーディング規約準拠）`

### レビュー系
- `このスクリプトをコーディング規約に沿ってレビュー`
- `エラーハンドリングを追加`

### ドキュメント系
- `このコードにdocstringを追加`
- `research_guideに基づいて処理フローを図解`
```

---

## 🎯 実装優先順位

### Phase 1: 必須（即効性高）
1. **`.github/copilot-instructions.md` 作成** ← 最優先
2. **タスクプロンプトのスリム化**
3. **テンプレート集の整備**

### Phase 2: 推奨（中期的効果）
4. **プロンプトフォルダ構造の再編**
5. **クイックコマンド集の作成**

### Phase 3: 長期的改善
6. **GitHub Issues連携**
7. **ドキュメント構造の最適化**

---

## 📊 期待される効果

| 項目 | 改善前 | 改善後 | 効果 |
|-----|--------|--------|------|
| タスク作成時間 | 15分 | 5分 | **-67%** |
| コンテキスト記述 | 毎回必要 | 自動適用 | **手間ゼロ** |
| コーディング規約遵守 | 手動確認 | AI自動適用 | **品質向上** |
| タスク管理 | 手動 | 半自動化 | **漏れ防止** |

---

## 🛠️ 導入支援

以下の作業を支援可能です：

✅ `.github/copilot-instructions.md` の作成  
✅ 現在のタスクプロンプトのスリム化  
✅ テンプレート集の作成  
✅ ディレクトリ構造の再編  
✅ 移行マニュアルの作成  

---

## 💡 補足: copilot-instructions.md の強力さ

### 実例
研究プロジェクトに特化した指示を書くと：

```markdown
# 研究固有ルール
- LSTは必ず摂氏で出力
- 座標系はWGS84を原則とする
- ベトナム語属性は翻訳前に確認
```

→ **全ての会話でAIがこれを守る**

### 用語の自動理解
```markdown
# 用語集
- SMW法: Statistical Mono-Window法（Ermida et al. 2020）
- ROI: Region of Interest（研究対象地域）
```

→ **説明不要で用語が通じる**

---

## 🤔 次のステップ

ご希望に応じて以下を実施します：

1. **今すぐ実装**: Phase 1（必須項目）を一緒に構築
2. **詳細相談**: 個別提案の深堀り
3. **段階的導入**: まず1つずつ試す

どの方向で進めますか？
