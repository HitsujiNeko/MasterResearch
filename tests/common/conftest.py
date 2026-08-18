"""tests/common/ 配下のpytest共通設定。

matplotlibのバックエンドをテスト収集より前に `Agg` へ固定する。GUIバックエンド
はヘッドレスなCI環境で失敗するため、各テストファイルで個別に設定せず、ここで
一度だけ設定する（各ファイルでの `import matplotlib; matplotlib.use("Agg")` の
重複と、それに伴うE402抑制コメントの散在を避けるため）。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
