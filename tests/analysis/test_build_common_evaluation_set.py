"""src/analysis/build_common_evaluation_set.py（共通評価セル集合の生成）のテスト。

有効条件そのものの正しさは各分析スクリプトのテスト（`build_valid_population`）で
検証済みのため、ここでは「各スクリプトの関数を呼んで積を取っていること」・値の
一致検査・標本と fold の割り当て・脱落セルの集計・保存までの結線を対象とする。
データセットの読込は、列選択を模した偽物へ差し替える。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis import analysis_rq3_limited as limited
from src.analysis import analysis_rq3_satellite_only as satellite_only
from src.analysis.build_common_evaluation_set import (
    BLOCK_DROPOUT_RATIO_THRESHOLD,
    SATELLITE_ONLY_CONFIGURATION,
    build_configuration_names,
    build_configuration_populations,
    classify_water_cover,
    compare_common_values,
    draw_evaluation_cells,
    intersect_cell_ids,
    main,
    parse_arguments,
    require_consistent_values,
    resolve_default_output_dir,
    summarize_block_concentration,
    summarize_dropout,
    validate_same_observation,
)
from src.analysis.urban_params.canonical_grid import make_cell_id
from src.common.analysis_dataset import (
    IN_ANALYSIS_AREA_COLUMN,
    IN_ANALYSIS_AREA_SURVEY_COLUMN,
    LST_VALID_RATIO_COLUMN,
)
from src.common.evaluation_cells import (
    BLOCK_ID_COLUMN,
    CELL_ID_COLUMN,
    FOLD_COLUMN,
    load_evaluation_set,
)

N_CELLS = 300
# 30m・ブロック2,700m（90セル）で複数ブロックに散らばるよう、30セル間隔の列に置く。
CELL_IDS = make_cell_id(np.zeros(N_CELLS, dtype=np.int64), np.arange(N_CELLS) * 30)


def _satellite_only_dataframe() -> pd.DataFrame:
    """全行が Satellite Only の有効条件を満たす合成データセット。"""
    rng = np.random.default_rng(seed=1)
    return pd.DataFrame(
        {
            CELL_ID_COLUMN: CELL_IDS,
            "lon": 0.0,
            "lat": 0.0,
            "NDVI": rng.normal(0.4, 0.05, N_CELLS),
            "NDBI": rng.normal(-0.1, 0.05, N_CELLS),
            "NDWI": rng.normal(0.2, 0.05, N_CELLS),
            "LST": rng.normal(35.0, 1.0, N_CELLS),
            IN_ANALYSIS_AREA_COLUMN: 1,
            LST_VALID_RATIO_COLUMN: 0.9,
        }
    )


def _limited_dataframe(satellite: pd.DataFrame) -> pd.DataFrame:
    """全行が Limited（人口3版）の有効条件を満たす合成データ（LST・NDVI・NDBI は引数と同じ）。"""
    rng = np.random.default_rng(seed=2)
    dataframe = satellite[[CELL_ID_COLUMN, "lon", "lat", "LST", "NDVI", "NDBI", "NDWI"]].copy()
    for column in limited.resolve_filter_columns():
        if column not in dataframe.columns:
            dataframe[column] = rng.uniform(0.01, 0.5, N_CELLS)
    for column in limited.ALL_CANDIDATE_FEATURE_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = rng.uniform(1.0, 10.0, N_CELLS)
    for column in limited.resolve_auxiliary_mask_columns(
        ["worldpop2020", "landscan2020", "landscan2023"]
    ):
        dataframe[column] = 1
    dataframe[IN_ANALYSIS_AREA_COLUMN] = 1
    dataframe[LST_VALID_RATIO_COLUMN] = 0.9
    dataframe[limited.VALID_GIS_MASK_COLUMN] = 1
    return dataframe


class TestDefaults:
    """既定値のテスト（分析スクリプトの既定値をそのまま使うこと）。"""

    def test_satellite_only_and_limited_share_defaults(self) -> None:
        """既定値は Satellite Only から読むため、Limited の既定値と一致している必要がある。"""
        satellite_defaults = satellite_only.parse_arguments([])
        limited_defaults = limited.parse_arguments([])

        for name in (
            "lst_valid_ratio_threshold",
            "sample_size",
            "random_state",
            "block_size_m",
            "cv_splits",
            "scale",
        ):
            assert getattr(satellite_defaults, name) == getattr(limited_defaults, name), name

    def test_defaults_follow_analysis_scripts(self) -> None:
        """引数の既定値・データセットは分析スクリプトの既定と同じになる。"""
        args = parse_arguments([])

        assert args.satellite_only_dataset == satellite_only.DEFAULT_DATASET_PATH
        assert args.limited_dataset == limited.DEFAULT_DATASET_PATH
        assert args.block_size_m == satellite_only.DEFAULT_BLOCK_SIZE_M
        assert args.analysis_area == "roi"
        assert args.output_dir.name == "20220906_032358"

    def test_survey_area_gets_its_own_default_output_dir(self) -> None:
        """survey を指定すると、既定の出力先の末尾に範囲が付く（ROI の出力を上書きしない）。"""
        args = parse_arguments(["--analysis-area", "survey"])

        assert args.analysis_area == "survey"
        assert args.output_dir.name == "20220906_032358_area_survey"

    def test_rejects_unknown_analysis_area(self) -> None:
        """対応外の範囲は引数の解析で止める。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--analysis-area", "city"])

    def test_configuration_names(self) -> None:
        """構成は Satellite Only と Limited の人口3版の4つ。"""
        assert build_configuration_names() == [
            "satellite_only",
            "limited_worldpop2020",
            "limited_landscan2020",
            "limited_landscan2023",
        ]


