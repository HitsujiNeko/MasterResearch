#!/bin/bash
set -e

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if python3 -c "import ee, geopandas, fiona, pyproj, shapely, rasterio, pandas, numpy, pytest" 2>/dev/null; then
  exit 0
fi

pip install -r requirements.txt pytest

# cryptography（earthengine-api -> google-auth 経由の依存）がコンテナのシステム版cffiと
# 衝突し ModuleNotFoundError: _cffi_backend で失敗することがあるため、明示的に入れ直す
pip install --force-reinstall cffi cryptography
