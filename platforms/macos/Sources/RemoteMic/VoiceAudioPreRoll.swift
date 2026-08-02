import Foundation

/// Holds the brief beginning of a remote voice session while the target app
/// opens its capture stream. The virtual microphone itself is already running.
struct VoiceAudioPreRoll {
    private(set) var isBuffering = false
    private(set) var bufferedSamples: [Int16] = []
    let maximumSampleCount: Int

    init(maximumSampleCount: Int) {
        self.maximumSampleCount = max(1, maximumSampleCount)
    }

    mutating func begin() {
        bufferedSamples.removeAll(keepingCapacity: true)
        isBuffering = true
    }

    /// Returns samples that can be sent to the virtual audio device immediately.
    /// While buffering, the incoming samples are retained and `nil` is returned.
    mutating func accept(_ samples: [Int16]) -> [Int16]? {
        guard isBuffering else { return samples }
        guard !samples.isEmpty else { return nil }

        if samples.count >= maximumSampleCount {
            bufferedSamples = Array(samples.suffix(maximumSampleCount))
            return nil
        }

        let overflow = bufferedSamples.count + samples.count - maximumSampleCount
        if overflow > 0 {
            bufferedSamples.removeFirst(overflow)
        }
        bufferedSamples.append(contentsOf: samples)
        return nil
    }

    mutating func release() -> [Int16] {
        isBuffering = false
        let samples = bufferedSamples
        bufferedSamples.removeAll(keepingCapacity: true)
        return samples
    }

    mutating func reset() {
        isBuffering = false
        bufferedSamples.removeAll(keepingCapacity: false)
    }
}
