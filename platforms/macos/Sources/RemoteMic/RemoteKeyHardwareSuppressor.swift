import Foundation

struct HIDUsageMapping: Codable, Equatable {
    static let sourceKey = "HIDKeyboardModifierMappingSrc"
    static let destinationKey = "HIDKeyboardModifierMappingDst"

    let source: UInt64
    let destination: UInt64

    init(source: UInt64, destination: UInt64) {
        self.source = source
        self.destination = destination
    }

    init?(property: [String: NSNumber]) {
        guard let source = property[Self.sourceKey],
              let destination = property[Self.destinationKey]
        else { return nil }
        self.source = source.uint64Value
        self.destination = destination.uint64Value
    }

    var property: [String: NSNumber] {
        [
            Self.sourceKey: NSNumber(value: source),
            Self.destinationKey: NSNumber(value: destination),
        ]
    }
}

enum RemoteKeyHardwareSuppressionPolicy {
    static let keyboardUsagePage: UInt64 = 0x07
    static let voiceKeyUsage: UInt16 = 0x3E
    static let noEventDestination = usage(0)

    static let targetSources = Set(
        RemoteButton.allCases.map { usage($0.hidUsage) } + [usage(voiceKeyUsage)]
    )

    static func usage(_ value: UInt16) -> UInt64 {
        keyboardUsagePage << 32 | UInt64(value)
    }

    static func applying(
        to current: [HIDUsageMapping],
        actions: [RemoteButton: ButtonAction],
        buttonsWithSecondaryActions: Set<RemoteButton>
    ) -> [HIDUsageMapping] {
        var desired = current.filter { !targetSources.contains($0.source) }
        for button in RemoteButton.allCases {
            let source = usage(button.hidUsage)
            let destination = hardwareDestination(
                button: button,
                for: actions[button] ?? .disabled,
                hasSecondaryActions: buttonsWithSecondaryActions.contains(button)
            )
            if let destination {
                if destination != source {
                    desired.append(HIDUsageMapping(
                        source: source,
                        destination: destination
                    ))
                }
            } else {
                desired.append(HIDUsageMapping(
                    source: source,
                    destination: noEventDestination
                ))
            }
        }
        desired.append(HIDUsageMapping(
            source: usage(voiceKeyUsage),
            destination: noEventDestination
        ))
        return desired
    }

    static func requiresApplicationDelivery(
        button: RemoteButton,
        action: ButtonAction,
        hasSecondaryActions: Bool
    ) -> Bool {
        hardwareDestination(
            button: button,
            for: action,
            hasSecondaryActions: hasSecondaryActions
        ) == nil
    }

    static func hardwareDestination(
        button: RemoteButton,
        for action: ButtonAction,
        hasSecondaryActions: Bool
    ) -> UInt64? {
        guard !hasSecondaryActions else { return nil }
        // Back is reported as non-standard usage 0xF1. It produces no macOS
        // keyboard event and hidutil cannot translate it, so every Back action
        // must be delivered immediately from the raw report by MiVibe.
        if button == .back { return nil }
        let usageValue: UInt16
        switch action {
        case .escape:
            usageValue = 0x29
        case .returnKey:
            usageValue = 0x28
        case .arrowUp:
            usageValue = 0x52
        case .arrowDown:
            usageValue = 0x51
        case .arrowLeft:
            usageValue = 0x50
        case .arrowRight:
            usageValue = 0x4F
        case .deleteBackward:
            usageValue = 0x2A
        case .contextMenu:
            usageValue = 0x65
        case .volumeUp:
            usageValue = 0x80
        case .volumeDown:
            usageValue = 0x81
        case .volumeMute:
            usageValue = 0x7F
        case .disabled, .showDesktop, .appSwitcher, .playPause, .customShortcut, .cyclePreset,
             .openRemoteMic, .openCodex, .openWorkBuddy, .openClaude, .openCmux, .openWeChat, .openCursor,
             .openXcode, .openSlack, .openWeCom, .openNeteaseMusic, .openChrome, .openSafari,
             .openZed:
            return nil
        }
        return usage(usageValue)
    }

    static func restoring(
        originalTargetMappings: [HIDUsageMapping],
        in current: [HIDUsageMapping]
    ) -> [HIDUsageMapping] {
        current.filter { !targetSources.contains($0.source) } + originalTargetMappings
    }
}

enum HIDTakeoverMode: Equatable {
    case exclusive
    case deviceSuppressed
    case nativeOnly

    static func resolve(
        seized: Bool,
        hardwareSuppressionApplied: Bool
    ) -> HIDTakeoverMode {
        if seized { return .exclusive }
        if hardwareSuppressionApplied { return .deviceSuppressed }
        return .nativeOnly
    }

    var canInjectMappedActions: Bool {
        self != .nativeOnly
    }
}

