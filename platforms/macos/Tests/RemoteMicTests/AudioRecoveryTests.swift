import Foundation
import Testing
@testable import RemoteMic

@Suite("Audio recovery stability")
struct AudioRecoveryTests {
    @Test func catchesObjectiveCExceptionsThatSwiftCannotCatch() {
        let description = ObjectiveCExceptionGuard.run {
            NSException(
                name: NSExceptionName("MiVibeAudioTestException"),
                reason: "simulated AVFAudio race"
            ).raise()
        }

        #expect(description?.contains("MiVibeAudioTestException") == true)
        #expect(description?.contains("simulated AVFAudio race") == true)
    }

    @Test func successfulObjectiveCCallReturnsNoException() {
        var executed = false
        let description = ObjectiveCExceptionGuard.run {
            executed = true
        }

        #expect(executed)
        #expect(description == nil)
    }

    @Test func unrelatedDeviceListChangesDoNotRebuildAHealthyRoute() {
        #expect(AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: "MiRemoteV",
            availableDeviceUIDs: ["MiRemoteV", "TemporaryAggregate"],
            selectedDeviceUID: "MiRemoteV",
            engineRunning: true,
            playerPlaying: true,
            actualOutputDeviceUID: "MiRemoteV"
        ))
    }

    @Test func missingStoppedOrMisboundRoutesStillRecover() {
        let base = (
            configured: "MiRemoteV",
            available: Set(["MiRemoteV"]),
            selected: Optional("MiRemoteV"),
            actual: Optional("MiRemoteV")
        )

        #expect(!AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: base.configured,
            availableDeviceUIDs: [],
            selectedDeviceUID: base.selected,
            engineRunning: true,
            playerPlaying: true,
            actualOutputDeviceUID: base.actual
        ))
        #expect(!AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: base.configured,
            availableDeviceUIDs: base.available,
            selectedDeviceUID: base.selected,
            engineRunning: false,
            playerPlaying: true,
            actualOutputDeviceUID: base.actual
        ))
        #expect(!AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: base.configured,
            availableDeviceUIDs: base.available,
            selectedDeviceUID: base.selected,
            engineRunning: true,
            playerPlaying: false,
            actualOutputDeviceUID: base.actual
        ))
        #expect(!AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: base.configured,
            availableDeviceUIDs: base.available,
            selectedDeviceUID: base.selected,
            engineRunning: true,
            playerPlaying: true,
            actualOutputDeviceUID: "MacBookSpeakers"
        ))
    }
}
