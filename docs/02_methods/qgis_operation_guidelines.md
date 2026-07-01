# QGIS 運用ガイドライン

**最終更新**: 2026-07-01
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

## 大規模レイヤーの取り扱い（クラッシュ対策）

GBA建物データ（約307万件）や測量データ複数レイヤー（数十万件規模）を同時に可視化状態にした際、QGIS本体がクラッシュする事例が確認された。

**必須の対策**:

1. **レイヤー・グループ追加のたびに`save_project`でこまめに保存する**。クラッシュ時に未保存の作業（レイヤー構成・グループ・Map Theme設定等）がすべて失われるため
2. 全レイヤーを同時に可視化する操作（`Full`テーマの確認など）を行う前に、直前の状態を保存しておく
3. クラッシュ後は`ping`で再接続を確認し、`get_project_info`・`get_layer_tree`で状態を確認してから作業を再開する

## ラスター疑似カラースタイル作成時の注意（重要）

`execute_code`でPyQGISの`QgsSingleBandPseudoColorRenderer`を使ってLST・NDVI等のラスターに疑似カラースタイルを設定する場合、**`renderer.setClassificationMin()` / `setClassificationMax()` を色ランプの値域と一致させて必ず明示的に設定すること**。

**理由**: この設定を省略すると、実行中のQGISセッションでは正しく表示されるが（`legendSymbologyItems()`で検証しても正しい値が返る）、`.qml`・`.qgz`への保存時に`classificationMin`/`classificationMax`が`nan`としてシリアライズされ、**プロジェクトを閉じて再度開くとスタイルが破損し、すべての値が`nan`表示になる**。実行中セッションの見た目だけでは検知できない不具合のため注意する。

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

このコマンドで該当箇所がヒットした場合はスタイルが破損している。
