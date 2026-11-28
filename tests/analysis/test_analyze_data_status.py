"""analyze_data_status.py（GIS データと LST データの整備状況の分析）のテスト。

対象モジュールは作業ディレクトリ基準の相対パスでデータを探すため、作業ディレクトリを
一時ディレクトリに移し、小さな GPKG・CSV・Shapefile を置いて集計の分岐を確かめる。

対象モジュールは import した時点で警告フィルタを書き換える（全警告を無視する）ため、
副作用を閉じ込めて import する。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from tests.helpers import import_with_contained_side_effects

# ハノイ付近の VN-2000（EPSG:5897）の座標（m）。座標範囲からの CRS 推定の対象になる
VN2000_BOX = (505_000.0, 2_320_000.0, 506_000.0, 2_321_000.0)


@pytest.fixture(scope="module")
def target(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """import 時の副作用を閉じ込めて対象モジュールを読み込む。"""
    return import_with_contained_side_effects(
        "src.analysis.analyze_data_status", tmp_path_factory.mktemp("import_cwd")
    )


@pytest.fixture()
def work_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """作業ディレクトリを一時ディレクトリに移す。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_merge_gpkg(work_dir: Path, suffix: str, crs: str | None, bounds: tuple) -> None:
    """測量 GIS と同じ名前の GPKG（面 2 つと点 1 つ）を書き出す。

    Args:
        work_dir: 作業ディレクトリ。
        suffix: データ種類（DC 等）。
        crs: CRS。None なら CRS を付けない。
        bounds: 面の範囲 (minx, miny, maxx, maxy)。
    """
    path = work_dir / "整備データ" / "merge" / f"merge_{suffix}.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    min_x, min_y, max_x, max_y = bounds
    gpd.GeoDataFrame(
        {"name": ["a", "b", "c"]},
        geometry=[
            box(min_x, min_y, (min_x + max_x) / 2, max_y),
            box((min_x + max_x) / 2, min_y, max_x, max_y),
            Point(min_x, min_y),
        ],
        crs=crs,
    ).to_file(path, driver="GPKG")


class TestAnalyzeGisData:
    """analyze_gis_data のテスト。"""

    def test_returns_empty_without_merge_files(self, target: ModuleType, work_dir: Path) -> None:
        """merge_*.gpkg が 1 つも無ければ空の辞書を返す。"""
        assert target.analyze_gis_data() == {}

    def test_summarizes_file_with_crs(self, target: ModuleType, work_dir: Path) -> None:
        """CRS 付きの GPKG について、EPSG・地物数・型・範囲と WGS84 の範囲をまとめる。"""
        _write_merge_gpkg(work_dir, "DC", "EPSG:5897", VN2000_BOX)

        result = target.analyze_gis_data()["DC"]

        assert result["file"] == "merge_DC.gpkg"
        assert result["crs_epsg"] == 5897
        assert result["crs_assumed"] is None
        assert result["feature_count"] == 3
        assert result["geometry_types"] == {"Polygon": 2, "Point": 1}
        assert result["bounds"] == pytest.approx(
            dict(zip(["minx", "miny", "maxx", "maxy"], VN2000_BOX))
        )
        wgs84 = result["bounds_wgs84"]
        assert 105.0 < wgs84["lon_min"] < wgs84["lon_max"] < 107.0
        assert 20.0 < wgs84["lat_min"] < wgs84["lat_max"] < 22.0

    def test_assumes_vn2000_for_undefined_crs_in_its_range(
        self, target: ModuleType, work_dir: Path
    ) -> None:
        """CRS が無く座標が VN-2000 の範囲なら EPSG:5897 と推定して WGS84 の範囲を出す。"""
        _write_merge_gpkg(work_dir, "GT", None, VN2000_BOX)

        result = target.analyze_gis_data()["GT"]

        assert result["crs_epsg"] is None
        assert result["crs_assumed"] == "EPSG:5897"
        assert 105.0 < result["bounds_wgs84"]["lon_min"] < 107.0

    def test_does_not_assume_crs_outside_vn2000_range(
        self, target: ModuleType, work_dir: Path
    ) -> None:
        """CRS が無く座標が VN-2000 の範囲外なら、CRS を推定せず WGS84 の範囲も出さない。"""
        _write_merge_gpkg(work_dir, "TH", None, (0.0, 0.0, 10.0, 10.0))

        result = target.analyze_gis_data()["TH"]

        assert result["crs_assumed"] is None
        assert "bounds_wgs84" not in result

    def test_records_error_for_unreadable_file(self, target: ModuleType, work_dir: Path) -> None:
        """読めないファイルは処理を止めず、エラーとして記録する。"""
        path = work_dir / "整備データ" / "merge" / "merge_CS.gpkg"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a geopackage")

        result = target.analyze_gis_data()

        assert set(result["CS"]) == {"error"}


class TestAnalyzeLstData:
    """analyze_lst_data のテスト。"""

    def test_returns_empty_without_inputs(self, target: ModuleType, work_dir: Path) -> None:
        """設定・結果・ROI がどれも無ければ空の辞書を返す。"""
        assert target.analyze_lst_data() == {}

    def test_summarizes_config_results_and_roi(self, target: ModuleType, work_dir: Path) -> None:
        """設定の一覧・結果の件数（出力済み・有効画素 50% 超）・ROI の範囲をまとめる。"""
        (work_dir / "data" / "input").mkdir(parents=True)
        pd.DataFrame(
            {
                "roi_shapefile_path": ["roi.shp"],
                "start_date": ["2023-01-01"],
                "end_date": ["2023-12-31"],
                "output_epsg": [4326],
                "lst_method": ["SMW"],
            }
        ).to_csv(work_dir / "data" / "input" / "gee_calc_LST_info.csv", index=False)
        (work_dir / "data" / "output").mkdir(parents=True)
        pd.DataFrame(
            {
                "date": ["2023-01-01", "2023-02-01", "2023-03-01"],
                "exported": [True, False, True],
                "valid_pixel_ratio": [80.0, 50.0, 20.0],
                "mean_temp_c": [30.0, 31.0, 32.0],
                "min_temp_c": [20.0, 21.0, 22.0],
                "max_temp_c": [40.0, 41.0, 42.0],
            }
        ).to_csv(work_dir / "data" / "output" / "gee_calc_LST_results.csv", index=False)
        roi_path = work_dir / "data" / "gis" / "boundaries" / "hanoi" / "roi.shp"
        roi_path.parent.mkdir(parents=True)
        gpd.GeoDataFrame(geometry=[box(105.3, 20.6, 106.0, 21.4)], crs="EPSG:4326").to_file(
            roi_path
        )

        result = target.analyze_lst_data()

        assert result["config"][0]["lst_method"] == "SMW"
        assert result["results_summary"] == {
            "record_count": 3,
            "exported_count": 2,
            "valid_count": 1,
        }
        roi = result["roi"]["roi"]
        assert roi["crs_epsg"] == 4326
        assert roi["bounds_wgs84"] == pytest.approx(
            {"lon_min": 105.3, "lat_min": 20.6, "lon_max": 106.0, "lat_max": 21.4}
        )


def test_main_writes_combined_json(target: ModuleType, work_dir: Path) -> None:
    """main が GIS と LST の分析結果をまとめた JSON を書き出す。"""
    target.main()

    output = work_dir / "data" / "output" / "data_preparation_analysis.json"
    assert json.loads(output.read_text(encoding="utf-8")) == {"gis_data": {}, "lst_data": {}}
