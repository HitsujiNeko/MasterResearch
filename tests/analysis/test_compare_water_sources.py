"""compare_water_sources.py（水域データの一致度比較）のテスト。

純粋関数（引き当て表・二値化・大津の閾値・集計）はユニットテストで、正準グリッドへの
集約は解析CRS（EPSG:5897）の 10m 格子にちょうど載る合成ラスタで検証する。
後者では、正準グリッドの row（北向きが正）とラスタの行（南向きが正）の向きの対応を確かめる。
"""

from __future__ import annotations

import csv
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from src.analysis import compare_water_sources as target
from src.analysis.urban_params.canonical_grid import build_canonical_grid, make_cell_id
from src.common.geo_metadata import BBox
from src.common.lulc_classes import (
    COMMON_BUILT,
    COMMON_CROPLAND,
    COMMON_WATER,
    GLC_TO_COMMON,
)

ANALYSIS_CRS = CRS.from_epsg(5897)
# ハノイ付近の正準グリッドの行・列（EPSG:5897 で x ≈ 585km、y ≈ 2,325km）
BASE_ROW = 77_500
BASE_COL = 19_500


def _layer(key: str, water: list[bool], valid: list[bool], fraction=None) -> target.WaterLayer:
    """テスト用の水域判定を作る。"""
    return target.WaterLayer(
        key=key,
        label=key,
        definition=key,
        water=np.array(water, dtype=bool),
        valid=np.array(valid, dtype=bool),
        fraction=None if fraction is None else np.array(fraction, dtype=np.float32),
    )


class TestLookups:
    """引き当て表のテスト。"""

    def test_binary_lookup_maps_water_other_and_invalid(self) -> None:
        """水域・非水域・どちらでもない値がそれぞれ 1・2・0 になる。"""
        lookup = target.build_binary_lookup([2], [1])

        assert lookup.tolist() == [0, target.BINARY_OTHER, target.BINARY_WATER]

    def test_binary_lookup_rejects_overlap(self) -> None:
        """同じ値を水域と非水域の両方に入れると停止する。"""
        with pytest.raises(ValueError, match="両方に含まれる"):
            target.build_binary_lookup([1, 2], [2, 3])

    def test_occurrence_lookup_is_inclusive_at_threshold(self) -> None:
        """閾値ちょうどの出現頻度は水域、1 つ下は非水域。"""
        lookup = target.build_occurrence_lookup(50)

        assert lookup[50] == target.BINARY_WATER
        assert lookup[49] == target.BINARY_OTHER
        assert lookup[100] == target.BINARY_WATER
        assert lookup[0] == target.BINARY_OTHER

    @pytest.mark.parametrize("threshold", [0, 101])
    def test_occurrence_lookup_rejects_out_of_range(self, threshold: int) -> None:
        """0 以下（全画素が水域）や 100 超の閾値は拒否する。"""
        with pytest.raises(ValueError, match="1〜100"):
            target.build_occurrence_lookup(threshold)

    def test_water_lookup_from_glc_classes(self) -> None:
        """GLC の 210 だけが水域、他の写像済みクラスは非水域、無効値は 0。"""
        lookup = target.build_water_lookup_from_classes(GLC_TO_COMMON)

        assert lookup[210] == target.BINARY_WATER
        assert lookup[190] == target.BINARY_OTHER
        assert lookup[10] == target.BINARY_OTHER
        assert lookup[0] == 0


class TestBinarize:
    """二値化のテスト。"""

    def test_fraction_threshold_and_valid_ratio(self) -> None:
        """面積率 0.5 ちょうどは水域。有効画素率 0.5 未満・NaN は無効。"""
        fraction = np.array([0.5, 0.49, 1.0, np.nan, 0.9])
        valid_ratio = np.array([1.0, 1.0, 0.4, 0.0, 0.5])

        water, valid = target.binarize_fraction(fraction, valid_ratio)

        assert valid.tolist() == [True, True, False, False, True]
        assert water.tolist() == [True, False, False, False, True]

    def test_values_threshold_is_inclusive_and_nan_is_invalid(self) -> None:
        """MNDWI は閾値以上が水域で、NaN は無効。"""
        water, valid = target.binarize_values(np.array([0.0, -0.01, np.nan]), 0.0)

        assert water.tolist() == [True, False, False]
        assert valid.tolist() == [True, True, False]

    def test_format_mndwi_key(self) -> None:
        """閾値の符号つきの識別子になる。"""
        assert target.format_mndwi_key(0.0) == "mndwi_+0.00"
        assert target.format_mndwi_key(-0.15) == "mndwi_-0.15"

    def test_mndwi_thresholds_include_primary(self) -> None:
        """感度の閾値列に主閾値 0 が含まれ、範囲は -0.2〜0.3。"""
        assert target.PRIMARY_MNDWI_THRESHOLD in target.MNDWI_THRESHOLDS
        assert target.MNDWI_THRESHOLDS[0] == -0.2
        assert target.MNDWI_THRESHOLDS[-1] == 0.3
        # 主閾値の識別子が感度の閾値列から作られる識別子と一致する（-0.0 に化けない）
        keys = [target.format_mndwi_key(value) for value in target.MNDWI_THRESHOLDS]
        assert target.format_mndwi_key(target.PRIMARY_MNDWI_THRESHOLD) in keys


