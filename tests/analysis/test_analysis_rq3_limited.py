"""src/analysis/analysis_rq3_limited.py（RQ3 Limitedエントリ）のテスト。

実データでのフルパイプライン実行（RF学習・SHAP計算等の重い処理）は動作確認
手順で扱い、ここでは薄いエントリとしての結線部分のみを対象とする:
CLI引数の解釈、出力パス解決、建物高さの補完、フィルタ条件の組み立て。
cell_idデコードからブロック割り当てまでの結線（assign_canonical_blocks）は
tests/analysis/urban_params/test_canonical_grid.py で検証する。
観測ラベル生成・スケール検証・ランダム分割/Spatial CV学習パイプラインは
`src.common.analysis_runs` へ集約済みのため、tests/common/test_analysis_runs.py
で検証する（Rule of Two: Satellite Onlyと重複した実装をそちらへ抽出済み）。
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from src.analysis.analysis_rq3_limited import (
    ALL_CANDIDATE_FEATURE_COLUMNS,
    BASE_FEATURE_COLUMNS,
    BUILD_COVERAGE_COLUMN,
    BUILD_DENSITY_COLUMN,
    BUILDING_FOOTPRINT_FEATURE_COLUMNS,
    BUILDING_HEIGHT_COLUMNS,
    BUILDING_HEIGHT_MAX_COLUMN,
    BUILDING_HEIGHT_MEAN_COLUMN,
    BUILDING_HEIGHT_MODES,
    BUILDING_HEIGHT_PC1_COLUMN,
    DEFAULT_BUILDING_HEIGHT_MODE,
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_POPULATION_SOURCES,
    DEFAULT_SCALE_M,
    DEFAULT_VARIABLE_SET,
    LULC_FEATURE_COLUMNS,
    LULC_REFERENCE_COLUMN,
    NIGHTLIGHT_FEATURE_COLUMNS,
    OTHER_BASE_FEATURE_COLUMNS,
    SPECTRAL_FEATURE_COLUMNS,
    VALID_GIS_MASK_COLUMN,
    VEGETATION_COVERAGE_COLUMNS,
    add_building_height_pc1,
    build_candidate_correlation_frame,
    build_filtered_sample,
    drop_constant_features,
    fill_missing_building_heights,
    main,
    parse_arguments,
    resolve_building_height_columns,
    resolve_feature_columns,
    resolve_filter_columns,
    resolve_output_stem,
    summarize_vegetation_shap,
)
from src.common.analysis_dataset import IN_ANALYSIS_AREA_COLUMN, LST_VALID_RATIO_COLUMN
from src.common.regression_models import fit_linear_regression

# 既定条件（--variable-set both / --population-source worldpop2020）の説明変数と、
# 非NULLを要求するフィルタ列。build_filtered_sample はモジュール定数ではなく引数で
# 列を受け取るため、テスト側で1度だけ解決して使い回す。
DEFAULT_FEATURE_COLUMNS = resolve_feature_columns(DEFAULT_VARIABLE_SET, DEFAULT_POPULATION_SOURCES)
DEFAULT_FILTER_COLUMNS = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)


class TestParseArguments:
    """parse_arguments のテスト。"""

    def test_defaults(self) -> None:
        """引数を指定しない場合、既定値が設定される。"""
        args = parse_arguments([])

        assert args.dataset_path == DEFAULT_DATASET_PATH
        assert args.output_dir == DEFAULT_OUTPUT_DIR
        assert args.scale == DEFAULT_SCALE_M
        assert args.lst_valid_ratio_threshold == pytest.approx(0.5)
        assert args.require_valid_gis_mask is False
        assert args.sample_size == 100_000
        assert args.random_state == 42
        assert args.cv_splits == 5
        assert args.block_size_m == 2_700
        assert args.shap_sample_size == 2_000
        assert args.shap_background_size == 500
        assert args.rf_trees == 300

    def test_overrides(self) -> None:
        """指定した引数で既定値を上書きできる。"""
        args = parse_arguments(
            [
                "--sample-size",
                "5000",
                "--block-size-m",
                "900",
                "--lst-valid-ratio-threshold",
                "0.8",
                "--require-valid-gis-mask",
            ]
        )

        assert args.sample_size == 5000
        assert args.block_size_m == 900
        assert args.lst_valid_ratio_threshold == pytest.approx(0.8)
        assert args.require_valid_gis_mask is True


class TestResolveOutputStem:
    """resolve_output_stem のテスト。"""

    _DATASET_PATH = Path("data/output/datasets/dataset_limited_20230707_032329_hanoi_30m.gpkg")

    def test_appends_variable_set(self) -> None:
        """変数セットは常に接頭辞へ付与し、構成の異なるランの出力を分ける。"""
        assert (
            resolve_output_stem(
                self._DATASET_PATH,
                "both",
                DEFAULT_POPULATION_SOURCES,
                require_valid_gis_mask=False,
                building_height_mode="both",
            )
            == "dataset_limited_20230707_032329_hanoi_30m_both"
        )
        assert (
            resolve_output_stem(
                self._DATASET_PATH,
                "coverage",
                DEFAULT_POPULATION_SOURCES,
                require_valid_gis_mask=False,
                building_height_mode="both",
            )
            == "dataset_limited_20230707_032329_hanoi_30m_coverage"
        )

    def test_omits_population_part_for_default_sources(self) -> None:
        """人口ソースが既定のままなら接頭辞に現れない
        （既存の出力名との差分を変数セットの追加だけに抑えるため）。
        """
        stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            DEFAULT_POPULATION_SOURCES,
            require_valid_gis_mask=False,
        )

        assert "pop_" not in stem

    def test_appends_population_sources_when_changed(self) -> None:
        """既定から変えた人口ソースは指定順に接頭辞へ現れる。"""
        assert (
            resolve_output_stem(
                self._DATASET_PATH,
                "both",
                ["landscan2020", "landscan2023"],
                require_valid_gis_mask=False,
                building_height_mode="both",
            )
            == "dataset_limited_20230707_032329_hanoi_30m_both_pop_landscan2020_pop_landscan2023"
        )

    def test_sensitivity_analysis_appends_gismask_suffix_last(self) -> None:
        """感度分析（--require-valid-gis-mask）の印は末尾に付ける
        （感度分析の印を末尾に置く既存の規約を保つ）。
        """
        stem = resolve_output_stem(
            self._DATASET_PATH,
            "coverage",
            ["none"],
            require_valid_gis_mask=True,
            building_height_mode="both",
        )

        assert stem == "dataset_limited_20230707_032329_hanoi_30m_coverage_pop_none_gismask"
        assert stem.endswith("_gismask")

    def test_omits_building_height_part_for_both(self) -> None:
        """建物高さが both のランは接頭辞に現れない（既存の出力名を動かさないため）。"""
        stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            DEFAULT_POPULATION_SOURCES,
            require_valid_gis_mask=False,
            building_height_mode="both",
        )

        assert stem == "dataset_limited_20230707_032329_hanoi_30m_both"
        assert "_bh_" not in stem

    def test_appends_building_height_part_between_variable_set_and_population(self) -> None:
        """建物高さパートは変数セットの後・人口の前に入る。"""
        stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            ["landscan2020"],
            require_valid_gis_mask=True,
            building_height_mode="pc1",
        )

        assert stem == (
            "dataset_limited_20230707_032329_hanoi_30m_both_bh_pc1_pop_landscan2020_gismask"
        )
        assert stem.index("_bh_pc1") < stem.index("_pop_")
        assert stem.endswith("_gismask")

    @pytest.mark.parametrize("building_height_mode", ["mean", "max", "pc1"])
    def test_appends_building_height_part_for_non_both_modes(
        self, building_height_mode: str
    ) -> None:
        """both 以外の構成はいずれも接頭辞に現れ、構成ごとに別の出力名になる。"""
        stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            DEFAULT_POPULATION_SOURCES,
            require_valid_gis_mask=False,
            building_height_mode=building_height_mode,
        )

        assert stem == (f"dataset_limited_20230707_032329_hanoi_30m_both_bh_{building_height_mode}")

    def test_building_height_part_is_decided_by_value_not_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既定を変えても出力名は動かない（既定基準ではなく both という値が基準）。

        既定基準で省略すると、既定を変えた瞬間に新しい既定の出力名が `_bh_` 無しの
        形へ移り、`both` で実行済みの既存ランの出力ファイルを上書きする。

        既定を**現在の値とは別の値**へ差し替えて検証する。現在の既定
        （`mean`）のまま差し替えても値が変わらず、検証にならないため。
        """
        monkeypatch.setattr("src.analysis.analysis_rq3_limited.DEFAULT_BUILDING_HEIGHT_MODE", "pc1")

        both_stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            DEFAULT_POPULATION_SOURCES,
            require_valid_gis_mask=False,
            building_height_mode="both",
        )
        mean_stem = resolve_output_stem(
            self._DATASET_PATH,
            "both",
            DEFAULT_POPULATION_SOURCES,
            require_valid_gis_mask=False,
            building_height_mode="mean",
        )

        assert both_stem == "dataset_limited_20230707_032329_hanoi_30m_both"
        assert mean_stem == "dataset_limited_20230707_032329_hanoi_30m_both_bh_mean"
        assert both_stem != mean_stem


