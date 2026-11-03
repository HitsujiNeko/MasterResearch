"""src/analysis/diagnose_spatial_cv_design.py（Spatial CV のブロック設計の診断）のテスト。

合成データで評価セルを作り（`build_common_evaluation_set.main`）、少ない決定木・
小さな部分標本で掃引とセミバリオグラムを通して、保存物・再開・既存の評価との
一致を確かめる。データセットの読込は列選択を模した偽物へ差し替える。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis import diagnose_spatial_cv_design as diagnose
from src.analysis import repeat_common_evaluation as repeat
from src.analysis.diagnose_spatial_cv_design import (
    MAX_FOLD_SIZE_RATIO,
    RUN_CONDITIONS_KEY,
    cell_coordinates,
    config_key,
    config_paths,
    draw_subsample_indices,
    evaluate_fold_models,
    load_completed_config,
    main,
    resolve_observation_dir_name,
    summarize_block_design,
)
from src.analysis.urban_params.canonical_grid import make_cell_id
from src.common.analysis_runs import run_spatial_cv_models
from src.common.evaluation_cells import (
    BLOCK_ID_COLUMN,
    FOLD_COLUMN,
    folds_from_labels,
    load_evaluation_set,
    select_evaluation_rows,
)
from tests.analysis.test_repeat_common_evaluation import _build_cells

SWEEP_OPTIONS = [
    "--block-sizes-m",
    "2700",
    "5400",
    "--buffers-m",
    "0",
    "1000",
    "--n-seeds",
    "1",
    "--rf-trees",
    "5",
    "--residual-sample-size",
    "60",
    "--residual-max-lag-m",
    "2700",
    "--cumulative-max-lag-m",
    "1800",
    "--permutations",
    "9",
]


class TestHelpers:
    """補助関数のテスト。"""

    @pytest.mark.parametrize(
        "text",
        ["2022-09-06 03:23:58", "dataset_limited_20220906_032358_hanoi_30m", "20220906_032358"],
    )
    def test_observation_dir_name(self, text: str) -> None:
        """観測日時の表記・ファイル名のどちらからも同じディレクトリ名を作る。"""
        assert resolve_observation_dir_name(text) == "20220906_032358"

    def test_observation_dir_name_raises_without_datetime(self) -> None:
        """観測日時を読み取れない場合は例外にする（出力先を取り違えないため）。"""
        with pytest.raises(ValueError, match="観測日時"):
            resolve_observation_dir_name("dataset_limited_hanoi_30m")

    def test_config_key(self) -> None:
        """設定のファイル名用の文字列は緩衝帯の小数を省いて表す。"""
        assert config_key(42, 2700, 900.0) == "seed42_block2700_buffer900"

    def test_config_files_are_not_scanned_as_results(self, tmp_path: Path) -> None:
        """途中結果は陳腐化チェックの走査対象（`_results.json`）にならない名前にする。"""
        paths = config_paths(tmp_path, "seed42_block2700_buffer0")
        assert not any(path.name.endswith("_results.json") for path in paths.values())

    def test_cell_coordinates_keep_cell_spacing(self) -> None:
        """隣り合うセルの座標の距離が解像度（m）になる。"""
        cell_ids = make_cell_id(np.array([5, 5, 6]), np.array([10, 11, 10]))
        coords = cell_coordinates(cell_ids, 30)
        assert np.hypot(*(coords[1] - coords[0])) == 30
        assert np.hypot(*(coords[2] - coords[0])) == 30

    def test_subsample_is_sorted_unique_and_reproducible(self) -> None:
        """部分標本は重複なし・昇順で、同じシードなら同じになる。"""
        first = draw_subsample_indices(100, 10, seed=3)
        assert len(np.unique(first)) == 10
        assert np.all(np.diff(first) > 0)
        np.testing.assert_array_equal(first, draw_subsample_indices(100, 10, seed=3))

    def test_subsample_takes_all_when_size_exceeds(self) -> None:
        """部分標本の件数が母集団以上なら全件を使う。"""
        np.testing.assert_array_equal(draw_subsample_indices(5, 10, seed=0), np.arange(5))

    def test_block_design_criteria(self) -> None:
        """非空ブロック数と fold の評価セル数の最大/最小比を判定基準と照らす。"""
        cells = pd.DataFrame({BLOCK_ID_COLUMN: [1, 1, 2, 3, 3, 3], FOLD_COLUMN: [1, 1, 2, 1, 1, 2]})
        design = summarize_block_design(cells)
        assert design["n_blocks"] == 3
        assert design["fold_size_ratio"] == 2.0
        assert not design["meets_min_blocks"]
        assert design["meets_fold_size_ratio"] is (2.0 <= MAX_FOLD_SIZE_RATIO)


class TestEvaluateFoldModels:
    """evaluate_fold_models のテスト。"""

    def test_matches_existing_spatial_cv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """緩衝帯なしの fold では、既存の run_spatial_cv_models と同じ fold 別指標になる。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        evaluation_set = load_evaluation_set(cells_path)
        _, populations = repeat.build_populations(evaluation_set)
        cells = evaluation_set.cells
        folds = folds_from_labels(cells[FOLD_COLUMN].to_numpy(), 5)
        sample = select_evaluation_rows(populations["satellite_only"], cells)
        features = ["NDVI", "NDBI", "NDWI"]

        fold_table, oof = evaluate_fold_models(sample, features, "LST", folds, 42, 5)
        _, expected = run_spatial_cv_models(
            sample, features, "LST", cells[BLOCK_ID_COLUMN].to_numpy(), 5, 42, 5, folds=folds
        )

        pd.testing.assert_frame_equal(fold_table[expected.columns], expected)
        # out-of-fold 予測は全行を1回ずつ覆い、観測値は標本の LST と一致する
        np.testing.assert_array_equal(oof["position"], np.arange(len(sample)))
        np.testing.assert_allclose(oof["observed"], sample["LST"])


