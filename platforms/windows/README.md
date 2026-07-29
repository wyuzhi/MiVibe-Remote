# MiVibe Remote for Windows

本目录基于 `xxb26553663-star/remote-bridge-hub v1.0.0` 的 Xiaomi
独立应用，保留其 WinRT GATT、ATVV、Windows 输入注入、VB-CABLE、托盘程序和安装器。

MiVibe Remote 的增量：

- 独立产品名称和原创 `.ico` 图标；
- 新增“Vibe Coding 预设”：
  - 电源键：从 Windows 开始菜单查找并打开 Codex；
  - 确定键：Enter / 发送；
  - 方向键：导航；
  - 返回键：退格；
  - 菜单键：Escape；
  - 语音键：保留可自定义的系统/输入法语音快捷键；
- Xiaomi 动作执行器复用上游已有的 `command` 动作能力；
- 普通按键支持单击自定义，返回键和音量键保留上游长按重复；
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
.\delivery\build-standalone-packages.ps1 -Version 0.1.3 -Product xiaomi -AllowUnsignedCandidate
```

默认只构建 MiVibe Remote；生成的可执行文件和安装器分别为
`MiVibeRemote.exe` 与 `MiVibeRemoteSetup-0.1.3.exe`。`-Product` 参数仍可显式选择
保留的其他上游独立产品，但它们不属于 MiVibe Remote 交付物。
构建同时生成对应的 `.exe.sha256` 校验文件。

构建会校验并获取 Frida Gadget。VB-CABLE 不嵌入安装包，而是在用户首次安装时从
VB-Audio 官方地址下载并校验；两者继续适用各自许可证。
上游说明见 [UPSTREAM_README.md](UPSTREAM_README.md)，来源与许可证见仓库根目录
`UPSTREAM.md`、本目录 `THIRD_PARTY_NOTICES.md` 和 `LICENSE`。
