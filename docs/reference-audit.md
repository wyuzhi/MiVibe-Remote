# 小米遥控器 Vibe Coding 工具：参考项目审计

审计日期：2026-07-28

## 审计对象

| 项目 | 审计版本 | 许可证 | 定位 |
| --- | --- | --- | --- |
| `VincentKingHsu/MiRemoteVoice` | `v1.0.0-beta.2` / `2c374d9` | App 为 MIT；BlackHole 派生驱动为 GPL-3.0 | macOS 最小 BLE/ATVV 语音桥 |
| `HD838A/remote-mic-app` | `v1.2.3` / `32edebd` | GPL-3.0-only；Logo 另行授权 | 完整 macOS 菜单栏产品 |
| `xxb26553663-star/remote-bridge-hub` | `v1.0.0`，审计其被引用提交 `8a93f32` | GPL-3.0 | `remote-mic-app` 的 Windows 上游，已有 RC003 安装包 |

第三个项目不是另找的替代方案，而是 `remote-mic-app` 在版权和第三方声明中明确列出的 Windows 上游。

## 已经解决的问题

### 共同的硬件协议

- 目标硬件：Xiaomi RC003，Vendor ID `0x2717`，Product ID `0x32B8`。
- Google ATVV 服务：`AB5E0001-5A21-4F05-BC7D-AF01F617B664`。
- 三个特征：
  - Host 写命令：`AB5E0002-5A21-4F05-BC7D-AF01F617B664`
  - 遥控器语音数据：`AB5E0003-5A21-4F05-BC7D-AF01F617B664`
  - 控制事件：`AB5E0004-5A21-4F05-BC7D-AF01F617B664`
- 已实现 capabilities、mic open/close、keep-alive、audio sync、16 kHz IMA/DVI ADPCM 解码和 PCM 后处理。
- 普通按键 HID usage 已知，包括方向、确定、返回、主页、菜单、TV、电源和音量。

这些都应直接复用，不重新研究协议。

### macOS：`remote-mic-app` 已有完整产品能力

- CoreBluetooth 自动发现、缓存外设身份、断线重连和初始化超时。
- IOHID 读取 RC003 原始报告；独占失败时退回兼容监听并抑制重复的系统事件。
- 单击、双击、长按和长按重复。
- 任意快捷键录制、系统音量/媒体动作、打开 Codex 等常用 App。
- 语音键按下/释放会发送 Codex 的 `Control + Shift + D` 长按听写快捷键，并与 ATVV 会话同步。
- CoreAudio 输出到 BlackHole 或 `MiRemoteV 2ch`；启用临时输入切换时，仅在遥控器语音会话期间把虚拟麦克风设为系统默认输入，结束尾音传输后恢复用户此前选择的设备，不修改系统默认输出。
- SwiftUI 设置页、菜单栏、权限引导、日志、测试音、驱动 PKG/DMG 和测试。
- 当前版本含 61 项 Swift 测试及 36 项自检。

结论：macOS 端不应重写。直接基于该项目做增量。

### Windows：`remote-bridge-hub` 已有完整硬件桥

- WinRT GATT 自动发现已配对 RC003，并实现完整 ATVV 会话。
- 解码 16 kHz ADPCM，重采样为 48 kHz PCM，写入 VB-CABLE 播放端；应用从 `CABLE Output` 录音。
- Windows 低级键盘 Hook、Raw Input 和 HID 报告监听。
- 返回键因普通 Windows 输入链路丢报告，已有基于 Frida Gadget 的兼容层。
- 按键映射、快捷键/单键/文本动作、长按重复、托盘应用、设置 UI。
- PyInstaller、Inno Setup、VB-CABLE 获取与哈希校验、安装器和自动测试。
- 官方已有 `XiaomiRemoteBridgeSetup-1.0.0.exe`。

结论：Windows 端同样不应从零实现。直接基于 Xiaomi Remote Bridge 增量开发。

## 当前机器上的原版验证

- macOS 26.5.2，Apple Silicon。
- 系统已连接“小米蓝牙语音遥控器”，电量 100%。
- 系统识别 VID/PID 为 `0x2717/0x32B8`。
- 临时启动 `remote-mic-app v1.2.3` 官方 App 后：
  - 进程正常运行；
  - 成功命中一个 RC003 HID 设备；
  - 语音键 `Control + Shift + D` 按住听写成功；
  - 设置页正常显示；
  - 唤醒遥控器后 CoreBluetooth 已连接“小米蓝牙语音遥控器”；
  - 语音状态已进入“等待麦克风键”；
  - 当前没有 BlackHole 或 `MiRemoteV 2ch`，所以语音尚无输出目标。
