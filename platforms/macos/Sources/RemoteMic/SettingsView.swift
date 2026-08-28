import AppKit
import Combine
import CoreBluetooth
import SwiftUI

extension Notification.Name {
    static let showRemoteMicAbout = Notification.Name("com.mivibe.remote.show-about")
}

private enum SettingsSection: String, CaseIterable, Identifiable {
    case connection
    case mapping
    case permissions
    case guide
    case about

    static let mainFlow: [SettingsSection] = [.connection, .mapping, .permissions, .guide]

    var id: String { rawValue }

    var title: String {
        switch self {
        case .connection: return "连接"
        case .mapping: return "按键"
        case .permissions: return "权限"
        case .guide: return "教程"
        case .about: return "关于"
        }
    }

    var systemImage: String {
        switch self {
        case .connection: return "link"
        case .mapping: return "keyboard"
        case .permissions: return "shield.lefthalf.filled"
        case .guide: return "book"
        case .about: return "info.circle"
        }
    }
}

private enum PermissionVisualState {
    case granted
    case pending
    case optional

    var title: String {
        switch self {
        case .granted: return "已开启"
        case .pending: return "待授权"
        case .optional: return "无需授权"
        }
    }

    var tint: Color {
        switch self {
        case .granted: return .green
        case .pending: return .orange
        case .optional: return .blue
        }
    }
}

private struct ShortcutEditingTarget: Identifiable {
    let button: RemoteButton
    let trigger: ButtonTrigger

    var id: String { "\(button.rawValue)-\(trigger.rawValue)" }
}

struct SettingsView: View {
    @ObservedObject var model: BridgeAppModel
    @ObservedObject var settings: AppSettings
    let updatesConfigured: Bool
    let onCheckForUpdates: () -> Void

    @State private var selectedSection: SettingsSection = .connection
    @State private var selectedRemoteButton: RemoteButton = .ok
    @State private var shortcutEditingTarget: ShortcutEditingTarget?
    @State private var voiceShortcutEditorPresented = false
    @State private var bluetoothAuthorization = CBManager.authorization
    @State private var inputMonitoringGranted = HIDRemoteMonitor.isInputMonitoringGranted
    @State private var accessibilityGranted = KeyboardInjector.isAccessibilityTrusted
    @State private var advancedAudioExpanded = false
    @State private var installedApplicationBundleIdentifiers = Set<String>()

    init(
        model: BridgeAppModel,
        updatesConfigured: Bool = false,
        onCheckForUpdates: @escaping () -> Void = {}
    ) {
        self.model = model
        settings = model.settings
        self.updatesConfigured = updatesConfigured
        self.onCheckForUpdates = onCheckForUpdates
    }

