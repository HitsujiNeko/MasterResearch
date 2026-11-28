"""visualize_lst_multidate.py（複数観測日の LST 分布のバイオリン図）のテスト。

実データ（サンプル CSV・要約 CSV）は使わず、小さな CSV を一時ディレクトリに書いて、
ラベルの抽出・読み込み・図の出力を確かめる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis import visualize_lst_multidate as target

# 実データと同じ命名規則のサンプル CSV 名（3 番目の要素が観測日）
SAMPLE_NAMES = [
    "satellite_only_20230707_20230707_032329Z_sample_100000.csv",
    "satellite_only_20230723_20230723_032309Z_sample_100000.csv",
    "satellite_only_20241130_20241130_032336Z_sample_100000.csv",
]
DATE_LABELS = ["2023-07-07", "2023-07-23", "2024-11-30"]


def _write_inputs(directory: Path) -> tuple[list[Path], Path]:
    """サンプル CSV 3 つと要約 CSV を書き出す。

    Args:
        directory: 出力先。

    Returns:
        (サンプル CSV のパスの一覧, 要約 CSV のパス)。
    """
    directory.mkdir(parents=True, exist_ok=True)
    sample_paths = []
    for index, name in enumerate(SAMPLE_NAMES):
        path = directory / name
        pd.DataFrame(
            {"LST": [30.0 + index, 32.0 + index, np.nan, 35.0 + index], "NDVI": [0.1] * 4}
        ).to_csv(path, index=False)
        sample_paths.append(path)
    summary_path = directory / "summary.csv"
    pd.DataFrame({"date": DATE_LABELS, "lst_mean_c": [32.3, 33.3, 34.3]}).to_csv(
        summary_path, index=False
    )
    return sample_paths, summary_path


def test_extract_date_label_formats_third_element() -> None:
    """ファイル名の 3 番目の要素（YYYYMMDD）を YYYY-MM-DD のラベルにする。"""
    assert target.extract_date_label(Path(SAMPLE_NAMES[0])) == "2023-07-07"


def test_load_lsts_reads_lst_column_without_missing(tmp_path: Path) -> None:
    """サンプル CSV から LST 列だけを読み、欠損を除く。"""
    sample_paths, _ = _write_inputs(tmp_path)

    values = target.load_lsts(sample_paths[0])

    np.testing.assert_array_equal(values, [30.0, 32.0, 35.0])


def test_load_mean_lsts_maps_date_to_mean(tmp_path: Path) -> None:
    """要約 CSV を、観測日から平均 LST への辞書として読む。"""
    _, summary_path = _write_inputs(tmp_path)

    assert target.load_mean_lsts(summary_path) == dict(zip(DATE_LABELS, [32.3, 33.3, 34.3]))


def test_create_violin_plot_writes_png(tmp_path: Path) -> None:
    """3 観測日のバイオリン図を、出力先のディレクトリを作って PNG で保存する。"""
    sample_paths, summary_path = _write_inputs(tmp_path)
    output_path = tmp_path / "figure" / "violin.png"

    target.create_violin_plot(sample_paths, target.load_mean_lsts(summary_path), output_path)

    assert output_path.read_bytes().startswith(b"\x89PNG")


def test_create_violin_plot_requires_mean_for_each_date(tmp_path: Path) -> None:
    """要約 CSV に無い観測日があれば、図を作らずに例外にする。"""
    sample_paths, _ = _write_inputs(tmp_path)
    output_path = tmp_path / "violin.png"

    with pytest.raises(KeyError, match="2024-11-30"):
        target.create_violin_plot(
            sample_paths, {"2023-07-07": 32.3, "2023-07-23": 33.3}, output_path
        )
    assert not output_path.exists()


def test_main_resolves_relative_paths_against_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """相対パスの引数をプロジェクトルート基準で解決して図を書き出す。"""
    _write_inputs(tmp_path / "inputs")
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "visualize_lst_multidate",
            "--sample-paths",
            *[f"inputs/{name}" for name in SAMPLE_NAMES],
            "--summary-path",
            "inputs/summary.csv",
            "--output-path",
            "out/violin.png",
        ],
    )

    target.main()

    assert (tmp_path / "out" / "violin.png").is_file()
