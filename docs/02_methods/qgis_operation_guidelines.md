# QGIS 運用ガイドライン

**最終更新**: 2026-08-22
**関連ドキュメント**: [qgis_mcp_usage_guide.md](qgis_mcp_usage_guide.md), [qgis_mcp_setup.md](../setup/qgis_mcp_setup.md), [data_management_guide.md](data_management_guide.md), [CLAUDE.md](../../CLAUDE.md)
**前提知識**: QGIS MCPのセットアップ完了、CRS・LSTの定義（[CLAUDE.md](../../CLAUDE.md)の用語集）

---

## 概要

Claude Code経由でQGISを操作する際に守るべきルールを定義する。

## QGIS-MCP の既知の制約と回避策

上流（[nkarasiak/qgis-mcp](https://github.com/nkarasiak/qgis-mcp)）由来の制約を集約した台帳。**バージョン更新時はこの節の該当項目だけを再検証する**（ガイドライン全体を読み直さない）。

**全行を最後に再検証した版数: v0.9.3**（`.mcp.json`のピンと一致するとは限らない。ピンを上げても再検証していなければ更新しない）

### 台帳（上流由来の制約）

| 対象ツール | 症状 | 回避策 | 最小再現手順 | 確認バージョン |
|---|---|---|---|---|
| `render_map` | 可視性の変更が出力画像に反映されないことがあった（キャッシュされた合成結果を返している可能性を推定していた） | **不要（解消済み）**。可視性を切り替えた直後の`render_map`をそのまま使ってよい | 可視レイヤを`set_layer_visibility(visible=false)`にして`render_map`し、そのレイヤが消えているかを見る | v0.9.3（解消を実測） |
| `execute_processing` | `OUTPUT` / `OUTPUT_TABLE`に`memory:`を指定すると、処理は成功するが出力レイヤが`get_layers`に現れない | 出力先に実ファイル（`.gpkg`等）を指定する。詳細は[execute_processing の出力先は実ファイルにする](#execute_processing-の出力先は実ファイルにする) | `OUTPUT`に`memory:tmp`を指定してバッファを実行し、`get_layers`に現れるかを見る | v0.9.3（未解消を実測） |
| `execute_code` | 変数へ代入した値は返却されず、戻り値は`executed` / `stdout` / `stderr`のみ | `print(json.dumps(..., ensure_ascii=False))`で標準出力へ書き出す。詳細は[execute_code の戻り値は stdout のみ](#execute_code-の戻り値は-stdout-のみ) | `result = 1`だけのコードを実行し、`stdout`が空で返ることを見る | v0.9.3 |
| 破壊的ツール（`remove_layer` / `delete_features` / `execute_code` / `set_setting` / `delete_field` / `remove_layout` / `rollback_edits` / `execute_connection_sql` / `import_layer_to_connection`） | 上流は実行前の確認要求（elicitation）を実装しているが、**本環境では確認なしで即時実行される場合がある**（原因は上流側に特定できていない。[運用注意](#運用注意)を参照） | 確認が入る前提で運用しない。取り消せない即時実行として扱い、対象レイヤIDを実行前に確認する | **前提**: 検証対象ツールが`.claude/settings.local.json`の`permissions.allow`に登録されていないことを確認する（登録済みだとClaude Code側で自動承認され、上流の挙動を判定できない）。そのうえで一時レイヤに対し`remove_layer`を実行し、プロンプトの有無を見る | v0.9.3（`remove_layer`で非出現を実測） |

「確認バージョン」は**その行の内容を最後に実機確認した版数**であり、台帳全体の「全行を最後に再検証した版数」とは一致しないことがある。差が開いている行ほど再検証の優先度が高い。

### 台帳に入れない項目

MCPのバージョンと無関係な制約は台帳に載せず、現行の記述位置に残す。台帳の再検証対象を上流の変更で動きうるものだけに絞るためである。

- ラスタ疑似カラーの`classificationMin` / `classificationMax`の`nan`化（PyQGIS / QGIS由来）→ [ラスター疑似カラースタイル作成時の注意（重要）](#ラスター疑似カラースタイル作成時の注意重要)
- 大規模レイヤーでのクラッシュ（QGIS本体由来）→ [大規模レイヤーの取り扱い（クラッシュ対策）](#大規模レイヤーの取り扱いクラッシュ対策)
- CRS統一方針・レイヤー命名規則・`.qml` / スクリーンショット規約・検証時のプロジェクト衛生（いずれも研究固有の運用ルール）

### 運用注意

- **破壊的ツールの確認プロンプトを当てにしない**: 上流は v0.8.1 で確認要求を実際に機能させ、v0.9.0 で対象に`rollback_edits` / `execute_connection_sql` / `import_layer_to_connection`（上書き時）を加えた。ただし本環境（Claude Code + v0.9.3）では`remove_layer`・`execute_code`のいずれも確認なしで実行された。ここで言う「確認」には**上流の確認要求（elicitation）**と**Claude Code の許可プロンプト**の2系統があり、両者は独立している。`execute_code`は`.claude/settings.local.json`の`permissions.allow`に登録済みであり、非出現は後者だけで説明がつくため上流の挙動の根拠にならない。`remove_layer`は未登録のまま非出現だったが、上流の確認要求が本環境に届いていないのか許可モード側の要因かは**未確認**である。いずれにせよ確認は最後の砦にならないため、`remove_layer`の対象IDや`execute_code`の副作用は呼び出す前に自分で確認する
- **Windowsで別ウィンドウがポートを保持している場合、サーバー起動が拒否される**: v0.9.0 以降、既に他のQGISウィンドウが 9876 を掴んでいると、後から起動したウィンドウでのサーバー起動は失敗する（従来は2窓とも同じポートを掴み、一方が無言で全接続を受けていた）。接続先が不定にならなくなる代わりに起動失敗が明示されるため、**QGISを複数開いている場合は接続したいウィンドウ以外のサーバーを停止する**。本プロジェクトはWindows環境のため該当する

### 新規機能の採否記録

一度判定した機能は**次回以降のバージョン更新で再検討しない**。運用を変える場合のみ見直す。ただし**判定の理由が上流の実装に由来する場合は例外**とし（不採用・条件付き採用・用途限定の採用のいずれも対象）、その理由が解消されたときに限り再判定する。どの理由が上流依存かは理由欄に**上流依存**と明記する。

| 機能 | 採否 | 理由 |
|---|---|---|
| `execute_sql` | **採用** | v0.8.0 以前はラスタが1枚でも読み込まれていると全クエリが失敗したが、ラスタ6枚を含む本プロジェクトで`SELECT COUNT(*)`の成功を実測。レイヤー横断の集計・結合を`execute_code`なしで書ける |
| `batch_commands` | **条件付き採用** | 読み取り操作を1往復にまとめる用途に使う。破壊的ツール（`execute_code` / `remove_layer` / `delete_features` / `set_setting` / `reload_plugin`）はバッチに含められないため、本研究で頻度の高いPyQGIS実行・片付けは個別呼び出しのまま。この除外リストは**上流依存**であり、緩和されたときに再判定する |
| `get_layer_extent` | **採用（範囲確認のみ）** | 範囲の取得は軽量で有用。地物ゼロのレイヤーでは`{"empty": true}`を返す。ただし`crs`フィールドが空文字を返す実測があるため、**CRS判定には使わない**（[CRS統一方針](#crs統一方針)に従う）。`crs`が空文字を返す点は**上流依存**だが、CRS判定はpyogrio / rasterio側で行う方針のため、上流が修正されても結論は変わらない |
| `set_raster_style` | **不採用（単バンド疑似カラー用途）** | (1) `color_ramp`はQGISの名前付きランプのみで、任意の値・色・ラベルの組（`20°C=#2166ac` … `50°C=#b2182b`）を指定できず、生成されるのは等間隔アイテム・ラベルは数値のみ (2) `min_value` / `max_value`を明示しても`classificationMin` / `classificationMax`が`nan`になる（Interpolated・Discrete・min/max未指定の3ケースで実測）。**(1)が恒久的な根拠**であり、(2)は上流の実装依存で変わりうるため、再判定は(1)が解消されたときに限る。既存の`execute_code`手順を正本のまま残す。単バンドグレー・マルチバンドRGB・陰影起伏は疑似カラーほど配色仕様を要求しないため、必要が生じた時点で個別に判断する |
| データベース接続系（`list_connections` / `list_connection_tables` / `add_layer_from_connection` / `import_layer_to_connection` / `execute_connection_sql`） | **不採用（現時点）** | `list_connections`が0件であることを実測。本研究はGeoPackageを保存済み接続として登録せず絶対パスで直接読み込むため、利点がない。接続を登録する運用に変えた場合に再検討する |
| 編集セッション系（`start_editing` / `commit_edits` / `rollback_edits` / `undo_edits` / `redo_edits` / `update_feature_geometry`） | **不採用（現時点）** | 本研究のGISデータはPython側で生成・加工し、QGISは描画確認に用いる方針のため、QGIS上で地物を編集する場面がない |

v0.9.2 で修正された「非空間テーブルを含むプロジェクトで`get_layers` / `get_project_info`がプロジェクト全体で失敗する」不具合について、本リポジトリに回避のための運用制約は設けていなかったため、解除すべき記述はない。

### 追随ポリシー

`.mcp.json`でバージョンをピン留めしているため、上流が更新されても本プロジェクトの動作は変わらない。したがって**最新版へ常時追随しない**。

バージョンを上げるのは次のトリガに該当するときのみとし、それ以外は据え置く。

1. 台帳に登録済みの制約に対応する修正が上流に入ったとき（台帳の「対象ツール」列を上流の変更内容と突合して判定する）
2. 本研究で必要な機能・不具合修正が入ったとき

上流の更新を**見に行く**タイミングは、大きなQGIS作業セッションの前（目安として月1回）とする。これは確認の契機であって更新トリガではなく、1・2 に該当しなければ版数は据え置く。

トリガに該当しないリリース（他MCPクライアント向けの対応、上流のリリース手続き都合による版数上げ、本研究で使わないツールのみの変更など）は、リリースノートを読んだ時点で「無関係」として切り、記録も残さない。

**リリースノートは空または不完全なことがある**（v0.9.0・v0.9.1 が該当）。差分の把握にはコミット履歴も参照する。

### 更新チェックリスト

- [ ] 上記トリガに該当するかを判定する（該当しなければ更新しない）
- [ ] `.mcp.json`の参照タグを更新する（**使用中バージョンの正本はこのファイル**。セットアップ・運用手順に「使用中の版数」を書かない。台帳の「確認バージョン」「全行を最後に再検証した版数」および採否記録の実測時の版数は、検証履歴として残す）
- [ ] QGISプラグインを同一バージョンへ入れ替える
- [ ] Claude Codeを再起動する（**再起動するまでMCPサーバーは旧バージョンのまま**で、新ツールは一覧に現れない）
- [ ] `diagnose`で`version_match`が`ok`・`status: healthy`であることを確認する
- [ ] 台帳の各行を「最小再現手順」で再検証し、「確認バージョン」を更新する。解消していれば回避策を削除する
- [ ] 新規に使えるようになった機能の採否を判定し、採否記録へ追記する
- [ ] 台帳の全行を再検証し終えた場合に限り、「全行を最後に再検証した版数」を更新する

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
- **CRSの判定に`get_layer_crs`の`authid`・`is_geographic`を根拠として使わない**。空文字列・`srsid=0`・`is_geographic=false`を返す事例が実測されている。判定はrasterio / GeoPandas側で行い、QGISは描画確認に限定する（手順は[qgis_mcp_usage_guide.md の「CRSの確認手順」](qgis_mcp_usage_guide.md#crsの確認手順)を参照）
- ベトナム測量データ（VN-2000）を読み込む場合は、上記の手順でCRSがVN-2000のまま正しく認識されているかを確認し、必要に応じて`transform_coordinates`でEPSG:4326に変換して重ね合わせる。**`merge_*.gpkg` の正本CRSは`EPSG:5897`（VN-2000 / TM-3 zone 482）**である（推定根拠は[survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)を参照）

## execute_code / execute_processing の値取得

### execute_code の戻り値は stdout のみ

`execute_code`は実行したコード内の変数（例: `result`）に値を代入しても、その値を返却しない。戻り値は `{"executed": true, "stdout": "", "stderr": ""}` の形式で、変数の中身は含まれない。**計算結果・レイヤー情報などを取得したい場合は、`print`で標準出力に書き出す必要がある**。

日本語やネストした構造を安全に受け渡すため、`json.dumps(..., ensure_ascii=False)` で出力する。

```python
import json

# layer は対象のレイヤー。例では現在のアクティブレイヤーを取得する
# （名前で取得する場合は QgsProject.instance().mapLayersByName("レイヤー名")[0]）
layer = iface.activeLayer()
# CRS の判定に authid() は使わない（空文字列を返す事例がある。CRS統一方針を参照）
result = {"count": layer.featureCount(), "extent": layer.extent().toString()}
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

GBA建物データ（約307万件）や測量データ複数レイヤー（数十万件規模）を**対話キャンバスで同時に可視化状態にした際**、QGIS本体がクラッシュする事例が確認された。一方、描画範囲をROIに固定した単発描画は同規模のデータでも完走している。大規模レイヤーを無条件に避けるのではなく、以下の切り分けに従う。

### クラッシュ条件の切り分け

| 操作 | 判断 | 根拠 |
|---|---|---|
| 対話キャンバスで全件を同時可視化し`save_project`する | **危険** | GBA建物・測量データ複数レイヤーでクラッシュを確認 |
| 描画範囲をROIに固定した単発描画（`render_map`・印刷レイアウトexport） | **安全** | GBA建物（約307万件）・`測量_DC`（約46万件）でもクラッシュせず完走し、PNG12枚を生成できた |

ROI固定の単発描画が今回のデータ・ROI・描画方式（`render_map`・印刷レイアウトexport）で完走したのは、描画対象がROI内に限られ、全件の同時描画が発生しないためと考えられる。ただし描画方式・空間インデックス・ジオメトリ異常・メモリ使用量などに依存するため、**同規模データ全般での安全性を保証するものではない**。**外れ値ジオメトリによりレイヤーのextentが破綻するデータ**（測量データでは`測量_DH`・`測量_TH`にX=499,999／Y=999,999付近のダミー座標が記録されている。[survey_gis_data_preparation_status.md](../03_results/survey_gis_data_preparation_status.md)の座標範囲表を参照）でも、今回はROI内の実データのみが描画され問題は生じなかった。それでもクラッシュ・応答なしが発生する場合は、**ROIをさらに縮小する・レイヤーを分割して個別に描画する・単発描画を複数回に分けて実行する**などの代替策を検討する。

**必須の対策**（対話キャンバスで作業する場合）:

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

## グラフィカルな属性分類（Quantile等）でのクラッシュ

`QgsGraduatedSymbolRenderer.createRenderer()` に `Mode.Quantile` を渡すと、複数テーブルを結合した多列（cell_id結合5テーブル・19列）・38,235件のベクタレイヤに対する分類走査で、QGIS本体が応答不能になった事例がある。`execute_code`の応答がソケットタイムアウトし、以降`ping`も含めQGIS-MCPサーバー自体に接続できなくなった（プラグイン・QGIS本体の再起動が必要だった）。件数自体は「大規模レイヤーの取り扱い」の対象（GBA建物約307万件等）に比べて小さく、結合による列数の多さか、Quantile分類が内部で行う全件ソートが負荷になったかは**未確認**である。

**回避策**: `NULL` / `NaN`（有効画素なしのセル）を除外した有限値について、QGIS外（Python + `pyogrio` / `numpy.percentile`等）で分類の境界値を事前計算し、`QgsRendererRange`を境界値から手動構築して`QgsGraduatedSymbolRenderer`に設定する。QGIS側では計算済み境界に色を割り当てるだけで済み、分類走査（`createRenderer`のmode計算）を行わずに済む。EqualInterval等の均等分類（`set_layer_style`ツールの既定）は同条件で試していないため、Quantileモード固有の問題かは切り分けられていない。

**欠損値の扱い**: `numpy.percentile`は入力に`NaN`が含まれると結果へ伝播させる（`NaN`を無視しない）ため、境界値の計算前に`values[np.isfinite(values)]`等で有限値のみへ絞り込む。実測値`0`は欠損ではないため除外してはならない。境界を`QgsRendererRange`で範囲指定すると、値が`NULL`（`NaN`）のセルはどの範囲にも属さず、既定では非表示（透過）になる。これは意図した挙動であり、有効画素なしのセルを可視化上も欠測として扱える。

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

### カテゴリ値ラスタの公式配色の確認順序

カテゴリ値ラスタの公式配色は、配布元のメタデータに含まれない場合がある。以下の順序で確認し、**記憶や一般に流布した値で埋めない**。

1. **配布元のメタデータ**を確認する（STAC配信ならコレクションのmetadata、それ以外なら配布元が提供するメタデータファイル）
2. **ソースラスタに埋め込まれたカラーテーブル**を確認する。COGなら署名付きURLで`rasterio.open()`し、ヘッダーのみ読めば全体をダウンロードせずに実測できる
3. **データセットの公開ドキュメント**を確認する

Esri LULC（`io-lulc-annual-v02`）では、STACコレクションの`item_assets.data.file:values`がクラス値とラベル（英語）を持つ一方、配色は含まれていなかった。ソースCOGにはGDALカラーテーブルが埋め込まれており、手順2で公式配色を実測できた。

**注意**: 窓読みで保存したサブセットにはカラーテーブルが引き継がれない。ローカルの取得済みファイルを見ても配色は分からないため、ソース側を確認する。

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
- **タイトル**（データセット＋ROI）と**スケールバー**（地図フレーム左下隅・枠内）は常時付与する。タイトルは `{データセット} {データ種別} {年} － {ROI}` の書式に統一する（例: `GLC_FCS30D 土地被覆 2022 － Hanoi ROI`）。`build_gis_figure` は `title_text` をそのまま使うため、**書式の統一はヘルパー側では担保されない**
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
- **算出結果の図**（取得データではなく、分析パイプラインが出力した値を描いたもの）は `images/{パッケージ名}/{パッケージ名}_{列名}_{ROI}_{スケール}.png` とする。例: `images/urban_params/urban_params_build_cov_hanoi_300m.png`。取得データの図と混在させないのは、両者で「何を検証しているか」（データのカバレッジか、算出値の妥当性か）が異なるためである
- 複数枚必要な場合は接尾辞を付す。`_overview` / `_detail`（空間スケールの違い）、`_{年}`（同一データセットの複数年）が該当する
- **同一タスク内で並べる図は接尾辞の有無を揃える**。年を付ける図と付けない図を混在させず、複数年ある側に合わせて1枚しかないデータセットにも年を付ける。一方が `population_landscan_hanoi_2023.png` なら、もう一方も `population_worldpop_hanoi_2020.png` とし、`population_worldpop_hanoi.png` のまま並べない。年の有無が不揃いだと図どうしの対応関係が読み取りにくくなるため（すべての図が年を持たない場合はそれで揃っているとみなす）
- `images/` は Git 追跡対象（`.gitignore` に `*.png` 除外はなく、直下 `images/` も除外対象外）

### スクリーンショットと `.qml` の関係（2 軸の整理）

スクリーンショットと `.qml` は目的の異なる別軸であり、両立させる。

| 成果物 | 目的 | 適用条件 |
|---|---|---|
| スクリーンショット（PNG） | **検証**（カバレッジ・CRS・分布の目視確認）・進捗資料転用 | 空間データに**普遍**（データ型で分岐しない） |
| `.qml` | **凡例/シンボロジ**（可視化設定の永続化） | 上記「スタイル作成要否の判定表」でデータ型により条件分岐 |

- 一方の要否が他方を左右することはない。スクショは空間データなら常に作成し、`.qml` は判定表に従う
- 保存先・命名の定型は `inspect-gis-data`（スクショ取得を担うスキル）に組み込む

### 統計値と図の役割分担（連続値ラスタ）

連続値ラスタでは「**統計値で異常を検出し、図で原因を特定する**」という役割分担が有効である。統計値だけでは異常の所在が分からず、図だけでは異常の有無を見落とすため、両方を突き合わせる。

実例:

- 人口密度ラスタ（WorldPop）の無効画素は、数値上は「ROI内の2.77%」としか分からなかった。図では紅河の本流と西湖がそのまま白く抜けており、水域であることが一目で判別できた（Esri LULC との突合でも83%がWaterと確認）
- 都心集中の急峻さ（LandScanがWorldPopより急）は、統計値（平均バイアスがほぼ0なのに中央値バイアスが大きく正）だけでは解釈が定まらなかったが、図が裏付けとなった

## ラスター疑似カラースタイル作成時の注意（重要）

`execute_code`でPyQGISの`QgsSingleBandPseudoColorRenderer`を使ってLST・NDVI等のラスターに疑似カラースタイルを設定する場合、**`renderer.setClassificationMin()` / `setClassificationMax()` を色ランプの値域と一致させて必ず明示的に設定すること**。

**`set_raster_style`では代替できない**: QGIS-MCPの`set_raster_style`（`style_type="singleband_pseudocolor"`）は名前付きカラーランプしか受け付けず、任意の値・色・ラベルの組（`20°C=#2166ac` … `50°C=#b2182b`）を指定できない。さらに`min_value` / `max_value`を明示しても`classificationMin` / `classificationMax`が`nan`になるため、下記の`nan`回避も果たせない。判定の根拠は[新規機能の採否記録](#新規機能の採否記録)を参照。**本節の`execute_code`手順が正本である。**

**理由**: この設定を省略すると、実行中のQGISセッションでは正しく表示されるが（`legendSymbologyItems()`で検証しても正しい値が返る）、`.qml`・`.qgz`への保存時に`classificationMin`/`classificationMax`が`nan`としてシリアライズされ、**プロジェクトを閉じて再度開くとスタイルが破損し、すべての値が`nan`表示になる**。実行中セッションの見た目だけでは検知できない不具合のため注意する。

**対象レンダラー**: この`nan`化問題は、連続値の疑似カラーを扱う`QgsSingleBandPseudoColorRenderer`**固有**である。カテゴリ分類の`QgsPalettedRasterRenderer`（LULC 等のクラス値ラスタで使う）では`classificationMin`/`classificationMax`を持たないため発生しないことを確認済み。したがって`setClassificationMin`/`setClassificationMax`の明示設定が必要なのは`QgsSingleBandPseudoColorRenderer`のときに限られる。

**分類方式（Interpolated / Discrete）による差はない**: `QgsSingleBandPseudoColorRenderer`を`Discrete`（離散分類）で使う場合も、`setClassificationMin`/`setClassificationMax`の明示は有効である。9クラスの離散分類で`classificationMin="0"`/`classificationMax="100000"`が正しく保存され`nan`化せず、後述の往復検証でも各クラスの値・色・ラベルが完全に一致した。下記の実装例は`Interpolated`だが、`Discrete`でも同じ扱いでよい。

**マルチバンドラスタでの注意**: `QgsSingleBandPseudoColorRenderer`に渡す`band`引数（下記実装例の`1`）は`.qml`に保存される。バンド構成の異なるラスタへ同じ`.qml`を流用すると意図しないバンドが描画されるため、流用時はバンド構成が一致するかを確認する。

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
