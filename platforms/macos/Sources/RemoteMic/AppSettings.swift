import Combine
import Foundation

enum VoiceShortcutProfile: String, CaseIterable, Codable, Equatable {
    case codex
    case workBuddy
    case weChat
    case custom

    var displayName: String {
        switch self {
        case .codex: return "Codex"
        case .workBuddy: return "WorkBuddy"
        case .weChat: return "微信"
        case .custom: return "自定义"
        }
    }

    var shortcutDisplayName: String {
        switch self {
        case .codex: return "⌃⇧D"
        case .workBuddy: return "⌘D"
        case .weChat: return "Fn（按住）"
        case .custom: return "用户快捷键"
        }
    }

    var readyStatus: String {
        switch self {
        case .codex: return "等待语音键；Codex 使用按住型 ⌃⇧D"
        case .workBuddy: return "等待语音键；WorkBuddy 使用开关型 ⌘D"
        case .weChat: return "等待语音键；微信使用按住 Fn 语音输入文字"
        case .custom: return "等待语音键；使用用户自定义快捷键"
        }
    }

    var next: VoiceShortcutProfile {
        guard let index = Self.allCases.firstIndex(of: self) else {
            return Self.allCases[0]
        }
        return Self.allCases[(index + 1) % Self.allCases.count]
    }
}

enum VoiceShortcutTriggerMode: String, CaseIterable, Codable, Equatable, Identifiable {
    case hold
    case toggle

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .hold: return "按住型"
        case .toggle: return "开关型"
        }
    }

    var helpText: String {
        switch self {
        case .hold: return "按住遥控器语音键时持续按下快捷键，松开时释放。"
        case .toggle: return "按下和松开遥控器语音键时各点按一次快捷键。"
        }
    }
}

struct VoiceShortcutConfiguration: Equatable {
    let profile: VoiceShortcutProfile
    let customShortcut: CustomKeyboardShortcut?
    let customTriggerMode: VoiceShortcutTriggerMode

    var displayName: String {
        guard profile == .custom else { return profile.shortcutDisplayName }
        return customShortcut?.displayName ?? "尚未录入"
    }

    var readyStatus: String {
        guard profile == .custom else { return profile.readyStatus }
        guard let customShortcut else { return "请先录入自定义语音快捷键" }
        return "等待语音键；\(customTriggerMode.displayName) \(customShortcut.displayName)"
    }
}

final class AppSettings: ObservableObject {
    private enum Keys {
        static let gainDB = "gainDB"
        static let selectedAudioDeviceUID = "selectedAudioDeviceUID"
        static let customMappingEnabled = "customMappingEnabled"
        static let legacyExclusiveHID = "exclusiveHID"
        static let buttonBindings = "buttonBindings"
        static let buttonShortcuts = "buttonShortcuts"
        static let secondaryButtonBindings = "secondaryButtonBindings"
        static let peripheralIdentifier = "peripheralIdentifier"
        static let voiceShortcutProfile = "voiceShortcutProfile"
        static let customVoiceShortcut = "customVoiceShortcut"
        static let customVoiceTriggerMode = "customVoiceTriggerMode"
        static let customPresetBindings = "customPresetBindings"
        static let customPresetShortcuts = "customPresetShortcuts"
        static let customPresetSecondaryBindings = "customPresetSecondaryBindings"
        static let headsetCompatibilityEnabled = "headsetCompatibilityEnabled"
        static let computerMicrophonePassthroughEnabled = "computerMicrophonePassthroughEnabled"
    }

    private let defaults: UserDefaults

    @Published var gainDB: Double {
        didSet { defaults.set(gainDB, forKey: Keys.gainDB) }
    }

    @Published var selectedAudioDeviceUID: String {
        didSet { defaults.set(selectedAudioDeviceUID, forKey: Keys.selectedAudioDeviceUID) }
    }

    @Published var customMappingEnabled: Bool {
        didSet { defaults.set(customMappingEnabled, forKey: Keys.customMappingEnabled) }
    }

    @Published var voiceShortcutProfile: VoiceShortcutProfile {
        didSet { defaults.set(voiceShortcutProfile.rawValue, forKey: Keys.voiceShortcutProfile) }
    }

    @Published var customVoiceShortcut: CustomKeyboardShortcut? {
        didSet { saveCustomVoiceShortcut() }
    }

    @Published var customVoiceTriggerMode: VoiceShortcutTriggerMode {
        didSet { defaults.set(customVoiceTriggerMode.rawValue, forKey: Keys.customVoiceTriggerMode) }
    }

