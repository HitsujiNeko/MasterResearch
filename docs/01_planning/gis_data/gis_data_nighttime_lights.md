# 夜間光データの調査・評価

**最終更新**: 2026-08-20  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義

---

## 1. 調査目的

`research_guide.md`では夜間光強度（VIIRS等）が「人口・人間活動指標」の追加候補として言及されている。また先行研究S8（Lin et al., 2024, 中国・武漢）では夜間光データとして`Luojia 1-01`を利用しており、夜間光は人口密度・経済活動の代理指標として都市構造パラメータに組み込まれる例がある。本資料ではオープンソースの夜間光データ候補を調査する。

Hanoi ROIでの実データ取得結果は5章に記載する。説明変数としての採否は [urban_structure_parameters.md](../urban_structure_parameters.md) を正本とし、本資料では扱わない。

なお、Jilin-1（92cm解像度、中国の商用衛星コンステレーション）も調査したが、商用データ（有料）であるため本調査の対象外とする（有料データは対象外とする方針のため）。

---

## 2. 候補データ比較表

| 項目 | VIIRS DNB（NOAA/NCEI EOG） | NASA Black Marble (VNP46A) | NPP-VIIRS-like（Chen et al.） | Harmonized Global NTL（Li et al.） | DMSP-OLS | Luojia 1-01 |
|---|---|---|---|---|---|---|
| センサー | Suomi NPP / NOAA-20 VIIRS DNB | 同左（高次処理版） | DMSP-OLS + VIIRSのクロスセンサー較正による疑似時系列 | 同左（別手法によるDMSP/VIIRS調和処理） | DMSP衛星 OLS | 武漢大学の専用夜間光衛星 |
| 空間解像度 | 約500m（15 arc-sec） | 約500m | 約500m（15 arc-sec） | 約1km（30 arc-sec、DMSP解像度に統一） | 約1km、市街地で飽和しやすい | **130m（ただし本リポジトリのS8構造化要約では30mと記録されており要検証、3.6節参照）** |
| データ時期 | 2012年〜現在 | 2012年〜現在 | 1992〜2023年（単一の一貫した時系列） | 1992〜2021年（単一の一貫した時系列） | 1992〜2013年（生産終了） | 2018年打ち上げ、単一ミッション期間のみ |
| 更新頻度 | 月次・年次、継続更新 | 日次・月次・年次、継続更新 | 年次、データセットとして順次拡張更新 | 年次、拡張版あり | 生産終了（更新なし） | 継続更新なし |
| 主な用途 | 特定年の現況把握に最適 | 特定年の現況把握（高品質版） | **長期トレンド分析**（DMSP時代とVIIRS時代を接続した一貫時系列） | 長期トレンド分析（同上、別手法） | 現行データなし（過去のみ） | S8の前例参照用 |
| ライセンス | パブリックドメイン | NASAオープンサイエンスポリシー | CC BY 4.0 | CC BY 4.0 | パブリックドメイン/CC BY 4.0 | 無償公開（ライセンス文言未確認） |
| 取得方法（スクリプト可否） | ✅ NOAA EOG/GEE経由 | ✅ NASA LAADS DAAC経由 | ✅ Harvard Dataverse/GEE経由 | ✅ Figshare/GEE経由 | ✅ GEE経由（現行データではない） | △ 中国側ポータル、スクリプト化要検証 |

---

## 3. 候補データ詳細

### 3.1 VIIRS DNB（NOAA/NCEI Earth Observation Group）

- **提供機関**: NOAA/NCEI（処理は Colorado School of Mines の Earth Observation Group）
- **データソース**: Suomi NPP衛星のVIIRS Day/Night Band（DNB）。現地時間午前1時ごろの通過軌道。
- **提供時期**: 2012年〜現在。月次コンポジット（雲なし平均放射輝度）を積み上げて年次コンポジットを作成。
- **配布形式**: NOAA EOGポータル（<https://eogdata.mines.edu/products/vnl/>）、GEEカタログ
  - **GEEのアセットIDは `NOAA/VIIRS/DNB/ANNUAL_V22`**（2022-2025年）／`NOAA/VIIRS/DNB/ANNUAL_V21`（2013-2021年）。カタログページのURLに現れる `NOAA_VIIRS_DNB_ANNUAL_V22` は**ページのスラッグであってアセットIDではない**。`NOAA/VIIRS/DNB_ANNUAL_V22`（`DNB`の後がアンダースコア）を指定すると `not found` になる（2026-07-27 実行確認）
