; Script generated for Muse AI Tool (similar to Tool Dola)
; SEE THE DOCUMENTATION FOR DETAILS ON CREATING INNO SETUP SCRIPT FILES!

#ifndef MyAppVersion
#define MyAppVersion "1.0.9"
#endif
#define MyAppName "Tool Muse"
#define MyAppPublisher "Muse AI"
#define MyAppURL "http://127.0.0.1:18610"
#define MyAppExeName "ToolMuse.exe"

[Setup]
AppId={{E6F74D42-9B7C-4C0A-9B77-9E457C9024D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Tool Muse
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=Tool_Muse_Setup_{#MyAppVersion}
SetupIconFile=app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{app}"; Permissions: users-full
Name: "{app}\.venv"; Permissions: users-full
Name: "{localappdata}\ToolMuse\data"; Permissions: users-full
Name: "{localappdata}\ToolMuse\data\media"; Permissions: users-full
Name: "{localappdata}\ToolMuse\data\refs"; Permissions: users-full
Name: "{localappdata}\ToolMuse\data\chrome_profiles"; Permissions: users-full
Name: "{app}\bin"; Permissions: users-full
Name: "{app}\redist"; Permissions: users-full

[Files]
; Main launcher executable with embedded icon
Source: "dist\ToolMuse.exe"; DestDir: "{app}"; Flags: ignoreversion

; Core Python source files
Source: "desktop.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "firebase_config.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "database.rules.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "VERSION"; DestDir: "{app}"; Flags: ignoreversion

; Core module
Source: "core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs

; Binaries (FFmpeg, FFprobe)
Source: "bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; Offline Python 3.12 64-bit installer
Source: "redist\python-3.12.10-amd64.exe"; DestDir: "{app}\redist"; Flags: ignoreversion skipifsourcedoesntexist

; Static Web Assets
Source: "static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
