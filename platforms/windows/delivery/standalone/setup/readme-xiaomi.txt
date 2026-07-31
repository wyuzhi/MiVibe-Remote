MiVibe Remote v0.1.4

把小米蓝牙遥控器 2 变成 Windows 上的 Vibe Coding 控制器。

包含：13 个正面按键映射、长按连续动作、蓝牙语音桥接、设置界面和开机启动。
不包含：任何输入法、语音识别服务、T1 或 V60 程序。

小米遥控器传来的是蓝牙压缩语音，不是 Windows 原生麦克风，因此语音必须使用 VB-CABLE。首次安装时，安装器会从 VB-Audio 官方地址下载固定版本、校验 SHA-256 与官方签名后自动安装；MiVibe 安装包本身不再分发该驱动。首次安装需要联网，并可能出现一次 Windows 管理员确认；若 Windows 要求重启，请重启一次。普通按键不受语音环境影响。

VB-CABLE 由 VB-Audio（https://vb-audio.com/Cable/）提供，采用 Donationware（捐赠软件）模式。VB-CABLE 不是本项目创作的软件，其权利、使用许可和服务由 VB-Audio 负责；专业、批量、集成或再分发使用请按 VB-Audio 当前许可另行确认。

首次使用前，请先在 Windows 蓝牙设置里配对遥控器。

推荐设置：
1. 打开“按键与语音设置”。
2. 全新安装默认启用“Codex 预设”；需要操作 WorkBuddy 时点击“WorkBuddy 预设”，再点击“保存并应用”。
3. 电源键会打开当前预设应用，确定键发送，方向键导航，返回键退格，菜单键为 Escape。
4. Codex 预设把语音键设为“按住型”右 Alt；请在 Codex 中把“按住即可听写”的全局快捷键设为右 Alt，并把麦克风输入选择为 `CABLE Output`。
5. WorkBuddy 预设把语音键设为“开关型”Ctrl+D；若 WorkBuddy 没有单独的麦克风选择项，请在 Windows 声音设置中把输入设备切换为 `CABLE Output`。

安装器不会修改 Windows 的系统默认麦克风，也不会改写麦克风隐私权限；`CABLE Output` 只需在 Codex 中单独选择。
