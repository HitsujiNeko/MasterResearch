"""シナリオ間で共通の評価セル（標本の cell_id と fold 割り当て）の保存・読込・検証。

Satellite Only と Limited の性能を「同じセル・同じ fold」の上で比べるため、
評価に使うセル（`cell_id`）・空間ブロック（`block_id`）・fold 番号（`fold`）を
CSV に固定し、各分析スクリプトはそれを読み込んで標本と fold を再現する。

- 評価セル CSV（例: `evaluation_cells_seed42.csv`）: 行順が標本の行順そのもので
  あり、ランダム分割もこの行順の上で行う。行順を変えると train/test が変わる
- メタデータ JSON（CSV と同じディレクトリの `{CSV の stem}_results.json`）:
  評価セルを作ったときの実行設定（ブロックサイズ・分割数・解像度・乱数シード・
  標本サイズ・LST 有効率の下限・分析対象範囲）と、CSV の内容ダイジェストを持つ。
  分析スクリプト側の引数がこれと食い違う場合は停止する（`validate_run_settings`）。
  ファイル名を `_results.json` で終わらせるのは、陳腐化チェック
  （`scripts/check_result_staleness.py`）の走査対象にするためである

分析スクリプト（Satellite Only・Limited）の `--evaluation-cells` は、
`load_evaluation_set_for_run`（読込と引数の照合）・`select_evaluation_rows`
（標本の選択）・`resolve_evaluation_folds`（fold の再現）・
`build_evaluation_record` / `evaluation_input_paths`（結果 JSON と来歴への記録）を
共通に使う。出力は通常ランと別のディレクトリ・別のファイル名にして、既存ランを
上書きしない（`resolve_evaluation_output_dir` / `resolve_evaluation_output_stem`）。

**内容ダイジェストはファイルのバイト列ではなく、3列を int64 に揃えた値から求める**
（`compute_evaluation_cells_digest`）。CSV はテキストのため、git の改行変換
（autocrlf）でバイト列が環境ごとに変わりうる。セルと fold の中身が同じなら
同じダイジェストになるようにして、CSV とメタデータの対応を確かめる。

fold 番号は 1 始まりとし、Spatial CV の fold 別指標 CSV（`spatial_cv_folds.csv`）の
`fold` 列と同じ番号にする。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.analysis_runs import validate_fold_test_sizes
from src.common.paths import to_project_relative_string
from src.common.summary import save_summary

CELL_ID_COLUMN = "cell_id"
BLOCK_ID_COLUMN = "block_id"
FOLD_COLUMN = "fold"
EVALUATION_CELLS_COLUMNS = [CELL_ID_COLUMN, BLOCK_ID_COLUMN, FOLD_COLUMN]
# メタデータ JSON に必ず含める実行設定のキー。分析スクリプトの引数と突き合わせる
# （`validate_run_settings`）。乱数シードはランダム分割と RF の両方に使うため、
# シナリオ間で同じ train/test・同じ学習条件にするには一致させる必要がある。
METADATA_SETTING_KEYS = (
    "block_size_m",
    "cv_splits",
    "scale_m",
    "random_state",
    "sample_size",
    "lst_valid_ratio_threshold",
    "analysis_area",
)
# メタデータ JSON の中で、評価セル CSV の情報を持つキー。
METADATA_CELLS_KEY = "evaluation_cells"
# 評価セルを使うランの既定の出力先は、通常ランのディレクトリ名にこの接尾辞を付けた
# 別ディレクトリとし、既存ランの出力を上書きしない。
EVALUATION_OUTPUT_DIR_SUFFIX = "_common_evaluation"


@dataclass(frozen=True)
class EvaluationSet:
    """load_evaluation_set の戻り値。

    Attributes:
        cells: 評価セル（`EVALUATION_CELLS_COLUMNS` の3列。行順は CSV のまま）。
        metadata: メタデータ JSON の内容。
        cells_path: 評価セル CSV のパス。
        metadata_path: メタデータ JSON のパス。
        digest: `cells` の内容ダイジェスト（`compute_evaluation_cells_digest`）。
    """

    cells: pd.DataFrame
    metadata: dict[str, Any]
    cells_path: Path
    metadata_path: Path
    digest: str


def resolve_metadata_path(cells_path: Path) -> Path:
    """評価セル CSV のパスから、対になるメタデータ JSON のパスを求める。

    Args:
        cells_path: 評価セル CSV のパス。
    Returns:
        同じディレクトリの `{CSV の stem}_results.json`。
    """
    return cells_path.with_name(f"{cells_path.stem}_results.json")


def build_fold_labels(folds: list[tuple[np.ndarray, np.ndarray]], n_rows: int) -> np.ndarray:
    """(train_idx, test_idx) のリストを、行ごとの fold 番号（1 始まり）へ変換する。

    Args:
        folds: `split_by_spatial_blocks` の戻り値（fold 順）。
        n_rows: 分割対象の行数。
    Returns:
        行ごとの fold 番号（int64 の配列。行 i はテストとして入った fold の番号）。
    Raises:
        ValueError: どの fold のテストにも入らない行、または複数の fold のテストに
            入る行がある場合（交差検証の分割になっていない）。
    """
    labels = np.zeros(n_rows, dtype=np.int64)
    for fold_number, (_, test_idx) in enumerate(folds, start=1):
        if np.any(labels[test_idx] != 0):
            raise ValueError("複数の fold のテストに入る行があります。")
        labels[test_idx] = fold_number
    if np.any(labels == 0):
        raise ValueError(
            f"どの fold のテストにも入らない行があります（{int(np.sum(labels == 0))}行）。"
        )
    return labels


def folds_from_labels(
    fold_labels: np.ndarray, n_splits: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """行ごとの fold 番号を、(train_idx, test_idx) のリストへ戻す。

    `build_fold_labels` の逆変換であり、GroupKFold の戻り値と同じく各インデックスは
    昇順に並ぶ。

    Args:
        fold_labels: 行ごとの fold 番号（1 始まり）。
        n_splits: 分割数。fold 番号は 1〜`n_splits` をすべて含む必要がある。
    Returns:
        (train_idx, test_idx) のタプルのリスト（fold 番号順）。
    Raises:
        ValueError: fold 番号の種類が 1〜`n_splits` と一致しない場合。
    """
    labels = np.asarray(fold_labels)
    found = sorted(int(value) for value in np.unique(labels))
    expected = list(range(1, n_splits + 1))
    if found != expected:
        raise ValueError(
            f"fold 番号の種類が分割数と一致しません（fold列の値: {found}、期待: {expected}）。"
        )
    return [
        (np.flatnonzero(labels != fold_number), np.flatnonzero(labels == fold_number))
        for fold_number in expected
    ]


def build_evaluation_cells(
    cell_ids: np.ndarray, block_ids: np.ndarray, fold_labels: np.ndarray
) -> pd.DataFrame:
    """評価セルのデータフレームを組み立てる（行順は引数のまま）。

    Args:
        cell_ids: 標本の cell_id（行順が標本の行順になる）。
        block_ids: 各行の空間ブロック ID。
        fold_labels: 各行の fold 番号（1 始まり）。
    Returns:
        `EVALUATION_CELLS_COLUMNS` の3列を int64 で持つデータフレーム。
    Raises:
        ValueError: 3つの配列の長さが揃わない場合、または cell_id が重複する場合。
    """
    lengths = {len(cell_ids), len(block_ids), len(fold_labels)}
    if len(lengths) != 1:
        raise ValueError(
            "cell_id・block_id・fold の長さが揃っていません"
            f"（{len(cell_ids)}, {len(block_ids)}, {len(fold_labels)}）。"
        )
    cells = pd.DataFrame(
        {
            CELL_ID_COLUMN: np.asarray(cell_ids, dtype=np.int64),
            BLOCK_ID_COLUMN: np.asarray(block_ids, dtype=np.int64),
            FOLD_COLUMN: np.asarray(fold_labels, dtype=np.int64),
        }
    )
    _require_unique_cell_ids(cells, "評価セル")
    return cells


def compute_evaluation_cells_digest(cells: pd.DataFrame) -> str:
    """評価セルの内容ダイジェスト（SHA-256）を、行順も含めて求める。

    ファイルのバイト列ではなく値から求める理由は module docstring を参照する。

    Args:
        cells: `EVALUATION_CELLS_COLUMNS` の3列を持つデータフレーム。
    Returns:
        SHA-256 の16進文字列。
    """
    values = np.ascontiguousarray(cells[EVALUATION_CELLS_COLUMNS].to_numpy(dtype=np.int64))
    digest = hashlib.sha256()
    digest.update(",".join(EVALUATION_CELLS_COLUMNS).encode("utf-8"))
    digest.update(values.astype("<i8").tobytes())
    return digest.hexdigest()


def save_evaluation_set(
    cells: pd.DataFrame, cells_path: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    """評価セル CSV と、対になるメタデータ JSON を保存する。

    メタデータには呼び出し側が `METADATA_SETTING_KEYS` を含めておく。本関数は
    `METADATA_CELLS_KEY` に CSV のファイル名・行数・内容ダイジェストを加えてから保存する。

    Args:
        cells: `build_evaluation_cells` の戻り値。
        cells_path: 評価セル CSV の保存先。
        metadata: 保存するメタデータ（呼び出し元の辞書は変更しない）。
    Returns:
        実際に保存したメタデータ（`METADATA_CELLS_KEY` を加えたもの）。
    Raises:
        ValueError: `metadata` に `METADATA_SETTING_KEYS` のいずれかが無い場合。
    """
    missing = [key for key in METADATA_SETTING_KEYS if key not in metadata]
    if missing:
        raise ValueError(f"メタデータに必要なキーがありません: {missing}")

    cells_path.parent.mkdir(parents=True, exist_ok=True)
    cells[EVALUATION_CELLS_COLUMNS].to_csv(cells_path, index=False)
    saved = {
        **metadata,
        METADATA_CELLS_KEY: {
            "file_name": cells_path.name,
            "row_count": int(len(cells)),
            "digest": compute_evaluation_cells_digest(cells),
            "digest_note": (
                "cell_id・block_id・fold の3列を int64 に揃えた値から行順込みで求めた"
                "SHA-256。ファイルのバイト列のハッシュではない（改行変換の影響を受けない）。"
            ),
        },
    }
    save_summary(saved, resolve_metadata_path(cells_path))
    return saved


def load_evaluation_set(cells_path: Path) -> EvaluationSet:
    """評価セル CSV と対になるメタデータ JSON を読み込み、両者の対応を検証する。

    Args:
        cells_path: 評価セル CSV のパス。
    Returns:
        `EvaluationSet`。
    Raises:
        FileNotFoundError: CSV またはメタデータ JSON が無い場合。
        ValueError: CSV の列・値が不正な場合、メタデータに必要なキーが無い場合、
            または CSV の内容ダイジェストがメタデータの記録と一致しない場合。
    """
    metadata_path = resolve_metadata_path(cells_path)
    if not cells_path.is_file():
        raise FileNotFoundError(f"評価セル CSV が見つかりません: {cells_path}")
    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"評価セルのメタデータ JSON が見つかりません: {metadata_path}"
            "（評価セル CSV と同じディレクトリに `{CSV の stem}_results.json` が必要です）。"
        )

    cells = pd.read_csv(cells_path)
    missing_columns = [column for column in EVALUATION_CELLS_COLUMNS if column not in cells.columns]
    if missing_columns:
        raise ValueError(f"評価セル CSV に必要な列がありません: {missing_columns}（{cells_path}）")
    cells = cells[EVALUATION_CELLS_COLUMNS]
    if cells.isna().to_numpy().any():
        raise ValueError(f"評価セル CSV に欠測があります: {cells_path}")
    cells = cells.astype(np.int64)
    _require_unique_cell_ids(cells, f"評価セル CSV（{cells_path}）")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in METADATA_SETTING_KEYS if key not in metadata]
    recorded = metadata.get(METADATA_CELLS_KEY, {})
    if missing_keys or "digest" not in recorded:
        raise ValueError(
            f"メタデータ JSON に必要なキーがありません: {missing_keys or [METADATA_CELLS_KEY]}"
            f"（{metadata_path}）"
        )

    digest = compute_evaluation_cells_digest(cells)
    if digest != recorded["digest"]:
        raise ValueError(
            "評価セル CSV の内容がメタデータの記録と一致しません"
            f"（CSV: {cells_path}、メタデータ: {metadata_path}）。"
            "CSV だけを作り直した、または別の CSV を指定した可能性があります。"
        )
    return EvaluationSet(
        cells=cells,
        metadata=metadata,
        cells_path=cells_path,
        metadata_path=metadata_path,
        digest=digest,
    )


def validate_run_settings(
    metadata: dict[str, Any],
    *,
    block_size_m: int,
    cv_splits: int,
    scale_m: int,
    random_state: int,
    sample_size: int,
    lst_valid_ratio_threshold: float,
    analysis_area: str,
) -> None:
    """分析スクリプトの引数が、評価セルを作ったときの設定と一致することを検査する。

    食い違ったまま進むと、results.json に記録する設定（引数のブロックサイズで
    数えた非空ブロック数・要求サンプル数等）が実際に使う標本・fold と合わなくなる。
    乱数シードが違うとランダム分割の train/test と RF の学習条件がシナリオ間で
    揃わなくなり、LST 有効率の下限・分析対象範囲が違うと有効母集団の定義がずれる。

    Args:
        metadata: `EvaluationSet.metadata`。
        block_size_m: 分析スクリプトの `--block-size-m`。
        cv_splits: 分析スクリプトの `--cv-splits`。
        scale_m: 分析スクリプトの `--scale`。
        random_state: 分析スクリプトの `--random-state`。
        sample_size: 分析スクリプトの `--sample-size`。
        lst_valid_ratio_threshold: 分析スクリプトの `--lst-valid-ratio-threshold`。
        analysis_area: 分析スクリプトの `--analysis-area`。
    Returns:
        None
    Raises:
        ValueError: いずれかの値がメタデータと一致しない場合。
    """
    given = {
        "block_size_m": block_size_m,
        "cv_splits": cv_splits,
        "scale_m": scale_m,
        "random_state": random_state,
        "sample_size": sample_size,
        "lst_valid_ratio_threshold": lst_valid_ratio_threshold,
        "analysis_area": analysis_area,
    }
    mismatched = {
        key: {"argument": value, "metadata": metadata[key]}
        for key, value in given.items()
        if value != metadata[key]
    }
    if mismatched:
        raise ValueError(
            f"引数が評価セルのメタデータと一致しません: {mismatched}。"
            "評価セルを作ったときと同じ値を指定してください。"
        )


def load_evaluation_set_for_run(args: argparse.Namespace) -> EvaluationSet | None:
    """分析スクリプトの引数から評価セルを読み込み、引数との一致を検査する。

    Satellite Only・Limited の両スクリプトが同じ名前の引数
    （`--evaluation-cells`・`--block-size-m`・`--cv-splits`・`--scale`・
    `--random-state`・`--sample-size`・`--lst-valid-ratio-threshold`・
    `--analysis-area`）を持つことを前提に、読込と検査をここにまとめる。

    Args:
        args: 分析スクリプトの `parse_arguments` の戻り値。
    Returns:
        `--evaluation-cells` 未指定なら `None`、指定ありなら `EvaluationSet`。
    Raises:
        FileNotFoundError: 評価セル CSV またはメタデータ JSON が無い場合。
        ValueError: 評価セルが不正な場合、または引数がメタデータと一致しない場合。
    """
    if args.evaluation_cells is None:
        return None
    evaluation_set = load_evaluation_set(args.evaluation_cells.resolve())
    validate_run_settings(
        evaluation_set.metadata,
        block_size_m=args.block_size_m,
        cv_splits=args.cv_splits,
        scale_m=args.scale,
        random_state=args.random_state,
        sample_size=args.sample_size,
        lst_valid_ratio_threshold=args.lst_valid_ratio_threshold,
        analysis_area=args.analysis_area,
    )
    return evaluation_set


def evaluation_input_paths(evaluation_set: EvaluationSet | None) -> list[Path]:
    """来歴の入力に加える、評価セル CSV とメタデータ JSON のパスを返す。

    Args:
        evaluation_set: `load_evaluation_set_for_run` の戻り値。
    Returns:
        評価セルを使わない場合は空リスト、使う場合は [CSV, メタデータ JSON]。
    """
    if evaluation_set is None:
        return []
    return [evaluation_set.cells_path, evaluation_set.metadata_path]


def resolve_evaluation_output_dir(default_output_dir: Path) -> Path:
    """評価セルを使うランの既定の出力先を求める。

    Args:
        default_output_dir: 通常ランの既定の出力先。
    Returns:
        同じ親ディレクトリで、名前に `EVALUATION_OUTPUT_DIR_SUFFIX` を付けたパス
        （例: `20220906_032358` → `20220906_032358_common_evaluation`）。
    """
    return default_output_dir.with_name(f"{default_output_dir.name}{EVALUATION_OUTPUT_DIR_SUFFIX}")


def resolve_evaluation_output_stem(output_stem: str, cells_path: Path) -> str:
    """評価セルを使うランの出力ファイル名の接頭辞を求める。

    出力ディレクトリだけでなくファイル名にも印を付け、通常ランの出力と取り違えない
    ようにする。

    Args:
        output_stem: 通常ランの出力ファイル名の接頭辞。
        cells_path: 評価セル CSV のパス。
    Returns:
        `{output_stem}_{CSV の stem}`（例: `..._30m_evaluation_cells_seed42`）。
    """
    return f"{output_stem}_{cells_path.stem}"


def resolve_evaluation_folds(
    cells: pd.DataFrame, block_ids: np.ndarray, cv_splits: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """評価セルの fold 列から、標本の行位置による (train_idx, test_idx) を求める。

    分析スクリプトが標本に対して引数のブロックサイズで割り当て直したブロック ID が
    評価セルの `block_id` と一致することも確かめる（ブロック定義の食い違いを、
    設定の照合とは別に実データで検出するため）。

    Args:
        cells: `EvaluationSet.cells`（行順が標本の行順と一致していること）。
        block_ids: 分析スクリプトが標本に割り当てたブロック ID（行位置対応）。
        cv_splits: 分割数。
    Returns:
        (train_idx, test_idx) のタプルのリスト（fold 番号順）。
    Raises:
        ValueError: ブロック ID が評価セルと一致しない場合、fold 番号の種類が分割数と
            一致しない場合、またはテスト行が2行未満の fold がある場合。
    """
    if not np.array_equal(np.asarray(block_ids), cells[BLOCK_ID_COLUMN].to_numpy()):
        raise ValueError(
            "標本に割り当てたブロック ID が評価セルの block_id と一致しません。"
            "ブロックサイズ・解像度が評価セルを作ったときと同じか確認してください。"
        )
    folds = folds_from_labels(cells[FOLD_COLUMN].to_numpy(), cv_splits)
    validate_fold_test_sizes(folds)
    return folds


def build_evaluation_record(evaluation_set: EvaluationSet, population_size: int) -> dict[str, Any]:
    """results.json に記録する、評価セルの情報を組み立てる。

    自シナリオの有効母集団の母数と、評価セルを抽出した共通集合の母数を並べて残す
    （標本がどの母集団から抽出されたかを後から読み違えないため）。

    Args:
        evaluation_set: `load_evaluation_set` の戻り値。
        population_size: 自シナリオの有効母集団の母数（サンプリング前）。
    Returns:
        評価セル CSV・メタデータのパス、内容ダイジェスト、行数、母数の辞書。
    """
    return {
        "path": to_project_relative_string(evaluation_set.cells_path),
        "metadata_path": to_project_relative_string(evaluation_set.metadata_path),
        "digest": evaluation_set.digest,
        "row_count": int(len(evaluation_set.cells)),
        "population_size": int(population_size),
        "common_size": evaluation_set.metadata.get("common_size"),
        "note": (
            "標本と Spatial CV の fold は評価セル CSV から固定した（抽出・GroupKFold は"
            "行っていない）。population_size は本シナリオの有効母集団、common_size は"
            "評価セルを抽出した全構成の共通集合の母数。"
        ),
    }


def select_evaluation_rows(population: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    """有効母集団から、評価セルの cell_id の行を評価セルの行順で選ぶ。

    Args:
        population: シナリオの有効母集団（`cell_id` 列を持つ）。
        cells: `EvaluationSet.cells`。
    Returns:
        選んだ行（行順は `cells` のまま。インデックスは0始まりに振り直す）。
    Raises:
        ValueError: 有効母集団の cell_id が重複する場合、または評価セルの
            cell_id が有効母集団に1件でも無い場合。
    """
    _require_unique_cell_ids(population, "有効母集団")
    indexed = population.set_index(CELL_ID_COLUMN, drop=False)
    wanted = cells[CELL_ID_COLUMN].to_numpy()
    present = np.isin(wanted, indexed.index.to_numpy())
    if not bool(present.all()):
        missing = wanted[~present]
        raise ValueError(
            f"評価セルのうち {len(missing)} 件が、このシナリオの有効母集団にありません"
            f"（例: {missing[:5].tolist()}）。評価セルを作ったときと有効条件・データセットが"
            "同じか確認してください。"
        )
    return indexed.loc[wanted].reset_index(drop=True)


def _require_unique_cell_ids(dataframe: pd.DataFrame, label: str) -> None:
    """cell_id が重複していないことを検査する。

    Args:
        dataframe: `cell_id` 列を持つデータフレーム。
        label: エラーメッセージに出す対象名。
    Returns:
        None
    Raises:
        ValueError: cell_id が重複する場合。
    """
    duplicated = dataframe[CELL_ID_COLUMN].duplicated()
    if bool(duplicated.any()):
        raise ValueError(f"{label}の cell_id が重複しています（{int(duplicated.sum())}件）。")
