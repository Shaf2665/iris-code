# Build the IrisCode one-folder app on Windows, zip it, and (if Inno Setup is
# present) build an installer.
# Run from the repo root:  pwsh -File scripts\build_windows.ps1
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads no-BOM scripts as
# ANSI, so non-ASCII bytes (e.g. an em-dash) corrupt string parsing.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-gui.txt pyinstaller

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }
pyinstaller packaging\iris_code.spec

# Smoke test the built exe (offscreen - no window needed). One-folder build:
# the executable lives inside dist\IrisCode\.
$env:QT_QPA_PLATFORM = "offscreen"
& .\dist\IrisCode\IrisCode.exe --selftest
Remove-Item Env:\QT_QPA_PLATFORM

New-Item -ItemType Directory -Force -Path artifacts | Out-Null
# Portable zip of the whole folder.
Compress-Archive -Path dist\IrisCode\* -DestinationPath artifacts\IrisCode-windows-x86_64.zip -Force

# Optional: build a proper installer if Inno Setup is available.
$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($iscc) {
    & $iscc.Source packaging\IrisCodeSetup.iss
    Write-Host "Built installer via Inno Setup."
} else {
    Write-Host "Inno Setup (iscc) not found - shipped the portable .zip only."
}
Write-Host "Built: artifacts\IrisCode-windows-x86_64.zip"
