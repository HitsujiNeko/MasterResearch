"""build_dataset.py（cell_id 結合による分析用データセット生成）のテスト。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio
import pytest

from src.analysis.build_dataset import (
    MISSING_REASON_COLUMN,
    VALID_GIS_MASK_COLUMN,
    VALID_NTL_MASK_COLUMN,
    VALID_SATELLITE_MASK_COLUMN,
    WATER_COVERAGE_COLUMN,
    add_auxiliary_quality_columns,
    add_quality_columns,
    classify_value_columns,
    fill_missing_population_for_water_dominant_cells,
    join_tables,
    load_param_table,
    main,
    observation_key,
    parse_arguments,
    population_filled_flag_column,
    report_match_counts,
    report_population_fill,
    resolve_dataset_name,
    resolve_dataset_path,
    resolve_table_names,
    valid_population_mask_column,
    validate_observation_consistency,
)
from src.analysis.urban_params.config import SCENARIO_TABLES
from src.analysis.urban_params.run import main as run_urban_params

from .conftest import (
    CITY,
    FINE_RES_M,
    LST_FILE_NAME,
    LST_TABLE_NAME,
    SATELLITE_FILE_NAME,
    SATELLITE_TABLE_NAME,
    SCALES,
)

# 結合の検証に使うスケール（合成グリッドでは 20m が 6x6 相当）。
TARGET_SCALE = SCALES[0]


# ---------------------------------------------------------------------------
# parse_arguments
# ---------------------------------------------------------------------------


def test_parse_arguments_expands_scenario() -> None:
    """--scenario 指定では --name の既定がシナリオ名になる。"""
    args = parse_arguments(["--scale", "30", "--scenario", "limited"])

    assert args.scenario == "limited"
    assert args.tables == []


def test_parse_arguments_requires_scenario_or_tables() -> None:
    """--scenario と --tables のどちらも指定しない場合はエラーになる。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--scale", "30"])


def test_parse_arguments_accepts_scenario_and_tables_together() -> None:
    """--scenario と --tables は併用できる（シナリオ展開＋観測ファイル単位テーブルの追加）。

    観測ファイル単位のテーブル（idx_* / lst_*）は SCENARIO_TABLES に列挙できないため、
    シナリオ展開＋観測テーブルの追加が RQ1・RQ2 でも定型になる。
    """
    args = parse_arguments(
        [
            "--scale",
            "30",
            "--scenario",
            "limited",
            "--tables",
            "idx_20230707_032329",
            "--name",
            "custom",
        ]
    )

    assert args.scenario == "limited"
    assert args.tables == ["idx_20230707_032329"]


def test_parse_arguments_requires_name_when_scenario_and_tables_combined() -> None:
    """--scenario と --tables を併用する場合も --name が必須（既定名を推測しないため）。"""
    with pytest.raises(SystemExit):
        parse_arguments(
            ["--scale", "30", "--scenario", "limited", "--tables", "idx_20230707_032329"]
        )


def test_parse_arguments_rejects_satellite_only_without_tables() -> None:
    """--scenario satellite_only を --tables なしで指定すると拒否する。

    衛星指標は観測ファイル単位のため SCENARIO_TABLES に列挙できず、シナリオ名だけの
    指定では mask_roi だけのデータセットが「衛星のみ」を名乗って出力される。
    名前が中身を偽るくらいなら止める。
    """
    with pytest.raises(SystemExit):
        parse_arguments(["--scale", "30", "--scenario", "satellite_only"])


def test_parse_arguments_rejects_satellite_only_without_satellite_table() -> None:
    """--scenario satellite_only を idx_* 抜きの --tables で指定すると拒否する。

    lst_* だけを許すと、目的変数（LST）しか持たないデータセットが「衛星のみ」を
    名乗ることになる。Satellite Only は衛星由来指標（idx_*）を用いるシナリオであり、
    lst_* の有無は解禁条件にしない。
    """
    with pytest.raises(SystemExit):
        parse_arguments(
            [
                "--scale",
                "30",
                "--scenario",
                "satellite_only",
                "--tables",
                "lst_20230707_032329",
                "--name",
                "custom",
            ]
        )


def test_parse_arguments_accepts_satellite_only_with_satellite_table() -> None:
    """--scenario satellite_only は idx_* を伴う --tables との併用で許可される。"""
    args = parse_arguments(
        [
            "--scale",
            "30",
            "--scenario",
            "satellite_only",
            "--tables",
            "idx_20230707_032329",
            "lst_20230707_032329",
            "--name",
            "custom",
        ]
    )

    assert args.scenario == "satellite_only"
    assert args.tables == ["idx_20230707_032329", "lst_20230707_032329"]


def test_parse_arguments_requires_name_with_tables() -> None:
    """--tables 指定時は --name が必須（既定名を推測しないため）。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--scale", "30", "--tables", "build_gba"])


@pytest.mark.parametrize("scale", ["40", "0", "7"])
def test_parse_arguments_rejects_unsupported_scale(scale: str) -> None:
    """900mの約数でないスケールはCLI段階で弾く。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--scale", scale, "--scenario", "limited"])


def test_parse_arguments_removes_duplicate_tables() -> None:
    """--tables は重複を除いた一覧に正規化される。"""
    args = parse_arguments(
        ["--scale", "30", "--tables", "build_gba", "build_gba", "road_osm", "--name", "custom"]
    )

    assert args.tables == ["build_gba", "road_osm"]


