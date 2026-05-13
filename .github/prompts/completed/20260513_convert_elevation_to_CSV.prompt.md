---
agent: agent
---

# タスク: 標高点データを CSV 形式に変換する

## 概要
`merge_DH.gpkg` の `elements` レイヤから `Point` 地物のみを抽出し、`Text` 属性を標高値として CSV に変換する。

生成した CSV は DEM 作成や補間処理に使える形式とし、座標は元データの投影座標をそのまま保持する。

## タスク詳細

### 入力
- `整備データ/merge/merge_DH.gpkg`

### 出力
CSV の列は以下とする。

`id,x,y,elevation`

- CRS: `EPSG:5897`（VN-2000 / TM-3 zone 482 として運用）
- `id`: 0,1,2,... の連番
- `x`: 元データ座標の X 値
- `y`: 元データ座標の Y 値
- `elevation`: `Text` 属性から読み取った標高値

### 注意事項
- 入力の正本は `整備データ/merge/merge_DH.gpkg` を使うこと
- `x,y` は元データ座標をそのまま出力すること
- `elevation` は `Text` 属性から数値化すること
- DEM 作成は本タスクに含めない

## 関連ファイル
- `gpkgの確認結果.md`
- `src/preprocessing/convert_elevation_to_csv.py`

---

`.github/copilot-instructions.md` を参照し、関連ドキュメントに従って進めること。

---

## 完了時の記録

**完了日**: 2026-05-13  
**ステータス**: 完了

### 実施内容
- `merge_DH.gpkg` の `elements` レイヤから `Point` 地物のみを抽出し、`Text` 属性を `elevation` として CSV 化する `src/preprocessing/convert_elevation_to_csv.py` を追加した
- 入力は `整備データ/merge/merge_DH.gpkg` を正本として採用し、旧 `gis_wgs84` への依存を外した
- `data/csv/analysis/merge_DH_elevation_points.csv` を生成した

### 生成物
- `data/csv/analysis/merge_DH_elevation_points.csv`

### 関連更新
- `src/preprocessing/convert_elevation_to_csv.py`
- `.github/prompts/active/convert_elevation_to_CSV.prompt.md`

### 検証・補足
- 出力 CSV の座標系は `EPSG:5897`
- CSV 行数は `46,254`
- `x` 範囲は `581170.148` - `589879.882`
- `y` 範囲は `2321894.322` - `2333459.619`
- `elevation` 範囲は `0.5` - `16.85`
- `python -m py_compile src/preprocessing/convert_elevation_to_csv.py` は通過
- 現在のシェル環境では `python src/preprocessing/convert_elevation_to_csv.py` 実行時に `ModuleNotFoundError: No module named 'fiona'` となるため、再実行には GIS 依存入り環境が必要

### 未完了事項・引き継ぎ事項
- 必要なら本タスク prompt を completed へ移動する
- 必要なら `fiona` を含む実行環境で再実行し、依存関係を `environment.yml` などに明記する
