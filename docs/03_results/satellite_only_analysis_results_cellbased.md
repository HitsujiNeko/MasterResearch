# Satellite Only 分析結果（cell_id結合経路）

**最終更新**: 2026-10-22  
**関連ドキュメント**: [limited_analysis_results.md](limited_analysis_results.md), [survey_area_comparison_results.md](survey_area_comparison_results.md), [satellite_only_analysis_results.md](satellite_only_analysis_results.md), [satellite_only_analysis_results_cellbased_20230707_032329.md](../04_archive/satellite_only_analysis_results_cellbased_20230707_032329.md), [analysis_rq3_satellite_only_guide.md](../02_methods/analysis_rq3_satellite_only_guide.md), [calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.7節, [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

---

## 0. 他の結果ドキュメントとの関係（必読）

本ドキュメントは30m・`cell_id` 結合経路による Satellite Only シナリオの結果である。**主結果は、主採用の観測 `2022-09-06T03:23:58Z`（以下 032358）による7章である。** 1〜6章は旧採用の観測 `2023-07-07T03:23:05Z`（以下 032305）による結果であり、比較用の観測の結果として残す。7章と1〜6章は観測が異なるため、LST の絶対値・RMSE（°C）を直接比べず、相対的な量だけを比べる（7.5節）。

**次の2つとは数値を直接比較しない。**

| 相手 | 何が違うか |
|---|---|
| [satellite_only_analysis_results.md](satellite_only_analysis_results.md)（旧ピクセル経路・3観測日） | 集計単位（Landsatピクセル 対 正準グリッドのセル）・格子・観測日数・Spatial CV の定義。格子が一致しないため、セル単位の対応づけによる差分評価もできない（[calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.7節） |
| [satellite_only_analysis_results_cellbased_20230707_032329.md](../04_archive/satellite_only_analysis_results_cellbased_20230707_032329.md)（同一経路・観測032329） | 観測。処理条件は同一だが母数が異なり、そこから抽出される10万件も別物である |

[Limited](limited_analysis_results.md) とは観測・格子・経路・ブロック定義が一致する。ただし説明変数の集合が異なり母数も揃っていないため、**シナリオ間の比較は参考の位置づけにとどまる**。参考比較の数値は Limited 側を正本とする（032358 は8.6節、032305 は6.7節。本ドキュメントに重複させない）。

---

## 1. 位置づけ

RQ3 では Full / Limited / Satellite Only の3シナリオを比較する。本ドキュメントは、そのうち衛星由来の分光指数のみを説明変数とする最小構成のベースラインを記録する。

観測 032305 への移行は、Limited シナリオが同観測で再構築されたことに伴うものである。**シナリオ間の比較を同一観測・同一格子のうえで行うことが移行の目的である。** その後、主採用の観測を 032358 に変えたため（[observation_selection.md](../02_methods/observation_selection.md) 8章）、Limited と同じ観測で再実行した結果を7章に記録する。

### 1.1 数値の正本

本ドキュメントの数値は次のファイルから読める。いずれも Git 管理下にある（サンプルCSV `*_sample_*.csv` のみ管理外）。

| 種別 | ファイル |
|---|---|
| 標準化係数・RF重要度・Permutation重要度・VIF | `{接頭辞}_feature_importance.csv` |
| SHAP 平均絶対値 | `{接頭辞}_shap_importance.csv` |
| 全結果の要約（母数・フィルタ脱落診断を含む） | `{接頭辞}_results.json` |
| fold別評価値 | `{接頭辞}_spatial_cv_folds.csv` |

接頭辞は `dataset_satellite_only_20230707_032305_hanoi_30m`、配置は `data/output/satellite_only_cellbased/20230707_032305/` である。**7章（主採用の観測）は接頭辞 `dataset_satellite_only_20220906_032358_hanoi_30m`、配置は `data/output/satellite_only_cellbased/20220906_032358/` である。**

測量GIS範囲と全域の比較（新世代の指標から作り直したデータセットによる）は `data/output/satellite_only_cellbased/20230707_032305_area_comparison/` に置き、[survey_area_comparison_results.md](survey_area_comparison_results.md) を正本とする。同ディレクトリの全域ランは本ドキュメントの数値と世代が異なるため、直接比較しない（3.1節）。

**4.5節（ブロック境界の実測）だけは上記ファイルに含まれない。** フィルタ後全数を対象とした一時的な診断であり、算出方法を同節に記す（再測定にはデータセットの再生成が要る）。

### 1.2 結果の一般化可能性の限界

本ドキュメントの各結果は **ハノイROI・30m・単一観測**（7章は 032358、1〜6章は 032305）のものである。雨季の2観測で同じ処理を回した比較は7.5節にあるが、乾季の観測・他の時刻・他の都市での再現性は検証していない。

---

## 2. 実施したこと

1. `src/analysis/build_dataset.py` で `cell_id` キーの分析用データセット（GeoPackage）を生成した
2. 品質列（`IN_ANALYSIS_AREA` / 特徴量・目的変数の非NULL / `LST_VALID_RATIO`）でフィルタし、乱数シード固定でサンプリングした
3. フィルタで脱落したセルの内訳を診断として記録した（3.6節）
4. Multiple Linear Regression（X・y双方標準化）と Random Forest を random split で比較した
5. 正準グリッドの row/col から作った物理的に等間隔な空間ブロックで Spatial CV（Group K-Fold）を実施した
6. Random Forest に対して SHAP を計算し、変数重要度と寄与方向を確認した
7. Spatial CV のブロック境界が生む残差リークの規模を、フィルタ後全数で実測した（4.5節）

---

## 3. データと処理条件

### 3.1 入力データセット

- `data/output/datasets/dataset_satellite_only_20230707_032305_hanoi_30m.gpkg`（`.gitignore` 対象・再生成可能）
- 生成コマンド:

```bash
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20230707_032305 lst_20230707_032305 --name satellite_only_20230707_032305
```

- 全セル数: 3,739,454行・10列（30m正準グリッドの全域と一致）
- `idx_*` と `lst_*` が同一観測であることは、結合前に `validate_observation_consistency()` が検証する
- **上記コマンドで再生成しても、本ドキュメントの数値は再現できない。** 30m の `idx_20230707_032305` は、Limited の水指数の構成比較のために作り直した新世代（ROI でクリップ済み・MNDWI 列あり）へ置き換わっている。本ドキュメントのデータセットはその前の旧世代の指標から作ったものであり、ROI 境界のセルで値と母数が変わる（世代の違いと差の実測は [limited_analysis_results.md](limited_analysis_results.md) 1.4節・3.10節）

### 3.2 品質管理（フィルタ条件）

以下をすべて満たすセルのみを分析対象とする。

- `IN_ANALYSIS_AREA == 1`
- `LST` / `NDVI` / `NDBI` / `NDWI` が非NULL
- `LST_VALID_RATIO >= 0.5`（**採用したしきい値**。`VALID_SATELLITE_MASK` は NDVI/NDBI/NDWI いずれかの非NULLというORで定義されておりLSTの被覆率を包含しないため、独立にこのしきい値を課している）

フィルタ後の母数は **3,317,272セル**（ROI内の 88.8%）。段階ごとの内訳は3.6節に示す。

### 3.3 サンプリング

- 適用順序: フィルタ → サンプリング → ブロック割り当て（ブロック割り当てを先にすると各ブロックのセル数が不均等に減り、fold のサイズ均衡が崩れるため）
- サンプル数: `100,000`（母数の 3.01%）
- 乱数シード: `42`

### 3.4 モデル設定

- 学習 / テスト: `80,000 / 20,000`（random split、`test_size=0.2`）
- 説明変数: `NDVI`, `NDBI`, `NDWI`
- 目的変数: `LST`（**摂氏**）
- MLR: 説明変数・目的変数の両方を標準化（標準化偏回帰係数として解釈）
- RF: `n_estimators=300`, `min_samples_leaf=5`
- Spatial CV:
  - `5-fold`（Group K-Fold、group = 空間ブロックID）
  - ブロック定義: 正準グリッドの row/col 絶対インデックスを `block_size_m // scale` セルで整数除算（原点はデータに依存させない）
  - ブロックサイズ: `2,700m`（`SNAP_UNIT_M`=900mの倍数。30/90/300mのいずれでも割り切れ、スケールを変えてもブロック境界が一致する）
  - 非空ブロック数: 509（脱落集計の基準段階ベース）、508（フィルタ後全数ベース）、504（10万件サンプル後ベース）
- SHAP: 評価サンプル `2,000` / background `500`

**本ドキュメントのラン（032305）の `results.json` には `--random-state`（42）と `--rf-trees`（300）が記録されていない。** いずれも既定値のまま実行したが、当該ランは実行パラメータ記録の導入前に実行したためである。**既定値が変われば引数を省略した再実行では同じ条件を再現できないため、再現時は `--random-state 42 --rf-trees 300` を明示する。** 導入後のランでは、これらを含む実行パラメータが `results.json` の `run_parameters` に記録される（キー構成は Limited と共通。記録範囲の判断は `src/common/run_parameters.py` のmodule docstringを正本とする）。既存ランは再実行・`results.json` の追記修正を行わない（記録値を後から書き足すと、実行時に実際に使われた値であることを結果ファイル自身が保証できなくなるため。上記の値は本節の記述を正とする）。

### 3.5 出力ファイル

`data/output/satellite_only_cellbased/20230707_032305/` に以下を保持する（接頭辞は `dataset_satellite_only_20230707_032305_hanoi_30m`）。

- `*_sample_100000.csv`: サンプリング結果（`.gitignore` 対象・Git管理外）
- `*_feature_importance.csv`: 係数・重要度・VIF
- `*_spatial_cv_folds.csv`: fold別評価値
- `*_model_comparison.png`, `*_feature_importance.png`, `*_spatial_cv.png`: 可視化
- `*_shap_importance.csv`, `*_shap_summary.png`, `*_shap_bar.png`, `*_shap_dependence_{NDVI,NDBI,NDWI}.png`: SHAP関連
- `*_results.json`: 全結果の要約

旧経路の出力先（`data/output/satellite_only/`）とは分離している。集計単位・格子が異なる別物であるためである（0節）。

### 3.6 フィルタ脱落の診断

**本節は分析結果ではなく、どのセルが分析対象から外れたかの記録である。** 数値は `results.json` の `filter_dropout` から読める。**この診断はアーカイブ版（032329ラン）には無い。** 診断の常設化が当該ランの実行後であったためである。**増えているのは診断項目だけであり、観測が異なる以上、結果そのものの上位互換ではない。**

#### 母数のファネル

| 段階 | セル数 | ROI比 |
|---|---|---|
| 正準グリッド全体 | 3,739,454 | — |
| ROI内（`IN_ANALYSIS_AREA == 1`） | 3,736,107 | 100% |
| LST非NULL かつ `LST_VALID_RATIO >= 0.5`（`target_available`、**脱落集計の基準段階**） | 3,337,319 | 89.3% |
| 説明変数の非NULL要求を通過（`feature_complete` ＝ 最終母数） | **3,317,272** | 88.8% |

Satellite Only は `required_mask_columns` が `IN_ANALYSIS_AREA` の1列のみであるため、Limited のような有効域品質列（人口・夜間光）による段は存在しない。

#### 要因別内訳（`target_available` を基準）

| 要因グループ | セル数 | 脱落セルの平均LST |
|---|---|---|
| 分光指数（`NDVI` / `NDBI` / `NDWI`） | 20,047 | 31.09°C |
| **脱落の和集合** | **20,047**（基準段階の 0.601%） | — |

説明変数は分光指数の3列のみであり、3列は同時にNULLになる（`columns.exclusive_null_count` は各0であり、規模は `column_groups` で読む）。脱落セルの平均LST（31.09°C）は最終母数の平均（35.49°C）より低く、**高温側のセルが系統的に欠ける種類の脱落ではない。**

#### 目的変数分布の変化

| 統計量 | 脱落前（`target_available`） | 脱落後（最終母数） |
|---|---|---|
| 件数 | 3,337,319 | 3,317,272 |
| 平均 | 35.47°C | 35.49°C |
| 標準偏差 | 2.54 | 2.52 |
| 最小 / 最大 | 23.85 / 51.57°C | 24.10 / 51.57°C |
| p1 / p50 / p99 | 29.28 / 35.19 / 42.08°C | 29.35 / 35.20 / 42.09°C |

分布はほぼ変わらない。**目的変数の裾を切り詰める脱落ではない。**

#### 空間的な集中

| 指標 | 値 |
|---|---|
| 基準段階のブロック数（2,700m） | 509 |
| ブロック別脱落率の中央値 | 0.0% |
| 同 p90 / p99 / 最大 | 3.59% / 32.96% / 100% |
| 脱落率が50%を超えるブロック | 3 |

**脱落は空間的に偏っている。** 半数以上のブロックでは脱落が生じない一方、ほぼ全損のブロックが3つある。全体では 0.601% にとどまり母集団の性格を変えるほどではないが、一様な脱落ではない点は解釈時に留意する。

---

## 4. 基本結果

### 4.1 ランダム分割でのモデル性能

| モデル | R² | RMSE | MAE |
|---|---|---|---|
| Linear Regression | 0.4828 | 1.8233 | 1.3507 |
| Random Forest | 0.6376 | 1.5261 | 1.1080 |

**RMSE は摂氏（°C）で読む。** RF で約 1.53°C である。

### 4.2 Spatial CV でのモデル性能

| モデル | R² mean | R² std | RMSE mean | MAE mean |
|---|---|---|---|---|
| Linear Regression | 0.4767 | 0.0373 | 1.8129 | 1.3445 |
| Random Forest | 0.6297 | 0.0404 | 1.5240 | 1.1084 |

random split から Spatial CV への変化は RF `0.6376 → 0.6297`（-0.008）、線形 `0.4828 → 0.4767`（-0.006）である。

**この低下の小ささを「空間自己相関による過大評価が無い」根拠として読んではならない。** [limited_analysis_results.md](limited_analysis_results.md) 3.9節の実測では、LST のセミバリアンスは 2,700m 地点で全体分散の69%にとどまり、sill に達するのは15〜30kmである。またブロックを広げると R² は単調に低下する。**目的変数とブロック定義は本シナリオと共通であるため、同じ制約がかかる。** 低下が小さいのは過大評価が無いからではなく、ブロックが小さく学習側と評価側が空間的に近いままであるためと解釈する。**本シナリオでのブロックサイズ感度の測定は未実施である。**

fold別の値は `*_spatial_cv_folds.csv` にある。RF の R² は fold 1〜3 が 0.583〜0.620、fold 4・5 が 0.681・0.673 と二分され、線形も同じ向きに分かれる（fold 1〜3 が 0.442〜0.449、fold 4・5 が 0.522・0.523）。**両モデルで同じ fold が高いことから、これはモデルの性質ではなく fold の地域差による。** fold間sd（RF 0.040）はこの偏りを反映している。

### 4.3 変数重要度

| 指標 | \|標準化係数\| | RF Importance | Permutation Importance | VIF |
|---|---|---|---|---|
| NDVI | 1.0826 | 0.1470 | 0.1631 | 26.8271 |
| NDBI | 0.5280 | 0.6619 | 0.6653 | 1.5101 |
| NDWI | 1.2079 | 0.1911 | 0.2510 | 25.1451 |

RF Importance・Permutation Importance ともに **NDBI が最大**であり、いずれも他の2変数の合計を上回る。標準化係数の絶対値では NDWI・NDVI が上位に来るが、両者の VIF は危険水準を大きく超えており（5.3節）、この順位を支配的な変数の根拠としない。

標準化係数の符号は `NDVI` −1.0826 / `NDBI` +0.5280 / `NDWI` −1.2079 であり、**NDBI が昇温側、NDVI・NDWI が冷却側**である。

### 4.4 SHAP 平均絶対値

| NDBI | NDVI | NDWI |
|---|---|---|
| 1.1481 | 0.4554 | 0.4283 |

SHAP でも NDBI が最大であり、RF Importance・Permutation Importance と整合する。**3つの指標が一致して NDBI を首位とするため、この順位は指標の選び方に依存しない。**

### 4.5 Spatial CVブロック境界の影響（実測）

`GroupKFold` を据え置いたことによる限界（ブロック境界で隣接するセル同士が train / test に分かれる）の規模を、フィルタ後全数 3,317,272セルを対象に実測した。

**算出方法**: 各セルの `cell_id` から正準グリッドの row/col を復元し、上下左右4方向の隣接セルが属するブロックを `assign_canonical_blocks` と同一の規則（`block_size_m=2,700`・`scale=30`）で求める。**隣接セルが母集団に実在し、かつ別ブロックに属する**場合に境界セルとする。fold は `split_by_spatial_blocks`（5-fold）がブロックへ割り当てたものを用いる。**この fold はフィルタ後全数（508ブロック）に対して割り当てたものであり、4.2節の Spatial CV が用いる10万件サンプルの fold（504ブロック）とは別である。**

| 指標 | 値 |
|---|---|
| 境界セル（上下左右いずれかの隣接セルが実在し、かつ別ブロック）の割合 | 4.39%（145,730 / 3,317,272セル） |
| 別foldの隣接セルを持つセルの割合 | 3.83%（126,974 / 3,317,272セル） |
| 境界セルのうち別foldに落ちる割合 | 87.13% |

隣接セルの実在を問わず位置だけで判定しても 146,018セル（4.40%）・127,222セル（3.84%）・87.13% とほぼ変わらない（母集団がブロックをおおむね埋めているため）。**4.2節の Spatial CV が実際に用いる10万件サンプルの fold で測り直すと、別foldの隣接セルを持つ割合は 3.59%（119,223セル）、境界セルのうち別foldに落ちる割合は 81.81% に下がる。** 上表は母集団全数の fold で測った、より保守的な値である。

境界セルの多くは実際に別foldへ分かれており、**空間的な独立性は完全ではない**。対象は全体の4%程度に限られるが、**本節が測ったのはセル数の割合だけであり、これが 4.2節の R² をどれだけ押し上げているかは未評価である**。境界セルを除外した再評価・バッファ付き leave-block-out・性能指標への感度分析は、いずれも実施していない。**したがって「規模が小さいから評価傾向は変わらない」とは本節の測定からは言えない。** 対処の要否は手法選択として独立に検討する。

---

## 5. 結果の解釈

### 5.1 まず言えること

30m・単一観測でも、**衛星由来の分光指数3つだけで LST の6割程度を説明できる**（Random Forest の random split `R²=0.6376`、Spatial CV `R² mean=0.6297`）。線形モデルでは 0.48 前後にとどまる。

**RF と線形の差（random split で +0.155、Spatial CV で +0.153）の内訳は本シナリオでは切り分けていない。** 非線形性の捕捉によるものか、空間自己相関の利用によるものかは分離できておらず、Limited 側では後者の寄与が相当あると示唆されている（[limited_analysis_results.md](limited_analysis_results.md) 3.9節）。

また 4.2節のとおり、Spatial CV の値を「未知の場所への汎化性能」として読んではならない。**同一ROI内・空間的に近い場所への内挿性能**として読む。

### 5.2 各変数はどう解釈できるか

NDBI が RF Importance・Permutation Importance・SHAP のいずれでも最大であり、昇温側の主要因である。NDVI・NDWI は標準化係数が負であり、冷却方向に寄与する。**「NDBI昇温・NDVI/NDWI冷却」という構図は、都市化した被覆ほど高温という一般的な理解と整合する。**

ただし NDVI については、目的変数との間接的な結合の可能性が残る（6節）。

### 5.3 多重共線性の扱い

NDVI・NDWI の VIF（26.83・25.15）は慣例的な危険水準（VIF > 10）を大きく超えている。VIF の計算自体は標準的な定義に従っており実装上の誤りではないが、この状態で標準化偏回帰係数を「支配的な変数」の根拠とすることには解釈上の疑義がある。

**線形回帰の標準化係数の絶対値順位は補助的な情報として扱い、変数重要度の主たる解釈は Random Forest の重要度と SHAP に基づく。** 変数選択（NDVI または NDWI の除外等）による多重共線性の解消は本ドキュメントでは行わない。

**Limited とは分光指数の変数定義が揃っていない。** Limited では水指数の扱いを同一セル上で比較し、NDWI を除外する構成を採用した（[limited_analysis_results.md](limited_analysis_results.md) 6.5節）。同節の比較では、ラン1の NDVI・NDWI の標準化係数（第1・2位）が共線性のアーティファクトであり、共線性を解消すると NDVI の係数がほぼ0になることも示された。本ドキュメントの3変数構成でも同じ構造の共線性があるため、**NDVI・NDWI の標準化係数を個別の寄与として読んではならない**。**この変数定義の不整合は残っており、解消は後続の課題として別途扱う**（Satellite Only 側でも同じ構成比較を行うか、変数の定義をシナリオ間で揃えるかを判断する・6章）。

### 5.4 Spatial CVの限界

限界は2つあり、**わかっている度合いが異なる**。

1. **ブロックサイズが空間自己相関の到達距離に対して小さい**（4.2節）。Limited 側でブロックを広げると R² が単調に低下することが実測されており、**報告する R² の読み方そのものに関わる**
2. **ブロック境界の残差リーク**（4.5節）。境界セルは全体の 4.39% で、その 87.13% が別fold の隣接セルを持つ。**セル数の規模は限定的だが、R² への影響は測っておらず未評価である**

`GroupKFold` の据え置きは意図的な見送りである。バッファ付き leave-block-out やブロックサイズの見直しは、Limited と共通の方法論上の課題として独立に検討する。

---

## 6. 今後の研究の方向性

- **Limited / Full との改善幅の評価**: 観測・格子・ブロック定義が揃ったことで、参考比較を同一観測どうしで行えるようになった（[limited_analysis_results.md](limited_analysis_results.md) 6.7節）。ただし説明変数の集合が異なり母数も揃っていないため、**Satellite Only をベースラインとした正式な改善幅の評価は別途扱う**。共通するセルに限定した評価の設計が要る
- **Spatial CV の設計見直し**: 5.4節の2つの限界のうち、ブロックサイズの見直しの優先度が高い。シナリオ横断の方法論として扱う
- **分光指数間の共線性の解消**: `NDVI` 26.83・`NDWI` 25.15 の VIF は未解決である。Limited では水指数の構成を同一セル上で比較し NDWI を除外する構成を採用したが（[limited_analysis_results.md](limited_analysis_results.md) 6.5節）、本シナリオでは構成比較は未実施である。本シナリオは説明変数が分光指数のみであり、NDWI を除外すると説明変数が2つになるため、Limited の結論をそのまま適用してよいかを含めて判断する
- **LSTプロダクトの算出仕様の確認**: Level-2 地表面温度プロダクトの放射率推定が同一シーンの植生指数を用いる場合、`NDVI` と `LST` の間に間接的な代数的依存が生じうる（[limited_analysis_results.md](limited_analysis_results.md) 3.9節）。**本シナリオは説明変数が分光指数のみであるため、この依存の影響を最も強く受ける。** 確認を要する
- **30mでの観測日拡張**: `20230723_032309` / `20241130_032336` の `idx_*` / `lst_*` テーブル算出は別途扱う。複数観測日が揃った時点で、同一経路での複数日比較を実施する

---

## 7. 主採用の観測（2022-09-06）の結果

**本章が Satellite Only シナリオの主結果である。** 主採用の観測 032358 で、1〜6章と同じ処理（分光指数3変数・全域）を30mで実行した。観測を変えた理由は [observation_selection.md](../02_methods/observation_selection.md) 8章を正本とする。

### 7.1 実行内容と数値の正本

- **出力先**: `data/output/satellite_only_cellbased/20220906_032358/`（接頭辞 `dataset_satellite_only_20220906_032358_hanoi_30m`）。数値の正本は1.1節と同じ種別のファイルである
- **データセット**: 現行の手順（新世代: ROI でクリップ済み・MNDWI 列あり）で作った指標テーブルから生成した。MNDWI 列はデータセットに含まれるが、説明変数・フィルタ列には使わない（3.2節と同じ）
- **処理条件**: 3.2〜3.4節と同じである（`IN_ANALYSIS_AREA == 1`・`LST_VALID_RATIO >= 0.5`・10万件・乱数シード42・RF 300本・ブロック 2,700m・5分割）。3.4節の注記と異なり、本章のランでは乱数シード・木の本数を含む実行パラメータが `results.json` の `run_parameters` に記録されている
- **来歴**: `results.json` の `provenance.git.dirty` は `false` であり、陳腐化チェック（`scripts/check_result_staleness.py`）で「最新」と判定される

生成コマンド（データセットは `.gitignore` 対象・再生成可能。指標・LST テーブルの生成は Limited 側 8.1節と共通）:

```bash
python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario satellite_only --tables idx_20220906_032358 lst_20220906_032358 --name satellite_only_20220906_032358
python -m src.analysis.analysis_rq3_satellite_only --dataset-path data/output/datasets/dataset_satellite_only_20220906_032358_hanoi_30m.gpkg --output-dir data/output/satellite_only_cellbased/20220906_032358 --scale 30 --random-state 42 --sample-size 100000 --block-size-m 2700 --cv-splits 5 --rf-trees 300
```

### 7.2 母数とフィルタ脱落

| 段階 | セル数 | ROI比 |
|---|---|---|
| 正準グリッド全体 | 3,739,454 | — |
| ROI内（`IN_ANALYSIS_AREA == 1`） | 3,736,107 | 100% |
| LST非NULL かつ `LST_VALID_RATIO >= 0.5`（`target_available`） | 3,492,215 | 93.5% |
| 説明変数の非NULL要求を通過（最終母数） | **3,491,872** | 93.5% |

- 分光指数の欠測による脱落は **343セル**（基準段階の 0.010%）にとどまる。032305 の 20,047セル（0.601%・3.6節。新世代の全域ランでは 20,059セル）から大きく減り、脱落率が50%を超えるブロックも無くなった（032305 では3つ）。ブロック別脱落率の最大は 1.05% である
- 脱落セルの平均 LST（29.63°C）は最終母数の平均（32.21°C）より低く、032305 と同じく高温側のセルが系統的に欠ける種類の脱落ではない
- 最終母数の LST の標準偏差は 2.65°C である（7.5節で誤差を正規化する分母に使う）。脱落の前後で分布の統計量はほぼ変わらない

### 7.3 モデル性能

| モデル | 評価 | R² | RMSE（°C） | MAE（°C） | RMSE ÷ LST の標準偏差 |
|---|---|---|---|---|---|
| Linear Regression | ランダム分割 | 0.6883 | 1.4737 | 1.1082 | 0.556 |
| Random Forest | ランダム分割 | 0.7543 | 1.3084 | 0.9853 | 0.493 |
| Linear Regression | Spatial CV（mean） | 0.6855（sd 0.0060） | 1.4850 | 1.1135 | 0.560 |
| Random Forest | Spatial CV（mean） | **0.7475**（sd 0.0144） | 1.3288 | 1.0013 | 0.501 |

- 非空ブロック数（10万件サンプル後）は 509 である
- ランダム分割から Spatial CV への低下は RF −0.007・線形 −0.003 と小さい。**4.2節と同じく、この小ささを空間自己相関による過大評価が無い根拠として読まない。** Spatial CV の値は同一ROI内・空間的に近い場所への内挿性能として読む
- fold 別の R² は RF で 0.729〜0.773 であり、032305 のように fold が2群に分かれる傾向（4.2節）は見られない。ただし fold間sd は標本で大きく動くため（Limited 側 2.1節）、032305 との差としては読まない

### 7.4 変数重要度

| 指標 | \|標準化係数\| | RF Importance | Permutation Importance | SHAP 平均絶対値 | VIF |
|---|---|---|---|---|---|
| NDVI | 0.2951 | 0.0895 | 0.0859 | 0.2977 | 36.58 |
| NDBI | 0.7963 | 0.8165 | 0.9548 | 1.3945 | 1.64 |
| NDWI | 0.3215 | 0.0940 | 0.2091 | 0.3456 | 34.34 |

- **4つの指標がそろって NDBI を首位とする。** 標準化係数の符号は `NDVI` −0.295 / `NDBI` +0.796 / `NDWI` −0.322 であり、**NDBI が昇温側、NDVI・NDWI が冷却側**という構図は 032305（4.3節）と同じである
- `NDVI`・`NDWI` の VIF（36.58・34.34）は危険水準（>10）を超えたままであり、032305 の新世代の全域ラン（26.47・24.76。7.5節の比較相手）より高い。**5.3節と同じく、`NDVI`・`NDWI` の標準化係数を個別の寄与として読まない**

### 7.5 旧採用との比較

**比較相手**: 032305 の新世代の全域ラン（`data/output/satellite_only_cellbased/20230707_032305_area_comparison/` の `dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m_results.json`・[survey_area_comparison_results.md](survey_area_comparison_results.md)）を使う。**4章の数値（`20230707_032305/`）は旧世代の指標（ROI でクリップする前）によるため使わない**（3.1節。[observation_selection.md](../02_methods/observation_selection.md) 9.1節の「新世代のランに限る」による）。

**比較相手の妥当性**:

- 比較相手は `mask_survey` を追加で結合したデータセットによるが、本章は結合しないデータセットによる。Limited では、同じ結合をした全域ランと結合しないラン13 の結果が完全に一致した（Limited 側 8.5節）。全域（`--analysis-area roi`）では `mask_survey` の結合は結果を変えないため、新世代の全域ランとして比べてよい
- 比較相手は陳腐化チェックで「要再実行（コード変更）」と判定される。生成はクリーンなコミットで行われており、生成後に変わったのは結果ファイルの保存と来歴の記録を担う `src/common/summary.py` だけである。数値の計算には関わらないため、比較相手として使う

**比べる量と比べない量**: LST の絶対値と RMSE・MAE（°C）は比べない（[observation_selection.md](../02_methods/observation_selection.md) 8.5節）。R²、RMSE を各観測の LST の標準偏差で割った値、変数重要度の順位を比べる。

| 指標 | 032358（本章） | 032305（全域ラン） | 差 |
|---|---|---|---|
| フィルタ後母数（ROI比） | 3,491,872（93.5%） | 3,317,260（88.8%） | +174,612 |
| RF R²（Spatial CV） | 0.7475 | 0.6302 | **+0.1173** |
| Linear R²（Spatial CV） | 0.6855 | 0.4821 | **+0.2034** |
| RF R²（ランダム分割） | 0.7543 | 0.6404 | +0.1139 |
| Linear R²（ランダム分割） | 0.6883 | 0.4920 | +0.1963 |
| RF の RMSE ÷ LST の標準偏差（Spatial CV） | 0.501 | 0.602 | −0.101 |
| Linear の RMSE ÷ LST の標準偏差（Spatial CV） | 0.560 | 0.714 | −0.154 |
| SHAP の順位 | `NDBI` 1.394・`NDWI` 0.346・`NDVI` 0.298 | `NDBI` 1.021・`NDVI` 0.490・`NDWI` 0.438 | 第2・3位が入れ替わり |
| Permutation の順位 | `NDBI`・`NDWI`・`NDVI` | 同じ順位 | 順位は不変 |

差の読み方は Limited 側 8.5節と同じ物差し（R² の標本変動 0.003程度・SHAP の変動 0.1程度。母集団が異なるため下限として扱う）による。

- **R² の差（+0.11〜+0.20）は標本変動をはるかに超える。** 上がり幅は Limited（+0.06〜+0.12）より大きく、とくに線形モデルで大きい
- **NDBI の首位は、どの指標でも、どちらの観測でも変わらない。** 1つの指標の選び方や観測の選び方に依存しない
- **第2・3位（`NDVI` と `NDWI`）の順位は読まない。** SHAP では入れ替わったが、両者の差は 032358 で 0.048、032305 で 0.052 と、SHAP の変動幅（0.1程度）より小さい。Permutation・RF Importance ではどちらの観測でも `NDWI` が第2位である。両者は VIF が危険水準を超える共線な組でもある（7.4節）

**R² が上がった理由は切り分けていない。** Limited 側 8.5節と同じく、母集団の違い（最終母数 +174,612セル・脱落が集中していたブロックの解消）と観測条件の違い（都心と郊外の LST 差が大きい観測）が重なっている。**「主採用の観測では R² が高い」ことを手法の性能の向上として読まない。** Satellite Only は説明変数が分光指数のみで、`NDVI` と LST の間接的な代数的依存（6章「LSTプロダクトの算出仕様の確認」）の影響を最も強く受けるシナリオであることにも留意する。
