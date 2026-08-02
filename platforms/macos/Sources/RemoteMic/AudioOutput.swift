import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation
import ObjCExceptionCatcher

struct AudioDeviceInfo: Identifiable, Equatable {
    let id: AudioDeviceID
    let uid: String
    let name: String
}

enum CoreAudioDeviceCatalog {
    static func outputDevices() -> [AudioDeviceInfo] {
        allDeviceIDs().compactMap { deviceID in
            guard outputChannelCount(for: deviceID) > 0 else { return nil }
            return deviceInfo(for: deviceID)
        }
        .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    static func device(uid: String) -> AudioDeviceInfo? {
        allDeviceIDs()
            .compactMap(deviceInfo)
            .first { $0.uid == uid }
    }

    static func defaultInputDevice() -> AudioDeviceInfo? {
        defaultDevice(selector: kAudioHardwarePropertyDefaultInputDevice)
    }

    static func supportsInput(_ device: AudioDeviceInfo) -> Bool {
        inputChannelCount(for: device.id) > 0
    }

    @discardableResult
    static func setDefaultInputDevice(_ device: AudioDeviceInfo) -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = device.id
        return AudioObjectSetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            UInt32(MemoryLayout<AudioDeviceID>.size),
            &deviceID
        ) == noErr
    }

    private static func allDeviceIDs() -> [AudioDeviceID] {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &size
        ) == noErr else { return [] }

        let count = Int(size) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = Array(repeating: AudioDeviceID(0), count: count)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &size,
            &deviceIDs
        ) == noErr else { return [] }
        return deviceIDs
    }

    static func deviceInfo(for deviceID: AudioDeviceID) -> AudioDeviceInfo? {
        guard deviceID != kAudioObjectUnknown,
              let uid = stringProperty(deviceID, selector: kAudioDevicePropertyDeviceUID),
              let name = stringProperty(deviceID, selector: kAudioObjectPropertyName)
        else { return nil }
        return AudioDeviceInfo(id: deviceID, uid: uid, name: name)
    }

    static func routeDiagnostic() -> String {
        let input = defaultDevice(selector: kAudioHardwarePropertyDefaultInputDevice)
        let output = defaultDevice(selector: kAudioHardwarePropertyDefaultOutputDevice)
        let systemOutput = defaultDevice(selector: kAudioHardwarePropertyDefaultSystemOutputDevice)
        return "default_input={\(deviceDiagnostic(input))} " +
            "default_output={\(deviceDiagnostic(output))} " +
            "default_system_output={\(deviceDiagnostic(systemOutput))}"
    }

    static func outputDevicesDiagnostic(_ devices: [AudioDeviceInfo]) -> String {
        devices.map(deviceDiagnostic).joined(separator: " | ")
    }

    static func deviceDiagnostic(_ device: AudioDeviceInfo?) -> String {
        guard let device else { return "none" }
        return "name=\(device.name) id=\(device.id)"
    }

    private static func defaultDevice(selector: AudioObjectPropertySelector) -> AudioDeviceInfo? {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = AudioDeviceID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &size,
            &deviceID
        ) == noErr else { return nil }
        return deviceInfo(for: deviceID)
    }

    private static func stringProperty(
        _ objectID: AudioObjectID,
        selector: AudioObjectPropertySelector
    ) -> String? {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(
            objectID,
            &address,
            0,
            nil,
            &size,
            &value
        ) == noErr else { return nil }
        return value?.takeUnretainedValue() as String?
    }

    private static func outputChannelCount(for deviceID: AudioDeviceID) -> Int {
        channelCount(for: deviceID, scope: kAudioDevicePropertyScopeOutput)
    }

    private static func inputChannelCount(for deviceID: AudioDeviceID) -> Int {
        channelCount(for: deviceID, scope: kAudioDevicePropertyScopeInput)
    }

    private static func channelCount(
        for deviceID: AudioDeviceID,
        scope: AudioObjectPropertyScope
    ) -> Int {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: scope,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &size) == noErr,
              size >= UInt32(MemoryLayout<AudioBufferList>.size)
        else { return 0 }

        let raw = UnsafeMutableRawPointer.allocate(
            byteCount: Int(size),
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, raw) == noErr else {
            return 0
        }
        let bufferList = UnsafeMutableAudioBufferListPointer(
            raw.assumingMemoryBound(to: AudioBufferList.self)
        )
        return bufferList.reduce(0) { $0 + Int($1.mNumberChannels) }
    }
}

