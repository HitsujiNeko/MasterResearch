"""src/analysis/repeat_common_evaluation.py（複数シードでの Spatial CV の反復）のテスト。

合成データで評価セルを作り（`build_common_evaluation_set.main`）、少ないシード数・
少ない決定木で反復を通して、保存物・再開・集計を確かめる。データセットの読込は
列選択を模した偽物へ差し替える。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis import build_common_evaluation_set
from src.analysis import repeat_common_evaluation as repeat
from src.analysis.repeat_common_evaluation import (
    load_completed_seed,
    main,
    prepare_limited_sample,
    resolve_limited_feature_columns,
    resolve_seeds,
    seed_paths,
    summarize_seed_differences,
    summarize_seed_variation,
)
from src.common.analysis_dataset import IN_ANALYSIS_AREA_SURVEY_COLUMN
from src.common.cv_paired_comparison import FOLD_METRIC_COLUMNS
from src.common.evaluation_cells import resolve_metadata_path
from tests.analysis.test_build_common_evaluation_set import (
    _limited_dataframe,
    _satellite_only_dataframe,
)


def _install_loaders(
    monkeypatch: pytest.MonkeyPatch, satellite: pd.DataFrame, limited_df: pd.DataFrame
) -> None:
    """両分析スクリプトの読込関数を、列選択を模した偽物へ差し替える。"""

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


def _build_cells(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, analysis_area: str = "roi"
) -> Path:
    """合成データで評価セル（シード42・200件）を作る。

    Args:
        monkeypatch: データセット読込関数の差し替えに使う pytest のフィクスチャ。
        tmp_path: 合成データと評価セルの保存先。
        analysis_area: 分析対象範囲。`survey` のときは末尾20セルを測量GIS範囲外とする。
    Returns:
        生成した評価セル CSV のパス。
    """
    satellite = _satellite_only_dataframe()
    limited_df = _limited_dataframe(satellite)
    if analysis_area == "survey":
        survey_mask = np.where(np.arange(len(satellite)) >= len(satellite) - 20, 0, 1)
        satellite[IN_ANALYSIS_AREA_SURVEY_COLUMN] = survey_mask
        limited_df[IN_ANALYSIS_AREA_SURVEY_COLUMN] = survey_mask
    _install_loaders(monkeypatch, satellite, limited_df)
    satellite_path = tmp_path / "dataset_satellite_only_20220906_032358_hanoi_30m.gpkg"
    limited_path = tmp_path / "dataset_limited_20220906_032358_hanoi_30m.gpkg"
    satellite_path.write_bytes(b"satellite")
    limited_path.write_bytes(b"limited")
    build_common_evaluation_set.main(
        [
            "--satellite-only-dataset",
            str(satellite_path),
            "--limited-dataset",
            str(limited_path),
            "--output-dir",
            str(tmp_path / "common"),
            "--sample-size",
            "200",
            "--analysis-area",
            analysis_area,
        ]
    )
    return tmp_path / "common" / "evaluation_cells_seed42.csv"


def _fold_frame(offset: float) -> pd.DataFrame:
    """5 fold の fold 別指標の合成データ。"""
    frame = pd.DataFrame({"fold": range(1, 6), "train_size": [80] * 5, "test_size": [20] * 5})
    for column in FOLD_METRIC_COLUMNS:
        frame[column] = np.linspace(0.5, 0.6, 5) + offset
    return frame


class TestHelpers:
    """補助関数のテスト。"""

    def test_seeds_are_consecutive_from_first_seed(self) -> None:
        """シードは最初のシードからの連番（既定 42〜61 の20個）。"""
        assert resolve_seeds(42, 20) == list(range(42, 62))

    def test_seed_files_are_not_scanned_as_results(self) -> None:
        """シードごとの途中結果は `_results.json` で終わらない（陳腐化チェックの対象外）。"""
        paths = seed_paths(Path("out"), 42)

        assert all(not path.name.endswith("_results.json") for path in paths.values())

    def test_limited_features_follow_adopted_configuration(self) -> None:
        """Limited の投入列は分析スクリプトの既定（採用構成）と同じ。"""
        from src.analysis import analysis_rq3_limited as limited

        defaults = limited.parse_arguments([])
        assert resolve_limited_feature_columns() == limited.resolve_feature_columns(
            defaults.variable_set,
            defaults.population_source,
            defaults.building_height,
            defaults.water_index,
        )

    def test_prepare_limited_sample_drops_constant_columns(self) -> None:
        """分散0の列は Limited の関数で除外し、除外した列を返す。"""
        sample = _limited_dataframe(_satellite_only_dataframe())
        sample["LULC_BARE_COV"] = 0.0
        columns = resolve_limited_feature_columns()

        _, kept, dropped = prepare_limited_sample(sample, columns)

        if "LULC_BARE_COV" in columns:
            assert "LULC_BARE_COV" in dropped
        assert set(kept) | set(dropped) == set(columns)

    def test_parse_rejects_single_seed(self) -> None:
        """シード間の変動を求められないため、シード数1は受け付けない。"""
        with pytest.raises(SystemExit):
            repeat.parse_arguments(["--n-seeds", "1"])


class TestSummaries:
    """シード間の集計のテスト。"""

    def test_seed_variation_uses_fold_means(self) -> None:
        """シードごとの fold 平均から、シード間の平均・sd・範囲を求める。"""
        frames = [
            _fold_frame(offset).assign(scenario=scenario, seed=seed)
            for seed, offset in ((1, 0.0), (2, 0.02))
            for scenario in ("satellite_only", "limited")
        ]

        variation = summarize_seed_variation(pd.concat(frames, ignore_index=True))

        rf_r2 = variation["limited"]["rf_r2"]
        assert rf_r2["mean"] == pytest.approx(0.56)
        assert rf_r2["min"] == pytest.approx(0.55)
        assert rf_r2["max"] == pytest.approx(0.57)
        assert rf_r2["sd"] == pytest.approx(np.std([0.55, 0.57], ddof=1))

    def test_seed_differences_report_percentiles(self) -> None:
        """シードごとの差（fold 平均）の平均・sd・2.5/97.5 パーセンタイルを出す。"""
        differences = pd.concat(
            [_fold_frame(offset).assign(seed=seed) for seed, offset in ((1, 0.0), (2, 0.1))],
            ignore_index=True,
        )

        summary = summarize_seed_differences(differences)

        assert set(summary["rf_r2"]) == {"mean", "sd", "p2.5", "p97.5"}
        assert summary["rf_r2"]["mean"] == pytest.approx(0.6)


class TestResume:
    """load_completed_seed のテスト（中断からの再開）。"""

    def test_returns_none_when_files_are_missing(self, tmp_path: Path) -> None:
        """完了印が無いシードは未完了とみなす。"""
        assert load_completed_seed(tmp_path, 42, "abc") is None

    def test_reuses_only_when_digest_matches(self, tmp_path: Path) -> None:
        """標本のダイジェストが一致するときだけ途中結果を再利用する。"""
        paths = seed_paths(tmp_path, 42)
        _fold_frame(0.0).to_csv(paths["satellite_only"], index=False)
        _fold_frame(0.1).to_csv(paths["limited"], index=False)
        paths["summary"].write_text(json.dumps({"seed": 42, "digest": "abc"}), encoding="utf-8")

        assert load_completed_seed(tmp_path, 42, "abc") is not None
        assert load_completed_seed(tmp_path, 42, "other") is None


class TestMain:
    """main() のテスト（合成データで2シードを通す）。"""

    def test_runs_seeds_saves_results_and_resumes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """2シードを回して結果を保存し、再実行では途中結果を再利用する。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        argv = ["--evaluation-cells", str(cells_path), "--n-seeds", "2", "--rf-trees", "5"]

        main(argv)

        result_path = cells_path.with_name(
            "repeated_comparison_evaluation_cells_seed42_results.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["seeds"] == [42, 43]
        assert result["analysis_area"] == "roi"
        assert result["repeated_kfold"]["metrics"]["rf_r2"]["n_splits"] == 10
        assert result["repeated_kfold"]["metrics"]["rf_r2"]["degrees_of_freedom"] == 9
        assert set(result["seed_variation"]) == {"satellite_only", "limited"}
        assert len(result["provenance"]["inputs"]) == 4
        differences = pd.read_csv(
            cells_path.with_name("repeated_comparison_evaluation_cells_seed42_differences.csv")
        )
        assert sorted(differences["seed"].unique()) == [42, 43]

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("完了済みのシードを計算し直してはならない")

        monkeypatch.setattr(repeat, "run_seed", _fail_if_called)
        main(argv)

    def test_stops_when_primary_seed_sample_differs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """主シードで作り直した標本が保存済みの評価セルと違えば停止する。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        original = repeat.draw_evaluation_cells

        def _shifted(*args: object, **kwargs: object):
            cells, summary = original(*args, **kwargs)
            return cells.iloc[::-1].reset_index(drop=True), summary

        monkeypatch.setattr(repeat, "draw_evaluation_cells", _shifted)

        with pytest.raises(ValueError, match="一致しません"):
            main(["--evaluation-cells", str(cells_path), "--n-seeds", "2", "--rf-trees", "5"])

    def test_runs_seeds_on_survey_area_cells(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """測量GIS範囲の評価セルでも、記録された範囲で母集団を作り直して反復できる。"""
        cells_path = _build_cells(monkeypatch, tmp_path, analysis_area="survey")

        main(["--evaluation-cells", str(cells_path), "--n-seeds", "2", "--rf-trees", "5"])

        result = json.loads(
            cells_path.with_name(
                "repeated_comparison_evaluation_cells_seed42_results.json"
            ).read_text(encoding="utf-8")
        )
        assert result["seeds"] == [42, 43]
        assert result["analysis_area"] == "survey"

    def test_stops_on_unknown_analysis_area(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """メタデータの範囲が対応外なら、データセットを読む前に停止する。"""
        cells_path = _build_cells(monkeypatch, tmp_path)
        metadata_path = resolve_metadata_path(cells_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["analysis_area"] = "city"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(ValueError, match="未対応の分析対象範囲"):
            main(["--evaluation-cells", str(cells_path), "--n-seeds", "2", "--rf-trees", "5"])
