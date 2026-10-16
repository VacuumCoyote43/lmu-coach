; Instalador de LMU Coach (Inno Setup 6). Compilar con build.bat o: ISCC installer.iss
#define AppName "LMU Coach"
#define AppVersion "1.5.0"

[Setup]
AppId={{6C1B7D0E-4A52-4C61-9E0B-5F3A9C2D7E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Sidney Cadahia
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Sin permisos de administrador: se instala para el usuario actual
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=LMU-Coach-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\{#AppName} - solo modo coach"; Filename: "{app}\{#AppName}.exe"; Parameters: "--coach"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Registry]
; Doble clic en un .lmusession -> lo importa en LMU Coach
Root: HKA; Subkey: "Software\Classes\.lmusession"; ValueType: string; ValueName: ""; ValueData: "LMUCoach.Session"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\LMUCoach.Session"; ValueType: string; ValueName: ""; ValueData: "Sesión de LMU Coach"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LMUCoach.Session\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppName}.exe,0"
Root: HKA; Subkey: "Software\Classes\LMUCoach.Session\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppName}.exe"" ""%1"""

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
