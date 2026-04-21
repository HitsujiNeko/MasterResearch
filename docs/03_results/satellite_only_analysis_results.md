# Satellite Only 分析結果

**最終更新**: 2026-04-21  
**関連ドキュメント**: [analysis_workflow.md](../02_methods/analysis_workflow.md), [research_guide.md](../01_planning/research_guide.md), [GIS_IDEAS_abstract.md](GIS_IDEAS_abstract.md)  
**対象RQ**: RQ3（データ制約下での有効性評価）

---

## 1. 今回の位置づけ

本研究の RQ3 では、以下の 3 シナリオを比較する。

| シナリオ | 使用データ | 想定状況 |
|------|------|------|
| Full | 衛星指標 + 測量 GIS + 公開 GIS | 理想的な研究環境 |
| Limited | 衛星指標 + 公開 GIS | 測量データ入手困難な都市 |
| Satellite Only | 衛星指標のみ | 最も制約された状況 |

現時点では `Limited` / `Full` は未完了であり、**Satellite Only をベースラインとして先に成立させる段階**にある。  
本ドキュメントは、そのベースライン結果を単日ではなく **3 観測日**で整理し、今後の比較の基準線として残すことを目的とする。

---

## 2. 今回実施したこと

1. 2023-2024 年の候補シーンから、LST と衛星指標の品質が十分な観測を選定した
2. 各観測について `LST`, `NDVI`, `NDBI`, `NDWI` を同一グリッド上で結合し、ピクセル単位の分析用 CSV を作成した
3. 各観測で Multiple Linear Regression と Random Forest を random split で比較した
4. `lon`, `lat` に基づく空間ブロック分割の Spatial CV を実施した
5. Random Forest に対して SHAP を計算し、変数重要度と寄与方向を確認した

---

## 3. データと処理条件

### 3.1 採用した観測

| 観測日 | 採用観測（UTC） | 備考 |
|------|------|------|
| 2023-07-07 | `2023-07-07T03:23:29Z` | 夏季、雲量が比較的少ない |
| 2023-07-23 | `2023-07-23T03:23:09Z` | 夏季の追加観測 |
| 2024-11-30 | `2024-11-30T03:23:36Z` | 乾季側の比較観測 |

採用理由は、ROI のカバー率と雲マスク後の LST・指標の有効画素率を比較した結果、  
分析に使える品質を満たしていたためである。

### 3.2 入力データ

- `data/output/LST/2023/LST_Landsat8_20230707_032329Z.tif`
- `data/output/LST/2023/LST_Landsat8_20230723_032309Z.tif`
- `data/output/LST/2024/LST_Landsat8_20241130_032336Z.tif`
- `data/output/indices/2023/INDICES_Landsat8_20230707_032329Z.tif`
- `data/output/indices/2023/INDICES_Landsat8_20230723_032309Z.tif`
- `data/output/indices/2024/INDICES_Landsat8_20241130_032336Z.tif`

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
- SHAP:
  - SHAP 評価サンプル: `2,000`
  - background: `500`

### 3.5 出力ファイル

観測日ごとに次の出力を保持している。

- `data/csv/analysis/satellite_only_<date>_<obs_key>_summary.json`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_results.json`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_feature_importance.csv`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_spatial_cv_folds.csv`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_shap_importance.csv`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_model_comparison.png`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_spatial_cv.png`
- `data/csv/analysis/satellite_only_<date>_<obs_key>_shap_summary.png`

観測日比較の要約:

- `data/csv/analysis/satellite_only_multidate_summary.csv`
- `data/csv/analysis/satellite_only_multidate_summary.json`
- `data/csv/analysis/satellite_only_multidate_lst_violin.png`

---

## 4. 基本結果

### 4.1 データセット規模

| 観測日 | 品質管理後ピクセル数 | LST 平均 |
|------|------|------|
| 2023-07-07 | 2,104,665 | 35.7646°C |
| 2023-07-23 | 3,213,377 | 36.0930°C |
| 2024-11-30 | 3,779,821 | 24.9937°C |

### 4.2 ランダム分割でのモデル性能

| 観測日 | LR R² | RF R² | LR RMSE | RF RMSE |
|------|------|------|------|------|
| 2023-07-07 | 0.5310 | 0.7009 | 1.4417 | 1.1514 |
| 2023-07-23 | 0.5401 | 0.6445 | 1.8775 | 1.6508 |
| 2024-11-30 | 0.5946 | 0.7180 | 1.2986 | 1.0830 |

### 4.3 Spatial CV でのモデル性能

| 観測日 | LR R² mean | RF R² mean | LR R² std | RF R² std |
|------|------|------|------|------|
| 2023-07-07 | 0.4929 | 0.6759 | 0.0649 | 0.0147 |
| 2023-07-23 | 0.4902 | 0.6032 | 0.0974 | 0.0583 |
| 2024-11-30 | 0.5744 | 0.6965 | 0.0447 | 0.0413 |

### 4.4 変数重要度

| 観測日 | 指標 | \|標準化係数\| | RF Importance | Permutation Importance | VIF |
|------|------|------|------|------|------|
| 2023-07-07 | NDVI | 1.1839 | 0.1817 | 0.3052 | 20.2073 |
| 2023-07-07 | NDBI | 0.5314 | 0.6490 | 0.7334 | 1.3346 |
| 2023-07-07 | NDWI | 1.1588 | 0.1693 | 0.2919 | 19.1795 |
| 2023-07-23 | NDVI | 0.7870 | 0.1042 | 0.1310 | 32.4660 |
| 2023-07-23 | NDBI | 0.6095 | 0.7215 | 0.7958 | 1.9789 |
| 2023-07-23 | NDWI | 0.8760 | 0.1743 | 0.2450 | 29.2833 |
| 2024-11-30 | NDVI | 0.9592 | 0.2481 | 0.5725 | 37.3960 |
| 2024-11-30 | NDBI | 0.6020 | 0.6416 | 0.5046 | 1.9288 |
| 2024-11-30 | NDWI | 0.8146 | 0.1103 | 0.2144 | 36.5068 |

