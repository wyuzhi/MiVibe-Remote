# MiVibe Remote for macOS

本目录基于 `HD838A/remote-mic-app v1.2.3`，保留其已经验证的
CoreBluetooth、ATVV、IOHID、CoreAudio、虚拟麦克风驱动和设置界面。

MiVibe Remote 的增量：

- 独立名称、Bundle ID 和原创图标；
- 移除上游专有 Logo、产品照片和上游更新源，使用 MiVibe 自己签名的更新源；
- 集成固定版本 Sparkle 2：每天检查一次更新，也可从应用菜单或菜单栏手动检查；
  发现新版后由用户确认，不在后台静默下载安装；
- 内置“Codex 预设”“WorkBuddy 预设”“微信预设”，并支持可命名、可新增、可编辑和可删除的本地预设：
  - 电源键：按当前预设打开 Codex、WorkBuddy 或微信；
  - 确定键：Return / 发送；
  - 方向键：导航；
  - 返回键：退格；
  - 菜单键：Escape；
  - Codex 语音键：ATVV 开始时按下 `⌃⇧D`，松开后释放；
  - WorkBuddy 语音键：ATVV 开始和结束时分别点按一次 `⌘D`。
  - 自定义语音键：录入任意快捷键，并选择按住型或开关型；原生语音键仍负责遥控器收音。
- 新增应用内使用教程，以及权限变化后的 HID 自动恢复；
- 保持虚拟麦克风为默认输入：MiVibe 运行期间把系统默认输入保持为
  `MiRemoteV 2ch`，退出时恢复原麦克风；
- 空闲时关闭虚拟音频通道，按住遥控器语音键后才启动并传输声音，尾音发送完成
  后立即关闭，避免橙色麦克风隐私标记常驻；
- 电脑麦克风透传改为默认关闭的可选功能，只有用户主动开启后才会持续采集
  MacBook 内置麦克风；
- 只缓存目标应用打开听写所需的极短开头语音，不再等待系统输入设备切换。

## 构建要求

- Apple Silicon Mac；
- macOS 15 或更高版本；macOS 26 使用原生 Liquid Glass，macOS 15 使用材质降级样式；
- Xcode / Command Line Tools 26.5 或更高版本，Swift 6.2；
- 构建完整语音安装包时还需构建 BlackHole 派生的 `MiRemoteV 2ch`。

```bash
./scripts/test.sh
swift test
./scripts/build-app.sh
./scripts/verify-app.sh
```

当前应用仍使用 ad-hoc 签名，未公证。蓝牙、输入监控和辅助功能权限必须由用户本人授予。

## 自动更新构建配置

Sparkle 固定为 `2.9.4`。发布构建必须同时注入下面两个环境变量：

```bash
MIVIBE_APPCAST_URL="https://updates.example.com/mac/appcast.xml" \
MIVIBE_UPDATE_ED25519_PUBLIC_KEY="<32 字节 Ed25519 公钥的 Base64>" \
./scripts/build-app.sh
```

- `MIVIBE_APPCAST_URL` 必须是 HTTPS；macOS 使用独立的 mac feed；
- 公钥会写入最终应用的 `Info.plist`，用于验证每个更新包；
- Ed25519 私钥只保存在发布环境的安全存储中，绝不能放入源码、应用或 Release；
- 两个变量缺少任意一个时构建会失败；两个都不提供时生成安全禁用自动更新的开发包，菜单会显示“自动更新未配置”；
- Sparkle 每 24 小时检查一次，但禁止自动下载和静默安装；用户也可以在应用菜单或右键菜单栏图标后选择“检查更新…”；
- 在线更新只替换 `MiVibe Remote.app`，不会安装、删除或替换 `MiRemoteV 2ch` 音频驱动。

自定义打包脚本会把 SwiftPM 下载的完整 `Sparkle.framework`（包含 Updater、Autoupdate
和 XPC helpers）放入 `Contents/Frameworks`，并严格按 Sparkle 2.9.4 的官方顺序逐层签名：
Installer、Downloader、Autoupdate、Updater、framework；其中只有 Downloader 保留上游
entitlements。验证脚本同时检查运行时 rpath、嵌套签名和 Autoupdate 没有残留 Sparkle 的
上游 application identifier。

当前仓库尚未配置 Developer ID Application 证书和 Apple 公证流程，公开安装包使用
ad-hoc 签名。用户首次安装或更新后需要在“隐私与安全性”中确认打开。

上游完整使用说明见 [UPSTREAM_README.md](UPSTREAM_README.md)，来源与许可证见仓库根目录
`UPSTREAM.md`、本目录 `COPYRIGHT.md`、`THIRD_PARTY_NOTICES.md` 和 `LICENSE.md`。
