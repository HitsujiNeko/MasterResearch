"""複数スクリプトで共有する定数群。

プロジェクトルート・CRS・Hanoi ROI のデフォルトパス・Landsat 観測年など、
`src/` 配下の複数ファイルで重複していた定数をここに集約する。
"""

from __future__ import annotations

from pathlib import Path

# src/common/config.py から2階層上がプロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 入出力の基準CRS（WGS84）
WGS84_CRS = "EPSG:4326"

# ハノイ周辺の面積・距離計算用CRS（UTM Zone 48N）
HANOI_UTM_CRS = "EPSG:32648"

# 本研究の Landsat 観測年。各データセットの提供年がこれに届くかの判定、
# 時間差の注記、取得スクリプトの既定年に使う。
LANDSAT_OBSERVATION_YEAR = 2023

# ハノイROIのデフォルトShapefileパス
DEFAULT_HANOI_ROI_PATH = (
    PROJECT_ROOT / "data" / "gis" / "boundaries" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
)

# 主採用観測（本研究で主に分析する Landsat の観測）の ID。
# 形式は「観測日_時刻（UTC）」で、分析データセット・出力先のファイル名やディレクトリ名に使う
PRIMARY_OBSERVATION_ID = "20220906_032358"

# 公開GISデータの取得・比較スクリプトが書き出すサマリーの既定の出力先
DEFAULT_OPEN_GIS_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "open_gis"
