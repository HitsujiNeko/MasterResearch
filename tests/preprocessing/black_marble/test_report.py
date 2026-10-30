"""サマリーの組み立て（`black_marble.report`）のテスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.preprocessing.black_marble import (
    listing,
    tile_grid,
)
from src.preprocessing.black_marble import report as target
from tests.helpers import HANOI_ROI_BOUNDS


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
            tiles=[tile_grid.TileIndex(28, 6)],
            tile_files={
                "h28v06": listing.TileFile(
                    name="VNP46A4.A2023001.h28v06.002.x.h5",
                    download_url="https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/x.h5",
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

    def test_lists_unusable_attributes_per_band(self) -> None:
        """適用できなかった属性も、欠落と区別できる文言で列挙する。"""
        metadata = {
            "band_attributes": {
                "near_nadir_num": {
                    "defaulted_attributes": [],
                    "unusable_attributes": ["_FillValue"],
                }
            }
        }

        warnings = target.collect_attribute_warnings(metadata)

        assert len(warnings) == 1
        assert "near_nadir_num" in warnings[0]
        assert "_FillValue" in warnings[0]
        assert "表現できず" in warnings[0]

    def test_returns_empty_when_all_attributes_present(self) -> None:
        """欠落が無ければ空リスト（サマリー上で「問題なし」と読める）。"""
        metadata = {
            "band_attributes": {
                "ntl_near_nadir": {"defaulted_attributes": [], "unusable_attributes": []}
            }
        }

        assert target.collect_attribute_warnings(metadata) == []

    def test_tolerates_missing_metadata(self) -> None:
        """メタデータが欠けていても落ちない。"""
        assert target.collect_attribute_warnings({}) == []
