"""Earthdata トークンの解決（`black_marble.auth`）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.preprocessing.black_marble import auth as target


class TestResolveEarthdataToken:
    """resolve_earthdata_token のテスト。"""

    def test_reads_from_environment_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数から読む。"""
        monkeypatch.setenv(target.EARTHDATA_TOKEN_ENV_VAR, "  env-token  ")

        assert target.resolve_earthdata_token() == "env-token"

    def test_explicit_file_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """明示指定のファイルが環境変数より優先される。"""
        monkeypatch.setenv(target.EARTHDATA_TOKEN_ENV_VAR, "env-token")
        token_path = tmp_path / "token.txt"
        token_path.write_text("file-token\n", encoding="utf-8")

        assert target.resolve_earthdata_token(token_path) == "file-token"

    def test_falls_back_to_env_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """環境変数が無ければリポジトリ直下の `.env` を見る。"""
        monkeypatch.delenv(target.EARTHDATA_TOKEN_ENV_VAR, raising=False)
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=dotenv-token\n", encoding="utf-8")
        monkeypatch.setattr(target, "DEFAULT_ENV_FILE_PATH", env_path)

        assert target.resolve_earthdata_token() == "dotenv-token"

    def test_raises_when_no_token_available(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """どこからも取得できなければ、発行手順と置き場所を添えて例外にする。"""
        monkeypatch.delenv(target.EARTHDATA_TOKEN_ENV_VAR, raising=False)
        monkeypatch.setattr(target, "DEFAULT_ENV_FILE_PATH", tmp_path / "absent.env")

        with pytest.raises(ValueError, match="generate-token"):
            target.resolve_earthdata_token()

    def test_error_message_mentions_dotenv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """例外メッセージで置き場所（.env）を案内する。"""
        monkeypatch.delenv(target.EARTHDATA_TOKEN_ENV_VAR, raising=False)
        monkeypatch.setattr(target, "DEFAULT_ENV_FILE_PATH", tmp_path / "absent.env")

        with pytest.raises(ValueError, match=r"\.env"):
            target.resolve_earthdata_token()

    def test_raises_when_explicit_file_missing(self, tmp_path: Path) -> None:
        """明示指定のファイルが無ければ、環境変数へ黙って落ちずに例外にする。"""
        with pytest.raises(FileNotFoundError):
            target.resolve_earthdata_token(tmp_path / "absent.txt")

    def test_reads_token_file_with_utf8_bom(self, tmp_path: Path) -> None:
        """BOM 付き UTF-8 のトークンファイルでも読める（`.env` 側と挙動を揃える）。"""
        token_path = tmp_path / "token.txt"
        token_path.write_text("file-token\n", encoding="utf-8-sig")

        assert target.resolve_earthdata_token(token_path) == "file-token"

    def test_raises_when_token_file_is_empty(self, tmp_path: Path) -> None:
        """空のトークンファイルは弾く（空文字で認証を試みない）。"""
        token_path = tmp_path / "token.txt"
        token_path.write_text("   \n", encoding="utf-8")

        with pytest.raises(ValueError, match="空です"):
            target.resolve_earthdata_token(token_path)

    def test_environment_variable_with_only_spaces_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """空白だけの環境変数は未設定として扱う。"""
        monkeypatch.setenv(target.EARTHDATA_TOKEN_ENV_VAR, "   ")
        monkeypatch.setattr(target, "DEFAULT_ENV_FILE_PATH", tmp_path / "absent.env")

        with pytest.raises(ValueError):
            target.resolve_earthdata_token()


class TestBuildAuthorizationHeaders:
    """build_authorization_headers のテスト。"""

    def test_builds_bearer_header(self) -> None:
        """Bearer スキームのヘッダーを作る。"""
        assert target.build_authorization_headers("abc") == {"Authorization": "Bearer abc"}
