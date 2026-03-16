"""
GeoPackageをVN-2000からWGS84へ変換（ogr2ogr版）

用途：
  merge_*.gpkgをWGS84に変換（GeoPandasでUTF-8エラーが出るファイル対応）

機能：
  - ogr2ogrを直接使用（エンコーディング問題を回避）
  - VN-2000 (EPSG:3405) → WGS84 (EPSG:4326)
  - ジオメトリ検証・修復オプション付き

作成日：2026-02-27
"""
import argparse
import subprocess
from pathlib import Path
import logging

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/output/convert_to_wgs84_ogr.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_ogr2ogr_path() -> str:
    """ogr2ogrの実行ファイルパスを取得"""
    candidates = [
        r"C:\Program Files\QGIS 3.40.11\bin\ogr2ogr.exe",
        r"C:\OSGeo4W\bin\ogr2ogr.exe",
        r"C:\OSGeo4W64\bin\ogr2ogr.exe",
        "ogr2ogr",
    ]
    for path in candidates:
        try:
            subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"ogr2ogr検出: {path}")
            return path
        except Exception:
            pass
    raise SystemExit("ogr2ogrが見つかりません。")


def convert_gpkg_to_wgs84(
    input_gpkg: Path,
    output_gpkg: Path,
    ogr2ogr_path: str,
    source_crs: str = "EPSG:3405"
) -> dict:
    """GeoPackageをWGS84に変換
    
    Args:
        input_gpkg: 入力GPKGファイル
        output_gpkg: 出力GPKGファイル
        ogr2ogr_path: ogr2ogrパス
        source_crs: 元の座標系（デフォルト: EPSG:3405 VN-2000 Hanoi）
        
    Returns:
        処理結果の辞書
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"WGS84変換: {input_gpkg.name}")
    logger.info(f"{'='*80}")
    
    if not input_gpkg.exists():
        logger.error(f"入力ファイルが存在しません: {input_gpkg}")
        return {'status': 'error', 'message': 'Input file not found'}
    
    # 出力ディレクトリ作成
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    
    # 既存の出力ファイルを削除
    if output_gpkg.exists():
        logger.info(f"既存ファイルを削除: {output_gpkg}")
        output_gpkg.unlink()
    
    # ogr2ogrコマンド構築
    cmd = [
        ogr2ogr_path,
        "-f", "GPKG",
        str(output_gpkg),
        str(input_gpkg),
        "-s_srs", source_crs,  # 元の座標系を明示的に指定
        "-t_srs", "EPSG:4326",  # WGS84へ変換
        "-makevalid",  # ジオメトリ検証・修復
        "-progress",  # 進捗表示
    ]
    
    logger.info(f"変換元座標系: {source_crs}")
    logger.info(f"変換先座標系: EPSG:4326 (WGS84)")
    logger.info(f"変換中...")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=600  # 10分タイムアウト
        )
        
        logger.info(f"✅ 変換成功: {output_gpkg.name}")
        
        # 出力ファイルサイズ確認
        file_size_mb = output_gpkg.stat().st_size / (1024 * 1024)
        logger.info(f"   出力サイズ: {file_size_mb:.2f} MB")
        
        # ogrinfoで地物数確認
        ogrinfo_path = ogr2ogr_path.replace("ogr2ogr", "ogrinfo")
        info_result = subprocess.run(
            [ogrinfo_path, "-al", "-so", str(output_gpkg)],
            capture_output=True,
            text=True
        )
        
        # Feature Countを抽出
        feature_count = None
        for line in info_result.stdout.split('\n'):
            if "Feature Count:" in line:
                try:
                    feature_count = int(line.split(":")[-1].strip())
                    logger.info(f"   地物数: {feature_count:,}")
                    break
                except:
                    pass
        
        logger.info(f"{'='*80}\n")
        
        return {
            'status': 'success',
            'output_file': str(output_gpkg),
            'file_size_mb': round(file_size_mb, 2),
            'feature_count': feature_count
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️  タイムアウト: {input_gpkg.name}")
        return {'status': 'timeout', 'message': 'Timeout (600s)'}
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 変換失敗: {input_gpkg.name}")
        logger.error(f"   エラー: {e.stderr[:500]}")
        return {'status': 'error', 'message': e.stderr[:500]}


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="GeoPackageをVN-2000からWGS84へ変換"
    )
    parser.add_argument(
        "suffixes",
        nargs="+",
        choices=["CS", "DC", "DH", "GT", "RG", "TH", "TV"],
        help="変換するデータ種類（複数指定可）"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("整備データ/merge"),
        help="入力GPKGディレクトリ"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/output/gis_wgs84"),
        help="出力GPKGディレクトリ"
    )
    parser.add_argument(
        "--source-crs",
        default="EPSG:3405",
        help="元の座標系（デフォルト: EPSG:3405）"
    )
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("GeoPackage WGS84変換処理（ogr2ogr版）")
    logger.info("=" * 80)
    logger.info(f"入力ディレクトリ: {args.input_dir}")
    logger.info(f"出力ディレクトリ: {args.output_dir}")
    
    # ogr2ogr取得
    ogr2ogr_path = get_ogr2ogr_path()
    
    # 各種類を処理
    all_stats = []
    for suffix in args.suffixes:
        input_file = args.input_dir / f"merge_{suffix}.gpkg"
        output_file = args.output_dir / f"merge_{suffix}_wgs84.gpkg"
        
        stats = convert_gpkg_to_wgs84(
            input_file,
            output_file,
            ogr2ogr_path,
            args.source_crs
        )
        stats['suffix'] = suffix
        all_stats.append(stats)
    
    # 総括レポート
    logger.info("\n" + "=" * 80)
    logger.info("総括レポート")
    logger.info("=" * 80)
    
    success_count = 0
    total_features = 0
    total_size_mb = 0
    
    for stat in all_stats:
        suffix = stat['suffix']
        status = stat['status']
        
        if status == 'success':
            logger.info(f"✅ {suffix}: 変換成功")
            logger.info(f"   地物数: {stat.get('feature_count', 'N/A'):,}")
            logger.info(f"   サイズ: {stat.get('file_size_mb', 0)} MB")
            success_count += 1
            if stat.get('feature_count'):
                total_features += stat['feature_count']
            if stat.get('file_size_mb'):
                total_size_mb += stat['file_size_mb']
        else:
            logger.error(f"❌ {suffix}: {status}")
    
    logger.info("")
    logger.info(f"成功: {success_count}/{len(all_stats)}")
    logger.info(f"総地物数: {total_features:,}")
    logger.info(f"総サイズ: {total_size_mb:.2f} MB")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
