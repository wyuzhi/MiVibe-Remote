# 无线麦技术文档

> 上游历史文档：以下内容随 `remote-mic-app v1.2.3` 保留，用于追溯原始实现。MiVibe Remote 的当前名称、资产、默认映射和打包文件以本目录 `README.md`、根目录 `UPSTREAM.md` 及实际脚本为准。

本文面向开发、审计和发布人员，描述 `1.2.3 (20)` 对应代码的实现、构建和发布约束。普通用户请阅读 [README.md](README.md)。

## 支持范围

- 运行系统：macOS 15 或更高版本；
- 架构：Apple Silicon `arm64`；
- 目标遥控器：小米蓝牙遥控器 2；本机 macOS 内部型号显示为 RC001；
- HID 标识：Vendor ID `0x2717`、Product ID `0x32B8`；
- Swift 工具链：Swift 6.2，源码以 Swift 5 语言模式编译；
- 发布签名：应用默认使用带固定 designated requirement 的 ad-hoc 签名；仅在显式传入有效签名身份时使用该身份。驱动使用 ad-hoc 签名，PKG 未使用 Installer 证书签名，当前未公证。

`Package.swift`、`Resources/Info.plist`、构建脚本和验证脚本都把最低系统版本固定为 macOS 15，并验证发布二进制只有 `arm64` 架构。macOS 26 使用原生 Liquid Glass；macOS 15–15.x 通过统一兼容层使用系统材质、描边和标准按钮样式。

## 模块结构

| 模块 | 主要职责 |
| --- | --- |
| `RemoteMicApp.swift` | AppKit 生命周期、菜单栏图标、主应用菜单、右键菜单、关于与版本菜单项、Sparkle 更新入口 |
| `AppUpdater.swift` | 安全校验更新配置、持有 Sparkle updater controller、定时检查和用户主动检查 |
| `SettingsView.swift` | 自适应设置界面、状态展示、音频选择、按键映射和权限入口 |
| `CompatibilityStyles.swift` | macOS 26 Liquid Glass 与 macOS 15 系统材质降级样式 |
| `BridgeAppModel.swift` | 蓝牙、音频、HID、Codex / WorkBuddy / 微信语音和 UI 状态的协调层 |
| `XiaomiBluetoothBridge.swift` | CoreBluetooth 扫描、连接、能力协商、语音会话和自动重连 |
| `ATVVProtocol.swift` | ATVV 命令、能力解析、IMA/DVI ADPCM 解码、帧累积与 PCM 后处理 |
| `AudioOutput.swift` | CoreAudio 输出设备枚举和 16 kHz 单声道语音写入 |
| `HIDRemoteMonitor.swift` | 小米遥控器原始 HID 报告、安全接管、按键重复和活动状态 |
| `RemoteKeyHardwareSuppressor.swift` | 只匹配硬件 ID `0x2717:0x32B8`，在设备层屏蔽原始系统按键，并在退出时恢复 |
| `KeyboardInjector.swift` | 键盘、媒体键和预置应用启动动作 |
| `AppSettings.swift` | 音频设备、增益、HID 开关、按键映射和外设标识持久化 |

## 蓝牙与 ATVV

应用只接受以下任一条件命中的候选设备：

- 系统名称去除首尾空白后等于 `MI RC`、`Xiaomi Bluetooth Remote 2 Pro` 或“小米蓝牙语音遥控器”；英文名称比较不区分大小写；
- 广播中包含 ATVV service UUID。

应用不会对所有名称中带有“小米”的蓝牙设备做模糊匹配。连接成功后会保存 macOS 提供的外设 UUID，以便下次优先恢复；初始化或连接失败后清除失效缓存，并在 3 秒后重新扫描。用户主动重新连接时使用约 0.1 秒延迟。

ATVV 通道为：

| 用途 | UUID |
| --- | --- |
| Service | `AB5E0001-5A21-4F05-BC7D-AF01F617B664` |
| Transmit | `AB5E0002-5A21-4F05-BC7D-AF01F617B664` |
| Audio | `AB5E0003-5A21-4F05-BC7D-AF01F617B664` |
| Control | `AB5E0004-5A21-4F05-BC7D-AF01F617B664` |

连接后必须完成特征发现、Audio/Control 通知订阅和能力确认，才会进入 ready 状态。初始化超时为 8 秒。当前只接受 16 kHz 编码；设备若只提供或切换到 8 kHz，连接会失败关闭并重新发现。

语音数据按遥控器声明的帧长累积，使用高半字节优先的 IMA/DVI ADPCM 顺序解码。同步包可重置 predictor 和 step index。解码后的 PCM 经过三点平滑与 `-24...24 dB` 安全限幅增益处理；设置界面当前允许用户选择 `0...24 dB`。

## 音频输出