final class DefaultInputDeviceLease {
    private var targetDeviceUID: String?
    private var previousDeviceUID: String?
    private let supportsInput: (AudioDeviceInfo) -> Bool
    private let defaultInputDevice: () -> AudioDeviceInfo?
    private let setDefaultInputDevice: (AudioDeviceInfo) -> Bool
    private let deviceForUID: (String) -> AudioDeviceInfo?

    var isActive: Bool { targetDeviceUID != nil }

    init(
        supportsInput: @escaping (AudioDeviceInfo) -> Bool = {
            CoreAudioDeviceCatalog.supportsInput($0)
        },
        defaultInputDevice: @escaping () -> AudioDeviceInfo? = {
            CoreAudioDeviceCatalog.defaultInputDevice()
        },
        setDefaultInputDevice: @escaping (AudioDeviceInfo) -> Bool = {
            CoreAudioDeviceCatalog.setDefaultInputDevice($0)
        },
        deviceForUID: @escaping (String) -> AudioDeviceInfo? = {
            CoreAudioDeviceCatalog.device(uid: $0)
        }
    ) {
        self.supportsInput = supportsInput
        self.defaultInputDevice = defaultInputDevice
        self.setDefaultInputDevice = setDefaultInputDevice
        self.deviceForUID = deviceForUID
    }

    @discardableResult
    func activate(target: AudioDeviceInfo) -> Bool {
        guard supportsInput(target) else {
            AppLogger.shared.write(
                "AUDIO INPUT_LEASE skipped reason=target_has_no_input target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))}"
            )
            return false
        }

        if targetDeviceUID == target.uid {
            let current = defaultInputDevice()
            guard current?.uid != target.uid else {
                return true
            }
            if let current {
                previousDeviceUID = current.uid
            }
            let restored = setDefaultInputDevice(target)
            AppLogger.shared.write(
                "AUDIO INPUT_LEASE reasserted=\(restored) target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))} " +
                    "previous={\(CoreAudioDeviceCatalog.deviceDiagnostic(current))}"
            )
            return restored
        }

        let previous = defaultInputDevice()
        if previous?.uid == target.uid {
            targetDeviceUID = target.uid
            previousDeviceUID = nil
            AppLogger.shared.write("AUDIO INPUT_LEASE already_active target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))}")
            return true
        }

        guard setDefaultInputDevice(target) else {
            AppLogger.shared.write(
                "AUDIO INPUT_LEASE activate_failed target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))}"
            )
            return false
        }
        targetDeviceUID = target.uid
        previousDeviceUID = previous?.uid
        AppLogger.shared.write(
            "AUDIO INPUT_LEASE activated target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))} " +
                "previous={\(CoreAudioDeviceCatalog.deviceDiagnostic(previous))}"
        )
        return true
    }

    func restore() {
        guard let targetDeviceUID else { return }
        defer {
            self.targetDeviceUID = nil
            previousDeviceUID = nil
        }
        guard let previousDeviceUID else {
            AppLogger.shared.write("AUDIO INPUT_LEASE released restore=not_needed")
            return
        }
        guard defaultInputDevice()?.uid == targetDeviceUID else {
            AppLogger.shared.write("AUDIO INPUT_LEASE released restore=skipped_default_changed")
            return
        }
        guard let previous = deviceForUID(previousDeviceUID) else {
            AppLogger.shared.write("AUDIO INPUT_LEASE released restore=previous_unavailable")
            return
        }
        let restored = setDefaultInputDevice(previous)
        AppLogger.shared.write(
            "AUDIO INPUT_LEASE released restored=\(restored) previous={\(CoreAudioDeviceCatalog.deviceDiagnostic(previous))}"
        )
    }
}

