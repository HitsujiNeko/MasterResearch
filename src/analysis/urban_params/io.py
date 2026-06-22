"""入力レイヤ・ラスタの解決と読み込みを扱うモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
from pyproj import CRS, Transformer

from .config import PROJECT_ROOT, RASTER_KEYS
from .grid import BBox, transform_bbox


@dataclass(frozen=True)
class LayerResource:
    """入力レイヤと解析用CRSへの変換情報を保持する。

    Attributes:
        path: GPKGファイルの絶対パス。
        layer_name: 実在を確認済みのレイヤ名。
        source_crs: レイヤ本来のCRS。
        analysis_crs: 解析用に統一するCRS（例: EPSG:5897）。
        to_analysis: ``source_crs`` から ``analysis_crs`` への変換器。
        from_analysis: ``analysis_crs`` から ``source_crs`` への変換器。
    """

    path: Path
    layer_name: str
    source_crs: CRS
    analysis_crs: CRS
    to_analysis: Transformer
    from_analysis: Transformer


def resolve_layer_name(gpkg_path: Path, preferred_layer: str) -> str:
    """指定レイヤが無い場合は、実在する最初の通常レイヤへフォールバックする。

    Args:
        gpkg_path: GPKGファイルの絶対パス。
        preferred_layer: 設定上で指定されたレイヤ名。

    Returns:
        ``preferred_layer`` が存在すればそのまま返し、存在しない場合は
        ``rtree_`` から始まる索引レイヤを除いた最初のレイヤ名を返す。

    Raises:
        FileNotFoundError: ``gpkg_path`` が存在しない場合。
        ValueError: 利用可能なレイヤが1つも無い場合。
    """
    if not gpkg_path.exists():
        raise FileNotFoundError(f"GPKGファイルが見つかりません: {gpkg_path}")

    layers = list(fiona.listlayers(gpkg_path))
    if preferred_layer in layers:
        return preferred_layer

    filtered_layers = [name for name in layers if not name.startswith("rtree_")]
    if not filtered_layers:
        raise ValueError(f"利用可能なレイヤがありません: {gpkg_path}")

    return filtered_layers[0]


def get_layer_resource(
    city_cfg: dict[str, Any],
    layer_key: str,
    analysis_crs: CRS,
) -> LayerResource:
    """都市設定から対象レイヤのファイルパスとレイヤ名を解決する。

    Args:
        city_cfg: ``CITY_CONFIG`` の対象都市エントリ（``layers`` を含む）。
        layer_key: ``city_cfg["layers"]`` のキー（例: "roi", "open_buildings"）。
        analysis_crs: 解析用CRS。変換器の構築に使用する。

    Returns:
        解決済みのファイルパス・レイヤ名・CRS変換器を保持する ``LayerResource``。

    Raises:
        ValueError: ``layer_key`` が ``city_cfg["layers"]`` に存在しない場合。
    """
    layer_cfg = city_cfg["layers"].get(layer_key)
    if layer_cfg is None:
        raise ValueError(f"都市設定にレイヤがありません: {layer_key}")

    gpkg_path = PROJECT_ROOT / layer_cfg["path"]
    layer_name = resolve_layer_name(gpkg_path, str(layer_cfg["layer"]))
    source_crs = CRS.from_epsg(int(layer_cfg["crs_epsg"]))
    to_analysis = Transformer.from_crs(source_crs, analysis_crs, always_xy=True)
    from_analysis = Transformer.from_crs(analysis_crs, source_crs, always_xy=True)
    return LayerResource(
        gpkg_path, layer_name, source_crs, analysis_crs, to_analysis, from_analysis
    )


def get_optional_layer_resource(
    city_cfg: dict[str, Any],
    layer_key: str | None,
) -> LayerResource | None:
    """シナリオで未指定のレイヤはNoneとして扱う。

    Args:
        city_cfg: ``CITY_CONFIG`` の対象都市エントリ。
        layer_key: ``city_cfg["layers"]`` のキー。シナリオで未使用の場合は ``None``。

    Returns:
        ``layer_key`` が ``None`` の場合は ``None``。
        それ以外は ``get_layer_resource()`` で解決した ``LayerResource``。
    """
    if layer_key is None:
        return None
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))
    return get_layer_resource(city_cfg, layer_key, analysis_crs)


def bbox_from_layer(resource: LayerResource, analysis_crs: CRS) -> BBox:
    """レイヤ全体のBBoxを解析用CRSで取得する。

    Args:
        resource: BBoxを取得する対象レイヤ。
        analysis_crs: 解析用CRS。``resource.source_crs`` と異なる場合は変換する。

    Returns:
        ``analysis_crs`` 上でのレイヤ全体のBBox。
    """
    with fiona.open(resource.path, layer=resource.layer_name) as src:
        minx, miny, maxx, maxy = src.bounds
    bbox = BBox(float(minx), float(miny), float(maxx), float(maxy))
    if resource.source_crs == analysis_crs:
        return bbox
    return transform_bbox(bbox, resource.to_analysis)


def iter_feature_records(resource: LayerResource, bbox_analysis: BBox) -> Iterable[dict[str, Any]]:
    """指定BBox内のフィーチャを逐次返す。

    Args:
        resource: フィーチャを読み込む対象レイヤ。
        bbox_analysis: 解析用CRS上の検索範囲。レイヤのCRSが異なる場合は
            レイヤのCRSへ変換してから検索する。

    Yields:
        ジオメトリを持つフィーチャ（``geometry`` が ``None`` のものは除外）。
    """
    query_bbox = bbox_analysis
    if resource.source_crs != resource.analysis_crs:
        query_bbox = transform_bbox(bbox_analysis, resource.from_analysis)

    with fiona.open(resource.path, layer=resource.layer_name, bbox=query_bbox.to_tuple()) as src:
        for feature in src:
            if feature.get("geometry") is None:
                continue
            yield feature


def find_satellite_rasters(satellite_path: Path) -> dict[str, tuple[Path, int]]:
    """衛星指標ラスタとバンド番号を自動検出する。

    バンドの説明（description）に ``NDVI``/``NDBI``/``NDWI``/``FVC`` のいずれかが
    含まれていればそのバンドを採用する。説明から特定できない指標は、
    ファイル名に指標名が含まれていればバンド1を採用する。

    Args:
        satellite_path: 衛星指標ラスタの単一ファイル、またはラスタを
            格納するディレクトリの絶対パス。存在しない場合は空辞書を返す。

    Returns:
        指標名（例: "NDVI"）から (ラスタパス, バンド番号) への辞書。

    Raises:
        ValueError: 同じ指標を含むファイルが複数検出された場合
            （単一の観測ファイルに絞り込む必要があることを示す）。
    """
    import rasterio

    detected: dict[str, tuple[Path, int]] = {}
    if not satellite_path.exists():
        return detected

    if satellite_path.is_file():
        tif_files = [satellite_path]
    else:
        tif_files = sorted(
            p
            for p in satellite_path.iterdir()
            if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}
        )

    for tif_path in tif_files:
        upper_name = tif_path.name.upper()
        with rasterio.open(tif_path) as src:
            descriptions = src.descriptions
            for band_index, description in enumerate(descriptions, start=1):
                if description is None:
                    continue
                key = str(description).upper()
                if key in RASTER_KEYS and key in detected and detected[key][0] != tif_path:
                    raise ValueError(
                        f"{key} を含む衛星指標ファイルが複数あります。"
                        f" 単一の観測ファイルを指定してください: {detected[key][0]}, {tif_path}"
                    )
                if key in RASTER_KEYS and key not in detected:
                    detected[key] = (tif_path, band_index)

        for key in RASTER_KEYS:
            if key in detected:
                continue
            if key in upper_name:
                detected[key] = (tif_path, 1)

    return detected