    @Published var headsetCompatibilityEnabled: Bool {
        didSet { defaults.set(headsetCompatibilityEnabled, forKey: Keys.headsetCompatibilityEnabled) }
    }

    @Published var computerMicrophonePassthroughEnabled: Bool {
        didSet {
            defaults.set(
                computerMicrophonePassthroughEnabled,
                forKey: Keys.computerMicrophonePassthroughEnabled
            )
        }
    }

    @Published var buttonBindings: [RemoteButton: ButtonAction] {
        didSet { saveBindings() }
    }

    @Published var buttonShortcuts: [RemoteButton: CustomKeyboardShortcut] {
        didSet { saveShortcuts() }
    }

    @Published var secondaryButtonBindings: [RemoteButton: [ButtonTrigger: ConfiguredButtonAction]] {
        didSet { saveSecondaryBindings() }
    }

    private var customPresetBindings: [RemoteButton: ButtonAction]?
    private var customPresetShortcuts: [RemoteButton: CustomKeyboardShortcut] = [:]
    private var customPresetSecondaryBindings: [RemoteButton: [ButtonTrigger: ConfiguredButtonAction]] = [:]

    var peripheralIdentifier: UUID? {
        get {
            guard let raw = defaults.string(forKey: Keys.peripheralIdentifier) else { return nil }
            return UUID(uuidString: raw)
        }
        set {
            defaults.set(newValue?.uuidString, forKey: Keys.peripheralIdentifier)
        }
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        gainDB = defaults.object(forKey: Keys.gainDB) == nil
            ? 10.0
            : defaults.double(forKey: Keys.gainDB)
        selectedAudioDeviceUID = defaults.string(forKey: Keys.selectedAudioDeviceUID) ?? ""
        if defaults.object(forKey: Keys.customMappingEnabled) != nil {
            customMappingEnabled = defaults.bool(forKey: Keys.customMappingEnabled)
        } else if defaults.object(forKey: Keys.legacyExclusiveHID) != nil {
            customMappingEnabled = defaults.bool(forKey: Keys.legacyExclusiveHID)
        } else {
            customMappingEnabled = true
        }
        voiceShortcutProfile = defaults.string(forKey: Keys.voiceShortcutProfile)
            .flatMap(VoiceShortcutProfile.init(rawValue:))
            ?? .codex
        customVoiceShortcut = defaults.data(forKey: Keys.customVoiceShortcut)
            .flatMap { try? JSONDecoder().decode(CustomKeyboardShortcut.self, from: $0) }
            ?? CustomKeyboardShortcut(
                keyCode: 2,
                modifierFlags: [.control, .shift],
                keyLabel: "D"
            )
        customVoiceTriggerMode = defaults.string(forKey: Keys.customVoiceTriggerMode)
            .flatMap(VoiceShortcutTriggerMode.init(rawValue:))
            ?? .hold
        headsetCompatibilityEnabled = defaults.object(forKey: Keys.headsetCompatibilityEnabled) == nil
            ? true
            : defaults.bool(forKey: Keys.headsetCompatibilityEnabled)
        computerMicrophonePassthroughEnabled = defaults.bool(
            forKey: Keys.computerMicrophonePassthroughEnabled
        )

        if
            let data = defaults.data(forKey: Keys.buttonBindings),
            let decoded = try? JSONDecoder().decode([String: ButtonAction].self, from: data)
        {
            let savedBindings = Self.defaultBindings.merging(
                Dictionary(uniqueKeysWithValues: decoded.compactMap { key, value in
                    RemoteButton(rawValue: key).map { ($0, value) }
                })
            ) { _, saved in saved }
            buttonBindings = savedBindings == Self.legacyVibeCodingBindings
                ? Self.codexBindings
                : savedBindings
        } else {
            buttonBindings = Self.defaultBindings
        }

        if
            let data = defaults.data(forKey: Keys.buttonShortcuts),
            let decoded = try? JSONDecoder().decode([String: CustomKeyboardShortcut].self, from: data)
        {
            buttonShortcuts = Dictionary(uniqueKeysWithValues: decoded.compactMap { key, value in
                RemoteButton(rawValue: key).map { ($0, value) }
            })
        } else {
            buttonShortcuts = [:]
        }

        if
            let data = defaults.data(forKey: Keys.secondaryButtonBindings),
            let decoded = try? JSONDecoder().decode(
                [String: [String: ConfiguredButtonAction]].self,
                from: data
            )
        {
            secondaryButtonBindings = Dictionary(uniqueKeysWithValues: decoded.compactMap { buttonKey, bindings in
                guard let button = RemoteButton(rawValue: buttonKey) else { return nil }
                let parsed = Dictionary(uniqueKeysWithValues: bindings.compactMap { triggerKey, binding in
                    ButtonTrigger(rawValue: triggerKey).map { ($0, binding) }
                })
                return parsed.isEmpty ? nil : (button, parsed)
            })
        } else {
            secondaryButtonBindings = [:]
        }

        customPresetBindings = Self.decodeBindings(
            defaults.data(forKey: Keys.customPresetBindings)
        )
        customPresetShortcuts = Self.decodeShortcuts(
            defaults.data(forKey: Keys.customPresetShortcuts)
        )
        customPresetSecondaryBindings = Self.decodeSecondaryBindings(
            defaults.data(forKey: Keys.customPresetSecondaryBindings)
        )
    }

