"""
既存GPKGに残りのDGNファイルを追加（特定ファイルスキップ版）

用途：
  merge_vector_fixed.pyがハングした後、残りのファイルを処理

機能：
  - 既存のmerge_*.gpkgに対してappendのみ実行
  - スキップリストに指定したファイルを除外
  - タイムアウトを短縮（3分→早期スキップ）
  - 詳細ログ記録

作成日：2026-02-27
"""
import argparse
import subprocess
from pathlib import Path
import logging
from typing import List, Set

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/output/append_remaining.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 問題ファイルのデフォルトスキップリスト
DEFAULT_SKIP_FILES = [
    "F-48-68-(251-c)_2018_DC.dgn",  # DCでハング
]


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


def get_processed_files_from_log(log_file: Path) -> Set[str]:
    """ログファイルから処理済みファイルのリストを抽出
    
    Args:
        log_file: merge_vector_fixed.logのパス
        
    Returns:
        処理済みファイル名のセット
    """
    processed = set()
    
    if not log_file.exists():
        logger.warning(f"ログファイルが見つかりません: {log_file}")
        return processed
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # "✅ 追加成功" または "✅ 初期化成功" の直前の行からファイル名を抽出
                if "追加中" in line or "初期化" in line:
                    # 例: "追加中 (58/79): F-48-68-(251-b)_2018_DC.dgn"
                    parts = line.split(":")
                    if len(parts) >= 2:
                        filename = parts[-1].strip()
                        # 次の行で成功を確認
                        next_line = next(f, None)
                        if next_line and "成功" in next_line:
                            processed.add(filename)
                            logger.debug(f"処理済み: {filename}")
    except Exception as e:
        logger.error(f"ログファイル読み込みエラー: {e}")
    
    logger.info(f"ログから{len(processed)}個の処理済みファイルを検出")
    return processed


