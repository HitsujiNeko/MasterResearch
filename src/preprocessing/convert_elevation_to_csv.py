"""DH の標高点 GeoPackage を CSV に変換する。

``merge_DH.gpkg`` の ``elements`` レイヤから ``Point`` 地物のみを抽出し、
``Text`` 属性を標高値として数値化したうえで、DEM 補間に使いやすい
CSV を出力する。

出力列:
    - ``id``: 0 から始まる連番
    - ``x``: 元データ座標の X 座標
    - ``y``: 元データ座標の Y 座標
    - ``elevation``: ``Text`` 属性から取得した標高値

座標系:
    - 出力 CSV の ``x,y`` は ``EPSG:5897`` のまま保持する。
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONDA_ROOT = PROJECT_ROOT / ".conda"
DEFAULT_INPUT_PATH = PROJECT_ROOT / "整備データ" / "merge" / "merge_DH.gpkg"
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "csv" / "analysis" / "merge_DH_elevation_points.csv"
)


def configure_gdal_environment() -> None:
    """ローカル Conda 環境がある場合に GDAL 関連の環境変数を設定する。"""
    gdal_data_path = CONDA_ROOT / "Library" / "share" / "gdal"
    proj_data_path = CONDA_ROOT / "Library" / "share" / "proj"

    if "GDAL_DATA" not in os.environ and gdal_data_path.exists():
        os.environ["GDAL_DATA"] = str(gdal_data_path)

    if "PROJ_LIB" not in os.environ and proj_data_path.exists():
        os.environ["PROJ_LIB"] = str(proj_data_path)


configure_gdal_environment()

import fiona


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="merge_DH.gpkg の標高点を CSV に変換する。"
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="入力 GeoPackage のパス",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力 CSV のパス",
    )
    parser.add_argument(
        "--layer",
        default="elements",
        help="GeoPackage から読み込むレイヤ名",
    )
    return parser.parse_args()


def parse_elevation(text_value: object) -> float:
    """Text 属性を標高値の float に変換する。"""
    if text_value is None:
        raise ValueError("Text 属性がありません。")

    normalized = str(text_value).strip().replace(",", ".")
    if not normalized:
        raise ValueError("Text 属性が空です。")

    return float(normalized)


def validate_input_path(input_path: Path) -> Path:
    """入力 GeoPackage の存在を確認し、絶対パスを返す。"""
    resolved = input_path if input_path.is_absolute() else (PROJECT_ROOT / input_path)
    resolved = resolved.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"入力 GeoPackage が見つかりません: {resolved}")
    return resolved


def validate_output_path(output_path: Path) -> Path:
    """出力先ディレクトリを作成し、絶対パスを返す。"""
    resolved = output_path if output_path.is_absolute() else (PROJECT_ROOT / output_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved.resolve()


def convert_points_to_csv(
    input_path: Path,
    output_path: Path,
    layer_name: str,
) -> dict[str, int]:
    """GeoPackage から標高点を抽出して CSV に書き出す。"""
    written_count = 0
    skipped_non_point = 0
    skipped_invalid_text = 0

    with fiona.open(input_path, layer=layer_name) as src:
        with output_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["id", "x", "y", "elevation"])

            for feature in src:
                geometry = feature.get("geometry")
                if geometry is None or geometry.get("type") != "Point":
                    skipped_non_point += 1
                    continue

                try:
                    elevation = parse_elevation(feature["properties"].get("Text"))
                except ValueError:
                    skipped_invalid_text += 1
                    continue

                x_coord, y_coord = geometry["coordinates"]
                writer.writerow([written_count, x_coord, y_coord, elevation])
                written_count += 1

    return {
        "written_count": written_count,
        "skipped_non_point": skipped_non_point,
        "skipped_invalid_text": skipped_invalid_text,
    }


def main() -> None:
    """GeoPackage から CSV への変換処理を実行する。"""
    args = parse_args()
    input_path = validate_input_path(args.input_path)
    output_path = validate_output_path(args.output_path)

    stats = convert_points_to_csv(
        input_path=input_path,
        output_path=output_path,
        layer_name=args.layer,
    )

    print("標高点 CSV の変換が完了しました。")
    print(f"入力: {input_path}")
    print(f"出力: {output_path}")
    print("座標系: EPSG:5897")
    print(f"出力行数: {stats['written_count']:,}")
    print(f"非 Point 地物のスキップ数: {stats['skipped_non_point']:,}")
    print(f"Text 不正値のスキップ数: {stats['skipped_invalid_text']:,}")


if __name__ == "__main__":
    main()
