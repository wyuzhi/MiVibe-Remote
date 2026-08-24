import CoreGraphics
import Testing
@testable import RemoteMic

@Suite("Voice Fn hold")
struct VoiceFunctionKeyLatchTests {
    @Test func macOSVoicePipelinePreservesBothEdgesOfSpeech() {
        #expect(BridgeAppModel.voiceCaptureStartupDelay == 0.20)
        #expect(BridgeAppModel.voicePacketSettleDelay >= 0.15)
        #expect(BridgeAppModel.voiceDrainDelay >= 0.30)
        #expect(BridgeAppModel.codexRecognitionCommitDelay >= 0.20)
        #expect(BridgeAppModel.voiceDrainSafetyTimeout >= 4)
        #expect(BridgeAppModel.maximumVoicePreRollSamples >= 16_000)
    }

    @Test func emitsOnePressAndOneReleasePerStream() {
        var latch = VoiceFunctionKeyLatch()

        #expect(latch.transition(streaming: true) == .press)
        #expect(latch.transition(streaming: true) == nil)
        #expect(latch.isHeld)
        #expect(latch.transition(streaming: false) == .release)
        #expect(latch.transition(streaming: false) == nil)
        #expect(!latch.isHeld)
    }

    @Test func rollsBackFailedTransitions() {
        var latch = VoiceFunctionKeyLatch()

        let press = latch.transition(streaming: true)
        #expect(press == .press)
        latch.rollback(.press)
        #expect(!latch.isHeld)

        #expect(latch.transition(streaming: true) == .press)
        let release = latch.transition(streaming: false)
        #expect(release == .release)
        latch.rollback(.release)
        #expect(latch.isHeld)
    }

    @Test func codexDictationUsesTheConfiguredHoldShortcut() {
        var posted: (keyCode: CGKeyCode, flags: CGEventFlags, held: Bool)?
        let sent = KeyboardInjector.setCodexDictationHeld(
            true,
            accessibilityTrusted: { true },
            keyStatePoster: {
                posted = ($0, $1, $2)
                return true
            }
        )

        #expect(sent)
        #expect(posted?.keyCode == 2)
        #expect(posted?.flags == [.maskControl, .maskShift])
        #expect(posted?.held == true)
    }

    @Test func codexDictationFailsClosedWithoutAccessibility() {
        #expect(!KeyboardInjector.setCodexDictationHeld(
            true,
            accessibilityTrusted: { false },
            keyStatePoster: { _, _, _ in
                Issue.record("Key state must not be posted without accessibility")
                return true
            }
        ))
    }

    @Test func codexProfileHoldsOnPressAndReleasesOnStop() {
        var posted: [(CGKeyCode, CGEventFlags, Bool)] = []
        for transition in [VoiceFunctionKeyTransition.press, .release] {
            #expect(KeyboardInjector.sendVoiceShortcut(
                profile: .codex,
                transition: transition,
                accessibilityTrusted: { true },
                keyStatePoster: {
                    posted.append(($0, $1, $2))
                    return true
                },
                keyTapPoster: { _, _ in
                    Issue.record("Codex must use held key state, not toggle taps")
                    return true
                }
            ))
        }

        #expect(posted.count == 2)
        #expect(posted[0].0 == 2)
        #expect(posted[0].1 == [.maskControl, .maskShift])
        #expect(posted[0].2)
        #expect(!posted[1].2)
    }

    @Test func workBuddyProfileTapsCommandDAtBothStreamEdges() {
        var posted: [(CGKeyCode, CGEventFlags)] = []
        for transition in [VoiceFunctionKeyTransition.press, .release] {
            #expect(KeyboardInjector.sendVoiceShortcut(
                profile: .workBuddy,
                transition: transition,
                accessibilityTrusted: { true },
                keyStatePoster: { _, _, _ in
                    Issue.record("WorkBuddy must use toggle taps, not a held key")
                    return true
                },
                keyTapPoster: {
                    posted.append(($0, $1))
                    return true
                }
            ))
        }

        #expect(posted.count == 2)
        #expect(posted.allSatisfy { $0.0 == 2 && $0.1 == [.maskCommand] })
    }

    @Test func weChatProfileHoldsFunctionKeyAcrossTheVoiceStream() {
        var posted: [Bool] = []
        for transition in [VoiceFunctionKeyTransition.press, .release] {
            #expect(KeyboardInjector.sendVoiceShortcut(
                profile: .weChat,
                transition: transition,
                accessibilityTrusted: { true },
                keyStatePoster: { _, _, _ in
                    Issue.record("WeChat must hold Fn, not use the Codex chord")
                    return true
                },
                functionKeyStatePoster: {
                    posted.append($0)
                    return true
                },
                keyTapPoster: { _, _ in
                    Issue.record("WeChat must hold Fn, not tap a normal key")
                    return true
                }
            ))
        }

        #expect(posted == [true, false])
    }

    @Test func customHoldProfileUsesRecordedShortcutAcrossBothEdges() {
        let shortcut = CustomKeyboardShortcut(
            keyCode: 40,
            modifierFlags: [.control, .option],
            keyLabel: "K"
        )
        var posted: [(CGKeyCode, CGEventFlags, Bool)] = []
        for transition in [VoiceFunctionKeyTransition.press, .release] {
            #expect(KeyboardInjector.sendVoiceShortcut(
                profile: .custom,
                transition: transition,
                customShortcut: shortcut,
                customTriggerMode: .hold,
                accessibilityTrusted: { true },
                keyStatePoster: {
                    posted.append(($0, $1, $2))
                    return true
                }
            ))
        }

        #expect(posted.count == 2)
        #expect(posted[0].0 == 40)
        #expect(posted[0].1 == [.maskControl, .maskAlternate])
        #expect(posted.map(\.2) == [true, false])
    }

    @Test func customToggleProfileTapsRecordedShortcutAtBothEdges() {
        let shortcut = CustomKeyboardShortcut(
            keyCode: 2,
            modifierFlags: [.command],
            keyLabel: "D"
        )
        var posted: [(CGKeyCode, CGEventFlags)] = []
        for transition in [VoiceFunctionKeyTransition.press, .release] {
            #expect(KeyboardInjector.sendVoiceShortcut(
                profile: .custom,
                transition: transition,
                customShortcut: shortcut,
                customTriggerMode: .toggle,
                accessibilityTrusted: { true },
                keyTapPoster: {
                    posted.append(($0, $1))
                    return true
                }
            ))
        }

        #expect(posted.count == 2)
        #expect(posted.allSatisfy { $0.0 == 2 && $0.1 == [.maskCommand] })
    }

    @Test func voiceProfilesFailClosedWithoutAccessibility() {
        for profile in VoiceShortcutProfile.allCases {
            #expect(!KeyboardInjector.sendVoiceShortcut(
                profile: profile,
                transition: .press,
                accessibilityTrusted: { false },
                keyStatePoster: { _, _, _ in
                    Issue.record("No held key may be posted without accessibility")
                    return true
                },
                keyTapPoster: { _, _ in
                    Issue.record("No toggle key may be posted without accessibility")
                    return true
                }
            ))
        }
    }

    @Test func aSecondMacInstanceYieldsToTheExistingProcess() {
        #expect(!SingleInstancePolicy.shouldYield(currentPID: 42, runningPIDs: [42]))
        #expect(SingleInstancePolicy.shouldYield(currentPID: 42, runningPIDs: [42, 99]))
    }
}
