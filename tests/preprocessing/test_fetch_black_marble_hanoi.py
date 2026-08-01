"""fetch_black_marble_hanoi.py（NASA Black Marble VNP46A4 取得スクリプト）のテスト。

ネットワークアクセスを伴わない純粋関数を中心とする。HDF5 の読み取りは、合成した
小さな `.h5` を書き出して検証する（配布物の 92MB タイルには依存させない）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest
import rasterio

from src.preprocessing import fetch_black_marble_hanoi as target
from tests.conftest import HANOI_ROI_BOUNDS, make_fake_build_target_area

# 合成タイルの一辺の画素数（実物は 2400。テストでは小さくして扱いやすくする）
FAKE_TILE_PIXELS = 20


def _write_fake_tile(
    path: Path,
    tile: target.TileIndex,
    scale_factor: float = 1.0,
    offset: float = 0.0,
    include_bounding_coords: bool = True,
    bounds_override: dict[str, float] | None = None,
    shape: tuple[int, int] = (FAKE_TILE_PIXELS, FAKE_TILE_PIXELS),
    extra_fill_positions: tuple[tuple[int, int], ...] = (),
) -> None:
    """テスト用の小さな VNP46A4 相当の HDF5 タイルを書き出す。

    **実ファイル（h28v06 の 2023 年版）の構造に合わせている**。合成バンドは
    float32 で `_FillValue = -999.9`、観測数は uint16 で 65535、オフセット属性の
    名前は `offset`（CF 規約の `add_offset` ではない）。想定に合わせた偽物にすると、
    想定違いをテストで検出できなくなる。

    Args:
        path: 出力パス。
        tile: タイル番号。
        scale_factor: SDS へ付与するスケール係数。
        offset: SDS へ付与するオフセット。実ファイルは 0.0 だが、換算式の
            符号・適用順を検証できるよう変えられるようにしている。
        include_bounding_coords: 境界座標のルート属性を付けるか。
        bounds_override: 境界座標を意図的にずらす場合の値。
        shape: 配列の形状 (行数, 列数)。既定は正方形。行と列の取り違えを
            検出したい場合に非正方形を渡す。
        extra_fill_positions: 追加で欠測にする画素の (行, 列)。ROI 内に欠測を
            置きたい場合に使う。
    """
    west, south, east, north = target.compute_tile_bounds(tile)
    bounds = bounds_override or {"west": west, "east": east, "north": north, "south": south}
    # 実ファイルに合わせた dtype と欠測値（合成バンドは float32、観測数は uint16）
    float_fill = np.float32(-999.9)
    count_fill = np.uint16(65535)

    with h5py.File(path, "w") as h5_file:
        if include_bounding_coords:
            for key, attribute_name in target.BOUNDING_COORD_ATTRIBUTES.items():
                h5_file.attrs[attribute_name] = np.float64(bounds[key])

        group = h5_file.create_group(target.SDS_GROUP_PATH)
        for index, band in enumerate(target.BAND_DEFINITIONS, start=1):
            is_count = band.sds_name.endswith("_Num")
            dtype = np.uint16 if is_count else np.float32
            fill_value = count_fill if is_count else float_fill
            values = np.full(shape, index * 10, dtype=dtype)
            # 1 画素だけ欠測を置き、_FillValue の扱いを検証できるようにする
            values[0, 0] = fill_value
            for row, column in extra_fill_positions:
                values[row, column] = fill_value
            dataset = group.create_dataset(band.sds_name, data=values)
            dataset.attrs["scale_factor"] = np.array([scale_factor], dtype=np.float64)
            # 実ファイルの属性名は offset（add_offset ではない）
            dataset.attrs["offset"] = np.array([offset], dtype=np.float64)
            dataset.attrs["_FillValue"] = np.array([fill_value], dtype=dtype)
            dataset.attrs["units"] = np.bytes_(b"nWatts/(cm^2 sr)")
            dataset.attrs["long_name"] = np.bytes_(band.sds_name.encode())


class TestResolveBlackMarbleTiles:
    """resolve_black_marble_tiles のテスト。"""

    def test_hanoi_roi_fits_in_a_single_tile(self) -> None:
        """Hanoi ROI は h28v06 の 1 タイルに収まる。"""
        tiles = target.resolve_black_marble_tiles(HANOI_ROI_BOUNDS)

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_tile_name_is_zero_padded(self) -> None:
        """タイル名は 2 桁ゼロ詰め（配布ファイル名と一致させるため）。"""
        assert target.TileIndex(horizontal=3, vertical=7).name == "h03v07"

    def test_spans_multiple_tiles_when_bbox_crosses_boundary(self) -> None:
        """タイル境界をまたぐ BBOX では、はみ出した先のタイルも含めて返す。

        経度 99.5-110.5 は h27（90-100E）・h28（100-110E）・h29（110-120E）に、
        緯度 19.5-30.5 は v05（30-40N）・v06（20-30N）・v07（10-20N）にまたがる。
        並び順は北西から南東（v の昇順 → h の昇順）。
        """
        tiles = target.resolve_black_marble_tiles((99.5, 19.5, 110.5, 30.5))

        assert [tile.name for tile in tiles] == [
            "h27v05",
            "h28v05",
            "h29v05",
            "h27v06",
            "h28v06",
            "h29v06",
            "h27v07",
            "h28v07",
            "h29v07",
        ]

    def test_east_edge_on_tile_boundary_does_not_add_empty_tile(self) -> None:
        """東端がちょうどタイル境界の場合、重なりの無い隣のタイルを拾わない。"""
        tiles = target.resolve_black_marble_tiles((100.0, 20.0, 110.0, 30.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_south_edge_on_tile_boundary_does_not_add_empty_tile(self) -> None:
        """南端がちょうどタイル境界の場合も同様。"""
        tiles = target.resolve_black_marble_tiles((100.5, 20.0, 100.6, 21.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_northwest_corner_maps_to_first_tile(self) -> None:
        """グリッド原点（-180E, 90N）は h00v00。"""
        tiles = target.resolve_black_marble_tiles((-180.0, 85.0, -179.0, 90.0))

        assert [tile.name for tile in tiles] == ["h00v00"]

    def test_southeast_corner_maps_to_last_tile(self) -> None:
        """南東端（180E, -90N）は h35v17（範囲外の索引を作らない）。"""
        tiles = target.resolve_black_marble_tiles((179.0, -90.0, 180.0, -89.0))

        assert [tile.name for tile in tiles] == ["h35v17"]

    def test_degenerate_bbox_still_returns_one_tile(self) -> None:
        """幅・高さが 0 の BBOX でも 1 タイルは返す（空リストにしない）。"""
        tiles = target.resolve_black_marble_tiles((105.8, 21.0, 105.8, 21.0))

        assert [tile.name for tile in tiles] == ["h28v06"]

    def test_degenerate_bbox_at_grid_maximum_still_returns_one_tile(self) -> None:
        """経度 180・緯度 -90 ちょうどの縮退 BBOX でも空リストにしない。

        この位置では索引式が索引上限を 1 超えるため、丸め方を誤ると開始 > 終了と
        なり空リストになる。呼び出し側は `tiles[0]` を取るので、素の IndexError に
        化けて原因が読めなくなる。
        """

        def tile_names(bounds: tuple[float, float, float, float]) -> list[str]:
            """指定 BBOX を覆うタイル名の一覧を返す。"""
            return [tile.name for tile in target.resolve_black_marble_tiles(bounds)]

        assert tile_names((180.0, -90.0, 180.0, -90.0)) == ["h35v17"]
        assert tile_names((180.0, 20.0, 180.0, 21.0)) == ["h35v06"]
        assert tile_names((105.0, -90.0, 106.0, -90.0)) == ["h28v17"]

    def test_rejects_out_of_range_bbox(self) -> None:
        """経緯度の値域を外れる BBOX は弾く。"""
        with pytest.raises(ValueError, match="値域"):
            target.resolve_black_marble_tiles((105.0, 20.0, 190.0, 21.0))


class TestComputeTileBounds:
    """compute_tile_bounds のテスト。"""

    def test_hanoi_tile_covers_expected_range(self) -> None:
        """h28v06 は経度 100-110E・緯度 20-30N を覆う。"""
        bounds = target.compute_tile_bounds(target.TileIndex(28, 6))

        assert bounds == pytest.approx((100.0, 20.0, 110.0, 30.0))

    def test_origin_tile_starts_at_grid_origin(self) -> None:
        """h00v00 は北西端の原点から始まる。"""
        bounds = target.compute_tile_bounds(target.TileIndex(0, 0))

        assert bounds == pytest.approx((-180.0, 80.0, -170.0, 90.0))

    def test_roi_is_contained_in_resolved_tile(self) -> None:
        """解決したタイルが実際に ROI を包含する（索引式の符号ミスを検出する）。"""
        tile = target.resolve_black_marble_tiles(HANOI_ROI_BOUNDS)[0]
        west, south, east, north = target.compute_tile_bounds(tile)

        assert west <= HANOI_ROI_BOUNDS[0] and HANOI_ROI_BOUNDS[2] <= east
        assert south <= HANOI_ROI_BOUNDS[1] and HANOI_ROI_BOUNDS[3] <= north


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
        """認証ヘッダーを取得処理へ渡す。"""
        recorded: dict[str, Any] = {}

        def fake_fetch(url: str, timeout: int, headers: dict[str, str]) -> bytes:
            recorded["url"] = url
            recorded["headers"] = headers
            return b'{"content": []}'

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)

        target.fetch_tile_listing(2023, {"Authorization": "Bearer t"})

        assert recorded["headers"] == {"Authorization": "Bearer t"}
        assert "/5200/VNP46A4/2023/001" in recorded["url"]


class TestExtractListingEntries:
    """extract_listing_entries のテスト。"""

    @staticmethod
    def _entry(name: str) -> dict[str, Any]:
        """LAADS の実レスポンスに合わせたエントリを作る。"""
        return {
            "name": name,
            "downloadsLink": f"https://example.invalid/api/v2/content/archives/{name}",
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
        return target.TileFile(name=name, download_url=f"https://example.invalid/{name}")

    def test_selects_file_for_requested_tile(self) -> None:
        """タイル名を含むファイルを選ぶ。"""
        tile_files = [
            self._tile_file("VNP46A4.A2023001.h28v06.002.2025162082259.h5"),
            self._tile_file("VNP46A4.A2023001.h29v06.002.2025162082259.h5"),
        ]

        selected = target.select_tile_files(tile_files, [target.TileIndex(28, 6)])

        assert selected["h28v06"].name == "VNP46A4.A2023001.h28v06.002.2025162082259.h5"

    def test_does_not_match_tile_name_as_substring(self) -> None:
        """区切りのドットを含めて照合する（h28v06 が h28v060 等に誤マッチしない）。"""
        tile_files = [self._tile_file("VNP46A4.A2023001.h28v060.002.2024032.h5")]

        with pytest.raises(RuntimeError, match="一覧にありません"):
            target.select_tile_files(tile_files, [target.TileIndex(28, 6)])

    def test_raises_when_tile_is_missing(self) -> None:
        """必要なタイルが無ければ例外にする。"""
        tile_files = [self._tile_file("VNP46A4.A2023001.h29v06.002.x.h5")]

        with pytest.raises(RuntimeError, match="一覧にありません"):
            target.select_tile_files(tile_files, [target.TileIndex(28, 6)])

    def test_raises_when_multiple_versions_exist(self) -> None:
        """同一タイルの版が複数あれば、どちらを使ったか不明になるため止める。"""
        tile_files = [
            self._tile_file("VNP46A4.A2023001.h28v06.002.2024032.h5"),
            self._tile_file("VNP46A4.A2023001.h28v06.002.2025100.h5"),
        ]

        with pytest.raises(RuntimeError, match="複数あります"):
            target.select_tile_files(tile_files, [target.TileIndex(28, 6)])


class TestValidateYear:
    """validate_year のテスト。"""

    def test_accepts_landsat_observation_year(self) -> None:
        """本研究の観測年は通す。"""
        target.validate_year(2023)

    def test_rejects_year_before_first_available(self) -> None:
        """提供開始年より前は弾く。"""
        with pytest.raises(ValueError, match="2012 年から"):
            target.validate_year(2011)

    def test_rejects_future_year(self) -> None:
        """未来の年は弾く。"""
        with pytest.raises(ValueError, match="未来の年"):
            target.validate_year(2999)


class TestReadScaledSds:
    """read_scaled_sds のテスト。"""

    def test_applies_scale_factor_from_attributes(self, tmp_path: Path) -> None:
        """スケール係数は属性から実測して適用する（決め打ちしない）。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6), scale_factor=0.25)

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        # 第1バンドの生値は 10、スケール 0.25 → 2.5
        assert applied["scale_factor"] == pytest.approx(0.25)
        assert values[1, 1] == pytest.approx(2.5)

    def test_applies_offset_from_attributes(self, tmp_path: Path) -> None:
        """オフセットも属性から実測し、`生値 * scale + offset` の順で適用する。

        実ファイルの offset は 0.0 のため、0 のままでは符号・適用順の取り違え
        （NASA 系にある `(生値 - offset) * scale` との混同）を検出できない。
        """
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6), scale_factor=0.5, offset=3.0)

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        # 第1バンドの生値は 10 → 10 * 0.5 + 3.0 = 8.0
        assert applied["offset"] == pytest.approx(3.0)
        assert applied["offset_attribute"] == "offset"
        assert values[1, 1] == pytest.approx(8.0)

    def test_falls_back_to_add_offset_attribute_name(self, tmp_path: Path) -> None:
        """CF 規約の `add_offset` しか持たない版でも読める。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6), offset=2.0)
        with h5py.File(tile_path, "a") as h5_file:
            dataset = h5_file[target.SDS_GROUP_PATH]["NearNadir_Composite_Snow_Free"]
            dataset.attrs["add_offset"] = dataset.attrs["offset"]
            del dataset.attrs["offset"]

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["offset_attribute"] == "add_offset"
        assert applied["defaulted_attributes"] == []
        assert values[1, 1] == pytest.approx(12.0)

    def test_replaces_fill_value_with_nodata(self, tmp_path: Path) -> None:
        """欠測値は共通の nodata へ置き換える（スケール適用後の値にしない）。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert values[0, 0] == target.OUTPUT_NODATA
        assert applied["fill_pixels"] == 1

    def test_records_units_and_long_name(self, tmp_path: Path) -> None:
        """単位・説明の属性も記録する（サマリーへ残すため）。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["units"] == "nWatts/(cm^2 sr)"
        assert applied["long_name"] == "NearNadir_Composite_Snow_Free"

    def test_raises_with_available_names_when_sds_missing(self, tmp_path: Path) -> None:
        """想定した SDS が無ければ、実在する名前を添えて例外にする。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            with pytest.raises(KeyError, match="NearNadir_Composite_Snow_Free"):
                target.read_scaled_sds(h5_file, "Renamed_In_A_Future_Version")


