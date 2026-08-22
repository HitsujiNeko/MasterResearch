# calc_urban_params 設計再定義ガイド

**最終更新**: 2026-08-22
**関連ドキュメント**: [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md), [analysis_workflow.md](analysis_workflow.md), [available_gis_data.md](../01_planning/available_gis_data.md), [survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md), [CodingRule.md](CodingRule.md), [calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md), [calc_urban_params_processing_design.md](calc_urban_params/calc_urban_params_processing_design.md), [calc_urban_params_cli_verification.md](calc_urban_params/calc_urban_params_cli_verification.md)
**前提知識**: RQ1-RQ3、CRS（WGS84/投影座標系）、ラスタ/ベクタ処理の基礎

> 本ドキュメントは索引を兼ねたハブである。5〜11章は [calc_urban_params/](calc_urban_params/) 配下の3ファイルへ分割済み。各節がどのファイルにあるかは下記索引を参照。

---

## 索引

節単位で「どの節がどのファイルにあるか」を示す。1行要約とあわせて、必要な節と収録ファイルを本表だけで特定できる。

**欠番について**: 2章「再構築が必要な理由」・12章「今回の再構築ゴール」は、記述内容がいずれも再構築時点の経緯であり現在は参照されないため削除した（3〜11章は外部が節番号で正本指定しているため振り直していない）。

| 章・節 | 1行要約 | 収録ファイル |
|---|---|---|
| 1. 本ガイドの位置づけ | 実装設計書としての目的と、変数の採否・出力仕様・データソース候補の正本の切り分け | 本ファイル |
| 1.1 正本の境界 | 採否は `urban_structure_parameters.md`、出力仕様は `calc_urban_params_io_spec.md` 6章、データソース候補は `available_gis_data.md` が正本 | 本ファイル |
| 3. 用語と空間整合ルール | LST・公開GIS・測量GISの有効カバレッジの違いと、分析時の空間整合手順 | 本ファイル |
| 3.1 重要な前提 | LST・公開GIS・測量GISのカバレッジに関する前提 | 本ファイル |
| 3.2 分析時の空間整合 | ROIとシナリオ別GIS有効域の交差による分析対象の決定 | 本ファイル |
| 4. スコープ定義 | 算出フェーズ・結合フェーズの担当範囲と非担当範囲 | 本ファイル |
| 4.1 担当範囲 | 算出フェーズと結合フェーズの責務 | 本ファイル |
| 4.2 非担当範囲 | LST算出・モデル構築・可視化の対象外範囲 | 本ファイル |
| 5. 入力仕様（再定義） | 必須入力・パラメータセット別入力（GIS）・任意入力（衛星指標・LSTラスタ） | [calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) |
| 6. 出力仕様 | 出力構成・パラメータテーブル・品質管理列・GIS由来パラメータ・分析用データセット・新旧差異 | [calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) |
| 7. 処理設計 | モジュール構成・関数責務・正準グリッド・格子整合・入力レイヤ読み込み | [calc_urban_params_processing_design.md](calc_urban_params/calc_urban_params_processing_design.md) |
| 8. CRS・単位ルール | 投影座標系・単位の統一ルール | [calc_urban_params_processing_design.md](calc_urban_params/calc_urban_params_processing_design.md) |
| 9. 例外処理と堅牢性 | 入力欠損・異常値への対応方針 | [calc_urban_params_processing_design.md](calc_urban_params/calc_urban_params_processing_design.md) |
| 10. CLI仕様 | 算出フェーズ・結合フェーズのコマンドラインオプション | [calc_urban_params_cli_verification.md](calc_urban_params/calc_urban_params_cli_verification.md) |
| 11. 検証項目（最低限） | ユニットテスト・旧wide CSVとの値照合・QGISでの目視確認・人口密度・夜間光のCLI検証結果・人口密度と夜間光の目視確認（画像保存） | [calc_urban_params_cli_verification.md](calc_urban_params/calc_urban_params_cli_verification.md) |
| 13. 更新ルール | 実装変更時の同時更新・履歴記録・カタログ整合の維持 | 本ファイル |

