"""fetch_esri_lulc_hanoi.py（Esri 10m LULC 取得スクリプト）のテスト。

ネットワークアクセスを伴わない純粋関数を対象とする。STAC API・SAS 署名の
呼び出しはモックに差し替えて検証する。ラスタ入出力を伴う再投影・ROI クリップは、
合成した小さな GeoTIFF を用いたスモークテストで出力の CRS・nodata・解像度を確認する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.common.raster_classes import build_class_distribution
from src.preprocessing import fetch_esri_lulc_hanoi as target

# ROI（hanoi_ROI_EPSG4326.shp）の実測 BBOX
HANOI_ROI_BOUNDS = (105.28812456270636, 20.564469161724375, 106.02005052860555, 21.385222290909635)


def _make_item(item_id: str, start_year: int) -> dict[str, Any]:
    """テスト用の最小 STAC アイテムを組み立てる。"""
    return {
        "id": item_id,
        "properties": {
            "start_datetime": f"{start_year}-01-01T00:00:00Z",
            "end_datetime": f"{start_year + 1}-01-01T00:00:00Z",
            "proj:epsg": 32648,
        },
        "assets": {"data": {"href": f"https://example.invalid/{item_id}.tif"}},
    }


class TestSearchAnnualItem:
    """search_annual_item のテスト。"""

    def test_selects_item_whose_start_year_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """範囲検索が前年アイテムも返す場合、start_datetime の年で絞り込む。"""
        features = [_make_item("48Q-2022", 2022), _make_item("48Q-2021", 2021)]
        monkeypatch.setattr(
            target, "fetch_json_with_retry", lambda *args, **kwargs: {"features": features}
        )

        item = target.search_annual_item(2022, HANOI_ROI_BOUNDS)

        assert item["id"] == "48Q-2022"

    def test_raises_when_no_item_matches_year(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """対象年のアイテムが無ければ RuntimeError になる。"""
        monkeypatch.setattr(
            target,
            "fetch_json_with_retry",
            lambda *args, **kwargs: {"features": [_make_item("48Q-2021", 2021)]},
        )

        with pytest.raises(RuntimeError, match="見つかりません"):
            target.search_annual_item(2022, HANOI_ROI_BOUNDS)

    def test_raises_when_roi_spans_multiple_tiles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同一年のアイテムが複数（複数タイル）なら未実装として止める。"""
        features = [_make_item("48Q-2022", 2022), _make_item("49Q-2022", 2022)]
        monkeypatch.setattr(
            target, "fetch_json_with_retry", lambda *args, **kwargs: {"features": features}
        )

        with pytest.raises(NotImplementedError, match="複数タイル"):
            target.search_annual_item(2022, HANOI_ROI_BOUNDS)

    def test_requests_collection_and_bbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """検索 URL にコレクション ID と BBOX が含まれる。"""
        captured: dict[str, str] = {}

        def fake_fetch(url: str, **kwargs: Any) -> dict[str, Any]:
            captured["url"] = url
            return {"features": [_make_item("48Q-2022", 2022)]}

        monkeypatch.setattr(target, "fetch_json_with_retry", fake_fetch)
        target.search_annual_item(2022, HANOI_ROI_BOUNDS)

        assert target.STAC_COLLECTION_ID in captured["url"]
        assert "105.28812456270636" in captured["url"]


