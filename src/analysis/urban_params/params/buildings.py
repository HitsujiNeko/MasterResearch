"""建物パラメータ（BUILD_COV / BUILD_DEN / BUILD_H_MEAN / BUILD_H_MAX）算出モジュール。

建物フットプリントレイヤから、グリッドセルごとの被覆率・棟数密度・平均高さ・
最大高さを算出する。

実装方式:
    本モジュールのみ、他のパラメータモジュール（``roads.py`` 等）が採る1件ずつの
    逐次処理ではなく、レイヤの一括読み込みとNumPyによるベクトル化集計を採る。
    対象が300万件規模で、逐次処理のオーバーヘッドが実行時間の支配項になるため
    である。ラスタ化・グリッド集約のコアロジックは ``geometry.py`` の既存関数を
    そのまま再利用しており、ロジックの二重化は生じない。

帰属方式:
    棟数密度は、建物ポリゴンの重心が含まれるcoarseセルへ1棟をまるごと帰属させる
    （按分しない）。

    高さ（BUILD_H_MEAN・BUILD_H_MAX）は、棟数密度とは異なり**重なり方式と重心
    方式を併用する**。有効高さを持つ建物のみをfineグリッドへ高さの値として
    ラスタ化し（重なりは最も高い建物の高さを残す）、coarseセルごとに被覆fine
    セルの高さの平均・最大を取るのが基本（重なり方式）である。

    - ``BUILD_H_MEAN`` は重なり方式の値をそのまま使い、被覆fineセルが1つも
      無いセル（NaN）のみ重心方式（棟数密度と同じ建物重心の帰属）で補完する。
    - ``BUILD_H_MAX`` は重なり方式の最大と重心方式の最大を ``np.fmax()`` で
      合成する（「重なり ∪ 重心」）。``BUILD_H_MEAN`` のような「NaNのセルのみ
      補完」にしないのは、fineセル1個（100m²）より小さい建物が、重心の帰属先
      とは別のセルでfine中心を1つも覆わずに落ちるケースを、重なり方式の
      フォールバック（セルの有効高さ被覆がゼロ）だけでは救えないため。低い
      大建物と高い小建物が同居するセルでは、大建物が被覆を作るためフォール
      バックが発動せず、小建物の高さだけが失われる。``np.fmax()`` による合成
      は現行（重心方式単独）の値を下回らない（``fmax(x, 現行値) >= 現行値``）。

    この結果、``BUILD_H_MEAN`` と ``BUILD_H_MAX`` は「同じ建物集合の平均と
    最大」ではなくなる（前者は重なり、後者は重なり∪重心）。棟数密度・被覆率・
    高さの3パラメータが同じ「セルに属する建物」集合を共有するという設計は
    高さの2列内でも成り立たない。

    ``BUILD_H_MEAN`` の推定量としての定義は「セルの建物被覆部分における上端
    高さ（重なる箇所は最も高い建物の高さを採る）の面積平均」であり、建物部分の
    面積加重平均高さ**ではない**。両者は建物同士が重なる箇所でのみ食い違う。
    上端高さを採るのは意図した選択であり、**有効高さを持つ建物に限り**
    ``BUILD_COV * BUILD_H_MEAN * セル面積`` がfine解像度で離散化したLoD1
    押し出し体積と厳密に一致する（``BUILD_COV`` は高さが無効な建物の
    フットプリントも含むため、無効高さの建物が混在するセルではこの恒等式が
    わずかに崩れる。ROI全体で無効高さは149棟のみのため影響は小さい）。

検証:
    ``BUILD_DEN`` は帰属方式を変更していないため、QGISとの比較検証（ハノイ
    中心部のテスト領域・2.1km四方・建物13,779件、``native:countpointsinpolygon``
    と float32 精度内で一致）が引き続き有効である。

    ``BUILD_H_MEAN`` / ``BUILD_H_MAX`` は本変更により、旧方式（重心方式単独）
    で成立していた QGIS との 1.0e-6 m 厳密一致は成り立たなくなる（重なり方式が
    fine解像度による離散化誤差を新規に持ち込むため）。新方式でのQGIS突合は
    完了しており、重なりが無いセルに限定した主検証（30m）で相関0.986・平均
    バイアス-0.012m・希釈係数 λ̂=0.968（``BUILD_COV`` の0.785を上回る）を得た。
    ``BUILD_H_MAX`` は当初案（フォールバックのみの補完）より
    ``np.fmax()`` による合成が全スケールで上回ることも実測済み。詳細な数値は
    ``docs/01_planning/gis_data/gis_data_buildings.md`` 3.6節を参照。

    BUILD_COV は fine グリッドへのラスタ化による近似であり、面積按分の厳密値
    （``native:dissolve`` + ``native:intersection``）とは離散化の分だけ差が出る。
    fine 10m の場合、平均バイアスは全スケールで +0.0013 と小さい一方、セル単位の
    ばらつきはcoarse解像度に依存する。

    ===========  ==========  ==========  ==================================
    coarse解像度  相関        誤差SD      備考
    ===========  ==========  ==========  ==================================
    30m          0.952       0.083       fineセル9個分のため10段階しか取らない
    90m          0.989       0.026       fineセル81個分
    300m         0.998       0.007       fineセル900個分
    ===========  ==========  ==========  ==================================

    30mでは説明変数としての測定誤差により、回帰係数が約2割縮む（希釈バイアス）と
    見積もられる。スケール間で説明力を比較する際は、この差が真のスケール効果か
    離散化の影響かを区別する必要がある。

高さの扱い:
    高さ推定の分散が負の建物は、推定の信頼度が無いことを示す番兵値とみなして
    高さ集計から除外する。分散は物理的に負にならないためである。高さ自体が
    負の建物、および高さ・分散のいずれかが欠測（NaN）の建物も同じ基準で除外
    する。フットプリント自体は有効なので、被覆率・棟数密度からは除外しない。

    セル内に有効な高さの建物が1棟も無い場合、平均・最大高さは 0.0 ではなく NaN
    とする。0.0 では「建物が無い」と「高さが不明」を区別できず、回帰分析で偽の
    低高度セルを生むためである。有効高さを持つ建物が1棟も無いセル（無効高さの
    建物のみを含むセル）は、重なり方式でも重心方式でも高さが得られないため
    NULLのまま残る。

    ``BUILD_H_MEAN`` は混成推定量である。大半のセルでは上端高さの面積平均だが、
    重なり方式の被覆が無いセルでは重心方式の単純平均に切り替わる。この切替が
    どのセルで起きたかは、出力テーブルからは厳密には判別できない
    （``BUILD_COV == 0`` は判別の目安にすぎず、``BUILD_COV`` は高さが無効な
    建物のフットプリントも含むため同値ではない）。さらに、被覆があるセルでも
    fineセル中心を1つも覆わない小さい建物は重み0で落ちるため、宣言した推定量
    （面積加重平均）から系統的にずれる。ハノイでは大フットプリント＝低層、
    小フットプリント＝中高層という対応があるため、この取りこぼしは密集低層
    地区で ``BUILD_H_MEAN`` を下方へ偏らせる。

解釈上の注意:
    GlobalBuildingAtlas の高さ属性は衛星画像からの機械学習推定値であり、現地
    測量値ではない。ハノイでのローカル精度（RMSE・バイアス）は未検証である。
    またLoD1（フットプリントを単一の代表高さで押し出した箱型）モデルのため、
    屋根形状や階別の形状変化は表現しない。高さ由来のパラメータを定量指標として
    解釈する際は、この精度限界を前提とする必要がある。

    実データには ``height`` が 1m 未満の建物が 2.6%（最小 0.0062m）含まれる。
    建物高さとして物理的に成立しない値だが、機械学習推定のアーティファクトと
    実在の平屋を判別する閾値を決められないため、本モジュールは負値のみを除外し
    小さな正値はそのまま集計する。閾値を設けるかは分析側の判断に委ねる。

    被覆率と棟数密度は、データの有効域外でも 0.0 を返す。「真に建物がない」
    状態と「データが無い」状態を区別しないため、``BUILD_COV = 0`` を建物の
    不存在と解釈する前に、対象セルが有効カバレッジ内かを別途確認する必要が
    ある（特に測量GISを使う ``full`` シナリオでは整備範囲がROIより狭い）。
    高さのみ、この区別のためにNaNを用いている。
"""