class TestPaths:
    """出力先・観測日時の検査のテスト。"""

    def test_default_output_dir_uses_observation(self) -> None:
        """出力先は観測日時（日付_時刻）のディレクトリになる。"""
        path = resolve_default_output_dir(Path("dataset_satellite_only_20220906_032358_x_30m.gpkg"))

        assert path.parts[-2:] == ("common_evaluation", "20220906_032358")

    def test_default_output_dir_appends_area_except_roi(self) -> None:
        """範囲が roi なら従来どおり、survey なら `_area_survey` を付ける。"""
        dataset = Path("dataset_satellite_only_masksurvey_20220906_032358_hanoi_30m.gpkg")

        assert resolve_default_output_dir(dataset, "roi").name == "20220906_032358"
        assert resolve_default_output_dir(dataset, "survey").name == "20220906_032358_area_survey"

    def test_rejects_different_observations(self) -> None:
        """2つのデータセットの観測日時が違えば停止する。"""
        with pytest.raises(ValueError, match="観測日時"):
            validate_same_observation(
                Path("dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"),
                Path("dataset_limited_20230707_032305_hanoi_30m.gpkg"),
            )

    def test_accepts_same_observation(self) -> None:
        """観測日時が同じなら通す。"""
        validate_same_observation(
            Path("dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"),
            Path("dataset_limited_20220906_032358_hanoi_30m.gpkg"),
        )


class TestBuildConfigurationPopulations:
    """build_configuration_populations のテスト（各スクリプトの有効条件の利用）。"""

    def test_each_configuration_uses_its_own_conditions(self) -> None:
        """Satellite Only は分光指数の欠測、Limited は人口ソースの品質列で母集団が変わる。"""
        satellite = _satellite_only_dataframe()
        limited_dataframe = _limited_dataframe(satellite)
        satellite.loc[0, "NDWI"] = np.nan
        limited_dataframe.loc[1, "VALID_POP_LANDSCAN2020_MASK"] = 0
        limited_dataframe.loc[2, "LULC_TREE_COV"] = np.nan

        populations = build_configuration_populations(satellite, limited_dataframe, 0.5)

        cell_sets = {
            name: set(population[CELL_ID_COLUMN]) for name, population in populations.items()
        }
        assert list(populations) == build_configuration_names()
        assert CELL_IDS[0] not in cell_sets["satellite_only"]
        assert CELL_IDS[0] in cell_sets["limited_worldpop2020"]
        assert CELL_IDS[1] not in cell_sets["limited_landscan2020"]
        assert CELL_IDS[1] in cell_sets["limited_worldpop2020"]
        assert all(
            CELL_IDS[2] not in cell_sets[name] for name in cell_sets if name.startswith("limited")
        )
        assert CELL_IDS[2] in cell_sets["satellite_only"]

    def test_survey_area_applies_to_every_configuration(self) -> None:
        """survey では測量GIS範囲外のセルが全構成から外れ、roi ではその列を見ない。"""
        satellite = _satellite_only_dataframe()
        limited_dataframe = _limited_dataframe(satellite)
        satellite[IN_ANALYSIS_AREA_SURVEY_COLUMN] = 1
        limited_dataframe[IN_ANALYSIS_AREA_SURVEY_COLUMN] = 1
        satellite.loc[3, IN_ANALYSIS_AREA_SURVEY_COLUMN] = 0
        limited_dataframe.loc[3, IN_ANALYSIS_AREA_SURVEY_COLUMN] = 0

        survey = build_configuration_populations(satellite, limited_dataframe, 0.5, "survey")
        roi = build_configuration_populations(satellite, limited_dataframe, 0.5)

        for name in build_configuration_names():
            assert CELL_IDS[3] not in set(survey[name][CELL_ID_COLUMN]), name
            assert len(survey[name]) == N_CELLS - 1, name
            assert len(roi[name]) == N_CELLS, name

    def test_satellite_only_gets_land_cover_from_limited(self) -> None:
        """Satellite Only の母集団にも Limited の建物被覆・水域被覆が付く。"""
        satellite = _satellite_only_dataframe()
        limited_dataframe = _limited_dataframe(satellite)

        populations = build_configuration_populations(satellite, limited_dataframe, 0.5)
        satellite_population = populations[SATELLITE_ONLY_CONFIGURATION]

        np.testing.assert_allclose(
            satellite_population["LULC_WATER_COV"], limited_dataframe["LULC_WATER_COV"]
        )

    def test_limited_population_reflects_building_height_zero_fill(self) -> None:
        """建物が無いセルの高さ欠測は0補完で残る（Limited の関数をそのまま使う証拠）。"""
        satellite = _satellite_only_dataframe()
        limited_dataframe = _limited_dataframe(satellite)
        limited_dataframe.loc[3, ["BUILD_COV", "BUILD_DEN"]] = 0.0
        limited_dataframe.loc[3, ["BUILD_H_MEAN", "BUILD_H_MAX"]] = np.nan

        populations = build_configuration_populations(satellite, limited_dataframe, 0.5)

        assert CELL_IDS[3] in set(populations["limited_worldpop2020"][CELL_ID_COLUMN])


