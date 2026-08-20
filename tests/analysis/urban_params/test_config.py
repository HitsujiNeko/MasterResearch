"""config.py（レイヤ構成・出力レイアウトの定義）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.urban_params.config import (
    CITY_CONFIG,
    PARAM_SETS,
    PARAMS_OUTPUT_PARTS,
    POPULATION_BASE_COLUMNS,
    grid_layer_name,
    resolve_table_path,
)

CITY_KEY = "hanoi"


@pytest.mark.parametrize(
    ("table_names", "label"),
    [
        (("build_gba", "build_dc"), "建物"),
        (("road_osm", "road_gt"), "道路"),
        (("ntl_viirs2023", "ntl_bm2023"), "夜間光"),
    ],
)
def test_param_sets_of_same_module_declare_identical_columns(
    table_names: tuple[str, ...], label: str
) -> None:
    """同じモジュールを使う別ソース版は、同じ列名を宣言する。

    感度分析で結合先を差し替えられるという設計の狙いは、この一致に依存する。
    片方の ``columns`` だけを変えても ``validate_computed_columns()`` は個別には
    通るため、列が揃わないことに気づくのは結合フェーズまで遅れる。
    """
    columns = {name: PARAM_SETS[name].columns for name in table_names}
    modules = {PARAM_SETS[name].module_name for name in table_names}

    assert len(modules) == 1, f"{label}の別ソース版が異なるモジュールを指しています: {modules}"
    assert len(set(columns.values())) == 1, f"{label}の別ソース版で列が揃っていません: {columns}"


def _population_param_sets() -> dict[str, object]:
    """人口モジュールを使うパラメータセットを抜き出す。"""
    return {
        name: param_set
        for name, param_set in PARAM_SETS.items()
        if param_set.module_name == "population"
    }


def test_population_param_sets_declare_distinct_columns() -> None:
    """人口の別ソース版は、互いに異なる列名を宣言する。

    建物・道路・夜間光の別ソース版は同一概念の「差し替え候補」であり同名でよい。
    一方、人口の3版は概念（居住人口 / 実効人口）も観測年も異なる**別変数**であり、
    説明力の差が概念差によるものか年差によるものかを分離するには、同一データセットへ
    同時に結合する必要がある。列名が重なると ``build_dataset.py`` の ``join_tables()``
    が衝突として結合を拒否し、この分離ができなくなる。
    """
    population_sets = _population_param_sets()
    assert len(population_sets) >= 2, "人口のパラメータセットが揃っていません"

    owner_of_column: dict[str, str] = {}
    for name, param_set in population_sets.items():
        for column in param_set.columns:
            previous = owner_of_column.get(column)
            assert previous is None, (
                f"人口の別ソース版で列名が重複しています: {column}（{previous} と {name}）"
            )
            owner_of_column[column] = name


def test_population_columns_follow_source_suffix_rule() -> None:
    """人口の宣言列は、基底名へデータソース接尾辞を付けた形になる。

    接尾辞の付与は ``run.py`` の ``apply_column_suffix()`` が行うため、宣言と付与規則が
    食い違うと ``validate_computed_columns()`` が実行時まで検知できない。
    """
    for name, param_set in _population_param_sets().items():
        assert param_set.column_suffix, f"{name} に接尾辞が宣言されていません"
        expected = tuple(f"{base}_{param_set.column_suffix}" for base in POPULATION_BASE_COLUMNS)
        assert param_set.columns == expected, f"{name} の列名が接尾辞規則と一致しません"


def test_param_sets_without_suffix_keep_module_column_names() -> None:
    """接尾辞を宣言しないパラメータセットは、列名をそのまま使う。

    接尾辞は人口のような「同時結合が要る別変数」に限る例外であり、既定は無付与である。
    """
    for name, param_set in PARAM_SETS.items():
        if param_set.module_name == "population":
            continue
        assert param_set.column_suffix == "", f"{name} に想定外の接尾辞があります"


def test_grid_layer_name_matches_canonical_grid_naming() -> None:
    """レイヤ名は canonical_grid が書き出す grid_{scale}m 形式になる。"""
    assert grid_layer_name(30) == "grid_30m"
    assert grid_layer_name(300) == "grid_300m"


def test_resolve_table_path_uses_scale_directory(tmp_path: Path) -> None:
    """出力先は {city}/{scale}m/{テーブル名}.gpkg の階層になる。"""
    path = resolve_table_path("hanoi", 90, "build_gba", base_dir=tmp_path)

    assert path == tmp_path / "hanoi" / "90m" / "build_gba.gpkg"


def test_resolve_table_path_default_root_is_project_relative() -> None:
    """既定の出力ルートは data/output/params 配下（プロジェクトルート基準）になる。"""
    path = resolve_table_path("hanoi", 30, "road_osm")

    assert path.parts[-4:] == ("params", "hanoi", "30m", "road_osm.gpkg")
    assert path.is_absolute()
    assert PARAMS_OUTPUT_PARTS == ("data", "output", "params")


def test_resolve_table_path_separates_sources_by_table_name(tmp_path: Path) -> None:
    """同じ列を持つ別ソースのテーブルが別ファイルへ分かれる。"""
    gba_path = resolve_table_path("hanoi", 30, "build_gba", base_dir=tmp_path)
    dc_path = resolve_table_path("hanoi", 30, "build_dc", base_dir=tmp_path)

    assert gba_path != dc_path
    assert gba_path.parent == dc_path.parent


def test_city_config_declares_analysis_epsg() -> None:
    """都市設定は面積・距離計算に使う投影EPSGを持つ。"""
    assert CITY_CONFIG[CITY_KEY]["analysis_epsg"] == 5897


def test_raster_param_sets_reference_declared_raster_input() -> None:
    """ラスタ入力のパラメータセットは、都市設定に実在する ``rasters`` キーを指す。

    キー名を打ち間違えても、失敗するのは入力解決に到達した実行時である。
    パラメータセットを追加した時点で気づけるよう、宣言どうしの対応を検査する。
    """
    declared_keys = set(CITY_CONFIG[CITY_KEY]["rasters"])
    referenced = {
        name: param_set.input_key
        for name, param_set in PARAM_SETS.items()
        if param_set.input_kind == "raster"
    }

    missing = {name: key for name, key in referenced.items() if key not in declared_keys}
    assert not missing, f"CITY_CONFIG['{CITY_KEY}']['rasters'] に無い入力キーです: {missing}"


def test_raster_param_sets_declare_band_index() -> None:
    """``rasters`` の各エントリはバンド番号を明示する。

    人口ラスタはカウント（band 1）と密度（band 2）を1ファイルに持つため、
    バンド番号の省略は既定値1＝カウントの黙った採用につながる。
    """
    for key, entry in CITY_CONFIG[CITY_KEY]["rasters"].items():
        assert "band" in entry, f"バンド番号が未指定です: {key}"
        assert isinstance(entry["band"], int) and entry["band"] >= 1, (
            f"バンド番号は1以上の整数である必要があります: {key}={entry['band']}"
        )
