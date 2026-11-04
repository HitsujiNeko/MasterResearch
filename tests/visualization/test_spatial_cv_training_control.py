"""src/visualization/spatial_cv_training_control.py のテスト。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.visualization.spatial_cv_training_control import (
    BUFFERED,
    OUTPUT_NAME,
    SCENARIOS,
    THINNED,
    format_buffer_tick,
    main,
    select_training_control,
)

METRICS = ("linear_r2", "linear_r2_sd", "rf_r2", "rf_r2_sd")
# (block_size_m, buffer_m, thinned_to_buffer_m, train_size)
CONFIGS = (
    (2700, 0.0, 0.0, 1000.0),
    (2700, 900.0, 0.0, 700.0),
    (2700, 1800.0, 0.0, 400.0),
    (2700, 0.0, 900.0, 700.0),
    (2700, 0.0, 1800.0, 400.0),
    (5400, 0.0, 0.0, 1000.0),
    (5400, 900.0, 0.0, 800.0),
)


def _summary() -> pd.DataFrame:
    """掃引の集計表を模した表を作る。"""
    rows = []
    for scenario in SCENARIOS:
        for block_size_m, buffer_m, thinned_m, train_size in CONFIGS:
            rows.append(
                {
                    "block_size_m": block_size_m,
                    "buffer_m": buffer_m,
                    "thinned_to_buffer_m": thinned_m,
                    "scenario": scenario,
                    "train_size": train_size,
                    **{metric: 0.5 for metric in METRICS},
                }
            )
    return pd.DataFrame(rows)


class TestSelectTrainingControl:
    """対照の比較表の作成を検証する。"""

    def test_keeps_only_block_with_control(self) -> None:
        """対照のあるブロックサイズだけを残す。"""
        table = select_training_control(_summary())
        assert set(table["block_size_m"]) == {2700}

    def test_both_series_share_baseline_and_matched_buffers(self) -> None:
        """両系列とも緩衝帯 0 を起点に、合わせた緩衝帯の点を同じ数だけ持つ。"""
        table = select_training_control(_summary())
        for scenario in SCENARIOS:
            data = table[table["scenario"] == scenario]
            for series in (BUFFERED, THINNED):
                matched = data.loc[data["series"] == series, "matched_buffer_m"]
                assert matched.tolist() == [0.0, 900.0, 1800.0]

    def test_train_share_is_relative_to_no_buffer(self) -> None:
        """学習セルの割合は緩衝帯なしの学習セル数を基準にする。"""
        table = select_training_control(_summary())
        shares = table.loc[
            (table["scenario"] == "limited") & (table["series"] == BUFFERED), "train_share"
        ]
        assert shares.tolist() == pytest.approx([1.0, 0.7, 0.4])

    def test_rejects_summary_without_control(self) -> None:
        """対照が無い表は例外にする。"""
        summary = _summary()
        with pytest.raises(ValueError, match="ちょうど1つ"):
            select_training_control(summary[summary["thinned_to_buffer_m"] == 0])

    def test_rejects_control_on_multiple_blocks(self) -> None:
        """対照が複数のブロックサイズにある表は例外にする（線が混ざるため）。"""
        summary = _summary()
        extra = summary[summary["thinned_to_buffer_m"] > 0].assign(block_size_m=5400)
        with pytest.raises(ValueError, match="ちょうど1つ"):
            select_training_control(pd.concat([summary, extra], ignore_index=True))

    def test_rejects_missing_buffered_config(self) -> None:
        """対照に対応する緩衝帯の設定が無い表は例外にする。"""
        summary = _summary()
        lacking = summary[~((summary["block_size_m"] == 2700) & (summary["buffer_m"] == 1800))]
        with pytest.raises(ValueError, match="足りません"):
            select_training_control(lacking)


def test_format_buffer_tick() -> None:
    """目盛りは緩衝帯（km）と学習セルの割合を2行で表す。"""
    assert format_buffer_tick(1800.0, 0.4327) == "1.8 km\n43% train"


class TestMain:
    """コマンド全体を検証する。"""

    def test_writes_figure_next_to_summary(self, tmp_path: Path) -> None:
        """出力先を省略すると、入力と同じ場所に図を保存する。"""
        summary_path = tmp_path / "spatial_cv_sweep_summary.csv"
        _summary().to_csv(summary_path, index=False)
        main(["--summary-csv", str(summary_path)])
        assert (tmp_path / OUTPUT_NAME).is_file()

    def test_writes_figure_to_given_output(self, tmp_path: Path) -> None:
        """出力先を指定できる。"""
        summary_path = tmp_path / "spatial_cv_sweep_summary.csv"
        _summary().to_csv(summary_path, index=False)
        output = tmp_path / "figure.png"
        main(["--summary-csv", str(summary_path), "--output", str(output)])
        assert output.is_file()
