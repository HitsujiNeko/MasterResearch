"""正本の標高点 CSV から BSHorizon パイプライン用の入力 CSV を生成する。

``data/output/survey_translated/merge_DH_elevation_points.csv``
（``convert_elevation_to_csv.py`` が生成する正本、ヘッダーあり）から
ヘッダー行を除いたコピーを ``data/BSHorizon/input/`` に書き出す。

``bs_horizon.py`` の ``_iter_records`` は空白/カンマ区切りの数値行のみを
想定しており、ヘッダー行があるとパースエラーになるため、この変換が必要。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.common.paths import prepare_output_path, resolve_existing_path

DEFAULT_INPUT_PATH = (
    PROJECT_ROOT / "data" / "output" / "survey_translated" / "merge_DH_elevation_points.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "BSHorizon" / "input" / "merge_DH_elevation_points.csv"
)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="正本の標高点 CSV からヘッダーなしの BSHorizon 入力 CSV を生成する。"
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="正本 CSV（ヘッダーあり）のパス",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力先 CSV（ヘッダーなし）のパス",
    )
    return parser.parse_args()


def strip_header(input_path: Path, output_path: Path) -> int:
    """入力 CSV の先頭1行（ヘッダー）を除いて出力先に書き出す。

    改行コードは変換せず、入力ファイルのものをそのまま保持する。

    Args:
        input_path: ヘッダーありの入力 CSV パス。
        output_path: ヘッダーなしの出力先 CSV パス。
    Returns:
        書き出したデータ行数（ヘッダー行を除いた件数）。
    """
    written_count = 0
    with input_path.open("r", encoding="utf-8", newline="") as src_file:
        with output_path.open("w", encoding="utf-8", newline="") as dst_file:
            for line_index, line in enumerate(src_file):
                if line_index == 0:
                    continue
                dst_file.write(line)
                written_count += 1
    return written_count


def main() -> None:
    """正本 CSV から BSHorizon 入力 CSV を生成する処理を実行する。"""
    args = parse_args()
    input_path = resolve_existing_path(args.input_path)
    output_path = prepare_output_path(args.output_path)

    written_count = strip_header(input_path, output_path)

    print("BSHorizon 入力 CSV の生成が完了しました。")
    print(f"入力: {input_path}")
    print(f"出力: {output_path}")
    print(f"出力行数: {written_count:,}")


if __name__ == "__main__":
    main()