# ---------------------------------------------------------------------------
# 結合対象・出力先の決定
# ---------------------------------------------------------------------------


def test_resolve_table_names_expands_scenario_tables() -> None:
    """シナリオ名は SCENARIO_TABLES へ展開される。"""
    assert resolve_table_names("limited", []) == list(SCENARIO_TABLES["limited"])
    assert resolve_table_names("", ["build_dc", "road_gt"]) == ["build_dc", "road_gt"]


def test_resolve_table_names_combines_scenario_and_tables() -> None:
    """シナリオ展開分（先）と直接指定分（後）を連結する。"""
    result = resolve_table_names("limited", ["idx_20230707_032329"])

    assert result == [*SCENARIO_TABLES["limited"], "idx_20230707_032329"]


def test_resolve_table_names_deduplicates_overlapping_names() -> None:
    """シナリオ展開分と直接指定分に同じテーブル名がある場合は重複を除く。"""
    result = resolve_table_names("limited", ["build_gba", "idx_20230707_032329"])

    assert result.count("build_gba") == 1
    assert result == [*SCENARIO_TABLES["limited"], "idx_20230707_032329"]


def test_resolve_dataset_name_prefers_explicit_name() -> None:
    """--name があればそれを使い、無ければシナリオ名を使う。"""
    assert resolve_dataset_name("limited", "") == "limited"
    assert resolve_dataset_name("limited", "custom") == "custom"


def test_resolve_dataset_path_includes_city_and_scale(tmp_path: Path) -> None:
    """出力ファイル名に都市とスケールが含まれる。"""
    path = resolve_dataset_path("limited", "hanoi", 30, base_dir=tmp_path)

    assert path == tmp_path / "dataset_limited_hanoi_30m.gpkg"


# ---------------------------------------------------------------------------
# load_param_table
# ---------------------------------------------------------------------------


def _write_table(path: Path, layer_name: str, frame: pd.DataFrame) -> None:
    """属性のみのテーブルを書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    pyogrio.write_dataframe(frame, path, layer=layer_name, driver="GPKG")


def test_load_param_table_missing_file_suggests_calculation_command(tmp_path: Path) -> None:
    """テーブルが無い場合は、算出コマンドを案内するFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError, match="src.analysis.urban_params"):
        load_param_table("build_gba", "hanoi", 30, tmp_path)


def test_load_param_table_rejects_duplicated_cell_id(tmp_path: Path) -> None:
    """cell_id に重複があるテーブルはValueErrorになる（結合で行が増えるため）。"""
    table_path = tmp_path / "hanoi" / "30m" / "build_gba.gpkg"
    _write_table(
        table_path,
        "build_gba",
        pd.DataFrame(
            {
                "cell_id": np.array([1_000_001, 1_000_001], dtype=np.int64),
                "BUILD_COV": np.array([0.1, 0.2], dtype=np.float32),
            }
        ),
    )

    with pytest.raises(ValueError, match="重複"):
        load_param_table("build_gba", "hanoi", 30, tmp_path)


def test_load_param_table_rejects_table_without_key_column(tmp_path: Path) -> None:
    """cell_id 列を持たないテーブルはValueErrorになる。"""
    table_path = tmp_path / "hanoi" / "30m" / "build_gba.gpkg"
    _write_table(
        table_path,
        "build_gba",
        pd.DataFrame({"BUILD_COV": np.array([0.1, 0.2], dtype=np.float32)}),
    )

    with pytest.raises(ValueError, match="cell_id 列がありません"):
        load_param_table("build_gba", "hanoi", 30, tmp_path)


# ---------------------------------------------------------------------------
# join_tables
# ---------------------------------------------------------------------------


def _base_frame() -> pd.DataFrame:
    """土台となる正準グリッドのフレーム。"""
    return pd.DataFrame(
        {
            "cell_id": np.array([1_000_001, 1_000_002, 1_000_003], dtype=np.int64),
            "lon": np.array([105.0, 105.1, 105.2], dtype=np.float64),
            "lat": np.array([21.0, 21.1, 21.2], dtype=np.float64),
        }
    )


def test_join_tables_keeps_all_base_rows_and_nulls_missing_cells() -> None:
    """土台の行はすべて残り、テーブルに無い cell_id は NULL になる。"""
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_001, 1_000_003], dtype=np.int64),
            "BUILD_COV": np.array([0.5, 0.25], dtype=np.float32),
        }
    )

    joined = join_tables(_base_frame(), {"build_gba": table})

    assert len(joined) == 3
    assert joined["BUILD_COV"].isna().tolist() == [False, True, False]
    np.testing.assert_allclose(joined.loc[0, "BUILD_COV"], 0.5)


def test_join_tables_merges_multiple_tables() -> None:
    """複数テーブルを同時に結合できる。"""
    tables = {
        "build_gba": pd.DataFrame(
            {
                "cell_id": np.array([1_000_001], dtype=np.int64),
                "BUILD_COV": np.array([0.5], dtype=np.float32),
            }
        ),
        "road_osm": pd.DataFrame(
            {
                "cell_id": np.array([1_000_002], dtype=np.int64),
                "ROAD_DEN": np.array([12.0], dtype=np.float32),
            }
        ),
    }

    joined = join_tables(_base_frame(), tables)

    assert list(joined.columns) == ["cell_id", "lon", "lat", "BUILD_COV", "ROAD_DEN"]
    assert len(joined) == 3


