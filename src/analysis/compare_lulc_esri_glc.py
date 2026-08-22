"""GLC_FCS30D（30m・35クラス）と Esri 10m LULC（10m・9クラス）の空間的一致度を評価する。

分類済み LULC を説明変数として使う前に、独立した別プロダクトとクロスチェックし、
特に不透水面（市街地）の抽出結果が整合するかを確認する。

方法上の要点:
- 解像度が異なる（30m と 10m）ため、GLC_FCS30D のグリッドを基準に揃える。
  GLC のセルを縦横 3 分割した細分グリッド（≒10m 相当・原点は GLC と一致）へ Esri を
  **最近傍**で再投影し、各 GLC セルに対応する 3x3 = 9 サブセルの**多数決**で集約する。
  カテゴリ値のため線形補間は使わない。
- 細分グリッドは GLC グリッドと厳密に 3x3 対応する（原点一致・整数分割）。ただし
  **Esri のソース画素と細分セルは一致しない**。Esri 出力の画素サイズは
  `calculate_default_transform` が決めた 10m 相当の度数（約 9.279e-05 度）で、
  細分セル（GLC の 1/3、約 8.983e-05 度）より約 3.3% 粗い。そのため一部のサブセルが
  隣接サブセルと同じソース画素を複製し、多数決の票の重みは完全には均一にならない
  （1 ブロックが参照する実 Esri 画素は平均約 8.4 個）。系統的にどれかのクラスへ
  偏る性質のものではないが、集約は近似である。
- ダウンサンプリングにより、10m でしか現れない少数クラスは失われる。
- 両者はクラス体系の粒度が異なる（35 対 9）ため、直接比較せず共通クラスへ写像して比較する。
- どちらも真値ではないため、精度（accuracy）ではなく**一致度（agreement）**として扱い、
  一方を基準にした指標には「GLC 基準」「Esri 基準」と明示した名前を使う。
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import reproject

from src.common.config import DEFAULT_HANOI_ROI_PATH, PROJECT_ROOT
from src.common.lulc_classes import (
    COMMON_BUILT,
    COMMON_CLASS_LABELS,
    COMMON_INVALID,
    ESRI_TO_COMMON,
    GLC_TO_COMMON,
    map_to_common_classes,
)
from src.common.paths import to_project_relative_string
from src.common.roi import load_roi_geometry
from src.common.summary import save_summary
from src.preprocessing.fetch_esri_lulc_hanoi import CLASS_LABELS as ESRI_CLASS_LABELS
from src.preprocessing.fetch_esri_lulc_hanoi import FILLED_VALUES as ESRI_FILLED_VALUES
from src.preprocessing.fetch_glc_fcs30d_hanoi import CLASS_LABELS as GLC_CLASS_LABELS
from src.preprocessing.fetch_glc_fcs30d_hanoi import FILLED_VALUES as GLC_FILLED_VALUES

DEFAULT_GLC_PATH = (
    PROJECT_ROOT / "data" / "gis" / "lulc" / "glc_fcs30d" / "glc_fcs30d_hanoi_2022.tif"
)
DEFAULT_ESRI_PATH = PROJECT_ROOT / "data" / "gis" / "lulc" / "esri_10m" / "esri_lulc_hanoi_2022.tif"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"

# GLC の 30m セルを何分割して Esri を評価するか（30m / 3 = 10m でネイティブ解像度に一致）
SUBDIVISION_FACTOR = 3

# 共通クラス体系・写像表（GLC_TO_COMMON・ESRI_TO_COMMON・COMMON_CLASS_LABELS）は
# `src/analysis/urban_params/params/lulc.py` と共用するため `src.common.lulc_classes`
# へ切り出した（上記 import）。

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: 解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="GLC_FCS30D と Esri 10m LULC の空間的一致度を評価する。"
    )
    parser.add_argument(
        "--glc-path",
        type=Path,
        default=DEFAULT_GLC_PATH,
        help="GLC_FCS30D の GeoTIFF パス（比較の基準グリッド）。",
    )
    parser.add_argument(
        "--esri-path",
        type=Path,
        default=DEFAULT_ESRI_PATH,
        help="Esri 10m LULC の GeoTIFF パス。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="サマリー JSON パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    parser.add_argument(
        "--confusion-path",
        type=Path,
        default=None,
        help="混同行列 CSV パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    parser.add_argument(
        "--label",
        default="hanoi_2022",
        help="出力ファイル名に使う識別子。",
    )
    return parser.parse_args()


def subdivided_transform(transform: Affine, factor: int) -> Affine:
    """アフィン変換を、画素を縦横 factor 分割した細分グリッドのものへ変換する。

    原点（左上隅）は変えず、画素サイズだけを 1/factor にする。これにより元グリッドの
    1 セルが細分グリッドの factor x factor セルと厳密に対応する。

    Args:
        transform (Affine): 元グリッドのアフィン変換。
        factor (int): 分割数（1 以上）。

    Returns:
        Affine: 細分グリッドのアフィン変換。

    Raises:
        ValueError: factor が 1 未満の場合。
    """
    if factor < 1:
        raise ValueError(f"分割数は 1 以上である必要があります: {factor}")
    return transform * Affine.scale(1.0 / factor, 1.0 / factor)


def majority_vote_blocks(
    array: np.ndarray,
    factor: int,
    invalid_values: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """factor x factor のブロックごとに最頻値（多数決）を取る。

    無効値はブロック内の投票から除外する。有効値が 1 つも無いブロックは 0（無効）にする。
    最頻値が複数ある場合は**クラス値の小さい方**を採る（実行ごとに結果が変わらないように
    決定的な規則を置く）。同数最頻となったブロックは呼び出し側で数えられるよう別に返す。

    Args:
        array (np.ndarray): 細分グリッドのクラス値配列（形状は factor の倍数であること）。
        factor (int): ブロックの一辺の画素数。
        invalid_values (tuple[int, ...]): 投票から除外する無効値。

    Returns:
        tuple[np.ndarray, np.ndarray]:
            (多数決後のクラス値配列, 同数最頻だったブロックを True とする真偽値配列)。

    Raises:
        ValueError: 配列の形状が factor で割り切れない場合。
    """
    height, width = array.shape
    if height % factor != 0 or width % factor != 0:
        raise ValueError(f"配列の形状 {array.shape} が分割数 {factor} で割り切れません。")

    out_height = height // factor
    out_width = width // factor
    # (out_height, out_width, factor * factor) へ並べ替え、最後の軸をブロック内の画素にする
    blocks = array.reshape(out_height, factor, out_width, factor)
    blocks = blocks.transpose(0, 2, 1, 3).reshape(out_height, out_width, factor * factor)

    class_values = np.array(sorted(set(np.unique(array).tolist()) - set(invalid_values)), dtype=int)
    if class_values.size == 0:
        empty = np.zeros((out_height, out_width), dtype=array.dtype)
        return empty, np.zeros((out_height, out_width), dtype=bool)

    # クラスごとの得票数を数える。class_values は昇順なので argmax は最小クラス値を選ぶ。
    # 得票数の上限は factor * factor なので、それを表現できる最小の符号なし整数型を使い、
    # 大きなラスタでもメモリを抑える（桁溢れすると多数決の結果が静かに壊れるため型は必ず選ぶ）。
    count_dtype = np.uint8 if factor * factor <= np.iinfo(np.uint8).max else np.uint32
    counts = np.stack(
        [(blocks == value).sum(axis=2, dtype=count_dtype) for value in class_values],
        axis=2,
    )
    max_counts = counts.max(axis=2)
    winner_index = counts.argmax(axis=2)
    voted = class_values[winner_index].astype(array.dtype)

    has_valid = max_counts > 0
    is_tied = (counts == max_counts[:, :, None]).sum(axis=2) > 1
    voted = np.where(has_valid, voted, 0).astype(array.dtype)
    return voted, np.logical_and(is_tied, has_valid)


def resample_esri_to_subgrid(
    esri_path: Path,
    reference_transform: Affine,
    reference_crs: Any,
    reference_width: int,
    reference_height: int,
    factor: int,
    nodata: int,
) -> np.ndarray:
    """Esri ラスタを、基準グリッドを factor 分割した細分グリッドへ最近傍で再投影する。

    Args:
        esri_path (Path): Esri ラスタのパス。
        reference_transform (Affine): 基準グリッドのアフィン変換。
        reference_crs (Any): 基準グリッドの CRS。
        reference_width (int): 基準グリッドの幅（画素）。
        reference_height (int): 基準グリッドの高さ（画素）。
        factor (int): 分割数。
        nodata (int): 出力の無効値。

    Returns:
        np.ndarray: 細分グリッド上の Esri クラス値配列。
    """
    destination = np.full(
        (reference_height * factor, reference_width * factor), nodata, dtype=np.uint8
    )
    with rasterio.open(esri_path) as source:
        reproject(
            source=rasterio.band(source, 1),
            destination=destination,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=subdivided_transform(reference_transform, factor),
            dst_crs=reference_crs,
            src_nodata=source.nodata if source.nodata is not None else nodata,
            dst_nodata=nodata,
            resampling=Resampling.nearest,
        )
    return destination


def build_confusion_matrix(
    glc_common: np.ndarray,
    esri_common: np.ndarray,
    class_values: list[int],
) -> np.ndarray:
    """共通クラス同士の混同行列を作る（行: GLC、列: Esri）。

    Args:
        glc_common (np.ndarray): GLC の共通クラス値（1次元）。
        esri_common (np.ndarray): Esri の共通クラス値（1次元）。
            2 つの配列とも **`class_values` に含まれる値のみ**を渡すこと（下記 Note 参照）。
        class_values (list[int]): 集計対象の共通クラス値（並び順が行・列に対応する）。

    Returns:
        np.ndarray: 混同行列（形状は (len(class_values), len(class_values))）。

    Note:
        引き当て表は `class_values` に無い値（無効値の 0 など）に対して 0 を返すため、
        そのまま先頭クラスの行・列へ黙って誤集計される。呼び出し側で無効値を
        除外してから渡すこと（`run` では `comparable_mask` で除外済み）。
    """
    size = len(class_values)
    # クラス値から行・列インデックスへの引き当て表。要素ごとの dict 参照より大幅に速い
    # 注意: class_values に無い値は 0（先頭クラス）に落ちる。前提条件は docstring を参照

    lookup = np.zeros(max(class_values) + 1, dtype=np.int64)
    for index, value in enumerate(class_values):
        lookup[value] = index

    glc_index = lookup[glc_common.astype(np.int64)]
    esri_index = lookup[esri_common.astype(np.int64)]
    flat = np.bincount(glc_index * size + esri_index, minlength=size * size)
    return flat.reshape(size, size)


def cohens_kappa(confusion: np.ndarray) -> float:
    """混同行列から Cohen's kappa を求める。

    Args:
        confusion (np.ndarray): 混同行列。

    Returns:
        float: kappa 係数。総画素数が 0 または偶然一致率が 1 の場合は 0.0。
    """
    total = float(confusion.sum())
    if total == 0:
        return 0.0
    observed = float(np.trace(confusion)) / total
    row_ratio = confusion.sum(axis=1) / total
    column_ratio = confusion.sum(axis=0) / total
    expected = float(np.sum(row_ratio * column_ratio))
    if expected >= 1.0:
        return 0.0
    return (observed - expected) / (1.0 - expected)


def summarize_classes(confusion: np.ndarray, class_values: list[int]) -> list[dict[str, Any]]:
    """共通クラスごとの一致状況を集計する。

    どちらのデータも真値ではないため、精度ではなく一致度として扱う。
    「GLC 基準の一致率」は GLC がそのクラスとした画素のうち Esri も同じクラスとした割合、
    「Esri 基準の一致率」はその逆である。IoU は両者の和集合に対する共通部分の割合。
    `esri_to_glc_pixel_count_ratio` は同一グリッド上の画素数比（Esri ÷ GLC）である。
    基準グリッドは地理座標系（EPSG:4326）で画素の地上面積が緯度により変わるため、
    厳密な面積比ではない。ROI（北緯 20.6-21.4 度）内での差は 1% 未満だが、
    面積として扱う場合は投影座標系で算出し直すこと。

    Args:
        confusion (np.ndarray): 混同行列（行: GLC、列: Esri）。
        class_values (list[int]): 混同行列の行・列に対応する共通クラス値。

    Returns:
        list[dict[str, Any]]: クラスごとの集計結果（GLC 画素数の降順）。
    """
    results: list[dict[str, Any]] = []
    for index, class_value in enumerate(class_values):
        agreed = int(confusion[index, index])
        glc_pixels = int(confusion[index, :].sum())
        esri_pixels = int(confusion[:, index].sum())
        union = glc_pixels + esri_pixels - agreed
        results.append(
            {
                "common_class": class_value,
                "label": COMMON_CLASS_LABELS[class_value],
                "glc_pixels": glc_pixels,
                "esri_pixels": esri_pixels,
                "agreed_pixels": agreed,
                "agreement_given_glc": (agreed / glc_pixels) if glc_pixels > 0 else None,
                "agreement_given_esri": (agreed / esri_pixels) if esri_pixels > 0 else None,
                "iou": (agreed / union) if union > 0 else None,
                "esri_to_glc_pixel_count_ratio": (
                    (esri_pixels / glc_pixels) if glc_pixels > 0 else None
                ),
            }
        )
    results.sort(key=lambda item: item["glc_pixels"], reverse=True)
    return results


def extract_year(path: Path) -> int | None:
    """ファイル名から 4 桁の西暦年を取り出す（見つからなければ None）。

    Args:
        path (Path): 対象パス。

    Returns:
        int | None: 抽出した年。複数ある場合は最後のものを返す。
    """
    years = re.findall(r"(?<!\d)(19|20)(\d{2})(?!\d)", path.stem)
    if not years:
        return None
    return int(years[-1][0] + years[-1][1])


def warn_on_year_mismatch(glc_path: Path, esri_path: Path) -> None:
    """入力ファイル名から読める対象年が食い違う場合に警告する。

    年の異なるマップを突き合わせると、一致率の低下が土地被覆の実変化なのか
    分類の差なのか区別できなくなる。ファイル名からの推定にすぎないため、
    処理は止めず警告に留める。

    Args:
        glc_path (Path): GLC_FCS30D の GeoTIFF パス。
        esri_path (Path): Esri 10m LULC の GeoTIFF パス。
    """
    glc_year = extract_year(glc_path)
    esri_year = extract_year(esri_path)
    if glc_year is not None and esri_year is not None and glc_year != esri_year:
        logger.warning(
            "入力の対象年が一致していない可能性があります（GLC: %d / Esri: %d）。"
            "一致率の低下が土地被覆の実変化を含む点に注意してください。",
            glc_year,
            esri_year,
        )


def save_confusion_csv(
    confusion: np.ndarray,
    class_values: list[int],
    confusion_path: Path,
) -> None:
    """混同行列を CSV として保存する（行: GLC、列: Esri）。

    ヘッダー・行ラベルに日本語のクラス名を含むため、BOM 付き UTF-8 で書き出す。
    BOM が無いと日本語環境の Excel で開いたときに文字化けする。

    Args:
        confusion (np.ndarray): 混同行列。
        class_values (list[int]): 行・列に対応する共通クラス値。
        confusion_path (Path): 保存先パス。
    """
    confusion_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["glc_common_class"] + [
        f"esri_{value}_{COMMON_CLASS_LABELS[value]}" for value in class_values
    ]
    with confusion_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        for index, class_value in enumerate(class_values):
            row_label = f"glc_{class_value}_{COMMON_CLASS_LABELS[class_value]}"
            writer.writerow([row_label] + [int(value) for value in confusion[index, :]])


def build_class_correspondence() -> list[dict[str, Any]]:
    """共通クラスごとに、写像元の GLC / Esri クラスを一覧化する。

    ドキュメントへ転記するクラス体系対応表の元データになる。

    Returns:
        list[dict[str, Any]]: 共通クラスごとの対応関係。
    """
    correspondence: list[dict[str, Any]] = []
    for common_value, common_label in COMMON_CLASS_LABELS.items():
        glc_members = [
            {"value": value, "label": GLC_CLASS_LABELS[value]}
            for value in sorted(GLC_TO_COMMON)
            if GLC_TO_COMMON[value] == common_value
        ]
        esri_members = [
            {"value": value, "label": ESRI_CLASS_LABELS[value]}
            for value in sorted(ESRI_TO_COMMON)
            if ESRI_TO_COMMON[value] == common_value
        ]
        correspondence.append(
            {
                "common_class": common_value,
                "label": common_label,
                "glc_classes": glc_members,
                "esri_classes": esri_members,
            }
        )
    return correspondence


def run(
    glc_path: Path,
    esri_path: Path,
    roi_path: Path,
    summary_path: Path | None,
    confusion_path: Path | None,
    label: str,
) -> tuple[Path, Path]:
    """比較から集計・保存までの処理全体を実行する。

    Args:
        glc_path (Path): GLC_FCS30D の GeoTIFF パス。
        esri_path (Path): Esri 10m LULC の GeoTIFF パス。
        roi_path (Path): ROI の Shapefile パス。
        summary_path (Path | None): サマリー JSON パス。
        confusion_path (Path | None): 混同行列 CSV パス。
        label (str): 出力ファイル名に使う識別子。

    Returns:
        tuple[Path, Path]: (サマリー JSON パス, 混同行列 CSV パス)。

    Raises:
        FileNotFoundError: 入力ラスタが存在しない場合。
    """
    for input_path in (glc_path, esri_path):
        if not input_path.exists():
            raise FileNotFoundError(f"入力ラスタが見つかりません: {input_path}")

    warn_on_year_mismatch(glc_path, esri_path)

    resolved_summary_path = summary_path or (
        DEFAULT_OUTPUT_DIR / f"lulc_esri_glc_agreement_{label}_summary.json"
    )
    resolved_confusion_path = confusion_path or (
        DEFAULT_OUTPUT_DIR / f"lulc_esri_glc_confusion_{label}.csv"
    )

    roi_gdf, _ = load_roi_geometry(roi_path)

    with rasterio.open(glc_path) as glc_source:
        glc_array = glc_source.read(1)
        reference_transform = glc_source.transform
        reference_crs = glc_source.crs
        reference_width = glc_source.width
        reference_height = glc_source.height
        reference_resolution = [float(glc_source.res[0]), float(glc_source.res[1])]
        # クリップ余白（ROI 外）を比較対象に含めないよう、ROI 内のマスクを作る
        roi_mask = geometry_mask(
            geometries=[
                geometry.__geo_interface__ for geometry in roi_gdf.to_crs(glc_source.crs).geometry
            ],
            out_shape=(glc_source.height, glc_source.width),
            transform=glc_source.transform,
            invert=True,
        )

    logger.info(
        "基準グリッド（GLC）: %d x %d 画素、解像度 %s",
        reference_width,
        reference_height,
        reference_resolution,
    )

    esri_subgrid = resample_esri_to_subgrid(
        esri_path=esri_path,
        reference_transform=reference_transform,
        reference_crs=reference_crs,
        reference_width=reference_width,
        reference_height=reference_height,
        factor=SUBDIVISION_FACTOR,
        nodata=0,
    )
    esri_on_reference, tie_mask = majority_vote_blocks(
        esri_subgrid, factor=SUBDIVISION_FACTOR, invalid_values=ESRI_FILLED_VALUES
    )
    logger.info("多数決を適用しました（%dx%d サブセル）", SUBDIVISION_FACTOR, SUBDIVISION_FACTOR)

    glc_common = map_to_common_classes(glc_array, GLC_TO_COMMON)
    esri_common = map_to_common_classes(esri_on_reference, ESRI_TO_COMMON)

    # ROI 内かつ両者とも共通クラスへ写像できた画素のみを比較対象にする
    comparable_mask = roi_mask & (glc_common != COMMON_INVALID) & (esri_common != COMMON_INVALID)
    glc_values = glc_common[comparable_mask]
    esri_values = esri_common[comparable_mask]

    class_values = sorted(COMMON_CLASS_LABELS)
    confusion = build_confusion_matrix(glc_values, esri_values, class_values)
    comparable_pixels = int(confusion.sum())
    agreed_pixels = int(np.trace(confusion))
    overall_agreement = (agreed_pixels / comparable_pixels) if comparable_pixels > 0 else 0.0
    kappa = cohens_kappa(confusion)

    save_confusion_csv(confusion, class_values, resolved_confusion_path)

    roi_pixels = int(np.count_nonzero(roi_mask))
    glc_invalid = int(np.count_nonzero(roi_mask & (glc_common == COMMON_INVALID)))
    esri_invalid = int(np.count_nonzero(roi_mask & (esri_common == COMMON_INVALID)))
    class_agreement = summarize_classes(confusion, class_values)
    tied_cells_in_roi = int(np.count_nonzero(np.logical_and(tie_mask, roi_mask)))

    summary = {
        "comparison": "GLC_FCS30D vs Esri Sentinel-2 10m Annual LULC",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "glc_raster": to_project_relative_string(glc_path),
            "esri_raster": to_project_relative_string(esri_path),
            "roi": to_project_relative_string(roi_path),
        },
        "reference_grid": {
            "source": "GLC_FCS30D",
            "crs": reference_crs.to_string() if reference_crs is not None else None,
            "width": reference_width,
            "height": reference_height,
            "resolution": reference_resolution,
        },
        "resolution_alignment": {
            "method": "subdivide_and_majority_vote",
            "subdivision_factor": SUBDIVISION_FACTOR,
            "resampling": "nearest",
            "tie_break_rule": "同数最頻の場合は Esri のクラス値の小さい方を採用する",
            "tied_cells_in_roi": tied_cells_in_roi,
            "note": (
                "GLC の 30m セルを 3x3 に分割した細分グリッド（原点・分割数とも GLC と厳密に一致）"
                "へ Esri を最近傍で再投影し、9 サブセルの多数決で 30m へ集約した。"
                "ただし Esri 出力の画素は細分セルより約 3.3% 粗いため、Esri のソース画素と"
                "細分セルは 1 対 1 に対応しない。一部のサブセルが隣接サブセルと同じソース画素を"
                "複製するため票の重みは完全には均一ではなく、集約は近似である"
                "（1 ブロックが参照する実 Esri 画素は平均約 8.4 個）。"
                "また 10m でしか現れない少数クラスは集約により失われる。"
            ),
        },
        "pixel_stats": {
            "roi_pixels": roi_pixels,
            "comparable_pixels": comparable_pixels,
            "comparable_ratio": (comparable_pixels / roi_pixels) if roi_pixels > 0 else 0.0,
            "glc_unmapped_pixels_in_roi": glc_invalid,
            "esri_unmapped_pixels_in_roi": esri_invalid,
        },
        "agreement": {
            "overall_agreement": overall_agreement,
            "agreed_pixels": agreed_pixels,
            "cohens_kappa": kappa,
            "note": (
                "どちらのデータも真値ではないため、精度（accuracy）ではなく一致度として扱う。"
            ),
        },
        "class_agreement": class_agreement,
        "built_up_agreement": next(
            entry for entry in class_agreement if entry["common_class"] == COMMON_BUILT
        ),
        "class_correspondence": build_class_correspondence(),
        "invalid_values": {
            "glc": list(GLC_FILLED_VALUES),
            "esri": list(ESRI_FILLED_VALUES),
        },
        "outputs": {
            "summary": to_project_relative_string(resolved_summary_path),
            "confusion_matrix": to_project_relative_string(resolved_confusion_path),
        },
    }
    save_summary(summary, resolved_summary_path)

    logger.info(
        "比較対象画素: %d（ROI 内 %d）/ 全体一致率: %.4f / kappa: %.4f",
        comparable_pixels,
        roi_pixels,
        overall_agreement,
        kappa,
    )
    for entry in summary["class_agreement"]:
        logger.info(
            "  %-10s GLC %9d / Esri %9d / 一致 %9d / IoU %s",
            entry["label"],
            entry["glc_pixels"],
            entry["esri_pixels"],
            entry["agreed_pixels"],
            f"{entry['iou']:.4f}" if entry["iou"] is not None else "-",
        )

    return resolved_summary_path, resolved_confusion_path


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    summary_path, confusion_path = run(
        glc_path=args.glc_path,
        esri_path=args.esri_path,
        roi_path=args.roi_path,
        summary_path=args.summary_path,
        confusion_path=args.confusion_path,
        label=args.label,
    )
    print(f"サマリー JSON を保存しました: {summary_path}")
    print(f"混同行列 CSV を保存しました: {confusion_path}")


if __name__ == "__main__":
    main()