class TestCollectSearchFeatures:
    """collect_search_features（STAC 検索のページネーション）のテスト。"""

    def test_follows_next_links_across_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """next リンクを辿り、2ページ目以降のアイテムも収集する。"""
        pages = {
            "page1": {
                "features": [_make_item("48Q-2021", 2021)],
                "links": [{"rel": "next", "href": "page2"}],
            },
            "page2": {"features": [_make_item("48Q-2022", 2022)], "links": []},
        }
        monkeypatch.setattr(target, "fetch_json_with_retry", lambda url, **kwargs: pages[url])

        features = target.collect_search_features("page1")

        assert [feature["id"] for feature in features] == ["48Q-2021", "48Q-2022"]

    def test_stops_when_no_next_link(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """next リンクが無ければ1ページで終了する。"""
        calls: list[str] = []

        def fake_fetch(url: str, **kwargs: Any) -> dict[str, Any]:
            calls.append(url)
            return {"features": [_make_item("48Q-2022", 2022)], "links": []}

        monkeypatch.setattr(target, "fetch_json_with_retry", fake_fetch)
        target.collect_search_features("page1")

        assert calls == ["page1"]

    def test_stops_at_max_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """next が途切れない場合も max_pages で打ち切る（無限ループ防止）。"""
        calls: list[str] = []

        def fake_fetch(url: str, **kwargs: Any) -> dict[str, Any]:
            calls.append(url)
            return {"features": [], "links": [{"rel": "next", "href": "same"}]}

        monkeypatch.setattr(target, "fetch_json_with_retry", fake_fetch)
        target.collect_search_features("page1", max_pages=3)

        assert len(calls) == 3

    def test_search_annual_item_finds_item_on_second_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """対象年のアイテムが2ページ目にあっても見つけられる。"""
        pages = [
            {
                "features": [_make_item("48Q-2021", 2021)],
                "links": [{"rel": "next", "href": "page2"}],
            },
            {"features": [_make_item("48Q-2022", 2022)], "links": []},
        ]
        monkeypatch.setattr(
            target, "fetch_json_with_retry", lambda url, **kwargs: pages.pop(0) if pages else {}
        )

        item = target.search_annual_item(2022, HANOI_ROI_BOUNDS)

        assert item["id"] == "48Q-2022"


class TestSignAssetHref:
    """sign_asset_href のテスト。"""

    def test_returns_signed_href(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """署名エンドポイントが返す href をそのまま返す。"""
        monkeypatch.setattr(
            target,
            "fetch_json_with_retry",
            lambda *args, **kwargs: {"href": "https://example.invalid/x.tif?sig=abc"},
        )

        assert target.sign_asset_href("https://example.invalid/x.tif").endswith("sig=abc")

    def test_raises_when_response_lacks_href(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """応答に href が無ければ RuntimeError になる。"""
        monkeypatch.setattr(
            target, "fetch_json_with_retry", lambda *args, **kwargs: {"msft:expiry": "..."}
        )

        with pytest.raises(RuntimeError, match="href がありません"):
            target.sign_asset_href("https://example.invalid/x.tif")


class TestPaddedWindow:
    """padded_window のテスト。"""

    # EPSG:4326 のソースを想定し、CRS 変換を恒等にして window 計算のみを検証する
    SOURCE_CRS = CRS.from_epsg(4326)
    SOURCE_TRANSFORM = from_origin(100.0, 30.0, 0.001, 0.001)
    SOURCE_WIDTH = 10000
    SOURCE_HEIGHT = 10000

    def test_window_covers_bounds_with_padding(self) -> None:
        """余白を含み、BBOX を確実に覆う整数画素の window を返す。"""
        window = target.padded_window(
            bounds=(101.0, 25.0, 101.1, 25.1),
            source_crs=self.SOURCE_CRS,
            source_transform=self.SOURCE_TRANSFORM,
            source_width=self.SOURCE_WIDTH,
            source_height=self.SOURCE_HEIGHT,
            pad_pixels=5,
        )

        # BBOX（0.1度四方 / 0.001度画素）単体では 100x100 画素。余白5画素が四方に付く
        assert window.col_off == 995
        assert window.row_off == 4895
        assert window.width == 110
        assert window.height == 110

    def test_window_is_clipped_to_raster_extent(self) -> None:
        """ラスタ範囲外へはみ出さないようクリップする。"""
        window = target.padded_window(
            bounds=(100.0, 29.9, 100.05, 30.0),
            source_crs=self.SOURCE_CRS,
            source_transform=self.SOURCE_TRANSFORM,
            source_width=self.SOURCE_WIDTH,
            source_height=self.SOURCE_HEIGHT,
            pad_pixels=8,
        )

        assert window.col_off == 0
        assert window.row_off == 0

    def test_raises_when_bounds_do_not_overlap(self) -> None:
        """BBOX がラスタと重ならなければ ValueError になる。"""
        with pytest.raises(ValueError, match="重なりません"):
            target.padded_window(
                bounds=(50.0, 10.0, 51.0, 11.0),
                source_crs=self.SOURCE_CRS,
                source_transform=self.SOURCE_TRANSFORM,
                source_width=self.SOURCE_WIDTH,
                source_height=self.SOURCE_HEIGHT,
            )


class TestCacheCoversBounds:
    """cache_covers_bounds（キャッシュ再利用の範囲検証）のテスト。"""

    @staticmethod
    def _write_raster(path: Path, bounds: tuple[float, float, float, float]) -> None:
        """指定 BBOX（EPSG:4326）を持つ最小のラスタを書き出す。"""
        min_lon, min_lat, max_lon, max_lat = bounds
        width = height = 10
        transform = from_origin(
            min_lon, max_lat, (max_lon - min_lon) / width, (max_lat - min_lat) / height
        )
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs=CRS.from_epsg(4326),
            transform=transform,
        ) as destination:
            destination.write(np.ones((height, width), dtype=np.uint8), 1)

    def test_accepts_cache_that_covers_requested_bounds(self, tmp_path: Path) -> None:
        """要求範囲を覆うキャッシュは再利用できる。"""
        cache_path = tmp_path / "cache.tif"
        self._write_raster(cache_path, (105.0, 20.0, 107.0, 22.0))

        assert target.cache_covers_bounds(cache_path, (105.5, 20.5, 106.5, 21.5)) is True

    def test_rejects_cache_that_does_not_cover_requested_bounds(self, tmp_path: Path) -> None:
        """別 ROI で作られた狭いキャッシュは再利用しない。"""
        cache_path = tmp_path / "cache.tif"
        self._write_raster(cache_path, (105.5, 20.5, 106.0, 21.0))

        assert target.cache_covers_bounds(cache_path, (105.0, 20.0, 107.0, 22.0)) is False

    def test_rejects_unreadable_cache(self, tmp_path: Path) -> None:
        """壊れたキャッシュは読めないため再取得させる。"""
        cache_path = tmp_path / "broken.tif"
        cache_path.write_text("not a raster", encoding="utf-8")

        assert target.cache_covers_bounds(cache_path, (105.0, 20.0, 106.0, 21.0)) is False


class TestRasterPipelineSmoke:
    """再投影・ROI クリップのスモークテスト（GIS 処理の出力形式を確認する）。

    ネットワークは使わず、UTM の小さな合成ラスタから
    `reproject_to_wgs84` → `clip_to_roi` を通し、出力の CRS・nodata・
    解像度・dtype が期待どおりかを確認する。
    """

    # ハノイ周辺（UTM 48N）の 10m 画素・50x50 の合成ラスタ
    UTM_CRS = CRS.from_epsg(32648)
    ORIGIN_X = 570000.0
    ORIGIN_Y = 2360000.0
    PIXEL_SIZE = 10.0
    SIZE = 50

    def _write_utm_raster(self, path: Path) -> None:
        """クラス値を持つ UTM の合成 GeoTIFF を書き出す。"""
        transform = from_origin(self.ORIGIN_X, self.ORIGIN_Y, self.PIXEL_SIZE, self.PIXEL_SIZE)
        # 左半分を市街地(7)、右半分を農地(5) にして、再投影後も値が保たれるか見る
        array = np.full((self.SIZE, self.SIZE), 5, dtype=np.uint8)
        array[:, : self.SIZE // 2] = 7
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=self.SIZE,
            height=self.SIZE,
            count=1,
            dtype="uint8",
            crs=self.UTM_CRS,
            transform=transform,
            nodata=target.OUTPUT_NODATA,
        ) as destination:
            destination.write(array, 1)

    def test_reproject_outputs_wgs84_preserving_class_values(self, tmp_path: Path) -> None:
        """再投影の出力は EPSG:4326・uint8 で、クラス値が補間で崩れない。"""
        source_path = tmp_path / "utm.tif"
        output_path = tmp_path / "wgs84.tif"
        self._write_utm_raster(source_path)

        target.reproject_to_wgs84(subset_path=source_path, output_path=output_path)

        with rasterio.open(output_path) as reprojected:
            assert reprojected.crs.to_string() == "EPSG:4326"
            assert reprojected.dtypes[0] == "uint8"
            assert reprojected.nodata == target.OUTPUT_NODATA
            assert reprojected.width > 0 and reprojected.height > 0
            values = set(np.unique(reprojected.read(1)).tolist())
        # 最近傍のため、元の 5・7（と余白の nodata 0）以外の中間値が現れない
        assert values <= {0, 5, 7}

    def test_clip_to_roi_returns_expected_profile(self, tmp_path: Path) -> None:
        """ROI クリップの返り値が EPSG:4326・nodata=0・10m 相当の諸元を持つ。"""
        source_path = tmp_path / "utm.tif"
        reprojected_path = tmp_path / "wgs84.tif"
        clipped_path = tmp_path / "clipped.tif"
        self._write_utm_raster(source_path)
        target.reproject_to_wgs84(subset_path=source_path, output_path=reprojected_path)

        with rasterio.open(reprojected_path) as reprojected:
            bounds = reprojected.bounds
        # ラスタ内部に収まる ROI を作り、クリップが効いていることを確認する
        margin_x = (bounds.right - bounds.left) / 4
        margin_y = (bounds.top - bounds.bottom) / 4
        roi_gdf = gpd.GeoDataFrame(
            geometry=[
                box(
                    bounds.left + margin_x,
                    bounds.bottom + margin_y,
                    bounds.right - margin_x,
                    bounds.top - margin_y,
                )
            ],
            crs="EPSG:4326",
        )

        profile = target.clip_to_roi(
            raster_path=reprojected_path, roi_gdf=roi_gdf, output_path=clipped_path
        )

        assert profile["crs"] == "EPSG:4326"
        assert profile["dtype"] == "uint8"
        assert profile["nodata"] == float(target.OUTPUT_NODATA)
        assert profile["width"] > 0 and profile["height"] > 0
        # 出力解像度は元の 10m 相当（度）を保つ
        assert profile["resolution"][0] == pytest.approx(profile["resolution"][1], rel=1e-6)
        # ROI で切り取ったぶん、再投影直後より小さくなる
        with rasterio.open(reprojected_path) as reprojected:
            assert profile["width"] < reprojected.width
            assert profile["height"] < reprojected.height

    def test_clip_to_roi_fills_outside_roi_with_nodata(self, tmp_path: Path) -> None:
        """ROI 外のクリップ余白は nodata で埋まる（有効カバレッジ判定の前提）。"""
        source_path = tmp_path / "utm.tif"
        reprojected_path = tmp_path / "wgs84.tif"
        clipped_path = tmp_path / "clipped.tif"
        self._write_utm_raster(source_path)
        target.reproject_to_wgs84(subset_path=source_path, output_path=reprojected_path)

        with rasterio.open(reprojected_path) as reprojected:
            bounds = reprojected.bounds
        # 三角形の ROI にすると BBOX 矩形との差分が必ず余白として残る
        roi_gdf = gpd.GeoDataFrame(
            geometry=[
                box(bounds.left, bounds.bottom, bounds.right, bounds.top).intersection(
                    box(bounds.left, bounds.bottom, bounds.right, bounds.top).centroid.buffer(
                        (bounds.right - bounds.left) / 3
                    )
                )
            ],
            crs="EPSG:4326",
        )

        target.clip_to_roi(raster_path=reprojected_path, roi_gdf=roi_gdf, output_path=clipped_path)

        with rasterio.open(clipped_path) as clipped:
            array = clipped.read(1)
        assert (array == target.OUTPUT_NODATA).any()


class TestClassScheme:
    """Esri 9クラス体系の定数（CLASS_LABELS・FILLED_VALUES）のテスト。

    集計ロジック自体は `tests/common/test_raster_classes.py` で検証する。
    """

    def test_treats_nodata_and_clouds_as_filled(self) -> None:
        """No Data(0)・Clouds(10) は無効値として扱う。"""
        array = np.array([[1, 0], [10, 7]], dtype=np.uint8)

        result = build_class_distribution(
            array, target.CLASS_LABELS, filled_values=target.FILLED_VALUES
        )

        assert result["filled_pixels"] == 2
        assert result["valid_pixels"] == 2
        assert {entry["value"] for entry in result["classes"]} == {1, 7}

    def test_labels_cover_the_nine_class_scheme(self) -> None:
        """9クラス（1〜11、3・6 は欠番）に No Data(0) を加えたラベルを持つ。"""
        assert set(target.CLASS_LABELS) == {0, 1, 2, 4, 5, 7, 8, 9, 10, 11}
        assert target.CLASS_LABELS[7] == "Built area"

    def test_reports_values_outside_class_scheme(self) -> None:
        """9クラス体系に無い値は unknown_class_values として報告する。"""
        array = np.array([[7, 200]], dtype=np.uint8)

        result = build_class_distribution(
            array, target.CLASS_LABELS, filled_values=target.FILLED_VALUES
        )

        assert result["unknown_class_values"] == [200]


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_uses_default_directories_with_year_in_name(self) -> None:
        """未指定時は既定ディレクトリへ、年を含むファイル名で解決する。"""
        output_path, summary_path = target.resolve_output_paths(2022, None, None)

        assert output_path.name == "esri_lulc_hanoi_2022.tif"
        assert output_path.parent == target.DEFAULT_OUTPUT_DIR
        assert summary_path.name == "esri_lulc_hanoi_2022_summary.json"
        assert summary_path.parent == target.DEFAULT_SUMMARY_DIR

    def test_respects_explicit_paths(self) -> None:
        """明示指定されたパスをそのまま使う。"""
        output_path, summary_path = target.resolve_output_paths(2022, Path("a.tif"), Path("b.json"))

        assert output_path == Path("a.tif")
        assert summary_path == Path("b.json")


class TestBuildSummary:
    """build_summary のテスト。"""

    def test_records_source_without_signed_url(self) -> None:
        """有効期限つきの署名済み URL は記録せず、署名前の href を記録する。"""
        item = _make_item("48Q-2022", 2022)
        class_distribution = build_class_distribution(
            np.array([[7, 1]], dtype=np.uint8),
            target.CLASS_LABELS,
            filled_values=target.FILLED_VALUES,
        )

        summary = target.build_summary(
            year=2022,
            item=item,
            roi_path=Path("roi.shp"),
            roi_bounds=HANOI_ROI_BOUNDS,
            raster_profile={"crs": "EPSG:4326"},
            class_distribution=class_distribution,
            output_path=Path("out.tif"),
            summary_path=Path("out.json"),
            retrieved_at="2026-07-25T00:00:00+00:00",
        )

        assert summary["stac_item_id"] == "48Q-2022"
        assert summary["asset_href"] == "https://example.invalid/48Q-2022.tif"
        assert summary["native_crs"] == "EPSG:32648"
        assert summary["license"] == "CC BY 4.0"
        assert "sig=" not in str(summary)
