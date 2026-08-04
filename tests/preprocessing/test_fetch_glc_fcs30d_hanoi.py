"""fetch_glc_fcs30d_hanoi.py（GLC_FCS30D 取得スクリプト）のテスト。

ネットワークアクセスを伴わない純粋関数を対象とする。Zenodo API 呼び出しは
モックに差し替えて検証する。
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.common.config import LANDSAT_OBSERVATION_YEAR
from src.common.raster_classes import build_class_distribution
from src.preprocessing import fetch_glc_fcs30d_hanoi as target
from tests.helpers import HANOI_ROI_BOUNDS


class TestBandIndexForYear:
    """band_index_for_year のテスト。"""

    @pytest.mark.parametrize(
        ("year", "expected_band_index"),
        [(2000, 1), (2001, 2), (2015, 16), (2022, 23)],
    )
    def test_maps_year_to_band_index(self, year: int, expected_band_index: int) -> None:
        """2000年をバンド1として、年とバンド番号が1対1で対応する。"""
        assert target.band_index_for_year(year) == expected_band_index

    @pytest.mark.parametrize("year", [1999, 2023, 1985, 0])
    def test_rejects_year_outside_dataset_range(self, year: int) -> None:
        """データセットが提供しない年は ValueError になる。"""
        with pytest.raises(ValueError, match="年次マップ"):
            target.band_index_for_year(year)


class TestTileNamesForBounds:
    """tile_names_for_bounds のテスト。"""

    def test_hanoi_roi_fits_in_single_tile(self) -> None:
        """Hanoi ROI の実測 BBOX は E105N25 の単一タイルに収まる。"""
        assert target.tile_names_for_bounds(HANOI_ROI_BOUNDS) == ["E105N25"]

    def test_bounds_spanning_two_tiles_horizontally(self) -> None:
        """経度方向にタイル境界をまたぐ BBOX は2タイルを返す。"""
        assert target.tile_names_for_bounds((104.5, 20.5, 106.5, 21.0)) == ["E100N25", "E105N25"]

    def test_bounds_spanning_two_tiles_vertically(self) -> None:
        """緯度方向にタイル境界をまたぐ BBOX は北のタイルから順に返す。"""
        assert target.tile_names_for_bounds((105.5, 19.5, 106.0, 20.5)) == ["E105N25", "E105N20"]

    def test_bounds_spanning_four_tiles(self) -> None:
        """縦横ともにまたぐ BBOX は4タイルを返す。"""
        assert target.tile_names_for_bounds((104.5, 19.5, 106.5, 20.5)) == [
            "E100N25",
            "E105N25",
            "E100N20",
            "E105N20",
        ]

    def test_eastern_edge_on_tile_boundary_excludes_next_tile(self) -> None:
        """BBOX の東端がタイル境界ちょうどでも、その東隣のタイルは含めない。"""
        assert target.tile_names_for_bounds((100.5, 20.5, 105.0, 21.0)) == ["E100N25"]

    def test_southern_edge_on_tile_boundary_excludes_next_tile(self) -> None:
        """BBOX の南端がタイル境界ちょうどでも、その南隣のタイルは含めない。"""
        assert target.tile_names_for_bounds((105.5, 20.0, 106.0, 21.0)) == ["E105N25"]

    def test_degenerate_point_bounds_returns_single_tile(self) -> None:
        """幅ゼロの BBOX（点）でも1タイルだけを返す。"""
        assert target.tile_names_for_bounds((105.5, 21.0, 105.5, 21.0)) == ["E105N25"]

    def test_southern_hemisphere_and_western_longitude(self) -> None:
        """南半球・西経の BBOX でも命名規則どおりのタイル名を返す。

        タイル名は左上隅を表すため、緯度 -5〜0 のタイルの上辺は 0 で "N0" となる。
        実データの収録タイル一覧にも E100N0 と E100S5 が存在し、"S0" は存在しない。
        """
        assert target.tile_names_for_bounds((-8.0, -3.0, -7.0, -2.0)) == ["W10N0"]

    def test_southern_hemisphere_below_five_degrees_south(self) -> None:
        """緯度 -10〜-5 のタイルは上辺 -5 の "S5" になる。"""
        assert target.tile_names_for_bounds((-8.0, -8.0, -7.0, -6.0)) == ["W10S5"]

    def test_rejects_inverted_bounds(self) -> None:
        """最小値が最大値を上回る BBOX は ValueError になる。"""
        with pytest.raises(ValueError, match="最小値が最大値"):
            target.tile_names_for_bounds((106.0, 20.5, 105.0, 21.0))


class TestZipNameForTile:
    """zip_name_for_tile のテスト。"""

    @pytest.mark.parametrize(
        ("tile_name", "expected_zip_name"),
        [
            ("E105N25", "GLC_FCS30D_19852022maps_E100-E105.zip"),
            ("E100N20", "GLC_FCS30D_19852022maps_E100-E105.zip"),
            ("E110N25", "GLC_FCS30D_19852022maps_E110-E115.zip"),
            ("E0N5", "GLC_FCS30D_19852022maps_E0-E5.zip"),
            ("E5N5", "GLC_FCS30D_19852022maps_E0-E5.zip"),
            # 西経は帯の区切りが絶対値5起点（実データの ZIP 名一覧で確認済み）
            ("W5S5", "GLC_FCS30D_19852022maps_W5-W10.zip"),
            ("W10S5", "GLC_FCS30D_19852022maps_W5-W10.zip"),
            ("W15N25", "GLC_FCS30D_19852022maps_W15-W20.zip"),
            ("W180N60", "GLC_FCS30D_19852022maps_W175-W180.zip"),
        ],
    )
    def test_maps_tile_to_zip(self, tile_name: str, expected_zip_name: str) -> None:
        """タイル名から収録 ZIP 名（経度10度帯）を決定できる。"""
        assert target.zip_name_for_tile(tile_name) == expected_zip_name

    def test_generated_zip_names_exist_in_actual_record(self) -> None:
        """全タイルから生成した ZIP 名が、Zenodo レコードの実在ファイル名と一致する。

        東経・西経で帯の区切り方が異なるため、実データの一覧（36ファイル）を
        期待値として突き合わせる。
        """
        expected_zip_names = {
            f"GLC_FCS30D_19852022maps_E{start}-E{start + 5}.zip" for start in range(0, 180, 10)
        } | {f"GLC_FCS30D_19852022maps_W{start}-W{start + 5}.zip" for start in range(5, 180, 10)}
        assert len(expected_zip_names) == 36

        generated_zip_names = set()
        for left_lon in range(-180, 180, 5):
            hemisphere = "E" if left_lon >= 0 else "W"
            tile_name = f"{hemisphere}{abs(left_lon)}N25"
            generated_zip_names.add(target.zip_name_for_tile(tile_name))

        assert generated_zip_names == expected_zip_names

    @pytest.mark.parametrize("tile_name", ["", "X105N25", "E105", "EN25", "ENN"])
    def test_rejects_malformed_tile_name(self, tile_name: str) -> None:
        """書式が不正なタイル名は ValueError になる。"""
        with pytest.raises(ValueError, match="書式が不正"):
            target.zip_name_for_tile(tile_name)


class TestMemberNameForTile:
    """member_name_for_tile のテスト。"""

    def test_builds_annual_member_path(self) -> None:
        """ZIP 内の年次版メンバーのパスを組み立てる。"""
        zip_name = "GLC_FCS30D_19852022maps_E100-E105.zip"
        assert target.member_name_for_tile(zip_name, "E105N25") == (
            "GLC_FCS30D_19852022maps_E100-E105/GLC_FCS30D_20002022_E105N25_Annual_V1.1.tif"
        )


class TestClassScheme:
    """GLC_FCS30D のクラス体系の定数（CLASS_LABELS・FILLED_VALUES）のテスト。

    集計ロジック自体は `tests/common/test_raster_classes.py` で検証する。
    """

    def test_treats_filled_values_as_invalid(self) -> None:
        """Filled value（0・250）を有効画素から除外して集計する。"""
        array = np.array([[190, 190, 210], [10, 0, 250]], dtype=np.uint8)

        result = build_class_distribution(
            array, target.CLASS_LABELS, filled_values=target.FILLED_VALUES
        )

        assert result["filled_pixels"] == 2
        assert result["valid_pixels"] == 4
        assert result["valid_pixel_ratio"] == pytest.approx(4 / 6)

    def test_labels_impervious_surfaces(self) -> None:
        """不透水面（190）のラベルが分類体系どおりである。"""
        assert target.CLASS_LABELS[190] == "Impervious surfaces"

    def test_reports_unknown_class_values(self) -> None:
        """分類体系にないクラス値は unknown_class_values に記録する。"""
        array = np.array([[190, 99]], dtype=np.uint8)

        result = build_class_distribution(
            array, target.CLASS_LABELS, filled_values=target.FILLED_VALUES
        )

        assert result["unknown_class_values"] == [99]
        assert any(entry["label"] == "Unknown" for entry in result["classes"])


class TestBuildSummary:
    """build_summary のテスト。"""

    @staticmethod
    def _build(tmp_path: Path, record_id: str = target.DEFAULT_ZENODO_RECORD_ID) -> dict[str, Any]:
        """テスト用のサマリーを生成する。"""
        raster_profile = {
            "crs": "EPSG:4326",
            "dtype": "uint8",
            "width": 10,
            "height": 20,
            "resolution": [0.00026949458523586, 0.00026949458523586],
            "bounds": {"minx": 105.0, "miny": 20.0, "maxx": 106.0, "maxy": 21.0},
            "nodata": 0.0,
        }
        class_distribution = build_class_distribution(
            np.array([[190, 210, 0]], dtype=np.uint8),
            target.CLASS_LABELS,
            filled_values=target.FILLED_VALUES,
        )
        return target.build_summary(
            year=2022,
            tile_names=["E105N25"],
            zip_name="GLC_FCS30D_19852022maps_E100-E105.zip",
            member_name="dir/member.tif",
            record_id=record_id,
            roi_path=tmp_path / "roi.shp",
            roi_bounds=HANOI_ROI_BOUNDS,
            raster_profile=raster_profile,
            class_distribution=class_distribution,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out.json",
            retrieved_at="2026-07-21T00:00:00+00:00",
        )

    def test_contains_required_keys(self, tmp_path: Path) -> None:
        """サマリーJSONの標準項目が揃う。"""
        summary = self._build(tmp_path)

        for key in ("dataset", "source", "retrieved_at", "roi_path", "crs", "outputs"):
            assert key in summary
        assert summary["outputs"].keys() == {"geotiff", "summary"}

    def test_records_year_and_band_index(self, tmp_path: Path) -> None:
        """対象年と対応するバンド番号を記録する。"""
        summary = self._build(tmp_path)

        assert summary["year"] == 2022
        assert summary["band_index"] == 23

    def test_year_note_mentions_provision_range_and_time_gap(self, tmp_path: Path) -> None:
        """提供年の範囲と、Landsat 観測年との時間差の注記を記録する。

        GLC_FCS30D の年次マップは観測年に届かないため、この注記が
        時間差を明示する唯一の手がかりとなる。
        """
        year_note = self._build(tmp_path)["year_note"]

        assert f"{target.ANNUAL_FIRST_YEAR}-{target.ANNUAL_LAST_YEAR} 年" in year_note
        assert f"Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年前後）" in year_note
        assert "ずれがある" in year_note

    def test_source_reflects_given_record_id(self, tmp_path: Path) -> None:
        """既定以外のレコードIDを指定すると、source と record_id がその値を反映する。"""
        summary = self._build(tmp_path, record_id="8239305")

        assert summary["record_id"] == "8239305"
        assert summary["source"].endswith("/8239305")

    def test_version_and_doi_are_none_for_non_default_record(self, tmp_path: Path) -> None:
        """既定以外のレコードでは、版に依存する情報を記録しない。

        別の版のDOIは分からないため、既定値をそのまま書くと誤った出典になる。
        """
        summary = self._build(tmp_path, record_id="8239305")

        assert summary["dataset_version"] is None
        assert summary["doi"] is None

    def test_version_and_doi_are_recorded_for_default_record(self, tmp_path: Path) -> None:
        """既定のレコードでは、版とDOIを記録する。"""
        summary = self._build(tmp_path)

        assert summary["record_id"] == target.DEFAULT_ZENODO_RECORD_ID
        assert summary["dataset_version"] == target.DATASET_VERSION
        assert summary["doi"] == target.DATASET_DOI
        assert summary["source"].endswith(f"/{target.DEFAULT_ZENODO_RECORD_ID}")

    def test_records_pixel_stats_consistent_with_distribution(self, tmp_path: Path) -> None:
        """pixel_stats がクラス分布の集計と整合する。"""
        summary = self._build(tmp_path)

        assert summary["pixel_stats"]["total_pixels"] == 3
        assert summary["pixel_stats"]["valid_pixels"] == 2
        assert summary["pixel_stats"]["filled_pixels"] == 1


class FakeHttpResponse:
    """`urllib.request.urlopen` の戻り値を模したテスト用オブジェクト。"""

    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        """応答の状態・ヘッダ・本文を保持する。"""
        self.status = status
        self.headers = headers
        self._body = body

    def read(self) -> bytes:
        """本文を返す。"""
        return self._body

    def __enter__(self) -> FakeHttpResponse:
        """コンテキストマネージャとして自身を返す。"""
        return self

    def __exit__(self, *args: object) -> None:
        """後処理は不要。"""
        return None


class TestHttpRangeReader:
    """HttpRangeReader のテスト（ネットワークはモックする）。"""

    CONTENT = bytes(range(256)) * 4  # 1024 バイトのテストデータ

    def _install_fake_urlopen(
        self,
        monkeypatch: pytest.MonkeyPatch,
        head_headers: dict[str, str] | None = None,
        range_status: int = 206,
        fail_times: int = 0,
    ) -> dict[str, int]:
        """HEAD と Range GET に応答する urlopen の差し替えを仕込む。

        Args:
            monkeypatch: pytest の monkeypatch フィクスチャ。
            head_headers: HEAD 応答のヘッダ。
            range_status: Range GET で返す HTTP ステータス。
            fail_times: Range GET を先頭から何回失敗させるか。

        Returns:
            呼び出し回数を記録する辞書（キー: head / get / failed）。
        """
        counters = {"head": 0, "get": 0, "failed": 0}
        headers = (
            head_headers
            if head_headers is not None
            else {"Content-Length": str(len(self.CONTENT)), "Accept-Ranges": "bytes"}
        )

        def fake_urlopen(request: Any, timeout: int = 0) -> FakeHttpResponse:
            if request.get_method() == "HEAD":
                counters["head"] += 1
                return FakeHttpResponse(200, headers)

            counters["get"] += 1
            if counters["failed"] < fail_times:
                counters["failed"] += 1
                raise urllib.error.URLError("一時的な接続エラー")

            range_header = request.headers.get("Range")
            start, end = (int(part) for part in range_header.removeprefix("bytes=").split("-"))
            return FakeHttpResponse(range_status, headers, self.CONTENT[start : end + 1])

        monkeypatch.setattr(target.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(target.time, "sleep", lambda seconds: None)
        return counters

    def test_rejects_non_http_scheme(self) -> None:
        """http/https 以外のURLスキームは ValueError になる。"""
        with pytest.raises(ValueError, match="URL スキーム"):
            target.HttpRangeReader("file:///etc/passwd")

    def test_raises_when_content_length_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Content-Length が得られない場合は RuntimeError になる。"""
        self._install_fake_urlopen(monkeypatch, head_headers={})

        with pytest.raises(RuntimeError, match="Content-Length"):
            target.HttpRangeReader("https://example.invalid/a.zip")

    def test_raises_when_server_denies_ranges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accept-Ranges: none のサーバーは、長時間の取得に入る前に弾く。"""
        self._install_fake_urlopen(
            monkeypatch,
            head_headers={"Content-Length": "1024", "Accept-Ranges": "none"},
        )

        with pytest.raises(RuntimeError, match="Range リクエストに対応していません"):
            target.HttpRangeReader("https://example.invalid/a.zip")

    def test_accepts_server_without_accept_ranges_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Accept-Ranges を返さないサーバー（Zenodo等）は拒否しない。"""
        self._install_fake_urlopen(monkeypatch, head_headers={"Content-Length": "1024"})

        reader = target.HttpRangeReader("https://example.invalid/a.zip")

        assert reader.size == 1024

    def test_reads_requested_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指定バイト数を現在位置から読み取る。"""
        self._install_fake_urlopen(monkeypatch)
        reader = target.HttpRangeReader("https://example.invalid/a.zip")

        assert reader.read(10) == self.CONTENT[:10]
        assert reader.tell() == 10
        assert reader.read(5) == self.CONTENT[10:15]

    def test_seek_from_end_reads_tail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """末尾基準のシークで終端を読める（ZIP中央ディレクトリ探索に相当）。"""
        self._install_fake_urlopen(monkeypatch)
        reader = target.HttpRangeReader("https://example.invalid/a.zip")

        reader.seek(-100, io.SEEK_END)

        assert reader.tell() == len(self.CONTENT) - 100
        assert reader.read(100) == self.CONTENT[-100:]

    def test_seek_is_clamped_to_file_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """範囲外へのシークはファイル内に丸められる。"""
        self._install_fake_urlopen(monkeypatch)
        reader = target.HttpRangeReader("https://example.invalid/a.zip")

        assert reader.seek(-10) == 0
        assert reader.seek(99999) == len(self.CONTENT)
        assert reader.read(10) == b""

    def test_read_negative_size_reads_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """負のサイズ指定は末尾まで読み取る。"""
        self._install_fake_urlopen(monkeypatch)
        reader = target.HttpRangeReader("https://example.invalid/a.zip")
        reader.seek(1000)

        assert reader.read(-1) == self.CONTENT[1000:]

    def test_retries_transient_error_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """一過性の接続エラーはリトライして回復する（同じ範囲を再取得する）。"""
        counters = self._install_fake_urlopen(monkeypatch, fail_times=2)
        reader = target.HttpRangeReader("https://example.invalid/a.zip", retry_wait_seconds=0)

        data = reader.read(10)

        assert data == self.CONTENT[:10]
        assert counters["failed"] == 2
        assert reader.tell() == 10

    def test_raises_after_retry_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """リトライ上限を超えた場合は RuntimeError になる。"""
        self._install_fake_urlopen(monkeypatch, fail_times=99)
        reader = target.HttpRangeReader(
            "https://example.invalid/a.zip", max_retry_count=2, retry_wait_seconds=0
        )

        with pytest.raises(RuntimeError, match="リトライ"):
            reader.read(10)

    def test_raises_when_response_is_not_partial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """206 以外の応答はリトライせず即座に失敗する。"""
        self._install_fake_urlopen(monkeypatch, range_status=200)
        reader = target.HttpRangeReader("https://example.invalid/a.zip", retry_wait_seconds=0)

        with pytest.raises(RuntimeError, match="Range リクエストに対応していません"):
            reader.read(10)


class TestClipBandToRoi:
    """clip_band_to_roi のテスト（合成ラスタを使いネットワークは使わない）。"""

    @staticmethod
    def _write_source_raster(path: Path) -> None:
        """バンドごとに一定値を持つ 3 バンドの合成ラスタを書き出す。

        バンド n の全画素値を (n * 10) とし、どのバンドを読んだかを値で判別できるようにする。
        """
        transform = from_origin(105.0, 21.0, 0.1, 0.1)
        profile = {
            "driver": "GTiff",
            "dtype": "uint8",
            "count": 3,
            "width": 10,
            "height": 10,
            "crs": "EPSG:4326",
            "transform": transform,
        }
        with rasterio.open(path, "w", **profile) as destination:
            for band_index in range(1, 4):
                destination.write(np.full((10, 10), band_index * 10, dtype=np.uint8), band_index)

    @staticmethod
    def _roi_geodataframe() -> gpd.GeoDataFrame:
        """合成ラスタの左上 4x4 画素分を覆う ROI を作る。"""
        return gpd.GeoDataFrame(
            geometry=[box(105.0, 20.6, 105.4, 21.0)],
            crs="EPSG:4326",
        )

    def test_extracts_requested_band_only(self, tmp_path: Path) -> None:
        """指定したバンドだけが単バンドの出力として書き出される。"""
        source_path = tmp_path / "source.tif"
        output_path = tmp_path / "clipped.tif"
        self._write_source_raster(source_path)

        target.clip_band_to_roi(source_path, self._roi_geodataframe(), 2, output_path)

        with rasterio.open(output_path) as destination:
            assert destination.count == 1
            # バンド2の値（20）だけが現れ、他バンドの値（10・30）は現れない
            assert set(np.unique(destination.read(1))) <= {20, target.OUTPUT_NODATA}
            assert 20 in np.unique(destination.read(1))

    def test_preserves_crs_and_resolution(self, tmp_path: Path) -> None:
        """出力の CRS（EPSG:4326）と解像度が入力から維持される。"""
        source_path = tmp_path / "source.tif"
        output_path = tmp_path / "clipped.tif"
        self._write_source_raster(source_path)

        raster_profile = target.clip_band_to_roi(
            source_path, self._roi_geodataframe(), 1, output_path
        )

        assert raster_profile["crs"] == "EPSG:4326"
        assert raster_profile["resolution"] == pytest.approx([0.1, 0.1])
        assert raster_profile["dtype"] == "uint8"
        assert raster_profile["nodata"] == float(target.OUTPUT_NODATA)

    def test_crops_to_roi_extent(self, tmp_path: Path) -> None:
        """出力範囲が ROI の BBOX まで切り詰められる。"""
        source_path = tmp_path / "source.tif"
        output_path = tmp_path / "clipped.tif"
        self._write_source_raster(source_path)

        raster_profile = target.clip_band_to_roi(
            source_path, self._roi_geodataframe(), 1, output_path
        )

        # 元ラスタは 10x10 画素、ROI は 4x4 画素分
        assert (raster_profile["width"], raster_profile["height"]) == (4, 4)
        assert raster_profile["bounds"]["minx"] == pytest.approx(105.0)
        assert raster_profile["bounds"]["maxy"] == pytest.approx(21.0)

    def test_reprojects_roi_given_in_other_crs(self, tmp_path: Path) -> None:
        """ROI が別 CRS で与えられてもラスタ側の CRS に変換してクリップする。"""
        source_path = tmp_path / "source.tif"
        output_path = tmp_path / "clipped.tif"
        self._write_source_raster(source_path)
        roi_in_utm = self._roi_geodataframe().to_crs("EPSG:32648")

        raster_profile = target.clip_band_to_roi(source_path, roi_in_utm, 1, output_path)

        assert raster_profile["crs"] == "EPSG:4326"
        assert raster_profile["width"] > 0


class TestResolveZipDownloadUrl:
    """resolve_zip_download_url のテスト（Zenodo API はモックする）。"""

    def test_returns_url_of_matching_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """レコード内の該当 ZIP のダウンロード URL を返す。"""
        record = {
            "files": [
                {"key": "other.zip", "links": {"self": "https://example.invalid/other"}},
                {"key": "target.zip", "links": {"self": "https://example.invalid/target"}},
            ]
        }
        monkeypatch.setattr(target, "fetch_json_with_retry", lambda *args, **kwargs: record)

        url = target.resolve_zip_download_url(record_id="1", zip_name="target.zip")

        assert url == "https://example.invalid/target"

    def test_raises_when_zip_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """該当 ZIP がレコードにない場合は RuntimeError になる。"""
        record = {"files": [{"key": "other.zip", "links": {"self": "https://example.invalid/o"}}]}
        monkeypatch.setattr(target, "fetch_json_with_retry", lambda *args, **kwargs: record)

        with pytest.raises(RuntimeError, match="見つかりません"):
            target.resolve_zip_download_url(record_id="1", zip_name="missing.zip")


class TestRunGuards:
    """run() の事前チェック分岐のテスト（ネットワークには到達しない）。"""

    @staticmethod
    def _roi_path(tmp_path: Path) -> Path:
        """単一タイルに収まる ROI（Hanoi 相当）を書き出す。"""
        roi_path = tmp_path / "roi.shp"
        gpd.GeoDataFrame(
            geometry=[box(*HANOI_ROI_BOUNDS)],
            crs="EPSG:4326",
        ).to_file(roi_path)
        return roi_path

    def test_raises_when_geotiff_exists_without_overwrite(self, tmp_path: Path) -> None:
        """出力 GeoTIFF が既存で --overwrite なしなら FileExistsError になる。"""
        output_path = tmp_path / "out.tif"
        output_path.write_bytes(b"")

        with pytest.raises(FileExistsError, match="out.tif"):
            target.run(
                roi_path=self._roi_path(tmp_path),
                year=2022,
                output_path=output_path,
                summary_path=tmp_path / "out.json",
                cache_dir=tmp_path / "cache",
                record_id="1",
                overwrite=False,
            )

    def test_raises_when_summary_exists_without_overwrite(self, tmp_path: Path) -> None:
        """サマリーJSONだけが既存の場合も、上書きせずに止まる。"""
        summary_path = tmp_path / "out.json"
        summary_path.write_text("{}", encoding="utf-8")

        with pytest.raises(FileExistsError, match="out.json"):
            target.run(
                roi_path=self._roi_path(tmp_path),
                year=2022,
                output_path=tmp_path / "out.tif",
                summary_path=summary_path,
                cache_dir=tmp_path / "cache",
                record_id="1",
                overwrite=False,
            )

    def test_raises_for_year_outside_dataset_range(self, tmp_path: Path) -> None:
        """データセットが提供しない年は、取得に入る前に ValueError になる。"""
        with pytest.raises(ValueError, match="年次マップ"):
            target.run(
                roi_path=self._roi_path(tmp_path),
                year=2023,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "out.json",
                cache_dir=tmp_path / "cache",
                record_id="1",
                overwrite=False,
            )

    def test_raises_when_roi_spans_multiple_tiles(self, tmp_path: Path) -> None:
        """ROI が複数タイルにまたがる場合は NotImplementedError になる。"""
        roi_path = tmp_path / "wide_roi.shp"
        gpd.GeoDataFrame(geometry=[box(104.5, 19.5, 106.5, 21.0)], crs="EPSG:4326").to_file(
            roi_path
        )

        with pytest.raises(NotImplementedError, match="複数タイル"):
            target.run(
                roi_path=roi_path,
                year=2022,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "out.json",
                cache_dir=tmp_path / "cache",
                record_id="1",
                overwrite=False,
            )


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_defaults_include_year_in_stem(self) -> None:
        """既定パスのファイル名に対象年が含まれる。"""
        output_path, summary_path = target.resolve_output_paths(2022, None, None)

        assert output_path.name == "glc_fcs30d_hanoi_2022.tif"
        assert summary_path.name == "glc_fcs30d_hanoi_2022_summary.json"

    def test_explicit_paths_take_precedence(self, tmp_path: Path) -> None:
        """明示指定したパスが優先される。"""
        output_path, summary_path = target.resolve_output_paths(
            2022, tmp_path / "a.tif", tmp_path / "b.json"
        )

        assert output_path == tmp_path / "a.tif"
        assert summary_path == tmp_path / "b.json"