`StableVirtualAudioOutput` 使用 CoreAudio `AudioDeviceIOProc` 直接打开 `MiRemoteV 2ch`，避免默认输入为虚拟麦克风、默认输出为蓝牙耳机时由 `AVAudioEngine` 触发系统聚合设备和路由重建。MiVibe 运行期间系统默认输入保持为 `MiRemoteV 2ch`，但默认空闲状态不创建 IOProc。遥控器语音开始时按需打开虚拟通道，使用短暂预缓存补发通道启动期间收到的 16 kHz PCM；尾音实际消费完成后关闭通道。整个按键过程不修改 CoreAudio 默认输入，系统默认输出始终不变。只有用户主动开启电脑麦克风透传时，才会保持虚拟通道并通过 `AVCaptureSession` 明确采集 MacBook 内置麦克风。退出应用时恢复启动前的输入设备。

测试音同样只在内存中生成。只有音频设备已经配置、小米遥控器未在传输语音且没有其他测试音播放时才允许发送；真实语音开始或设备重新配置时会取消测试音，避免阻塞语音缓冲。

## 豆包兼容驱动

`scripts/build-doubao-driver.sh` 固定从 BlackHole `v0.7.1`、提交 `e2b22aaaba4e507a097131704bf96dabc004d9cf` 构建 `MiRemoteV2ch.driver`。项目补丁只把实际 Audio Device transport 报告为 USB，并使用独立的 bundle identifier、设备 UID 和 CFPlugIn factory UUID。

发布设备名为 `MiRemoteV 2ch`，UID 为 `MiRemoteV2ch_UID`。它与 `BlackHole2ch.driver` 并存，不覆盖或删除 BlackHole。

安装 PKG 的 payload 包含：

- `/Applications/无线麦.app`；
- `/Library/Audio/Plug-Ins/HAL/MiRemoteV2ch.driver`。

安装脚本校验架构、最低系统版本和签名，重启 CoreAudio，并为当前桌面用户启动应用。卸载 PKG 只删除 `MiRemoteV2ch.driver` 并重启 CoreAudio，不删除应用或 BlackHole。

## HID 与按键映射

自定义按键映射默认关闭。启用后必须同时具备输入监控和辅助功能权限，否则 HID 处理失败关闭。

`HIDRemoteMonitor` 首先尝试独占打开小米遥控器。若 macOS 拒绝独占，`RemoteKeyHardwareSuppressor` 会调用系统自带 `hidutil` 设置设备级 `UserKeyMapping`，只匹配 Vendor ID `0x2717`、Product ID `0x32B8` 的目标设备。方向、Return 和音量等标准动作由设备直接交给 macOS，获得原生的快速连点和长按重复；返回键使用非标准 usage `0xF1`，不会产生 macOS 键盘事件，必须在原始按下报告到达时由应用把退格事件直接投递给当前前台应用进程，避开全局 CGEvent 队列。打开应用、切换应用、自定义快捷键和带双击/长按配置的按键也由应用执行。MacBook 自带键盘和其他键盘不会被修改。

设备级映射会保留原有映射备份。关闭自定义映射或正常退出应用时立即恢复；应用异常退出后，下次启动会继续使用持久化备份，避免把应用自己的规则误当成用户原始设置。若独占和设备级映射都失败，应用会停止发送自定义动作，让 macOS 原生处理按键，避免重复输入。

默认映射为：

| 遥控器按键 | 默认动作 |
| --- | --- |
| 方向 / 确定 | 方向键 / Return |
| 返回 | Delete（退格） |
| 主页 | 显示桌面（Fn-F11） |
| 菜单 | macOS 上下文菜单键 |
| TV | Command-Tab |
| 电源 | Escape |
| 音量 + / - | 系统音量增减 |

用户还可以选择系统静音、播放/暂停，或打开 Codex、WorkBuddy、Claude、cmux、微信、Cursor、Xcode、Slack、企业微信、网易云音乐、Chrome、Safari 和 Zed。选择器只显示当前已安装的预置应用，但会保留后来被卸载的已有映射；应用启动动作不会重复创建实例。

方向、返回和音量等标准动作由 macOS 原生处理长按重复；仅在独占模式下由应用生成重复事件。打开应用动作不重复。普通实体按键活动状态会发布到 SwiftUI，用于高亮遥控器示意图和定位映射行。

## 语音键与应用预设

Codex 预设在小米遥控器开始发送 ATVV 音频时按下 `⌃⇧D`。松键后先接收 STOP 通知之后到达的 BLE 尾包，再让虚拟麦克风播放完尾音和短静音，并给 Codex 的输入缓冲留出提交窗口，最后才释放快捷键。WorkBuddy 预设在开始和停止边沿各点按一次 `⌘D`。微信 4.x 的输入栏明确使用“语音输入文字（按住 Fn）”，所以微信预设在遥控器语音开始时发送 Fn flags-changed 按下状态，停止时释放 Fn，把微信原生的按住型录音与遥控器完全对齐。设备级按键屏蔽同时覆盖遥控器语音键对应的 F5 usage，避免 F5 原生动作进入前台应用，但不会影响遥控器固件启动 ATVV 音频。

启用自定义按键映射时应用设备级屏蔽；语音流开始和结束通过 `VoiceFunctionKeyLatch` 保证每个会话只处理一次开始和停止边沿。关闭自定义映射或退出应用时恢复启动前的目标按键映射，同时保留运行期间其他来源的映射变化。

## 菜单栏与窗口