from __future__ import annotations

import warnings

import geopandas as gpd
import numpy as np
import pandas as pd

from ..geometry import (
    POLYGON_GEOM_TYPES,
    aggregate_mean_from_fine_mask,
    aggregate_mean_max_from_fine_values,
    centroid_cell_indices,
    rasterize_binary_mask,
    rasterize_max_value_field,
)
from ..grid import BBox, GridSpec, cell_area_ha
from ..io import LayerResource, list_layer_fields, read_layer_dataframe

# 建物高さと、その推定分散を保持する属性列の名前。
HEIGHT_FIELD = "height"
HEIGHT_VARIANCE_FIELD = "var"

# 高さラスタ化の番兵値。建物高さは0以上のため衝突しない。
HEIGHT_RASTER_NODATA = -1.0


def _filter_usable_polygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """ポリゴンとして扱える行のみを残す。不正ジオメトリは修復を試みる。

    逐次経路の ``project_geometry_safe()`` は不正ジオメトリを ``make_valid``
    で修復してから採用する。同じ意味論を保つため本関数でも修復を先に行い、
    修復しても使えない行だけを除外する。修復せずに除外すると、同じレイヤに
    対して ``compute_polygon_coverage()`` と異なる被覆率を返してしまう。

    除外理由は「ポリゴン以外」と「不正・空」に分けて数える。測量GIS由来の
    レイヤはポイント・ラインを含むことがあり正常な内訳である一方、不正・空の
    ジオメトリはデータ品質の問題を示すため、前者の件数に後者が埋もれると
    問題を見落とすためである。件数は警告として出し、静かなデータ欠落に
    ならないようにする。

    Args:
        gdf: 解析用CRSへ投影済みの建物レイヤ。

    Returns:
        ポリゴン系として使える行のみを残し、修復済みジオメトリを反映した
        GeoDataFrame。
    """
    geometries = gdf.geometry
    present_mask = geometries.notna()
    # 修復でジオメトリ種別が変わりうるため、ポリゴン系かの判定は修復前の型で行う。
    was_polygon_mask = present_mask & geometries.geom_type.isin(POLYGON_GEOM_TYPES)

    invalid_mask = was_polygon_mask & ~geometries.is_valid
    repaired_count = int(invalid_mask.sum())
    if repaired_count:
        geometries = geometries.copy()
        geometries.loc[invalid_mask] = geometries.loc[invalid_mask].make_valid()
        gdf = gdf.set_geometry(geometries)
        warnings.warn(
            f"不正な建物ジオメトリを修復しました: {repaired_count} 件",
            stacklevel=2,
        )

    # 修復結果がGeometryCollection等になる場合があるため、修復後に再判定する。
    usable_mask = (
        was_polygon_mask & geometries.geom_type.isin(POLYGON_GEOM_TYPES) & ~geometries.is_empty
    )

    # ジオメトリは存在するがポリゴン系でないもの（測量GISでは正常な内訳）。
    non_polygon_count = int((present_mask & ~was_polygon_mask).sum())
    if non_polygon_count:
        warnings.warn(
            f"ポリゴン以外の建物ジオメトリを除外しました: {non_polygon_count} 件",
            stacklevel=2,
        )

    # NULL・空・修復できなかったジオメトリ（NULLは正常な内訳ではない）。
    broken_count = int((~present_mask).sum()) + int((was_polygon_mask & ~usable_mask).sum())
    if broken_count:
        warnings.warn(
            f"不正または空の建物ジオメトリを除外しました: {broken_count} 件",
            stacklevel=2,
        )

    return gdf.loc[usable_mask]