- **利点**: 継続的に更新される現行データセットであり、本研究のLandsat観測期間（2023年前後）と対応する年次コンポジットを選べる。取得実績・研究利用例が最も豊富。

### 3.2 NASA Black Marble（VNP46A シリーズ）

- **提供機関**: NASA（VIIRS Land Team）
- **データソース**: VIIRS DNBと同じセンサーだが、月光・BRDF（双方向反射率）補正を加えた高次プロダクト。日次（VNP46A1/A2）、月次（VNP46A3）、年次（VNP46A4）が提供される。
- **提供時期**: 2012年〜現在、継続更新。
- **配布形式**: LAADS DAAC の ArchiveSet 5200（Black Marble Collection 2.0）。HDF-EOS5（`.h5`）、10°×10°タイル単位。h28v06の2023年版は**実測 約120MB**（製品ページ記載の「92MB」より大きい）。
- **利点**: 月光の影響やセンサー角度の影響を補正済みであるため、VIIRS DNBの生データより品質が高い可能性がある。
- **懸念点**（2026-07-28 実行確認）:
  - **年次プロダクト`VNP46A4`はGEEに存在しない**。GEEで利用できるのは日次の`NASA/VIIRS/002/VNP46A2`（BRDF・月光補正済み、2012-01-19〜、7バンド）と`NOAA/VIIRS/001/VNP46A1`（補正前の生ラジアンス）のみ。年次を使うにはLAADS DAACから直接取得する必要がある
  - **Earthdataアカウントの Bearer トークンが必須**。ファイル一覧APIの時点でEarthdataのOAuthへリダイレクト（HTTP 302）される
  - **データ利用許諾への同意が別途必要**。未同意だと401ではなく`/profiles/licenses/...`へ303され、リダイレクトを辿った先のEarthdata OAuthで401になるため、原因が分かりにくい。同意はブラウザでEarthdataにログインした状態で当該ページを開いて行う
  - **ダウンロードURLは自前で組み立てられない**。公開パス（`/archive/allData/...`）はライセンス同意ページへ303されるため、一覧APIが返す`downloadsLink`（`/api/v2/content/archives/allData/...`）を使う必要がある
  - HDF-EOS5形式のため読み込みに`h5py`が要る（本プロジェクトの実行環境のGDALはHDF5ドライバなしでビルドされている）

### 3.3 NPP-VIIRS-like nighttime light dataset（Chen et al.）

- **正式名称**: An extended time series of global NPP-VIIRS-like nighttime light data
- **提供機関**: 研究グループ（Chen et al.、深層学習/クロスセンサー較正による疑似データ生成）
- **手法**: DMSP-OLS（2000〜2012年）とNPP-VIIRS（2013年〜）を統一的な較正モデルでつなぎ、単一の一貫した年次時系列（1992〜2023年）として再構成したデータセット。
- **配布形式**: Harvard Dataverse（DOI: 10.7910/DVN/YGIVCD）、GEEコミュニティカタログ
- **位置づけ**: 特定年のスナップショットではなく、**長期の都市化トレンドを一貫した指標で追う**ことを目的としたデータセット。本研究が単年（もしくは数時点）のLST分析であれば必須ではないが、夜間光の経年変化を都市構造の変遷として扱う場合に有用。

### 3.4 Harmonized Global Nighttime Light dataset（Li et al.）

- **提供機関**: 研究グループ（Li, Zhou, Zhao, Zhao, 2020, Scientific Data）
- **手法**: DMSPとVIIRSの相互較正により調和させた1992〜2018年（拡張版は2021年まで）の時系列データセット。NPP-VIIRS-likeと類似の目的だが、較正手法が異なる。
- **配布形式**: Figshare（DOI: 10.6084/m9.figshare.9828827.v2）、GEE（`projects/sat-io/open-datasets/Harmonized_NTL/`）
- **位置づけ**: 3.3のNPP-VIIRS-likeと同様、長期トレンド分析向け。解像度はDMSP解像度（約1km）に統一されているため、単年の空間パターン分析にはVIIRS DNBやBlack Marbleの方が適する。

