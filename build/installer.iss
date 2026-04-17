; Inno Setup script for "Up Front Shop"
;
; Produces:  UpFrontShopSetup.exe  — a normal Windows installer that
; drops the app in C:\Program Files\UpFrontShop\, adds Start Menu and
; Desktop shortcuts, and writes the SQLite DB into %APPDATA%\UpFrontShop\
; on first launch.
;
; Build with Inno Setup 6:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
;
; Requires a prior PyInstaller build (see build\upfront.spec and build\build.bat).

#define MyAppName     "Up Front Shop"
#define MyAppVersion  "1.6.0"
#define MyAppPublisher "Up Front Auto Repair"
#define MyAppExeName  "UpFrontShop.exe"

[Setup]
AppId={{B1F2A4B0-9A1C-4C8E-AE6A-5C1F36D14F21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\UpFrontShop
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=UpFrontShopSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
; Installer shell icon (shown in Explorer before the user launches it)
; and in the wizard title bar. Uses the multi-resolution .ico we ship.
SetupIconFile=..\resources\upfront_logo.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";   Description: "Create a &Desktop shortcut";    GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
; Pull in the entire PyInstaller --onedir output
Source: "..\dist\UpFrontShop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";     Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leave %APPDATA%\UpFrontShop\ alone on uninstall so shop data is preserved.
; If you really want to wipe data, uncomment the next line:
; Type: filesandordirs; Name: "{userappdata}\UpFrontShop"
