<!--
見出し: 3.1　LST と分光指数の算出
状態: 初稿
依拠する正本:
  - docs/02_methods/gee_calc_LST.md @ 32c9d07811
  - docs/02_methods/calc_LST_report.md @ 20fe1daab8
  - docs/02_methods/gee_calc_satellite_indices.md @ 27c58ff56b
-->

## 3.1　LST と分光指数の算出

### 3.1.1　LST の算出

LST は，Ermida らが GEE 上で公開した SMW 法のコード[@S1]を Python に書き直して算出した．SMW 法は，熱赤外バンド（Landsat 8/9 のバンド 10）の大気上端の輝度温度 $T_b$ と地表面の放射率 $\varepsilon$ から，@eq:smw で LST を求める[@S1]．

$$ \mathrm{LST} = A\frac{T_b}{\varepsilon} + \frac{B}{\varepsilon} + C $$ {#eq:smw}

係数 $A$・$B$・$C$ は，センサと，大気中の可降水量の階級（10 階級）ごとに定められている[@S1]．可降水量は NCEP/NCAR の再解析データ[@kalnay1996_ncep_ncar]を観測時刻へ線形内挿して求める．@eq:smw で得た絶対温度から 273.15 を引いて °C に換算する．放射率は，ASTER GED v3[@hulley2015_aster_ged]から求めた裸地の放射率と植生の放射率（0.99）を，観測時の NDVI から求めた植生被覆率で混ぜ合わせて求める[@S1]．このため，説明変数に用いる NDVI が LST の算出にも入る．その影響は感度分析で確かめる（3.6.3 項）．

雲と影は，地表面反射率の品質情報（QA_PIXEL）で除く．原典のコードは雲と雲の影のフラグだけを用いるが，その条件では LST の最小値が −102.2 °C となる観測があり，−20 °C 未満の画素には巻雲と雪のフラグが立っていた．そこで本研究では，巻雲と雪のフラグが立つ画素も除いた．原典から意図して変えたのは，この点と，出力を °C にした点だけである．

### 3.1.2　分光指数の算出

分光指数は，LST と同じ観測の地表面反射率から，@tbl:spectral_indices の 4 つを算出した．品質情報の条件は LST より厳しく，雲の周辺・欠損・放射量の飽和を示す画素も除く．このため LST と指数では有効な画素の範囲が異なり，分析には両方が有効なセルだけを用いる（3.3 節）．

| 指数 | 定義 | 主に表すもの |
|------|------|------|
| NDVI（正規化植生指数） | (NIR − RED)/(NIR + RED) | 植生 |
| NDBI（正規化市街地指数） | (SWIR1 − NIR)/(SWIR1 + NIR) | 市街地・裸地 |
| NDWI（正規化水指数） | (GREEN − NIR)/(GREEN + NIR) | 水域 |
| MNDWI（修正正規化水指数） | (GREEN − SWIR1)/(GREEN + SWIR1) | 水域 |

: 算出した分光指数（GREEN・RED・NIR・SWIR1 は Landsat 8/9 のバンド 3・4・5・6） {#tbl:spectral_indices}

NDBI・NDWI・MNDWI は，それぞれ Zha ら (2003)，McFeeters (1996)，Xu (2006) が提案した指数である[要出典]．NDVI と NDWI はどちらも NIR を逆の符号で含むため構造的に強く負に相関し，MNDWI は NIR を含まない．どの指数を説明変数に用いるかは 3.3.3 項で述べる．