### 4.5 SHAP 平均絶対値

| 観測日 | NDBI | NDVI | NDWI |
|------|------|------|------|
| 2023-07-07 | 0.8327 | 0.5441 | 0.4261 |
| 2023-07-23 | 1.2505 | 0.4977 | 0.4147 |
| 2024-11-30 | 0.8035 | 0.6436 | 0.3260 |

---

## 5. 結果の解釈

### 5.1 まず言えること

3 観測日すべてで、**衛星指標だけでも LST を一定程度説明できた**。

- Linear Regression の random split `R²` は `0.5310`〜`0.5946`
- Random Forest の random split `R²` は `0.6445`〜`0.7180`
- Random Forest の Spatial CV `R² mean` は `0.6032`〜`0.6965`

したがって、`Satellite Only` は単日限定の偶然ではなく、複数観測日でも成立するベースラインである。

### 5.2 Spatial CV で何が分かったか

どの観測日でも random split から Spatial CV への性能低下はあったが、落ち幅は極端ではない。

- 2023-07-07: RF `0.7009 → 0.6759`
- 2023-07-23: RF `0.6445 → 0.6032`
- 2024-11-30: RF `0.7180 → 0.6965`

このことから、ランダム分割の性能が空間自己相関だけで説明される過大評価ではないと解釈できる。  
特に 2024-11-30 でも RF が `R² mean ≈ 0.6965` を維持している点は重要である。

### 5.3 なぜ Random Forest の方が良いのか

3 観測日すべてで Random Forest が Linear Regression を上回った。  
これは、LST と衛星指標の関係が単純な直線ではなく、**非線形な効き方を含む**ことを示唆する。

特に 2023-07-23 のように夏季でばらつきが大きい観測でも、RF は LR より高い説明力を維持した。

### 5.4 各変数はどう解釈できるか

3 観測日を通じて、NDBI は一貫して最重要の昇温側指標であった。

- RF Importance は毎回 NDBI が最大
- SHAP の mean \|SHAP\| も毎回 NDBI が最大

一方で NDVI と NDWI は冷却側の役割を持つ傾向が維持された。  
観測日により NDVI と NDWI の相対的な大きさは多少変動するが、**「NDBI が昇温、NDVI / NDWI が冷却」**という構図自体は一貫している。

### 5.5 SHAP を追加した意味

SHAP により、Random Forest のような非線形モデルでも寄与方向を説明できるようになった。  
今回の結果では、

- NDBI は 3 観測日で一貫して大きい正方向寄与を持つ
- NDVI は高いほど冷却方向に働く
- NDWI も高いほど冷却方向に働く

という解釈を、単なる性能差ではなくモデル内部の寄与として確認できた。

### 5.6 ただし注意点もある

NDVI と NDWI の VIF は 3 観測日とも高く、多重共線性の影響が強い。

- 2023-07-07: `20.2073`, `19.1795`
- 2023-07-23: `32.4660`, `29.2833`
- 2024-11-30: `37.3960`, `36.5068`

したがって、線形回帰の係数の絶対値順位は補助的に扱うべきであり、  
主な解釈は Random Forest と SHAP に基づくのが妥当である。

### 5.7 今回の結果をどう位置づけるべきか

今回の結果は、研究全体としてはまだ `Satellite Only` に限られている。  
ただし、次の 3 点は十分に示せた。

1. Satellite Only 条件でも LST の説明力は無視できない
2. その説明力は 3 観測日で概ね再現した
3. NDBI 優位、NDVI / NDWI 冷却という解釈は複数観測日で大きく崩れなかった

したがって、本ドキュメントは `Limited` / `Full` と比較するための **基準線ドキュメント** として位置づけるのが適切である。

---

## 6. 今後の研究の方向性

### 6.1 Limited シナリオへ進む

次段階では、OpenStreetMap や Microsoft GlobalMLBuildingFootprints を導入し、  
公開 GIS を加えた `Limited` が `Satellite Only` をどれだけ改善するかを確認する。

### 6.2 Full シナリオへ接続する

測量由来 GIS の利用可能レイヤと算出方法を整理した後、`Full` を実装する。  
その上で、

- `Satellite Only`
- `Limited`
- `Full`

の 3 条件を比較することで、RQ3 の中心比較が完成する。

### 6.3 複数日・季節比較を継続する

現時点では夏季 2 観測、乾季 1 観測である。  
今後は追加日付も含めて、

- 季節差で説明力がどう変わるか
- 重要度順位が安定しているか
- `Limited` / `Full` の改善幅が季節で変わるか

を検証する必要がある。

---

## 7. 現時点での結論

今回の実行から言えることは、以下の通りである。

1. `Satellite Only` 条件でも LST の説明は十分に可能である
2. Random Forest は 3 観測すべてで Spatial CV 後も `R² mean > 0.60` を維持した
3. 過大評価は多少あるかもしれないが、空間分割後も結論が大きく崩れるほどではなかった
4. `NDBI` は一貫して最重要の昇温側要因であり、`NDVI` と `NDWI` は冷却側要因として働いた
5. SHAP により、非線形モデルでも寄与方向を解釈できる状態になった
6. 次は `Limited`、その後に `Full` 比較へ進むのが妥当である

要するに、今回の結果は「Satellite Only は研究の出発点として十分に成立する」だけでなく、  
「複数観測日でもその結論が大きく揺らがない」ことまで示した。
