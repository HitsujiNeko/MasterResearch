"""都市構造パラメータ算出のオーケストレーションモジュール。

パラメータセット単位でパラメータを算出し、正準グリッドの ``cell_id`` をキーとする
属性テーブル（GeoPackage）へ出力する。1つのパラメータの追加・変更が、そのパラメータ
の再計算だけで済むようにするための構成である。

実行例::

    # パラメータセット単位（複数スケールでも入力レイヤの読み込みは1回）
    python -m src.analysis.urban_params --city hanoi \\
        --params build_gba road_osm --scales 30 90 300

    # 衛星指標（観測ファイル単位）
    python -m src.analysis.urban_params --city hanoi \\
        --satellite-file data/satellite/indices/2023/INDICES_Landsat8_20230707_032329Z.tif \\
        --scales 30 90 300

シナリオ（satellite_only / limited / full）は算出側では扱わない。「どのテーブルを
結合するか」の選択へ還元したため、結合側（``build_dataset.py``）が持つ。
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS

from src.common.geo_metadata import BBox

from .canonical_grid import (
    SNAP_UNIT_M,
    CanonicalGridSpec,
    build_canonical_grid,
    is_supported_resolution,
    resolve_output_path,
)
from .config import (
    ANALYSIS_EXTENT_LAYER_KEY,
    CITY_CONFIG,
    PARAM_SETS,
    PROJECT_ROOT,
    SATELLITE_TABLE_PREFIX,
    ParamSet,
    grid_layer_name,
    resolve_table_path,
)
from .grid import GridSpec
from .io import (
    LayerResource,
    RasterResource,
    bbox_from_layer,
    find_satellite_rasters,
    get_layer_resource,
    get_optional_raster_resource,
    layer_cache,
)
from .params import buildings, elevation, mask, raster, roads
from .tables import (
    aligned_bbox,
    build_aligned_grid,
    build_param_table,
    read_grid_cell_ids,
    require_grid_layers,
    write_attribute_table,
)

# ``ParamSet.module_name`` から実体への対応。config.py が直接モジュールを保持すると
# params/* -> io -> config の循環importになるため、解決はここで行う。
PARAM_MODULES = {
    "buildings": buildings,
    "roads": roads,
    "elevation": elevation,
    "mask": mask,
}

# 衛星指標ファイル名から観測日時を取り出すパターン。
SATELLITE_FILENAME_PATTERN = re.compile(
    r"^INDICES_[^_]+_(?P<date>\d{8})_(?P<time>\d{6})Z\.tiff?$", re.IGNORECASE
)


@dataclass(frozen=True)
class ParamTask:
    """1テーブル分の算出タスク。

    ``params/*.py`` の ``compute()`` はモジュールごとにシグネチャが異なる
    （衛星指標は ``bbox_analysis`` を取らずラスタ辞書を受け取る）。呼び出し側で
    分岐を持たずに済むよう、ここで ``(bbox, grid_spec) -> 列辞書`` の形へ揃える。

    Attributes:
        table_name: 出力するテーブル名（ファイル名・レイヤ名の双方に使う）。
        compute: 解析BBoxとグリッド仕様から列辞書を返す関数。
        expected_columns: 期待する出力列。実際の戻り値と突き合わせて検証する。
    """

    table_name: str
    compute: Callable[[BBox, GridSpec], dict[str, np.ndarray]]
    expected_columns: tuple[str, ...]


def satellite_table_name(satellite_path: Path) -> str:
    """衛星指標ファイル名から観測日時つきのテーブル名を導く。

    ファイル名から観測を特定できないまま出力すると、どの観測のテーブルか後から
    判別できなくなる。そのため合致しないファイル名は**推測せずに停止する**。

    Args:
        satellite_path: 衛星指標ラスタのパス。

    Returns:
        ``idx_{YYYYMMDD}_{HHMMSS}`` 形式のテーブル名。

    Raises:
        ValueError: ファイル名が想定の形式に合致しない場合。
    """
    matched = SATELLITE_FILENAME_PATTERN.match(satellite_path.name)
    if matched is None:
        raise ValueError(
            f"衛星指標ファイル名から観測日時を特定できません: {satellite_path.name}。"
            " INDICES_{センサ}_{YYYYMMDD}_{HHMMSS}Z.tif の形式のファイルを指定してください。"
        )
    return f"{SATELLITE_TABLE_PREFIX}{matched.group('date')}_{matched.group('time')}"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI引数を解釈して返す。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。

    Returns:
        解釈済みの引数。``--scales`` と ``--params`` は重複を除いた一覧に正規化する。
    """
    parser = argparse.ArgumentParser(
        description="都市構造パラメータ算出（パラメータセット単位のテーブル出力）"
    )
    parser.add_argument("--city", default="hanoi", choices=list(CITY_CONFIG.keys()))
    parser.add_argument(
        "--params",
        nargs="+",
        default=[],
        choices=list(PARAM_SETS.keys()),
        help="算出するパラメータセット名の一覧。テーブル名としてそのまま使う。",
    )
    parser.add_argument(
        "--satellite-file",
        default="",
        help="衛星指標ラスタのファイルパス（任意）。相対パスはプロジェクトルート基準。"
        " テーブル名はファイル名の観測日時から導く。",
    )
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[30, 90, 300],
        help="出力するcoarseグリッド解像度（m）の一覧。",
    )
    parser.add_argument(
        "--fine-res", type=float, default=10.0, help="被覆率計算用の補助解像度（m）。"
    )
    parser.add_argument(
        "--grid",
        default="",
        help="正準グリッドGeoPackageのパス。相対パスはプロジェクトルート基準。"
        " 既定は data/output/grid/grid_{city}.gpkg。",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="出力ルート。相対パスはプロジェクトルート基準。既定は data/output/params。",
    )

    args = parser.parse_args(argv)
    if any(scale <= 0 for scale in args.scales):
        parser.error("--scales には正の整数のみ指定してください。")

    # 正準グリッドが扱えない解像度は、入力の解決や算出へ進む前にここで弾く。
    # 判定は is_supported_resolution() に委ね、約数の規則を二重に持たない。
    # 検出しないまま進むと build_canonical_grid() のトレースバックになり、
    # 原因が「解像度の指定」にあることを読み取りにくい。
    unsupported = [scale for scale in args.scales if not is_supported_resolution(float(scale))]
    if unsupported:
        parser.error(
            f"--scales には {SNAP_UNIT_M:.0f}m の約数のみ指定してください"
            f"（指定値: {', '.join(str(scale) for scale in unsupported)}）。"
        )

    if not args.params and not args.satellite_file:
        parser.error("--params と --satellite-file の少なくとも一方を指定してください。")

    args.scales = list(dict.fromkeys(args.scales))
    args.params = list(dict.fromkeys(args.params))
    return args


def resolve_param_resource(
    city_cfg: dict[str, object],
    param_set: ParamSet,
    analysis_crs: CRS,
) -> LayerResource | RasterResource:
    """パラメータセットの入力を解決する。

    Args:
        city_cfg: ``CITY_CONFIG`` の対象都市エントリ。
        param_set: 解決するパラメータセットの定義。
        analysis_crs: 解析用CRS。

    Returns:
        解決済みの入力（ベクタレイヤまたはラスタ）。

    Raises:
        ValueError: ``input_kind`` が未知の場合、または設定にキーが無い場合。
        FileNotFoundError: 入力ファイルが存在しない場合。
    """
    if param_set.input_kind == "layer":
        return get_layer_resource(city_cfg, param_set.input_key, analysis_crs)
    if param_set.input_kind == "raster":
        resource = get_optional_raster_resource(city_cfg, param_set.input_key)
        if resource is None:  # pragma: no cover - input_key が None の場合のみ
            raise ValueError(f"ラスタ入力を解決できません: {param_set.input_key}")
        return resource
    raise ValueError(f"未知の入力種別です: {param_set.input_kind}")


def build_param_tasks(
    param_names: list[str],
    city_cfg: dict[str, object],
    analysis_crs: CRS,
) -> list[ParamTask]:
    """パラメータセット名の一覧から算出タスクを組み立てる。

    **入力の解決はすべてのタスク分をまとめて先に行う。** 1つ目の出力を書き終えてから
    2つ目の入力が見つからずに失敗すると、中途半端な出力が残るためである。

    Args:
        param_names: 算出するパラメータセット名の一覧。
        city_cfg: ``CITY_CONFIG`` の対象都市エントリ。
        analysis_crs: 解析用CRS。

    Returns:
        算出タスクの一覧（``param_names`` と同じ順序）。
    """
    tasks: list[ParamTask] = []
    for table_name in param_names:
        param_set = PARAM_SETS[table_name]
        module = PARAM_MODULES[param_set.module_name]
        resource = resolve_param_resource(city_cfg, param_set, analysis_crs)

        def compute(
            bbox_analysis: BBox,
            grid_spec: GridSpec,
            _module: object = module,
            _resource: object = resource,
        ) -> dict[str, np.ndarray]:
            """標準シグネチャの ``compute()`` を呼ぶ。"""
            return _module.compute(_resource, bbox_analysis, grid_spec)

        tasks.append(ParamTask(table_name, compute, param_set.columns))
    return tasks


def build_satellite_task(satellite_path: Path) -> ParamTask:
    """衛星指標ラスタから算出タスクを組み立てる。

    Args:
        satellite_path: 衛星指標ラスタのパス。

    Returns:
        観測日時つきのテーブル名を持つ算出タスク。

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
        ValueError: ファイル名から観測日時を特定できない場合、または指標を
            1つも検出できない場合。
    """
    if not satellite_path.is_file():
        raise FileNotFoundError(f"衛星指標ファイルが見つかりません: {satellite_path}")

    table_name = satellite_table_name(satellite_path)
    raster_resources = find_satellite_rasters(satellite_path)
    if not raster_resources:
        raise ValueError(
            f"衛星指標を検出できませんでした: {satellite_path}。"
            " バンド説明またはファイル名に NDVI / NDBI / NDWI が含まれる必要があります。"
        )

    def compute(
        bbox_analysis: BBox,
        grid_spec: GridSpec,
    ) -> dict[str, np.ndarray]:
        """衛星指標は ``bbox_analysis`` を取らない別シグネチャのため個別に扱う。"""
        return raster.compute(raster_resources, grid_spec)

    return ParamTask(table_name, compute, tuple(sorted(raster_resources)))


def validate_computed_columns(task: ParamTask, columns: dict[str, np.ndarray]) -> None:
    """``compute()`` の戻り値が期待した列と一致するかを検証する。

    同じ列名を持つべき別ソース版（``build_gba`` と ``build_dc`` など）が食い違うと、
    感度分析で結合先を差し替えたときに列が揃わない。算出モジュール側の列名変更を
    出力前に検知するための確認である。

    Args:
        task: 検証対象のタスク。
        columns: ``compute()`` が返した列辞書。

    Raises:
        ValueError: 列の集合が期待と一致しない場合。
    """
    actual = set(columns)
    expected = set(task.expected_columns)
    if actual != expected:
        raise ValueError(
            f"{task.table_name} の出力列が期待と一致しません"
            f"（不足: {sorted(expected - actual)} / 余分: {sorted(actual - expected)}）。"
            " 算出モジュールの列名と config.py の PARAM_SETS を確認してください。"
        )


def summarize_table(table_name: str, table: pd.DataFrame) -> None:
    """出力したテーブルの行数と主要統計を標準出力する。

    Args:
        table_name: テーブル名。
        table: 出力したテーブル（``cell_id`` 列を含む）。
    """
    value_columns = [name for name in table.columns if name != "cell_id"]
    print(f"[{table_name}] {len(table):,} 行 / 列: {', '.join(value_columns)}", flush=True)
    if value_columns:
        statistics = table[value_columns].describe().loc[["min", "mean", "max"]]
        print(statistics.to_string(), flush=True)


def run_for_scale(
    scale: int,
    tasks: list[ParamTask],
    canonical_spec: CanonicalGridSpec,
    grid_path: Path,
    fine_res_m: float,
    city: str,
    output_dir: Path | None,
) -> None:
    """1スケール分のパラメータテーブルを算出して書き出す。

    Args:
        scale: coarseグリッド解像度（m）。
        tasks: 算出タスクの一覧。
        canonical_spec: 当該スケールの正準グリッド仕様。
        grid_path: 正準グリッドGeoPackageのパス。
        fine_res_m: 被覆率計算用の補助解像度（m）。
        city: 都市ID（出力パスに使う）。
        output_dir: 出力ルート。``None`` の場合は既定パスを使う。
    """
    grid_spec = build_aligned_grid(canonical_spec, fine_res_m)
    bbox_analysis = aligned_bbox(canonical_spec)
    print(
        f"[scale={scale}m] coarse shape: {grid_spec.coarse_shape} / 整合BBox: {bbox_analysis}",
        flush=True,
    )

    cell_ids = read_grid_cell_ids(grid_path, grid_layer_name(scale))
    print(f"[scale={scale}m] 正準グリッドの対象セル: {cell_ids.size:,} 件", flush=True)

    for task in tasks:
        columns = task.compute(bbox_analysis, grid_spec)
        validate_computed_columns(task, columns)

        table = build_param_table(columns, canonical_spec, cell_ids)
        output_path = resolve_table_path(city, scale, task.table_name, output_dir)
        write_attribute_table(table, output_path, task.table_name)

        summarize_table(task.table_name, table)
        print(f"  出力先: {output_path}", flush=True)


def main(argv: list[str] | None = None) -> None:
    """都市構造パラメータ算出処理を実行する。

    解析範囲は正準グリッドと同じ基準レイヤ（ROI）から取る。``compute()`` へ渡す
    解析BBoxは、ROIのBBoxではなく**正準グリッドのセル境界に載る整合BBox**とする。
    整合BBoxは必ずROIのBBoxを包含するため、ROI側を渡すと外周1セル分の帯にかかる
    道路を取りこぼす。

    Args:
        argv: 解釈する引数列。``None`` の場合は ``sys.argv`` を使う。
    """
    args = parse_arguments(argv)
    city_cfg = CITY_CONFIG[args.city]
    analysis_crs = CRS.from_epsg(int(city_cfg["analysis_epsg"]))

    extent_resource = get_layer_resource(city_cfg, ANALYSIS_EXTENT_LAYER_KEY, analysis_crs)
    roi_bbox = bbox_from_layer(extent_resource, analysis_crs)
    grid_path = resolve_output_path(args.grid, args.city)
    output_dir = (PROJECT_ROOT / args.output_dir) if args.output_dir else None

    print("都市:", args.city)
    print("解析範囲レイヤ:", ANALYSIS_EXTENT_LAYER_KEY, "->", extent_resource.path.name)
    print("ROI BBox:", roi_bbox)
    print("正準グリッド:", grid_path)

    # 入力の解決と、対象スケールのグリッドレイヤの存在確認を、算出に入る前に
    # まとめて済ませる。途中で失敗すると先行するスケール・テーブルの出力だけが
    # 残り、どこまでが最新なのか分からなくなるためである。
    require_grid_layers(grid_path, [grid_layer_name(scale) for scale in args.scales])
    tasks = build_param_tasks(args.params, city_cfg, analysis_crs)
    if args.satellite_file:
        tasks.append(build_satellite_task((PROJECT_ROOT / args.satellite_file).resolve()))
    print("算出するテーブル:", ", ".join(task.table_name for task in tasks))

    # 入力レイヤの読み込みを1回で済ませるため、全スケールを1つのキャッシュスコープで囲む。
    with layer_cache() as cache:
        for scale in args.scales:
            canonical_spec = build_canonical_grid(roi_bbox, analysis_crs, float(scale))
            run_for_scale(
                scale=scale,
                tasks=tasks,
                canonical_spec=canonical_spec,
                grid_path=grid_path,
                fine_res_m=args.fine_res,
                city=args.city,
                output_dir=output_dir,
            )

        print("\n入力レイヤの実読み込み回数:", flush=True)
        for label, count in cache.load_counts.items():
            print(f"  {label}: {count} 回", flush=True)


if __name__ == "__main__":
    main()