def _valid_height_values(gdf: gpd.GeoDataFrame) -> np.ndarray:
    """高さ集計に用いる高さ配列を返す。集計対象外の行は ``NaN`` とする。

    Args:
        gdf: ポリゴンの絞り込み済み建物レイヤ。

    Returns:
        ``gdf`` と同じ長さの高さ配列（m）。高さが欠測・負値の行、および
        推定分散が負・欠測の行は ``NaN`` とする。
    """
    if HEIGHT_FIELD not in gdf.columns:
        warnings.warn(
            f"建物レイヤに高さ属性 '{HEIGHT_FIELD}' がありません。高さ列はすべてNaNになります。",
            stacklevel=2,
        )
        return np.full(len(gdf), np.nan, dtype=np.float64)

    heights = pd.to_numeric(gdf[HEIGHT_FIELD], errors="coerce").to_numpy(dtype=np.float64)
    # 高さも物理的に負にならないため、分散と同じ基準で番兵値・異常値を除外する。
    reliable_mask = heights >= 0

    if HEIGHT_VARIANCE_FIELD not in gdf.columns:
        # 分散属性を持たないレイヤでは信頼度による絞り込みができない。
        # 同じ列名でも意味論が変わるため、解釈時に気づけるよう警告する。
        warnings.warn(
            f"建物レイヤに高さの推定分散 '{HEIGHT_VARIANCE_FIELD}' がありません。"
            "信頼度による絞り込みを行わず、取得できた高さをすべて集計します。",
            stacklevel=2,
        )
    else:
        variances = pd.to_numeric(gdf[HEIGHT_VARIANCE_FIELD], errors="coerce").to_numpy(
            dtype=np.float64
        )
        # 分散は物理的に負にならないため、負値は信頼度なしを示す番兵値とみなす。
        # NaNとの比較は偽になるので、分散が欠測の建物も同時に除外される。
        reliable_mask &= variances >= 0

    return np.where(reliable_mask, heights, np.nan)


