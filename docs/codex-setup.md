# Codex 端到端设置

MiVibe Remote 不内置第二套语音识别。它复用 Codex 已有的全局听写能力：

- Codex 提供“按住听写快捷键”：在桌面任意位置按住即可听写到当前光标位置；
- Codex 提供“开关听写快捷键”：按一次开始，再按一次停止；
- Codex 可以选择具体麦克风输入设备；
- macOS 和 Windows 版本使用同一套 Codex 命令定义。

这样 RC003 只负责采集音频和发送物理按键，转写仍由 Codex 完成。

## macOS

1. 安装并运行 MiVibe Remote。
2. MiVibe Remote 会自动选择 `MiRemoteV 2ch` 虚拟麦克风。
3. 在 Codex 的“设置 → 语音”中选择同一个 `MiRemoteV 2ch` 作为麦克风输入。
4. 确认 Codex 的“设置 → 键盘快捷键 → 按住听写”是 `Control + Shift + D`。
5. 全新安装已默认启用 Codex 映射；如果之前改过按键，可在“按键”页面点击“Codex 预设”恢复。

MiVibe Remote 会把 RC003 语音键的按下与松开同步为 Codex 的
`Control + Shift + D` 长按听写：

```text
按住遥控器语音键
  ├─ Control + Shift + D down → Codex 开始听写
  └─ RC003 ATVV 音频 → MiRemoteV 2ch → Codex

松开遥控器语音键
  └─ Control + Shift + D up → Codex 停止并转写
```

## Windows

1. 安装 MiVibe Remote Windows 包；首次安装会从 VB-Audio 官方地址下载并配置 VB-CABLE。
2. 在 Codex 的“设置 → 语音”中选择 `CABLE Output` 作为麦克风输入。
3. 在 Codex 的“设置 → 键盘快捷键”中，把“按住听写快捷键”设为右 Alt。
4. 在 MiVibe Remote 设置中：
   - 全新安装无需切换预设；如果之前改过按键，点击“Codex 预设”恢复；
   - 确认语音键为右 Alt；
   - 触发方式选择“按住型”；
   - 保存并应用。

Windows 桥会在 RC003 语音会话期间持续按住右 Alt，并把 ATVV 音频解码、重采样后写入
VB-CABLE。

## 默认 Codex 按键

| 遥控器按键 | 动作 |
| --- | --- |
| 电源 | 打开并激活 Codex |
| 语音 | 按住听写 |
| 确定 | Return / 发送 |
| 方向 | 浏览与移动光标 |
| 返回 | 退格 |
| 菜单 | Escape |
| 主页 | 显示桌面 |
| 音量 | 系统音量 |

## 唤醒电脑

RC003 同时是系统配对的 HID 设备。能否从睡眠中唤醒电脑由操作系统、蓝牙控制器和电源设置
决定，不是 MiVibe Remote 在应用退出/电脑睡眠后能够接管的功能。实际产品应把“唤醒电脑”
视为硬件/系统能力，把“唤醒后打开 Codex”视为 MiVibe Remote 的电源键动作。
