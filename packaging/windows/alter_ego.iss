; Inno Setup script for the Windows installer (AlterEgo-Setup-vX.Y.Z.exe).
;
; Build after PyInstaller, from the project root:
;     iscc /DAppVersion=0.7.0 packaging\windows\alter_ego.iss
; The release workflow passes the version from the git tag.
;
; Installs for the current user only (no administrator prompt), into
; %LOCALAPPDATA%\Programs\Alter Ego. Settings and memories live in
; %APPDATA%\AlterEgo and are kept when Alter Ego is uninstalled or updated.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Alter Ego"
#define AppExe "AlterEgo.exe"

[Setup]
AppId={{6C3B7F0E-2E5A-4C7B-9C51-AE0A1E7E6F21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Alter Ego contributors
AppPublisherURL=https://github.com/1andresito/AlterEgo-Companion
AppSupportURL=https://github.com/1andresito/AlterEgo-Companion/issues
DefaultDirName={localappdata}\Programs\Alter Ego
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
SetupIconFile=..\AlterEgo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\..\dist
OutputBaseFilename=AlterEgo-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put Alter Ego on the desktop"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Alter Ego when I sign in to Windows"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\AlterEgo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update replaces the whole program folder, so files from an older version cannot linger.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start Alter Ego now"; Flags: nowait postinstall skipifsilent
; An update from inside Alter Ego runs this installer silently with /RELAUNCH=1, so the new version starts by itself.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchAfterUpdate

[Code]
function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