class TestFillMissingBuildingHeights:
    """fill_missing_building_heights のテスト。"""

    def _dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "cell_id": [0, 1, 2, 3],
                BUILD_COVERAGE_COLUMN: [0.0, 0.0, 0.3, 0.5],
                BUILD_DENSITY_COLUMN: [0.0, 0.0, 5.0, 3.0],
                "BUILD_H_MEAN": [np.nan, np.nan, np.nan, 12.0],
                "BUILD_H_MAX": [np.nan, np.nan, np.nan, 18.0],
            }
        )

    def test_fills_zero_only_when_no_building_coverage_and_no_building_density(self) -> None:
        """BUILD_COV == 0 かつ BUILD_DEN == 0（建物が無い）かつ高さNULLの行のみ0で補完する。"""
        dataframe = self._dataframe()

        filled, fill_count = fill_missing_building_heights(dataframe)

        assert fill_count == 2  # cell_id 0, 1
        assert filled.loc[0, "BUILD_H_MEAN"] == 0.0
        assert filled.loc[0, "BUILD_H_MAX"] == 0.0
        assert filled.loc[1, "BUILD_H_MEAN"] == 0.0
        assert filled.loc[1, "BUILD_H_MAX"] == 0.0

    def test_does_not_fill_true_missing_values(self) -> None:
        """BUILD_COV > 0 なのに高さNULL（真の欠落）は補完せず残す。"""
        dataframe = self._dataframe()

        filled, _ = fill_missing_building_heights(dataframe)

        assert pd.isna(filled.loc[2, "BUILD_H_MEAN"])
        assert pd.isna(filled.loc[2, "BUILD_H_MAX"])

    def test_does_not_fill_when_coverage_is_zero_but_density_is_positive(self) -> None:
        """BUILD_COV == 0 でも BUILD_DEN > 0（建物の重心はある）なら補完しない
        （ローカルレビューで検出した回帰テスト。30mではBUILD_DEN>0のセルの14.0%が
        BUILD_COV==0になることが docs/01_planning/gis_data/gis_data_buildings.md
        「小さい建物の取りこぼし」で実測されており、BUILD_COV単独では小規模建物を
        「建物が無い」と誤判定する）。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [0],
                BUILD_COVERAGE_COLUMN: [0.0],
                BUILD_DENSITY_COLUMN: [3.0],
                "BUILD_H_MEAN": [np.nan],
                "BUILD_H_MAX": [np.nan],
            }
        )

        filled, fill_count = fill_missing_building_heights(dataframe)

        assert fill_count == 0
        assert pd.isna(filled.loc[0, "BUILD_H_MEAN"])
        assert pd.isna(filled.loc[0, "BUILD_H_MAX"])

    def test_leaves_non_missing_values_untouched(self) -> None:
        """既に値がある行はそのまま維持される。"""
        dataframe = self._dataframe()

        filled, _ = fill_missing_building_heights(dataframe)

        assert filled.loc[3, "BUILD_H_MEAN"] == 12.0
        assert filled.loc[3, "BUILD_H_MAX"] == 18.0

    def test_raises_when_required_column_missing(self) -> None:
        """必要な列が欠けている場合はValueErrorになる。"""
        dataframe = self._dataframe().drop(columns=[BUILD_COVERAGE_COLUMN])

        with pytest.raises(ValueError, match=BUILD_COVERAGE_COLUMN):
            fill_missing_building_heights(dataframe)

    def test_does_not_fill_when_coverage_is_a_tiny_nonzero_value(self) -> None:
        """BUILD_COVがごく僅かでも非ゼロなら補完対象にしない（==0の完全一致比較を固定する境界テスト）。

        BUILD_COVはfine grid（0/1マスク）の平均であり、建物が1つも無いセルは
        演算を経ずに厳密な0.0になる（fill_missing_building_heightsのコメント参照）。
        そのため0近傍の非ゼロ値は「建物が1画素以上ある」ことを意味し、高さが
        NULLなら「真の欠落」として補完せず残すのが正しい。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [0],
                BUILD_COVERAGE_COLUMN: [1e-6],
                BUILD_DENSITY_COLUMN: [0.0],
                "BUILD_H_MEAN": [np.nan],
                "BUILD_H_MAX": [np.nan],
            }
        )

        filled, fill_count = fill_missing_building_heights(dataframe)

        assert fill_count == 0
        assert pd.isna(filled.loc[0, "BUILD_H_MEAN"])
        assert pd.isna(filled.loc[0, "BUILD_H_MAX"])


def _quality_dataframe(n: int = 10) -> pd.DataFrame:
    """フィルタを全件通過する合成データセット（拡張後の全候補列 + 品質列）。

    値は列ごとに独立な変動を与える。全行同値にすると全列が定数列になり、
    `drop_constant_features` の検証が「定数列だけを落とす」ことの確認にならない。
    さらに、全列を同じ単調増加量（行番号由来の`step`）で作ると列どうしが完全な
    線形従属になり、`compute_vif` の補助回帰が決定係数1.0を返して全列のVIFが
    `inf` になる。これでは多重共線性の診断（本スクリプトの主目的）に対するテストが
    「有限のVIFを返す」ことを検証できないため、固定シードの乱数で列ごとに独立な
    変動を与え、再現性を保ちつつ有限のVIFが出る状態にする。
    """
    rng = np.random.default_rng(seed=20230707)

    def _values(base: float, spread: float) -> list[float]:
        """基準値のまわりに、他の列とは独立な変動を与えた列を作る。"""
        return (base + rng.normal(loc=0.0, scale=spread, size=n)).tolist()

    return pd.DataFrame(
        {
            "cell_id": range(n),
            IN_ANALYSIS_AREA_COLUMN: [1] * n,
            VALID_GIS_MASK_COLUMN: [1] * n,
            "BUILD_COV": _values(0.2, 0.03),
            "BUILD_DEN": _values(5.0, 1.0),
            "BUILD_H_MEAN": _values(10.0, 2.0),
            "BUILD_H_MAX": _values(15.0, 3.0),
            "ROAD_DEN": _values(50.0, 10.0),
            "ELEV_MEAN": _values(8.0, 2.0),
            "NDVI": _values(0.4, 0.05),
            "NDBI": _values(-0.1, 0.05),
            "NDWI": _values(0.2, 0.05),
            "LULC_WATER_COV": _values(0.05, 0.01),
            "LULC_TREE_COV": _values(0.10, 0.02),
            "LULC_CROP_COV": _values(0.60, 0.05),
            "LULC_BUILT_COV": _values(0.15, 0.03),
            "LULC_RANGE_COV": _values(0.05, 0.01),
            "LULC_WETLAND_COV": _values(0.03, 0.01),
            "LULC_BARE_COV": _values(0.02, 0.005),
            "NTL_MEAN": _values(12.0, 2.0),
            "POP_DEN_WORLDPOP2020": _values(100.0, 10.0),
            "POP_DEN_LANDSCAN2020": _values(120.0, 10.0),
            "POP_DEN_LANDSCAN2023": _values(130.0, 10.0),
            "LST": _values(35.0, 1.0),
            LST_VALID_RATIO_COLUMN: [0.9] * n,
        }
    )


