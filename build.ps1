param()
$ErrorActionPreference = "Stop"
$distSettings = Join-Path $PSScriptRoot "dist\settings.local.json"
$distCredentials = Join-Path $PSScriptRoot "dist\credentials.local.json"
Remove-Item -LiteralPath $distSettings, $distCredentials -Force -ErrorAction SilentlyContinue
$vendorDirectory = Join-Path $PSScriptRoot "vendor\ffmpeg"
$ffmpegPath = Join-Path $vendorDirectory "ffmpeg.exe"
$licensePath = Join-Path $vendorDirectory "LICENSE"
if (-not (Test-Path -LiteralPath $ffmpegPath) -or -not (Test-Path -LiteralPath $licensePath)) {
    $archivePath = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
    $extractDirectory = Join-Path $env:TEMP "douyin-ai-editor-ffmpeg-essentials"
    New-Item -ItemType Directory -Path $vendorDirectory -Force | Out-Null
    Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $archivePath
    if (Test-Path -LiteralPath $extractDirectory) { Remove-Item -LiteralPath $extractDirectory -Recurse -Force }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDirectory -Force
    $bundle = Get-ChildItem -LiteralPath $extractDirectory -Directory | Select-Object -First 1
    Copy-Item -LiteralPath (Join-Path $bundle.FullName "bin\ffmpeg.exe") -Destination $ffmpegPath -Force
    Copy-Item -LiteralPath (Join-Path $bundle.FullName "LICENSE") -Destination $licensePath -Force
}
python -m pip install -r "$PSScriptRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DouyinAIEditor --add-binary "$ffmpegPath;." --add-data "$licensePath;ffmpeg-license" "$PSScriptRoot\main.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Built dist\DouyinAIEditor.exe"
