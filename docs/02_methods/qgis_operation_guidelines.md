# QGIS 運用ガイドライン

**最終更新**: 2026-07-23
**関連ドキュメント**: [qgis_mcp_usage_guide.md](qgis_mcp_usage_guide.md), [qgis_mcp_setup.md](../setup/qgis_mcp_setup.md), [data_management_guide.md](data_management_guide.md), [CLAUDE.md](../../CLAUDE.md)
**前提知識**: QGIS MCPのセットアップ完了、CRS・LSTの定義（[CLAUDE.md](../../CLAUDE.md)の用語集）

---

## 概要

Claude Code経由でQGISを操作する際に守るべきルールを定義する。

## ディレクトリ構成・保存先ルール

```text
qgis/
├── projects/    # 都市単位のQGISプロジェクト（.qgz）。Git管理外（ローカルのみ）
├── styles/      # 再利用スタイル（.qml）。Git追跡
└── templates/   # 印刷レイアウトテンプレート（.qpt）。Git追跡
```

- `qgis/projects/*.qgz` はローカル環境ごとに保持し、Gitでは共有しない（`.gitignore`で除外）。レイヤーパスは相対パスで保存する（下記参照）ため、`git clone`後もリポジトリ内の同じ相対位置に置けばレイヤー参照は解決できるが、**レイヤーグループ・Map Theme・スタイル適用等の構成自体は自動復元されない**。再構築する場合は[qgis_mcp_usage_guide.md](qgis_mcp_usage_guide.md)のユースケースに沿って手動で組み直す
- `qgis/styles/`・`qgis/templates/`はチームで共有する成果物のためGit追跡する

## レイヤー命名規則

- **レイヤーグループ**: データカテゴリ名（例: `ROI`, `建物`, `道路`, `DEM`, `衛星指標`, `測量データ`。日本語を基本とし、`ROI`・`DEM`等の一般的な略称はそのまま使う）
- **レイヤー名**: データソース略称＋カテゴリ名（例: `GBA建物`, `OSM道路`）、または技術的な識別子をそのまま使用（例: `FABDEM`, `LST_20230707_032305Z`）。取得日時を含むファイル名は識別性を優先しそのまま使う
- 測量データは`測量_{略称}`の形式（例: `測量_CS`）とし、[survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)の略称定義に合わせる

## CRS統一方針

- プロジェクトのCRSは**EPSG:4326（WGS84）を基準**とする（[CLAUDE.md](../../CLAUDE.md)の用語集に準拠）
- 面積・距離計算やバッファ処理など投影座標系が必要な処理では、都度適切なUTM等の投影座標系に変換する（データを恒久的に再投影しない。プロジェクトCRSはEPSG:4326のまま維持する）
- ベトナム測量データ（VN-2000）を読み込む場合は、レイヤーのCRSがVN-2000のまま正しく認識されているか`get_layer_crs`で確認し、必要に応じて`transform_coordinates`でEPSG:4326に変換して重ね合わせる

## execute_code / execute_processing の値取得

### execute_code の戻り値は stdout のみ

`execute_code`は実行したコード内の変数（例: `result`）に値を代入しても、その値を返却しない。戻り値は `{"executed": true, "stdout": "", "stderr": ""}` の形式で、変数の中身は含まれない。**計算結果・レイヤー情報などを取得したい場合は、`print`で標準出力に書き出す必要がある**。

日本語やネストした構造を安全に受け渡すため、`json.dumps(..., ensure_ascii=False)` で出力する。

```python
import json

# layer は対象のレイヤー。例では現在のアクティブレイヤーを取得する
# （名前で取得する場合は QgsProject.instance().mapLayersByName("レイヤー名")[0]）
layer = iface.activeLayer()
result = {"count": layer.featureCount(), "crs": layer.crs().authid()}
print(json.dumps(result, ensure_ascii=False))  # これで stdout 経由で取得できる
```

`print`を書かずに変数へ代入するだけだと、`stdout`が空のまま返り、値を取得できない。

