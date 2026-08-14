"""地表面温度パラメータ（LST / LST_VALID_RATIO）算出モジュール。

LandsatのLSTラスタをcoarseグリッドへ平均集約し、セル平均地表面温度（°C）と
セル内のLST有効画素率（0-1）を求める。集約は衛星指標・標高と共通の
``params.raster`` の集約関数を用いる。

解釈上の前提:
    - LSTは目的変数である。``lst_*`` テーブルの列は衛星指標の品質管理列
      （``VALID_SATELLITE_MASK``）の判定材料には含めない。目的変数と説明変数の
      有効性を混ぜないためである。
    - LSTラスタは摂氏（°C）で格納されている前提とする。ケルビン単位のラスタを
      誤って渡した場合を検知するため、集約後の有効値の中央値が地表面温度として
      妥当な範囲（``PLAUSIBLE_LST_MIN_C``〜``PLAUSIBLE_LST_MAX_C``）の外であれば
      警告する。正常なLSTを誤って弾かないよう範囲は広めに取っており、値の書き換え
      や処理停止は行わない。
    - 雲マスクにより欠測画素が多い（実データでは有効画素率25.4〜45.7%）。
      ``LST`` はセル内の**有効画素のみ**の平均であるため、セルの大部分が雲に
      覆われていても値は ``NaN`` にならない。セルの信頼度は ``LST_VALID_RATIO``
      （有効画素率）で判断する。``NaN`` の件数だけでは部分被覆のセルを捕捉できず、
      有効カバレッジを過大評価する（標高と同じ規約）。
    - ラスタ範囲外のセルは ``LST_VALID_RATIO`` が ``0.0`` になる
      （``aggregate_valid_ratio_to_grid()`` の既知の制約）。LSTラスタの範囲は
      FABDEMと同一でROIを覆うため、影響を受けるのは解析BBox最外周セルに限られる。
    - LSTラスタが解析グリッドと全く重ならない場合（都市とラスタの取り違え・切り出し
      範囲の誤り等）は、有効画素が1つも無いためケルビン検知（中央値判定）ができない。
      その場合は別途、全セルNaNになる旨を警告する（標高と同じ規約）。
"""

from __future__ import annotations

import warnings

import numpy as np

from ..grid import GridSpec
from ..io import RasterResource
from .raster import aggregate_raster_to_grid, aggregate_valid_ratio_to_grid

# 摂氏として妥当とみなす地表面温度の範囲（°C）。ケルビン取り違え（300前後の値）を
# 検知するための閾値であり、正常なLST（実データ実測 13.50〜63.27°C）を弾かないよう
# 広めに取る。
PLAUSIBLE_LST_MIN_C = -60.0
PLAUSIBLE_LST_MAX_C = 90.0


def compute(resource: RasterResource, grid_spec: GridSpec) -> dict[str, np.ndarray]:
    """LSTパラメータを算出する。

    Args:
        resource: LSTラスタ（バンド番号は呼び出し側で検証済みのものを渡す）。
        grid_spec: fine/coarseグリッドの仕様。coarseグリッドへ集約する。

    Returns:
        ``{"LST": array, "LST_VALID_RATIO": array}`` 形式の辞書。
        ``LST`` の単位は摂氏（°C）、``LST_VALID_RATIO`` はセル内のLST有効画素率
        （0-1、ラスタ範囲外は ``0.0``）。
    """
    lst_mean = aggregate_raster_to_grid(resource.path, grid_spec, resource.band_index)
    valid_ratio = aggregate_valid_ratio_to_grid(resource.path, grid_spec, resource.band_index)

    # ケルビン単位のラスタを誤って渡すと、全セルが270〜320付近に偏る。摂氏として
    # 妥当な範囲の外れを中央値で検知する（平均だと外れ値1つでも判定が振れるため）。
    finite_values = lst_mean[np.isfinite(lst_mean)]
    if finite_values.size > 0:
        median = float(np.median(finite_values))
        if not (PLAUSIBLE_LST_MIN_C <= median <= PLAUSIBLE_LST_MAX_C):
            warnings.warn(
                "LSTの集約値の中央値が摂氏として妥当な範囲"
                f"（{PLAUSIBLE_LST_MIN_C:.0f}〜{PLAUSIBLE_LST_MAX_C:.0f}°C）の外です"
                f"（中央値: {median:.1f}）。ケルビン単位のラスタを渡していないか"
                f" 確認してください: {resource.path}",
                stacklevel=2,
            )
    else:
        # 都市とLSTラスタの取り違えや切り出し範囲の誤りでは、ファイルが存在するため
        # 入力解決を素通りし、全セルNaNの列が黙って出力される。列が残るぶん欠損に
        # 気づきにくいため、ここで警告する（elevation.pyと同じ規約）。
        warnings.warn(
            f"LSTラスタが解析グリッドと重なりません。LST列は全セルNaNになります: {resource.path}",
            stacklevel=2,
        )

    return {"LST": lst_mean, "LST_VALID_RATIO": valid_ratio}
