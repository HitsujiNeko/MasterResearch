"""パラメータテーブルを ``cell_id`` で結合し、分析用データセットを生成するモジュール。

算出フェーズ（``urban_params``）が出力したパラメータ単位のテーブルから、必要な
ものだけを選んで1つのデータセットへ結合する。シナリオは「どのテーブルを結合するか」
の選択へ還元されているため、感度分析は結合先の差し替えだけで済む。

実行例::

    # シナリオ名で結合対象を展開する
    python -m src.analysis.build_dataset --city hanoi --scale 30 --scenario limited

    # テーブルを直接指定する（別ソース版の比較・衛星指標の追加など）
    python -m src.analysis.build_dataset --city hanoi --scale 30 \\
        --tables build_dc road_gt idx_20230707_032329 --name full_with_indices

    # シナリオと観測ファイル単位のテーブルを併用する（satellite_only はこの形が必須）
    python -m src.analysis.build_dataset --city hanoi --scale 30 \\
        --scenario satellite_only --tables idx_20230707_032329 lst_20230707_032329 \\
        --name satellite_only_20230707_032329

結合の土台は正準グリッドのレイヤ（``cell_id`` / ``lon`` / ``lat``）とする。
あるテーブルにのみ存在しない ``cell_id`` は NULL として残す。

**単一スケールのテーブルのみを結合する。** ``cell_id`` は ``row * 1000000 + col``
で全スケール共通の式のため、**一意なのは同一スケールのレイヤ内に限られる**。
30m の ``(row=7582, col=1765)`` と 300m の同じ添字は同じ ``cell_id`` になるため、
異なるスケールのテーブルを ``cell_id`` だけで結合すると無関係なセルが結び付く。
``--scale`` を単一指定に限り、テーブルも同じスケールのディレクトリからのみ読む。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

from src.analysis.urban_params.canonical_grid import (
    SNAP_UNIT_M,
    is_supported_resolution,
    resolve_output_path,
)
from src.analysis.urban_params.config import (
    CITY_CONFIG,
    DATASETS_OUTPUT_PARTS,
    LST_TABLE_PREFIX,
    PARAM_SETS,
    PROJECT_ROOT,
    SATELLITE_ONLY_SCENARIO,
    SATELLITE_TABLE_PREFIX,
    SCENARIO_TABLES,
    grid_layer_name,
    resolve_table_path,
)
from src.analysis.urban_params.tables import (
    CELL_ID_COLUMN,
    read_grid_frame,
    write_attribute_table,
)

# 正準グリッドから引き継ぐ列。座標はパラメータテーブルではなくグリッドが保持する。
GRID_COLUMNS = (CELL_ID_COLUMN, "lon", "lat")

# ``VALID_GIS_MASK`` の判定材料とするパラメータのモジュール。
#
# 標高（``elevation``）は除く。判定は「値が0より大きいセルを有効」とみなすが、これは
# 被覆率・密度のような「地物の量」を前提とした基準である。標高は連続量であり0mは
# 「データが無い」ではなく海抜0mを意味するため、この基準を適用すること自体が不適切で
# ある。加えて、標高を含めるとROI内のほぼ全セルが有効となり、``VALID_GIS_MASK`` が
# 「建物・道路データが存在するか」という本来の意味を失う。
#
# 解析対象域フラグ（``mask``）も除く。有効域の定義であって地物の量ではない。
GIS_INDICATOR_MODULES = frozenset({"buildings", "roads"})

VALID_GIS_MASK_COLUMN = "VALID_GIS_MASK"
MISSING_REASON_COLUMN = "MISSING_REASON"
VALID_SATELLITE_MASK_COLUMN = "VALID_SATELLITE_MASK"

# ``MISSING_REASON`` が取る値。
#
# ``no_gis_feature`` と ``missing_gis_data`` を分けるのは、両者が意味も対処も異なる
# ためである。前者は「データを見たうえで地物が無かった」という**観測結果**であり、
# 分析上は0として扱ってよい。後者は「そのセルの値がそもそも得られていない」という
# **データ側の欠落**であり、結合したテーブルの世代違いや算出範囲の不足を疑うべき
# 状態である。両者を同じ値にまとめると、テーブルの取り違えが「地物が無い地域」に
# 化けて分析へ流れ込む。
MISSING_REASON_NONE = "none"
MISSING_REASON_NO_GIS_FEATURE = "no_gis_feature"
MISSING_REASON_MISSING_GIS_DATA = "missing_gis_data"

# 観測ファイル単位のテーブル名（``idx_`` / ``lst_``）から観測日時を取り出すパターン。
# 接頭辞は config.py の定数から組み立て、命名規則を二重に持たない。
OBSERVATION_TABLE_PATTERN = re.compile(
    rf"^(?:{re.escape(SATELLITE_TABLE_PREFIX)}|{re.escape(LST_TABLE_PREFIX)})"
    r"(?P<observation>\d{8}_\d{6})$"
)


def observation_key(table_name: str) -> str | None:
    """観測ファイル単位のテーブル名から観測日時キーを取り出す。

    Args:
        table_name: テーブル名。

    Returns:
        ``{YYYYMMDD}_{HHMMSS}`` 形式の観測日時キー。観測ファイル単位のテーブルで
        ない場合（``build_gba`` 等のパラメータセット）は ``None``。
    """
    matched = OBSERVATION_TABLE_PATTERN.match(table_name)
    return matched.group("observation") if matched is not None else None


def validate_observation_consistency(table_names: list[str]) -> None:
    """観測ファイル単位のテーブルが単一の観測に揃っているかを検証する。

    **LSTと衛星指標は同一観測でなければ対応づかない。** 目的変数（``LST``）と説明変数
    （``NDVI`` / ``NDBI`` / ``NDWI``）が別の日時の観測から来ていると、両者の関係を
    見るという分析の前提そのものが崩れる。それでいて結合自体は ``cell_id`` で成立し、
    行数も欠損も正常に見えるため、**出力を見ても気づけない**。テーブル名が観測日時を
    保持しているうちに、結合の入口で止める。

    Args:
        table_names: 結合するテーブル名の一覧。

    Raises:
        ValueError: 観測日時の異なる観測テーブルが混在する場合。
    """
    observations: dict[str, list[str]] = {}
    for table_name in table_names:
        key = observation_key(table_name)
        if key is None:
            continue
        observations.setdefault(key, []).append(table_name)

    if len(observations) <= 1:
        return

    detail = " / ".join(f"{key}: {', '.join(names)}" for key, names in sorted(observations.items()))
    raise ValueError(
        f"観測日時の異なるテーブルを同時に結合できません（{detail}）。"
        " LSTと衛星指標は同一観測でなければ対応づかず、結合自体は成立してしまうため"
        " 出力からは判別できません。同じ観測日時のテーブルだけを指定してください。"
    )


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI引数を解釈して返す。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。

    Returns:
        解釈済みの引数。``--tables`` は重複を除いた一覧に正規化する。
    """
    parser = argparse.ArgumentParser(
        description="パラメータテーブルを cell_id で結合し分析用データセットを生成する"
    )
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument(
        "--scale",
        type=int,
        required=True,
        help="結合対象のcoarseグリッド解像度（m）。cell_id はスケール内でのみ一意のため、"
        " 単一のスケールしか指定できない。",
    )
    parser.add_argument(
        "--scenario",
        default="",
        choices=["", *SCENARIO_TABLES.keys()],
        help="結合するテーブルをシナリオ名で指定する（SCENARIO_TABLES を展開する）。",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        default=[],
        help="結合するテーブル名を直接指定する。観測ファイル単位のテーブル"
        f"（衛星指標は{SATELLITE_TABLE_PREFIX}、LSTは{LST_TABLE_PREFIX}で始まる名前）も"
        " ここで指定する。両者を併せて指定する場合は同一観測日時である必要がある。",
    )
    parser.add_argument(
        "--name",
        default="",
        help="データセット名。出力ファイル名・レイヤ名に使う。"
        " --scenario 指定時の既定はシナリオ名。--tables 指定時は必須。",
    )
    parser.add_argument(
        "--params-dir",
        default="",
        help="パラメータテーブルの格納ルート。既定は data/output/params。",
    )
    parser.add_argument(
        "--grid",
        default="",
        help="正準グリッドGeoPackageのパス。既定は data/output/grid/grid_{city}.gpkg。",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="出力ルート。既定は data/output/datasets。",
    )

    args = parser.parse_args(argv)
    if args.scale <= 0:
        parser.error("--scale には正の整数を指定してください。")
    if not is_supported_resolution(float(args.scale)):
        parser.error(
            f"--scale には {SNAP_UNIT_M:.0f}m の約数を指定してください（指定値: {args.scale}）。"
        )
    if not args.scenario and not args.tables:
        parser.error("--scenario と --tables の少なくとも一方を指定してください。")
    # satellite_only は衛星由来指標（idx_*）を含まなければ「衛星のみ」の意味を成さない。
    # 衛星指標は観測ファイル単位のため SCENARIO_TABLES に列挙できず、シナリオ名だけの
    # 指定では mask_roi だけのデータセットになる。--tables に idx_* を伴う場合のみ許可する
    # （lst_* の有無は解禁条件にしない。LSTは目的変数であり、lst_* だけを許すと目的変数
    # しか持たないデータセットが「衛星のみ」を名乗ることになるため）。
    if args.scenario == SATELLITE_ONLY_SCENARIO:
        has_satellite_table = any(table.startswith(SATELLITE_TABLE_PREFIX) for table in args.tables)
        if not has_satellite_table:
            parser.error(
                f"--scenario {SATELLITE_ONLY_SCENARIO} は --tables に"
                f" {SATELLITE_TABLE_PREFIX}{{YYYYMMDD}}_{{HHMMSS}} 形式の衛星指標テーブルを"
                "伴う場合のみ使えます。衛星指標は観測ファイル単位のテーブルであり、"
                "シナリオ名だけでは mask_roi だけのデータセットになるため、"
                f" --scenario {SATELLITE_ONLY_SCENARIO} --tables {SATELLITE_TABLE_PREFIX}"
                "{YYYYMMDD}_{HHMMSS}"
                " --name ... のように併用してください。"
            )
    if args.tables and not args.name:
        parser.error("--tables を使う場合は --name でデータセット名を指定してください。")

    args.tables = list(dict.fromkeys(args.tables))
    return args


