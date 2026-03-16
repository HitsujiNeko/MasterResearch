"""
DGNファイルをGeoPackageに統合（ジオメトリ修復版）

元のmerge_vector.pyに以下の改善を追加：
1. ogr2ogrに-makevalidオプションを追加（ジオメトリ自動修復）
2. -skipfailuresオプション（修復不可能なフィーチャをスキップ）
3. 処理ログの詳細化
4. エラーハンドリングの強化

依存関係：
  - GDAL/ogr2ogr（3.0以降推奨、-makevalidサポート）

作成日：2026-02-26
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
        logging.FileHandler('data/output/merge_vector_fixed.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SUFFIXES = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]


def get_ogr2ogr_path() -> str:
    """ogr2ogrの実行ファイルパスを取得
    
    Returns:
        ogr2ogrの実行可能パス
        
    Raises:
        SystemExit: ogr2ogrが見つからない場合
    
    優先順位：
        1. QGIS 3.40.11のバンドル版
        2. OSGeo4W（64bit/32bit）
        3. システムパス上のogr2ogr
    """
    candidates = [
        r"C:\Program Files\QGIS 3.40.11\bin\ogr2ogr.exe",
        r"C:\OSGeo4W\bin\ogr2ogr.exe",
        r"C:\OSGeo4W64\bin\ogr2ogr.exe",
        "ogr2ogr",
    ]
    for path in candidates:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                check=True
            )
            version = result.stdout.strip()
            logger.info(f"ogr2ogr検出: {path}")
            logger.info(f"バージョン: {version}")
            return path
        except Exception:
            pass
    
    raise SystemExit("ogr2ogrが見つかりません。GDALのインストール確認が必要です。")


def check_file_validity(dgn_file: Path, ogr2ogr_path: str) -> dict:
    """DGNファイルの有効性を事前チェック
    
    Args:
        dgn_file: DGNファイルのパス
        ogr2ogr_path: ogr2ogrの実行パス
        
    Returns:
        チェック結果の辞書（valid, layer_count, error_message）
    """
    try:
        # ogrinfo で情報取得を試みる
        ogrinfo_path = ogr2ogr_path.replace("ogr2ogr", "ogrinfo")
        result = subprocess.run(
            [ogrinfo_path, str(dgn_file)],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # レイヤー数をカウント
            layer_count = result.stdout.count("Layer name:")
            return {
                'valid': True,
                'layer_count': layer_count,
                'error_message': None
            }
        else:
            return {
                'valid': False,
                'layer_count': 0,
                'error_message': result.stderr
            }
    except Exception as e:
        return {
            'valid': False,
            'layer_count': 0,
            'error_message': str(e)
        }


def merge_to_geopackage(
    input_dir: Path,
    suffix: str,
    output_root: Path,
    ogr2ogr_path: str,
    skip_existing: bool = False
) -> dict:
    """DGNファイルをGeoPackageに統合（ジオメトリ修復付き）
    
    Args:
        input_dir: DGNファイルが格納されたディレクトリ
        suffix: データ種類（CS/DC/DH等）
        output_root: 出力先ディレクトリ
        ogr2ogr_path: ogr2ogrの実行パス
        skip_existing: 既存のGPKGファイルをスキップするか
        
    Returns:
        処理結果の辞書
    
    処理内容：
        1. DGNファイルのリストアップ
        2. 出力GPKGファイルの準備
        3. 最初のファイルでGPKG作成（-makevalidオプション付き）
        4. 残りのファイルをappend（-skipfailuresオプション付き）
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"処理開始: {suffix}")
    logger.info(f"{'='*80}")
    
    files = sorted(input_dir.glob("*.dgn"))
    if not files:
        logger.warning(f"No DGN files for {suffix} in {input_dir}")
        return {'status': 'no_files', 'file_count': 0}

    logger.info(f"検出されたDGNファイル数: {len(files)}")
    
    out_gpkg = output_root / f"merge_{suffix}.gpkg"
    
    # 既存ファイルのスキップチェック
    if skip_existing and out_gpkg.exists():
        logger.info(f"既存のファイルをスキップ: {out_gpkg}")
        return {'status': 'skipped', 'file_count': len(files)}
    
    # 既存ファイルを削除
    if out_gpkg.exists():
        logger.info(f"既存ファイルを削除: {out_gpkg}")
        out_gpkg.unlink()

    # 統計情報
    stats = {
        'status': 'processing',
        'total_files': len(files),
        'processed_files': 0,
        'failed_files': 0,
        'errors': []
    }

    # 最初のファイルでGPKGを作成
    first = files[0]
    logger.info(f"\n初期化: {first.name}")
    
    # GDAL 3.0以降では-makevalidが使用可能
    cmd_init = [
        ogr2ogr_path,
        "-f", "GPKG",
        str(out_gpkg),
        str(first),
        "-makevalid",  # ジオメトリ自動修復
        "-skipfailures",  # エラーフィーチャをスキップ
        "-progress"  # 進捗表示
    ]
    
    try:
        result = subprocess.run(
            cmd_init,
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"  ✅ 初期化成功: {first.name}")
        stats['processed_files'] += 1
    except subprocess.CalledProcessError as e:
        logger.error(f"  ❌ 初期化失敗: {first.name}")
        logger.error(f"     エラー: {e.stderr}")
        stats['failed_files'] += 1
        stats['errors'].append({'file': first.name, 'error': e.stderr})
        
        # 初期化失敗の場合は中止
        stats['status'] = 'failed'
        return stats

    # 残りのファイルをappend
    for i, f in enumerate(files[1:], 1):
        logger.info(f"\n追加中 ({i}/{len(files)-1}): {f.name}")
        
        cmd_append = [
            ogr2ogr_path,
            "-f", "GPKG",
            str(out_gpkg),
            str(f),
            "-update",
            "-append",
            "-makevalid",  # ジオメトリ自動修復
            "-skipfailures",  # エラーフィーチャをスキップ
        ]
        
        try:
            result = subprocess.run(
                cmd_append,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5分タイムアウト
            )
            logger.info(f"  ✅ 追加成功")
            stats['processed_files'] += 1
        except subprocess.CalledProcessError as e:
            logger.warning(f"  ⚠️ 追加失敗（スキップ）: {f.name}")
            logger.warning(f"     エラー: {e.stderr[:200]}")
            stats['failed_files'] += 1
            stats['errors'].append({'file': f.name, 'error': e.stderr[:200]})
        except subprocess.TimeoutExpired:
            logger.warning(f"  ⚠️ タイムアウト（スキップ）: {f.name}")
            stats['failed_files'] += 1
            stats['errors'].append({'file': f.name, 'error': 'Timeout (300s)'})

    # 最終結果
    if out_gpkg.exists():
        file_size_mb = out_gpkg.stat().st_size / (1024 * 1024)
        stats['status'] = 'success'
        stats['output_file'] = out_gpkg.name
        stats['output_size_mb'] = round(file_size_mb, 2)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"✅ 完了: {out_gpkg.name}")
        logger.info(f"   処理成功: {stats['processed_files']}/{stats['total_files']}")
        logger.info(f"   処理失敗: {stats['failed_files']}/{stats['total_files']}")
        logger.info(f"   出力サイズ: {stats['output_size_mb']} MB")
        logger.info(f"{'='*80}\n")
    else:
        stats['status'] = 'failed'
        logger.error(f"出力ファイルが作成されませんでした: {out_gpkg}")

    return stats


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="DGNを種類別にGeoPackageへ統合（ジオメトリ修復版）"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"整備データ"),
        help="Vector_* があるルートディレクトリ"
    )
    parser.add_argument(
        "--suffix",
        choices=SUFFIXES,
        help="特定種類のみ統合 (例: DC)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="既存のGPKGファイルをスキップ"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"整備データ/merge"),
        help="出力先ディレクトリ"
    )
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("DGNファイル統合処理（ジオメトリ修復版）")
    logger.info("=" * 80)
    logger.info(f"入力ディレクトリ: {args.root}")
    logger.info(f"出力ディレクトリ: {args.output}")
    
    # 出力ディレクトリ作成
    args.output.mkdir(parents=True, exist_ok=True)
    
    # ogr2ogrパス取得
    ogr2ogr_path = get_ogr2ogr_path()

    # 処理対象決定
    targets = [args.suffix] if args.suffix else SUFFIXES
    logger.info(f"処理対象: {', '.join(targets)}\n")

    # 各種類を処理
    all_stats = []
    for s in targets:
        in_dir = args.root / f"Vector_{s}"
        if not in_dir.exists():
            logger.warning(f"ディレクトリが見つかりません: {in_dir}")
            continue
        
        stats = merge_to_geopackage(
            in_dir,
            s,
            args.output,
            ogr2ogr_path,
            args.skip_existing
        )
        all_stats.append({'suffix': s, **stats})

    # 総括レポート
    logger.info("\n" + "=" * 80)
    logger.info("総括レポート")
    logger.info("=" * 80)
    
    for stat in all_stats:
        suffix = stat['suffix']
        status = stat['status']
        
        if status == 'success':
            logger.info(f"✅ {suffix}: {stat['processed_files']}/{stat['total_files']} 成功")
            logger.info(f"   出力: {stat.get('output_file', 'N/A')}")
            logger.info(f"   サイズ: {stat.get('output_size_mb', 0)} MB")
        elif status == 'skipped':
            logger.info(f"⏭️  {suffix}: スキップ済み")
        elif status == 'no_files':
            logger.warning(f"⚠️ {suffix}: DGNファイルなし")
        else:
            logger.error(f"❌ {suffix}: 処理失敗")
    
    logger.info("=" * 80)
    logger.info("処理完了")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
