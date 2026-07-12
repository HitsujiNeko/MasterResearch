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