def test_report_match_counts_shows_matched_rows(capsys: pytest.CaptureFixture[str]) -> None:
    """テーブルの行数・土台と一致した件数・土台側で値が付く件数を報告する。

    テーブルが土台より広い場合（余分な行を持つ場合）は、土台の全行に値が付く
    ため警告しない。
    """
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_001, 1_000_002, 1_000_003, 9_999_999], dtype=np.int64),
            "BUILD_COV": np.array([0.5, 0.25, 0.125, 0.0625], dtype=np.float32),
        }
    )

    report_match_counts(_base_frame(), {"build_gba": table})

    output = capsys.readouterr().out
    assert "build_gba: 4 行（うち土台と一致 3 行 / 土台 3 行のうち値が付くのは 3 行）" in output
    assert "警告" not in output


def test_report_match_counts_warns_on_partial_coverage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """土台の一部にしか値が付かないテーブルも警告する。

    部分的に stale なテーブルは一致0件にならないため、0件だけを検知していると
    見逃す。左結合ではその差分がそのまま NULL の行数になる。
    """
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_001], dtype=np.int64),
            "BUILD_COV": np.array([0.5], dtype=np.float32),
        }
    )

    report_match_counts(_base_frame(), {"build_gba": table})

    output = capsys.readouterr().out
    assert "警告" in output
    assert "土台の 2 行" in output


def test_report_match_counts_warns_when_nothing_matches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """1件も一致しない場合は、世代違いの可能性を警告する。

    stale なテーブルの結合は例外にならず、該当列が全行NULLになるだけで
    静かに壊れるため、検知手段を明示的に置く。
    """
    table = pd.DataFrame(
        {
            "cell_id": np.array([9_999_998, 9_999_999], dtype=np.int64),
            "BUILD_COV": np.array([0.5, 0.25], dtype=np.float32),
        }
    )

    report_match_counts(_base_frame(), {"build_gba": table})

    output = capsys.readouterr().out
    assert "うち土台と一致 0 行" in output
    assert "警告" in output


def test_join_tables_rejects_column_name_conflict() -> None:
    """同じ列名を持つ別ソースのテーブルを同時に結合するとValueErrorになる。"""
    same_columns = pd.DataFrame(
        {
            "cell_id": np.array([1_000_001], dtype=np.int64),
            "BUILD_COV": np.array([0.5], dtype=np.float32),
        }
    )
    tables = {"build_gba": same_columns, "build_dc": same_columns.copy()}

    with pytest.raises(ValueError, match="BUILD_COV（build_gba）"):
        join_tables(_base_frame(), tables)


def test_join_tables_rejects_conflict_with_grid_columns() -> None:
    """土台の座標列と同名の列を持つテーブルもValueErrorになる。

    検査対象に土台の列を含めないと、pandas が ``lon_x`` / ``lon_y`` へ暗黙に
    リネームし、例外も警告も出ないまま座標列が二重化する。
    """
    table = pd.DataFrame(
        {
            "cell_id": np.array([1_000_001], dtype=np.int64),
            "lon": np.array([105.0], dtype=np.float64),
        }
    )

    with pytest.raises(ValueError, match="lon（正準グリッド）"):
        join_tables(_base_frame(), {"build_gba": table})


# ---------------------------------------------------------------------------
# classify_value_columns
# ---------------------------------------------------------------------------


def _one_row(columns: list[str]) -> pd.DataFrame:
    """指定列を持つ1行のテーブルを作る。"""
    data: dict[str, np.ndarray] = {"cell_id": np.array([1_000_001], dtype=np.int64)}
    for name in columns:
        data[name] = np.array([1.0], dtype=np.float32)
    return pd.DataFrame(data)


def test_classify_value_columns_splits_gis_and_satellite() -> None:
    """建物・道路はGIS由来、idx_ で始まるテーブルは衛星由来として扱う。"""
    tables = {
        "build_gba": _one_row(["BUILD_COV", "BUILD_DEN"]),
        "road_osm": _one_row(["ROAD_DEN"]),
        SATELLITE_TABLE_NAME: _one_row(["NDVI", "NDBI"]),
    }

    gis_columns, satellite_columns = classify_value_columns(list(tables), tables)

    assert gis_columns == ["BUILD_COV", "BUILD_DEN", "ROAD_DEN"]
    assert satellite_columns == ["NDVI", "NDBI"]


def test_classify_value_columns_excludes_lst_from_both_masks() -> None:
    """LST（lst_ で始まるテーブル）はGIS・衛星いずれの分類にも含めない。

    LSTは目的変数であり、VALID_GIS_MASK / VALID_SATELLITE_MASK の判定材料に
    混ぜてはならない。
    """
    tables = {
        "build_gba": _one_row(["BUILD_COV"]),
        SATELLITE_TABLE_NAME: _one_row(["NDVI"]),
        LST_TABLE_NAME: _one_row(["LST", "LST_VALID_RATIO"]),
    }

    gis_columns, satellite_columns = classify_value_columns(list(tables), tables)

    assert gis_columns == ["BUILD_COV"]
    assert satellite_columns == ["NDVI"]