class TestCommonCells:
    """intersect_cell_ids・compare_common_values のテスト。"""

    def test_intersection_is_sorted_and_common_to_all(self) -> None:
        """全構成に共通する cell_id だけを昇順で返す。"""
        populations = {
            "a": pd.DataFrame({CELL_ID_COLUMN: [5, 3, 1, 9]}),
            "b": pd.DataFrame({CELL_ID_COLUMN: [9, 1, 3]}),
            "c": pd.DataFrame({CELL_ID_COLUMN: [3, 9, 7]}),
        }

        np.testing.assert_array_equal(intersect_cell_ids(populations), [3, 9])

    def test_value_mismatch_is_counted_and_stops(self) -> None:
        """共通セル上で値が1件でも違えば数え、停止する。丸め程度の差は一致とみなす。"""
        left = pd.DataFrame(
            {CELL_ID_COLUMN: [1, 2, 3], "LST": [30.0, 31.0, 32.0], "NDVI": 0.1, "NDBI": 0.2}
        )
        right = left.copy()
        right.loc[0, "LST"] = 30.0 + 1e-9
        right.loc[2, "NDVI"] = 0.15

        consistency = compare_common_values(left, right, np.array([1, 2, 3]))

        assert consistency["mismatch_counts"] == {"LST": 0, "NDVI": 1, "NDBI": 0}
        with pytest.raises(ValueError, match="一致しません"):
            require_consistent_values(consistency)

    def test_value_consistency_compares_only_common_cells(self) -> None:
        """共通集合の外のセルの値の違いは数えない。"""
        left = pd.DataFrame({CELL_ID_COLUMN: [1, 2], "LST": [30.0, 31.0], "NDVI": 0.1, "NDBI": 0.2})
        right = left.copy()
        right.loc[1, "LST"] = 99.0

        consistency = compare_common_values(left, right, np.array([1]))

        assert consistency["mismatch_counts"]["LST"] == 0
        require_consistent_values(consistency)


