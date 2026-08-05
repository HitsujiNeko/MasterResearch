"""入力レイヤ・ラスタの解決と読み込みを扱うモジュール。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
import geopandas as gpd
from pyproj import CRS, Transformer

from src.common.geo_metadata import BBox, transform_bbox

from .config import PROJECT_ROOT, RASTER_KEYS


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


@dataclass(frozen=True)
class RasterResource:
    """入力ラスタの所在を保持する。

    ``LayerResource`` と分けているのは、ラスタにはレイヤ名が無く、CRS変換も
    再投影（``rasterio.warp.reproject``）が担うため、ベクタ固有のフィールドが
    常に無意味になるためである。

    Attributes:
        path: ラスタファイルの絶対パス。
        band_index: 読み込むバンド番号（1始まり）。
    """

    path: Path
    band_index: int


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


def get_optional_raster_resource(
    city_cfg: dict[str, Any],
    raster_key: str | None,
) -> RasterResource | None:
    """シナリオで未指定のラスタはNoneとして扱う。

    ファイルが存在しない場合に ``None`` を返さず例外を送出するのは、出力列が
    黙って消えると欠損に気づかないまま分析に進む事故を招くためである。ベクタ側の
    ``resolve_layer_name()`` も同じ挙動であり、一貫させている。

    Args:
        city_cfg: ``CITY_CONFIG`` の対象都市エントリ（``rasters`` を含む）。
        raster_key: ``city_cfg["rasters"]`` のキー。シナリオで未使用の場合は ``None``。

    Returns:
        ``raster_key`` が ``None`` の場合は ``None``。
        それ以外は解決済みのパスとバンド番号を保持する ``RasterResource``。

    Raises:
        ValueError: ``raster_key`` が ``city_cfg["rasters"]`` に存在しない場合。
        FileNotFoundError: 設定されたラスタファイルが存在しない場合。
    """
    if raster_key is None:
        return None

    raster_cfg = city_cfg.get("rasters", {}).get(raster_key)
    if raster_cfg is None:
        raise ValueError(f"都市設定にラスタがありません: {raster_key}")

    raster_path = PROJECT_ROOT / raster_cfg["path"]
    if not raster_path.exists():
        raise FileNotFoundError(f"ラスタファイルが見つかりません: {raster_path}")

    return RasterResource(raster_path, int(raster_cfg["band"]))


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


def _covers_layer_extent(src: fiona.Collection, query_bbox: BBox) -> bool:
    """検索BBoxがレイヤ全体の範囲を覆いきるかを判定する。

    覆いきる場合は空間フィルタを適用しても結果が変わらないため、
    フィルタを省略して読み込みを高速化できる。

    判定はレイヤが記録している範囲（``src.bounds``）に基づく。この値が実データ
    の範囲より狭い破損データではフィルタを省略しても該当しない地物が返るが、
    呼び出し側はいずれもグリッド範囲でクリップするため結果は変わらず、処理量
    だけが増える。なお ``bbox_from_layer()`` も同じ値を信頼しているものの、
    そちらは解析範囲を決める基準レイヤ1つに限られる点で適用範囲が異なる。

    Args:
        src: オープン済みのFionaコレクション。
        query_bbox: レイヤ本来のCRS上の検索範囲。

    Returns:
        検索BBoxがレイヤ全体を覆う場合は ``True``。範囲を取得できない
        （空レイヤ等）場合や有限値でない場合は、安全側に倒して ``False``
        を返す（＝従来どおり空間フィルタを適用する）。
    """
    try:
        minx, miny, maxx, maxy = src.bounds
    except Exception:
        # 空レイヤなどで範囲を計算できない場合はフィルタ省略の判断ができない。
        return False

    if not all(math.isfinite(value) for value in (minx, miny, maxx, maxy)):
        return False

    return (
        query_bbox.minx <= minx
        and query_bbox.miny <= miny
        and query_bbox.maxx >= maxx
        and query_bbox.maxy >= maxy
    )


def iter_feature_records(resource: LayerResource, bbox_analysis: BBox) -> Iterable[dict[str, Any]]:
    """指定BBox内のフィーチャを逐次返す。

    検索BBoxがレイヤ全体の範囲を覆う場合は、空間フィルタを適用しても
    全フィーチャが該当するため、フィルタを省略して読み込む。空間索引の
    参照コストを避けるための最適化であり、レイヤの記録範囲が正しい限り
    返すフィーチャ集合は変わらない。

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

    with fiona.open(resource.path, layer=resource.layer_name) as src:
        if _covers_layer_extent(src, query_bbox):
            features: Iterable[dict[str, Any]] = src
        else:
            features = src.filter(bbox=query_bbox.to_tuple())

        for feature in features:
            if feature.get("geometry") is None:
                continue
            yield feature


def list_layer_fields(resource: LayerResource) -> list[str]:
    """レイヤが持つ属性列名の一覧を返す。

    読み込む列を絞り込む前に、対象レイヤに実在する列を確認するために使う。
    シナリオによってレイヤのスキーマが異なる（公開GISと測量GISで属性が
    揃っていない）ため、存在しない列を指定して読み込みが失敗するのを避ける。

    Args:
        resource: 対象レイヤ。

    Returns:
        属性列名のリスト。ジオメトリ列は含まない。
    """
    with fiona.open(resource.path, layer=resource.layer_name) as src:
        return list(src.schema["properties"])


def read_layer_dataframe(
    resource: LayerResource,
    columns: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """レイヤ全体をGeoDataFrameとして一括読み込みし、解析用CRSへ投影する。

    フィーチャ数が多いレイヤでは、1件ずつの読み込み・投影がオーバーヘッドの
    支配項になる。一括読み込みと ``to_crs()`` による一括投影で、同じ結果を
    大幅に短い時間で得るための関数である。

    CRSは、ファイルに記載された値ではなく ``resource.source_crs``
    （都市設定の ``crs_epsg``）を優先して明示する。逐次読み込み経路
    （``iter_feature_records()`` + ``project_geometry_safe()``）と
    同じCRSの意味論を保つためである。

    空間フィルタは適用せず全件を読み込む。呼び出し側はラスタ化・セル添字
    判定の時点でグリッド範囲外を除外するため、ここで絞り込む必要はない。
    ただしcoarseグリッドは解析BBoxを最大1セル分だけ外側（+X側・-Y側）まで
    含むため、その帯に入る地物の扱いのみ、空間フィルタを適用する逐次経路
    （``iter_feature_records()``）と異なる。

    全件読み込みが妥当なのは、現行の入力レイヤがいずれもROIへクリップ済みで
    解析範囲を大きく超えないためである。ROIより広いレイヤへ差し替える場合は
    メモリ使用量がレイヤ全体に比例するため、``gpd.read_file()`` の ``bbox``
    引数で絞り込む形へ変更する（逐次経路と範囲の意味論も揃う）。

    Args:
        resource: 読み込む対象レイヤ。
        columns: 読み込む属性列の一覧。``None`` の場合は全列を読み込む。
            ジオメトリ列は指定に関わらず常に読み込まれる。

    Returns:
        解析用CRSへ投影済みのGeoDataFrame。
    """
    read_kwargs: dict[str, Any] = {"layer": resource.layer_name}
    if columns is not None:
        read_kwargs["columns"] = columns

    gdf = gpd.read_file(resource.path, **read_kwargs)
    gdf = gdf.set_crs(resource.source_crs, allow_override=True)
    if resource.source_crs != resource.analysis_crs:
        gdf = gdf.to_crs(resource.analysis_crs)
    return gdf


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