class TestResume:
    """load_completed_config のテスト。"""

    def test_returns_none_when_files_are_missing(self, tmp_path: Path) -> None:
        """途中結果が揃っていなければ再利用しない。"""
        paths = config_paths(tmp_path, "seed42_block2700_buffer0")
        assert load_completed_config(paths, "digest", {"code_digest": "x"}) is None

    @pytest.mark.parametrize(
        ("digest", "conditions"),
        [("other", {"code_digest": "x"}), ("digest", {"code_digest": "y"})],
    )
    def test_does_not_reuse_on_mismatch(
        self, tmp_path: Path, digest: str, conditions: dict[str, str]
    ) -> None:
        """標本のダイジェストか実行条件が違えば再利用しない。"""
        paths = config_paths(tmp_path, "seed42_block2700_buffer0")
        for name in ("folds", "correlograms", "residual_semivariograms"):
            pd.DataFrame({"a": [1]}).to_csv(paths[name], index=False)
        paths["summary"].write_text(
            json.dumps({"digest": "digest", RUN_CONDITIONS_KEY: {"code_digest": "x"}}),
            encoding="utf-8",
        )
        assert load_completed_config(paths, "digest", {"code_digest": "x"}) is not None
        assert load_completed_config(paths, digest, conditions) is None


class TestSweep:
    """sweep サブコマンドのテスト（合成データで2ブロック × 2緩衝帯を通す）。"""

    def test_runs_saves_results_and_resumes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """掃引の結果を保存し、再実行では途中結果を再利用する。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        output_dir = tmp_path / "design"
        argv = [
            "sweep",
            "--evaluation-cells",
            str(cells_path),
            "--output-dir",
            str(output_dir),
            *SWEEP_OPTIONS,
        ]

        main(argv)

        result = json.loads(
            (output_dir / "spatial_cv_sweep_results.json").read_text(encoding="utf-8")
        )
        assert result["block_sizes_m"] == [2700, 5400]
        assert result["buffers_m"] == [0.0, 1000.0]
        assert len(result["configs"]) == 4
        assert len(result["provenance"]["inputs"]) == 4
        assert "esda" in result["provenance"]["packages"]
        summary = pd.read_csv(output_dir / "spatial_cv_sweep_summary.csv")
        assert set(summary["scenario"]) == {"satellite_only", "limited"}
        assert len(summary) == 8
        # 900m 間隔のセルに緩衝帯 1000m をかけると、評価セルの隣の学習セルが除かれる
        folds = pd.read_csv(output_dir / "spatial_cv_sweep_folds.csv")
        assert (folds.loc[folds["buffer_m"] == 0, "n_excluded"] == 0).all()
        assert (folds.loc[folds["buffer_m"] == 1000, "n_excluded"] > 0).all()
        correlograms = pd.read_csv(output_dir / "spatial_cv_sweep_correlograms.csv")
        assert set(correlograms["band_type"]) == {"ring", "cumulative"}
        assert set(correlograms["series"]) == {
            "satellite_only_linear",
            "satellite_only_rf",
            "limited_linear",
            "limited_rf",
        }
        assert (output_dir / "spatial_cv_sweep_r2.png").is_file()
        residuals = pd.read_csv(output_dir / "sweep" / "seed42_block2700_buffer0_residuals.csv")
        assert len(residuals) == 60

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("完了済みの設定を計算し直してはならない")

        monkeypatch.setattr(diagnose, "run_config", _fail_if_called)
        main(argv)

    def test_stops_when_primary_sample_differs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """保存済みの評価セルと同じ設定の標本が一致しなければ止める。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        original = diagnose.draw_evaluation_cells

        def _shifted(*args: object, **kwargs: object):
            cells, summary = original(*args, **kwargs)
            cells[FOLD_COLUMN] = (cells[FOLD_COLUMN] % 5) + 1
            return cells, summary

        monkeypatch.setattr(diagnose, "draw_evaluation_cells", _shifted)
        with pytest.raises(ValueError, match="一致しません"):
            main(
                [
                    "sweep",
                    "--evaluation-cells",
                    str(cells_path),
                    "--output-dir",
                    str(tmp_path / "design"),
                    *SWEEP_OPTIONS,
                ]
            )