def resolve_table_names(scenario: str, tables: list[str]) -> list[str]:
    """結合するテーブル名の一覧を決める。

    ``--scenario`` と ``--tables`` は併用できるため、シナリオ展開分（先）と
    直接指定分（後）を連結する。両方に同じテーブル名が含まれる場合は重複を除く。

    Args:
        scenario: シナリオ名（未指定の場合は空文字）。
        tables: 直接指定されたテーブル名の一覧。

    Returns:
        結合するテーブル名の一覧（シナリオ展開分が先、順序保持・重複除去済み）。
    """
    scenario_tables = list(SCENARIO_TABLES[scenario]) if scenario else []
    return list(dict.fromkeys(scenario_tables + tables))


def resolve_dataset_name(scenario: str, name: str) -> str:
    """データセット名を決める。

    Args:
        scenario: シナリオ名（未指定の場合は空文字）。
        name: ``--name`` の値。

    Returns:
        データセット名。``--name`` があればそれを、無ければシナリオ名を使う。
    """
    return name or scenario


def resolve_dataset_path(
    dataset_name: str,
    city: str,
    scale: int,
    base_dir: Path | None = None,
) -> Path:
    """分析用データセットの出力先パスを決める。

    Args:
        dataset_name: データセット名。
        city: 都市ID。
        scale: coarseグリッド解像度（m）。
        base_dir: 出力ルート。``None`` の場合は ``data/output/datasets`` を使う。

    Returns:
        ``{base_dir}/dataset_{name}_{city}_{scale}m.gpkg`` の絶対パス。
    """
    root = base_dir if base_dir is not None else PROJECT_ROOT.joinpath(*DATASETS_OUTPUT_PARTS)
    return root / f"dataset_{dataset_name}_{city}_{scale}m.gpkg"


