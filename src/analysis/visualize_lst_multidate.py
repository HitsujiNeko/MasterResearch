"""複数観測日のLST分布をmatplotlibで可視化する。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data/csv/analysis/satellite_only_multidate_lst_violin.png"
DEFAULT_SAMPLE_PATHS = [
    PROJECT_ROOT / "data/csv/analysis/satellite_only_20230707_20230707_032329Z_sample_100000.csv",
    PROJECT_ROOT / "data/csv/analysis/satellite_only_20230723_20230723_032309Z_sample_100000.csv",
    PROJECT_ROOT / "data/csv/analysis/satellite_only_20241130_20241130_032336Z_sample_100000.csv",
]
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data/csv/analysis/satellite_only_multidate_summary.csv"
COLORS = ["#232a8f", "#35d31f", "#f0aa1c"]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""

    parser = argparse.ArgumentParser(description="Create a multi-date LST violin plot.")
    parser.add_argument(
        "--sample-paths",
        nargs="+",
        type=Path,
        default=DEFAULT_SAMPLE_PATHS,
        help="Paths to sampled dataset CSV files used for violin plots.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Path to the multidate summary CSV used for mean LST markers.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path for the PNG figure.",
    )
    return parser.parse_args()


def extract_date_label(sample_path: Path) -> str:
    """サンプルCSVファイル名から観測日ラベルを生成する。"""

    stem_parts = sample_path.stem.split("_")
    raw_date = stem_parts[2]
    return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"


def load_lsts(sample_path: Path) -> np.ndarray:
    """サンプルCSVからLST列のみを読み込む。"""

    return pd.read_csv(sample_path, usecols=["LST"])["LST"].dropna().to_numpy()


def load_mean_lsts(summary_path: Path) -> dict[str, float]:
    """要約CSVから平均LSTを辞書として読み込む。"""

    summary_df = pd.read_csv(summary_path, usecols=["date", "lst_mean_c"])
    return dict(zip(summary_df["date"], summary_df["lst_mean_c"], strict=True))


def annotate_summary_stats(
    ax: plt.Axes,
    x_position: int,
    values: np.ndarray,
    mean_value: float,
) -> None:
    """最小値・最大値・平均値を注記する。"""

    min_value = float(np.min(values))
    max_value = float(np.max(values))

    ax.text(x_position, max_value + 0.35, f"{max_value:.2f}", ha="center", va="bottom", fontsize=8, color="black")
    ax.text(x_position, min_value - 0.35, f"{min_value:.2f}", ha="center", va="top", fontsize=8, color="black")
    ax.text(x_position, mean_value, f"{mean_value:.2f}", ha="center", va="center", fontsize=8, color="red", fontweight="bold")


def create_violin_plot(
    sample_paths: list[Path],
    mean_lsts: dict[str, float],
    output_path: Path,
) -> None:
    """LST分布のバイオリンプロットを作成して保存する。"""

    labels = [extract_date_label(sample_path) for sample_path in sample_paths]
    lst_arrays = [load_lsts(sample_path) for sample_path in sample_paths]
    plot_means = [float(mean_lsts[label]) for label in labels]

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    violin = ax.violinplot(
        lst_arrays,
        positions=np.arange(1, len(lst_arrays) + 1),
        widths=0.75,
        showmeans=False,
        showmedians=False,
        showextrema=False,
    )

    for body, color in zip(violin["bodies"], COLORS, strict=True):
        body.set_facecolor(color)
        body.set_edgecolor("black")
        body.set_alpha(0.65)
        body.set_linewidth(0.7)

    for index, (values, mean_value) in enumerate(zip(lst_arrays, plot_means, strict=True), start=1):
        min_value = float(np.min(values))
        max_value = float(np.max(values))
        ax.scatter(index, min_value, color="black", s=12, zorder=3)
        ax.scatter(index, max_value, color="red", s=12, zorder=3)
        ax.scatter(index, mean_value, color="blue", s=12, zorder=3)
        annotate_summary_stats(ax=ax, x_position=index, values=values, mean_value=mean_value)

    ax.scatter([], [], color="black", s=12, label="Min")
    ax.scatter([], [], color="red", s=12, label="Max")
    ax.scatter([], [], color="blue", s=12, label="Mean")

    ax.set_xticks(np.arange(1, len(labels) + 1), labels, rotation=40, ha="right")
    ax.set_xlabel("Observation date")
    ax.set_ylabel("Temperature (°C)")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper right", frameon=False, fontsize=8)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def main() -> None:
    """スクリプトのエントリーポイント。"""

    args = parse_args()
    sample_paths = [path if path.is_absolute() else PROJECT_ROOT / path for path in args.sample_paths]
    summary_path = args.summary_path if args.summary_path.is_absolute() else PROJECT_ROOT / args.summary_path
    output_path = args.output_path if args.output_path.is_absolute() else PROJECT_ROOT / args.output_path

    mean_lsts = load_mean_lsts(summary_path)
    create_violin_plot(sample_paths=sample_paths, mean_lsts=mean_lsts, output_path=output_path)


if __name__ == "__main__":
    main()
