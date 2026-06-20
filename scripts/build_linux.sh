#!/usr/bin/env bash
# Build the Iris Code desktop binary on Linux and package it as a tarball.
# Run from the repo root:  bash scripts/build_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-gui.txt pyinstaller

rm -rf build dist
pyinstaller packaging/iris_code.spec

# Smoke test the built binary (offscreen — no display needed).
QT_QPA_PLATFORM=offscreen ./dist/IrisCode --selftest

mkdir -p artifacts
tar -C dist -czf "artifacts/IrisCode-linux-x86_64.tar.gz" IrisCode
echo "Built: artifacts/IrisCode-linux-x86_64.tar.gz"
