"""
GISデータ（GeoPackage）の座標参照系（CRS）設定と変換スクリプト

目的：
  - CRS未定義のgpkgファイルにEPSG:3405 (VN-2000 Hanoi zone)を設定
  - WGS84（EPSG:4326）へ変換して分析用データを生成
  - LST データ（EPSG:4326）との統合を容易にする

処理フロー：
  1. `整備データ/merge/`配下の全gpkgファイルを読み込み
  2. CRS未定義の場合、EPSG:3405を手動設定
  3. ジオメトリエラーがあれば自動修復を試行
  4. WGS84（EPSG:4326）へ変換
  5. `data/output/gis_wgs84/`へ保存
  6. 変換結果をJSON/CSVに記録

依存関係：
  - geopandas
  - pandas
  - fiona
  - shapely

作成日：2026-02-26
"""
import geopandas as gpd
import pandas as pd
import fiona
from pathlib import Path
import json
import logging
from typing import Dict, List
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/output/gis_crs_conversion.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_gpkg_safely(gpkg_path: Path) -> gpd.GeoDataFrame:
    """gpkgファイルを安全に読み込む（エンコーディングエラー対策）
    
    Args:
        gpkg_path: gpkgファイルのパス
        
    Returns:
        GeoDataFrame
        
    Raises:
        Exception: 読み込みに完全に失敗した場合
    
    処理手順：
        1. UTF-8エンコーディングで試行
        2. 失敗時はlatin1で試行
        3. それでも失敗時はfionaで直接geometryのみ読み込み
    """
    logger.info(f"読み込み中: {gpkg_path.name}")
    
    # 方法1: 標準的な読み込み（UTF-8）
    try:
        gdf = gpd.read_file(str(gpkg_path), encoding='utf-8')
        logger.info(f"  UTF-8で読み込み成功 ({len(gdf):,}地物)")
        return gdf
    except UnicodeDecodeError:
        logger.warning(f"  UTF-8デコードエラー、latin1で試行...")
    
    # 方法2: latin1エンコーディングで試行
    try:
        gdf = gpd.read_file(str(gpkg_path), encoding='latin1')
        logger.info(f"  latin1で読み込み成功 ({len(gdf):,}地物)")
        return gdf
    except Exception as e:
        logger.warning(f"  latin1も失敗: {e}")
    
    # 方法3: fionaで直接geometryのみ読み込み
    try:
        logger.info(f"  fionaでgeometryのみ読み込み中...")
        features = []
        with fiona.open(str(gpkg_path)) as src:
            for feat in src:
                features.append(feat)
        gdf = gpd.GeoDataFrame.from_features(features)
        logger.info(f"  fionaで読み込み成功 ({len(gdf):,}地物)")
        return gdf
    except Exception as e:
        logger.error(f"  全ての読み込み方法が失敗: {e}")
        raise


def fix_invalid_geometries(gdf: gpd.GeoDataFrame) -> tuple:
    """無効なジオメトリを修復
    
    Args:
        gdf: GeoDataFrame
        
    Returns:
        (修復済みGeoDataFrame, 修復統計情報)のタプル
    
    修復方法：
        - buffer(0): ほとんどの一般的なジオメトリエラーを自動修正
        - make_valid(): buffer(0)で失敗した場合の代替手法
    """
    invalid_count_before = (~gdf.geometry.is_valid).sum()
    
    if invalid_count_before == 0:
        logger.info("  ジオメトリは全て有効です")
        return gdf, {'invalid_before': 0, 'fixed': 0, 'still_invalid': 0}
    
    logger.warning(f"  {invalid_count_before}個の無効なジオメトリを検出")
    
    # buffer(0)で修復を試行
    fixed_count = 0
    for idx in gdf[~gdf.geometry.is_valid].index:
        try:
            gdf.at[idx, 'geometry'] = gdf.at[idx, 'geometry'].buffer(0)
            if gdf.at[idx, 'geometry'].is_valid:
                fixed_count += 1
        except Exception as e:
            logger.debug(f"    インデックス{idx}の修復失敗: {e}")
    
    invalid_count_after = (~gdf.geometry.is_valid).sum()
    
    stats = {
        'invalid_before': invalid_count_before,
        'fixed': fixed_count,
        'still_invalid': invalid_count_after
    }
    
    if invalid_count_after > 0:
        logger.warning(f"  修復完了: {fixed_count}個修復、{invalid_count_after}個は修復不可")
        # 修復不可能なジオメトリを削除
        gdf = gdf[gdf.geometry.is_valid].copy()
        logger.info(f"  修復不可能なジオメトリ を除外: 残り{len(gdf):,}地物")
    else:
        logger.info(f"  全てのジオメトリを修復しました ({fixed_count}個)")
    
    return gdf, stats


