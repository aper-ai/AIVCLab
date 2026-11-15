#define WorkbenchName "AIVCLab · 虚拟细胞研究平台"
#define WorkbenchPublisher "Aper AI"
#define WorkbenchExe "AperVirtualCellWorkbench.exe"
#ifndef WorkbenchPayload
#error Use build.ps1 to freeze the workbench and provide the installation payload.
#endif

[Setup]
AppId={{7D5D4566-0C97-42D9-BCF4-A743A29DB94A}
AppName={#WorkbenchName}
AppVersion={#WorkbenchVersion}
AppPublisher={#WorkbenchPublisher}
DefaultDirName={localappdata}\Programs\Aper AI\Virtual Cell Workbench
DefaultGroupName=Aper AI
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter={#WorkbenchExe}
RestartApplications=no
Compression=lzma2
SolidCompression=yes
OutputDir={#WorkbenchOutput}
OutputBaseFilename=AperAI-VirtualCell-Workbench-Setup-{#WorkbenchVersion}-x64
UninstallDisplayIcon={app}\{#WorkbenchExe}
VersionInfoVersion={#WorkbenchVersion}
VersionInfoCompany={#WorkbenchPublisher}
VersionInfoDescription={#WorkbenchName} Setup
#ifdef WorkbenchIcon
SetupIconFile={#WorkbenchIcon}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#ifdef ChineseMessages
Name: "chinesesimp"; MessagesFile: "{#ChineseMessages}"
#endif

[Files]
Source: "{#WorkbenchPayload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef TranslationLicense
Source: "{#TranslationLicense}"; DestDir: "{app}\licenses"; DestName: "Inno-Chinese-Simplified.LICENSE.txt"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#WorkbenchName}"; Filename: "{app}\{#WorkbenchExe}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#WorkbenchExe}"; Description: "{cm:LaunchProgram,{#WorkbenchName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