    var body: some View {
        HStack(spacing: 0) {
            sidebar
                .frame(width: 108)
            Divider()
            selectedPage
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 760, minHeight: 600)
        .onAppear(perform: refreshRuntimeStates)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            refreshRuntimeStates()
        }
        .onReceive(NotificationCenter.default.publisher(for: .showRemoteMicAbout)) { _ in
            selectedSection = .about
        }
        .sheet(item: $shortcutEditingTarget) { target in
            ShortcutEditorSheet(
                title: "录入\(target.button.displayName)\(target.trigger.displayName)快捷键",
                currentShortcut: settings.configuredAction(
                    for: target.button,
                    trigger: target.trigger
                ).shortcut
            ) { shortcut in
                settings.setShortcut(
                    shortcut,
                    for: target.button,
                    trigger: target.trigger
                )
            }
        }
        .sheet(isPresented: $voiceShortcutEditorPresented) {
            ShortcutEditorSheet(
                title: "录入语音键快捷键",
                currentShortcut: settings.customVoiceShortcut
            ) { shortcut in
                settings.customVoiceShortcut = shortcut
                settings.selectVoiceShortcutProfile(.custom)
            }
        }
    }

    private var sidebar: some View {
        VStack(spacing: 10) {
            ForEach(SettingsSection.mainFlow) { section in
                sidebarButton(section)
            }
            Spacer(minLength: 0)
            sidebarButton(.about, subtitle: "起司制作")
            Divider()
            Button {
                NSApp.terminate(nil)
            } label: {
                VStack(spacing: 7) {
                    Image(systemName: "power")
                        .font(.system(size: 19, weight: .semibold))
                    Text("退出应用")
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 11)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("停止遥控器服务并完全退出 MiVibe Remote")
        }
        .padding(10)
        .background(.regularMaterial)
    }

    private func sidebarButton(
        _ section: SettingsSection,
        subtitle: String? = nil
    ) -> some View {
        Button {
            selectedSection = section
        } label: {
            VStack(spacing: 7) {
                Image(systemName: section.systemImage)
                    .font(.system(size: 21, weight: .semibold))
                Text(section.title)
                    .font(.system(size: 13, weight: .semibold))
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(selectedSection == section ? Color.accentColor : .secondary)
        .background(
            selectedSection == section ? Color.accentColor.opacity(0.12) : Color.clear,
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .accessibilityAddTraits(selectedSection == section ? .isSelected : [])
    }

    private var selectedPage: some View {
        ZStack {
            connectionPage
                .opacity(selectedSection == .connection ? 1 : 0)
                .allowsHitTesting(selectedSection == .connection)
                .accessibilityHidden(selectedSection != .connection)
            mappingPage
                .opacity(selectedSection == .mapping ? 1 : 0)
                .allowsHitTesting(selectedSection == .mapping)
                .accessibilityHidden(selectedSection != .mapping)
            permissionsPage
                .opacity(selectedSection == .permissions ? 1 : 0)
                .allowsHitTesting(selectedSection == .permissions)
                .accessibilityHidden(selectedSection != .permissions)
            guidePage
                .opacity(selectedSection == .guide ? 1 : 0)
                .allowsHitTesting(selectedSection == .guide)
                .accessibilityHidden(selectedSection != .guide)
            AboutView(
                updatesConfigured: updatesConfigured,
                onCheckForUpdates: onCheckForUpdates
            )
            .opacity(selectedSection == .about ? 1 : 0)
            .allowsHitTesting(selectedSection == .about)
            .accessibilityHidden(selectedSection != .about)
        }
    }

    private var connectionPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: "使用状态",
                    subtitle: "三个项目全部就绪后，就可以直接用遥控器操作 \(settings.voiceShortcutProfile.displayName)"
                )

                AdaptiveGlassEffectContainer(spacing: 14) {
                    HStack(alignment: .top, spacing: 14) {
                        connectionDevicePanel
                            .frame(width: 196)
                        audioSettingsPanel
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .adaptiveSoftTopScrollEdge()
    }

    private var connectionDevicePanel: some View {
        GlassPanel {
            VStack(spacing: 14) {
                VStack(spacing: 2) {
                    Text("遥控器 2")
                        .font(.headline)
                    Text("小米蓝牙")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                RC003Photo()
                    .frame(width: 70, height: 142)

                VStack(spacing: 12) {
                    DeviceStatusStep(
                        symbol: "antenna.radiowaves.left.and.right",
                        title: "蓝牙状态",
                        detail: model.connectionStatus,
                        badge: connectionBadge,
                        tint: connectionTint
                    )
                    DeviceStatusStep(
                        symbol: "waveform",
                        title: "麦克风键",
                        detail: model.isStreaming
                            ? "正在把语音传给 \(settings.voiceShortcutProfile.displayName)"
                            : "按住说话，松开停止",
                        badge: model.isStreaming ? "语音中" : "已就绪",
                        tint: model.isStreaming ? .orange : .blue
                    )
                    DeviceStatusStep(
                        symbol: "mic.fill",
                        title: "\(settings.voiceShortcutProfile.displayName) 语音",
                        detail: "快捷键 \(settings.voiceShortcutDisplayName)",
                        badge: voiceTriggerBadge,
                        tint: .blue
                    )
                }

                Button {
                    model.reconnect()
                } label: {
                    Text("重新连接遥控器")
                        .foregroundStyle(.white)
                }
                    .adaptiveProminentGlassButtonStyle()
                    .buttonBorderShape(.roundedRectangle(radius: 10))
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private var audioSettingsPanel: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 13) {
                Text("准备情况")
                    .font(.headline)

                SetupStatusRow(
                    symbol: "mic.and.signal.meter.fill",
                    title: "虚拟麦克风",
                    detail: virtualMicrophoneDetail,
                    badge: virtualMicrophoneBadge,
                    tint: isVirtualMicrophoneSelected && model.isAudioReady ? .green : .orange
                )

                Divider()

                VStack(alignment: .leading, spacing: 9) {
                    Text("这样使用")
                        .font(.headline)
                    UsageInstructionRow(
                        number: 1,
                        text: "按电源键，打开或切换到 \(settings.voiceShortcutProfile.displayName)"
                    )
                    UsageInstructionRow(number: 2, text: "按住麦克风键说话，松开后停止听写")
                    UsageInstructionRow(number: 3, text: "按中间确认键发送；返回键删除文字")
                }

                Divider()

                DisclosureGroup("高级设置（一般不需要修改）", isExpanded: $advancedAudioExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 14) {
                            Text("音频路由")
                                .frame(width: 72, alignment: .leading)
                            Picker("", selection: Binding(
                                get: { settings.selectedAudioDeviceUID },
                                set: { value in
                                    settings.selectedAudioDeviceUID = value
                                    model.applyAudioSettings()
                                }
                            )) {
                                Text("不输出语音").tag("")
                                ForEach(model.audioDevices) { device in
                                    Text(device.name).tag(device.uid)
                                }
                            }
                            .labelsHidden()
                            .frame(maxWidth: 270)
                        }

                        HStack(spacing: 14) {
                            Text("麦克风音量")
                                .frame(width: 72, alignment: .leading)
                            Slider(value: Binding(
                                get: { settings.gainDB },
                                set: { settings.gainDB = $0 }
                            ), in: 0...24, step: 1)
                            Text("\(Int(settings.gainDB)) dB")
                                .font(.system(.body, design: .monospaced))
                                .frame(width: 54, alignment: .trailing)
                        }

                        Text("声音太小时调高，环境噪声较大时调低。建议保持 6–12 dB。")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        Toggle("保持虚拟麦克风为默认输入", isOn: Binding(
                            get: { settings.headsetCompatibilityEnabled },
                            set: { enabled in
                                settings.headsetCompatibilityEnabled = enabled
                                model.applyHeadsetCompatibilitySetting()
                            }
                        ))
                        Text("开启后，MiVibe 运行期间固定系统默认输入为 MiRemoteV 2ch；关闭或退出后恢复原麦克风。此设置本身不会采集 MacBook 麦克风。")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        Toggle("电脑麦克风透传（会显示橙色隐私标记）", isOn: Binding(
                            get: { settings.computerMicrophonePassthroughEnabled },
                            set: { enabled in
                                settings.computerMicrophonePassthroughEnabled = enabled
                                model.applyComputerMicrophonePassthroughSetting()
                            }
                        ))
                        Text("默认关闭。开启后，未按遥控器语音键时会把 MacBook 麦克风送入 MiRemoteV 2ch，macOS 将持续显示麦克风隐私标记；关闭后 MiVibe 只传输遥控器声音，直接用电脑说话时需在目标软件选择 MacBook 麦克风。")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        Label(model.computerMicrophoneStatus, systemImage: "macbook.and.iphone")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        HStack(spacing: 10) {
                            Button("重新选择虚拟麦克风") {
                                model.refreshAudioDevices()
                                model.selectDoubaoAudioDevice()
                            }
                            .adaptiveProminentGlassButtonStyle()
                            .disabled(!model.hasDoubaoAudioDevice)
                            Button("测试音频通道") { model.sendTestTone() }
                                .adaptiveGlassButtonStyle()
                                .disabled(!model.canSendTestTone)
                            if !model.hasDoubaoAudioDevice {
                                Button("驱动安装说明") { model.openDoubaoDriverInstructions() }
                                    .adaptiveGlassButtonStyle()
                            }
                        }

                        Text(model.testToneStatus)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 10)
                }
            }
        }
    }

    private var mappingPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
            PageHeader(
                title: "按键映射",
                subtitle: "普通按键和语音触发都可配置；遥控器麦克风的收音开关仍由语音键可靠控制"
            )

            GlassPanel {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .center, spacing: 12) {
                        mappingStatusBlock
                        Spacer(minLength: 12)
                        mappingPresetControls
                    }
                    VStack(alignment: .leading, spacing: 12) {
                        mappingStatusBlock
                        mappingPresetControls
                    }
                }
            }

            voiceShortcutPanel

            AdaptiveGlassEffectContainer(spacing: 14) {
                HStack(alignment: .top, spacing: 14) {
                    GlassPanel {
                        RemoteControlDiagram(
                            selectedButton: $selectedRemoteButton,
                            activeButtons: model.activeRemoteButtons,
                            voiceActive: model.isStreaming,
                            voiceProfile: settings.voiceShortcutProfile,
                            voiceShortcutDisplayName: settings.voiceShortcutDisplayName
                        )
                        .onReceive(model.$activeRemoteButtons) { buttons in
                            if let button = RemoteButton.allCases.first(where: { buttons.contains($0) }) {
                                selectedRemoteButton = button
                            }
                        }
                    }
                    .frame(width: 206)

                    GlassPanel {
                        VStack(alignment: .leading, spacing: 10) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("按键动作")
                                    .font(.headline)
                                Text("点击或按下左侧实体按键定位；修改后自动保存。将任意键设为“循环切换预设”，即可按 Codex → WorkBuddy → 微信 → 自定义循环。")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }

                            let buttons = RemoteButton.allCases
                            let midpoint = (buttons.count + 1) / 2

                            HStack(alignment: .top, spacing: 8) {
                                ForEach(0..<2, id: \.self) { column in
                                    VStack(spacing: 4) {
                                        let range = column == 0
                                            ? buttons.prefix(midpoint)
                                            : buttons.suffix(from: midpoint)
                                        ForEach(range) { button in
                                            mappingRow(button)
                                        }
                                    }
                                    .frame(maxWidth: .infinity)
                                }
                            }

                            Divider()
                            secondaryActionsPanel(for: selectedRemoteButton)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .frame(maxHeight: .infinity)
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .adaptiveSoftTopScrollEdge()
    }

    private var mappingStatusBlock: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text("当前模式")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                StatusPill(
                    text: currentPresetStatus,
                    tint: settings.activePreset == nil ? .orange : .green
                )
            }
            Toggle("启用小米遥控器自定义按键映射", isOn: Binding(
                get: { settings.customMappingEnabled },
                set: { enabled in
                    settings.customMappingEnabled = enabled
                    model.applyHIDSettings()
                }
            ))
            Text(model.hidStatus)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .fixedSize(horizontal: true, vertical: false)
    }

    private var mappingPresetControls: some View {
        HStack(spacing: 8) {
            StatusPill(
                text: settings.customMappingEnabled ? "已启用" : "未启用",
                tint: settings.customMappingEnabled ? .green : .secondary
            )
            Button("恢复默认") {
                settings.resetBindings()
                selectedRemoteButton = .ok
            }
            .adaptiveGlassButtonStyle()
            presetButton(.codex)
            presetButton(.workBuddy)
            presetButton(.weChat)
            presetButton(.custom)
        }
        .fixedSize(horizontal: true, vertical: false)
    }

    private var voiceShortcutPanel: some View {
        GlassPanel {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 14) {
                    voiceShortcutHeading
                    Spacer(minLength: 8)
                    voiceShortcutControls
                }
                VStack(alignment: .leading, spacing: 12) {
                    voiceShortcutHeading
                    voiceShortcutControls
                }
            }
        }
    }

    private var voiceShortcutHeading: some View {
        HStack(alignment: .center, spacing: 14) {
                Image(systemName: "mic.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(Color.accentColor)

                VStack(alignment: .leading, spacing: 3) {
                    Text("语音键动作")
                        .font(.headline)
                    Text("按住原生语音键仍会开启遥控器麦克风；这里决定目标软件收到哪个快捷键。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
        }
    }

    private var voiceShortcutControls: some View {
        HStack(spacing: 10) {
                Picker("语音快捷键", selection: Binding(
                    get: { settings.voiceShortcutProfile },
                    set: { settings.selectVoiceShortcutProfile($0) }
                )) {
                    ForEach(VoiceShortcutProfile.allCases, id: \.rawValue) { profile in
                        Text(profile.displayName).tag(profile)
                    }
                }
                .labelsHidden()
                .frame(width: 112)

                if settings.voiceShortcutProfile == .custom {
                    Button {
                        voiceShortcutEditorPresented = true
                    } label: {
                        Label(settings.voiceShortcutDisplayName, systemImage: "keyboard")
                    }
                    .adaptiveGlassButtonStyle()

                    Picker("触发方式", selection: $settings.customVoiceTriggerMode) {
                        ForEach(VoiceShortcutTriggerMode.allCases) { mode in
                            Text(mode.displayName).tag(mode)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 92)
                    .help(settings.customVoiceTriggerMode.helpText)

                    Button("保存当前为自定义预设") {
                        settings.saveCurrentAsCustomPreset()
                    }
                    .adaptiveProminentGlassButtonStyle()
                } else {
                    Text(settings.voiceShortcutDisplayName)
                        .font(.system(.body, design: .rounded).weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(minWidth: 74)
                }
        }
        .fixedSize(horizontal: true, vertical: false)
    }

    @ViewBuilder
    private func mappingRow(_ button: RemoteButton) -> some View {
        let selected = selectedRemoteButton == button
        let currentAction = settings.action(for: button)
        let currentShortcut = settings.shortcut(for: button)
        let content = VStack(spacing: 4) {
            HStack(spacing: 8) {
                Button {
                    selectedRemoteButton = button
                } label: {
                    Text(button.displayName)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .help("\(button.displayName) · HID \(String(format: "0x%02X", button.hidUsage))")

                Picker("", selection: Binding(
                    get: { currentAction },
                    set: { action in
                        settings.setAction(action, for: button)
                        selectedRemoteButton = button
                        if action == .customShortcut {
                            shortcutEditingTarget = ShortcutEditingTarget(
                                button: button,
                                trigger: .singleClick
                            )
                        }
                    }
                )) {
                    ForEach(ButtonAction.pickerActions(
                        installedBundleIdentifiers: installedApplicationBundleIdentifiers,
                        current: currentAction
                    )) { action in
                        let unavailable = action.presetApplication.map {
                            !installedApplicationBundleIdentifiers.contains($0.bundleIdentifier)
                        } ?? false
                        Text(action.displayName + (unavailable ? "（未安装）" : "")).tag(action)
                    }
                }
                .labelsHidden()
                .frame(width: 112)
            }

            if currentAction == .customShortcut {
                Button {
                    selectedRemoteButton = button
                    shortcutEditingTarget = ShortcutEditingTarget(
                        button: button,
                        trigger: .singleClick
                    )
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "keyboard")
                        Text(currentShortcut?.displayName ?? "点击录入快捷键")
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        Image(systemName: "pencil")
                    }
                    .font(.caption)
                    .foregroundStyle(currentShortcut == nil ? Color.orange : Color.primary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .frame(maxWidth: .infinity)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
                .help("录入要发送给当前应用的键盘快捷键")
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)

        if selected {
            content
                .adaptiveTintedGlassRounded(
                    cornerRadius: 12,
                    tint: Color.accentColor.opacity(0.10),
                    interactive: true
                )
        } else {
            VStack(spacing: 0) {
                content
                Divider()
                    .padding(.leading, 8)
            }
        }
    }

    private func secondaryActionsPanel(for button: RemoteButton) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text("\(button.displayName)其他触发")
                    .font(.caption.weight(.semibold))
                Spacer()
                if settings.hasSecondaryAction(for: button) {
                    Text("按住重复已停用")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.orange)
                }
            }

            secondaryActionRow(button, trigger: .doubleClick)
            secondaryActionRow(button, trigger: .longPress)

            Text("双击会等待约 0.3 秒确认单击；长按约 0.55 秒触发。未配置时保持原有即时响应。")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
        }
    }

    private func secondaryActionRow(
        _ button: RemoteButton,
        trigger: ButtonTrigger
    ) -> some View {
        let configured = settings.configuredAction(for: button, trigger: trigger)
        return HStack(spacing: 8) {
            Text(trigger.displayName)
                .font(.caption)
                .frame(width: 38, alignment: .leading)

            Picker("", selection: Binding(
                get: { configured.action },
                set: { action in
                    settings.setAction(action, for: button, trigger: trigger)
                    if action == .customShortcut {
                        shortcutEditingTarget = ShortcutEditingTarget(
                            button: button,
                            trigger: trigger
                        )
                    }
                }
            )) {
                ForEach(ButtonAction.pickerActions(
                    installedBundleIdentifiers: installedApplicationBundleIdentifiers,
                    current: configured.action
                )) { action in
                    let unavailable = action.presetApplication.map {
                        !installedApplicationBundleIdentifiers.contains($0.bundleIdentifier)
                    } ?? false
                    Text(action.displayName + (unavailable ? "（未安装）" : "")).tag(action)
                }
            }
            .labelsHidden()
            .frame(width: 150)

            if configured.action == .customShortcut {
                Button {
                    shortcutEditingTarget = ShortcutEditingTarget(
                        button: button,
                        trigger: trigger
                    )
                } label: {
                    HStack(spacing: 5) {
                        Text(configured.shortcut?.displayName ?? "点击录入")
                            .lineLimit(1)
                        Image(systemName: "pencil")
                    }
                    .font(.caption)
                    .foregroundStyle(configured.shortcut == nil ? Color.orange : Color.primary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
            }

            Spacer(minLength: 0)
        }
    }

    private var guidePage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: "使用教程",
                    subtitle: "从首次连接到自定义语音键，按这条最短路径完成设置"
                )

                GlassPanel {
                    VStack(alignment: .leading, spacing: 16) {
                        GuideStepRow(
                            number: 1,
                            title: "先完成三个权限",
                            detail: "开启蓝牙、输入监控和辅助功能。授权后返回 MiVibe，应用会自动重新检测按键。",
                            symbol: "checkmark.shield.fill"
                        )
                        GuideStepRow(
                            number: 2,
                            title: "确认遥控器和虚拟麦克风就绪",
                            detail: "连接页应显示遥控器已连接、MiRemoteV 2ch 已就绪。可先播放测试音检查音频通道。",
                            symbol: "waveform.badge.mic"
                        )
                        GuideStepRow(
                            number: 3,
                            title: "选择预设或自定义",
                            detail: "Codex、WorkBuddy、微信可以一键套用；自定义预设会保存普通按键、双击/长按和语音快捷键。",
                            symbol: "slider.horizontal.3"
                        )
                        GuideStepRow(
                            number: 4,
                            title: "按住语音键说话",
                            detail: "原生语音键负责让遥控器真正传输声音；松开后应用会等待尾部音频送完，再结束目标软件听写。",
                            symbol: "mic.fill"
                        )
                    }
                }

                AdaptiveGlassEffectContainer(spacing: 14) {
                    HStack(alignment: .top, spacing: 14) {
                        GlassPanel {
                            VStack(alignment: .leading, spacing: 10) {
                                Label("推荐测试顺序", systemImage: "list.number")
                                    .font(.headline)
                                Text("1. 用方向键移动光标\n2. 用返回键删除\n3. 按住语音键说一句完整的话\n4. 松开后确认尾音完整\n5. 用确认键发送")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .lineSpacing(4)
                            }
                        }
                        .frame(maxWidth: .infinity)

                        GlassPanel {
                            VStack(alignment: .leading, spacing: 10) {
                                Label("遇到问题", systemImage: "wrench.and.screwdriver.fill")
                                    .font(.headline)
                                Text("方向键可用但映射无效：重新检查输入监控与辅助功能。\n有快捷键但没声音：确认按的是原生语音键。\n语音无文字：检查目标软件快捷键与当前预设是否一致。")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .lineSpacing(4)
                                HStack {
                                    Button("查看权限") { selectedSection = .permissions }
                                        .adaptiveGlassButtonStyle()
                                    Button("打开日志") { model.openLogFolder() }
                                        .adaptiveGlassButtonStyle()
                                }
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .adaptiveSoftTopScrollEdge()
    }

    private var permissionsPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: "权限与隐私",
                    subtitle: "按顺序完成权限设置，确保小米遥控器正常连接和发送按键"
                )

                AdaptiveGlassEffectContainer(spacing: 14) {
                    GlassPanel {
                        VStack(alignment: .leading, spacing: 0) {
                            Text("所需权限")
                                .font(.headline)
                                .padding(.bottom, 8)

                            permissionRow(
                                index: 1,
                                symbol: "antenna.radiowaves.left.and.right",
                                title: "蓝牙",
                                detail: "连接小米遥控器并读取 ATVV 语音服务",
                                state: bluetoothPermissionState,
                                actionTitle: "打开蓝牙设置"
                            ) {
                                if let url = URL(string: "x-apple.systempreferences:com.apple.BluetoothSettings") {
                                    NSWorkspace.shared.open(url)
                                }
                            }

                            Divider().padding(.leading, 62)

                            permissionRow(
                                index: 2,
                                symbol: "keyboard",
                                title: "输入监控",
                                detail: "只在小米遥控器设备层屏蔽原始事件，再发送一次自定义动作",
                                state: inputMonitoringGranted ? .granted : .pending,
                                actionTitle: "请求权限"
                            ) {
                                model.requestInputMonitoringPermission()
                            }

                            Divider().padding(.leading, 62)

                            permissionRow(
                                index: 3,
                                symbol: "mic",
                                title: "麦克风",
                                detail: settings.computerMicrophonePassthroughEnabled
                                    ? "可选：把 MacBook 内置麦克风转发到常驻的 MiRemoteV 2ch"
                                    : "可选功能，默认关闭；仅开启电脑麦克风透传时才需要授权",
                                state: computerMicrophonePermissionState,
                                actionTitle: settings.computerMicrophonePassthroughEnabled
                                    ? "请求权限"
                                    : "开启透传"
                            ) {
                                model.requestMicrophonePermission()
                            }

                            Divider().padding(.leading, 62)

                            permissionRow(
                                index: 4,
                                symbol: "accessibility",
                                title: "辅助功能",
                                detail: "把映射后的按键动作发送给当前应用",
                                state: accessibilityGranted ? .granted : .pending,
                                actionTitle: "请求权限"
                            ) {
                                model.requestAccessibilityPermission()
                            }
                        }
                    }

                    GlassPanel {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("诊断")
                                .font(.headline)
                            HStack(spacing: 12) {
                                Image(systemName: "doc.text.magnifyingglass")
                                    .font(.title3)
                                    .foregroundStyle(Color.accentColor)
                                    .frame(width: 34, height: 34)
                                    .adaptiveTintedGlassCircle(Color.accentColor.opacity(0.14))
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("应用日志")
                                    Text("日志不记录语音内容、蓝牙地址或外设 UUID。")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("在 Finder 中显示日志") { model.openLogFolder() }
                                    .adaptiveGlassButtonStyle()
                            }
                        }
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .adaptiveSoftTopScrollEdge()
    }

    private func permissionRow(
        index: Int,
        symbol: String,
        title: String,
        detail: String,
        state: PermissionVisualState,
        actionTitle: String,
        action: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 14) {
            Text("\(index)")
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Color.accentColor, in: Circle())

            Image(systemName: symbol)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Color.accentColor)
                .frame(width: 42, height: 42)
                .adaptiveTintedGlassCircle(Color.accentColor.opacity(0.14))

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 16)
            StatusPill(text: state.title, tint: state.tint)
            Button(actionTitle, action: action)
                .adaptiveGlassButtonStyle()
                .frame(width: 112)
        }
        .padding(.vertical, 12)
    }

    private var connectionBadge: String {
        model.connectionStatus.contains("已连接") ? "已连接" : "连接中"
    }

    private var connectionTint: Color {
        model.connectionStatus.contains("已连接") ? .green : .orange
    }

    private var voiceTriggerBadge: String {
        model.voiceShortcutStatus.contains("需要辅助功能") ? "需要授权" : "已启用"
    }

    private var isVirtualMicrophoneSelected: Bool {
        guard let device = DoubaoAudioDevicePolicy.device(in: model.audioDevices) else {
            return false
        }
        return settings.selectedAudioDeviceUID == device.uid
    }

    private var virtualMicrophoneBadge: String {
        if isVirtualMicrophoneSelected && model.isAudioReady { return "已就绪" }
        if isVirtualMicrophoneSelected { return "自动恢复中" }
        return model.hasDoubaoAudioDevice ? "正在配置" : "需要安装"
    }

    private var virtualMicrophoneDetail: String {
        if isVirtualMicrophoneSelected && model.isAudioReady {
            if settings.computerMicrophonePassthroughEnabled {
                return "默认输入保持 MiRemoteV 2ch；电脑麦克风与遥控器在内部无缝切换"
            }
            return "默认输入保持 MiRemoteV 2ch；仅按住遥控器语音键时传输声音"
        }
        if isVirtualMicrophoneSelected {
            return model.audioStatus
        }
        if model.hasDoubaoAudioDevice {
            return "已找到 MiRemoteV 2ch，正在自动选择"
        }
        return "未找到 MiRemoteV 2ch，请重新安装应用和驱动"
    }

    private var bluetoothPermissionState: PermissionVisualState {
        bluetoothAuthorization == .allowedAlways ? .granted : .pending
    }

    private var computerMicrophonePermissionState: PermissionVisualState {
        guard settings.computerMicrophonePassthroughEnabled else { return .optional }
        return model.computerMicrophoneStatus.contains("→ MiRemoteV 2ch")
            ? .granted
            : .pending
    }

    private var currentPresetStatus: String {
        if let preset = settings.activePreset {
            return "\(preset.displayName) 模式"
        }
        return "自定义 · 语音 \(settings.voiceShortcutProfile.displayName)"
    }

    @ViewBuilder
    private func presetButton(_ preset: VoiceShortcutProfile) -> some View {
        let isActive = settings.activePreset == preset
        let action = {
            switch preset {
            case .codex:
                settings.applyCodexPreset()
            case .workBuddy:
                settings.applyWorkBuddyPreset()
            case .weChat:
                settings.applyWeChatPreset()
            case .custom:
                settings.applyCustomPreset()
            }
            selectedRemoteButton = .power
        }
        if isActive {
            Button(action: action) {
                Label("\(preset.displayName) 已启用", systemImage: "checkmark.circle.fill")
            }
            .adaptiveProminentGlassButtonStyle()
        } else {
            Button("\(preset.displayName) 预设", action: action)
                .adaptiveGlassButtonStyle()
        }
    }

    private func refreshRuntimeStates() {
        bluetoothAuthorization = CBManager.authorization
        inputMonitoringGranted = HIDRemoteMonitor.isInputMonitoringGranted
        accessibilityGranted = KeyboardInjector.isAccessibilityTrusted
        installedApplicationBundleIdentifiers = PresetApplication.installedBundleIdentifiers
    }
}

private struct ShortcutEditorSheet: View {
    @Environment(\.dismiss) private var dismiss

    let title: String
    let currentShortcut: CustomKeyboardShortcut?
    let onSave: (CustomKeyboardShortcut?) -> Void

    @State private var shortcut: CustomKeyboardShortcut?

    init(
        title: String,
        currentShortcut: CustomKeyboardShortcut?,
        onSave: @escaping (CustomKeyboardShortcut?) -> Void
    ) {
        self.title = title
        self.currentShortcut = currentShortcut
        self.onSave = onSave
        _shortcut = State(initialValue: currentShortcut)
    }

    var body: some View {
        VStack(spacing: 18) {
            VStack(spacing: 5) {
                Text(title)
                    .font(.title3.weight(.semibold))
                Text("直接按下想要的按键组合，支持 Command、Option、Control、Shift 和 Fn。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            Text(shortcut?.displayName ?? "等待按键…")
                .font(.system(size: 24, weight: .semibold, design: .rounded))
                .foregroundStyle(shortcut == nil ? Color.secondary : Color.primary)
                .frame(maxWidth: .infinity, minHeight: 62)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 12))

            ShortcutCaptureView { shortcut = $0 }
                .frame(height: 1)

            HStack {
                Button("清除") {
                    onSave(nil)
                    dismiss()
                }
                .disabled(currentShortcut == nil)

                Spacer()

                Button("取消") { dismiss() }
                Button("保存") {
                    onSave(shortcut)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(shortcut == nil)
            }
        }
        .padding(24)
        .frame(width: 400)
    }
}

private struct ShortcutCaptureView: NSViewRepresentable {
    let onCapture: (CustomKeyboardShortcut) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onCapture: onCapture)
    }

    func makeNSView(context: Context) -> ShortcutCaptureNSView {
        let view = ShortcutCaptureNSView()
        context.coordinator.view = view
        context.coordinator.startMonitoring()
        return view
    }

    func updateNSView(_ nsView: ShortcutCaptureNSView, context: Context) {
        context.coordinator.onCapture = onCapture
    }

    static func dismantleNSView(_ nsView: ShortcutCaptureNSView, coordinator: Coordinator) {
        coordinator.stopMonitoring()
    }

    final class Coordinator {
        var onCapture: (CustomKeyboardShortcut) -> Void
        weak var view: NSView?
        private var monitor: Any?

        init(onCapture: @escaping (CustomKeyboardShortcut) -> Void) {
            self.onCapture = onCapture
        }

        func startMonitoring() {
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, event.window === self.view?.window else { return event }
                self.onCapture(CustomKeyboardShortcut(event: event))
                return nil
            }
        }

        func stopMonitoring() {
            guard let monitor else { return }
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }

        deinit {
            stopMonitoring()
        }
    }
}