class TestDrawEvaluationCells:
    """draw_evaluation_cells のテスト（標本抽出と fold 割り当て）。"""

    def test_folds_cover_every_row_and_follow_blocks(self) -> None:
        """全行に fold が付き、同じブロックのセルは同じ fold に入る。"""
        cells, summary = draw_evaluation_cells(CELL_IDS, 200, 42, 2_700, 30, 5)

        assert len(cells) == 200
        assert set(cells[FOLD_COLUMN]) == {1, 2, 3, 4, 5}
        assert cells.groupby(BLOCK_ID_COLUMN)[FOLD_COLUMN].nunique().max() == 1
        assert sum(summary["fold_sizes"].values()) == 200
        assert summary["n_blocks"] == cells[BLOCK_ID_COLUMN].nunique()

    def test_does_not_depend_on_input_order(self) -> None:
        """共通集合の並び順が違っても、同じシードなら同じ標本・同じ fold になる。"""
        shuffled = np.random.default_rng(seed=0).permutation(CELL_IDS)

        expected, _ = draw_evaluation_cells(CELL_IDS, 200, 42, 2_700, 30, 5)
        actual, _ = draw_evaluation_cells(shuffled, 200, 42, 2_700, 30, 5)

        pd.testing.assert_frame_equal(actual, expected)

    def test_seed_changes_the_sample(self) -> None:
        """シードを変えると標本が変わる。"""
        first, _ = draw_evaluation_cells(CELL_IDS, 200, 42, 2_700, 30, 5)
        second, _ = draw_evaluation_cells(CELL_IDS, 200, 43, 2_700, 30, 5)

        assert list(first[CELL_ID_COLUMN]) != list(second[CELL_ID_COLUMN])


class TestDropoutSummary:
    """脱落セルの集計のテスト。"""

    def test_water_cover_classes_follow_results_document_bins(self) -> None:
        """水域被覆の階級は「なし（0）・わずか・部分・優勢・水域優位・欠測」に分かれる。"""
        values = pd.Series([0.0, 0.05, 0.1, 0.49, 0.5, 0.89, 0.9, 1.0, np.nan])

        assert classify_water_cover(values) == {
            "none": 1,
            "slight": 1,
            "partial": 2,
            "dominant": 2,
            "water": 2,
            "missing": 1,
        }

    def test_block_concentration_counts_blocks_over_threshold(self) -> None:
        """脱落率がブロック単位で50%を超えるブロックを数える（50%ちょうどは含めない）。"""
        # ブロック0: 4セル中3セル脱落（75%）、ブロック1: 4セル中2セル脱落（50%）、
        # ブロック2: 脱落なし。1ブロック＝90セル幅のため、列を90セルずつずらす。
        columns = np.array([0, 1, 2, 3, 90, 91, 92, 93, 180, 181])
        cell_ids = make_cell_id(np.zeros(len(columns), dtype=np.int64), columns)
        dropped = np.array([1, 1, 1, 0, 1, 1, 0, 0, 0, 0], dtype=bool)

        result = summarize_block_concentration(cell_ids, dropped, 2_700, 30)

        assert BLOCK_DROPOUT_RATIO_THRESHOLD == 0.5
        assert result == {"n_blocks": 3, "blocks_with_dropout": 2, "blocks_over_50pct": 1}

    def test_summarize_dropout_reports_dropped_cells_only(self) -> None:
        """共通集合から外れたセルだけを集計し、件数と割合を記録する。"""
        population = pd.DataFrame(
            {
                CELL_ID_COLUMN: CELL_IDS[:4],
                "LST": [30.0, 32.0, 35.0, 36.0],
                "NDVI": [0.5, 0.3, 0.2, 0.1],
                "NDBI": 0.0,
                "BUILD_COV": [0.0, 0.0, 0.4, 0.5],
                "LULC_WATER_COV": [1.0, np.nan, 0.0, 0.0],
            }
        )

        result = summarize_dropout(population, CELL_IDS[2:4], 2_700, 30)

        assert result["population_size"] == 4
        assert result["dropped_count"] == 2
        assert result["dropped_ratio"] == 0.5
        assert result["dropped"]["lst_mean_c"] == pytest.approx(31.0)
        assert result["dropped"]["means"]["LULC_WATER_COV"] == pytest.approx(1.0)
        assert result["dropped"]["missing_counts"]["LULC_WATER_COV"] == 1


