"""夜間光強度パラメータ（NTL_MEAN / NTL_VALID_RATIO）算出モジュール。

夜間光ラスタ（VIIRS DNB 年次コンポジット / NASA Black Marble VNP46A4）の放射輝度
バンドをcoarseグリッドへ平均集約し、セル平均放射輝度（nW·cm⁻²·sr⁻¹）とセル内の
有効画素率（0-1）を求める。集約は標高・人口と共通の ``params.raster`` の集約関数を
用いる。

**放射輝度は面積に比例しない強度量であるため、単位換算を行わない。** 人口密度
（``population.py``）が /ha へ正規化するのは示量的な量を面積で割るためであり、
放射輝度にはその操作が当たらない。

解釈上の前提:
    - 参照するのは各データセットの**主バンド**である。VIIRS DNB は ``avg_radiance``
      （band 1）、Black Marble は ``ntl_near_nadir``（band 1、近直下視合成）を用いる。
    - **VIIRS DNB の band 2（``avg_radiance_masked``）は使わない。** 背景と判定された
      画素の扱いは配布データ側に依存し、0 で現れる場合とマスク（nodata）で現れる場合が
      ある。**本ファイル・本ROIでは 0 として現れた**（有効画素数は band 1 と同じ16,796で、
      最小値のみ 0.506 → 0.000 に変化）。0で現れる限り、「電力由来の光が検出されな
      かった」ことと「観測できなかった」ことの区別が値の上で失われる。別年・別地域を
      取得した場合はこの前提を再確認すること。
    - 値 ``0`` は実測値であり欠測ではない。欠測は ``NaN`` である。Black Marble の
      ``ntl_near_nadir`` は ROI 内の最小値が 0.000 であり、実際に0を含む。
    - **ROI内に飽和は認められない**（両データセットとも p99/max が 0.21〜0.35、最大値と
      同値の画素は1つのみ）。DMSP-OLS で問題となる「都心で値が上限に張り付き空間
      パターンが識別できない」状態には該当せず、都心部でも階調を説明変数に使える。
    - 両データセットは ROI 全域で有効画素率 1.0 であり、``NTL_VALID_RATIO`` は
      ほぼ定数列になる。それでも対で出すのは、``aggregate_mean_and_valid_ratio()``
      が2列を対で返すためであり、将来の入力差し替え時にカバレッジ低下を検知する
      手段にもなる。
    - **全解析スケール（30m・90m・300m）より粗い。** 公称は約464mだが、ハノイの緯度
      （約21.0°N）での画素実寸は約 433.3m × 461.3m（約 0.200 km²）である。1セルあたりの
      画素数は30mで0.005・90mで0.041・300mでも0.450にとどまり、**どのスケールでも
      集約ではなく内挿**になる。1画素の値が複数セルへ一様に配られ、セル間の変動が入力の
      解像度に由来しないため、RQ2のスケール間比較には用いない（RQ2未割当）。
    - 両データセットはグリッド原点が半画素ずれる（VIIRS DNB は整数度から
      ``-180.00208333335``、Black Marble はタイル境界が整数度）。本モジュールは
      どちらも解析CRSのグリッドへ再投影するため、この差は集約経路で吸収される。
"""

from __future__ import annotations

import numpy as np

from ..grid import BBox, GridSpec
from ..io import RasterResource
from .raster import aggregate_mean_and_valid_ratio, warn_if_band_description_unexpected

# 放射輝度の主バンド名。データセット間で異なる（VIIRS DNB: ``avg_radiance`` /
# Black Marble: ``ntl_near_nadir``）ため候補として列挙する。
#
# **部分一致ではなく完全一致で照合する。** 兄弟バンドの ``avg_radiance_masked`` ・
# ``max_radiance`` ・ ``ntl_all_angle`` はいずれも主バンドと語を共有するため、部分一致
# では取り違えを素通りさせる。とりわけ ``avg_radiance_masked`` は本モジュールが明示的に
# 退けているバンドでありながら、本ROIでのROI平均が 5.307 と主バンドの 5.407 にほぼ等しく、
# 出力統計を見ても判別できない。完全一致なら、両データセットの4バンドのうち主バンド
# 以外をすべて検知できる。
RADIANCE_BAND_NAMES = ("avg_radiance", "ntl_near_nadir")


def compute(
    resource: RasterResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """夜間光強度パラメータを算出する。

    Args:
        resource: 夜間光ラスタ（未指定シナリオでは ``None``）。放射輝度の主バンドを
            指す ``band_index`` を持つこと。
        bbox_analysis: 解析用CRS上の検索範囲。集約先の範囲は ``grid_spec`` が
            保持するため本関数では参照しないが、他パラメータモジュールと
            シグネチャを揃えるために受け取る。
        grid_spec: fine/coarseグリッドの仕様。coarseグリッドへ集約する。

    Returns:
        ``{"NTL_MEAN": array, "NTL_VALID_RATIO": array}`` 形式の辞書。
        ``NTL_MEAN`` の単位は nW·cm⁻²·sr⁻¹、``NTL_VALID_RATIO`` はセル内の
        夜間光ラスタ有効画素率（0-1、ラスタ範囲外は ``0.0``）。
        ``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    # 主バンド以外を指していないかを先に確かめる。取り違えても値は出るため、集約後の
    # 統計を見ても気づけない（``cf_cvg`` は51-96で放射輝度と桁が重なり、
    # ``avg_radiance_masked`` に至っては主バンドとほぼ同じ値になる）。
    warn_if_band_description_unexpected(
        resource.path, resource.band_index, RADIANCE_BAND_NAMES, "夜間光", exact=True
    )

    # 都市とデータセットの取り違えや切り出し範囲の誤りでは、ファイルが存在するため
    # 入力解決（io.get_optional_raster_resource）を素通りし、全セルNaNの列が黙って
    # 出力される。列が残るぶん欠損に気づきにくいため、共通処理が原因を切り分けて警告する。
    return aggregate_mean_and_valid_ratio(
        resource.path,
        grid_spec,
        resource.band_index,
        "NTL_MEAN",
        "NTL_VALID_RATIO",
        "夜間光",
    )
