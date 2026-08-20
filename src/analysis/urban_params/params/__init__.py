"""都市構造パラメータ算出モジュール群。

各モジュールは次の標準シグネチャに従う関数 ``compute()`` を提供する。

    def compute(
        resource: LayerResource | None,
        bbox_analysis: BBox,
        grid_spec: GridSpec,
    ) -> dict[str, np.ndarray]:

戻り値は列名をキーとし、``grid_spec.coarse_shape`` の2次元配列を値とする辞書である。
**列名にスケールの接尾辞を付けてはならない。** スケールは出力先のディレクトリ階層で
表現するため、呼び出し側も接尾辞を付与しない。

**返す列は ``config.PARAM_SETS`` の宣言列と厳密に一致させること。** ``run.py`` の
``validate_computed_columns()`` が両者を突き合わせ、過不足があれば実行を停止する。
条件によって列を出したり出さなかったりする実装は、この検証で弾かれる。値が求まらない
セルは列ごと落とすのではなく ``np.nan`` を入れる（GeoPackage の NULL として保存される）。

``resource`` が ``None`` の場合に空辞書を返す規約は各モジュールが引き続き持つが、
``run.py`` は ``PARAM_SETS`` から必ずリソースを解決するため ``None`` は渡らない。
空辞書は上記の検証が「宣言列の不足」として ``ValueError`` にするため、**未実装の
モジュールが空辞書を返して黙って列が消える、という逃げ道は無い**。

``elevation.py`` ・ ``population.py`` ・ ``nightlight.py`` は、ベクタレイヤではなく
ラスタを入力とするため第1引数が ``RasterResource | None`` である。

``raster.py`` のみ、衛星指標ラスタの検出結果辞書を受け取る別シグネチャを持つ。

入力そのものの妥当性を確かめる必要があるモジュールは、任意で次の関数を追加できる。

    def validate_resource(resource: LayerResource | RasterResource) -> None:

``run.py`` の ``build_param_tasks()`` が入力解決の直後に1回だけ呼ぶ。``compute()``
の中で確かめるとスケールごとに繰り返され、算出を始めてからでないと誤りが分からない。
現在は ``population.py`` ・ ``nightlight.py`` が、1ファイルに複数バンドを持つ入力で
バンド番号の取り違えを検知するために提供している。
"""
