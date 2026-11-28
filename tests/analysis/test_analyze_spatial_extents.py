"""analyze_spatial_extents.py（ROI と測量 GIS の空間範囲の比較レポート）のテスト。

実データ（ROI の Shapefile・merge_*.gpkg・LST）は使わず、`PROJECT_ROOT` を一時
ディレクトリに差し替えて、小さなベクタ・ラスタから範囲を読む処理を確かめる。
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from pyproj import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from src.analysis import analyze_spatial_extents as target
from tests.helpers import write_test_raster

# ハノイ付近の VN-2000（EPSG:5897）の座標（m）。WGS84 で経度 105.8 度・緯度 21 度前後になる
VN2000_BOX = (505_000.0, 2_320_000.0, 506_000.0, 2_321_000.0)
ROI_RELATIVE = Path("data") / "gis" / "boundaries" / "hanoi" / "hanoi_ROI_EPSG4326.shp"


@pytest.fixture()
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`PROJECT_ROOT` を一時ディレクトリに差し替える。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _write_roi(project_root: Path) -> None:
    """2 つのポリゴンを持つ ROI の Shapefile を書き出す。"""
    path = project_root / ROI_RELATIVE
    path.parent.mkdir(parents=True)
    gpd.GeoDataFrame(
        geometry=[box(105.3, 20.6, 105.6, 21.0), box(105.5, 20.9, 106.0, 21.4)], crs="EPSG:4326"
    ).to_file(path)


def _write_two_layer_gpkg(
    path: Path, crs: str | None, bounds: tuple[float, float, float, float] = VN2000_BOX
) -> None:
    """範囲の異なる 2 レイヤを持つ GPKG を書き出す。

    Args:
        path: 出力先。
        crs: CRS。None なら CRS を付けない（測量 GIS の merge_*.gpkg と同じ形）。
        bounds: 2 レイヤを合わせた範囲 (minx, miny, maxx, maxy)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    min_x, min_y, max_x, max_y = bounds
    half_x = (min_x + max_x) / 2
    gpd.GeoDataFrame(geometry=[box(min_x, min_y, half_x, max_y)], crs=crs).to_file(
        path, layer="left", driver="GPKG"
    )
    gpd.GeoDataFrame(geometry=[box(half_x, min_y, max_x, max_y)], crs=crs).to_file(
        path, layer="right", driver="GPKG"
    )


class TestFlattenCoords:
    """_flatten_coords のテスト。"""

    def test_flattens_nested_polygon_coordinates(self) -> None:
        """Polygon・MultiPolygon の入れ子の座標を (x, y) の一覧にする。"""
        multipolygon = [[[(0, 0), (1, 0), (1, 1)]], [[(5, 5), (6, 6.5)]]]

        assert target._flatten_coords(multipolygon) == [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (5.0, 5.0),
            (6.0, 6.5),
        ]

    def test_returns_empty_for_none(self) -> None:
        """座標が None なら空の一覧を返す。"""
        assert target._flatten_coords(None) == []


class TestReadVectorBboxAnyLayer:
    """read_vector_bbox_any_layer のテスト。"""

    def test_reports_each_layer_and_their_union(self, project_root: Path) -> None:
        """レイヤごとの範囲と、全レイヤを合わせた範囲を返す。"""
        path = project_root / "merge" / "merge_DC.gpkg"
        _write_two_layer_gpkg(path, crs="EPSG:5897")

        info = target.read_vector_bbox_any_layer(path)

        assert info["path"] == "merge/merge_DC.gpkg"
        assert [layer["layer"] for layer in info["layers"]] == ["left", "right"]
        assert info["bbox_union"] == pytest.approx(list(VN2000_BOX))
        assert info["crs_wkt"]

    def test_transforms_bboxes_to_output_crs(self, project_root: Path) -> None:
        """入力と出力の CRS を指定すると、範囲を出力の CRS に変換する。"""
        path = project_root / "merge" / "merge_DC.gpkg"
        _write_two_layer_gpkg(path, crs=None)

        info = target.read_vector_bbox_any_layer(
            path, source_crs=CRS.from_epsg(5897), output_crs=CRS.from_epsg(4326)
        )

        lon_min, lat_min, lon_max, lat_max = info["bbox_union"]
        assert 105.0 < lon_min < lon_max < 107.0
        assert 20.0 < lat_min < lat_max < 22.0


