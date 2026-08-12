"""再設計前後で算出値が変わっていないことを確認する検証専用モジュール。

正準グリッドと旧グリッドはセルが対応しない（グリッド原点が異なり、ハノイROI・30m
では dx=29.97m / dy=23.23m ずれる）ため、再設計後の出力と旧 wide CSV をセル単位で
照合することはできない。そこで**検証専用に旧BBox原点の ``GridSpec`` を構築**し、
再設計後の算出経路を通した結果を旧 CSV と全列照合する。

照合は**新しいオーケストレーション（``PARAM_SETS`` による入力解決・io層のキャッシュ・
``compute()`` の列検証）を経由し、``GridSpec`` と解析BBoxだけを旧仕様へ差し替える**。
``compute()`` を直接呼ぶだけでは、再設計で新たに入った要素を何も検証しないためである。

実行例::

    python -m src.analysis.urban_params.verify_values --city hanoi \\
        --params build_gba road_osm --legacy-scenario limited --scales 30 90 300

.. note::

   **本モジュールは検証専用であり、旧 CSV が役目を終えた時点で削除してよい。**
   削除してよい条件は次の2つをともに満たしたときである。

   1. 再設計後の出力（``data/output/params/``）で分析を一巡し、値の妥当性が
      確認できている
   2. ``data/output/urban_params/*.csv`` を参照する分析・ドキュメントが無くなっている

   本モジュールを削除する際は、対応するテスト（``tests/.../test_verify_values.py``）
   も併せて削除する。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS

from src.common.geo_metadata import BBox

from .config import CITY_CONFIG, PARAM_SETS, PROJECT_ROOT
from .geometry import compute_polygon_coverage
from .grid import GridSpec, build_grid, grid_centers_wgs84
from .io import bbox_from_layer, get_layer_resource, layer_cache
from .run import build_param_tasks, validate_computed_columns

# 旧 wide CSV の格納ルート（プロジェクトルートからの相対パス要素）。
LEGACY_OUTPUT_PARTS = ("data", "output", "urban_params")

# 旧 run.py がシナリオごとに使っていた解析範囲レイヤ。``SCENARIO_INPUT_KEYS`` は
# 廃止済みのため、照合の前提を明示するためにここへ残す。行の絞り込みを旧実装と
# 同じマスクで行うために必要であり、再設計後の解析範囲（ROIへ一本化）とは別物である。
LEGACY_MASK_LAYER_KEYS = {"satellite_only": "roi", "limited": "roi", "full": "rg"}

# 照合対象の列（建物4種・道路）。標高は旧 CSV の生成後に算出内容が変わっており
# （``ELEV_VALID_RATIO`` が未収録）、値の同一性を問える状態にないため含めない。
COMPARED_COLUMNS = ("BUILD_COV", "BUILD_DEN", "BUILD_H_MEAN", "BUILD_H_MAX", "ROAD_DEN")

# 座標の突合に使う許容差（度）。約0.1mmに相当する。座標は行の対応づけのキーでは
# なく、**順序ずれの検知にのみ**使うため、浮動小数点の完全一致には依存させない。
COORDINATE_TOLERANCE_DEG = 1e-9

# 照合対象の列が旧 CSV に保存された精度。``params/*.py`` の ``compute()`` はいずれも
# float32 を返し、CSVには「float32として往復できる最短の10進表記」が書かれている。
LEGACY_STORAGE_DTYPE = np.float32


@dataclass(frozen=True)
class ColumnComparison:
    """1列分の照合結果。

    Attributes:
        column: 照合した列名（サフィックス無し）。
        matched: 一致した行数（NaN同士の一致を含む）。
        mismatched: 一致しなかった行数。
        max_abs_diff: 双方が有限値である行における最大絶対差。該当行が無い場合は
            ``0.0``。
        legacy_only_nan: 旧側のみ NaN だった行数。
        current_only_nan: 現行側のみ NaN だった行数。
    """

    column: str
    matched: int
    mismatched: int
    max_abs_diff: float
    legacy_only_nan: int
    current_only_nan: int

    @property
    def is_match(self) -> bool:
        """不一致が1行も無ければ ``True`` を返す。"""
        return self.mismatched == 0


def legacy_csv_path(
    scenario: str,
    city: str,
    scale: int,
    base_dir: Path | None = None,
) -> Path:
    """照合先の旧 wide CSV のパスを決める。

    Args:
        scenario: 旧シナリオ名。**ファイル名の特定にのみ使うラベル**であり、
            入力レイヤの解決には使わない（解決は ``PARAM_SETS`` が担う）。
        city: 都市ID。
        scale: coarseグリッド解像度（m）。
        base_dir: 旧 CSV の格納ルート。``None`` の場合は
            ``data/output/urban_params`` を使う。

    Returns:
        ``urban_params_{scenario}_{city}_{scale}m.csv`` の絶対パス。
    """
    root = base_dir if base_dir is not None else PROJECT_ROOT.joinpath(*LEGACY_OUTPUT_PARTS)
    return root / f"urban_params_{scenario}_{city}_{scale}m.csv"


def build_legacy_grid(
    bbox_analysis: BBox,
    analysis_crs: CRS,
    scale: int,
    fine_res_m: float,
) -> GridSpec:
    """旧仕様（解析範囲レイヤのBBoxを原点とする）のグリッドを構築する。

    再設計後の ``tables.build_aligned_grid()`` が正準グリッドのセル境界に載る
    BBoxを使うのに対し、こちらは旧実装と同じく解析範囲レイヤのBBoxをそのまま使う。
    旧 CSV と同じセル配置を再現するための、**検証専用の構築経路**である。

    Args:
        bbox_analysis: 解析範囲レイヤのBBox（解析用CRS上）。
        analysis_crs: 解析用CRS。
        scale: coarseグリッド解像度（m）。
        fine_res_m: 被覆率計算用の補助解像度（m）。

    Returns:
        旧仕様のグリッド仕様。
    """
    return build_grid(bbox_analysis, analysis_crs, float(scale), fine_res_m)


def select_analysis_rows(
    columns: dict[str, np.ndarray],
    analysis_mask: np.ndarray,
) -> dict[str, np.ndarray]:
    """``IN_ANALYSIS_AREA == 1`` のセルだけを ``ravel()`` 順で取り出す。

    旧 CSV は解析対象セルのみを ``ravel()`` 順で保存しているため、同じ順序・同じ
    絞り込みを再現する。

    Args:
        columns: 列名からcoarseグリッド配列への辞書。
        analysis_mask: 解析対象セルが ``True`` の真偽値配列（グリッドと同形状）。

    Returns:
        列名から1次元配列への辞書。
    """
    flat_mask = analysis_mask.ravel()
    return {name: values.ravel()[flat_mask] for name, values in columns.items()}


def to_storage_precision(values: np.ndarray) -> np.ndarray:
    """値を旧 CSV の保存精度（float32）へ揃える。

    旧 CSV は float32 の値を「float32 として往復できる最短の10進表記」で保存して
    いる。これを float64 として読むと、元の float32 との間に最大で float32 の
    1ULPの半分（値1.0付近で約6e-8、値680付近で約3e-5）のずれが生じる。**これは
    算出値の差ではなく表記の丸めによる差**であり、そのまま比較すると再設計が値を
    変えたのかCSVの表記精度なのかを区別できない。

    保存精度へ揃えてから比較することで表記由来のずれを取り除き、算出値そのものの
    一致をビット単位で判定できるようにする。

    Args:
        values: 揃える対象の配列。

    Returns:
        ``float32`` へ変換した配列。
    """
    return np.asarray(values, dtype=LEGACY_STORAGE_DTYPE)


def compare_values(
    legacy: np.ndarray,
    current: np.ndarray,
    rtol: float,
    atol: float,
) -> np.ndarray:
    """2つの配列を要素ごとに比較し、一致を表す真偽値配列を返す。

    **NaN 同士は一致として扱う。** ``BUILD_H_MEAN`` / ``BUILD_H_MAX`` は「セル内に
    有効高さの建物が無い」場合に NaN とする欠測規約を持ち、その規約自体が維持されて
    いることを確認する必要があるためである。

    Args:
        legacy: 旧 CSV 側の値。
        current: 再設計後の算出値。
        rtol: 相対許容差。
        atol: 絶対許容差。

    Returns:
        要素ごとの一致を表す真偽値配列。
    """
    legacy_nan = np.isnan(legacy)
    current_nan = np.isnan(current)
    both_nan = legacy_nan & current_nan
    both_finite = ~legacy_nan & ~current_nan

    close = np.zeros(legacy.shape, dtype=bool)
    close[both_finite] = np.isclose(legacy[both_finite], current[both_finite], rtol=rtol, atol=atol)
    return both_nan | close


def compare_column(
    column: str,
    legacy: np.ndarray,
    current: np.ndarray,
    rtol: float,
    atol: float,
) -> ColumnComparison:
    """1列分の照合結果を集計する。

    Args:
        column: 列名（サフィックス無し）。
        legacy: 旧 CSV 側の値。
        current: 再設計後の算出値。
        rtol: 相対許容差。
        atol: 絶対許容差。

    Returns:
        集計済みの照合結果。
    """
    matches = compare_values(legacy, current, rtol, atol)
    legacy_nan = np.isnan(legacy)
    current_nan = np.isnan(current)
    both_finite = ~legacy_nan & ~current_nan

    max_abs_diff = 0.0
    if bool(both_finite.any()):
        # 差そのものは float64 で求める（float32 のまま引くと差が丸められる）。
        difference = legacy[both_finite].astype(np.float64) - current[both_finite].astype(
            np.float64
        )
        max_abs_diff = float(np.max(np.abs(difference)))

    return ColumnComparison(
        column=column,
        matched=int(matches.sum()),
        mismatched=int((~matches).sum()),
        max_abs_diff=max_abs_diff,
        legacy_only_nan=int((legacy_nan & ~current_nan).sum()),
        current_only_nan=int((~legacy_nan & current_nan).sum()),
    )


def compare_coordinates(
    legacy_frame: pd.DataFrame,
    lon: np.ndarray,
    lat: np.ndarray,
) -> tuple[float, float]:
    """座標の最大差を返す（行の順序ずれを検知するために使う）。

    Args:
        legacy_frame: 旧 CSV のデータフレーム（``lon`` / ``lat`` を含む）。
        lon: 再設計後の経度配列（絞り込み済み・1次元）。
        lat: 再設計後の緯度配列（絞り込み済み・1次元）。

    Returns:
        (経度の最大絶対差, 緯度の最大絶対差) の組（度）。
    """
    lon_diff = float(np.max(np.abs(legacy_frame["lon"].to_numpy(dtype=np.float64) - lon)))
    lat_diff = float(np.max(np.abs(legacy_frame["lat"].to_numpy(dtype=np.float64) - lat)))
    return lon_diff, lat_diff


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI引数を解釈して返す。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。

    Returns:
        解釈済みの引数。
    """
    parser = argparse.ArgumentParser(
        description="旧 wide CSV との値照合（再設計が算出値を変えていないことの確認）"
    )
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument(
        "--params",
        nargs="+",
        required=True,
        choices=list(PARAM_SETS.keys()),
        help="照合するパラメータセット名の一覧。入力の解決は PARAM_SETS が担う。",
    )
    parser.add_argument(
        "--legacy-scenario",
        default="limited",
        choices=list(LEGACY_MASK_LAYER_KEYS.keys()),
        help="照合先の旧 CSV を特定するシナリオ名。旧実装と同じ解析範囲レイヤを"
        " 選ぶためにも使う（入力レイヤの解決には使わない）。",
    )
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[30, 90, 300],
        help="照合するcoarseグリッド解像度（m）の一覧。",
    )
    parser.add_argument(
        "--fine-res", type=float, default=10.0, help="被覆率計算用の補助解像度（m）。"
    )
    parser.add_argument(
        "--legacy-dir",
        default="",
        help="旧 CSV の格納ルート。既定は data/output/urban_params。",
    )
    parser.add_argument(
        "--rtol", type=float, default=0.0, help="照合の相対許容差（既定は完全一致）。"
    )
    parser.add_argument(
        "--atol", type=float, default=0.0, help="照合の絶対許容差（既定は完全一致）。"
    )

    args = parser.parse_args(argv)
    if any(scale <= 0 for scale in args.scales):
        parser.error("--scales には正の整数のみ指定してください。")
    args.scales = list(dict.fromkeys(args.scales))
    args.params = list(dict.fromkeys(args.params))
    return args


