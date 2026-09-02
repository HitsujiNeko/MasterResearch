"""src/analysis/analysis_rq3_satellite_only.py（RQ3 Satellite Onlyエントリ）のテスト。

実データでのフルパイプライン実行（RF学習・SHAP計算等の重い処理）は動作確認
手順で扱い、ここでは薄いエントリとしての結線部分のみを対象とする:
CLI引数の解釈、フィルタ条件の組み立て、出力パス解決、フィルタ脱落診断
（filter_dropout）への結線。
cell_idデコード・ブロック割り当てそのもの（assign_canonical_blocks・
compute_block_cells）の正しさは tests/analysis/urban_params/test_canonical_grid.py
で検証する。`build_filtered_sample` はフィルタ脱落診断用のブロックIDを内側で
自ら計算するようになった（Spatial CV用のブロック割り当てとは対象母集団が別物で、
`main()` 側に残る）ため、ここでは「その結果を診断へ正しく結線しているか」のみを
対象とする。
観測ラベル生成・スケール検証・ランダム分割/Spatial CV学習パイプラインは
`src.common.analysis_runs` へ集約済みのため、tests/common/test_analysis_runs.py
で検証する（Rule of Two: Limitedシナリオと重複した実装をそちらへ抽出済み）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.analysis_rq3_satellite_only import (
    DEFAULT_BLOCK_SIZE_M,
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCALE_M,
    FEATURE_COLUMNS,
    build_filtered_sample,
    parse_arguments,
    resolve_output_stem,
)


class TestParseArguments:
    """parse_arguments のテスト。"""

    def test_defaults(self) -> None:
        """引数を指定しない場合、既定値が設定される。"""
        args = parse_arguments([])

        assert args.dataset_path == DEFAULT_DATASET_PATH
        assert args.output_dir == DEFAULT_OUTPUT_DIR
        assert args.scale == DEFAULT_SCALE_M
        assert args.lst_valid_ratio_threshold == pytest.approx(0.5)
        assert args.sample_size == 100_000
        assert args.random_state == 42
        assert args.cv_splits == 5
        assert args.block_size_m == DEFAULT_BLOCK_SIZE_M
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
            ]
        )

        assert args.sample_size == 5000
        assert args.block_size_m == 900
        assert args.lst_valid_ratio_threshold == pytest.approx(0.8)


class TestResolveOutputStem:
    """resolve_output_stem のテスト。"""

    def test_uses_dataset_filename_stem(self) -> None:
        """データセットファイル名（拡張子を除く）を出力接頭辞として使う。"""
        path = Path("data/output/datasets/dataset_satellite_only_20230707_032305_hanoi_30m.gpkg")

        assert resolve_output_stem(path) == "dataset_satellite_only_20230707_032305_hanoi_30m"


def _quality_dataframe(n: int = 10) -> pd.DataFrame:
    """フィルタを全件通過する合成データセット。"""
    return pd.DataFrame(
        {
            "cell_id": range(n),
            "IN_ANALYSIS_AREA": [1] * n,
            "NDVI": [0.4] * n,
            "NDBI": [-0.1] * n,
            "NDWI": [0.2] * n,
            "LST": [35.0] * n,
            "LST_VALID_RATIO": [0.9] * n,
        }
    )


class TestBuildFilteredSample:
    """build_filtered_sample のテスト（フィルタ条件の組み立て・フィルタ脱落診断への結線）。

    戻り値は FilteredSampleResult（sampled / filter_dropout）。
    """

    def test_uses_module_feature_columns_for_filtering(self) -> None:
        """FEATURE_COLUMNS（NDVI/NDBI/NDWI）とLSTの非NULLをフィルタ条件に使う。"""
        dataframe = _quality_dataframe()
        dataframe.loc[0, "NDVI"] = np.nan  # FEATURE_COLUMNSの1つがNULL -> 除外されるはず

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result.sampled) == len(dataframe) - 1
        assert set(FEATURE_COLUMNS) == {"NDVI", "NDBI", "NDWI"}

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
        dataframe.loc[:4, "IN_ANALYSIS_AREA"] = 0  # cell_id 0-4 を対象外にする

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=3, random_state=42
        )

        assert len(result.sampled) == 3
        assert set(result.sampled["cell_id"]).issubset({5, 6, 7, 8, 9})

    def test_respects_lst_valid_ratio_threshold(self) -> None:
        """LST_VALID_RATIOのしきい値が正しく渡される。"""
        dataframe = _quality_dataframe()
        dataframe["LST_VALID_RATIO"] = 0.3

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result.sampled) == 0

    def test_filter_dropout_reflects_population_and_stage_counts(self) -> None:
        """filter_dropoutはFEATURE_COLUMNS由来の脱落を段階別母数として反映する
        （FilteredSampleResult.filter_dropoutへの結線を検証する）。
        """
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[0, "NDVI"] = np.nan  # 1件を非NULL要求で除外する

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )
        stages = result.filter_dropout["stages"]

        assert stages["dataset_row_count"] == len(dataframe)
        assert stages["target_available"] == len(dataframe)
        assert stages["feature_complete"] == len(dataframe) - 1
        assert stages["feature_complete"] == len(result.sampled)
        assert stages["sampled"] == len(result.sampled)
        assert result.filter_dropout["dropped_count"] == 1

    def test_filter_dropout_column_groups_use_the_single_spectral_indices_group(self) -> None:
        """column_groupsはspectral_indices（NDVI/NDBI/NDWI）の1グループのみを持つ

        （Limitedのbuilding_height/population/nighttime_light/otherと異なり、
        Satellite OnlyはFEATURE_COLUMNS以外の非NULL要求列を持たないため）。
        """
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[0, "NDBI"] = np.nan

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )
        column_groups = result.filter_dropout["column_groups"]

        assert set(column_groups) == {"spectral_indices"}
        assert column_groups["spectral_indices"]["null_count"] == 1

    def test_raises_when_block_size_m_is_not_multiple_of_scale(self) -> None:
        """block_size_mがscaleの倍数でない場合、build_filtered_sampleの時点で例外にする。

        フィルタ脱落診断用のブロック割り当て（assign_canonical_blocks →
        compute_block_cells）を本関数が内包したことにより、この検証は
        フィルタ・サンプリングより前倒しで発火するようになった（意図的な挙動変更。
        `src.analysis.analysis_rq3_limited` の同名テストと同じ理由）。
        """
        dataframe = _quality_dataframe()

        with pytest.raises(ValueError, match="倍数"):
            build_filtered_sample(
                dataframe,
                lst_valid_ratio_threshold=0.5,
                sample_size=0,
                random_state=42,
                block_size_m=100,  # 既定scale（30）の倍数ではない
            )