def test_classify_value_columns_excludes_elevation_and_mask() -> None:
    """標高と解析対象域フラグは VALID_GIS_MASK の判定材料に含めない。

    標高は連続量で0mが「データが無い」を意味しないため、地物の量を前提とした
    判定基準を適用すること自体が不適切である。
    """
    tables = {
        "elev_fabdem": _one_row(["ELEV_MEAN", "ELEV_VALID_RATIO"]),
        "mask_roi": _one_row(["IN_ANALYSIS_AREA"]),
    }

    gis_columns, satellite_columns = classify_value_columns(list(tables), tables)

    assert gis_columns == []
    assert satellite_columns == []


def test_classify_value_columns_excludes_lulc_from_both_masks() -> None:
    """土地被覆（lulc_* テーブル）は VALID_GIS_MASK / VALID_SATELLITE_MASK の判定材料に含めない。

    7クラスの面積率の和は有効セルで必ず1になるため、判定材料に含めると ROI 内の
    ほぼ全セルが有効と判定され、``VALID_GIS_MASK`` 本来の意味（建物・道路データが
    当該セルに存在するか）が失われる。``GIS_INDICATOR_MODULES`` に ``lulc`` を
    加えないことで実現しており、その効果をユニットテストで固定する。
    """
    tables = {
        "build_gba": _one_row(["BUILD_COV"]),
        SATELLITE_TABLE_NAME: _one_row(["NDVI"]),
        "lulc_glc2022": _one_row(
            [
                "LULC_WATER_COV",
                "LULC_TREE_COV",
                "LULC_CROP_COV",
                "LULC_BUILT_COV",
                "LULC_RANGE_COV",
                "LULC_WETLAND_COV",
                "LULC_BARE_COV",
                "LULC_VALID_RATIO",
            ]
        ),
    }

    gis_columns, satellite_columns = classify_value_columns(list(tables), tables)

    assert gis_columns == ["BUILD_COV"]
    assert satellite_columns == ["NDVI"]


def test_classify_value_columns_rejects_unknown_table() -> None:
    """PARAM_SETS にも衛星指標の命名規則にも該当しないテーブルはValueErrorになる。"""
    tables = {"mystery": _one_row(["SOMETHING"])}

    with pytest.raises(ValueError, match="種別を判別できません"):
        classify_value_columns(list(tables), tables)


# ---------------------------------------------------------------------------
# observation_key / validate_observation_consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table_name", "expected"),
    [
        ("idx_20230707_032329", "20230707_032329"),
        ("lst_20230707_032329", "20230707_032329"),
        ("lst_20241130_032336", "20241130_032336"),
        # 観測ファイル単位でないテーブルは観測日時を持たない。
        ("build_gba", None),
        ("mask_roi", None),
        # 接頭辞は合っていても日時形式に合致しないものは対象外とする。
        ("idx_2023", None),
        ("lst_20230707_0323290", None),
    ],
)
def test_observation_key_extracts_datetime(table_name: str, expected: str | None) -> None:
    """観測ファイル単位のテーブル名からのみ観測日時キーを取り出す。"""
    assert observation_key(table_name) == expected


@pytest.mark.parametrize(
    "table_names",
    [
        ["idx_20230707_032329", "lst_20230707_032329"],
        ["mask_roi", "build_gba", "idx_20230707_032329", "lst_20230707_032329"],
        # 観測テーブルが1つだけ、あるいは1つも無い場合も通す。
        ["lst_20230707_032329"],
        ["mask_roi", "build_gba"],
        [],
    ],
)
def test_validate_observation_consistency_accepts_single_observation(
    table_names: list[str],
) -> None:
    """観測日時が揃っている（または観測テーブルが1つ以下の）場合は通る。"""
    validate_observation_consistency(table_names)


def test_validate_observation_consistency_rejects_mixed_observations() -> None:
    """観測日時の異なる idx_* と lst_* の同時結合はValueErrorで止める。

    LSTと衛星指標が別の観測から来ていると、目的変数と説明変数の関係を見るという
    分析の前提が崩れる。それでいて cell_id 結合は成立し、行数も欠損も正常に見える
    ため、出力からは判別できない。
    """
    with pytest.raises(ValueError, match="観測日時の異なるテーブル"):
        validate_observation_consistency(["mask_roi", "idx_20230707_032329", "lst_20241130_032336"])


def test_validate_observation_consistency_rejects_two_satellite_observations() -> None:
    """同種のテーブルどうしでも、観測日時が異なれば止める。"""
    with pytest.raises(ValueError, match="観測日時の異なるテーブル"):
        validate_observation_consistency(["idx_20230707_032329", "idx_20241130_032336"])


def test_build_dataset_rejects_mixed_observations_before_reading(
    city_environment: dict[str, Any],
) -> None:
    """観測日時の食い違いは、テーブルを読み込む前に検出する。

    ファイルは実在するため読み込み自体は成功し、結合まで進んでも異常として現れない。
    """
    _run_param_calculation(
        city_environment,
        ["--satellite-file", f"data/{SATELLITE_FILE_NAME}", "--lst-file", f"data/{LST_FILE_NAME}"],
    )

    with pytest.raises(ValueError, match="観測日時の異なるテーブル"):
        _run_build_dataset(
            city_environment,
            [
                "--tables",
                SATELLITE_TABLE_NAME,
                "lst_20241130_032336",
                "--name",
                "mixed_observation",
            ],
        )


# ---------------------------------------------------------------------------
# add_quality_columns
# ---------------------------------------------------------------------------


