# Builds a single-file, windowed Windows executable.
# Run from the repo root in PowerShell:  .\build.ps1
#
# Output: dist\PulsarBatteryNotifier.exe

pip install -r requirements.txt
pip install pyinstaller

python -m PyInstaller --clean --noconfirm --onefile --windowed `
  --name "PulsarBatteryNotifier" `
  --hidden-import "winrt.windows.foundation.collections" `
  --collect-all "windows_toasts" `
  --optimize 2 `
  main.py

Write-Host ""
Write-Host "Built: dist\PulsarBatteryNotifier.exe"
Write-Host "To auto-start on login, drop a shortcut to it in:"
Write-Host "  %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
