"""config.py（レイヤ構成・出力レイアウトの定義）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.urban_params.config import (
    CITY_CONFIG,
    PARAM_SETS,
    PARAMS_OUTPUT_PARTS,
    grid_layer_name,
    resolve_table_path,
)


@pytest.mark.parametrize(
    ("table_names", "label"),
    [
        (("build_gba", "build_dc"), "建物"),
        (("road_osm", "road_gt"), "道路"),
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
    assert CITY_CONFIG["hanoi"]["analysis_epsg"] == 5897