    func action(for button: RemoteButton) -> ButtonAction {
        buttonBindings[button] ?? .disabled
    }

    func setAction(_ action: ButtonAction, for button: RemoteButton) {
        buttonBindings[button] = action
        saveCustomPresetIfActive()
    }

    func shortcut(for button: RemoteButton) -> CustomKeyboardShortcut? {
        buttonShortcuts[button]
    }

    func setShortcut(_ shortcut: CustomKeyboardShortcut?, for button: RemoteButton) {
        buttonShortcuts[button] = shortcut
        saveCustomPresetIfActive()
    }

    func configuredAction(
        for button: RemoteButton,
        trigger: ButtonTrigger
    ) -> ConfiguredButtonAction {
        if trigger == .singleClick {
            return ConfiguredButtonAction(
                action: action(for: button),
                shortcut: shortcut(for: button)
            )
        }
        return secondaryButtonBindings[button]?[trigger] ?? .disabled
    }

    func setAction(_ action: ButtonAction, for button: RemoteButton, trigger: ButtonTrigger) {
        guard trigger != .singleClick else {
            setAction(action, for: button)
            if action != .customShortcut { setShortcut(nil, for: button) }
            return
        }

        var bindings = secondaryButtonBindings[button] ?? [:]
        if action == .disabled {
            bindings.removeValue(forKey: trigger)
        } else {
            let shortcut = action == .customShortcut ? bindings[trigger]?.shortcut : nil
            bindings[trigger] = ConfiguredButtonAction(action: action, shortcut: shortcut)
        }
        secondaryButtonBindings[button] = bindings.isEmpty ? nil : bindings
        saveCustomPresetIfActive()
    }

    func setShortcut(
        _ shortcut: CustomKeyboardShortcut?,
        for button: RemoteButton,
        trigger: ButtonTrigger
    ) {
        guard trigger != .singleClick else {
            setShortcut(shortcut, for: button)
            return
        }
        guard var bindings = secondaryButtonBindings[button], var binding = bindings[trigger] else {
            return
        }
        binding.shortcut = shortcut
        bindings[trigger] = binding
        secondaryButtonBindings[button] = bindings
        saveCustomPresetIfActive()
    }

    func hasSecondaryAction(for button: RemoteButton) -> Bool {
        [.doubleClick, .longPress].contains { trigger in
            configuredAction(for: button, trigger: trigger).action != .disabled
        }
    }

    func resetBindings() {
        voiceShortcutProfile = .codex
        buttonBindings = Self.defaultBindings
        buttonShortcuts = [:]
        secondaryButtonBindings = [:]
    }

    var voiceShortcutConfiguration: VoiceShortcutConfiguration {
        VoiceShortcutConfiguration(
            profile: voiceShortcutProfile,
            customShortcut: customVoiceShortcut,
            customTriggerMode: customVoiceTriggerMode
        )
    }

    var voiceShortcutDisplayName: String {
        voiceShortcutConfiguration.displayName
    }

    func selectVoiceShortcutProfile(_ profile: VoiceShortcutProfile) {
        voiceShortcutProfile = profile
    }

    func saveCurrentAsCustomPreset() {
        customPresetBindings = buttonBindings
        customPresetShortcuts = buttonShortcuts
        customPresetSecondaryBindings = secondaryButtonBindings
        saveCustomPreset()
        voiceShortcutProfile = .custom
    }

    func applyCodexPreset() {
        applyPreset(.codex)
    }

    func applyWorkBuddyPreset() {
        applyPreset(.workBuddy)
    }