### execute_processing の出力先は実ファイルにする

`execute_processing()`の`OUTPUT` / `OUTPUT_TABLE`に`memory:...`を指定すると、**処理自体は成功するが、出力レイヤが`get_layers()`に現れず、`get_layer_features()`でも参照できない**（`Layer not found`となる）。後続で検証・比較する用途では、出力先に実ファイル（`.gpkg`等）を指定する。

```text
OUTPUT: <ABS_PATH>/data/tmp/buffer_result.gpkg   # 実ファイルを指定（memory: は使わない）
```

一時的な検証結果でも、参照するなら実ファイルに書き出す。片付けは[検証時のプロジェクト衛生](#検証時のプロジェクト衛生場面別のsave方針)の方針に従う。

## 大規模レイヤーの取り扱い（クラッシュ対策）

GBA建物データ（約307万件）や測量データ複数レイヤー（数十万件規模）を同時に可視化状態にした際、QGIS本体がクラッシュする事例が確認された。

**必須の対策**:

1. **レイヤー・グループ追加のたびに`save_project`でこまめに保存する**。クラッシュ時に未保存の作業（レイヤー構成・グループ・Map Theme設定等）がすべて失われるため
2. 全レイヤーを同時に可視化する操作（`Full`テーマの確認など）を行う前に、直前の状態を保存しておく
3. クラッシュ後は`ping`で再接続を確認し、`get_project_info`・`get_layer_tree`で状態を確認してから作業を再開する

### 大規模レイヤーを含むテーマへのレイヤ追加は描画を伴わない方式で行う

Map Theme に含まれるレイヤを追加・変更する際に`apply_map_theme()`を呼ぶと、そのテーマに含まれる大規模レイヤ（GBA建物 約307万地物 等）の描画が発生し、クラッシュ・長い待ち時間のリスクがある。

テーマを**適用せず**に、`execute_code`でテーマのレコードを直接操作すれば、描画を伴わず安全・高速にレイヤを追加できる。

```python
from qgis.core import QgsProject, QgsMapThemeCollection

# target_layer はテーマに追加する対象レイヤー（例: 名前で取得）
target_layer = QgsProject.instance().mapLayersByName("レイヤー名")[0]

collection = QgsProject.instance().mapThemeCollection()
record = collection.mapThemeState("Full")          # テーマのレコードを取得（描画なし）
layer_record = QgsMapThemeCollection.MapThemeLayerRecord(target_layer)
record.addLayerRecord(layer_record)                # レコードにレイヤを追加
collection.update("Full", record)                  # テーマを更新（描画なし）
```

`apply_map_theme()`はテーマの内容を確認・確定したい最終段階でのみ使い、レイヤ構成の編集中は上記の方式を用いる。

### 検証時のプロジェクト衛生（場面別のsave方針）

QGIS-MCP は「現在開いているプロジェクト」に対して操作する設計のため、検証用に追加した一時レイヤや可視性変更が、ユーザーの作業中プロジェクトを汚したり誤って保存されたりするリスクがある。上記「クラッシュ対策」の「こまめに`save_project`」と場面が異なるため、以下のように切り分ける。

- **プロジェクトを意図して構築中**（レイヤ順・グループ・Map Theme を整えている）: 上記のとおり、レイヤ・グループ追加のたびに`save_project`でこまめに保存する（クラッシュ対策を優先）
- **一時的な検証・作図中**（アルゴリズムの突合や特定レイヤーの作図など、プロジェクトの永続構成を変えるつもりがない）: `save_project()`は**明示的に指示されない限り呼ばない**。可視性変更・テーマ適用・一時レイヤ追加を行った場合は、元の状態（テーマの再適用等）に戻し、追加した一時レイヤを`remove_layer()`で片付けてからセッションを終える

両者は排他ではなく「今どちらの場面か」で判断する。判断に迷う場合は、プロジェクトの永続構成を変える意図があるかで切り分ける。

## データ取得タスクにおけるスタイル成果物（.qml）の扱い

`qgis/projects/*.qgz` は Git 管理外のため、レイヤーグループ・Map Theme・スタイル適用の構成は自動復元されない。**`.qml` が可視化設定を残せる唯一の永続成果物**である。データ取得タスクでは、以下の判定に従ってスタイル（`.qml`）作成の要否を決める。

### スタイル作成要否の判定表

| データ型 | スタイル作成 | 理由 |
|---|---|---|
| カテゴリ値ラスタ（LULC 等）・コード値属性ベクタ | **必須** | 凡例なしでは内容判別が不可能 |
| 連続値ラスタ（人口密度・夜間光・不透水面率 等） | 任意 | 既定ストレッチで判読できる場合は不要 |
| 単純なポイント/ライン（POI・道路 等） | 不要 | — |

- 既存 `qgis/styles/` は LST・NDVI・NDBI・NDWI・DEM・建物被覆といった指標に加え、カテゴリ値ラスタの `lulc_glc_fcs30d.qml` で構成され、いずれも「凡例に意味があるデータ」である。一方、道路・建物フットプリントの生データ（単純なポイント/ライン）には `.qml` がない。この実態を踏まえた判定である
- 命名規則は `{カテゴリ}_{データセット}.qml`（英小文字スネークケース）を基本とし、**分類区分がデータセット固有の場合**に用いる（例: `lulc_glc_fcs30d.qml`）
- **例外**: 連続値ラスタで、複数データセットに同一の分類区分を適用して図を直接比較したい場合は `{カテゴリ}_{指標}.qml`（例: `population_density.qml`）とする。同じ色が同じ値を意味する図になり、データセット間の比較が可能になるため。既存の `dem_elevation.qml`・`lst_colorramp.qml`・`ndvi_classification.qml` もこの形である（`{データセット}` を含むのは分類がデータセット固有の LULC 2件のみ）
- 保存後は、プロジェクトを閉じて再度開き直し凡例が正しく表示されることを必ず確認する。**ラスタの疑似カラースタイル**は、これに加えて下記「ラスター疑似カラースタイル作成時の注意」の `classificationMin`/`classificationMax` が `nan` 化する破損チェックも実施する（ベクタの分類レンダラには当該項目はない）

### QGIS プロジェクト（.qgz）への追加は完了条件に含めない

`qgis/projects/*.qgz` は Git 管理外のため、プロジェクトへのレイヤ追加・Map Theme 更新・`save_project()` は**完了条件に含めない**。検証のための一時的なレイヤ追加は行い、プロジェクトに残すかは研究者の判断とする。

理由:

- `.github/ISSUE_TEMPLATE/task.md` は完了条件を「検証可能なチェック項目」と定めるが、ローカルの `.qgz` 状態は PR でレビューできず他環境でも再現しないため、チェック項目として機能しない
- `save_project()` は他タスクで構築中のレイヤ順・グループ構成・Map Theme を上書きする。並列 worktree 運用では複数タスクが同一プロジェクトを触るため、競合を Git で検知できない
- 「なぜ `.qml` だけが完了条件なのか」を残さないと、同じ問いが将来再発する

## データ取得タスクにおけるスクリーンショット（視覚的検証記録）の扱い

データ取得タスクでは、取得した空間データを QGIS で ROI と重ねて表示したスクリーンショット（PNG）をリポジトリにコミットする。目的はレビュアー向けエビデンスではなく、**著者自身による視覚的検証**（ROI カバレッジ・CRS ずれ・分布/外れ値の妥当性）と、**成果物の再利用**（進捗報告資料への転用）である。PNG は PR diff に現れてレビュー可能で、Git 管理外の `.qgz` に代わる**永続の視覚記録**になる（PR への画像添付操作は行わない）。

### 対象範囲

| 対象 | 判断 |
|---|---|
| 空間データ（ラスタ・ベクタを問わず） | **対象**（検証価値は普遍的なためデータ型で分岐しない） |
| 非空間データ（統計 CSV 等、地図に載らないもの） | 対象外 |

### 取得方法・構図

コミット用 PNG は再利用ヘルパー `src/visualization/qgis_figure.py`（`build_gis_figure` 等）で生成する。都度 PyQGIS を書かず、体裁を全図で統一するため。手動生成時も以下の構図要件に従う。

**構図要件**:

- **地図フレームは ROI と同じ縦横比で固定**し、ROI が見切れないようにする。凡例が必要な図はフレームを縮めず、ページを縦に伸ばして地図の下に凡例帯を置く
- **タイトル**（データセット＋ROI）と**スケールバー**（地図フレーム左下隅・枠内）は常時付与する
- **凡例**はデータ型で分岐する:
  - カテゴリ値ラスタ（LULC 等）・連続値ラスタ（DEM 等）: **必須**（前者は実在クラスに絞り、後者は項目表示にすると判読しやすい）
  - 単一シンボル（POI・道路・建物フットプリント等）: 不要（タイトルのみ）
- ROI 基準でズームし、カバレッジ・CRS 整合・分布/外れ値が判読できる構図とする
- 大規模レイヤは既存のクラッシュ対策（ROI 基準ズーム）に従う

**保存機構**:

- コミット用 PNG は `render_map(path=...)`、または印刷レイアウト export（`build_gis_figure` はこちら）で生成する
- `get_canvas_screenshot` は画像をインライン返却するのみで**ファイル保存しない**。即時の目視確認用であり、コミット用 PNG の生成には使わない

### 保存先・命名規則

- `images/gis_data/{カテゴリ}/{カテゴリ}_{データセット}_{ROI}.png`（英小文字スネークケース）
- 例: `images/gis_data/roads/roads_osm_hanoi.png`
- 複数枚必要な場合は `_overview` / `_detail` 等の接尾辞を付す
- `images/` は Git 追跡対象（`.gitignore` に `*.png` 除外はなく、直下 `images/` も除外対象外）

### スクリーンショットと `.qml` の関係（2 軸の整理）

スクリーンショットと `.qml` は目的の異なる別軸であり、両立させる。

| 成果物 | 目的 | 適用条件 |
|---|---|---|
| スクリーンショット（PNG） | **検証**（カバレッジ・CRS・分布の目視確認）・進捗資料転用 | 空間データに**普遍**（データ型で分岐しない） |
| `.qml` | **凡例/シンボロジ**（可視化設定の永続化） | 上記「スタイル作成要否の判定表」でデータ型により条件分岐 |

- 一方の要否が他方を左右することはない。スクショは空間データなら常に作成し、`.qml` は判定表に従う
- 保存先・命名の定型は `inspect-gis-data`（スクショ取得を担うスキル）に組み込む

## ラスター疑似カラースタイル作成時の注意（重要）

`execute_code`でPyQGISの`QgsSingleBandPseudoColorRenderer`を使ってLST・NDVI等のラスターに疑似カラースタイルを設定する場合、**`renderer.setClassificationMin()` / `setClassificationMax()` を色ランプの値域と一致させて必ず明示的に設定すること**。

**理由**: この設定を省略すると、実行中のQGISセッションでは正しく表示されるが（`legendSymbologyItems()`で検証しても正しい値が返る）、`.qml`・`.qgz`への保存時に`classificationMin`/`classificationMax`が`nan`としてシリアライズされ、**プロジェクトを閉じて再度開くとスタイルが破損し、すべての値が`nan`表示になる**。実行中セッションの見た目だけでは検知できない不具合のため注意する。

**対象レンダラー**: この`nan`化問題は、連続値の疑似カラーを扱う`QgsSingleBandPseudoColorRenderer`**固有**である。カテゴリ分類の`QgsPalettedRasterRenderer`（LULC 等のクラス値ラスタで使う）では`classificationMin`/`classificationMax`を持たないため発生しないことを確認済み。したがって`setClassificationMin`/`setClassificationMax`の明示設定が必要なのは`QgsSingleBandPseudoColorRenderer`のときに限られる。

**実装例**:

```python
from qgis.core import QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer
from qgis.PyQt.QtGui import QColor

fcn = QgsColorRampShader()
fcn.setColorRampType(QgsColorRampShader.Interpolated)
fcn.setColorRampItemList([
    QgsColorRampShader.ColorRampItem(20, QColor("#2166ac"), "20°C"),
    QgsColorRampShader.ColorRampItem(50, QColor("#b2182b"), "50°C"),
])
shader = QgsRasterShader()
shader.setRasterShaderFunction(fcn)

renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
renderer.setClassificationMin(20)   # 忘れると保存後にnan化する
renderer.setClassificationMax(50)   # 忘れると保存後にnan化する
layer.setRenderer(renderer)
```

**検証方法**: スタイル設定後は、実行中セッションでの確認だけでなく、**必ずプロジェクトを閉じて再度開き直し**、凡例の値が正しく表示されることを確認する。`.qml`ファイル単体の検証は以下のコマンドでも可能。

```powershell
Select-String -Path "qgis/styles/*.qml" -Pattern 'classificationM(in|ax)="nan"'
```

このコマンドで該当箇所がヒットした場合はスタイルが破損している（`QgsSingleBandPseudoColorRenderer`の場合）。

**レンダラー種別によらない往復検証手順**: `nan`化に限らずスタイルの保存・復元が正しく機能するかは、以下の往復（スタイル保存 → 別レイヤへ再適用 → 復元確認）で検証できる。カテゴリ分類（`QgsPalettedRasterRenderer`）でも連続値疑似カラーでも有効である。

1. スタイルを設定したレイヤで`save_style_qml()`（または`.qml`書き出し）を行う
2. 同じ元データを別レイヤとして読み込む
3. その別レイヤに`apply_style_qml()`で 1 の`.qml`を再適用する
4. **クラス数・各クラスの値・色・ラベルが元と一致して復元されるか**を確認する（カテゴリ分類ならクラス欠落がないか、疑似カラーなら値域が`nan`化していないか）

## Python 自前実装と QGIS ネイティブアルゴリズムの突合（クロスチェック）

Python での自前集計・幾何計算の正しさは、同一入力を QGIS ネイティブアルゴリズムにも通し、結果を突き合わせることで検証できる。実タスクで、ベクタ（線長集計）・ラスタ（クラス別画素数集計）の双方で有効性を確認済みである。

**実証例**:

- **ベクタ（線長集計）**: グリッドセルごとの道路線長を、Python 自前実装と`native:sumlinelengths`で算出し突合したところ、49セル中49セルが一致し、最大絶対誤差は約 1.3cm に収まった
- **ラスタ（クラス別画素数集計）**: 土地利用ラスタのクラス別画素数を、Python 自前集計と`native:rasterlayeruniquevaluesreport`で算出し突合したところ、総画素数・NoData・全15クラスで完全一致した

### 定型手順

1. Python で自前実装し、結果を得る
2. 同一入力を QGIS 処理系にも渡す
3. `get_algorithm_help()`でアルゴリズムのパラメータ・戻り値を事前確認する
4. `execute_processing()`を実行し、結果を**実ファイル**（`.gpkg`等）に出力する（`memory:`は使わない。理由は[execute_processing の出力先は実ファイルにする](#execute_processing-の出力先は実ファイルにする)を参照）
5. 両者を突合する（数値・件数・クラス構成などタスクに応じた観点で一致を確認する）
6. 検証のために現在のプロジェクトへ追加した一時レイヤは、検証後に必ず`remove_layer()`で片付ける（[検証時のプロジェクト衛生](#検証時のプロジェクト衛生場面別のsave方針)の方針に従う）

この手順は、自前実装の妥当性を確認したい任意のベクタ・ラスタ処理に適用できる。
