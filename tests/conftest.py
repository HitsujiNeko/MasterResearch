"""tests/ 配下の pytest 共通設定。

matplotlib のバックエンドをテスト収集より前に `Agg` へ固定する。GUI バックエンド
はヘッドレスな CI 環境で失敗するため、各テストファイルで個別に設定せず、ここで
一度だけ設定する（各ファイルでの `import matplotlib; matplotlib.use("Agg")` の
重複と、それに伴う E402 抑制コメントの散在を避けるため）。

描画するスクリプトのうち他から import されるもの（`analysis_rq3_limited` など）は、
import 時ではなく `main()` の中でバックエンドを設定する。テストは `main()` を通らずに
描画の関数を呼ぶことがあるため、`tests/` 全体に効くこの場所で設定する。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