    func applyWeChatPreset() {
        applyPreset(.weChat)
    }

    func applyCustomPreset() {
        applyPreset(.custom)
    }

    @discardableResult
    func cyclePreset() -> VoiceShortcutProfile {
        let nextProfile = voiceShortcutProfile.next
        applyPreset(nextProfile)
        return nextProfile
    }

    func applyPreset(
        _ profile: VoiceShortcutProfile,
        preservingCycleActions: Bool = true
    ) {
        let cycleActions = preservingCycleActions ? configuredCycleActions : []
        customMappingEnabled = true
        if profile == .custom {
            if let customPresetBindings {
                buttonBindings = customPresetBindings
                buttonShortcuts = customPresetShortcuts
                secondaryButtonBindings = customPresetSecondaryBindings
            } else {
                customPresetBindings = buttonBindings
                customPresetShortcuts = buttonShortcuts
                customPresetSecondaryBindings = secondaryButtonBindings
                saveCustomPreset()
            }
            voiceShortcutProfile = .custom
        } else {
            voiceShortcutProfile = profile
            buttonBindings = Self.bindings(for: profile)
            buttonShortcuts = [:]
            secondaryButtonBindings = [:]
        }
        for (button, trigger) in cycleActions {
            setAction(.cyclePreset, for: button, trigger: trigger)
        }
        if profile == .custom {
            customPresetBindings = buttonBindings
            customPresetShortcuts = buttonShortcuts
            customPresetSecondaryBindings = secondaryButtonBindings
            saveCustomPreset()
        }
    }

    var activePreset: VoiceShortcutProfile? {
        guard customMappingEnabled else { return nil }
        if voiceShortcutProfile == .custom {
            return customPresetMatchesCurrentBindings ? .custom : nil
        }
        guard buttonShortcuts.isEmpty else { return nil }

        let expected = Self.bindings(for: voiceShortcutProfile)
        let mainBindingsMatch = RemoteButton.allCases.allSatisfy { button in
            let action = action(for: button)
            return action == expected[button] || action == .cyclePreset
        }
        let secondaryBindingsAreOnlyPresetSwitches = secondaryButtonBindings.values
            .flatMap(\.values)
            .allSatisfy { $0.action == .cyclePreset }
        return mainBindingsMatch && secondaryBindingsAreOnlyPresetSwitches
            ? voiceShortcutProfile
            : nil
    }

    private var customPresetMatchesCurrentBindings: Bool {
        guard let customPresetBindings else { return false }
        return buttonBindings == customPresetBindings
            && buttonShortcuts == customPresetShortcuts
            && secondaryButtonBindings == customPresetSecondaryBindings
    }

    private var configuredCycleActions: [(RemoteButton, ButtonTrigger)] {
        RemoteButton.allCases.flatMap { button in
            ButtonTrigger.allCases.compactMap { trigger in
                configuredAction(for: button, trigger: trigger).action == .cyclePreset
                    ? (button, trigger)
                    : nil
            }
        }
    }

    private static func bindings(
        for profile: VoiceShortcutProfile
    ) -> [RemoteButton: ButtonAction] {
        switch profile {
        case .codex:
            return codexBindings
        case .workBuddy:
            return workBuddyBindings
        case .weChat:
            return weChatBindings
        case .custom:
            return defaultBindings
        }
    }

    private func saveCustomVoiceShortcut() {
        guard let customVoiceShortcut,
              let data = try? JSONEncoder().encode(customVoiceShortcut)
        else {
            defaults.removeObject(forKey: Keys.customVoiceShortcut)
            return
        }
        defaults.set(data, forKey: Keys.customVoiceShortcut)
    }

    private func saveCustomPresetIfActive() {
        guard voiceShortcutProfile == .custom else { return }
        customPresetBindings = buttonBindings
        customPresetShortcuts = buttonShortcuts
        customPresetSecondaryBindings = secondaryButtonBindings
        saveCustomPreset()
    }

