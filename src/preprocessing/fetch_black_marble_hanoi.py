"""NASA Black Marble（VNP46A4）年次プロダクトから Hanoi ROI の夜間光を取得する。

データソース: NASA LAADS DAAC の ArchiveSet 5200（Black Marble Collection 2.0）
<https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/>

ライセンス: NASA オープンサイエンスポリシー（再配布・改変とも自由）。出典表記は
NASA VIIRS Land Science Team（Black Marble）に対して行う。

制約メモ（2026-07-27 確認）:
- **年次プロダクト VNP46A4 は Google Earth Engine に存在しない**。GEE で使えるのは
  日次の `NASA/VIIRS/002/VNP46A2` と `NOAA/VIIRS/001/VNP46A1` のみ。年次を使うには
  LAADS DAAC から直接取得する必要がある。
- **Earthdata の Bearer トークンが必須**。ファイル一覧 API の時点で Earthdata の
  OAuth へリダイレクト（HTTP 302）される。トークンは
  <https://ladsweb.modaps.eosdis.nasa.gov/profile/#generate-token> で発行し、
  リポジトリ直下の `.env`（Git 管理外）に `EARTHDATA_TOKEN=...` として置く。
  環境変数で与えた場合はそちらが優先される。
- **データ利用許諾（ライセンス）への同意が別途必要**。未同意だと 401 ではなく
  `/profiles/licenses/...` へ 303 され、リダイレクトを辿った先の Earthdata OAuth で
  401 になる。原因が分かりにくいため `find_license_gate` で切り分けている。
  同意はブラウザで Earthdata にログインした状態で同ページを開いて行う。
- **ダウンロード URL は自前で組み立てない**。公開パス
  （`/archive/allData/...`）はライセンス同意ページへ 303 されるため、
  一覧が返す `downloadsLink`（`/api/v2/content/archives/allData/...`）を使う。
  ただし一覧の URL は外部由来のため、宛先は `ALLOWED_DOWNLOAD_HOSTS` へ限る。
  `urllib` は `Authorization` をリダイレクト先へ引き継ぐので、初回 URL の検証
  だけでは足りず、リダイレクト先も `ALLOWED_REDIRECT_HOSTS` で検証する。
- 配布形式は HDF-EOS5（`.h5`）、10°×10° のタイル単位。h28v06 の 2023 年版は
  実測 119.8MB（製品ページ記載の「92MB」より大きい）。
  **本環境の GDAL は HDF5 ドライバなしでビルドされている**ため、読み込みには h5py を使う。
- タイルは 10°グリッド（原点 -180E/90N、h は西→東、v は北→南）。Hanoi ROI
  （経度 105.29-106.02、緯度 20.56-21.39）は `h28v06` 1 タイルに収まる。
- 年次プロダクトの day-of-year は常に `001`。
- SDS 名・スケール係数・欠測値は**ファイルの属性から実測して適用する**（配布バージョンで
  変わりうるため、コード側で決め打ちしない）。想定した SDS が無い場合は、実在する
  SDS 名を添えて例外にする。
- ファイル内部の構造（2026-07-29 に h28v06 の 2023 年版で実測）:
  - SDS のグループは `HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields`
    （プロダクト名から連想される `VNP_Grid_DNB` ではない）
  - 合成バンドは 2400×2400 の **float32 で既に物理値**（`scale_factor = 1.0`、
    `offset = 0.0`、`_FillValue = -999.9`、単位 `nWatts/(cm^2 sr)`）
  - **オフセット属性の名前は `offset`**（CF 規約の `add_offset` ではない）
  - ルート属性に `WestBoundingCoord` 等の境界座標と `HorizontalTileNumber` /
    `VerticalTileNumber` があり、タイル番号の妥当性を突き合わせられる

処理の本体は `src/preprocessing/black_marble/` の各モジュールにあり、本ファイルは
コマンドライン引数の解釈と実行の振り分けだけを持つ（上記の関数名・定数名もそちらにある）。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.common.config import DEFAULT_HANOI_ROI_PATH, LANDSAT_OBSERVATION_YEAR, PROJECT_ROOT
from src.preprocessing.black_marble.auth import EARTHDATA_TOKEN_ENV_VAR
from src.preprocessing.black_marble.pipeline import run, run_inspection

# ダウンロードした .h5 タイルの保存先。1 タイル 100MB 超のため再実行で再取得しない。
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "gis" / "raw" / "black_marble"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。

    Returns:
        解析済み引数。
    """
    parser = argparse.ArgumentParser(
        description="NASA Black Marble（VNP46A4）から Hanoi ROI の夜間光を取得する。"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=LANDSAT_OBSERVATION_YEAR,
        help="取得対象年。",
    )
    parser.add_argument(
        "--roi-path",
        type=Path,
        default=DEFAULT_HANOI_ROI_PATH,
        help="ROI の Shapefile パス。",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help=(
            "試行実行用の小範囲 BBOX（EPSG:4326）。配布はタイル単位のため"
            "ダウンロード量は減らず、クリップ範囲だけが狭くなる点に注意する。"
        ),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            "出力 GeoTIFF パス。未指定時は data/gis/nighttime_lights/black_marble/ 配下へ保存する。"
        ),
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="サマリー JSON パス。未指定時は data/output/open_gis/ 配下へ保存する。",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="ダウンロードした .h5 タイルの保存先。既に在れば再ダウンロードしない。",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help=(
            f"Earthdata トークンだけを記載したファイル。未指定時は環境変数 "
            f"{EARTHDATA_TOKEN_ENV_VAR} を見て、無ければリポジトリ直下の .env を読む。"
        ),
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help=(
            "取得済みタイルの HDF5 構造（SDS 名・形状・属性）を出力して終了する。"
            "配布バージョンの変更で SDS 名や属性が変わっていないかの確認に使う。"
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の出力ファイルを上書きする。",
    )
    return parser.parse_args()


def main() -> None:
    """エントリーポイント。"""
    args = parse_arguments()
    if args.inspect:
        run_inspection(
            year=args.year, cache_dir=args.cache_dir, roi_path=args.roi_path, bbox=args.bbox
        )
        return

    output_path, summary_path = run(
        year=args.year,
        roi_path=args.roi_path,
        bbox=args.bbox,
        output_path=args.output_path,
        summary_path=args.summary_path,
        cache_dir=args.cache_dir,
        token_file=args.token_file,
        overwrite=args.overwrite,
    )
    print(f"GeoTIFF を保存しました: {output_path}")
    print(f"サマリー JSON を保存しました: {summary_path}")


if __name__ == "__main__":
    main()
