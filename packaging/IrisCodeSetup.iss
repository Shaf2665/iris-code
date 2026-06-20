; Inno Setup script - wraps the PyInstaller onefile exe in a Windows installer.
; Build with:  iscc packaging\IrisCodeSetup.iss   (after pyinstaller has produced dist\IrisCode.exe)

#define AppName "Iris Code"
#define AppVersion "0.1.0"
#define AppPublisher "Shafiq"
#define AppExe "IrisCode.exe"

[Setup]
AppId={{B8B3F2A1-2C4D-4E6F-9A1B-IRISCODE0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\IrisCode
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\artifacts
OutputBaseFilename=IrisCode-Setup
SetupIconFile=..\packaging\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