def _aggregate_heights(
    flat_indices: np.ndarray,
    heights: np.ndarray,
    cell_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """セルごとの平均高さ・最大高さを一括集計する。

    Args:
        flat_indices: 各建物が属するcoarseセルの1次元添字。
        heights: 各建物の高さ（m）。集計対象外の要素は ``NaN``。
        cell_count: coarseグリッドの総セル数。

    Returns:
        (平均高さ, 最大高さ) の組（いずれも長さ ``cell_count`` の1次元配列）。
        有効な高さを持つ建物が1棟も無いセルは ``NaN`` とする。
    """
    finite_mask = np.isfinite(heights)
    valid_indices = flat_indices[finite_mask]
    valid_heights = heights[finite_mask]

    height_sums = np.bincount(valid_indices, weights=valid_heights, minlength=cell_count)
    height_counts = np.bincount(valid_indices, minlength=cell_count)
    height_maxima = np.full(cell_count, -np.inf, dtype=np.float64)
    np.maximum.at(height_maxima, valid_indices, valid_heights)

    has_height = height_counts > 0
    # ゼロ除算を避けるため、件数0のセルは除数を1に置き換えてからNaNで上書きする。
    mean_heights = np.where(has_height, height_sums / np.maximum(height_counts, 1), np.nan)
    max_heights = np.where(has_height, height_maxima, np.nan)
    return mean_heights, max_heights


def compute(
    resource: LayerResource | None,
    bbox_analysis: BBox,
    grid_spec: GridSpec,
) -> dict[str, np.ndarray]:
    """建物パラメータを算出する。

    ``bbox_analysis`` は本モジュールでは直接使用しない。解析範囲は
    ``grid_spec`` に反映済みであり、範囲外の建物はラスタ化とセル添字の
    範囲判定で除外されるためである。標準シグネチャに合わせて受け取る。

    Args:
        resource: 建物レイヤ（未指定シナリオでは ``None``）。
        bbox_analysis: 解析用CRS上の検索範囲。
        grid_spec: fine/coarseグリッドの仕様。

    Returns:
        ``BUILD_COV``（被覆率 0-1）・``BUILD_DEN``（棟/ha）・
        ``BUILD_H_MEAN``・``BUILD_H_MAX``（いずれもm）を持つ辞書。
        ``resource`` が ``None`` の場合は空辞書を返す。
    """
    if resource is None:
        return {}

    available_fields = list_layer_fields(resource)
    height_columns = [
        name for name in (HEIGHT_FIELD, HEIGHT_VARIANCE_FIELD) if name in available_fields
    ]
    gdf = _filter_usable_polygons(read_layer_dataframe(resource, columns=height_columns))
    geometries = gdf.geometry.to_numpy()

    fine_mask = rasterize_binary_mask(
        geometries=geometries,
        out_shape=grid_spec.fine_shape,
        out_transform=grid_spec.fine_transform,
    )
    coverage = aggregate_mean_from_fine_mask(fine_mask, grid_spec.factor)
    # 高さラスタ（float32で約280MB）を確保する前に解放し、ピークメモリ増分を
    # fine_mask分（uint8で約70MB）だけ抑える。
    del fine_mask

    centroids = gdf.geometry.centroid
    rows, cols, inside_mask = centroid_cell_indices(
        centroids.x.to_numpy(), centroids.y.to_numpy(), grid_spec
    )

    n_rows, n_cols = grid_spec.coarse_shape
    cell_count = n_rows * n_cols
    flat_indices = rows[inside_mask] * n_cols + cols[inside_mask]

    building_counts = np.bincount(flat_indices, minlength=cell_count)
    density = building_counts / cell_area_ha(grid_spec)

    # ラスタ化には全行版の高さ配列を使う（重心がグリッド外でもフットプリントが
    # 張り出したセルへ値を焼くため）。重心方式は重心がグリッド内にある行だけに
    # 絞った配列を使う。この2つを同名変数で使い回すと、絞り込みの有無が
    # 静かに入れ替わって壊れるため、変数名を明確に分ける。
    all_heights = _valid_height_values(gdf)
    centroid_heights = all_heights[inside_mask]
    mean_centroid, max_centroid = _aggregate_heights(flat_indices, centroid_heights, cell_count)
    mean_centroid = mean_centroid.reshape(grid_spec.coarse_shape)
    max_centroid = max_centroid.reshape(grid_spec.coarse_shape)

    fine_heights = rasterize_max_value_field(
        geometries=geometries,
        values=all_heights,
        out_shape=grid_spec.fine_shape,
        out_transform=grid_spec.fine_transform,
        nodata=HEIGHT_RASTER_NODATA,
    )
    mean_overlap, max_overlap = aggregate_mean_max_from_fine_values(
        fine_heights, grid_spec.factor, nodata=HEIGHT_RASTER_NODATA
    )

    # BUILD_H_MEAN: 重なり方式の値をそのまま使い、被覆fineセルが1つも無い
    # セル（NaN）のみ重心方式で補完する。
    mean_heights = np.where(np.isnan(mean_overlap), mean_centroid, mean_overlap)
    # BUILD_H_MAX: 重なり方式の最大と重心方式の最大をnp.fmax()で合成する
    # （np.maximumではなくnp.fmaxを使う理由はモジュールdocstring「帰属方式」
    # 節を参照。np.maximumはNaN側を伝播させ、片側のみ有効なセルもNaNになる）。
    max_heights = np.fmax(max_overlap, max_centroid)

    return {
        "BUILD_COV": coverage.astype(np.float32),
        "BUILD_DEN": density.reshape(grid_spec.coarse_shape).astype(np.float32),
        "BUILD_H_MEAN": mean_heights.astype(np.float32),
        "BUILD_H_MAX": max_heights.astype(np.float32),
    }
