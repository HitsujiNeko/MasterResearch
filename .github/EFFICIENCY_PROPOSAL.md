# 研究環境の効率化提案書（実施状況サマリー）

**最終更新**: 2026-03-16

この文書は、研究環境の効率化提案の進捗管理用メモです。  
詳細手順は各ドキュメントに委譲し、本ファイルでは「実施済み / 未実施」のみを管理します。

---

## 実施済み

1. プロジェクト共通指示の導入
- `.github/copilot-instructions.md` を整備済み。

2. プロンプト構造の整理
- `.github/prompts/active/`, `.github/prompts/templates/`, `.github/prompts/completed/` を運用済み。

3. データ管理方針の整備（2層運用）
- `docs/02_methods/data_management_guide.md` を作成済み。
- 方針: Git（コード・軽量メタ情報） + Google Drive（大容量実データ）。

4. 大容量出力のGit追跡見直し
- `data/output/gis_wgs84/*.gpkg` を index 追跡から除外済み（ローカル実体は保持）。

5. LSTエクスポート先の設定化
- `src/gee/gee_calc_LST.py` を更新し、Driveフォルダ名を設定CSVから制御可能に変更済み。
- `data/input/gee_calc_LST_info.csv` に `city_name`, `drive_root_folder`, `drive_export_folder` を追加済み。

6. データ目録の初期整備
- `data/input/data_catalog.csv` を作成し、初期レコードを登録済み。

---

## 未実施

1. データ目録の自動更新
- `gee_calc_LST_results.csv` から `data_catalog.csv` に自動追記するスクリプトは未作成。

2. 運用チェックの自動化
- pre-commit や CI での大容量ファイル検知（例: 50MB超ブロック）は未導入。

3. タスク管理の外部連携
- GitHub Issues / Projects とプロンプト運用の連携は未導入。

4. クイックコマンド集
- `.github/references/quick_commands.md` は未作成。

5. LFS / DVC の段階導入
- 現在は2層運用で対応中。必要時に導入可否を再評価。

---

## 次回の優先実装（短期）

1. `data_catalog.csv` 自動追記スクリプトの作成
2. pre-commit による大容量ファイル誤コミット防止
3. クイックコマンド集の最小版作成
