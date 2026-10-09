; WinLinAI Windows Installer Script (Inno Setup)
; Creates a .exe installer for WinLinAI on Windows
;
; Prerequisites:
;   - Inno Setup 6 installed (https://jrsoftware.org/isinfo.php)
;   - Python 3.12 installed on the build machine
;
; Usage:
;   iscc installer/winlinai.iss
;
; Or use the build script:
;   powershell -ExecutionPolicy Bypass -File installer/build-installer.ps1

#define MyAppName "WinLinAI"
#ifndef MyAppVersion
  // The build script passes /DMyAppVersion=<version from src/_version.py>;
  // this fallback only serves ad-hoc compiles.
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "WinLinAI Team"
#define MyAppURL "https://github.com/1400015/winlinai"
#define MyAppExeName "winlinai.exe"
#define MyAppId "{{8F6D4E2A-1B3C-4D5E-9F8A-7B6C5D4E3F2A}"

[Setup]
; Application information
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases

; Installation directories
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Output. Paths are relative to this script, which lives in installer\.
OutputDir=output
OutputBaseFilename=WinLinAI-{#MyAppVersion}-Setup
SetupIconFile=..\assets\io.github.linux_ai_assistant.ico

; Compression
Compression=lzma2
SolidCompression=yes

; Privileges (install for current user only - no admin required)
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

; Modern UI
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start WinLinAI when Windows starts"; GroupDescription: "Startup"; Flags: checkedonce

[Files]
; Application files (dist/ will be created by the build script)
Source: "pyinstaller\dist\winlinai\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Visual C++ Redistributable (if needed for Python)
; Source: "installer\vcredist_x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsVCRedist

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "WinLinAI - AI Assistant for Windows"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

; Desktop icon (optional)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "WinLinAI - AI Assistant for Windows"

; Startup (autostart)
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon; Comment: "WinLinAI"

[Run]
; Launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Check if Visual C++ Redistributable is needed
function NeedsVCRedist(): Boolean;
begin
  // Python 3.12 requires VC++ Redistributable
  Result := True;
end;

// Check if app is running and close it before uninstall
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // Try to close running instances; a taskkill failure means the app is
  // simply not running, which must not abort the installation.
  Exec('taskkill', '/F /IM winlinai.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

// Custom welcome message
function InitializeSetup(): Boolean;
begin
  Result := True;
  // Could add Python version check here
end;
