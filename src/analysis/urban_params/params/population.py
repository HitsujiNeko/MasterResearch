"""人口密度パラメータ（POP_DEN / POP_VALID_RATIO）算出モジュール。

公開人口グリッド（WorldPop / LandScan Global）の**密度バンド（人/km²）**を
coarseグリッドへ平均集約し、100で割ってセル平均人口密度（人/ha）と
セル内の有効画素率（0-1）を求める。集約は標高・LSTと共通の ``params.raster``
の集約関数を用いる。

**単位換算に ``grid.cell_area_ha()`` を使わない**のは、密度バンドが取得時点で
行ごとにWGS84楕円体上の実面積を用いて算出されているためである
（``gis_data_population.md`` 6.2節）。平面セル面積で割り直すと、この実面積に
基づく値を近似で上書きすることになる。1 km² = 100 ha の定数換算で足りる。

人口カウントバンド（band 1）を合計集約する経路は採らない。カウントは合計保存量で
あり合計集約を要するが、本モジュールが集約するのは合計保存量ではない密度であり、
平均集約が妥当である。本研究がセル単位の密度のみを説明変数に使うため、人口総数を
保存する利点も活かせない。

解釈上の前提:
    - **WorldPopは居住人口、LandScanは実効人口**（昼間の人口移動を考慮）であり、
      概念が異なる。集計レベルでは一致するが、セル単位では都心でLandScanが大きく
      上回る（``gis_data_population.md`` 6.5節）。同一の列名で出力されるため、
      どのデータセット由来かはテーブル名（``pop_worldpop2020`` 等）で区別する。
    - **WorldPopのベトナムは2020年までしか提供されない。** Landsat観測年（2023年）
      との3年差があるため、WorldPopとLandScan 2023の説明力の差は「人口概念の差」と
      「観測年の差」が混ざる。年差単独の寄与はLandScan 2020と2023の比較で分離する。
    - **WorldPopはROI内の2.77%が無効画素**で、その83%は水域である（西湖・紅河本流）。
      ただし厳密な水域マスクではなく、大規模水域に対応するものである。LandScanは
      水域を含めて全画素に値を持つ（有効画素率1.0）。
    - ``POP_DEN`` はセル内の**有効画素のみ**の平均である。水域が大半を占めるセルでも
      陸地部分の密度がそのまま入り ``NaN`` にはならないため、セルの信頼度は
      ``POP_VALID_RATIO`` で判断する。セル全体を母数とする密度が必要な場合は
      ``POP_DEN × POP_VALID_RATIO`` で得られる。
    - ``scale`` とデータセット解像度の関係に注意する。公称解像度は緯線上の度数から
      換算した値であり、ハノイの緯度（約21.0°N）での画素実寸は WorldPop が約
      86.7m × 92.3m（約 7,995 m²）、LandScan が約 866.6m × 922.6m（約 0.80 km²）である。
      1セルあたりの画素数に直すと、WorldPop は 30m で 0.11・90m で 1.01・300m で 11.3、
      LandScan は 300m でも 0.11 にとどまる。**セル内の複数画素を平均する「真の集約」に
      なるのは WorldPop の 300m だけ**であり、WorldPop の 90m は実質的なリサンプリング
      （``elevation.py`` の ``scale=30`` と同じ状況）、残りはいずれも内挿である。
      内挿では1画素の値が複数セルへ一様に配られ、セル間の変動が入力の解像度に由来
      しないため、RQ2のスケール間比較でこれらの値を過大解釈しない。
    - 値 ``0`` は「人口ゼロ」という実測値であり欠測ではない。欠測は ``NaN`` である。
"""

from __future__ import annotations

import numpy as np

from ..grid import BBox, GridSpec
from ..io import RasterResource
from .raster import aggregate_mean_and_valid_ratio, warn_if_band_description_unexpected

# 1 km² あたりのヘクタール数。人/km² をこれで**割る**と人/ha になる。
# 名前で換算の向きが読めるようにしているのは、単位を2桁誤っても密度としては
# 成立してしまい、出力値を眺めるだけでは誤りに気づけないためである。
HECTARES_PER_SQUARE_KM = 100.0

# 密度バンドのバンド説明に含まれるべき語。WorldPop・LandScanとも取得スクリプトが
# ``population_density_per_km2`` を付与しており、カウントバンド（``population_count``）
# を指した場合はこの語を含まないため取り違えを検知できる。
#
# 夜間光と違い**部分一致で照合する**。同じ語を含む紛らわしい兄弟バンドが無く、かつ
# 他の人口グリッド（GHS-POP等）を追加した際に説明の表記が違っても語が残れば通るためである。
DENSITY_BAND_KEYWORDS = ("density",)


def validate_resource(resource: RasterResource) -> None:
    """入力ラスタが密度バンドを指しているかを検証する。

    **``compute()`` ではなく入力解決の段階で呼ぶ。** バンド番号の取り違えは設定の
    誤りであり、他の入力検証と同じくすべてのタスク分をまとめて先に確かめたほうが、
    スケールごとの進捗出力に紛れない。同じファイルをスケールの数だけ開き直さずに
    済むという利点もある。呼び出しは ``run.py`` の ``build_param_tasks()`` が担う。

    カウントバンド（band 1）を指しても値は出るため、集約後の統計を見ても気づけない。

    Args:
        resource: 解決済みの人口ラスタ。
    """
    warn_if_band_description_unexpected(
        resource.path, resource.band_index, DENSITY_BAND_KEYWORDS, "人口"
    )


def compute(
    resource: RasterResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """人口密度パラメータを算出する。

    Args:
        resource: 人口ラスタ（未指定シナリオでは ``None``）。密度バンド（人/km²）を
            指す ``band_index`` を持つこと。カウントバンドを指すと単位が人/haに
            ならないが、バンドの取り違えは入力解決時の ``validate_resource()`` が
            検査する（本関数は値域の妥当性を検査しない）。
        bbox_analysis: 解析用CRS上の検索範囲。集約先の範囲は ``grid_spec`` が
            保持するため本関数では参照しないが、他パラメータモジュールと
            シグネチャを揃えるために受け取る。
        grid_spec: fine/coarseグリッドの仕様。coarseグリッドへ集約する。

    Returns:
        ``{"POP_DEN": array, "POP_VALID_RATIO": array}`` 形式の辞書。
        ``POP_DEN`` の単位は人/ha、``POP_VALID_RATIO`` はセル内の人口ラスタ
        有効画素率（0-1、ラスタ範囲外は ``0.0``）。
        ``resource`` が ``None`` の場合は空辞書を返す。

        **実際に出力される列名はデータソース接尾辞つきになる**（例:
        ``POP_DEN_LANDSCAN2023``）。付与は ``run.py`` の ``apply_column_suffix()``
        が担い、本モジュールはどのデータセットを処理しているかを知らない。
    """
    if resource is None:
        return {}

    # 都市とデータセットの取り違えや切り出し範囲の誤りでは、ファイルが存在するため
    # 入力解決（io.get_optional_raster_resource）を素通りし、全セルNaNの列が黙って
    # 出力される。列が残るぶん欠損に気づきにくいため、共通処理が原因を切り分けて警告する。
    columns = aggregate_mean_and_valid_ratio(
        resource.path,
        grid_spec,
        resource.band_index,
        "POP_DEN",
        "POP_VALID_RATIO",
        "人口",
    )

    # NaN（有効画素が1つも無いセル）は除算後もNaNのまま残る。
    columns["POP_DEN"] = (columns["POP_DEN"] / HECTARES_PER_SQUARE_KM).astype(np.float32)
    return columns