enum HIDUtilMappingOutputParser {
    static func mappings(from output: String) -> [HIDUsageMapping]? {
        guard output.contains("UserKeyMapping") else { return nil }
        if output.contains("(null)") { return [] }

        let fullRange = NSRange(output.startIndex..<output.endIndex, in: output)
        let blockExpression = try? NSRegularExpression(pattern: #"\{[^}]*\}"#)
        let blocks = blockExpression?.matches(in: output, range: fullRange) ?? []
        if blocks.isEmpty { return [] }

        var mappings: [HIDUsageMapping] = []
        for block in blocks {
            guard let range = Range(block.range, in: output) else { return nil }
            let text = String(output[range])
            guard let source = decimalValue(
                named: HIDUsageMapping.sourceKey,
                in: text
            ), let destination = decimalValue(
                named: HIDUsageMapping.destinationKey,
                in: text
            ) else { return nil }
            mappings.append(HIDUsageMapping(source: source, destination: destination))
        }
        return mappings
    }

    private static func decimalValue(named key: String, in text: String) -> UInt64? {
        let escapedKey = NSRegularExpression.escapedPattern(for: key)
        guard let expression = try? NSRegularExpression(
            pattern: escapedKey + #"\s*=\s*([0-9]+)\s*;"#
        ) else { return nil }
        let fullRange = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = expression.firstMatch(in: text, range: fullRange),
              match.numberOfRanges == 2,
              let valueRange = Range(match.range(at: 1), in: text)
        else { return nil }
        return UInt64(text[valueRange])
    }
}

final class RemoteKeyHardwareSuppressor {
    private static let backupKey = "rc003OriginalTargetKeyMappingsV1"
    private static let matchingJSON = #"{"VendorID":0x2717,"ProductID":0x32B8}"#
    private static let hidutilURL = URL(fileURLWithPath: "/usr/bin/hidutil")

    private let defaults: UserDefaults
    private(set) var isApplied = false

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    @discardableResult
    func apply(settings: AppSettings) -> Bool {
        guard let current = Self.readMappings() else {
            isApplied = false
            AppLogger.shared.write("HID HARDWARE_SUPPRESSION applied=false matched=0")
            return false
        }

        var originalTargetMappings = loadBackup()
        if originalTargetMappings == nil {
            originalTargetMappings = current.filter {
                RemoteKeyHardwareSuppressionPolicy.targetSources.contains($0.source)
            }
            saveBackup(originalTargetMappings ?? [])
        }

        let actions = Dictionary(uniqueKeysWithValues: RemoteButton.allCases.map {
            ($0, settings.action(for: $0))
        })
        let buttonsWithSecondaryActions = Set(
            RemoteButton.allCases.filter(settings.hasSecondaryAction)
        )
        let desired = RemoteKeyHardwareSuppressionPolicy.applying(
            to: current,
            actions: actions,
            buttonsWithSecondaryActions: buttonsWithSecondaryActions
        )
        isApplied = Self.setMappings(desired)
        AppLogger.shared.write(
            "HID HARDWARE_SUPPRESSION applied=\(isApplied) " +
                "entries=\(desired.count)"
        )
        return isApplied
    }

    @discardableResult
    func restore() -> Bool {
        guard let originalTargetMappings = loadBackup() else {
            isApplied = false
            return true
        }
        guard let current = Self.readMappings() else {
            isApplied = false
            AppLogger.shared.write("HID HARDWARE_SUPPRESSION restore_deferred matched=0")
            return false
        }

        let restored = RemoteKeyHardwareSuppressionPolicy.restoring(
            originalTargetMappings: originalTargetMappings,
            in: current
        )
        let restoredAll = Self.setMappings(restored)
        if restoredAll {
            defaults.removeObject(forKey: Self.backupKey)
        }
        isApplied = false
        AppLogger.shared.write(
            "HID HARDWARE_SUPPRESSION restored=\(restoredAll) " +
                "entries=\(restored.count)"
        )
        return restoredAll
    }

    private func loadBackup() -> [HIDUsageMapping]? {
        guard let data = defaults.data(forKey: Self.backupKey) else { return nil }
        return try? JSONDecoder().decode([HIDUsageMapping].self, from: data)
    }

    private func saveBackup(_ mappings: [HIDUsageMapping]) {
        guard let data = try? JSONEncoder().encode(mappings) else { return }
        defaults.set(data, forKey: Self.backupKey)
    }

    private static func readMappings() -> [HIDUsageMapping]? {
        let result = runHIDUtil([
            "property",
            "--matching", matchingJSON,
            "--get", "UserKeyMapping",
        ])
        guard result.status == 0 else { return nil }
        return HIDUtilMappingOutputParser.mappings(from: result.output)
    }

    private static func setMappings(_ mappings: [HIDUsageMapping]) -> Bool {
        let object: [String: Any] = [
            "UserKeyMapping": mappings.map(\.property),
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: object),
              let json = String(data: data, encoding: .utf8)
        else { return false }
        let result = runHIDUtil([
            "property",
            "--matching", matchingJSON,
            "--set", json,
        ])
        return result.status == 0 &&
            HIDUtilMappingOutputParser.mappings(from: result.output) != nil
    }

    private static func runHIDUtil(_ arguments: [String]) -> (status: Int32, output: String) {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = hidutilURL
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return (
                process.terminationStatus,
                String(data: data, encoding: .utf8) ?? ""
            )
        } catch {
            return (-1, error.localizedDescription)
        }
    }
}
