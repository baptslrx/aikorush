; Installateur Windows d'AikoRush (Inno Setup 6)
#define AppVersion GetEnv("AIKORUSH_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B176F0D8-FFB5-4642-846B-D45033B4A813}
AppName=AikoRush
AppVersion={#AppVersion}
AppPublisher=Aikographic
DefaultDirName={localappdata}\Programs\AikoRush
DefaultGroupName=AikoRush
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AikoRush-Windows-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AikoRush.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Options :"

[Files]
Source: "..\app\dist\AikoRush\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AikoRush"; Filename: "{app}\AikoRush.exe"
Name: "{group}\Désinstaller AikoRush"; Filename: "{uninstallexe}"
Name: "{userdesktop}\AikoRush"; Filename: "{app}\AikoRush.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AikoRush.exe"; Description: "Lancer AikoRush"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM AikoRush.exe"; Flags: runhidden; RunOnceId: "KillAikoRush"
