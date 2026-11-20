# QGIS 運用ガイドライン: 図の生成手段

**最終更新**: 2026-11-19
**関連ドキュメント**: [qgis_operation_guidelines.md](qgis_operation_guidelines.md)（本体）, [qgis_data_acquisition_artifacts.md](qgis_data_acquisition_artifacts.md)（スクリーンショットの構図・命名）, [qgis_mcp_usage_guide.md](qgis_mcp_usage_guide.md), [CLAUDE.md](../../CLAUDE.md)
**前提知識**: [qgis_operation_guidelines.md](qgis_operation_guidelines.md) の既知の制約・CRS統一方針

---

## 図の生成手段（ヘッドレス PyQGIS を既定とする）

コミット用の図（PNG）の生成、すなわちレイヤの読み込み・スタイル設定・印刷レイアウトの書き出しは、**QGIS 本体を起動せずに PyQGIS を動かすヘッドレス実行を既定の手段とする**。QGIS-MCP の`execute_code`は、起動中の QGIS のプロジェクトや画面を直接操作する必要がある場面に限って使う。

### 使い分け

| 場面 | 手段 | 理由 |
|---|---|---|
| 図の生成（1 枚でも複数枚でも）・スタイルを当てた PNG の書き出し | **ヘッドレス PyQGIS**（既定） | キャンバスの再描画とレイヤツリーの更新が起きないため速く、ユーザーの QGIS 本体を巻き込まない |
| 起動中のプロジェクトの構成を変える（Map Theme のレコード編集、レイヤグループの可視性設定など）、起動中のプロジェクトのレイヤにスタイルを当てて`.qml`を作る | `execute_code` | 対象が「いま開いているプロジェクト」やそのレイヤそのものであり、ヘッドレスでは触れない |
| 起動中のレイヤの状態を軽く確かめる（CRS の WKT・地図単位、件数・範囲など） | `execute_code`（専用ツールで足りるならそちら） | 1 回の呼び出しが数秒で終わる読み取りに限る |
| 目視確認のための即時表示、Git 管理外の画像（ゼミ資料など） | `get_canvas_screenshot` / `render_map` | コミット用 PNG には使わない（[保存機構](qgis_data_acquisition_artifacts.md#取得方法構図)を参照） |

**`execute_code`で重い描画をしない**: `execute_code`は QGIS のメインスレッドで動き、MCP の応答は約 60 秒で打ち切られる（2026-08-15 の事象で観察した値。クライアント・サーバーの設定値かは未確認）。打ち切られても QGIS 側は処理を続けるため、繰り返すと QGIS 本体が応答しなくなる（ユーザーのアプリのため、Claude 側で強制終了できない）。2026-08-15 に 300m グリッド（38,235 セル）の主題図 5 枚を作った際、MCP 経由では 1 枚目で 60 秒を超えて QGIS が固まった一方、ヘッドレスでは 5 枚合計 5.3 秒で完了した（起動・終了を含むかは記録がなく未確認。所要時間の記録は本節を正本とする）。`execute_code`は許可プロンプトの対象でもあり（[運用注意](qgis_operation_guidelines.md#運用注意)）、図を作るたびに確認を挟むことになる点でもヘッドレスが向く。

### 実行手順

QGIS 同梱の Python（OSGeo4W の`python-qgis-ltr.bat`）でランナースクリプトを実行する。conda 環境`masterresearch`の Python には`qgis.core`が無いため使えない。OSGeo4W には LTR 版（3.44）と最新版（4.0）が併存するが、`qgis/styles/*.qml`は LTR 版で作っているため、同じ LTR 版の Python を使う。

```powershell
# OSGeo4W のインストール先が既定（C:\OSGeo4W）の場合。<runner> はランナーのパス、
# <repo_root> はリポジトリ（worktree で作業中なら worktree）のルートに置き換える
& "C:\OSGeo4W\bin\python-qgis-ltr.bat" <runner>.py <repo_root>
```

ランナーの骨格は次のとおり。作図そのものは`src/visualization/qgis_figure.py`の関数（`build_gis_figure`等）に任せ、ランナーにはレイヤの読み込みと呼び出しだけを書く。

```python
import os
import sys
from pathlib import Path

# リポジトリルートを第 1 引数で受け取り、先頭に加える（ランナーの置き場所に依存させない）
REPO_ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO_ROOT))

from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsVectorLayer

# 接頭辞パスは python-qgis-ltr.bat が設定する環境変数から取る（絶対パスを書かない）
QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
app = QgsApplication([], False)  # 第 2 引数 False で GUI なし
app.initQgis()
try:
    from src.visualization import figure_layout as fl
    from src.visualization import qgis_figure as qf

    print(qf.__file__)  # 読み込まれたモジュールの場所（worktree で作業中なら必ず確かめる）

    project = QgsProject.instance()
    roi = QgsVectorLayer(str(roi_path), "ROI", "ogr")
    dem = QgsRasterLayer(str(raster_path), "FABDEM")
    # パスの誤りなどで無効なレイヤを渡すと、原因の分かりにくい失敗になるため先に止める
    if not (roi.isValid() and dem.isValid()):
        raise ValueError(f"レイヤを読み込めない: roi={roi_path}, raster={raster_path}")
    project.addMapLayers([roi, dem])
    dem.loadNamedStyle(str(REPO_ROOT / "qgis/styles/dem_elevation.qml"))
    qf.style_roi_outline(roi)  # 省略すると ROI の塗りがデータを覆う
    qf.set_raster_itemized_legend(dem)
    result = qf.build_gis_figure(
        "FABDEM", "ROI", "FABDEM v1.2 標高 － Hanoi ROI", str(out_png), legend_kind=fl.LEGEND_ITEMS
    )
    print(result)  # 例: {'ok': True, 'path': '...'}
finally:
    app.exitQgis()
```

- レイヤを受け取る`qgis_figure`の公開関数は、いずれも`build_gis_figure`と同じ「レイヤ名 + `project`」で呼べる（例: `qf.style_roi_outline("ROI", project=project)`）。`style_roi_outline` / `filter_paletted_to_present` / `set_raster_itemized_legend`は、上記の骨格のようにレイヤオブジェクトを渡してもよい
- 衛星画像などの下絵を敷く、または比較用のレイヤを重ねるときは、`build_gis_figure`の`background_layer_names` / `overlay_layer_names`にレイヤ名を渡す。重ね順は上から ROI 枠 → 重ねるレイヤ → 対象データ → 下絵で、凡例には重ねるレイヤと対象データが載る。XYZ タイルの読み込みに失敗しても書き出しは`ok: True`を返すため、出力した図は目視で確かめる
- `roi_path` / `raster_path` / `out_png`もリポジトリルートと同様に引数や設定から受け取り、研究データの絶対パスをランナーに書かない（[CodingRule.md](CodingRule.md) 7章）
- タイトルの書式は[取得方法・構図](qgis_data_acquisition_artifacts.md#取得方法構図)に従う（例は既存の`images/gis_data/dem/dem_fabdem_hanoi.png`と同じタイトルで、書式の`{年}`を省いている。FABDEM の原データの観測期間は 2010〜2015 年にまたがり、年が一つに定まらないため）
- 複数枚を作る場合は、`initQgis()`から`exitQgis()`までの 1 回の起動の中でループする。起動と終了には数秒かかるため、1 枚ごとに起動し直さない
- 2026-10-22 の実測: ハノイ ROI と FABDEM の項目凡例つきの図 1 枚が、描画・書き出し 1.2〜2.2 秒、起動・終了込みで約 6.4 秒だった

### 環境変数

`python-qgis-ltr.bat`は内部で OSGeo4W の初期化（`o4w_env.bat`）を呼び、`GDAL_DATA` / `PROJ_LIB` / `PYTHONHOME`を OSGeo4W 側の値に設定し直し、`PYTHONPATH`を空にしてから QGIS の Python パスを加える。`QGIS_PREFIX_PATH`もここで設定される。

- そのため、Claude Code の設定で conda 環境向けに入れている`GDAL_DATA` / `PROJ_LIB`は**引き継がれず、干渉もしない**。呼び出し前に外す必要はない
- 同じ理由で`PYTHONPATH`経由のリポジトリルートも消える。`src`を import するには、上記の骨格のとおりランナー内で`sys.path`に加える。worktree で作業している場合はメインのチェックアウトではなく worktree のルートを第 1 引数に渡し、`qgis_figure.__file__`を表示して、変更中のモジュールが読み込まれていることを確かめる

### 注意点

- **proj.db の警告**: 実行時に`proj.db contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 4 is expected`という警告が大量に出る。OSGeo4W 同梱の proj.db が古いためで、EPSG:4326 のデータを描く限り図は正しく出力される（2026-10-22 に確認）。ただし**EPSG:5897 のラスタは EPSG:4326 への再投影に失敗し、描画されない**ため、EPSG:5897 のデータ（測量 GIS や、正準グリッドへラスタ化したデータなど）は事前に EPSG:4326 へ再投影してから渡す（事例は[limited_analysis_results.md](../03_results/limited_analysis_results.md)の図の生成。EPSG:5897 のベクタで同じことが起きるかは未確認）。proj.db の状態は`scripts/check_external_deps.py`で確認できる
- **`The PNG driver does not support update access`**: 書き出し時に出るが、PNG 自体は出力される（同上）
- **凡例の言語**: ヘッドレスでは QGIS の日本語ロケールが読まれず、自動生成される凡例の文字列だけが英語になる（ラスタのバンド凡例が`バンド 1 (グレー)`ではなく`Band 1 (Gray)`になる）。`build_gis_figure`の凡例タイトル（`凡例`）、レイヤ名、呼び出し側が渡すラベルは渡したとおりに出るため、ベクタ主題図の体裁は変わらない。ラスタ図のバンド凡例が英語になることは許容する（ユーザー判断）
- **プロジェクトを汚さない**: ヘッドレスの`QgsProject.instance()`はランナー内だけの空のプロジェクトであり、`hanoi.qgz`は読み込まない限り変わらない。`qgis/projects/*.qgz`を`read()`で読み込んで使う場合も、`write()`を呼ばない
