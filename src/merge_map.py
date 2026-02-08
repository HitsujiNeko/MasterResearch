"""
geotiff形式の地図データを、クリップして結合するプログラム

- 地図データの名前と位置情報（4隅の座標情報）をまとめたCSVファイルを読み込む
- CSCファイルに記載されている地図データを読み込み、読み込んだファイル数を出力する
- 各地図データを指定された座標でクリップし、地図の枠線の余白を削除する。処理中に進捗を表示する（ファイル名と現在の処理数/総ファイル数）
- クリップした地図データを一つの大きな地図に結合する
- 結合した地図データを新しいgeotiffファイルとして保存する

path:
- 地図データ： workspace/data/maps/maps 内の複数のgeotiffファイル
- CSVファイル： workspace/data/maps/map_info.csv
- 出力先： workspace/data/maps/merged_map.tif

map_info.csvのフォーマット例:
id,BJC_code,grid,x1,y1,x2,y2,x3,y3,x4,y4

- ファイル名： grid_modified.tif
- 4隅の座標：(x1, y1), (x2, y2), (x3, y3), (x4, y4)座標はEPSG:5897 の値
1:北西端, 2:北東端, 3:南東端, 4:南西端を示す

出力条件：
- 出力ファイル名： merged_map.tif
- 出力形式： GeoTIFF
- 座標参照系： EPSG:5897

注意：
- 入力する地図データは23枚で、それぞれが隣接している
- 地図データは手動でジオリファレンスして保存したものであり、位置情報は確認したが、誤差がある
- クリップと結合の際に、地図データの重複部分や隙間が生じる可能性があるため、適切に処理する必要がある
- 出力地図の解像度は、入力地図の解像度と同じにする

入力パラメータ:
- merge_method: 結合方法（デフォルトは 'first'）。他に 'last', 'min', 'max', 'mean', 'median', 'mode' などが利用可能
- merge_nodata: 結合時のNoData値（デフォルトは None）
- merge_res: 結合後の解像度（デフォルトは None、入力地図の解像度を使用）
- merge_dst_crs: 結合後の座標参照系（デフォルトは None、入力地図のCRSを使用）
- merge_bounds: 結合範囲（デフォルトは None、全範囲を使用）

結合方法の詳細：
'first'（デフォルト）
最初に出現した画像の値を採用します。リストの先頭画像が優先されます。
'last'
最後に出現した画像の値を採用します。リストの末尾画像が優先されます。
'min'
重複領域の値の最小値を採用します。
'max'
重複領域の値の最大値を採用します。
'sum'
重複領域の値を合計します。
'count'
重複領域に値が存在する画像の枚数をカウントします（値自体ではなく「重なり数」）。


"""

# 必要なライブラリのインポート
import os
import tempfile
import pandas as pd
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
from shapely.geometry import Polygon, mapping
from rasterio.warp import calculate_default_transform, reproject, Resampling

# パス設定
MAP_INFO_PATH = "data\input\maps\map_info.csv"
MAPS_DIR = "data\input\maps"
OUTPUT_PATH = "data\output\maps/merged_map.tif"
CRS = "EPSG:5897"

# パラメータ設定
MERGE_METHOD = 'first'  # 'first', 'last', 'min', 'max', 'mean', 'median', 'mode' など
MERGE_NODATA = None  # Noneの場合、入力データのNoData値を使用
MERGE_RES = None  # Noneの場合、入力データの解像度を使用
MERGE_DST_CRS = None  # Noneの場合、入力データのCRSを使用
MERGE_BOUNDS = None  # Noneの場合、全範囲を使用


def read_map_info(csv_path):
    df = pd.read_csv(csv_path)
    return df

def get_polygon(row):
    # 4隅の座標からポリゴン作成
    coords = [
        (row['x1'], row['y1']),
        (row['x2'], row['y2']),
        (row['x3'], row['y3']),
        (row['x4'], row['y4']),
        (row['x1'], row['y1']) # 閉じる
    ]
    return Polygon(coords)