def load_param_table(
    table_name: str,
    city: str,
    scale: int,
    params_dir: Path | None,
) -> pd.DataFrame:
    """パラメータテーブルを読み込む。

    Args:
        table_name: テーブル名。ファイル名・レイヤ名の双方に使う。
        city: 都市ID。
        scale: coarseグリッド解像度（m）。
        params_dir: パラメータテーブルの格納ルート。

    Returns:
        ``cell_id`` を含むテーブル。

    Raises:
        FileNotFoundError: テーブルが存在しない場合。
        ValueError: テーブルが ``cell_id`` 列を持たない場合、または ``cell_id`` に
            重複がある場合。
    """
    table_path = resolve_table_path(city, scale, table_name, params_dir)
    if not table_path.exists():
        raise FileNotFoundError(
            f"パラメータテーブルが見つかりません: {table_path}。"
            " 先に python -m src.analysis.urban_params で算出してください。"
        )

    table = pyogrio.read_dataframe(table_path, layer=table_name, read_geometry=False)
    if CELL_ID_COLUMN not in table.columns:
        raise ValueError(f"テーブルに {CELL_ID_COLUMN} 列がありません: {table_path}")
    # 重複があると結合で行が増える。値の誤りではなく行数の誤りとして現れ、
    # 気づくのが遅れるため、読み込みの時点で弾く。
    if table[CELL_ID_COLUMN].duplicated().any():
        raise ValueError(f"テーブルの {CELL_ID_COLUMN} に重複があります: {table_path}")
    return table