def test_add_quality_columns_marks_cells_with_any_positive_indicator() -> None:
    """いずれかのGIS指標が0より大きいセルのみ VALID_GIS_MASK=1 になる。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2, 3, 4], dtype=np.int64),
            "BUILD_COV": np.array([0.0, 0.0, np.nan, 0.0], dtype=np.float32),
            "ROAD_DEN": np.array([1.0, 0.0, 0.0, np.nan], dtype=np.float32),
        }
    )

    result = add_quality_columns(dataset, ["BUILD_COV", "ROAD_DEN"], [])

    np.testing.assert_array_equal(
        result[VALID_GIS_MASK_COLUMN].to_numpy(), np.array([1, 0, 0, 0], dtype=np.int8)
    )
    assert result[MISSING_REASON_COLUMN].tolist() == [
        "none",
        "no_gis_feature",
        "no_gis_feature",
        "no_gis_feature",
    ]


def test_add_quality_columns_distinguishes_missing_data_from_absent_feature() -> None:
    """判定材料がすべてNULLのセルは no_gis_feature と区別する。

    左結合ではテーブルに存在しない cell_id の列が NULL になる。0（地物が無い）と
    同じラベルにまとめると、テーブルの世代違いや算出範囲の不足が「地物が無い地域」
    として分析へ流れ込む。1列でも値があれば観測結果として扱う。
    """
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2, 3], dtype=np.int64),
            "BUILD_COV": np.array([0.0, np.nan, np.nan], dtype=np.float32),
            "ROAD_DEN": np.array([0.0, 0.0, np.nan], dtype=np.float32),
        }
    )

    result = add_quality_columns(dataset, ["BUILD_COV", "ROAD_DEN"], [])

    assert result[MISSING_REASON_COLUMN].tolist() == [
        "no_gis_feature",
        "no_gis_feature",
        "missing_gis_data",
    ]
    # 値が得られていないセルも「有効なGIS指標を持たない」ことに変わりはないため、
    # VALID_GIS_MASK は 0 のままとする。
    np.testing.assert_array_equal(
        result[VALID_GIS_MASK_COLUMN].to_numpy(), np.array([0, 0, 0], dtype=np.int8)
    )


def test_add_quality_columns_detects_non_nan_satellite_cells() -> None:
    """NaNでない衛星指標があるセルのみ VALID_SATELLITE_MASK=1 になる。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2, 3], dtype=np.int64),
            "NDVI": np.array([0.5, np.nan, np.nan], dtype=np.float32),
            "NDBI": np.array([np.nan, -0.2, np.nan], dtype=np.float32),
        }
    )

    result = add_quality_columns(dataset, [], ["NDVI", "NDBI"])

    np.testing.assert_array_equal(
        result[VALID_SATELLITE_MASK_COLUMN].to_numpy(), np.array([1, 1, 0], dtype=np.int8)
    )
    assert VALID_GIS_MASK_COLUMN not in result.columns


def test_add_quality_columns_omits_columns_without_source() -> None:
    """判定材料の列が無い場合、対応する品質管理列を付与しない。

    全セル0の列を出すと「確認したうえで無効と判定した」ように読めてしまうため。
    """
    dataset = pd.DataFrame({"cell_id": np.array([1, 2], dtype=np.int64)})

    result = add_quality_columns(dataset, [], [])

    assert VALID_GIS_MASK_COLUMN not in result.columns
    assert MISSING_REASON_COLUMN not in result.columns
    assert VALID_SATELLITE_MASK_COLUMN not in result.columns


def test_add_quality_columns_does_not_mutate_input() -> None:
    """入力のデータフレームを破壊的に変更しない。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            "ROAD_DEN": np.array([1.0], dtype=np.float32),
        }
    )

    add_quality_columns(dataset, ["ROAD_DEN"], [])

    assert VALID_GIS_MASK_COLUMN not in dataset.columns


# ---------------------------------------------------------------------------
# add_auxiliary_quality_columns（人口・夜間光の有効域品質列）
# ---------------------------------------------------------------------------


def test_add_auxiliary_quality_columns_marks_nightlight_presence() -> None:
    """NTL_MEANが非NULLなセルのみ VALID_NTL_MASK=1 になる。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2, 3], dtype=np.int64),
            "NTL_MEAN": np.array([0.0, np.nan, 5.0], dtype=np.float32),
            "NTL_VALID_RATIO": np.array([1.0, 1.0, 1.0], dtype=np.float32),
        }
    )

    result = add_auxiliary_quality_columns(dataset, ["ntl_viirs2023"])

    np.testing.assert_array_equal(
        result[VALID_NTL_MASK_COLUMN].to_numpy(), np.array([1, 0, 1], dtype=np.int8)
    )


def test_add_auxiliary_quality_columns_marks_population_presence_per_source() -> None:
    """人口ソースごとに独立した有効域品質列を付与する（他ソースの欠測に引きずられない）。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2], dtype=np.int64),
            "POP_DEN_WORLDPOP2020": np.array([np.nan, 3.0], dtype=np.float32),
            "POP_DEN_LANDSCAN2020": np.array([1.0, np.nan], dtype=np.float32),
        }
    )

    result = add_auxiliary_quality_columns(dataset, ["pop_worldpop2020", "pop_landscan2020"])

    np.testing.assert_array_equal(
        result[valid_population_mask_column("WORLDPOP2020")].to_numpy(),
        np.array([0, 1], dtype=np.int8),
    )
    np.testing.assert_array_equal(
        result[valid_population_mask_column("LANDSCAN2020")].to_numpy(),
        np.array([1, 0], dtype=np.int8),
    )


def test_add_auxiliary_quality_columns_ignores_unrelated_tables() -> None:
    """人口・夜間光以外のテーブルからは品質列を導出しない。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            "BUILD_COV": np.array([0.5], dtype=np.float32),
        }
    )

    result = add_auxiliary_quality_columns(dataset, ["build_gba"])

    assert VALID_NTL_MASK_COLUMN not in result.columns
    assert valid_population_mask_column("WORLDPOP2020") not in result.columns


