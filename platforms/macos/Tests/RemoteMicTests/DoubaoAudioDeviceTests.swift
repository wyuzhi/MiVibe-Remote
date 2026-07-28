import Testing
@testable import RemoteMic

@Suite("MiVibe virtual microphone")
struct DoubaoAudioDeviceTests {
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
