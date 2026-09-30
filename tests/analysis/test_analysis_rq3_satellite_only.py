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
例外として、results.json への実行パラメータ（run_parameters）と来歴メタデータ
（provenance）の記録は、合成データ・小規模設定（決定木5本等）で main() を通して
検証する。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
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
    main,
    parse_arguments,
    resolve_output_stem,
)
from src.analysis.urban_params.canonical_grid import make_cell_id
from src.common.run_parameters import build_run_parameters_from_args


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


# 来歴を検証するためのダミーの入力ファイルの中身（ハッシュの期待値を計算できるよう固定する）
DUMMY_DATASET_BYTES = b"dummy geopackage for provenance test"

# build_provenance が返す来歴のトップレベルキー
PROVENANCE_KEYS = {
    "script",
    "executed_at",
    "python_version",
    "platform",
    "git",
    "packages",
    "inputs",
}


def _spread_dataframe(n: int = 200) -> pd.DataFrame:
    """Spatial CVのfoldを組めるよう、複数ブロックへ散らばる合成データセット。

    `cell_id` を30セル（900m）間隔の列に置き、既定のブロックサイズ（2700m＝90セル）
    で約 n/3 個のブロックへ分かれるようにする。値は固定シードの乱数で列ごとに
    独立な変動を与える（全行同値だとRF・VIF・SHAPが意味のある値を返さないため）。
    """
    rng = np.random.default_rng(seed=20230707)
    ndvi = 0.4 + rng.normal(scale=0.05, size=n)
    ndbi = -0.1 + rng.normal(scale=0.05, size=n)
    ndwi = 0.2 + rng.normal(scale=0.05, size=n)
    return pd.DataFrame(
        {
            "cell_id": make_cell_id(np.zeros(n, dtype=np.int64), np.arange(n) * 30),
            "IN_ANALYSIS_AREA": [1] * n,
            "NDVI": ndvi,
            "NDBI": ndbi,
            "NDWI": ndwi,
            "LST": 35.0 - 5.0 * ndvi + 3.0 * ndbi + rng.normal(scale=0.2, size=n),
            "LST_VALID_RATIO": [0.9] * n,
        }
    )


def _capture_model_run_arguments(
    monkeypatch: pytest.MonkeyPatch, module_name: str
) -> dict[str, dict[str, object]]:
    """モデル実行関数を元の処理を呼ぶラッパーへ差し替え、実際に渡された引数を控える。

    記録値（run_parameters）と、学習に実際に使われた値との一致を検証するために使う。

    Args:
        monkeypatch: pytest の monkeypatch。
        module_name: 差し替え対象の関数を import している分析スクリプトのモジュール名。

    Returns:
        関数名をキー、束縛済みの引数辞書を値とする辞書（main() 実行後に埋まる）。
    """
    module = importlib.import_module(module_name)
    captured: dict[str, dict[str, object]] = {}

    for function_name in ("run_random_split_models", "run_spatial_cv_models"):
        original = getattr(module, function_name)
        signature = inspect.signature(original)

        def wrapper(*args, _original=original, _signature=signature, _name=function_name, **kwargs):
            captured[_name] = dict(_signature.bind(*args, **kwargs).arguments)
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, function_name, wrapper)
    return captured


class TestMainRunParameters:
    """main() が results.json へ実行パラメータ（run_parameters）を記録することの検証。

    データ読込（load_analysis_dataset）だけを合成データへ差し替え、決定木本数・
    SHAP件数を小さくしてフルパイプラインを実行する（実データは使わない）。
    """

    def _run_main(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra_args: str
    ) -> dict[str, object]:
        """合成データで main() を実行し、保存された results.json を読み込んで返す。"""
        dataframe = _spread_dataframe()
        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.load_analysis_dataset",
            lambda *args, **kwargs: dataframe,
        )
        # データ読込は差し替えるが、来歴（provenance）は入力ファイルの実体をハッシュ
        # するため、中身を固定したダミーファイルを置く。
        dataset_path = tmp_path / "dataset_satellite_only_dummy_hanoi_30m.gpkg"
        dataset_path.write_bytes(DUMMY_DATASET_BYTES)
        output_dir = tmp_path / "output"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "analysis_rq3_satellite_only.py",
                "--dataset-path",
                str(dataset_path),
                "--output-dir",
                str(output_dir),
                "--sample-size",
                "0",
                "--rf-trees",
                "5",
                "--shap-sample-size",
                "10",
                "--shap-background-size",
                "10",
                *extra_args,
            ],
        )

        main()

        result_files = list(output_dir.glob("*_results.json"))
        assert len(result_files) == 1
        return json.loads(result_files[0].read_text(encoding="utf-8"))

    def test_records_run_parameters_from_cli(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--random-state・--rf-trees 等の指定値が run_parameters にそのまま記録される。"""
        captured = _capture_model_run_arguments(
            monkeypatch, "src.analysis.analysis_rq3_satellite_only"
        )
        result = self._run_main(monkeypatch, tmp_path, "--random-state", "7")

        run_parameters = result["run_parameters"]
        assert run_parameters["random_state"] == 7
        assert run_parameters["rf_trees"] == 5
        assert run_parameters["requested_sample_size"] == 0
        assert run_parameters["scale_m"] == DEFAULT_SCALE_M
        assert run_parameters["requested_shap_sample_size"] == 10
        assert run_parameters["requested_shap_background_size"] == 10

        # 記録値が、学習に実際に渡された値と一致する（記録側と使用側の乖離を検出する）
        for function_name in ("run_random_split_models", "run_spatial_cv_models"):
            used = captured[function_name]
            assert used["random_state"] == run_parameters["random_state"]
            assert used["rf_trees"] == run_parameters["rf_trees"]

    def test_keeps_existing_top_level_keys(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既存のトップレベルキーは移動・改名せずに残す（既存の参照を壊さない）。"""
        result = self._run_main(monkeypatch, tmp_path)

        assert result["sample_size"] == len(_spread_dataframe())
        assert result["lst_valid_ratio_threshold"] == pytest.approx(0.5)
        assert result["spatial_cv"]["cv_splits"] == 5
        assert result["spatial_cv"]["block_definition"]["block_size_m"] == DEFAULT_BLOCK_SIZE_M

    def test_records_provenance_with_dataset_hash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """来歴（provenance）が付与され、入力はデータセット1件でハッシュが実体と一致する。"""
        result = self._run_main(monkeypatch, tmp_path)

        provenance = result["provenance"]
        assert set(provenance) == PROVENANCE_KEYS
        assert provenance["script"] == "src.analysis.analysis_rq3_satellite_only"
        assert len(provenance["inputs"]) == 1
        assert provenance["inputs"][0]["path"].endswith(
            "dataset_satellite_only_dummy_hanoi_30m.gpkg"
        )
        assert provenance["inputs"][0]["sha256"] == hashlib.sha256(DUMMY_DATASET_BYTES).hexdigest()


class TestRunParametersFromDefaults:
    """既定のCLI引数から作る run_parameters の検証（main() を実行しない軽量版）。"""

    def test_default_seed_and_trees_are_recorded(self) -> None:
        """既定値（シード42・決定木300本）が記録値に反映される。"""
        run_parameters = build_run_parameters_from_args(parse_arguments([]))

        assert run_parameters["random_state"] == 42
        assert run_parameters["rf_trees"] == 300
        assert run_parameters["requested_sample_size"] == 100_000
        assert run_parameters["scale_m"] == DEFAULT_SCALE_M
