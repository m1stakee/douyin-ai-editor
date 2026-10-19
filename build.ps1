param()
python -m pip install -r "$PSScriptRoot\requirements.txt"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DouyinAIEditor "$PSScriptRoot\main.py"
Write-Host "Built dist\DouyinAIEditor.exe"
