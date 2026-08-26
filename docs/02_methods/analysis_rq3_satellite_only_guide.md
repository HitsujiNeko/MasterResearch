# analysis_rq3_satellite_only.py 解説書（統計初心者向け）

**最終更新**: 2026-08-26  
**関連ドキュメント**: [analysis_workflow.md](analysis_workflow.md), [CodingRule.md](CodingRule.md), [satellite_only_analysis_results_cellbased.md](../03_results/satellite_only_analysis_results_cellbased.md), [limited_analysis_results.md](../03_results/limited_analysis_results.md), [calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) 6.7節  
**前提知識**: RQ3の目的（「衛星データだけでLSTをどこまで説明できるか」）

---

## 1. このコードの目的

このスクリプトは、`src/analysis/analysis_rq3_satellite_only.py` で次を行います。

- 衛星指標（NDVI, NDBI, NDWI）だけでLSTを予測
- 2つの評価方法でモデル性能を比較
- 各指標がどれだけ効いているかを可視化

評価方法は次の2種類です。

1. **ランダム分割**: データをランダムに学習用とテスト用に分ける
2. **Spatial CV（空間交差検証）**: 地理的に離れたブロックで学習・評価を分ける

ポイントは、ランダム分割よりSpatial CVのほうが厳しめに性能を評価できることです。

**このスクリプトは「薄いエントリ」です。** 実際の処理（フィルタ・サンプリング・モデル学習・SHAP・プロット）は `src/common/` 配下の共通モジュールに委譲しており、`analysis_rq3_satellite_only.py` 自体はデータセットパス・特徴量列・出力先の組み立てとCLI引数の解釈のみを担います。Limited / Full シナリオでも同じ共通モジュールを再利用する前提です。

---

## 2. 入力データと列

入力は `src.analysis.build_dataset` が生成した `cell_id` 結合のGeoPackageです（旧実装のピクセル単位CSVではありません）。このコードで使う主な列は次のとおりです。

- `cell_id`: 正準グリッドのセルID（`row * 1000000 + col` で採番）
- `lon`, `lat`: セル中心の座標
- `LST`: 目的変数（予測したい値、°C）
- `NDVI`, `NDBI`, `NDWI`: 説明変数（予測に使う特徴量）
- `IN_ANALYSIS_AREA`, `LST_VALID_RATIO`: 品質管理列（フィルタに使用。3節参照）
- `VALID_SATELLITE_MASK`: 品質管理列。ただし独立のフィルタ条件には使わない（この列は「NDVI / NDBI / NDWI のいずれかが非NULL」というORで定義されており、3列すべての非NULLを要求する時点で包含されるため）

---

## 3. 処理全体の流れ

処理は大きく9段階です（`src/common/` 内の担当モジュールを併記）。

1. **引数を読む**（`parse_arguments`）

   - データセットパス、しきい値、サンプル数、CV分割数、RF木本数などを受け取る

2. **データセットを読み込む**（`analysis_dataset.load_analysis_dataset`）

   - `cell_id` をキーとする属性テーブル（ジオメトリなし）を読み込む

3. **品質列でフィルタし、サンプリングする**（`analysis_dataset.filter_valid_rows` / `sample_dataset`）

   - `IN_ANALYSIS_AREA == 1` かつ特徴量・目的変数が非NULL かつ `LST_VALID_RATIO >= しきい値`（既定0.5）
   - フィルタ→サンプリングの順（ブロック割り当てより先。ブロック割り当てを先にすると各ブロックのセル数が不均等に減るため）

4. **ランダム分割で学習・評価**（`regression_models.fit_linear_regression` / `fit_random_forest`）

   - 学習80% / テスト20%
   - 線形回帰（X・y双方を標準化）とランダムフォレスト（RF）を学習
   - R2, RMSE, MAEを算出（`model_metrics.compute_metrics`）

5. **特徴量重要度の算出**（`regression_models` の戻り値 + `model_metrics.compute_vif`）

   - 線形回帰: 標準化係数の絶対値（`fit_linear_regression` の戻り値）
   - RF: 不純度ベース重要度（`fit_random_forest` の戻り値）
   - RF: permutation importance（`fit_random_forest` の戻り値）
   - 参考: VIF（多重共線性の確認）（`model_metrics.compute_vif`）

6. **Spatial CVで評価**（`spatial_cv.assign_spatial_blocks` / `split_by_spatial_blocks`）

   - 正準グリッドの row/col（`cell_id` をデコードして取得）を物理的に等間隔なブロックへ分割
   - GroupKFoldで空間ブロック単位に学習/評価を分離
   - foldごとの性能を記録し、平均と標準偏差を算出（`model_metrics.summarize_metric_dicts`）

