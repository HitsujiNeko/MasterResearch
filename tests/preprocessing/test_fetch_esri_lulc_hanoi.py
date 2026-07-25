"""fetch_esri_lulc_hanoi.py（Esri 10m LULC 取得スクリプト）のテスト。

ネットワークアクセスを伴わない純粋関数を対象とする。STAC API・SAS 署名の
呼び出しはモックに差し替えて検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

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
