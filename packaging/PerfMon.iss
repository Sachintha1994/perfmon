; Inno Setup script for PerfMon. Built by build.bat - run that instead of compiling
; this directly (it prepares dist\PerfMon\ and vendor\ first).

#define AppName "PerfMon"
#define AppVersion "1.2.1"
#define AppExe "PerfMon.exe"

[Setup]
AppId={{6B1E6C7A-4E0B-4C55-9D1E-5B7C9F2A1D10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL=https://github.com/Sachintha1994/perfmon
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Admin is needed once: temperature monitoring installs the PawnIO driver and a
; scheduled task that starts LibreHardwareMonitor elevated at sign-in.
PrivilegesRequired=admin
OutputDir=..\installer
OutputBaseFilename=PerfMon-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
MinVersion=10.0.17763

[Tasks]
Name: "sensors"; Description: "Enable temperature monitoring (installs LibreHardwareMonitor and the PawnIO sensor driver)"; GroupDescription: "Temperatures:"
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startup"; Description: "Start PerfMon when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\PerfMon\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\vendor\LibreHardwareMonitor\*"; DestDir: "{app}\LibreHardwareMonitor"; Tasks: sensors; Flags: ignoreversion recursesubdirs createallsubdirs
; preset: local-only web server for PerfMon, minimized to tray; keep the user's own settings on upgrade
Source: "LibreHardwareMonitor.config"; DestDir: "{app}\LibreHardwareMonitor"; Tasks: sensors; Flags: onlyifdoesntexist
Source: "sensors.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\vendor\PawnIO_setup.exe"; DestDir: "{tmp}"; Tasks: sensors; Flags: deleteafterinstall
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{tmp}\PawnIO_setup.exe"; Parameters: "-install -silent"; StatusMsg: "Installing the PawnIO sensor driver..."; Tasks: sensors; Check: not PawnIOInstalled; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\sensors.ps1"" -Action uninstall -AppDir ""{app}"""; RunOnceId: "RemoveSensorsTask"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\LibreHardwareMonitor"
Type: filesandordirs; Name: "{localappdata}\{#AppName}"

[Code]
function PawnIOInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO');
end;

{ Registers the sign-in task and starts the sensors; warns (instead of failing silently) on error. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('sensors') then
  begin
    WizardForm.StatusLabel.Caption := 'Setting up temperature monitoring...';
    if (not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\tools\sensors.ps1') +
        '" -Action install -AppDir "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code)) or (Code <> 0) then
      SuppressibleMsgBox('PerfMon was installed, but temperature monitoring could not be set up (code ' + IntToStr(Code) + ').' + #13#10#13#10 +
        'PerfMon will still work; you can start the sensors from its Thermals page instead.', mbError, MB_OK, IDOK);
  end;
end;

{ Stop a running bundled LibreHardwareMonitor so its files can be replaced on upgrade. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\tools\sensors.ps1')) then
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process LibreHardwareMonitor -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '*'' } | Stop-Process -Force"',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