class TestOtsuThreshold:
    """otsu_threshold のテスト。"""

    def test_separates_bimodal_values(self) -> None:
        """2 つの山の間に閾値が来る。"""
        rng = np.random.default_rng(0)
        values = np.concatenate([rng.normal(-0.4, 0.05, 5000), rng.normal(0.4, 0.05, 1000)])

        threshold = target.otsu_threshold(np.append(values, np.nan))

        # 山の間の空白ではどこで切ってもクラス間分散が同じになるため、範囲で確かめる
        assert values[:5000].max() <= threshold <= values[5000:].min()

    def test_rejects_empty_or_constant(self) -> None:
        """有効値が無い・全値が同じ場合は停止する。"""
        with pytest.raises(ValueError, match="有効な値"):
            target.otsu_threshold(np.array([np.nan]))
        with pytest.raises(ValueError, match="全値が同じ"):
            target.otsu_threshold(np.array([0.1, 0.1]))


class TestDominantClass:
    """dominant_class のテスト。"""

    def test_picks_maximum_and_breaks_ties_by_smaller_id(self) -> None:
        """最大の面積率のクラス。同率なら ID の小さい方。全 NaN は 0。"""
        fractions = {
            COMMON_WATER: np.array([0.6, 0.5, np.nan]),
            COMMON_CROPLAND: np.array([0.4, 0.5, np.nan]),
        }

        assert target.dominant_class(fractions).tolist() == [COMMON_WATER, COMMON_WATER, 0]


class TestComparisons:
    """ペア比較・面積率比較・食い違いの内訳のテスト。"""

    def test_pairs_use_cells_valid_in_both(self) -> None:
        """どちらかが無効なセルは比較から除き、面積は 30m セルで km² にする。"""
        layers = {
            "a": _layer("a", [True, True, False, True], [True, True, True, False]),
            "b": _layer("b", [True, False, True, True], [True, True, True, True]),
        }

        (row,) = target.compare_layer_pairs(layers, [("a", "b")], "main", 900.0)

        assert row["comparison_set"] == "main"
        assert row["valid_cells"] == 3
        assert row["both_cells"] == 1
        assert row["iou"] == pytest.approx(1 / 3)
        assert row["a_area_km2"] == pytest.approx(2 * 900 / 1e6)

    def test_fraction_comparison(self) -> None:
        """共通の有効セルで相関・平均絶対差・平均差（B − A）を求める。"""
        layers = {
            "a": _layer("a", [False] * 4, [True, True, True, False], [0.0, 0.5, 1.0, 0.2]),
            "b": _layer("b", [False] * 4, [True, True, True, True], [0.1, 0.6, 1.0, 0.9]),
        }

        (row,) = target.compare_fractions(layers, ["a", "b"])

        assert row["cells"] == 3
        assert row["pearson_r"] == pytest.approx(np.corrcoef([0, 0.5, 1], [0.1, 0.6, 1])[0, 1])
        assert row["mean_abs_diff"] == pytest.approx(0.2 / 3)
        assert row["mean_diff_b_minus_a"] == pytest.approx(0.2 / 3)

    def test_fraction_comparison_without_variance(self) -> None:
        """値が一定のときは相関を None にする（NaN を出さない）。"""
        layers = {
            "a": _layer("a", [False] * 2, [True, True], [0.0, 0.0]),
            "b": _layer("b", [False] * 2, [True, True], [0.0, 1.0]),
        }

        (row,) = target.compare_fractions(layers, ["a", "b"])

        assert row["pearson_r"] is None

    def test_disagreement_breakdown_counts_by_dominant_class(self) -> None:
        """片方だけ水域のセルを、参照データの優占クラス別に数える。"""
        layers = {
            "a": _layer("a", [True, True, False, True], [True] * 4),
            "b": _layer("b", [True, False, True, False], [True] * 4),
        }
        dominant = {"glc": np.array([COMMON_WATER, COMMON_CROPLAND, COMMON_BUILT, COMMON_CROPLAND])}

        rows = target.build_disagreement_breakdown(layers, [("a", "b")], dominant)
        counts = {(row["direction"], row["dominant_class"]): row["cells"] for row in rows}

        assert counts[("a_only", COMMON_CROPLAND)] == 2
        assert counts[("b_only", COMMON_BUILT)] == 1
        assert counts[("both", COMMON_WATER)] == 1

    def test_disagreement_breakdown_skips_self_reference(self) -> None:
        """参照データが比較の当事者である組み合わせは出力しない。"""
        layers = {
            "glc": _layer("glc", [True, False], [True, True]),
            "esri": _layer("esri", [False, True], [True, True]),
        }
        dominant = {
            "glc": np.array([COMMON_WATER, COMMON_CROPLAND]),
            "esri": np.array([COMMON_CROPLAND, COMMON_WATER]),
        }

        rows = target.build_disagreement_breakdown(layers, [("glc", "esri")], dominant)

        assert rows == []

    def test_verify_against_dataset(self) -> None:
        """一致・NaN の不一致・最大差を数える。"""
        result = target.verify_against_dataset(
            np.array([0.0, 0.5, np.nan, 1.0], dtype=np.float32),
            np.array([0.0, 0.5, np.nan, np.nan], dtype=np.float32),
        )

        assert result["compared_cells"] == 2
        assert result["nan_mismatch_cells"] == 1
        assert result["close_ratio"] == 1.0
        assert result["max_abs_diff"] == 0.0