private final class ShortcutCaptureNSView: NSView {
    override var acceptsFirstResponder: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.window?.makeFirstResponder(self)
        }
    }
}

private struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 25, weight: .semibold))
            Text(subtitle)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

private struct GlassPanel<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(16)
            .adaptiveRegularGlassRounded(cornerRadius: 20)
    }
}

private struct StatusPill: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .adaptiveTintedGlassCapsule(tint.opacity(0.14))
    }
}

private struct DeviceStatusStep: View {
    let symbol: String
    let title: String
    let detail: String
    let badge: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: symbol)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 28, height: 28)
                .adaptiveTintedGlassCircle(tint.opacity(0.14))
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(title)
                        .font(.caption.weight(.semibold))
                    Spacer(minLength: 4)
                    StatusPill(text: badge, tint: tint)
                }
                Text(detail)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct SetupStatusRow: View {
    let symbol: String
    let title: String
    let detail: String
    let badge: String
    let tint: Color

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 40, height: 40)
                .adaptiveTintedGlassCircle(tint.opacity(0.14))
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            StatusPill(text: badge, tint: tint)
        }
    }
}

private struct UsageInstructionRow: View {
    let number: Int
    let text: String

    var body: some View {
        HStack(spacing: 10) {
            Text("\(number)")
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Color.accentColor, in: Circle())
            Text(text)
                .font(.subheadline)
        }
    }
}

