"""正準グリッドに整合したグリッド構築と ``cell_id`` 付きテーブル化を扱うモジュール。

``grid.py`` の ``build_grid()`` はグリッド原点を解析範囲レイヤのBBoxから取るため、
``canonical_grid.py`` が定義する正準グリッド（原点を座標系原点へスナップ）とは格子の
位相がずれる。そのままでは coarse配列の添字を ``cell_id`` へ対応づけられない。

本モジュールは、正準グリッドの ``row`` / ``col`` 範囲から**セル境界にちょうど載る
BBox**（以下「整合BBox」）を組み立て、それを ``build_grid()`` へ渡す。整合BBoxの
幅・高さは解像度の整数倍になるため ``build_grid()`` のパディングが0となり、
``coarse_shape`` が正準グリッドの ``(n_rows, n_cols)`` と厳密に一致する。

配列添字と正準インデックスの対応は次のとおりである。``coarse_transform`` は北から南へ
row が増えるのに対し、正準グリッドの ``row`` は北向きが正であるため反転する。

.. code-block:: text

    canonical_row = row_max - i     （i: coarse配列の行添字）
    canonical_col = col_min + j     （j: coarse配列の列添字）
    cell_id = make_cell_id(canonical_row, canonical_col)

出力するテーブルは ``cell_id`` と当該パラメータの列だけを持つ**属性のみのテーブル**で
あり、``lon`` / ``lat`` は持たせない。座標は正準グリッドのレイヤが保持しており、
全テーブルへ複製するとパラメータ単位で独立させる狙いに反するためである。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

from src.common.geo_metadata import BBox
from src.common.geopackage import remove_geopackage, remove_sidecar_files

from .canonical_grid import CanonicalGridSpec, make_cell_id, split_cell_id
from .grid import GridSpec, build_grid

# パラメータテーブルのキー列。パラメータの列名として使うことはできない。
CELL_ID_COLUMN = "cell_id"


def aligned_bbox(canonical_spec: CanonicalGridSpec) -> BBox:
    """正準グリッドのセル境界にちょうど載るBBoxを返す。

    ``row_min`` / ``row_max`` / ``col_min`` / ``col_max`` はいずれも範囲に**含む**
    インデックスであるため、上端・右端はそれぞれ1セル分だけ外側の境界を採る。

    Args:
        canonical_spec: 正準グリッドの仕様。

    Returns:
        ``canonical_spec.analysis_crs`` 上の整合BBox。
    """
    res_m = canonical_spec.res_m
    return BBox(
        minx=canonical_spec.origin_x + (canonical_spec.col_min * res_m),
        miny=canonical_spec.origin_y + (canonical_spec.row_min * res_m),
        maxx=canonical_spec.origin_x + ((canonical_spec.col_max + 1) * res_m),
        maxy=canonical_spec.origin_y + ((canonical_spec.row_max + 1) * res_m),
    )


def build_aligned_grid(canonical_spec: CanonicalGridSpec, fine_res_m: float) -> GridSpec:
    """正準グリッドと格子が一致する ``GridSpec`` を構築する。

    ``params/*.py`` の ``compute()`` は ``GridSpec`` を受け取るため、正準グリッドへ
    出力を載せ替えるにあたって変更が必要なのは**渡す ``GridSpec`` の作り方だけ**で
    ある。整合BBoxを ``build_grid()`` へ渡すことでこれを満たす。

    形状の一致は**実行時に検証する**。正準グリッドGeoPackageが別の解析範囲・別の
    マスクで再生成された場合や、丸め誤差でパディングが生じた場合に、例外を出さずに
    対応のずれたテーブルを作ってしまうのを防ぐためである。

    Args:
        canonical_spec: 正準グリッドの仕様。
        fine_res_m: 被覆率計算用の補助解像度（m）。``canonical_spec.res_m`` の
            約数である必要がある（判定は ``build_grid()`` が行う）。

    Returns:
        ``coarse_shape`` が ``(n_rows, n_cols)`` と一致する ``GridSpec``。

    Raises:
        ValueError: ``build_grid()`` が解像度・BBoxを受け付けない場合、または
            構築した ``coarse_shape`` が正準グリッドの形状と一致しない場合。
    """
    grid_spec = build_grid(
        aligned_bbox(canonical_spec),
        canonical_spec.analysis_crs,
        canonical_spec.res_m,
        fine_res_m,
    )

    expected_shape = (canonical_spec.n_rows, canonical_spec.n_cols)
    if grid_spec.coarse_shape != expected_shape:
        raise ValueError(
            "構築したグリッドが正準グリッドと一致しません"
            f"（coarse_shape={grid_spec.coarse_shape} / 正準={expected_shape}）。"
            " 解析範囲・解像度・補助解像度の組合せを確認してください。"
        )
    return grid_spec


def cell_id_array(canonical_spec: CanonicalGridSpec) -> np.ndarray:
    """coarse配列の添字順に並んだ ``cell_id`` の2次元配列を返す。

    先頭行（添字0）が最も北の行（``row_max``）に対応する。ラスタの慣習に合わせた
    並びであり、正準グリッドの北向き ``row`` とは向きが逆である点に注意する。

    Args:
        canonical_spec: 正準グリッドの仕様。

    Returns:
        形状 ``(n_rows, n_cols)`` の ``int64`` 配列。
    """
    row_indices = canonical_spec.row_max - np.arange(canonical_spec.n_rows, dtype=np.int64)
    col_indices = canonical_spec.col_min + np.arange(canonical_spec.n_cols, dtype=np.int64)
    col_grid, row_grid = np.meshgrid(col_indices, row_indices)
    return np.asarray(make_cell_id(row_grid, col_grid))


def read_grid_cell_ids(grid_path: Path, layer_name: str) -> np.ndarray:
    """正準グリッドGeoPackageのレイヤから ``cell_id`` 列だけを読み出す。

    ジオメトリと他の属性を読まないため、30mスケール（約374万セル）でも数秒で
    済む。パラメータテーブルの行集合はこの ``cell_id`` を正本とし、マスク交差判定を
    再計算しない。判定ロジックが二重化すると、両者がずれたときに結合が静かに壊れる
    ためである。

    Args:
        grid_path: 正準グリッドGeoPackageのパス。
        layer_name: 読み出すレイヤ名（例: ``grid_30m``）。

    Returns:
        レイヤの格納順に並んだ ``cell_id`` の1次元 ``int64`` 配列。

    Raises:
        FileNotFoundError: ``grid_path`` が存在しない場合。
        ValueError: ``layer_name`` がGeoPackageに存在しない場合、または対象レイヤが
            ``cell_id`` 列を持たない場合。
    """
    if not grid_path.exists():
        raise FileNotFoundError(f"正準グリッドGeoPackageが見つかりません: {grid_path}")

    available_layers = [str(name) for name in pyogrio.list_layers(grid_path)[:, 0]]
    if layer_name not in available_layers:
        raise ValueError(
            f"正準グリッドにレイヤがありません: {layer_name}"
            f"（候補: {', '.join(available_layers)} / パス: {grid_path}）"
        )

    # 列の存在を先に確かめる。pyogrio は存在しない列を指定しても例外を出さず、
    # 列も行も持たない空のデータフレームを返すため、そのまま読むと原因の分からない
    # KeyError になる。
    available_fields = [
        str(name) for name in pyogrio.read_info(grid_path, layer=layer_name)["fields"]
    ]
    if CELL_ID_COLUMN not in available_fields:
        raise ValueError(
            f"レイヤに {CELL_ID_COLUMN} 列がありません: {layer_name}"
            f"（列: {', '.join(available_fields)} / パス: {grid_path}）"
        )

    frame = pyogrio.read_dataframe(
        grid_path, layer=layer_name, columns=[CELL_ID_COLUMN], read_geometry=False
    )
    return frame[CELL_ID_COLUMN].to_numpy(dtype=np.int64)


def build_param_table(
    columns: dict[str, np.ndarray],
    canonical_spec: CanonicalGridSpec,
    cell_ids: np.ndarray,
) -> pd.DataFrame:
    """coarse配列群を ``cell_id`` キーのテーブルへ変換する。

    出力する行は ``cell_ids`` が指すセルのみで、順序も ``cell_ids`` の並びに従う。
    正準グリッドのレイヤと1:1で結合できる状態にするためである。

    Args:
        columns: 列名から ``canonical_spec`` の形状と一致する2次元配列への辞書。
        canonical_spec: 正準グリッドの仕様。
        cell_ids: 出力対象の ``cell_id``（1次元・整数）。

    Returns:
        先頭列を ``cell_id`` とし、以降に ``columns`` の各列を持つデータフレーム。

    Raises:
        ValueError: ``columns`` が空の場合、``columns`` がキー列と同名の列を含む
            場合、配列の形状が正準グリッドと一致しない場合、``cell_ids`` が1次元で
            ない場合・空の場合・重複を含む場合、または ``cell_ids`` に正準グリッドの
            範囲外の値が含まれる場合。
    """
    if not columns:
        raise ValueError("出力する列がありません。columns には1つ以上の列を指定してください。")
    # キー列と同名のパラメータ列を許すと、後段の代入でキーが値に置き換わり、
    # 結合先が黙ってずれる。列名の衝突として明示的に弾く。
    if CELL_ID_COLUMN in columns:
        raise ValueError(
            f"列名 {CELL_ID_COLUMN} はキー列として予約されています。"
            " パラメータの列名を変更してください。"
        )

    expected_shape = (canonical_spec.n_rows, canonical_spec.n_cols)
    for column_name, values in columns.items():
        if values.shape != expected_shape:
            raise ValueError(
                f"列の形状が正準グリッドと一致しません: {column_name}"
                f"（shape={values.shape} / 正準={expected_shape}）"
            )

    cell_id_values = np.asarray(cell_ids)
    if cell_id_values.ndim != 1:
        raise ValueError(f"cell_ids は1次元配列で指定してください（ndim={cell_id_values.ndim}）。")
    if cell_id_values.size == 0:
        raise ValueError(
            "cell_ids が空です。正準グリッドのレイヤと解析範囲の対応を確認してください。"
        )
    # 重複があると結合先の行が増え、値の誤りではなく行数の誤りとして現れる。
    # 検知が遅れると原因の特定が難しいため、テーブル化の時点で弾く。
    if np.unique(cell_id_values).size != cell_id_values.size:
        raise ValueError("cell_ids に重複があります。正準グリッドのレイヤを確認してください。")

    rows, cols = split_cell_id(cell_id_values)
    row_offsets = canonical_spec.row_max - np.asarray(rows)
    col_offsets = np.asarray(cols) - canonical_spec.col_min

    out_of_range = (
        (row_offsets < 0)
        | (row_offsets >= canonical_spec.n_rows)
        | (col_offsets < 0)
        | (col_offsets >= canonical_spec.n_cols)
    )
    if bool(out_of_range.any()):
        invalid_count = int(out_of_range.sum())
        sample = cell_id_values[out_of_range][:5].tolist()
        raise ValueError(
            f"正準グリッドの範囲外を指す cell_id があります（{invalid_count} 件 /"
            f" 全 {cell_id_values.size} 件・例: {sample}）。"
            " グリッドGeoPackageと解析範囲・スケールの対応を確認してください。"
        )

    flat_indices = (row_offsets * canonical_spec.n_cols) + col_offsets
    table_data: dict[str, np.ndarray] = {CELL_ID_COLUMN: cell_id_values.astype(np.int64)}
    for column_name, values in columns.items():
        table_data[column_name] = values.ravel()[flat_indices]
    return pd.DataFrame(table_data)


def write_param_table(table: pd.DataFrame, output_path: Path, layer_name: str) -> None:
    """パラメータテーブルを属性のみのGeoPackageとして書き出す。

    **追記モードは使わない。** 追記で ``cell_id`` が二重化すると結合が静かに壊れる
    ため、その経路自体を持たせない。書き出しは一時ファイルへ行い、完了後に
    ``Path.replace()`` で差し替える。同一ディレクトリ内の置換はアトミックに動作し、
    途中で失敗しても既存の正しい出力はそのまま残る。

    ``canonical_grid.write_grid_layers()`` と異なり ``overwrite`` を課さないのは、
    「1つのパラメータだけ再計算する」ことが通常運用であり、毎回フラグを要求すると
    パラメータ単位で独立に再計算できるという狙いと逆行するためである。失敗時に
    既存の出力を失わない保護は一時ファイル経由で担保する。

    Args:
        table: 出力するテーブル（``cell_id`` 列を含む）。
        output_path: 出力先のGeoPackageパス。
        layer_name: 書き出すレイヤ名。パラメータセット名と一致させる。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 拡張子は出力先と揃える（ドライバの判定を拡張子に依存させないため）。
    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    remove_geopackage(temp_path)

    try:
        pyogrio.write_dataframe(table, temp_path, layer=layer_name, driver="GPKG")
    except BaseException:
        # 中断（KeyboardInterrupt）も含めて書きかけを残さない。
        remove_geopackage(temp_path)
        raise

    # 置換前に、出力先に残っている古い付随ファイルを消す。本体だけを差し替えると
    # 別のデータベースの -wal / -shm が残った状態になるため。
    remove_sidecar_files(output_path)
    temp_path.replace(output_path)
