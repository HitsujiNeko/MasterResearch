# 不透水面率データの調査・評価

**最終更新**: 2026-08-06  
**関連ドキュメント**: [available_gis_data.md](../available_gis_data.md), [research_guide.md](../research_guide.md), [calc_urban_params_guide.md](../../02_methods/calc_urban_params_guide.md), [gis_data_population.md](gis_data_population.md)  
**前提知識**: RQ1-RQ3の理解、都市構造パラメータの定義（NDBIとの違い）

---

## 1. 調査目的

本研究では衛星由来指標としてNDBI（市街化・不透水面の代理指標）を既に算出しているが、これは連続値の代理指標であり、専用アルゴリズムで検証された「不透水面率（グリッド内の不透水面面積割合）」プロダクトとは異なる。本資料では、不透水面率を直接算出したオープンソースデータ候補を調査する。

### 1.1 「不透水面（impervious surface）」と「建物量（built-up）」の違いに注意

候補データの中には、「不透水面（道路・駐車場・広場等を含む人工被覆全般）」を測定するものと、「建物量（built-up、建物の屋根・フットプリントのみ）」を測定するものが混在する。都市の地表面温度（LST）に対しては、建物か否かによらず人工被覆全般の熱的性質が影響するため、本研究の目的には「不透水面」を測定するデータの方がより直接的に対応する。この違いは評価表・推奨方針で明記する。

Hanoi ROIでの実データは未取得である。採否は [urban_structure_parameters.md](../urban_structure_parameters.md) を正本とし、本資料では扱わない。

---

## 2. 候補データ比較表

| 項目 | World Settlement Footprint Imperviousness (WSF-SI) | GISA-10m | GAIA | GHS-BUILT-S | GMIS |
|---|---|---|---|---|---|
| 測定対象 | 不透水面率（PIS: Percent Impervious Surface） | 不透水面（ISA: Impervious Surface Area） | 不透水面（人工不透水域） | **建物量**（built-up surface fraction、不透水面とは概念が異なる） | 不透水面（人工不透水域の割合） |
| 提供機関 | DLR（ドイツ航空宇宙センター） | 研究グループ（Huang et al.） | 清華大学（Gong et al.） | European Commission JRC | NASA SEDAC / CIESIN |
| 空間解像度 | 10m | 10m | 30m | 10m | 30m/250m/1km |
| データ時期 | 2016年7月〜現在、半期ごと更新 | 単一〜数エポック（Sentinel光学+SAR、2015年代を中心とした期間） | 1985〜2018年（年次） | 1975〜2030年（5年おき） | 2010年（単一時点、静的） |
| 更新頻度 | 半期ごと、継続更新 | 更新未確認（論文公開時点が最新の可能性） | 生産終了（2018年が最新） | 5年おき | 更新なし（2010年のみ） |
| ベトナム/ハノイ カバレッジ | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット | ✅ 全球データセット（やや古い） |
| 精度（論文記載） | 未確認 | 総合精度86%以上 | 総合精度90%以上 | 未確認（学習にOSM/Microsoft/Facebook建物データを使用） | 未確認 |
| ライセンス | CC BY 4.0 | CC BY 4.0（Zenodo標準ライセンスと推定、要確認） | 不明瞭（「無償ダウンロード」の記載はあるが明示的なライセンス文言が確認できず） | 完全オープン（JRC無償公開） | CC BY 4.0（SEDAC標準） |
| 取得方法（スクリプト可否） | ✅ Copernicus/DLRポータル経由 | ✅ Zenodo直接ダウンロード | △ Tsinghua大学ポータル（`data.ess.tsinghua.edu.cn`）またはGEE経由、ライセンス確認が必要 | ✅ JRCポータル/GEE経由 | ✅ NASA SEDAC経由 |

---

## 3. 候補データ詳細

### 3.1 World Settlement Footprint Imperviousness (WSF-SI)

- **提供機関**: DLR（ドイツ航空宇宙センター）
- **データソース**: Sentinel-1（SAR）+ Sentinel-2（光学）
- **提供時期**: 2016年7月〜現在、半期（biannual）ごとに更新される継続的なデータセット。
- **利点**: 「不透水面率（Percent Impervious Surface）」を直接測定する目的で設計されており、本研究の目的と概念的に最も一致する。継続更新のため本研究のLandsat観測期間（2023年前後）に対応する時点を選べる。
- **配布形式**: World Settlement Footprint Platform、Copernicus LAC Platform経由

### 3.2 GISA-10m（Global Impervious Surface Area, 10m）

- **提供機関**: 研究グループ（Huang et al., 2022, ESSD）
- **データソース**: Sentinel光学・SAR画像（270万シーン以上）をGoogle Earth Engine上で解析
- **精度**: 総合精度86%以上
- **配布形式**: Zenodo（DOI: 10.5281/zenodo.5791855）、GEEコミュニティカタログ
- **懸念点**: 継続更新されているかが未確認（論文公開時点のエポックが最新の可能性がある）。

