"""都市構造パラメータ算出モジュール群。

各モジュールは次の標準シグネチャに従う関数 ``compute()`` を提供する。

    def compute(
        resource: LayerResource | None,
        bbox_analysis: BBox,
        grid_spec: GridSpec,
    ) -> dict[str, np.ndarray]:

戻り値はサフィックス無しの列名をキーとし、`grid_spec.coarse_shape` の2次元配列を
値とする辞書である。呼び出し側（``run.py``）が列名に ``_{scale}`` を付与する。
``resource`` が ``None`` の場合、または未実装のモジュールは空辞書を返す。

``elevation.py`` のみ、ベクタレイヤではなくラスタを入力とするため第1引数が
``RasterResource | None`` である。

``raster.py`` のみ、衛星指標ラスタの検出結果辞書を受け取る別シグネチャを持つ。
"""
