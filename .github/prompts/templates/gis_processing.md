---
agent: agent
---

# タスク: GISデータ処理・解析

## 📝 概要
[GeoPackage/Shapefile/Rasterデータの処理・解析タスク]

## 🎯 目的
[空間解析、属性抽出、統計計算など]

## 📥 入力データ
- **GISデータ**: `data/input/xxx.gpkg` - [レイヤー名、CRS、内容]
- **補助データ**: `data/input/xxx.csv` - [オプション]

## 📤 出力データ
- **処理済みGIS**: `data/output/xxx.gpkg` - [処理内容]
- **統計CSV**: `data/output/xxx_stats.csv` - [集計内容]
- **地図画像**: `data/output/xxx_map.png` - [オプション]

## ⚙️ 処理要件
### データ読み込み
- [ ] CRSの確認（WGS84またはVN-2000）
- [ ] レイヤー数とジオメトリタイプの確認

### 空間処理
- [ ] [バッファ / インターセクト / 集計など]
- [ ] CRS変換（必要に応じて）

### 属性処理
- [ ] 属性名の確認
- [ ] 欠損値の処理
- [ ] [計算・集計など]

### 出力
- [ ] GeoPackage形式で保存
- [ ] 統計結果をCSVで保存

## 🔍 GIS固有の注意事項
- **座標系**: 出力はWGS84（EPSG:4326）を原則とする
- **ジオメトリ検証**: `gdf.is_valid.all()` で確認
- **大規模データ**: メモリ使用量に注意、必要に応じてチャンク処理

## 📊 期待される結果
- [空間分布の可視化]
- [統計量の算出]

## 🔗 関連ファイル
- スクリプト: `src/xxx.py`
- 入力データ: `整備データ/merge/xxx.gpkg`
- 出力先: `data/output/`

## 💻 使用ライブラリ
```python
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon
import matplotlib.pyplot as plt
```
