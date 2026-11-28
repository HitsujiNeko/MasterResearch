"""スクリプトの既定値が、共通定数への置き換えの前後で変わらないことのテスト。

主採用観測の ID と公開GISデータのサマリーの出力先は `src/common/config.py` の定数から
組み立てる。組み立て方を誤ると、出力先や読み込むデータセットが黙って変わってしまうため、
置き換え前の文字列（プロジェクトルートからの相対パス）と突き合わせる。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from src.common.config import (
    DEFAULT_OPEN_GIS_OUTPUT_DIR,
    PRIMARY_OBSERVATION_ID,
    PROJECT_ROOT,
)

# (モジュール, 定数名, 置き換え前の値（プロジェクトルートからの相対パス）)
PATH_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "src.analysis.analysis_rq3_limited",
        "DEFAULT_DATASET_PATH",
        "data/output/datasets/dataset_limited_20220906_032358_hanoi_30m.gpkg",
    ),
    (
        "src.analysis.analysis_rq3_limited",
        "DEFAULT_OUTPUT_DIR",
        "data/output/limited/20220906_032358",
    ),
    (
        "src.analysis.analysis_rq3_satellite_only",
        "DEFAULT_DATASET_PATH",
        "data/output/datasets/dataset_satellite_only_20220906_032358_hanoi_30m.gpkg",
    ),
    (
        "src.analysis.analysis_rq3_satellite_only",
        "DEFAULT_OUTPUT_DIR",
        "data/output/satellite_only_cellbased/20220906_032358",
    ),
    (
        "src.analysis.build_water_sensitivity_datasets",
        "DEFAULT_SUMMARY_PATH",
        "data/output/limited/20220906_032358_water_sensitivity/"
        "water_sensitivity_datasets_results.json",
    ),
    (
        "src.analysis.compare_water_sensitivity",
        "DEFAULT_OUTPUT_DIR",
        "data/output/limited/20220906_032358_water_sensitivity",
    ),
    (
        "src.analysis.compare_water_sources",
        "DEFAULT_DATASET_PATH",
        "data/output/datasets/dataset_limited_20220906_032358_hanoi_30m.gpkg",
    ),
    ("src.analysis.compare_water_sources", "DEFAULT_OUTPUT_DIR", "data/output/open_gis"),
    ("src.analysis.compare_lulc_esri_glc", "DEFAULT_OUTPUT_DIR", "data/output/open_gis"),
    (
        "src.analysis.compare_nighttime_lights_viirs_blackmarble",
        "DEFAULT_SUMMARY_DIR",
        "data/output/open_gis",
    ),
    (
        "src.analysis.compare_population_worldpop_landscan",
        "DEFAULT_SUMMARY_PATH",
        "data/output/open_gis/population_worldpop_landscan_hanoi_2020_summary.json",
    ),
    ("src.preprocessing.black_marble.pipeline", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
    (
        "src.preprocessing.extract_geofabrik_roads_hanoi",
        "DEFAULT_SUMMARY_PATH",
        "data/output/open_gis/hanoi_osm_roads_summary.json",
    ),
    ("src.preprocessing.fetch_esri_lulc_hanoi", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
    (
        "src.preprocessing.fetch_gba_buildings_hanoi",
        "DEFAULT_SUMMARY_PATH",
        "data/output/open_gis/hanoi_gba_buildings_summary.json",
    ),
    ("src.preprocessing.fetch_glc_fcs30d_hanoi", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
    ("src.preprocessing.fetch_jrc_gsw_hanoi", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
    ("src.preprocessing.fetch_population_hanoi", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
    ("src.preprocessing.fetch_viirs_dnb_hanoi", "DEFAULT_SUMMARY_DIR", "data/output/open_gis"),
)


def test_shared_constant_values() -> None:
    """共通定数の値が、置き換え前に各ファイルへ直書きされていた値と同じである。"""
    assert PRIMARY_OBSERVATION_ID == "20220906_032358"
    assert DEFAULT_OPEN_GIS_OUTPUT_DIR == PROJECT_ROOT / "data" / "output" / "open_gis"


@pytest.mark.parametrize(("module_name", "attribute", "relative_path"), PATH_DEFAULTS)
def test_path_defaults_are_unchanged(module_name: str, attribute: str, relative_path: str) -> None:
    """各スクリプトの既定のパスが、置き換え前と同じ場所を指す。"""
    module = importlib.import_module(module_name)

    assert getattr(module, attribute) == PROJECT_ROOT / Path(relative_path)


def test_summarize_rq2_default_observation_is_unchanged() -> None:
    """RQ2 の集計の既定の観測が、置き換え前と同じ主採用観測である。"""
    module = importlib.import_module("src.analysis.summarize_rq2_scale_area")

    assert module.DEFAULT_OBSERVATION == "20220906_032358"


def test_compare_observations_default_runs_are_unchanged() -> None:
    """観測の比較の既定のランのうち、主採用観測の 2 件が置き換え前と同じである。"""
    module = importlib.import_module("src.analysis.compare_observations")

    primary_runs = [
        (run.observation, run.scenario, run.results_path.as_posix())
        for run in module.DEFAULT_RUNS[:2]
    ]
    assert primary_runs == [
        (
            "20220906_032358",
            "satellite_only",
            "data/output/satellite_only_cellbased/20220906_032358/"
            "dataset_satellite_only_20220906_032358_hanoi_30m_results.json",
        ),
        (
            "20220906_032358",
            "limited",
            "data/output/limited/20220906_032358/"
            "dataset_limited_20220906_032358_hanoi_30m_both_bh_mean_wi_none_results.json",
        ),
    ]


# (モジュール, 引数名, 置き換え前の既定値（プロジェクトルートからの相対パス）)。
# 引数のリストを受け取れる parse_arguments を持ち、必須の引数が無いものに限る
CLI_PATH_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "src.analysis.analysis_rq3_limited",
        "dataset_path",
        "data/output/datasets/dataset_limited_20220906_032358_hanoi_30m.gpkg",
    ),
    (
        "src.analysis.analysis_rq3_satellite_only",
        "dataset_path",
        "data/output/datasets/dataset_satellite_only_20220906_032358_hanoi_30m.gpkg",
    ),
    (
        "src.analysis.build_water_sensitivity_datasets",
        "summary_path",
        "data/output/limited/20220906_032358_water_sensitivity/"
        "water_sensitivity_datasets_results.json",
    ),
)


@pytest.mark.parametrize(("module_name", "argument", "relative_path"), CLI_PATH_DEFAULTS)
def test_cli_path_defaults_are_unchanged(
    module_name: str, argument: str, relative_path: str
) -> None:
    """引数を指定しないときの CLI の既定のパスが、置き換え前と同じ場所を指す。"""
    module = importlib.import_module(module_name)

    args = module.parse_arguments([])

    assert getattr(args, argument) == PROJECT_ROOT / Path(relative_path)


def test_summarize_rq2_cli_default_observation_is_unchanged() -> None:
    """RQ2 の集計の CLI で、観測を指定しないときは置き換え前と同じ主採用観測を使う。"""
    module = importlib.import_module("src.analysis.summarize_rq2_scale_area")

    assert module.parse_arguments([]).observation == "20220906_032358"
