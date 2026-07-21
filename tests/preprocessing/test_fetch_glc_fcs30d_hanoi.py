"""fetch_glc_fcs30d_hanoi.py（GLC_FCS30D 取得スクリプト）のテスト。

ネットワークアクセスを伴わない純粋関数を対象とする。Zenodo API 呼び出しは
モックに差し替えて検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.preprocessing import fetch_glc_fcs30d_hanoi as target

# ROI（hanoi_ROI_EPSG4326.shp）の実測 BBOX
HANOI_ROI_BOUNDS = (105.28812456270636, 20.564469161724375, 106.02005052860555, 21.385222290909635)


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


class TestBuildClassDistribution:
    """build_class_distribution のテスト。"""

    def test_counts_classes_and_excludes_filled_values(self) -> None:
        """Filled value（0・250）を有効画素から除外して集計する。"""
        array = np.array([[190, 190, 210], [10, 0, 250]], dtype=np.uint8)

        result = target.build_class_distribution(array)

        assert result["total_pixels"] == 6
        assert result["roi_pixels"] == 6
        assert result["outside_roi_pixels"] == 0
        assert result["valid_pixels"] == 4
        assert result["filled_pixels"] == 2
        assert result["valid_pixel_ratio"] == pytest.approx(4 / 6)

    def test_roi_mask_excludes_clip_margin_from_coverage(self) -> None:
        """ROI 外のクリップ余白を欠測と数えず、有効画素率の分母も ROI 内画素数になる。

        余白（ROI 外）は nodata=0 で Filled value と同値になるため、マスクなしでは
        有効カバレッジを過小評価してしまう。
        """
        array = np.array([[190, 210, 0], [10, 0, 0]], dtype=np.uint8)
        # 左2列が ROI 内、右1列は ROI 外の余白
        roi_mask = np.array([[True, True, False], [True, True, False]])

        result = target.build_class_distribution(array, roi_mask=roi_mask)

        assert result["total_pixels"] == 6
        assert result["roi_pixels"] == 4
        assert result["outside_roi_pixels"] == 2
        # ROI 内の Filled value は1画素のみ（余白の2画素は含めない）
        assert result["filled_pixels"] == 1
        assert result["valid_pixels"] == 3
        assert result["valid_pixel_ratio"] == pytest.approx(3 / 4)

    def test_roi_mask_excludes_outside_classes_from_distribution(self) -> None:
        """ROI 外のクラス値はクラス分布に含めない。"""
        array = np.array([[190, 220], [10, 220]], dtype=np.uint8)
        roi_mask = np.array([[True, False], [True, False]])

        result = target.build_class_distribution(array, roi_mask=roi_mask)

        assert [entry["value"] for entry in result["classes"]] == [10, 190]

    def test_rejects_roi_mask_with_mismatched_shape(self) -> None:
        """形状が一致しない roi_mask は ValueError になる。"""
        array = np.array([[190, 210]], dtype=np.uint8)
        roi_mask = np.array([[True, True, True]])

        with pytest.raises(ValueError, match="形状が"):
            target.build_class_distribution(array, roi_mask=roi_mask)

    def test_ratios_sum_to_one_and_sorted_by_pixel_count(self) -> None:
        """クラス別比率の合計は1になり、画素数の降順で並ぶ。"""
        array = np.array([[190, 190, 190], [210, 210, 10]], dtype=np.uint8)

        classes = target.build_class_distribution(array)["classes"]

        assert [entry["value"] for entry in classes] == [190, 210, 10]
        assert sum(entry["ratio"] for entry in classes) == pytest.approx(1.0)
        assert classes[0]["label"] == "Impervious surfaces"

    def test_reports_unknown_class_values(self) -> None:
        """分類体系にないクラス値は unknown_class_values に記録する。"""
        array = np.array([[190, 99]], dtype=np.uint8)

        result = target.build_class_distribution(array)

        assert result["unknown_class_values"] == [99]
        assert any(entry["label"] == "Unknown" for entry in result["classes"])

    def test_all_filled_array_yields_zero_ratio_without_error(self) -> None:
        """全画素が Filled value でも例外にならず、有効画素率は0になる。"""
        array = np.zeros((3, 3), dtype=np.uint8)

        result = target.build_class_distribution(array)

        assert result["valid_pixels"] == 0
        assert result["valid_pixel_ratio"] == 0.0
        assert result["classes"] == []

    def test_empty_array_yields_zero_ratio_without_error(self) -> None:
        """画素が1つもない配列でもゼロ除算にならない。"""
        array = np.array([], dtype=np.uint8)

        result = target.build_class_distribution(array)

        assert result["total_pixels"] == 0
        assert result["valid_pixel_ratio"] == 0.0


class TestBuildSummary:
    """build_summary のテスト。"""

    @staticmethod
    def _build(tmp_path: Any, record_id: str = target.DEFAULT_ZENODO_RECORD_ID) -> dict[str, Any]:
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
        class_distribution = target.build_class_distribution(
            np.array([[190, 210, 0]], dtype=np.uint8)
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

    def test_contains_required_keys(self, tmp_path: Any) -> None:
        """サマリーJSONの標準項目が揃う。"""
        summary = self._build(tmp_path)

        for key in ("dataset", "source", "retrieved_at", "roi_path", "crs", "outputs"):
            assert key in summary
        assert summary["outputs"].keys() == {"geotiff", "summary"}

    def test_records_year_and_band_index(self, tmp_path: Any) -> None:
        """対象年と対応するバンド番号を記録する。"""
        summary = self._build(tmp_path)

        assert summary["year"] == 2022
        assert summary["band_index"] == 23

    def test_source_reflects_given_record_id(self, tmp_path: Any) -> None:
        """既定以外のレコードIDを指定すると、source と record_id がその値を反映する。"""
        summary = self._build(tmp_path, record_id="8239305")

        assert summary["record_id"] == "8239305"
        assert summary["source"].endswith("/8239305")

    def test_version_and_doi_are_none_for_non_default_record(self, tmp_path: Any) -> None:
        """既定以外のレコードでは、版に依存する情報を記録しない。

        別の版のDOIは分からないため、既定値をそのまま書くと誤った出典になる。
        """
        summary = self._build(tmp_path, record_id="8239305")

        assert summary["dataset_version"] is None
        assert summary["doi"] is None

    def test_version_and_doi_are_recorded_for_default_record(self, tmp_path: Any) -> None:
        """既定のレコードでは、版とDOIを記録する。"""
        summary = self._build(tmp_path)

        assert summary["record_id"] == target.DEFAULT_ZENODO_RECORD_ID
        assert summary["dataset_version"] == target.DATASET_VERSION
        assert summary["doi"] == target.DATASET_DOI
        assert summary["source"].endswith(f"/{target.DEFAULT_ZENODO_RECORD_ID}")

    def test_records_pixel_stats_consistent_with_distribution(self, tmp_path: Any) -> None:
        """pixel_stats がクラス分布の集計と整合する。"""
        summary = self._build(tmp_path)

        assert summary["pixel_stats"]["total_pixels"] == 3
        assert summary["pixel_stats"]["valid_pixels"] == 2
        assert summary["pixel_stats"]["filled_pixels"] == 1


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


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_defaults_include_year_in_stem(self) -> None:
        """既定パスのファイル名に対象年が含まれる。"""
        output_path, summary_path = target.resolve_output_paths(2022, None, None)

        assert output_path.name == "glc_fcs30d_hanoi_2022.tif"
        assert summary_path.name == "glc_fcs30d_hanoi_2022_summary.json"

    def test_explicit_paths_take_precedence(self, tmp_path: Any) -> None:
        """明示指定したパスが優先される。"""
        output_path, summary_path = target.resolve_output_paths(
            2022, tmp_path / "a.tif", tmp_path / "b.json"
        )

        assert output_path == tmp_path / "a.tif"
        assert summary_path == tmp_path / "b.json"
