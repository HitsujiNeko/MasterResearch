# 建物データの調査・評価

**最終更新**: 2026-08-03  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義、分析シナリオ（Satellite Only / Limited / Full）の定義

---

## 1. 採用データと用途

建物面積率や建物密度は、単一データを即採用せず、Microsoft / Google Open Buildings / OSM / GlobalBuildingAtlas を比較して決める。特に Hanoi ROI では Microsoft の西側欠落が確認されたため、Microsoft のゼロ値を建物不存在として扱ってはならない。

### 1.1 Microsoft GlobalMLBuildingFootprints の確認結果

Hanoi ROI で `Microsoft GlobalMLBuildingFootprints` を取得した結果、次の問題を確認した。

- ROI bbox: `105.288125, 20.564469, 106.020051, 21.385222`
- Microsoft 建物 bbox: `105.468713, 20.566427, 106.002608, 21.384685`
- ROI 西側の `105.288E` から概ね `105.469E` までに建物データがほぼ存在しない。
- 欠落境界は quadkey 境界の `105.46875E` と整合する。
- 出力済み建物数は `1,065,629` 件だが、候補 west-side quadkey は `source_feature_count > 0` に対して `matched_feature_count = 0` であり、単純な「候補タイル未選択」だけでは説明しにくい。
- 既存 CSV の経度ビン確認でも、`105.28E` から `105.45E` 付近までは `BUILD_COV_0` / `BUILD_DEN_0` がほぼゼロだった。

このため、Microsoft は「Hanoi 中心部から東側に強い建物データ」としては利用できる可能性があるが、ROI 全域の `BUILD_COV_0` / `BUILD_DEN_0` を代表するデータとしては不十分である。

### 1.2 建物データの優先順位・取得状況（2026-06-09 更新）

GBA の WFS 取得完了・Microsoft 欠落域の定量確認を経て、比較優先順位と取得状況を次のとおり更新する。

#### 候補比較表

| 項目 | GlobalBuildingAtlas (GBA) | Google Open Buildings V3 | OSM building=* |
|---|---|---|---|
| Hanoi ROI全域カバレッジ | ✅ 取得完了（3,071,511件） | ✅ Vietnam明記 | 要QA |
| Microsoft欠落域（西側）対応 | ✅ 273,742件（面積率1.25%）確認済み | ✅ 東南アジア対応 | 要QA |
| 建物高さ情報 | ✅ あり（ML推定、RMSE未確認） | ❌ なし（V3 polygon） | △ 一部のみ |
| ライセンス | CC BY-NC 4.0（学術OK） | CC BY 4.0（最も寛容） | ODbL |
| アクセス方法 | **✅ 取得済み**（GPKG出力済み）。再取得はHuggingFaceを推奨 | gsutil / Colab ノートブック | Geofabrik（取得済み） |
| 取得状況 | ✅ 採用済み（`Limited`シナリオ主ソース） | 未取得・比較候補 | 未取得・比較候補 |
| 下地データ | Google Open Buildings 由来 | — | コミュニティ編集 |
| 備考 | **WFSレート制限注意**: 1,554タイルでIPブロック（48h+）が発生。再取得はHuggingFace（タイル`e105_n25_e110_n20`、~1.78GB）推奨 | 建物高さはV3ではなく2.5D Temporalで別途取得 | 品質は地域差が大きい |

#### 優先順位・取得状況

1. `GlobalBuildingAtlas` via WFS / HuggingFace: **✅ 採用済み（`Limited`シナリオ建物主ソース）**。2026-06-09 に ROI クリップ済みで 3,071,511 件取得完了。`data/gis/buildings/hanoi_gba_buildings.gpkg` に出力済み。スクリプト: `src/preprocessing/fetch_gba_buildings_hanoi.py`（`--start-tile-index` で途中再開可能）。**再取得時は WFS でなく HuggingFace バルクDL推奨**（WFS は大量リクエスト時に IP ブロックが発生するため）。
2. `Google Open Buildings V3 Polygons`: 未取得。ライセンスがより寛容（CC BY 4.0）。建物高さ不要で面積・密度のみ算出する場合の比較候補。confidence閾値の感度分析が必要。GBA との重複率・差分を確認してから採用判断する。
3. `OSM building=*`: 未取得。Geofabrik Vietnam extract から追加取得でき、道路と同一ソースで再現性が高い。コミュニティ整備状況に依存するため、建物密度の空間偏りを QA する。
4. `Google Open Buildings 2.5D Temporal`, `GHSL`, `WSF`: 個別フットプリントではなく、built-up / building presence / height の補助変数または妥当性確認に使う。