class TestVerifyTileGeoreference:
    """verify_tile_georeference のテスト。"""

    def test_accepts_matching_bounds(self) -> None:
        """属性とタイル番号由来の境界が一致すれば通す。"""
        tile = target.TileIndex(28, 6)
        attributes = {
            "WestBoundingCoord": 100.0,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        result = target.verify_tile_georeference(attributes, tile)

        assert result["tile"] == "h28v06"

    def test_rejects_mismatched_bounds(self) -> None:
        """食い違えば、タイル番号の読み違いを疑って止める。"""
        tile = target.TileIndex(28, 6)
        attributes = {
            "WestBoundingCoord": 110.0,
            "EastBoundingCoord": 120.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        with pytest.raises(ValueError, match="一致しません"):
            target.verify_tile_georeference(attributes, tile)

    def test_accepts_difference_within_tolerance(self) -> None:
        """許容差の内側のずれは通す（丸め誤差で止まらないことの担保）。"""
        attributes = {
            "WestBoundingCoord": 100.0 + target.GEOREFERENCE_TOLERANCE_DEG / 2,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        result = target.verify_tile_georeference(attributes, target.TileIndex(28, 6))

        assert result["tile"] == "h28v06"

    def test_rejects_difference_over_tolerance(self) -> None:
        """許容差を超えるずれは、値が近くても弾く。"""
        attributes = {
            "WestBoundingCoord": 100.0 + target.GEOREFERENCE_TOLERANCE_DEG * 10,
            "EastBoundingCoord": 110.0,
            "NorthBoundingCoord": 30.0,
            "SouthBoundingCoord": 20.0,
        }

        with pytest.raises(ValueError, match="一致しません"):
            target.verify_tile_georeference(attributes, target.TileIndex(28, 6))

    def test_raises_when_attributes_are_missing(self) -> None:
        """境界座標の属性が欠けていれば例外にする。"""
        with pytest.raises(KeyError, match="BoundingCoord"):
            target.verify_tile_georeference({"WestBoundingCoord": 100.0}, target.TileIndex(28, 6))


class TestWriteTileGeotiff:
    """write_tile_geotiff のテスト。"""

    def test_writes_all_bands_with_tile_georeference(self, tmp_path: Path) -> None:
        """タイル番号から組み立てたジオリファレンスで全バンドを書き出す。"""
        tile = target.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, tile)

        output_path, metadata = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            assert raster.count == len(target.BAND_DEFINITIONS)
            assert raster.crs.to_epsg() == 4326
            assert raster.descriptions == tuple(
                band.output_name for band in target.BAND_DEFINITIONS
            )
            assert raster.bounds.left == pytest.approx(100.0)
            assert raster.bounds.top == pytest.approx(30.0)
            assert raster.bounds.right == pytest.approx(110.0)
            assert raster.bounds.bottom == pytest.approx(20.0)
        assert metadata["pixel_size_deg"] == pytest.approx(target.TILE_SIZE_DEG / FAKE_TILE_PIXELS)

    def test_band_order_matches_definitions(self, tmp_path: Path) -> None:
        """SDS の並びが定義順のまま出力バンドへ対応する（取り違えの検出）。"""
        tile = target.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, tile, scale_factor=1.0)

        output_path, _ = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            for index in range(1, len(target.BAND_DEFINITIONS) + 1):
                values = raster.read(index)
                # 合成タイルは第 n バンドを一律 n*10 で埋めてある（欠測の 1 画素を除く）
                assert values[1, 1] == pytest.approx(index * 10)

    def test_non_square_tile_keeps_row_and_column_order(self, tmp_path: Path) -> None:
        """行数と列数が異なっても、行=緯度方向・列=経度方向の対応が崩れない。

        実ファイルは 2400×2400 の正方形のため、正方形だけで検証していると
        行と列の取り違え（経度・緯度分解能の入れ替え）が素通りする。
        """
        tile = target.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, tile, shape=(10, 20))

        output_path, metadata = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            assert (raster.height, raster.width) == (10, 20)
            # タイルは常に 10°×10°。列 20 なら経度 0.5°/画素、行 10 なら緯度 1.0°/画素
            assert raster.transform.a == pytest.approx(0.5)
            assert raster.transform.e == pytest.approx(-1.0)
            assert raster.bounds.right == pytest.approx(110.0)
            assert raster.bounds.bottom == pytest.approx(20.0)
        assert metadata["tile_shape"] == [10, 20]

    def test_rejects_tile_whose_attributes_disagree(self, tmp_path: Path) -> None:
        """属性の境界座標がタイル番号と食い違うファイルは変換しない。"""
        tile = target.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(
            tile_path,
            tile,
            bounds_override={"west": 110.0, "east": 120.0, "north": 30.0, "south": 20.0},
        )

        with pytest.raises(ValueError, match="一致しません"):
            target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")


