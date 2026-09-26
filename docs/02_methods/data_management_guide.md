# データ管理ガイド（2層運用: Git + Google Drive）

**最終更新**: 2026-09-26  
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

ローカル `data/` と Google Drive は、それぞれ異なる役割を持つ。

| | ローカル `data/` | Google Drive |
|---|---|---|
| **役割** | スクリプト実行の正本（作業環境） | 永続保管 + PC間共有のハブ |
| **対象** | 全データ（軽量はGit、大容量はローカルのみ） | Git管理外の大容量ファイルのみ |
| **更新タイミング** | スクリプト実行時に随時 | 新データ生成・前処理完了後にアップロード |

- スクリプトは常にローカル `data/` を参照する（Driveを直接参照しない）
- Driveは「PCを変えても同じデータにアクセスできる」ための永続保管・共有用ハブであり、作業の正本ではない

---

## 3. Google Driveのフォルダ構成

ローカル `data/` のカテゴリ構成（`gis/`, `satellite/`）に揃えて、Drive側も以下の構成で固定化する。

```text
MasterResearch/
├── satellite/
│   ├── lst/
│   └── indices/
└── gis/
    ├── buildings/
    ├── roads/
    ├── boundaries/
    ├── dem/
    ├── lulc/
    ├── population/
    ├── nighttime_lights/
    ├── survey/
    ├── maps/
    └── raw/
```

- ルートフォルダは `MasterResearch/` 1つに集約する
- `data/input/`, `data/output/` は基本的にGit管理のためDriveには置かない
  - ただし `data/output/` 配下には `.gitignore` で除外した大容量ファイル（`satellite_only/*/*_dataset.csv`, `satellite_only/*/*_sample_100000.csv`, `urban_params/*.csv` 等）もローカルのみで存在する。これらのDrive同期要否は別途検討する
- `data/BSHorizon/` はDrive管理対象外（ローカルのみで管理する）

命名ルール:

- ファイル名は半角英数字 + アンダースコア
- 日付は YYYYMMDD

---

## 4. Claude Code からの Google Drive アクセス

Claude Code には Google Drive へのアクセス機能が組み込みで利用可能であり、`.mcp.json` への追加設定は不要。ファイル一覧取得・検索・ダウンロード・アップロードをClaude Codeから直接行える。

- **マウント運用は行わない**: どのPCでもGoogle Drive for desktopによるローカルドライブ化は行わない。MCP経由でのアクセスで十分とする
- **大容量ファイルのアップロード**: 数百MB〜GB級のファイルはMCP経由のインライン転送に向かないため、ユーザーがGoogle Drive for desktopやWebブラウザ経由で手動アップロードする
- **小容量ファイル**: メタデータJSONや軽量なベクタファイル等はClaude CodeからMCP経由でアップロード・取得して構わない

---

## 5. 大容量バイナリの除外方針

- `.tif` / `.gpkg` はサイズに関わらず一律Git追跡しない方針とする。共有はDrive経由で行う
- `.gitignore` は「新規追加」を防ぐだけで、既追跡ファイルには効かない
- 大容量バイナリを通常Gitで履歴管理すると、clone/pullが重くなる

このため、拡張子ベースの除外に加えて**パスベースの除外 + サンプル例外許可**を併用する。

---

## 6. データ配置原則

### 6.1 原則

1. **入力データと出力データを分離する** — 元データを保護し、再実行を容易にする
2. **データの分類軸はカテゴリ（用途）で統一する** — ファイル形式やソース名で分けない
3. **前処理で生成した空間データも、下流分析の入力であれば入力側に配置する** — 出自はファイル命名規則とGoogle Drive MCPでの検索により追跡する
4. **衛星由来データと GIS データは別カテゴリとして管理する** — 分ける基準は「由来が衛星かどうか」ではなく「本研究で自前に処理したかどうか」。センサ由来でも、配布元が完成品として提供するラスタ（夜間光・人口密度等）は公開GISデータとして `data/gis/{category}/` へ置く

### 6.2 配置先の判定ルール

| データの性質 | 配置先 | 例 |
|---|---|---|
| 衛星画像から**自前で処理した**空間データ | `data/satellite/` | Landsat 8 の LST GeoTIFF, NDVI, NDWI |
| **完成品として配布されている**衛星由来ラスタ | `data/gis/{category}/` | 夜間光（VIIRS DNB, VNP46A4）, 人口密度（WorldPop） |
| GIS 空間データ（由来を問わない） | `data/gis/{category}/` | 建物 GPKG, 道路, DEM, ROI, 地図 |
| 未加工のソースデータ | `data/gis/raw/` | geofabrik PBF |
| 軽量な設定・テキスト | `data/input/` | 設定 CSV, テキスト |
| 分析結果・ログ | `data/output/` | 正準グリッド・パラメータテーブル・分析用データセット（GeoPackage）, JSON レポート, ログ |
| BSHorizon関連データ | `data/BSHorizon/` | 入力CSV, 設定YAML, 出力TXT |

---

## 7. 本リポジトリでの運用ルール

### 7.1 .gitignore の方針

