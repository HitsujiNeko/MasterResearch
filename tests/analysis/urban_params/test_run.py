"""run.py（パラメータセット単位のオーケストレーション）のテスト。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analysis.urban_params import io as urban_params_io
from src.analysis.urban_params.canonical_grid import build_canonical_grid
from src.analysis.urban_params.config import ParamSet
from src.analysis.urban_params.run import (
    ParamTask,
    build_lst_task,
    build_param_tasks,
    build_satellite_task,
    lst_table_name,
    main,
    parse_arguments,
    satellite_table_name,
    validate_computed_columns,
)
from src.analysis.urban_params.tables import aligned_bbox, build_aligned_grid
from src.common.geo_metadata import BBox

from ..conftest import (
    ANALYSIS_CRS,
    ANALYSIS_EPSG,
    CITY,
    FINE_RES_M,
    LST_FILE_NAME,
    LST_TABLE_NAME,
    ROI_BOUNDS,
    SATELLITE_FILE_NAME,
    SATELLITE_TABLE_NAME,
    SCALES,
)

# ---------------------------------------------------------------------------
# satellite_table_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("INDICES_Landsat8_20230707_032329Z.tif", "idx_20230707_032329"),
        ("INDICES_Landsat8_20241130_032336Z.tif", "idx_20241130_032336"),
        ("INDICES_Sentinel2_20230723_032309Z.tiff", "idx_20230723_032309"),
    ],
)
def test_satellite_table_name_derives_observation(file_name: str, expected: str) -> None:
    """ファイル名の観測日時からテーブル名を導く。"""
    assert satellite_table_name(Path(file_name)) == expected


@pytest.mark.parametrize(
    "file_name",
    [
        "indices_20230707.tif",
        "INDICES_Landsat8_20230707Z.tif",
        "INDICES_Landsat8_2023077_032329Z.tif",
        "INDICES_Landsat_8_20230707_032329Z.tif",
        "INDICES_Landsat8_20230707_032329Z.csv",
    ],
)
def test_satellite_table_name_rejects_unparsable_name(file_name: str) -> None:
    """観測を特定できないファイル名は推測せずValueErrorで停止する。"""
    with pytest.raises(ValueError, match="観測日時を特定できません"):
        satellite_table_name(Path(file_name))


# ---------------------------------------------------------------------------
# lst_table_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("LST_Landsat8_20230707_032329Z.tif", "lst_20230707_032329"),
        ("LST_Landsat8_20241130_032336Z.tif", "lst_20241130_032336"),
        ("LST_Sentinel2_20230723_032309Z.tiff", "lst_20230723_032309"),
    ],
)
def test_lst_table_name_derives_observation(file_name: str, expected: str) -> None:
    """ファイル名の観測日時からテーブル名を導く。"""
    assert lst_table_name(Path(file_name)) == expected


@pytest.mark.parametrize(
    "file_name",
    [
        "lst_20230707.tif",
        "LST_Landsat8_20230707Z.tif",
        "LST_Landsat8_2023077_032329Z.tif",
        "LST_Landsat_8_20230707_032329Z.tif",
        "LST_Landsat8_20230707_032329Z.csv",
    ],
)
def test_lst_table_name_rejects_unparsable_name(file_name: str) -> None:
    """観測を特定できないファイル名は推測せずValueErrorで停止する。"""
    with pytest.raises(ValueError, match="観測日時を特定できません"):
        lst_table_name(Path(file_name))


# ---------------------------------------------------------------------------
# parse_arguments
# ---------------------------------------------------------------------------


def test_parse_arguments_requires_params_or_satellite_file() -> None:
    """算出対象を1つも指定しない場合はエラーになる。"""
    with pytest.raises(SystemExit):
        parse_arguments([])


def test_parse_arguments_removes_duplicates() -> None:
    """--scales と --params は重複を除いた一覧に正規化される。"""
    args = parse_arguments(
        ["--params", "build_gba", "build_gba", "road_osm", "--scales", "30", "30", "90"]
    )

    assert args.params == ["build_gba", "road_osm"]
    assert args.scales == [30, 90]


def test_parse_arguments_rejects_non_positive_scale() -> None:
    """0以下のスケールはエラーになる。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--params", "build_gba", "--scales", "0"])


