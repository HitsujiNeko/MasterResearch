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
    build_valid_population,
    load_scenario_dataset,
    main,
    parse_arguments,
    resolve_output_stem,
    resolve_required_mask_columns,
)
from src.analysis.build_common_evaluation_set import draw_evaluation_cells
from src.analysis.urban_params.canonical_grid import make_cell_id
from src.common.analysis_dataset import (
    ANALYSIS_AREA_ROI,
    ANALYSIS_AREA_SURVEY,
    DEFAULT_REQUIRED_MASK_COLUMNS,
    IN_ANALYSIS_AREA_COLUMN,
    IN_ANALYSIS_AREA_SURVEY_COLUMN,
)
from src.common.analysis_runs import build_observation_label
from src.common.evaluation_cells import save_evaluation_set
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

    def test_default_dataset_and_output_dir_share_observation(self) -> None:
        """既定の入力データセットと出力先が同じ観測日時を指す。

        片方だけを別の観測へ切り替えると、引数を省略した実行で別観測の結果が
        出力先に混在するため、両者の観測日時ラベルの一致を確かめる。
        """
        dataset_label = build_observation_label(DEFAULT_DATASET_PATH.stem)
        output_label = build_observation_label(DEFAULT_OUTPUT_DIR.name)

        # パターンが見つからないと入力がそのまま返るため、整形済みであることも確かめる
        assert dataset_label != DEFAULT_DATASET_PATH.stem
        assert dataset_label == output_label

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
    "code",
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


class TestAnalysisAreaArguments:
    """--analysis-area の引数解析と出力名のテスト。"""

    def test_default_is_roi(self) -> None:
        """既定は roi（既存コマンドの挙動を変えない）。"""
        assert parse_arguments([]).analysis_area == ANALYSIS_AREA_ROI

    def test_accepts_survey(self) -> None:
        args = parse_arguments(["--analysis-area", ANALYSIS_AREA_SURVEY])

        assert args.analysis_area == ANALYSIS_AREA_SURVEY

    def test_rejects_unknown_area(self) -> None:
        with pytest.raises(SystemExit):
            parse_arguments(["--analysis-area", "full"])

    def test_roi_keeps_existing_output_stem(self) -> None:
        """roi は従来と同じ出力名になる（既存出力名との互換の回帰テスト）。"""
        path = Path("data/output/datasets/dataset_satellite_only_20230707_032305_hanoi_30m.gpkg")

        assert resolve_output_stem(path) == resolve_output_stem(path, ANALYSIS_AREA_ROI)
        assert (
            resolve_output_stem(path, ANALYSIS_AREA_ROI)
            == "dataset_satellite_only_20230707_032305_hanoi_30m"
        )

    def test_survey_appends_area_suffix(self) -> None:
        """survey は末尾に _area_survey を付け、全域ランの出力を上書きしない。"""
        path = Path("dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m.gpkg")

        assert (
            resolve_output_stem(path, ANALYSIS_AREA_SURVEY)
            == "dataset_satellite_only_masksurvey_20230707_032305_hanoi_30m_area_survey"
        )


