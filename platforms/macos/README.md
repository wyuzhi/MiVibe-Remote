# MiVibe Remote for macOS

本目录基于 `HD838A/remote-mic-app v1.2.3`，保留其已经验证的
CoreBluetooth、ATVV、IOHID、CoreAudio、虚拟麦克风驱动和设置界面。

MiVibe Remote 的增量：

- 独立名称、Bundle ID 和原创图标；
- 移除上游专有 Logo、产品照片和上游 Sparkle 更新源；
- 新增“Codex 预设”“WorkBuddy 预设”和“微信预设”：
  - 电源键：按当前预设打开 Codex、WorkBuddy 或微信；
  - 确定键：Return / 发送；
  - 方向键：导航；
  - 返回键：退格；
  - 菜单键：Escape；
  - Codex 语音键：ATVV 开始时按下 `⌃⇧D`，松开后释放；
  - WorkBuddy 语音键：ATVV 开始和结束时分别点按一次 `⌘D`。
- 恢复 `0.1.6` 的常驻虚拟麦克风路径：MiVibe 运行期间把系统默认输入保持为
  `MiRemoteV 2ch`，退出时恢复原麦克风；
- 空闲时把 MacBook 内置麦克风转发到 `MiRemoteV 2ch`，按住遥控器语音键时
  在应用内部由遥控器接管，松开后立即回到 MacBook 麦克风；
- 只缓存目标应用打开听写所需的极短开头语音，不再等待系统输入设备切换。

## 构建要求

- Apple Silicon Mac；
- macOS 26 或更高版本；
- Xcode / Command Line Tools 26.5 或更高版本，Swift 6.2；
- 构建完整语音安装包时还需构建 BlackHole 派生的 `MiRemoteV 2ch`。

```bash
./scripts/test.sh
swift test
./scripts/build-app.sh
./scripts/verify-app.sh
```

当前应用仍使用 ad-hoc 签名，未公证。蓝牙、输入监控和辅助功能权限必须由用户本人授予。

上游完整使用说明见 [UPSTREAM_README.md](UPSTREAM_README.md)，来源与许可证见仓库根目录
`UPSTREAM.md`、本目录 `COPYRIGHT.md`、`THIRD_PARTY_NOTICES.md` 和 `LICENSE.md`。
