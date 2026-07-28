#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef VersionInfoVersion
  #define VersionInfoVersion "1.0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #define OutputDir ".\out"
#endif

#ifndef AppPublisher
  #define AppPublisher "Remote Bridge Contributors"
#endif
#ifndef AppGroupName
  #define AppGroupName "Remote Bridge"
#endif

[Setup]
AppId={#SetupAppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppGroupName}\{#AppFolder}
DefaultGroupName={#AppGroupName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=yes
InfoBeforeFile={#ReadmeFile}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#VersionInfoVersion}
VersionInfoVersion={#VersionInfoVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "..\..\setup\ChineseSimplified.isl"

[Tasks]
Name: "startmenuicon"; Description: "创建开始菜单快捷方式"; Flags: checkedonce
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
Name: "startup"; Description: "登录 Windows 后自动启动"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ReadmeFile}"; DestDir: "{app}"; DestName: "使用说明.txt"; Flags: ignoreversion
Source: "..\..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; DestName: "第三方组件说明.md"; Flags: ignoreversion
Source: "stop-product.ps1"; DestDir: "{app}\support"; Flags: ignoreversion
Source: "stop-product.ps1"; Flags: dontcopy
#if ProductKind == "xiaomi"
Source: "configure-xiaomi-audio.ps1"; DestDir: "{app}\support"; Flags: ignoreversion
Source: "..\..\vendor\frida-COPYING.txt"; DestDir: "{app}\support\third-party"; Flags: ignoreversion
#else
Source: "configure-native-audio.ps1"; DestDir: "{app}\support"; Flags: ignoreversion
#endif

[Icons]
Name: "{autoprograms}\{#AppGroupName}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: startmenuicon
Name: "{autoprograms}\{#AppGroupName}\{#AppName} 使用说明"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\使用说明.txt"""; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: "--minimized"; WorkingDir: "{app}"; Tasks: startup
#if ProductKind == "xiaomi"
Name: "{autoprograms}\{#AppGroupName}\小米语音环境检查与修复"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-xiaomi-audio.ps1"" -Mode Repair -AppPath ""{app}"""; WorkingDir: "{app}\support"
#else
Name: "{autoprograms}\{#AppGroupName}\{#AppName} 麦克风检查与修复"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-native-audio.ps1"" -Mode Repair -ProductId ""{#ProductId}"" -ProductName ""{#AppName}"" -EndpointPattern ""{#EndpointPattern}"""; WorkingDir: "{app}\support"
#endif

[Run]
#if ProductKind == "xiaomi"
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-xiaomi-audio.ps1"" -Mode Install -AppPath ""{app}"""; WorkingDir: "{app}\support"; StatusMsg: "正在从 VB-Audio 官方地址下载并配置小米语音环境..."; Flags: waituntilterminated skipifsilent
#else
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-native-audio.ps1"" -Mode Install -ProductId ""{#ProductId}"" -ProductName ""{#AppName}"" -EndpointPattern ""{#EndpointPattern}"""; WorkingDir: "{app}\support"; StatusMsg: "正在配置设备自带麦克风..."; Flags: waituntilterminated skipifsilent
#endif
Filename: "{app}\{#AppExeName}"; Description: "立即启动 {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\stop-product.ps1"" -AppPath ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "StopProduct"
#if ProductKind == "xiaomi"
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-xiaomi-audio.ps1"" -Mode Restore -AppPath ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "RestoreMicrophone"
#else
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\configure-native-audio.ps1"" -Mode Restore -ProductId ""{#ProductId}"" -ProductName ""{#AppName}"" -EndpointPattern ""{#EndpointPattern}"""; Flags: runhidden waituntilterminated; RunOnceId: "RestoreMicrophone"
#endif

[Code]
function StopRunningProduct(): Boolean;
var
  ResultCode: Integer;
begin
  ExtractTemporaryFile('stop-product.ps1');
  Result := Exec(
    ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File ' + AddQuotes(ExpandConstant('{tmp}\stop-product.ps1')) + ' -AppPath ' + AddQuotes(ExpandConstant('{app}')),
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode
  ) and (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if StopRunningProduct() then Result := ''
  else Result := '无法安全关闭正在运行的桥接程序，请先从托盘退出后重试。';
end;