class TestBuildFilteredSample:
    """build_filtered_sample のテスト（建物高さ補完→フィルタ→サンプリングの結線）。

    戻り値は FilteredSampleResult（sampled / dataset_filled_cell_count /
    population_size / population_filled_cell_count / sample_filled_cell_count）。
    """

    def test_uses_given_feature_columns_for_filtering(self) -> None:
        """渡された feature_columns とLSTの非NULLをフィルタ条件に使う。"""
        dataframe = _quality_dataframe()
        dataframe.loc[0, "NDVI"] = np.nan  # 投入した特徴量の1つがNULL -> 除外されるはず

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert len(result.sampled) == len(dataframe) - 1

    def test_uses_given_columns_not_a_module_constant(self) -> None:
        """モジュール定数ではなく、渡された列だけをフィルタ条件に使う。

        分光指数のみを渡した場合、土地被覆列が欠測していても母数が減らない。
        """
        dataframe = _quality_dataframe()
        dataframe.loc[0, "LULC_BUILT_COV"] = np.nan
        spectral_columns = resolve_feature_columns("spectral", DEFAULT_POPULATION_SOURCES)

        result = build_filtered_sample(
            dataframe,
            filter_columns=spectral_columns,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert len(result.sampled) == len(dataframe)

    def test_applies_filter_before_sampling(self) -> None:
        """フィルタで除外された行はサンプリング対象に含まれない
        （フィルタ→サンプリングの順序を検証する）。

        sample_size(3) をフィルタ後の行数(5) より小さくすることで、
        sample_dataset の「サンプルサイズが行数以上なら全件返す」分岐を
        通らせず、実際のランダムサンプリングを踏ませる。この上で、
        サンプリングで先に選ばれた行がフィルタ前の cell_id (0-4) を含んで
        いないことを検証すれば、呼び出し順序（フィルタ→サンプリング）が
        入れ替わる回帰を検出できる。
        """
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[:4, IN_ANALYSIS_AREA_COLUMN] = 0  # cell_id 0-4 を対象外にする

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=3,
            random_state=42,
        )

        assert len(result.sampled) == 3
        assert set(result.sampled["cell_id"]).issubset({5, 6, 7, 8, 9})

    def test_respects_lst_valid_ratio_threshold(self) -> None:
        """LST_VALID_RATIOのしきい値が正しく渡される。"""
        dataframe = _quality_dataframe()
        dataframe[LST_VALID_RATIO_COLUMN] = 0.3

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert len(result.sampled) == 0

    def test_default_required_mask_columns_ignore_valid_gis_mask(self) -> None:
        """既定（required_mask_columns未指定）ではVALID_GIS_MASKを課さない。

        主結果はVALID_GIS_MASK==0の行も残す方針（計画書の決定事項）のため、
        VALID_GIS_MASKを0にしても除外されないことを検証する。
        """
        dataframe = _quality_dataframe()
        dataframe.loc[0, VALID_GIS_MASK_COLUMN] = 0

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert len(result.sampled) == len(dataframe)

    def test_require_valid_gis_mask_excludes_zero_rows(self) -> None:
        """required_mask_columnsにVALID_GIS_MASKを追加すると==0の行が除外される
        （--require-valid-gis-mask指定時の感度分析の挙動）。
        """
        dataframe = _quality_dataframe()
        dataframe.loc[0, VALID_GIS_MASK_COLUMN] = 0

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
            required_mask_columns=(IN_ANALYSIS_AREA_COLUMN, VALID_GIS_MASK_COLUMN),
        )

        assert len(result.sampled) == len(dataframe) - 1

    def test_fills_building_heights_before_filtering(self) -> None:
        """呼び出し側が補完を挟まなくても、内部で建物高さの0補完を先に適用する
        （fill_missing_building_heightsとの呼び出し順序をこの関数に閉じ込める結線を検証する）。

        全行がフィルタを通過するデータのため、dataset_filled_cell_count・
        population_filled_cell_count・sample_filled_cell_countはすべて一致する
        （3者が乖離するケースは
        test_dataset_population_and_sample_fill_counts_differ_when_filter_excludes_filled_rows
        で検証する）。
        """
        dataframe = _quality_dataframe()
        dataframe.loc[0, "BUILD_COV"] = 0.0
        dataframe.loc[0, "BUILD_DEN"] = 0.0
        dataframe.loc[0, "BUILD_H_MEAN"] = np.nan
        dataframe.loc[0, "BUILD_H_MAX"] = np.nan

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert result.dataset_filled_cell_count == 1
        assert result.population_size == len(dataframe)
        assert result.population_filled_cell_count == 1
        assert result.sample_filled_cell_count == 1
        # 補完されていれば非NULLフィルタを通過し、除外されない。
        assert len(result.sampled) == len(dataframe)
        assert result.sampled.loc[result.sampled["cell_id"] == 0, "BUILD_H_MEAN"].iloc[0] == 0.0
        # 内部一時列（BUILDING_HEIGHT_FILLED_COLUMN）は最終的な戻り値に残さない。
        assert "_BUILDING_HEIGHT_FILLED" not in result.sampled.columns

    def test_dataset_population_and_sample_fill_counts_differ_when_filter_excludes_filled_rows(
        self,
    ) -> None:
        """補完対象セルがフィルタで除外される場合、dataset_filled_cell_count・
        population_filled_cell_count・sample_filled_cell_countは一致しない
        （3者が常に一致するとは限らないことを固定する回帰テスト。取り違えると
        研究成果の記述が実態と乖離するため）。
        """
        dataframe = _quality_dataframe(n=10)
        # cell_id 0: 建物高さを補完対象にする（BUILD_COV==0 かつBUILD_DEN==0 かつ高さNULL）。
        dataframe.loc[0, "BUILD_COV"] = 0.0
        dataframe.loc[0, "BUILD_DEN"] = 0.0
        dataframe.loc[0, "BUILD_H_MEAN"] = np.nan
        dataframe.loc[0, "BUILD_H_MAX"] = np.nan
        # cell_id 0 をIN_ANALYSIS_AREAで除外し、補完はされるがフィルタ後の母数にも
        # 最終サンプルにも残らない状態を作る。
        dataframe.loc[0, IN_ANALYSIS_AREA_COLUMN] = 0

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert result.dataset_filled_cell_count == 1
        assert result.population_size == len(dataframe) - 1  # cell_id 0 が除外される
        assert result.population_filled_cell_count == 0
        assert result.sample_filled_cell_count == 0

    def test_population_size_reflects_filtered_row_count_before_sampling(self) -> None:
        """population_sizeはサンプリング前のフィルタ後件数を反映する
        （sample_sizeでさらに間引かれた後の件数とは異なる）。
        """
        dataframe = _quality_dataframe(n=10)

        result = build_filtered_sample(
            dataframe,
            filter_columns=DEFAULT_FILTER_COLUMNS,
            lst_valid_ratio_threshold=0.5,
            sample_size=3,
            random_state=42,
        )

        assert result.population_size == 10
        assert len(result.sampled) == 3


class TestResolveBuildingHeightColumns:
    """resolve_building_height_columns のテスト。"""

    def test_both_returns_the_two_source_columns(self) -> None:
        """both は BUILD_H_MEAN・BUILD_H_MAX を順序どおり2列とも返す。"""
        assert resolve_building_height_columns("both") == [
            BUILDING_HEIGHT_MEAN_COLUMN,
            BUILDING_HEIGHT_MAX_COLUMN,
        ]

    def test_mean_and_max_return_a_single_column(self) -> None:
        """mean / max はそれぞれ1列だけを返す（高さブロックの共線性を断つ構成）。"""
        assert resolve_building_height_columns("mean") == [BUILDING_HEIGHT_MEAN_COLUMN]
        assert resolve_building_height_columns("max") == [BUILDING_HEIGHT_MAX_COLUMN]

    def test_pc1_returns_the_synthesized_column(self) -> None:
        """pc1 は入力データセットに無い合成列を返す（add_building_height_pc1 が作る）。"""
        assert resolve_building_height_columns("pc1") == [BUILDING_HEIGHT_PC1_COLUMN]
        assert BUILDING_HEIGHT_PC1_COLUMN not in ALL_CANDIDATE_FEATURE_COLUMNS

    def test_every_mode_is_supported(self) -> None:
        """BUILDING_HEIGHT_MODES のすべてが解決でき、構成ごとに列が異なる。

        構成を増やしたときに、解決漏れ（例外）と列の重複（実質同じ構成が2つある
        状態）の両方を検出する。
        """
        resolved = {mode: resolve_building_height_columns(mode) for mode in BUILDING_HEIGHT_MODES}

        assert all(columns for columns in resolved.values())
        assert len({tuple(columns) for columns in resolved.values()}) == len(BUILDING_HEIGHT_MODES)

    def test_raises_for_unsupported_mode(self) -> None:
        """対応外の建物高さ構成は原因の分かる例外にする。"""
        with pytest.raises(ValueError, match="対応していない建物高さ構成"):
            resolve_building_height_columns("median")


