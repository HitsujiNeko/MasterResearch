"""LAADS のファイル一覧の取得・解釈（`black_marble.listing`）のテスト。"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.preprocessing.black_marble import listing as target
from src.preprocessing.black_marble import (
    tile_grid,
)


class TestBuildListingUrl:
    """build_listing_url のテスト。"""

    def test_targets_archive_set_and_annual_day(self) -> None:
        """一覧 URL は ArchiveSet 5200 と day-of-year 001 を指す。"""
        url = target.build_listing_url(2023)

        assert "/5200/VNP46A4/2023/001" in url
        assert url.startswith("https://")


class TestFetchTileListing:
    """fetch_tile_listing のテスト。"""

    def test_returns_parsed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON が返れば辞書として返す。"""
        monkeypatch.setattr(
            target, "fetch_bytes_with_retry", lambda *a, **k: b'{"content": [{"name": "a.h5"}]}'
        )

        assert target.fetch_tile_listing(2023, {}) == {"content": [{"name": "a.h5"}]}

    def test_raises_authentication_hint_when_html_is_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ログインページの HTML が返った場合、認証を疑う旨を添えて例外にする。

        未認証時の LAADS は 401 ではなく Earthdata のログインページへ 302 する。
        素の json.loads だと原因の分からない例外になるため、ここで言い換える。
        """
        monkeypatch.setattr(
            target,
            "fetch_bytes_with_retry",
            lambda *a, **k: b"<!DOCTYPE html><html><body>Earthdata Login</body></html>",
        )

        with pytest.raises(RuntimeError, match="トークンが無効・期限切れ"):
            target.fetch_tile_listing(2023, {})

    def test_error_includes_response_preview(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """原因調査のため応答の先頭を添える。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: b"<!DOCTYPE html>")

        with pytest.raises(RuntimeError, match="DOCTYPE"):
            target.fetch_tile_listing(2023, {})

    def test_handles_non_utf8_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """UTF-8 として読めない応答でも、デコード失敗で落ちず同じ例外にまとめる。"""
        monkeypatch.setattr(
            target, "fetch_bytes_with_retry", lambda *a, **k: bytes([0xFF, 0xFE, 0x00]) + b"bin"
        )

        with pytest.raises(RuntimeError, match="JSON で返りませんでした"):
            target.fetch_tile_listing(2023, {})

    def test_passes_authorization_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """認証ヘッダーと、リダイレクト先の許可ホストを取得処理へ渡す。

        認証ヘッダーはリダイレクト先へ引き継がれるため、ヘッダーを付ける経路では
        許可ホストの指定が伴っていないと送信先を閉じられない。
        """
        recorded: dict[str, Any] = {}

        def fake_fetch(
            url: str,
            timeout: int,
            headers: dict[str, str],
            allowed_redirect_hosts: frozenset[str] | None = None,
        ) -> bytes:
            """呼び出し引数を記録し、空の一覧を返す。"""
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["allowed_redirect_hosts"] = allowed_redirect_hosts
            return b'{"content": []}'

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)

        target.fetch_tile_listing(2023, {"Authorization": "Bearer t"})

        assert recorded["headers"] == {"Authorization": "Bearer t"}
        assert "/5200/VNP46A4/2023/001" in recorded["url"]
        assert recorded["allowed_redirect_hosts"] == target.ALLOWED_REDIRECT_HOSTS


