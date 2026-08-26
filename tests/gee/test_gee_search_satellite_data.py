"""gee_search_satellite_data.py（観測選定指標の実効ROIカバー率）のテスト。

GEEへの接続を伴わない純粋関数（実効ROIカバー率の算出・再ランキング）のみを
対象とし、`ee` 関連のシーン探索処理はテスト対象外とする。
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

import src.gee.gee_search_satellite_data as search


def test_calculate_effective_roi_coverage_converts_units() -> None:
    """0-1のシーン被覆率と0-100の有効ピクセル率から0-100の実効カバー率を得る。"""
    effective_roi_coverage = search.calculate_effective_roi_coverage(
        scene_coverage_ratio=0.5, valid_pixel_ratio=80.0
    )

    assert effective_roi_coverage == pytest.approx(40.0)


@pytest.mark.parametrize(
    ("scene_coverage_ratio", "valid_pixel_ratio"),
    [
        (None, 80.0),
        (0.5, None),
        (float("nan"), 80.0),
        (0.5, float("nan")),
    ],
)
def test_calculate_effective_roi_coverage_handles_missing_values(
    scene_coverage_ratio: float | None, valid_pixel_ratio: float | None
) -> None:
    """欠損（None/NaN）入力はNaNとして扱い、誤った実数値を返さない。"""
    effective_roi_coverage = search.calculate_effective_roi_coverage(
        scene_coverage_ratio=scene_coverage_ratio, valid_pixel_ratio=valid_pixel_ratio
    )

    assert math.isnan(effective_roi_coverage)


def test_build_effective_roi_coverage_result_selects_minimum() -> None:
    """選定キーはLST側・指標側の実効カバー率の最小値である。"""
    result = search.build_effective_roi_coverage_result(
        scene_coverage_ratio=0.5,
        lst_valid_pixel_ratio=90.0,
        indices_valid_pixel_ratio=80.0,
    )

    assert result["lst_effective_roi_coverage"] == pytest.approx(45.0)
    assert result["indices_effective_roi_coverage"] == pytest.approx(40.0)
    assert result["effective_roi_coverage"] == pytest.approx(40.0)


def test_build_effective_roi_coverage_result_propagates_nan() -> None:
    """LST・指標のどちらかが欠損している場合、選定キーもNaNとし過大評価しない。"""
    result = search.build_effective_roi_coverage_result(
        scene_coverage_ratio=0.5,
        lst_valid_pixel_ratio=float("nan"),
        indices_valid_pixel_ratio=80.0,
    )

    assert math.isnan(result["effective_roi_coverage"])


def test_add_effective_roi_coverage_columns_preserves_row_order() -> None:
    """列を追加するだけで、既存の行順は変更しない。"""
    results_df = pd.DataFrame(
        {
            "observation_datetime_utc": ["2023-01-01T00:00:00", "2023-01-02T00:00:00"],
            "scene_coverage_ratio": [0.9, 0.5],
            "lst_valid_pixel_ratio": [90.0, 95.0],
            "indices_valid_pixel_ratio": [80.0, 60.0],
        }
    )

    augmented_df = search.add_effective_roi_coverage_columns(results_df)

    assert list(augmented_df["observation_datetime_utc"]) == [
        "2023-01-01T00:00:00",
        "2023-01-02T00:00:00",
    ]
    assert augmented_df.loc[0, "effective_roi_coverage"] == pytest.approx(72.0)
    assert augmented_df.loc[1, "effective_roi_coverage"] == pytest.approx(30.0)


def test_add_effective_roi_coverage_columns_handles_empty_dataframe() -> None:
    """0行のDataFrameでもKeyErrorを送出せず、空の3列を追加して返す。"""
    empty_df = pd.DataFrame(
        columns=["scene_coverage_ratio", "lst_valid_pixel_ratio", "indices_valid_pixel_ratio"]
    )

    augmented_df = search.add_effective_roi_coverage_columns(empty_df)

    assert len(augmented_df) == 0
    assert list(augmented_df.columns) == [
        "scene_coverage_ratio",
        "lst_valid_pixel_ratio",
        "indices_valid_pixel_ratio",
        "lst_effective_roi_coverage",
        "indices_effective_roi_coverage",
        "effective_roi_coverage",
    ]


def test_add_effective_roi_coverage_columns_raises_when_required_column_missing() -> None:
    """必須列が欠けている場合は、生のKeyErrorではなく日本語メッセージのValueErrorを送出する。"""
    results_df = pd.DataFrame({"observation_datetime_utc": ["2023-01-01T00:00:00"]})

    with pytest.raises(ValueError, match="scene_coverage_ratio"):
        search.add_effective_roi_coverage_columns(results_df)


def test_run_rerank_only_updates_results_and_writes_sorted_ranking(tmp_path: Path) -> None:
    """結果CSVは行順維持のまま列追加、ランキングCSVは降順に並べ替えて出力する。"""
    results_csv_path = tmp_path / "results.csv"
    ranking_csv_path = tmp_path / "ranking.csv"
    pd.DataFrame(
        {
            "observation_datetime_utc": [
                "2023-07-07T03:23:05",
                "2023-07-07T03:23:29",
                "2024-11-30T03:23:36",
            ],
            "scene_coverage_ratio": [0.934884, 0.525702, 0.940320],
            "lst_valid_pixel_ratio": [95.571404, 99.600128, 99.903376],
            "indices_valid_pixel_ratio": [94.901696, 99.572892, 99.909538],
        }
    ).to_csv(results_csv_path, index=False, encoding="utf-8")

    search.run_rerank_only(results_csv_path=results_csv_path, ranking_csv_path=ranking_csv_path)

    updated_results_df = pd.read_csv(results_csv_path)
    assert list(updated_results_df["observation_datetime_utc"]) == [
        "2023-07-07T03:23:05",
        "2023-07-07T03:23:29",
        "2024-11-30T03:23:36",
    ]
    assert "effective_roi_coverage" in updated_results_df.columns

    ranked_df = pd.read_csv(ranking_csv_path)
    assert list(ranked_df["observation_datetime_utc"]) == [
        "2024-11-30T03:23:36",
        "2023-07-07T03:23:05",
        "2023-07-07T03:23:29",
    ]
    assert ranked_df["effective_roi_coverage"].is_monotonic_decreasing


def test_run_rerank_only_preserves_existing_column_precision(tmp_path: Path) -> None:
    """既定の高速CSVパーサーによる丸めが発生せず、既存列の値をそのまま保持する。

    pandas.read_csv はデフォルト（非 round-trip）パーサーだと、倍精度浮動小数点の
    最終桁が入力テキストと異なる値に丸められることがある。既存行は変更しない
    という要件のため、round-trip精度での読み込みを検証する。
    """
    results_csv_path = tmp_path / "results.csv"
    # デフォルトパーサーでは丸めが生じる、桁数の多い値を用いる。
    precise_value = "0.009340830889155879"
    results_csv_path.write_text(
        "observation_datetime_utc,scene_coverage_ratio,lst_valid_pixel_ratio,"
        "indices_valid_pixel_ratio\n"
        f"2023-01-05T03:17:38,{precise_value},0.0,0.0\n",
        encoding="utf-8",
    )

    search.run_rerank_only(
        results_csv_path=results_csv_path, ranking_csv_path=tmp_path / "ranking.csv"
    )

    updated_text = results_csv_path.read_text(encoding="utf-8")
    assert precise_value in updated_text


def test_run_rerank_only_raises_when_results_csv_missing(tmp_path: Path) -> None:
    """探索結果CSVが存在しない場合は明示的に例外を送出する。"""
    missing_csv_path = tmp_path / "not_found.csv"

    with pytest.raises(FileNotFoundError):
        search.run_rerank_only(
            results_csv_path=missing_csv_path,
            ranking_csv_path=tmp_path / "ranking.csv",
        )


def test_parse_arguments_accepts_rerank_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """--rerank-only / --ranking-csv-path が正しく解析される。"""
    monkeypatch.setattr(
        "sys.argv",
        [
            "gee_search_satellite_data.py",
            "--rerank-only",
            "--ranking-csv-path",
            "custom_ranking.csv",
        ],
    )

    args = search.parse_arguments()

    assert args.rerank_only is True
    assert args.ranking_csv_path == Path("custom_ranking.csv")


def test_main_dispatches_to_rerank_only_without_calling_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--rerank-only 指定時はGEE接続を伴う run() を呼ばず、rerank専用処理へ分岐する。"""
    calls: dict[str, object] = {}
    monkeypatch.setattr("sys.argv", ["gee_search_satellite_data.py", "--rerank-only"])
    monkeypatch.setattr(
        search,
        "run_rerank_only",
        lambda results_csv_path, ranking_csv_path: calls.__setitem__(
            "rerank_only", (results_csv_path, ranking_csv_path)
        ),
    )
    monkeypatch.setattr(search, "run", lambda **kwargs: calls.__setitem__("run", kwargs))

    search.main()

    assert "rerank_only" in calls
    assert "run" not in calls


def test_main_dispatches_to_run_when_rerank_only_not_specified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--rerank-only 未指定時は従来通り run()（探索処理）へ分岐する。"""
    calls: dict[str, object] = {}
    monkeypatch.setattr("sys.argv", ["gee_search_satellite_data.py"])
    monkeypatch.setattr(
        search,
        "run_rerank_only",
        lambda **kwargs: calls.__setitem__("rerank_only", kwargs),
    )
    monkeypatch.setattr(search, "run", lambda **kwargs: calls.__setitem__("run", kwargs))

    search.main()

    assert "run" in calls
    assert "rerank_only" not in calls