class TestSemivariogram:
    """semivariogram サブコマンドのテスト。"""

    def test_runs_on_common_evaluation_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """共通集合の LST でセミバリオグラムを複数本求めて保存する。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        output_dir = tmp_path / "design"
        main(
            [
                "semivariogram",
                "--evaluation-cells",
                str(cells_path),
                "--output-dir",
                str(output_dir),
                "--sample-size",
                "100",
                "--repeats",
                "2",
                "--max-lag-m",
                "9000",
            ]
        )
        result = json.loads(
            (output_dir / "lst_semivariogram_results.json").read_text(encoding="utf-8")
        )
        assert result["population"] == "common_evaluation_set"
        assert result["population_size"] == 300
        assert [run["seed"] for run in result["repeats"]] == [42, 43]
        assert len(result["spread"]["empirical_range_m"]) == 2
        lags = pd.read_csv(output_dir / "lst_semivariogram_lags.csv")
        assert sorted(lags["repeat"].unique()) == [1, 2]
        assert (output_dir / "lst_semivariogram.png").is_file()

    def test_runs_on_dataset_valid_population(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """データセット指定では Limited の有効母集団を使い、観測日時をファイル名から読む。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        dataset_path = cells_path.parents[1] / "dataset_limited_20220906_032358_hanoi_30m.gpkg"
        output_dir = tmp_path / "design_dataset"
        main(
            [
                "semivariogram",
                "--dataset",
                str(dataset_path),
                "--output-dir",
                str(output_dir),
                "--sample-size",
                "100",
                "--repeats",
                "1",
                "--max-lag-m",
                "9000",
            ]
        )
        result = json.loads(
            (output_dir / "lst_semivariogram_results.json").read_text(encoding="utf-8")
        )
        assert result["population"] == "limited_valid_population"
        assert result["observation"] == "20220906_032358"
        assert result["population_size"] == 300