- 拡張子ベースのグローバル除外
  - `*.tif`, `*.tiff`, `*.gpkg`, `*.aux.xml`（大容量バイナリ）
  - 都市構造パラメータの出力（`data/output/grid/`・`data/output/params/`・`data/output/datasets/`）はすべて GeoPackage のため、この拡張子ベース除外でカバーされる。ディレクトリベースの追加は不要である
  - **ただし GeoPackage の付随ファイル（`-wal` / `-shm` / `-journal`）は `*.gpkg` に一致しない。** GeoPackage は SQLite であり、書き込みが中断されるとこれらが残る。`-wal` は本体に近いサイズまで成長しうるため、誤って追跡するとリポジトリが重くなる。通常は `src/common/geopackage.py` が書き出しの成功後に必ず削除するため残らないが、異常終了時は手動で確認する
- ディレクトリベースの除外
  - `data/gis/`（GIS 空間データ）
  - `data/satellite/`（衛星由来データ）
  - `data/output/satellite_only/*/*_dataset.csv`（大容量中間生成物）
  - `data/output/satellite_only/*/*_sample_100000.csv`（大容量サンプルCSV）
  - `data/output/limited/*/*_sample_*.csv`（大容量サンプルCSV。Limitedシナリオ分析）
  - `data/output/urban_params/*.csv`（都市構造パラメータCSV）
- ファイルベースの除外
  - `data/BSHorizon/input/merge_DH_elevation_points.csv`（正本 `data/output/survey_translated/merge_DH_elevation_points.csv` から `prepare_bs_horizon_input.py` で再生成可能なため）
- サンプル共有用フォルダは例外で追跡許可
  - `!data/samples/`
  - `!data/samples/**`

補足:

- `data/output/satellite_only/*/*_dataset.csv` はピクセル単位の大容量中間生成物を想定し、Git管理外とする
- `data/output/satellite_only/*/*_sample_100000.csv` も同様に大容量のため、Git管理外とする
- `data/output/limited/*/*_sample_*.csv` はLimitedシナリオ分析（`analysis_rq3_limited.py`）のサンプルCSV（1件あたり10MB超）を想定し、Git管理外とする

### 7.2 認証情報（APIトークン）の扱い

外部データ配布サービスのAPIトークン等の秘密情報は、**リポジトリ直下の `.env`（Git管理外）に集約する**。

| ファイル | 追跡 | 内容 |
|---|---|---|
| `.env` | **しない**（`.gitignore` で除外） | 実際のトークン値 |
| `.env.example` | する | 変数名と取得手順のみ。**値は書かない** |

- 読み込みは `src/common/env_file.py`（標準ライブラリのみ。外部依存を追加しない）。**`os.environ` は書き換えない**
- 優先順位は「コマンドライン引数での明示指定 → 環境変数 → `.env`」。環境変数を`.env`より優先することで、CIや一時的な上書きが`.env`を書き換えずに効く
- **`data/input/` には置かない**。同ディレクトリは「配下のファイルはGit追跡する」運用のため、秘密情報を置くと`.gitignore`の1行だけが漏洩を防ぐ状態になり、取り違えが起きやすい

#### 登録変数と有効期限

