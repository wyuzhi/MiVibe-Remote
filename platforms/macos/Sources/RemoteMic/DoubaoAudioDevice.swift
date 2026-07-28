import Foundation

enum DoubaoAudioDevicePolicy {
    static let deviceUID = "MiRemoteV2ch_UID"
    static let deviceName = "MiRemoteV 2ch"

    static func device(in devices: [AudioDeviceInfo]) -> AudioDeviceInfo? {
        devices.first { device in
            device.uid == deviceUID || device.name == deviceName
        }
    }

    static func preferredDeviceUID(
        currentUID: String,
        in devices: [AudioDeviceInfo]
    ) -> String {
        device(in: devices)?.uid ?? currentUID
    }

    static func status(in devices: [AudioDeviceInfo]) -> String {
        if device(in: devices) != nil {
            return "虚拟麦克风已安装"
        }
        return "虚拟麦克风未安装"
    }
}