### 1.3 Limited シナリオの建物データ方針（2026-06-09 更新）

**GBA の取得完了により、`Limited` シナリオの建物主ソースを `GlobalBuildingAtlas` に確定した。**

- `data/gis/buildings/hanoi_gba_buildings.gpkg`（3,071,511 件、ROI クリップ済み）を建物フットプリントの正本として使う。
- Microsoft 欠落域（105.29–105.47°E）では GBA に 273,742 件の実データが存在することを確認済み。GBA を使うことで Microsoft のカバレッジ欠落問題は解消される。
- `BUILD_COV_0`, `BUILD_DEN_0` などの建物系パラメータは GBA を主ソースとして再算出する。
- Microsoft は「Hanoi 中心部から東側の補助的な比較データ」として保持するが、主ソースとしては使わない。
- `BUILD_COV_0 = 0`, `BUILD_DEN_0 = 0` を「建物なし」と解釈する前に、そのセルが GBA の有効カバレッジ内かを確認する（GBA は ROI 行政区画クリップ済みのため境界付近には注意）。

---

## 2. GlobalBuildingAtlas 詳細仕様

本研究の `Limited` シナリオで建物主ソースとして採用した GlobalBuildingAtlas（GBA）について、データの特性・制限・引用方法を記録する。

### 2.1 データセット概要

| 項目 | 内容 |
|---|---|
| 正式名称 | GlobalBuildingAtlas (GBA) |
| バージョン | v1.0.0（2025年11月公開） |
| 規模 | 約 2.75 億棟（全球） |
| 提供機関 | Chair of Remote Sensing Technology, Technical University of Munich (TUM) / zhu-xlab グループ |
| 配布形式 | WFS（GeoServer）、HuggingFace（5°×5° GeoJSON タイル）、GitHub |
| ライセンス | CC BY-NC 4.0（非商用・帰属表示必須） |
| GitHub | <https://github.com/zhu-xlab/GlobalBuildingAtlas> |
| 論文 DOI | <https://doi.org/10.5194/essd-17-6647-2025> |

### 2.2 データの構成とフットプリントのソース

GBA は **建物フットプリント（ポリゴン）** と **ML 推定建物高さ** を組み合わせた全球 LoD1 建物モデルである。

**フットプリントのソース**:

- 地域によって複数ソースを統合している。東南アジア（ベトナム含む）は **Google Open Buildings V3** が主ソースである。WFS レスポンスの `source` 属性に `google` と格納されていることで確認できる。
- フットプリントの検出精度は元ソース（Google Open Buildings 等）の機械学習モデルに依存する。

**建物高さ（`height` 属性）**:

- 衛星画像から機械学習で推定した値であり、現地測量値ではない。
- 推定アルゴリズムの詳細は論文（Zhu et al., 2025）を参照。
- ハノイ ROI での高さ推定精度（RMSE 等）は本研究では未検証。

**LoD1 モデルとは**:

- Level of Detail 1（LoD1）= フットプリントポリゴンを**単一の代表高さで押し出した箱型 3D モデル**。
- 屋根の形状（切妻・寄棟等）や階別の形状変化は表現しない。
- 本研究では建物フットプリント面積・建物密度・建物高さ（`height`）の算出に利用する。

### 2.3 データの参照時期（temporal reference）

GBA はフットプリントと建物高さで**元データの年代が異なる**。また、地域ごとの正確な撮影日はメタデータとして公開されていない。

| コンポーネント | 元データ | 推論時期 | 推定される画像年代 |
|---|---|---|---|
| フットプリント（ポリゴン） | Google Open Buildings V3（50cm 高解像度衛星画像） | 2023年5月 | 概ね **2021〜2023年**（後述） |
| 建物高さ（`height`） | PlanetScope 衛星画像（約3m解像度） | GBA v1.0.0（2025年11月公開） | 論文中に **2019年** の画像取得への言及あり |

