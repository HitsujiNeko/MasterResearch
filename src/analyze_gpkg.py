"""
地理空間データ（gpkg形式）の属性情報を解析し、ベトナム語から日本語へ翻訳するスクリプト

- 属性名・属性値を抽出し、内容を解析
- ベトナム語→日本語翻訳（API利用 or CSVエクスポート方式に対応）
- 結果をCSVとして出力（元名・元値・訳名・訳値の4列）

コーディング規約: .github/prompts/CodingRule.md 準拠
"""

import argparse
from pathlib import Path
import pandas as pd
import geopandas as gpd
import requests  # オンライン翻訳API利用時に有効化
import fiona


# ====== 設定ここから ======
# 入力ファイルが含まれるディレクトリ（gpkg）
INPUT_FILE_DIR = Path("整備データ/merge")  # 必要に応じてファイル名を変更
# オンライン翻訳APIを利用する場合はTrue
USE_API = False
# 出力先ディレクトリ
OUTPUT_CSV_DIR = Path("data/csv/analysis")
OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV_PATH = OUTPUT_CSV_DIR / "merge_CS_translated.csv"
OUTPUT_GPKG_DIR = Path("data/output")
OUTPUT_GPKG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_GPKG_PATH = OUTPUT_GPKG_DIR / "merge_CS_translated.gpkg"
# ====== 設定ここまで ======


def extract_attributes(gpkg_path: Path) -> pd.DataFrame:
    """
    GeoPackageファイルから全属性名・属性値を抽出する関数

    Args:
        gpkg_path (Path): 入力gpkgファイルのパス
    Returns:
        pd.DataFrame: 属性名・属性値のペア一覧
    """
    try:
        # GeoPackage内の全レイヤーを取得
        layers = fiona.listlayers(str(gpkg_path))
        records = []
        for layer in layers:
            try:
                gdf = gpd.read_file(gpkg_path, layer=layer)
            except Exception as e:
                print(f"レイヤー '{layer}' の読み込みに失敗しました: {e}")
                continue
            for col in gdf.columns:
                if col == gdf.geometry.name:
                    continue
                # 属性値をstr型に変換し、unhashableな型も文字列化
                try:
                    values = gdf[col].dropna().unique()
                except Exception:
                    values = gdf[col].dropna().apply(lambda x: str(x)).unique()
                for val in values:
                    try:
                        sval = str(val)
                    except Exception:
                        sval = repr(val)
                    records.append({
                        'original_field': col,
                        'original_value': sval
                    })
        if records:
            df = pd.DataFrame(records)
            # drop_duplicatesでunhashableを回避
            df['original_value'] = df['original_value'].astype(str)
            df = df.drop_duplicates()
        else:
            df = pd.DataFrame(columns=['original_field', 'original_value'])
        return df
    except Exception as e:
        print(f"属性抽出時にエラーが発生しました: {e}")
        return pd.DataFrame(columns=['original_field', 'original_value'])


def translate_text(text: str, src: str = 'vi', dest: str = 'ja') -> str:
    """
    テキストをベトナム語から日本語に翻訳する関数（ダミー実装）
    ※実運用時はGoogle Translate API等に置き換え

    Args:
        text (str): 翻訳対象テキスト
        src (str): 入力言語コード
        dest (str): 出力言語コード
    Returns:
        str: 日本語訳
    """
    # ここにAPI呼び出し等を実装
    return f"{text}_ja"  # ダミー: 実際はAPI等で翻訳


def translate_attributes(df: pd.DataFrame, use_api: bool = False) -> pd.DataFrame:
    """
    属性名・属性値を日本語に翻訳する関数

    Args:
        df (pd.DataFrame): 元の属性名・値のDataFrame
        use_api (bool): オンライン翻訳APIを使う場合True
    Returns:
        pd.DataFrame: 翻訳後の属性名・値を含むDataFrame
    """
    if 'original_field' not in df.columns:
        df['original_field'] = ''
    if 'original_value' not in df.columns:
        df['original_value'] = ''
    if use_api:
        df['translated_field'] = df['original_field'].apply(lambda x: translate_text(x))
        df['translated_value'] = df['original_value'].apply(lambda x: translate_text(str(x)))
    else:
        df['translated_field'] = ''
        df['translated_value'] = ''
    return df


def main():
    """
    定数で入力・出力パスやAPI利用有無を指定し、属性情報の抽出・翻訳・出力を行うメイン関数
    """

    # merge_*.gpkgファイルをすべて処理
    try:
        gpkg_files = sorted(INPUT_FILE_DIR.glob("merge_*.gpkg"))
        if not gpkg_files:
            print(f"{INPUT_FILE_DIR} に対象gpkgファイルがありません")
            return
        for gpkg_path in gpkg_files:
            # ファイル名からベース名を取得
            base_name = gpkg_path.stem  # 例: merge_CS
            # 属性情報抽出
            df = extract_attributes(gpkg_path)
            if df.empty:
                print(f"{gpkg_path} の属性情報が抽出できませんでした。スキップします。")
                continue
            # 翻訳（API利用 or 空欄）
            df = translate_attributes(df, use_api=USE_API)
            # 必要なカラムが揃っているかチェック
            required_cols = ['original_field', 'original_value', 'translated_field', 'translated_value']
            for col in required_cols:
                if col not in df.columns:
                    df[col] = ''
            output_csv_path = OUTPUT_CSV_DIR / f"{base_name}_translated.csv"
            try:
                df[required_cols].to_csv(output_csv_path, index=False)
                print(f"出力完了: {output_csv_path}")
            except Exception as e:
                print(f"CSV出力時にエラーが発生しました: {e}")
                print(f"DataFrame columns: {df.columns.tolist()}")
            # 必要に応じて、翻訳後の属性情報を新しいgpkgファイルとして保存する処理を追加可能
            # 例: gdf.to_file(OUTPUT_GPKG_DIR / f"{base_name}_translated.gpkg", driver="GPKG")
    except Exception as e:
        print(f"全体処理中にエラーが発生しました: {e}")


if __name__ == "__main__":
    main()
