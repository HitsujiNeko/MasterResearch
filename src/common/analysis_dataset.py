"""分析用データセットGeoPackageの読込・品質列フィルタリング・サンプリング・
フィルタ脱落の診断集計を行う共通モジュール。

`src.analysis.build_dataset` が `cell_id` 結合で生成したGeoPackageを対象とする。
品質列（`IN_ANALYSIS_AREA` / `LST_VALID_RATIO` 等）の名前はシナリオ間で共通の
ため、特徴量列名だけを引数化すればシナリオ非依存で再利用できる。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

# 分析対象域フラグ。1のセルのみを分析対象とする。
IN_ANALYSIS_AREA_COLUMN = "IN_ANALYSIS_AREA"
# LSTのセル内有効画素率。VALID_SATELLITE_MASKはLSTの被覆率を包含しないため、
# 別途このしきい値でフィルタする（研究上の判断。既定値は呼び出し側が指定する）。
LST_VALID_RATIO_COLUMN = "LST_VALID_RATIO"
# filter_valid_rowsが既定で==1を要求する品質列。Satellite Onlyシナリオではこの
# 1列のみだが、Limited/FullシナリオはVALID_GIS_MASK等の追加の品質軸を持つ
# （`src.analysis.build_dataset.add_quality_columns` 参照）ため、呼び出し側が
# `required_mask_columns` で追加できるようにしている。
DEFAULT_REQUIRED_MASK_COLUMNS: tuple[str, ...] = (IN_ANALYSIS_AREA_COLUMN,)


def valid_population_mask_column(column_suffix: str) -> str:
    """人口ソースの接尾辞から、対応する有効域品質列名を組み立てる。

    人口は複数版（WorldPop・LandScan2020・LandScan2023等）を同一データセットへ
    同時に結合するため、有効域の品質列もソースごとに分ける（1本にまとめると、
    分析側が選んだソースと無関係な別ソースの欠測に有効域が引きずられるため）。

    列名の生成規則を `src.analysis.build_dataset`（品質列を付与する側）と
    `src.analysis.analysis_rq3_limited`（品質列を読む側）の両方で共有するために
    ここへ置く。生成規則を2箇所に文字列として重複定義すると、どちらか一方だけを
    変更した場合に列名が食い違い、片方は新しい列を書き出す一方でもう片方は古い
    列名を要求して停止する。

    Args:
        column_suffix: 列名へ付けるデータソース識別子
            （`src.analysis.urban_params.config.ParamSet.column_suffix`。
            例: ``"WORLDPOP2020"``）。
    Returns:
        対応する有効域品質列名（例: ``"VALID_POP_WORLDPOP2020_MASK"``）。
    """
    return f"VALID_POP_{column_suffix}_MASK"


def load_analysis_dataset(dataset_path: Path, columns: Sequence[str] | None = None) -> pd.DataFrame:
    """分析用データセットGeoPackageを読み込む。

    `src.analysis.build_dataset` が生成するデータセットは `cell_id` をキーとする
    属性のみのテーブル（ジオメトリを持たない）であり、座標は `lon` / `lat` 列
    として保持される。

    Args:
        dataset_path: `src.analysis.build_dataset` が生成したGeoPackageのパス。
        columns: 読み込む列名。`None`（既定）の場合は全列を読み込む。後段の
            `filter_valid_rows` / `sample_dataset` で実際に使う列だけを指定すると、
            使わない列（他シナリオ用の品質列等）の読込コストを避けられる。
    Returns:
        `cell_id` / `lon` / `lat` / 特徴量 / 品質列を含むDataFrame。
    """
    return pd.DataFrame(gpd.read_file(dataset_path, columns=columns))


def _build_filter_masks(
    dataframe: pd.DataFrame,
    feature_columns: Sequence[str],
    target_column: str,
    lst_valid_ratio_threshold: float,
    required_mask_columns: Sequence[str],
) -> dict[str, pd.Series]:
    """フィルタ条件を段階別の累積ブールマスクとして組み立てる。

    `filter_valid_rows` と `summarize_filter_dropout` の両方がこのヘルパーを
    経由することで、フィルタ条件を二重定義しない（条件を変更する際にこの関数
    だけを直せば両方に反映される）。3段階はいずれも累積（前段階を含む）の
    ANDであり、AND結合は結合順によらないため、最終段階（`feature_complete`）は
    旧実装が一括で組んでいたマスクとビット単位で一致する。

    Args:
        dataframe: フィルタ対象のデータフレーム。
        feature_columns: 非NULLを要求する説明変数の列名リスト。
        target_column: 非NULLを要求する目的変数の列名。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限（この値以上を残す）。
        required_mask_columns: `== 1` を要求する品質列名。
        `required_mask_columns` に pandas の nullable 拡張dtype（`Int64` 等）で
        実際に欠損（`pd.NA`）を含む列を渡すと、`==` の結果が nullable boolean
        dtype（`pd.NA` を含みうる）になる。`.loc[]` によるブール添字はこの
        `pd.NA` を「行を残さない」側として扱うため、最終的な行選択結果は
        欠損を通常の `False` として扱った場合と変わらない。一方で `pd.NA` を
        含んだままの Series は `.sum()` の対象に含まれない・`.to_numpy()` が
        `object` dtype配列に化けて後段のNumPyインデックス参照が壊れる等、
        呼び出し側で扱いにくいため、`fillna(False)` で明示的に確定させてから
        返す（行選択の結果自体は変えない、内部表現の正規化）。
    Returns:
        `dataframe.index` に揃った、`pd.NA` を含まない純粋なブールSeriesを
        3段階分持つ辞書。
        `"mask_passed"`: `required_mask_columns` のみを課した段階。
        `"target_available"`: `mask_passed` に加え `target_column` の非NULLと
        `LST_VALID_RATIO` のしきい値を課した段階。
        `"feature_complete"`: `target_available` に加え `feature_columns` 全ての
        非NULLを課した段階（`filter_valid_rows` の最終結果と同じ）。
    """
    mask_passed = pd.Series(True, index=dataframe.index)
    for column in required_mask_columns:
        mask_passed &= dataframe[column] == 1

    target_available = mask_passed & dataframe[target_column].notna()
    target_available &= dataframe[LST_VALID_RATIO_COLUMN] >= lst_valid_ratio_threshold

    feature_complete = target_available.copy()
    for column in feature_columns:
        feature_complete &= dataframe[column].notna()

    return {
        "mask_passed": mask_passed.fillna(False),
        "target_available": target_available.fillna(False),
        "feature_complete": feature_complete.fillna(False),
    }


def filter_valid_rows(
    dataframe: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    lst_valid_ratio_threshold: float,
    required_mask_columns: Sequence[str] = DEFAULT_REQUIRED_MASK_COLUMNS,
) -> pd.DataFrame:
    """品質列に基づき、分析に使う有効な行だけを残す。

    以下をすべて満たす行を残す。

    - `required_mask_columns`（既定は `IN_ANALYSIS_AREA` のみ）がすべて `== 1`
    - `feature_columns` と `target_column` がすべて非NULL
    - `LST_VALID_RATIO >= lst_valid_ratio_threshold`

    `VALID_SATELLITE_MASK` は独立の条件として課さない。この列は
    「NDVI / NDBI / NDWI のいずれかが非NULL」というORで定義されており、
    `feature_columns` 全ての非NULLを要求する時点で包含されるため。

    Args:
        dataframe: 分析用データセット（`load_analysis_dataset` の戻り値相当）。
        feature_columns: 非NULLを要求する説明変数の列名リスト。
        target_column: 非NULLを要求する目的変数の列名（通常 `"LST"`）。
        lst_valid_ratio_threshold: `LST_VALID_RATIO` の下限（この値以上を残す）。
        required_mask_columns: `== 1` を要求する品質列名（既定は `IN_ANALYSIS_AREA`
            のみ）。Limited/Fullシナリオで `VALID_GIS_MASK` 等の追加の品質軸を
            課したい場合に、この共通モジュールを変更せず呼び出し側から渡せる。
    Returns:
        フィルタ後のデータフレーム（インデックスは0始まりに振り直し済み）。
    """
    masks = _build_filter_masks(
        dataframe, feature_columns, target_column, lst_valid_ratio_threshold, required_mask_columns
    )
    return dataframe.loc[masks["feature_complete"]].reset_index(drop=True)


def _none_if_nan(value: float) -> float | None:
    """非有限値（NaN・Inf）をJSON書き出し可能な `None` に変換する。

    該当セルが0件の場合、平均・分位点はNaNになる。`src.common.summary.save_summary`
    は `allow_nan=False` でありInf・NaNを例外にするため、`sanitize_vif_for_json`
    （`src.common.model_metrics`）と同じ方針で `None` に落とす。`None` は
    「該当セルが無い」ことを表す。

    Args:
        value: 検査する値。
    Returns:
        有限なら `float`、非有限（またはNone）なら `None`。
    """
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _distribution_stats(values: pd.Series) -> dict[str, float | int | None]:
    """1変数の分布統計（件数・平均・標準偏差・分位点）を求める。

    Args:
        values: 対象の数値Series。
    Returns:
        `count` / `mean` / `std` / `min` / `p1` / `p25` / `p50` / `p75` / `p99`
        / `max` を持つ辞書。`count` が0の場合、`count` 以外は `None`。
    """
    count = int(values.count())
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "p1": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p99": None,
            "max": None,
        }
    # min/max/分位点もmean/stdと同じく_none_if_nanを通す。対象列にInf（NaNでは
    # ない）が1件でも混入しているとcountはそれを含めて数えるため、素の
    # float()だけではInfがそのまま残り、save_summary（allow_nan=False）で
    # 例外になりうる。
    quantiles = values.quantile([0.01, 0.25, 0.5, 0.75, 0.99])
    return {
        "count": count,
        "mean": _none_if_nan(values.mean()),
        "std": _none_if_nan(values.std()),
        "min": _none_if_nan(values.min()),
        "p1": _none_if_nan(quantiles.loc[0.01]),
        "p25": _none_if_nan(quantiles.loc[0.25]),
        "p50": _none_if_nan(quantiles.loc[0.5]),
        "p75": _none_if_nan(quantiles.loc[0.75]),
        "p99": _none_if_nan(quantiles.loc[0.99]),
        "max": _none_if_nan(values.max()),
    }


def _block_dropout_stats(dropped_ratio: pd.Series) -> dict[str, float | None]:
    """ブロック別脱落率の分布統計（中央値・p90・p99・最大値）を求める。

    Args:
        dropped_ratio: ブロックごとの脱落率（0〜1）のSeries。
    Returns:
        `median` / `p90` / `p99` / `max` を持つ辞書。`dropped_ratio` が空の場合、
        すべて `None`。
    """
    if dropped_ratio.empty:
        return {"median": None, "p90": None, "p99": None, "max": None}
    quantiles = dropped_ratio.quantile([0.5, 0.9, 0.99])
    return {
        "median": _none_if_nan(quantiles.loc[0.5]),
        "p90": _none_if_nan(quantiles.loc[0.9]),
        "p99": _none_if_nan(quantiles.loc[0.99]),
        "max": _none_if_nan(dropped_ratio.max()),
    }


def summarize_filter_dropout(
    dataframe: pd.DataFrame,
    feature_columns: Sequence[str],
    target_column: str,
    lst_valid_ratio_threshold: float,
    summary_columns: Sequence[str],
    column_groups: dict[str, list[str]],
    block_id: np.ndarray,
    block_size_m: int,
    sampled_row_count: int,
    required_mask_columns: Sequence[str] = DEFAULT_REQUIRED_MASK_COLUMNS,
) -> dict[str, object]:
    """`filter_valid_rows` による脱落の内訳を診断として集計する。

    フィルタ条件は `_build_filter_masks`（`filter_valid_rows` と共通）で組み立てる
    ため、この関数が返す `feature_complete` 段階の母数は常に `filter_valid_rows`
    の出力行数と一致する（条件の二重定義を避けるための設計判断であり、
    フィルタ条件を変更してもこの関数を個別に直す必要はない）。

    脱落集計の基準段階は `target_available`（品質マスク・目的変数・LST有効率の
    条件を通過した段階）とする。ROI全体を分母にすると、LSTの雲マスク由来の
    脱落が説明変数側の脱落を覆い隠して読めなくなるため。

    `feature_columns` と `summary_columns` は役割が異なる。`feature_columns` は
    マスク構築（`_build_filter_masks`）に使い、`filter_valid_rows` と同様に
    列が存在しない場合は例外になる。`summary_columns` は列ごとの内訳集計にのみ
    使い、存在しない列は例外にせず読み飛ばして `missing_summary_columns` に
    記録する（シナリオ間でデータセットの列構成が異なりうるための緩和であり、
    `feature_columns` 自体の欠落は呼び出し側の既存の検証で先に例外になるため、
    この緩和で診断が実態とずれることはない）。

    **`columns.exclusive_null_count`（列単位の排他判定）は `summary_columns` の
    範囲内でのみ排他性を判定する。** `feature_columns` に `summary_columns` に
    含まれない列がある場合、その列だけがNULLの行は「他の集計対象列はどれも
    NULLでない」行として扱われ、`exclusive_null_count` が実態（`feature_columns`
    全体を基準にした排他性）より多く出うる。呼び出し側（Limited・Satellite
    Only）はいずれも `feature_columns` と同じ列を `summary_columns` に渡している
    ため現状は一致するが、両者が食い違う呼び出しでは値がずれる。

    Args:
        dataframe: 診断対象のデータフレーム（`filter_valid_rows` に渡す
            `dataframe` と同じものを想定。Limitedでは建物高さ補完後のフレーム）。
        feature_columns: `filter_valid_rows` に渡すものと同じ、非NULLを要求する
            説明変数の列名リスト。
        target_column: `filter_valid_rows` に渡すものと同じ、目的変数の列名。
        lst_valid_ratio_threshold: `filter_valid_rows` に渡すものと同じしきい値。
        summary_columns: 列ごとの脱落内訳（`columns`）を集計する対象の列名。
            通常は `feature_columns` と同じ列を渡す。
        column_groups: 要因グループ名をキー、そのグループに属する列名リストを
            値とする辞書（例: `{"population": ["POP_DEN_WORLDPOP2020"]}`）。
            `summary_columns` とグループに属する列の集合は完全に一致している
            必要がある（`summary_columns` にあるのに `column_groups` のどこにも
            属さない列、および `column_groups` にあるのに `summary_columns` に
            無い列は、いずれも `ValueError`）。
        block_id: 正準グリッドの空間ブロックID配列。`dataframe` と**位置対応**
            （同じ長さ・同じ並び）している必要がある。
        block_size_m: ブロックの一辺の長さ（m）。集計には使わず、出力への
            記録のみに使う。
        sampled_row_count: サンプリング後の行数（`stages.sampled` に記録する。
            この関数自身はサンプリングを行わない）。
        required_mask_columns: `filter_valid_rows` に渡すものと同じ、`== 1` を
            要求する品質列名。既定は `DEFAULT_REQUIRED_MASK_COLUMNS`。
    Returns:
        `filter_dropout` の中身に相当する辞書（キー: `stages` / `base_stage` /
        `dropped_count` / `dropped_ratio` / `columns` / `column_groups` /
        `dropped_summary` / `missing_summary_columns` / `target_distribution` /
        `spatial_blocks` / `note`）。件数系はすべて `int`、非有限値は `None` に
        変換済みで、そのまま `save_summary` へ渡せる。
    Raises:
        ValueError: `block_id` の長さが `dataframe` の行数と一致しない場合、
            または `summary_columns` と `column_groups` の列集合が一致しない
            場合（どちらか一方にしか無い列がある場合）。
    """
    if len(block_id) != len(dataframe):
        raise ValueError(
            "block_idの長さがdataframeの行数と一致しません"
            f"（block_id={len(block_id)}, dataframe={len(dataframe)}）。"
            "block_idはdataframeと位置対応する全行分の配列である必要があります。"
        )

    # column_groupsとsummary_columnsの列集合は双方向で一致させる。片方向のみの
    # 検証（summary_columns→column_groups）だと、column_groups側にだけ列を
    # 足し忘れた場合は例外になり気付けるが、逆にsummary_columns側にだけ列を
    # 足し忘れた場合（column_groupsには入れたがsummary_columnsに入れ忘れた）は
    # その列がpresent_summary_columnsに含まれず、missing_summary_columnsにも
    # 記録されないまま集計から静かに抜け落ち、グループ単位の脱落数が過小に出る。
    grouped_columns = {column for columns in column_groups.values() for column in columns}
    summary_columns_set = set(summary_columns)
    ungrouped_columns = [column for column in summary_columns if column not in grouped_columns]
    if ungrouped_columns:
        raise ValueError(
            f"次の要約対象列がcolumn_groupsのいずれにも属していません: {ungrouped_columns}。"
            "全ての要約対象列をいずれかのグループへ割り当ててください。"
        )
    extra_grouped_columns = sorted(grouped_columns - summary_columns_set)
    if extra_grouped_columns:
        raise ValueError(
            f"次の列がcolumn_groupsに含まれていますが、summary_columnsにありません: "
            f"{extra_grouped_columns}。summary_columnsとcolumn_groupsの列集合を"
            "一致させてください。"
        )

    masks = _build_filter_masks(
        dataframe, feature_columns, target_column, lst_valid_ratio_threshold, required_mask_columns
    )
    mask_passed = masks["mask_passed"]
    target_available = masks["target_available"]
    feature_complete = masks["feature_complete"]
    dropped_mask = target_available & ~feature_complete

    stages = {
        "dataset_row_count": int(len(dataframe)),
        "mask_passed": int(mask_passed.sum()),
        "target_available": int(target_available.sum()),
        "feature_complete": int(feature_complete.sum()),
        "sampled": int(sampled_row_count),
    }
    dropped_count = int(dropped_mask.sum())
    dropped_ratio = (
        dropped_count / stages["target_available"] if stages["target_available"] > 0 else None
    )

    present_summary_columns = [c for c in summary_columns if c in dataframe.columns]
    missing_summary_columns = [c for c in summary_columns if c not in dataframe.columns]

    # target_available_frame・dropped_frame・final_frameはいずれも、以降で
    # 実際に読む列（要約対象列＋目的変数）だけへ`.loc`で絞ってから複製する。
    # dataframeの全列（cell_id・lon/lat・品質列・他シナリオ用の列等）をそのまま
    # 複製すると、行数が数百万規模のときに使わない列の複製コストが無駄になる。
    frame_columns = list(dict.fromkeys([*present_summary_columns, target_column]))

    # 列ごとの排他判定は「NULL列数のカウンタ配列」を1本持ち回る形にし、
    # 列ごとのブールマスクを同時に保持しない（メモリ増を抑える設計判断）。
    # null_count_per_rowはpresent_summary_columns（summary_columnsのうち存在する
    # 列）だけを数えるため、exclusive_null_countの排他性もsummary_columnsの範囲に
    # 限られる（docstring参照）。
    target_available_frame = dataframe.loc[target_available, frame_columns]
    is_null = target_available_frame[present_summary_columns].isna()
    null_count_per_row = is_null.sum(axis=1)
    target_values = target_available_frame[target_column]

    columns_summary: dict[str, dict[str, object]] = {}
    for column in present_summary_columns:
        column_null = is_null[column]
        exclusive_null = column_null & (null_count_per_row == 1)
        columns_summary[column] = {
            "null_count": int(column_null.sum()),
            "exclusive_null_count": int(exclusive_null.sum()),
            "target_mean": _none_if_nan(target_values.loc[column_null].mean()),
        }

    column_groups_summary: dict[str, dict[str, object]] = {}
    for group_name, group_columns in column_groups.items():
        present_group_columns = [c for c in group_columns if c in present_summary_columns]
        if present_group_columns:
            group_null_per_row = is_null[present_group_columns].sum(axis=1)
        else:
            group_null_per_row = pd.Series(0, index=is_null.index)
        group_null = group_null_per_row > 0
        outside_null_per_row = null_count_per_row - group_null_per_row
        exclusive_group_null = group_null & (outside_null_per_row == 0)
        column_groups_summary[group_name] = {
            "null_count": int(group_null.sum()),
            "exclusive_null_count": int(exclusive_group_null.sum()),
            "target_mean": _none_if_nan(target_values.loc[group_null].mean()),
        }

    dropped_frame = dataframe.loc[dropped_mask, present_summary_columns]
    final_frame = dataframe.loc[feature_complete, frame_columns]
    dropped_summary: dict[str, dict[str, object]] = {}
    for column in present_summary_columns:
        dropped_summary[column] = {
            "dropped": {
                "mean": _none_if_nan(dropped_frame[column].mean()),
                "non_null_count": int(dropped_frame[column].notna().sum()),
            },
            "final": {
                "mean": _none_if_nan(final_frame[column].mean()),
                "non_null_count": int(final_frame[column].notna().sum()),
            },
        }

    target_distribution = {
        "before": _distribution_stats(target_available_frame[target_column]),
        "after": _distribution_stats(final_frame[target_column]),
    }

    # block_idはdataframeと位置対応する配列のため、Seriesではなくブール配列
    # （.to_numpy()、ラベルではなく行順で揃う）でインデックスする。
    block_id_array = np.asarray(block_id)
    target_available_positions = target_available.to_numpy()
    feature_complete_positions = feature_complete.to_numpy()
    block_frame = pd.DataFrame(
        {
            "block_id": block_id_array[target_available_positions],
            "kept": feature_complete_positions[target_available_positions],
        }
    )
    if block_frame.empty:
        spatial_blocks: dict[str, object] = {
            "n_blocks": 0,
            "block_size_m": int(block_size_m),
            "dropped_ratio": {"median": None, "p90": None, "p99": None, "max": None},
            "blocks_over_50pct": 0,
        }
    else:
        block_stats = block_frame.groupby("block_id")["kept"].agg(["sum", "count"])
        block_dropped_ratio = 1.0 - block_stats["sum"] / block_stats["count"]
        spatial_blocks = {
            "n_blocks": int(len(block_stats)),
            "block_size_m": int(block_size_m),
            "dropped_ratio": _block_dropout_stats(block_dropped_ratio),
            "blocks_over_50pct": int((block_dropped_ratio > 0.5).sum()),
        }

    note = (
        "target_available（基準段階）はmask_passedを通過し、かつ"
        f"{target_column}が非NULL、かつLST_VALID_RATIO>={lst_valid_ratio_threshold}の行。"
        f"mask_passedはrequired_mask_columns（{list(required_mask_columns)}）依存であり、"
        "Limited/Fullシナリオでは--require-valid-gis-maskの有無で中身が変わる。"
        "target_distributionの「前」はtarget_available、「後」はfeature_complete"
        "（sampledではない）の分布。"
        "columns.null_countは重複計上であり、列ごとの和はdropped_countを上回りうる。"
        "spatial_blocks.n_blocksは基準段階の母集団に対する非空ブロック数であり、"
        "spatial_cv.block_definition.n_blocks（分析サンプルに対する値）とは一致しない。"
        "columns.exclusive_null_countは、同時にNULL/非NULLになる列の対では両方とも0になる"
        "（要因としての大きさはcolumn_groups側で読むこと）。"
    )

    return {
        "stages": stages,
        "base_stage": "target_available",
        "dropped_count": dropped_count,
        "dropped_ratio": dropped_ratio,
        "columns": columns_summary,
        "column_groups": column_groups_summary,
        "dropped_summary": dropped_summary,
        "missing_summary_columns": missing_summary_columns,
        "target_distribution": target_distribution,
        "spatial_blocks": spatial_blocks,
        "note": note,
    }


def sample_dataset(
    dataframe: pd.DataFrame,
    sample_size: int,
    random_state: int,
) -> pd.DataFrame:
    """乱数シードを固定してデータセットをサンプリングする。

    支配的な計算コストはpermutation importanceではなくRFの学習そのものであり、
    時間よりメモリが先に問題になる規模のため、サンプリングを用意する。

    Args:
        dataframe: サンプリング対象のデータフレーム（`filter_valid_rows` 適用後を想定）。
        sample_size: 抽出するサンプル数。0を指定すると全件を返す（サンプリングしない）。
        random_state: 乱数シード。
    Returns:
        サンプリング後のデータフレーム（インデックスは0始まりに振り直し済み）。
        `sample_size` が0または `dataframe` の行数以上の場合は全件を返す。
    Raises:
        ValueError: `sample_size` が負の場合。
    """
    if sample_size < 0:
        raise ValueError(f"sample_sizeは0以上である必要があります（sample_size={sample_size}）。")
    if sample_size == 0 or sample_size >= len(dataframe):
        return dataframe.reset_index(drop=True)

    return dataframe.sample(n=sample_size, random_state=random_state).reset_index(drop=True)
