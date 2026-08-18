; Inno Setup script -> builds dist\PulsarBatteryNotifier-Setup.exe
;
; Wraps the PyInstaller one-file exe (dist\PulsarBatteryNotifier.exe) in a
; friendly installer: Start Menu shortcut, optional "run at login", and a
; proper uninstaller. Installs per-user, so it needs no admin rights / UAC.
;
; Build locally (after .\build.ps1 has produced the exe):
;   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer.iss
; The version defaults to 0.0.0-dev if /DAppVersion is not passed.

#define AppName "Pulsar Battery Notifier"
#define AppExe "PulsarBatteryNotifier.exe"
#define Publisher "shuukree"
#define AppUrl "https://github.com/shuukree/pulsar-battery-notifier"
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
; Keep this GUID stable across releases so upgrades replace the prior install.
AppId={{9F3B2C1A-7D4E-4B6A-9E2F-1C8D5A0E3B47}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
DefaultDirName={autopf}\Pulsar Battery Notifier
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=assets\app.ico
OutputDir=dist
OutputBaseFilename=PulsarBatteryNotifier-Setup
Compression=lzma2
SolidCompression=yes
; Per-user install: no admin prompt, no UAC.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "startupicon"; Description: "Start automatically when I sign in to Windows"; GroupDescription: "Startup:"

[Files]
; One-dir bundle: ship the whole program folder.
Source: "dist\PulsarBatteryNotifier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pulsar Battery Notifier"; Filename: "{app}\{#AppExe}"
Name: "{userstartup}\Pulsar Battery Notifier"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Pulsar Battery Notifier now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The Startup shortcut is created by the [Icons] task above and removed with it,
; but clean up in case the app also wrote one on first run.
Type: files; Name: "{userstartup}\Pulsar Battery Notifier.lnk"
