"""Spatial CV の緩衝帯の影響と、学習量の対照を並べて図にする。

緩衝帯は空間リークと同時に学習量も減らす。そこで「緩衝帯をかけた設定」と「緩衝帯なしで
同じ学習セル数まで間引いた対照」を、合わせた緩衝帯ごとに比べる。2本の線の差が、学習量では
説明できない（近傍の学習セルを失ったことによる）R² の低下を表す。

入力は `src.analysis.diagnose_spatial_cv_design` の ``sweep`` が保存した
``spatial_cv_sweep_summary.csv`` である。集計済みの表から描くだけなので、再計算はしない。
この図は診断スクリプトの来歴の監視対象に含めない別モジュールとして置く（診断スクリプトを
変更すると、掃引の途中結果がコードのダイジェスト不一致で再利用できなくなるため）。

実行例::

    python -m src.visualization.spatial_cv_training_control --summary-csv <集計表のパス>
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SCENARIOS = ("satellite_only", "limited")
MODELS = ("linear", "rf")
OUTPUT_NAME = "spatial_cv_training_control.png"
BUFFERED = "buffered"
THINNED = "thinned"
# 比較の種類ごとの描画設定（色だけに頼らないよう、線種とマーカーも変える）
SERIES_STYLES = {
    BUFFERED: {
        "label": "Buffer applied",
        "color": "#1f77b4",
        "marker": "o",
        "linestyle": "-",
    },
    THINNED: {
        "label": "No buffer, training cells thinned to the same count",
        "color": "#d95f02",
        "marker": "s",
        "linestyle": "--",
    },
}


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Args:
        argv: 引数のリスト。``None`` なら ``sys.argv`` を使う。
    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(description="緩衝帯の影響と学習量の対照を図にする。")
    parser.add_argument(
        "--summary-csv",
        type=Path,
        required=True,
        help="spatial_cv_sweep_summary.csv のパス",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"出力先の PNG（省略時は入力と同じ場所の {OUTPUT_NAME}）",
    )
    return parser.parse_args(argv)


def select_training_control(summary: pd.DataFrame) -> pd.DataFrame:
    """学習量の対照がある設定だけを取り出し、比較用の表にする。

    緩衝帯なし・間引きなしの設定は、緩衝帯 0 の起点として両方の系列に含める。

    Args:
        summary: ``spatial_cv_sweep_summary.csv`` の内容。
    Returns:
        ``series``（``buffered``・``thinned``）・``matched_buffer_m``（合わせた緩衝帯）・
        ``train_share``（緩衝帯なしに対する学習セル数の割合）の列を加えた表。
    Raises:
        ValueError: 対照が無い場合、対照が複数のブロックサイズにある場合、対照に対応する
            緩衝帯の設定が欠けている場合。
    """
    thinned = summary[summary["thinned_to_buffer_m"] > 0]
    block_sizes = thinned["block_size_m"].unique()
    if len(block_sizes) != 1:
        raise ValueError(
            f"学習量の対照はちょうど1つのブロックサイズにある必要があります: {block_sizes}"
        )
    block_table = summary[summary["block_size_m"] == block_sizes[0]]
    matched_buffers = sorted(thinned["thinned_to_buffer_m"].unique())
    plain = block_table[block_table["thinned_to_buffer_m"] == 0]
    buffered = plain[plain["buffer_m"].isin([0.0, *matched_buffers])]
    if set(buffered["buffer_m"]) != {0.0, *matched_buffers}:
        raise ValueError(f"対照に対応する緩衝帯の設定が足りません: {matched_buffers}")
    baseline = plain[plain["buffer_m"] == 0]
    frames = [
        buffered.assign(series=BUFFERED, matched_buffer_m=buffered["buffer_m"]),
        baseline.assign(series=THINNED, matched_buffer_m=0.0),
        thinned.assign(series=THINNED, matched_buffer_m=thinned["thinned_to_buffer_m"]),
    ]
    table = pd.concat(frames, ignore_index=True)
    baseline_size = baseline.set_index("scenario")["train_size"]
    table["train_share"] = table["train_size"] / table["scenario"].map(baseline_size)
    return table.sort_values(["scenario", "series", "matched_buffer_m"], ignore_index=True)


def format_buffer_tick(buffer_m: float, train_share: float) -> str:
    """横軸の目盛りの文字列（緩衝帯と残る学習セルの割合）を作る。

    Args:
        buffer_m: 緩衝帯（m）。
        train_share: 緩衝帯なしに対する学習セル数の割合。
    Returns:
        ``"1.8 km\\n43% train"`` の形式の文字列。
    """
    return f"{buffer_m / 1000:g} km\n{train_share:.0%} train"


def plot_training_control(table: pd.DataFrame, path: Path) -> None:
    """シナリオ・モデルごとに、緩衝帯の設定と学習量の対照の R² を線で並べる。

    Args:
        table: ``select_training_control`` の戻り値。
        path: 保存先（PNG）。
    Returns:
        None
    """
    block_km = table["block_size_m"].iloc[0] / 1000
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, sharey=True)
    for row_no, scenario in enumerate(SCENARIOS):
        data = table[table["scenario"] == scenario]
        ticks = data[data["series"] == BUFFERED].sort_values("matched_buffer_m")
        for col_no, model in enumerate(MODELS):
            ax = axes[row_no, col_no]
            for series, style in SERIES_STYLES.items():
                group = data[data["series"] == series]
                ax.errorbar(
                    group["matched_buffer_m"] / 1000,
                    group[f"{model}_r2"],
                    yerr=group[f"{model}_r2_sd"].fillna(0),
                    capsize=3,
                    linewidth=2,
                    markersize=7,
                    **style,
                )
            ax.set_xticks(ticks["matched_buffer_m"] / 1000)
            ax.set_xticklabels(
                [
                    format_buffer_tick(buffer_m, share)
                    for buffer_m, share in zip(ticks["matched_buffer_m"], ticks["train_share"])
                ]
            )
            ax.tick_params(labelbottom=True)
            ax.set_title(f"{scenario} / {model}")
            ax.grid(alpha=0.3)
    for ax in axes[1]:
        ax.set_xlabel("Matched buffer (training cells kept)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Out-of-fold R2 (fold mean)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False)
    fig.suptitle(f"Effect of the spatial buffer vs. training size (block {block_km:g} km)")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    """集計表を読み、図を保存する。

    Args:
        argv: 引数のリスト。``None`` なら ``sys.argv`` を使う。
    Returns:
        None
    """
    args = parse_arguments(argv)
    output = args.output or args.summary_csv.parent / OUTPUT_NAME
    table = select_training_control(pd.read_csv(args.summary_csv))
    plot_training_control(table, output)
    print(f"図を保存しました: {output}")


if __name__ == "__main__":
    main()
