# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Iris Code desktop app.

Run from the repo root on each target OS:

    pyinstaller packaging/iris_code.spec

Produces a single windowed executable in dist/:
  • Linux/Windows: dist/IrisCode  (onefile)
  • macOS:         dist/IrisCode.app  (bundle, via BUNDLE below)

markdown and pygments import lexers/styles/extensions dynamically, so we
collect them wholesale; the PySide6 PyInstaller hook handles Qt plugins.
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("markdown", "pygments", "forge", "gui"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Bundle the PNG so the running app can set its window icon (frozen + source).
datas += [(os.path.join("..", "packaging", "icon.png"), "packaging")]

block_cipher = None
is_mac = sys.platform == "darwin"

# Platform-specific app icon: .ico (Windows), .icns (macOS), none (Linux).
if sys.platform == "win32":
    app_icon = os.path.join("..", "packaging", "icon.ico")
elif is_mac:
    app_icon = os.path.join("..", "packaging", "icon.icns")
else:
    app_icon = None

a = Analysis(
    ["../iris_code_gui.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="IrisCode",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,                      # windowed app (no terminal)
    disable_windowed_traceback=False,
    icon=app_icon,
    target_arch=None,
)

if is_mac:
    app = BUNDLE(
        exe,
        name="IrisCode.app",
        icon=app_icon,
        bundle_identifier="dev.iriscode.forge",
        info_plist={
            "CFBundleName": "Iris Code",
            "CFBundleDisplayName": "Iris Code",
            "NSHighResolutionCapable": True,
        },
    )
