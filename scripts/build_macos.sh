#!/usr/bin/env bash
# Build IrisCode.app on macOS and wrap it in a .dmg.
# Run from the repo root:  bash scripts/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-gui.txt pyinstaller

rm -rf build dist
pyinstaller packaging/iris_code.spec

# Smoke test the built app bundle (offscreen).
QT_QPA_PLATFORM=offscreen ./dist/IrisCode.app/Contents/MacOS/IrisCode --selftest

mkdir -p artifacts
hdiutil create -volname "Iris Code" -srcfolder "dist/IrisCode.app" \
  -ov -format UDZO "artifacts/IrisCode-macos.dmg"
echo "Built: artifacts/IrisCode-macos.dmg"