### 3.5 DMSP-OLS

- **提供機関**: NOAA/NGDC（旧プロダクト）
- **提供時期**: 1992〜2013年（2014年に生産終了）。F18衛星の軌道劣化により後継プロダクトなし。
- **懸念点**: 解像度が粗く（約1km）、市街地中心部で放射輝度が飽和しやすいという既知の欠点がある。本研究の分析対象期間（2023年前後）のデータが存在しないため、**単独データとしては不採用**。

### 3.6 Luojia 1-01

- **提供機関**: 武漢大学 + Chang Guang Satellite Technology
- **データソース**: 専用夜間光観測衛星（2018年6月打ち上げ）
- **解像度**: Web調査（Chen et al., 2019, IEEE論文）では130m（衛星ネイティブ仕様）とされる一方、本リポジトリの先行研究構造化要約 [S8_Lin_2024.md](../../04_archive/02_structured_summaries/S8_Lin_2024.md) では、S8論文（Lin et al., 2024, 武漢）が実際に使用したLuojia 1-01データの解像度を30mと記録している。両者は同一データセットの解像度として10倍以上食い違っており、ネイティブ仕様と論文側が使用した再加工済みプロダクトの違いによるものか、いずれかの記録誤りかは本資料の調査だけでは切り分けられない。採用を検討する場合は、Lin et al. (2024) 原著論文で使用解像度を再確認すること。
- **本研究との関連**: 先行研究S8（Lin et al., 2024, 武漢）で夜間光データとして採用されている前例。ただし上記の解像度不一致が未解消のため、前例としての参照は解像度確認後に行う。
- **懸念点**: 単一ミッション期間のみのデータであり、本研究の分析対象期間（2023年前後）に対応する観測があるか未確認。配布は中国側ポータル経由で、Pythonスクリプトから機械的に取得できるかは要検証。上記の解像度不一致も未解消。

---

## 4. 推奨方針

- **主候補**: `VIIRS DNB`（NOAA/NCEI EOG）。現行データセットとして継続更新されており、本研究のLandsat観測期間に対応する年次コンポジットを取得できる。取得方法が確立されており、スクリプト取得の実現性が最も高い。
- **代替候補（品質重視の場合）**: `NASA Black Marble`。月光・BRDF補正済みで品質が高いが、前処理がやや複雑になる可能性がある。
- **将来の拡張候補（経年変化を扱う場合）**: `NPP-VIIRS-like`または`Harmonized Global NTL`。単年分析では不要だが、都市化の経年トレンドを夜間光で追う分析に発展させる場合の候補として記録しておく。
- **参考（先行研究の前例）**: `Luojia 1-01`はS8で採用された前例だが、単一ミッション期間のデータであり本研究の観測期間との対応、スクリプトによる自動取得の可否、および解像度の記録不一致（3.6節参照）がいずれも未確認のため、優先度は低い。
- **不採用**: `DMSP-OLS`単独（2013年で更新終了、現行分析には使えない）。`Jilin-1`（商用データのため対象外）。
- `VIIRS DNB`と`NASA Black Marble`はPythonスクリプト経由（GEE / NASA LAADS DAAC）で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（優先度はユーザーに確認の上で起票）。

### 4.1 入力データセットの確定（2026-08-20）

都市構造パラメータ P10 夜間光強度の入力を次のとおり確定した。

| パラメータセット | 入力ファイル | バンド | 位置づけ |
|---|---|---|---|
| `ntl_viirs2023` | `viirs_dnb_hanoi_2023.tif` | 1（`avg_radiance`） | 主候補 |
| `ntl_bm2023` | `black_marble_vnp46a4_hanoi_2023.tif` | 1（`ntl_near_nadir`） | 副候補 |

上記の推奨方針をそのまま採用した。5.3節の比較で両者の主バンド同士は強く相関しており（Pearson r = 0.976、ただしVIIRSグリッド上で重なる16,579画素での値）、**同一概念の差し替え候補**として扱える。したがって人口密度と異なり、両者は同じ列名（`NTL_MEAN` / `NTL_VALID_RATIO`）を共有し、感度分析は結合先テーブルの差し替えだけで済む。