class TestDescribeHdf5Structure:
    """describe_hdf5_structure のテスト。"""

    def test_lists_datasets_and_attributes(self, tmp_path: Path) -> None:
        """SDS 名・形状・属性を読み取れる。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        structure = target.describe_hdf5_structure(tile_path)

        assert "NearNadir_Composite_Snow_Free" in structure["datasets"]
        entry = structure["datasets"]["NearNadir_Composite_Snow_Free"]
        assert entry["shape"] == [FAKE_TILE_PIXELS, FAKE_TILE_PIXELS]
        assert entry["attributes"]["scale_factor"] == pytest.approx(1.0)
        assert structure["root_attributes"]["WestBoundingCoord"] == pytest.approx(100.0)

    def test_result_is_json_serializable(self, tmp_path: Path) -> None:
        """HDF5 の属性型が JSON へ書ける形に変換されている。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        json.dumps(target.describe_hdf5_structure(tile_path), ensure_ascii=False)

    def test_raises_when_group_is_absent(self, tmp_path: Path) -> None:
        """SDS グループが無ければ、ルートのキーを添えて例外にする。"""
        tile_path = tmp_path / "empty.h5"
        with h5py.File(tile_path, "w") as h5_file:
            h5_file.create_group("Unexpected")

        with pytest.raises(KeyError, match="Unexpected"):
            target.describe_hdf5_structure(tile_path)