@pytest.mark.parametrize("scale", ["40", "7", "1000"])
def test_parse_arguments_rejects_unsupported_scale(scale: str) -> None:
    """900mの約数でないスケールはCLI段階で弾く（正準グリッドが扱えないため）。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--params", "build_gba", "--scales", scale])


@pytest.mark.parametrize("scale", ["10", "30", "90", "300", "900"])
def test_parse_arguments_accepts_supported_scale(scale: str) -> None:
    """900mの約数であるスケールは受け付ける。"""
    args = parse_arguments(["--params", "build_gba", "--scales", scale])

    assert args.scales == [int(scale)]


def test_parse_arguments_rejects_unknown_param_set() -> None:
    """PARAM_SETS に無いパラメータセット名はエラーになる。"""
    with pytest.raises(SystemExit):
        parse_arguments(["--params", "build_unknown"])


def test_parse_arguments_accepts_satellite_file_only() -> None:
    """衛星指標だけの指定でも受け付ける。"""
    args = parse_arguments(["--satellite-file", "data/satellite/x.tif"])

    assert args.params == []
    assert args.satellite_file == "data/satellite/x.tif"


def test_parse_arguments_accepts_lst_file_only() -> None:
    """LSTだけの指定でも受け付ける。"""
    args = parse_arguments(["--lst-file", "data/satellite/lst/x.tif"])

    assert args.params == []
    assert args.lst_file == "data/satellite/lst/x.tif"


# ---------------------------------------------------------------------------
# validate_computed_columns
# ---------------------------------------------------------------------------


def _dummy_task(expected_columns: tuple[str, ...]) -> ParamTask:
    """列検証だけを試すためのタスクを作る。"""
    return ParamTask("dummy", lambda bbox, grid_spec: {}, expected_columns)


def test_validate_computed_columns_accepts_exact_match() -> None:
    """期待した列と一致すれば例外にならない。"""
    task = _dummy_task(("BUILD_COV", "BUILD_DEN"))

    validate_computed_columns(task, {"BUILD_DEN": np.zeros(1), "BUILD_COV": np.zeros(1)})


@pytest.mark.parametrize(
    ("actual_columns", "message"),
    [
        (("BUILD_COV",), "不足"),
        (("BUILD_COV", "BUILD_DEN", "BUILD_EXTRA"), "余分"),
    ],
)
def test_validate_computed_columns_reports_difference(
    actual_columns: tuple[str, ...], message: str
) -> None:
    """列が食い違う場合は不足・余分を示すValueErrorになる。"""
    task = _dummy_task(("BUILD_COV", "BUILD_DEN"))
    columns = {name: np.zeros(1) for name in actual_columns}

    with pytest.raises(ValueError, match=message):
        validate_computed_columns(task, columns)


# ---------------------------------------------------------------------------
# 合成データによるオーケストレーションの検証
# ---------------------------------------------------------------------------


def _run_main(city_environment: dict[str, Any], extra_args: list[str]) -> None:
    """合成環境に対して main() を実行する。"""
    main(
        [
            "--city",
            CITY,
            "--scales",
            *[str(scale) for scale in SCALES],
            "--fine-res",
            str(FINE_RES_M),
            "--grid",
            city_environment["grid_argument"],
            "--output-dir",
            "out",
            *extra_args,
        ]
    )


def _read_table(output_dir: Path, scale: int, table_name: str):
    """出力したテーブルを読み戻す。"""
    path = output_dir / CITY / f"{scale}m" / f"{table_name}.gpkg"
    return pyogrio.read_dataframe(path, layer=table_name, read_geometry=False)


def test_main_writes_one_table_per_param_set(city_environment: dict[str, Any]) -> None:
    """パラメータセットごとに、スケール別ディレクトリへテーブルが出力される。"""
    _run_main(city_environment, ["--params", "build_gba", "road_osm", "mask_roi"])

    output_dir = city_environment["output_dir"]
    for scale in SCALES:
        for table_name in ("build_gba", "road_osm", "mask_roi"):
            path = output_dir / CITY / f"{scale}m" / f"{table_name}.gpkg"
            assert path.exists(), path


def test_main_output_matches_canonical_cell_ids(city_environment: dict[str, Any]) -> None:
    """出力行は正準グリッドレイヤの cell_id と件数・並びが一致する。"""
    _run_main(city_environment, ["--params", "build_gba"])

    for scale in SCALES:
        table = _read_table(city_environment["output_dir"], scale, "build_gba")
        expected_cell_ids = city_environment["cell_ids_by_scale"][scale]

        assert len(table) == len(expected_cell_ids)
        np.testing.assert_array_equal(table["cell_id"].to_numpy(), expected_cell_ids)


def test_main_output_columns_have_no_scale_suffix(city_environment: dict[str, Any]) -> None:
    """列名にスケールのサフィックスが付かない（スケールはディレクトリで表す）。"""
    _run_main(city_environment, ["--params", "build_gba", "road_osm", "mask_roi"])

    build_table = _read_table(city_environment["output_dir"], 20, "build_gba")
    road_table = _read_table(city_environment["output_dir"], 20, "road_osm")
    mask_table = _read_table(city_environment["output_dir"], 20, "mask_roi")

    assert list(build_table.columns) == [
        "cell_id",
        "BUILD_COV",
        "BUILD_DEN",
        "BUILD_H_MEAN",
        "BUILD_H_MAX",
    ]
    assert list(road_table.columns) == ["cell_id", "ROAD_DEN"]
    assert list(mask_table.columns) == ["cell_id", "IN_ANALYSIS_AREA"]


def test_main_keeps_missing_height_as_null(city_environment: dict[str, Any]) -> None:
    """建物が無いセルの BUILD_H_MEAN は NULL として保持される。"""
    _run_main(city_environment, ["--params", "build_gba"])

    table = _read_table(city_environment["output_dir"], 20, "build_gba")

    assert table["BUILD_H_MEAN"].isna().any()
    # 建物があるセルには値が入る。
    assert table["BUILD_H_MEAN"].notna().any()


def test_main_reads_input_layer_once_across_scales(
    city_environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """複数スケールを1回の実行で出力しても、入力レイヤの読み込みは1回で済む。"""
    counts = {"dataframe": 0, "features": 0}
    original_frame = urban_params_io._read_layer_dataframe_uncached
    original_records = urban_params_io._iter_feature_records_uncached

    def counting_frame(resource: Any, columns: Any) -> Any:
        """建物レイヤの実読み込み回数を数える。"""
        counts["dataframe"] += 1
        return original_frame(resource, columns)

    def counting_records(resource: Any, bbox_analysis: Any) -> Any:
        """道路・ROIレイヤの実読み込み回数を数える。"""
        counts["features"] += 1
        return original_records(resource, bbox_analysis)

    monkeypatch.setattr(urban_params_io, "_read_layer_dataframe_uncached", counting_frame)
    monkeypatch.setattr(urban_params_io, "_iter_feature_records_uncached", counting_records)

    _run_main(city_environment, ["--params", "build_gba", "road_osm", "mask_roi"])

    # 建物1回（2スケール分）。道路とROIで合わせて2回。
    assert counts["dataframe"] == 1
    assert counts["features"] == 2


def test_main_uses_default_output_root_when_not_specified(
    city_environment: dict[str, Any],
) -> None:
    """--output-dir 未指定でも、プロジェクトルート基準の既定パスへ出力される。"""
    main(
        [
            "--city",
            CITY,
            "--params",
            "road_osm",
            "--scales",
            "60",
            "--fine-res",
            str(FINE_RES_M),
            "--grid",
            city_environment["grid_argument"],
        ]
    )

    default_path = (
        city_environment["root"] / "data" / "output" / "params" / CITY / "60m" / "road_osm.gpkg"
    )
    assert default_path.exists()


def test_main_rejects_scale_without_grid_layer_before_writing(
    city_environment: dict[str, Any],
) -> None:
    """グリッドレイヤの無いスケールを含む場合、1件も出力せずに停止する。

    スケールごとの処理に入ってから気づくと、先行するスケールの出力だけが残り、
    どこまでが最新なのか分からなくなる。
    """
    # 45 は900mの約数のためCLI検証は通るが、グリッドは生成していない。
    with pytest.raises(ValueError, match="正準グリッドにレイヤがありません"):
        main(
            [
                "--city",
                CITY,
                "--params",
                "road_osm",
                "--scales",
                "20",
                "45",
                "--fine-res",
                str(FINE_RES_M),
                "--grid",
                city_environment["grid_argument"],
                "--output-dir",
                "out",
            ]
        )

    assert not (city_environment["output_dir"]).exists()


def test_main_rerun_does_not_duplicate_rows(city_environment: dict[str, Any]) -> None:
    """同じコマンドを2回実行しても行数が倍にならない。"""
    _run_main(city_environment, ["--params", "road_osm"])
    first = len(_read_table(city_environment["output_dir"], 20, "road_osm"))

    _run_main(city_environment, ["--params", "road_osm"])
    second = len(_read_table(city_environment["output_dir"], 20, "road_osm"))

    assert first == second


def test_main_writes_elevation_table(city_environment: dict[str, Any]) -> None:
    """ラスタ入力のパラメータセットも同じ枠組みで出力される。"""
    _run_main(city_environment, ["--params", "elev_fabdem"])

    table = _read_table(city_environment["output_dir"], 60, "elev_fabdem")

    assert list(table.columns) == ["cell_id", "ELEV_MEAN", "ELEV_VALID_RATIO"]
    np.testing.assert_allclose(table["ELEV_MEAN"].to_numpy(), 30.0, rtol=1e-5)


def test_main_writes_satellite_table_named_by_observation(
    city_environment: dict[str, Any],
) -> None:
    """衛星指標は観測日時つきのテーブル名で出力される。"""
    _run_main(
        city_environment,
        ["--satellite-file", f"data/{SATELLITE_FILE_NAME}"],
    )

    output_dir = city_environment["output_dir"]
    path = output_dir / CITY / "20m" / f"{SATELLITE_TABLE_NAME}.gpkg"
    assert path.exists()

    table = pyogrio.read_dataframe(path, layer=SATELLITE_TABLE_NAME, read_geometry=False)
    assert set(table.columns) == {"cell_id", "NDVI", "NDBI", "NDWI"}


def test_main_writes_lst_table_named_by_observation(
    city_environment: dict[str, Any],
) -> None:
    """LSTは観測日時つきのテーブル名で出力される。"""
    _run_main(
        city_environment,
        ["--lst-file", f"data/{LST_FILE_NAME}"],
    )

    output_dir = city_environment["output_dir"]
    path = output_dir / CITY / "20m" / f"{LST_TABLE_NAME}.gpkg"
    assert path.exists()

    table = pyogrio.read_dataframe(path, layer=LST_TABLE_NAME, read_geometry=False)
    assert set(table.columns) == {"cell_id", "LST", "LST_VALID_RATIO"}


def test_build_param_tasks_binds_each_resource_independently(
    city_environment: dict[str, Any],
) -> None:
    """複数タスクを作っても、各タスクが自分の入力とモジュールを保持する。

    ループ内で定義したクロージャが最後の変数を共有する（遅延束縛）と、すべての
    タスクが同じパラメータを算出してしまう。その退行を防ぐための検証である。
    """
    tasks = build_param_tasks(
        ["build_gba", "road_osm", "mask_roi"], city_environment["city_cfg"], ANALYSIS_CRS
    )

    assert [task.table_name for task in tasks] == ["build_gba", "road_osm", "mask_roi"]

    canonical = build_canonical_grid(BBox(*ROI_BOUNDS), ANALYSIS_CRS, 20.0)
    grid_spec = build_aligned_grid(canonical, FINE_RES_M)
    bbox = aligned_bbox(canonical)

    computed = [set(task.compute(bbox, grid_spec)) for task in tasks]
    assert computed[0] == {"BUILD_COV", "BUILD_DEN", "BUILD_H_MEAN", "BUILD_H_MAX"}
    assert computed[1] == {"ROAD_DEN"}
    assert computed[2] == {"IN_ANALYSIS_AREA"}


def test_build_param_tasks_resolves_all_inputs_before_running(
    city_environment: dict[str, Any],
) -> None:
    """入力が解決できないパラメータセットがあれば、タスク組み立ての時点で失敗する。"""
    city_cfg = dict(city_environment["city_cfg"])
    city_cfg["layers"] = dict(city_cfg["layers"])
    city_cfg["layers"]["dc"] = {
        "path": "data/missing.gpkg",
        "layer": "data",
        "crs_epsg": ANALYSIS_EPSG,
    }

    with pytest.raises(FileNotFoundError):
        build_param_tasks(["build_gba", "build_dc"], city_cfg, ANALYSIS_CRS)


def test_build_satellite_task_missing_file_raises(tmp_path: Path) -> None:
    """存在しない衛星指標ファイルはFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError):
        build_satellite_task(tmp_path / SATELLITE_FILE_NAME)


