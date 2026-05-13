---
agent: agent
---

# タスク: `merge_*_wgs84.gpkg` を使わない前提で分析フローを再設計する

## 概要
`data/output/gis_wgs84/merge_*_wgs84.gpkg` に系統的な位置ずれが確認されたため、これらを分析本流から外し、測量 GIS の正本を `整備データ/merge/merge_XX.gpkg` に統一する。

CRS は `EPSG:3405` を正とし、GEE 由来ラスタや公開 GIS と連携する場面だけ、その場で必要最小限の再投影を行う運用へ切り替える。

## 目的
1. `merge_*_wgs84.gpkg` を分析本流から外す。
2. `merge_XX.gpkg (EPSG:3405)` を正本として扱う。
3. 旧 WGS84 変換スクリプトと関連参照を整理する。
4. ドキュメントと運用ルールを新方針に合わせて更新する。

## 主な対象
- `整備データ/merge/merge_XX.gpkg`
- `src/analysis/calc_urban_params.py`
- `src/analysis/analyze_spatial_extents.py`
- `docs/02_methods/analysis_workflow.md`
- `docs/02_methods/calc_urban_params_guide.md`
- `docs/02_methods/data_management_guide.md`
- `docs/03_results/survey_gis_data_preparation_status.md`

---

` .github/copilot-instructions.md ` を参照し、関連ドキュメントに従って進めること。

---

## 完了時の記録

**完了日**: 2026-05-13  
**ステータス**: completed

### 実施内容
- `calc_urban_params.py` を `整備データ/merge/merge_*.gpkg` 直読みに切り替え、測量 GIS の正本を `EPSG:3405` として扱う構成へ変更した。
- `analyze_spatial_extents.py` の `gis_wgs84` 依存を外し、`merge_*.gpkg` をその場で WGS84 換算して bbox を比較する方式へ変更した。
- 旧スクリプト `src/preprocessing/convert_gis_to_wgs84.py`, `src/preprocessing/convert_to_wgs84_ogr.py`, `src/analysis/find_gpkg_outliers.py` を削除した。
- `data/output/gis_wgs84` を削除し、旧 WGS84 変換成果物を運用対象から外した。
- `docs/02_methods/data_management_guide.md`, `docs/03_results/survey_gis_data_preparation_status.md`, `.github/EFFICIENCY_PROPOSAL.md` などの参照を整理した。

### 生成・更新物
- `data/output/spatial_extent_report.json`
- `src/analysis/calc_urban_params.py`
- `src/analysis/analyze_spatial_extents.py`
- `docs/02_methods/data_management_guide.md`
- `docs/03_results/survey_gis_data_preparation_status.md`
- `.github/EFFICIENCY_PROPOSAL.md`

### 削除したファイル
- `src/preprocessing/convert_gis_to_wgs84.py`
- `src/preprocessing/convert_to_wgs84_ogr.py`
- `src/analysis/find_gpkg_outliers.py`
- `data/output/gis_wgs84/`

### 検証
- `python -m py_compile src/analysis/calc_urban_params.py src/analysis/analyze_spatial_extents.py`
- `python -m src.analysis.analyze_spatial_extents`

### 補足
- `docs/02_methods/analysis_workflow.md` と `docs/02_methods/calc_urban_params_guide.md` には関連する別タスクの変更が含まれるため、このタスクのコミット単位とは切り分けて扱う。
