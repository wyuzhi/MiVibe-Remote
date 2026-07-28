# MiVibe Remote

<p align="center">
  <img src="platforms/macos/Resources/AppIcon.png" width="144" alt="MiVibe Remote">
</p>

<p align="center">
  把小米蓝牙语音遥控器 2 Pro（RC003）变成 macOS 和 Windows 上的 Vibe Coding 控制器。
</p>

<p align="center">
  <a href="https://github.com/wyuzhi/MiVibe-Remote/releases/latest">下载安装包</a>
  ·
  <a href="docs/codex-setup.md">Codex 设置</a>
  ·
  <a href="docs/reference-audit.md">上游复用与技术说明</a>
</p>

## 它能做什么

MiVibe Remote 复用遥控器内置麦克风和实体按键，让你不必一直坐在键盘前：

- 电源键：打开或切换到 Codex，也可以改成 Cursor、Claude、Xcode 等应用；
- 麦克风键：按住开始 Codex 听写，松开停止并转写；
- 中间确认键：发送当前输入；
- 返回键：删除光标前的文字；
- 方向键：移动光标或浏览内容；
- 其他普通按键：可以自由映射为快捷键、系统动作或应用启动动作。

macOS 还支持单击、双击和长按动作；Windows 支持普通单击以及返回键、音量键的长按重复。

## 下载

前往 [GitHub Releases](https://github.com/wyuzhi/MiVibe-Remote/releases/latest) 下载：

- macOS：`MiVibe-Remote-0.1.1.dmg`
- Windows：`MiVibeRemoteSetup-0.1.1.exe`
- 每个安装包旁边都有对应的 `.sha256` 校验文件

> 当前 macOS 首发包使用 ad-hoc 签名，尚未进行 Apple 公证。请只安装本仓库 Release
> 发布的文件。Windows 首发包同样是未进行商业代码签名的候选版本。

## 支持的硬件

- 小米蓝牙语音遥控器 2 Pro / RC003
- USB Vendor ID：`0x2717`
- USB Product ID：`0x32B8`

使用前先在操作系统蓝牙设置中完成遥控器配对。

## macOS 安装

要求：Apple Silicon Mac、macOS 26 或更高版本。

1. 下载并打开 `MiVibe-Remote-0.1.1.dmg`。
2. 双击“安装 MiVibe Remote.pkg”。
3. 按系统提示输入管理员密码；安装器会同时安装应用和 `MiRemoteV 2ch` 虚拟麦克风。
4. 首次启动后，在“权限”页面依次允许蓝牙、输入监控和辅助功能。
5. 在 Codex 中选择 `MiRemoteV 2ch` 作为麦克风。
6. 确认 Codex 的“按住听写”快捷键为 `Control + Shift + D`。

MiVibe Remote 会自动选择正确的虚拟麦克风。正常使用不需要理解或修改“音频路由”。

## Windows 安装

要求：Windows 10/11，首次安装需要联网。

1. 下载并运行 `MiVibeRemoteSetup-0.1.1.exe`。
2. 安装器会从 VB-Audio 官方地址下载并验证 VB-CABLE，然后完成配置。
3. 在 Codex 中选择 `CABLE Output` 作为麦克风。
4. 确认 Codex 的“按住听写”快捷键为右 Alt。

安装器不会擅自修改 Windows 的系统默认麦克风或全局麦克风隐私设置。

## 默认按键

| 遥控器按键 | 默认动作 |
| --- | --- |
| 电源 | 打开/切换到 Codex |
| 麦克风 | 按住听写，松开停止 |
| 确定 | Return / 发送 |
| 返回 | Delete / 退格 |
| 方向 | 移动光标 |
| 主页 | 显示桌面 |
| 菜单 | Escape |
| TV | 应用切换 |
| 音量 | 系统音量 |

在“按键”页面可以修改普通按键；点击“Vibe Coding 预设”可恢复上表。

## 工作原理

```text
RC003 麦克风
  → Bluetooth LE ATVV / IMA ADPCM
  → MiVibe Remote 解码
  → 虚拟麦克风
  → Codex 听写

RC003 实体按键
  → HID 报告
  → MiVibe Remote 映射
  → Codex / 当前应用
```

本项目不重复实现已经验证的硬件协议：

- macOS 基于 [HD838A/remote-mic-app](https://github.com/HD838A/remote-mic-app) `v1.2.3`；
- Windows 基于 [xxb26553663-star/remote-bridge-hub](https://github.com/xxb26553663-star/remote-bridge-hub) `v1.0.0` 的 Xiaomi 桥；
- [VincentKingHsu/MiRemoteVoice](https://github.com/VincentKingHsu/MiRemoteVoice) `v1.0.0-beta.2` 作为 ATVV 协议实现参考。

精确版本、提交、许可与复用边界见 [UPSTREAM.md](UPSTREAM.md) 和
[docs/reference-audit.md](docs/reference-audit.md)。

## 隐私

- 不上传、保存或转写语音内容；
- 语音只在本机从遥控器传到用户选择的听写应用；
- 日志不记录语音内容、蓝牙地址或外设 UUID；
- macOS 安装器不会修改系统默认输入/输出设备；
- Windows 安装器不会修改系统默认麦克风或全局麦克风隐私设置。

## 从源码构建

本机便携检查：

```bash
./scripts/test-portable.sh
```

macOS：

```bash
cd platforms/macos
./scripts/test.sh
./scripts/build-dmg.sh
./scripts/verify-dmg.sh
```

Windows 请在 Windows PowerShell 中运行：

```powershell
cd platforms/windows
.\delivery\build-standalone-packages.ps1 `
  -Version 0.1.1 `
  -Product xiaomi `
  -AllowUnsignedCandidate
```

根目录的 GitHub Actions 会在原生 macOS 和 Windows runner 上测试并构建两个安装包。

## 许可证

MiVibe Remote 使用 [GPL-3.0-only](LICENSE) 许可证。上游版权、第三方组件许可和未纳入项目的
专有素材说明保留在各平台目录及 `THIRD_PARTY_NOTICES.md` 中。