def append_remaining_files(
    input_dir: Path,
    suffix: str,
    output_gpkg: Path,
    ogr2ogr_path: str,
    skip_files: Set[str],
    processed_files: Set[str],
    timeout_seconds: int = 180
) -> dict:
    """既存GPKGに残りのDGNファイルを追加
    
    Args:
        input_dir: DGNファイルディレクトリ
        suffix: データ種類（DC等）
        output_gpkg: 既存のGPKGファイル
        ogr2ogr_path: ogr2ogrパス
        skip_files: スキップするファイル名のセット
        processed_files: 既に処理済みのファイル名のセット
        timeout_seconds: タイムアウト秒数（デフォルト3分）
        
    Returns:
        処理結果の辞書
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"残りファイルの追加処理: {suffix}")
    logger.info(f"{'='*80}")
    
    if not output_gpkg.exists():
        logger.error(f"出力ファイルが存在しません: {output_gpkg}")
        return {'status': 'error', 'message': 'Output file not found'}
    
    # 全DGNファイルを取得
    all_files = sorted(input_dir.glob("*.dgn"))
    logger.info(f"検出された全DGNファイル数: {len(all_files)}")
    
    # 処理対象ファイルをフィルタリング
    remaining_files = []
    for f in all_files:
        if f.name in skip_files:
            logger.warning(f"スキップリスト: {f.name}")
        elif f.name in processed_files:
            logger.debug(f"処理済み: {f.name}")
        else:
            remaining_files.append(f)
    
    logger.info(f"処理対象ファイル数: {len(remaining_files)}")
    
    if len(remaining_files) == 0:
        logger.info("処理すべき残りファイルはありません")
        return {'status': 'complete', 'processed': 0, 'failed': 0}
    
    # 統計情報
    stats = {
        'status': 'processing',
        'total_files': len(remaining_files),
        'processed_files': 0,
        'failed_files': 0,
        'skipped_files': 0,
        'errors': []
    }
    
    # 各ファイルを処理
    for i, dgn_file in enumerate(remaining_files, 1):
        logger.info(f"\n追加中 ({i}/{len(remaining_files)}): {dgn_file.name}")
        
        cmd_append = [
            ogr2ogr_path,
            "-f", "GPKG",
            str(output_gpkg),
            str(dgn_file),
            "-update",
            "-append",
            "-makevalid",
            "-skipfailures",
        ]
        
        try:
            result = subprocess.run(
                cmd_append,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds
            )
            logger.info(f"  ✅ 追加成功")
            stats['processed_files'] += 1
            
        except subprocess.TimeoutExpired:
            logger.warning(f"  ⏱️  タイムアウト（{timeout_seconds}秒）: {dgn_file.name}")
            logger.warning(f"     このファイルをスキップリストに追加することを推奨")
            stats['skipped_files'] += 1
            stats['errors'].append({
                'file': dgn_file.name,
                'error': f'Timeout ({timeout_seconds}s)'
            })
            
        except subprocess.CalledProcessError as e:
            logger.warning(f"  ⚠️ 追加失敗: {dgn_file.name}")
            error_msg = e.stderr[:300] if e.stderr else "Unknown error"
            logger.warning(f"     エラー: {error_msg}")
            stats['failed_files'] += 1
            stats['errors'].append({
                'file': dgn_file.name,
                'error': error_msg
            })
    
    # 最終結果
    stats['status'] = 'success'
    logger.info(f"\n{'='*80}")
    logger.info(f"追加処理完了: {output_gpkg.name}")
    logger.info(f"  処理成功: {stats['processed_files']}/{stats['total_files']}")
    logger.info(f"  処理失敗: {stats['failed_files']}/{stats['total_files']}")
    logger.info(f"  タイムアウト: {stats['skipped_files']}/{stats['total_files']}")
    logger.info(f"{'='*80}\n")
    
    return stats


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="既存GPKGに残りのDGNファイルを追加"
    )
    parser.add_argument(
        "suffix",
        choices=["CS", "DC", "DH", "GT", "RG", "TH", "TV"],
        help="データ種類（例: DC）"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="DGNファイルディレクトリ（デフォルト: 整備データ/Vector_<suffix>）"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="既存のGPKGファイル（デフォルト: 整備データ/merge/merge_<suffix>.gpkg）"
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("data/output/merge_vector_fixed.log"),
        help="処理済みファイルを確認するログファイル"
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        help="スキップするファイル名のリスト"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="各ファイルのタイムアウト秒数（デフォルト: 180秒）"
    )
    args = parser.parse_args()
    
    # パス設定
    suffix = args.suffix
    input_dir = args.input_dir or Path(f"整備データ/Vector_{suffix}")
    output_gpkg = args.output or Path(f"整備データ/merge/merge_{suffix}.gpkg")
    
    logger.info("=" * 80)
    logger.info("残りDGNファイルの追加処理")
    logger.info("=" * 80)
    logger.info(f"データ種類: {suffix}")
    logger.info(f"入力ディレクトリ: {input_dir}")
    logger.info(f"出力GPKG: {output_gpkg}")
    logger.info(f"タイムアウト: {args.timeout}秒")
    
    # ディレクトリ存在確認
    if not input_dir.exists():
        logger.error(f"入力ディレクトリが存在しません: {input_dir}")
        return
    
    if not output_gpkg.exists():
        logger.error(f"出力GPKGファイルが存在しません: {output_gpkg}")
        logger.error("先にmerge_vector_fixed.pyで初期作成してください")
        return
    
    # ogr2ogr取得
    ogr2ogr_path = get_ogr2ogr_path()
    
    # スキップファイルリスト作成
    skip_files = set(DEFAULT_SKIP_FILES)
    if args.skip:
        skip_files.update(args.skip)
    logger.info(f"スキップファイル: {len(skip_files)}個")
    for f in skip_files:
        logger.info(f"  - {f}")
    
    # 処理済みファイルリスト取得
    processed_files = get_processed_files_from_log(args.log_file)
    
    # 処理実行
    stats = append_remaining_files(
        input_dir,
        suffix,
        output_gpkg,
        ogr2ogr_path,
        skip_files,
        processed_files,
        args.timeout
    )
    
    # サマリー出力
    logger.info("\n" + "=" * 80)
    logger.info("処理サマリー")
    logger.info("=" * 80)
    logger.info(f"ステータス: {stats['status']}")
    logger.info(f"処理対象: {stats['total_files']}ファイル")
    logger.info(f"成功: {stats['processed_files']}ファイル")
    logger.info(f"失敗: {stats['failed_files']}ファイル")
    logger.info(f"タイムアウト: {stats['skipped_files']}ファイル")
    
    if stats.get('errors'):
        logger.info("\nエラー詳細:")
        for err in stats['errors']:
            logger.info(f"  - {err['file']}: {err['error'][:100]}")
    
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
