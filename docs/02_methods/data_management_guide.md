# データ管理ガイド（2層運用: Git + Google Drive）

**最終更新**: 2026-03-16  
**関連ドキュメント**: [analysis_workflow.md](analysis_workflow.md), [CodingRule.md](CodingRule.md), [../README.md](../README.md)  
**前提知識**: RQ1-RQ3の理解

## 1. 目的

本研究は、衛星画像（LST, GeoTIFF）や都市構造データ（GPKG）など大容量ファイルを扱う。  
本研究は個人研究であるため、運用負荷を抑えつつ再現性を確保できる**2層運用**を採用する。  
このガイドの目的は、以下を同時に満たすこと。

- 研究の再現性を維持する
- GitHub運用を軽量に保つ
- 研究期間中のデータ散逸を防ぐ

---

## 2. 基本方針（2層管理）

### Layer 1: Gitで管理するもの

- コード: src/
- ドキュメント: docs/
- 設定: .github/, .vscode/, .gitignore
- 軽量な表データ: data/input/*.csv, data/output/*.json
- 再現実行に必要な最小サンプル: data/samples/

### Layer 2: Google Driveで管理するもの

- 大容量ラスタ: data/output/LST/ 配下で生成される GeoTIFF
- 大容量ベクタ: data/output/gis_wgs84/*.gpkg
- GEEからExportされる配布前データ一式
- 原則として「成果物の実体」はDrive、「参照情報」はGitに保存

---

## 3. Google Driveの推奨フォルダ構成

以下のように、都市・年・データ種別で固定化する。

```text
MasterResearch_Data/
  LST/
    hanoi/
      2023/
      2024/
    osaka/
      2023/
  GIS_GPKG/
    wgs84/
      v20260316/
  snapshots/
    thesis_freeze_v1/
```

命名ルール:

- ファイル名は半角英数字 + アンダースコア
- 日付は YYYYMMDD
- バージョンは vYYYYMMDD（例: v20260316）
- 論文で使う確定データは snapshots/thesis_freeze_v1 のように凍結保存

---

## 4. Google Driveをマウントして使う

Windowsでは Google Drive for desktop を使い、Driveをローカルドライブとしてマウントできる。  
これにより、解析スクリプトからDrive上データを通常のパスとして参照できる。

推奨手順:

1. Google Drive for desktop をインストールする
2. ストリーミングモードでDriveをマウントする（容量節約のため）
3. マウント先（例: G:/My Drive/MasterResearch_Data/）を固定して使う
4. ローカル解析時は必要ファイルだけ同期し、処理後にDriveへ戻す

注意:

- 共同編集しない個人研究では、まずは手動同期で十分
- 巨大ラスタを常時ミラーリングするとローカル容量を圧迫しやすい

---

## 5. なぜ拡張子一律除外だけでは不十分か

- *.tif 一括除外は安全だが、共有すべき小サンプルも除外しやすい
- .gitignore は「新規追加」を防ぐだけで、既追跡ファイルには効かない
- 大容量バイナリを通常Gitで履歴管理すると、clone/pullが重くなる

このため、**パスベースの除外 + サンプル例外許可**を採用する。

---

## 6. 本リポジトリでの運用ルール

### 6.1 .gitignore の方針

- 再生成可能な重い出力は除外
  - data/output/LST/**/*.tif
  - data/output/LST/**/*.aux.xml
  - data/output/maps/**/*.tif
  - data/output/maps/**/*.aux.xml
  - data/output/gis_wgs84/*.gpkg
- 入力の大容量ラスタは除外
  - data/input/**/*.tif
- サンプル共有用フォルダは例外で追跡許可
  - !data/samples/
  - !data/samples/**

### 6.2 既追跡の大容量出力の扱い

以下コマンドで、ローカルファイルは残したまま index から除外する。

```powershell
git rm --cached data/output/gis_wgs84/*.gpkg
git commit -m "Stop tracking large generated gpkg outputs"
```

必要に応じて、将来的に履歴クリーンアップ（git filter-repo 等）を検討する。

---

## 7. 具体的な日次運用フロー

### 7.1 GEE Export直後

1. Google Driveの対象フォルダに保存先を統一する
2. ファイル名を規約に合わせる（都市_期間_指標_日付）
3. エクスポート結果を目視確認し、欠損や異常値を簡易チェックする

### 7.2 ローカル解析前

1. Driveから必要ファイルのみ取得する
2. ローカルでは data/temp/ または data/output/ に配置する
3. 解析後に生成される大容量出力はGitへ追加しない

### 7.3 解析完了後（必須）

1. 重要成果物はDriveに反映する
2. docs 側に更新記録を残す（対象都市、期間、生成日時、スクリプト名）
3. git status --short で大容量ファイルが追跡対象に入っていないことを確認する

---

## 8. データ目録（メタデータ）をGitで管理する

大容量実体をGitに入れない代わりに、以下の情報をCSVで管理する。

- 推奨ファイル: data/input/data_catalog.csv
- 最低限の列:
  - dataset_id
  - city
  - period
  - variable
  - crs
  - resolution_m
  - created_at
  - created_by_script
  - drive_path
  - notes

CSV例:

```csv
dataset_id,city,period,variable,crs,resolution_m,created_at,created_by_script,drive_path,notes
lst_hanoi_20230716,hanoi,2023-07-16,LST,EPSG:4326,30,2026-03-16,src/gee/gee_calc_LST.py,MasterResearch_Data/LST/hanoi/2023/,cloud<10%
```

---

## 9. LFS/DVCは将来拡張として扱う

本研究の現時点では、Git + Google Drive の2層で十分。  
ただし、以下の条件に該当したら追加導入を検討する。

- Git LFS: 中容量ファイルをGit的に追跡したくなった場合
- DVC: 時系列データ増加と再現実験管理が複雑化した場合

---

## 10. 最小運用チェックリスト

- [ ] 50MB超の新規ファイルを通常Gitへ追加していない
- [ ] 生成物は data/output/ に分離し、必要最小限のみ追跡
- [ ] 実験再現に必要なサンプルを data/samples/ に保持
- [ ] どのデータから結果を作成したかを docs/ と data_catalog.csv に記録

---

## 11. 補足: コマンド早見表

```powershell
# 追跡中の大きいファイルを確認（例: 50MB超）
git ls-files | ForEach-Object {
  if (Test-Path $_) {
    $size = (Get-Item $_).Length / 1MB
    if ($size -gt 50) { "{0}`t{1:N1} MB" -f $_, $size }
  }
}

# 既追跡の大容量出力を index から除外（ローカルは残る）
git rm --cached data/output/gis_wgs84/*.gpkg

# 変更確認
git status --short
```