---

## 1. 本ガイドの位置づけ

本ドキュメントは、都市構造パラメータ算出処理（`src/analysis/urban_params/` パッケージ）の設計正本です。  
次の目的を持つ実装設計書として扱います。

- 都市構造パラメータ算出処理の責務を再定義する
- GIS由来と衛星由来の説明変数を同一フレームで扱う
- LSTとの空間整合ルール（ROI→GIS有効域）を明文化する
- 再現可能な入出力仕様を固定する
- `Satellite Only` / `Limited` / `Full` の3シナリオ・複数スケール（30/90/300m）で使える設計を明文化する

### 1.1 正本の境界

説明変数をめぐる記述は3つのドキュメントに分かれる。**「採用済みパラメータの出力仕様」の正本は [calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) 6章であり、本ガイドはその参照先を示す**。

| 内容 | 正本 |
|---|---|
| どの説明変数を採用するか（採否ステータス・概念定義・単位・根拠文献・対応RQ） | [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) |
| **採用済みパラメータの出力仕様（列名・算出方法・実装状況）** | **[calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) 6章** |
| データソースの候補比較・空間解像度・ライセンス | [available_gis_data.md](../01_planning/available_gis_data.md) とそのカテゴリ別ドキュメント |

したがって**本ガイドには採否ステータス（採用 / 保留 / 不採用）を書かない**。採否は上記の正本を参照する。

「採否」と「設計」は独立した軸であり、「**採用済みだが設計未確定**」という状態が生じる。本ガイドで「設計未確定」と記すのは後者の軸を指し、採否が未確定であることを意味しない。

> 旧実装 `src/analysis/calc_urban_params.py`（30m・単一シナリオの探索版）はfrozenとして残置されており、新規実装・実行はすべて `src/analysis/urban_params/` パッケージ（`python -m src.analysis.urban_params`）を使用する。

研究手順の根拠は [analysis_workflow.md](analysis_workflow.md) と整合させる（`analysis_workflow.md` 3.1 は [urban_structure_parameters.md](../01_planning/urban_structure_parameters.md) への参照に置き換わっている）。

---

## 3. 用語と空間整合ルール

### 3.1 重要な前提

- LSTはGEE算出時点でROI（行政区画）にクリップ済み
- 公開 GIS は ROI 全体を覆える場合があるが、データセットごとに有効カバレッジが異なる
- 測量GISはROI内の一部（中心部の矩形領域）である

### 3.2 分析時の空間整合

1. LSTはROIクリップ済みデータを入力する  
2. `Limited` では公開 GIS の有効カバレッジ、`Full` では測量 GIS 有効域で分析対象を限定する  
3. その結果、LSTとの結合時には「ROI内かつシナリオごとのGIS有効域内」のセルが対象になる

> これは不整合ではなく、処理段階の違いである。

---

## 4. スコープ定義（本スクリプトが担う範囲）

### 4.1 担当範囲

処理は**算出フェーズ**と**結合フェーズ**の2段に分かれる。

**算出フェーズ**（`src/analysis/urban_params/`）

- 正準グリッド（[calc_urban_params_processing_design.md](calc_urban_params/calc_urban_params_processing_design.md) 7.5節）に整合したマルチスケールグリッドの生成（計算は投影座標系）
- GIS由来パラメータ算出
- 衛星由来ラスタ指標のグリッド集約（任意入力）
- **パラメータセット単位の独立したテーブル**（`cell_id` キーのGeoPackage）の出力

**結合フェーズ**（`src/analysis/build_dataset.py`）

- 指定したテーブル群の `cell_id` による結合
- 結合した列からの品質管理列の導出
- 分析用データセットの出力

### 4.2 非担当範囲

- LST算出（`src/gee/gee_calc_LST.py`）
- モデル構築・評価（RQ1-RQ3の回帰/ML処理）
- 可視化スクリプト

---

## 13. 更新ルール

- 実装変更時は本ガイドを同時更新する
- 列名・単位・欠損規則を変更した場合は必ず履歴に残す
- `docs/README.md` のカタログ情報と齟齬を作らない
