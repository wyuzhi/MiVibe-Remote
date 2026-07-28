import CoreGraphics
import Testing
@testable import RemoteMic

@Suite("Voice Fn hold")
struct VoiceFunctionKeyLatchTests {
    @Test func macOSVoiceDrainMatchesTheProvenWindowsBridgeWindow() {
        #expect(BridgeAppModel.voiceDrainDelay == 0.12)
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

    @Test func aSecondMacInstanceYieldsToTheExistingProcess() {
        #expect(!SingleInstancePolicy.shouldYield(currentPID: 42, runningPIDs: [42]))
        #expect(SingleInstancePolicy.shouldYield(currentPID: 42, runningPIDs: [42, 99]))
    }
}
