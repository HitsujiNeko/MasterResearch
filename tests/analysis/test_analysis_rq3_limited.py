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

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.analysis_rq3_limited import (
    BUILD_COVERAGE_COLUMN,
    BUILD_DENSITY_COLUMN,
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCALE_M,
    FEATURE_COLUMNS,
    VALID_GIS_MASK_COLUMN,
    build_filtered_sample,
    fill_missing_building_heights,
    parse_arguments,
    resolve_output_stem,
)
from src.common.analysis_dataset import IN_ANALYSIS_AREA_COLUMN, LST_VALID_RATIO_COLUMN


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

    def test_main_result_uses_dataset_filename_stem(self) -> None:
        """主結果（感度分析でない）はデータセットファイル名そのものを使う。"""
        path = Path("data/output/datasets/dataset_limited_20230707_032329_hanoi_30m.gpkg")

        assert (
            resolve_output_stem(path, require_valid_gis_mask=False)
            == "dataset_limited_20230707_032329_hanoi_30m"
        )

    def test_sensitivity_analysis_appends_gismask_suffix(self) -> None:
        """感度分析（--require-valid-gis-mask）は接頭辞に_gismaskを付与し、
        主結果の出力ファイルと衝突しないようにする。
        """
        path = Path("data/output/datasets/dataset_limited_20230707_032329_hanoi_30m.gpkg")

        assert (
            resolve_output_stem(path, require_valid_gis_mask=True)
            == "dataset_limited_20230707_032329_hanoi_30m_gismask"
        )


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
    """フィルタを全件通過する合成データセット（9特徴量 + 品質列）。"""
    return pd.DataFrame(
        {
            "cell_id": range(n),
            IN_ANALYSIS_AREA_COLUMN: [1] * n,
            VALID_GIS_MASK_COLUMN: [1] * n,
            "BUILD_COV": [0.2] * n,
            "BUILD_DEN": [5.0] * n,
            "BUILD_H_MEAN": [10.0] * n,
            "BUILD_H_MAX": [15.0] * n,
            "ROAD_DEN": [50.0] * n,
            "ELEV_MEAN": [8.0] * n,
            "NDVI": [0.4] * n,
            "NDBI": [-0.1] * n,
            "NDWI": [0.2] * n,
            "LST": [35.0] * n,
            LST_VALID_RATIO_COLUMN: [0.9] * n,
        }
    )


class TestBuildFilteredSample:
    """build_filtered_sample のテスト（建物高さ補完→フィルタ→サンプリングの結線）。

    戻り値は FilteredSampleResult（sampled / dataset_filled_cell_count /
    population_size / population_filled_cell_count / sample_filled_cell_count）。
    """

    def test_uses_module_feature_columns_for_filtering(self) -> None:
        """FEATURE_COLUMNS（9変数）とLSTの非NULLをフィルタ条件に使う。"""
        dataframe = _quality_dataframe()
        dataframe.loc[0, "NDVI"] = np.nan  # FEATURE_COLUMNSの1つがNULL -> 除外されるはず

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result.sampled) == len(dataframe) - 1
        assert set(FEATURE_COLUMNS) == {
            "BUILD_COV",
            "BUILD_DEN",
            "BUILD_H_MEAN",
            "BUILD_H_MAX",
            "ROAD_DEN",
            "ELEV_MEAN",
            "NDVI",
            "NDBI",
            "NDWI",
        }

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
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=3, random_state=42
        )

        assert len(result.sampled) == 3
        assert set(result.sampled["cell_id"]).issubset({5, 6, 7, 8, 9})

    def test_respects_lst_valid_ratio_threshold(self) -> None:
        """LST_VALID_RATIOのしきい値が正しく渡される。"""
        dataframe = _quality_dataframe()
        dataframe[LST_VALID_RATIO_COLUMN] = 0.3

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
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
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
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
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
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
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
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
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=3, random_state=42
        )

        assert result.population_size == 10
        assert len(result.sampled) == 3