- 本机 Command Line Tools 的 Swift 是 5.8.1，低于 `remote-mic-app` 要求的 Swift 6.2；原版发布二进制可运行，但源码构建前需要更新 Xcode/Command Line Tools。

### 原项目测试结果

- `MiRemoteVoice` 的 3 项 ATVV 音频同步回归自检全部通过。
- `remote-mic-app` 的官方 `v1.2.3` 发布二进制签名、架构和最低系统版本检查正常；源码测试被本机不完整/过旧的 Xcode Command Line Tools 阻止，并非测试失败。
- `remote-bridge-hub` 在 macOS 临时 Python 3.12 环境中：
  - 21 项与平台无关的配置、打包边界和入口测试通过；
  - 2 个测试模块按设计依赖 Windows 的 `winreg`/Raw Input，需在 Windows CI 或真实 Windows 机器运行。

## 真正需要新增的功能

现有项目已经覆盖约 80% 的硬件和系统工作。Vibe Coding 产品层只需要补以下增量：

1. Codex 工作流预设：
   - 电源键激活或打开 Codex；
   - 语音键按住时触发 Codex 的全局“按住即可听写”；
   - 松开语音键即结束听写；
   - 确定键发送 Return。
2. 应用工作流预设：
   - Codex 预设使用按住型语音快捷键；
   - WorkBuddy 预设使用开关型语音快捷键；
   - Cursor、Claude Code、VS Code、终端等仍可通过自定义按键打开。
   - 用户仍可覆盖每个按键。
3. Windows 的“打开应用”动作：
   - Windows 上游底层共享 mapper 已支持 command/process；
   - Xiaomi 设置页当前只暴露 hotkey、key、text，需要把现有能力接入 Xiaomi 映射。
4. 跨平台一致的配置概念和界面文案：
   - 不强求相同运行时；
   - macOS 保留 Swift/AppKit/CoreBluetooth/CoreAudio；
   - Windows 保留 Python/WinRT/Raw Input/VB-CABLE；
   - 共享动作 schema、预设和用户文档。
5. 不内置重复的语音识别：
   - Codex 桌面端已经提供全局按住听写、全局开关听写和麦克风设备选择；
   - 第一版只负责把遥控器音频桥接成虚拟麦克风，并生成与 ATVV 会话同步的快捷键按下/释放；
   - 离线 Whisper 只作为未来可选能力，不进入第一版。

## 推荐主线

采用“一个产品、两个经过验证的原生宿主”，而不是为了单一技术栈重写硬件层：

```text
MiVibe Remote
├── macOS：fork remote-mic-app
│   ├── 复用 BLE / ATVV / HID / CoreAudio / 驱动 / UI
│   └── 新增 Codex / WorkBuddy 启动动作、预设和引导
└── Windows：fork remote-bridge-hub 的 Xiaomi 独立包
    ├── 复用 WinRT / ATVV / HID / VB-CABLE / 安装器
    └── 新增打开 Codex / WorkBuddy、双预设和引导
```

这样能最大化复用已验证代码，也保留各平台处理蓝牙、HID、音频驱动和权限的最佳实现。

## 许可证决策

- 因为完整 macOS 项目和 Windows 上游均为 GPL-3.0，产品源码应继续使用 GPL-3.0。
- 可以复用 `MiRemoteVoice` 的 MIT 协议实现，但不能借此把基于另外两个 GPL 项目的完整产品改成闭源。
- 不复用 `remote-mic-app` 的专有 Logo；新产品需要自己的图标和品牌资产。
- macOS 虚拟音频驱动继续遵守 BlackHole GPL。
- Windows VB-CABLE 保留 VB-Audio 来源、Donationware 提示和许可约束；公开安装包不内嵌驱动，首次安装从官方地址下载并校验。

## 下一步验证顺序

1. 更新本机 Command Line Tools，运行 macOS 全部 Swift 测试。
2. 构建并安装 `MiRemoteV 2ch` 与 MiVibe Remote 候选包。
3. 验证遥控器语音 PCM 经虚拟麦克风进入 Codex。
4. 验证电源键打开 Codex、按住听写、松开转写和确定键发送的完整流程。
5. 在真实 Windows 机器或 Windows CI 构建、安装和验证对应流程。
