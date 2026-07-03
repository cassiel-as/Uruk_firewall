#!/bin/bash
# URUK Trinity Console - macOS/Linux standalone build

set -e

echo "Building URUK Trinity Console standalone app..."

pip install pyinstaller --quiet

pyinstaller \
  --onefile \
  --windowed \
  --name "URUK_Trinity" \
  --add-data "static:static" \
  --add-data "config:config" \
  --add-data "data:data" \
  --hidden-import "uvicorn.logging" \
  --hidden-import "uvicorn.protocols" \
  --hidden-import "uvicorn.protocols.http" \
  --hidden-import "uvicorn.protocols.http.auto" \
  --hidden-import "uvicorn.protocols.websockets" \
  --hidden-import "uvicorn.protocols.websockets.auto" \
  --hidden-import "uvicorn.lifespan" \
  --hidden-import "uvicorn.lifespan.on" \
  desktop_launcher.py

echo ""
echo "Done. Check dist/URUK_Trinity"
