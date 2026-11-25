; Установщик Немо (Inno Setup 6). Собирается в GitHub Actions:
;   iscc /DAppVersion=1.0.0 installer\nemo.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8B6C1C2E-5E0B-4F8D-9C1A-4E7A1F0B6C11}
AppName=Немо
AppVersion={#AppVersion}
AppVerName=Немо {#AppVersion}
AppPublisher=wonbix1409
AppPublisherURL=https://github.com/wonbix1409/nemo
DefaultDirName={autopf}\Nemo
DefaultGroupName=Немо
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Nemo-Setup-{#AppVersion}
SetupIconFile=..\assets\nemo.ico
UninstallDisplayIcon={app}\Nemo.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\Nemo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Немо"; Filename: "{app}\Nemo.exe"
Name: "{group}\Удалить Немо"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Немо"; Filename: "{app}\Nemo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nemo.exe"; Description: "Запустить Немо"; Flags: nowait postinstall skipifsilent