class TestBuildFilteredSampleAnalysisArea:
    """build_filtered_sample の required_mask_columns（分析対象範囲の絞り込み）のテスト。"""

    _SURVEY_MASK_COLUMNS = (*DEFAULT_REQUIRED_MASK_COLUMNS, IN_ANALYSIS_AREA_SURVEY_COLUMN)

    def test_default_ignores_survey_flag(self) -> None:
        """既定（IN_ANALYSIS_AREA のみ）では測量GISフラグを見ない（従来どおり）。"""
        dataframe = _quality_dataframe(n=10)
        dataframe[IN_ANALYSIS_AREA_SURVEY_COLUMN] = [1] * 4 + [0] * 6

        result = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        )

        assert len(result.sampled) == 10

    def test_survey_mask_narrows_sample_and_dropout_baseline(self) -> None:
        """測量GISフラグを加えると、分析母数と脱落診断の基準が同じ範囲に絞られる。"""
        dataframe = _quality_dataframe(n=10)
        dataframe[IN_ANALYSIS_AREA_SURVEY_COLUMN] = [1] * 4 + [0] * 6
        dataframe.loc[0, "NDVI"] = np.nan  # 測量GIS範囲内の1件を非NULL要求で落とす

        result = build_filtered_sample(
            dataframe,
            lst_valid_ratio_threshold=0.5,
            sample_size=0,
            random_state=42,
            required_mask_columns=self._SURVEY_MASK_COLUMNS,
        )
        stages = result.filter_dropout["stages"]

        assert set(result.sampled["cell_id"]) == {1, 2, 3}
        # 脱落診断も同じ品質列で絞っている（基準段階が測量GIS範囲の4件になる）
        assert stages["mask_passed"] == 4
        assert stages["target_available"] == 4
        assert stages["feature_complete"] == len(result.sampled)