def test_build_satellite_task_without_indices_raises(tmp_path: Path) -> None:
    """指標を1つも検出できないラスタはValueErrorになる。"""
    path = tmp_path / SATELLITE_FILE_NAME
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0.0, 20.0, 10.0, 10.0),
    ) as dst:
        dst.write(np.zeros((2, 2), dtype=np.float32), 1)

    with pytest.raises(ValueError, match="衛星指標を検出できませんでした"):
        build_satellite_task(path)


# ---------------------------------------------------------------------------
# build_lst_task
# ---------------------------------------------------------------------------


def _write_single_band_raster(path: Path, description: str | None, band_count: int = 1) -> None:
    """バンド説明・バンド数を指定した合成ラスタを書き出す（LSTのバンド検証用）。"""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=band_count,
        dtype="float32",
        crs=ANALYSIS_CRS,
        transform=from_origin(0.0, 20.0, 10.0, 10.0),
    ) as dst:
        for band_index in range(1, band_count + 1):
            dst.write(np.full((2, 2), 30.0, dtype=np.float32), band_index)
        if description is not None:
            dst.set_band_description(1, description)


def test_build_lst_task_missing_file_raises(tmp_path: Path) -> None:
    """存在しないLSTファイルはFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError):
        build_lst_task(tmp_path / LST_FILE_NAME)


def test_build_lst_task_rejects_multiple_bands(tmp_path: Path) -> None:
    """バンド数が1でないLSTラスタはValueErrorになる。

    指標側は io.find_satellite_rasters() でバンド説明を検証しているが、LST側は
    単一バンド前提の入力であり、同じ検証を経由しない。誤って多バンドのラスタを
    渡した場合に気づけるよう、ここで個別に検証する。
    """
    path = tmp_path / LST_FILE_NAME
    _write_single_band_raster(path, "LST", band_count=2)

    with pytest.raises(ValueError, match="バンド数が1ではありません"):
        build_lst_task(path)


def test_build_lst_task_rejects_mismatched_band_description(tmp_path: Path) -> None:
    """バンド説明が設定されていて LST 以外の場合はValueErrorになる。"""
    path = tmp_path / LST_FILE_NAME
    _write_single_band_raster(path, "NDVI")

    with pytest.raises(ValueError, match="バンド説明が想定と異なります"):
        build_lst_task(path)


def test_build_lst_task_accepts_missing_band_description(tmp_path: Path) -> None:
    """バンド説明が未設定の場合は通す（正常なLSTを誤って弾かないため）。"""
    path = tmp_path / LST_FILE_NAME
    _write_single_band_raster(path, None)

    task = build_lst_task(path)

    assert task.table_name == lst_table_name(path)


def test_build_lst_task_accepts_lst_band_description(tmp_path: Path) -> None:
    """バンド説明が LST の場合は通す。"""
    path = tmp_path / LST_FILE_NAME
    _write_single_band_raster(path, "LST")

    task = build_lst_task(path)

    assert task.expected_columns == ("LST", "LST_VALID_RATIO")


def test_build_lst_task_accepts_lowercase_lst_band_description(tmp_path: Path) -> None:
    """バンド説明が小文字表記（lst）でも大文字小文字を無視して受け入れる。"""
    path = tmp_path / LST_FILE_NAME
    _write_single_band_raster(path, "lst")

    task = build_lst_task(path)

    assert task.expected_columns == ("LST", "LST_VALID_RATIO")


def test_param_set_columns_match_computed_columns(city_environment: dict[str, Any]) -> None:
    """PARAM_SETS の宣言列と compute() の実際の出力列が一致する。

    宣言が実装から乖離すると、感度分析で結合先を差し替えたときに列が揃わない。
    """
    canonical = build_canonical_grid(BBox(*ROI_BOUNDS), ANALYSIS_CRS, 20.0)
    grid_spec = build_aligned_grid(canonical, FINE_RES_M)
    bbox = aligned_bbox(canonical)

    for table_name in ("build_gba", "road_osm", "mask_roi", "elev_fabdem"):
        task = build_param_tasks([table_name], city_environment["city_cfg"], ANALYSIS_CRS)[0]
        validate_computed_columns(task, task.compute(bbox, grid_spec))


def test_param_set_dataclass_is_immutable() -> None:
    """パラメータセット定義は変更できない（実行中の書き換えを防ぐ）。"""
    param_set = ParamSet("buildings", "layer", "open_buildings", ("BUILD_COV",))

    # 例外型を絞る。Exception のままだと、frozen でなくなった後に別の理由で失敗
    # するようになってもテストが通り続け、不変性の保証を検証できない。
    with pytest.raises(FrozenInstanceError):
        param_set.input_key = "dc"  # type: ignore[misc]