| 変数 | 用途 | 発行・再発行 | 有効期限 |
|---|---|---|---|
| `EARTHDATA_TOKEN` | NASA Earthdata。LAADS DAACからのBlack Marble（VNP46A4）取得 | [LAADS DAAC プロフィール](https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token)（事前に [Earthdata アカウント](https://urs.earthdata.nasa.gov/)が必要） | **正本は同ページの `Expires at`**。再発行すると変わるため、失効前に確認して `.env` を差し替える（2026-07-29 時点の発行分は 2026-09-25 08:41 EDT 失効） |

- **トークンの失効は取得の 401 として現れる**。取得スクリプトは「トークンが無効・期限切れの可能性」を示すメッセージを出すので、まず有効期限を疑う
- **トークンとは別に、対象プロダクトのデータ利用許諾への同意が要る**。未同意だと 401 ではなくライセンス同意ページへ 303 されるため、症状が似ていて紛らわしい。同意はブラウザで Earthdata にログインした状態で当該ページを開いて行う

### 7.3 既追跡の大容量出力の扱い

以下コマンドで、ローカルファイルは残したまま index から除外する。

```powershell
git rm --cached <tracked-generated-file>
git commit -m "Stop tracking generated outputs"
```

必要に応じて、将来的に履歴クリーンアップ（git filter-repo 等）を検討する。

正本から派生する入力ファイル（例: `data/BSHorizon/input/merge_DH_elevation_points.csv`）を
追跡解除する場合は、`git rm --cached` に加えて再生成用スクリプトを用意し、
下流パイプラインが要求する形式（ヘッダー有無・改行コード等）を維持したまま
いつでも再生成できることを確認してから解除する（例: `prepare_bs_horizon_input.py`）。

### 7.4 データインベントリの自動生成

`data/` は Git 管理外のため、リポジトリだけでは手元にどのデータがあるか分からない。
そこで `data/gis/` と `data/satellite/` を走査し、各ファイルのメタデータを
JSON として再生成できるインベントリスクリプトを用意している。

- **スクリプト**: `src/analysis/build_data_inventory.py`
- **出力**: `data/output/data_inventory.json`（Git 追跡対象・軽量。実行日時を記録）
- **記録内容**:
  - ラスタ（`.tif` / `.tiff`）: CRS・空間範囲・解像度・バンド数・nodata・dtype
  - ベクタ（`.gpkg` / `.shp` / `.geojson` / `.gml`）: レイヤ一覧・ジオメトリ種別・地物数・属性スキーマ・CRS
  - 共通: 相対パス・ファイルサイズ・更新日時
- **設計方針**: 手保守の台帳ではなく**スクリプトで再生成する成果物**とし、陳腐化を防ぐ。
  読み込みはメタデータのみ（全画素・全地物は読み込まない）。1ファイルの読み込み失敗は
  `error` として記録し、走査を止めない。

実行方法（conda 環境 `masterresearch` を使用）:

```powershell
# プロジェクトルートで実行
& "$env:USERPROFILE\miniconda3\envs\masterresearch\python.exe" -m src.analysis.build_data_inventory
```

新しいデータを配置・更新したら再実行して `data_inventory.json` を更新する。
存在の突合は check-drive-sync、内容面の把握は本スクリプトが担う。

### 7.5 結果JSONの来歴メタデータ（provenance）

結果JSONの数値が「どのコード・どの環境・どの入力から生成されたか」を遡れるよう、
結果JSONに来歴を `provenance` キーとして付与する。生成は
`src.common.summary.build_provenance` が担い、各スクリプトは保存直前のサマリー辞書へ
`summary["provenance"] = build_provenance(...)` として追加する。

- **既存スキーマとの関係**: `provenance` キーの追加のみとし、既存キーの移動・改名は行わない
- **記録内容**:

| キー | 内容 |
|---|---|
| `script` | 実行スクリプトの識別名（例: `src.analysis.diagnose_nodata_dropout`） |
| `executed_at` | 来歴を生成した時刻（UTC・ISO 8601）。呼び出し側が指定しない場合は保存直前の時刻となり、実行開始時刻ではない |
| `python_version` / `platform` | Python のバージョンと OS |
| `git.commit` / `git.dirty` | コミットハッシュと、コード（`src/` 配下。未追跡ファイルを含む）の未コミット変更の有無。`dirty` が `true` の場合、コミットだけでは生成時のコードを復元できない。結果ファイル等のコード以外の変更は判定に含めない。git を利用できない環境では両方 `null` |
| `packages` | 主要ライブラリ（numpy・pandas・scikit-learn・shap・geopandas・rasterio・shapely・pyproj・pyogrio）のバージョン。未インストールは `null` |
| `inputs` | 入力ファイルの `path`（可能ならプロジェクト相対）と `sha256` のリスト。プロジェクトルート外のパスは絶対パスのまま記録されるため、入力はプロジェクト内（`data/` 配下）に配置して実行する |

- **記録しないもの**: 乱数シード・モデルのハイパーパラメータ等の**実行パラメータ**は来歴に含めず、
  各スクリプトのサマリー側で記録する（来歴はコード・環境・入力の追跡に責務を限定する）
- **適用範囲**: 現時点では `src.analysis.diagnose_nodata_dropout` の
  `*_nodata_dropout_summary.json` に付与している。他の結果出力には、各スクリプトを次に
  改修する機会に順次適用する。付与前に生成した既存の結果JSONには `provenance` が無い
- **記録する入力の範囲**: どのファイルを渡すかは各スクリプトが決める（`build_provenance` は渡されたパスをそのままハッシュする）。
  欠測脱落診断では、データセット・ROI・参照ラスタを渡し、ROI の Shapefile は主ファイル（`.shp`）に加えて
  実在する付随ファイル（`.shx`・`.dbf`・`.prj`・`.cpg`）も渡す（座標系の再定義では `.prj` だけが変わるため）
- **注意**: 入力ハッシュは全バイトを読んで計算するため、大容量の GeoPackage・GeoTIFF では
  実行時間が延びる

---

## 8. 具体的な日次運用フロー

### 8.1 GEE Export直後

1. Google Driveの対象フォルダに保存先を統一する
2. ファイル名を規約に合わせる（都市_期間_指標_日付）
3. エクスポート結果を目視確認し、欠損や異常値を簡易チェックする

### 8.2 ローカル解析前

1. Claude Code の Google Drive MCP、またはGoogle Drive for desktop/Webブラウザから必要ファイルのみ取得する
2. ローカルでは `data/gis/{category}/` または `data/satellite/{category}/` に配置する
3. 解析後に生成される大容量出力はGitへ追加しない

### 8.3 解析完了後（必須）

1. 重要成果物はDriveに反映する
2. docs 側に更新記録を残す（対象都市、期間、生成日時、スクリプト名）
3. git status --short で大容量ファイルが追跡対象に入っていないことを確認する

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
- [ ] `.gitignore` の更新時は `docs/README.md` と本ガイドの記述も確認した

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
git rm --cached <tracked-generated-file>

# 変更確認
git status --short
```