class TestDownloadTile:
    """download_tile のテスト。"""

    # 保存前の検証を通る最小の中身（HDF5 の署名で始まるバイト列）
    TILE_BODY = target.HDF5_SIGNATURE + b"NEW-TILE"

    @classmethod
    def _tile_file(cls, size_bytes: int | None = None) -> target.TileFile:
        """テスト用のファイル情報を作る。

        Args:
            size_bytes: 一覧が返すサイズ。既定では `TILE_BODY` と整合する値にする。
        """
        return target.TileFile(
            name="tile.h5",
            download_url="https://example.invalid/api/v2/content/archives/tile.h5",
            size_bytes=len(cls.TILE_BODY) if size_bytes is None else size_bytes,
        )

    def test_reuses_cached_tile_without_network_access(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既に取得済みなら再ダウンロードしない（100MB 超の無駄打ちを避ける）。"""
        cached = tmp_path / "tile.h5"
        cached.write_bytes(self.TILE_BODY)

        def fail_if_called(*args: Any, **kwargs: Any) -> bytes:
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

        def fake_fetch(url: str, timeout: int, headers: dict[str, str]) -> bytes:
            recorded["url"] = url
            recorded["headers"] = headers
            return self.TILE_BODY

        monkeypatch.setattr(target, "fetch_bytes_with_retry", fake_fetch)

        target.download_tile(
            self._tile_file(), tmp_path / "tile.h5", headers={"Authorization": "Bearer t"}
        )

        assert recorded["url"] == "https://example.invalid/api/v2/content/archives/tile.h5"
        assert recorded["headers"] == {"Authorization": "Bearer t"}

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
        tile_file = target.TileFile(
            name="tile.h5", download_url="https://example.invalid/tile.h5", size_bytes=None
        )

        result = target.download_tile(tile_file, tmp_path / "tile.h5", headers={})

        assert result.read_bytes() == self.TILE_BODY

    def test_reports_license_gate_with_actionable_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ライセンス未同意が原因なら、同意ページの URL を添えて投げ直す。

        素の失敗は「リダイレクト先の Earthdata で 401」となり原因が読み取れない。
        """

        def raise_runtime_error(*args: Any, **kwargs: Any) -> bytes:
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
            raise RuntimeError("リクエストが3回失敗しました")

        monkeypatch.setattr(target, "fetch_bytes_with_retry", raise_runtime_error)
        monkeypatch.setattr(target, "find_license_gate", lambda url, headers: None)
        destination = tmp_path / "tile.h5"

        with pytest.raises(RuntimeError):
            target.download_tile(self._tile_file(), destination, headers={})

        assert not destination.exists()
        assert not destination.with_suffix(".h5.part").exists()


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_builds_default_paths_from_year(self) -> None:
        """既定では年つきのファイル名になる。"""
        output_path, summary_path = target.resolve_output_paths(2023, None, None)

        assert output_path.parent.name == "black_marble"
        assert output_path.name == "black_marble_vnp46a4_hanoi_2023.tif"
        assert summary_path.name == (
            "nighttime_lights_black_marble_vnp46a4_hanoi_2023_summary.json"
        )

    def test_trial_run_gets_distinct_filename(self) -> None:
        """試行実行では ROI 全域の成果物を上書きしないよう _trial を付ける。"""
        production_path, _ = target.resolve_output_paths(2023, None, None, is_trial=False)
        trial_path, _ = target.resolve_output_paths(2023, None, None, is_trial=True)

        assert trial_path.name == "black_marble_vnp46a4_hanoi_2023_trial.tif"
        assert trial_path != production_path


class TestBuildSummary:
    """build_summary のテスト。"""

    @staticmethod
    def _build(year: int = 2023) -> dict[str, Any]:
        """最小限の入力でサマリーを組み立てる。"""
        return target.build_summary(
            year=year,
            roi_path=Path("data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp"),
            is_trial=False,
            area_bounds=HANOI_ROI_BOUNDS,
            tiles=[target.TileIndex(28, 6)],
            tile_files={
                "h28v06": target.TileFile(
                    name="VNP46A4.A2023001.h28v06.002.x.h5",
                    download_url="https://example.invalid/api/v2/content/archives/x.h5",
                    size_bytes=119818130,
                )
            },
            tile_metadata={"tile_shape": [2400, 2400]},
            raster_profile={"crs": "EPSG:4326"},
            pixel_stats={"valid_pixel_ratio": 1.0},
            output_path=Path("data/gis/nighttime_lights/black_marble/x.tif"),
            summary_path=Path("data/output/open_gis/x_summary.json"),
            retrieved_at="2026-07-27T00:00:00+00:00",
        )

    def test_records_access_route_and_license(self) -> None:
        """GEE に無く LAADS 経由である旨とライセンスを記録する。"""
        summary = self._build()

        assert summary["archive_set"] == "5200"
        assert "Google Earth Engine に存在せず" in summary["access_note"]
        assert "Earthdata" in summary["license_note"]

    def test_records_tiles_used(self) -> None:
        """使用したタイルと実ファイル名を記録する（再現性のため）。"""
        summary = self._build()

        assert summary["tiles"] == ["h28v06"]
        assert summary["tile_files"]["h28v06"]["name"].endswith(".h5")
        # 再取得の経路を辿れるよう、実際に使った URL も残す
        assert "/api/v2/content/archives/" in summary["tile_files"]["h28v06"]["download_url"]

    def test_records_scaling_provenance(self) -> None:
        """スケール係数を属性から実測した旨を記録する。"""
        summary = self._build()

        assert "決め打ちしていない" in summary["scaling_note"]

    def test_records_pixel_statistics(self) -> None:
        """受け取った画素統計をサマリーへ載せる。

        欠けても他のキーは揃うため、キーを個別に見るテストだけでは気づけない。
        統計はこのサマリーの主目的なので、存在自体を固定する。
        """
        summary = self._build()

        assert summary["pixel_stats"] == {"valid_pixel_ratio": 1.0}

    def test_notes_no_time_gap_for_landsat_year(self) -> None:
        """観測年と一致する年では時間差なしと記録する。"""
        assert "時間差はない" in self._build(2023)["year_note"]

    def test_notes_time_gap_for_other_years(self) -> None:
        """観測年と異なる年では時間差を明記する。"""
        assert "3 年の時間差" in self._build(2020)["year_note"]

    def test_band_definitions_record_source_sds(self) -> None:
        """各バンドの由来 SDS を記録する。"""
        summary = self._build()

        assert summary["bands"]["1"]["name"] == "ntl_near_nadir"
        assert summary["bands"]["1"]["source_sds"] == "NearNadir_Composite_Snow_Free"

    def test_is_json_serializable(self) -> None:
        """サマリーがそのまま JSON へ書き出せる。"""
        json.dumps(self._build(), ensure_ascii=False, allow_nan=False)


class TestRunGuards:
    """run の事前チェックのテスト（ネットワークへ出る前に止まること）。"""

    def test_rejects_unavailable_year_before_token_lookup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """提供年外の指定は、トークン解決より前に弾く。"""

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            raise AssertionError("提供年外の指定でトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(ValueError, match="2012 年から"):
            target.run(
                year=2010,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=True,
            )

    def test_refuses_to_overwrite_existing_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既存の出力があり --overwrite が無ければ、取得を始める前に止める。"""
        existing_output = tmp_path / "existing.tif"
        existing_output.write_bytes(b"IMPORTANT")
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            raise AssertionError("既存ファイルがある場合はトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(FileExistsError, match="--overwrite"):
            target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=existing_output,
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=False,
            )

        assert existing_output.read_bytes() == b"IMPORTANT"

    def test_stops_when_multiple_tiles_are_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """複数タイルが要る範囲では、部分的な成果物を作らず明示的に止める。"""
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area((99.0, 19.0, 111.0, 31.0))
        )

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            raise AssertionError("タイル結合が必要な場合はトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(NotImplementedError, match="複数タイルの結合"):
            target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=True,
            )


class TestRunEndToEnd:
    """run の統合テスト（ネットワーク・HDF5 の取得はモックする）。

    `write_tile_geotiff` → `clip_multiband_to_area` →
    `build_multiband_pixel_statistics` → `build_summary` → `save_summary` →
    `log_results` の接合部を一度通す。とくに `log_results` は `save_summary` の
    後に走るため、ここが壊れていると 100MB 超のダウンロードと全処理を終えた
    あとで初めて失敗する。
    """

    # h28v06（経度 100-110E・緯度 20-30N）に収まり、合成タイルで複数画素になる範囲
    AREA_BOUNDS = (105.0, 21.0, 107.0, 23.0)

    def _install_fakes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        extra_fill_positions: tuple[tuple[int, int], ...] = (),
    ) -> None:
        """範囲組み立て・認証・一覧・ダウンロードを差し替える。

        Args:
            monkeypatch: pytest の monkeypatch フィクスチャ。
            extra_fill_positions: 合成タイルで追加の欠測にする画素の (行, 列)。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(self.AREA_BOUNDS)
        )
        monkeypatch.setattr(target, "resolve_earthdata_token", lambda token_file=None: "t")

        file_name = "VNP46A4.A2023001.h28v06.002.2025162082259.h5"
        monkeypatch.setattr(
            target,
            "fetch_tile_listing",
            lambda year, headers: {
                "content": [
                    {
                        "name": file_name,
                        "downloadsLink": f"https://example.invalid/api/v2/content/archives/{file_name}",
                        "size": 119818130,
                    }
                ]
            },
        )

        def fake_download(
            tile_file: target.TileFile, destination_path: Path, headers: dict[str, str]
        ) -> Path:
            """配布物の代わりに合成 HDF5 タイルを置く。"""
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            _write_fake_tile(
                destination_path,
                target.TileIndex(28, 6),
                extra_fill_positions=extra_fill_positions,
            )
            return destination_path

        monkeypatch.setattr(target, "download_tile", fake_download)

    def test_writes_raster_and_summary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """取得から保存までを通しで実行し、GeoTIFF とサマリーが揃う。"""
        cache_dir = tmp_path / "cache"
        self._install_fakes(monkeypatch)

        output_path, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=cache_dir,
            token_file=None,
            overwrite=True,
        )

        with rasterio.open(output_path) as raster:
            assert raster.count == len(target.BAND_DEFINITIONS)
            assert raster.crs.to_epsg() == 4326
            assert raster.descriptions == tuple(
                band.output_name for band in target.BAND_DEFINITIONS
            )
            assert raster.nodata == target.OUTPUT_NODATA

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["dataset_key"] == "black_marble_vnp46a4"
        assert summary["year"] == 2023
        assert summary["tiles"] == ["h28v06"]
        assert summary["pixel_stats"]["covers_requested_area"] is True

    def test_summary_records_saturation_for_radiance_bands(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """飽和指標が放射輝度バンドにだけ入る（log_results が参照するキーの担保）。

        log_results は save_summary の後に走るため、参照キーがずれていると
        全処理を終えた後に KeyError で落ちる。ここで実際に通しておく。
        """
        self._install_fakes(monkeypatch)

        _, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        saturation = json.loads(summary_path.read_text(encoding="utf-8"))["pixel_stats"][
            "saturation"
        ]
        expected = {band.output_name for band in target.BAND_DEFINITIONS if band.is_radiance}
        assert set(saturation) == expected
        for indicators in saturation.values():
            # log_results が参照するキーが揃っていること
            assert {
                "p99_to_max_ratio",
                "pixels_at_max",
                "pixels_near_max",
                "ratio_near_max",
            } <= set(indicators)

    def test_applies_scale_factor_from_the_tile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """タイル属性のスケール係数が最終出力まで反映される。"""
        self._install_fakes(monkeypatch)

        output_path, _ = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        with rasterio.open(output_path) as raster:
            # 合成タイルは第1バンドを 10 で埋めており、scale_factor は 1.0
            values = raster.read(1)
            assert values[values != target.OUTPUT_NODATA].max() == pytest.approx(10.0)

    def test_missing_pixels_inside_area_lower_the_valid_ratio(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """範囲内に欠測があれば有効画素率が 1 を下回り、警告も出る。

        実データ（Hanoi ROI 2023）は有効画素率 1.0000 だったため、この経路は
        実行時に一度も踏んでいない。有効域を ROI 全体と同一視しないための
        指標が欠測時にも正しく動くことを、ここで固定する。

        合成タイルは 20×20（1 画素 0.5°）で、(行 15, 列 11) の画素中心は
        経度 105.75 / 緯度 22.25 にあたり、対象範囲の内側に入る。
        """
        self._install_fakes(monkeypatch, extra_fill_positions=((15, 11),))

        with caplog.at_level(logging.WARNING):
            _, summary_path = target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "out_summary.json",
                cache_dir=tmp_path / "cache",
                token_file=None,
                overwrite=True,
            )

        pixel_stats = json.loads(summary_path.read_text(encoding="utf-8"))["pixel_stats"]
        assert pixel_stats["valid_pixels"] == pixel_stats["roi_pixels"] - 1
        assert pixel_stats["valid_pixel_ratio"] < 1.0
        # 範囲は覆えているが値が欠けている、という区別が付くこと
        assert pixel_stats["covers_requested_area"] is True
        assert "無効画素" in caplog.text

    def test_trial_run_marks_summary_and_uses_distinct_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BBOX 指定時は試行実行として記録され、既定パスに _trial が付く。"""
        self._install_fakes(monkeypatch)
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_ROOT", tmp_path / "gis" / "black_marble")

        output_path, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=[105.0, 21.0, 106.0, 22.0],
            output_path=None,
            summary_path=tmp_path / "trial_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        assert output_path.name == "black_marble_vnp46a4_hanoi_2023_trial.tif"
        assert output_path.is_relative_to(tmp_path)
        assert json.loads(summary_path.read_text(encoding="utf-8"))["is_trial_run"] is True


class TestFindLicenseGate:
    """find_license_gate のテスト（ネットワークへは出ない）。

    このスクリプト固有の価値は「ライセンス未同意を切り分けて伝える」ことにある。
    ここが黙って None を返すと、利用者は原因の分からない 401 に戻される。
    """

    @staticmethod
    def _install_opener(monkeypatch: pytest.MonkeyPatch, raiser: Any) -> None:
        """`build_opener` を差し替え、`open` の挙動を差し込む。"""

        class _FakeOpener:
            def open(self, request: Any, timeout: int) -> Any:
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
            raise self._http_error("/oauth/login?redirect=%2Fx")

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://example.invalid/x.h5", {}) is None

    def test_returns_none_when_location_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Location が無いエラー（401 等）でも落ちずに None を返す。"""

        def raiser() -> Any:
            raise self._http_error(None, code=401)

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://example.invalid/x.h5", {}) is None

    def test_returns_none_when_request_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """そもそも成功する URL ならライセンスは原因ではない。"""

        class _FakeResponse:
            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, *exc_info: object) -> None:
                return None

        self._install_opener(monkeypatch, lambda: _FakeResponse())

        assert target.find_license_gate("https://example.invalid/x.h5", {}) is None

    def test_returns_none_on_connection_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """切り分けの補助なので、ここでの通信失敗は握って元エラーを優先する。"""

        def raiser() -> Any:
            raise target.urllib.error.URLError("unreachable")

        self._install_opener(monkeypatch, raiser)

        assert target.find_license_gate("https://example.invalid/x.h5", {}) is None


