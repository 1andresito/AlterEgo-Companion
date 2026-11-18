; Inno Setup script for the Windows installer (AlterEgo-Setup-vX.Y.Z.exe).
;
; Build after PyInstaller, from the project root:
;     iscc /DAppVersion=0.7.0 packaging\windows\alter_ego.iss
; The release workflow passes the version from the git tag.
;
; Installs for the current user only (no administrator prompt), into
; %LOCALAPPDATA%\Programs\Alter Ego. Settings and memories live in
; %APPDATA%\AlterEgo and are kept on update. When uninstalling, a window asks
; what else should go (memories, downloads, Ollama, its models, ...), with
; nothing ticked; a silent uninstall removes only the program.

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

{ ----- Uninstalling: what else should go? -----
  Nothing is ticked: memories survive unless the user asks, and Ollama is its own program that
  other apps may use. "Everything above" ticks all the others. Each choice is shown only when
  there is something to remove, with its size. }

var
  MemoriesBox, DownloadsBox, SpeechBox, FilesBox, ModelsBox, OllamaBox, EverythingBox: TNewCheckBox;
  RemoveMemories, RemoveDownloads, RemoveSpeech, RemoveFiles, RemoveModels, RemoveOllama: Boolean;

function DataDir: String;
begin
  Result := ExpandConstant('{userappdata}\AlterEgo');
end;

function FilesDir: String;
begin
  Result := ExpandConstant('{userdocs}\Alter Ego');
end;

function SpeechCacheDir: String;
begin
  Result := GetEnv('HF_HOME');
  if Result = '' then
    Result := ExpandConstant('{%USERPROFILE}\.cache\huggingface');
  Result := AddBackslash(Result) + 'hub';
end;

function OllamaModelsDir: String;
begin
  Result := GetEnv('OLLAMA_MODELS');
  if Result = '' then
    Result := ExpandConstant('{%USERPROFILE}\.ollama\models');
end;

function OllamaUninstaller: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Ollama\unins000.exe');
end;

function FolderSize(const Path: String): Int64;
var
  Rec: TFindRec;
begin
  Result := 0;
  if FindFirst(AddBackslash(Path) + '*', Rec) then
  try
    repeat
      if (Rec.Name <> '.') and (Rec.Name <> '..') then
      begin
        if Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          Result := Result + FolderSize(AddBackslash(Path) + Rec.Name)
        else
          Result := Result + Int64(Rec.SizeHigh) * 4294967296 + Rec.SizeLow;
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