7. **可視化の保存**（`analysis_plots.save_*`）

   - モデル比較図、特徴量重要度図、Spatial CVのfold別性能図

8. **SHAP解析**（`shap_report.compute_shap_outputs`）

   - RFモデルに対してSHAP値を計算
   - 平均絶対SHAPを算出し、summary/bar/dependence図を保存

9. **結果JSONを保存**（`src.common.summary.save_summary`）

   - 評価値、重要度、SHAP結果、出力ファイルパスをまとめて保存
   - VIFがInfになった場合は `null` に変換し、Infだった変数名を別キー（`vif_non_finite_features`）に記録する（`model_metrics.sanitize_vif_for_json`）

---

## 4. 指標の読み方（最重要）

### R2（決定係数）

- 1に近いほど良い
- 0に近いと「平均予測と同程度」
- マイナスだと平均予測より悪い

### RMSE（二乗平均平方根誤差）

- 予測誤差の代表値
- 小さいほど良い
- 外れ値の影響を受けやすい

### MAE（平均絶対誤差）

- 予測誤差の絶対値平均
- 小さいほど良い
- RMSEより外れ値に頑健

実務では、RMSEとMAEを併せて見ると誤差の性質を把握しやすいです。

### VIF（Variance Inflation Factor: 分散拡大要因）

VIFは、**説明変数どうしが似すぎていないか（多重共線性）**を確認するための指標です。

- このスクリプトでは、NDVI・NDBI・NDWIの関係が強すぎると、
  線形回帰の係数解釈が不安定になるため、VIFを確認しています。
- 目的は「予測精度を直接上げること」ではなく、
  **係数の解釈リスクを把握すること**です。

#### なぜ必要か

- 多重共線性が強いと、線形回帰の係数がデータ分割やノイズで大きく変わることがあります。
- その結果、「どの変数が効いているか」の解釈がぶれやすくなります。

#### なんのためにやったのか（このコードでの役割）

- 線形回帰の標準化係数を読むときの注意情報として利用するためです。
- `*_feature_importance.csv` と `*_results.json` に出力し、
  重要度比較（線形係数・RF重要度・SHAP）とあわせて解釈します。

#### どうやって評価しているか

このコードでは、各説明変数ごとに次を行います。

1. ある変数（例: NDVI）を一時的な目的変数にする
2. 残りの変数（例: NDBI, NDWI）で線形回帰する
3. そのときの $R^2$ から次式でVIFを計算する

$$
\mathrm{VIF}_j = \frac{1}{1 - R_j^2}
$$

- $R^2$ が 1 に近いほどVIFは大きくなり、共線性が強いことを示します。
- 実装では $R^2 \geq 0.999999$ を無限大（`inf`）として扱っています。

#### 目安（実務でよく使う判断）

- VIF ≈ 1: ほぼ問題なし
- VIF > 5: 注意
- VIF > 10: 強い多重共線性の疑い

注意: VIFが高いことは「モデルが必ず悪い」という意味ではありません。  
ここでは「線形係数の解釈には慎重になるべき」という警告として使います。実際に本分析でもNDVI・NDWIのVIFは10を大きく超えており、結果ドキュメントでは線形係数を補助的な情報として扱っています（[satellite_only_analysis_results_cellbased.md](../03_results/satellite_only_analysis_results_cellbased.md) 5.3節）。

#### 高VIFが係数に与える影響の実例

「係数の解釈には慎重に」が具体的に何を意味するかは、Limited シナリオで実測されています。相関 +0.986 の2列（建物の平均高さと最大高さ）を両方投入すると VIF は 46.7・54.9 に達し、**大きさが同程度で符号が逆の一対の係数**（+0.126 と −0.144）が現れて、全16変数中の第6・7位という高い順位を占めていました。片方の列を外して VIF を 2.5 まで下げると、同じ変数の係数はほぼ0（**残る15変数中の最下位**）へ収束します。**同一のセル集合で比較した結果**であるため、標本の違いでは説明できません。

つまり高VIFのもとでは、**係数の大きさも符号も実際の寄与を表さないこと**があります。順位が高いことを「支配的な変数である」根拠にしてはいけません。実例と対処の詳細は[limited_analysis_results.md](../03_results/limited_analysis_results.md) 6.4節を参照してください。

---

## 5. Spatial CVが必要な理由

地理データでは、近い地点ほど似た値を取りやすいです。  
ランダム分割だけだと、学習データとテストデータが近接しすぎて、性能を高く見積もることがあります。

Spatial CVでは、地理的にまとまったブロック単位で分けるため、
「未知の場所にどれだけ一般化できるか」をより現実的に評価できます。

### ブロックの作り方（新経路での変更点）