class TestReadRoiHanoiBbox:
    """read_roi_hanoi_bbox のテスト。"""

    def test_missing_roi_raises(self, project_root: Path) -> None:
        """ROI のファイルが無ければ例外にする。"""
        with pytest.raises(FileNotFoundError, match="ROIが見つかりません"):
            target.read_roi_hanoi_bbox()

    def test_returns_union_of_all_features(self, project_root: Path) -> None:
        """ROI の全地物を合わせた範囲を返す。"""
        _write_roi(project_root)

        result = target.read_roi_hanoi_bbox()

        assert result["path"] == ROI_RELATIVE.as_posix()
        assert result["filter"] == {"all_features": True}
        assert result["bbox"] == pytest.approx([105.3, 20.6, 106.0, 21.4])


class TestReadLstBboxOsakaAny:
    """read_lst_bbox_osaka_any のテスト。"""

    def test_returns_none_without_directory_or_tif(self, project_root: Path) -> None:
        """LST のディレクトリや GeoTIFF が無ければ None を返す。"""
        assert target.read_lst_bbox_osaka_any() is None
        (project_root / "data" / "output" / "LST" / "osaka").mkdir(parents=True)
        assert target.read_lst_bbox_osaka_any() is None

    def test_reads_first_tif_in_name_order(self, project_root: Path) -> None:
        """名前順で先頭の GeoTIFF から範囲と CRS を読む。"""
        lst_dir = project_root / "data" / "output" / "LST" / "osaka"
        for name, origin_x in (("b.tif", 136.0), ("a.tif", 135.0)):
            write_test_raster(
                lst_dir / name,
                np.zeros((2, 2), dtype=np.float32),
                transform=from_origin(origin_x, 35.0, 0.5, 0.5),
            )

        result = target.read_lst_bbox_osaka_any()

        assert result["path"] == "data/output/LST/osaka/a.tif"
        assert result["bbox"] == pytest.approx([135.0, 34.0, 136.0, 35.0])
        assert result["crs"] == "EPSG:4326"


def test_main_writes_report_with_union_of_survey_files(project_root: Path) -> None:
    """main が ROI・測量 GIS の範囲（WGS84 に変換）と、全ファイルを合わせた範囲をレポートに書く。"""
    _write_roi(project_root)
    merge_dir = project_root / "整備データ" / "merge"
    _write_two_layer_gpkg(merge_dir / "merge_DC.gpkg", crs=None)
    # GT は DC より東・北にずらし、和が両方より広くなるようにする
    shifted = (507_000.0, 2_322_000.0, 508_000.0, 2_323_000.0)
    _write_two_layer_gpkg(merge_dir / "merge_GT.gpkg", crs=None, bounds=shifted)

    target.main()

    report = json.loads(
        (project_root / "data" / "output" / "spatial_extent_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["roi_hanoi"]["bbox"] == pytest.approx([105.3, 20.6, 106.0, 21.4])
    assert [info["path"] for info in report["gis_merge_from_5897"]] == [
        "整備データ/merge/merge_DC.gpkg",
        "整備データ/merge/merge_GT.gpkg",
    ]
    dc_bbox, gt_bbox = (info["bbox_union"] for info in report["gis_merge_from_5897"])
    for lon_min, lat_min, lon_max, lat_max in (dc_bbox, gt_bbox):
        assert 105.0 < lon_min < lon_max < 107.0
        assert 20.0 < lat_min < lat_max < 22.0
    assert dc_bbox[2] < gt_bbox[0]
    assert report["gis_bbox_union_all_layers"] == pytest.approx(
        [dc_bbox[0], dc_bbox[1], gt_bbox[2], gt_bbox[3]]
    )
    assert report["lst_osaka_example"] is None