{ Alter Ego's speech models only (Systran faster-whisper), never the rest of the shared cache. }
function SpeechSize: Int64;
var
  Rec: TFindRec;
begin
  Result := 0;
  if FindFirst(AddBackslash(SpeechCacheDir) + 'models--Systran--faster-whisper-*', Rec) then
  try
    repeat
      Result := Result + FolderSize(AddBackslash(SpeechCacheDir) + Rec.Name);
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

{ Memories and settings: everything in the data folder except the downloads (voices, gpu). }
function MemoriesSize: Int64;
var
  Rec: TFindRec;
begin
  Result := 0;
  if FindFirst(AddBackslash(DataDir) + '*', Rec) then
  try
    repeat
      if (Rec.Name <> '.') and (Rec.Name <> '..') and (CompareText(Rec.Name, 'voices') <> 0)
          and (CompareText(Rec.Name, 'gpu') <> 0) then
      begin
        if Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          Result := Result + FolderSize(AddBackslash(DataDir) + Rec.Name)
        else
          Result := Result + Int64(Rec.SizeHigh) * 4294967296 + Rec.SizeLow;
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

function SizeText(Size: Int64): String;
var
  Tenths: Int64;
begin
  if Size >= 1073741824 then
  begin
    Tenths := Size div 107374182;
    Result := IntToStr(Tenths div 10) + '.' + IntToStr(Tenths mod 10) + ' GB';
  end
  else if Size >= 1048576 then
    Result := IntToStr(Size div 1048576) + ' MB'
  else
    Result := 'less than 1 MB';
end;

procedure EverythingClicked(Sender: TObject);
var
  Box: TNewCheckBox;
  I: Integer;
begin
  for I := 0 to 5 do
  begin
    case I of
      0: Box := MemoriesBox;
      1: Box := DownloadsBox;
      2: Box := SpeechBox;
      3: Box := FilesBox;
      4: Box := ModelsBox;
    else
      Box := OllamaBox;
    end;
    if Box.Enabled then
      Box.Checked := EverythingBox.Checked;
  end;
end;

function AddChoice(Form: TSetupForm; var Top: Integer; const Caption: String; Available: Boolean): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(Form);
  Result.Parent := Form;
  Result.Left := ScaleX(20);
  Result.Top := Top;
  Result.Width := Form.ClientWidth - ScaleX(40);
  Result.Height := ScaleY(20);
  Result.Caption := Caption;
  Result.Checked := False;
  Result.Enabled := Available;
  if not Available then
    Result.Caption := Caption + ' (nothing to remove)';
  Top := Top + ScaleY(26);
end;

function InitializeUninstall: Boolean;
var
  Form: TSetupForm;
  Intro: TNewStaticText;
  UninstallButton, CancelButton: TNewButton;
  Top: Integer;
  Downloads, Speech, Files, Models: Int64;
begin
  Result := True;
  if UninstallSilent then
    Exit;  { Scripts and silent uninstalls remove only the program. }

  Downloads := FolderSize(DataDir + '\voices') + FolderSize(DataDir + '\gpu');
  Speech := SpeechSize;
  Files := FolderSize(FilesDir);
  Models := FolderSize(OllamaModelsDir);

  { Inno Setup 6.6+ takes the size here (unscaled; it scales it itself) and makes it read-only. }
  Form := CreateCustomForm(500, 330, True, True);
  try
    Form.Caption := 'Uninstall Alter Ego';
    Form.Position := poScreenCenter;

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(20);
    Intro.Top := ScaleY(16);
    Intro.Width := Form.ClientWidth - ScaleX(40);
    Intro.WordWrap := True;
    Intro.Caption := 'Alter Ego will be removed. What else should go? Anything not ticked is kept, ' +
      'so you can reinstall later and pick up where you left off.';
    Intro.AutoSize := True;

    Top := ScaleY(64);
    MemoriesBox := AddChoice(Form, Top, 'My memories and settings (' + SizeText(MemoriesSize) + ')',
      DirExists(DataDir) and (MemoriesSize > 0));
    DownloadsBox := AddChoice(Form, Top, 'My voice files and the GPU pack (' + SizeText(Downloads) + ')',
      Downloads > 0);
    SpeechBox := AddChoice(Form, Top, 'My speech-recognition models (' + SizeText(Speech) + ')', Speech > 0);
    FilesBox := AddChoice(Form, Top, 'Files I saved for you in Documents\Alter Ego (' + SizeText(Files) + ')',
      DirExists(FilesDir));
    ModelsBox := AddChoice(Form, Top, 'Ollama''s AI models, for every program that uses Ollama (' +
      SizeText(Models) + ')', Models > 0);
    OllamaBox := AddChoice(Form, Top, 'The Ollama program itself', FileExists(OllamaUninstaller));
    Top := Top + ScaleY(6);
    EverythingBox := AddChoice(Form, Top, 'Everything above', True);
    EverythingBox.Caption := 'Everything above';
    EverythingBox.Font.Style := [fsBold];
    EverythingBox.OnClick := @EverythingClicked;

    UninstallButton := TNewButton.Create(Form);
    UninstallButton.Parent := Form;
    UninstallButton.Caption := 'Uninstall';
    UninstallButton.ModalResult := mrOk;
    UninstallButton.Default := True;
    UninstallButton.Width := ScaleX(90);
    UninstallButton.Height := ScaleY(26);
    UninstallButton.Left := Form.ClientWidth - ScaleX(20) - ScaleX(90) * 2 - ScaleX(10);
    UninstallButton.Top := Form.ClientHeight - ScaleY(44);

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    CancelButton.Width := ScaleX(90);
    CancelButton.Height := ScaleY(26);
    CancelButton.Left := Form.ClientWidth - ScaleX(20) - ScaleX(90);
    CancelButton.Top := Form.ClientHeight - ScaleY(44);

    if Form.ShowModal <> mrOk then
    begin
      Result := False;  { Cancel: nothing is uninstalled. }
      Exit;
    end;

    RemoveMemories := MemoriesBox.Checked;
    RemoveDownloads := DownloadsBox.Checked;
    RemoveSpeech := SpeechBox.Checked;
    RemoveFiles := FilesBox.Checked;
    RemoveModels := ModelsBox.Checked;
    RemoveOllama := OllamaBox.Checked;
  finally
    Form.Free;
  end;

  if RemoveMemories or RemoveFiles or RemoveModels then
    if MsgBox('Deleting memories, your saved files or Ollama''s models can''t be undone. Continue?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
      Result := False;
end;

procedure DeleteMemories;
var
  Rec: TFindRec;
  Path: String;
begin
  if FindFirst(AddBackslash(DataDir) + '*', Rec) then
  try
    repeat
      Path := AddBackslash(DataDir) + Rec.Name;
      if (Rec.Name <> '.') and (Rec.Name <> '..') and (CompareText(Rec.Name, 'voices') <> 0)
          and (CompareText(Rec.Name, 'gpu') <> 0) then
      begin
        if Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          DelTree(Path, True, True, True)
        else
          DeleteFile(Path);
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

procedure DeleteSpeechModels;
var
  Rec: TFindRec;
begin
  if FindFirst(AddBackslash(SpeechCacheDir) + 'models--Systran--faster-whisper-*', Rec) then
  try
    repeat
      DelTree(AddBackslash(SpeechCacheDir) + Rec.Name, True, True, True);
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

procedure StopProgram(const Exe: String);
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "' + Exe + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
    StopProgram('{#AppExe}');  { Alter Ego and its helper processes, so no file is in use. }
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if RemoveModels or RemoveOllama then
  begin
    StopProgram('ollama app.exe');
    StopProgram('ollama.exe');
  end;
  if RemoveMemories then
    DeleteMemories;
  if RemoveDownloads then
  begin
    DelTree(DataDir + '\voices', True, True, True);
    DelTree(DataDir + '\gpu', True, True, True);
  end;
  if RemoveMemories and RemoveDownloads then
    RemoveDir(DataDir);
  if RemoveSpeech then
    DeleteSpeechModels;
  if RemoveFiles then
    DelTree(FilesDir, True, True, True);
  if RemoveModels then
    DelTree(OllamaModelsDir, True, True, True);
  if RemoveOllama and FileExists(OllamaUninstaller) then
    Exec(OllamaUninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;