class TestResolveFeatureColumns:
    """resolve_feature_columns のテスト。"""

    def test_variable_set_swaps_only_spectral_and_coverage_blocks(self) -> None:
        """差し替わるのは分光指数と土地被覆のブロックだけで、共通ベースは全構成に入る。

        比較軸を「分光 vs 被覆率」に絞るための設計を固定する。
        """
        common = {*BASE_FEATURE_COLUMNS, *NIGHTLIGHT_FEATURE_COLUMNS, "POP_DEN_WORLDPOP2020"}

        # 建物高さ構成は変数セット軸と独立の軸であるため、ここでは both に固定して
        # 「変数セットで差し替わるのは分光・被覆率の2ブロックだけ」を検証する。
        spectral = resolve_feature_columns("spectral", DEFAULT_POPULATION_SOURCES, "both")
        coverage = resolve_feature_columns("coverage", DEFAULT_POPULATION_SOURCES, "both")
        both = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "both")

        assert common.issubset(set(spectral))
        assert common.issubset(set(coverage))
        assert common.issubset(set(both))
        assert set(spectral) - common == set(SPECTRAL_FEATURE_COLUMNS)
        assert set(coverage) - common == set(LULC_FEATURE_COLUMNS)
        assert set(both) - common == {*SPECTRAL_FEATURE_COLUMNS, *LULC_FEATURE_COLUMNS}

    def test_variable_set_counts(self) -> None:
        """3構成の名目変数数を固定する。

        建物高さ2列を投入する `both` 構成で 11 / 14 / 17、既定（高さ1列）で
        10 / 13 / 16 になる。
        """
        for variable_set, both_count in (("spectral", 11), ("coverage", 14), ("both", 17)):
            assert (
                len(resolve_feature_columns(variable_set, DEFAULT_POPULATION_SOURCES, "both"))
                == both_count
            )
            assert (
                len(resolve_feature_columns(variable_set, DEFAULT_POPULATION_SOURCES))
                == both_count - 1
            )

    def test_excludes_lulc_reference_class(self) -> None:
        """参照クラス（農地）は説明変数に含めない。

        7クラスの面積率の和が有効セルで1になるため、そのまま投入すると
        ダミー変数トラップと同一構造の完全な線形従属になる。
        """
        coverage = resolve_feature_columns("coverage", DEFAULT_POPULATION_SOURCES)

        assert LULC_REFERENCE_COLUMN not in coverage
        assert LULC_REFERENCE_COLUMN in ALL_CANDIDATE_FEATURE_COLUMNS

    def test_excludes_vegetation_coverage_as_independent_variable(self) -> None:
        """植生被覆率は独立した説明変数として投入しない（SHAPの事後合算で読む）。"""
        both = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES)

        assert "LULC_VEGETATION_COV" not in both
        # 合算の材料となるクラス列そのものは投入される。
        assert set(VEGETATION_COVERAGE_COLUMNS).issubset(set(both))

    def test_multiple_population_sources_are_all_included(self) -> None:
        """人口を複数指定すると、指定順にすべて投入される。"""
        columns = resolve_feature_columns("spectral", ["worldpop2020", "landscan2023"])

        assert "POP_DEN_WORLDPOP2020" in columns
        assert "POP_DEN_LANDSCAN2023" in columns
        assert columns.index("POP_DEN_WORLDPOP2020") < columns.index("POP_DEN_LANDSCAN2023")

    def test_population_source_none_drops_population_columns(self) -> None:
        """none を指定すると人口の列を1つも投入しない。"""
        columns = resolve_feature_columns("spectral", ["none"])

        assert not [column for column in columns if column.startswith("POP_DEN_")]

    def test_raises_for_unsupported_variable_set(self) -> None:
        """対応外の変数セットは原因の分かる例外にする。"""
        with pytest.raises(ValueError, match="対応していない変数セット"):
            resolve_feature_columns("unknown", DEFAULT_POPULATION_SOURCES)

    def test_raises_for_unknown_population_source(self) -> None:
        """未知の人口ソースは原因の分かる例外にする。"""
        with pytest.raises(ValueError, match="未知の人口密度データソース"):
            resolve_feature_columns("spectral", ["worldpop2019"])

    def test_raises_with_the_right_reason_when_none_is_combined(self) -> None:
        """none の併用は「未知のデータソース」ではなく併用不可として拒否する。

        CLI経由では parse_arguments が先に弾くが、関数を直接呼ぶ経路で誤った
        理由のエラーになると原因の特定を誤らせる。
        """
        with pytest.raises(ValueError, match="併用できません"):
            resolve_feature_columns("spectral", ["none", "worldpop2020"])

    def test_omitting_the_building_height_mode_uses_the_default(self) -> None:
        """建物高さを指定しない場合、既定の構成が使われる。"""
        explicit = resolve_feature_columns(
            "both", DEFAULT_POPULATION_SOURCES, DEFAULT_BUILDING_HEIGHT_MODE
        )

        assert resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES) == explicit

    def test_both_mode_reproduces_the_base_block(self) -> None:
        """both を指定した場合、共通ベースは従来の並び（高さ2列）のままになる。

        既定が mean へ変わった後も、both 構成そのものは以前と同じ列・同じ順序で
        再現できる必要がある（ラン1〜10 との比較可能性を保つため）。
        """
        columns = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "both")

        assert columns[: len(BASE_FEATURE_COLUMNS)] == BASE_FEATURE_COLUMNS

    def test_building_height_mode_swaps_only_the_height_block(self) -> None:
        """差し替わるのは建物高さブロックだけで、他の列は構成間で1つも変わらない。"""
        height_columns = {*BUILDING_HEIGHT_COLUMNS, BUILDING_HEIGHT_PC1_COLUMN}
        both = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "both")
        non_height_columns = [column for column in both if column not in height_columns]

        for mode, expected_height_columns in (
            ("both", list(BUILDING_HEIGHT_COLUMNS)),
            ("mean", [BUILDING_HEIGHT_MEAN_COLUMN]),
            ("max", [BUILDING_HEIGHT_MAX_COLUMN]),
            ("pc1", [BUILDING_HEIGHT_PC1_COLUMN]),
        ):
            columns = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, mode)

            assert [
                column for column in columns if column in height_columns
            ] == expected_height_columns
            assert [
                column for column in columns if column not in height_columns
            ] == non_height_columns

    def test_building_height_mode_keeps_the_column_order(self) -> None:
        """高さ列は共通ベースの位置のまま差し替わる（重要度CSV等の並びを揃えるため）。

        列順は重要度CSV・VIF・SHAPの並びにそのまま現れるため、構成を変えても
        建物・道路・標高…の並びが崩れないことを固定する。
        """
        columns = resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "pc1")

        footprint_size = len(BUILDING_FOOTPRINT_FEATURE_COLUMNS)
        assert columns[:footprint_size] == BUILDING_FOOTPRINT_FEATURE_COLUMNS
        assert columns.index(BUILDING_HEIGHT_PC1_COLUMN) == footprint_size
        other_start = footprint_size + 1
        assert columns[other_start : other_start + len(OTHER_BASE_FEATURE_COLUMNS)] == (
            OTHER_BASE_FEATURE_COLUMNS
        )

    def test_single_height_column_modes_reduce_the_variable_count_by_one(self) -> None:
        """mean / max / pc1 は both より1変数少なくなる（17 → 16）。"""
        assert len(resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "both")) == 17
        for mode in ("mean", "max", "pc1"):
            assert len(resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, mode)) == 16

    def test_raises_for_unsupported_building_height_mode(self) -> None:
        """対応外の建物高さ構成は原因の分かる例外にする。"""
        with pytest.raises(ValueError, match="対応していない建物高さ構成"):
            resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "median")