def validate_raster(raster_path, reference_crs=None, reference_res=None):
    """
    1. ファイル存在確認
    2. CRS一致確認（reference_crs指定時）
    3. 解像度一致確認（reference_res指定時）
    """
    if not os.path.exists(raster_path):
        print(f"ファイルが存在しません: {raster_path}")
        return False, None, None
    with rasterio.open(raster_path) as src:
        crs = src.crs.to_string() if src.crs else None
        res = src.res
        if reference_crs and crs != reference_crs:
            print(f"CRS不一致: {raster_path} (CRS: {crs}) → {reference_crs} である必要あり")
            return False, crs, res
        if reference_res and (abs(res[0] - reference_res[0]) > 1e-3 or abs(res[1] - reference_res[1]) > 1e-3):
            print(f"解像度不一致: {raster_path} (res: {res}) → {reference_res} である必要あり")
            return False, crs, res
    return True, crs, res
    
    

def clip_raster(raster_path, polygon):
    with rasterio.open(raster_path) as src:
        out_image, out_transform = mask(src, [mapping(polygon)], crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
            "crs": CRS
        })
    return out_image, out_meta

def main(
    merge_method=MERGE_METHOD,
    merge_nodata=MERGE_NODATA,
    merge_res=MERGE_RES,
    merge_dst_crs=MERGE_DST_CRS,
    merge_bounds=MERGE_BOUNDS
):
    # 1. map_info.csv 読み込み
    map_info = read_map_info(MAP_INFO_PATH)
    print(f"地図情報ファイル読み込み: {len(map_info)} 枚")

    clipped_files = []
    clipped_metas = []
    validation_results = []

    # 2. 各地図データをクリップ
    reference_crs = CRS
    reference_res = None
    for idx, row in map_info.iterrows():
        grid = row['grid']
        tiff_name = f"{grid}_modified.tif"
        tiff_path = os.path.join(MAPS_DIR, tiff_name)
        polygon = get_polygon(row)
        print(f"[{idx+1}/{len(map_info)}] クリップ前バリデーション: {tiff_name}")
        valid, crs, res = validate_raster(tiff_path, reference_crs, reference_res)
        # バリデーション結果を記録
        validation_results.append({
            "filename": tiff_name,
            "crs": crs,
            "res_x": res[0] if res else None,
            "res_y": res[1] if res else None,
            "valid": valid
        })
        if not valid:
            print(f"バリデーション失敗: {tiff_name}。処理を中断します。")
            # CSV出力してから中断
            pd.DataFrame(validation_results).to_csv("workspace/data/maps/validation_results.csv", index=False)
            return
        if reference_res is None:
            reference_res = res  # 最初の画像の解像度を基準に
        print(f"[{idx+1}/{len(map_info)}] クリップ中: {tiff_name}")
        clipped_img, clipped_meta = clip_raster(tiff_path, polygon)
        if clipped_img is not None:
            tmpfile = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
            with rasterio.open(tmpfile.name, "w", **clipped_meta) as dst:
                dst.write(clipped_img)
            clipped_files.append(tmpfile.name)
            clipped_metas.append(clipped_meta)

    # バリデーション結果をCSV出力
    pd.DataFrame(validation_results).to_csv("data/output/maps/validation_results.csv", index=False)

    print(f"クリップ完了: {len(clipped_files)} 枚")

    # 3. 結合
    print("地図データ結合中...")
    srcs = [rasterio.open(f) for f in clipped_files]
    # merge関数のパラメータをdictでまとめる
    merge_kwargs = {
        'method': merge_method
    }
    if merge_nodata is not None:
        merge_kwargs['nodata'] = merge_nodata
    if merge_res is not None:
        merge_kwargs['res'] = merge_res
    if merge_dst_crs is not None:
        merge_kwargs['dst_crs'] = merge_dst_crs
    if merge_bounds is not None:
        merge_kwargs['bounds'] = merge_bounds

    merged_img, merged_transform = merge(srcs, **merge_kwargs)
    merged_meta = clipped_metas[0].copy()
    merged_meta.update({
        "height": merged_img.shape[1],
        "width": merged_img.shape[2],
        "transform": merged_transform,
        "crs": CRS,
        "count": merged_img.shape[0]
    })

    # 4. 保存（バンドごとに書き込み）
    print(f"保存: {OUTPUT_PATH}")
    with rasterio.open(OUTPUT_PATH, "w", **merged_meta) as dest:
        for i in range(merged_img.shape[0]):
            dest.write(merged_img[i], i + 1)
    print("完了")

if __name__ == "__main__":
    main()