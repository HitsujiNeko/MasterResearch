---
agent: agent
---

# タスク: データ分析スクリプト作成

## 📝 概要
[統計分析・機械学習・可視化などのデータ解析タスク]

## 🎯 目的
[RQ1/RQ2/RQ3のどれに対応するか明記]

## 📥 入力データ
- **主データ**: `data/csv/analysis/xxx.csv` - [説明変数、目的変数]
- **補助データ**: `data/xxx.csv` - [オプション]

## 📤 出力データ
- **分析結果**: `data/output/analysis_results.csv`
- **可視化**: `data/output/figures/xxx.png`
- **モデル**: `data/output/models/xxx.pkl` - [オプション]

## ⚙️ 処理要件
### データ前処理
- [ ] 欠損値の確認と処理
- [ ] 外れ値の検出
- [ ] 正規化・標準化（必要に応じて）

### 探索的データ解析（EDA）
- [ ] 基本統計量の算出
- [ ] 相関分析
- [ ] データ分布の可視化

### モデリング
- [ ] [重回帰 / ランダムフォレスト / その他]
- [ ] 学習・検証データの分割
- [ ] モデル評価（R², RMSE等）

### 結果出力
- [ ] 係数・重要度の抽出
- [ ] 可視化（散布図、残差プロット等）
- [ ] レポート用の数値整理

## 🔍 分析固有の注意事項
- **説明変数**: 多重共線性の確認（VIF < 10）
- **外れ値**: Cook's D などで検出
- **乱数シード**: 再現性のため `random_state=42` を設定

## 📊 期待される結果
- [どの都市構造パラメータがLSTに影響するか]
- [モデルの説明力（R²）]

## 🔗 関連ファイル
- スクリプト: `src/analysis_xxx.py`
- 入力データ: `data/csv/analysis/xxx.csv`
- 出力先: `data/output/`

## 💻 使用ライブラリ
```python
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import matplotlib.pyplot as plt
import seaborn as sns
```
