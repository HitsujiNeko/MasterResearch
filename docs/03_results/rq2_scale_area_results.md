# グリッド解像度と分析対象範囲による説明力・寄与順位の変化（RQ2・Satellite Only・Limited）

**最終更新**: 2026-11-10  
**関連ドキュメント**: [analysis_workflow.md](../02_methods/analysis_workflow.md) 5.2節・6.1.1節, [survey_area_comparison_results.md](survey_area_comparison_results.md) 3章・7章, [spatial_cv_design_results.md](spatial_cv_design_results.md) 5章, [calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節, [calc_urban_params_io_spec.md](../02_methods/calc_urban_params/calc_urban_params_io_spec.md) 6.6節, [research_guide.md](../01_planning/research_guide.md)  
**前提知識**: Satellite Only・Limited の処理条件（両結果ドキュメントの3節）、Spatial CV のブロック定義と判定基準（survey_area_comparison_results.md 3.5節）、分析対象範囲の指定（analysis_workflow.md 実装スケジュール表下の注記）  
**対象RQ**: RQ2（空間集計単位・分析対象範囲による関係の変化）

---

> **本版は実行前の記録である。** 1〜4章（位置づけ・実行前に固定した判定規則・ラン一覧・データの準備）だけを書き、結果の章は実行後に追記する。判定規則を結果を見る前に固定したことを、この版の履歴で示すためである。

## 1. 位置づけ

RQ2 は、都市構造パラメータと LST の関係（説明力と変数の寄与順位）が、空間集計単位（グリッド解像度）と分析対象範囲（全域／都心部）によってどう変わるかを問う（[analysis_workflow.md](../02_methods/analysis_workflow.md) 5.2節）。本ドキュメントは、主採用の観測 `2022-09-06T03:23:58Z`（032358）で、Satellite Only と Limited の採用構成を 30m・90m・300m × 全域（`roi`）・都心部（`survey`。測量GIS範囲）の組合せで実行した結果を記録する。

- **Limited の構成**: 採用構成（`--variable-set both --building-height mean --population-source worldpop2020 --water-index none`）に限る
- **Full は対象外**である。全域では成立しないため（analysis_workflow.md 5.2節）
- **分析コードは変えていない。** 既存の分析スクリプトの `--scale`・`--analysis-area`・`--block-size-m`・`--sample-size`・`--random-state` で条件を変えた
- **30m・2,700m・シード42 のランは、範囲の比較（[survey_area_comparison_results.md](survey_area_comparison_results.md) 7章）の通常ランを使う。** 全域と都心部が同じデータセット（`mask_survey` を結合したもの）から作られているためである

**有効カバレッジを ROI と同一視しない。** 「全域」は ROI そのものではなく、`IN_ANALYSIS_AREA == 1` とシナリオごとの有効域品質列で絞った範囲である。「都心部」はさらに `IN_ANALYSIS_AREA_SURVEY == 1` で絞った範囲で、30m で約100 km² である。

## 2. 実行前に固定した判定規則

次の規則は、90m・300m のランを実行する前に決めた（2026-11-10）。

| 項目 | 規則 |
|---|---|
| 区画長 | 2,700m に固定する（物理的な長さ。解像度で変えない。[analysis_workflow.md](../02_methods/analysis_workflow.md) 6.1.1節） |
| ブロック判定 | (a) 非空ブロック数が 10 以上、(b) fold のテストセル数の最大/最小が 1.5 以下（[survey_area_comparison_results.md](survey_area_comparison_results.md) 3.5節と同じ基準）。満たさない組合せは評価対象から外し、理由を記録する |
| サンプル数 | 既定の10万件を上限とする（フィルタ後の母数が10万件以下なら全件）。抽出率を記録する |
| 境界の部分被覆セル | 都心部の 90m・300m でも、30m と同じく除外せずそのまま使う（下記） |
| 都心部 × 300m | ブロック判定を満たしても**参考値**として扱い、全域との比較の主な結論には使わない（下記） |
| 解像度をまたぐ比較 | 主指標は「Spatial CV の RF の RMSE ÷ フィルタ後の母数の LST 標準偏差」と SHAP の順位とする。R² は従とする。°C の RMSE は、同じ解像度内の範囲比較にだけ使う |

**境界の部分被覆セルをそのまま使う理由**: `IN_ANALYSIS_AREA_SURVEY = 1` は「セル内の fine ピクセル中心が1つでも有効域に入る」ことを意味するため、境界にかかるセルを含む。面積換算の超過は 30m で約0.4%、90m で約1.8%、300m で約8% である（[calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節）。Satellite Only・Limited の入力（衛星・公開GIS）は測量GIS範囲の外にも有効な値があり、境界セルの値に欠けが無い。このため境界セルは「都心部の外側を少し含むセル」であって「値の一部が欠けたセル」ではない。面積の超過は限界として記録し、測量GISを使う Full では改めて検討する。

**都心部 × 300m を参考値とする理由**: 都心部の 300m は約1,200 セル（33 × 33 セル程度）しかなく、2,700m の区画には1つあたり 9 × 9 = 81 セルしか入らない。ブロック判定を満たしても、fold の組み方で結果が大きく動くと見込まれるため、評価対象から外さずに記録だけ残し、シードを変えた反復（3章の群 D）で順位の揺れを確かめる。

**解像度をまたぐ比較で °C の RMSE を使わない理由**: 解像度を粗くすると、セル内で LST が平均されて分散が小さくなる。同じモデルの当てはまりでも、°C の誤差は小さく出る。LST の標準偏差で割った誤差と、変数の寄与の順位で比べる。

## 3. ラン一覧

| 群 | 内容 | ラン数 | 出力先（各シナリオの出力ディレクトリの下） |
|---|---|---:|---|
| A 本体 | 2シナリオ × 90m・300m × 全域・都心部。2,700m・シード42 | 8 | `20220906_032358_rq2_scale/` |
| A' 30m の基準 | 範囲の比較の通常ラン（30m × 全域・都心部 × 2シナリオ） | 4（再利用） | `20220906_032358_area_comparison/` |
| B 13,500m の併記 | 2シナリオ × 30m・90m・300m × 全域。13,500m・シード42 | 6 | `20220906_032358_rq2_scale_block13500/` |
| C 標本数の感度 | 2シナリオ × 30m × 全域。サンプル数を全域 300m のフィルタ後の母数に揃える | 2 | `20220906_032358_rq2_scale_n{サンプル数}/` |
| D 順位の安定性 | 2シナリオ × 30m・90m・300m × 都心部。シード 43〜51（シード42 は A・A' を使う） | 54 | `20220906_032358_rq2_scale_seeds/seed{シード}/` |

各シナリオの出力ディレクトリは `data/output/satellite_only_cellbased/`（Satellite Only）・`data/output/limited/`（Limited）である。

- **出力名に区画長・サンプル数・シードが入らないため、群ごとに出力先を分けて上書きを防ぐ。** 解像度と範囲は出力名に入る（`_hanoi_{解像度}m`・範囲が `survey` のとき末尾に `_area_survey`）
- **13,500m は全域だけで併記する。** 論文の性能値には 13,500m の値を併記する方針である（analysis_workflow.md 6.1.1節）。都心部は約100 km² しかなく、13,500m（1ブロック約182 km²）では非空ブロックが数個にとどまり、ブロック判定 (a)（10 以上）を満たさないため実行しない
- **C は「30m 全域の結果は標本数で決まっているのではないか」を確かめる。** 全域 300m の母数は 38,200 セル以下（`IN_ANALYSIS_AREA = 1` のセル数。4.2節）で、10万件の上限に届かない。サンプル数は全域 300m のランのフィルタ後の母数（シナリオごと）に揃えるため、群 A の実行後に決まる。30m 全域を同じ件数に減らして回し、30m と 300m の差のうち標本数の違いで説明できる分を見る
- **D は SHAP の順位の揺れを測る。** シードを変えると、ランダム分割の学習/テスト・RF の乱数・SHAP の評価標本が変わる。都心部の 90m・300m は全件を使うため標本は変わらず、モデル側の揺れだけを測ることになる（30m は10万件の抽出も変わる）。fold ごとの SHAP は分析スクリプトの変更が要るため採らない
- **共通評価セル（[analysis_workflow.md](../02_methods/analysis_workflow.md) 5.3.3節）は使わない。** RQ2 はシナリオ内での解像度・範囲の比較であり、シナリオ間で標本をそろえる必要が無いためである

各ランの結果は `src/analysis/summarize_rq2_scale_area.py` で1つの表に集計し、`data/output/rq2_scale_area/20220906_032358/` に保存する。本ドキュメントの数値はこの集計結果を正本とする。

## 4. データの準備

### 4.1 テーブルの来歴

90m・300m のデータセットは、`data/output/params/hanoi/{90m,300m}/` の既存のテーブルと、主採用の観測で新たに生成した衛星指標・LST のテーブルから作った。30m の主結果と同じ処理で作られたテーブルかを、生成日時（ファイルの更新日時）と生成コードで確かめた。

| テーブル | 30m | 90m | 300m | 判定 |
|---|---|---|---|---|
| `build_gba` | 08-27 15:49 | 08-27 15:59 | 08-27 16:09 | 同じ実行（解像度を続けて出力） |
| `road_osm` | 08-12 12:46 | 08-12 13:38 | 08-12 13:31 | 現行コードの再生成と全セル一致（下記） |
| `elev_fabdem` | 08-12 12:46 | 08-12 13:38 | **08-15 00:06** | 現行コードの再生成と全セル一致（下記） |
| `mask_roi` | 08-12 12:47 | 08-12 13:38 | **08-15 00:06** | 現行コードの再生成と全セル一致（下記） |
| `lulc_glc2022` | 08-22 21:28 | 08-22 21:28 | 08-22 21:28 | 同じ実行 |
| `ntl_viirs2023` | 08-20 11:47 | 08-20 11:47 | 08-20 11:47 | 同じ実行 |
| `pop_worldpop2020`・`pop_landscan2020`・`pop_landscan2023` | 08-20 11:46〜11:47 | 08-20 11:47 | 08-20 11:47 | 同じ実行 |
| `mask_survey` | 10-19 21:01 | 10-19 21:01 | 10-19 21:01 | 同じ実行 |
| `idx_20220906_032358`・`lst_20220906_032358` | 10-22 17:36 | **11-10 21:49（新規）** | **11-10 21:49（新規）** | 30m の生成以降、生成コードに値を変える変更なし（下記） |

日付はいずれも2026年である。人口の LandScan 2版はモデルに投入しないが、Limited のデータセットには結合される。

- **生成日時が解像度で食い違う3テーブルは、現行コードで作り直して突き合わせた。** `road_osm`・`elev_fabdem`・`mask_roi` を 30m・90m・300m で作業用の出力先に再生成し、既存のテーブルと `cell_id` ごとに比べた。9件（3テーブル × 3解像度）とも行と `cell_id` の集合が一致し、全列で値の不一致は0セル（欠損の位置も一致）だった。300m の `elev_fabdem`・`mask_roi` は 30m より後に作られているが、値は 30m と同じコードによるものと同じである。既存のテーブルを上書きせず、そのまま使った
- **同じ実行の6テーブルは突き合わせていない。** 解像度を続けて出力した1回の実行（数分以内）で作られており、解像度間で生成コードが同じであるためである。これらのテーブルが現行コードで作り直しても同じになるかは確かめていない（**未確認**）。ただし 30m の主結果も同じテーブルを使っており、解像度の比較の前提（解像度間で同じ処理）には影響しない
- **衛星指標・LST は主採用の観測で 90m・300m を新たに生成した。** 30m の生成（10-22）以降に生成コード（`src/analysis/urban_params/`）の変更は無く、そこから使う共通モジュールの変更は Spatial CV の緩衝帯の関数の追加だけである（既存の関数は変わっていない）。LST は各セル内の有効画素の平均（°C）として集計される（`src/analysis/urban_params/params/lst.py`）

生成コマンド:

```bash
python -m src.analysis.urban_params --city hanoi --lst-file data/satellite/lst/2022/LST_Landsat8_20220906_032358Z.tif --satellite-file data/satellite/indices/2022/INDICES_Landsat8_20220906_032358Z.tif --scales 90 300
```

### 4.2 データセットの生成

30m と同じ形（衛星指標・LST・`mask_survey` を結合）で、90m・300m のデータセットを4本生成した（既存のデータセットは上書きしていない）。

```bash
python -m src.analysis.build_dataset --city hanoi --scale {90,300} --scenario limited --tables idx_20220906_032358 lst_20220906_032358 mask_survey --name limited_masksurvey_20220906_032358
python -m src.analysis.build_dataset --city hanoi --scale {90,300} --scenario satellite_only --tables idx_20220906_032358 lst_20220906_032358 mask_survey --name satellite_only_masksurvey_20220906_032358
```

| データセット | 行数 | `IN_ANALYSIS_AREA = 1` | `IN_ANALYSIS_AREA_SURVEY = 1` |
|---|---:|---:|---:|
| `dataset_{limited,satellite_only}_masksurvey_20220906_032358_hanoi_90m.gpkg` | 417,694 | 417,336 | 12,549 |
| `dataset_{limited,satellite_only}_masksurvey_20220906_032358_hanoi_300m.gpkg` | 38,235 | 38,200 | 1,200 |

- 行数と `IN_ANALYSIS_AREA_SURVEY = 1` のセル数は、正準グリッドの検証の記録（[calc_urban_params_cli_verification.md](../02_methods/calc_urban_params/calc_urban_params_cli_verification.md) 11.8節）と一致した。都心部のセルはすべて `IN_ANALYSIS_AREA = 1` の内側にある
- 結合時の突合では、全テーブルが正準グリッドの全行と一致し、件数の警告は出なかった
- データセットは Git 管理外である。各ランの結果 JSON の来歴（`provenance.inputs`）に SHA-256 が残る
