"""`.env` ファイルによる認証情報の読み込み。

API トークン等の秘密情報を、リポジトリ直下の `.env`（Git 管理外）から読む。
外部ライブラリ（python-dotenv）は使わず標準ライブラリのみで解決する
（`http_fetch` が requests を使わないのと同じ方針）。

置き場所を `.env` に固定する理由:

- `data/input/` は「配下のファイルは Git 追跡する」運用のため、そこへ秘密情報を置くと
  `.gitignore` の1行だけが漏洩を防いでいる状態になり、取り違えが起きやすい
- リポジトリ直下の `.env` は除外対象として広く認識されており、誤ってコミットしにくい
- 秘密情報の置き場所が1箇所に集まり、追加時の判断が要らない

**このモジュールは `os.environ` を書き換えない**。読み取った値を返すだけにして、
プロセス全体へ秘密情報が漏れ出す範囲を狭く保つ。
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.common.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE_PATH = PROJECT_ROOT / ".env"


def load_env_file(env_file_path: Path = DEFAULT_ENV_FILE_PATH) -> dict[str, str]:
    """`.env` 形式のファイルを読み、キーと値の辞書を返す。

    受け付ける記法は最小限に絞る。

    - 空行と `#` で始まる行は無視する
    - `KEY=VALUE` 形式（先頭の `export ` は許容する）
    - 値を囲む引用符（`'` または `"`）は取り除く
    - **値の途中の `#` は注釈として扱わない**（トークンに `#` が含まれても壊さないため）

    読み込みは `utf-8-sig` で行い、**BOM を取り除く**。Windows のエディタや
    PowerShell の `Out-File` は BOM 付き UTF-8 で書き出すことがあり、素の `utf-8`
    で読むと先頭キーが `\\ufeffEARTHDATA_TOKEN` になる。`str.strip()` は U+FEFF を
    空白として扱わないため、設定済みなのに「見つからない」という分かりにくい失敗になる。

    ファイルが存在しない場合は空の辞書を返す（未設定は異常ではなく、環境変数など
    別の経路で与えられうるため）。

    Args:
        env_file_path: 読み込む `.env` のパス。

    Returns:
        キー -> 値 の辞書。ファイルが無ければ空の辞書。
    """
    if not env_file_path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        env_file_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            # 値を持たない行は書き損じの可能性が高い。黙って捨てず記録に残す
            # （秘密情報が混ざりうるため、行番号のみでファイル内容は出力しない）
            logger.warning(
                "%s の %d 行目に '=' が無いため読み飛ばします。", env_file_path.name, line_number
            )
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_secret(
    name: str,
    environment: dict[str, str],
    env_file_path: Path = DEFAULT_ENV_FILE_PATH,
) -> str:
    """秘密情報を、環境変数 → `.env` の順で解決する。

    環境変数を優先するのは、CI や一時的な上書きが `.env` を書き換えずに効くようにするため
    （python-dotenv の既定の優先順位と同じ）。

    Args:
        name: 変数名（例 `EARTHDATA_TOKEN`）。
        environment: 環境変数の辞書（通常は `os.environ`）。呼び出し側から渡すことで
            テスト時にグローバル状態へ依存しないようにする。
        env_file_path: `.env` のパス。

    Returns:
        解決した値。前後の空白は取り除く。見つからなければ空文字列。
    """
    environment_value = environment.get(name, "").strip()
    if environment_value:
        return environment_value

    return load_env_file(env_file_path).get(name, "").strip()
