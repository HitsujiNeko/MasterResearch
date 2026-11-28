"""fetch_gba_buildings_hanoi.py（GlobalBuildingAtlas の建物取得スクリプト）のテスト。

WFS へのアクセス（`fetch_tile_records`）は差し替え、ROI の読み込み・タイル分割・
GeoPackage への書き込み・サマリー JSON の保存までを、小さな ROI で通して確かめる。
ROI の読み込みとサマリーの保存は共通モジュール（`src.common.roi`・`src.common.summary`）を
使うので、その異常系（CRS 未定義・NaN）で取得前・保存前に止まることも確かめる。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from shapely.geometry import box

from src.common import config, http_fetch, roi, summary
from src.preprocessing import fetch_gba_buildings_hanoi as target

# 小さな ROI（EPSG:4326）。タイルサイズ 0.01° で 2×2 タイルに分かれる
ROI_BOUNDS = (105.80, 21.00, 105.82, 21.02)
TILE_SIZE_DEG = 0.01


def _write_roi(path: Path, crs: str | None = "EPSG:4326") -> Path:
    """矩形 1 つの ROI を Shapefile に書き出す。

    Args:
        path: 出力パス。
        crs: ROI の CRS。None なら CRS を持たない（.prj の無い）ファイルにする。

    Returns:
        書き出したパス。
    """
    gpd.GeoDataFrame(geometry=[box(*ROI_BOUNDS)], crs=crs).to_file(path)
    return path


def _fake_fetch_tile_records(
    called_bboxes: list[tuple[float, float, float, float]],
) -> Any:
    """WFS へアクセスせず、タイルの中心に小さな建物を 1 件返す差し替え関数を作る。

    Args:
        called_bboxes: 呼び出されたタイルの BBOX を記録するリスト。

    Returns:
        `fetch_tile_records` と同じ引数を取る関数。
    """

    def fake(
        tile_bbox_4326: tuple[float, float, float, float],
        tile_index: int,
        max_count: int,
        roi_union: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        called_bboxes.append(tile_bbox_4326)
        min_lon, min_lat, max_lon, max_lat = tile_bbox_4326
        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2
        record = {
            "ogc_fid": tile_index,
            "source": "test",
            "gba_id": f"b{tile_index}",
            "height": 10.0,
            "var": 0.0,
            "region": "test",
            "geometry": box(center_lon, center_lat, center_lon + 0.0001, center_lat + 0.0001),
        }
        tile_summary = {"tile_index": tile_index, "record_count": 1}
        return [record], tile_summary

    return fake


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """一時ディレクトリをプロジェクトルートとみなし、入出力パスを用意する。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    return {
        "roi_path": tmp_path / "roi.shp",
        "output_path": tmp_path / "out" / "buildings.gpkg",
        "summary_path": tmp_path / "out" / "summary.json",
    }


def _run(paths: dict[str, Path]) -> None:
    """テスト用の引数で `run` を呼ぶ。"""
    target.run(
        roi_path=paths["roi_path"],
        output_path=paths["output_path"],
        summary_path=paths["summary_path"],
        layer_name="buildings",
        tile_size_deg=TILE_SIZE_DEG,
        max_count=100,
        limit_tiles=None,
        overwrite=False,
        start_tile_index=1,
    )


class TestCommonModuleUsage:
    """共通モジュールの関数・定数を使っていることの確認。"""

    def test_uses_common_functions(self) -> None:
        """ROI の読み込みとサマリーの保存に共通モジュールの関数を使う。"""
        assert target.load_roi_geometry is roi.load_roi_geometry
        assert target.save_summary is summary.save_summary
        assert target.fetch_json_with_retry is http_fetch.fetch_json_with_retry

    def test_uses_common_constants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """UTM の CRS と ROI の既定パスに共通設定の値を使う。"""
        # 同じ文字列の再定義でも通ってしまわないよう、同一オブジェクトかを確かめる
        assert target.HANOI_UTM_CRS is config.HANOI_UTM_CRS
        monkeypatch.setattr(sys, "argv", ["fetch_gba_buildings_hanoi.py"])
        assert target.parse_arguments().roi_path == config.DEFAULT_HANOI_ROI_PATH


