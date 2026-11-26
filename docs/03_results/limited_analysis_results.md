# 衛星＋公開GISデータのシナリオ 分析結果

**最終更新**: 2026-11-26  
**関連ドキュメント**: [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md), [satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md), [survey_area_comparison_results.md](survey_area_comparison_results.md), [spatial_cv_design_results.md](spatial_cv_design_results.md), [observation_selection.md](../02_methods/observation_selection.md), [lst_emissivity_sensitivity_results.md](lst_emissivity_sensitivity_results.md), [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md), [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md), [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md), [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

> 本ドキュメントは索引を兼ねたハブである。2〜8章は [limited_analysis/](limited_analysis/) 配下の4ファイルへ分割済みで、章・節番号は分割前のまま変えていない。各節がどのファイルにあるかは下記の索引を参照。1章および子ファイルの「本ドキュメント」は、分割前の文書全体（本ファイルと子ファイル4件）を指す。主結果（主採用の観測 2022-09-06）は8章（[limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md)）にある。

---

## 索引

章・節単位で「どの節がどのファイルにあるか」を示す。1行要約とあわせて、必要な節と収録ファイルを本表だけで特定できる。番号の付いていない小見出し（3.8節の「母数のファネル」など）は、親の節と同じファイルにある。

| 章・節 | 1行要約 | 収録ファイル |
|---|---|---|
| 1. 位置づけ | RQ3 における本シナリオの位置づけ。主結果は8章、2〜7章は旧採用の観測の記録。アーカイブ・シーン選定の正本 | 本ファイル |
| 1.1 数値の正本 | フル表は貼らず CSV/JSON を数値の正本とすること、出力ディレクトリの置き場所 | 本ファイル |
| 1.2 現行の定義（建物高さ・人口・夜間光） | 建物高さの帰属方式と、人口・夜間光の nodata 方針（アーカイブの旧記録との差） | 本ファイル |
| 1.3 結果の一般化可能性の限界 | 単一 ROI・30m・単一観測の結果であることと、検証されていない点 | 本ファイル |
| 1.4 データセットの世代（衛星指標の再生成） | 衛星指標の再生成で生じた新旧2世代のデータセットと、世代をまたぐ比較の注意 | 本ファイル |
| 2. 分析ラン一覧（台帳） | 旧採用の観測 032305 のラン1〜15の台帳（1ラン=1行）と変数セットの記法 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 2.1 台帳の読み方（比較してよい組み合わせ） | 母数・標本が揃い数値を直接比べてよいランの組み合わせと、標本変動の実測 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 3. ラン間で共通の処理条件 | 全ランに共通する処理条件（ランごとに変えた項目は2章の台帳） | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.1 ROI・スケール・格子・観測 | ROI・30m・正準グリッド・観測 032305 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.2 建物高さ列の補完 | 建物の無いセルの高さの0補完の判定条件と、`--building-height` の構成 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.3 品質管理（フィルタ条件） | 有効域マスク・非NULL要求のフィルタ条件と、`--water-index` の構成 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.4 サンプリング | 適用順序・標本数10万・乱数シード | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.5 モデル設定 | 学習/テスト分割・MLR の標準化・RF のハイパーパラメータ・Spatial CV | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.6 分散0の特徴量列の除外 | 標本内で分散0になる列を VIF 算出・学習の前に除く理由 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.7 出力ファイル | 出力ディレクトリと出力接頭辞の組み立て規則 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.8 フィルタ脱落と欠損値処理の診断 | 母数のファネル・要因別内訳・0補完の実測・空間的な集中・水域被覆の偏り・事前の多重共線性診断 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.9 分析実行前のモデル前提の精査 | Spatial CV のブロックサイズと R² の関係、建物高さ0補完の構造的従属、目的変数と説明変数の結合、変数分布 | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 3.10 衛星指標の再生成（MNDWI の追加） | MNDWI 追加のための衛星指標の再エクスポート、旧 tif がクリップ前だった判断、新旧の突き合わせ | [limited_analysis_processing.md](limited_analysis/limited_analysis_processing.md) |
| 4. モデル性能 | 旧採用の観測でのランごとのモデル性能 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 4.1 ランダム分割 | ランごとのランダム分割の R²・RMSE・MAE | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 4.2 Spatial CV | ランダム分割から Spatial CV への低下幅と、ランによる違い | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 4.3 変数セット別の比較 | 同一セル上での変数セット（spectral／coverage／both）の比較 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5. 変数重要度 | ラン間の比較に必要な変数重要度の要約 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.1 ラン1（主結果）の上位変数 | ラン1の指標ごとの上位6変数（指標によって首位が入れ替わる） | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.2 ラン1とラン2（gismask）の差分 | GIS 有効域マスク（gismask）の有無による SHAP の差 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.3 分光ブロックと被覆率ブロックの寄与（SHAP合計） | ブロック単位の SHAP 合計による分光ブロックと被覆率ブロックの比較 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.4 S10 の報告（被覆率型が分光指数と同等以上）の再現性 | 先行研究 S10 の報告（被覆率型が分光指数と同等以上）の部分的な再現 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.5 土地被覆ソースの差し替え（GLC / Esri） | 土地被覆ソース（GLC / Esri）の差し替えによる被覆率型の評価 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.5.1 二値化の度合いの実測（想定と逆の結果） | セル内の被覆率が0/1へ二値化する度合いの実測 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.6 人口密度データソースの差し替え | 人口密度データソース（WorldPop2020・LandScan2020・LandScan2023）の差し替え | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 5.7 符号の解釈 | ラン1の標準化係数の符号の読み方 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 6. 多重共線性と解釈上の注意 | VIF・共線構造と、建物高さ・水指数の構成比較による採用構成の根拠 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.1 VIF 一覧（危険水準を超えた変数のみ） | ランごとの VIF > 10 の変数 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.2 計画段階で想定した共線構造との突き合わせ | 計画段階で想定した4つの共線構造と相関行列の実測の突き合わせ | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.3 人口3版どうしの相関（30m正準グリッド上） | 人口3版どうしの相関と、同時投入しない判断 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4 建物高さ列の多重共線性（解消済み） | 建物高さ構成（both/mean/max/pc1）の比較と `mean` の採用 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.1 問題の所在 | 建物高さ2列を投入したときの VIF の高さと原因 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.2 4構成の比較（ラン1・5・6・7） | 同一セル上での建物高さ4構成の比較 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.3 最も重要な所見: `both` の標準化係数は共線性のアーティファクトだった | `both` の標準化係数が共線性のアーティファクトだったこと | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.4 採用構成: `mean`（セル内の平均建物高さ） | `mean` を採用した判断軸 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.5 標準化係数を主たる解釈に用いてよいかの判断 | 標準化係数を主たる解釈に用いてよいかの判断 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.4.6 検討対象外とした案 | 検討対象外とした案と却下の根拠 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5 分光指数間の共線性（水指数ブロックの構成比較） | 水指数構成（ndwi/none/pc1/mndwi）の比較と `none` の採用 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.1 問題の所在 | `NDVI`・`NDWI` の VIF の高さと構造的な相関 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.2 4構成の比較（ラン12〜15） | 同一セル上での水指数4構成（ラン12〜15）の比較 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.3 最も重要な所見: `ndwi` の分光指数の標準化係数は共線性のアーティファクトだった | `ndwi` の分光指数の標準化係数が共線性のアーティファクトだったこと | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.4 MNDWI で共線性が解消しなかった理由 | 正規化差の恒等式による、MNDWI で共線性が解消しなかった理由 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.5 事前に決めた採用基準との照合 | 構成比較の前に固定した採用基準との照合 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.6 採用構成: `none`（事前の手順から外れた判断とその根拠） | 事前の手順から外れて `none` を採用した判断とその根拠 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.7 先行研究との位置づけ | 文献調査による先行研究との位置づけ | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.5.8 検討対象外とした案 | 検討対象外とした案（ANDWI 等） | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.6 VALID_GIS_MASK を主結果に課さなかった判断の妥当性 | VALID_GIS_MASK を主結果に課さなかった判断の妥当性 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 6.7 衛星データのみとの参考比較 | 同一観測（032305）・同一格子での衛星データのみとの参考比較 | [limited_analysis_multicollinearity.md](limited_analysis/limited_analysis_multicollinearity.md) |
| 7. 今後の研究の方向性 | シナリオ間比較の標本統制など、残る課題と今後の方向性 | [limited_analysis_legacy_20230707.md](limited_analysis/limited_analysis_legacy_20230707.md) |
| 8. 主採用の観測（2022-09-06）の結果 | 主採用の観測 032358 で採用構成を実行した、本シナリオの主結果 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.1 実行内容と数値の正本 | 出力先・データセット・構成と数値の正本 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.2 母数とフィルタ脱落 | 032358 と 032305（ラン13）の母数とフィルタ脱落の比較 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.3 モデル性能 | ランダム分割・Spatial CV のモデル性能 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.4 変数重要度 | 指標ごとの変数重要度の順位 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.5 旧採用（ラン13）との比較 | 同じ採用構成を雨季の2観測で比べた相対量の比較 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6 衛星データのみとの比較（共通評価セル） | 共通評価セルでの衛星データのみとの比較 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.1 評価の設計と数値の正本 | 共通集合・評価セル・fold の設計と数値の正本 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.2 共通集合の母数と脱落セルの性格 | 共通集合の母数と、共通集合から外れたセルの性格 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.3 単発の比較（シード42） | シード42での fold ごとの対応のある差と補正 t 区間 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.4 20シードの反復 | シード 42〜61 の20シードの反復 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.5 読み方と限界 | 比較結果の読み方と限界 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.6.6 分光指数を揃えた感度分析 | 分光指数を揃えた感度分析（`NDWI` を含む構成との比較） | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7 水域率の元データを JRC に差し替えた感度分析 | `LULC_WATER_COV` を JRC Global Surface Water 由来に差し替えた感度分析 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7.1 方法と数値の正本 | 差し替えた候補・構成データと人口補完の扱い・評価の設計と数値の正本 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7.2 差し替えた水域率と構成データの扱い | 候補ごとの水域の量、据え置き版の二重計上、正規化版の副作用、人口補完の食い違い | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7.3 共通セルと評価セル | JRC 月次の欠測による共通セルと、共通セルから外れたセルの性格 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7.4 結果 | GLC 版との性能の差、水域の係数と寄与、変数の順位 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |
| 8.7.5 読み方と限界 | 感度分析の結果の読み方と限界 | [limited_analysis_main_20220906.md](limited_analysis/limited_analysis_main_20220906.md) |

---

## 1. 位置づけ

RQ3 では衛星データのみと衛星＋公開GISデータの2シナリオを主軸として比較し、測量建物置き換えは付録で扱う（余裕があれば実施）。衛星データのみは cell_id結合の新経路で既に成立済み（[satellite_only_analysis_results_cellbased.md](satellite_only_analysis_results_cellbased.md)）であり、本ドキュメントは公開GISと衛星指標を組み合わせた **衛星＋公開GISデータ** シナリオの評価結果を記録する。付録の測量建物置き換え（建物の変数を測量GIS由来に置き換える）は本ドキュメントの対象外（未着手）。

**主結果は、主採用の観測 `2022-09-06T03:23:58Z`（以下 032358）による8章である。** 2〜7章の全ラン（台帳のラン1〜15）は旧採用の観測 `2023-07-07T03:23:05Z`（以下 032305）に基づき、比較用の観測の結果として残す。2〜7章の数値と8章の数値は観測が異なるため、LST の絶対値・RMSE（°C）を直接比べず、相対的な量だけを比べる（8.5節）。**8章と比べてよいのは 032305 の新世代のラン（ラン12〜15、採用構成はラン13）に限る。** 旧世代のラン1〜11 は衛星指標の作り方が異なるため（1.4節）、相対的な量であっても8章とは比べない。**2〜7章の「主結果」（ラン1）という表記は、032305 の記録の中での基準ランを指す**（記録時の呼び方のまま残している）。現在の主結果は8章である。

観測 `2023-07-07T03:23:29Z`（032329）に基づく旧ラン1〜13 の記録は [limited_analysis_results_20230707_032329.md](../04_archive/limited_analysis_results_20230707_032329.md) へ移した。**旧記録とはカバレッジ・建物高さの帰属方式・人口/夜間光の nodata 方針が食い違うため、数値を直接比較してはならない**（アーカイブ側 0.1節）。ラン番号も振り直しているため、番号だけで旧記録を参照しないこと（対応表はアーカイブ側 0.2節）。

**シーン選定の根拠**（主採用を 032358 に変えた理由は8章、032305 を採用した当時の理由・2シーン合成を採らなかった判断は5章・4章）は [observation_selection.md](../02_methods/observation_selection.md) を正本とする。

### 1.1 数値の正本

**変数重要度・VIF・相関行列のフル表は本ドキュメントに貼らない。** 変数が増えるとフル表が読めなくなるため、次のファイルを数値の正本とし、本文には比較に必要な要約（上位変数・危険水準を超えたVIF・ラン間の差分）のみを載せる。

| 種別 | ファイル |
|---|---|
| 標準化係数・RF重要度・Permutation重要度・VIF | `{接頭辞}_feature_importance.csv` |
| SHAP 平均絶対値 | `{接頭辞}_shap_importance.csv` |
| 全結果の要約（母数・除外列・診断範囲を含む） | `{接頭辞}_results.json` |
| fold別評価値 | `{接頭辞}_spatial_cv_folds.csv` |

いずれも `data/output/limited/20230707_032305/` に置き、Git管理下にある（サンプルCSV `*_sample_*.csv` のみ管理外）。**8章（主採用の観測）の出力は `data/output/limited/20220906_032358/` に置く。** 8.6節（衛星データのみとの比較）の出力は、共通評価セルと比較・反復の結果を `data/output/common_evaluation/20220906_032358/` に、共通評価セルでの衛星＋公開GISデータの全工程ランを `data/output/limited/20220906_032358_common_evaluation/` に置く。8.7節（水域率の感度分析）の出力は、派生データセットの要約と GLC 版との比較を `data/output/limited/20220906_032358_water_sensitivity/` に、評価セルを `data/output/common_evaluation/20220906_032358_water_sensitivity/` に、7版の全工程ランを `data/output/limited/20220906_032358_water/` に置く。また、**ラン12〜15（水指数ブロックの構成比較）だけは `data/output/limited/20230707_032305_water_index/` に置く。** データセットの世代が異なり（1.4節）、同じ出力接頭辞のラン1の出力を上書きしないためである。

**測量GIS範囲と全域の比較（ラン12・13 の構成を `mask_survey` 結合データセットで回し直したもの）は `data/output/limited/20230707_032305_area_comparison/` に置く。** 本ドキュメントの台帳には含めず、結果と解釈は [survey_area_comparison_results.md](survey_area_comparison_results.md) を正本とする。同ディレクトリの全域ランは、ラン12・13 の母数・サンプル・Spatial CV の R² を再現している（同ドキュメント3.3節）。

### 1.2 現行の定義（建物高さ・人口・夜間光）

本ドキュメントの全ランは、次の定義で生成したデータセットに基づく。**旧記録との差はここに集約される。**

- **建物高さの帰属方式**: 重なりベースと重心の併用。旧方式（重心単独）では大規模建物の張り出しセルが `BUILD_H_MEAN` / `BUILD_H_MAX` の NULL になり非NULL要求フィルタで系統的に脱落していたが、現行方式では建物高さ由来の脱落が **21セル**にとどまる（3.8節）。ただし `BUILD_H_MEAN` は**混成推定量**（大半のセルは上端高さの面積平均、重なり方式の被覆が無いセルは重心方式の単純平均）であり、fine セル中心を覆わない小さい建物は重み0で落ちるため、この測定誤差はハノイの都市形態（大フットプリント＝低層、小フットプリント＝中高層）に沿って**密集低層地区で下方へ偏る**。詳細は [gis_data_buildings.md](../01_planning/gis_data/gis_data_buildings.md) 3.2節を参照する
- **人口・夜間光の nodata 対処**: 原因ごとに扱いを分ける。**境界帯型**（ROIクリップ×粗い画素。LandScan約920m・VIIRS約460m）は有効域を明示的な品質列（`VALID_POP_<ソース>_MASK` / `VALID_NTL_MASK`）として除外し、補完しない。**WorldPopマスク型のうち水域優位**（`LULC_WATER_COV >= 0.9`）のセルは0で補完し、`POP_FILLED_<ソース>` フラグ列で「補完した実測0」と区別する。**水域と断定できない陸地**（92m画素の無効値マスクが陸地部分まで巻き込んだセル等）は補完せず除外を維持する。原因別の実測は [gis_data_population.md](../01_planning/gis_data/gis_data_population.md) 6.4節・[gis_data_nighttime_lights.md](../01_planning/gis_data/gis_data_nighttime_lights.md) 5.1節、集計方法は `src.analysis.diagnose_nodata_dropout` を正本とする

境界帯型を陸地であるにもかかわらず0補完しない・水域優位以外の WorldPop 欠測セルを補完しないのは、いずれも根拠の無い外挿・誤った0埋めを避けるためである（920m画素の値をROI外向きに延ばす根拠は薄く、水域と判定できない陸地に人口0を与えるのは誤りになる）。この方針の実データ上の帰結は3.8節に記録する。

### 1.3 結果の一般化可能性の限界

本ドキュメントの各ランは **ハノイROI・30m・単一観測**（8章は 032358、2〜7章は 032305）の結果である。雨季の2観測で同じ構成を回した比較は8.5節にあるが、次の点は**検証されていない**。

- **季節・時刻**: 乾季の観測、他の時刻の観測での再現性。植生指数と土地被覆の関係は季節依存が大きいと予想されるが、本研究では未確認（8.5節の比較は雨季どうしに限られる）
- **他都市**: ベトナム他都市および他国の都市での再現性
- **他スケール**: 90m・300mでの再現性。特に土地被覆の面積率は30mで二値化しており（5.5.1節）、粗いスケールでは性質が変わる
- **空間カバレッジ**: 母集団はLST有効セル（ROI内 3,736,107セルのうち、032305 で 89.3%、032358 で 93.5%）に依存する。032305 では南部の一部（観測フットプリント端）と北東部の雲域を除いてROIをほぼ覆うが（3.8節の目視確認）、**カバレッジが変われば母集団の性格も変わる**（2観測の母数の違いは8.2節。032358 の欠測域の目視確認は未実施）
- **母集団の性格**: 都心に加えて農村部と山地を広く含む。土地被覆は農地が支配的であり（`LULC_CROP_COV` の平均 0.6554・5.5.1節）、都市域のみを対象とした研究の知見がそのまま当てはまるとは限らない

「分光指数が被覆率型を上回る」（4.3節。**RF に限定した観察であり、線形モデルでは向きが逆になる**）を含む本ドキュメントの結論は、**上記の条件下での観察**であり、条件を変えた場合の一般性を主張するものではない。

### 1.4 データセットの世代（衛星指標の再生成）

本ドキュメントのランは、衛星指標の作り方が異なる**2世代のデータセット**に分かれる。水指数 MNDWI を追加するために同じ観測（032305）の衛星指標を GEE から再エクスポートした際、旧 tif が ROI ポリゴンでのクリップ導入前の出力だったことが判明し、現行の仕様（クリップあり）で作り直したためである（経緯と検証は3.10節）。

| 世代 | 対象ラン | 衛星指標 tif | 分光指数の列 | フィルタ後母数 |
|---|---|---|---|---|
| 旧 | 1〜11 | ROI ポリゴンでクリップする前の出力（ROI の外接矩形全体に値を持つ） | NDVI・NDBI・NDWI | 3,274,665 |
| 新 | 12〜15 | 同じ観測を現行コードで再エクスポートした出力（ROI でクリップ済み） | NDVI・NDBI・NDWI・MNDWI | 3,274,657 |

- **差は ROI の境界にかかるセルに限られる。** 既存3指標の値が変わったのは 7,950セル（うち30セルは欠測に変わった）で、それ以外の列はすべて一致する（3.10節）
- **世代をまたいだ比較は標本統制されない**（ラン1とラン12の標本の重なりは 13.46%・2.1節）。数値を直接比較しない
- **ラン1は旧世代の主結果として、ラン2〜11 の比較の基準のまま残す。** 水指数の構成を含む現行の採用構成は**ラン13**（`--water-index none`・6.5節）である。他の比較軸を新世代・採用構成で測り直すことは7節の課題とする
- **ラン1〜11 は現行のスクリプトでは再実行できない。** 非NULLを要求するフィルタ列が MNDWI を含むようになり（3.3節）、MNDWI 列の無い旧世代のデータセットはどの構成でも拒否されるためである。旧世代の Esri 版データセット（ラン10・11）も再生成していない