class TestExtractListingEntries:
    """extract_listing_entries のテスト。"""

    @staticmethod
    def _entry(name: str) -> dict[str, Any]:
        """LAADS の実レスポンスに合わせたエントリを作る。"""
        return {
            "name": name,
            "downloadsLink": f"https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/{name}",
            "size": 119818130,
            "resourceType": "File",
        }

    def test_extracts_name_and_download_url(self) -> None:
        """名前とダウンロード URL を取り出す。"""
        entries = target.extract_listing_entries({"content": [self._entry("a.h5")]})

        assert len(entries) == 1
        assert entries[0].name == "a.h5"
        assert entries[0].download_url.endswith("/archives/a.h5")
        assert entries[0].size_bytes == 119818130

    def test_uses_downloads_link_not_public_archive_path(self) -> None:
        """公開アーカイブのパスを組み立てず、一覧が返す URL をそのまま使う。

        `/archive/allData/...` はライセンス同意ページへ 303 されるため、
        Bearer トークンでは辿れない。
        """
        entries = target.extract_listing_entries({"content": [self._entry("a.h5")]})

        assert "/api/v2/content/archives/" in entries[0].download_url
        assert "/archive/allData/" not in entries[0].download_url

    def test_accepts_file_name_key(self) -> None:
        """fileName キーの版にも対応する。"""
        entry = self._entry("a.h5")
        entry["fileName"] = entry.pop("name")

        entries = target.extract_listing_entries({"content": [entry]})

        assert entries[0].name == "a.h5"

    def test_skips_entry_without_download_link(self) -> None:
        """ダウンロード URL の無いエントリは対象から外す（取得できないため）。"""
        entry = self._entry("a.h5")
        del entry["downloadsLink"]

        with pytest.raises(RuntimeError, match="取り出せませんでした"):
            target.extract_listing_entries({"content": [entry]})

    def test_tolerates_missing_size(self) -> None:
        """サイズが無くても取得は続行できる。"""
        entry = self._entry("a.h5")
        del entry["size"]

        entries = target.extract_listing_entries({"content": [entry]})

        assert entries[0].size_bytes is None

    @pytest.mark.parametrize(
        ("raw_size", "expected"),
        [
            (119818130, 119818130),
            ("119818130", 119818130),
            (119818130.0, 119818130),
            ("  119818130  ", 119818130),
        ],
    )
    def test_accepts_size_in_other_representations(self, raw_size: Any, expected: int) -> None:
        """サイズが文字列・浮動小数点で返る版でも受け取る。

        int 決め打ちにすると None になり、ダウンロードサイズの検証が例外にも
        警告にもならず飛ばされる。
        """
        entry = self._entry("a.h5")
        entry["size"] = raw_size

        entries = target.extract_listing_entries({"content": [entry]})

        assert entries[0].size_bytes == expected

    @pytest.mark.parametrize("raw_size", ["unknown", "nan", "inf", "-inf", float("inf")])
    def test_warns_when_size_cannot_be_parsed(
        self, raw_size: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """解釈できないサイズは、検証が無効になることが分かるよう警告する。

        `nan` は ValueError、`inf` は OverflowError になる。捕まえ損ねると
        「解釈できない値は None + 警告に落とす」という方針を素通りしてしまう。
        """
        entry = self._entry("a.h5")
        entry["size"] = raw_size

        with caplog.at_level(logging.WARNING):
            entries = target.extract_listing_entries({"content": [entry]})

        assert entries[0].size_bytes is None
        assert "検証を行いません" in caplog.text

    @pytest.mark.parametrize(
        "unsafe_name",
        [
            "../../evil.h5",
            "sub/dir/tile.h5",
            "..\\evil.h5",
            "C:evil.h5",
            "..",
        ],
    )
    def test_rejects_file_name_that_escapes_the_cache_directory(self, unsafe_name: str) -> None:
        """パスとして安全でない名前は対象から外す。

        `name` は唯一そのままキャッシュのパスになる外部由来の値で、区切り文字を
        含んでいると保存先の外へ 100MB 超を書き出しうる。
        """
        entry = self._entry(unsafe_name)

        with pytest.raises(RuntimeError, match="取り出せませんでした"):
            target.extract_listing_entries({"content": [entry]})

    def test_accepts_actual_distribution_file_name(self) -> None:
        """実際の配布ファイル名は安全と判定される（過剰な拒否をしない）。"""
        assert target.is_safe_tile_file_name("VNP46A4.A2023001.h28v06.002.2025162082259.h5")

    @pytest.mark.parametrize(
        "unsafe_url",
        [
            "http://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/a.h5",
            "https://evil.invalid/api/v2/content/archives/a.h5",
            "https://ladsweb.modaps.eosdis.nasa.gov.evil.invalid/a.h5",
            "file:///etc/passwd",
        ],
    )
    def test_skips_entry_whose_download_url_points_elsewhere(self, unsafe_url: str) -> None:
        """想定外の宛先の URL は対象から外す。

        この URL は Earthdata の Bearer トークンを添えて叩く。別ホストを指していると
        トークンが第三者へ送られる。
        """
        entry = self._entry("a.h5")
        entry["downloadsLink"] = unsafe_url

        with pytest.raises(RuntimeError, match="取り出せませんでした"):
            target.extract_listing_entries({"content": [entry]})

    def test_accepts_actual_distribution_download_url(self) -> None:
        """実際の配信 URL は安全と判定される（過剰な拒否をしない）。"""
        assert target.is_safe_download_url(
            "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/allData/5200/a.h5"
        )

    def test_raises_when_content_is_missing(self) -> None:
        """content が無ければ、返ってきたキーを添えて例外にする。"""
        with pytest.raises(RuntimeError, match="content 配列がありません"):
            target.extract_listing_entries({"error": "unauthorized"})

    def test_raises_when_no_entries_found(self) -> None:
        """構造は合っていても取れなければ、空を返さず例外にする。"""
        with pytest.raises(RuntimeError, match="取り出せませんでした"):
            target.extract_listing_entries({"content": [{"size": 1}]})


class TestSelectTileFiles:
    """select_tile_files のテスト。"""

    @staticmethod
    def _tile_file(name: str) -> target.TileFile:
        """テスト用のファイル情報を作る。"""
        return target.TileFile(
            name=name,
            download_url=f"https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/{name}",
        )

    def test_selects_file_for_requested_tile(self) -> None:
        """タイル名を含むファイルを選ぶ。"""
        tile_files = [
            self._tile_file("VNP46A4.A2023001.h28v06.002.2025162082259.h5"),
            self._tile_file("VNP46A4.A2023001.h29v06.002.2025162082259.h5"),
        ]

        selected = target.select_tile_files(tile_files, [tile_grid.TileIndex(28, 6)])

        assert selected["h28v06"].name == "VNP46A4.A2023001.h28v06.002.2025162082259.h5"

    def test_does_not_match_tile_name_as_substring(self) -> None:
        """区切りのドットを含めて照合する（h28v06 が h28v060 等に誤マッチしない）。"""
        tile_files = [self._tile_file("VNP46A4.A2023001.h28v060.002.2024032.h5")]

        with pytest.raises(RuntimeError, match="一覧にありません"):
            target.select_tile_files(tile_files, [tile_grid.TileIndex(28, 6)])

    def test_raises_when_tile_is_missing(self) -> None:
        """必要なタイルが無ければ例外にする。"""
        tile_files = [self._tile_file("VNP46A4.A2023001.h29v06.002.x.h5")]

        with pytest.raises(RuntimeError, match="一覧にありません"):
            target.select_tile_files(tile_files, [tile_grid.TileIndex(28, 6)])

    def test_raises_when_multiple_versions_exist(self) -> None:
        """同一タイルの版が複数あれば、どちらを使ったか不明になるため止める。"""
        tile_files = [
            self._tile_file("VNP46A4.A2023001.h28v06.002.2024032.h5"),
            self._tile_file("VNP46A4.A2023001.h28v06.002.2025100.h5"),
        ]

        with pytest.raises(RuntimeError, match="複数あります"):
            target.select_tile_files(tile_files, [tile_grid.TileIndex(28, 6)])