**band 1（主バンド）を採る理由**: VIIRS DNB の band 2（`avg_radiance_masked`）は背景と判定された画素の扱いが配布データ側に依存し、本ファイル・本ROIでは **0 として現れた**（5.1節）。0で現れる限り「電力由来の光が検出されなかった」ことと「観測できなかった」ことの区別が値の上で失われるため、背景除去前の主バンドを用いる。Black Marble も比較を5.3節と揃えるため主バンド（近直下視合成）を採る。

**算出経路**: 放射輝度は面積に比例しない**強度量**であるため、人口密度と違い面積正規化を行わず、セル平均をそのまま出力する（単位は nW·cm⁻²·sr⁻¹）。集約は標高・人口と共通の集約関数を用いる。

**RQ2は割り当てない**: ハノイの緯度での画素実寸は約 433.3m × 461.3m（約 0.200 km²）で、最も粗い300mセルでも0.450画素/セルにとどまる。全解析スケールで実質的な内挿になるため、§1.4 の除外条件①に該当する。判定基準と実測値は [urban_structure_parameters.md](../urban_structure_parameters.md) §1.4・§2.1 を正本とする。

---

## 5. Hanoi ROI での取得結果

取得スクリプト: `src/preprocessing/fetch_viirs_dnb_hanoi.py`（VIIRS DNB）/ `src/preprocessing/fetch_black_marble_hanoi.py`（Black Marble）
比較スクリプト: `src/analysis/compare_nighttime_lights_viirs_blackmarble.py`

**QGISスタイル**: `qgis/styles/nighttime_lights_radiance.qml`（両データセット共有。「同じ色＝同じ放射輝度」で直接比較できるよう、9区分の分類を共通化している）

**スクリーンショット**:

- `images/gis_data/nighttime_lights/nighttime_lights_viirs_dnb_hanoi_2023.png`
- `images/gis_data/nighttime_lights/nighttime_lights_black_marble_hanoi_2023.png`

いずれも上記の共有スタイルを適用しており、凡例の色と値域は2枚で一致する。最上位区分（> 100 nW·cm⁻²·sr⁻¹）は VIIRS DNB のROI内には該当画素が無いが、データセット間で色の意味を揃えるため意図的に残している。

### 5.1 VIIRS DNB 年次コンポジット V2.2（2023年）

取得日: 2026-07-27。アセット `NOAA/VIIRS/DNB/ANNUAL_V22`、`system:index = 20230101`。

**本研究のLandsat観測年（2023年）の年次コンポジットが直接取得できた**（人口データ（WorldPop）のような提供年の不足による時間差は生じない）。

| 項目 | 結果 |
|---|---|
| 出力CRS | EPSG:4326 |
| 解像度 | 0.0041666667°（約463.83m、15 arc-sec） |
| 出力サイズ | 177 × 198 画素（4バンド）、ROI内 16,796 画素 |
| 有効画素率 | **1.0000**（全バンド。ROI内に欠測なし） |
| ROI被覆 | `covers_requested_area = True`（要求範囲を完全に包含） |

バンド別の値域（ROI内有効画素、単位は放射輝度バンドが nW·cm⁻²·sr⁻¹）:

| バンド | 由来 | min | median | p95 | p99 | max | mean |
|---|---|---|---|---|---|---|---|
| `avg_radiance` | `average` | 0.506 | 2.717 | 21.348 | 33.644 | 96.100 | 5.407 |
| `avg_radiance_masked` | `average_masked` | 0.000 | 2.714 | 21.348 | 33.644 | 96.100 | 5.307 |
| `cf_cvg` | `cf_cvg` | 51 | 74 | 85 | 91 | 96 | 73.29 |
| `max_radiance` | `maximum` | 0.647 | 4.387 | 30.825 | 51.719 | 230.595 | 8.371 |

**カバレッジ**: ROI全域に欠測なし。雲なし観測数（`cf_cvg`）はROI内で最小51回・中央値74回あり、年次合成の基礎となる観測は十分に確保されている。

