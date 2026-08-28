import AppKit
import Foundation
import Testing
@testable import RemoteMic

@Suite("Remote buttons")
struct RemoteButtonsTests {
    @Test func presetApplicationsHaveExpectedNamesAndBundleIdentifiers() {
        let mappings = Dictionary(uniqueKeysWithValues: PresetApplication.allCases.map {
            ($0.displayName, $0.bundleIdentifier)
        })
        #expect(mappings == [
            "MiVibe Remote": "com.mivibe.remote",
            "Codex": "com.openai.codex",
            "WorkBuddy": "com.workbuddy.workbuddy",
            "Claude": "com.anthropic.claudefordesktop",
            "cmux": "com.cmuxterm.app",
            "微信": "com.tencent.xinWeChat",
            "Cursor": "com.todesktop.230313mzl4w4u92",
            "Xcode": "com.apple.dt.Xcode",
            "Slack": "com.tinyspeck.slackmacgap",
            "企业微信": "com.tencent.WeWorkMac",
            "网易云音乐": "com.netease.163music",
            "Chrome": "com.google.Chrome",
            "Safari": "com.apple.Safari",
            "Zed": "dev.zed.Zed",
        ])
        #expect(Set(ButtonAction.allCases.compactMap(\.presetApplication)) == Set(PresetApplication.allCases))
    }

    @Test func remoteMicApplicationActionIsAlwaysAvailable() {
        #expect(PresetApplication.installedBundleIdentifiers.contains(
            PresetApplication.remoteMic.bundleIdentifier
        ))
        #expect(ButtonAction.pickerActions(
            installedBundleIdentifiers: PresetApplication.installedBundleIdentifiers,
            current: .escape
        ).contains(.openRemoteMic))
        #expect(ButtonAction.openRemoteMic.displayName == "打开 MiVibe Remote")
    }

    @Test func pickerHidesUnavailableApplicationsAndPreservesCurrentMissingSelection() {
        let installed = Set([PresetApplication.codex.bundleIdentifier])
        let normalSelection = ButtonAction.pickerActions(
            installedBundleIdentifiers: installed,
            current: .escape
        )
        #expect(normalSelection.contains(.openCodex))
        #expect(!normalSelection.contains(.openClaude))

        let missingSelection = ButtonAction.pickerActions(
            installedBundleIdentifiers: installed,
            current: .openClaude
        )
        #expect(missingSelection.contains(.openClaude))
        #expect(!missingSelection.contains(.openXcode))
    }

    @Test func applicationActionsNeverRepeat() {
        let applicationActions = ButtonAction.allCases.filter { $0.presetApplication != nil }
        #expect(applicationActions.count == PresetApplication.allCases.count)
        #expect(applicationActions.allSatisfy { !$0.allowsRepeat })
        #expect(!ButtonAction.cyclePreset.allowsRepeat)
    }

    @Test func cyclePresetMovesInDeclaredOrderAndWrapsAround() {
        #expect(VoiceShortcutProfile.codex.next == .workBuddy)
        #expect(VoiceShortcutProfile.workBuddy.next == .weChat)
        #expect(VoiceShortcutProfile.weChat.next == .custom)
        #expect(VoiceShortcutProfile.custom.next == .codex)
    }

    @Test func buttonActionsKeepRawValueCodableCompatibility() throws {
        let legacy = try JSONDecoder().decode(ButtonAction.self, from: Data(#""appSwitcher""#.utf8))
        #expect(legacy == .appSwitcher)

        let custom = try JSONDecoder().decode(ButtonAction.self, from: Data(#""customShortcut""#.utf8))
        #expect(custom == .customShortcut)

        for action in ButtonAction.allCases {
            let encoded = try JSONEncoder().encode(action)
            #expect(try JSONDecoder().decode(ButtonAction.self, from: encoded) == action)
        }
    }

    @Test func customShortcutNormalizesDisplaysAndConvertsModifiers() throws {
        let shortcut = CustomKeyboardShortcut(
            keyCode: 40,
            modifierFlags: [.capsLock, .shift, .command],
            keyLabel: "K"
        )

        #expect(shortcut.displayName == "⇧⌘K")
        #expect(shortcut.modifierFlags == [.shift, .command])
        #expect(shortcut.cgEventFlags == [.maskShift, .maskCommand])
        #expect(try JSONDecoder().decode(
            CustomKeyboardShortcut.self,
            from: JSONEncoder().encode(shortcut)
        ) == shortcut)
    }

    @Test func customShortcutPostsRecordedKeyAndRequiresAccessibility() {
        let shortcut = CustomKeyboardShortcut(
            keyCode: 40,
            modifierFlags: [.control, .option],
            keyLabel: "K"
        )
        var posted: (CGKeyCode, CGEventFlags)?

        #expect(KeyboardInjector.send(
            .customShortcut,
            shortcut: shortcut,
            accessibilityTrusted: { true },
            keyPoster: { posted = ($0, $1) }
        ))
        #expect(posted?.0 == 40)
        #expect(posted?.1 == [.maskControl, .maskAlternate])

        posted = nil
        #expect(!KeyboardInjector.send(
            .customShortcut,
            shortcut: shortcut,
            accessibilityTrusted: { false },
            keyPoster: { posted = ($0, $1) }
        ))
        #expect(posted == nil)
    }

    @Test func unconfiguredCustomShortcutDoesNotReportPermissionFailure() {
        #expect(KeyboardInjector.send(
            .customShortcut,
            accessibilityTrusted: { false }
        ))
    }

    @Test func deletePostsDirectlyToTheFrontmostApplication() {
        var globalPost: (CGKeyCode, CGEventFlags)?
        var frontmostPost: (CGKeyCode, CGEventFlags)?

        #expect(KeyboardInjector.send(
            .deleteBackward,
            accessibilityTrusted: { true },
            keyPoster: { globalPost = ($0, $1) },
            frontmostKeyPoster: { frontmostPost = ($0, $1) }
        ))
        #expect(globalPost == nil)
        #expect(frontmostPost?.0 == 51)
        #expect(frontmostPost?.1 == [])
    }

    @Test func missingApplicationIsHandledWithoutPermissionFailure() {
        #expect(KeyboardInjector.send(.openCodex, applicationURL: { _ in nil }))
    }

    @Test func applicationLaunchFailureIsHandledWithoutPermissionFailure() {
        struct LaunchFailure: Error {}
        var attemptedApplication: PresetApplication?

        let handled = KeyboardInjector.send(
            .openCodex,
            applicationURL: { _ in URL(fileURLWithPath: "/Applications/Codex.app") },
            applicationOpener: { _, application, completion in
                attemptedApplication = application
                completion(LaunchFailure())
            }
        )

        #expect(handled)
        #expect(attemptedApplication == .codex)
    }

    @Test func tvDefaultRemainsAppSwitcher() {
        #expect(AppSettings.defaultBindings[.tv] == .appSwitcher)
    }

    @Test func codexPresetOpensCodexAndKeepsNavigationAndSend() throws {
        #expect(AppSettings.codexBindings[.power] == .openCodex)
        #expect(AppSettings.codexBindings[.home] == .showDesktop)
        #expect(AppSettings.codexBindings[.ok] == .returnKey)
        #expect(AppSettings.codexBindings[.up] == .arrowUp)
        #expect(AppSettings.codexBindings[.down] == .arrowDown)
        #expect(AppSettings.codexBindings[.back] == .deleteBackward)
        #expect(AppSettings.codexBindings[.menu] == .escape)

        let suiteName = "RemoteMicTests.codexPreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)
        #expect(settings.customMappingEnabled)
        #expect(settings.voiceShortcutProfile == .codex)
        #expect(settings.action(for: .power) == .openCodex)
        #expect(settings.action(for: .menu) == .escape)
        settings.setAction(.openClaude, for: .power)
        settings.setAction(.openCursor, for: .tv, trigger: .doubleClick)

        settings.applyCodexPreset()
        #expect(settings.activePreset == .codex)

        #expect(settings.customMappingEnabled)
        #expect(settings.voiceShortcutProfile == .codex)
        #expect(settings.action(for: .power) == .openCodex)
        #expect(settings.action(for: .ok) == .returnKey)
        #expect(settings.action(for: .back) == .deleteBackward)
        #expect(!settings.hasSecondaryAction(for: .tv))
    }

    @Test func workBuddyPresetOpensWorkBuddyAndUsesItsVoiceProfile() throws {
        #expect(AppSettings.workBuddyBindings[.power] == .openWorkBuddy)
        #expect(AppSettings.workBuddyBindings[.home] == .showDesktop)
        #expect(AppSettings.workBuddyBindings[.ok] == .returnKey)
        #expect(AppSettings.workBuddyBindings[.back] == .deleteBackward)
        #expect(AppSettings.workBuddyBindings[.menu] == .escape)

        let suiteName = "RemoteMicTests.workBuddyPreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)

        settings.applyWorkBuddyPreset()
        #expect(settings.activePreset == .workBuddy)

        #expect(settings.customMappingEnabled)
        #expect(settings.voiceShortcutProfile == .workBuddy)
        #expect(settings.action(for: .power) == .openWorkBuddy)
        #expect(settings.action(for: .ok) == .returnKey)
        #expect(settings.action(for: .back) == .deleteBackward)

        let restored = AppSettings(defaults: defaults)
        #expect(restored.voiceShortcutProfile == .workBuddy)
        #expect(restored.action(for: .power) == .openWorkBuddy)
    }

    @Test func weChatPresetOpensWeChatAndUsesSystemDictation() throws {
        #expect(AppSettings.weChatBindings[.power] == .openWeChat)
        #expect(AppSettings.weChatBindings[.home] == .showDesktop)
        #expect(AppSettings.weChatBindings[.ok] == .returnKey)
        #expect(AppSettings.weChatBindings[.back] == .deleteBackward)
        #expect(AppSettings.weChatBindings[.menu] == .escape)

        let suiteName = "RemoteMicTests.weChatPreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)

        settings.applyWeChatPreset()
        #expect(settings.activePreset == .weChat)
        #expect(settings.voiceShortcutProfile == .weChat)
        #expect(settings.action(for: .power) == .openWeChat)
        #expect(settings.action(for: .ok) == .returnKey)
        #expect(settings.action(for: .back) == .deleteBackward)

        let restored = AppSettings(defaults: defaults)
        #expect(restored.voiceShortcutProfile == .weChat)
        #expect(restored.action(for: .power) == .openWeChat)
    }

    @Test func cyclePresetKeepsEveryConfiguredCycleTrigger() throws {
        let suiteName = "RemoteMicTests.cyclePreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)

        settings.setAction(.cyclePreset, for: .tv)
        settings.setAction(.cyclePreset, for: .menu, trigger: .doubleClick)

        #expect(settings.activePreset == .codex)
        #expect(settings.cyclePreset() == .workBuddy)
        #expect(settings.voiceShortcutProfile == .workBuddy)
        #expect(settings.action(for: .power) == .openWorkBuddy)
        #expect(settings.action(for: .tv) == .cyclePreset)
        #expect(settings.configuredAction(
            for: .menu,
            trigger: .doubleClick
        ).action == .cyclePreset)
        #expect(settings.activePreset == .workBuddy)

        #expect(settings.cyclePreset() == .weChat)
        #expect(settings.action(for: .power) == .openWeChat)
        #expect(settings.action(for: .tv) == .cyclePreset)
        #expect(settings.activePreset == .weChat)

        #expect(settings.cyclePreset() == .custom)
        #expect(settings.action(for: .power) == .openWeChat)
        #expect(settings.action(for: .tv) == .cyclePreset)
        #expect(settings.activePreset == .custom)

        #expect(settings.cyclePreset() == .codex)
        #expect(settings.action(for: .power) == .openCodex)
        #expect(settings.action(for: .tv) == .cyclePreset)
        #expect(settings.activePreset == .codex)
    }

    @Test func customPresetPersistsMappingsVoiceShortcutAndTriggerMode() throws {
        let suiteName = "RemoteMicTests.customPreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)
        let shortcut = CustomKeyboardShortcut(
            keyCode: 40,
            modifierFlags: [.control, .option],
            keyLabel: "K"
        )

        settings.setAction(.openClaude, for: .power)
        settings.customVoiceShortcut = shortcut
        settings.customVoiceTriggerMode = .toggle
        settings.saveCurrentAsCustomPreset()
        settings.applyCodexPreset()
        settings.applyCustomPreset()

        #expect(settings.activePreset == .custom)
        #expect(settings.action(for: .power) == .openClaude)
        #expect(settings.voiceShortcutProfile == .custom)
        #expect(settings.voiceShortcutConfiguration.customShortcut == shortcut)
        #expect(settings.voiceShortcutConfiguration.customTriggerMode == .toggle)

        let restored = AppSettings(defaults: defaults)
        restored.applyCustomPreset()
        #expect(restored.action(for: .power) == .openClaude)
        #expect(restored.voiceShortcutConfiguration.customShortcut == shortcut)
        #expect(restored.voiceShortcutConfiguration.customTriggerMode == .toggle)
    }

    @Test func selectingCustomVoiceDoesNotOverwriteTheSavedCustomPreset() throws {
        let suiteName = "RemoteMicTests.customVoiceKeepsPreset.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let settings = AppSettings(defaults: defaults)

        settings.setAction(.openClaude, for: .power)
        settings.saveCurrentAsCustomPreset()
        settings.applyCodexPreset()

        settings.selectVoiceShortcutProfile(.custom)
        #expect(settings.action(for: .power) == .openCodex)
        #expect(settings.activePreset == nil)

        settings.applyCustomPreset()
        #expect(settings.action(for: .power) == .openClaude)
        #expect(settings.activePreset == .custom)
    }

    @Test func customizedPresetIsClearlyReportedAndPersistentVirtualInputDefaultsOn() throws {
        let suite = "RemoteButtonsTests-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)

        #expect(settings.activePreset == .codex)
        #expect(settings.headsetCompatibilityEnabled)

        settings.setAction(.openWorkBuddy, for: .tv)
        #expect(settings.activePreset == nil)

        settings.headsetCompatibilityEnabled = false
        let restored = AppSettings(defaults: defaults)
        #expect(!restored.headsetCompatibilityEnabled)
    }

    @Test func persistentVirtualInputKeepsTheVersion016Preference() throws {
        let suite = "RemoteButtonsTests.persistentInput-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(false, forKey: "headsetCompatibilityEnabled")

        let settings = AppSettings(defaults: defaults)

        #expect(!settings.headsetCompatibilityEnabled)
    }

    @Test func computerMicrophonePassthroughIsPrivacyFirstAndPersistent() throws {
        let suite = "RemoteButtonsTests.microphonePassthrough-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        let settings = AppSettings(defaults: defaults)
        #expect(!settings.computerMicrophonePassthroughEnabled)

        settings.computerMicrophonePassthroughEnabled = true
        let restored = AppSettings(defaults: defaults)
        #expect(restored.computerMicrophonePassthroughEnabled)
    }

    @Test func migratesTheOriginalHomeKeyVibePresetToThePowerKey() throws {
        let suiteName = "RemoteMicTests.vibePresetMigration.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let raw = Dictionary(uniqueKeysWithValues: AppSettings.legacyVibeCodingBindings.map {
            ($0.key.rawValue, $0.value)
        })
        defaults.set(try JSONEncoder().encode(raw), forKey: "buttonBindings")

        let settings = AppSettings(defaults: defaults)

        #expect(settings.action(for: .power) == .openCodex)
        #expect(settings.action(for: .home) == .showDesktop)
        #expect(settings.action(for: .ok) == .returnKey)
        #expect(settings.action(for: .back) == .deleteBackward)
    }

    @Test func mapsActiveUsagesToButtonsForUIFeedback() {
        #expect(RemoteButton.buttons(for: [0x52, 0x65, 0xFFFF]) == Set<RemoteButton>([.up, .menu]))
    }

    @Test func HIDCallbacksDoNotDeferReportHandling() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: root.appendingPathComponent("Sources/RemoteMic/HIDRemoteMonitor.swift"), encoding: .utf8)
        #expect(!source.contains("DispatchQueue.main.async"))
    }

    @Test func parsesRC003ReportOneUsages() {
        let data = Data([0xF1, 0x00, 0x80, 0x00, 0x00, 0x00])
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: data) == Set([UInt16(0xF1), UInt16(0x80)]))
    }

    @Test func acceptsFirmwareReportWithIncludedID() {
        let data = Data([0x01, 0x35, 0x00, 0x00, 0x00, 0x00, 0x00])
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: data) == Set([UInt16(0x35)]))
    }

    @Test func rejectsOtherReportsAndMalformedPayloads() {
        #expect(RemoteHIDReportParser.usages(reportID: 2, data: Data([0, 0])) == nil)
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: Data()) == nil)
        #expect(RemoteHIDReportParser.usages(reportID: 1, data: Data([1])) == nil)
    }

    @Test func everyKnownUsageHasDefaultBinding() {
        for button in Set(RemoteButton.usageMap.values) {
            #expect(AppSettings.defaultBindings[button] != nil, Comment(rawValue: button.rawValue))
        }
    }

    @Test func usesVerifiedRC003UsageTable() {
        #expect(RemoteButton.usageMap == [
            0x28: .ok,
            0x35: .tv,
            0x4A: .home,
            0x4F: .right,
            0x50: .left,
            0x51: .down,
            0x52: .up,
            0x65: .menu,
            0x66: .power,
            0x80: .volumeUp,
            0x81: .volumeDown,
            0xF1: .back,
        ])
    }

    @Test func HIDPermissionGateFailsClosed() {
        #expect(!HIDPermissionGate.canMonitor(
            mappingEnabled: true,
            inputMonitoringGranted: false,
            accessibilityGranted: true
        ))
        #expect(!HIDPermissionGate.canMonitor(
            mappingEnabled: true,
            inputMonitoringGranted: true,
            accessibilityGranted: false
        ))
        #expect(HIDPermissionGate.canMonitor(
            mappingEnabled: true,
            inputMonitoringGranted: true,
            accessibilityGranted: true
        ))
    }

    @Test func HIDPermissionRequestsAreSequentialAndOptIn() {
        #expect(HIDPermissionGate.nextPermissionRequest(
            mappingEnabled: false,
            inputMonitoringGranted: false,
            accessibilityGranted: false
        ) == .none)
        #expect(HIDPermissionGate.nextPermissionRequest(
            mappingEnabled: true,
            inputMonitoringGranted: false,
            accessibilityGranted: false
        ) == .inputMonitoring)
        #expect(HIDPermissionGate.nextPermissionRequest(
            mappingEnabled: true,
            inputMonitoringGranted: true,
            accessibilityGranted: false
        ) == .accessibility)
        #expect(HIDPermissionGate.nextPermissionRequest(
            mappingEnabled: true,
            inputMonitoringGranted: true,
            accessibilityGranted: true
        ) == .none)
    }

    @Test func HIDPermissionsRecoverOnlyAfterARealRuntimePermissionChange() {
        let denied = HIDPermissionSnapshot(
            inputMonitoringGranted: false,
            accessibilityGranted: false
        )
        let granted = HIDPermissionSnapshot(
            inputMonitoringGranted: true,
            accessibilityGranted: true
        )

        #expect(HIDPermissionRecoveryPolicy.shouldReapply(
            started: true,
            mappingEnabled: true,
            previous: denied,
            current: granted
        ))
        #expect(!HIDPermissionRecoveryPolicy.shouldReapply(
            started: true,
            mappingEnabled: true,
            previous: granted,
            current: granted
        ))
        #expect(!HIDPermissionRecoveryPolicy.shouldReapply(
            started: false,
            mappingEnabled: true,
            previous: denied,
            current: granted
        ))
        #expect(!HIDPermissionRecoveryPolicy.shouldReapply(
            started: true,
            mappingEnabled: false,
            previous: denied,
            current: granted
        ))
    }

    @Test func savedBindingsMergeWithDefaults() throws {
        let suiteName = "RemoteMicTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }

        let saved = try JSONEncoder().encode([RemoteButton.back.rawValue: ButtonAction.disabled])
        defaults.set(saved, forKey: "buttonBindings")
        let settings = AppSettings(defaults: defaults)

        #expect(settings.action(for: .back) == .disabled)
        #expect(settings.action(for: .up) == .arrowUp)
    }

    @Test func customShortcutsPersistAndResetWithBindings() throws {
        let suiteName = "RemoteMicTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let shortcut = CustomKeyboardShortcut(
            keyCode: 8,
            modifierFlags: [.command, .shift],
            keyLabel: "C"
        )

        let settings = AppSettings(defaults: defaults)
        settings.setAction(.customShortcut, for: .tv)
        settings.setShortcut(shortcut, for: .tv)

        let restored = AppSettings(defaults: defaults)
        #expect(restored.action(for: .tv) == .customShortcut)
        #expect(restored.shortcut(for: .tv) == shortcut)

        restored.resetBindings()
        #expect(restored.action(for: .tv) == .appSwitcher)
        #expect(restored.shortcut(for: .tv) == nil)
    }

    @Test func secondaryTriggerActionsPersistAndResetWithoutChangingSingleClick() throws {
        let suiteName = "RemoteMicTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let shortcut = CustomKeyboardShortcut(
            keyCode: 9,
            modifierFlags: [.control, .command],
            keyLabel: "V"
        )

        let settings = AppSettings(defaults: defaults)
        settings.setAction(.openCodex, for: .tv, trigger: .doubleClick)
        settings.setAction(.customShortcut, for: .tv, trigger: .longPress)
        settings.setShortcut(shortcut, for: .tv, trigger: .longPress)

        let restored = AppSettings(defaults: defaults)
        #expect(restored.action(for: .tv) == .appSwitcher)
        #expect(restored.configuredAction(for: .tv, trigger: .doubleClick) == ConfiguredButtonAction(
            action: .openCodex,
            shortcut: nil
        ))
        #expect(restored.configuredAction(for: .tv, trigger: .longPress) == ConfiguredButtonAction(
            action: .customShortcut,
            shortcut: shortcut
        ))
        #expect(restored.hasSecondaryAction(for: .tv))

        restored.setAction(.disabled, for: .tv, trigger: .doubleClick)
        #expect(restored.configuredAction(for: .tv, trigger: .doubleClick) == .disabled)
        #expect(restored.hasSecondaryAction(for: .tv))

        restored.resetBindings()
        #expect(restored.action(for: .tv) == .appSwitcher)
        #expect(!restored.hasSecondaryAction(for: .tv))
    }

    @Test func migratesLegacyExclusiveToggleToCustomMappingToggle() throws {
        let suiteName = "RemoteMicTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }

        defaults.set(true, forKey: "exclusiveHID")
        let settings = AppSettings(defaults: defaults)

        #expect(settings.customMappingEnabled)
    }

}
