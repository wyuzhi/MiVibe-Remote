import Testing
@testable import RemoteMic

@Suite("MiVibe virtual microphone")
struct DoubaoAudioDeviceTests {
    @Test func appLifetimeInputLeaseRestoresTheUsersPreviousMicrophoneOnExit() {
        let builtIn = AudioDeviceInfo(id: 1, uid: "BuiltIn", name: "MacBook Pro 麦克风")
        let virtual = AudioDeviceInfo(id: 2, uid: "MiRemoteV", name: "MiRemoteV 2ch")
        var current: AudioDeviceInfo? = builtIn
        let devices = [builtIn.uid: builtIn, virtual.uid: virtual]
        let lease = DefaultInputDeviceLease(
            supportsInput: { _ in true },
            defaultInputDevice: { current },
            setDefaultInputDevice: {
                current = $0
                return true
            },
            deviceForUID: { devices[$0] }
        )

        #expect(lease.activate(target: virtual))
        #expect(current?.uid == virtual.uid)
        #expect(lease.isActive)

        lease.restore()

        #expect(current?.uid == builtIn.uid)
        #expect(!lease.isActive)
    }

    @Test func appLifetimeInputLeasePreservesANewerFallbackAfterSystemRouteChange() {
        let builtIn = AudioDeviceInfo(id: 1, uid: "BuiltIn", name: "MacBook Pro 麦克风")
        let virtual = AudioDeviceInfo(id: 2, uid: "MiRemoteV", name: "MiRemoteV 2ch")
        let headset = AudioDeviceInfo(id: 3, uid: "Headset", name: "蓝牙耳机麦克风")
        var current: AudioDeviceInfo? = builtIn
        let devices = [builtIn.uid: builtIn, virtual.uid: virtual, headset.uid: headset]
        let lease = DefaultInputDeviceLease(
            supportsInput: { _ in true },
            defaultInputDevice: { current },
            setDefaultInputDevice: {
                current = $0
                return true
            },
            deviceForUID: { devices[$0] }
        )

        #expect(lease.activate(target: virtual))
        current = headset
        #expect(lease.activate(target: virtual))
        lease.restore()

        #expect(current?.uid == headset.uid)
    }

    @Test func recognizesTheDerivedBlackHoleDeviceByUID() {
        let device = AudioDeviceInfo(
            id: 1,
            uid: DoubaoAudioDevicePolicy.deviceUID,
            name: "renamed by user"
        )

        #expect(DoubaoAudioDevicePolicy.device(in: [device])?.id == device.id)
    }

    @Test func recognizesTheDerivedBlackHoleDeviceByName() {
        let device = AudioDeviceInfo(
            id: 2,
            uid: "unknown",
            name: DoubaoAudioDevicePolicy.deviceName
        )

        #expect(DoubaoAudioDevicePolicy.device(in: [device])?.id == device.id)
        #expect(DoubaoAudioDevicePolicy.status(in: [device]) == "虚拟麦克风已安装")
    }

    @Test func reportsWhenTheCompatibilityDriverIsMissing() {
        let physicalDevice = AudioDeviceInfo(id: 3, uid: "BuiltIn", name: "MacBook 麦克风")

        #expect(DoubaoAudioDevicePolicy.device(in: [physicalDevice]) == nil)
        #expect(DoubaoAudioDevicePolicy.status(in: [physicalDevice]) == "虚拟麦克风未安装")
    }

    @Test func automaticallyPrefersTheBundledVirtualMicrophone() {
        let device = AudioDeviceInfo(
            id: 4,
            uid: DoubaoAudioDevicePolicy.deviceUID,
            name: DoubaoAudioDevicePolicy.deviceName
        )

        #expect(
            DoubaoAudioDevicePolicy.preferredDeviceUID(currentUID: "", in: [device])
                == DoubaoAudioDevicePolicy.deviceUID
        )
        #expect(
            DoubaoAudioDevicePolicy.preferredDeviceUID(
                currentUID: "UserSelectedDevice",
                in: [device]
            ) == DoubaoAudioDevicePolicy.deviceUID
        )
        #expect(
            DoubaoAudioDevicePolicy.preferredDeviceUID(
                currentUID: "UserSelectedDevice",
                in: []
            ) == "UserSelectedDevice"
        )
    }
}