def test_add_auxiliary_quality_columns_does_not_mutate_input() -> None:
    """入力のデータフレームを破壊的に変更しない。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            "NTL_MEAN": np.array([1.0], dtype=np.float32),
        }
    )

    add_auxiliary_quality_columns(dataset, ["ntl_viirs2023"])

    assert VALID_NTL_MASK_COLUMN not in dataset.columns


# ---------------------------------------------------------------------------
# fill_missing_population_for_water_dominant_cells（水域優位セルの人口0補完）
# ---------------------------------------------------------------------------


def test_fill_missing_population_fills_only_water_dominant_null_cells() -> None:
    """水域優位（既定0.9以上）かつNULLのセルのみ0で補完する。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2, 3, 4], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([0.95, 0.5, 0.95, 0.0], dtype=np.float32),
            "POP_DEN_WORLDPOP2020": np.array([np.nan, np.nan, 5.0, np.nan], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(
        dataset, ["pop_worldpop2020"]
    )

    np.testing.assert_array_equal(
        result["POP_DEN_WORLDPOP2020"].to_numpy(), np.array([0.0, np.nan, 5.0, np.nan])
    )
    np.testing.assert_array_equal(
        result[population_filled_flag_column("WORLDPOP2020")].to_numpy(),
        np.array([1, 0, 0, 0], dtype=np.int8),
    )
    assert filled_counts == {"POP_DEN_WORLDPOP2020": 1}


def test_fill_missing_population_respects_custom_threshold() -> None:
    """water_dominant_threshold を変えると、補完対象の境界が追従する。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([0.85, 0.75], dtype=np.float32),
            "POP_DEN_WORLDPOP2020": np.array([np.nan, np.nan], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(
        dataset, ["pop_worldpop2020"], water_dominant_threshold=0.8
    )

    np.testing.assert_array_equal(
        result["POP_DEN_WORLDPOP2020"].to_numpy(), np.array([0.0, np.nan])
    )
    assert filled_counts == {"POP_DEN_WORLDPOP2020": 1}


def test_fill_missing_population_ignores_non_population_tables() -> None:
    """人口以外のテーブルは補完対象にしない（列自体を追加しない）。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([1.0], dtype=np.float32),
            "BUILD_COV": np.array([0.5], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(dataset, ["build_gba"])

    assert filled_counts == {}
    assert population_filled_flag_column("WORLDPOP2020") not in result.columns


def test_fill_missing_population_skips_when_water_coverage_column_absent() -> None:
    """LULC_WATER_COV が結合されていない場合、水域優位を判定できないため補完しない。

    フラグ列も付与しない（`add_quality_columns` が判定材料の列が無い場合に
    品質管理列自体を付与しない方針と同じ理由）。
    """
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            "POP_DEN_WORLDPOP2020": np.array([np.nan], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(
        dataset, ["pop_worldpop2020"]
    )

    assert filled_counts == {}
    assert population_filled_flag_column("WORLDPOP2020") not in result.columns
    assert pd.isna(result.loc[0, "POP_DEN_WORLDPOP2020"])


def test_fill_missing_population_records_zero_when_nothing_qualifies() -> None:
    """補完対象が0件でも、テーブルが結合されていればフラグ列・件数0を記録する。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([0.95, 0.1], dtype=np.float32),
            "POP_DEN_WORLDPOP2020": np.array([5.0, 3.0], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(
        dataset, ["pop_worldpop2020"]
    )

    assert filled_counts == {"POP_DEN_WORLDPOP2020": 0}
    np.testing.assert_array_equal(
        result[population_filled_flag_column("WORLDPOP2020")].to_numpy(),
        np.array([0, 0], dtype=np.int8),
    )


def test_fill_missing_population_handles_multiple_sources_independently() -> None:
    """複数の人口ソースが同時に結合されていても、それぞれ独立に補完・集計する。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1, 2], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([0.95, 0.95], dtype=np.float32),
            "POP_DEN_WORLDPOP2020": np.array([np.nan, np.nan], dtype=np.float32),
            "POP_DEN_LANDSCAN2020": np.array([np.nan, 1.0], dtype=np.float32),
        }
    )

    result, filled_counts = fill_missing_population_for_water_dominant_cells(
        dataset, ["pop_worldpop2020", "pop_landscan2020"]
    )

    assert filled_counts == {"POP_DEN_WORLDPOP2020": 2, "POP_DEN_LANDSCAN2020": 1}
    np.testing.assert_array_equal(result["POP_DEN_WORLDPOP2020"].to_numpy(), np.array([0.0, 0.0]))
    np.testing.assert_array_equal(result["POP_DEN_LANDSCAN2020"].to_numpy(), np.array([0.0, 1.0]))


