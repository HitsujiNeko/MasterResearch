"""download_open_dem.py（公開 DEM を GEE から取得するスクリプト）のテスト。

GEE の認証・画像の組み立て・ダウンロード（外部サービス）は差し替え、合成した小さな
GeoTIFF を「ダウンロード結果」として渡して、ROI でのクリップとメタデータ JSON の保存までを
通して確かめる。GEE プロジェクト ID・ROI の読み込み・メタデータの保存は共通モジュール
（`src.common.gee`・`src.common.roi`・`src.common.summary`）を使うので、その異常系
（CSV の NaN・CRS 未定義・メタデータの NaN）で止まることも確かめる。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.common import config, gee, roi, summary
from src.gee import download_open_dem as target

# 小さな ROI（EPSG:4326）と、それを覆う合成 DEM（0.001° 格子・30×30 画素）
ROI_BOUNDS = (105.80, 21.00, 105.82, 21.02)
RASTER_WEST = 105.795
RASTER_NORTH = 21.025
PIXEL_DEG = 0.001
RASTER_SIZE = 30
DATASET_KEY = "copernicus_glo30"


def _write_roi(path: Path, crs: str | None = "EPSG:4326") -> Path:
    """矩形 1 つの ROI を Shapefile に書き出す。

    Args:
        path: 出力パス。
        crs: 書き出す CRS。EPSG:4326 以外なら ROI を投影してから書く。
            None なら CRS を持たない（.prj の無い）ファイルにする。

    Returns:
        書き出したパス。
    """
    roi_gdf = gpd.GeoDataFrame(
        geometry=[box(*ROI_BOUNDS)], crs=None if crs is None else "EPSG:4326"
    )
    if crs is not None and crs != "EPSG:4326":
        roi_gdf = roi_gdf.to_crs(crs)
    roi_gdf.to_file(path)
    return path


def _make_geotiff_bytes(tmp_path: Path) -> bytes:
    """ROI を覆う合成 DEM（EPSG:4326・float32）の GeoTIFF をバイト列で返す。"""
    raster_path = tmp_path / "synthetic_dem.tif"
    values = np.arange(RASTER_SIZE * RASTER_SIZE, dtype=np.float32).reshape(
        1, RASTER_SIZE, RASTER_SIZE
    )
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=RASTER_SIZE,
        width=RASTER_SIZE,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(4326),
        transform=from_origin(RASTER_WEST, RASTER_NORTH, PIXEL_DEG, PIXEL_DEG),
    ) as dst:
        dst.write(values)
    return raster_path.read_bytes()


def _write_config(path: Path, project_id: str) -> Path:
    """GEE 設定 CSV を書き出す。project_id が空なら列は空欄（読み込むと NaN）になる。"""
    path.write_text(f"gee_project_id,city_name\n{project_id},hanoi\n", encoding="utf-8")
    return path


def _patch_gee(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """GEE の認証・画像の組み立て・ダウンロードを差し替える。

    Args:
        monkeypatch: pytest の monkeypatch。
        tmp_path: 合成 GeoTIFF の作業ディレクトリ。

    Returns:
        認証に渡されたプロジェクト ID と、ROI ジオメトリの組み立てに渡された
        GeoDataFrame を記録する辞書。
    """
    calls: dict[str, Any] = {}
    content = _make_geotiff_bytes(tmp_path)

    def fake_build_roi_geometry(roi_gdf: gpd.GeoDataFrame) -> tuple[None, dict[str, Any]]:
        calls["roi_gdf"] = roi_gdf
        return None, roi_gdf.geometry.union_all().__geo_interface__

    monkeypatch.setattr(
        target, "authenticate_gee", lambda project_id: calls.setdefault("project_id", project_id)
    )
    monkeypatch.setattr(target, "build_roi_geometry", fake_build_roi_geometry)
    monkeypatch.setattr(target, "get_dem_image", lambda dataset_config: None)
    monkeypatch.setattr(
        target, "build_gee_download_url", lambda **kwargs: "https://example.invalid"
    )
    monkeypatch.setattr(target, "download_http_content", lambda download_url: content)
    return calls


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    """入出力パスを用意する。"""
    return {
        "roi_path": tmp_path / "roi.shp",
        "config_path": tmp_path / "gee_config.csv",
        "output_path": tmp_path / "out" / "dem.tif",
        "metadata_path": tmp_path / "out" / "dem_metadata.json",
    }


def _run(paths: dict[str, Path]) -> tuple[Path, Path]:
    """テスト用の引数で `run` を呼ぶ。"""
    return target.run(
        dataset_key=DATASET_KEY,
        roi_path=paths["roi_path"],
        output_path=paths["output_path"],
        metadata_path=paths["metadata_path"],
        config_path=paths["config_path"],
        gee_project_id="",
        output_crs="EPSG:4326",
        scale_m=None,
        overwrite=False,
    )


class TestCommonModuleUsage:
    """共通モジュールの関数・定数を使っていることの確認。"""

    def test_uses_common_functions(self) -> None:
        assert target.authenticate_gee is gee.authenticate_gee
        assert target.load_gee_project_id is gee.load_gee_project_id
        assert target.load_roi_geometry is roi.load_roi_geometry
        assert target.save_summary is summary.save_summary

    def test_default_roi_path_is_common(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["download_open_dem.py"])
        assert target.parse_arguments().roi_path == config.DEFAULT_HANOI_ROI_PATH


class TestRun:
    """取得処理全体（GEE とダウンロードを差し替えて実行）。"""

    def test_writes_clipped_geotiff_and_metadata(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # ROI を UTM で書いておき、EPSG:4326 に直してから使われることも確かめる
        _write_roi(paths["roi_path"], crs=config.HANOI_UTM_CRS)
        _write_config(paths["config_path"], "test-project")
        calls = _patch_gee(monkeypatch, tmp_path)

        output_path, metadata_path = _run(paths)

        assert calls["project_id"] == "test-project"
        assert calls["roi_gdf"].crs.to_epsg() == 4326
        with rasterio.open(output_path) as src:
            assert src.crs.to_epsg() == 4326
            assert src.nodata == target.CLIP_NODATA
            # ROI（0.02° 四方）に合わせて切り出され、元の 30×30 画素より小さい
            assert src.width < RASTER_SIZE
            assert src.height < RASTER_SIZE

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["dataset"]["dataset_key"] == DATASET_KEY
        assert metadata["requested_output_crs"] == "EPSG:4326"
        assert metadata["source_details"] == {"download_source": "Google Earth Engine"}
        raster_summary = metadata["raster_summary"]
        assert raster_summary["valid_pixel_count"] > 0
        assert raster_summary["statistics"]["min"] >= 0

    def test_nan_project_id_stops_before_authentication(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_roi(paths["roi_path"])
        _write_config(paths["config_path"], "")
        _patch_gee(monkeypatch, tmp_path)

        def fail_if_called(project_id: str) -> None:
            raise AssertionError("プロジェクト ID が NaN のまま認証してはいけない")

        monkeypatch.setattr(target, "authenticate_gee", fail_if_called)

        with pytest.raises(ValueError, match="プロジェクトID"):
            _run(paths)
        assert not paths["output_path"].exists()

    # CRS の無い ROI をわざと書き出すため、書き出し時の警告は想定どおり
    @pytest.mark.filterwarnings("ignore:'crs' was not provided")
    def test_roi_without_crs_stops_before_download(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_roi(paths["roi_path"], crs=None)
        _write_config(paths["config_path"], "test-project")
        calls = _patch_gee(monkeypatch, tmp_path)

        with pytest.raises(ValueError, match="CRSが未定義"):
            _run(paths)
        assert "project_id" not in calls
        assert not paths["output_path"].exists()

    def test_nan_in_metadata_stops_without_saving(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_roi(paths["roi_path"])
        _write_config(paths["config_path"], "test-project")
        _patch_gee(monkeypatch, tmp_path)
        monkeypatch.setattr(
            target, "read_raster_summary", lambda output_path: {"statistics": {"mean": np.nan}}
        )

        with pytest.raises(ValueError, match="NaN"):
            _run(paths)
        assert not paths["metadata_path"].exists()