def verify_scale(
    scale: int,
    args: argparse.Namespace,
    tasks: list,
    mask_resource: object,
    bbox_analysis: BBox,
    analysis_crs: CRS,
    legacy_dir: Path | None,
) -> list[ColumnComparison]:
    """1スケール分の照合を行い、列ごとの結果を返す。

    Args:
        scale: coarseグリッド解像度（m）。
        args: CLI引数。
        tasks: 算出タスクの一覧（``run.build_param_tasks()`` の戻り値）。
        mask_resource: 旧実装と同じ解析範囲レイヤ。
        bbox_analysis: 解析範囲レイヤのBBox（旧仕様のグリッド原点になる）。
        analysis_crs: 解析用CRS。
        legacy_dir: 旧 CSV の格納ルート。

    Returns:
        列ごとの照合結果。

    Raises:
        FileNotFoundError: 旧 CSV が存在しない場合。
        ValueError: 行数が一致しない場合、座標が許容差を超えてずれている場合、
            または照合対象の列が旧 CSV に無い場合。
    """
    csv_path = legacy_csv_path(args.legacy_scenario, args.city, scale, legacy_dir)
    if not csv_path.exists():
        raise FileNotFoundError(f"旧 wide CSV が見つかりません: {csv_path}")

    grid_spec = build_legacy_grid(bbox_analysis, analysis_crs, scale, args.fine_res)
    print(f"[scale={scale}m] 旧仕様の coarse shape: {grid_spec.coarse_shape}", flush=True)

    computed: dict[str, np.ndarray] = {}
    for task in tasks:
        task_columns = task.compute(bbox_analysis, grid_spec)
        validate_computed_columns(task, task_columns)
        computed.update(task_columns)

    # 旧 run.py と同じマスクを再計算し、ravel() 順で絞る。
    analysis_mask = compute_polygon_coverage(mask_resource, bbox_analysis, grid_spec) > 0
    selected = select_analysis_rows(computed, analysis_mask)
    lon, lat = grid_centers_wgs84(grid_spec)
    selected_lon = lon.ravel()[analysis_mask.ravel()]
    selected_lat = lat.ravel()[analysis_mask.ravel()]

    target_columns = [name for name in COMPARED_COLUMNS if name in selected]
    legacy_columns = {name: f"{name}_{scale}" for name in target_columns}
    legacy_frame = pd.read_csv(csv_path, usecols=["lon", "lat", *legacy_columns.values()])

    if len(legacy_frame) != len(selected_lon):
        raise ValueError(
            f"行数が一致しません（旧 {len(legacy_frame):,} 行 / 現行 {len(selected_lon):,} 行）。"
            " 解析範囲レイヤ・補助解像度が旧実行時と同じか確認してください。"
        )
    print(f"[scale={scale}m] 行数: {len(legacy_frame):,} 行（一致）", flush=True)

    lon_diff, lat_diff = compare_coordinates(legacy_frame, selected_lon, selected_lat)
    if lon_diff > COORDINATE_TOLERANCE_DEG or lat_diff > COORDINATE_TOLERANCE_DEG:
        raise ValueError(
            f"座標が一致しません（最大差 lon={lon_diff:.3e} / lat={lat_diff:.3e} 度）。"
            " 行の順序が旧 CSV と食い違っている可能性があります。"
        )
    print(f"[scale={scale}m] 座標の最大差: lon={lon_diff:.3e} / lat={lat_diff:.3e} 度", flush=True)

    comparisons: list[ColumnComparison] = []
    for name in target_columns:
        comparison = compare_column(
            name,
            to_storage_precision(legacy_frame[legacy_columns[name]].to_numpy()),
            to_storage_precision(selected[name]),
            args.rtol,
            args.atol,
        )
        comparisons.append(comparison)
        status = "一致" if comparison.is_match else "不一致あり"
        print(
            f"  {name}: {status} / 一致 {comparison.matched:,} 件"
            f" / 不一致 {comparison.mismatched:,} 件"
            f" / 最大絶対差 {comparison.max_abs_diff:.6g}",
            flush=True,
        )
        if not comparison.is_match:
            print(
                f"    旧のみNaN {comparison.legacy_only_nan:,} 件"
                f" / 現行のみNaN {comparison.current_only_nan:,} 件",
                flush=True,
            )
    return comparisons