**フットプリントの画像年代について**:

- Google Open Buildings V3 は 2023年5月に推論を実施し、「特に人口密集地ではできるだけ最新の画像を優先した」と公式に述べている（[Google Open Buildings](https://sites.research.google/gr/open-buildings/)）。
- 一方で「場所によっては最新の画像が数年前（several years old）の場合がある」とも注記されている。
- ハノイは首都かつ大都市であり、商用高解像度画像の入手性が高いため、2021〜2023年の画像が使用されている可能性が高い。ただし ROI 郊外部では画像年代が異なる可能性がある。
- V3 の前バージョン V2 は 2022年8月に推論されており、V3 は「V2 よりも最新の画像に基づく」と明記されている。
- 特定エリアの画像年代を確認するには Google Earth Pro の「過去のイメージ」機能で高解像度画像の日付を参照する方法が推奨されている。

**研究上の注意**:

- フットプリントと高さで参照時期が異なる可能性があるため、論文では両コンポーネントの年代を区別して記述する。
- LST（Landsat 8）の撮影年と建物データの年代の整合性は、分析結果の解釈時に考慮が必要。

### 2.4 WFS エンドポイント情報

| 項目 | 値 |
|---|---|
| エンドポイント URL | `https://tubvsig-so2sat-vm1.srv.mwn.de/geoserver/ows` |
| レイヤー名 | `global3D:lod1_global` |
| プロトコル | WFS 2.0.0 (OGC) |
| Native CRS | EPSG:3857（Web メルカトル） |
| BBOX 指定 | EPSG:3857 に変換して指定する必要がある（EPSG:4326 のまま渡すと座標系ずれが生じる） |
| 最大取得件数 / リクエスト | 50,000 件（`count` パラメータ上限） |

### 2.5 今回の取得処理の内容（Hanoi ROI）

スクリプト `src/preprocessing/fetch_gba_buildings_hanoi.py` で実施した主な処理：

1. **タイル分割**: ROI BBOX を 0.02° × 0.02° グリッドに分割（全 1,554 タイル）し、WFS を 1 タイルずつ取得。50,000 件 / リクエスト上限によるデータ欠落を回避するため。
2. **ROI 事前フィルタ**: タイルと行政区画ポリゴンが交差しない場合はリクエスト自体をスキップ（不要リクエストを削減）。
3. **CRS 変換**: WFS レスポンス（EPSG:3857）を EPSG:4326 に変換。
4. **ROI クリップ**: 各建物ポリゴンを Hanoi 行政区画ポリゴン（`data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp`）でクリップ。境界を跨ぐ建物は切断して境界内の部分のみ保持。
5. **出力**: `data/gis/buildings/hanoi_gba_buildings.gpkg`（GeoPackage 形式、EPSG:4326）

**取得結果**: 3,071,511 件（2026-06-09 完了）

### 2.6 精度・制限事項

- **高さ精度未検証**: `height` 属性は ML 推定値。ハノイでのローカル精度（RMSE・バイアス）は未検証。高さを定量指標として使う場合は別途現地データとの検証が必要。
- **高さの実測分布（Hanoi ROI 全 3,071,511 件、2026-08-03 計測）**: 値域は 0.0062〜169.42 m、欠測（NULL）は 0 件、負値も 0 件。ただし **`height < 1 m` が 80,332 件（2.6%）**あり、最小値 0.0062 m は建物高さとして物理的に成立しない。ML 推定のアーティファクトとみられ、セル平均高さ（`BUILD_H_MEAN`）を下方向へ引く要因になる。
- **推定分散 `var` の番兵値**: 値域は −1.0〜2434.86。**負値は 149 件で、すべて厳密に −1.0**。分散は物理的に負にならないため、これは推定の信頼度が無いことを示す番兵値である。欠測（NULL）は 0 件。
- **フットプリントの過検出・未検出**: 元ソースが機械学習検出のため、仮設構造物・農業用建屋の誤検出や小規模建物の未検出がある可能性がある。
- **GBA と Google Open Buildings の独立性**: ベトナムでは GBA フットプリントが Google Open Buildings V3 と概ね重複する。両者を独立した検証データとして扱うことはできない。
- **ROI 境界付近の部分ポリゴン**: 行政区画境界を跨ぐ建物はクリップして保持しているため、境界付近には部分的なポリゴンが含まれる。建物面積・高さ指標の算出時は境界付近の扱いに注意。
- **WFS レート制限**: 今回の 1,554 タイル取得で IP レベルのレート制限（48 時間以上のブロック）が発生した。再取得が必要な場合は WFS ではなく HuggingFace のバルクダウンロード（タイル `e105_n25_e110_n20`、約 1.78GB GeoJSON）を推奨。

### 2.7 論文への引用

論文・学位論文で本データを使用する場合は、以下の論文を引用する。

```bibtex
Zhu, X. X. et al.: GlobalBuildingAtlas: A global LoD1 building model,
Earth Syst. Sci. Data, 17, 6647–6670,
https://doi.org/10.5194/essd-17-6647-2025, 2025.
```

> **注意**: 著者リストの正式表記は論文ページ（<https://essd.copernicus.org/articles/17/6647/2025/>）で確認すること。上記の `Zhu, X. X. et al.` は略記であり、投稿規程に合わせて正確な著者リストを使うこと。

CC BY-NC 4.0 ライセンスの帰属表示要件として、論文本文またはデータセクションに以下のような記述を含めること：

> Building footprint and height data are from the GlobalBuildingAtlas (GBA) v1.0.0 (Zhu et al., 2025), available at <https://github.com/zhu-xlab/GlobalBuildingAtlas>, licensed under CC BY-NC 4.0.

### 2.8 フットプリント元ソース：Google Open Buildings V3 について

GBA のフットプリントはベトナムでは Google Open Buildings V3 由来（WFS の `source:google` 属性で確認済み）であるため、補足として概要を記録する。

Google Open Buildings V3 は Google が衛星画像から機械学習で検出した建物フットプリントデータセットである。東南アジア・アフリカ等を対象に約 18 億件を収録し、各検出に **信頼スコア（confidence: 0〜1）** を付与している点が Microsoft との主な違いである。ライセンスは CC BY 4.0（商用利用可）。

**Microsoft との主な違い**:

| 項目 | Google Open Buildings V3 | Microsoft GlobalMLBuildingFootprints |
|---|---|---|
| 学習用画像ソース | Google 衛星画像 | Bing Maps 衛星画像 |
| 信頼スコア | あり（confidence: 0〜1） | なし |
| Hanoi ROI カバレッジ | 全域 | 西側（〜105.47°E）欠落 |
| ライセンス | CC BY 4.0 | ODbL |

**本研究での注意点**:  
GBA（ベトナム）のフットプリントは Google Open Buildings V3 と概ね同一であるため、両者を**独立した検証データとして相互利用することはできない**。Microsoft は異なる衛星画像・異なるモデルで検出しているため、カバレッジが重なる ROI 東側（約 105.47°E 以東）に限り独立した比較が可能である。

---

## 3. 都市構造パラメータの算出方法

GBA から算出する建物パラメータの定義と、解釈上の前提を示す。実装は `src/analysis/urban_params/params/buildings.py`。

### 3.1 算出する4パラメータ

| 列名 | 定義 | 単位 | 算出方法 |
|---|---|---|---|
| `BUILD_COV` | 建物フットプリント被覆率 | 0-1（比率） | 建物ポリゴンを fine グリッド（既定 10m）へラスタ化し、coarse セルへ平均集約 |
| `BUILD_DEN` | 建物棟数密度 | 棟/ha | 重心が属する coarse セルごとの棟数 ÷ セル面積 |
| `BUILD_H_MEAN` | セル内建物の平均高さ | m | 重心が属するセルごとに、有効高さの平均 |
| `BUILD_H_MAX` | セル内建物の最大高さ | m | 重心が属するセルごとに、有効高さの最大 |

### 3.2 帰属方式（centroid 方式）

`BUILD_DEN` と `BUILD_H_MEAN` / `BUILD_H_MAX` は、各建物ポリゴンの**重心が含まれる coarse セルに1棟をまるごと帰属**させる（面積按分をしない）。3パラメータが同じ「セルに属する建物」集合を共有するため、パラメータ間の整合性が取れる。

**解釈上の注意**: 重心が隣接セルにある建物のフットプリントだけが張り出したセルは、`BUILD_COV > 0` でありながら `BUILD_DEN = 0` かつ `BUILD_H_MEAN` / `BUILD_H_MAX` が NaN になる。これは設計どおりの挙動であり、欠測や不具合ではない。

この状態に該当するセルの規模は無視できない。Hanoi ROI・`Limited` シナリオの出力での実測（2026-08-03）は次のとおり。

| coarse 解像度 | `BUILD_COV > 0` のセル | うち `BUILD_H_MEAN` が NaN | 割合 |
|---|---|---|---|
| 30m | 839,942 | 118,255 | 14.1% |
| 90m | 180,690 | 5,041 | 2.8% |
| 300m | 29,185 | 119 | 0.4% |

**30m では被覆率のあるセルの約7分の1で高さが欠測**する。高さ列を使う分析では、欠測をどう扱うか（当該セルを除外するか、被覆率のみのモデルと比較するか等）が実質的な判断事項になる。粗いスケールほど1セルに含まれる建物が増えるため、この割合は急速に下がる。

### 3.3 高さの有効性判定

推定分散 `var` が負、または `height` 自体が負の建物を高さ集計から除外する。いずれも物理的に負にならないため、負値は番兵値とみなす（Section 2.6 参照）。**`BUILD_COV` / `BUILD_DEN` からは除外しない**（フットプリント自体は有効なため）。

- **欠測（NULL / NaN）も除外する**。判定は `var >= 0` かつ `height >= 0` で行い、欠測値との比較は偽になるため自動的に集計対象外になる。GBA は両属性とも欠測 0 件だが、他レイヤへ適用する際の規則として同じ扱いとする
- **`var` 列を持たないレイヤ**では信頼度による絞り込みができないため、取得できた高さをすべて集計し、意味論が変わることを警告する。同じ `BUILD_H_MEAN` という列名でも、GBA のように分散で絞り込んだ値とは前提が異なる
- **`height` 列も持たないレイヤ**では高さ列がすべて NaN になる。`Full` シナリオの建物レイヤ（`merge_DC.gpkg`）は CAD 由来で `height` / `var` のいずれも持たないため、この状態になる

### 3.4 欠測値の扱い

| 状況 | `BUILD_COV` | `BUILD_DEN` | `BUILD_H_MEAN` / `BUILD_H_MAX` |
|---|---|---|---|
| セル内に建物なし | 0.0 | 0.0 | **NaN** |
| 建物はあるが全て有効高さなし | 実値 | 実値 | **NaN** |

高さは 0.0 ではなく NaN とする。0 m だと「建物が無い」状態と「高さが不明」な状態を区別できず、回帰分析で偽の低高度セルを生むためである。

2行目（重心が属する建物はあるが全て有効高さなし）に該当するセルは、`var = -1` の 149 棟だけを含むセルであり、実測では 30m で 26 セル・90m で 6 セル・300m で 3 セルとごく少数である。Section 3.2 の表で示した「被覆率はあるが高さ欠測」のセルは、その大半が**重心が他セルにある**ケース（1行目に相当）である点に注意する。

### 3.5 `BUILD_COV` の精度とスケール依存性

`BUILD_COV` は fine グリッドへのラスタ化による**近似**であり、面積按分の厳密値とは離散化の分だけ差が出る。ハノイ中心部のテスト領域で QGIS の厳密値と突合した結果を示す。

**突合の条件（追試用）**: 本節の数値は QGIS-MCP による一回限りの手動計測（2026-08-03、QGIS 3.44.11）であり、リポジトリ内に自動化スクリプトを持たない。再計測する場合は以下の条件で行う。

| 項目 | 値 |
|---|---|
| テスト領域の中心 | 105.852°E, 21.028°N（ホアンキエム湖周辺） |
| テスト領域の範囲（EPSG:5897） | 587313.553, 2325238.732 – 589413.553, 2327338.732（2.1 km 四方） |
| 対象建物 | 上記範囲の BBox で `hanoi_gba_buildings.gpkg` から切り出した 13,779 件 |
| fine 解像度 | 10 m |
| 自作側 | `params/buildings.py` の `compute()` を上記範囲の `GridSpec` で実行 |
| QGIS側（厳密値） | `native:dissolve`（建物同士の重なり 4.44% を解消）→ `native:intersection`（セルポリゴンと交差）→ セルごとに面積合計 ÷ セル面積 |
| セルポリゴン | `GridSpec.coarse_transform` から生成し、両者に同一のジオメトリを渡す |

建物同士に重なりがあるため、`native:dissolve` を省くと厳密値が過大になる点に注意する。また比較は EPSG:5897 に投影済みのジオメトリどうしで行っており、CRS 変換の妥当性は本突合の対象外である。

| coarse 解像度 | fine セル数/coarse セル | 相関 | 平均バイアス | 誤差SD | 取りうる値 |
|---|---|---|---|---|---|
| 30m | 9 | 0.952 | +0.0013 | 0.083 | 10段階のみ |
| 90m | 81 | 0.989 | +0.0012 | 0.026 | 82段階 |
| 300m | 900 | 0.998 | +0.0013 | 0.007 | 901段階 |

**平均バイアスは全スケールでほぼ一定（+0.0013）**で系統的な偏りは小さい一方、**セル単位のばらつきは coarse 解像度に強く依存**する。30m では fine セル9個分しかないため被覆率が10段階の値しか取らない。

説明変数の測定誤差は回帰係数を 0 方向へ縮める（希釈バイアス）。ROI 全域の `BUILD_COV` 分散と上表の誤差分散から見積もった希釈の程度は次のとおり。

| coarse 解像度 | 希釈係数 λ | 係数の縮み |
|---|---|---|
| 30m | 0.785 | 約 21% |
| 90m | 0.967 | 約 3% |
| 300m | 0.996 | 約 0.4% |

**RQ2（スケール依存性）の解釈にあたっての注意**: 「30m で被覆率の説明力が相対的に低い」という結果が出た場合、真のスケール効果ではなく本アーティファクトの可能性を先に検討する。希釈は影響を過小評価する向きに働くため、30m でも被覆率が支配的なら結論は安全側である。

なお誤差分散は高密度な中心部での実測であり、**ROI 全域でのセル単位の誤差分散は未検証**である。上記の λ はこの前提のうえでの目安として扱う。また GBA フットプリント自体の過検出・未検出の誤差は未定量であり、30m セルでは建物1棟の検出漏れが被覆率を 0.11 動かすため、データ側の誤差が離散化誤差を上回る可能性がある。

#### 小さい建物の取りこぼし（`BUILD_COV = 0` の解釈）

ラスタ化はピクセル中心で内外を判定するため、**fine セル（10m 四方 = 100 m²）の中心を1つも含まない建物は被覆率に一切寄与しない**。GBA の建物は小さく、この条件に該当しやすい。

| 指標 | 実測値（Hanoi ROI 全 3,071,511 件） |
|---|---|
| フットプリント面積の中央値 | 51.8 m² |
| 100 m² 未満の割合 | 80.7% |
| 50 m² 未満の割合 | 48.3% |

結果として、**重心が属する建物があるセル（`BUILD_DEN > 0`）でも `BUILD_COV = 0` になる**ことがある。実測値は次のとおり。

| coarse 解像度 | `BUILD_DEN > 0` のセル | うち `BUILD_COV = 0` | 割合 |
|---|---|---|---|
| 30m | 839,102 | 117,401 | 14.0% |
| 90m | 196,768 | 21,116 | 10.7% |
| 300m | 30,699 | 1,632 | 5.3% |

**`BUILD_COV = 0` を「建物が存在しない」と解釈してはならない。** 30m では建物のあるセルの14%が該当する。建物の有無は `BUILD_DEN` で判定し、`BUILD_COV` は面積的な密度の指標として扱う。

ただし**集計レベルでは打ち消し合う**。ROI 全域でラスタ化した被覆面積の合計は 263.92 km² で、実フットプリント面積の合計 274.37 km²（建物同士の重なりを含む）の 0.962 倍である。中心部で実測した重なり 4.44% とほぼ一致するため、全域の集計値としての偏りは小さい。取りこぼしは**セル単位の解釈でのみ問題になる**。

`BUILD_DEN` / `BUILD_H_MEAN` / `BUILD_H_MAX` は同じ突合で QGIS の重心内包カウント・属性の空間結合（集計つき）と float32 精度内（最大絶対誤差 1.0e-6 m）で一致しており、離散化の影響を受けない。

---

## 4. 注意点

- `OSM` は地域差が大きく、Hanoi 周辺でも建物の完全性を保証しない。
- `Microsoft` は全球対応だが、Hanoi ROI では西側欠落が確認されたため、ROI 全域の建物ゼロ値をそのまま解釈してはならない。
- `Microsoft` の `height_m` と `confidence` は地域や更新時期によって未提供の場合があり、Hanoi ROI の今回取得結果では `-1` が入っていたため、属性値の直接利用は避ける。
- `Google Open Buildings` は confidence 閾値により建物数と面積率が変わるため、閾値感度分析を行う。
- `GlobalBuildingAtlas` の WFS は大量リクエスト（~1,554 タイル）時に IP レート制限（48 時間以上のブロック）が発生する場合がある。再取得が必要な場合は HuggingFace（`zhu-xlab/GBA.LoD1`、タイル `e105_n25_e110_n20`、約 1.78GB GeoJSON）によるバルクDL を使うこと。スクリプト `src/preprocessing/fetch_gba_buildings_hanoi.py` には `--start-tile-index` で途中再開機能を実装済み。
- `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` は建物ポリゴンそのものではなく、`BUILD_DEN_0` と同じ定義ではない。
- いずれの候補も、測量データの代替真値ではなく、測量データの不足を補う補助ソースとして扱うのが安全である。

---

## 5. ワークフロー（2026-06-09 更新）

1. Microsoft 建物データのカバレッジ欠落を QA 結果として固定し、現行 `hanoi_microsoft_buildings.gpkg` の有効範囲を明示する（保留扱い確定）。
2. ~~`GlobalBuildingAtlas` を WFS で Hanoi ROI から取得する。~~ **✅ 完了（2026-06-09）**。行政区画ポリゴンクリップ済みで 3,071,511 件取得。出力: `data/gis/buildings/hanoi_gba_buildings.gpkg`。スクリプト: `src/preprocessing/fetch_gba_buildings_hanoi.py`（`--start-tile-index` で途中再開可能）。**再取得時は WFS ではなく HuggingFace バルクDL を推奨**（WFS は IP ブロックが発生したため）。
3. ~~GBA 取得後、Microsoft 欠落域（105.29–105.47°E）での建物数・面積率を比較し、カバレッジ改善を定量確認する。~~ **✅ 完了（2026-06-09）**。Microsoft 欠落域で 273,742 件・面積率 1.25% を確認（ゼロでなく実データあり）。GBA を `Limited` シナリオ建物主ソースとして確定。
4. 必要に応じて `Google Open Buildings V3 Polygons` を Geofabrik の代替または補完データとして取得し、GBA と比較する。
5. Geofabrik Vietnam extract から `building=*` を抽出し、GBA / Google と密度・面積率を比較する。
6. `GHSL`, `WSF`, `Google Open Buildings 2.5D Temporal` で built-up / building presence の補助指標を作る。
7. 各候補について欠測率、重複率、空間カバレッジ、建物数、建物面積率を同一 ROI グリッドで比較する。
8. 採用可否を [analysis_workflow.md](../../02_methods/analysis_workflow.md) と [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md) に反映する。

---

## 6. 参考ソース

- Microsoft GlobalMLBuildingFootprints: <https://github.com/microsoft/GlobalMLBuildingFootprints>
- Google Open Buildings: <https://sites.research.google/open-buildings>
- Google Open Buildings V3 Polygons: <https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons>
- Google Open Buildings 2.5D Temporal: <https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1>
- GlobalBuildingAtlas: <https://github.com/zhu-xlab/GlobalBuildingAtlas>
- GlobalBuildingAtlas paper: <https://essd.copernicus.org/articles/17/6647/2025/>
- GHSL Data Package 2023 / GHS-BUILT: <https://ghsl.jrc.ec.europa.eu/documents/GHSL_data_access.pdf>
- GHSL collection landing page: <https://data.jrc.ec.europa.eu/collection/ghsl/>
- World Settlement Footprint 2015: <https://geoservice.dlr.de/web/maps/eoc%3Awsf>