class TestFetchWfsPage:
    """fetch_wfs_page のテスト（HTTP 取得は差し替える）。"""

    def test_returns_features_and_number_matched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """応答の地物と総件数を取り出し、URL とタイムアウトをそのまま渡す。"""
        calls: list[tuple[str, int]] = []

        def fake_fetch(url: str, timeout: int) -> dict[str, Any]:
            calls.append((url, timeout))
            return {"features": [{"id": 1}, {"id": 2}], "numberMatched": 2}

        monkeypatch.setattr(target, "fetch_json_with_retry", fake_fetch)

        features, number_matched = target.fetch_wfs_page("https://example.invalid/wfs", 30)

        assert features == [{"id": 1}, {"id": 2}]
        assert number_matched == 2
        assert calls == [("https://example.invalid/wfs", 30)]

    def test_missing_fields_fall_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """features が null・numberMatched が無い応答は、空リストと -1（不明）にする。"""
        monkeypatch.setattr(
            target, "fetch_json_with_retry", lambda url, timeout: {"features": None}
        )

        assert target.fetch_wfs_page("https://example.invalid/wfs", 30) == ([], -1)


class TestRun:
    """取得処理全体（WFS を差し替えて実行）。"""

    def test_writes_summary_with_roi_bounds(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ROI の範囲で建物を取得し、その範囲をサマリーに書く。"""
        _write_roi(paths["roi_path"])
        called_bboxes: list[tuple[float, float, float, float]] = []
        monkeypatch.setattr(target, "fetch_tile_records", _fake_fetch_tile_records(called_bboxes))

        _run(paths)

        saved = json.loads(paths["summary_path"].read_text(encoding="utf-8"))
        assert saved["roi_bbox"] == pytest.approx(list(ROI_BOUNDS))
        # タイル分割は ROI の BBOX から始まる
        assert called_bboxes[0][:2] == pytest.approx(ROI_BOUNDS[:2])
        assert saved["tile_count"] == len(called_bboxes) == 4
        assert saved["total_building_count"] == 4
        assert saved["session_building_count"] == 4
        assert saved["roi_path"] == "roi.shp"
        # ROI は Microsoft 欠落域（105.29–105.47°E）の外にある
        assert saved["microsoft_missing_area_coverage"]["building_count"] == 0

        buildings = gpd.read_file(paths["output_path"], layer="buildings")
        assert buildings.crs.to_epsg() == 4326
        assert len(buildings) == 4

    # CRS の無い ROI をわざと書き出すため、書き出し時の警告は想定どおり
    @pytest.mark.filterwarnings("ignore:'crs' was not provided")
    def test_roi_without_crs_stops_before_fetch(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CRS の無い ROI は、WFS の取得に進まず例外にする。"""
        _write_roi(paths["roi_path"], crs=None)

        def fail_if_called(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("CRS 未定義の ROI で WFS へアクセスしてはいけない")

        monkeypatch.setattr(target, "fetch_tile_records", fail_if_called)

        with pytest.raises(ValueError, match="CRSが未定義"):
            _run(paths)
        assert not paths["output_path"].exists()

    def test_nan_in_summary_stops_without_saving(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """サマリーに NaN があれば、保存せずに例外にする。"""
        _write_roi(paths["roi_path"])
        monkeypatch.setattr(target, "fetch_tile_records", _fake_fetch_tile_records([]))
        monkeypatch.setattr(
            target,
            "compute_missing_area_stats",
            lambda **kwargs: {"building_count": 0, "building_area_ratio": float("nan")},
        )

        with pytest.raises(ValueError, match="NaN"):
            _run(paths)
        assert not paths["summary_path"].exists()