def join_tables(base: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """土台のフレームへ各テーブルを ``cell_id`` で左結合する。

    左結合とするのは、正準グリッドのセルを1行も落とさないためである。あるテーブル
    にのみ存在しない ``cell_id`` の値は NULL として残る。

    Args:
        base: 土台のフレーム（``cell_id`` を含む）。
        tables: テーブル名からデータフレームへの辞書。

    Returns:
        結合済みのデータフレーム。

    Raises:
        ValueError: 複数のテーブルが同じ列名を持つ場合、または土台の列と衝突する
            場合。前者は同じ列名の別ソース版（``build_gba`` と ``build_dc`` など）
            を同時に結合しようとした場合に起きる。どちらを使うかは分析者が選ぶべき
            であり、接尾辞を付けて黙って両方残すと、どちらがどのソースか分からなく
            なる。
    """
    joined = base
    # 土台の列（``lon`` / ``lat``）も衝突検査の対象に含める。含めないと、テーブルが
    # 同名の列を持った場合に pandas が ``lon_x`` / ``lon_y`` へ暗黙にリネームし、
    # 例外も警告も出ないまま座標列が二重化する。``cell_id`` は結合キーなので除く。
    column_owners: dict[str, str] = {
        name: "正準グリッド" for name in base.columns if name != CELL_ID_COLUMN
    }

    for table_name, table in tables.items():
        value_columns = [name for name in table.columns if name != CELL_ID_COLUMN]
        conflicts = [name for name in value_columns if name in column_owners]
        if conflicts:
            owners = ", ".join(f"{name}（{column_owners[name]}）" for name in conflicts)
            raise ValueError(
                f"{table_name} の列が既に結合済みの列と衝突します: {owners}。"
                " 同じ列名を持つ別ソースのテーブルは、どちらか一方を選んで結合してください。"
            )
        column_owners.update({name: table_name for name in value_columns})
        joined = joined.merge(table, on=CELL_ID_COLUMN, how="left")

    return joined


def report_match_counts(base: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> None:
    """各テーブルの行数と、土台と ``cell_id`` が一致した件数を報告する。

    **古い解析範囲で算出した stale なテーブルを結合しても例外にはならず、該当列が
    広範囲に NULL になるだけである。** 行数だけを見ていると原因がテーブルの世代違い
    だと気づきにくいため、突合件数を明示する。

    報告する件数は2種類ある。``一致`` はテーブル側の行のうち土台にも存在するもの
    （テーブルが土台より広い場合に減る）、``値が付く`` は土台側の行のうちテーブルに
    値があるもの（**左結合で NULL になる行数の裏返し**）である。**部分的に stale な
    テーブルは全件一致でも0件一致でもないため、一致0件だけを見ていると見逃す。**
    後段の ``add_quality_columns()`` は NULL を ``missing_gis_data`` として区別する
    が、それは結果側の表示であり、原因がテーブルの世代違いであることは示さない。

    Args:
        base: 土台のフレーム（``cell_id`` を含む）。
        tables: テーブル名からデータフレームへの辞書。
    """
    base_cell_ids = base[CELL_ID_COLUMN]
    base_count = len(base)
    for table_name, table in tables.items():
        matched = int(table[CELL_ID_COLUMN].isin(base_cell_ids).sum())
        covered = int(base_cell_ids.isin(table[CELL_ID_COLUMN]).sum())
        print(
            f"  {table_name}: {len(table):,} 行"
            f"（うち土台と一致 {matched:,} 行 / 土台 {base_count:,} 行のうち"
            f"値が付くのは {covered:,} 行）",
            flush=True,
        )
        if covered == 0:
            print(
                f"  警告: {table_name} は土台と1件も一致しません。"
                " 正準グリッドを再生成した後にテーブルを算出し直していない可能性があります。",
                flush=True,
            )
        elif covered < base_count:
            print(
                f"  警告: {table_name} は土台の {base_count - covered:,} 行"
                f"（{(base_count - covered) / base_count:.1%}）に値を持ちません。"
                " 解析範囲を変更した後にテーブルを算出し直していない可能性があります。",
                flush=True,
            )


def classify_value_columns(
    table_names: list[str], tables: dict[str, pd.DataFrame]
) -> tuple[list[str], list[str]]:
    """結合した列を、GIS由来の指標と衛星由来の指標へ分類する。

    LST（``lst_`` で始まるテーブル）は目的変数であり、GIS・衛星いずれの品質管理列
    （``VALID_GIS_MASK`` / ``VALID_SATELLITE_MASK``）の判定材料にもしないため、
    戻り値のどちらにも含めず読み飛ばす（列自体はデータセットへ残る）。目的変数と
    説明変数の有効性を混ぜないためである。

    Args:
        table_names: 結合したテーブル名の一覧。
        tables: テーブル名からデータフレームへの辞書。

    Returns:
        (GIS由来の指標列, 衛星由来の指標列) の組。

    Raises:
        ValueError: ``PARAM_SETS`` にも無く、衛星指標・LSTの命名規則にも合致しない
            テーブル名が含まれる場合。
    """
    gis_columns: list[str] = []
    satellite_columns: list[str] = []

    for table_name in table_names:
        value_columns = [name for name in tables[table_name].columns if name != CELL_ID_COLUMN]
        param_set = PARAM_SETS.get(table_name)
        if param_set is not None:
            if param_set.module_name in GIS_INDICATOR_MODULES:
                gis_columns.extend(value_columns)
            continue
        if table_name.startswith(SATELLITE_TABLE_PREFIX):
            satellite_columns.extend(value_columns)
            continue
        if table_name.startswith(LST_TABLE_PREFIX):
            continue
        raise ValueError(
            f"テーブルの種別を判別できません: {table_name}。"
            f" PARAM_SETS のいずれか（{', '.join(PARAM_SETS)}）か、"
            f" {SATELLITE_TABLE_PREFIX} で始まる衛星指標テーブル、"
            f" {LST_TABLE_PREFIX} で始まるLSTテーブルを指定してください。"
        )

    return gis_columns, satellite_columns


def add_quality_columns(
    dataset: pd.DataFrame,
    gis_columns: list[str],
    satellite_columns: list[str],
) -> pd.DataFrame:
    """結合済みの列から品質管理列を導出して付与する。

    **判定材料となる列が1つも無い場合、対応する品質管理列は付与しない。** 全セル0の
    列を出すと「データを確認したうえで無効と判定した」ように読めてしまうためである。

    ``MISSING_REASON`` は NULL（値が得られていない）と0（地物が無い）を区別する。
    左結合では、テーブルに存在しない ``cell_id`` の列が NULL になる。これを0と同じ
    ``no_gis_feature`` にまとめると、テーブルの世代違いや算出範囲の不足が「地物が
    無い地域」として分析へ流れ込む。判定材料の列が**すべて** NULL のセルのみ
    ``missing_gis_data`` とし、1列でも値があれば観測結果として扱う。

    Args:
        dataset: 結合済みのデータフレーム。
        gis_columns: GIS由来の指標列（建物・道路）。
        satellite_columns: 衛星由来の指標列。

    Returns:
        品質管理列を付与したデータフレーム。
    """
    result = dataset.copy()

    if gis_columns:
        # 「値が0より大きいセル」を有効とみなす。被覆率・密度はいずれも地物の量を
        # 表すため、0は「その地物が無い」ことを意味する。
        valid_gis = np.zeros(len(result), dtype=bool)
        # 1列でも実測値（非NULL）を持つか。すべてNULLのセルだけを欠落として扱う。
        has_gis_value = np.zeros(len(result), dtype=bool)
        for column_name in gis_columns:
            values = result[column_name].to_numpy(dtype=np.float64, na_value=np.nan)
            has_gis_value |= ~np.isnan(values)
            valid_gis |= np.nan_to_num(values, nan=0.0) > 0
        result[VALID_GIS_MASK_COLUMN] = valid_gis.astype(np.int8)
        result[MISSING_REASON_COLUMN] = np.where(
            valid_gis,
            MISSING_REASON_NONE,
            np.where(has_gis_value, MISSING_REASON_NO_GIS_FEATURE, MISSING_REASON_MISSING_GIS_DATA),
        )

    if satellite_columns:
        valid_satellite = np.zeros(len(result), dtype=bool)
        for column_name in satellite_columns:
            values = result[column_name].to_numpy(dtype=np.float64, na_value=np.nan)
            valid_satellite |= ~np.isnan(values)
        result[VALID_SATELLITE_MASK_COLUMN] = valid_satellite.astype(np.int8)

    return result


def build_dataset(
    table_names: list[str],
    city: str,
    scale: int,
    grid_path: Path,
    params_dir: Path | None,
) -> pd.DataFrame:
    """指定テーブルを ``cell_id`` で結合し、分析用データセットを組み立てる。

    Args:
        table_names: 結合するテーブル名の一覧。
        city: 都市ID。
        scale: coarseグリッド解像度（m）。
        grid_path: 正準グリッドGeoPackageのパス。
        params_dir: パラメータテーブルの格納ルート。

    Returns:
        ``cell_id`` / ``lon`` / ``lat`` に各テーブルの列と品質管理列を加えた
        データフレーム。

    Raises:
        ValueError: 結合するテーブルが1つも無い場合、または観測日時の異なる観測
            テーブル（``idx_*`` / ``lst_*``）が混在する場合。
    """
    if not table_names:
        raise ValueError("結合するテーブルが指定されていません。")
    # 読み込みより前に検証する。ファイルは実在するため読み込みは成功してしまい、
    # 結合まで進んでも異常として現れないためである。
    validate_observation_consistency(table_names)

    base = read_grid_frame(grid_path, grid_layer_name(scale), GRID_COLUMNS)
    print(f"土台の正準グリッド: {len(base):,} 行（{grid_layer_name(scale)}）", flush=True)

    # 読み込みは結合の前にまとめて行う。1つ目を結合してから2つ目が見つからずに
    # 失敗しても得るものが無いためである。
    tables = {
        table_name: load_param_table(table_name, city, scale, params_dir)
        for table_name in table_names
    }
    report_match_counts(base, tables)

    dataset = join_tables(base, tables)
    gis_columns, satellite_columns = classify_value_columns(table_names, tables)
    return add_quality_columns(dataset, gis_columns, satellite_columns)


def summarize_dataset(dataset: pd.DataFrame) -> None:
    """データセットの行数と欠損状況を標準出力する。

    Args:
        dataset: 出力するデータセット。
    """
    print(f"データセット: {len(dataset):,} 行 / {len(dataset.columns)} 列", flush=True)
    missing_counts = dataset.isna().sum()
    missing_columns = missing_counts[missing_counts > 0]
    if len(missing_columns) == 0:
        print("欠損のある列はありません。", flush=True)
        return
    print("欠損のある列（NULL 件数）:", flush=True)
    for column_name, count in missing_columns.items():
        print(f"  {column_name}: {int(count):,}", flush=True)


def main(argv: list[str] | None = None) -> None:
    """分析用データセットの生成処理を実行する。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。
    """
    args = parse_arguments(argv)

    table_names = resolve_table_names(args.scenario, args.tables)
    dataset_name = resolve_dataset_name(args.scenario, args.name)
    grid_path = resolve_output_path(args.grid, args.city)
    params_dir = (PROJECT_ROOT / args.params_dir) if args.params_dir else None
    output_dir = (PROJECT_ROOT / args.output_dir) if args.output_dir else None

    print("都市:", args.city)
    print("スケール:", f"{args.scale}m")
    print("データセット名:", dataset_name)
    print("結合するテーブル:", ", ".join(table_names))

    dataset = build_dataset(table_names, args.city, args.scale, grid_path, params_dir)

    output_path = resolve_dataset_path(dataset_name, args.city, args.scale, output_dir)
    write_attribute_table(dataset, output_path, dataset_name)

    summarize_dataset(dataset)
    print("出力先:", output_path)


if __name__ == "__main__":
    main()
