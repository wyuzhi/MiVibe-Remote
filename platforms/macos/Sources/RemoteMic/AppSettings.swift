import Combine
import Foundation

enum VoiceShortcutProfile: String, CaseIterable, Codable, Equatable {
    case codex
    case workBuddy
    case weChat

    var displayName: String {
        switch self {
        case .codex: return "Codex"
        case .workBuddy: return "WorkBuddy"
        case .weChat: return "微信"
        }
    }

    var shortcutDisplayName: String {
        switch self {
        case .codex: return "⌃⇧D"
        case .workBuddy: return "⌘D"
        case .weChat: return "Fn（按住）"
        }
    }

    var readyStatus: String {
        switch self {
        case .codex: return "等待语音键；Codex 使用按住型 ⌃⇧D"
        case .workBuddy: return "等待语音键；WorkBuddy 使用开关型 ⌘D"
        case .weChat: return "等待语音键；微信使用按住 Fn 语音输入文字"
        }
    }

    var next: VoiceShortcutProfile {
        guard let index = Self.allCases.firstIndex(of: self) else {
            return Self.allCases[0]
        }
        return Self.allCases[(index + 1) % Self.allCases.count]
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
        static let headsetCompatibilityEnabled = "headsetCompatibilityEnabled"
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

    @Published var headsetCompatibilityEnabled: Bool {
        didSet { defaults.set(headsetCompatibilityEnabled, forKey: Keys.headsetCompatibilityEnabled) }
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
        headsetCompatibilityEnabled = defaults.object(forKey: Keys.headsetCompatibilityEnabled) == nil
            ? true
            : defaults.bool(forKey: Keys.headsetCompatibilityEnabled)

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
    }

    func action(for button: RemoteButton) -> ButtonAction {
        buttonBindings[button] ?? .disabled
    }

    func setAction(_ action: ButtonAction, for button: RemoteButton) {
        buttonBindings[button] = action
    }

    func shortcut(for button: RemoteButton) -> CustomKeyboardShortcut? {
        buttonShortcuts[button]
    }

    func setShortcut(_ shortcut: CustomKeyboardShortcut?, for button: RemoteButton) {
        buttonShortcuts[button] = shortcut
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

    func applyCodexPreset() {
        applyPreset(.codex)
    }

    func applyWorkBuddyPreset() {
        applyPreset(.workBuddy)
    }

    func applyWeChatPreset() {
        applyPreset(.weChat)
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
        voiceShortcutProfile = profile
        buttonBindings = Self.bindings(for: profile)
        buttonShortcuts = [:]
        secondaryButtonBindings = [:]
        for (button, trigger) in cycleActions {
            setAction(.cyclePreset, for: button, trigger: trigger)
        }
    }

    var activePreset: VoiceShortcutProfile? {
        guard customMappingEnabled,
              buttonShortcuts.isEmpty
        else { return nil }

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
        }
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
