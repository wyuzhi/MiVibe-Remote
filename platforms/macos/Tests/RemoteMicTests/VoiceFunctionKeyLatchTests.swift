import CoreGraphics
import Testing
@testable import RemoteMic

@Suite("Voice Fn hold")
struct VoiceFunctionKeyLatchTests {
    @Test func macOSVoicePipelinePreservesBothEdgesOfSpeech() {
        #expect(BridgeAppModel.voiceInputSwitchSettleDelay == 0.30)
        #expect(BridgeAppModel.voiceCaptureStartupDelay == 0.20)
        #expect(BridgeAppModel.voiceDrainDelay == 0.12)
        #expect(BridgeAppModel.voicePipelineLatency == 0.50)
        #expect(BridgeAppModel.voiceStopDelay == 0.62)
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

    @Test func voiceProfilesFailClosedWithoutAccessibility() {
        for profile in [VoiceShortcutProfile.codex, .workBuddy] {
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