private struct GuideStepRow: View {
    let number: Int
    let title: String
    let detail: String
    let symbol: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text("\(number)")
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(Color.accentColor, in: Circle())
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Color.accentColor)
                .frame(width: 34)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct RC003Photo: View {
    private static let productImage: NSImage? = {
        guard let url = Bundle.main.url(
            forResource: "RemoteProduct",
            withExtension: "png"
        ) else { return nil }
        return NSImage(contentsOf: url)
    }()

    var body: some View {
        Group {
            if let productImage = Self.productImage {
                Image(nsImage: productImage)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .shadow(color: .black.opacity(0.24), radius: 8, y: 5)
            } else {
                RC003Placeholder()
            }
        }
        .accessibilityHidden(true)
    }
}

private struct RC003Placeholder: View {
    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let height = proxy.size.height
            ZStack {
                RoundedRectangle(cornerRadius: width * 0.28, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color(white: 0.20), Color(white: 0.08)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                Circle()
                    .fill(.white.opacity(0.08))
                    .frame(width: width * 0.50)
                    .position(x: width * 0.50, y: height * 0.25)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 5)
    }
}

private struct RemoteControlDiagram: View {
    @Binding var selectedButton: RemoteButton
    let activeButtons: Set<RemoteButton>
    let voiceActive: Bool
    let voiceProfile: VoiceShortcutProfile
    let voiceShortcutDisplayName: String

