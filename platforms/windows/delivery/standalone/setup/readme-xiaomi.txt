MiVibe Remote v0.1.20

把小米蓝牙遥控器 2 变成 Windows 上的 Vibe Coding 控制器。

包含：13 个正面按键映射、长按连续动作、蓝牙语音桥接、设置界面和开机启动。
不包含：任何输入法、语音识别服务、T1 或 V60 程序。

在线更新：程序启动后按每天一次的周期静默检查已签名的新版本；只有发现新版时才提示。也可以在主窗口或托盘点击“检查更新”。下载完成后会校验 Ed25519 签名，再原位覆盖升级并重新打开程序。在线更新不会重复运行 VB-CABLE 驱动安装流程。

小米遥控器传来的是蓝牙压缩语音，不是 Windows 原生麦克风，因此语音必须使用 VB-CABLE。MiVibe 不再自行模拟安装驱动：请在主窗口点击“安装/修复语音驱动”，程序会从 VB-Audio 官方地址下载固定版本、校验 SHA-256 与官方签名，然后打开官方 VBCABLE_Setup_x64.exe。请在官方窗口点击 Install，并重启 Windows。普通按键和设置页面不依赖语音驱动，VB-CABLE 尚未安装时也应保持可用。

VB-CABLE 由 VB-Audio（https://vb-audio.com/Cable/）提供，采用 Donationware（捐赠软件）模式。VB-CABLE 不是本项目创作的软件，其权利、使用许可和服务由 VB-Audio 负责；专业、批量、集成或再分发使用请按 VB-Audio 当前许可另行确认。

首次使用前，请先在 Windows 蓝牙设置里配对遥控器。RC001、MI RC 以及带有 Google ATVV 语音服务的兼容小米蓝牙遥控器会自动发现；只有经过验证的 RC003 硬件才启用可选的高级 HID 兼容层。

推荐设置：
1. 打开“按键与语音设置”。
2. 全新安装默认启用“Codex 预设”；可切换“WorkBuddy 预设”或“微信预设”，再点击“保存并应用”。微信语音键会按住 Ctrl+Win，松开后转成文字。
3. 电源键会打开当前预设应用，确定键发送，方向键导航，返回键退格，菜单键为 Escape。
4. Codex 预设把语音键设为“按住型”右 Alt；请在 Codex 中把“按住即可听写”的全局快捷键设为右 Alt，并把麦克风输入选择为 `CABLE Output`。
5. WorkBuddy 预设把语音键设为“开关型”Ctrl+D；若 WorkBuddy 没有单独的麦克风选择项，请在 Windows 声音设置中把输入设备切换为 `CABLE Output`。

MiVibe 不会主动修改 Windows 的系统默认麦克风或麦克风隐私权限；官方驱动安装期间如果 Windows 自动切换默认设备，助手会尝试恢复安装前的麦克风。`CABLE Output` 只需在 Codex 中单独选择。
