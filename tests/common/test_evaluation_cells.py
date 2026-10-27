"""src/common/evaluation_cells.py（共通評価セルの保存・読込・検証）のテスト。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.evaluation_cells import (
    BLOCK_ID_COLUMN,
    CELL_ID_COLUMN,
    FOLD_COLUMN,
    METADATA_CELLS_KEY,
    build_evaluation_cells,
    build_evaluation_record,
    build_fold_labels,
    compute_evaluation_cells_digest,
    evaluation_input_paths,
    folds_from_labels,
    load_evaluation_set,
    load_evaluation_set_for_run,
    resolve_evaluation_folds,
    resolve_evaluation_output_dir,
    resolve_evaluation_output_stem,
    resolve_metadata_path,
    save_evaluation_set,
    select_evaluation_rows,
    validate_run_settings,
)
from src.common.spatial_cv import split_by_spatial_blocks

SETTINGS = {
    "block_size_m": 2_700,
    "cv_splits": 3,
    "scale_m": 30,
    "random_state": 42,
    "sample_size": 12,
    "lst_valid_ratio_threshold": 0.5,
    "analysis_area": "roi",
}


def _cells(n: int = 12) -> pd.DataFrame:
    """3 fold・6ブロックの評価セル（cell_id は行順と逆順に振る）。"""
    block_ids = np.repeat(np.arange(6), n // 6)
    folds = split_by_spatial_blocks(block_ids, n_splits=3)
    return build_evaluation_cells(
        cell_ids=np.arange(n)[::-1] + 100,
        block_ids=block_ids,
        fold_labels=build_fold_labels(folds, n),
    )


class TestFoldLabels:
    """build_fold_labels・folds_from_labels のテスト（fold の往復変換）。"""

    def test_round_trip_reproduces_group_kfold_exactly(self) -> None:
        """GroupKFold の分割を番号に直して戻すと、train/test が完全に一致する。"""
        block_ids = np.array([3, 1, 1, 2, 0, 3, 2, 0, 4, 4, 1, 0])
        folds = split_by_spatial_blocks(block_ids, n_splits=3)

        restored = folds_from_labels(build_fold_labels(folds, len(block_ids)), n_splits=3)

        assert len(restored) == len(folds)
        for (train_a, test_a), (train_b, test_b) in zip(folds, restored, strict=True):
            np.testing.assert_array_equal(train_a, train_b)
            np.testing.assert_array_equal(test_a, test_b)

    def test_labels_start_at_one(self) -> None:
        """fold 番号は fold 別指標 CSV と同じく 1 始まりになる。"""
        folds = [(np.array([2, 3]), np.array([0, 1])), (np.array([0, 1]), np.array([2, 3]))]

        np.testing.assert_array_equal(build_fold_labels(folds, 4), [1, 1, 2, 2])

    def test_raises_when_a_row_is_in_no_test_fold(self) -> None:
        """どの fold のテストにも入らない行があれば停止する。"""
        folds = [(np.array([1, 2]), np.array([0]))]

        with pytest.raises(ValueError, match="どの fold"):
            build_fold_labels(folds, 3)

    def test_raises_when_a_row_is_in_two_test_folds(self) -> None:
        """2つの fold のテストに入る行があれば停止する。"""
        folds = [(np.array([1]), np.array([0])), (np.array([1]), np.array([0]))]

        with pytest.raises(ValueError, match="複数の fold"):
            build_fold_labels(folds, 2)

    def test_folds_from_labels_rejects_mismatched_split_count(self) -> None:
        """fold 番号の種類が分割数と違えば停止する（欠けた fold・余分な fold）。"""
        with pytest.raises(ValueError, match="分割数と一致しません"):
            folds_from_labels(np.array([1, 1, 2, 2]), n_splits=3)
        with pytest.raises(ValueError, match="分割数と一致しません"):
            folds_from_labels(np.array([1, 2, 3, 4]), n_splits=3)


class TestBuildEvaluationCells:
    """build_evaluation_cells のテスト。"""

    def test_keeps_given_row_order(self) -> None:
        """行順は引数のまま保つ（行順が標本の行順になるため並べ替えない）。"""
        cells = build_evaluation_cells(
            np.array([9, 3, 5]), np.array([0, 0, 1]), np.array([1, 1, 2])
        )

        assert list(cells[CELL_ID_COLUMN]) == [9, 3, 5]
        assert list(cells.columns) == [CELL_ID_COLUMN, BLOCK_ID_COLUMN, FOLD_COLUMN]

    def test_raises_on_duplicated_cell_id(self) -> None:
        """cell_id が重複していれば停止する。"""
        with pytest.raises(ValueError, match="重複"):
            build_evaluation_cells(np.array([1, 1]), np.array([0, 0]), np.array([1, 2]))

    def test_raises_on_length_mismatch(self) -> None:
        """3つの配列の長さが揃わなければ停止する。"""
        with pytest.raises(ValueError, match="長さ"):
            build_evaluation_cells(np.array([1, 2]), np.array([0]), np.array([1, 2]))


class TestDigest:
    """compute_evaluation_cells_digest のテスト。"""

    def test_depends_on_row_order(self) -> None:
        """同じセルでも行順が変わればダイジェストが変わる（行順で train/test が決まるため）。"""
        cells = _cells()
        reversed_cells = cells.iloc[::-1].reset_index(drop=True)

        assert compute_evaluation_cells_digest(cells) != compute_evaluation_cells_digest(
            reversed_cells
        )

    def test_does_not_depend_on_integer_dtype(self) -> None:
        """int32 で読まれた場合でも、値が同じなら同じダイジェストになる。"""
        cells = _cells()

        assert compute_evaluation_cells_digest(cells) == compute_evaluation_cells_digest(
            cells.astype(np.int32)
        )


class TestSaveAndLoadEvaluationSet:
    """save_evaluation_set・load_evaluation_set のテスト（CSV とメタデータの対応）。"""

    def test_round_trip(self, tmp_path: Path) -> None:
        """保存した評価セルを、行順・値・設定とも同じまま読み戻せる。"""
        cells = _cells()
        cells_path = tmp_path / "evaluation_cells_seed42.csv"

        save_evaluation_set(cells, cells_path, dict(SETTINGS))
        loaded = load_evaluation_set(cells_path)

        pd.testing.assert_frame_equal(loaded.cells, cells)
        assert loaded.metadata_path == tmp_path / "evaluation_cells_seed42_results.json"
        assert loaded.metadata["block_size_m"] == 2_700
        assert loaded.digest == compute_evaluation_cells_digest(cells)
        assert loaded.metadata[METADATA_CELLS_KEY]["row_count"] == len(cells)

    def test_metadata_file_name_ends_with_results_json(self) -> None:
        """メタデータは陳腐化チェックの走査対象になる `_results.json` で終わる。"""
        assert resolve_metadata_path(Path("a/evaluation_cells_seed42.csv")).name.endswith(
            "_results.json"
        )

    def test_crlf_line_endings_do_not_break_verification(self, tmp_path: Path) -> None:
        """改行が CRLF に変わっても、内容が同じなら検証を通る（git の改行変換への備え）。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, dict(SETTINGS))
        text = cells_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        cells_path.write_bytes(text)

        load_evaluation_set(cells_path)

    def test_raises_when_csv_was_changed_after_saving(self, tmp_path: Path) -> None:
        """CSV だけを書き換えると、メタデータとの不一致で停止する。"""
        cells = _cells()
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(cells, cells_path, dict(SETTINGS))
        changed = cells.copy()
        changed.loc[0, FOLD_COLUMN] = 3 if changed.loc[0, FOLD_COLUMN] != 3 else 1
        changed.to_csv(cells_path, index=False)

        with pytest.raises(ValueError, match="一致しません"):
            load_evaluation_set(cells_path)

    def test_raises_when_metadata_is_missing(self, tmp_path: Path) -> None:
        """対になるメタデータ JSON が無ければ停止する。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        _cells().to_csv(cells_path, index=False)

        with pytest.raises(FileNotFoundError, match="メタデータ"):
            load_evaluation_set(cells_path)

    def test_save_requires_setting_keys(self, tmp_path: Path) -> None:
        """設定キー（ブロックサイズ・分割数等）が欠けたメタデータは保存しない。"""
        with pytest.raises(ValueError, match="cv_splits"):
            save_evaluation_set(
                _cells(), tmp_path / "cells.csv", {"block_size_m": 2_700, "scale_m": 30}
            )
        assert not (tmp_path / "cells.csv").exists()

    def test_raises_when_cells_have_missing_values(self, tmp_path: Path) -> None:
        """CSV に欠測があれば停止する。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, dict(SETTINGS))
        broken = pd.read_csv(cells_path).astype(float)
        broken.loc[0, BLOCK_ID_COLUMN] = np.nan
        broken.to_csv(cells_path, index=False)

        with pytest.raises(ValueError, match="欠測"):
            load_evaluation_set(cells_path)

    def test_saved_metadata_keeps_caller_keys(self, tmp_path: Path) -> None:
        """呼び出し側が渡したキー（定義・母数など）はそのまま保存される。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, {**SETTINGS, "common_size": 123})

        saved = json.loads(resolve_metadata_path(cells_path).read_text(encoding="utf-8"))

        assert saved["common_size"] == 123


class TestValidateRunSettings:
    """validate_run_settings のテスト（引数とメタデータの一致検査）。"""

    def test_accepts_matching_settings(self) -> None:
        """すべて一致すれば何もしない。"""
        validate_run_settings(SETTINGS, **SETTINGS)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("block_size_m", 3_000),
            ("cv_splits", 5),
            ("scale_m", 90),
            ("random_state", 43),
            ("sample_size", 0),
            ("lst_valid_ratio_threshold", 0.6),
            ("analysis_area", "survey"),
        ],
    )
    def test_raises_on_any_mismatch(self, key: str, value: object) -> None:
        """どれか1つでも食い違えば、その項目名を示して停止する。"""
        with pytest.raises(ValueError, match=key):
            validate_run_settings(SETTINGS, **{**SETTINGS, key: value})


class TestLoadEvaluationSetForRun:
    """load_evaluation_set_for_run のテスト（分析スクリプトの引数からの読込）。"""

    @staticmethod
    def _args(cells_path: Path | None, **overrides: object) -> argparse.Namespace:
        """分析スクリプトと同じ名前の引数を持つ Namespace を作る。"""
        values = {
            "evaluation_cells": cells_path,
            "block_size_m": 2_700,
            "cv_splits": 3,
            "scale": 30,
            "random_state": 42,
            "sample_size": 12,
            "lst_valid_ratio_threshold": 0.5,
            "analysis_area": "roi",
        }
        return argparse.Namespace(**{**values, **overrides})

    def test_returns_none_without_evaluation_cells(self) -> None:
        """--evaluation-cells 未指定なら何も読まない。"""
        assert load_evaluation_set_for_run(self._args(None)) is None

    def test_loads_and_validates(self, tmp_path: Path) -> None:
        """指定があれば読み込み、引数が一致すれば EvaluationSet を返す。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, dict(SETTINGS))

        evaluation_set = load_evaluation_set_for_run(self._args(cells_path))

        assert evaluation_set is not None
        assert evaluation_input_paths(evaluation_set) == [
            evaluation_set.cells_path,
            evaluation_set.metadata_path,
        ]

    def test_stops_when_block_size_differs(self, tmp_path: Path) -> None:
        """--block-size-m がメタデータと違えば停止する。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, dict(SETTINGS))

        with pytest.raises(ValueError, match="block_size_m"):
            load_evaluation_set_for_run(self._args(cells_path, block_size_m=3_000))

    def test_input_paths_are_empty_without_evaluation_set(self) -> None:
        """評価セルを使わないランでは、来歴に入力を加えない。"""
        assert evaluation_input_paths(None) == []


class TestEvaluationOutputNames:
    """評価セルを使うランの出力先・出力名のテスト（既存ランを上書きしない）。"""

    def test_output_dir_gets_suffix(self) -> None:
        """出力先は通常ランのディレクトリ名に接尾辞を付けた兄弟ディレクトリになる。"""
        path = resolve_evaluation_output_dir(Path("data/output/limited/20220906_032358"))

        assert path == Path("data/output/limited/20220906_032358_common_evaluation")

    def test_output_stem_gets_cells_name(self) -> None:
        """出力名には評価セル CSV の名前を付ける。"""
        cells_path = Path("a/evaluation_cells_seed42.csv")
        stem = resolve_evaluation_output_stem("dataset_x_30m", cells_path)

        assert stem == "dataset_x_30m_evaluation_cells_seed42"


class TestResolveEvaluationFolds:
    """resolve_evaluation_folds のテスト（評価セルの fold 列からの分割）。"""

    def test_returns_folds_from_labels(self) -> None:
        """ブロック ID が一致すれば、fold 列どおりの分割を返す。"""
        cells = _cells()

        folds = resolve_evaluation_folds(cells, cells[BLOCK_ID_COLUMN].to_numpy(), 3)

        for fold_number, (_, test_idx) in enumerate(folds, start=1):
            np.testing.assert_array_equal(
                test_idx, np.flatnonzero(cells[FOLD_COLUMN].to_numpy() == fold_number)
            )

    def test_stops_when_block_ids_differ(self) -> None:
        """標本に割り当て直したブロック ID が評価セルと違えば停止する。"""
        cells = _cells()
        block_ids = cells[BLOCK_ID_COLUMN].to_numpy() + 1

        with pytest.raises(ValueError, match="block_id"):
            resolve_evaluation_folds(cells, block_ids, 3)

    def test_stops_when_split_count_differs(self) -> None:
        """fold の種類が分割数と違えば停止する。"""
        cells = _cells()

        with pytest.raises(ValueError, match="分割数"):
            resolve_evaluation_folds(cells, cells[BLOCK_ID_COLUMN].to_numpy(), 5)

    def test_stops_when_a_fold_has_one_test_row(self) -> None:
        """テスト行が1行の fold があれば停止する。"""
        cells = build_evaluation_cells(
            np.array([1, 2, 3, 4]), np.array([0, 0, 0, 1]), np.array([1, 1, 1, 2])
        )

        with pytest.raises(ValueError, match="2行以上"):
            resolve_evaluation_folds(cells, cells[BLOCK_ID_COLUMN].to_numpy(), 2)


class TestBuildEvaluationRecord:
    """build_evaluation_record のテスト（results.json への記録）。"""

    def test_records_both_population_sizes_and_digest(self, tmp_path: Path) -> None:
        """自シナリオの母数・共通集合の母数・ダイジェストを並べて記録する。"""
        cells_path = tmp_path / "evaluation_cells_seed42.csv"
        save_evaluation_set(_cells(), cells_path, {**SETTINGS, "common_size": 1_000})
        evaluation_set = load_evaluation_set(cells_path)

        record = build_evaluation_record(evaluation_set, population_size=1_234)

        assert record["population_size"] == 1_234
        assert record["common_size"] == 1_000
        assert record["digest"] == evaluation_set.digest
        assert record["row_count"] == 12
        json.dumps(record, allow_nan=False)


class TestSelectEvaluationRows:
    """select_evaluation_rows のテスト（有効母集団からの行の選択）。"""

    def _population(self) -> pd.DataFrame:
        """cell_id 100〜111 の有効母集団（値は cell_id に対応させる）。"""
        cell_ids = np.arange(100, 112)
        return pd.DataFrame({CELL_ID_COLUMN: cell_ids, "VALUE": cell_ids * 10.0})

    def test_selects_rows_in_evaluation_order(self) -> None:
        """母集団の行順ではなく、評価セルの行順で選ぶ。"""
        cells = _cells()

        selected = select_evaluation_rows(self._population(), cells)

        assert list(selected[CELL_ID_COLUMN]) == list(cells[CELL_ID_COLUMN])
        assert list(selected["VALUE"]) == [cell_id * 10.0 for cell_id in cells[CELL_ID_COLUMN]]
        assert list(selected.index) == list(range(len(cells)))

    def test_raises_when_a_cell_is_outside_population(self) -> None:
        """評価セルが1件でも母集団に無ければ停止する。"""
        population = self._population().iloc[1:]

        with pytest.raises(ValueError, match="1 件"):
            select_evaluation_rows(population, _cells())

    def test_raises_when_population_has_duplicated_cell_id(self) -> None:
        """母集団の cell_id が重複していれば停止する（行の選び方が一意に決まらない）。"""
        population = pd.concat([self._population(), self._population().iloc[:1]])

        with pytest.raises(ValueError, match="重複"):
            select_evaluation_rows(population, _cells())
