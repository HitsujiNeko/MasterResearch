"""タイルの取得とライセンス切り分け（`black_marble.download`）のテスト。

ネットワークアクセスは差し替え、実通信は行わない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.preprocessing.black_marble import download as target
from src.preprocessing.black_marble import (
    listing,
)


class TestDownloadTile:
    """download_tile のテスト。"""

    # 保存前の検証を通る最小の中身（HDF5 の署名で始まるバイト列）
    TILE_BODY = target.HDF5_SIGNATURE + b"NEW-TILE"

    @classmethod
    def _tile_file(cls, size_bytes: int | None = None) -> listing.TileFile:
        """テスト用のファイル情報を作る。

        Args:
            size_bytes: 一覧が返すサイズ。既定では `TILE_BODY` と整合する値にする。
        """
        return listing.TileFile(
            name="tile.h5",
            download_url="https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/tile.h5",
            size_bytes=len(cls.TILE_BODY) if size_bytes is None else size_bytes,
        )

    def test_reuses_cached_tile_without_network_access(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既に取得済みなら再ダウンロードしない（100MB 超の無駄打ちを避ける）。"""
        cached = tmp_path / "tile.h5"
        cached.write_bytes(self.TILE_BODY)

        def fail_if_called(*args: Any, **kwargs: Any) -> bytes:
            """呼ばれた時点で失敗させる（キャッシュ利用時は取得しない）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("キャッシュがある場合はダウンロードしてはいけない")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fail_if_called)

        result = target.download_tile(self._tile_file(), cached, headers={})

        assert result.read_bytes() == self.TILE_BODY

    def test_downloads_and_saves_when_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """未取得ならダウンロードして保存する。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: self.TILE_BODY)

        result = target.download_tile(self._tile_file(), tmp_path / "sub" / "tile.h5", headers={})

        assert result.read_bytes() == self.TILE_BODY

    def test_uses_download_url_from_listing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """一覧が返した URL をそのまま使う（自前で組み立てない）。"""
        recorded: dict[str, Any] = {}

        def fake_fetch(
            url: str,
            timeout: int,
            headers: dict[str, str],
            allowed_redirect_hosts: frozenset[str] | None = None,
        ) -> bytes:
            """呼び出し引数を記録し、タイル本体を返す。"""
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["allowed_redirect_hosts"] = allowed_redirect_hosts
            return self.TILE_BODY

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)

        target.download_tile(
            self._tile_file(), tmp_path / "tile.h5", headers={"Authorization": "Bearer t"}
        )

        assert (
            recorded["url"]
            == "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/tile.h5"
        )
        assert recorded["headers"] == {"Authorization": "Bearer t"}
        # 認証ヘッダーはリダイレクト先へ引き継がれるため、送信先の制限も伴う必要がある
        assert recorded["allowed_redirect_hosts"] == listing.ALLOWED_REDIRECT_HOSTS

    def test_refuses_to_cache_non_hdf5_response(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """HTML が返ってきた場合、`.h5` として保存しない。

        未認証・トークン失効時の LAADS は 401 ではなくログインページの HTML を
        HTTP 200 で返す。保存してしまうと以降は取得済み扱いになり、トークンを
        再発行しても復旧しなくなる。
        """
        login_page = b"<!DOCTYPE html><html><body>Earthdata Login</body></html>"
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: login_page)
        destination = tmp_path / "tile.h5"

        with pytest.raises(RuntimeError, match="HDF5 ではありません"):
            target.download_tile(self._tile_file(len(login_page)), destination, headers={})

        assert not destination.exists()
        assert not destination.with_suffix(".h5.part").exists()

    def test_refuses_to_cache_truncated_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """一覧のサイズと一致しない（＝途中で切れた）内容は保存しない。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: self.TILE_BODY)
        destination = tmp_path / "tile.h5"

        with pytest.raises(RuntimeError, match="サイズが一覧の値と一致しません"):
            target.download_tile(self._tile_file(size_bytes=119818130), destination, headers={})

        assert not destination.exists()

    def test_replaces_cache_that_is_not_hdf5(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """壊れたキャッシュは取得済み扱いにせず、破棄して取り直す。

        以前の版が焼き付けた HTML が残っていても、手動削除なしに復旧できること。
        """
        cached = tmp_path / "tile.h5"
        cached.write_bytes(b"<!DOCTYPE html><html>Earthdata Login</html>")
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: self.TILE_BODY)

        result = target.download_tile(self._tile_file(), cached, headers={})

        assert result.read_bytes() == self.TILE_BODY

    def test_accepts_download_without_size_in_listing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """一覧にサイズが無い場合は、サイズ照合を飛ばして保存する。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: self.TILE_BODY)
        tile_file = listing.TileFile(
            name="tile.h5",
            download_url="https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/tile.h5",
            size_bytes=None,
        )

        result = target.download_tile(tile_file, tmp_path / "tile.h5", headers={})

        assert result.read_bytes() == self.TILE_BODY

    def test_refuses_download_url_pointing_elsewhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """想定外の宛先の URL には、トークンを送らずに例外で止まる。"""

        def fail_if_called(*args: Any, **kwargs: Any) -> bytes:
            """呼ばれた時点で失敗させる（想定外の宛先へは通信しない）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("想定外の宛先へリクエストしてはいけない")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fail_if_called)
        tile_file = listing.TileFile(
            name="tile.h5", download_url="https://evil.invalid/tile.h5", size_bytes=None
        )

        with pytest.raises(RuntimeError, match="想定外の宛先"):
            target.download_tile(tile_file, tmp_path / "tile.h5", headers={"Authorization": "t"})

    def test_reports_license_gate_with_actionable_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ライセンス未同意が原因なら、同意ページの URL を添えて投げ直す。

        素の失敗は「リダイレクト先の Earthdata で 401」となり原因が読み取れない。
        """

        def raise_runtime_error(*args: Any, **kwargs: Any) -> bytes:
            """未認証時に相当する 401 の失敗を模す。

            Raises:
                RuntimeError: 毎回。
            """
            raise RuntimeError("リクエストが3回失敗しました: HTTP Error 401: Unauthorized")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", raise_runtime_error)
        monkeypatch.setattr(
            target,
            "find_license_gate",
            lambda url, headers: "https://example.invalid/profiles/licenses/x.h5",
        )

        with pytest.raises(RuntimeError, match="データ利用許諾が未同意"):
            target.download_tile(self._tile_file(), tmp_path / "tile.h5", headers={})

    def test_propagates_original_error_when_not_license_gate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ライセンスが原因でなければ、元のエラーを言い換えずに伝える。"""

        def raise_runtime_error(*args: Any, **kwargs: Any) -> bytes:
            """ライセンス以外の原因による失敗を模す。

            Raises:
                RuntimeError: 毎回。
            """
            raise RuntimeError("リクエストが3回失敗しました")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", raise_runtime_error)
        monkeypatch.setattr(target, "find_license_gate", lambda url, headers: None)

        with pytest.raises(RuntimeError, match="3回失敗"):
            target.download_tile(self._tile_file(), tmp_path / "tile.h5", headers={})

    def test_does_not_leave_partial_file_on_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """途中で失敗したとき、壊れたファイルをキャッシュに残さない。"""

        def raise_runtime_error(*args: Any, **kwargs: Any) -> bytes:
            """ダウンロード途中での失敗を模す。

            Raises:
                RuntimeError: 毎回。
            """
            raise RuntimeError("リクエストが3回失敗しました")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", raise_runtime_error)
        monkeypatch.setattr(target, "find_license_gate", lambda url, headers: None)
        destination = tmp_path / "tile.h5"

        with pytest.raises(RuntimeError):
            target.download_tile(self._tile_file(), destination, headers={})

        assert not destination.exists()
        assert not destination.with_suffix(".h5.part").exists()


class TestFindLicenseGate:
    """find_license_gate のテスト（ネットワークへは出ない）。

    このスクリプト固有の価値は「ライセンス未同意を切り分けて伝える」ことにある。
    ここが黙って None を返すと、利用者は原因の分からない 401 に戻される。
    """

    @staticmethod
    def _install_opener(monkeypatch: pytest.MonkeyPatch, raiser: Any) -> None:
        """`build_opener` を差し替え、`open` の挙動を差し込む。"""

        class _FakeOpener:
            """`build_opener` の戻り値を模したダミー。"""

            def open(self, request: Any, timeout: int) -> Any:
                """渡された挙動をそのまま呼び出して返す。"""
                return raiser()

        monkeypatch.setattr(target.urllib.request, "build_opener", lambda *handlers: _FakeOpener())

    @staticmethod
    def _http_error(location: str | None, code: int = 303) -> Any:
        """Location ヘッダーを持つ HTTPError を作る。"""
        headers = {} if location is None else {"Location": location}
        return target.urllib.error.HTTPError(
            "https://example.invalid/x.h5", code, "See Other", headers, None
        )

    def test_returns_license_url_when_redirected_to_licenses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ライセンス同意ページへ 303 されたら、その絶対 URL を返す。"""
        relative = "/profiles/licenses/api/v2/content/archives/allData/5200/x.h5"

        def raiser() -> Any:
            """ライセンス同意ページへの 303 を模した HTTPError を送出する。

            Raises:
                urllib.error.HTTPError: 毎回。
            """
            raise self._http_error(relative)

        self._install_opener(monkeypatch, raiser)

        result = target.find_license_gate(
            "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/x.h5", {}
        )

        # 相対 Location を元 URL のホストで絶対化する
        assert result == f"https://ladsweb.modaps.eosdis.nasa.gov{relative}"

    def test_returns_none_when_redirect_is_unrelated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ライセンス以外のリダイレクトでは None を返し、元エラーを優先させる。"""

        def raiser() -> Any:
            """ライセンスと無関係なリダイレクトを模した HTTPError を送出する。

            Raises:
                urllib.error.HTTPError: 毎回。
            """
            raise self._http_error("/oauth/login?redirect=%2Fx")

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://ladsweb.modaps.eosdis.nasa.gov/x.h5", {}) is None

    def test_returns_none_when_location_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Location が無いエラー（401 等）でも落ちずに None を返す。"""

        def raiser() -> Any:
            """Location を持たない 401 を模した HTTPError を送出する。

            Raises:
                urllib.error.HTTPError: 毎回。
            """
            raise self._http_error(None, code=401)

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://ladsweb.modaps.eosdis.nasa.gov/x.h5", {}) is None

    def test_returns_none_when_request_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """そもそも成功する URL ならライセンスは原因ではない。"""

        class _FakeResponse:
            """成功レスポンスを模したダミー（本文は使わない）。"""

            def __enter__(self) -> "_FakeResponse":
                """`with` 文で自身を返す。"""
                return self

            def __exit__(self, *exc_info: object) -> None:
                """後始末は不要なため何もしない。"""
                return None

        self._install_opener(monkeypatch, lambda: _FakeResponse())

        assert target.find_license_gate("https://ladsweb.modaps.eosdis.nasa.gov/x.h5", {}) is None

    def test_returns_none_on_connection_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """切り分けの補助なので、ここでの通信失敗は握って元エラーを優先する。"""

        def raiser() -> Any:
            """接続そのものの失敗を模す。

            Raises:
                urllib.error.URLError: 毎回。
            """
            raise target.urllib.error.URLError("unreachable")

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://ladsweb.modaps.eosdis.nasa.gov/x.h5", {}) is None

    def test_does_not_open_url_pointing_elsewhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """想定外の宛先には認証ヘッダーを送らず、確認そのものを行わない。

        この経路は `fetch_bytes_with_retry` のスキーム検証を通らないため、
        ここで弾かないと `file://` などがそのまま `opener.open` へ渡る。
        """

        def raiser() -> Any:
            """呼ばれた時点で失敗させる（想定外の宛先は開かない）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("想定外の宛先を開いてはいけない")

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("file:///etc/passwd", {}) is None
        assert target.find_license_gate("https://evil.invalid/x.h5", {}) is None
