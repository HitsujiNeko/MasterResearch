# Limited シナリオ 分析結果

**最終更新**: 2026-08-19  
**関連ドキュメント**: [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md), [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

---

## 1. 今回の位置づけ

RQ3 では Full / Limited / Satellite Only の3シナリオを比較する。Satellite Only は cell_id結合の新経路で既に成立済み（[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md)）であり、本ドキュメントは公開GIS（GlobalBuildingAtlas建物、OSM道路、FABDEM標高）と衛星指標を組み合わせた **Limited** シナリオの評価結果を記録する。Full シナリオ（測量GISの追加）は本ドキュメントの対象外（未着手）。

分析対象は Satellite Only と同じく **30m・単一観測日（`2023-07-07T03:23:29Z`）** に限定する。格子・観測日は Satellite Only と同一（同じ cell_id結合経路のため）だが、特徴量集合が異なる（9変数 vs 3変数）ため、**数値の直接比較は本Issueのスコープ外**とする。参考情報として5.5節に並記するのみで、定量的な優劣判定は行わない。

---

## 2. 今回実施したこと

1. `src/analysis/build_dataset.py` で `cell_id` キーのLimited用分析データセット（GeoPackage）を生成した
2. 建物高さ列（`BUILD_H_MEAN`/`BUILD_H_MAX`）のNULLのうち、建物が存在しないセル（`BUILD_COV == 0` かつ `BUILD_DEN == 0`）に限り0mで補完した
3. 品質列でフィルタし、乱数シード固定でサンプリングした（主結果は `VALID_GIS_MASK` を課さず有効域全体を対象、感度分析では `VALID_GIS_MASK == 1` に限定）
4. Multiple Linear Regression（X・y双方標準化）と Random Forest を random split で比較した
5. 正準グリッドの row/col から作った物理的に等間隔な空間ブロックで Spatial CV（Group K-Fold）を実施した
6. Random Forest に対して SHAP を計算し、変数重要度と寄与方向を確認した
7. 主結果と感度分析（`VALID_GIS_MASK == 1` 限定）を両方実行し、差分を記録した

---

## 3. データと処理条件

### 3.1 入力データセット

- `data/output/datasets/dataset_limited_20230707_032329_hanoi_30m.gpkg`
- 生成コマンド: `python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited --tables lst_20230707_032329 idx_20230707_032329 --name limited_20230707_032329`
- 全セル数: **3,739,454行**（30m正準グリッドの全域。Satellite Onlyと同じ格子）

### 3.2 建物高さ列の補完

`BUILD_H_MEAN`/`BUILD_H_MAX` は、高さが取れる建物が1つも無いセルでNULLになる。「建物が無い」の判定は `BUILD_COV == 0`（被覆率）単独ではなく、`BUILD_COV == 0 AND BUILD_DEN == 0`（棟数密度も0）で行う。

`BUILD_COV` はfineグリッドへのラスタ化による近似であり、`gis_data_buildings.md`「小さい建物の取りこぼし」の実測によれば、30mでは建物の重心が存在するセル（`BUILD_DEN > 0`）の**14.0%**で `BUILD_COV == 0` になる（GBAの建物の80.7%が100m²未満で、fine 10mセルの中心を1つも含まない場合に被覆率へ寄与しないため）。`BUILD_DEN` は高さ集計と同じ建物重心の帰属方式であるため、`BUILD_COV` 単独より「建物が無い」の判定に適する。`BUILD_COV == 0` のみを基準にした場合、実データで16セル（有効域内）が誤って0補完される（`BUILD_DEN > 0` なのに `BUILD_COV == 0` かつ高さNULL）ことを確認した。

この2条件のANDに基づき、`BUILD_COV == 0 AND BUILD_DEN == 0` のセルのみ「建物が無い ⇒ 建物高さ0m」として0補完し、`BUILD_COV > 0` または `BUILD_DEN > 0` なのに高さNULL（真の欠落）のセルは補完せず、後段の非NULL要求フィルタで除外した。

データセット全体（3,739,454セル）での補完件数: **2,781,918セル（74.4%）**。

### 3.3 品質管理（フィルタ条件）

**主結果**（以下をすべて満たすセル）:

- `IN_ANALYSIS_AREA == 1`
- 9特徴量（`BUILD_COV`, `BUILD_DEN`, `BUILD_H_MEAN`, `BUILD_H_MAX`, `ROAD_DEN`, `ELEV_MEAN`, `NDVI`, `NDBI`, `NDWI`）と `LST` が非NULL（建物高さ補完後）
- `LST_VALID_RATIO >= 0.5`

フィルタ後の母数: **1,901,915セル**。うち建物高さ補完セル: 1,513,657セル（79.6%）。

**感度分析**（`--require-valid-gis-mask`。上記に加え `VALID_GIS_MASK == 1` を課す）:

フィルタ後の母数: **631,885セル**（主結果の33.2%）。うち建物高さ補完セル: 243,627セル（38.6%）。

`VALID_GIS_MASK == 0` は全件 `no_gis_feature`（`build_dataset.py` のコメントにより「分析上は0として扱ってよい」観測結果）であり、`missing_gis_data` は0件だった。**ただしこの「0件」は、建物パラメータテーブルが正準グリッドの全セルに結合できたこと（テーブル結合の完全性）を示すのみであり、GBAが現地の建物を漏れなく検出できていること（データそのものの正確性・有効カバレッジ）までは検証していない**（`BUILD_COV`/`BUILD_DEN` は結合の有効域外でも常に0.0を返す設計のため、結合が成功していれば `missing_gis_data` は構造的にほぼ0件になる。3.2節で述べた小規模建物の取りこぼしはこの「0件」では検出できない）。

この限界を踏まえたうえで、**主結果では `VALID_GIS_MASK` を課さず有効域全体を対象**とした（`VALID_GIS_MASK == 0` のセルを「GIS特徴量が観測結果として0」として扱う判断自体は妥当であり、テーブル結合の完全性は確認済みのため）。`VALID_GIS_MASK == 1` に限定した場合の結果は感度分析として別途保持し、4.5節で両者を比較する。

### 3.4 サンプリング

- 適用順序: 建物高さ補完 → フィルタ → サンプリング → ブロック割り当て（ブロック割り当てを先にすると各ブロックのセル数が不均等に減り、fold のサイズ均衡が崩れるため）
- サンプル数: `100,000`（主結果・感度分析とも共通）
- 乱数シード: `42`
- サンプル内の建物高さ補完セル数: 主結果 **79,593件**、感度分析 **38,552件**

  この値は3.3節の「フィルタ後母数における補完セル数」とは異なる母集団（フィルタ後の全件 vs 10万件サンプル）に対する集計であり、両者は一致しない（比率はほぼ一致: 主結果 79.6% vs 79.6%、感度分析 38.6% vs 38.6%）。研究記述で引用する際はどちらの母数か明記すること。

### 3.5 モデル設定

- 学習 / テスト: `80,000 / 20,000`（random split、`test_size=0.2`）
- 説明変数（9変数）: `BUILD_COV`, `BUILD_DEN`, `BUILD_H_MEAN`, `BUILD_H_MAX`, `ROAD_DEN`, `ELEV_MEAN`, `NDVI`, `NDBI`, `NDWI`
- 目的変数: `LST`（°C）
- MLR: 説明変数・目的変数の両方を標準化（標準化偏回帰係数として解釈）
- RF: `n_estimators=300`, `min_samples_leaf=5`
- Spatial CV:
  - `5-fold`（Group K-Fold、group = 空間ブロックID）
  - ブロックサイズ: `2,700m`
  - 非空ブロック数: 主結果 305、感度分析 299（10万件サンプル後ベース）
- SHAP: 評価サンプル `2,000`、background `500`

### 3.6 出力ファイル

`data/output/limited/20230707_032329/` に以下を保持する（接頭辞は `dataset_limited_20230707_032329_hanoi_30m`。感度分析は末尾に `_gismask` を付与し主結果と区別する）。

- `*_sample_100000.csv`: サンプリング結果（Git管理外）
- `*_feature_importance.csv`: 係数・重要度・VIF
- `*_spatial_cv_folds.csv`: fold別評価値
- `*_model_comparison.png`, `*_feature_importance.png`, `*_spatial_cv.png`: 可視化
- `*_shap_importance.csv`, `*_shap_summary.png`, `*_shap_bar.png`, `*_shap_dependence_{9変数}.png`: SHAP関連
- `*_results.json`: 全結果の要約

---

## 4. 基本結果

### 4.1 ランダム分割でのモデル性能

| モデル | 主結果 R² | 主結果 RMSE | 主結果 MAE | 感度分析 R² | 感度分析 RMSE | 感度分析 MAE |
|---|---|---|---|---|---|---|
| Linear Regression | 0.6696 | 1.1726 | 0.8657 | 0.6801 | 1.1952 | 0.9236 |
| Random Forest | 0.7952 | 0.9232 | 0.6923 | 0.7417 | 1.0740 | 0.8238 |

### 4.2 Spatial CV でのモデル性能

| モデル | 主結果 R² mean | 主結果 R² std | 感度分析 R² mean | 感度分析 R² std |
|---|---|---|---|---|
| Linear Regression | 0.6582 | 0.0184 | 0.6758 | 0.0122 |
| Random Forest | 0.7801 | 0.0081 | 0.7233 | 0.0239 |

主結果では random split から Spatial CV への性能低下が RF で `0.7952 → 0.7801`（-0.015）と小幅であり、ランダム分割の性能が空間自己相関だけで説明される過大評価ではないと解釈できる。

### 4.3 変数重要度（主結果）

| 指標 | 標準化係数（符号付き） | RF Importance | Permutation Importance | VIF |
|---|---|---|---|---|
| BUILD_COV | +0.1518 | 0.0020 | 0.0003 | 3.84 |
| BUILD_DEN | +0.0399 | 0.0021 | 0.0004 | 3.71 |
| BUILD_H_MEAN | +0.1143 | 0.0161 | 0.0077 | **41.38** |
| BUILD_H_MAX | -0.0306 | 0.0133 | 0.0042 | **47.56** |
| ROAD_DEN | +0.1121 | 0.0173 | 0.0125 | 1.22 |
| ELEV_MEAN | -0.2799 | 0.0884 | 0.1267 | 1.16 |
| NDVI | -0.9974 | 0.1510 | 0.3078 | 22.31 |
| NDBI | +0.3322 | **0.5810** | **0.6258** | 2.01 |
| NDWI | -1.0734 | 0.1288 | 0.2193 | 21.17 |

### 4.4 変数重要度（感度分析）

| 指標 | 標準化係数（符号付き） | RF Importance | Permutation Importance | VIF |
|---|---|---|---|---|
| BUILD_COV | +0.0550 | 0.0053 | 0.0007 | 3.01 |
| BUILD_DEN | -0.0062 | 0.0059 | 0.0013 | 3.05 |
| BUILD_H_MEAN | +0.1073 | 0.0175 | 0.0101 | **36.24** |
| BUILD_H_MAX | -0.0484 | 0.0160 | 0.0053 | **41.42** |
| ROAD_DEN | +0.0433 | 0.0241 | 0.0085 | 1.11 |
| ELEV_MEAN | -0.0724 | 0.0813 | 0.0996 | 1.06 |
| NDVI | -0.1228 | 0.0315 | 0.0260 | 21.49 |
| NDBI | +0.7253 | **0.7766** | **0.8298** | 3.63 |
| NDWI | -0.1195 | 0.0418 | 0.0492 | 16.76 |

### 4.5 主結果と感度分析の比較

- 感度分析（`VALID_GIS_MASK == 1` 限定）では NDBI の重要度がさらに支配的になり（RF Importance 0.581→0.777）、NDVI・NDWI・ELEV_MEAN の相対的な寄与が下がる。`VALID_GIS_MASK == 1` は建物・道路等のGIS特徴量のいずれかが観測結果として0より大きいセルを指す（3.3節）。これに限定すると植生・水域・標高の勾配が失われるため、自然な傾向と解釈できる
- Spatial CV の R²（RF）は主結果 0.7801 → 感度分析 0.7233 に低下する。有効域全体（農地・水域を含む）の方が、`VALID_GIS_MASK == 1` 限定より説明力が高い
- 建物高さ列（`BUILD_H_MEAN`/`BUILD_H_MAX`）のVIFはいずれの条件でも極めて高い（主結果41.38/47.56、感度分析36.24/41.42）。5.4節で解釈する

### 4.6 SHAP 平均絶対値

| 変数 | 主結果 | 感度分析 |
|---|---|---|
| NDBI | 0.6555 | 1.1434 |
| NDVI | 0.5215 | 0.1310 |
| NDWI | 0.3131 | 0.1177 |
| ELEV_MEAN | 0.3088 | 0.3319 |
| ROAD_DEN | 0.0612 | 0.0504 |
| BUILD_H_MEAN | 0.0585 | 0.1052 |
| BUILD_H_MAX | 0.0408 | 0.0615 |
| BUILD_DEN | 0.0042 | 0.0121 |
| BUILD_COV | 0.0038 | 0.0122 |

SHAPでも NDBI が両条件で最大であり、RF Importance と整合する。感度分析ではNDVI・NDWIのSHAP寄与が大きく下がる一方、NDBIの寄与が上がる。

---

## 5. 結果の解釈

### 5.1 まず言えること

30m・単一観測日において、Limited シナリオ（衛星指標 + 公開GIS）は Random Forest の random split `R²=0.7952`、Spatial CV `R² mean=0.7801` であった。NDBI（建築密度指標）が RF Importance・Permutation Importance・SHAP のいずれでも最大であり、昇温側の主要因である。

### 5.2 各変数の解釈

NDVI・NDWI は標準化係数が負（冷却方向）、NDBI・BUILD_COV・BUILD_H_MEAN・ROAD_DENは正（昇温方向）であり、植生・水域が冷却、建築・道路が昇温という直感的に妥当な符号関係を示す。ただし `BUILD_H_MAX` の係数は負（-0.031）であり、`BUILD_H_MEAN` と符号が逆転している点は単純な解釈が難しい（5.4節参照）。

`ELEV_MEAN` の係数が負（標高が高いほどLSTが低い）であるのは、標高上昇に伴う気温低減という一般的な傾向と整合する。

### 5.3 VALID_GIS_MASK を主結果に課さなかった判断の妥当性

3.3節の実測（`VALID_GIS_MASK == 0` が全件 `no_gis_feature` で `missing_gis_data` が0件）を踏まえ、主結果ではこの条件を課さなかった。ただしこの「0件」という実測は、建物パラメータテーブルの結合が正準グリッド全体に対して完全であることの確認に過ぎず、GBAが現地の建物を漏れなく検出できていることまでは保証しない（3.2節・3.3節参照）。この限界を踏まえてもなお、`VALID_GIS_MASK == 0` のセルを観測結果として0扱いする判断自体は妥当と考えられる（3.3節）。

4.5節の比較から、この判断により Spatial CV R²（RF）は0.7801（主結果）対0.7233（`VALID_GIS_MASK == 1` 限定）と、有効域全体を対象にした方が高い説明力を示すことが確認できた。これは「Limitedシナリオが農地・水域を含む多様な土地被覆下でLSTをどれだけ説明できるか」という本Issueの評価意図と整合する。

### 5.4 建物高さ列の多重共線性について（要検討事項）

計画段階で懸念していたとおり、建物高さの0補完（`BUILD_COV == 0 AND BUILD_DEN == 0` のセルへの適用）により、`BUILD_H_MEAN`/`BUILD_H_MAX` のVIFが極めて高い値（主結果41.38/47.56、感度分析36.24/41.42。慣例的な危険水準VIF>10を大きく超える）を示した。

これは補完によって「高さ0」の大きなスパイクが「建物が無い」セルと完全に共起し、2つの高さ変数（`BUILD_H_MEAN`と`BUILD_H_MAX`）が互いに強く相関する（高さが0のセルでは両者とも0になる）ことに加え、`BUILD_COV`（被覆率）・`BUILD_DEN`（棟数密度）とも「建物の有無」を重複して符号化している可能性を示唆する。一方で、SHAP・RF Importance上は `BUILD_COV`/`BUILD_DEN` 自体の寄与が非常に小さい（主結果 SHAP 0.0038/0.0042、RF Importance 0.0020/0.0021）ため、建物の有無に関する情報は主に高さ2変数に吸収されていると見られる。

この状態のまま9変数構成の標準化係数を「支配的な変数」の根拠とすることには解釈上の疑義がある。Satellite Only の既存結果と同様の方針で、**線形回帰の標準化係数の絶対値順位は補助的な情報として扱い、変数重要度の主たる解釈は Random Forest の重要度と SHAP に基づく**。建物高さ2変数の統合（例: 主成分化）や `BUILD_COV`/`BUILD_DEN` の除外による多重共線性の解消は、本ドキュメントでは行わず今後の検討課題とする（6節）。

`NDVI`・`NDWI` のVIF（主結果22.31・21.17、感度分析21.49・16.76）も Satellite Only の既存結果（21.09・20.05）と同水準の高さであり、同じ植生指標間の共線性が継続している。

### 5.5 Satellite Only との参考比較（非公式・スコープ外）

以下は定量的な比較検証ではなく、目視での妥当性確認のための参考情報である（格子・観測日は同一だが特徴量集合が異なるため、厳密な比較ではない）。

| 指標 | Satellite Only（3変数） | Limited 主結果（9変数） |
|---|---|---|
| Linear R²（random split） | 0.5645 | 0.6696 |
| RF R²（random split） | 0.7427 | 0.7952 |
| RF R²（Spatial CV mean） | 0.7277 | 0.7801 |

説明変数が増えるほどR²が向上する自然な傾向であり、不自然な値（負・1超・分割間の極端な乖離）は見られない。定量的な改善幅の評価は別Issueで扱う。

---

## 6. 今後の研究の方向性

- **Full シナリオへ進む**: 測量GISを加えた Full が Limited をどれだけ改善するかを、同じ共通モジュール（`src.common.*`, `src.common.analysis_runs`）を再利用して確認する
- **建物高さ列の多重共線性の解消方法の検討**: `BUILD_H_MEAN`/`BUILD_H_MAX` のVIFが極めて高い状態（5.4節）を、主成分化・変数統合・`BUILD_COV`/`BUILD_DEN`除外のいずれで対応するかを別途検討する
- **GBAの有効カバレッジそのものの検証**: 3.3節で指摘したとおり、`missing_gis_data == 0` はテーブル結合の完全性のみを示し、GBAが現地の建物を漏れなく検出できているかは未検証である。別途、現地測量データや高解像度衛星画像との突合による検証を検討する
- **30mでの観測日拡張**: Satellite Only と同様、複数観測日が揃った時点で同じ経路での複数日比較を検討する
- **Satellite Only との定量比較**: 5.5節の参考比較を、正式な改善幅の評価として別Issueで扱う
