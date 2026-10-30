"""Earthdata の Bearer トークンの解決と認証ヘッダーの組み立て。

**トークンの値はログにも例外メッセージにも出さない**。
"""

from __future__ import annotations

import os
from pathlib import Path

from src.common.env_file import DEFAULT_ENV_FILE_PATH, resolve_secret

# トークンの変数名。環境変数またはリポジトリ直下の .env（Git 管理外）から読む。
EARTHDATA_TOKEN_ENV_VAR = "EARTHDATA_TOKEN"


def resolve_earthdata_token(token_file: Path | None = None) -> str:
    """Earthdata の Bearer トークンを解決する。

    優先順位は「明示指定されたファイル → 環境変数 → リポジトリ直下の `.env`」。
    明示指定を最優先にするのは、コマンドラインでの指定が利用者の意図として最も強いため。
    **トークンの値はログにも例外メッセージにも出さない**。

    Args:
        token_file: トークンだけを記載したファイル。未指定なら環境変数・`.env` を見る。

    Returns:
        トークン文字列。

    Raises:
        FileNotFoundError: 明示指定されたトークンファイルが存在しない場合。
        ValueError: どこからもトークンを取得できない、または内容が空の場合。
    """
    if token_file is not None:
        if not token_file.exists():
            raise FileNotFoundError(f"トークンファイルが見つかりません: {token_file}")
        # `.env` 側と同じく BOM 付き UTF-8 を許容する（Windows のエディタ対策）
        token = token_file.read_text(encoding="utf-8-sig").strip()
        if not token:
            raise ValueError(f"トークンファイルが空です: {token_file}")
        return token

    token = resolve_secret(
        EARTHDATA_TOKEN_ENV_VAR, dict(os.environ), env_file_path=DEFAULT_ENV_FILE_PATH
    )
    if token:
        return token

    raise ValueError(
        "Earthdata のトークンが見つかりません。"
        "<https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token> で発行し、"
        f"リポジトリ直下の .env に {EARTHDATA_TOKEN_ENV_VAR}=... を書くか、"
        f"環境変数 {EARTHDATA_TOKEN_ENV_VAR} を設定してください"
        "（--token-file でファイルを直接指定することもできます）。"
    )


def build_authorization_headers(token: str) -> dict[str, str]:
    """LAADS DAAC 用の認証ヘッダーを組み立てる。

    Args:
        token: Earthdata の Bearer トークン。

    Returns:
        Authorization ヘッダーを含む辞書。
    """
    return {"Authorization": f"Bearer {token}"}