class TestRunInspection:
    """run_inspection のテスト。"""

    def test_finds_cached_tile_by_actual_file_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """glob パターンが実際の配布ファイル名に一致する。

        実名は `VNP46A4.A2023001.h28v06.002.2025162082259.h5` で、生成日時部分は
        事前に分からない。パターンがずれるとキャッシュ済みでも「無い」と言われる。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        tile_path = cache_dir / "VNP46A4.A2023001.h28v06.002.2025162082259.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        target.run_inspection(
            year=2023, cache_dir=cache_dir, roi_path=tmp_path / "roi.shp", bbox=None
        )

        printed = json.loads(capsys.readouterr().out)
        assert "NearNadir_Composite_Snow_Free" in printed["datasets"]

    def test_raises_with_search_pattern_when_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """見つからない場合は、探索したパターンを添えて例外にする。"""
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )

        with pytest.raises(FileNotFoundError, match="h28v06"):
            target.run_inspection(
                year=2023, cache_dir=tmp_path, roi_path=tmp_path / "roi.shp", bbox=None
            )

    def test_warns_when_multiple_tiles_are_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """複数タイルが要る範囲では、先頭だけを見ることを明示する。

        取得側は同じ状況を NotImplementedError で止めるため、検査側だけ黙って
        絞ると挙動が食い違う。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area((99.0, 19.0, 111.0, 31.0))
        )

        with caplog.at_level(logging.WARNING):
            with pytest.raises(FileNotFoundError):
                target.run_inspection(
                    year=2023, cache_dir=tmp_path, roi_path=tmp_path / "roi.shp", bbox=None
                )

        assert "先頭" in caplog.text


