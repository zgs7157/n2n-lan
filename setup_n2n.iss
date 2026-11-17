; n2n-lan 房间管理器 安装脚本（Inno Setup 6）
; 编译：ISCC.exe setup_n2n.iss
#define MyAppName "n2n-lan 房间管理器"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "n2n-lan"
#define MyAppURL "https://zgs7157.github.io/n2n-lan/"
#define MyAppExeName "n2n_room_manager.exe"
#define MyAppIcon "n2n-lan.ico"

[Setup]
AppId={{8E2C4A51-7D3B-4F0A-9B61-5C2D8E3A1F47}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}releases
VersionInfoVersion=1.1.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
DefaultDirName={autopf}\n2n-lan
DefaultGroupName=n2n-lan
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist_installer
OutputBaseFilename=n2n-lan-setup-{#MyAppVersion}
SetupIconFile=client\{#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
DisableWelcomePage=no

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; 客户端全部内容：exe、bin（edge/supernode/udp6 转发器）、TAP 驱动、源码、mac/linux 脚本
Source: "client\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "logs\*,config.json,n2n_room_manager_old_noipv6.exe,edge_lucktu_nov6.bak.exe,__pycache__\*,*.pyc,*.bak,tools\WinIPBroadcast.exe"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIcon}"; Comment: "n2n-lan 局域网联机组网客户端"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#MyAppIcon}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIcon}"; Tasks: desktopicon; Comment: "n2n-lan 局域网联机组网客户端"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\config.json"
Type: dirifempty; Name: "{app}"
