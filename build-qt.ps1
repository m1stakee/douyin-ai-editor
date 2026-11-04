$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv-qt\Scripts\python.exe')) {
        python -m venv .venv-qt
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $qtPython = Join-Path $PSScriptRoot '.venv-qt\Scripts\python.exe'
    & $qtPython -m pip install -r requirements-qt.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not (Test-Path -LiteralPath 'vendor\ffmpeg\ffmpeg.exe')) { throw 'Run build.ps1 first to prepare bundled FFmpeg.' }
    & $qtPython -m PyInstaller --noconfirm --clean --onefile --windowed --name VideoFlow-Qt-Preview --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --add-binary 'vendor\ffmpeg\ffmpeg.exe;.' --add-data 'vendor\ffmpeg\LICENSE;ffmpeg-license' qt_voice_preview.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
