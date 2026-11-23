<!--
見出し: 3.1　LST と分光指数の算出
状態: 初稿
依拠する正本:
  - docs/02_methods/gee_calc_LST.md @ 32c9d07811
  - docs/02_methods/calc_LST_report.md @ 20fe1daab8
  - docs/02_methods/gee_calc_satellite_indices.md @ 27c58ff56b
-->

## 3.1　LST と分光指数の算出

### 3.1.1　SMW 法による LST の算出

LST は，Ermida らが GEE 上の JavaScript で公開した SMW 法のコード[@S1]を Python に書き直して算出した．係数の表と放射率の換算係数は原典のコードの値をそのまま用い，原典から意図して変えたのは，出力を摂氏に換算する点と，3.1.2 項で述べる雲のマスクの条件だけである．

SMW 法は，熱赤外バンド（Landsat 8/9 のバンド 10）の大気上端の輝度温度 $T_b$ と，地表面の放射率 $\varepsilon$ から，@eq:smw で LST を求める[@S1]．

$$ \mathrm{LST} = A\frac{T_b}{\varepsilon} + \frac{B}{\varepsilon} + C $$ {#eq:smw}

係数 $A$・$B$・$C$ は，センサごとに，大気中の可降水量（TPW）の階級に応じて定められている[@S1]．TPW は NCEP/NCAR の再解析データ[@kalnay1996_ncep_ncar]から，観測日（協定世界時）の 0 時から翌日 0 時までのデータのうち観測時刻に最も近い 2 時刻の値を線形内挿して求め，6 kg/m² 刻みの 10 階級に分ける．観測日のデータが無い画素は LST を求めずにマスクする．@eq:smw で得た値は絶対温度であるため，273.15 を引いて摂氏（°C）に換算する．

放射率は，ASTER GED v3[@hulley2015_aster_ged]の放射率を基に，観測時の植生の量に合わせて補正して求める[@S1]．まず，観測した地表面反射率から求めた NDVI（3.1.3 項）を用いて，植生被覆率 $\mathrm{FVC}$ を @eq:fvc で求め，0〜1 の範囲に収める．

$$ \mathrm{FVC} = \left(\frac{\mathrm{NDVI} - 0.2}{0.86 - 0.2}\right)^2 $$ {#eq:fvc}

ASTER GED v3 は 2000〜2008 年の平均の放射率を 100 m の解像度で与える．そのバンド 13・14 の放射率 $\varepsilon_{13}$・$\varepsilon_{14}$ を，$0.6820\,\varepsilon_{13} + 0.2578\,\varepsilon_{14} + 0.0584$ により Landsat の熱赤外バンドの放射率 $\varepsilon_{\mathrm{ASTER}}$ に換算する．この値から，ASTER の NDVI で求めた植生被覆率 $\mathrm{FVC}_{\mathrm{ASTER}}$ を用いて植生の寄与を除き，裸地の放射率 $\varepsilon_{\mathrm{bare}}$ を @eq:ebare で求める．

$$ \varepsilon_{\mathrm{bare}} = \frac{\varepsilon_{\mathrm{ASTER}} - 0.99\,\mathrm{FVC}_{\mathrm{ASTER}}}{1 - \mathrm{FVC}_{\mathrm{ASTER}}} $$ {#eq:ebare}

観測時の放射率は，観測時の植生被覆率で植生（放射率 0.99）と裸地を混ぜ合わせた @eq:emissivity で求める．ただし，Landsat の品質情報（QA_PIXEL）で水域と判定された画素は 0.99，雪と判定された画素は 0.989 に置き換える．

$$ \varepsilon = 0.99\,\mathrm{FVC} + (1 - \mathrm{FVC})\,\varepsilon_{\mathrm{bare}} $$ {#eq:emissivity}

この放射率は観測時の NDVI から求めるため，説明変数に用いる NDVI が目的変数の LST の算出にも入る．この依存が結果に与える影響は，NDVI による補正を行わない放射率で求めた LST と比べる感度分析で確かめる（3.6 節）．

### 3.1.2　雲・影のマスク

LST の算出では，地表面反射率の品質情報（QA_PIXEL）のうち，巻雲（ビット 2）・雲（ビット 3）・雲の影（ビット 4）・雪（ビット 5）のフラグがすべて立っていない画素だけを用いる．原典のコードは雲と雲の影の 2 つのフラグだけを用いるが，本研究では巻雲と雪を加えた．原典の条件では，LST の最小値が −102.2 °C となる観測があり，原典のマスクを通った −20 °C 未満の画素を調べると，雪と巻雲のフラグが立っていたためである．ハノイで雪は考えにくいため，低温の雲が雪や氷と判定されたと考えられる．雲の周りを広げて除くフラグ（ビット 1）は，加えてもこの観測の主な異常が解消しなかったため用いない．

### 3.1.3　分光指数の算出

説明変数の候補とする分光指数は，LST と同じ観測の地表面反射率（Level-2）から算出した．反射率は，配布される整数値 $\mathrm{DN}$ を $\mathrm{DN} \times 0.0000275 - 0.2$ で物理量に換算し，有効範囲（7273〜43636）の外の値は除く．品質情報は，LST の算出よりも厳しく，QA_PIXEL の欠損（ビット 0）・雲の周辺（ビット 1）・巻雲・雲・雲の影・雪のフラグがすべて立っておらず，かつ放射量の飽和を示す QA_RADSAT が 0 の画素だけを用いる．

算出した指数は @tbl:spectral_indices の 4 つで，いずれも 2 つのバンドの正規化差分 $(A - B)/(A + B)$ である．分母の絶対値が $10^{-6}$ 以下の画素は，値が定まらないためマスクする．

| 指数 | 名称 | 定義 | 主に表すもの |
|------|------|------|------|
| NDVI | 正規化植生指数 | (NIR − RED)/(NIR + RED) | 植生 |
| NDBI | 正規化市街地指数 | (SWIR1 − NIR)/(SWIR1 + NIR) | 市街地・裸地 |
| NDWI | 正規化水指数 | (GREEN − NIR)/(GREEN + NIR) | 水域 |
| MNDWI | 修正正規化水指数 | (GREEN − SWIR1)/(GREEN + SWIR1) | 水域 |

: 算出した分光指数（GREEN・RED・NIR・SWIR1 は Landsat 8/9 のバンド 3・4・5・6） {#tbl:spectral_indices}

NDBI・NDWI・MNDWI は，それぞれ Zha ら (2003)，McFeeters (1996)，Xu (2006) が提案した指数である[要出典]．MNDWI は NDWI の NIR を SWIR1 に置き換えたものである．NDVI と NDWI はどちらも NIR を含み，NIR の符号が逆であるため，構造的に強い負の相関を持つ．MNDWI は NIR を含まないため，この構造を持たない．各シナリオでどの指数を説明変数に用いるか，またその理由は 3.3 節で述べる．

指数は ROI で切り出し，LST と同じ 30 m の解像度で出力した．LST と指数では雲のマスクの条件が異なるため，有効な画素の範囲も異なる．分析には，LST と指数の両方が有効なセルだけを用いる（3.3 節）．
