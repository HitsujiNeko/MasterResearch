"""分析用データセットGeoPackageの読込・品質列フィルタリング・サンプリングを行う
共通モジュール。

`src.analysis.build_dataset` が `cell_id` 結合で生成したGeoPackageを対象とする。
品質列（`IN_ANALYSIS_AREA` / `LST_VALID_RATIO` 等）の名前はシナリオ間で共通の
ため、特徴量列名だけを引数化すればシナリオ非依存で再利用できる。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import geopandas as gpd
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
    mask = pd.Series(True, index=dataframe.index)
    for column in required_mask_columns:
        mask &= dataframe[column] == 1
    for column in [*feature_columns, target_column]:
        mask &= dataframe[column].notna()
    mask &= dataframe[LST_VALID_RATIO_COLUMN] >= lst_valid_ratio_threshold

    return dataframe.loc[mask].reset_index(drop=True)


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