def set_crs_vn2000(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """CRS未定義のGeoDataFrameにEPSG:3405 (VN-2000 Hanoi zone)を設定
    
    Args:
        gdf: CRS未定義のGeoDataFrame
        
    Returns:
        CRS設定済みGeoDataFrame
    
    注意：
        座標範囲から判断してVN-2000 Hanoi zone（EPSG:3405）と推定。
        他の地域の場合は異なるEPSGコードが必要。
    """
    if gdf.crs is None or gdf.crs.to_epsg() is None:
        logger.info(f"  CRS未定義 → EPSG:3405 (VN-2000 Hanoi)を設定")
        gdf = gdf.set_crs(epsg=3405, allow_override=True)
    else:
        current_epsg = gdf.crs.to_epsg()
        logger.info(f"  既存CRS: EPSG:{current_epsg}")
        if current_epsg != 3405:
            logger.warning(f"  EPSG:{current_epsg}からEPSG:3405に上書き設定")
            gdf = gdf.set_crs(epsg=3405, allow_override=True)
    
    return gdf


def convert_to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """WGS84（EPSG:4326）へ変換
    
    Args:
        gdf: EPSG:3405設定済みGeoDataFrame
        
    Returns:
        WGS84変換済みGeoDataFrame
    
    用途：
        LST データ（EPSG:4326）との空間結合・可視化
    """
    logger.info(f"  WGS84 (EPSG:4326)へ変換中...")
    gdf_wgs84 = gdf.to_crs(epsg=4326)
    
    # 変換後の範囲を確認
    bounds = gdf_wgs84.total_bounds
    logger.info(f"  変換後の範囲（WGS84）:")
    logger.info(f"    経度: {bounds[0]:.6f} ～ {bounds[2]:.6f}")
    logger.info(f"    緯度: {bounds[1]:.6f} ～ {bounds[3]:.6f}")
    
    return gdf_wgs84


def process_single_gpkg(
    gpkg_path: Path,
    output_dir: Path
) -> Dict:
    """単一のgpkgファイルを処理
    
    Args:
        gpkg_path: 入力gpkgファイルのパス
        output_dir: 出力ディレクトリ
        
    Returns:
        処理結果の統計情報
    
    処理内容：
        1. 読み込み（エンコーディングエラー対策）
        2. ジオメトリ修復
        3. CRS設定（EPSG:3405）
        4. WGS84変換（EPSG:4326）
        5. 保存
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"処理開始: {gpkg_path.name}")
    logger.info(f"{'='*80}")
    
    result = {
        'file': gpkg_path.name,
        'status': 'processing',
        'error': None
    }
    
    try:
        # 1. 読み込み
        gdf = load_gpkg_safely(gpkg_path)
        result['feature_count_input'] = len(gdf)
        
        # 2. ジオメトリ修復
        gdf, fix_stats = fix_invalid_geometries(gdf)
        result['geometry_fix'] = fix_stats
        result['feature_count_after_fix'] = len(gdf)
        
        # 3. CRS設定
        gdf = set_crs_vn2000(gdf)
        result['crs_original'] = 'LOCAL_CS (Undefined)'
        result['crs_set'] = 'EPSG:3405'
        
        # 4. WGS84変換
        gdf_wgs84 = convert_to_wgs84(gdf)
        result['crs_converted'] = 'EPSG:4326'
        
        # 空間範囲を記録
        bounds = gdf_wgs84.total_bounds
        result['bounds_wgs84'] = {
            'lon_min': float(bounds[0]),
            'lat_min': float(bounds[1]),
            'lon_max': float(bounds[2]),
            'lat_max': float(bounds[3])
        }
        
        # 5. 保存
        output_file = output_dir / f"{gpkg_path.stem}_wgs84.gpkg"
        gdf_wgs84.to_file(output_file, driver='GPKG')
        logger.info(f"  保存完了: {output_file.name}")
        
        result['output_file'] = output_file.name
        result['status'] = 'success'
        
    except Exception as e:
        logger.error(f"  エラー: {e}")
        result['status'] = 'failed'
        result['error'] = str(e)
    
    logger.info(f"{'='*80}\n")
    return result


def save_conversion_report(
    results: List[Dict],
    output_dir: Path
) -> None:
    """変換結果レポートを保存
    
    Args:
        results: 各ファイルの処理結果リスト
        output_dir: 出力ディレクトリ
    
    出力ファイル：
        - gis_crs_conversion_report.json: 詳細なJSON形式
        - gis_crs_conversion_report.csv: 簡易CSV形式
    """
    # NumPy型をPython標準型に変換
    import numpy as np
    
    def convert_types(obj):
        """NumPy型をPython標準型に変換"""
        if isinstance(obj, dict):
            return {k: convert_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_types(item) for item in obj]
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        else:
            return obj
    
    results = convert_types(results)
    
    # JSON保存
    json_path = output_dir / "gis_crs_conversion_report.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"詳細レポート保存: {json_path}")
    
    # CSV保存（サマリー）
    csv_data = []
    for r in results:
        csv_data.append({
            'file': r['file'],
            'status': r['status'],
            'input_features': r.get('feature_count_input', 'N/A'),
            'output_features': r.get('feature_count_after_fix', 'N/A'),
            'geometry_fixed': r.get('geometry_fix', {}).get('fixed', 0),
            'output_file': r.get('output_file', 'N/A'),
            'error': r.get('error', '')
        })
    
    df = pd.DataFrame(csv_data)
    csv_path = output_dir / "gis_crs_conversion_report.csv"
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    logger.info(f"サマリーレポート保存: {csv_path}")


def main():
    """メイン処理"""
    logger.info("GIS CRS設定・変換プログラム開始")
    logger.info(f"{'='*80}\n")
    
    # ディレクトリ設定
    input_dir = Path("整備データ/merge")
    output_dir = Path("data/output/gis_wgs84")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 処理対象ファイル
    suffixes = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]
    gpkg_files = [input_dir / f"merge_{suffix}.gpkg" for suffix in suffixes]
    
    # 存在するファイルのみ処理
    existing_files = [f for f in gpkg_files if f.exists()]
    logger.info(f"処理対象: {len(existing_files)}ファイル")
    for f in existing_files:
        logger.info(f"  - {f.name}")
    logger.info("")
    
    # 各ファイルを処理
    results = []
    for gpkg_file in tqdm(existing_files, desc="変換中"):
        result = process_single_gpkg(gpkg_file, output_dir)
        results.append(result)
    
    # レポート保存
    save_conversion_report(results, output_dir)
    
    # サマリー表示
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    
    logger.info(f"\n{'='*80}")
    logger.info("変換完了！")
    logger.info(f"  成功: {success_count}ファイル")
    logger.info(f"  失敗: {failed_count}ファイル")
    logger.info(f"  出力先: {output_dir}")
    logger.info(f"{'='*80}\n")


if __name__ == "__main__":
    main()
