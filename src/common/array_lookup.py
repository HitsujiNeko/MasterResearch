"""NumPy配列を添字表で安全に引くための共通ヘルパー。

``lulc_classes.py``（画素値→共通クラスIDの写像）と ``urban_params/params/raster.py``
（カテゴリラスタの集約）の双方で、配列の値をそのまま添字として使う処理が重複していた。
両者は互いに依存させない構成（``raster.py`` は写像表そのものに依存しない）のため、
どちらからも参照できる中立な場所としてここへ切り出す。
"""

from __future__ import annotations

import numpy as np


def in_lookup_range(values: np.ndarray, lookup_size: int) -> np.ndarray:
    """``lookup[values]`` で安全に参照できる位置を表す真偽値配列を返す。

    ``values < lookup_size`` だけで判定すると、負の値はNumPyの負インデックス
    解釈により「範囲内」と判定されてしまい、``lookup[values]`` が配列の末尾側
    から誤って参照される（意図しない別クラスへ静かに誤分類されうる）。
    ``values >= 0`` を組み合わせることで、この誤参照を防ぐ。

    Args:
        values: 添字として使う配列（整数dtype）。
        lookup_size: 添字表（``lookup``）の要素数。

    Returns:
        ``0 <= values < lookup_size`` を満たす位置が ``True`` の真偽値配列。
    """
    return (values >= 0) & (values < lookup_size)
