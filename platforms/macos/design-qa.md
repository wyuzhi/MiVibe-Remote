# Design QA：macOS 15–26 自适应设置页

> 上游历史文档：原商品照片和截图未进入 MiVibe Remote；当前界面使用代码绘制的遥控器示意图。

## 审查范围

- 设置窗口：最小尺寸 800×650，可自由缩放；
- 页面：连接与语音、按键映射、权限与隐私；
- 仓库截图：
  - [连接与语音](Screenshots/connection-and-voice.png)
  - [按键映射](Screenshots/key-mapping.png)
  - [权限与隐私](Screenshots/permissions-and-privacy.png)

## 当前实现

- 设置页使用窄侧栏、标题区和分层内容区，三个页面的主要操作在最小窗口下可访问；
- 侧栏选择态和按键选择态使用低透明度语义蓝交互玻璃；
- 使用系统字体、语义字号和系统颜色，跟随浅色、深色、降低透明度与增强对比度设置；
- macOS 26 面板和按钮使用原生 `glassEffect` 与 glass button style；macOS 15 使用系统 `regularMaterial`、标准按钮和轻量描边；
- 按键页面复用 `Resources/RC003-remote-photo.png`，保持 508×1030 原始比例；
- 普通实体按键按下时会高亮遥控器示意图并定位映射行，语音键使用独立的语音活动状态；
- 界面未展示实物上不存在的独立静音键。

## 代码对应位置

- 窗口创建与最小尺寸：`Sources/RemoteMic/RemoteMicApp.swift`；
- 页面布局、材质和遥控器热点：`Sources/RemoteMic/SettingsView.swift`；
- 实体按键活动状态：`Sources/RemoteMic/HIDRemoteMonitor.swift` 与 `Sources/RemoteMic/BridgeAppModel.swift`。

## 结论

当前实现保留 macOS 26 Liquid Glass 外观，并为 macOS 15 提供结构、间距和功能一致的系统材质外观；未保留依赖本机临时目录的审查引用。
