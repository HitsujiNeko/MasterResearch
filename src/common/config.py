"""複数スクリプトで共有する定数群。

プロジェクトルート・CRS・Hanoi ROI のデフォルトパスなど、
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

# ハノイROIのデフォルトShapefileパス
DEFAULT_HANOI_ROI_PATH = (
    PROJECT_ROOT / "data" / "gis" / "boundaries" / "hanoi" / "hanoi_ROI_EPSG4326.shp"
)
