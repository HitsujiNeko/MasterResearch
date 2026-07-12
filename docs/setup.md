# Setup

**最終更新**: 2026-07-12  
**関連ドキュメント**: [README.md](README.md), [setup/qgis_mcp_setup.md](setup/qgis_mcp_setup.md), [../.github/task-workflow.md](../.github/task-workflow.md)  
**対象**: このリポジトリを新しい端末で再現可能にセットアップする人

---

## 1. 方針

このリポジトリの環境構築は、**`environment.yml` を正本**として進める。  
GeoPandas / Fiona / Rasterio / GDAL を含むため、`pip install -r requirements.txt` を環境構築の起点にはしない。  
**Conda 環境を唯一の実行環境**とする。

---

## 2. 前提

- OS: Windows
- Conda または Miniconda を利用可能であること
- リポジトリのルートで作業すること
- Google Earth Engine を使う場合は、Google アカウントと GCP プロジェクトを用意していること

---

## 3. 環境構築

リポジトリのルートで実行する。

```powershell
conda env create -f environment.yml
conda activate masterresearch
```

既存環境を更新する場合:

```powershell
conda env update -f environment.yml --prune
conda activate masterresearch
```

Conda が未初期化で `conda activate` が通らない場合は、Miniconda の案内に従ってシェル初期化を行う。

---

## 4. Python 依存の確認

最小限、次の import が通れば GIS 系の主要依存と分析系依存は読み込めている。

```powershell
python -c "import ee, geopandas, fiona, rasterio, pyproj, shapely, pandas, numpy, scipy, sklearn, matplotlib, shap, requests, tqdm"
```

`ogr2ogr` は `environment.yml` の `gdal` に含まれる想定。次で確認する。

```powershell
ogr2ogr --version
```

---

## 5. Google Earth Engine 設定

### 5.1 認証

初回のみ実行:

```powershell
earthengine authenticate
```

または LST 計算時に `src.gee.gee_calc_LST` から対話認証を行ってもよい。

### 5.2 設定 CSV

[`data/input/gee_calc_LST_info.csv`](../data/input/gee_calc_LST_info.csv) を確認し、少なくとも以下を設定する。

- `roi_shapefile_path`
- `start_date`
- `end_date`
- `cloud_threshold`
- `valid_pixel_threshold`
- `output_epsg`
- `lst_method`
- `gee_project_id`
- `city_name`
- `drive_root_folder`
- `drive_export_folder`

---

## 6. 実行ルール

`src` はパッケージとして扱っているため、**`python -m ...` 形式で実行**する。  
基本は `conda activate masterresearch` 後に実行し、単発実行だけなら `conda run -n masterresearch ...` でもよい。

例:

```powershell
python -m src.analysis.analyze_spatial_extents
python -m src.analysis.calc_urban_params --city hanoi
python -m src.gee.gee_calc_LST
```

`python src/...` ではなく `python -m ...` を使うことで、パッケージ import を壊さない。

単発で repo ルートから実行したい場合:

```powershell
conda run -n masterresearch python -m src.analysis.analyze_spatial_extents
```

補助スクリプトを使う場合:

```powershell
.\scripts\project_python.ps1 -m src.analysis.analyze_spatial_extents
```

PowerShell の実行ポリシーで `.ps1` が使えない場合:

```powershell
.\scripts\project_python.cmd -m src.analysis.analyze_spatial_extents
```

---

## 7. セットアップ確認

初回セットアップ後に、以下を順に実行する。

### 7.1 空間範囲レポート

```powershell
python -m src.analysis.analyze_spatial_extents
```

期待結果:

- `data/output/spatial_extent_report.json` が更新される

### 7.2 都市構造パラメータ

```powershell
python -m src.analysis.calc_urban_params --city hanoi
```

期待結果:

- `data/output/urban_params/urban_params_hanoi.csv` が生成または更新される

### 7.3 LST 計算

```powershell
python -m src.gee.gee_calc_LST
```

期待結果:

- `data/output/gee_calc_LST_results.csv` が更新される
- 条件を満たした画像が Google Drive に export される

---

## 8. トラブルシュート

### `conda` が見つからない

- Miniconda / Conda をインストールする
- 新しいシェルを開き直す
- `conda --version` が通ることを確認する

### `conda activate masterresearch` が通らない

- Conda のシェル初期化を行う
- 代替として `conda run -n masterresearch ...` を使う

### `ModuleNotFoundError`

- `conda activate masterresearch` 後に再実行する
- `python -m ...` 形式で起動しているか確認する

### `ogr2ogr` が見つからない

- `conda activate masterresearch` を実行してから再試行する
- `ogr2ogr --version` が通るか確認する

### `gh` コマンドが見つからない

- GitHub CLI をインストールする（セクション 9.1 参照）
- 新しいシェルを開き直す
- `gh --version` が通ることを確認する

### `gh auth status` で未認証と表示される

- `gh auth login` を再実行する
- 認証後に `gh auth status` で `takumid0419` のアカウントが表示されることを確認する

### GEE 認証エラー

- `earthengine authenticate` を再実行する
- `gee_project_id` が正しいか確認する

### GDAL / Fiona / Rasterio / SHAP の import エラー

- `pip` で個別追加せず、`environment.yml` から環境を作り直す
- `conda env update -f environment.yml --prune` を試す

---

## 9. GitHub CLI のセットアップ

タスク管理ワークフロー（[task-workflow.md](../.github/task-workflow.md)）で `gh` コマンドを使用するため、GitHub CLI のインストールと認証が必要。

### 9.1 インストール