final class VirtualAudioOutput {
    private var engine: AVAudioEngine?
    private var remotePlayer: AVAudioPlayerNode?
    private var builtInPlayer: AVAudioPlayerNode?
    private var engineConfigurationObserver: NSObjectProtocol?
    private var engineConfigurationGeneration: UInt64 = 0
    private var rejectedWriteCount = 0
    private var lastRejectedWriteLogDate = Date.distantPast
    private let sourceStateLock = NSLock()
    private var remoteActive = false
    private var testToneActive = false
    private let builtInCapture = BuiltInMicrophoneCapture()
    private let sourceFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 16_000,
        channels: 1,
        interleaved: false
    )!
    private let builtInFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 48_000,
        channels: 1,
        interleaved: false
    )!

    private(set) var selectedDevice: AudioDeviceInfo?
    private(set) var status = "未选择语音输出设备"
    var onConfigurationChange: (() -> Void)?
    var onBuiltInMicrophoneStateChange: ((BuiltInMicrophoneCapture.State) -> Void)?

    init() {
        builtInCapture.onSamples = { [weak self] samples, sampleRate in
            self?.enqueueBuiltIn(samples: samples, sampleRate: sampleRate)
        }
        builtInCapture.onStateChange = { [weak self] state in
            self?.onBuiltInMicrophoneStateChange?(state)
            AppLogger.shared.write("AUDIO BUILTIN_CAPTURE state=\(state.statusText)")
        }
    }

    func retryBuiltInMicrophoneCapture() {
        builtInCapture.retry()
    }

    @discardableResult
    func configure(deviceUID: String) -> Bool {
        let previousState = diagnosticState()
        stopEngine()
        guard !deviceUID.isEmpty else {
            status = "未选择语音输出设备"
            AppLogger.shared.write("AUDIO CONFIGURE skipped reason=no_selected_device previous={\(previousState)}")
            return false
        }
        let availableDevices = CoreAudioDeviceCatalog.outputDevices()
        guard let device = availableDevices.first(where: { $0.uid == deviceUID }) else {
            status = "所选语音输出设备不可用"
            AppLogger.shared.write(
                "AUDIO CONFIGURE failed reason=selected_device_unavailable " +
                    "available={\(CoreAudioDeviceCatalog.outputDevicesDiagnostic(availableDevices))}"
            )
            return false
        }
        AppLogger.shared.write(
            "AUDIO CONFIGURE begin target={\(CoreAudioDeviceCatalog.deviceDiagnostic(device))} " +
                "previous={\(previousState)}"
        )

        let engine = AVAudioEngine()
        let remotePlayer = AVAudioPlayerNode()
        let builtInPlayer = AVAudioPlayerNode()

        // Select the virtual device before constructing the graph. If the graph is
        // connected first, AVAudioEngine initially adopts the system default output
        // format (often the 16 kHz Bluetooth hands-free profile). Changing it to the
        // 48 kHz virtual device afterwards tears the running graph down and can leave
        // voice buffers permanently rejected.
        guard let outputUnit = engine.outputNode.audioUnit else {
            status = "无法打开 CoreAudio 输出单元"
            AppLogger.shared.write("AUDIO CONFIGURE failed reason=no_output_unit target={\(CoreAudioDeviceCatalog.deviceDiagnostic(device))}")
            return false
        }
        var deviceID = device.id
        let result = AudioUnitSetProperty(
            outputUnit,
            kAudioOutputUnitProperty_CurrentDevice,
            kAudioUnitScope_Global,
            0,
            &deviceID,
            UInt32(MemoryLayout<AudioDeviceID>.size)
        )
        guard result == noErr else {
            status = "无法选择音频设备（错误 \(result)）"
            AppLogger.shared.write(
                "AUDIO CONFIGURE failed reason=set_current_device " +
                    "target={\(CoreAudioDeviceCatalog.deviceDiagnostic(device))} error=\(result)"
            )
            return false
        }

        engine.attach(remotePlayer)
        engine.attach(builtInPlayer)
        engine.connect(remotePlayer, to: engine.mainMixerNode, format: sourceFormat)
        engine.connect(builtInPlayer, to: engine.mainMixerNode, format: builtInFormat)

        self.engine = engine
        self.remotePlayer = remotePlayer
        self.builtInPlayer = builtInPlayer
        selectedDevice = device
        observeConfigurationChanges(for: engine)

        do {
            engine.prepare()
            try engine.start()
            guard engine.isRunning else {
                return failConfiguration(
                    message: "音频设备正在变化，稍后自动重试",
                    logReason: "engine_stopped_during_start",
                    target: device
                )
            }
            if let exception = ObjectiveCExceptionGuard.run({
                remotePlayer.play()
                builtInPlayer.play()
            }) {
                return failConfiguration(
                    message: "音频设备正在变化，稍后自动重试",
                    logReason: "player_start_exception exception=\(exception)",
                    target: device
                )
            }
            guard engine.isRunning, remotePlayer.isPlaying, builtInPlayer.isPlaying else {
                return failConfiguration(
                    message: "音频设备正在变化，稍后自动重试",
                    logReason: "player_or_engine_stopped_after_start",
                    target: device
                )
            }
            status = "语音输出：\(device.name)"
            builtInCapture.start()
            AppLogger.shared.write("AUDIO READY target={\(CoreAudioDeviceCatalog.deviceDiagnostic(device))} state={\(diagnosticState())}")
            return true
        } catch {
            return failConfiguration(
                message: "启动音频输出失败：\(error.localizedDescription)",
                logReason: "engine_start_error error=\(error.localizedDescription)",
                target: device
            )
        }
    }

    func isHealthy(configuredDeviceUID: String, availableDevices: [AudioDeviceInfo]) -> Bool {
        AudioRecoveryPolicy.routeIsHealthy(
            configuredDeviceUID: configuredDeviceUID,
            availableDeviceUIDs: Set(availableDevices.map(\.uid)),
            selectedDeviceUID: selectedDevice?.uid,
            engineRunning: engine?.isRunning == true,
            playerPlaying: remotePlayer?.isPlaying == true && builtInPlayer?.isPlaying == true,
            actualOutputDeviceUID: currentOutputDevice()?.uid
        )
    }

    var isReadyForTestTone: Bool {
        selectedDevice != nil && engine?.isRunning == true
    }

    /// Schedules the test tone and reports actual playback completion via `scheduleBuffer`'s
    /// `.dataPlayedBack` callback rather than a fixed timer. `completion` receives `true` only
    /// when the tone finished sounding; `false` if it was cut short (device torn down, real
    /// voice preempted it, etc.). Returns `false` immediately if scheduling never happened.
    @discardableResult
    func playTestTone(completion: @escaping (Bool) -> Void) -> Bool {
        guard isReadyForTestTone,
              let remotePlayer,
              let buffer = makeBuffer(samples: TestToneGenerator.samples(sampleRate: sourceFormat.sampleRate))
        else { return false }
        setTestToneActive(true)
        flushPlayer(builtInPlayer)
        remotePlayer.scheduleBuffer(
            buffer,
            at: nil,
            options: [],
            completionCallbackType: .dataPlayedBack
        ) { [weak self] callbackType in
            self?.setTestToneActive(false)
            completion(callbackType == .dataPlayedBack)
        }
        return true
    }

    /// Flushes any buffer currently queued on the player node (including an in-flight test
    /// tone) so real RC003 voice audio scheduled right after this call is not delayed behind it.
    func cancelTestTone() {
        setTestToneActive(false)
        flushPlayer(remotePlayer)
    }

    private func makeBuffer(samples: [Int16]) -> AVAudioPCMBuffer? {
        guard !samples.isEmpty,
              let buffer = AVAudioPCMBuffer(
                pcmFormat: sourceFormat,
                frameCapacity: AVAudioFrameCount(samples.count)
              ),
              let channel = buffer.floatChannelData?[0]
        else { return nil }

        for index in samples.indices {
            channel[index] = Float(samples[index]) / Float(Int16.max)
        }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        return buffer
    }

    @discardableResult
    func enqueue(samples: [Int16]) -> Bool {
        guard isRemoteActive,
              let remotePlayer,
              engine?.isRunning == true,
              let buffer = makeBuffer(samples: samples)
        else {
            logRejectedWrite()
            return false
        }
        if rejectedWriteCount > 0 {
            AppLogger.shared.write("AUDIO WRITE resumed rejected_count=\(rejectedWriteCount) state={\(basicDiagnosticState())}")
            rejectedWriteCount = 0
        }
        remotePlayer.scheduleBuffer(buffer)
        return true
    }

    /// Changes the source inside the already-running virtual microphone. No
    /// CoreAudio default-device change occurs here.
    func setRemoteActive(_ active: Bool) {
        sourceStateLock.lock()
        let changed = remoteActive != active
        remoteActive = active
        if active {
            testToneActive = false
        }
        sourceStateLock.unlock()
        guard changed else { return }

        if active {
            flushPlayer(builtInPlayer)
            flushPlayer(remotePlayer)
        } else {
            flushPlayer(remotePlayer)
        }
        AppLogger.shared.write(
            active
                ? "AUDIO SOURCE switched=remote"
                : "AUDIO SOURCE switched=builtin"
        )
    }

    private var isRemoteActive: Bool {
        sourceStateLock.lock()
        defer { sourceStateLock.unlock() }
        return remoteActive
    }

    private func setTestToneActive(_ active: Bool) {
        sourceStateLock.lock()
        testToneActive = active
        sourceStateLock.unlock()
    }

    private func enqueueBuiltIn(samples: [Float], sampleRate: Double) {
        sourceStateLock.lock()
        let shouldForward = !remoteActive && !testToneActive
        sourceStateLock.unlock()
        guard shouldForward,
              let builtInPlayer,
              engine?.isRunning == true
        else { return }

        let resampled = Self.resample(
            samples,
            from: sampleRate,
            to: builtInFormat.sampleRate
        )
        guard let buffer = makeBuiltInBuffer(samples: resampled) else { return }

        // Re-check after conversion so a remote press can win even if a capture
        // callback was already in flight.
        sourceStateLock.lock()
        let stillShouldForward = !remoteActive && !testToneActive
        sourceStateLock.unlock()
        guard stillShouldForward else { return }
        builtInPlayer.scheduleBuffer(buffer)
    }

    private func makeBuiltInBuffer(samples: [Float]) -> AVAudioPCMBuffer? {
        guard !samples.isEmpty,
              let buffer = AVAudioPCMBuffer(
                  pcmFormat: builtInFormat,
                  frameCapacity: AVAudioFrameCount(samples.count)
              ),
              let channel = buffer.floatChannelData?[0]
        else { return nil }
        for index in samples.indices {
            channel[index] = max(-1, min(1, samples[index]))
        }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        return buffer
    }

    private static func resample(
        _ input: [Float],
        from inputRate: Double,
        to outputRate: Double
    ) -> [Float] {
        guard !input.isEmpty, inputRate > 0, outputRate > 0 else { return [] }
        guard abs(inputRate - outputRate) >= 1 else { return input }
        let ratio = outputRate / inputRate
        let outputCount = max(1, Int((Double(input.count) * ratio).rounded(.down)))
        var output = [Float](repeating: 0, count: outputCount)
        for index in 0..<outputCount {
            let position = Double(index) / ratio
            let lower = min(Int(position), input.count - 1)
            let upper = min(lower + 1, input.count - 1)
            let fraction = Float(position - Double(lower))
            output[index] = input[lower] + (input[upper] - input[lower]) * fraction
        }
        return output
    }

    func endSession() {
        flushPlayer(remotePlayer)
    }

    /// Places a short silent marker after every voice buffer already queued. The
    /// completion fires only when CoreAudio reports that marker was actually played,
    /// so callers can release the target app's recording shortcut without guessing
    /// how much audio remains in AVAudioPlayerNode.
    @discardableResult
    func drainSession(
        trailingSilenceDuration: TimeInterval,
        completion: @escaping (Bool) -> Void
    ) -> Bool {
        let sampleCount = max(
            1,
            Int((sourceFormat.sampleRate * trailingSilenceDuration).rounded())
        )
        guard let remotePlayer,
              engine?.isRunning == true,
              let marker = makeBuffer(samples: Array(repeating: 0, count: sampleCount))
        else { return false }
        remotePlayer.scheduleBuffer(
            marker,
            at: nil,
            options: [],
            completionCallbackType: .dataPlayedBack
        ) { callbackType in
            completion(callbackType == .dataPlayedBack)
        }
        return true
    }

    private func flushPlayer(_ player: AVAudioPlayerNode?) {
        guard let player, engine?.isRunning == true else { return }
        player.stop()
        player.reset()
        if let exception = ObjectiveCExceptionGuard.run({ player.play() }) {
            AppLogger.shared.write(
                "AUDIO PLAYER restart_exception=\(exception) state={\(basicDiagnosticState())}"
            )
            stop()
            onConfigurationChange?()
        }
    }

    func stop() {
        builtInCapture.stop()
        stopEngine()
    }

    private func stopEngine() {
        removeEngineConfigurationObserver()
        remotePlayer?.stop()
        builtInPlayer?.stop()
        engine?.stop()
        remotePlayer = nil
        builtInPlayer = nil
        engine = nil
        selectedDevice = nil
        sourceStateLock.lock()
        remoteActive = false
        testToneActive = false
        sourceStateLock.unlock()
    }

    private func observeConfigurationChanges(for engine: AVAudioEngine) {
        engineConfigurationGeneration &+= 1
        let generation = engineConfigurationGeneration
        engineConfigurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: nil
        ) { [weak self, weak engine] _ in
            guard let self,
                  let engine,
                  self.engine === engine,
                  self.engineConfigurationGeneration == generation
            else { return }
            AppLogger.shared.write("AUDIO ENGINE configuration_changed generation=\(generation)")
            self.onConfigurationChange?()
        }
    }

    private func removeEngineConfigurationObserver() {
        if let engineConfigurationObserver {
            NotificationCenter.default.removeObserver(engineConfigurationObserver)
            self.engineConfigurationObserver = nil
        }
        engineConfigurationGeneration &+= 1
    }

    func diagnosticState() -> String {
        let actualOutput = currentOutputDevice()
        let isBound: String
        if let selectedDevice, let actualOutput {
            isBound = selectedDevice.id == actualOutput.id ? "true" : "false"
        } else {
            isBound = "unknown"
        }
        return "\(basicDiagnosticState()) " +
            "actual_output={\(CoreAudioDeviceCatalog.deviceDiagnostic(actualOutput))} " +
            "bound_to_selected=\(isBound) \(CoreAudioDeviceCatalog.routeDiagnostic())"
    }

    private func basicDiagnosticState() -> String {
        "engine_running=\(engine?.isRunning == true) " +
            "remote_player=\(remotePlayer?.isPlaying == true) " +
            "builtin_player=\(builtInPlayer?.isPlaying == true) " +
            "source=\(isRemoteActive ? "remote" : "builtin") " +
            "selected={\(CoreAudioDeviceCatalog.deviceDiagnostic(selectedDevice))}"
    }

    private func currentOutputDevice() -> AudioDeviceInfo? {
        guard let outputUnit = engine?.outputNode.audioUnit else { return nil }
        var deviceID = AudioDeviceID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioUnitGetProperty(
            outputUnit,
            kAudioOutputUnitProperty_CurrentDevice,
            kAudioUnitScope_Global,
            0,
            &deviceID,
            &size
        ) == noErr else { return nil }
        return CoreAudioDeviceCatalog.deviceInfo(for: deviceID)
    }

    private func logRejectedWrite() {
        rejectedWriteCount += 1
        let now = Date()
        guard now.timeIntervalSince(lastRejectedWriteLogDate) >= 1 else { return }
        lastRejectedWriteLogDate = now
        AppLogger.shared.write("AUDIO WRITE rejected count=\(rejectedWriteCount) state={\(basicDiagnosticState())}")
    }

    private func failConfiguration(
        message: String,
        logReason: String,
        target: AudioDeviceInfo
    ) -> Bool {
        status = message
        AppLogger.shared.write(
            "AUDIO CONFIGURE failed reason=\(logReason) " +
                "target={\(CoreAudioDeviceCatalog.deviceDiagnostic(target))} " +
                "state={\(diagnosticState())}"
        )
        stop()
        return false
    }
}

enum ObjectiveCExceptionGuard {
    static func run(_ body: () -> Void) -> String? {
        MiVibeCatchObjectiveCException(body) as String?
    }
}

enum AudioRecoveryPolicy {
    static let retryDelays: [TimeInterval] = [0.5, 1, 2, 4, 8]

    static func retryDelay(afterFailedAttempt attempt: Int) -> TimeInterval? {
        guard retryDelays.indices.contains(attempt) else { return nil }
        return retryDelays[attempt]
    }

    static func routeIsHealthy(
        configuredDeviceUID: String,
        availableDeviceUIDs: Set<String>,
        selectedDeviceUID: String?,
        engineRunning: Bool,
        playerPlaying: Bool,
        actualOutputDeviceUID: String?
    ) -> Bool {
        !configuredDeviceUID.isEmpty &&
            availableDeviceUIDs.contains(configuredDeviceUID) &&
            selectedDeviceUID == configuredDeviceUID &&
            engineRunning &&
            playerPlaying &&
            actualOutputDeviceUID == configuredDeviceUID
    }
}