**背景除去バンドの挙動**: `average_masked` はROI内で欠測（nodata）にはならず、背景と判定された画素が **0** に置き換わる形で現れた（有効画素数は `average` と同じ16,796、最小値のみ 0.506 → 0.000 に変化）。したがって本データセットでは、`average_masked` の低値域は「データ無し」ではなく「電力由来の光が検出されなかった」と読む。

**飽和状況**: **ROI内に飽和は認められない**。

| バンド | p99/max | 最大値と同値の画素数 | 最大値の1%以内の画素数（割合） |
|---|---|---|---|
| `avg_radiance` | 0.350 | 1 | 2（0.01%） |
| `max_radiance` | 0.224 | 1 | 1（0.01%） |

上位分位点（p99）が最大値の1/3〜1/4程度にとどまり、最大値は単独画素にしか現れない。DMSP-OLSで問題となる「都市中心部で値が上限に張り付き、密集市街地内の空間パターンが識別できない」状態には該当しない。ハノイ都心部でも階調が保たれており、都市構造パラメータの説明変数として値の分解能を利用できる。

### 5.2 NASA Black Marble VNP46A4（2023年）

取得日: 2026-07-29。LAADS DAAC ArchiveSet 5200、タイル `h28v06`（`VNP46A4.A2023001.h28v06.002.2025162082259.h5`、119.8 MB）。

| 項目 | 結果 |
|---|---|
| 出力CRS | EPSG:4326 |
| 解像度 | 0.004166666666666667°（＝1/240、15 arc-sec。タイルは2400×2400） |
| 出力サイズ | 176 × 198 画素（4バンド）、ROI内 16,797 画素 |
| 有効画素率 | **1.0000**（全バンド。ROI内に欠測なし） |
| ROI被覆 | `covers_requested_area = True` |
| ジオリファレンス | タイル番号由来の範囲とファイルの境界座標属性（100–110E / 20–30N）が一致 |

バンド別の値域（ROI内有効画素、単位は放射輝度バンドが nW·cm⁻²·sr⁻¹）:

| バンド | 由来SDS | min | median | p95 | p99 | max | mean |
|---|---|---|---|---|---|---|---|
| `ntl_near_nadir` | `NearNadir_Composite_Snow_Free` | 0.000 | 3.257 | 27.023 | 45.122 | 213.980 | 6.712 |
| `ntl_all_angle` | `AllAngle_Composite_Snow_Free` | 0.531 | 3.963 | 28.251 | 43.887 | 124.377 | 7.384 |
| `near_nadir_num` | `..._Num` | 2 | 13 | 19 | 22 | 31 | 13.79 |
| `near_nadir_std` | `..._Std` | 0.017 | 1.028 | 8.591 | 16.884 | 161.150 | 2.264 |

**飽和状況**: **ROI内に飽和は認められない**（`ntl_near_nadir` の p99/max = 0.211、`ntl_all_angle` は 0.353。いずれも最大値と同値の画素は1つのみ）。VIIRS DNBと同じ結論である。

**観測数**: 近直下視の合成に用いた観測数は中央値13回・最小2回。VIIRS DNB年次コンポジットの雲なし観測数（中央値74回）の約6分の1だが、これは視野角0–20°に限定しているためで、`ntl_all_angle` は全視野角を使うぶん観測数が多い。

#### 実ファイルで判明した内部構造（2026-07-29 確認）

事前の想定と食い違った点を記録する。文献やプロダクト名からの推測は当てにならなかった。

| 項目 | 事前の想定 | 実際 |
|---|---|---|
| SDSのグループパス | `HDFEOS/GRIDS/VNP_Grid_DNB/Data Fields` | **`HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields`** |
| オフセット属性名 | `add_offset`（CF規約） | **`offset`** |
| データ型・スケール | uint16 × `scale_factor` 0.1 | **float32 × 1.0**（既に物理値）、`_FillValue = -999.9` |
| SDS名・境界座標属性・タイル解決 | — | 想定どおり |

- 合成バンド（`*_Composite_Snow_Free` / `_Std`）は float32 で `_FillValue = -999.9`、`_Num` は uint16 で 65535、`_Quality` は uint8 で 255
- ルート属性に `HorizontalTileNumber` / `VerticalTileNumber` があり、タイル番号の突き合わせに使える
- 単位の表記はファイル上 `nWatts/(cm^2 sr)`

