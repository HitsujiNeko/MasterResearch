"""gee_raster.py（GEE 由来ラスタのダウンロード処理）のテスト。

ネットワーク・GEE アクセスは伴わせず、ダウンロード URL の生成条件と
ZIP 応答の取り出しを対象とする。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from src.common import gee_raster as target

# WorldPop の実測ネイティブ投影（GEE の projection().getInfo() の戻り値）
WORLDPOP_PROJECTION = {
    "crs": "EPSG:4326",
    "transform": [
        0.0008333333299579025,
        0,
        102.145416273,
        0,
        -0.0008333333300179816,
        23.392916775,
    ],
}


class _FakeValue:
    """getInfo() だけを持つ値オブジェクト。"""

    def __init__(self, value: Any) -> None:
        self.value = value

    def getInfo(self) -> Any:  # noqa: N802  # GEE API 名に合わせる
        """保持している値を返す。"""
        return self.value


class _FakeProjectionImage:
    """select / projection / toFloat / unmask / getDownloadURL を持つ偽の ee.Image。"""

    def __init__(self, projection_info: dict[str, Any], recorded: dict[str, Any]) -> None:
        self.projection_info = projection_info
        self.recorded = recorded

    def select(self, band: Any) -> "_FakeProjectionImage":
        """バンド選択の引数を記録する。"""
        self.recorded["selected_band"] = band
        return self

    def projection(self) -> _FakeValue:
        """ネイティブ投影情報を返す。"""
        return _FakeValue(self.projection_info)

    def toFloat(self) -> "_FakeProjectionImage":  # noqa: N802  # GEE API 名に合わせる
        """float 化されたことを記録する。"""
        self.recorded["to_float_called"] = True
        return self

    def unmask(self, value: float) -> "_FakeProjectionImage":
        """unmask に渡された値を記録する。"""
        self.recorded["unmask_value"] = value
        return self

    def getDownloadURL(self, params: dict[str, Any]) -> str:  # noqa: N802  # GEE API 名に合わせる
        """ダウンロードパラメータを記録する。"""
        self.recorded["params"] = params
        return "https://example.invalid/download"


class TestBuildNativeDownloadUrl:
    """build_native_download_url のテスト。"""

    def test_requests_native_grid_instead_of_scale(self) -> None:
        """scale ではなく crs / crs_transform を渡し、再サンプリングを避ける。"""
        recorded: dict[str, Any] = {}
        image = _FakeProjectionImage(WORLDPOP_PROJECTION, recorded)

        _, projection_info = target.build_native_download_url(
            image, {"type": "Polygon", "coordinates": []}
        )

        params = recorded["params"]
        assert "scale" not in params, "scale 指定は再投影を招き、画素値が保存されない"
        assert params["crs"] == "EPSG:4326"
        assert params["crs_transform"] == WORLDPOP_PROJECTION["transform"]
        assert params["format"] == "GEO_TIFF"
        assert projection_info == WORLDPOP_PROJECTION

    def test_reads_projection_from_first_band(self) -> None:
        """投影情報は先頭バンドから取る（複数バンド画像で projection() が失敗するため）。"""
        recorded: dict[str, Any] = {}
        image = _FakeProjectionImage(WORLDPOP_PROJECTION, recorded)

        target.build_native_download_url(image, {"type": "Polygon", "coordinates": []})

        assert recorded["selected_band"] == 0

    def test_unmasks_with_given_nodata_before_download(self) -> None:
        """マスク画素を明示的な nodata へ置き換えてから取得する。"""
        recorded: dict[str, Any] = {}
        image = _FakeProjectionImage(WORLDPOP_PROJECTION, recorded)

        target.build_native_download_url(image, {"type": "Polygon", "coordinates": []})

        assert recorded["to_float_called"] is True
        # 0 のままだと「値が 0 の場所」と「データ無し」が区別できなくなる
        assert recorded["unmask_value"] == target.DEFAULT_RASTER_NODATA

    def test_uses_explicit_nodata_when_given(self) -> None:
        """nodata を明示した場合はその値で unmask する。"""
        recorded: dict[str, Any] = {}
        image = _FakeProjectionImage(WORLDPOP_PROJECTION, recorded)

        target.build_native_download_url(
            image, {"type": "Polygon", "coordinates": []}, nodata=-32768.0
        )

        assert recorded["unmask_value"] == -32768.0


class TestDownloadGeeRaster:
    """download_gee_raster のテスト。"""

    def test_extracts_geotiff_from_zip_response(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ZIP で返った場合は中の GeoTIFF を取り出す。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "ignored")
            archive.writestr("download.tif", b"GEOTIFF-BYTES")
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: buffer.getvalue())

        destination = target.download_gee_raster(
            "https://example.invalid/x", tmp_path / "out.tif", timeout=10
        )

        assert destination.read_bytes() == b"GEOTIFF-BYTES"

    def test_writes_plain_geotiff_response_as_is(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ZIP でなければレスポンス本文をそのまま保存する。"""
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: b"PLAIN-GEOTIFF")

        destination = target.download_gee_raster(
            "https://example.invalid/x", tmp_path / "out.tif", timeout=10
        )

        assert destination.read_bytes() == b"PLAIN-GEOTIFF"

    def test_raises_when_zip_has_no_geotiff(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ZIP 内に GeoTIFF が無ければ例外にする。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "no raster here")
        monkeypatch.setattr(target, "fetch_bytes_with_retry", lambda *a, **k: buffer.getvalue())

        with pytest.raises(ValueError, match="GeoTIFF がありません"):
            target.download_gee_raster(
                "https://example.invalid/x", tmp_path / "out.tif", timeout=10
            )

    def test_propagates_network_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """リトライ上限に達した失敗は握りつぶさず呼び出し元へ伝え、空ファイルも残さない。"""

        def raise_runtime_error(*args: Any, **kwargs: Any) -> bytes:
            raise RuntimeError("リクエストが3回失敗しました")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", raise_runtime_error)

        with pytest.raises(RuntimeError, match="3回失敗"):
            target.download_gee_raster(
                "https://example.invalid/x", tmp_path / "out.tif", timeout=10
            )
        assert not (tmp_path / "out.tif").exists()

    def test_forwards_timeout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """指定したタイムアウトが取得処理へ渡される。"""
        recorded: dict[str, Any] = {}

        def fake_fetch(url: str, timeout: int) -> bytes:
            recorded["timeout"] = timeout
            return b"PLAIN-GEOTIFF"

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)

        target.download_gee_raster("https://example.invalid/x", tmp_path / "out.tif", timeout=300)

        assert recorded["timeout"] == 300