def test_fill_missing_population_does_not_mutate_input() -> None:
    """入力のデータフレームを破壊的に変更しない。"""
    dataset = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype=np.int64),
            WATER_COVERAGE_COLUMN: np.array([0.95], dtype=np.float32),
            "POP_DEN_WORLDPOP2020": np.array([np.nan], dtype=np.float32),
        }
    )

    fill_missing_population_for_water_dominant_cells(dataset, ["pop_worldpop2020"])

    assert pd.isna(dataset.loc[0, "POP_DEN_WORLDPOP2020"])
    assert population_filled_flag_column("WORLDPOP2020") not in dataset.columns


def test_population_filled_flag_column_builds_the_expected_name() -> None:
    """フラグ列名は POP_FILLED_<接尾辞> の形式になる。"""
    assert population_filled_flag_column("WORLDPOP2020") == "POP_FILLED_WORLDPOP2020"


# ---------------------------------------------------------------------------
# report_population_fill
# ---------------------------------------------------------------------------


def test_report_population_fill_prints_threshold_and_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """閾値とソースごとの補完セル数を出力する。"""
    report_population_fill({"POP_DEN_WORLDPOP2020": 51_992, "POP_DEN_LANDSCAN2020": 0}, 0.9)

    output = capsys.readouterr().out
    assert "0.9" in output
    assert "POP_DEN_WORLDPOP2020: 51,992" in output
    assert "POP_DEN_LANDSCAN2020: 0" in output


