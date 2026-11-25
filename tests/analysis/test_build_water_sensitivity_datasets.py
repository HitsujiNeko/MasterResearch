"""build_water_sensitivity_datasets.py（水域率の差し替えデータセット）のテスト。

集計の関数は小さな配列で、`run` は解析CRS（EPSG:5897）の 10m 格子にちょうど載る合成の
JRC ラスタと、2x2 セルの合成データセットで検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from src.analysis import build_water_sensitivity_datasets as target
from src.analysis.urban_params.canonical_grid import build_canonical_grid, make_cell_id
from src.common.analysis_runs import build_observation_label, validate_scale_matches_dataset
from src.common.config import PROJECT_ROOT
from src.common.geo_metadata import BBox

ANALYSIS_CRS = CRS.from_epsg(5897)
# ハノイ付近の正準グリッドの行・列（EPSG:5897 で x ≈ 585km、y ≈ 2,325km）
BASE_ROW = 77_500
BASE_COL = 19_500
LAYER_NAME = "limited_20220906_032358"
NAN = np.nan


def _floats(values: list[float]) -> np.ndarray:
    """float32 の配列を作る。"""
    return np.array(values, dtype=np.float32)


def _lulc_frame(**columns: list[float]) -> pd.DataFrame:
    """土地被覆 7 列のデータフレームを作る（指定しないクラスは 0）。"""
    length = len(next(iter(columns.values())))
    return pd.DataFrame(
        {
            name: _floats(columns.get(name.split("_")[1], [0.0] * length))
            for name in target.LULC_COLUMNS
        }
    )


class TestCandidates:
    """JRC の候補の定義のテスト。"""

    def test_keys_bands_and_suffixes(self) -> None:
        """月次・Occurrence 50%・25% の 3 候補で、バンドは取得スクリプトに実在する。"""
        candidates = target.build_candidates()

        assert [c.key for c in candidates] == ["jrc_monthly", "jrc_occ50", "jrc_occ25"]
        assert all(c.band_name in target.JRC_BAND_INDEX for c in candidates)
        assert len({c.dataset_suffix for c in candidates}) == 3

    def test_lookups(self) -> None:
        """月次は 2 が水域・1 が非水域・0 は欠測。Occurrence は閾値以上が水域。"""
        monthly, occ50, occ25 = (c.lookup for c in target.build_candidates())

        assert monthly.tolist() == [0, 2, 1]
        assert (occ50[49], occ50[50]) == (2, 1)
        assert (occ25[24], occ25[25]) == (2, 1)


class TestMasks:
    """有効条件と共通セル集合のテスト。"""

    def test_mask_invalid_fraction_is_inclusive_at_threshold(self) -> None:
        """有効画素率 0.5 ちょうどは有効、それ未満と NaN は欠測。"""
        result = target.mask_invalid_fraction(
            _floats([0.3, 0.3, NAN, 1.0]), _floats([0.5, 0.49, 1.0, 1.0])
        )

        assert result.dtype == np.float32
        np.testing.assert_allclose(result, [0.3, NAN, NAN, 1.0], rtol=1e-6)

    def test_common_mask_requires_every_source(self) -> None:
        """GLC・全候補のどれか 1 つでも欠測なら共通セルに入らない。"""
        mask = target.build_common_cell_mask(
            _floats([0.1, NAN, 0.1, 0.1]),
            {"a": _floats([0.1, 0.1, NAN, 0.1]), "b": _floats([0.1, 0.1, 0.1, NAN])},
        )

        assert mask.tolist() == [True, False, False, False]

    def test_common_mask_rejects_empty(self) -> None:
        """共通セルが無ければ停止する。"""
        with pytest.raises(ValueError, match="ともに有効なセルがありません"):
            target.build_common_cell_mask(_floats([NAN]), {"a": _floats([0.1])})


class TestSummaries:
    """集計のテスト。"""

    def test_water_fraction(self) -> None:
        """集計対象の外と無効セルを除いて、水域セル数・平均・GLC との差を求める。"""
        result = target.summarize_water_fraction(
            _floats([1.0, 0.5, 0.0, NAN, 1.0]),
            _floats([1.0, 0.0, 0.0, 1.0, 0.0]),
            np.array([True, True, True, True, False]),
        )

        assert result["cells"] == 4
        assert result["valid_cells"] == 3
        assert result["water_cells"] == 2
        assert result["water_area_km2"] == pytest.approx(2 * 900 / 1e6)
        assert result["mean"] == pytest.approx(0.5)
        assert result["mean_difference_from_glc"] == pytest.approx(0.5 / 3)
        assert result["mean_absolute_difference_from_glc"] == pytest.approx(0.5 / 3)
        assert result["unchanged_cell_ratio"] == pytest.approx(2 / 3)
        assert result["pearson_with_glc"] == pytest.approx(
            np.corrcoef([1.0, 0.5, 0.0], [1.0, 0.0, 0.0])[0, 1]
        )

    def test_water_fraction_without_values(self) -> None:
        """有効セルが無い・分散が 0 の場合は、統計を None にして止めない。"""
        empty = target.summarize_water_fraction(_floats([NAN]), _floats([0.0]), np.array([True]))
        constant = target.summarize_water_fraction(
            _floats([0.0, 0.0]), _floats([0.0, 1.0]), np.array([True, True])
        )

        assert empty["mean"] is None
        assert empty["water_cells"] == 0
        assert constant["pearson_with_glc"] is None

    def test_composition_overlap_counts_negative_cells(self) -> None:
        """農地・水域の合計を超えて水域が増えたセルだけを二重計上と数え、丸め誤差は数えない。"""
        dataset = _lulc_frame(
            WATER=[0.0, 0.2, 0.1, 0.1, 0.9],
            CROP=[0.5, 0.0, 0.3, 0.0, 0.1],
            WETLAND=[0.5, 0.8, 0.6, 0.9, 0.0],
        )

        result = target.summarize_composition_overlap(
            dataset,
            _floats([0.5, 1.0, 0.1, 0.1 + 5e-8, 0.0]),
            np.array([True, True, True, True, True]),
        )

        assert result["cells"] == 5
        assert result["negative_cells"] == 1
        assert result["minimum"] == pytest.approx(-0.8)
        assert result["negative_mean"] == pytest.approx(-0.8)
        assert result["water_cells"] == 2
        assert result["negative_ratio_in_water_cells"] == pytest.approx(0.5)
        assert result["negative_cells_by_glc_dominant_class"]["LULC_WETLAND_COV"] == 1
        assert sum(result["negative_cells_by_glc_dominant_class"].values()) == 1
        assert result["glc_only_water_cells"] == 1
        assert result["replaced_only_water_cells"] == 2
        # 1 行目は農地 0.5・湿地 0.5 の同率で、列の並びの先（農地）を採る
        by_class = result["replaced_only_water_cells_by_glc_dominant_class"]
        assert (by_class["LULC_CROP_COV"], by_class["LULC_WETLAND_COV"]) == (1, 1)

    def test_normalize_composition(self) -> None:
        """6 列の比を保って和を 1 に戻し、全面水域だったセルの残りは農地に入れる。"""
        dataset = _lulc_frame(
            WATER=[0.2, 1.0, 1.0, 0.0, 0.3],
            CROP=[0.2, 0.0, 0.0, 1.0, 0.7],
            WETLAND=[0.6, 0.0, 0.0, 0.0, 0.0],
        )

        result, summary = target.normalize_composition(
            dataset,
            _floats([0.6, 0.4, 1.0, 1.0, 0.9]),
            np.array([True, True, True, True, False]),
        )

        np.testing.assert_allclose(result["LULC_WATER_COV"], [0.6, 0.4, 1.0, 1.0, NAN], rtol=1e-6)
        np.testing.assert_allclose(result["LULC_CROP_COV"], [0.1, 0.6, 0.0, 0.0, 0.7], atol=1e-6)
        np.testing.assert_allclose(result["LULC_WETLAND_COV"], [0.3, 0, 0, 0, 0], atol=1e-6)
        assert (result.dtypes == dataset.dtypes).all()
        assert list(result.columns) == list(dataset.columns)
        assert summary["cells"] == 4
        # 3 行目は全面水域のままで残りが無い
        assert summary["remainder_to_crop_cells"] == 1
        assert summary["remainder_to_crop_mean"] == pytest.approx(0.6, rel=1e-6)
        assert summary["max_abs_deviation_from_one"] < 1e-6
        assert summary["column_means_glc"]["LULC_WETLAND_COV"] == pytest.approx(0.15, rel=1e-6)
        assert summary["column_means_normalized"]["LULC_WETLAND_COV"] == pytest.approx(
            0.075, rel=1e-6
        )
        np.testing.assert_allclose(dataset["LULC_CROP_COV"], [0.2, 0, 0, 1.0, 0.7], rtol=1e-6)

    def test_normalize_keeps_unchanged_water(self) -> None:
        """水域率が変わらないセルでは、他の列も変わらない。"""
        dataset = _lulc_frame(WATER=[0.2], CROP=[0.3], WETLAND=[0.5])

        result, _ = target.normalize_composition(dataset, _floats([0.2]), np.array([True]))

        np.testing.assert_allclose(result.to_numpy(), dataset.to_numpy(), atol=1e-6)

    def test_population_fill_counts_disagreement(self) -> None:
        """元の欠測を復元し、GLC だけ・差し替え後だけが補完するセルを数える。"""
        result = target.summarize_population_fill(
            density=np.array([0.0, 0.0, NAN, NAN, 5.0]),
            filled_flag=np.array([1, 1, 0, 0, 0]),
            glc_water=_floats([1.0, 0.95, 0.5, 0.5, 1.0]),
            water=_floats([0.9, 0.2, 0.9, NAN, 1.0]),
            cell_mask=np.ones(5, dtype=bool),
        )

        assert result == {
            "originally_missing_cells": 4,
            "glc_filled_cells": 2,
            "replaced_filled_cells": 2,
            "glc_only_filled_cells": 1,
            "replaced_only_filled_cells": 1,
        }

    def test_population_fill_rejects_other_threshold(self) -> None:
        """フラグが GLC の判定と合わない（別の下限で作った）データセットは拒否する。"""
        with pytest.raises(ValueError, match="水域優位の判定と一致しません"):
            target.summarize_population_fill(
                density=np.array([0.0]),
                filled_flag=np.array([1]),
                glc_water=_floats([0.6]),
                water=_floats([0.6]),
                cell_mask=np.array([True]),
            )

    def test_population_suffixes(self) -> None:
        """密度列の接尾辞を取り出す。フラグ列が無い・密度列が無い場合は停止する。"""
        assert target.find_population_suffixes(
            ["POP_DEN_A", "POP_VALID_RATIO_A", "POP_FILLED_A"]
        ) == ["A"]
        with pytest.raises(ValueError, match="フラグ列"):
            target.find_population_suffixes(["POP_DEN_A"])
        with pytest.raises(ValueError, match="人口密度の列"):
            target.find_population_suffixes(["NDVI"])

    def test_replace_changes_only_water(self) -> None:
        """水域列だけが変わり、共通セルの外は欠測になる。元のデータは変わらない。"""
        dataset = pd.DataFrame({"cell_id": [1, 2], "LULC_WATER_COV": _floats([0.1, 0.2])})

        result = target.replace_water_column(dataset, _floats([0.7, 0.8]), np.array([True, False]))

        np.testing.assert_allclose(result["LULC_WATER_COV"], [0.7, NAN], rtol=1e-6)
        assert result["LULC_WATER_COV"].dtype == np.float32
        np.testing.assert_allclose(dataset["LULC_WATER_COV"], [0.1, 0.2], rtol=1e-6)


def _cell_ids() -> list[int]:
    """2x2 セルの cell_id（北西・北東・南西・南東）を返す。"""
    return [
        int(make_cell_id(BASE_ROW + row, BASE_COL + col))
        for row, col in ((1, 0), (1, 1), (0, 0), (0, 1))
    ]


def _write_base_dataset(path: Path, **overrides: object) -> Path:
    """2x2 セルの GLC 版データセットを書く。"""
    frame = pd.DataFrame(
        {
            "cell_id": _cell_ids(),
            "IN_ANALYSIS_AREA": np.array([1, 1, 1, 0], dtype=np.int16),
            "LST": _floats([30.0, 31.0, 32.0, 33.0]),
            "NDVI": _floats([0.1, 0.2, 0.3, 0.4]),
            "BUILD_COV": _floats([0.0, 0.1, 0.2, 0.3]),
            "LULC_WATER_COV": _floats([1.0, 0.0, 0.0, 0.0]),
            "LULC_TREE_COV": _floats([0.0] * 4),
            "LULC_CROP_COV": _floats([0.0, 1.0, 0.0, 1.0]),
            "LULC_BUILT_COV": _floats([0.0] * 4),
            "LULC_RANGE_COV": _floats([0.0] * 4),
            "LULC_WETLAND_COV": _floats([0.0, 0.0, 1.0, 0.0]),
            "LULC_BARE_COV": _floats([0.0] * 4),
            "POP_DEN_WORLDPOP2020": _floats([0.0, 5.0, 6.0, 7.0]),
            "POP_FILLED_WORLDPOP2020": np.array([1, 0, 0, 0], dtype=np.int16),
            "MISSING_REASON": ["none"] * 4,
        }
    ).assign(**overrides)
    pyogrio.write_dataframe(frame, path, layer=LAYER_NAME, driver="GPKG")
    return path


def _write_jrc_raster(path: Path) -> Path:
    """2x2 セルを覆う 10m 格子の JRC ラスタを書く（Occurrence・月次以外のバンドは 0）。"""
    bands = np.zeros((len(target.JRC_BAND_INDEX), 6, 6), dtype=np.uint8)
    occurrence = np.zeros((6, 6), dtype=np.uint8)
    occurrence[0:3, 0:3] = 80  # 北西セル: 水域
    occurrence[3:6, 0:3] = 30  # 南西セル: 25% では水域、50% では非水域
    monthly = np.ones((6, 6), dtype=np.uint8)
    monthly[0:3, 0:3] = 2  # 北西セル: 水域
    monthly[0:3, 3:6] = 0  # 北東セル: 全画素が欠測
    bands[target.JRC_BAND_INDEX["occurrence"] - 1] = occurrence
    bands[target.JRC_BAND_INDEX["monthly_water"] - 1] = monthly
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=6,
        width=6,
        count=len(bands),
        dtype="uint8",
        crs=ANALYSIS_CRS,
        transform=from_origin(BASE_COL * 30.0, (BASE_ROW + 2) * 30.0, 10.0, 10.0),
    ) as destination:
        destination.write(bands)
    return path


@pytest.fixture()
def roi_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """正準グリッドの作成を、2x2 セルの範囲に差し替える。"""
    roi_path = tmp_path / "roi.shp"
    roi_path.write_bytes(b"roi")
    bbox = BBox(
        minx=BASE_COL * 30.0,
        miny=BASE_ROW * 30.0,
        maxx=(BASE_COL + 2) * 30.0,
        maxy=(BASE_ROW + 2) * 30.0,
    )
    spec = build_canonical_grid(bbox, ANALYSIS_CRS, 30.0)
    monkeypatch.setattr(target, "build_roi_canonical_grid", lambda: (spec, roi_path))
    return roi_path


class TestRun:
    """派生データセットの書き出しのテスト。"""

    def test_run_writes_datasets_and_summary(self, tmp_path: Path, roi_grid: Path) -> None:
        """候補ごとに据え置き・正規化の 2 本のデータセットと、来歴つきの要約を書く。"""
        base_path = _write_base_dataset(tmp_path / "dataset_limited_20220906_032358_hanoi_30m.gpkg")
        base_bytes = base_path.read_bytes()
        jrc_path = _write_jrc_raster(tmp_path / "jrc.tif")

        summary_path = target.run(
            base_path, jrc_path, tmp_path / "out", tmp_path / "summary_results.json"
        )

        base = pyogrio.read_dataframe(base_path, read_geometry=False)
        expected = {
            "waterjrcmonthly": [1.0, NAN, 0.0, 0.0],
            "waterjrcocc50": [1.0, NAN, 0.0, 0.0],
            "waterjrcocc25": [1.0, NAN, 1.0, 0.0],
        }
        lulc = list(target.LULC_COLUMNS)
        cases = [
            (f"{suffix}{extra}", water, changed)
            for suffix, water in expected.items()
            for extra, changed in (("", ["LULC_WATER_COV"]), ("norm", lulc))
        ]
        for suffix, water, changed in cases:
            path = tmp_path / "out" / f"dataset_{LAYER_NAME}_{suffix}_hanoi_30m.gpkg"
            frame = pyogrio.read_dataframe(path, read_geometry=False)
            np.testing.assert_allclose(frame["LULC_WATER_COV"], water, atol=1e-6)
            assert list(frame.columns) == list(base.columns)
            pd.testing.assert_frame_equal(frame.drop(columns=changed), base.drop(columns=changed))
            if changed == lulc:
                np.testing.assert_allclose(frame.loc[[0, 2, 3], lulc].sum(axis=1), 1.0, atol=1e-6)
            # 分析スクリプトがファイル名から観測日時・解像度を読めること
            assert build_observation_label(path.stem) == "2022-09-06 03:23:58"
            validate_scale_matches_dataset(path, 30)
        assert base_path.read_bytes() == base_bytes

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["common_cells"]["in_area_cells"] == 3
        assert summary["common_cells"]["common_cells"] == 2
        assert summary["common_cells"]["profile_excluded"]["means"]["LST"] == pytest.approx(31.0)
        # 南西セルは農地率 0・GLC 水域率 0（湿地 1）のまま水域率が 1 になる
        occ25 = summary["candidates"]["jrc_occ25"]
        assert occ25["composition_overlap"]["negative_cells"] == 1
        assert occ25["normalization"]["column_means_normalized"]["LULC_WETLAND_COV"] == 0.0
        assert summary["candidates"]["jrc_occ50"]["composition_overlap"]["negative_cells"] == 0
        assert len(summary["outputs"]["datasets"]) == 6
        assert len(summary["outputs"]["datasets"]["jrc_monthly_fixed"]["sha256"]) == 64
        assert len(summary["provenance"]["inputs"]) == 3

    def test_run_rejects_missing_column(self, tmp_path: Path, roi_grid: Path) -> None:
        """必要な列が無いデータセットは、書き出す前に拒否する。"""
        path = tmp_path / "base.gpkg"
        pyogrio.write_dataframe(
            pd.DataFrame({"cell_id": _cell_ids()}), path, layer=LAYER_NAME, driver="GPKG"
        )

        with pytest.raises(ValueError, match="必要な列がありません"):
            target.run(
                path, _write_jrc_raster(tmp_path / "jrc.tif"), tmp_path / "out", tmp_path / "s.json"
            )
        assert not (tmp_path / "out").exists()

    def test_run_rejects_duplicated_cells(self, tmp_path: Path, roi_grid: Path) -> None:
        """cell_id の重複は拒否する。"""
        path = _write_base_dataset(tmp_path / "base.gpkg", cell_id=[_cell_ids()[0]] * 4)

        with pytest.raises(ValueError, match="重複"):
            target.load_base_dataset(path)


class TestWatchPaths:
    """来歴の追加監視パスのテスト。"""

    def test_watch_paths_exist(self) -> None:
        """追加監視パスはすべて実在するファイルを指す。"""
        missing = [path for path in target.WATCH_PATHS if not (PROJECT_ROOT / path).is_file()]

        assert missing == []