class TestMainAnalysisArea:
    """main() の分析対象範囲の結線（読込列・列不足時の停止・結果JSONへの記録）のテスト。

    読込関数は、実物と同じく「指定された列のうち存在する列だけを返す」偽物へ
    差し替える。`gpd.read_file(columns=...)` は存在しない列を黙って読み飛ばす
    ため、読込列への追加漏れや列不足を、実物と同じ条件で検出できる。
    """

    def _install_loader(
        self, monkeypatch: pytest.MonkeyPatch, dataframe: pd.DataFrame
    ) -> dict[str, list[str]]:
        """列選択を模した読込関数へ差し替え、要求された列を控える。"""
        captured: dict[str, list[str]] = {}

        def fake_loader(dataset_path: Path, columns: list[str] | None = None) -> pd.DataFrame:
            captured["columns"] = list(columns or [])
            available = [column for column in captured["columns"] if column in dataframe.columns]
            return dataframe[available].copy()

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.load_analysis_dataset", fake_loader
        )
        return captured

    def _set_argv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra_args: str) -> Path:
        """main() のCLI引数を設定し、出力先ディレクトリを返す。"""
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
        return output_dir

    def test_survey_without_mask_survey_column_stops_before_modeling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """mask_survey を結合していないデータセットでは、モデル学習前に ValueError で止まる。"""
        self._install_loader(monkeypatch, _spread_dataframe())

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("列不足のままモデル学習へ進んではならない")

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.run_random_split_models", _fail_if_called
        )
        self._set_argv(monkeypatch, tmp_path, "--analysis-area", ANALYSIS_AREA_SURVEY)

        with pytest.raises(ValueError, match="mask_survey"):
            main()

    def test_survey_reads_flag_and_records_area(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """survey は測量GISフラグを読込列に含め、絞った母数で実行し、結果JSONに範囲を残す。"""
        dataframe = _spread_dataframe(n=200)
        dataframe[IN_ANALYSIS_AREA_SURVEY_COLUMN] = [1] * 150 + [0] * 50
        captured = self._install_loader(monkeypatch, dataframe)
        output_dir = self._set_argv(monkeypatch, tmp_path, "--analysis-area", ANALYSIS_AREA_SURVEY)

        main()

        assert IN_ANALYSIS_AREA_SURVEY_COLUMN in captured["columns"]
        result_files = list(output_dir.glob("*_results.json"))
        assert [path.name for path in result_files] == [
            "dataset_satellite_only_dummy_hanoi_30m_area_survey_results.json"
        ]
        result = json.loads(result_files[0].read_text(encoding="utf-8"))
        assert result["analysis_area"] == ANALYSIS_AREA_SURVEY
        assert result["required_mask_columns"] == [
            IN_ANALYSIS_AREA_COLUMN,
            IN_ANALYSIS_AREA_SURVEY_COLUMN,
        ]
        assert result["sample_size"] == 150
        assert result["filter_dropout"]["stages"]["mask_passed"] == 150

    def test_roi_keeps_existing_behavior(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """roi（既定）は測量GISフラグを読まず、従来の出力名・母数のまま範囲を記録する。"""
        captured = self._install_loader(monkeypatch, _spread_dataframe(n=200))
        output_dir = self._set_argv(monkeypatch, tmp_path)

        main()

        assert IN_ANALYSIS_AREA_SURVEY_COLUMN not in captured["columns"]
        result_files = list(output_dir.glob("*_results.json"))
        assert [path.name for path in result_files] == [
            "dataset_satellite_only_dummy_hanoi_30m_results.json"
        ]
        result = json.loads(result_files[0].read_text(encoding="utf-8"))
        assert result["analysis_area"] == ANALYSIS_AREA_ROI
        assert result["required_mask_columns"] == [IN_ANALYSIS_AREA_COLUMN]
        assert result["sample_size"] == 200


class TestResolveRequiredMaskColumns:
    """resolve_required_mask_columns のテスト（有効母集団の品質列の組み立て）。"""

    def test_roi_requires_only_default_mask_columns(self) -> None:
        """ROI 全域では既定の品質列（IN_ANALYSIS_AREA）だけを要求する。"""
        assert resolve_required_mask_columns(ANALYSIS_AREA_ROI) == DEFAULT_REQUIRED_MASK_COLUMNS

    def test_survey_appends_survey_flag_after_default(self) -> None:
        """測量GIS範囲では、既定の品質列の後ろに測量GISフラグを加える。"""
        assert resolve_required_mask_columns(ANALYSIS_AREA_SURVEY) == (
            *DEFAULT_REQUIRED_MASK_COLUMNS,
            IN_ANALYSIS_AREA_SURVEY_COLUMN,
        )


class TestBuildValidPopulation:
    """build_valid_population のテスト（サンプリング前の有効母集団）。

    `build_filtered_sample` と、共通評価セル集合の生成の両方がこの関数を呼ぶため、
    両者の母集団が一致することを固定する。
    """

    def test_excludes_rows_failing_any_condition(self) -> None:
        """分光指数のNULL・LSTのNULL・品質列0・LST有効率の下限割れをそれぞれ除外する。"""
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[0, "NDWI"] = np.nan
        dataframe.loc[1, "LST"] = np.nan
        dataframe.loc[2, IN_ANALYSIS_AREA_COLUMN] = 0
        dataframe.loc[3, "LST_VALID_RATIO"] = 0.4

        population = build_valid_population(dataframe, lst_valid_ratio_threshold=0.5)

        assert list(population["cell_id"]) == [4, 5, 6, 7, 8, 9]

    def test_matches_rows_used_by_build_filtered_sample(self) -> None:
        """全件抽出（sample_size=0）の build_filtered_sample と同じ行を同じ順で返す。"""
        dataframe = _quality_dataframe(n=10)
        dataframe.loc[[1, 4], "NDVI"] = np.nan

        population = build_valid_population(dataframe, lst_valid_ratio_threshold=0.5)
        sampled = build_filtered_sample(
            dataframe, lst_valid_ratio_threshold=0.5, sample_size=0, random_state=42
        ).sampled

        assert list(population["cell_id"]) == list(sampled["cell_id"])

    def test_required_mask_columns_narrow_population(self) -> None:
        """渡した品質列（測量GISフラグ）で母集団が絞られる。"""
        dataframe = _quality_dataframe(n=10)
        dataframe[IN_ANALYSIS_AREA_SURVEY_COLUMN] = [1] * 4 + [0] * 6

        population = build_valid_population(
            dataframe,
            lst_valid_ratio_threshold=0.5,
            required_mask_columns=resolve_required_mask_columns(ANALYSIS_AREA_SURVEY),
        )

        assert list(population["cell_id"]) == [0, 1, 2, 3]


class TestLoadScenarioDataset:
    """load_scenario_dataset のテスト（読込列と分析対象範囲の品質列の検査）。

    読込関数は「指定された列のうち存在する列だけを返す」偽物へ差し替える
    （`TestMainAnalysisArea` と同じ方針）。
    """

    def _install_loader(
        self, monkeypatch: pytest.MonkeyPatch, dataframe: pd.DataFrame
    ) -> dict[str, list[str]]:
        """列選択を模した読込関数へ差し替え、要求された列を控える。"""
        captured: dict[str, list[str]] = {}

        def fake_loader(dataset_path: Path, columns: list[str] | None = None) -> pd.DataFrame:
            captured["columns"] = list(columns or [])
            available = [column for column in captured["columns"] if column in dataframe.columns]
            return dataframe[available].copy()

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.load_analysis_dataset", fake_loader
        )
        return captured

    def test_reads_columns_needed_for_valid_population(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """有効母集団の判定と分析に使う列を要求し、測量GISフラグはROIでは読まない。"""
        dataframe = _quality_dataframe(n=5)
        dataframe["lon"] = 0.0
        dataframe["lat"] = 0.0
        captured = self._install_loader(monkeypatch, dataframe)

        loaded = load_scenario_dataset(Path("dummy.gpkg"), ANALYSIS_AREA_ROI)

        assert {"cell_id", *FEATURE_COLUMNS, "LST", "LST_VALID_RATIO"}.issubset(loaded.columns)
        assert IN_ANALYSIS_AREA_COLUMN in captured["columns"]
        assert IN_ANALYSIS_AREA_SURVEY_COLUMN not in captured["columns"]

    def test_survey_without_flag_column_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """測量GIS範囲を指定し、データセットにフラグ列が無ければ停止する。"""
        self._install_loader(monkeypatch, _quality_dataframe(n=5))

        with pytest.raises(ValueError, match="mask_survey"):
            load_scenario_dataset(Path("dummy.gpkg"), ANALYSIS_AREA_SURVEY)


def _save_common_evaluation_set(
    tmp_path: Path, cell_ids: np.ndarray, sample_size: int = 0, block_size_m: int = 2_700
) -> Path:
    """合成データの cell_id から評価セル CSV とメタデータを作り、CSV のパスを返す。

    メタデータの設定は、`--sample-size` 以外は分析スクリプトの既定値に揃える。
    """
    cells, _ = draw_evaluation_cells(
        cell_ids,
        sample_size=sample_size,
        random_state=42,
        block_size_m=block_size_m,
        scale=30,
        cv_splits=5,
    )
    cells_path = tmp_path / "common" / "evaluation_cells_seed42.csv"
    save_evaluation_set(
        cells,
        cells_path,
        {
            "block_size_m": block_size_m,
            "cv_splits": 5,
            "scale_m": 30,
            "random_state": 42,
            "sample_size": sample_size,
            "lst_valid_ratio_threshold": 0.5,
            "analysis_area": ANALYSIS_AREA_ROI,
            "common_size": len(cell_ids),
        },
    )
    return cells_path


class TestEvaluationCellsArguments:
    """--evaluation-cells の引数解釈（出力先の既定）のテスト。"""

    def test_default_output_dir_is_separated(self) -> None:
        """評価セル指定時の既定の出力先は、通常ランと別のディレクトリになる。"""
        args = parse_arguments(["--evaluation-cells", "cells.csv"])

        assert args.output_dir == DEFAULT_OUTPUT_DIR.with_name(
            f"{DEFAULT_OUTPUT_DIR.name}_common_evaluation"
        )

    def test_explicit_output_dir_is_kept(self, tmp_path: Path) -> None:
        """--output-dir を明示した場合はそのまま使う。"""
        args = parse_arguments(["--evaluation-cells", "cells.csv", "--output-dir", str(tmp_path)])

        assert args.output_dir == tmp_path

    def test_default_run_keeps_default_output_dir(self) -> None:
        """評価セルを指定しない場合の出力先は従来どおり。"""
        args = parse_arguments([])

        assert args.output_dir == DEFAULT_OUTPUT_DIR
        assert args.evaluation_cells is None


class TestMainEvaluationCells:
    """main() の --evaluation-cells の結線（標本・fold の固定、記録、停止条件）のテスト。"""

    _install_loader = TestMainAnalysisArea._install_loader
    _set_argv = TestMainAnalysisArea._set_argv

    def test_uses_cells_in_csv_order_and_fixed_folds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """標本は CSV の行順、Spatial CV は CSV の fold で行い、評価セルと来歴を記録する。"""
        dataframe = _spread_dataframe(n=200)
        cells_path = _save_common_evaluation_set(tmp_path, dataframe["cell_id"].to_numpy())
        self._install_loader(monkeypatch, dataframe)
        output_dir = self._set_argv(monkeypatch, tmp_path, "--evaluation-cells", str(cells_path))

        main()

        cells = pd.read_csv(cells_path)
        stem = "dataset_satellite_only_dummy_hanoi_30m_evaluation_cells_seed42"
        sample = pd.read_csv(output_dir / f"{stem}_sample_0.csv")
        assert list(sample["cell_id"]) == list(cells["cell_id"])
        folds = pd.read_csv(output_dir / f"{stem}_spatial_cv_folds.csv")
        assert list(folds["test_size"]) == list(cells["fold"].value_counts().sort_index())
        result = json.loads((output_dir / f"{stem}_results.json").read_text(encoding="utf-8"))
        record = result["evaluation_cells"]
        assert record["population_size"] == 200
        assert record["common_size"] == 200
        assert record["path"].endswith("evaluation_cells_seed42.csv")
        input_paths = [entry["path"] for entry in result["provenance"]["inputs"]]
        assert any(path.endswith("evaluation_cells_seed42.csv") for path in input_paths)
        assert any(path.endswith("evaluation_cells_seed42_results.json") for path in input_paths)

    def test_default_run_records_null_evaluation_cells(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """評価セルを指定しないランでは evaluation_cells を null とし、来歴の入力は GPKG のみ。"""
        self._install_loader(monkeypatch, _spread_dataframe(n=200))
        output_dir = self._set_argv(monkeypatch, tmp_path)

        main()

        result = json.loads(next(output_dir.glob("*_results.json")).read_text(encoding="utf-8"))
        assert result["evaluation_cells"] is None
        assert len(result["provenance"]["inputs"]) == 1

    def test_mismatched_block_size_stops_before_loading(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--block-size-m がメタデータと違えば、データセットを読む前に停止する。"""
        dataframe = _spread_dataframe(n=200)
        cells_path = _save_common_evaluation_set(tmp_path, dataframe["cell_id"].to_numpy())

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("設定が食い違ったままデータセットを読んではならない")

        monkeypatch.setattr(
            "src.analysis.analysis_rq3_satellite_only.load_analysis_dataset", _fail_if_called
        )
        self._set_argv(
            monkeypatch, tmp_path, "--evaluation-cells", str(cells_path), "--block-size-m", "900"
        )

        with pytest.raises(ValueError, match="block_size_m"):
            main()

    def test_cell_outside_population_stops(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """評価セルが自シナリオの有効母集団に無ければ、モデル学習前に停止する。"""
        dataframe = _spread_dataframe(n=200)
        cells_path = _save_common_evaluation_set(tmp_path, dataframe["cell_id"].to_numpy())
        dataframe.loc[0, "NDVI"] = np.nan
        self._install_loader(monkeypatch, dataframe)
        self._set_argv(monkeypatch, tmp_path, "--evaluation-cells", str(cells_path))

        with pytest.raises(ValueError, match="有効母集団にありません"):
            main()