class TestReadScaledSdsMissingAttributes:
    """属性が欠けた SDS の扱いのテスト。

    属性名が配布バージョンで変わると、換算がずれたまま最後まで通ってしまう
    （実ファイルの `scale_factor` は 1.0 だが、これも実測して初めて分かった値で、
    事前の想定 0.1 は外れていた）。既定値で代用した事実が記録に残ることを固定する。
    """

    @staticmethod
    def _write_tile_without_attributes(path: Path, tile: target.TileIndex) -> None:
        """スケール・欠測値の属性を持たない合成タイルを書き出す。"""
        west, south, east, north = target.compute_tile_bounds(tile)
        bounds = {"west": west, "east": east, "north": north, "south": south}
        with h5py.File(path, "w") as h5_file:
            for key, attribute_name in target.BOUNDING_COORD_ATTRIBUTES.items():
                h5_file.attrs[attribute_name] = np.float64(bounds[key])
            group = h5_file.create_group(target.SDS_GROUP_PATH)
            for index, band in enumerate(target.BAND_DEFINITIONS, start=1):
                group.create_dataset(
                    band.sds_name,
                    data=np.full((FAKE_TILE_PIXELS, FAKE_TILE_PIXELS), index * 10, dtype=np.uint16),
                )

    def test_records_defaulted_attributes(self, tmp_path: Path) -> None:
        """欠けた属性名を記録に残す。"""
        tile_path = tmp_path / "tile.h5"
        self._write_tile_without_attributes(tile_path, target.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["defaulted_attributes"] == ["scale_factor", "offset", "_FillValue"]

    def test_records_nothing_when_attributes_are_present(self, tmp_path: Path) -> None:
        """属性が揃っていれば記録は空になる。"""
        tile_path = tmp_path / "tile.h5"
        _write_fake_tile(tile_path, target.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["defaulted_attributes"] == []


class TestCollectAttributeWarnings:
    """collect_attribute_warnings のテスト。"""

    def test_lists_defaulted_attributes_per_band(self) -> None:
        """バンドごとの欠落属性を人が読める形にする。"""
        metadata = {
            "band_attributes": {
                "ntl_near_nadir": {"defaulted_attributes": ["scale_factor"]},
                "near_nadir_num": {"defaulted_attributes": []},
            }
        }

        warnings = target.collect_attribute_warnings(metadata)

        assert len(warnings) == 1
        assert "ntl_near_nadir" in warnings[0]
        assert "scale_factor" in warnings[0]

    def test_returns_empty_when_all_attributes_present(self) -> None:
        """欠落が無ければ空リスト（サマリー上で「問題なし」と読める）。"""
        metadata = {"band_attributes": {"ntl_near_nadir": {"defaulted_attributes": []}}}

        assert target.collect_attribute_warnings(metadata) == []

    def test_tolerates_missing_metadata(self) -> None:
        """メタデータが欠けていても落ちない。"""
        assert target.collect_attribute_warnings({}) == []
