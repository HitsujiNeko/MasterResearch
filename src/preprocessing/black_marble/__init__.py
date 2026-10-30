"""NASA Black Marble（VNP46A4）年次夜間光の取得処理。

エントリポイントは `src/preprocessing/fetch_black_marble_hanoi.py`（CLI）で、
本パッケージは責務ごとのモジュールに処理の本体を持つ。

- `product`: 製品の定義（製品名・バンド構成・無効値）
- `auth`: Earthdata トークンの解決と認証ヘッダー
- `tile_grid`: タイル格子と ROI・ファイル属性との対応づけ
- `listing`: LAADS のファイル一覧の取得・解釈・検証
- `download`: タイルの取得・キャッシュとライセンス未同意の切り分け
- `conversion`: HDF5 の読み込みと GeoTIFF 変換
- `report`: サマリーの組み立てとログ出力
- `pipeline`: 処理全体の実行
"""