def _two_by_two_spec():
    """2x2 セル（row 77,500〜77,501・col 19,500〜19,501）の正準グリッドを作る。"""
    bbox = BBox(
        minx=BASE_COL * 30.0,
        miny=BASE_ROW * 30.0,
        maxx=(BASE_COL + 2) * 30.0,
        maxy=(BASE_ROW + 2) * 30.0,
    )
    return build_canonical_grid(bbox, ANALYSIS_CRS, 30.0)


def _cells_two_by_two() -> np.ndarray:
    """2x2 セル（row 77,500〜77,501・col 19,500〜19,501）の cell_id を返す。"""
    return np.array(
        [
            make_cell_id(BASE_ROW + 1, BASE_COL),  # 北西
            make_cell_id(BASE_ROW + 1, BASE_COL + 1),  # 北東
            make_cell_id(BASE_ROW, BASE_COL),  # 南西
            make_cell_id(BASE_ROW, BASE_COL + 1),  # 南東
        ],
        dtype=np.int64,
    )


class TestGridAndAggregation:
    """正準グリッドの復元と、合成ラスタからの集約のテスト。"""

    def test_grid_orientation(self) -> None:
        """北側の row が配列の上の行に来る。"""
        canonical_spec = _two_by_two_spec()
        grid_spec, flat_indices = target.locate_cells(_cells_two_by_two(), canonical_spec)

        assert (canonical_spec.n_rows, canonical_spec.n_cols) == (2, 2)
        assert grid_spec.coarse_shape == (2, 2)
        assert flat_indices.tolist() == [0, 1, 2, 3]
        # 左上の座標は北西セルの左上隅
        assert grid_spec.coarse_transform.c == pytest.approx(BASE_COL * 30.0)
        assert grid_spec.coarse_transform.f == pytest.approx((BASE_ROW + 2) * 30.0)

    def test_rejects_cells_outside_grid(self) -> None:
        """グリッドの範囲外の cell_id があれば停止する（データセットとの取り違え）。"""
        cells = np.append(_cells_two_by_two(), make_cell_id(BASE_ROW + 5, BASE_COL))

        with pytest.raises(ValueError, match="範囲外を指す cell_id"):
            target.locate_cells(cells, _two_by_two_spec())

    def test_aggregates_occurrence_into_cells(self, tmp_path: Path) -> None:
        """10m 格子のラスタを集約すると、北西セルの水域率が 1、南東は 1/9 になる。"""
        canonical_spec = _two_by_two_spec()
        grid_spec, flat_indices = target.locate_cells(_cells_two_by_two(), canonical_spec)
        occurrence = np.zeros((6, 6), dtype=np.uint8)
        occurrence[0:3, 0:3] = 80  # 北西セル全体
        occurrence[5, 5] = 60  # 南東セルの 1 画素
        occurrence[0, 3] = 255  # 北東セルの 1 画素を無効値に
        raster_path = tmp_path / "occ.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=6,
            width=6,
            count=1,
            dtype="uint8",
            crs=ANALYSIS_CRS,
            transform=from_origin(BASE_COL * 30.0, (BASE_ROW + 2) * 30.0, 10.0, 10.0),
            nodata=255,
        ) as destination:
            destination.write(occurrence, 1)

        fraction, valid_ratio = target.aggregate_binary_water(
            raster_path, 1, target.build_occurrence_lookup(50), grid_spec, flat_indices
        )

        assert fraction.tolist() == pytest.approx([1.0, 0.0, 0.0, 1 / 9])
        assert valid_ratio.tolist() == pytest.approx([1.0, 8 / 9, 1.0, 1.0])

    def test_write_mask_raster(self, tmp_path: Path) -> None:
        """水域 1・非水域 0・無効 255 で、セルの位置に書き込まれる。"""
        canonical_spec = _two_by_two_spec()
        grid_spec, flat_indices = target.locate_cells(_cells_two_by_two(), canonical_spec)
        layer = _layer("glc", [True, False, True, False], [True, True, False, True])

        path = target.write_mask_raster(
            tmp_path / "mask.tif", [layer], canonical_spec, grid_spec, flat_indices
        )

        with rasterio.open(path) as source:
            assert source.read(1).tolist() == [[1, 0], [255, 0]]
            assert source.descriptions == ("glc",)
            assert source.crs.to_epsg() == 5897


