; Installer DiFFDB per Windows (Inno Setup).
;
; Compilato in CI:  ISCC /DMyAppVersion=1.3.0 packaging\windows\DiFFDB.iss
; Prende l'eseguibile gia' costruito da PyInstaller in dist\DiFFDB.exe e produce
; dist\DiFFDB-Setup-<versione>.exe.
;
; Installazione per-utente (nessun admin): meno attrito con SmartScreen, e
; coerente con un'app portable che non tocca HKLM. L'utente puo' comunque
; scegliere un'installazione per-macchina dal dialogo iniziale.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "DiFFDB"
#define MyAppExeName "DiFFDB.exe"
#define MyAppPublisher "DiFFDB"
#define MyAppURL "https://github.com/Tony-BlaZeeR/DiFFDB"

[Setup]
; AppId identifica il programma per gli aggiornamenti e la disinstallazione:
; deve restare lo stesso fra le versioni, quindi NON va rigenerato.
AppId={{A7E3F1C2-8D4B-4E6A-9F2C-1B5D7E9A3C40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\..\dist
OutputBaseFilename=DiFFDB-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\diffdb\images\logo.ico
; Per-utente di default, con possibilita' di scegliere per-macchina.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