class TestVariableSetArguments:
    """--variable-set / --population-source / --diagnose-only のCLI検証。"""

    def test_defaults(self) -> None:
        """既定は both / worldpop2020 単独 / 診断のみでない。"""
        args = parse_arguments([])

        assert args.variable_set == DEFAULT_VARIABLE_SET
        assert args.population_source == list(DEFAULT_POPULATION_SOURCES)
        assert args.diagnose_only is False

    def test_accepts_multiple_population_sources(self) -> None:
        """人口ソースは複数受け取れる（3版同時投入へ切り替えられるようにする）。"""
        args = parse_arguments(
            ["--population-source", "worldpop2020", "landscan2020", "landscan2023"]
        )

        assert args.population_source == ["worldpop2020", "landscan2020", "landscan2023"]

    def test_rejects_none_combined_with_other_sources(self) -> None:
        """none は他の値と併用できない（人口を投入するのかしないのかが定まらないため）。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--population-source", "none", "worldpop2020"])

    def test_rejects_duplicated_population_sources(self) -> None:
        """同じ人口ソースの重複指定は拒否する（同一列の二重投入は完全共線になる）。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--population-source", "worldpop2020", "worldpop2020"])

    def test_rejects_unknown_variable_set(self) -> None:
        """対応外の変数セットはargparseの段階で拒否する。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--variable-set", "unknown"])

    def test_building_height_defaults_to_the_adopted_mode(self) -> None:
        """--building-height の既定は採用構成（mean）である。

        建物高さ3構成の比較の結果、平均高さ1列を投入する構成を採用した。既定を
        固定しておくことで、以後のランが既定のまま共線性を持ち込まないようにする。
        """
        args = parse_arguments([])

        assert args.building_height == DEFAULT_BUILDING_HEIGHT_MODE
        assert DEFAULT_BUILDING_HEIGHT_MODE == "mean"

    @pytest.mark.parametrize("building_height_mode", ["both", "mean", "max", "pc1"])
    def test_accepts_every_building_height_mode(self, building_height_mode: str) -> None:
        """4構成すべてをCLIから指定できる。"""
        args = parse_arguments(["--building-height", building_height_mode])

        assert args.building_height == building_height_mode

    def test_rejects_unknown_building_height_mode(self) -> None:
        """対応外の建物高さ構成はargparseの段階で拒否する。"""
        with pytest.raises(SystemExit):
            parse_arguments(["--building-height", "median"])


class TestDropConstantFeatures:
    """drop_constant_features のテスト。"""

    def test_drops_only_zero_variance_columns(self) -> None:
        """分散0の列だけを除外し、他の列は順序を保って残す。"""
        dataframe = pd.DataFrame(
            {
                "varying": [1.0, 2.0, 3.0],
                "constant": [0.0, 0.0, 0.0],
                "also_varying": [5.0, 4.0, 3.0],
            }
        )

        kept, dropped = drop_constant_features(dataframe, ["varying", "constant", "also_varying"])

        assert kept == ["varying", "also_varying"]
        assert dropped == ["constant"]

    def test_drops_all_zero_coverage_column(self) -> None:
        """ROIに1画素も存在しないクラスの被覆率（全セル0.0）を除外する。

        主ソースGLCのハノイROIでは裸地クラスの画素が0であり、LULC_BARE_COV が
        定数列になる。残すとVIFが inf になり、実体のある共線性と区別できなくなる。
        """
        dataframe = _quality_dataframe()
        dataframe["LULC_BARE_COV"] = 0.0

        kept, dropped = drop_constant_features(
            dataframe, resolve_feature_columns("coverage", DEFAULT_POPULATION_SOURCES)
        )

        assert dropped == ["LULC_BARE_COV"]
        assert "LULC_BARE_COV" not in kept


class TestBuildCandidateCorrelationFrame:
    """build_candidate_correlation_frame のテスト。"""

    def test_targets_all_candidate_columns_not_the_model_features(self) -> None:
        """相関行列の対象は変数セットに依らず全候補列である。

        人口3版どうし・参照クラスを含む土地被覆7クラス全部のように、特定の
        変数セットには同時に入らない組み合わせも診断対象に含める。
        """
        dataframe = _quality_dataframe()

        frame, missing = build_candidate_correlation_frame(dataframe)

        assert list(frame.columns) == ALL_CANDIDATE_FEATURE_COLUMNS
        assert missing == []
        assert LULC_REFERENCE_COLUMN in frame.columns
        assert {
            "POP_DEN_WORLDPOP2020",
            "POP_DEN_LANDSCAN2020",
            "POP_DEN_LANDSCAN2023",
        }.issubset(set(frame.columns))

    def test_drops_rows_with_missing_candidate_values(self) -> None:
        """候補列に欠測を含む行は落とす（ペアワイズ削除で母数が揃わなくなるため）。"""
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[0, "LULC_CROP_COV"] = np.nan

        frame, _ = build_candidate_correlation_frame(dataframe)

        assert len(frame) == 9

    def test_reports_candidate_columns_absent_from_dataset(self) -> None:
        """データセットに無い候補列は結果から外し、名前を報告する。"""
        dataframe = _quality_dataframe().drop(columns=["NTL_MEAN"])

        frame, missing = build_candidate_correlation_frame(dataframe)

        assert "NTL_MEAN" not in frame.columns
        assert missing == ["NTL_MEAN"]


class TestSummarizeVegetationShap:
    """summarize_vegetation_shap のテスト。"""

    def test_sums_mean_abs_shap_of_vegetation_classes(self) -> None:
        """樹林・草地低木の平均絶対SHAP値を合算する（SHAP値は加法的）。"""
        mean_abs_shap = {
            "LULC_TREE_COV": 0.4,
            "LULC_RANGE_COV": 0.1,
            "LULC_BUILT_COV": 0.9,
        }

        result = summarize_vegetation_shap(mean_abs_shap, list(mean_abs_shap))

        assert result is not None
        assert result["columns"] == VEGETATION_COVERAGE_COLUMNS
        assert result["excluded_columns"] == []
        assert result["mean_abs_shap_sum"] == pytest.approx(0.5)

    def test_returns_none_when_no_vegetation_column_in_model(self) -> None:
        """分光指数のみの構成では合算する対象が無いため None を返す。"""
        spectral = resolve_feature_columns("spectral", DEFAULT_POPULATION_SOURCES)
        mean_abs_shap = dict.fromkeys(spectral, 0.1)

        assert summarize_vegetation_shap(mean_abs_shap, spectral) is None

    def test_reports_excluded_columns_when_partially_present(self) -> None:
        """一部の植生クラスだけが投入されている場合、欠けた列名を記録する
        （定数列として除外されたケースを合算結果から追えるようにする）。
        """
        mean_abs_shap = {"LULC_TREE_COV": 0.4}

        result = summarize_vegetation_shap(mean_abs_shap, ["LULC_TREE_COV"])

        assert result is not None
        assert result["columns"] == ["LULC_TREE_COV"]
        assert result["excluded_columns"] == ["LULC_RANGE_COV"]
        assert result["mean_abs_shap_sum"] == pytest.approx(0.4)


class TestResolveFilterColumns:
    """resolve_filter_columns のテスト。

    フィルタ列を投入列と一致させると、変数セットごとにフィルタ後の母数が変わり、
    「分光指数 vs 被覆率型のどちらが LST をよりよく説明するか」の比較が母数差の
    影響と混ざる。ここではその分離を固定する。
    """

    def test_is_constant_across_variable_sets(self) -> None:
        """フィルタ列は変数セット・建物高さ構成の指定を受け取らない（構成に依らず一定）。

        `resolve_filter_columns` は建物高さ構成を引数に取らず、内部で `both` を
        固定して渡す。既定値（`DEFAULT_BUILDING_HEIGHT_MODE`）を読まないため、
        既定が変わってもフィルタ列は動かない。動くと構成間・ラン間で母数が変わる。
        """
        filter_columns = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)

        assert filter_columns == resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, "both")

    def test_is_a_superset_of_every_variable_set(self) -> None:
        """フィルタ列はどの変数セットの投入列も包含する。"""
        filter_columns = set(resolve_filter_columns(DEFAULT_POPULATION_SOURCES))

        for variable_set in ("spectral", "coverage", "both"):
            assert set(resolve_feature_columns(variable_set, DEFAULT_POPULATION_SOURCES)).issubset(
                filter_columns
            )

    def test_always_requires_spectral_columns(self) -> None:
        """分光指数は coverage 構成でも非NULLを要求する。

        `filter_valid_rows` は VALID_SATELLITE_MASK を独立の条件として課さず、
        分光指数の非NULL要求が包含することを前提にしている。投入列でフィルタすると
        coverage のときだけこの前提が崩れ、分光指数がすべてNULLのセル（雲マスク
        由来の欠測）が母集団へ混入する。
        """
        filter_columns = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)

        assert set(SPECTRAL_FEATURE_COLUMNS).issubset(set(filter_columns))

    def test_requires_only_the_selected_population_versions(self) -> None:
        """人口は選択した版のみ要求する（投入しない版の欠測で母数を減らさない）。"""
        filter_columns = resolve_filter_columns(["worldpop2020"])

        assert "POP_DEN_WORLDPOP2020" in filter_columns
        assert "POP_DEN_LANDSCAN2020" not in filter_columns
        assert "POP_DEN_LANDSCAN2023" not in filter_columns

    def test_always_requires_both_building_height_columns(self) -> None:
        """投入する高さ列が1本でも、非NULL要求は2列とも課す。

        片方だけを要求すると、もう片方だけが欠測のセルが構成によって出入りし、
        建物高さ3構成の比較が母数差の影響と混ざる。
        """
        filter_columns = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)

        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(filter_columns))

    def test_is_a_superset_of_every_building_height_mode(self) -> None:
        """フィルタ列はどの建物高さ構成の投入列も包含する（合成列を除く）。"""
        filter_columns = set(resolve_filter_columns(DEFAULT_POPULATION_SOURCES))

        for mode in ("both", "mean", "max"):
            assert set(resolve_feature_columns("both", DEFAULT_POPULATION_SOURCES, mode)).issubset(
                filter_columns
            )

    def test_never_requires_the_synthesized_pc1_column(self) -> None:
        """合成列 BUILD_H_PC1 は入力データセットに無いため、フィルタ列に含めない。

        含めると main() の「フィルタに必要な列がデータセットに存在しません」検証に
        必ず引っかかり、pc1 構成が実行不能になる。
        """
        filter_columns = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)

        assert BUILDING_HEIGHT_PC1_COLUMN not in filter_columns


class TestPopulationIsEqualAcrossVariableSets:
    """変数セットを変えてもフィルタ後の母数が変わらないことの回帰テスト。"""

    def test_same_row_count_for_every_variable_set(self) -> None:
        """分光指数がすべてNULLのセルは、どの変数セットでも同じように除外される。"""
        dataframe = _quality_dataframe(n=10)
        # 雲マスク由来の欠測を模す（VALID_SATELLITE_MASK == 0 に相当する状態）。
        for column in SPECTRAL_FEATURE_COLUMNS:
            dataframe.loc[0, column] = np.nan

        filter_columns = resolve_filter_columns(DEFAULT_POPULATION_SOURCES)
        row_counts = set()
        for variable_set in ("spectral", "coverage", "both"):
            result = build_filtered_sample(
                dataframe,
                filter_columns=filter_columns,
                lst_valid_ratio_threshold=0.5,
                sample_size=0,
                random_state=42,
            )
            row_counts.add(len(result.sampled))
            # 投入列は構成ごとに変わるが、母数には影響しない。
            assert len(resolve_feature_columns(variable_set, DEFAULT_POPULATION_SOURCES)) > 0

        assert row_counts == {len(dataframe) - 1}

    def test_coverage_would_leak_cloudy_cells_without_the_fix(self) -> None:
        """投入列でフィルタすると coverage だけ母数が増えることを示す（退行の検出）。

        修正の効果を測るため、あえて coverage の投入列でフィルタした場合と比較する。
        両者の母数が一致してしまうと、この回帰テストは意味を失う。
        """
        dataframe = _quality_dataframe(n=10)
        for column in SPECTRAL_FEATURE_COLUMNS:
            dataframe.loc[0, column] = np.nan

        with_fix = build_filtered_sample(
            dataframe,
            filter_columns=resolve_filter_columns(DEFAULT_POPULATION_SOURCES),
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )
        without_fix = build_filtered_sample(
            dataframe,
            filter_columns=resolve_feature_columns("coverage", DEFAULT_POPULATION_SOURCES),
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
        )

        assert len(with_fix.sampled) == len(dataframe) - 1
        assert len(without_fix.sampled) == len(dataframe)


def _building_height_frame(n: int = 20_000, seed: int = 20230707) -> pd.DataFrame:
    """建物高さ2列と目的変数を持つ合成サンプル（主成分化のテスト用）。

    実データの分布に寄せて8割のセルを高さ0（建物が無いセル）にし、残りに
    ガンマ分布の高さを与える。BUILD_H_MAX には独立な上振れを足して相関を
    r ≈ 0.98 に落としてある。実データのラン5は r = +0.986 であり、r が低いほど
    固有値の差（1 - r）が小さく主成分の向きが不安定になるため、**実データより
    保守側**の設定になる。

    LST は他の2変数が主で、建物高さの寄与を小さく（係数0.02）してある。
    実データのRF重要度でも建物高さ2変数の合計は1%未満であり、高さブロックへの
    依存度を実データより高く設定すると fold 内 fit との差を過大に見積もるため。

    Args:
        n: 生成する行数。
        seed: 乱数シード。
    Returns:
        BUILD_H_MEAN / BUILD_H_MAX / OTHER_A / OTHER_B / LST を持つデータフレーム。
    """
    rng = np.random.default_rng(seed)
    has_building = rng.random(n) > 0.8
    base_height = rng.gamma(2.0, 3.0, size=n)
    mean_height = np.where(has_building, base_height, 0.0)
    max_height = np.where(
        has_building, base_height * 1.5 + np.abs(rng.normal(0.0, 3.5, size=n)), 0.0
    )
    other_a = rng.normal(0.0, 1.0, size=n)
    other_b = rng.normal(0.0, 1.0, size=n)
    return pd.DataFrame(
        {
            "BUILD_H_MEAN": mean_height,
            "BUILD_H_MAX": max_height,
            "OTHER_A": other_a,
            "OTHER_B": other_b,
            "LST": (
                30.0
                + 0.8 * other_a
                + 0.5 * other_b
                + 0.02 * mean_height
                + rng.normal(0.0, 1.0, size=n)
            ),
        }
    )


class TestAddBuildingHeightPc1:
    """add_building_height_pc1 のテスト。

    許容誤差つきで検証する。z空間の loadings は代数的には 1/√2 に決まるが、
    sklearn の PCA は SVD による数値計算であり厳密な等価にはならないため、
    厳密比較にすると必ず失敗する。
    """

    def test_loadings_are_equal_weights_for_positively_correlated_columns(self) -> None:
        """正相関の2変数では loadings が (1/√2, 1/√2) になる。

        標準化した2変数の相関行列 [[1, r], [r, 1]] の固有ベクトルは
        r > 0 のとき (1/√2, 1/√2)（固有値 1 + r）である。
        """
        frame = _building_height_frame()

        _, diagnostics = add_building_height_pc1(frame)

        assert diagnostics["source_correlation_pearson"] > 0
        expected = 1.0 / np.sqrt(2.0)
        assert diagnostics["loadings"][BUILDING_HEIGHT_MEAN_COLUMN] == pytest.approx(expected)
        assert diagnostics["loadings"][BUILDING_HEIGHT_MAX_COLUMN] == pytest.approx(expected)

    def test_explained_variance_ratio_matches_the_algebraic_value(self) -> None:
        """寄与率は (1 + r) / 2 になる（2変数の相関行列の固有値 1 + r を 2 で割った値）。"""
        frame = _building_height_frame()

        _, diagnostics = add_building_height_pc1(frame)

        correlation = diagnostics["source_correlation_pearson"]
        assert diagnostics["explained_variance_ratio"] == pytest.approx((1.0 + correlation) / 2.0)

    def test_sign_is_normalized_towards_the_mean_column(self) -> None:
        """符号は BUILD_H_MEAN への寄与が正になる向きへ揃える。

        揃えないと「PC1が大きいほど建物が低い」向きが偶発的に生じ、標準化係数・
        SHAP値の符号解釈が反転する。負相関のケースでも向きは MEAN 基準で決まる。
        """
        frame = _building_height_frame()
        negative = frame.copy()
        negative[BUILDING_HEIGHT_MAX_COLUMN] = -negative[BUILDING_HEIGHT_MAX_COLUMN]

        for target in (frame, negative):
            with_pc1, diagnostics = add_building_height_pc1(target)

            assert diagnostics["loadings"][BUILDING_HEIGHT_MEAN_COLUMN] > 0
            correlation = with_pc1[BUILDING_HEIGHT_PC1_COLUMN].corr(
                with_pc1[BUILDING_HEIGHT_MEAN_COLUMN]
            )
            assert correlation > 0

    def test_negative_correlation_flips_the_max_loading(self) -> None:
        """負相関では第1主成分が (1/√2, -1/√2) へ入れ替わる（無条件の恒等式ではない）。"""
        frame = _building_height_frame()
        frame[BUILDING_HEIGHT_MAX_COLUMN] = -frame[BUILDING_HEIGHT_MAX_COLUMN]

        _, diagnostics = add_building_height_pc1(frame)

        expected = 1.0 / np.sqrt(2.0)
        assert diagnostics["source_correlation_pearson"] < 0
        assert diagnostics["loadings"][BUILDING_HEIGHT_MEAN_COLUMN] == pytest.approx(expected)
        assert diagnostics["loadings"][BUILDING_HEIGHT_MAX_COLUMN] == pytest.approx(-expected)

    def test_does_not_modify_the_input_dataframe(self) -> None:
        """入力データフレームは変更せず、合成列を足した複製を返す。"""
        frame = _building_height_frame(n=100)
        original_columns = list(frame.columns)

        with_pc1, _ = add_building_height_pc1(frame)

        assert list(frame.columns) == original_columns
        assert BUILDING_HEIGHT_PC1_COLUMN not in frame.columns
        assert list(with_pc1.columns) == [*original_columns, BUILDING_HEIGHT_PC1_COLUMN]

    def test_records_the_fit_sample_size_and_standardization(self) -> None:
        """fit対象の行数・標準化統計を記録する（母集団ではなく分析サンプル上の値）。"""
        frame = _building_height_frame(n=500)

        _, diagnostics = add_building_height_pc1(frame)

        assert diagnostics["fit_row_count"] == 500
        assert diagnostics["column"] == BUILDING_HEIGHT_PC1_COLUMN
        assert diagnostics["source_columns"] == list(BUILDING_HEIGHT_COLUMNS)
        means = diagnostics["standardization"]["means"]
        scales = diagnostics["standardization"]["scales"]
        assert means[BUILDING_HEIGHT_MEAN_COLUMN] == pytest.approx(
            float(frame[BUILDING_HEIGHT_MEAN_COLUMN].mean())
        )
        assert scales[BUILDING_HEIGHT_MEAN_COLUMN] == pytest.approx(
            float(frame[BUILDING_HEIGHT_MEAN_COLUMN].std(ddof=0))
        )

    def test_degenerate_input_is_recorded_instead_of_breaking_the_json(self) -> None:
        """高さ2列が定数の場合、非有限値をNoneへ落として該当項目名を残す。

        標準化後が全て0になり寄与率・元2列の相関がNaNになる。そのまま残すと
        `save_summary`（allow_nan=False）がフル実行の**最終保存時**に落ち、
        モデル学習・SHAPをすべて終えた後で、どの値が原因かも分からない状態になる。
        """
        frame = pd.DataFrame(
            {
                BUILDING_HEIGHT_MEAN_COLUMN: [3.0] * 50,
                BUILDING_HEIGHT_MAX_COLUMN: [7.0] * 50,
            }
        )

        with warnings.catch_warnings():
            # 定数列どうしの相関は0除算になる（NaNとして受け取るのが意図した挙動）。
            warnings.simplefilter("ignore", RuntimeWarning)
            _, diagnostics = add_building_height_pc1(frame)

        assert diagnostics["non_finite_items"] == [
            "explained_variance_ratio",
            "source_correlation_pearson",
        ]
        assert diagnostics["explained_variance_ratio"] is None
        assert diagnostics["source_correlation_pearson"] is None
        # save_summary と同じ条件でJSONへ書き出せる（最終保存時に落ちない）。
        json.dumps(diagnostics, allow_nan=False, ensure_ascii=False)

    def test_finite_input_records_no_non_finite_items(self) -> None:
        """通常の入力では非有限の項目は記録されない。"""
        _, diagnostics = add_building_height_pc1(_building_height_frame(n=500))

        assert diagnostics["non_finite_items"] == []

    def test_raises_for_missing_columns(self) -> None:
        """建物高さ列が無い場合は原因の分かる例外にする。"""
        frame = _building_height_frame(n=10).drop(columns=[BUILDING_HEIGHT_MAX_COLUMN])

        with pytest.raises(ValueError, match=BUILDING_HEIGHT_MAX_COLUMN):
            add_building_height_pc1(frame)

    def test_raises_when_nulls_remain(self) -> None:
        """欠測が残った状態で呼ばれた場合は原因の分かる例外にする。

        補完・フィルタの前に呼ぶと欠測が残り、PCAが黙って例外を投げるか
        誤った統計量でfitされるため、呼び出し順の誤りをここで検出する。
        """
        frame = _building_height_frame(n=10)
        frame.loc[0, BUILDING_HEIGHT_MEAN_COLUMN] = np.nan

        with pytest.raises(ValueError, match="欠測が残っている"):
            add_building_height_pc1(frame)

    def test_whole_sample_fit_agrees_with_fold_internal_fit(self) -> None:
        """全体fitのPC1は、fold内fitのPC1と実質同じ結果を与える。

        全体fitが持ち込むfold依存は「高さ2列の標準偏差の比」だけであり、
        平均・尺度に由来するリークは fit_linear_regression の fold 内標準化が
        既に除いている。fold内fitを実装しない判断（共通モジュールへfold内変換の
        仕組みを持ち込むコストに見合わない）の根拠を、許容誤差つきで固定する。

        ランダムフォレストは対象にしない。RF自身の乱数シードによる決定係数の
        振れ幅（1e-03オーダー）の方が大きく、判定材料にならないため。
        """
        frame = _building_height_frame()
        rng = np.random.default_rng(seed=20230707)
        # 建物のあるセルを学習側へ多く寄せ、fold と全体で高さ分布をずらす
        # （標準偏差の比が変わる状況を作るため）。
        has_building = frame[BUILDING_HEIGHT_MEAN_COLUMN].to_numpy() > 0
        in_train = np.where(
            has_building, rng.random(len(frame)) < 0.9, rng.random(len(frame)) < 0.7
        )

        whole_fit, _ = add_building_height_pc1(frame)
        scaler = StandardScaler().fit(frame.loc[in_train, BUILDING_HEIGHT_COLUMNS])
        pca = PCA(n_components=1).fit(
            scaler.transform(frame.loc[in_train, BUILDING_HEIGHT_COLUMNS])
        )
        fold_scores = pca.transform(scaler.transform(frame[BUILDING_HEIGHT_COLUMNS]))[:, 0]
        if pca.components_[0][0] < 0:
            fold_scores = -fold_scores

        correlation = float(
            np.corrcoef(whole_fit[BUILDING_HEIGHT_PC1_COLUMN].to_numpy(), fold_scores)[0, 1]
        )
        assert correlation > 1.0 - 1e-6

        features = [BUILDING_HEIGHT_PC1_COLUMN, "OTHER_A", "OTHER_B"]

        def _r2(pc1_scores: np.ndarray) -> float:
            """指定したPC1列で線形回帰を学習し、テスト側の決定係数を返す。"""
            data = frame.copy()
            data[BUILDING_HEIGHT_PC1_COLUMN] = pc1_scores
            result, _, _ = fit_linear_regression(
                data.loc[in_train, features],
                data.loc[~in_train, features],
                data.loc[in_train, "LST"],
                data.loc[~in_train, "LST"],
            )
            return float(result["metrics"]["r2"])

        r2_difference = abs(
            _r2(whole_fit[BUILDING_HEIGHT_PC1_COLUMN].to_numpy()) - _r2(fold_scores)
        )

        assert r2_difference < 1e-4


class TestMainDiagnoseOnly:
    """main() に新規追加した2つのロジックを検証する
    （フィルタ列欠損時のValueError送出、--diagnose-only指定時のモデル学習・SHAP省略）。

    データ読込（load_analysis_dataset）だけを合成データへ差し替え、実データや
    実GeoPackageは使わない（薄いエントリとしての結線部分のみを対象とする方針は
    本ファイル冒頭のdocstring参照）。
    """

    def _run_argv(self, dataset_path: Path, output_dir: Path, *extra_args: str) -> list[str]:
        """main() が読むCLI引数を組み立てる（--diagnose-onlyを常に含める）。"""
        return [
            "analysis_rq3_limited.py",
            "--dataset-path",
            str(dataset_path),
            "--output-dir",
            str(output_dir),
            "--diagnose-only",
            *extra_args,
        ]

    def test_missing_filter_column_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """フィルタに必要な列がデータセットに存在しない場合、ValueErrorを送出する。

        既定の --population-source（worldpop2020）が要求する列を合成データから
        落とすことで、main() の「フィルタに必要な列がデータセットに存在しません」
        検証（load_analysis_dataset の直後、build_filtered_sample の前）を踏ませる。
        """
        dataframe = _quality_dataframe().drop(columns=["POP_DEN_WORLDPOP2020"])
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(sys, "argv", self._run_argv(dataset_path, output_dir))

        with pytest.raises(ValueError, match="POP_DEN_WORLDPOP2020"):
            main()

    def test_diagnose_only_skips_modeling_and_writes_diagnostics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--diagnose-only指定時、モデル学習・SHAPを実行せず診断結果のみを保存する。

        モデル学習・SHAP関数を「呼ばれたら失敗」に差し替えることで、main() の
        `args.diagnose_only` による早期return分岐が実際に効いていること
        （後続のモデル学習コードへ進まないこと）を確認する。
        """
        dataframe = _quality_dataframe(n=20)
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("--diagnose-only指定時にモデル学習・SHAPが呼ばれてはならない")

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.run_random_split_models", _fail_if_called
        )
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.run_spatial_cv_models", _fail_if_called
        )
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.compute_shap_outputs", _fail_if_called
        )

        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(
            sys,
            "argv",
            self._run_argv(dataset_path, output_dir, "--variable-set", "spectral"),
        )

        main()

        diagnostics_files = list(output_dir.glob("*_diagnostics.json"))
        assert len(diagnostics_files) == 1
        diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))
        assert diagnostics["scenario"] == "Limited"
        assert diagnostics["mode"] == "diagnose_only"
        assert diagnostics["variable_set"] == "spectral"
        assert diagnostics["sample_size"] == len(dataframe)
        assert diagnostics["population_size"] == len(dataframe)
        assert "vif" in diagnostics
        assert "correlation_pearson_csv" in diagnostics["outputs"]
        # モデル学習・SHAP由来の結果ファイルは存在しない（診断のみで終了した証跡）。
        assert not list(output_dir.glob("*_results.json"))

    def test_both_mode_records_no_component_diagnostics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """both では主成分の診断情報を持たず、出力名にも建物高さは現れない。

        出力名の省略基準は既定値ではなく both という値であるため、既定が mean へ
        変わった後も both のランの出力名は `_bh_` 無しのまま動かない。これにより
        ラン1〜10 の既存の出力ファイルと衝突しない。
        """
        dataframe = _quality_dataframe(n=20)
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(
            sys, "argv", self._run_argv(dataset_path, output_dir, "--building-height", "both")
        )

        main()

        diagnostics_files = list(output_dir.glob("*_diagnostics.json"))
        assert len(diagnostics_files) == 1
        assert "_bh_" not in diagnostics_files[0].name
        diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))
        assert diagnostics["building_height_mode"] == "both"
        assert "building_height_pc1" not in diagnostics
        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(diagnostics["features"]))

    def test_default_run_uses_the_adopted_mode_and_names_the_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """引数を指定しないランは採用構成（mean）で走り、出力名に `_bh_mean` が付く。"""
        dataframe = _quality_dataframe(n=20)
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(sys, "argv", self._run_argv(dataset_path, output_dir))

        main()

        diagnostics_files = list(output_dir.glob("*_diagnostics.json"))
        assert len(diagnostics_files) == 1
        assert "_bh_mean_" in diagnostics_files[0].name
        diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))
        assert diagnostics["building_height_mode"] == "mean"
        assert BUILDING_HEIGHT_MEAN_COLUMN in diagnostics["features"]
        assert BUILDING_HEIGHT_MAX_COLUMN not in diagnostics["features"]
        # 既定を変えてもフィルタ列は2列のままで、母数は変わらない。
        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(diagnostics["filter_columns"]))

    def test_pc1_mode_swaps_the_model_columns_but_not_the_sample(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """pc1構成では合成列を投入しつつ、フィルタ列・相関行列の対象は据え置く。

        標本統制（フィルタ列は2列とも要求）と、相関行列の比較可能性
        （対象列は拡張後の全候補列のまま・合成列を含めない）を同時に固定する。
        """
        dataframe = _quality_dataframe(n=20)
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(
            sys,
            "argv",
            self._run_argv(dataset_path, output_dir, "--building-height", "pc1"),
        )

        main()

        diagnostics_files = list(output_dir.glob("*_diagnostics.json"))
        assert len(diagnostics_files) == 1
        assert diagnostics_files[0].name.startswith("dataset_limited_dummy_hanoi_30m_both_bh_pc1_")
        diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))

        assert diagnostics["building_height_mode"] == "pc1"
        # モデルへ投入するのは合成列のみ（元の2列は入らない）。
        assert BUILDING_HEIGHT_PC1_COLUMN in diagnostics["features"]
        assert not set(BUILDING_HEIGHT_COLUMNS) & set(diagnostics["features"])
        assert BUILDING_HEIGHT_PC1_COLUMN in diagnostics["vif"]
        # フィルタは構成に依らず元の2列とも非NULLを要求する（標本統制）。
        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(diagnostics["filter_columns"]))
        assert BUILDING_HEIGHT_PC1_COLUMN not in diagnostics["filter_columns"]
        # 相関行列の対象列は構成に依らず一定（合成列は加えない）。
        correlation_columns = diagnostics["diagnostics_scope"]["correlation_columns"]
        assert BUILDING_HEIGHT_PC1_COLUMN not in correlation_columns
        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(correlation_columns))
        # 主成分の向き・寄与率は解釈に直結するため診断のみの実行でも残す。
        component = diagnostics["building_height_pc1"]
        assert component["fit_row_count"] == len(dataframe)
        assert component["loadings"][BUILDING_HEIGHT_MEAN_COLUMN] > 0
        assert 0.0 < component["explained_variance_ratio"] <= 1.0

    @pytest.mark.parametrize(
        ("building_height_mode", "expected_column"),
        [("mean", BUILDING_HEIGHT_MEAN_COLUMN), ("max", BUILDING_HEIGHT_MAX_COLUMN)],
    )
    def test_single_column_modes_keep_the_sample_control(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        building_height_mode: str,
        expected_column: str,
    ) -> None:
        """mean / max は片方だけを投入するが、母数はどの構成でも変わらない。"""
        dataframe = _quality_dataframe(n=20)
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_limited.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        dataset_path = tmp_path / "dataset_limited_dummy_hanoi_30m.gpkg"
        output_dir = tmp_path / "output"
        monkeypatch.setattr(
            sys,
            "argv",
            self._run_argv(dataset_path, output_dir, "--building-height", building_height_mode),
        )

        main()

        diagnostics_files = list(output_dir.glob("*_diagnostics.json"))
        assert len(diagnostics_files) == 1
        diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))

        assert diagnostics["features"].count(expected_column) == 1
        assert len([c for c in diagnostics["features"] if c in BUILDING_HEIGHT_COLUMNS]) == 1
        assert set(BUILDING_HEIGHT_COLUMNS).issubset(set(diagnostics["filter_columns"]))
        assert diagnostics["population_size"] == len(dataframe)
