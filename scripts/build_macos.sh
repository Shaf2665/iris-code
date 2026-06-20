#!/usr/bin/env bash
# Build IrisCode.app on macOS and wrap it in a .dmg.
# Run from the repo root:  bash scripts/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-gui.txt pyinstaller

# Regenerate a high-res .icns from the source PNG using native macOS tooling
# (falls back to the committed Pillow-made icon.icns if anything fails).
if command -v iconutil >/dev/null && command -v sips >/dev/null; then
  ICONSET="packaging/icon.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s packaging/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s*2)); sips -z $d $d packaging/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o packaging/icon.icns && echo "Regenerated packaging/icon.icns"
  rm -rf "$ICONSET"
fi

rm -rf build dist
pyinstaller packaging/iris_code.spec

# Smoke test the built app bundle (offscreen).
QT_QPA_PLATFORM=offscreen ./dist/IrisCode.app/Contents/MacOS/IrisCode --selftest

mkdir -p artifacts
hdiutil create -volname "Iris Code" -srcfolder "dist/IrisCode.app" \
  -ov -format UDZO "artifacts/IrisCode-macos.dmg"
echo "Built: artifacts/IrisCode-macos.dmg"