#### VIIRS DNBとの比較にあたっての注意

両者はグリッド原点が**半画素ずれる**（VIIRS DNB: `-180.00208333335`、Black Marble: タイル境界が整数度）。解像度は同じ15 arc-secだが、画素単位で突き合わせるには再投影が要る。

### 5.3 VIIRS DNB と Black Marble の比較（2023年）

比較スクリプト: `src/analysis/compare_nighttime_lights_viirs_blackmarble.py`。VIIRS DNB を基準グリッドとし、Black Marble を再投影して重ねる。比較は主バンド同士（`avg_radiance` と `ntl_near_nadir`、いずれも nW·cm⁻²·sr⁻¹）。

**グリッドずれの実測**: 原点差は経度方向 0.4995 画素・緯度方向 −0.5001 画素で、**半画素ずれが実測で裏付けられた**（経度差 0.00208105°）。

#### 一致度（載せ替え方法別）

| 方法 | 比較画素数 | Pearson r | Spearman ρ | 平均バイアス | 中央値バイアス | RMSE | MAE |
|---|---|---|---|---|---|---|---|
| **双一次内挿で再投影（採用）** | 16,579 | **0.9762** | **0.9831** | +1.315 | +0.464 | 3.114 | 1.487 |
| 最近傍で再投影 | 16,579 | 0.9362 | 0.9532 | +1.316 | +0.290 | 4.099 | 1.807 |
| 再投影なし（索引対応） | 16,575 | 0.9255 | 0.9497 | +1.337 | +0.297 | 4.279 | 1.895 |

バイアスは Black Marble − VIIRS DNB。**再投影方法を変えても「強い正の相関」「Black Marble のほうが明るい」という結論は変わらない**が、半画素ずれを補正しない索引対応では RMSE が約37%悪化する（3.114 → 4.279）ため、画素単位の突き合わせには再投影が必要である。双一次内挿が最良なのは、半画素ずれを内挿で吸収できるためと解釈できる。

**有効カバレッジの注意**: 比較できたのは16,579画素で、VIIRS グリッド上のROI内画素（16,796）のうち **217画素（1.3%）はROI外縁で除外**されている。Black Marble 側がROIのbboxでクリップ済みのため、再投影時に外縁で有効値を作れないことによる。**比較統計はROI全体ではなくこの16,579画素に対するもの**である。

#### 分位点対応

| 分位点 | VIIRS DNB | Black Marble |
|---|---|---|
| p50 | 2.727 | 3.327 |
| p90 | 13.226 | 16.741 |
| p95 | 21.428 | 26.801 |
| p99 | 33.781 | 44.241 |
| max | 96.100 | 150.413 |

Black Marble が**全分位点で系統的に高い**。差は上位ほど大きく、最大値では約1.57倍になる。これはセンサー差ではなく、Black Marble が月光・大気・BRDF補正を施し視野角を近直下視に限定していることによる処理の違いと解釈する。どちらが「正しい」かを意味しない。

> **この表の Black Marble 列は再投影（双一次内挿）後の値**であり、5.2節の生データの値とは一致しない（例: max は再投影後 150.413 に対し生データ 213.980）。内挿は上位の値を削るため、生データ同士では最大値の比は約2.23倍になる。**同一グリッド上で対にした値の比較**という目的にはこの表が正しく、**データセット自体の値域**を見るときは5.2節を参照する。

#### 飽和状況（都心・外縁の比較）

飽和はソースデータの性質のため、**両データセットとも自身のグリッドの生データ（再投影なし）で評価する**。再投影後の値で測ると内挿の平滑化が上位の値を削り、飽和指標が「飽和していない」方向へ歪む（Black Marble の ROI 全体の `p99/max` は生データ 0.211 に対し双一次内挿後 0.294 と上振れした）。

ゾーンは、**VIIRS DNB の ROI 内で放射輝度が上位1%に入る画素の重心（105.795, 21.075）＝最輝部の中心**からの距離の四分位で、都心側（下位25%）・外縁側（上位25%）に分けた。ROI の重心を基準にすると最輝部から約20km外れ、**ROI全体の最輝画素が都心側・外縁側のどちらにも入らなかった**ため、輝度側から都心を定めている。同じ距離閾値を両データセットへ適用し、ゾーンを地理的に揃えている。