    private func saveCustomPreset() {
        if let customPresetBindings {
            let raw = Dictionary(uniqueKeysWithValues: customPresetBindings.map {
                ($0.key.rawValue, $0.value)
            })
            if let data = try? JSONEncoder().encode(raw) {
                defaults.set(data, forKey: Keys.customPresetBindings)
            }
        }
        let shortcuts = Dictionary(uniqueKeysWithValues: customPresetShortcuts.map {
            ($0.key.rawValue, $0.value)
        })
        if let data = try? JSONEncoder().encode(shortcuts) {
            defaults.set(data, forKey: Keys.customPresetShortcuts)
        }
        let secondary = Dictionary(uniqueKeysWithValues: customPresetSecondaryBindings.map {
            button, bindings in
            (
                button.rawValue,
                Dictionary(uniqueKeysWithValues: bindings.map { ($0.key.rawValue, $0.value) })
            )
        })
        if let data = try? JSONEncoder().encode(secondary) {
            defaults.set(data, forKey: Keys.customPresetSecondaryBindings)
        }
    }

    private static func decodeBindings(_ data: Data?) -> [RemoteButton: ButtonAction]? {
        guard let data,
              let decoded = try? JSONDecoder().decode([String: ButtonAction].self, from: data)
        else { return nil }
        return Dictionary(uniqueKeysWithValues: decoded.compactMap { key, value in
            RemoteButton(rawValue: key).map { ($0, value) }
        })
    }

    private static func decodeShortcuts(_ data: Data?) -> [RemoteButton: CustomKeyboardShortcut] {
        guard let data,
              let decoded = try? JSONDecoder().decode([String: CustomKeyboardShortcut].self, from: data)
        else { return [:] }
        return Dictionary(uniqueKeysWithValues: decoded.compactMap { key, value in
            RemoteButton(rawValue: key).map { ($0, value) }
        })
    }

    private static func decodeSecondaryBindings(
        _ data: Data?
    ) -> [RemoteButton: [ButtonTrigger: ConfiguredButtonAction]] {
        guard let data,
              let decoded = try? JSONDecoder().decode(
                  [String: [String: ConfiguredButtonAction]].self,
                  from: data
              )
        else { return [:] }
        return Dictionary(uniqueKeysWithValues: decoded.compactMap { buttonKey, bindings in
            guard let button = RemoteButton(rawValue: buttonKey) else { return nil }
            let parsed = Dictionary(uniqueKeysWithValues: bindings.compactMap { triggerKey, binding in
                ButtonTrigger(rawValue: triggerKey).map { ($0, binding) }
            })
            return parsed.isEmpty ? nil : (button, parsed)
        })
    }

    private func saveBindings() {
        let raw = Dictionary(uniqueKeysWithValues: buttonBindings.map { ($0.key.rawValue, $0.value) })
        if let data = try? JSONEncoder().encode(raw) {
            defaults.set(data, forKey: Keys.buttonBindings)
        }
    }

    private func saveShortcuts() {
        let raw = Dictionary(uniqueKeysWithValues: buttonShortcuts.map { ($0.key.rawValue, $0.value) })
        if let data = try? JSONEncoder().encode(raw) {
            defaults.set(data, forKey: Keys.buttonShortcuts)
        }
    }

    private func saveSecondaryBindings() {
        let raw = Dictionary(uniqueKeysWithValues: secondaryButtonBindings.map { button, bindings in
            (
                button.rawValue,
                Dictionary(uniqueKeysWithValues: bindings.map { ($0.key.rawValue, $0.value) })
            )
        })
        if let data = try? JSONEncoder().encode(raw) {
            defaults.set(data, forKey: Keys.secondaryButtonBindings)
        }
    }

    static let standardBindings: [RemoteButton: ButtonAction] = [
        .power: .escape,
        .up: .arrowUp,
        .left: .arrowLeft,
        .ok: .returnKey,
        .right: .arrowRight,
        .down: .arrowDown,
        .back: .deleteBackward,
        .volumeUp: .volumeUp,
        .home: .showDesktop,
        .volumeDown: .volumeDown,
        .menu: .contextMenu,
        .tv: .appSwitcher,
    ]

    static let legacyVibeCodingBindings: [RemoteButton: ButtonAction] = standardBindings.merging([
        .home: .openCodex,
        .menu: .escape,
    ]) { _, vibeAction in vibeAction }

    static let codexBindings: [RemoteButton: ButtonAction] = standardBindings.merging([
        .power: .openCodex,
        .menu: .escape,
    ]) { _, presetAction in presetAction }

    static let workBuddyBindings: [RemoteButton: ButtonAction] = standardBindings.merging([
        .power: .openWorkBuddy,
        .menu: .escape,
    ]) { _, presetAction in presetAction }

    static let weChatBindings: [RemoteButton: ButtonAction] = standardBindings.merging([
        .power: .openWeChat,
        .menu: .escape,
    ]) { _, presetAction in presetAction }

    static let defaultBindings = codexBindings
}
