"""
Google Earth Engineを使用したLandsat 8地表面温度（LST）計算プログラム

本プログラムは以下の論文の手法に基づく：
Ermida, S.L., Soares, P., Mantas, V., Göttsche, F.-M., Trigo, I.F., 2020.
Google Earth Engine open-source code for Land Surface Temperature estimation
from the Landsat series. Remote Sensing, 12 (9), 1471.
https://doi.org/10.3390/rs12091471

設定ファイルはdef main()内の
config_path = r"data\input\gee_calc_LST_info.csv"
で指定されたパスにあるCSVファイルを使用。

CSVファイルの例は以下の通り：
roi_shapefile_path,start_date,end_date,cloud_threshold,valid_pixel_threshold,output_epsg,lst_method,gee_project_id,city_name,drive_root_folder,drive_export_folder
data\GISData\ROI\hanoi\hanoi_roi.shp,2023-07-01,2023-08-31,30,50,4326,smw,YOUR_GCP_PROJECT_ID,hanoi,MasterResearch_Data,

"""

import ee
import geopandas as gpd
import pandas as pd
import numpy as np
import re
from pathlib import Path
from typing import Dict, List, Tuple
from tqdm import tqdm
import logging

# SMW手法モジュールをインポート
from src.module.lst_smw import calculate_lst_smw

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def authenticate_gee(project_id: str = None) -> None:
    """Google Earth Engineの認証と初期化
    
    Args:
        project_id: Google Cloud Platform プロジェクトID
    
    初回実行時はブラウザで認証が必要
    """
    try:
        ee.Initialize(project=project_id)
        logger.info(f"GEEはすでに認証されています (プロジェクト: {project_id})")
    except Exception:
        logger.info("GEEを認証しています...")
        try:
            ee.Authenticate()
            ee.Initialize(project=project_id)
            logger.info(f"GEE認証に成功しました (プロジェクト: {project_id})")
        except Exception as e:
            logger.error(f"GEE認証エラー: {e}")
            raise


