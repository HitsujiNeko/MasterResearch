# データ取得スクリプト作成 — 参照情報

## データソース区分と参照実装の対応表

| 区分 | 典型例 | 参照実装（必ずReadする） | 踏襲すべきポイント |
|---|---|---|---|
| GEE ラスタ取得 | DEM、LULC、夜間光、人口密度、不透水面率 | `src/gee/download_open_dem.py` | GEE認証、ROIクリップ、GeoTIFF+メタデータJSON出力、dataclassによる設定管理 |
| HTTP / WFS ベクタ取得 | 建物（GBA）、POI、水域 | `src/preprocessing/fetch_gba_buildings_hanoi.py` | タイル分割クエリ、リトライ（指数バックオフ）、レート制限対応、EPSG変換、カバレッジ確認 |
| ローカルファイル抽出・変換 | OSM PBF 抽出、公園ポリゴン | `src/preprocessing/extract_geofabrik_roads_hanoi.py` | ogr2ogr 候補パス探索、属性フィルタ、ROIクリップ、サマリーJSON |

## scaffold 構成（共通の型）

スクリプトは以下の構成を標準とする（参照実装と同じ並び）:

```python
"""
{データセット名} から Hanoi ROI 内の{対象}を取得する。

データソース: {URL または GEEアセットID}
ライセンス: {ライセンス名・出典表記の要否}

制約メモ（YYYY-MM-DD 確認）:
- {レート制限・ページング不可・タイムアウト等、動作確認で判明した制約}
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROI_PATH = PROJECT_ROOT / "data" / "gis" / "boundaries" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "gis" / "{カテゴリ}" / "{出力名}.gpkg"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data" / "output" / "open_gis" / "{出力名}_summary.json"

HANOI_UTM_CRS = "EPSG:32648"  # 面積・距離計算用
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_COUNT = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    # --roi / --output / --summary / 試行実行用の --bbox 等を定義


def load_roi(roi_path: Path):
    """ROI ポリゴンを読み込み、EPSG:4326 のジオメトリを返す。"""


def fetch_data(...):
    """データソースから取得する（リトライ・レート制限対応を含む）。"""


def build_summary(...) -> dict:
    """件数・カバレッジ・値域などのサマリー辞書を作る（純粋関数・テスト対象）。"""


def main() -> None:
    """取得 → 検証 → 保存 → サマリー出力を実行する。"""


if __name__ == "__main__":
    main()
```

設計原則:

- 引数なしで「本番の全量取得」、`--bbox` 等の引数で「小範囲の試行実行」ができるようにする
- サマリー生成・座標計算・属性変換は I/O から分離した純粋関数にする（テスト容易性のため）
- 中間結果・進捗ログを適宜出力する（大規模データ処理時）

## 検証チェックリスト（Step 6 で実施）

- [ ] **CRS**: 出力の CRS が EPSG:4326 である（`gdf.crs` / rasterio の `crs` で確認）
- [ ] **件数・値域**: 件数（ベクタ）または画素統計（ラスタ: `total_pixels` / `valid_pixels` / `valid_pixel_ratio` / `mean` / `min` / `max` / `std`）が調査ドキュメントの想定と整合する
- [ ] **カバレッジ**: ROI に対する空間的な抜けがない（bbox比較、必要なら QGIS で目視）
- [ ] **属性**: 必要な属性列が揃い、型・単位が仕様どおり（LST関連は必ず °C）
- [ ] **有効カバレッジの記録**: 欠損域・データ提供範囲の限界をサマリーJSONと調査ドキュメントに記録する
- [ ] **再現性**: 同一引数での再実行で同一結果になる（乱数を使う場合はシード固定）
- [ ] **QGIS 突合**（集計値を出す場合）: 同一入力を QGIS ネイティブアルゴリズムに渡し、結果を突き合わせる。突合値は必ず直前のツール出力からコピーする（記憶・再計算による値を渡さない）

## サマリーJSON の標準項目

```json
{
  "dataset": "データセット名",
  "source": "URL または GEEアセットID",
  "retrieved_at": "ISO8601 日時",
  "roi": "ROIファイルパス",
  "crs": "EPSG:4326",
  "feature_count": 0,
  "coverage_note": "欠損域・提供範囲の注意",
  "outputs": {"gpkg": "...", "summary": "..."}
}
```

ラスタの場合は `feature_count` の代わりに `pixel_stats` を記録する。キー名は既存実装（`src/gee/gee_calc_LST.py` の `calculate_pixel_stats()` 等）の契約に合わせ、`total_pixels` / `valid_pixels` / `valid_pixel_ratio` を基本とし、必要に応じて `mean` / `min` / `max` / `std` を含める。