class TestMain:
    """main() の結線のテスト（読込を偽物へ差し替え、保存物を検証する）。"""

    def _install_loaders(
        self, monkeypatch: pytest.MonkeyPatch, satellite: pd.DataFrame, limited_df: pd.DataFrame
    ) -> None:
        """両スクリプトの読込関数を、列選択を模した偽物へ差し替える。"""

        def _fake(source: pd.DataFrame):
            def loader(dataset_path: Path, columns: list[str] | None = None) -> pd.DataFrame:
                available = [column for column in columns or [] if column in source.columns]
                return source[available].copy()

            return loader

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.load_analysis_dataset", _fake(satellite)
        )
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset", _fake(limited_df)
        )

    def _argv(self, tmp_path: Path, *extra: str) -> list[str]:
        """ダミーのデータセットファイルを置き、main() の引数を組み立てる。"""
        satellite_path = tmp_path / "dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"
        limited_path = tmp_path / "dataset_limited_20220906_032358_hanoi_30m.gpkg"
        satellite_path.write_bytes(b"satellite")
        limited_path.write_bytes(b"limited")
        return [
            "--satellite-only-dataset",
            str(satellite_path),
            "--limited-dataset",
            str(limited_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--sample-size",
            "200",
            *extra,
        ]

    def test_saves_cells_within_every_population_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """評価セルは全構成の有効母集団に含まれ、メタデータに母数と脱落の集計が残る。"""
        satellite = _satellite_only_dataframe()
        limited_df = _limited_dataframe(satellite)
        satellite.loc[0, "NDVI"] = np.nan  # Satellite Only だけで落ちる
        limited_df.loc[1, "VALID_POP_LANDSCAN2023_MASK"] = 0  # LandScan2023 だけで落ちる
        self._install_loaders(monkeypatch, satellite, limited_df)

        main(self._argv(tmp_path))

        evaluation_set = load_evaluation_set(tmp_path / "out" / "evaluation_cells_seed42.csv")
        metadata = evaluation_set.metadata
        assert len(evaluation_set.cells) == 200
        assert not set(evaluation_set.cells[CELL_ID_COLUMN]) & {CELL_IDS[0], CELL_IDS[1]}
        assert metadata["common_size"] == N_CELLS - 2
        assert metadata["configurations"]["satellite_only"]["population_size"] == N_CELLS - 1
        assert metadata["configurations"]["limited_landscan2023"]["population_size"] == N_CELLS - 1
        assert metadata["dropout"]["limited_worldpop2020"]["dropped_count"] == 2
        assert metadata["dropout"]["satellite_only"]["dropped_count"] == 1
        assert metadata["value_consistency"]["mismatch_counts"] == {"LST": 0, "NDVI": 0, "NDBI": 0}
        assert metadata["provenance"]["inputs"][0]["path"].endswith(
            "dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"
        )
        assert metadata["analysis_area"] == "roi"
        assert all(
            IN_ANALYSIS_AREA_SURVEY_COLUMN not in configuration["required_mask_columns"]
            for configuration in metadata["configurations"].values()
        )
        json.dumps(metadata, allow_nan=False)

    def test_survey_area_is_recorded_in_metadata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """survey では測量GIS範囲内のセルだけを抽出し、範囲と品質列をメタデータに残す。"""
        satellite = _satellite_only_dataframe()
        limited_df = _limited_dataframe(satellite)
        outside = np.arange(N_CELLS) >= 250  # 測量GIS範囲外の50セル
        satellite[IN_ANALYSIS_AREA_SURVEY_COLUMN] = np.where(outside, 0, 1)
        limited_df[IN_ANALYSIS_AREA_SURVEY_COLUMN] = np.where(outside, 0, 1)
        self._install_loaders(monkeypatch, satellite, limited_df)

        main(self._argv(tmp_path, "--analysis-area", "survey"))

        evaluation_set = load_evaluation_set(tmp_path / "out" / "evaluation_cells_seed42.csv")
        metadata = evaluation_set.metadata
        assert metadata["analysis_area"] == "survey"
        assert metadata["common_size"] == 250
        assert not set(evaluation_set.cells[CELL_ID_COLUMN]) & set(CELL_IDS[outside])
        for name, configuration in metadata["configurations"].items():
            assert IN_ANALYSIS_AREA_SURVEY_COLUMN in configuration["required_mask_columns"], name
            assert configuration["population_size"] == 250, name

    def test_survey_area_requires_survey_mask_column(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """mask_survey を結合していないデータセットで survey を指定すると停止する。"""
        satellite = _satellite_only_dataframe()
        self._install_loaders(monkeypatch, satellite, _limited_dataframe(satellite))

        with pytest.raises(ValueError, match=IN_ANALYSIS_AREA_SURVEY_COLUMN):
            main(self._argv(tmp_path, "--analysis-area", "survey"))
        assert not (tmp_path / "out").exists()

    def test_stops_when_values_differ_between_datasets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """2つのデータセットで共通セルの LST が違えば、何も保存せずに停止する。"""
        satellite = _satellite_only_dataframe()
        limited_df = _limited_dataframe(satellite)
        limited_df.loc[5, "LST"] += 0.5
        self._install_loaders(monkeypatch, satellite, limited_df)

        with pytest.raises(ValueError, match="一致しません"):
            main(self._argv(tmp_path))
        assert not (tmp_path / "out").exists()