def load_config(csv_path: str) -> Dict:
    """設定ファイル（CSV）を読み込む
    
    Args:
        csv_path: 設定CSVファイルのパス
        
    Returns:
        設定情報を含む辞書
        
    Raises:
        FileNotFoundError: CSVファイルが存在しない場合
        ValueError: CSVの形式が不正な場合
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"設定ファイルが存在しません: {csv_path}")
    
    try:
        df = pd.read_csv(csv_path)
        if len(df) == 0:
            raise ValueError("設定ファイルが空です")
        
        config = df.iloc[0].to_dict()
        logger.info(f"設定ファイルの内容: {config}")
        return config
    except Exception as e:
        logger.error(f"設定ファイルの読み込みに失敗しました: {e}")
        raise


def load_roi_from_shapefile(shapefile_path: str) -> ee.Geometry:
    """ShapefileからROIを読み込み、GEE用のGeometryに変換
    この関数は、再利用性が低いです（特定の形式のShapefileに依存しているため）。
    ベトナムハノイ市のROIを抽出するように設計されています。
    
    Args:
        shapefile_path: Shapefileのパス
        
    Returns:
        ee.Geometry.Polygon
        
    Raises:
        FileNotFoundError: Shapefileが存在しない場合
    """
    shp_path = Path(shapefile_path)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefileが存在しません: {shapefile_path}")
    
    try:
        # Shapefileを読み込み
        boundary_df = gpd.read_file(shapefile_path)
        
        # WGS84（EPSG:4326）に変換（Google Earth Engineは内部的にWGS84（EPSG:4326）の経度・緯度を使用するため）
        if boundary_df.crs.to_epsg() != 4326:
            boundary_df = boundary_df.to_crs(epsg=4326)
            logger.info(f"ROIをEPSG:4326に再投影しました")
        
        # 'TinhThanh'カラムで'Hà Nội'をフィルタリング
        hanoi_geom = boundary_df[boundary_df['TinhThanh'] == 'Hà Nội'].iloc[0].geometry
        
        # GEE用のGeometryに変換（__geo_interface__を使用）
        ee_geom = ee.Geometry(hanoi_geom.__geo_interface__)
        
        logger.info(f"ROIの読み込み完了（Hà Nội）")
        return ee_geom
    except Exception as e:
        logger.error(f" ROIの読み込みに失敗しました: {e}")
        raise

def load_roi_from_shapefile_jp(shapefile_path: str) -> ee.Geometry:
    """ShapefileからROIを読み込み、GEE用のGeometryに変換
    この関数は、再利用性が低いです（特定の形式のShapefileに依存しているため）。
    大阪府のROIを抽出するように設計されています。
    国土数値情報ダウンロードサービスの行政区域データを想定。
    

    Args:
        shapefile_path: Shapefileのパス
        
    Returns:
        ee.Geometry.Polygon
        
    Raises:
        FileNotFoundError: Shapefileが存在しない場合
    """
    shp_path = Path(shapefile_path)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefileが存在しません: {shapefile_path}")
    
    try:
        # Shapefileを読み込み
        boundary_df = gpd.read_file(shapefile_path)
        
        # WGS84（EPSG:4326）に変換（Google Earth Engineは内部的にWGS84（EPSG:4326）の経度・緯度を使用するため）
        if boundary_df.crs.to_epsg() != 4326:
            boundary_df = boundary_df.to_crs(epsg=4326)
            logger.info(f"ROIをEPSG:4326に再投影しました")
        
        # 'N03_001'カラムで'大阪府'をフィルタリングし、全てのジオメトリを結合
        osaka_df = boundary_df[boundary_df['N03_001'] == '大阪府']
        if osaka_df.empty:
            raise ValueError("Shapefileに大阪府のデータが見つかりませんでした")
        # 全てのジオメトリを結合（MultiPolygonも含めて大阪府全体）
        osaka_geom = osaka_df.geometry.unary_union
        # GEE用のGeometryに変換（__geo_interface__を使用）
        ee_geom = ee.Geometry(osaka_geom.__geo_interface__)
        logger.info(f"ROIの読み込み完了（大阪府全体, ポリゴン数: {len(osaka_df)}）")
        return ee_geom
    except Exception as e:
        logger.error(f" ROIの読み込みに失敗しました: {e}")
        raise


def cloud_mask(image: ee.Image) -> ee.Image:
    """雲と影をマスクする
    
    Args:
        image: Landsat 8 Collection 2 Level-2画像
        
    Returns:
        マスク適用済み画像
    """
    qa = image.select('QA_PIXEL')
    # ビット3: 雲の影 (0=影なし)
    shadow = qa.bitwiseAnd(1 << 3).eq(0)
    # ビット4: 雲 (0=雲なし)
    cloud = qa.bitwiseAnd(1 << 4).eq(0)
    
    return image.updateMask(cloud.And(shadow))


def get_landsat8_collection(
    start_date: str,
    end_date: str,
    roi: ee.Geometry
) -> tuple:
    """Landsat 8データセットを取得（TOAとSRの両方）
    
    Args:
        start_date: 開始日（YYYY-MM-DD形式）
        end_date: 終了日（YYYY-MM-DD形式）
        roi: 対象地域
        
    Returns:
        (TOAコレクション, SRコレクション)のタプル
    """
    # TOAコレクション（熱赤外バンドB10用）
    collection_toa = ee.ImageCollection('LANDSAT/LC08/C02/T1_TOA') \
        .filterDate(start_date, end_date) \
        .filterBounds(roi)
    
    # SRコレクション（可視光・近赤外バンド用）
    collection_sr = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterDate(start_date, end_date) \
        .filterBounds(roi) \
        .map(cloud_mask)
    
    count = collection_sr.size().getInfo()
    logger.info(f"指定期間内に {count} 個のLandsat 8画像が見つかりました")
    
    return collection_toa, collection_sr


def get_matching_toa_image(
    image_sr: ee.Image,
    collection_toa: ee.ImageCollection
) -> ee.Image:
    """SR画像に対応する同一シーンのTOA画像を取得する

    元の JavaScript 実装では `combine(..., true)` により、
    同一シーン ID を持つ SR/TOA のみを結合している。
    Python 版でも同じ前提を明示し、`system:index` で対応付ける。

    Args:
        image_sr: Surface Reflectance 画像
        collection_toa: TOA 画像コレクション

    Returns:
        対応する TOA 画像

    Raises:
        ValueError: 対応する TOA 画像が見つからない場合
    """
    scene_index = image_sr.get('system:index')
    matched_toa = collection_toa.filter(ee.Filter.eq('system:index', scene_index))
    match_count = matched_toa.size().getInfo()
    scene_index_text = ee.String(scene_index).getInfo()

    if match_count == 0:
        raise ValueError(
            f"SR画像に対応するTOA画像が見つかりません: system:index={scene_index_text}"
        )

    if match_count > 1:
        logger.warning(
            "同一system:indexに対して複数のTOA画像が見つかりました。"
            f"先頭を採用します: system:index={scene_index_text}, matches={match_count}"
        )

    return ee.Image(matched_toa.first())


def calculate_lst_simple(image: ee.Image) -> ee.Image:
    """Simple手法でLST計算（スケーリング＋摂氏変換のみ）
    テスト用に残している
    Args:
        image: Landsat 8画像
        
    Returns:
        LSTバンドを追加した画像
    """
    # ST_B10バンドを選択してスケーリング
    temp_k = image.select('ST_B10').multiply(0.00341802).add(149.0)
    # ケルビンから摂氏に変換
    temp_c = temp_k.subtract(273.15).rename('LST')
    
    return image.addBands(temp_c)


def calculate_pixel_stats(image: ee.Image, roi: ee.Geometry) -> Dict:
    """ピクセル統計を計算（全体・有効ピクセル数）
    
    Args:
        image: LST計算済みの画像
        roi: 対象地域
        
    Returns:
        ピクセル統計情報
    """
    lst = image.select('LST')
    
    # 全体ピクセル数（マスクなし）
    total_pixels = ee.Number(lst.unmask().reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=roi,
        scale=30,
        maxPixels=1e9
    ).get('LST'))
    
    # 有効ピクセル数（マスク後）
    valid_pixels = ee.Number(lst.reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=roi,
        scale=30,
        maxPixels=1e9
    ).get('LST'))
    
    return {
        'total_pixels': total_pixels.getInfo(),
        'valid_pixels': valid_pixels.getInfo()
    }


def extract_statistics(image: ee.Image, roi: ee.Geometry) -> Dict:
    """温度統計値を抽出
    
    Args:
        image: LST計算済みの画像（摂氏温度）
        roi: 対象地域
        
    Returns:
        統計値を含む辞書（摂氏温度）
    """
    lst = image.select('LST')
    
    # 統計値を計算（摂氏温度）
    stats = lst.reduceRegion(
        reducer=ee.Reducer.mean()
                .combine(ee.Reducer.min(), '', True)
                .combine(ee.Reducer.max(), '', True)
                .combine(ee.Reducer.stdDev(), '', True),
        geometry=roi,
        scale=30,
        maxPixels=1e9
    )
    
    return {
        'mean': stats.get('LST_mean').getInfo(),
        'min': stats.get('LST_min').getInfo(),
        'max': stats.get('LST_max').getInfo(),
        'std': stats.get('LST_stdDev').getInfo()
    }


def should_export(valid_pixel_ratio: float, threshold: float) -> bool:
    """エクスポート判定
    
    Args:
        valid_pixel_ratio: 有効ピクセル割合
        threshold: 閾値
        
    Returns:
        エクスポートすべきかどうか
    """
    return valid_pixel_ratio >= threshold


def save_results_to_csv(results: List[Dict], output_path: str) -> None:
    """結果をCSVファイルに保存
    
    Args:
        results: 結果のリスト
        output_path: 出力CSVファイルのパス
    """
    df = pd.DataFrame(results)
    
    # 出力ディレクトリを作成
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    df.to_csv(output_path, index=False)
    logger.info(f"Results saved to {output_path}")


def _normalize_config_value(value, default: str) -> str:
    """設定値を文字列として正規化する

    pandasで読み込んだNaNや空文字を安全に扱うための補助関数。

    Args:
        value: 設定値
        default: 既定値

    Returns:
        正規化済みの文字列
    """
    if value is None:
        return default

    if isinstance(value, float) and np.isnan(value):
        return default

    text = str(value).strip()
    if not text:
        return default

    return text


def _sanitize_drive_token(text: str) -> str:
    """Driveフォルダ名に使える文字列へ整形する"""
    normalized = text.lower().replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown"


def build_drive_export_folder(config: Dict, date_text: str) -> str:
    """Google Driveのエクスポート先フォルダ名を構築する

    優先順位:
    1. drive_export_folder が設定されていればその値を使用
    2. それ以外は city_name と日付から規則的に構築
    """
    explicit_folder = _normalize_config_value(config.get('drive_export_folder'), '')
    if explicit_folder:
        return explicit_folder

    drive_root = _normalize_config_value(config.get('drive_root_folder'), 'MasterResearch_Data')
    city_name = _normalize_config_value(config.get('city_name'), 'unknown_city')
    city_token = _sanitize_drive_token(city_name)
    year = date_text[:4]

    return f"{drive_root}_LST_{city_token}_{year}"


def export_to_drive(
    image: ee.Image,
    description: str,
    folder: str,
    roi: ee.Geometry,
    scale: int,
    crs: str
) -> None:
    """GeoTIFFをGoogle Driveにエクスポート
    
    Args:
        image: エクスポートする画像
        description: タスクの説明
        folder: Google Driveの出力先フォルダ名
        roi: 対象地域
        scale: 解像度（メートル）
        crs: 座標参照系（例: 'EPSG:32648'）
    """
    task = ee.batch.Export.image.toDrive(
        image=image.select('LST'),
        description=description,
        folder=folder,
        fileNamePrefix=description,
        scale=scale,
        region=roi,
        crs=crs,
        fileFormat='GeoTIFF',
        maxPixels=1e9
    )
    
    task.start()
    logger.info(f"Export task started: {description} -> Drive folder: {folder}")


def process_image(
    image_sr: ee.Image,
    image_toa: ee.Image,
    config: Dict,
    roi: ee.Geometry
) -> Tuple[ee.Image, Dict]:
    """画像処理（手法に応じて分岐）
    
    Args:
        image_sr: Landsat 8 Surface Reflectance画像
        image_toa: Landsat 8 TOA画像（B10バンド用）
        config: 設定情報
        roi: 対象地域
        
    Returns:
        処理済み画像と統計情報のタプル
    """
    lst_method = config['lst_method']
    
    # LST計算（手法に応じて分岐）
    if lst_method == 'simple':
        image = calculate_lst_simple(image_sr)
    elif lst_method == 'smw':
        image = calculate_lst_smw(image_sr, image_toa, roi)
    else:
        raise ValueError(f"Unknown LST method: {lst_method}")
    
    # 日付と雲量を取得（SRから）
    date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    cloud_cover = image.get('CLOUD_COVER').getInfo()
    
    # ピクセル統計を計算
    pixel_stats = calculate_pixel_stats(image, roi)
    total_pixels = pixel_stats['total_pixels']
    valid_pixels = pixel_stats['valid_pixels']
    valid_pixel_ratio = (valid_pixels / total_pixels * 100) if total_pixels > 0 else 0
    
    # 温度統計を計算
    temp_stats = extract_statistics(image, roi)
    
    # 結果を統合
    result = {
        'date': date,
        'satellite': 'Landsat8',
        'mean_temp_c': temp_stats['mean'],
        'min_temp_c': temp_stats['min'],
        'max_temp_c': temp_stats['max'],
        'std_temp_c': temp_stats['std'],
        'total_pixels': total_pixels,
        'valid_pixels': valid_pixels,
        'valid_pixel_ratio': valid_pixel_ratio,
        'cloud_cover': cloud_cover,
        'exported': False,
        'drive_folder': ''
    }
    
    # エクスポート判定
    if should_export(valid_pixel_ratio, config['valid_pixel_threshold']):
        result['exported'] = True
        # エクスポート
        description = f"LST_Landsat8_{date.replace('-', '')}"
        crs = f"EPSG:{int(config['output_epsg'])}"
        drive_folder = build_drive_export_folder(config, date)
        result['drive_folder'] = drive_folder
        export_to_drive(image, description, drive_folder, roi, 30, crs)
    
    return image, result


def main():
    """メイン処理"""
    try:
        # 設定ファイル読み込み
        logger.info("LST計算プログラムを開始します...")
        config_path = r"data\input\gee_calc_LST_info.csv"
        config = load_config(config_path)
        
        # GEE認証
        gee_project_id = config.get('gee_project_id')
        if not gee_project_id or gee_project_id == 'YOUR_GCP_PROJECT_ID':
            logger.error("GCPプロジェクトIDが設定されていません。configファイルを確認してください。")
            return
        authenticate_gee(gee_project_id)
        
        # ROI読み込み
        roi = load_roi_from_shapefile(config['roi_shapefile_path'])
        
        # Landsat 8データセット取得（TOAとSR）
        collection_toa, collection_sr = get_landsat8_collection(
            config['start_date'],
            config['end_date'],
            roi
        )
        
        # 画像リストを取得
        image_list_sr = collection_sr.toList(collection_sr.size())
        count = collection_sr.size().getInfo()
        
        if count == 0:
            logger.warning("ROI内に利用可能なLandsat 8画像がありません。終了します。")
            return
        
        # 各画像を処理
        results = []
        logger.info(f"{count} 個の画像を {config['lst_method']} 手法で処理します...")
        
        for i in tqdm(range(count), desc="画像を処理中"):
            try:
                image_sr = ee.Image(image_list_sr.get(i))
                image_toa = get_matching_toa_image(image_sr, collection_toa)
                _, result = process_image(image_sr, image_toa, config, roi)
                results.append(result)
                
                # 統計値がNoneの場合の処理
                mean_str = f"{result['mean_temp_c']:.2f}°C" if result['mean_temp_c'] is not None else "N/A"
                logger.info(
                    f"{result['date']} を処理しました: "
                    f"平均={mean_str}, "
                    f"有効ピクセル={result['valid_pixel_ratio']:.1f}%"
                )
            except Exception as e:
                logger.error(f"画像 {i} の処理中にエラーが発生しました: {e}")
                continue
        
        # 結果をCSVに保存
        output_path = r"data\output\gee_calc_LST_results.csv"
        save_results_to_csv(results, output_path)
        
        # サマリー表示
        exported_count = sum(1 for r in results if r['exported'])
        logger.info(f"\n{'='*60}")
        logger.info(f"処理が完了しました！")
        logger.info(f"処理した画像の総数: {len(results)}")
        logger.info(f"Google Driveにエクスポートされた画像数: {exported_count}")
        logger.info(f"結果が保存されたパス: {output_path}")
        logger.info(f"{'='*60}\n")
        
    except Exception as e:
        logger.error(f"プログラムが失敗しました: {e}")
        raise


if __name__ == '__main__':
    main()
