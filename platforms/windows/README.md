# MiVibe Remote for Windows

本目录基于 `xxb26553663-star/remote-bridge-hub v1.0.0` 的 Xiaomi
独立应用，保留其 WinRT GATT、ATVV、Windows 输入注入、VB-CABLE、托盘程序和安装器。

MiVibe Remote 的增量：

- 独立产品名称和原创 `.ico` 图标；
- 新增“Codex 预设”“WorkBuddy 预设”和“微信预设”：
  - 电源键：从 Windows 开始菜单查找并打开当前预设应用；
  - 确定键：Enter / 发送；
  - 方向键：导航；
  - 返回键：退格；
  - 菜单键：Escape；
  - Codex 语音键：默认按住右 Alt；
  - WorkBuddy 语音键：语音开始和结束时分别点按一次 `Ctrl+D`；
  - 语音快捷键仍可继续自定义；
- Xiaomi 动作执行器复用上游已有的 `command` 动作能力；
- 普通按键支持单击自定义，返回键和音量键保留上游长按重复；
- 使用 WinSparkle 每 24 小时自动检查一次已签名更新，主窗口和托盘也可手动“检查更新”；
- 主窗口和托盘提供“关于 MiVibe Remote”，可查看作者联系方式、复制微信号并检查更新；
- 主窗口改为状态控制台，新增只读环境检查：分别检查配置、VB-CABLE 两个端点、后台桥接、修复脚本和遥控器识别，并给出对应修复动作；
- 新增应用内使用教程，覆盖首次安装、预设、触发方式和真实文本框测试；
- 安装路径和开始菜单分组不再使用上游商业品牌。

## 构建要求

- 64 位 Windows 10 1809 或更高版本；
- Python 3.12；
- Inno Setup 6；
- `requirements.txt` 与 `requirements-dev.txt` 中的依赖。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -v
$env:MIVIBE_APPCAST_URL = "https://updates.example.com/windows-appcast.xml"
$env:MIVIBE_UPDATE_ED25519_PUBLIC_KEY = "<base64-encoded-32-byte-public-key>"
.\delivery\build-standalone-packages.ps1 -Version 0.1.19 -Product xiaomi -AllowUnsignedCandidate
```

默认只构建 MiVibe Remote；生成的可执行文件和安装器分别为
`MiVibeRemote.exe` 与 `MiVibeRemoteSetup-0.1.19.exe`。`-Product` 参数仍可显式选择
保留的其他上游独立产品，但它们不属于 MiVibe Remote 交付物。
构建同时生成对应的 `.exe.sha256` 校验文件。

两个更新变量必须同时提供。构建脚本只会把 HTTPS appcast 地址和公开 Ed25519
验签公钥写入生成资源；若两者均未提供，安装包仍能构建和运行，但在线更新会安全禁用。
任何更新签名私钥、GitHub Token 或会员凭证都不得传给此构建脚本或写入安装包。

Windows appcast 的安装包 enclosure 应标记 `sparkle:os="windows-x64"`，携带
`sparkle:edSignature`，并使用以下安装参数：

```text
/SILENT /SP- /NOICONS /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /UPDATED
```

`/UPDATED` 让固定 AppId 的 Inno Setup 执行原位覆盖升级、保留用户此前选择的任务，
跳过首次安装的 VB-CABLE 检查，并在更新完成后重新启动 MiVibe Remote。签名私钥只在
隔离的发布环境中用于签署最终安装包；客户端只持有公钥。

构建会校验并获取 Frida Gadget 和固定版本 WinSparkle。VB-CABLE 不嵌入安装包；用户从 MiVibe 主窗口主动
打开语音驱动助手后，助手从 VB-Audio 官方地址下载、校验并启动官方安装程序。
上游说明见 [UPSTREAM_README.md](UPSTREAM_README.md)，来源与许可证见仓库根目录
`UPSTREAM.md`、本目录 `THIRD_PARTY_NOTICES.md` 和 `LICENSE`。
