"""水域データの食い違いを地図にする（全域の一致数マップと、代表地点の拡大図）。

入力は `src.analysis.compare_water_sources` が保存するセル単位の水域マスク GeoTIFF
（30m 正準グリッド・EPSG:5897。値は 0: 非水域、1: 水域、255: 無効）である。

- 全域図: 主要な水域判定のうち何種類が「水域」としたかをセルごとに色分けする。
  いずれかの判定が無効なセルは灰色にする（有効域を ROI 全体と同一視しないため）。
- 拡大図: 代表地点（都心の湖沼・紅河の砂州・郊外の養殖池や水田）ごとに、GLC と他データの
  ペアを「両方水域・GLC のみ・相手のみ・両方非水域・無効」の 5 区分で示す。

背景地図は重ねない（マスクと Web タイルで座標系が異なり、描画のたびにネットワークへ
依存するため）。場所の判読は、マスク GeoTIFF を QGIS で背景地図と重ねて行う。

実行例::

    python -m src.visualization.water_source_disagreement_map
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  # バックエンド指定の後に読み込む
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from pyproj import Transformer  # noqa: E402

from src.common.config import PROJECT_ROOT  # noqa: E402
from src.common.paths import prepare_output_path  # noqa: E402

DEFAULT_LABEL = "hanoi_20220906"
DEFAULT_MASK_PATH = (
    PROJECT_ROOT / "data" / "gis" / "water" / "comparison" / f"water_masks_{DEFAULT_LABEL}.tif"
)
# GIS 図の置き場所（Git 追跡）。取得データの図は images/gis_data/{カテゴリ}/ に置く慣行に合わせる
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "images" / "gis_data" / "water"

# マスク GeoTIFF の値（compare_water_sources と同じ）
MASK_WATER = 1
MASK_NODATA = 255

# 全域図で一致数を数える水域判定（バンド名）と表示名。JRC 月次（2021-09）は入れない。
# 月次は縞状の欠測が全域に広がり（Landsat 7 の走査線欠損と見られるが未確認）、
# 「すべて有効なセル」に絞ると全域図の大半が灰色になるため。月次は拡大図で示す
OVERVIEW_KEYS: tuple[str, ...] = ("glc", "esri", "jrc_occ50", "mndwi_+0.00")
LAYER_LABELS: dict[str, str] = {
    "glc": "GLC 2022",
    "esri": "Esri 2022",
    "jrc_occ50": "JRC Occurrence ≥50%",
    "jrc_monthly": "JRC 2021-09",
    "mndwi_+0.00": "MNDWI ≥0（2022-09-06）",
}
# 拡大図で GLC と比べる相手
ZOOM_PARTNERS: tuple[str, ...] = ("esri", "jrc_occ50", "jrc_monthly", "mndwi_+0.00")

# ペア比較の区分
PAIR_NEITHER = 0
PAIR_BOTH = 1
PAIR_A_ONLY = 2
PAIR_B_ONLY = 3
PAIR_INVALID = 4
PAIR_COLORS = ("#f2f2f2", "#1f4e9c", "#e08b2c", "#3fae7a", "#b0b0b0")
PAIR_LABELS = ("両方非水域", "両方水域", "GLC のみ水域", "相手のみ水域", "無効")

# 和文フォントの候補（先頭から順に、インストールされているものを使う）
JAPANESE_FONT_CANDIDATES: tuple[str, ...] = ("Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP")

FIGURE_DPI = 200

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZoomWindow:
    """拡大図の 1 地点。

    Attributes:
        key: 識別子。
        label: 表示名。
        lon: 中心の経度（WGS84）。
        lat: 中心の緯度（WGS84）。
        half_size_m: 中心から窓の端までの距離（m）。
        rationale: この地点を選んだ理由。
    """

    key: str
    label: str
    lon: float
    lat: float
    half_size_m: float
    rationale: str


# 代表地点。都心と紅河の窓は重ならないように置く（紅河の窓の左下にタイ湖が入る）。
# 郊外の地点は、試算で「Esri のみ水域」「MNDWI のみ水域」「GLC のみ水域」のセルが
# いずれも最も集中した 4.5km 区画の中心（ハノイ南部）である。地物（養殖池・水田など）は
# 背景地図で確かめていない
DEFAULT_WINDOWS: tuple[ZoomWindow, ...] = (
    ZoomWindow(
        key="urban_lakes",
        label="都心の湖沼（ホアンキエム湖周辺）",
        lon=105.835,
        lat=21.020,
        half_size_m=3000.0,
        rationale="都心の小規模な湖沼の検出の差を見る",
    ),
    ZoomWindow(
        key="red_river",
        label="紅河の河道と砂州（タイ湖の北東）",
        lon=105.845,
        lat=21.080,
        half_size_m=3000.0,
        rationale="季節によって冠水・露出する砂州の扱いの差を見る",
    ),
    ZoomWindow(
        key="southern_suburb",
        label="南部郊外（食い違いの集中区画）",
        lon=105.827,
        lat=20.716,
        half_size_m=3000.0,
        rationale="食い違いが最も集中する郊外の区画としてデータから選んだ（地物は未確認）",
    ),
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(description="水域データの食い違いを地図にする。")
    parser.add_argument("--mask-path", type=Path, default=DEFAULT_MASK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=DEFAULT_LABEL, help="出力ファイル名に使う識別子。")
    return parser.parse_args()


def configure_japanese_font() -> str | None:
    """インストールされている和文フォントを matplotlib の既定にする。

    Returns:
        設定したフォント名。候補が無い場合は None（文字化けの可能性を警告する）。
    """
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for name in JAPANESE_FONT_CANDIDATES:
        if name in installed:
            plt.rcParams["font.family"] = [name, "DejaVu Sans"]
            return name
    logger.warning("和文フォントが見つかりません。図の日本語が表示されない可能性があります。")
    return None


def read_mask_raster(mask_path: Path) -> tuple[dict[str, np.ndarray], rasterio.Affine, str]:
    """水域マスク GeoTIFF を読み、バンド名 → 配列の辞書にする。

    Args:
        mask_path: 水域マスク GeoTIFF。

    Returns:
        (バンド名 → 配列, アフィン変換, CRS の文字列)。

    Raises:
        FileNotFoundError: ファイルが無い場合。
        ValueError: バンド名（説明）が設定されていない場合。
    """
    if not mask_path.exists():
        raise FileNotFoundError(f"水域マスクが見つかりません: {mask_path}")
    with rasterio.open(mask_path) as source:
        names = source.descriptions
        if any(name is None for name in names):
            raise ValueError(f"バンド名が設定されていないバンドがあります: {mask_path}")
        masks = {name: source.read(index) for index, name in enumerate(names, start=1)}
        return masks, source.transform, source.crs.to_string()


def count_water_sources(masks: dict[str, np.ndarray], keys: tuple[str, ...]) -> np.ma.MaskedArray:
    """セルごとに、何種類の判定が水域としたかを数える。

    Args:
        masks: バンド名 → マスク配列。
        keys: 数える判定のバンド名。

    Returns:
        一致数（0〜len(keys)）。いずれかの判定が無効なセルはマスクする。

    Raises:
        KeyError: ``keys`` にマスクに無いバンド名がある場合。
    """
    missing = [key for key in keys if key not in masks]
    if missing:
        raise KeyError(f"水域マスクに無いバンドがあります: {missing}")
    stacked = np.stack([masks[key] for key in keys])
    invalid = np.any(stacked == MASK_NODATA, axis=0)
    counts = np.sum(stacked == MASK_WATER, axis=0)
    return np.ma.masked_array(counts, mask=invalid)


def classify_pair(mask_a: np.ndarray, mask_b: np.ndarray) -> np.ndarray:
    """2 つの判定を「両方非水域・両方水域・A のみ・B のみ・無効」の 5 区分にする。

    Args:
        mask_a: 判定 A のマスク配列。
        mask_b: 判定 B のマスク配列。

    Returns:
        区分（``PAIR_*``）の配列。
    """
    water_a = mask_a == MASK_WATER
    water_b = mask_b == MASK_WATER
    classes = np.full(mask_a.shape, PAIR_NEITHER, dtype=np.uint8)
    classes[water_a & water_b] = PAIR_BOTH
    classes[water_a & ~water_b] = PAIR_A_ONLY
    classes[~water_a & water_b] = PAIR_B_ONLY
    classes[(mask_a == MASK_NODATA) | (mask_b == MASK_NODATA)] = PAIR_INVALID
    return classes


def window_slices(
    window: ZoomWindow, transform: rasterio.Affine, crs: str, shape: tuple[int, int]
) -> tuple[slice, slice]:
    """拡大図の窓を、配列の行・列の範囲へ変換する（配列の外にはみ出す分は切り詰める）。

    Args:
        window: 拡大図の地点。
        transform: マスクのアフィン変換（投影座標系・北が上）。
        crs: マスクの CRS。
        shape: 配列の形状 (行数, 列数)。

    Returns:
        (行の範囲, 列の範囲)。

    Raises:
        ValueError: 窓が配列と重ならない場合。
    """
    to_mask_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    center_x, center_y = to_mask_crs.transform(window.lon, window.lat)
    inverse = ~transform
    col_start, row_start = inverse * (center_x - window.half_size_m, center_y + window.half_size_m)
    col_stop, row_stop = inverse * (center_x + window.half_size_m, center_y - window.half_size_m)
    rows = slice(max(int(np.floor(row_start)), 0), min(int(np.ceil(row_stop)), shape[0]))
    cols = slice(max(int(np.floor(col_start)), 0), min(int(np.ceil(col_stop)), shape[1]))
    if rows.start >= rows.stop or cols.start >= cols.stop:
        raise ValueError(f"拡大図の窓 {window.key} が水域マスクの範囲と重なりません。")
    return rows, cols


def plot_overview(
    masks: dict[str, np.ndarray],
    transform: rasterio.Affine,
    crs: str,
    windows: tuple[ZoomWindow, ...],
    output_path: Path,
) -> Path:
    """全域の一致数マップを描き、拡大図の窓を枠で示す。

    Args:
        masks: バンド名 → マスク配列。
        transform: マスクのアフィン変換。
        crs: マスクの CRS。
        windows: 拡大図の地点（枠を描く）。
        output_path: 出力 PNG。

    Returns:
        出力パス。
    """
    counts = count_water_sources(masks, OVERVIEW_KEYS)
    height, width = counts.shape
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    level_count = len(OVERVIEW_KEYS)
    colors = ["#ffffff"] + list(plt.get_cmap("Blues")(np.linspace(0.3, 1.0, level_count)))
    cmap = ListedColormap(colors)
    cmap.set_bad("#c8c8c8")
    norm = BoundaryNorm(np.arange(-0.5, level_count + 1), cmap.N)

    figure, axes = plt.subplots(figsize=(7.5, 8.5))
    axes.imshow(
        counts, cmap=cmap, norm=norm, extent=(left, right, bottom, top), interpolation="nearest"
    )
    to_mask_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    for window in windows:
        x, y = to_mask_crs.transform(window.lon, window.lat)
        size = window.half_size_m
        axes.add_patch(
            plt.Rectangle((x - size, y - size), 2 * size, 2 * size, fill=False, color="red", lw=1.2)
        )
        axes.annotate(window.label.split("（")[0], (x + size, y + size), color="red", fontsize=8)
    _draw_scalebar(axes, left, bottom, 10_000.0, "10 km")
    axes.set_axis_off()
    legend_items = [Patch(facecolor=colors[0], edgecolor="#999999", label="0（どれも非水域）")]
    legend_items += [
        Patch(facecolor=colors[count], label=f"{count} 種類が水域")
        for count in range(1, level_count + 1)
    ]
    legend_items.append(Patch(facecolor="#c8c8c8", label="いずれかが無効"))
    axes.legend(handles=legend_items, loc="lower right", fontsize=8, framealpha=0.9)
    axes.set_title(
        "水域と判定したデータの数（30m セル）\n対象: "
        + "・".join(LAYER_LABELS[k] for k in OVERVIEW_KEYS),
        fontsize=9,
    )
    figure.tight_layout()
    figure.savefig(output_path, dpi=FIGURE_DPI)
    plt.close(figure)
    return output_path


def plot_zoom_panels(
    masks: dict[str, np.ndarray],
    transform: rasterio.Affine,
    crs: str,
    windows: tuple[ZoomWindow, ...],
    output_path: Path,
) -> Path:
    """代表地点ごとに、GLC と各データのペア区分を並べて描く（行: 地点、列: 相手）。

    Args:
        masks: バンド名 → マスク配列。
        transform: マスクのアフィン変換。
        crs: マスクの CRS。
        windows: 拡大図の地点。
        output_path: 出力 PNG。

    Returns:
        出力パス。
    """
    cmap = ListedColormap(PAIR_COLORS)
    norm = BoundaryNorm(np.arange(-0.5, len(PAIR_COLORS)), cmap.N)
    figure, axes_grid = plt.subplots(
        len(windows),
        len(ZOOM_PARTNERS),
        figsize=(3.0 * len(ZOOM_PARTNERS), 3.2 * len(windows)),
        squeeze=False,
    )
    for row_index, window in enumerate(windows):
        rows, cols = window_slices(window, transform, crs, masks["glc"].shape)
        for col_index, partner in enumerate(ZOOM_PARTNERS):
            axes = axes_grid[row_index][col_index]
            classes = classify_pair(masks["glc"][rows, cols], masks[partner][rows, cols])
            axes.imshow(classes, cmap=cmap, norm=norm, interpolation="nearest")
            axes.set_xticks([])
            axes.set_yticks([])
            if row_index == 0:
                axes.set_title(f"GLC vs {LAYER_LABELS[partner]}", fontsize=8)
            if col_index == 0:
                axes.set_ylabel(window.label, fontsize=8)
    figure.legend(
        handles=[
            Patch(facecolor=color, edgecolor="#999999", label=label)
            for color, label in zip(PAIR_COLORS, PAIR_LABELS)
        ],
        loc="lower center",
        ncol=len(PAIR_COLORS),
        fontsize=8,
    )
    window_km = 2 * windows[0].half_size_m / 1000
    figure.suptitle(
        f"GLC と他データの水域の食い違い（各図 {window_km:.0f} km 四方・30m セル）",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.97))
    figure.savefig(output_path, dpi=FIGURE_DPI)
    plt.close(figure)
    return output_path


def _draw_scalebar(axes: plt.Axes, left: float, bottom: float, length_m: float, text: str) -> None:
    """地図の左下に縮尺のバーを描く（投影座標系のメートル単位を前提とする）。

    Args:
        axes: 描画先。
        left: 地図の左端の X 座標。
        bottom: 地図の下端の Y 座標。
        length_m: バーの長さ（m）。
        text: バーの注記。
    """
    x0 = left + 3_000.0
    y0 = bottom + 3_000.0
    axes.plot([x0, x0 + length_m], [y0, y0], color="black", lw=2)
    axes.text(x0 + length_m / 2, y0 + 800.0, text, ha="center", fontsize=8)


def run(mask_path: Path, output_dir: Path, label: str) -> tuple[Path, Path]:
    """マスクを読み、全域図と拡大図を保存する。

    Args:
        mask_path: 水域マスク GeoTIFF。
        output_dir: 出力先ディレクトリ。
        label: 出力ファイル名の識別子。

    Returns:
        (全域図のパス, 拡大図のパス)。
    """
    font = configure_japanese_font()
    logger.info("和文フォント: %s", font)
    masks, transform, crs = read_mask_raster(mask_path)
    overview_path = prepare_output_path(
        output_dir / f"water_sources_disagreement_{label}_overview.png"
    )
    zoom_path = prepare_output_path(output_dir / f"water_sources_disagreement_{label}_zoom.png")
    plot_overview(masks, transform, crs, DEFAULT_WINDOWS, overview_path)
    plot_zoom_panels(masks, transform, crs, DEFAULT_WINDOWS, zoom_path)
    return overview_path, zoom_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    overview_path, zoom_path = run(args.mask_path, args.output_dir, args.label)
    print(f"全域図を保存しました: {overview_path}")
    print(f"拡大図を保存しました: {zoom_path}")


if __name__ == "__main__":
    main()
