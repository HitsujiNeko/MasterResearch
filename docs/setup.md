# Setup

**最終更新**: 2026-03-24  
**関連ドキュメント**: [README.md](README.md), [02_methods/gee_calc_LST.md](02_methods/gee_calc_LST.md), [02_methods/calc_urban_params_guide.md](02_methods/calc_urban_params_guide.md)  
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

- `data/csv/analysis/urban_params_hanoi.csv` が生成または更新される

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

### GEE 認証エラー

- `earthengine authenticate` を再実行する
- `gee_project_id` が正しいか確認する

### GDAL / Fiona / Rasterio / SHAP の import エラー

- `pip` で個別追加せず、`environment.yml` から環境を作り直す
- `conda env update -f environment.yml --prune` を試す

---

## 9. 補足

- [`requirements.txt`](../requirements.txt) は参照用の最小一覧であり、環境構築の正本ではない
- セットアップ手順を変更した場合は、この `setup.md` も更新する