### 3.3 GAIA（Global Artificial Impervious Area）

- **提供機関**: 清華大学（Gong et al., 2020）
- **データソース**: 30m解像度Landsat時系列（GEE上で処理）
- **提供時期**: 1985〜2018年、年次
- **精度**: 総合精度90%以上（3,500検証サンプル）
- **懸念点**: 配布ポータル（`data.ess.tsinghua.edu.cn`）で「無償ダウンロード」との記載は確認できたが、明示的なライセンス文言（CC BY等）が検索結果からは確認できなかった。採用する場合はポータルで直接ライセンス条項を確認する必要がある。長期時系列（1985年以降）を活かした経年変化分析に向く。

### 3.4 GHS-BUILT-S（参考: 建物量データ、不透水面とは別概念）

- **提供機関**: European Commission JRC
- **測定対象**: 建物量（built-up surface fraction）。不透水面全般ではなく建物の屋根・フットプリント面積の割合を測定する。
- **解像度**: 10m
- **学習データ**: OSM・Microsoft・Facebookの建物デリニエーションを学習データに使用
- **位置づけ**: [gis_data_population.md](gis_data_population.md) で調査したGHS-POPと同一フレームワーク（GHSL）のデータであり、人口密度との整合性を取りやすい。ただし「不透水面率」としては、道路・駐車場等の非建物不透水面を捉えないため、本カテゴリの主要候補としては不採用とし、建物被覆率（`BUILD_COV`）算出の補助候補として扱う。

### 3.5 GMIS（Global Man-made Impervious Surface, NASA/SEDAC）

- **提供機関**: NASA SEDAC / CIESIN
- **提供時期**: 2010年（単一時点、Global Land Survey Landsatデータから算出）
- **懸念点**: 2010年時点の静的データであり、本研究の分析対象期間（2023年前後）との時間差が大きい。より新しい年次時系列データ（WSF-SI, GISA-10m, GAIA）が存在するため、優先度は低い。

---

## 4. 推奨方針

- **主候補**: `World Settlement Footprint Imperviousness`。「不透水面率」を直接測定する目的のデータであり、継続的に更新（半期ごと）されているため、本研究のLandsat観測期間に対応する時点を選べる。ライセンスもCC BY 4.0で明確。
- **比較候補**: `GISA-10m`。解像度・精度ともに高く、WSF-SIとのクロスチェックに使える。
- **経年変化分析用の候補**: `GAIA`。1985年以降の長期年次時系列を持つため、都市化の経年トレンドを扱う分析拡張に備えられる。ただし採用時はポータルでライセンス条項を必ず確認する。
- **補助候補（建物量の観点）**: `GHS-BUILT-S`。不透水面率の主要候補としては採用しないが、人口密度（GHS-POP）と同一フレームワークのため、建物系パラメータとの整合性確認に使える。
- **不採用**: `GMIS`。2010年の単一時点データであり、本研究の分析対象期間との時間差が大きい。
- `World Settlement Footprint Imperviousness`と`GISA-10m`はPythonスクリプト経由（DLRポータル/Zenodo直接DL）で取得可能なため、**取得スクリプト作成タスクとして別Issueを起票**する（優先度はユーザーに確認の上で起票）。

---

## 5. 注意点

- 「不透水面（impervious surface）」と「建物量（built-up）」は異なる概念であり、候補データがどちらを測定しているか確認せずに混同しないよう注意する（Section 1.1参照）。
- GAIAのライセンス条項は本資料執筆時点で確認できなかったため、取得スクリプト作成前にポータルで直接確認し、CC BY等の帰属表示要件を満たせるか確認する。
- WSF-SIとGISA-10mはいずれもSentinel由来（10m）であり、本研究の解析グリッド（30m）への変換（ダウンスケール集計）が必要になる。
- いずれのデータセットも実際のHanoi ROIでの取得・値域確認は未実施。取得スクリプト作成時に確認する。

---

## 6. 参考ソース

- World Settlement Footprint: <https://worldsettlementfootprint.com/>
- World Settlement Footprint Imperviousness仕様: <https://docs.copernicuslac.terradue.com/services/exposure/wsf-si-layer-specs/>
- GISA-10m論文（Huang et al., 2022, ESSD）: <https://essd.copernicus.org/articles/14/3649/2022/>
- GISA-10m（Zenodo）: <https://zenodo.org/records/6991620>
- GAIAデータポータル: <http://data.ess.tsinghua.edu.cn/gaia.html>
- GAIA GEEカタログ: <https://developers.google.com/earth-engine/datasets/catalog/Tsinghua_FROM-GLC_GAIA_v10>
- GHS-BUILT-S: <https://human-settlement.emergency.copernicus.eu/ghs_buS2023.php>
- GMIS（NASA SEDAC）: <https://sedac.ciesin.columbia.edu/data/set/ulandsat-gmis-v1>
