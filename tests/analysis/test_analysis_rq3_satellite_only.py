"""src/analysis/analysis_rq3_satellite_only.py（RQ3 Satellite Onlyエントリ）のテスト。

実データでのフルパイプライン実行（RF学習・SHAP計算等の重い処理）は動作確認
手順で扱い、ここでは薄いエントリとしての結線部分のみを対象とする:
CLI引数の解釈、フィルタ条件の組み立て、出力パス解決。cell_idデコードから
ブロック割り当てまでの結線（assign_canonical_blocks）は
tests/analysis/urban_params/test_canonical_grid.py で検証する。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.analysis_rq3_satellite_only import (
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCALE_M,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_filtered_sample,
    build_observation_label,
    parse_arguments,
    resolve_output_stem,
    run_random_split_models,
    run_spatial_cv_models,
    validate_scale_matches_dataset,
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
            ]
        )

        assert args.sample_size == 5000
        assert args.block_size_m == 900
        assert args.lst_valid_ratio_threshold == pytest.approx(0.8)


class TestResolveOutputStem:
    """resolve_output_stem のテスト。"""

    def test_uses_dataset_filename_stem(self) -> None:
        """データセットファイル名（拡張子を除く）を出力接頭辞として使う。"""
        path = Path("data/output/datasets/dataset_satellite_only_20230707_032329_hanoi_30m.gpkg")

        assert resolve_output_stem(path) == "dataset_satellite_only_20230707_032329_hanoi_30m"


class TestValidateScaleMatchesDataset:
    """validate_scale_matches_dataset のテスト。"""

    def test_accepts_matching_scale(self) -> None:
        """ファイル名末尾が--scaleと一致する場合は例外にならない。"""
        path = Path("data/output/datasets/dataset_satellite_only_20230707_032329_hanoi_30m.gpkg")

        validate_scale_matches_dataset(path, scale=30)

    def test_raises_when_scale_does_not_match_filename(self) -> None:
        """ファイル名末尾が--scaleと一致しない場合はValueErrorになる。

        90mデータセットに--scale=30を指定するような設定ミスを、誤ったブロック
        サイズでSpatial CVが静かに実行される前に検出する。
        """
        path = Path("data/output/datasets/dataset_satellite_only_20230707_032329_hanoi_90m.gpkg")

        with pytest.raises(ValueError, match="--scale"):
            validate_scale_matches_dataset(path, scale=30)


class TestBuildObservationLabel:
    """build_observation_label のテスト。"""

    def test_formats_date_and_time_from_output_stem(self) -> None:
        """8桁の日付・6桁の時刻を可読な形式へ整形する。"""
        label = build_observation_label("dataset_satellite_only_20230707_032329_hanoi_30m")

        assert label == "2023-07-07 03:23:29"

    def test_returns_output_stem_when_pattern_not_found(self) -> None:
        """日付・時刻パターンが見つからない場合はoutput_stemをそのまま返す。"""
        label = build_observation_label("dataset_without_date")

        assert label == "dataset_without_date"


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
    """build_filtered_sample のテスト（フィルタ条件の組み立て）。"""

    def test_uses_module_feature_columns_for_filtering(self) -> None:
        """FEATURE_COLUMNS（NDVI/NDBI/NDWI）とLSTの非NULLをフィルタ条件に使う。"""
        dataframe = _quality_dataframe()
        dataframe.loc[0, "NDVI"] = np.nan  # FEATURE_COLUMNSの1つがNULL -> 除外されるはず

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result) == len(dataframe) - 1
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

        assert len(result) == 3
        assert set(result["cell_id"]).issubset({5, 6, 7, 8, 9})

    def test_respects_lst_valid_ratio_threshold(self) -> None:
        """LST_VALID_RATIOのしきい値が正しく渡される。"""
        dataframe = _quality_dataframe()
        dataframe["LST_VALID_RATIO"] = 0.3

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result) == 0


def _linear_sample_dataframe(n: int = 60, seed: int = 0) -> pd.DataFrame:
    """run_random_split_models / run_spatial_cv_models 用の合成データ。

    FEATURE_COLUMNS・TARGET_COLUMNの実列名を使い、値には多少のばらつきを
    持たせる（定数列だとVIF計算やRFの分岐が退化するため）。
    """
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "NDVI": rng.normal(size=n),
            "NDBI": rng.normal(size=n),
            "NDWI": rng.normal(size=n),
            TARGET_COLUMN: rng.normal(size=n),
        }
    )


class TestRunRandomSplitModels:
    """run_random_split_models のスモークテスト。"""

    def test_returns_result_with_expected_shapes_and_keys(self) -> None:
        """train/testの分割比率、metrics・重要度辞書のキー構成を検証する。"""
        sampled = _linear_sample_dataframe(n=100)

        result = run_random_split_models(sampled, random_state=42, rf_trees=5)

        # test_size=0.2固定のため、100件なら test=20, train=80 になる。
        assert len(result.x_train) == 80
        assert len(result.x_test) == 20
        assert set(result.linear_result["metrics"].keys()) == {"r2", "rmse", "mae"}
        assert set(result.rf_result["metrics"].keys()) == {"r2", "rmse", "mae"}
        # 標準化係数・重要度はlinear_result/rf_resultの中に含まれ、専用フィールド
        # としては持たない（二重管理を避けるため）。
        assert set(result.linear_result["standardized_coefficients"].keys()) == set(FEATURE_COLUMNS)
        assert set(result.rf_result["feature_importance"].keys()) == set(FEATURE_COLUMNS)
        assert set(result.rf_result["permutation_importance"].keys()) == set(FEATURE_COLUMNS)


class TestRunSpatialCvModels:
    """run_spatial_cv_models のスモークテスト（fold集計と出力契約）。"""

    def test_returns_fold_metrics_columns_expected_by_plot(self) -> None:
        """プロット関数（save_spatial_cv_plot / save_model_comparison_plot）が
        要求する列名・キー名を返す。列名の変更をここで検出する。
        """
        sampled = _linear_sample_dataframe(n=60)
        block_ids = np.repeat(np.arange(6), 10)

        summary, fold_metrics_df = run_spatial_cv_models(
            sampled, block_ids, cv_splits=3, random_state=42, rf_trees=5
        )

        assert len(fold_metrics_df) == 3
        for column in (
            "fold",
            "train_size",
            "test_size",
            "linear_r2",
            "linear_rmse",
            "linear_mae",
            "rf_r2",
            "rf_rmse",
            "rf_mae",
        ):
            assert column in fold_metrics_df.columns
        assert "r2_mean" in summary["linear_regression"]
        assert "r2_mean" in summary["random_forest"]
        assert summary["cv_splits"] == 3
