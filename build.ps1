# Builds a windowed Windows app as a one-dir bundle (a folder), which avoids the
# one-file self-extraction that trips PyInstaller's parent-process security check
# during in-app updates.
# Run from the repo root in PowerShell:  .\build.ps1
#
# Output: dist\PulsarBatteryNotifier\PulsarBatteryNotifier.exe (+ support files)

pip install -r requirements.txt
pip install pyinstaller

python -m PyInstaller --clean --noconfirm --onedir --windowed `
  --name "PulsarBatteryNotifier" `
  --icon "assets\app.ico" `
  --add-data "assets\device_default.png;assets" `
  --hidden-import "winrt.windows.foundation.collections" `
  --collect-all "windows_toasts" `
  --optimize 2 `
  main.py

Write-Host ""
Write-Host "Built: dist\PulsarBatteryNotifier\PulsarBatteryNotifier.exe"

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
