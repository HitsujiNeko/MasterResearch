# 夜間光データの調査・評価

**最終更新**: 2026-07-28  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義

---

## 1. 調査目的

`research_guide.md`では夜間光強度（VIIRS等）が「人口・人間活動指標」の追加候補として言及されている。また先行研究S8（Lin et al., 2024, 中国・武漢）では夜間光データとして`Luojia 1-01`を利用しており、夜間光は人口密度・経済活動の代理指標として都市構造パラメータに組み込まれる例がある。本資料ではオープンソースの夜間光データ候補を調査する。

Hanoi ROIでの実データ取得結果は5章に記載する（採用可否は未判断）。

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

---

## 5. Hanoi ROI での取得結果

取得スクリプト: `src/preprocessing/fetch_viirs_dnb_hanoi.py`（VIIRS DNB）/ `src/preprocessing/fetch_black_marble_hanoi.py`（Black Marble）

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

取得スクリプトは実装済み。一覧API・タイル解決（`h28v06`）・`downloadsLink`の取得までは実データで確認済み。**ROIクリップまでの通し実行は未了**（本節は取得後に追記する）。

---

## 6. 注意点

- 夜間光データは都市中心部で値が飽和しやすく、密集市街地内での空間パターンの識別力が限られる可能性がある（DMSP-OLSで特に顕著、VIIRS DNBでも都市中心部では相対的に緩和されるが完全ではない）。
- VIIRS DNBの月次コンポジットには月明かり・雲・グレア等のノイズが含まれるため、複数月の中央値合成や品質フラグでのフィルタリングが必要になる場合がある。
- 長期トレンド用データセット（NPP-VIIRS-like, Harmonized Global NTL）は解像度がDMSP水準（約1km）に統一されているため、空間パターンの精緻な分析には向かない点に注意する。
- VIIRS DNBのHanoi ROIでの取得・値域確認は実施済み（5.1節）。飽和は認められなかった。Black Marbleは未実施（5.2節）。それ以外のデータセットは未取得。
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
