import Foundation
import Testing
@testable import RemoteMic

@Suite("RC003 hardware key suppression")
struct RemoteKeyHardwareSuppressorTests {
    @Test func coversEveryRemoteButtonAndTheFixedVoiceKey() {
        let expectedSources = Set(
            RemoteButton.allCases.map {
                RemoteKeyHardwareSuppressionPolicy.usage($0.hidUsage)
            } + [
                RemoteKeyHardwareSuppressionPolicy.usage(
                    RemoteKeyHardwareSuppressionPolicy.voiceKeyUsage
                ),
            ]
        )

        #expect(RemoteKeyHardwareSuppressionPolicy.targetSources == expectedSources)
        #expect(expectedSources.count == 13)
    }

    @Test func applyingReplacesOnlyRC003Sources() {
        let leftSource = RemoteKeyHardwareSuppressionPolicy.usage(
            RemoteButton.left.hidUsage
        )
        let unrelated = HIDUsageMapping(source: 0x0000_0007_0000_0004, destination: 99)
        let existingLeft = HIDUsageMapping(source: leftSource, destination: 42)

        let actions = AppSettings.codexBindings
        let applied = RemoteKeyHardwareSuppressionPolicy.applying(
            to: [unrelated, existingLeft],
            actions: actions,
            buttonsWithSecondaryActions: []
        )

        #expect(applied.contains(unrelated))
        #expect(!applied.contains(existingLeft))
        #expect(!applied.contains { $0.source == leftSource })
        #expect(applied.contains(HIDUsageMapping(
            source: RemoteKeyHardwareSuppressionPolicy.usage(RemoteButton.back.hidUsage),
            destination: RemoteKeyHardwareSuppressionPolicy.noEventDestination
        )))
        #expect(applied.contains(HIDUsageMapping(
            source: RemoteKeyHardwareSuppressionPolicy.usage(RemoteButton.power.hidUsage),
            destination: RemoteKeyHardwareSuppressionPolicy.noEventDestination
        )))
    }

    @Test func restoringPreservesUnrelatedChangesAndRestoresOriginalTargets() {
        let leftSource = RemoteKeyHardwareSuppressionPolicy.usage(
            RemoteButton.left.hidUsage
        )
        let originalLeft = HIDUsageMapping(source: leftSource, destination: 42)
        let unrelated = HIDUsageMapping(source: 0x0000_0007_0000_0004, destination: 100)
        let current = RemoteKeyHardwareSuppressionPolicy.applying(
            to: [unrelated],
            actions: AppSettings.codexBindings,
            buttonsWithSecondaryActions: []
        )

        let restored = RemoteKeyHardwareSuppressionPolicy.restoring(
            originalTargetMappings: [originalLeft],
            in: current
        )

        #expect(restored.contains(unrelated))
        #expect(restored.contains(originalLeft))
        #expect(!restored.contains(HIDUsageMapping(
            source: leftSource,
            destination: RemoteKeyHardwareSuppressionPolicy.noEventDestination
        )))
    }

    @Test func standardKeysUseNativeDeliveryAndSecondaryGesturesUseTheApp() {
        #expect(!RemoteKeyHardwareSuppressionPolicy.requiresApplicationDelivery(
            button: .left,
            action: .arrowLeft,
            hasSecondaryActions: false
        ))
        #expect(RemoteKeyHardwareSuppressionPolicy.requiresApplicationDelivery(
            button: .back,
            action: .deleteBackward,
            hasSecondaryActions: false
        ))
        #expect(RemoteKeyHardwareSuppressionPolicy.requiresApplicationDelivery(
            button: .left,
            action: .arrowLeft,
            hasSecondaryActions: true
        ))
        #expect(RemoteKeyHardwareSuppressionPolicy.requiresApplicationDelivery(
            button: .power,
            action: .openCodex,
            hasSecondaryActions: false
        ))
        #expect(RemoteKeyHardwareSuppressionPolicy.hardwareDestination(
            button: .left,
            for: .arrowRight,
            hasSecondaryActions: false
        ) == RemoteKeyHardwareSuppressionPolicy.usage(0x4F))
    }

    @Test func takeoverFailsClosedWhenNeitherExclusiveNorDeviceSuppressed() {
        #expect(HIDTakeoverMode.resolve(
            seized: true,
            hardwareSuppressionApplied: false
        ) == .exclusive)
        #expect(HIDTakeoverMode.resolve(
            seized: false,
            hardwareSuppressionApplied: true
        ) == .deviceSuppressed)
        #expect(HIDTakeoverMode.resolve(
            seized: false,
            hardwareSuppressionApplied: false
        ) == .nativeOnly)
        #expect(HIDTakeoverMode.exclusive.canInjectMappedActions)
        #expect(HIDTakeoverMode.deviceSuppressed.canInjectMappedActions)
        #expect(!HIDTakeoverMode.nativeOnly.canInjectMappedActions)
    }

    @Test func parsesHIDUtilNullEmptyAndPopulatedMappingOutput() {
        let nullOutput = """
        RegistryID  Key                   Value
        100026eef   UserKeyMapping   (null)
        """
        let emptyOutput = """
        RegistryID  Key                   Value
        100026eef   UserKeyMapping   (
        )
        """
        let populatedOutput = """
        RegistryID  Key                   Value
        100026eef   UserKeyMapping   (
                {
                HIDKeyboardModifierMappingDst = 30064771072;
                HIDKeyboardModifierMappingSrc = 30064771152;
            }
        )
        """

        #expect(HIDUtilMappingOutputParser.mappings(from: nullOutput) == [])
        #expect(HIDUtilMappingOutputParser.mappings(from: emptyOutput) == [])
        #expect(HIDUtilMappingOutputParser.mappings(from: populatedOutput) == [
            HIDUsageMapping(source: 30_064_771_152, destination: 30_064_771_072),
        ])
        #expect(HIDUtilMappingOutputParser.mappings(from: "no matching service") == nil)
    }
}
