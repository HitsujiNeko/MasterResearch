"""標高パラメータ（ELEV_MEAN / ELEV_VALID_RATIO）算出モジュール。

オープンソースDEM（FABDEM v1.2）のラスタをcoarseグリッドへ平均集約し、
セル平均標高（m）とセル内のDEM有効画素率（0-1）を求める。集約は衛星指標と
共通の ``params.raster`` の集約関数を用いる。

解釈上の前提:
    - FABDEMは準DTMである。Copernicus GLO-30をランダムフォレスト回帰で
      補正し建物・森林バイアスを除去したものであり、生のDSMではない。
      ただし高密度キャノピー・急峻地形では補正残差が残る。
    - 垂直基準面はEGM2008ジオイド高であり、0mは平均海面と厳密には一致しない。
    - ライセンスはCC BY-NC-SA 4.0（非商用）。論文・資料へ帰属文の記載が必須である。
    - ROIの有効カバレッジ外は ``NaN`` であり ``0`` ではない。0mは実在する
      標高値（海抜0m）であるため、両者を同一視してはならない。
    - ``ELEV_MEAN`` はセル内の**有効画素のみ**の平均である。セルの一部しか
      DEMに覆われていなくても値は ``NaN`` にならないため、セルの信頼度は
      ``ELEV_VALID_RATIO``（有効画素率）で判断する。``NaN`` の件数だけでは
      部分被覆のセルを捕捉できず、有効カバレッジを過大評価する。
    - ``scale=30`` では集約が実質的なリサンプリングになる。FABDEMの画素は
      0.000269度で、ハノイの緯度では東西約28m・南北約30mであり、30mセルと
      ほぼ1対1に対応する。「セル内の面積平均標高」とは言えないため、
      RQ2のスケール間比較で30mの値を過大解釈しない。
"""

from __future__ import annotations

import warnings

import numpy as np

from ..grid import BBox, GridSpec
from ..io import RasterResource
from .raster import aggregate_raster_to_grid, aggregate_valid_ratio_to_grid


def compute(
    resource: RasterResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """標高パラメータを算出する。

    Args:
        resource: DEMラスタ（未指定シナリオでは ``None``）。
        bbox_analysis: 解析用CRS上の検索範囲。集約先の範囲は ``grid_spec`` が
            保持するため本関数では参照しないが、他パラメータモジュールと
            シグネチャを揃えるために受け取る。
        grid_spec: fine/coarseグリッドの仕様。coarseグリッドへ集約する。

    Returns:
        ``{"ELEV_MEAN": array, "ELEV_VALID_RATIO": array}`` 形式の辞書。
        ``ELEV_MEAN`` の単位はm、``ELEV_VALID_RATIO`` はセル内のDEM有効画素率
        （0-1、ラスタ範囲外は ``0.0``）。
        ``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    elev_mean = aggregate_raster_to_grid(resource.path, grid_spec, resource.band_index)
    valid_ratio = aggregate_valid_ratio_to_grid(resource.path, grid_spec, resource.band_index)

    # 都市とDEMの取り違えや切り出し範囲の誤りでは、ファイルが存在するため入力解決
    # （io.get_optional_raster_resource）を素通りし、全セルNaNの列が黙って出力される。
    # 列が残るぶん欠損に気づきにくいため、ここで警告する。
    if not np.isfinite(elev_mean).any():
        warnings.warn(
            f"DEMが解析グリッドと重なりません。標高列は全セルNaNになります: {resource.path}",
            stacklevel=2,
        )

    return {"ELEV_MEAN": elev_mean, "ELEV_VALID_RATIO": valid_ratio}