def main(argv: list[str] | None = None) -> None:
    """旧 wide CSV との値照合を実行する。

    不一致があった場合は終了コード1で終了する。検証ツールとして、成功と失敗を
    終了コードでも区別できるようにするためである。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。
    """
    args = parse_arguments(argv)
    city_cfg = CITY_CONFIG[args.city]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))

    mask_layer_key = LEGACY_MASK_LAYER_KEYS[args.legacy_scenario]
    mask_resource = get_layer_resource(city_cfg, mask_layer_key, analysis_crs)
    bbox_analysis = bbox_from_layer(mask_resource, analysis_crs)
    legacy_dir = (PROJECT_ROOT / args.legacy_dir) if args.legacy_dir else None

    print("都市:", args.city)
    print("旧シナリオ（照合先の特定用）:", args.legacy_scenario)
    print("旧実装の解析範囲レイヤ:", mask_layer_key, "->", mask_resource.path.name)
    print("旧BBox（グリッド原点）:", bbox_analysis)
    print("照合するパラメータセット:", ", ".join(args.params))

    tasks = build_param_tasks(args.params, city_cfg, analysis_crs)

    failures: list[tuple[int, ColumnComparison]] = []
    with layer_cache():
        for scale in args.scales:
            comparisons = verify_scale(
                scale=scale,
                args=args,
                tasks=tasks,
                mask_resource=mask_resource,
                bbox_analysis=bbox_analysis,
                analysis_crs=analysis_crs,
                legacy_dir=legacy_dir,
            )
            failures.extend(
                (scale, comparison) for comparison in comparisons if not comparison.is_match
            )

    if failures:
        print("\n不一致のある列:", flush=True)
        for scale, comparison in failures:
            print(
                f"  [{scale}m] {comparison.column}: {comparison.mismatched:,} 件",
                flush=True,
            )
        sys.exit(1)

    print("\nすべての列が一致しました。", flush=True)


if __name__ == "__main__":
    main()
