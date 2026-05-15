---
agent: agent
---

# タスク: `merge_XX.gpkg` の正本 CRS を `EPSG:5897` 前提へ修正する

## 背景
これまで `merge_XX.gpkg` は `EPSG:3405` 前提で扱っていたが、QGIS 上での再確認により、正しく重なるのは `EPSG:5897` であることが判明した。

このため、測量 GIS の正本 CRS を `EPSG:5897` として再定義し、分析コード・補助スクリプト・関連ドキュメントの `3405` 前提を `5897` 前提へ修正する。

## 問題整理
- `merge_XX.gpkg` を `EPSG:3405` で読むと一様なずれが生じる
- `merge_XX.gpkg` を `EPSG:5897` で読むと正しい位置に表示される
- 直前の `merge_*_wgs84` 廃止タスクでは、正本 CRS を `EPSG:3405` と仮定して整理していた
- そのため、コードとドキュメントに `3405` 前提の記述が残っていた

## 目的
1. 測量 GIS の正本 CRS を `EPSG:5897` に統一する
2. `src/analysis/calc_urban_params.py` などの分析コードを `5897` 前提へ修正する
3. `src/analysis/analyze_spatial_extents.py` などの補助コードを `5897` 前提へ修正する
4. 関連ドキュメントの CRS 記述を `5897` に改める

## 対象ファイル
- `整備データ/merge/merge_XX.gpkg`
- `src/analysis/calc_urban_params.py`
- `src/analysis/analyze_spatial_extents.py`
- `src/analysis/analyze_data_status.py`
- `data/output/spatial_extent_report.json`
- `docs/02_methods/analysis_workflow.md`
- `docs/02_methods/calc_urban_params_guide.md`
- `docs/03_results/survey_gis_data_preparation_status.md`
- `.github/prompts/completed/20260513_rework_analysis_flow_without_merge_wgs84.prompt.md`

## 完了条件
- `EPSG:5897` 前提に修正した分析コード
- `EPSG:5897` 前提に修正したドキュメント
- `gis_merge_from_5897` を持つ `data/output/spatial_extent_report.json`
- 修正内容と確認結果を残した task prompt

## 注意点
- `EPSG:3405` を `EPSG:5897` に置き換えるだけでなく、変換ロジックや bbox の意味が変わる箇所を確認する
- 旧記録で `3405` を使っていた箇所は、履歴として残すべきか、是正記録として追記すべきかを区別する
- `merge_*_wgs84` は本流から外れているため、正本 CRS 是正後も復活させない

## 参考
- `src/preprocessing/merge_map.py`: `EPSG:5897` を使っている既存実装
- `.github/prompts/completed/20260513_convert_elevation_to_CSV.prompt.md`: CSV タスクで `EPSG:5897` に修正済み
- `.github/prompts/completed/20260513_rework_analysis_flow_without_merge_wgs84.prompt.md`: `3405` 前提で完了した直前タスク

---

## 進捗記録

**最終更新日**: 2026-05-15  
**ステータス**: 完了

### 実施内容
- `src/analysis/calc_urban_params.py` の `analysis_epsg` と測量 GIS レイヤの `crs_epsg` を `EPSG:5897` へ修正
- `src/analysis/analyze_spatial_extents.py` の正本 CRS 前提とレポートキーを `EPSG:5897` / `gis_merge_from_5897` へ修正
- `src/analysis/analyze_data_status.py` の未定義 CRS 推定を `EPSG:5897` 前提へ修正
- `docs/02_methods/analysis_workflow.md`, `docs/02_methods/calc_urban_params_guide.md`, `docs/03_results/survey_gis_data_preparation_status.md` の正本 CRS 記述を `EPSG:5897` へ更新
- `.github/prompts/completed/20260513_rework_analysis_flow_without_merge_wgs84.prompt.md` に、`EPSG:3405` 前提だったことへの是正注記を追加
- `data/output/spatial_extent_report.json` を再生成し、`gis_merge_from_5897` を持つレポートへ更新

### 関連更新
- `src/analysis/calc_urban_params.py`
- `src/analysis/analyze_spatial_extents.py`
- `src/analysis/analyze_data_status.py`
- `docs/02_methods/analysis_workflow.md`
- `docs/02_methods/calc_urban_params_guide.md`
- `docs/03_results/survey_gis_data_preparation_status.md`
- `.github/prompts/completed/20260513_rework_analysis_flow_without_merge_wgs84.prompt.md`
- `data/output/spatial_extent_report.json`

### 検証・確認
- `src/preprocessing/merge_map.py` では既に `EPSG:5897` が使われている
- `python -m py_compile src/analysis/calc_urban_params.py src/analysis/analyze_spatial_extents.py src/analysis/analyze_data_status.py` は成功
- `C:\Users\takum\miniconda3\envs\masterresearch\python.exe -m src.analysis.analyze_spatial_extents` でレポート再生成に成功
- 再生成後の `data/output/spatial_extent_report.json` には `gis_merge_from_5897` が存在し、`gis_merge_from_3405` は含まれない
- 実行時に `GDAL_DATA is not defined` 警告は出たが、レポート生成自体は完了した

### 補足
- `conda run -n masterresearch ...` は現環境で文字コード由来のエラーが出たため、環境内の Python 実体を直接指定して実行した