旧実装は経度・緯度をそれぞれ分位ビン化して掛け合わせる方式でしたが、ブロックの物理サイズがデータ密度に依存して不均一になる問題がありました。

新経路では、正準グリッドの row / col（絶対インデックス）を `block_size_m // scale` セルで整数除算し、物理的に等間隔なブロックを作ります。

```text
block_row = row // block_cells
block_col = col // block_cells
block_id  = block_row * block_id_stride + block_col
```

- ブロックサイズはメートル指定（`--block-size-m`、既定 `2700m`）
- ブロック原点はデータに依存させない（観測データの最小値を原点にしない）ため、しきい値・スケールを変えてもブロック境界がずれない
- **限界**: ブロック境界に位置するセルは、隣接ブロックと別foldに分かれる可能性が残る。この影響を定量化した結果は結果ドキュメントを参照（[satellite_only_analysis_results_cellbased.md](../03_results/satellite_only_analysis_results_cellbased.md) 4.5節）

---

## 6. SHAPの見方

SHAPは「各特徴量が予測値をどれだけ押し上げ/押し下げたか」を分解する手法です。

- `mean_abs_shap` が大きい特徴量ほど、予測に強く効いている
- summary plotで、影響の方向と強さを確認できる
- dependence plotで、各特徴量の値と寄与の関係を確認できる

注意点として、SHAPは因果関係を直接示すものではありません。

---

## 7. 主な出力ファイル

`data/output/satellite_only_cellbased/<観測日時>/` に次が出ます（接頭辞はデータセットファイル名に依存）。

- `*_sample_*.csv`: サンプリング結果
- `*_feature_importance.csv`: 係数・重要度・VIF
- `*_spatial_cv_folds.csv`: fold別評価値
- `*_model_comparison.png`: モデル比較図
- `*_feature_importance.png`: 特徴量重要度図
- `*_spatial_cv.png`: Spatial CV図
- `*_shap_importance.csv`: SHAP重要度
- `*_shap_summary.png`, `*_shap_bar.png`, `*_shap_dependence_*.png`: SHAP可視化
- `*_results.json`: 全結果の要約

旧経路の出力先（`data/output/satellite_only/`）とは分離しています。集計単位・格子が異なる別物であるためです（[calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) 6.7節）。

---

## 8. 実行例

```powershell
python -m src.analysis.analysis_rq3_satellite_only `
  --dataset-path data/output/datasets/dataset_satellite_only_20230707_032329_hanoi_30m.gpkg `
  --lst-valid-ratio-threshold 0.5 `
  --sample-size 100000 `
  --cv-splits 5 `
  --block-size-m 2700 `
  --rf-trees 300
```

引数を省略すると、既定値（30m・`20230707_032329`観測・block-size-m=2700等）で実行されます。データセットが未生成の場合は、先に `build_dataset.py` で生成してください（[calc_urban_params_io_spec.md](calc_urban_params/calc_urban_params_io_spec.md) 6章参照）。

---

## 9. 初心者向けの読み解き順

統計に不慣れな場合は、次の順で読むと理解しやすいです。

1. `main()` で全体フローを確認
2. `src.common.regression_models.fit_linear_regression()` と `fit_random_forest()` でモデル比較の軸を理解
3. `src.common.analysis_runs.run_spatial_cv_models()` と `src.common.spatial_cv.assign_spatial_blocks()` で空間評価の考え方を理解
4. `src.common.shap_report.compute_shap_outputs()` で解釈可能性の見方を理解

---

## 10. よくあるつまずき

- **つまずき1**: R2が高いのにSpatial CVで落ちる  
  ランダム分割の過大評価が原因のことがあります。

- **つまずき2**: SHAP重要度とRF重要度の順位が違う  
  算出原理が異なるため、ある程度の差は自然です。

- **つまずき3**: VIFが高いと悪いモデルなのか  
  線形回帰の係数解釈には注意が必要、という警告指標です。予測性能そのものは、共線性を解消してもほとんど変わらないことが実測されています（[limited_analysis_results.md](../03_results/limited_analysis_results.md) 6.4節）。

- **つまずき4**: 旧結果ドキュメントと数値が違う  
  集計単位（ピクセル vs セル）・格子・観測日数・Spatial CV方式が異なる別物です。直接比較しないでください（[satellite_only_analysis_results_cellbased.md](../03_results/satellite_only_analysis_results_cellbased.md) 0節）。

---

## 11. 次にやると理解が深まること

- `*_results.json` の `random_split` と `spatial_cv` を比較する
- `*_shap_summary.png` と `*_shap_dependence_*.png` を見て、寄与の方向性を確認する
- RQ3観点で「衛星指標だけで説明できる範囲」と「限界」を文章化する
