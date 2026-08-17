# Satellite Only 分析結果（cell_id結合経路）

**最終更新**: 2026-08-17  
**関連ドキュメント**: [satellite_only_analysis_results.md](satellite_only_analysis_results.md), [analysis_rq3_satellite_only_guide.md](../02_methods/analysis_rq3_satellite_only_guide.md), [calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md) 6.7節, [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

---

## 0. 既存結果との関係（必読）

本ドキュメントは、既存の [satellite_only_analysis_results.md](satellite_only_analysis_results.md)（旧経路・ピクセル単位・3観測日）とは**別のパイプラインによる別物の結果**である。**数値を直接比較しない。**

| 観点 | 旧（ピクセル単位・CSV経路） | 新（cell_id・GeoPackage経路、本ドキュメント） |
|---|---|---|
| 集計単位 | Landsat ピクセル | 正準グリッドのセル |
| 格子 | 旧経路独自。セル単位の対応づけ不可 | 正準グリッド（EPSG:5897） |
| 観測日数 | 3観測日 | 1観測日（`20230707_032329`） |
| Spatial CV | 経緯度の分位ビン（ブロックの物理サイズが不均一） | row/colベースの物理的に等間隔なブロック |

格子が一致しないため、セル単位の対応づけによる差分評価もできない（[calc_urban_params_guide.md](../02_methods/calc_urban_params_guide.md) 6.7節）。旧結果はピクセル単位の先行結果として引き続き保持する。

---

## 1. 今回の位置づけ

RQ3 では Full / Limited / Satellite Only の3シナリオを比較する。現時点で Limited / Full は未完了であり、Satellite Only をベースラインとして先に成立させる段階にある。

本ドキュメントは、旧実装（ピクセル単位・大規模CSV経路）を関数単位で選別移植した新経路（`cell_id` 結合のGeoPackage経路）による再実行結果を記録する。新経路への移行理由・設計判断は実装時の計画書、共通モジュール化の経緯は下記関連ドキュメントを参照。

分析対象は **30m・単一観測日（`2023-07-07T03:23:29Z`）** に限定する。着手時点で30m/90mは当該観測日のテーブルのみ整備済みのため（他日時への拡張は別途行う）。

---

## 2. 今回実施したこと

1. `src/analysis/build_dataset.py` で `cell_id` キーの分析用データセット（GeoPackage）を生成した
2. 品質列（`IN_ANALYSIS_AREA` / 特徴量・目的変数の非NULL / `LST_VALID_RATIO`）でフィルタし、乱数シード固定でサンプリングした
3. Multiple Linear Regression（X・y双方標準化）と Random Forest を random split で比較した
4. 正準グリッドの row/col から作った物理的に等間隔な空間ブロックで Spatial CV（Group K-Fold）を実施した
5. Random Forest に対して SHAP を計算し、変数重要度と寄与方向を確認した
6. 移植前後の等価性をゴールデン比較で確認した（4.6節）

---

## 3. データと処理条件

### 3.1 入力データセット

- `data/output/datasets/dataset_satellite_only_20230707_032329_hanoi_30m.gpkg`
- 生成コマンド: `python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20230707_032329 lst_20230707_032329 --name satellite_only_20230707_032329`
- 全セル数: 3,739,454行（30m正準グリッドの全域）

### 3.2 品質管理（フィルタ条件）

以下をすべて満たすセルのみを分析対象とする。

- `IN_ANALYSIS_AREA == 1`
- `LST` / `NDVI` / `NDBI` / `NDWI` が非NULL
- `LST_VALID_RATIO >= 0.5`（**採用したしきい値**。`VALID_SATELLITE_MASK` は NDVI/NDBI/NDWI いずれかの非NULLというORで定義されておりLSTの被覆率を包含しないため、独立にこのしきい値を課している）

フィルタ後の母数: **1,955,963セル**（しきい値0.5により、`ratio < 0.5` の1,938セル・0.099%を追加除外）。

### 3.3 サンプリング

- 適用順序: フィルタ → サンプリング → ブロック割り当て（ブロック割り当てを先にすると各ブロックのセル数が不均等に減り、fold のサイズ均衡が崩れるため）
- サンプル数: `100,000`（既定値。根拠は旧実装の踏襲ではなく、支配的な計算コストがRFの学習そのものであるため）
- 乱数シード: `42`

### 3.4 モデル設定

- 学習 / テスト: `80,000 / 20,000`（random split、`test_size=0.2`）
- 説明変数: `NDVI`, `NDBI`, `NDWI`
- 目的変数: `LST`
- MLR: 説明変数・目的変数の両方を標準化（標準化偏回帰係数として解釈）
- RF: `n_estimators=300`, `min_samples_leaf=5`
- Spatial CV:
  - `5-fold`（Group K-Fold、group = 空間ブロックID）
  - ブロック定義: 正準グリッドの row/col 絶対インデックスを `block_size_m // scale` セルで整数除算（原点はデータに依存させない）
  - ブロックサイズ: `2,700m`（`SNAP_UNIT_M`=900mの倍数。30/90/300mのいずれでも割り切れ、スケールを変えてもブロック境界が一致する）
  - 非空ブロック数: 306（フィルタ後全数ベース）、305（10万件サンプル後ベース）
- SHAP:
  - 評価サンプル: `2,000`
  - background: `500`

### 3.5 出力ファイル

`data/output/satellite_only_cellbased/20230707_032329/` に以下を保持する（接頭辞は `dataset_satellite_only_20230707_032329_hanoi_30m`）。

- `*_sample_100000.csv`: サンプリング結果
- `*_feature_importance.csv`: 係数・重要度・VIF
- `*_spatial_cv_folds.csv`: fold別評価値
- `*_model_comparison.png`, `*_feature_importance.png`, `*_spatial_cv.png`: 可視化
- `*_shap_importance.csv`, `*_shap_summary.png`, `*_shap_bar.png`, `*_shap_dependence_{NDVI,NDBI,NDWI}.png`: SHAP関連
- `*_results.json`: 全結果の要約

---

## 4. 基本結果

### 4.1 ランダム分割でのモデル性能

| モデル | R² | RMSE | MAE |
|---|---|---|---|
| Linear Regression | 0.5645 | 1.3894 | 1.0099 |
| Random Forest | 0.7427 | 1.0680 | 0.8011 |

### 4.2 Spatial CV でのモデル性能

| モデル | R² mean | R² std | RMSE mean | MAE mean |
|---|---|---|---|---|
| Linear Regression | 0.5541 | 0.0369 | 1.3924 | 1.0173 |
| Random Forest | 0.7277 | 0.0245 | 1.0866 | 0.8114 |

random split から Spatial CV への性能低下は RF で `0.7427 → 0.7277`（-0.015）、LR で `0.5645 → 0.5541`（-0.010）と小幅であり、ランダム分割の性能が空間自己相関だけで説明される過大評価ではないと解釈できる。

### 4.3 変数重要度

| 指標 | \|標準化係数\| | RF Importance | Permutation Importance | VIF |
|---|---|---|---|---|
| NDVI | 1.2610 | 0.1759 | 0.2714 | 21.0914 |
| NDBI | 0.5410 | 0.6649 | 0.8005 | 1.3524 |
| NDWI | 1.2264 | 0.1592 | 0.2846 | 20.0547 |

RF Importance・Permutation Importance ともに NDBI が最大であり、旧結果（3観測日）と同じ「NDBI優位」の傾向を示す。

### 4.4 SHAP 平均絶対値

| NDBI | NDVI | NDWI |
|---|---|---|
| 0.8860 | 0.4839 | 0.4038 |

SHAPでも NDBI が最大であり、RF Importance と整合する。

### 4.5 Spatial CVブロック境界の影響概算

`GroupKFold` を据え置いたことによる限界（ブロック境界で隣接するセル同士が train/test に分かれる可能性）を定量化した（フィルタ後全数1,955,963セルを対象、block_size_m=2,700m）。

| 指標 | 値 |
|---|---|
| 境界セル（上下左右いずれかの隣接セルが別ブロック）の割合 | 4.42%（86,416 / 1,955,963セル） |
| 別foldの隣接セルを持つセルの割合 | 3.67%（71,804 / 1,955,963セル） |
| 境界セルのうち別foldに落ちる割合 | 83.09% |

境界セルの多くは実際に別foldへ分かれており、空間的な独立性は完全ではない。ただし対象は全体の4%程度に限られ、Spatial CV全体の評価傾向（4.2節）を覆すほどの規模ではないと考えられる。バッファ付き leave-block-out 等でこの残差リークを塞ぐかどうかは、本Issueのスコープ外の手法選択として別途検討する。

### 4.6 移植の等価性確認（ゴールデン比較）

旧実装のサンプルCSV（`data/output/satellite_only/20230707_032329Z/satellite_only_20230707_20230707_032329Z_sample_100000.csv`）を入力に、新共通モジュール（`src.common.model_metrics` / `src.common.regression_models`）と旧実装の計算結果を突き合わせた。

VIF・線形回帰の R²/RMSE/MAE・標準化偏回帰係数・RF の R²/RMSE/MAE・RF Importance のすべてが、小数点以下の精度まで**完全に一致**した。関数単位の移植（`compute_vif` / `fit_linear_regression` / `fit_random_forest`）が数値的に等価であることを確認できた。

Spatial CV はブロック定義を再設計しているため、この比較の対象外である（一致しない前提）。SHAP は背景データのサンプリング乱数に依存するため厳密な一致は確認していない。

**この一致は移植前後の等価性を示すのみであり、旧結果（≒新結果）の妥当性を保証するものではない。**

---

## 5. 結果の解釈

### 5.1 まず言えること

30m・単一観測日でも、**衛星指標だけでLSTを一定程度説明できる**。Random Forest の random split `R²=0.7427`、Spatial CV `R² mean=0.7277` であり、旧結果（3観測日、RF Spatial CV `R² mean` 0.6032〜0.6965）と同水準かやや高い。ただし観測日数・格子が異なるため（0節）、この比較は参考程度に留める。

### 5.2 各変数はどう解釈できるか

NDBI が RF Importance・Permutation Importance・SHAP のいずれでも最大であり、昇温側の主要因である。NDVI・NDWI は標準化係数が負（冷却方向）であり、旧結果と同じ「NDBI昇温・NDVI/NDWI冷却」という構図を示す。

### 5.3 多重共線性の扱い

NDVI・NDWI の VIF（21.09・20.05）は慣例的な危険水準（VIF > 10）を超えており、旧結果（20.21・19.18）と同様の傾向である。VIFの計算自体は標準的な定義に従っており実装上の誤りではないが、この状態で標準化偏回帰係数を「支配的な変数」の根拠とすることには解釈上の疑義がある。

旧結果ドキュメントの方針を踏襲し、**線形回帰の標準化係数の絶対値順位は補助的な情報として扱い、変数重要度の主たる解釈は Random Forest の重要度と SHAP に基づく**。変数選択（NDVIまたはNDWIの除外等）による多重共線性の解消は本ドキュメントでは行わない。

### 5.4 Spatial CVの限界

4.5節で示したとおり、ブロック境界に位置するセル（全体の4.42%）の8割以上が隣接ブロックと異なるfoldに分かれており、空間的な独立性は部分的である。`GroupKFold` を据え置いたのは意図的な見送りであり、バッファ付き leave-block-out の導入は手法選択として独立に検討する。

---

## 6. 今後の研究の方向性

- **30mでの観測日拡張**: `20230723_032309` / `20241130_032336` の `idx_*`/`lst_*` テーブル算出は別Issueで扱う。複数観測日が揃った時点で、旧結果と同様の複数日比較を新経路でも実施する
- **Limited シナリオへ進む**: 公開GISを加えた Limited が Satellite Only をどれだけ改善するかを、同じ共通モジュール（`src.common.*`）を再利用して確認する
- **バッファ付き Spatial CV の検討**: 4.5節の残差リークを踏まえ、leave-block-out 等の手法導入を別Issueとして起票する