应用以 `LSUIElement` accessory 模式运行，不显示 Dock 图标。状态栏按钮同时接收左右鼠标抬起事件：

- 左键：创建或置前 800×650 的可缩放设置窗口；
- 右键：显示连接、音频、HID 状态，以及重新连接、打开设置、日志、关于、版本号、检查更新、GitHub 和退出菜单。

设置窗口包含“连接”“按键”“权限”三个页面。macOS 26 使用原生 `glassEffect` 和 glass button style；macOS 15 使用 `regularMaterial`、标准按钮与轻量描边，并同样跟随系统浅色、深色、降低透明度与增强对比度设置。

## 数据与日志

- 语音 PCM 只存在于进程内存和用户选择的 CoreAudio 输出链路中，不落盘、不上传；
- 测试音只在内存生成；
- 持久化内容包括增益、音频设备 UID、自定义映射开关、按键绑定和 macOS 外设 UUID；
- 日志位于 `~/Library/Logs/RemoteMic/runtime.log`，记录状态和错误，不记录语音内容、蓝牙地址或外设 UUID。

## 构建与测试

开发构建：

```bash
./scripts/test.sh
xcrun swift test
./scripts/build-app.sh
./scripts/verify-app.sh
```

`scripts/test.sh` 运行协议/策略自检并编译完整应用。Swift Testing 覆盖 ATVV、蓝牙生命周期、音频设备策略、按键、权限、小米遥控器设备级屏蔽、Codex / WorkBuddy / 微信语音触发和测试音。

构建并启动应用：

```bash
./script/build_and_run.sh
./script/build_and_run.sh --verify
```

`--verify` 会构建、启动并确认 `RemoteMic` 进程存在；它不是遥控器或真实语音链路的硬件验收。

## 发布产物

完整发布构建：

```bash
./scripts/build-dmg.sh
./scripts/verify-dmg.sh
```

`build-dmg.sh` 会依次构建并验证应用、驱动、安装 PKG 和卸载 PKG，生成：

- `dist/无线麦.app`；
- `dist/MiRemoteV2ch.driver`；
- `dist/安装无线麦.pkg`；
- `dist/卸载无线麦.pkg`；
- `dist/Remote-Mic-1.2.3.dmg`；
- `dist/Remote-Mic-1.2.3.dmg.sha256`。

DMG 根目录严格只有四项：

- `安装无线麦.pkg`；
- `卸载无线麦.pkg`；
- `无线麦.app`；
- 指向 `/Applications` 的 `Applications` 入口。

`verify-dmg.sh` 校验 SHA-256、HFS+ 镜像、根目录清单、应用 bundle 内容、PKG payload、版本号、`arm64` 架构、macOS 15 最低版本、有效代码签名和本地路径泄漏。

Sparkle `2.9.4` 作为精确版本 SwiftPM 依赖嵌入应用。构建脚本只接受
`MIVIBE_APPCAST_URL` 和 `MIVIBE_UPDATE_ED25519_PUBLIC_KEY`，并在两者同时有效时把更新源与
Ed25519 公钥注入最终应用的 `Info.plist`。源码不含生产 feed、公钥占位符、访问令牌或私钥；
私钥只存储在发布环境的受限安全存储中，不进入项目、应用或 Release。

发布版默认每 86400 秒定期检查一次，也提供应用菜单和菜单栏菜单的“检查更新…”入口。
`SUAllowsAutomaticUpdates=false` 与 `SUAutomaticallyUpdate=false` 禁止后台静默下载和安装，
新版本必须由用户确认。构建未注入完整配置时不会启动 Sparkle updater，也不会访问网络，菜单明确
显示“检查更新…（自动更新未配置）”。Sparkle 只更新应用 bundle，不安装或替换兼容麦克风驱动。

SwiftPM CLI 不会替手工组装的 `.app` 完成 Embed & Sign，因此 `build-app.sh` 明确复制
`Sparkle.framework` 到 `Contents/Frameworks`，为主程序添加
`@executable_path/../Frameworks` rpath，并依次签名 Installer XPC、Downloader XPC、
Autoupdate、Updater、framework 和主应用。按 Sparkle 2.9.4 的官方手工签名要求，仅
Downloader XPC 使用 `--preserve-metadata=entitlements`；其他组件不得继承上游签名的
entitlements，尤其不能让 Autoupdate 保留 Sparkle 的 application identifier。验证脚本检查
这些嵌套组件、Autoupdate entitlement、动态链接路径与严格深度签名。

正式对外发布还必须由发布环境提供 Developer ID Application 身份，对最终应用和 DMG 完成
Apple 公证与 stapling；在这条外部证书流程就绪前，现有 ad-hoc 构建是明确的生产发布阻塞项。

## 许可与来源

项目软件代码按 `GPL-3.0-only` 发布，App Logo 按独立的 [Logo 许可](LOGO-LICENSE.md) 管理。ATVV 与 RC003 行为参考 `xxb26553663-star/remote-bridge-hub`，豆包兼容驱动基于固定版本 BlackHole 构建；完整归属与限制见 [COPYRIGHT.md](COPYRIGHT.md) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