class TestWatchPaths:
    """来歴の追加監視パスのテスト。"""

    def test_watch_paths_exist(self) -> None:
        """追加監視パスはすべて実在するファイルを指す（打ち間違いで監視が空振りしない）。"""
        from src.common.config import PROJECT_ROOT

        missing = [path for path in target.WATCH_PATHS if not (PROJECT_ROOT / path).is_file()]

        assert missing == []


class TestIo:
    """入出力のテスト。"""

    def _write_dataset(self, path: Path, frame: pd.DataFrame) -> Path:
        """属性のみの GeoPackage を書き出す。"""
        gpd.GeoDataFrame(frame, geometry=[None] * len(frame)).to_file(path, driver="GPKG")
        return path

    def test_load_dataset_cells_filters_analysis_area(self, tmp_path: Path) -> None:
        """IN_ANALYSIS_AREA == 1 のセルだけを読む。"""
        path = self._write_dataset(
            tmp_path / "d.gpkg",
            pd.DataFrame(
                {
                    "cell_id": [1, 2, 3],
                    "IN_ANALYSIS_AREA": [1, 0, 1],
                    "MNDWI": [0.1, 0.2, np.nan],
                    "LULC_WATER_COV": [1.0, 0.0, 0.5],
                }
            ),
        )

        cells = target.load_dataset_cells(path)

        assert cells["cell_id"].tolist() == [1, 3]

    def test_load_dataset_cells_requires_columns(self, tmp_path: Path) -> None:
        """必要な列が無ければ停止する。"""
        path = self._write_dataset(
            tmp_path / "d.gpkg", pd.DataFrame({"cell_id": [1], "IN_ANALYSIS_AREA": [1]})
        )

        with pytest.raises(ValueError, match="必要な列"):
            target.load_dataset_cells(path)

    def test_load_dataset_cells_missing_file(self, tmp_path: Path) -> None:
        """データセットが無ければ停止する。"""
        with pytest.raises(FileNotFoundError):
            target.load_dataset_cells(tmp_path / "missing.gpkg")

    def test_write_rows_csv(self, tmp_path: Path) -> None:
        """行を BOM 付き UTF-8 の CSV に書き、空なら停止する。"""
        path = target.write_rows_csv([{"a": "水域", "b": 1}], tmp_path / "rows.csv")

        with path.open(encoding="utf-8-sig", newline="") as handle:
            assert list(csv.DictReader(handle)) == [{"a": "水域", "b": "1"}]
        with pytest.raises(ValueError, match="書き出す行がありません"):
            target.write_rows_csv([], tmp_path / "empty.csv")