| ゾーン | データセット | 画素数 | 中央値 | p99 | max | p99/max | p99−中央値 |
|---|---|---|---|---|---|---|---|
| 都心側 | VIIRS DNB | 4,199 | 9.783 | 44.493 | 96.100 | 0.463 | 34.710 |
| 都心側 | Black Marble | 4,202 | 12.084 | 59.359 | 213.980 | 0.277 | 47.276 |
| 外縁側 | VIIRS DNB | 4,199 | 1.430 | 5.588 | 11.023 | 0.507 | 4.158 |
| 外縁側 | Black Marble | 4,189 | 1.459 | 8.330 | 18.957 | 0.439 | 6.871 |

都心側ゾーンの max は両データセットともROI全体の最大値（96.100 / 213.980）と一致しており、**最輝部がゾーンに含まれている**ことが確認できる。

**両データセットとも都心側で飽和は認められない**。飽和していれば都心側で上位の値が最大値へ張り付き、`p99−中央値` が外縁側と比べて相対的に小さくなるはずだが、実際は都心側のほうが7〜8倍大きく、値の広がりはむしろ都心側で保たれている。`p99/max` も同一データセット内で都心側が外縁側より小さく（VIIRS DNB: 0.463 < 0.507、Black Marble: 0.277 < 0.439）、最大値と同値の画素はいずれのゾーン・データセットでも1画素のみである。ハノイ都心部の空間パターンは、どちらのデータセットでも階調として識別できる。

---

## 6. 注意点

- 夜間光データは都市中心部で値が飽和しやすく、密集市街地内での空間パターンの識別力が限られる可能性がある（DMSP-OLSで特に顕著、VIIRS DNBでも都市中心部では相対的に緩和されるが完全ではない）。
- VIIRS DNBの月次コンポジットには月明かり・雲・グレア等のノイズが含まれるため、複数月の中央値合成や品質フラグでのフィルタリングが必要になる場合がある。
- 長期トレンド用データセット（NPP-VIIRS-like, Harmonized Global NTL）は解像度がDMSP水準（約1km）に統一されているため、空間パターンの精緻な分析には向かない点に注意する。
- VIIRS DNB（5.1節）・Black Marble VNP46A4（5.2節）ともHanoi ROIでの取得・値域確認は実施済みで、両者とも飽和は認められなかった。両者の比較も実施済み（5.3節、Pearson r = 0.976）。それ以外のデータセットは未取得。
- VIIRS DNB年次コンポジットのグリッド原点は `-180.00208333335 / 75.00208333335` で、**整数度から半画素ずれる**。Black MarbleのタイルグリッドやLandsat由来のグリッドと画素単位で突き合わせる際は再投影が要る。

---

## 7. 参考ソース

- VIIRS Nighttime Light（NOAA/NCEI EOG）: <https://eogdata.mines.edu/products/vnl/>
- VIIRS DNB Annual Composites GEEカタログ: <https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_ANNUAL_V22>
- NASA Black Marble: <https://blackmarble.gsfc.nasa.gov/>
- NASA Black Marble Product（VIIRS Land Team）: <https://viirsland.gsfc.nasa.gov/Products/NASA/BlackMarble.html>
- NPP-VIIRS-like nighttime light dataset（Harvard Dataverse）: <https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/YGIVCD>
- NPP-VIIRS-like論文（2024, Scientific Data）: <https://www.nature.com/articles/s41597-024-04228-6>
- Harmonized Global Nighttime Light dataset論文（Li et al., 2020, Scientific Data）: <https://www.nature.com/articles/s41597-020-0510-y>
- DMSP Nighttime Lights（Earth Observation Group）: <https://eogdata.mines.edu/products/dmsp/>
- DMSP-OLS GEEカタログ: <https://developers.google.com/earth-engine/datasets/catalog/NOAA_DMSP-OLS_NIGHTTIME_LIGHTS>
- Luojia 1-01評価論文（Chen et al., 2019, IEEE）: <https://ieeexplore.ieee.org/document/8924611/>
- 先行研究S8（Lin et al., 2024）構造化要約: [S8_Lin_2024.md](../../04_archive/02_structured_summaries/S8_Lin_2024.md)
