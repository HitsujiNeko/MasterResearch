"""verify_values.py（旧 wide CSV との値照合）のテスト。

照合の純粋関数（NaN同士の一致判定・保存精度の揃え方・マスクによる行の絞り込み・
集計）を対象とする。実データ（旧 CSV は最大388MB）を用いた照合そのものは、
テストではなく実行時の検証で担保する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

from src.analysis.urban_params import verify_values
from src.analysis.urban_params.geometry import compute_polygon_coverage
from src.analysis.urban_params.grid import grid_centers_wgs84
from src.analysis.urban_params.io import bbox_from_layer, get_layer_resource
from src.analysis.urban_params.run import build_param_tasks
from src.analysis.urban_params.verify_values import (
    COMPARED_COLUMNS,
    LEGACY_MASK_LAYER_KEYS,
    ColumnComparison,
    build_legacy_grid,
    compare_column,
    compare_coordinates,
    compare_values,
    legacy_csv_path,
    parse_arguments,
    select_analysis_rows,
    to_storage_precision,
)
from src.analysis.urban_params.verify_values import main as verify_main

from ..conftest import CITY, FINE_RES_M, SCALES

# ---------------------------------------------------------------------------
# 定数・パス解決
# ---------------------------------------------------------------------------


def test_compared_columns_cover_expected_targets() -> None:
    """照合対象は建物2種（被覆率・棟数密度）と道路である。"""
    assert set(COMPARED_COLUMNS) == {
        "BUILD_COV",
        "BUILD_DEN",
        "ROAD_DEN",
    }
    # 標高は旧 CSV の生成後に算出内容が変わっているため含めない。
    assert "ELEV_MEAN" not in COMPARED_COLUMNS
    # 建物高さは帰属方式の変更（重心方式から重なりベースとの併用へ）により
    # 旧 wide CSV とは設計上必ず不一致になるため含めない。
    assert "BUILD_H_MEAN" not in COMPARED_COLUMNS
    assert "BUILD_H_MAX" not in COMPARED_COLUMNS


def test_legacy_mask_layer_keys_record_old_behavior() -> None:
    """旧実装がシナリオごとに使っていた解析範囲レイヤを保持している。"""
    assert LEGACY_MASK_LAYER_KEYS == {
        "satellite_only": "roi",
        "limited": "roi",
        "full": "rg",
    }


def test_legacy_csv_path_matches_old_naming(tmp_path: Path) -> None:
    """旧 CSV のファイル名規則どおりのパスを返す。"""
    path = legacy_csv_path("limited", "hanoi", 30, base_dir=tmp_path)

    assert path == tmp_path / "urban_params_limited_hanoi_30m.csv"


def test_parse_arguments_defaults_to_exact_match() -> None:
    """既定の許容差は0（完全一致）である。"""
    args = parse_arguments(["--params", "build_gba"])

    assert args.rtol == 0.0
    assert args.atol == 0.0
    assert args.legacy_scenario == "limited"


def test_parse_arguments_requires_params() -> None:
    """--params は必須である。"""
    with pytest.raises(SystemExit):
        parse_arguments([])


# ---------------------------------------------------------------------------
# to_storage_precision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["0.008888889", "15.44849", "680.151001", "4.051491", "1.5555556"],
)
def test_to_storage_precision_recovers_original_float32(text: str) -> None:
    """CSVの10進表記をfloat32へ戻すと、元のfloat32とビット単位で一致する。

    旧 CSV は float32 の値を「float32として往復できる最短の10進表記」で保存して
    いるため、float64のまま比較すると表記由来のずれ（最大で float32 の半ULP）が
    残り、算出値の差と区別できなくなる。
    """
    as_float64 = np.array([float(text)], dtype=np.float64)
    expected_float32 = np.array([text], dtype=np.float32)
    restored = to_storage_precision(as_float64)

    assert restored.dtype == np.float32
    # 保存精度へ揃えれば、元の float32 とビット単位で一致する。
    np.testing.assert_array_equal(restored, expected_float32)
    # float64 のまま比較すると表記由来のずれが残る。これを取り除くのが本関数の
    # 目的であるため、ずれが実際に存在することもテストの前提として固定する。
    assert float(as_float64[0]) != float(expected_float32[0])


def test_to_storage_precision_keeps_nan() -> None:
    """欠測（NaN）は保存精度へ揃えてもNaNのまま保たれる。"""
    restored = to_storage_precision(np.array([np.nan, 1.0], dtype=np.float64))

    assert bool(np.isnan(restored[0]))
    assert restored[1] == np.float32(1.0)


# ---------------------------------------------------------------------------
# compare_values / compare_column
# ---------------------------------------------------------------------------


def test_compare_values_treats_nan_pairs_as_match() -> None:
    """NaN同士は一致として扱う（欠測規約が維持されていることの確認）。"""
    legacy = np.array([np.nan, 1.0, np.nan], dtype=np.float32)
    current = np.array([np.nan, 1.0, 2.0], dtype=np.float32)

    matches = compare_values(legacy, current, rtol=0.0, atol=0.0)

    np.testing.assert_array_equal(matches, np.array([True, True, False]))


def test_compare_values_marks_one_sided_nan_as_mismatch() -> None:
    """片側だけがNaNの場合は不一致とする（欠測規約の変化を見逃さない）。"""
    legacy = np.array([1.0, np.nan], dtype=np.float32)
    current = np.array([np.nan, 2.0], dtype=np.float32)

    matches = compare_values(legacy, current, rtol=0.0, atol=0.0)

    np.testing.assert_array_equal(matches, np.array([False, False]))


def test_compare_values_requires_exact_match_by_default() -> None:
    """許容差0では、1ULPの差も不一致とする。"""
    legacy = np.array([1.0], dtype=np.float32)
    current = np.array([np.nextafter(np.float32(1.0), np.float32(2.0))], dtype=np.float32)

    matches = compare_values(legacy, current, rtol=0.0, atol=0.0)

    assert not bool(matches[0])


def test_compare_values_accepts_within_tolerance() -> None:
    """許容差を与えれば、その範囲内の差は一致として扱える。"""
    legacy = np.array([1.0], dtype=np.float32)
    current = np.array([1.000001], dtype=np.float32)

    matches = compare_values(legacy, current, rtol=0.0, atol=1e-5)

    assert bool(matches[0])


def test_compare_column_aggregates_counts_and_max_difference() -> None:
    """一致・不一致の件数、最大絶対差、片側NaNの件数を集計する。"""
    legacy = np.array([1.0, 2.0, np.nan, 4.0, np.nan], dtype=np.float32)
    current = np.array([1.0, 2.5, np.nan, np.nan, 5.0], dtype=np.float32)

    comparison = compare_column("BUILD_COV", legacy, current, rtol=0.0, atol=0.0)

    assert comparison == ColumnComparison(
        column="BUILD_COV",
        matched=2,
        mismatched=3,
        max_abs_diff=0.5,
        legacy_only_nan=1,
        current_only_nan=1,
    )
    assert not comparison.is_match


def test_compare_column_reports_match_when_all_equal() -> None:
    """全行一致なら is_match が真になり、最大絶対差は0になる。"""
    values = np.array([1.0, np.nan, 3.0], dtype=np.float32)

    comparison = compare_column("ROAD_DEN", values, values.copy(), rtol=0.0, atol=0.0)

    assert comparison.is_match
    assert comparison.max_abs_diff == 0.0
    assert comparison.matched == 3


def test_compare_column_handles_all_nan_columns() -> None:
    """双方が全てNaNの列でも例外にならず、一致として集計される。"""
    values = np.full(3, np.nan, dtype=np.float32)

    comparison = compare_column("BUILD_H_MEAN", values, values.copy(), rtol=0.0, atol=0.0)

    assert comparison.is_match
    assert comparison.max_abs_diff == 0.0


# ---------------------------------------------------------------------------
# select_analysis_rows / compare_coordinates
# ---------------------------------------------------------------------------


def test_select_analysis_rows_keeps_ravel_order() -> None:
    """マスクで絞った結果が ravel() 順（行優先）に並ぶ。

    旧 CSV は解析対象セルのみを ravel 順で保存しているため、同じ並びを再現する。
    """
    columns = {"BUILD_COV": np.arange(6, dtype=np.float32).reshape(2, 3)}
    analysis_mask = np.array([[True, False, True], [False, True, True]])

    selected = select_analysis_rows(columns, analysis_mask)

    np.testing.assert_array_equal(
        selected["BUILD_COV"], np.array([0.0, 2.0, 4.0, 5.0], dtype=np.float32)
    )


def test_select_analysis_rows_applies_same_mask_to_every_column() -> None:
    """複数列に同じマスクが適用され、行数が揃う。"""
    columns = {
        "BUILD_COV": np.arange(4, dtype=np.float32).reshape(2, 2),
        "ROAD_DEN": np.arange(10, 14, dtype=np.float32).reshape(2, 2),
    }
    analysis_mask = np.array([[True, False], [False, True]])

    selected = select_analysis_rows(columns, analysis_mask)

    np.testing.assert_array_equal(selected["BUILD_COV"], np.array([0.0, 3.0], dtype=np.float32))
    np.testing.assert_array_equal(selected["ROAD_DEN"], np.array([10.0, 13.0], dtype=np.float32))


def test_compare_coordinates_returns_max_differences() -> None:
    """経度・緯度それぞれの最大絶対差を返す。"""
    legacy_frame = pd.DataFrame({"lon": [105.0, 105.5], "lat": [21.0, 21.5]})

    lon_diff, lat_diff = compare_coordinates(
        legacy_frame,
        np.array([105.0, 105.5 + 1e-8]),
        np.array([21.0 - 2e-8, 21.5]),
    )

    assert lon_diff == pytest.approx(1e-8, rel=1e-3)
    assert lat_diff == pytest.approx(2e-8, rel=1e-3)


# ---------------------------------------------------------------------------
# 合成データによる照合フロー全体の検証
#
# 値そのものの正しさは実データでの照合が担う。ここで確かめるのは、旧 CSV の
# 特定・行数と座標の突合・列名のサフィックス変換・終了コードといった配管であり、
# これらが壊れると照合結果そのものが信用できなくなる。
# ---------------------------------------------------------------------------


def _write_legacy_csv(
    csv_path: Path,
    city_environment: dict[str, Any],
    scale: int,
    perturb_column: str | None = None,
    drop_last_row: bool = False,
    shift_lon_deg: float = 0.0,
) -> None:
    """合成環境から、旧 run.py と同じ形式の wide CSV を書き出す。

    旧実装が残っていないため、旧BBox原点のグリッドで算出した結果を旧形式へ
    整形して「照合先」を用意する。値の同一性ではなく配管の検証に用いる。

    Args:
        csv_path: 出力先のCSVパス。
        city_environment: 合成データ一式。
        scale: coarseグリッド解像度（m）。
        perturb_column: 値を1件だけずらす列名（不一致の検出を試すときに指定する）。
        drop_last_row: 末尾1行を落とすかどうか（行数不一致を試すときに指定する）。
        shift_lon_deg: 経度をずらす量（度）。座標ずれの検出を試すときに指定する。
    """
    city_cfg = city_environment["city_cfg"]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))
    mask_resource = get_layer_resource(city_cfg, "roi", analysis_crs)
    bbox_analysis = bbox_from_layer(mask_resource, analysis_crs)

    grid_spec = build_legacy_grid(bbox_analysis, analysis_crs, scale, FINE_RES_M)
    tasks = build_param_tasks(["build_gba", "road_osm"], city_cfg, analysis_crs)

    computed: dict[str, np.ndarray] = {}
    for task in tasks:
        computed.update(task.compute(bbox_analysis, grid_spec))

    analysis_mask = compute_polygon_coverage(mask_resource, bbox_analysis, grid_spec) > 0
    selected = select_analysis_rows(computed, analysis_mask)
    lon, lat = grid_centers_wgs84(grid_spec)

    frame = pd.DataFrame(
        {
            "lon": lon.ravel()[analysis_mask.ravel()],
            "lat": lat.ravel()[analysis_mask.ravel()],
            **{f"{name}_{scale}": values for name, values in selected.items()},
        }
    )
    if perturb_column is not None:
        legacy_name = f"{perturb_column}_{scale}"
        frame.loc[0, legacy_name] = np.float32(frame.loc[0, legacy_name]) + np.float32(1.0)
    if drop_last_row:
        frame = frame.iloc[:-1]
    if shift_lon_deg:
        frame["lon"] = frame["lon"] + shift_lon_deg

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _legacy_arguments(scale: int) -> list[str]:
    """合成環境に対する verify_values の引数を組み立てる。"""
    return [
        "--city",
        CITY,
        "--params",
        "build_gba",
        "road_osm",
        "--legacy-scenario",
        "limited",
        "--scales",
        str(scale),
        "--fine-res",
        str(FINE_RES_M),
        "--legacy-dir",
        "legacy",
    ]


def test_main_reports_match_for_identical_values(
    city_environment: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """同じ算出経路で作った旧 CSV と照合すると、全列が一致する。"""
    scale = SCALES[0]
    _write_legacy_csv(
        city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv",
        city_environment,
        scale,
    )

    verify_main(_legacy_arguments(scale))

    output = capsys.readouterr().out
    assert "すべての列が一致しました。" in output
    for column in COMPARED_COLUMNS:
        assert f"  {column}: 一致" in output


def test_main_exits_with_error_on_mismatch(
    city_environment: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """1件でも値が食い違えば、不一致を報告して終了コード1で終わる。"""
    scale = SCALES[0]
    _write_legacy_csv(
        city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv",
        city_environment,
        scale,
        perturb_column="ROAD_DEN",
    )

    with pytest.raises(SystemExit) as exit_info:
        verify_main(_legacy_arguments(scale))

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert "ROAD_DEN: 不一致あり" in output
    assert "不一致のある列:" in output


def test_main_rejects_row_count_mismatch(city_environment: dict[str, Any]) -> None:
    """行数が食い違う場合は、原因の候補を示すValueErrorで停止する。"""
    scale = SCALES[0]
    _write_legacy_csv(
        city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv",
        city_environment,
        scale,
        drop_last_row=True,
    )

    with pytest.raises(ValueError, match="行数が一致しません"):
        verify_main(_legacy_arguments(scale))


def test_main_reports_missing_legacy_csv(city_environment: dict[str, Any]) -> None:
    """旧 CSV が無い場合は、探したパスを示すFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError, match="旧 wide CSV が見つかりません"):
        verify_main(_legacy_arguments(SCALES[0]))


