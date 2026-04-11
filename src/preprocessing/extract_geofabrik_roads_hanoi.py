"""
Geofabrik Vietnam extract から Hanoi ROI の道路ラインを抽出する。

本スクリプトは Geofabrik の `.osm.pbf` を QGIS 同梱の `ogr2ogr` で読み込み、
`lines` レイヤのうち `highway` 属性を持つ道路ラインだけを抽出する。
抽出結果は Hanoi ROI でクリップし、GeoPackage とサマリー JSON に保存する。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PBF = PROJECT_ROOT / "data" / "GISData" / "geofabrik" / "vietnam-260408.osm.pbf"
DEFAULT_ROI_PATH = PROJECT_ROOT / "data" / "GISData" / "ROI" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_osm_roads.gpkg"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "hanoi_osm_roads_summary.json"
DEFAULT_LAYER_NAME = "roads"
REQUEST_TIMEOUT_SECONDS = 3600
OGR2OGR_CANDIDATES = (
    Path(r"C:\Program Files\QGIS 3.40.11\bin\ogr2ogr.exe"),
    Path(r"C:\OSGeo4W\bin\ogr2ogr.exe"),
    Path(r"C:\OSGeo4W64\bin\ogr2ogr.exe"),
)
OGRINFO_CANDIDATES = (
    Path(r"C:\Program Files\QGIS 3.40.11\bin\ogrinfo.exe"),
    Path(r"C:\OSGeo4W\bin\ogrinfo.exe"),
    Path(r"C:\OSGeo4W64\bin\ogrinfo.exe"),
)
GDAL_DATA_CANDIDATES = (
    Path(r"C:\Program Files\QGIS 3.40.11\apps\gdal\share\gdal"),
    Path(r"C:\OSGeo4W\share\gdal"),
    Path(r"C:\OSGeo4W64\share\gdal"),
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="Geofabrik Vietnam extract から Hanoi ROI の道路ラインを抽出する。"
    )
    parser.add_argument(
        "--input-pbf",
        type=Path,
        default=DEFAULT_INPUT_PBF,
        help="入力 OSM PBF パス。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力 GeoPackage パス。",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="出力サマリー JSON パス。",
    )
    parser.add_argument(
        "--layer-name",
        default=DEFAULT_LAYER_NAME,
        help="GeoPackage に保存するレイヤ名。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def ensure_input_files(input_pbf: Path, roi_path: Path) -> None:
    """入力ファイルの存在を検証する。"""
    if not input_pbf.exists():
        raise FileNotFoundError(f"入力 OSM PBF が見つかりません: {input_pbf}")
    if not roi_path.exists():
        raise FileNotFoundError(f"ROI ファイルが見つかりません: {roi_path}")


def find_existing_path(candidates: tuple[Path, ...], label: str) -> Path:
    """候補の中から存在する実行ファイルまたはディレクトリを返す。"""
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{label} が見つかりませんでした。候補: {candidates}")


def build_gdal_environment(gdal_data_path: Path) -> dict[str, str]:
    """OSM ドライバが動く GDAL 環境変数を構築する。"""
    environment = dict(**subprocess.os.environ)
    environment["GDAL_DATA"] = str(gdal_data_path)
    return environment


def remove_existing_output(output_path: Path, overwrite: bool) -> None:
    """既存出力の扱いを制御する。"""
    if not output_path.exists():
        return
    if not overwrite:
        raise FileExistsError(
            f"出力ファイルは既に存在します: {output_path}。上書きする場合は --overwrite を指定してください。"
        )
    output_path.unlink()


def build_extract_command(
    ogr2ogr_path: Path,
    input_pbf: Path,
    roi_path: Path,
    output_path: Path,
    layer_name: str,
) -> list[str]:
    """道路抽出用の ogr2ogr コマンドを構築する。"""
    return [
        str(ogr2ogr_path),
        "-progress",
        "-skipfailures",
        "-f",
        "GPKG",
        str(output_path),
        str(input_pbf),
        "lines",
        "-where",
        "highway IS NOT NULL",
        "-select",
        "osm_id,name,highway,z_order,other_tags",
        "-clipsrc",
        str(roi_path),
        "-nlt",
        "MULTILINESTRING",
        "-nln",
        layer_name,
        "-lco",
        "SPATIAL_INDEX=YES",
        "-makevalid",
    ]


def run_extract_command(command: list[str], environment: dict[str, str]) -> None:
    """道路抽出コマンドを実行する。"""
    logger.info("道路抽出を開始します。")
    subprocess.run(
        command,
        check=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
        env=environment,
    )


def extract_feature_count(ogrinfo_path: Path, output_path: Path, layer_name: str, environment: dict[str, str]) -> int:
    """出力 GeoPackage の件数を取得する。"""
    command = [str(ogrinfo_path), "-so", "-al", str(output_path), layer_name]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
        env=environment,
    )
    for line in result.stdout.splitlines():
        if "Feature Count:" not in line:
            continue
        return int(line.split(":")[-1].strip())
    raise ValueError(f"Feature Count を取得できませんでした: {output_path}")


def build_summary(
    input_pbf: Path,
    roi_path: Path,
    output_path: Path,
    summary_path: Path,
    layer_name: str,
    feature_count: int,
) -> dict[str, Any]:
    """出力サマリーを組み立てる。"""
    file_size_mb = round(output_path.stat().st_size / (1024 * 1024), 2)
    return {
        "input_pbf": str(input_pbf.relative_to(PROJECT_ROOT)),
        "roi_path": str(roi_path.relative_to(PROJECT_ROOT)),
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "summary_path": str(summary_path.relative_to(PROJECT_ROOT)),
        "layer_name": layer_name,
        "feature_count": feature_count,
        "file_size_mb": file_size_mb,
    }


def save_summary(summary: dict[str, Any], summary_path: Path) -> None:
    """サマリー JSON を保存する。"""
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run(
    input_pbf: Path,
    roi_path: Path,
    output_path: Path,
    summary_path: Path,
    layer_name: str,
    overwrite: bool,
) -> None:
    """道路抽出処理を実行する。"""
    ensure_input_files(input_pbf, roi_path)
    ogr2ogr_path = find_existing_path(OGR2OGR_CANDIDATES, "ogr2ogr")
    ogrinfo_path = find_existing_path(OGRINFO_CANDIDATES, "ogrinfo")
    gdal_data_path = find_existing_path(GDAL_DATA_CANDIDATES, "GDAL_DATA")
    environment = build_gdal_environment(gdal_data_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    remove_existing_output(output_path, overwrite)

    command = build_extract_command(
        ogr2ogr_path=ogr2ogr_path,
        input_pbf=input_pbf,
        roi_path=roi_path,
        output_path=output_path,
        layer_name=layer_name,
    )
    run_extract_command(command, environment)
    feature_count = extract_feature_count(ogrinfo_path, output_path, layer_name, environment)
    summary = build_summary(
        input_pbf=input_pbf,
        roi_path=roi_path,
        output_path=output_path,
        summary_path=summary_path,
        layer_name=layer_name,
        feature_count=feature_count,
    )
    save_summary(summary, summary_path)

    logger.info("抽出が完了しました。")
    logger.info("Feature Count: %s", feature_count)
    logger.info("GeoPackage: %s", output_path)
    logger.info("Summary JSON: %s", summary_path)


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    run(
        input_pbf=args.input_pbf,
        roi_path=args.roi_path,
        output_path=args.output_path,
        summary_path=args.summary_path,
        layer_name=args.layer_name,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
