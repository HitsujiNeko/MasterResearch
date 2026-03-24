# Setup

**最終更新**: 2026-03-24  
**関連ドキュメント**: [README.md](README.md), [02_methods/gee_calc_LST.md](02_methods/gee_calc_LST.md), [02_methods/calc_urban_params_guide.md](02_methods/calc_urban_params_guide.md)  
**対象**: このリポジトリを新しい環境で再現する人

---

## 1. 方針

このリポジトリの環境構築は、**`environment.yml` を正本**として進める。  
GeoPandas / Fiona / Rasterio / GDAL を含むため、`pip install -r requirements.txt` 単独ではなく、
**Conda 環境の作成を標準手順**とする。

---

## 2. 前提

- OS: Windows
- Conda または Miniconda が利用可能
- リポジトリのルートで作業する
- Google Earth Engine を使う場合は Google アカウントと GCP プロジェクトがある

---

## 3. 環境作成

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

---

## 4. Python 依存の確認

最低限、次が import できれば GIS 系の基本依存は揃っている。

```powershell
python -c "import ee, geopandas, fiona, rasterio, pyproj, shapely, pandas, numpy, requests"
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

または、LST 算出時に `src.gee.gee_calc_LST` から対話認証を行ってもよい。

### 5.2 設定 CSV

[`data/input/gee_calc_LST_info.csv`](../data/input/gee_calc_LST_info.csv) の `gee_project_id` を確認する。

必須列:

- `roi_shapefile_path`
- `start_date`
- `end_date`
- `valid_pixel_threshold`
- `output_epsg`
- `lst_method`
- `gee_project_id`

---

## 6. 実行ルール

`src` はパッケージとして扱い、**`python -m ...` 形式で実行**する。

例:

```powershell
python -m src.analysis.analyze_spatial_extents
python -m src.analysis.calc_urban_params --city hanoi
python -m src.gee.gee_calc_LST
```

`python src/...` ではなく `python -m ...` を使うことで、パッケージ import を安定させる。

この端末で repo ローカル環境を使う場合は、次のどちらかを使う。

```powershell
.\.venv\Scripts\python.exe -m src.analysis.analyze_spatial_extents
```

または PowerShell セッション内で:

```powershell
. .\scripts\activate_project_python.ps1
python -m src.analysis.analyze_spatial_extents
```

PowerShell の実行ポリシーで `.ps1` が使えない場合は、`.cmd` ラッパーを使う。

```powershell
.\scripts\project_python.cmd -m src.analysis.analyze_spatial_extents
```

---

## 7. 動作確認

初回セットアップ後は、まず軽い確認として次を実行する。

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

- `data/csv/analysis/urban_params_hanoi.csv` が生成または更新される

### 7.3 LST 算出

```powershell
python -m src.gee.gee_calc_LST
```

期待結果:

- `data/output/gee_calc_LST_results.csv` が更新される
- 条件を満たした画像は Google Drive に export される

---

## 8. トラブルシュート

### `ModuleNotFoundError`

`python -m ...` 形式で起動しているか確認する。

### `ogr2ogr` が見つからない

- `conda activate masterresearch` を実行してから再試行する
- `ogr2ogr --version` が通るか確認する

### GEE 認証エラー

- `earthengine authenticate` を実行する
- `gee_project_id` が有効か確認する

### GDAL / Fiona / Rasterio の import エラー

- `pip` ではなく `environment.yml` から環境を作り直す
- `conda env update -f environment.yml --prune` を試す

---

## 9. 補足

- [`requirements.txt`](../requirements.txt) は補助的な依存一覧であり、環境再現の正本ではない
- セットアップ手順を変更した場合は、この `setup.md` を優先して更新する