[GitHub CLI 公式サイト](https://cli.github.com/) からインストーラーを取得するか、winget で導入する。

```powershell
winget install --id GitHub.cli
```

インストール後、新しいシェルを開いて確認する。

```powershell
gh --version
```

### 9.2 認証

初回のみ実行する。ブラウザが開き、GitHub アカウントへの認証を求められる。

```powershell
gh auth login
```

対話形式で以下を選択する。

- `GitHub.com`
- `HTTPS`
- `Login with a web browser`（推奨）

認証後、状態を確認する。

```powershell
gh auth status
```

`Logged in to github.com account takumid0419` のように表示されれば完了。

### 9.3 追加スコープの付与

タスク管理ワークフローで GitHub Projects v2 を操作するため、`read:project` スコープが必要。ログイン直後は付与されていない場合があるため、以下を実行する。

```powershell
gh auth refresh -s read:project --hostname github.com
```

ブラウザで承認後、次のコマンドでスコープを確認する。

```powershell
gh auth status
```

`Token scopes` に `read:project` が含まれていれば完了。

### 9.4 リポジトリの確認

```powershell
gh repo view
```

リポジトリ情報が表示されれば、Issue・プロジェクト操作の準備が整っている。

---

## 10. コード品質チェック（ruff / pre-commit）

`ruff`（lint + format）と `pre-commit` は `environment.yml` に含まれる。設定は [`pyproject.toml`](../pyproject.toml)、フックは [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) を参照。なお、pre-commit は独自に ruff を取得するため、`ruff` コマンド（conda 側）とバージョンが異なる場合がある。結果を揃えたい場合はバージョンを固定するか、`pre-commit run -a` を利用する。
初回のみ、リポジトリのルートで pre-commit フックを有効化する。

```powershell
conda activate masterresearch
pre-commit install
```

手動で確認したい場合:

```powershell
ruff check .
ruff format --check .
```

差分を自動修正する場合:

```powershell
ruff check --fix .
ruff format .
```

---

## 11. QGIS MCP（Claude Code 連携）

Claude Code から QGIS を直接操作するための MCP サーバーが `.mcp.json` に設定済み。
QGIS プラグインのインストールや接続設定の詳細は [setup/qgis_mcp_setup.md](setup/qgis_mcp_setup.md) を参照。

---

## 12. CI（GitHub Actions）

`.github/workflows/ci.yml` により、PR作成時・`main` へのpush時に以下が自動実行される。

- `ruff check .` / `ruff format --check .`
- `pytest tests/`
- `npx --yes markdownlint-cli2@0.22.1 "**/*.md"`

Python系CI依存の導入はpipベース（`requirements.txt` + `pytest`/`ruff`）で、Markdown lintは
`npx --yes markdownlint-cli2@0.22.1` で実行する。本セットアップ（1章）の
**ローカル開発ではConda環境を唯一の実行環境とする方針は変更しない**。CIは大容量の研究データを必要としない
`tests/` 配下のユニットテストのみを対象とする軽量な検査であり、ローカル開発環境の構築手段は
引き続き `environment.yml` を正本とする。

---

## 13. リモートセッション（Claude Code on the web）

Claude Code on the web のクラウドセッションには Python 3.x（pip / pytest / ruff 含む）が標準でプリインストールされているが、
本プロジェクト固有の依存（geopandas・fiona・rasterio・pyproj・shapely・earthengine-api 等）は含まれない。
このため `.claude/settings.json` の **SessionStart hook** から [`scripts/install_pkgs.sh`](../scripts/install_pkgs.sh) を実行し、
クラウドセッション起動時にのみ依存を導入する。

### 13.1 仕組み

- `SessionStart` hook はセッション開始・resume のたびに実行される（Claude Code 起動後、リポジトリのクローンが確定した状態で走る）
- `scripts/install_pkgs.sh` は環境変数 `CLAUDE_CODE_REMOTE` が `"true"` の場合のみ処理を行う。ローカル（Windows + Conda）では即座に `exit 0` し、何もしない
- 主要パッケージが import 可能な場合はインストールをスキップし、起動レイテンシを抑える
- 未導入の場合のみ `pip install -r requirements.txt pytest` を実行する

依存リストは CI（[12章](#12-cigithub-actions)）と同じ `requirements.txt` を参照するため、二重管理にならない。

### 13.2 動作確認

Claude Code on the web で新規セッションを開始すると自動的に hook が実行される。手動での設定は不要。
セッション内で以下を実行し、テストが通ることを確認する。

```bash
pytest tests/
```

### 13.3 注意点

- hook はリポジトリにコミットされているため、環境を再作成しても手動設定は不要
- `scripts/install_pkgs.sh` は LF 改行を前提とする（`.gitattributes` で `*.sh` を `eol=lf` に固定済み。Windows 側の `core.autocrlf` によるコミット時の改行コード破壊を防止するため）
- hook は `bash` 経由で明示的に起動する（`chmod +x` によるGit実行ビット管理は、ローカルがWindows・`core.fileMode=false`のため信頼できないための対応）
- `cryptography`（`earthengine-api` → `google-auth` 経由の依存）がコンテナのシステム版 `cffi` と衝突し `ModuleNotFoundError: _cffi_backend` で失敗することが実測で確認されているため、`scripts/install_pkgs.sh` は `pip install --force-reinstall cffi cryptography` を自動実行する

---

## 14. 補足

- [`requirements.txt`](../requirements.txt) は参照用の最小一覧であり、環境構築の正本ではない
- セットアップ手順を変更した場合は、この `setup.md` も更新する
