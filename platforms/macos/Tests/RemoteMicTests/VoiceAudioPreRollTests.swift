import Testing
@testable import RemoteMic

@Suite("Voice audio pre-roll")
struct VoiceAudioPreRollTests {
    @Test func buffersTheBeginningAndReleasesItInOrder() {
        var preRoll = VoiceAudioPreRoll(maximumSampleCount: 8)

        preRoll.begin()
        #expect(preRoll.accept([1, 2, 3]) == nil)
        #expect(preRoll.accept([4, 5]) == nil)
        #expect(preRoll.bufferedSamples == [1, 2, 3, 4, 5])
        #expect(preRoll.release() == [1, 2, 3, 4, 5])
        #expect(!preRoll.isBuffering)
        #expect(preRoll.accept([6, 7]) == [6, 7])
    }

    @Test func keepsTheNewestAudioWhenTheSafetyLimitIsReached() {
        var preRoll = VoiceAudioPreRoll(maximumSampleCount: 5)

        preRoll.begin()
        _ = preRoll.accept([1, 2, 3])
        _ = preRoll.accept([4, 5, 6, 7])

        #expect(preRoll.release() == [3, 4, 5, 6, 7])
    }

    @Test func resetDropsPendingAudioAndReturnsToPassThrough() {
        var preRoll = VoiceAudioPreRoll(maximumSampleCount: 8)

        preRoll.begin()
        _ = preRoll.accept([1, 2, 3])
        preRoll.reset()

        #expect(!preRoll.isBuffering)
        #expect(preRoll.bufferedSamples.isEmpty)
        #expect(preRoll.accept([4]) == [4])
    }
}
