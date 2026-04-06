# Satellite Only 初期実行結果

**最終更新**: 2026-04-06  
**関連ドキュメント**: [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

---

## 1. 今回の位置づけ

本研究の RQ3 では、以下の 3 シナリオを比較する。

| シナリオ | 使用データ | 想定状況 |
|------|------|------|
| Full | 衛星指標 + 測量 GIS | 理想的な研究環境 |
| Limited | 衛星指標 + OSM 公開データ | 測量データ入手困難な都市 |
| Satellite Only | 衛星指標のみ | 最も制約された状況 |

現時点では GIS データ整備と OSM 利用設計が未確定であるため、今回は **Satellite Only シナリオを先に成立させること** を目的とした。  
具体的には、衛星指標だけで LST をどこまで説明できるかを先に定量化し、その結果が空間自己相関に依存した過大評価でないかを Spatial CV で確認し、さらに SHAP によって非線形寄与の方向性を解釈できるようにした。

---

## 2. 今回実施したこと

1. 2023-07-07 の観測から、LST と衛星指標の両方で品質が最も高い観測を選定した
2. 選定観測の `LST`, `NDVI`, `NDBI`, `NDWI` を同一グリッド上で結合し、ピクセル単位の分析用 CSV を作成した
3. ランダム分割で Multiple Linear Regression と Random Forest を実行した
4. `lon`, `lat` を用いた空間ブロック分割の Spatial CV を追加した
5. Random Forest に対して SHAP を計算し、重要度と寄与方向を可視化した

---

## 3. データと処理条件

### 3.1 採用した観測

- 対象日: `2023-07-07`
- 採用観測: `2023-07-07T03:23:29Z`
- 採用理由:
  - `LST valid_pixel_ratio = 99.6001%`
  - `indices valid_pixel_ratio = 99.5729%`
  - `cloud_cover = 8.38`

この観測は、同日の候補の中で LST と衛星指標の両方の有効画素率が最も高く、雲量も少ないため、検証データとして最も妥当と判断した。

### 3.2 入力データ

- `data/output/LST/2023/LST_Landsat8_20230707_032329Z.tif`
- `data/output/indices/2023/INDICES_Landsat8_20230707_032329Z.tif`

### 3.3 品質管理

- NaN を除外
- `LST` を `15–65°C` に制限
- `NDVI`, `NDBI`, `NDWI` を `-1.1〜1.1` に制限

### 3.4 モデル設定

- サンプル数: `100,000`
- 学習 / テスト: `80,000 / 20,000`
- 説明変数: `NDVI`, `NDBI`, `NDWI`
- 目的変数: `LST`
- Spatial CV:
  - `5-fold`
  - `lon/lat` をそれぞれ `8` 分位に区切った空間ブロック
  - 実際に使われたグループ数: `54`
- SHAP:
  - SHAP 評価サンプル: `2,000`
  - background: `500`

### 3.5 出力ファイル

- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_dataset.csv`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_summary.json`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_results.json`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_feature_importance.csv`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_spatial_cv_folds.csv`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_importance.csv`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_model_comparison.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_spatial_cv.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_summary.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_bar.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_dependence_NDVI.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_dependence_NDBI.png`
- `data/csv/analysis/satellite_only_20230707_20230707_032329Z_shap_dependence_NDWI.png`

---

## 4. 基本結果

### 4.1 データセット規模

| 項目 | 値 |
|------|------|
| 全ピクセル数 | 8,278,699 |
| 品質管理後ピクセル数 | 2,104,665 |
| LST 平均 | 35.7646°C |

### 4.2 ランダム分割でのモデル性能

| モデル | R² | RMSE | MAE |
|------|------|------|------|
| Linear Regression | 0.5310 | 1.4417 | 1.0621 |
| Random Forest | 0.7009 | 1.1514 | 0.8555 |

### 4.3 Spatial CV でのモデル性能

| モデル | R² mean | R² std | RMSE mean | MAE mean |
|------|------|------|------|------|
| Linear Regression | 0.4929 | 0.0649 | 1.4809 | 1.0949 |
| Random Forest | 0.6759 | 0.0147 | 1.1838 | 0.8846 |

### 4.4 変数重要度

| 変数 | \|標準化係数\| | RF Importance | Permutation Importance | VIF |
|------|------|------|------|------|
| NDVI | 1.1839 | 0.1817 | 0.3052 | 20.2073 |
| NDBI | 0.5314 | 0.6490 | 0.7334 | 1.3346 |
| NDWI | 1.1588 | 0.1693 | 0.2919 | 19.1795 |

### 4.5 SHAP 平均絶対値

| 変数 | mean \|SHAP\| |
|------|------|
| NDBI | 0.8327 |
| NDVI | 0.5441 |
| NDWI | 0.4261 |

---

## 5. 結果の解釈

### 5.1 まず言えること

今回の結果でまず重要なのは、**衛星指標だけでも LST をかなり説明できた** ことである。

- ランダム分割でも Linear Regression は `R² = 0.5310`
- ランダム分割では Random Forest が `R² = 0.7009`
- Spatial CV でも Random Forest は `R² mean = 0.6759`

これは、`NDVI`, `NDBI`, `NDWI` の 3 変数だけでも、2023-07-07 のハノイにおける LST 分布のばらつきのかなり大きな部分を説明できたことを意味する。  
したがって、Satellite Only は「最低限の代替案」にとどまらず、**初期段階として十分に有望な分析条件** である。

### 5.2 Spatial CV で何が分かったか

今回追加した Spatial CV の目的は、ランダム分割での高い精度が、近接ピクセル同士の空間自己相関に強く依存した過大評価でないかを確認することだった。

結果は次の通りである。

- Linear Regression:
  - ランダム分割 `R² = 0.5310`
  - Spatial CV `R² mean = 0.4929`
- Random Forest:
  - ランダム分割 `R² = 0.7009`
  - Spatial CV `R² mean = 0.6759`

どちらのモデルでも精度はやや低下したが、落ち幅は極端ではない。

- Linear Regression の低下幅: 約 `0.038`
- Random Forest の低下幅: 約 `0.025`

このことから、**ランダム分割での評価は多少楽観的だった可能性はあるが、結果の本質が崩れるほどの過大評価ではない** と解釈できる。  
特に Random Forest は Spatial CV でも `R² ≈ 0.676` を維持しており、Satellite Only の説明力は比較的頑健とみなせる。

### 5.3 なぜ Random Forest の方が良いのか

Random Forest の性能が Linear Regression より一貫して高い。

- ランダム分割でも高い
- Spatial CV でも高い
- Fold ごとのばらつきも比較的小さい

これは、LST と衛星指標の関係が単純な直線ではなく、**非線形な関係を含んでいる** ことを示唆する。  
つまり、Satellite Only 条件では「直線的に効く」とみなすより、「条件に応じて効き方が変わる」と考えた方が現実に近い。

### 5.4 各変数はどう解釈できるか

Random Forest の重要度、Permutation Importance、SHAP の 3 つを総合すると、今回もっとも支配的だったのは `NDBI` である。

- RF Importance: `NDBI = 0.6490`
- Permutation Importance: `NDBI = 0.7334`
- mean |SHAP|: `NDBI = 0.8327`

これは、市街地的・人工被覆的な地表特性が強いほど LST が高くなりやすいことを示す結果として解釈できる。

一方、`NDVI` と `NDWI` は冷却側の役割を示している。

SHAP の分位点ベース確認では、

- `NDVI` が低い領域では SHAP 平均が正、高い領域では負
- `NDBI` が低い領域では SHAP 平均が負、高い領域では正
- `NDWI` が低い領域では SHAP 平均が正、高い領域では負

となった。

これは、概念的には次のように読める。

- `NDBI` が高いほど昇温方向に寄与する
- `NDVI` が高いほど冷却方向に寄与する
- `NDWI` が高いほど冷却方向に寄与する

したがって、今回の初期結果は大きく見ると、

- `NDBI`: 昇温側
- `NDVI`: 冷却側
- `NDWI`: 冷却側

という、都市気候研究として比較的自然な構図になっている。

### 5.5 SHAP を追加した意味

これまでは「NDBI が重要らしい」「NDVI と NDWI は負方向らしい」という解釈だったが、SHAP を追加したことで、**Random Forest のような非線形モデルでも寄与方向を説明できるようになった**。

今回の SHAP により、

- NDBI は非線形モデルでも一貫して最重要
- NDVI と NDWI は高いほど冷却方向
- 線形回帰の符号と大筋では整合

ということが確認できた。

これは、単なる性能比較だけでなく、「なぜ RF の方が良いのか」を説明する材料として重要である。

### 5.6 ただし注意点もある

線形回帰の係数は、そのまま「どちらが本当に重要か」とは言い切れない。  
理由は `NDVI` と `NDWI` の VIF が高く、両者がかなり似た情報を持っているためである。

- `NDVI VIF = 20.2073`
- `NDWI VIF = 19.1795`

このため、線形回帰での係数の大きさは多重共線性の影響を受けている可能性が高い。  
現段階では、

- 係数の符号は参考になる
- 重要度順位の解釈は RF と SHAP を優先する

という理解が適切である。

### 5.7 今回の結果をどう位置づけるべきか

今回の結果は、研究としてはまだ **単日・単都市・初期ベースライン** である。  
ただし、次の 3 点は十分に示せた。

1. Satellite Only 条件でも LST の説明力は無視できない水準にある
2. Random Forest は Spatial CV を通しても高い説明力を維持した
3. SHAP により、NDBI が昇温、NDVI/NDWI が冷却という解釈を非線形モデルでも補強できた

したがって、今回の結果は「Satellite Only は研究の出発点として十分に成立する」ことの定量的根拠になっている。

---

## 6. 今後の研究の方向性

### 6.1 Satellite Only を複数日へ広げる

今回は `2023-07-07` の 1 観測のみである。  
今後は複数日・複数季節・可能なら複数年へ広げて、

- この関係が安定しているのか
- 雨季と乾季で説明力が変わるのか
- 変数重要度が季節で入れ替わるのか

を確認する必要がある。

### 6.2 SHAP 解釈をさらに深める

今回は summary plot と dependence plot を作成したが、次の段階ではそれを論文用の説明に落とし込む必要がある。

具体的には、

- `NDBI` がどの範囲で急に効くのか
- `NDVI` や `NDWI` がどの程度増えると冷却が強くなるのか
- 特定の閾値や飽和的な変化があるのか

を整理すると、議論の質が上がる。

### 6.3 Limited シナリオへ進む

RQ3 の本来の設計では、Satellite Only の次に **Limited** を比較することが重要である。  
つまり、OSM を導入してどれだけ改善するかを確認する。

ここで答えたい問いは、

- 衛星指標だけで十分か
- OSM を足すとどれくらい改善するか
- 公開データだけでも実用的な説明力に届くか

である。

### 6.4 最後に Full シナリオへ接続する

GIS 整備が完了した後は、測量 GIS を含む **Full** シナリオを実装する。  
その上で、

- `Satellite Only`
- `Limited`
- `Full`

の 3 条件を比較すれば、RQ3 の中心的な比較設計が完成する。

---

## 7. 現時点での結論

今回の実行から言えることは、以下の通りである。

1. `Satellite Only` 条件でも LST の説明は十分に可能である
2. Random Forest はランダム分割で `R² = 0.7009`、Spatial CV でも `R² mean = 0.6759` を維持した
3. 過大評価は多少あるかもしれないが、空間分割後も結論が大きく崩れるほどではなかった
4. `NDBI` は最重要の昇温側要因であり、`NDVI` と `NDWI` は冷却側要因として働いた
5. SHAP により、非線形モデルでも寄与方向を解釈できる状態になった
6. 次は複数日化、その後に Limited / Full 比較へ進むのが妥当である

要するに、今回の結果は「Satellite Only は研究の出発点として十分に成立する」だけでなく、  
「Spatial CV と SHAP を加えてもその結論は大きく揺らがない」ことまで示した。
