import AppKit
import Combine
import CoreBluetooth
import SwiftUI

private enum SettingsSection: String, CaseIterable, Identifiable {
    case connection
    case mapping
    case permissions

    var id: String { rawValue }

    var title: String {
        switch self {
        case .connection: return "连接"
        case .mapping: return "按键"
        case .permissions: return "权限"
        }
    }

    var systemImage: String {
        switch self {
        case .connection: return "link"
        case .mapping: return "keyboard"
        case .permissions: return "shield.lefthalf.filled"
        }
    }
}

private enum PermissionVisualState {
    case granted
    case pending

    var title: String {
        switch self {
        case .granted: return "已开启"
        case .pending: return "待授权"
        }
    }

    var tint: Color {
        switch self {
        case .granted: return .green
        case .pending: return .orange
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

    @State private var selectedSection: SettingsSection = .connection
    @State private var selectedRemoteButton: RemoteButton = .ok
    @State private var shortcutEditingTarget: ShortcutEditingTarget?
    @State private var bluetoothAuthorization = CBManager.authorization
    @State private var inputMonitoringGranted = HIDRemoteMonitor.isInputMonitoringGranted
    @State private var accessibilityGranted = KeyboardInjector.isAccessibilityTrusted
    @State private var advancedAudioExpanded = false
    @State private var installedApplicationBundleIdentifiers = Set<String>()

    init(model: BridgeAppModel) {
        self.model = model
        settings = model.settings
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
        .sheet(item: $shortcutEditingTarget) { target in
            ShortcutEditorSheet(
                button: target.button,
                trigger: target.trigger,
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
    }

    private var sidebar: some View {
        VStack(spacing: 10) {
            ForEach(SettingsSection.allCases) { section in
                sidebarButton(section)
            }
            Spacer(minLength: 0)
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

    private func sidebarButton(_ section: SettingsSection) -> some View {
        Button {
            selectedSection = section
        } label: {
            VStack(spacing: 7) {
                Image(systemName: section.systemImage)
                    .font(.system(size: 21, weight: .semibold))
                Text(section.title)
                    .font(.system(size: 13, weight: .semibold))
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
        }
    }

    private var connectionPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: "使用状态",
                    subtitle: "三个项目全部就绪后，就可以直接用遥控器操作 \(settings.voiceShortcutProfile.displayName)"
                )

                GlassEffectContainer(spacing: 14) {
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
        .scrollEdgeEffectStyle(.soft, for: .top)
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
                        detail: "快捷键 \(settings.voiceShortcutProfile.shortcutDisplayName)",
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
                    .buttonStyle(.glassProminent)
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

                        Toggle("遥控器语音时临时切换系统麦克风", isOn: Binding(
                            get: { settings.temporaryVoiceInputSwitchEnabled },
                            set: { enabled in
                                settings.temporaryVoiceInputSwitchEnabled = enabled
                                model.applyTemporaryVoiceInputSetting()
                            }
                        ))
                        Text("开启后，仅在按住遥控器语音键期间切到 MiRemoteV 2ch；松开并完成尾音传输后，自动恢复你此前选择的 MacBook、耳机或其他麦克风。")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        HStack(spacing: 10) {
                            Button("重新选择虚拟麦克风") {
                                model.refreshAudioDevices()
                                model.selectDoubaoAudioDevice()
                            }
                            .buttonStyle(.glassProminent)
                            .disabled(!model.hasDoubaoAudioDevice)
                            Button("测试音频通道") { model.sendTestTone() }
                                .buttonStyle(.glass)
                                .disabled(!model.canSendTestTone)
                            if !model.hasDoubaoAudioDevice {
                                Button("驱动安装说明") { model.openDoubaoDriverInstructions() }
                                    .buttonStyle(.glass)
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
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(
                title: "按键映射",
                subtitle: "自定义小米遥控器按键功能，并保留语音键的固定核心行为"
            )

            GlassPanel {
                HStack(alignment: .center, spacing: 12) {
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
                    Spacer(minLength: 12)
                    StatusPill(
                        text: settings.customMappingEnabled ? "已启用" : "未启用",
                        tint: settings.customMappingEnabled ? .green : .secondary
                    )
                    Button("恢复默认") {
                        settings.resetBindings()
                        selectedRemoteButton = .ok
                    }
                    .buttonStyle(.glass)
                    presetButton(.codex)
                    presetButton(.workBuddy)
                }
            }

            GlassEffectContainer(spacing: 14) {
                HStack(alignment: .top, spacing: 14) {
                    GlassPanel {
                        RemoteControlDiagram(
                            selectedButton: $selectedRemoteButton,
                            activeButtons: model.activeRemoteButtons,
                            voiceActive: model.isStreaming,
                            voiceProfile: settings.voiceShortcutProfile
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
                                Text("点击或按下左侧实体按键定位；修改后自动保存。将任意键设为“循环切换预设”，即可按 Codex → WorkBuddy 循环。")
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
                .glassEffect(
                    .clear.tint(Color.accentColor.opacity(0.10)).interactive(),
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous)
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

    private var permissionsPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: "权限与隐私",
                    subtitle: "按顺序完成权限设置，确保小米遥控器正常连接和发送按键"
                )

                GlassEffectContainer(spacing: 14) {
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
                                    .glassEffect(
                                        .clear.tint(Color.accentColor.opacity(0.14)),
                                        in: Circle()
                                    )
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("应用日志")
                                    Text("日志不记录语音内容、蓝牙地址或外设 UUID。")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("在 Finder 中显示日志") { model.openLogFolder() }
                                    .buttonStyle(.glass)
                            }
                        }
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .scrollEdgeEffectStyle(.soft, for: .top)
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
                .glassEffect(
                    .clear.tint(Color.accentColor.opacity(0.14)),
                    in: Circle()
                )

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
                .buttonStyle(.glass)
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
            return "按住遥控器语音键时临时切换到 MiRemoteV 2ch，松开后恢复原麦克风"
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
            }
            selectedRemoteButton = .power
        }
        if isActive {
            Button(action: action) {
                Label("\(preset.displayName) 已启用", systemImage: "checkmark.circle.fill")
            }
            .buttonStyle(.glassProminent)
        } else {
            Button("\(preset.displayName) 预设", action: action)
                .buttonStyle(.glass)
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

    let button: RemoteButton
    let trigger: ButtonTrigger
    let currentShortcut: CustomKeyboardShortcut?
    let onSave: (CustomKeyboardShortcut?) -> Void

    @State private var shortcut: CustomKeyboardShortcut?

    init(
        button: RemoteButton,
        trigger: ButtonTrigger,
        currentShortcut: CustomKeyboardShortcut?,
        onSave: @escaping (CustomKeyboardShortcut?) -> Void
    ) {
        self.button = button
        self.trigger = trigger
        self.currentShortcut = currentShortcut
        self.onSave = onSave
        _shortcut = State(initialValue: currentShortcut)
    }

    var body: some View {
        VStack(spacing: 18) {
            VStack(spacing: 5) {
                Text("录入\(button.displayName)\(trigger.displayName)快捷键")
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
            .glassEffect(
                .regular,
                in: RoundedRectangle(cornerRadius: 20, style: .continuous)
            )
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
            .glassEffect(.clear.tint(tint.opacity(0.14)), in: Capsule())
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
                .glassEffect(.clear.tint(tint.opacity(0.14)), in: Circle())
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
                .glassEffect(.clear.tint(tint.opacity(0.14)), in: Circle())
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
                "按住时触发 \(voiceProfile.displayName) \(voiceProfile.shortcutDisplayName) " +
                    "并桥接遥控器语音；松开时停止"
            )
            .accessibilityElement()
            .accessibilityLabel(Text("\(voiceProfile.displayName) 语音键，固定核心功能"))
    }
}
