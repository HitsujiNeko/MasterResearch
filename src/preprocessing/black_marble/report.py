"""取得サマリーの組み立てと、結果の要点のログ出力。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.common.config import LANDSAT_OBSERVATION_YEAR
from src.common.paths import to_project_relative_string
from src.preprocessing.black_marble.listing import TileFile
from src.preprocessing.black_marble.product import (
    BAND_DEFINITIONS,
    FIRST_AVAILABLE_YEAR,
    LAADS_ARCHIVE_SET,
    OUTPUT_NODATA,
    PRIMARY_BAND_NAME,
    PRODUCT_NAME,
)
from src.preprocessing.black_marble.tile_grid import TileIndex

logger = logging.getLogger(__name__)


def collect_attribute_warnings(tile_metadata: dict[str, Any]) -> list[str]:
    """属性が欠けて既定値で代用したバンドを、人が読める形で列挙する。

    `band_attributes` の奥に埋もれた `defaulted_attributes` を最上位へ引き上げる
    ための整形。属性名が配布バージョンで変わると、換算がずれたまま成果物が出来上がって
    しまうため、サマリーを一目見て気づける位置に無いと意味がない。

    Args:
        tile_metadata: `write_tile_geotiff` が返したメタデータ。

    Returns:
        警告文のリスト。欠落が無ければ空リスト。
    """
    warnings: list[str] = []
    for band_name, applied in sorted(tile_metadata.get("band_attributes", {}).items()):
        for attribute_name in applied.get("defaulted_attributes", []):
            warnings.append(
                f"{band_name}: SDS 属性 {attribute_name} が無く既定値で代用した"
                "（配布側の属性名が変わっていないか確認すること）"
            )
        for attribute_name in applied.get("unusable_attributes", []):
            warnings.append(
                f"{band_name}: SDS 属性 {attribute_name} は存在するが配列の型で"
                "表現できず適用できなかった（配布側の型が変わっていないか確認すること）"
            )
    return warnings


def build_summary(
    year: int,
    roi_path: Path,
    is_trial: bool,
    area_bounds: tuple[float, float, float, float],
    tiles: list[TileIndex],
    tile_files: dict[str, TileFile],
    tile_metadata: dict[str, Any],
    raster_profile: dict[str, Any],
    pixel_stats: dict[str, Any],
    output_path: Path,
    summary_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    """取得サマリーの辞書を組み立てる。

    Args:
        year: 取得対象年。
        roi_path: ROI ファイルパス。
        is_trial: 試行実行（BBOX 指定）かどうか。
        area_bounds: 取得対象範囲の BBOX。
        tiles: 使用したタイル。
        tile_files: タイル名 -> 実ファイル情報。
        tile_metadata: タイル読み取り時のメタデータ。
        raster_profile: 出力ラスタの諸元。
        pixel_stats: 画素統計。
        output_path: 出力 GeoTIFF パス。
        summary_path: サマリー JSON パス。
        retrieved_at: 取得日時（ISO8601）。

    Returns:
        サマリー辞書。
    """
    year_note = f"{PRODUCT_NAME} の提供は {FIRST_AVAILABLE_YEAR} 年から。"
    if year == LANDSAT_OBSERVATION_YEAR:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）と一致しており、時間差はない。"
        )
    else:
        year_note += (
            f"本研究の Landsat 観測年（{LANDSAT_OBSERVATION_YEAR}年）との間に "
            f"{abs(LANDSAT_OBSERVATION_YEAR - year)} 年の時間差がある。"
        )

    return {
        "dataset": f"NASA Black Marble {PRODUCT_NAME}（年次・月光/BRDF補正済み）",
        "dataset_key": "black_marble_vnp46a4",
        "archive_set": LAADS_ARCHIVE_SET,
        "source": (
            "https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/"
        ),
        "license": "NASA オープンサイエンスポリシー",
        "license_note": (
            "出典表記は NASA VIIRS Land Science Team（Black Marble）に対して行う。"
            "取得には Earthdata アカウントの Bearer トークンが必要。"
        ),
        "retrieved_at": retrieved_at,
        "year": year,
        "year_note": year_note,
        "access_note": (
            f"{PRODUCT_NAME}（年次）は Google Earth Engine に存在せず、LAADS DAAC から"
            "直接取得している。GEE で使えるのは日次の VNP46A2 / VNP46A1 のみ。"
        ),
        "tiles": [tile.name for tile in tiles],
        "tile_files": {
            tile_name: {
                "name": tile_file.name,
                "download_url": tile_file.download_url,
                "size_bytes": tile_file.size_bytes,
            }
            for tile_name, tile_file in tile_files.items()
        },
        "tile_metadata": tile_metadata,
        "grid_note": (
            "配布は 10°×10° タイル（原点 -180E/90N、15 arc-sec）。ジオリファレンスは"
            "タイル番号から組み立て、ファイルの境界座標属性と一致することを検証している。"
            "VIIRS DNB 年次コンポジットとはグリッド原点が半画素ずれるため、画素単位の"
            "突き合わせには再投影が要る。"
        ),
        "roi_path": to_project_relative_string(roi_path),
        "is_trial_run": is_trial,
        "area_bbox": list(area_bounds),
        # サマリーJSONの標準項目として最上位に置く。実体は raster_profile 側が正
        "crs": raster_profile["crs"],
        "raster_profile": raster_profile,
        "bands": {
            str(index): {
                "name": band.output_name,
                "source_sds": band.sds_name,
                "unit": band.unit,
                "description": band.description,
            }
            for index, band in enumerate(BAND_DEFINITIONS, start=1)
        },
        "pixel_stats": pixel_stats,
        # 属性欠落は band_attributes の奥に埋もれると気づけないため最上位へ引き上げる。
        # 属性名が版で変わると、換算がずれたまま成果物が出来上がってしまう
        "attribute_warnings": collect_attribute_warnings(tile_metadata),
        "scaling_note": (
            "スケール係数・オフセット・欠測値は SDS 属性から実測して適用している"
            "（tile_metadata.band_attributes に記録）。コード側では決め打ちしていない。"
            "属性が欠けていた場合は attribute_warnings に列挙する。空リストであれば、"
            "全バンドの換算がファイルの属性どおりに行われたことを意味する。"
        ),
        "saturation_note": (
            "飽和指標は、放射輝度そのものを表す合成バンド（ntl_near_nadir / "
            "ntl_all_angle）についてのみ算出している。near_nadir_std は単位こそ同じ"
            "放射輝度だが年内のばらつきを表す量で、上限への張り付きという意味を持た"
            "ないため対象外とした。near_nadir_num は観測回数で単位が異なる。"
            "p99_to_max_ratio が 1 に近く、かつ ratio_near_max が無視できない大きさで"
            "あれば、上位の値が最大値へ張り付いている（飽和が疑われる）。"
        ),
        "coverage_note": (
            "ROI ポリゴンで真にクリップしているため出力は BBOX 矩形となり、ROI 外の余白は "
            f"nodata（{OUTPUT_NODATA}）で埋まる。valid_pixel_ratio の分母 roi_pixels は"
            "**クリップ後の出力に含まれる ROI 内画素**であり、ROI 全体ではない。"
            "有効画素はバンドごとに別々に数えており、最上位の valid_pixels / "
            f"valid_pixel_ratio はデータ被覆の指標として主バンド {PRIMARY_BAND_NAME} で"
            "代表させている。"
        ),
        "outputs": {
            "geotiff": to_project_relative_string(output_path),
            "summary": to_project_relative_string(summary_path),
        },
    }


def log_results(pixel_stats: dict[str, Any]) -> None:
    """取得結果の要点をログへ出力する。

    Args:
        pixel_stats: 画素統計。
    """
    logger.info(
        "有効画素率: %.4f（有効 %d / 範囲内 %d、ラスタ全体 %d）",
        pixel_stats["valid_pixel_ratio"],
        pixel_stats["valid_pixels"],
        pixel_stats["roi_pixels"],
        pixel_stats["total_pixels"],
    )
    for band in BAND_DEFINITIONS:
        band_stats = pixel_stats[band.output_name]
        if "min" not in band_stats:
            logger.warning("バンド %s に有効画素がありません。", band.output_name)
            continue
        logger.info(
            "%s（%s）: 有効 %d 画素（%.4f） min=%.3f median=%.3f p95=%.3f p99=%.3f max=%.3f",
            band.output_name,
            band.unit,
            band_stats["valid_pixels"],
            band_stats["valid_pixel_ratio"],
            band_stats["min"],
            band_stats["median"],
            band_stats["p95"],
            band_stats["p99"],
            band_stats["max"],
        )

    for band_name, indicators in pixel_stats["saturation"].items():
        if indicators is None:
            continue
        ratio_text = (
            "算出不可"
            if indicators["p99_to_max_ratio"] is None
            else f"{indicators['p99_to_max_ratio']:.3f}"
        )
        # 近傍幅は可変なので、文言に固定値を埋め込まず実際の設定値から組み立てる
        neighborhood_percent = indicators["neighborhood_ratio"] * 100
        logger.info(
            "飽和指標 %s: p99/max=%s、最大値と同値 %d 画素、最大値の%.3g%%以内 %d 画素（%.4f）",
            band_name,
            ratio_text,
            indicators["pixels_at_max"],
            neighborhood_percent,
            indicators["pixels_near_max"],
            indicators["ratio_near_max"],
        )

    if pixel_stats["valid_pixel_ratio"] < 1.0:
        logger.warning(
            "範囲内に無効画素があります（有効率 %.4f）。データ提供範囲の限界を確認してください。",
            pixel_stats["valid_pixel_ratio"],
        )
    if not pixel_stats["covers_requested_area"]:
        logger.warning(
            "出力が要求範囲を覆いきれていません。有効率は覆えた範囲内でしか評価されていない"
            "ため、タイルの選択が正しいか確認してください。"
        )
