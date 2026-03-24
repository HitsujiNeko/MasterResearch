"""GPKG内の外れ値ジオメトリ探索

目的:
    いくつかの merge_*_wgs84.gpkg でBBoxが不自然に広がる原因（少数の外れ値座標）を
    特定するため、指定レイヤの地物を走査して「想定範囲」を外れる最初の地物を見つける。

注意:
    - 全件走査になる可能性がある（DCは地物数が多い）。
    - まずは「最初の外れ値1件」を見つける用途。

実行例:
    python -m src.analysis.find_gpkg_outliers \
      --gpkg data/output/gis_wgs84/merge_DC_wgs84.gpkg --layer elements

最終更新: 2026-03-03
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import fiona


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def flatten_coords(coords: Any) -> list[tuple[float, float]]:
    """GeoJSON coordinates を (x,y) のリストに平坦化する（Polygon/MultiPolygon対応）。"""
    out: list[tuple[float, float]] = []

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, (list, tuple)):
            if len(obj) == 2 and all(isinstance(v, (int, float)) for v in obj):
                out.append((float(obj[0]), float(obj[1])))
                return
            for item in obj:
                walk(item)

    walk(coords)
    return out


def bbox_from_geom(geom: dict[str, Any]) -> tuple[float, float, float, float] | None:
    coords = flatten_coords(geom.get("coordinates"))
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def iter_features(path: Path, layer: str) -> Iterable[dict[str, Any]]:
    with fiona.open(path, layer=layer) as src:
        for feat in src:
            yield feat


def main() -> None:
    parser = argparse.ArgumentParser(description="GPKG内の外れ値ジオメトリ探索")
    parser.add_argument("--gpkg", required=True, help="対象GPKG（相対パス推奨）")
    parser.add_argument("--layer", required=True, help="対象レイヤ名")
    parser.add_argument("--lon-min", type=float, default=104.5)
    parser.add_argument("--lon-max", type=float, default=107.5)
    parser.add_argument("--lat-min", type=float, default=19.0)
    parser.add_argument("--lat-max", type=float, default=22.5)
    parser.add_argument("--progress-every", type=int, default=100000)
    args = parser.parse_args()

    gpkg_path = (PROJECT_ROOT / args.gpkg).resolve() if not Path(args.gpkg).is_absolute() else Path(args.gpkg)

    if not gpkg_path.exists():
        raise FileNotFoundError(f"GPKGが見つかりません: {gpkg_path}")

    lon_min, lon_max = args.lon_min, args.lon_max
    lat_min, lat_max = args.lat_min, args.lat_max

    print("対象:", gpkg_path)
    print("レイヤ:", args.layer)
    print("想定範囲: lon[", lon_min, ",", lon_max, "] lat[", lat_min, ",", lat_max, "]")

    checked = 0
    for feat_idx, feat in enumerate(iter_features(gpkg_path, args.layer), start=1):
        geom = feat.get("geometry")
        if not geom:
            continue
        bb = bbox_from_geom(geom)
        if bb is None:
            continue

        checked += 1
        if checked % args.progress_every == 0:
            print("  checked:", checked)

        minx, miny, maxx, maxy = bb
        if minx < lon_min or maxx > lon_max or miny < lat_min or maxy > lat_max:
            props = feat.get("properties") or {}
            print("FOUND outlier")
            print("  feature_index:", feat_idx)
            print("  bbox:", bb)
            # プロパティが巨大な場合があるためキーだけ出す
            print("  properties_keys:", list(props.keys())[:30])
            break
    else:
        print("No outlier found under thresholds")


if __name__ == "__main__":
    main()
