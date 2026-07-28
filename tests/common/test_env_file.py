"""env_file.py（`.env` による認証情報の読み込み）のテスト。

秘密情報を扱うため、実際の `.env` には触れず `tmp_path` 上のファイルだけを対象とする。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.common import env_file as target


class TestLoadEnvFile:
    """load_env_file のテスト。"""

    def test_returns_empty_dict_when_file_is_absent(self, tmp_path: Path) -> None:
        """ファイルが無ければ空の辞書を返す（未設定は異常ではない）。"""
        assert target.load_env_file(tmp_path / "absent.env") == {}

    def test_parses_key_value_pairs(self, tmp_path: Path) -> None:
        """基本の KEY=VALUE を読む。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc123\nOTHER=xyz\n", encoding="utf-8")

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc123", "OTHER": "xyz"}

    def test_ignores_comments_and_blank_lines(self, tmp_path: Path) -> None:
        """空行と # で始まる行は無視する。"""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# NASA Earthdata のトークン\n\nEARTHDATA_TOKEN=abc123\n\n", encoding="utf-8"
        )

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc123"}

    def test_accepts_export_prefix(self, tmp_path: Path) -> None:
        """シェル向けに export を付けた記法も読める。"""
        env_path = tmp_path / ".env"
        env_path.write_text("export EARTHDATA_TOKEN=abc123\n", encoding="utf-8")

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc123"}

    def test_strips_surrounding_quotes(self, tmp_path: Path) -> None:
        """値を囲む引用符は取り除く。"""
        env_path = tmp_path / ".env"
        env_path.write_text("A=\"abc\"\nB='def'\n", encoding="utf-8")

        assert target.load_env_file(env_path) == {"A": "abc", "B": "def"}

    def test_reads_file_with_utf8_bom(self, tmp_path: Path) -> None:
        """BOM 付き UTF-8 でも先頭キーが壊れない。

        Windows のエディタや PowerShell の `Out-File` は BOM を付けて書き出す。
        素の utf-8 で読むと先頭キーが `\\ufeffEARTHDATA_TOKEN` になり、
        `str.strip()` は U+FEFF を除かないため設定済みでも見つからなくなる。
        """
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc123\n", encoding="utf-8-sig")

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc123"}

    def test_resolves_secret_from_file_with_utf8_bom(self, tmp_path: Path) -> None:
        """BOM 付きでも解決経路の端まで通る（回帰の検出点を実利用側にも置く）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc123\n", encoding="utf-8-sig")

        assert target.resolve_secret("EARTHDATA_TOKEN", {}, env_path) == "abc123"

    def test_keeps_hash_inside_value(self, tmp_path: Path) -> None:
        """値の途中の # は注釈にしない（トークンに # が含まれても壊さない）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc#def\n", encoding="utf-8")

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc#def"}

    def test_keeps_equals_inside_value(self, tmp_path: Path) -> None:
        """値に = が含まれても最初の = だけで分割する（JWT 等のパディング対策）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc=def==\n", encoding="utf-8")

        assert target.load_env_file(env_path) == {"EARTHDATA_TOKEN": "abc=def=="}

    def test_skips_line_without_equals_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """= の無い行は読み飛ばし、行番号だけを警告に残す（値は出力しない）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN\nOTHER=xyz\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            values = target.load_env_file(env_path)

        assert values == {"OTHER": "xyz"}
        assert "1 行目" in caplog.text
        # 秘密情報が混ざりうるため、行の中身はログへ出さない
        assert "EARTHDATA_TOKEN" not in caplog.text

    def test_does_not_mutate_process_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """os.environ を書き換えない（秘密情報の漏れ出す範囲を狭く保つ）。"""
        monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=abc123\n", encoding="utf-8")

        target.load_env_file(env_path)

        import os

        assert "EARTHDATA_TOKEN" not in os.environ


class TestResolveSecret:
    """resolve_secret のテスト。"""

    def test_environment_variable_takes_precedence(self, tmp_path: Path) -> None:
        """環境変数が `.env` より優先される（CI・一時的な上書きを効かせるため）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=from-file\n", encoding="utf-8")

        resolved = target.resolve_secret(
            "EARTHDATA_TOKEN", {"EARTHDATA_TOKEN": "from-env"}, env_path
        )

        assert resolved == "from-env"

    def test_falls_back_to_env_file(self, tmp_path: Path) -> None:
        """環境変数が無ければ `.env` から読む。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=from-file\n", encoding="utf-8")

        assert target.resolve_secret("EARTHDATA_TOKEN", {}, env_path) == "from-file"

    def test_blank_environment_variable_falls_back(self, tmp_path: Path) -> None:
        """空白だけの環境変数は未設定として扱い、`.env` へ落とす。"""
        env_path = tmp_path / ".env"
        env_path.write_text("EARTHDATA_TOKEN=from-file\n", encoding="utf-8")

        resolved = target.resolve_secret("EARTHDATA_TOKEN", {"EARTHDATA_TOKEN": "   "}, env_path)

        assert resolved == "from-file"

    def test_returns_empty_string_when_unavailable(self, tmp_path: Path) -> None:
        """どこにも無ければ空文字列を返す（判断は呼び出し側に委ねる）。"""
        assert target.resolve_secret("EARTHDATA_TOKEN", {}, tmp_path / "absent.env") == ""

    def test_strips_surrounding_whitespace(self, tmp_path: Path) -> None:
        """前後の空白・改行は取り除く（コピー貼り付けの事故を吸収する）。"""
        resolved = target.resolve_secret(
            "EARTHDATA_TOKEN", {"EARTHDATA_TOKEN": "  abc123\n"}, tmp_path / "absent.env"
        )

        assert resolved == "abc123"