def test_report_population_fill_prints_nothing_when_no_population_tables(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """人口テーブルが1つも結合されていない場合（辞書が空）、何も出力しない。"""
    report_population_fill({}, 0.9)

    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# 合成グリッドでの compute -> tables -> build_dataset のE2E検証
# ---------------------------------------------------------------------------


def _run_param_calculation(city_environment: dict[str, Any], extra_args: list[str]) -> None:
    """算出フェーズ（urban_params）を合成環境で実行する。"""
    run_urban_params(
        [
            "--city",
            CITY,
            "--scales",
            str(TARGET_SCALE),
            "--fine-res",
            str(FINE_RES_M),
            "--grid",
            city_environment["grid_argument"],
            "--output-dir",
            "params",
            *extra_args,
        ]
    )


def _run_build_dataset(city_environment: dict[str, Any], extra_args: list[str]) -> None:
    """結合フェーズ（build_dataset）を合成環境で実行する。"""
    main(
        [
            "--city",
            CITY,
            "--scale",
            str(TARGET_SCALE),
            "--params-dir",
            "params",
            "--grid",
            city_environment["grid_argument"],
            "--output-dir",
            "datasets",
            *extra_args,
        ]
    )


def _read_dataset(city_environment: dict[str, Any], dataset_name: str) -> pd.DataFrame:
    """出力したデータセットを読み戻す。"""
    path = (
        city_environment["root"]
        / "datasets"
        / f"dataset_{dataset_name}_{CITY}_{TARGET_SCALE}m.gpkg"
    )
    return pyogrio.read_dataframe(path, layer=dataset_name, read_geometry=False)


def test_end_to_end_join_matches_canonical_grid(city_environment: dict[str, Any]) -> None:
    """算出したテーブルを結合すると、正準グリッドと同じ行集合になる。"""
    _run_param_calculation(city_environment, ["--params", "build_gba", "road_osm", "mask_roi"])
    _run_build_dataset(
        city_environment,
        ["--tables", "build_gba", "road_osm", "mask_roi", "--name", "e2e"],
    )

    dataset = _read_dataset(city_environment, "e2e")
    expected_cell_ids = city_environment["cell_ids_by_scale"][TARGET_SCALE]

    assert len(dataset) == len(expected_cell_ids)
    np.testing.assert_array_equal(dataset["cell_id"].to_numpy(), expected_cell_ids)
    assert list(dataset.columns) == [
        "cell_id",
        "lon",
        "lat",
        "BUILD_COV",
        "BUILD_DEN",
        "BUILD_H_MEAN",
        "BUILD_H_MAX",
        "ROAD_DEN",
        "IN_ANALYSIS_AREA",
        VALID_GIS_MASK_COLUMN,
        MISSING_REASON_COLUMN,
    ]


def test_end_to_end_values_match_source_tables(city_environment: dict[str, Any]) -> None:
    """結合後の値が、算出したパラメータテーブルの値と cell_id 単位で一致する。"""
    _run_param_calculation(city_environment, ["--params", "build_gba", "road_osm"])
    _run_build_dataset(city_environment, ["--tables", "build_gba", "road_osm", "--name", "values"])

    dataset = _read_dataset(city_environment, "values").set_index("cell_id")
    for table_name, column_name in (("build_gba", "BUILD_COV"), ("road_osm", "ROAD_DEN")):
        source = pyogrio.read_dataframe(
            city_environment["root"] / "params" / CITY / f"{TARGET_SCALE}m" / f"{table_name}.gpkg",
            layer=table_name,
            read_geometry=False,
        ).set_index("cell_id")
        np.testing.assert_allclose(
            dataset.loc[source.index, column_name].to_numpy(),
            source[column_name].to_numpy(),
            equal_nan=True,
        )


def test_end_to_end_satellite_table_adds_quality_column(
    city_environment: dict[str, Any],
) -> None:
    """衛星指標テーブルを結合すると VALID_SATELLITE_MASK が導出される。"""
    _run_param_calculation(city_environment, ["--satellite-file", f"data/{SATELLITE_FILE_NAME}"])
    _run_build_dataset(city_environment, ["--tables", SATELLITE_TABLE_NAME, "--name", "satellite"])

    dataset = _read_dataset(city_environment, "satellite")

    assert {"NDVI", "NDBI", "NDWI"}.issubset(set(dataset.columns))
    assert VALID_SATELLITE_MASK_COLUMN in dataset.columns
    assert VALID_GIS_MASK_COLUMN not in dataset.columns


def test_end_to_end_lst_table_adds_no_quality_column(city_environment: dict[str, Any]) -> None:
    """LSTテーブルを結合しても、GIS・衛星いずれの品質管理列も導出されない。

    LSTは目的変数であり、判定材料に混ぜてはならない（方針2）。
    """
    _run_param_calculation(city_environment, ["--lst-file", f"data/{LST_FILE_NAME}"])
    _run_build_dataset(city_environment, ["--tables", LST_TABLE_NAME, "--name", "lst_only"])

    dataset = _read_dataset(city_environment, "lst_only")

    assert {"LST", "LST_VALID_RATIO"}.issubset(set(dataset.columns))
    assert VALID_GIS_MASK_COLUMN not in dataset.columns
    assert VALID_SATELLITE_MASK_COLUMN not in dataset.columns


def test_end_to_end_satellite_only_scenario_with_tables(city_environment: dict[str, Any]) -> None:
    """--scenario satellite_only は idx_* を伴う --tables との併用で結合できる。

    VALID_SATELLITE_MASK は NDVI/NDBI/NDWI のみから決まり、LSTの有無で変わらない
    （方針2・方針4）。
    """
    _run_param_calculation(
        city_environment,
        [
            "--params",
            "mask_roi",
            "--satellite-file",
            f"data/{SATELLITE_FILE_NAME}",
            "--lst-file",
            f"data/{LST_FILE_NAME}",
        ],
    )
    _run_build_dataset(
        city_environment,
        [
            "--scenario",
            "satellite_only",
            "--tables",
            SATELLITE_TABLE_NAME,
            LST_TABLE_NAME,
            "--name",
            "satellite_only_with_lst",
        ],
    )

    dataset = _read_dataset(city_environment, "satellite_only_with_lst")

    assert {"IN_ANALYSIS_AREA", "NDVI", "NDBI", "NDWI", "LST", "LST_VALID_RATIO"}.issubset(
        set(dataset.columns)
    )
    assert VALID_SATELLITE_MASK_COLUMN in dataset.columns
    assert VALID_GIS_MASK_COLUMN not in dataset.columns


def test_end_to_end_scenario_expands_to_tables(city_environment: dict[str, Any]) -> None:
    """--scenario は SCENARIO_TABLES を展開し、シナリオ名で出力する。

    limited は建物・道路・標高に加えて土地被覆・夜間光・人口密度3版を結合する。
    人口は3版とも同時に結合できることを、接尾辞つきの列が揃うことで確認する
    （列名を共有していれば ``join_tables()`` が衝突として拒否するため、
    結合が成立すること自体が接尾辞の効いている証拠になる）。
    """
    _run_param_calculation(city_environment, ["--params", *SCENARIO_TABLES["limited"]])
    _run_build_dataset(city_environment, ["--scenario", "limited"])

    dataset = _read_dataset(city_environment, "limited")

    assert {
        "BUILD_COV",
        "ROAD_DEN",
        "ELEV_MEAN",
        "IN_ANALYSIS_AREA",
        "LULC_BUILT_COV",
        "LULC_TREE_COV",
        "LULC_VALID_RATIO",
        "NTL_MEAN",
        "POP_DEN_WORLDPOP2020",
        "POP_DEN_LANDSCAN2020",
        "POP_DEN_LANDSCAN2023",
    }.issubset(set(dataset.columns))
    # 土地被覆の副ソースは列名を共有する差し替え関係のため、シナリオ展開には含めない。
    assert "lulc_esri2022" not in SCENARIO_TABLES["limited"]
    assert "ntl_bm2023" not in SCENARIO_TABLES["limited"]
    # 標高・土地被覆は VALID_GIS_MASK の判定材料に含めないため、建物・道路が無いセルは0のまま。
    assert (dataset[VALID_GIS_MASK_COLUMN] == 0).any()
    # 人口3版・夜間光それぞれの有効域品質列が導出される（合成データはROI全域を
    # 覆うため、全セルで1になる）。
    assert VALID_NTL_MASK_COLUMN in dataset.columns
    for suffix in ("WORLDPOP2020", "LANDSCAN2020", "LANDSCAN2023"):
        assert valid_population_mask_column(suffix) in dataset.columns
        # 合成データは水域被覆・人口とも欠測を作り込んでいないため、水域優位0補完の
        # フラグ列は存在するが全セル0になる（列自体が結線されていることの確認）。
        assert (dataset[population_filled_flag_column(suffix)] == 0).all()


def test_end_to_end_missing_table_stops_before_writing(
    city_environment: dict[str, Any],
) -> None:
    """一部のテーブルが未算出なら、データセットを1件も書かずに停止する。"""
    _run_param_calculation(city_environment, ["--params", "build_gba"])

    with pytest.raises(FileNotFoundError, match="パラメータテーブルが見つかりません"):
        _run_build_dataset(
            city_environment, ["--tables", "build_gba", "road_osm", "--name", "partial"]
        )

    assert not (city_environment["root"] / "datasets").exists()
