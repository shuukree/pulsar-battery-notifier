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

# If Inno Setup is installed, also build the friendly installer (setup.exe).
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
  & $iscc /DAppVersion=1.0.0 installer.iss
  Write-Host "Built: dist\PulsarBatteryNotifier-Setup.exe"
} else {
  Write-Host "Inno Setup not found - skipping installer."
  Write-Host "Install it from https://jrsoftware.org/isdl.php to build setup.exe."
}

Write-Host "To auto-start on login, install via setup.exe (tick the startup box),"
Write-Host "or drop a shortcut to the exe in:"
Write-Host "  %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
