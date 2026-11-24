<!--
見出し: 付録
状態: 執筆中
依拠する正本:
  - docs/03_results/limited_analysis/limited_analysis_multicollinearity.md @ 5d2eaf93f2
  - docs/03_results/spatial_cv_design_results.md @ 8f171b7531
-->

# 付録

[TBD:本文]

<!--
付録 A・B は第3章（3.5.2 項・3.3.3 項）から参照している．付録の項の番号と並びは付録の執筆時に決める．
付録 A に書く内容: LST のセミバリオグラムの図と表，ブロックの大きさ × 緩衝帯の比較，学習量の対照，
ブロック数と fold のばらつき，残差の Moran の I．正本は docs/03_results/spatial_cv_design_results.md の 4 章．
セミバリオグラムの図は images/ に未作成（2026-11-24 時点）．
-->

## 付録 A　Spatial CV のブロック設計の詳細

[TBD:本文]

## 付録 B　分光指数の間の関係

正規化差分 $\mathrm{ND}(x, y) = (x - y)/(x + y)$ には，$\operatorname{atanh}(\mathrm{ND}) = \frac{1}{2}\ln(x/y)$ という性質がある．このため，緑（G）・赤（R）・近赤外（NIR）・短波赤外（SWIR1）の 4 つのバンドから作る指数の間には，画素ごとに @eq:ndwi_identity と @eq:mndwi_identity の関係が成り立つ．これは本研究で導いた関係である．

$$ \operatorname{atanh}(\mathrm{NDWI}) = \frac{1}{2}\ln\frac{G}{R} - \operatorname{atanh}(\mathrm{NDVI}) $$ {#eq:ndwi_identity}

$$ \operatorname{atanh}(\mathrm{MNDWI}) = \operatorname{atanh}(\mathrm{NDWI}) - \operatorname{atanh}(\mathrm{NDBI}) $$ {#eq:mndwi_identity}

したがって，NDVI と NDBI をモデルに含めると，NDWI と MNDWI がそれ以上に加える情報は，いずれも緑と赤の反射率の比だけである．MNDWI が NIR を含まないことは，NDVI との 2 変数の相関を下げても，3 つの指数の組での共線性を断つ理由にはならない．セルで平均した値では近似になるが，分析に用いた標本でもほぼ成り立つことを確かめた．ただし，この関係が示すのは，NDWI を除くと失われる成分を緑と赤の比として書けることまでであり，その成分が水域の情報を含まないことは示さない．
