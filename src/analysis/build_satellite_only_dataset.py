"""Satellite Only 分析用データセットを GeoTIFF から構築する。

2023-07-07 の検証日に対し、LST と衛星指標（NDVI/NDBI/NDWI）の
観測ペアを選定し、GDAL の XYZ 出力を経由して 1 行 1 ピクセルの
分析用 CSV を作成する。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONDA_ROOT = PROJECT_ROOT / ".conda"
CONDA_PATH_PREFIX = [
    str(CONDA_ROOT),
    str(CONDA_ROOT / "Library" / "bin"),
    str(CONDA_ROOT / "Scripts"),
]
os.environ["PATH"] = os.pathsep.join([*CONDA_PATH_PREFIX, os.environ.get("PATH", "")])

import numpy as np
import pandas as pd


OUTPUT_DIR = PROJECT_ROOT / "data" / "csv" / "analysis"
LST_RESULTS_PATH = PROJECT_ROOT / "data" / "output" / "gee_calc_LST_results.csv"
INDICES_RESULTS_PATH = PROJECT_ROOT / "data" / "output" / "gee_calc_indices_results.csv"
LST_RASTER_DIR = PROJECT_ROOT / "data" / "output" / "LST" / "2023"
INDICES_RASTER_DIR = PROJECT_ROOT / "data" / "output" / "indices" / "2023"
GDALINFO_EXE = PROJECT_ROOT / ".conda" / "Library" / "bin" / "gdalinfo.exe"
GDAL_TRANSLATE_EXE = PROJECT_ROOT / ".conda" / "Library" / "bin" / "gdal_translate.exe"
GDAL_DATA_DIR = PROJECT_ROOT / ".conda" / "Library" / "share" / "gdal"
PROJ_DATA_DIR = PROJECT_ROOT / ".conda" / "Library" / "share" / "proj"

FEATURE_COLUMNS = ("NDVI", "NDBI", "NDWI")
DATA_COLUMNS = ("lon", "lat", "LST", "NDVI", "NDBI", "NDWI")


def parse_arguments() -> argparse.Namespace:
    """CLI 引数を解釈する。"""
    parser = argparse.ArgumentParser(
        description="Satellite Only 分析用のピクセル単位 CSV を構築する。"
    )
    parser.add_argument("--date", default="2023-07-07")
    parser.add_argument("--chunksize", type=int, default=200_000)
    parser.add_argument("--min-lst", type=float, default=15.0)
    parser.add_argument("--max-lst", type=float, default=65.0)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def build_gdal_env() -> dict[str, str]:
    """GDAL 実行用の環境変数を返す。"""
    env = os.environ.copy()
    env["GDAL_DATA"] = str(GDAL_DATA_DIR)
    env["PROJ_LIB"] = str(PROJ_DATA_DIR)
    return env


def run_command(command: list[str]) -> str:
    """外部コマンドを実行して標準出力を返す。"""
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=build_gdal_env(),
    )
    return result.stdout


def load_and_pair_results(target_date: str) -> pd.DataFrame:
    """LST と衛星指標の結果 CSV を日付で突き合わせる。"""
    lst_df = pd.read_csv(LST_RESULTS_PATH)
    idx_df = pd.read_csv(INDICES_RESULTS_PATH)

    lst_target = lst_df.loc[lst_df["date"] == target_date].copy()
    idx_target = idx_df.loc[idx_df["date"] == target_date].copy()

    if lst_target.empty or idx_target.empty:
        raise ValueError(f"指定日の結果が見つかりません: {target_date}")

    paired = lst_target.merge(
        idx_target,
        on=["date", "observation_datetime_utc"],
        suffixes=("_lst", "_idx"),
    )
    if paired.empty:
        raise ValueError(f"LST と indices の観測時刻が一致する行がありません: {target_date}")

    paired["pair_valid_pixel_ratio"] = (
        paired["valid_pixel_ratio_lst"] + paired["valid_pixel_ratio_idx"]
    ) / 2.0
    paired["pair_cloud_cover"] = paired["cloud_cover_lst"]

    return paired.sort_values(
        by=["pair_valid_pixel_ratio", "pair_cloud_cover"],
        ascending=[False, True],
    ).reset_index(drop=True)


def build_observation_key(observation_datetime_utc: str) -> str:
    """観測日時からファイル名キーを生成する。"""
    timestamp = pd.to_datetime(observation_datetime_utc, utc=True)
    return timestamp.strftime("%Y%m%d_%H%M%SZ")


def resolve_raster_path(directory: Path, prefix: str, observation_key: str) -> Path:
    """観測キーに対応する GeoTIFF を取得する。"""
    pattern = f"{prefix}_Landsat8_{observation_key}.tif"
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"GeoTIFF を一意に特定できません: {pattern}")
    return matches[0]


def read_gdalinfo_json(raster_path: Path) -> dict:
    """gdalinfo の JSON 出力を取得する。"""
    stdout = run_command([str(GDALINFO_EXE), "-json", str(raster_path)])
    return json.loads(stdout)


def validate_raster_pair(lst_info: dict, indices_info: dict) -> None:
    """LST と指標ラスタが同一グリッドか検証する。"""
    if lst_info["size"] != indices_info["size"]:
        raise ValueError("LST と indices のラスタサイズが一致しません。")

    if lst_info["geoTransform"] != indices_info["geoTransform"]:
        raise ValueError("LST と indices の geotransform が一致しません。")

    lst_epsg = lst_info["stac"].get("proj:epsg")
    idx_epsg = indices_info["stac"].get("proj:epsg")
    if lst_epsg != idx_epsg:
        raise ValueError("LST と indices の EPSG が一致しません。")

    band_names = [band.get("description") for band in indices_info["bands"]]
    if band_names[:3] != ["NDVI", "NDBI", "NDWI"]:
        raise ValueError(f"indices バンド名が想定と異なります: {band_names}")


def export_xyz(raster_path: Path, band_number: int, output_path: Path) -> None:
    """GeoTIFF の指定バンドを XYZ へ書き出す。"""
    if output_path.exists():
        output_path.unlink()

    run_command(
        [
            str(GDAL_TRANSLATE_EXE),
            "-b",
            str(band_number),
            "-of",
            "XYZ",
            str(raster_path),
            str(output_path),
        ]
    )


def iter_xyz_chunks(xyz_path: Path, value_name: str, chunksize: int) -> Iterator[pd.DataFrame]:
    """XYZ ファイルを分割読み込みする。"""
    return pd.read_csv(
        xyz_path,
        sep=r"\s+",
        names=["lon", "lat", value_name],
        chunksize=chunksize,
        dtype=np.float64,
    )


def update_summary(summary: dict, chunk_df: pd.DataFrame) -> None:
    """サマリー統計を更新する。"""
    summary["rows_after_quality_filter"] += int(len(chunk_df))

    for column in DATA_COLUMNS[2:]:
        series = chunk_df[column]
        summary["stats"][column]["min"] = min(summary["stats"][column]["min"], float(series.min()))
        summary["stats"][column]["max"] = max(summary["stats"][column]["max"], float(series.max()))
        summary["stats"][column]["sum"] += float(series.sum())


def finalize_summary(summary: dict) -> None:
    """サマリーの最終値を計算する。"""
    row_count = summary["rows_after_quality_filter"]
    for column in DATA_COLUMNS[2:]:
        if row_count == 0:
            summary["stats"][column]["mean"] = None
            summary["stats"][column].pop("sum", None)
            continue

        summary["stats"][column]["mean"] = summary["stats"][column]["sum"] / row_count
        summary["stats"][column].pop("sum", None)


def build_dataset(
    lst_xyz_path: Path,
    ndvi_xyz_path: Path,
    ndbi_xyz_path: Path,
    ndwi_xyz_path: Path,
    output_csv_path: Path,
    chunksize: int,
    min_lst: float,
    max_lst: float,
) -> dict:
    """XYZ 群を結合して分析用 CSV を構築する。"""
    if output_csv_path.exists():
        output_csv_path.unlink()

    summary = {
        "rows_before_quality_filter": 0,
        "rows_after_quality_filter": 0,
        "stats": {
            column: {"min": float("inf"), "max": float("-inf"), "sum": 0.0}
            for column in DATA_COLUMNS[2:]
        },
    }

    readers = (
        iter_xyz_chunks(lst_xyz_path, "LST", chunksize),
        iter_xyz_chunks(ndvi_xyz_path, "NDVI", chunksize),
        iter_xyz_chunks(ndbi_xyz_path, "NDBI", chunksize),
        iter_xyz_chunks(ndwi_xyz_path, "NDWI", chunksize),
    )

    first_chunk = True
    header_written = False
    for lst_chunk, ndvi_chunk, ndbi_chunk, ndwi_chunk in zip(*readers, strict=True):
        if first_chunk:
            if not np.allclose(lst_chunk["lon"], ndvi_chunk["lon"], equal_nan=True):
                raise ValueError("LST と NDVI の座標が一致しません。")
            if not np.allclose(lst_chunk["lat"], ndvi_chunk["lat"], equal_nan=True):
                raise ValueError("LST と NDVI の座標が一致しません。")

        merged = pd.DataFrame(
            {
                "lon": lst_chunk["lon"],
                "lat": lst_chunk["lat"],
                "LST": lst_chunk["LST"],
                "NDVI": ndvi_chunk["NDVI"],
                "NDBI": ndbi_chunk["NDBI"],
                "NDWI": ndwi_chunk["NDWI"],
            }
        )

        summary["rows_before_quality_filter"] += int(len(merged))

        valid_mask = merged[["LST", *FEATURE_COLUMNS]].notna().all(axis=1)
        valid_mask &= merged["LST"].between(min_lst, max_lst)
        valid_mask &= merged["NDVI"].between(-1.1, 1.1)
        valid_mask &= merged["NDBI"].between(-1.1, 1.1)
        valid_mask &= merged["NDWI"].between(-1.1, 1.1)

        cleaned = merged.loc[valid_mask].copy()
        if cleaned.empty:
            first_chunk = False
            continue

        cleaned.to_csv(output_csv_path, mode="a", index=False, header=not header_written)
        update_summary(summary, cleaned)
        header_written = True
        first_chunk = False

    finalize_summary(summary)
    return summary


def main() -> None:
    """処理全体を実行する。"""
    args = parse_arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    paired_results = load_and_pair_results(args.date)
    best_row = paired_results.iloc[0]
    observation_key = build_observation_key(str(best_row["observation_datetime_utc"]))

    lst_raster_path = resolve_raster_path(LST_RASTER_DIR, "LST", observation_key)
    indices_raster_path = resolve_raster_path(INDICES_RASTER_DIR, "INDICES", observation_key)

    lst_info = read_gdalinfo_json(lst_raster_path)
    indices_info = read_gdalinfo_json(indices_raster_path)
    validate_raster_pair(lst_info, indices_info)

    output_stem = f"satellite_only_20230707_{observation_key}"
    lst_xyz_path = args.output_dir / f"{output_stem}_lst.xyz"
    ndvi_xyz_path = args.output_dir / f"{output_stem}_ndvi.xyz"
    ndbi_xyz_path = args.output_dir / f"{output_stem}_ndbi.xyz"
    ndwi_xyz_path = args.output_dir / f"{output_stem}_ndwi.xyz"
    output_csv_path = args.output_dir / f"{output_stem}_dataset.csv"
    output_summary_path = args.output_dir / f"{output_stem}_summary.json"

    export_xyz(lst_raster_path, 1, lst_xyz_path)
    export_xyz(indices_raster_path, 1, ndvi_xyz_path)
    export_xyz(indices_raster_path, 2, ndbi_xyz_path)
    export_xyz(indices_raster_path, 3, ndwi_xyz_path)

    build_summary = build_dataset(
        lst_xyz_path=lst_xyz_path,
        ndvi_xyz_path=ndvi_xyz_path,
        ndbi_xyz_path=ndbi_xyz_path,
        ndwi_xyz_path=ndwi_xyz_path,
        output_csv_path=output_csv_path,
        chunksize=args.chunksize,
        min_lst=args.min_lst,
        max_lst=args.max_lst,
    )

    result_summary = {
        "date": args.date,
        "observation_datetime_utc": str(best_row["observation_datetime_utc"]),
        "observation_key": observation_key,
        "selection_reason": {
            "pair_valid_pixel_ratio": float(best_row["pair_valid_pixel_ratio"]),
            "cloud_cover": float(best_row["pair_cloud_cover"]),
            "lst_valid_pixel_ratio": float(best_row["valid_pixel_ratio_lst"]),
            "indices_valid_pixel_ratio": float(best_row["valid_pixel_ratio_idx"]),
        },
        "inputs": {
            "lst_raster": str(lst_raster_path.relative_to(PROJECT_ROOT)),
            "indices_raster": str(indices_raster_path.relative_to(PROJECT_ROOT)),
        },
        "outputs": {
            "dataset_csv": str(output_csv_path.relative_to(PROJECT_ROOT)),
            "summary_json": str(output_summary_path.relative_to(PROJECT_ROOT)),
        },
        "quality_filter": {
            "lst_range_c": [args.min_lst, args.max_lst],
            "index_range": [-1.1, 1.1],
        },
        **build_summary,
    }

    output_summary_path.write_text(
        json.dumps(result_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for tmp_path in (lst_xyz_path, ndvi_xyz_path, ndbi_xyz_path, ndwi_xyz_path):
        if tmp_path.exists():
            tmp_path.unlink()

    print(json.dumps(result_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