def test_main_rejects_coordinate_drift(city_environment: dict[str, Any]) -> None:
    """座標が許容差を超えてずれている場合は停止する。

    行数が同じでも行の順序が食い違っていれば、別セル同士を比較して「一致」と
    報告しうる。座標の突合はその取り違えを検知するためのガードである。
    """
    scale = SCALES[0]
    csv_path = city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv"
    _write_legacy_csv(csv_path, city_environment, scale, shift_lon_deg=1.0)

    with pytest.raises(ValueError, match="座標が一致しません"):
        verify_main(_legacy_arguments(scale))


def test_main_rejects_run_without_any_row(
    city_environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧 CSV と現行がともに0行の場合は、原因を示して停止する。

    行数の一致確認は通過するため、そのまま進むと座標比較の ``np.max()`` が
    空配列に対して原因の読み取れない例外を出す。何も照合しないまま成功扱いに
    することも避ける。
    """
    scale = SCALES[0]
    csv_path = city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv"
    _write_legacy_csv(csv_path, city_environment, scale)
    # ヘッダだけを残して0行のCSVにする。
    pd.read_csv(csv_path).head(0).to_csv(csv_path, index=False)

    def empty_coverage(_resource: Any, _bbox: Any, grid_spec: Any) -> np.ndarray:
        """解析対象域が1セルも選ばれない状況を模す。"""
        return np.zeros(grid_spec.coarse_shape, dtype=np.float64)

    monkeypatch.setattr(verify_values, "compute_polygon_coverage", empty_coverage)

    with pytest.raises(ValueError, match="照合対象の行が1行もありません"):
        verify_main(_legacy_arguments(scale))


def test_main_rejects_run_without_comparable_columns(city_environment: dict[str, Any]) -> None:
    """照合対象の列を返さないパラメータセットだけを指定した場合は停止する。

    何も検証していないのに「すべて一致」と報告して終了コード0で終わるのが、
    検証ツールとして最も避けたい失敗であるため。
    """
    scale = SCALES[0]
    _write_legacy_csv(
        city_environment["root"] / "legacy" / f"urban_params_limited_{CITY}_{scale}m.csv",
        city_environment,
        scale,
    )

    with pytest.raises(ValueError, match="照合対象の列が1つもありません"):
        verify_main(
            [
                "--city",
                CITY,
                "--params",
                "mask_roi",
                "--legacy-scenario",
                "limited",
                "--scales",
                str(scale),
                "--fine-res",
                str(FINE_RES_M),
                "--legacy-dir",
                "legacy",
            ]
        )