    private let canvasSize = CGSize(width: 174, height: 352)

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RC003Photo()
                    .frame(width: canvasSize.width, height: canvasSize.height)

                hotspot(.power, x: 0.386, y: 0.099, width: 0.15, height: 0.072)
                voiceHotspot(x: 0.630, y: 0.099, width: 0.15, height: 0.072)

                hotspot(.up, x: 0.502, y: 0.179, width: 0.18, height: 0.065)
                hotspot(.left, x: 0.362, y: 0.246, width: 0.15, height: 0.080)
                hotspot(.ok, x: 0.502, y: 0.246, width: 0.19, height: 0.095)
                hotspot(.right, x: 0.638, y: 0.246, width: 0.15, height: 0.080)
                hotspot(.down, x: 0.502, y: 0.317, width: 0.18, height: 0.065)

                hotspot(.back, x: 0.406, y: 0.389, width: 0.17, height: 0.080)
                hotspot(.volumeUp, x: 0.604, y: 0.390, width: 0.16, height: 0.080)
                hotspot(.home, x: 0.406, y: 0.479, width: 0.17, height: 0.080)
                hotspot(.volumeDown, x: 0.604, y: 0.480, width: 0.16, height: 0.080)
                hotspot(.menu, x: 0.406, y: 0.569, width: 0.17, height: 0.080)
                hotspot(.tv, x: 0.604, y: 0.569, width: 0.17, height: 0.080)
            }
            .frame(width: canvasSize.width, height: canvasSize.height)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            Text(
                "点击或按下实物按键定位映射；麦克风键当前控制 \(voiceProfile.displayName) 语音。"
            )
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
    }

    private func hotspot(
        _ button: RemoteButton,
        x: CGFloat,
        y: CGFloat,
        width: CGFloat,
        height: CGFloat
    ) -> some View {
        let active = activeButtons.contains(button)
        return Button {
            selectedButton = button
        } label: {
            RoundedRectangle(cornerRadius: 999, style: .continuous)
                .fill(active ? Color.orange.opacity(0.30) : selectedButton == button ? Color.accentColor.opacity(0.24) : Color.clear)
                .overlay {
                    RoundedRectangle(cornerRadius: 999, style: .continuous)
                        .stroke(
                            active ? Color.orange : selectedButton == button ? Color.accentColor : Color.clear,
                            lineWidth: 2
                        )
                }
                .contentShape(RoundedRectangle(cornerRadius: 999, style: .continuous))
        }
        .buttonStyle(.plain)
        .frame(width: canvasSize.width * width, height: canvasSize.height * height)
        .position(x: canvasSize.width * x, y: canvasSize.height * y)
        .help(button.displayName)
        .accessibilityLabel(Text(button.displayName))
    }

    private func voiceHotspot(
        x: CGFloat,
        y: CGFloat,
        width: CGFloat,
        height: CGFloat
    ) -> some View {
        Circle()
            .fill(voiceActive ? Color.orange.opacity(0.28) : Color.clear)
            .overlay {
                Circle().stroke(voiceActive ? Color.orange : Color.clear, lineWidth: 2)
            }
            .contentShape(Circle())
            .frame(width: canvasSize.width * width, height: canvasSize.height * height)
            .position(x: canvasSize.width * x, y: canvasSize.height * y)
            .help(
                "按住时触发 \(voiceProfile.displayName) \(voiceShortcutDisplayName) " +
                    "并桥接遥控器语音；松开时停止"
            )
            .accessibilityElement()
            .accessibilityLabel(Text("\(voiceProfile.displayName) 语音键，可在上方自定义快捷键"))
    }
}
