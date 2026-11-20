#define AppName "Photo Viewer"
#define AppVersion "2.0.1"
#define AppExeName "PhotoViewer.exe"
#define ProgId "PhotoViewer.Image"
#define SourceDir "..\dist\PhotoViewer"
#define SourceRoot ".."
#define OutputDir "..\release"

[Setup]
AppId={{26CDC75D-0D0D-401F-9F5C-5F65D5BDC143}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion=2.0.1.0
VersionInfoProductVersion=2.0.1.0
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UsePreviousPrivileges=no
; Recalculate the scope-specific default directory on every run so users can
; switch between per-user and all-users installs without reusing the previous
; scope's path.
UsePreviousAppDir=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern dynamic windows11 hidebevels
WizardSizePercent=120,120
WizardBackColor=#fdfcff
WizardBackColorDynamicDark=#211f28
SetupIconFile={#SourceRoot}\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} v{#AppVersion}
OutputDir={#OutputDir}
OutputBaseFilename=PhotoViewer_v2.0.1_Setup
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter={#AppExeName}
RestartApplications=no
ChangesAssociations=yes
MinVersion=10.0
ShowLanguageDialog=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "settings.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\settings.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\INSTALLER_BUILD_v2.0.1.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} 실행"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  ImageExtensionCount = 39;
  AppProgId = '{#ProgId}';
  NoPreviousAssociation = '<none>';
  UninstallRegistryKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{26CDC75D-0D0D-401F-9F5C-5F65D5BDC143}_is1';
  LegacyUninstallRegistryKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A83BE9D6-7C2C-4C70-9EEB-4EBEA01D2090}_is1';
  UninstallRegistryBase = 'Software\Microsoft\Windows\CurrentVersion\Uninstall';

var
  AssociationPage: TWizardPage;
  AssociationList: TNewCheckListBox;
  SelectAllButton: TNewButton;
  ClearAllButton: TNewButton;
  SelectionCountLabel: TNewStaticText;
  AssociationNoteLabel: TNewStaticText;
  ImageExtensions: array[0..ImageExtensionCount - 1] of String;
  ImageDescriptions: array[0..ImageExtensionCount - 1] of String;

procedure InitializeImageExtensions;
begin
  ImageExtensions[0] := '.apng'; ImageDescriptions[0] := 'Animated PNG';
  ImageExtensions[1] := '.avif'; ImageDescriptions[1] := 'AVIF Image';
  ImageExtensions[2] := '.avifs'; ImageDescriptions[2] := 'AVIF Sequence';
  ImageExtensions[3] := '.bmp'; ImageDescriptions[3] := 'Bitmap Image';
  ImageExtensions[4] := '.bw'; ImageDescriptions[4] := 'SGI Image';
  ImageExtensions[5] := '.dds'; ImageDescriptions[5] := 'DirectDraw Surface';
  ImageExtensions[6] := '.gif'; ImageDescriptions[6] := 'GIF Image';
  ImageExtensions[7] := '.icb'; ImageDescriptions[7] := 'Targa Image';
  ImageExtensions[8] := '.ico'; ImageDescriptions[8] := 'Windows Icon';
  ImageExtensions[9] := '.j2c'; ImageDescriptions[9] := 'JPEG 2000';
  ImageExtensions[10] := '.j2k'; ImageDescriptions[10] := 'JPEG 2000';
  ImageExtensions[11] := '.jfif'; ImageDescriptions[11] := 'JPEG Image';
  ImageExtensions[12] := '.jp2'; ImageDescriptions[12] := 'JPEG 2000';
  ImageExtensions[13] := '.jpc'; ImageDescriptions[13] := 'JPEG 2000';
  ImageExtensions[14] := '.jpe'; ImageDescriptions[14] := 'JPEG Image';
  ImageExtensions[15] := '.jpeg'; ImageDescriptions[15] := 'JPEG Image';
  ImageExtensions[16] := '.jpf'; ImageDescriptions[16] := 'JPEG 2000';
  ImageExtensions[17] := '.jpg'; ImageDescriptions[17] := 'JPEG Image';
  ImageExtensions[18] := '.jpx'; ImageDescriptions[18] := 'JPEG 2000';
  ImageExtensions[19] := '.pbm'; ImageDescriptions[19] := 'Portable Bitmap';
  ImageExtensions[20] := '.pcx'; ImageDescriptions[20] := 'PCX Image';
  ImageExtensions[21] := '.pgm'; ImageDescriptions[21] := 'Portable Graymap';
  ImageExtensions[22] := '.png'; ImageDescriptions[22] := 'PNG Image';
  ImageExtensions[23] := '.pnm'; ImageDescriptions[23] := 'Portable Anymap';
  ImageExtensions[24] := '.ppm'; ImageDescriptions[24] := 'Portable Pixmap';
  ImageExtensions[25] := '.psd'; ImageDescriptions[25] := 'Photoshop Image';
  ImageExtensions[26] := '.qoi'; ImageDescriptions[26] := 'Quite OK Image';
  ImageExtensions[27] := '.ras'; ImageDescriptions[27] := 'Sun Raster Image';
  ImageExtensions[28] := '.rgb'; ImageDescriptions[28] := 'SGI Image';
  ImageExtensions[29] := '.rgba'; ImageDescriptions[29] := 'SGI Image';
  ImageExtensions[30] := '.sgi'; ImageDescriptions[30] := 'SGI Image';
  ImageExtensions[31] := '.tga'; ImageDescriptions[31] := 'Targa Image';
  ImageExtensions[32] := '.tif'; ImageDescriptions[32] := 'TIFF Image';
  ImageExtensions[33] := '.tiff'; ImageDescriptions[33] := 'TIFF Image';
  ImageExtensions[34] := '.vda'; ImageDescriptions[34] := 'Targa Image';
  ImageExtensions[35] := '.vst'; ImageDescriptions[35] := 'Targa Image';
  ImageExtensions[36] := '.webp'; ImageDescriptions[36] := 'WebP Image';
  ImageExtensions[37] := '.xbm'; ImageDescriptions[37] := 'X Bitmap';
  ImageExtensions[38] := '.xpm'; ImageDescriptions[38] := 'X PixMap';
end;

procedure UpdateSelectionCount;
var
  I, SelectedCount: Integer;
begin
  SelectedCount := 0;
  for I := 0 to ImageExtensionCount - 1 do
    if AssociationList.Checked[I] then
      SelectedCount := SelectedCount + 1;
  SelectionCountLabel.Caption := Format('%d / %d 선택', [SelectedCount, ImageExtensionCount]);
  SelectionCountLabel.Left := AssociationPage.SurfaceWidth - SelectionCountLabel.Width;
end;

procedure AssociationClickCheck(Sender: TObject);
begin
  UpdateSelectionCount;
end;

procedure SelectAllClick(Sender: TObject);
var
  I: Integer;
begin
  for I := 0 to ImageExtensionCount - 1 do
    AssociationList.Checked[I] := True;
  UpdateSelectionCount;
end;

procedure ClearAllClick(Sender: TObject);
var
  I: Integer;
begin
  for I := 0 to ImageExtensionCount - 1 do
    AssociationList.Checked[I] := False;
  UpdateSelectionCount;
end;

procedure InitializeWizard;
var
  I: Integer;
begin
  InitializeImageExtensions;

  AssociationPage := CreateCustomPage(
    wpSelectDir,
    '연결할 이미지 확장자를 선택하세요',
    '선택한 형식의 이미지를 Photo Viewer로 열 수 있게 등록합니다.');

  SelectAllButton := TNewButton.Create(AssociationPage);
  SelectAllButton.Parent := AssociationPage.Surface;
  SelectAllButton.Caption := '전체 선택';
  SelectAllButton.Left := 0;
  SelectAllButton.Top := 0;
  SelectAllButton.Width := ScaleX(90);
  SelectAllButton.OnClick := @SelectAllClick;

  ClearAllButton := TNewButton.Create(AssociationPage);
  ClearAllButton.Parent := AssociationPage.Surface;
  ClearAllButton.Caption := '전체 해제';
  ClearAllButton.Left := SelectAllButton.Left + SelectAllButton.Width + ScaleX(8);
  ClearAllButton.Top := 0;
  ClearAllButton.Width := ScaleX(90);
  ClearAllButton.OnClick := @ClearAllClick;

  SelectionCountLabel := TNewStaticText.Create(AssociationPage);
  SelectionCountLabel.Parent := AssociationPage.Surface;
  SelectionCountLabel.AutoSize := True;
  SelectionCountLabel.Top := ScaleY(8);

  AssociationList := TNewCheckListBox.Create(AssociationPage);
  AssociationList.Parent := AssociationPage.Surface;
  AssociationList.Left := 0;
  AssociationList.Top := SelectAllButton.Top + SelectAllButton.Height + ScaleY(10);
  AssociationList.Width := AssociationPage.SurfaceWidth;
  AssociationList.Height := AssociationPage.SurfaceHeight - AssociationList.Top - ScaleY(36);
  AssociationList.Flat := True;
  AssociationList.ShowLines := False;
  AssociationList.MinItemHeight := ScaleY(24);
  AssociationList.OnClickCheck := @AssociationClickCheck;
  for I := 0 to ImageExtensionCount - 1 do
    AssociationList.AddCheckBox(
      Uppercase(ImageExtensions[I]), ImageDescriptions[I], 0,
      True, True, False, True, nil);

  AssociationNoteLabel := TNewStaticText.Create(AssociationPage);
  AssociationNoteLabel.Parent := AssociationPage.Surface;
  AssociationNoteLabel.Left := 0;
  AssociationNoteLabel.Top := AssociationList.Top + AssociationList.Height + ScaleY(8);
  AssociationNoteLabel.Width := AssociationPage.SurfaceWidth;
  AssociationNoteLabel.AutoSize := False;
  AssociationNoteLabel.WordWrap := True;
  AssociationNoteLabel.Caption := '기본값은 전체 선택입니다. 영상은 제외합니다. 실제 기본 앱 선택이 필요한 확장자는 설치 후 이미지 파일을 더블클릭하여 연결하세요.';

  UpdateSelectionCount;
end;

function ExtractUninstallExecutable(const CommandLine: String): String;
var
  S: String;
  ClosingQuote, FirstSpace: Integer;
begin
  Result := '';
  S := Trim(CommandLine);
  if S = '' then
    exit;

  if S[1] = '"' then
  begin
    Delete(S, 1, 1);
    ClosingQuote := Pos('"', S);
    if ClosingQuote > 0 then
      Result := Copy(S, 1, ClosingQuote - 1);
  end
  else
  begin
    FirstSpace := Pos(' ', S);
    if FirstSpace > 0 then
      Result := Copy(S, 1, FirstSpace - 1)
    else
      Result := S;
  end;
end;

function StartsWithVersionedName(const Name, Prefix: String): Boolean;
var
  VersionStart: Integer;
begin
  VersionStart := Length(Prefix) + 1;
  Result :=
    (Pos(Prefix, Name) = 1) and
    (Length(Name) >= VersionStart) and
    (Name[VersionStart] >= '0') and (Name[VersionStart] <= '9');
end;

function IsPhotoViewerDisplayName(const DisplayName: String): Boolean;
var
  Name: String;
begin
  Name := Lowercase(Trim(DisplayName));
  Result :=
    (Name = 'photo viewer') or
    StartsWithVersionedName(Name, 'photo viewer v') or
    (Name = 'portable photo viewer') or
    StartsWithVersionedName(Name, 'portable photo viewer v');
end;

function RunRegisteredUninstaller(
  Root: Integer; const RegistryKey: String; Elevate: Boolean;
  var FailureMessage: String): Boolean;
var
  CommandLine, Uninstaller, Parameters: String;
  ExitCode: Integer;
  Started: Boolean;
begin
  Result := True;
  if not RegKeyExists(Root, RegistryKey) then
    exit;

  if not RegQueryStringValue(Root, RegistryKey, 'QuietUninstallString', CommandLine) then
    RegQueryStringValue(Root, RegistryKey, 'UninstallString', CommandLine);
  Uninstaller := ExtractUninstallExecutable(CommandLine);
  if (Uninstaller = '') or (not FileExists(Uninstaller)) then
  begin
    FailureMessage :=
      '기존 Photo Viewer 제거 프로그램을 찾을 수 없습니다.' + #13#10 +
      RegistryKey;
    Result := False;
    exit;
  end;

  Parameters := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';
  if Elevate then
    Started := ShellExec(
      'runas', Uninstaller, Parameters, '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode)
  else
    Started := Exec(
      Uninstaller, Parameters, '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode);

  if not Started then
  begin
    FailureMessage :=
      '기존 Photo Viewer 제거를 시작하지 못했습니다.' + #13#10 +
      '전체 사용자 설치 제거 권한 요청을 취소했다면 다시 실행하여 허용해 주세요.';
    Result := False;
    exit;
  end;

  if ExitCode <> 0 then
  begin
    FailureMessage := Format(
      '기존 Photo Viewer 제거가 실패했습니다. (종료 코드: %d)', [ExitCode]);
    Result := False;
    exit;
  end;

  if RegKeyExists(Root, RegistryKey) then
  begin
    FailureMessage :=
      '기존 Photo Viewer 설치 정보가 제거 후에도 남아 있습니다.' + #13#10 +
      'PC를 다시 시작한 뒤 설치 파일을 다시 실행해 주세요.';
    Result := False;
  end;
end;

function RemoveMatchingInstallations(
  Root: Integer; Elevate: Boolean; var FailureMessage: String): Boolean;
var
  SubKeys: TArrayOfString;
  RegistryKey, DisplayName: String;
  I: Integer;
begin
  Result := True;
  if not RegGetSubkeyNames(Root, UninstallRegistryBase, SubKeys) then
    exit;

  for I := 0 to GetArrayLength(SubKeys) - 1 do
  begin
    RegistryKey := UninstallRegistryBase + '\' + SubKeys[I];
    DisplayName := '';
    RegQueryStringValue(Root, RegistryKey, 'DisplayName', DisplayName);
    if IsPhotoViewerDisplayName(DisplayName) then
    begin
      if not RunRegisteredUninstaller(
        Root, RegistryKey, Elevate, FailureMessage) then
      begin
        Result := False;
        exit;
      end;
    end;
  end;
end;

function RemoveAllExistingInstallations(var FailureMessage: String): Boolean;
var
  IgnoreExitCode: Integer;
begin
  Result := False;

  { Ensure an old viewer cannot keep its executable or VLC files locked. }
  Exec(
    ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExeName}', '',
    SW_HIDE, ewWaitUntilTerminated, IgnoreExitCode);

  { Remove every registered per-user build, including legacy AppIds. }
  if not RunRegisteredUninstaller(
    HKEY_CURRENT_USER, UninstallRegistryKey, False, FailureMessage) then
    exit;
  if not RunRegisteredUninstaller(
    HKEY_CURRENT_USER, LegacyUninstallRegistryKey, False, FailureMessage) then
    exit;
  if not RemoveMatchingInstallations(
    HKEY_CURRENT_USER, False, FailureMessage) then
    exit;

  { Machine-wide uninstallers always run elevated. If Setup is already
    elevated Windows reuses that token; otherwise this produces one UAC prompt. }
  if not RunRegisteredUninstaller(
    HKEY_LOCAL_MACHINE, UninstallRegistryKey, True, FailureMessage) then
    exit;
  if not RunRegisteredUninstaller(
    HKEY_LOCAL_MACHINE, LegacyUninstallRegistryKey, True, FailureMessage) then
    exit;
  if not RemoveMatchingInstallations(
    HKEY_LOCAL_MACHINE, True, FailureMessage) then
    exit;

  { Also cover installers built as 32-bit before the x64 packaging change. }
  if not RunRegisteredUninstaller(
    HKEY_LOCAL_MACHINE_32, UninstallRegistryKey, True, FailureMessage) then
    exit;
  if not RunRegisteredUninstaller(
    HKEY_LOCAL_MACHINE_32, LegacyUninstallRegistryKey, True, FailureMessage) then
    exit;
  if not RemoveMatchingInstallations(
    HKEY_LOCAL_MACHINE_32, True, FailureMessage) then
    exit;

  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  RemoveAllExistingInstallations(Result);
end;

function AssociationRoot: Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function ClassesKey(const Suffix: String): String;
begin
  Result := 'Software\Classes\' + Suffix;
end;

function BackupKey: String;
begin
  Result := 'Software\Photo Viewer\Installer\PreviousAssociations';
end;

procedure BackupPreviousAssociation(Root: Integer; const Ext: String);
var
  PreviousValue: String;
begin
  if RegValueExists(Root, BackupKey, Ext) then
    exit;
  if RegQueryStringValue(Root, ClassesKey(Ext), '', PreviousValue) then
    RegWriteStringValue(Root, BackupKey, Ext, PreviousValue)
  else
    RegWriteStringValue(Root, BackupKey, Ext, NoPreviousAssociation);
end;

procedure RestorePreviousAssociation(Root: Integer; const Ext: String);
var
  CurrentValue, PreviousValue: String;
begin
  if not RegQueryStringValue(Root, ClassesKey(Ext), '', CurrentValue) then
    CurrentValue := '';

  if CurrentValue = AppProgId then
  begin
    if RegQueryStringValue(Root, BackupKey, Ext, PreviousValue) then
    begin
      if PreviousValue = NoPreviousAssociation then
        RegDeleteValue(Root, ClassesKey(Ext), '')
      else
        RegWriteStringValue(Root, ClassesKey(Ext), '', PreviousValue);
    end
    else
      RegDeleteValue(Root, ClassesKey(Ext), '');
  end;

  RegDeleteValue(Root, ClassesKey(Ext + '\OpenWithProgids'), AppProgId);
  RegDeleteValue(Root, ClassesKey('Applications\{#AppExeName}\SupportedTypes'), Ext);
  RegDeleteValue(Root, 'Software\Photo Viewer\Capabilities\FileAssociations', Ext);
  RegDeleteValue(Root, BackupKey, Ext);
end;

procedure RegisterProgId(Root: Integer);
var
  ExePath, OpenCommand: String;
begin
  ExePath := ExpandConstant('{app}\{#AppExeName}');
  OpenCommand := '"' + ExePath + '" "%1"';

  RegWriteStringValue(Root, ClassesKey(AppProgId), '', 'Photo Viewer 이미지');
  RegWriteStringValue(Root, ClassesKey(AppProgId + '\DefaultIcon'), '', ExePath + ',0');
  RegWriteStringValue(Root, ClassesKey(AppProgId + '\shell\open\command'), '', OpenCommand);

  RegWriteStringValue(Root, ClassesKey('Applications\{#AppExeName}'), 'FriendlyAppName', '{#AppName}');
  RegWriteStringValue(Root, ClassesKey('Applications\{#AppExeName}\DefaultIcon'), '', ExePath + ',0');
  RegWriteStringValue(Root, ClassesKey('Applications\{#AppExeName}\shell\open\command'), '', OpenCommand);

  RegWriteStringValue(Root, 'Software\Photo Viewer\Capabilities', 'ApplicationName', '{#AppName}');
  RegWriteStringValue(Root, 'Software\Photo Viewer\Capabilities', 'ApplicationDescription', '이미지와 영상을 빠르게 탐색하고 보는 프로그램');
  RegWriteStringValue(Root, 'Software\Photo Viewer\Capabilities', 'ApplicationIcon', ExePath + ',0');
  RegWriteStringValue(Root, 'Software\RegisteredApplications', '{#AppName}', 'Software\Photo Viewer\Capabilities');
end;

procedure RemoveProgId(Root: Integer);
begin
  RegDeleteValue(Root, 'Software\RegisteredApplications', '{#AppName}');
  RegDeleteKeyIncludingSubkeys(Root, ClassesKey(AppProgId));
  RegDeleteKeyIncludingSubkeys(Root, ClassesKey('Applications\{#AppExeName}'));
  RegDeleteKeyIncludingSubkeys(Root, 'Software\Photo Viewer\Capabilities');
  RegDeleteKeyIfEmpty(Root, BackupKey);
  RegDeleteKeyIfEmpty(Root, 'Software\Photo Viewer\Installer');
  RegDeleteKeyIfEmpty(Root, 'Software\Photo Viewer');
end;

procedure ApplySelectedAssociations;
var
  I, Root: Integer;
  Ext: String;
begin
  Root := AssociationRoot;
  RegisterProgId(Root);
  for I := 0 to ImageExtensionCount - 1 do
  begin
    Ext := ImageExtensions[I];
    if AssociationList.Checked[I] then
    begin
      { Use the Windows-supported registration model without forcing UserChoice. }
      RestorePreviousAssociation(Root, Ext);
      RegWriteStringValue(Root, ClassesKey(Ext + '\OpenWithProgids'), AppProgId, '');
      RegWriteStringValue(Root, ClassesKey('Applications\{#AppExeName}\SupportedTypes'), Ext, '');
      RegWriteStringValue(Root, 'Software\Photo Viewer\Capabilities\FileAssociations', Ext, AppProgId);
    end
    else
      RestorePreviousAssociation(Root, Ext);
  end;
end;

procedure RemoveAllAssociations;
var
  I, Root: Integer;
begin
  Root := AssociationRoot;
  for I := 0 to ImageExtensionCount - 1 do
    RestorePreviousAssociation(Root, ImageExtensions[I]);
  RemoveProgId(Root);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ApplySelectedAssociations;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    InitializeImageExtensions;
    RemoveAllAssociations;
  end;
end;
