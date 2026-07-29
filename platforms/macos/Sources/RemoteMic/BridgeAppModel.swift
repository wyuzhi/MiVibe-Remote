import AppKit
import Combine
import CoreAudio
import Foundation

final class BridgeAppModel: ObservableObject, XiaomiBluetoothBridgeDelegate {
    static let voiceDrainDelay: TimeInterval = 0.12

    let settings = AppSettings()

    @Published private(set) var connectionStatus = "正在初始化蓝牙"
    @Published private(set) var hidStatus = "按键映射未启用"
    @Published private(set) var audioStatus = "未选择语音输出设备"
    @Published private(set) var doubaoAudioStatus = "正在检查豆包兼容音频设备"
    @Published private(set) var isStreaming = false
    @Published private(set) var activeRemoteButtons = Set<RemoteButton>()
    @Published private(set) var audioDevices: [AudioDeviceInfo] = []
    @Published private(set) var testToneStatus = "未选择语音输出设备"
    @Published private(set) var isPlayingTestTone = false
    @Published private(set) var voiceShortcutStatus = "正在准备 Codex ⌃⇧D 听写快捷键"

    private let audioOutput = VirtualAudioOutput()
    private var testToneGeneration = 0
    private var voiceFunctionKeyLatch = VoiceFunctionKeyLatch()
    private var voiceStopWorkItem: DispatchWorkItem?
    private var voiceStopGeneration: UInt64 = 0
    private let keyHardwareSuppressor = RemoteKeyHardwareSuppressor()
    private lazy var bluetoothBridge = XiaomiBluetoothBridge(settings: settings, delegate: self)
    private lazy var hidMonitor: HIDRemoteMonitor = {
        let monitor = HIDRemoteMonitor(settings: settings)
        monitor.onStatus = { [weak self] value in
            self?.hidStatus = value
        }
        monitor.onActiveButtons = { [weak self] buttons in
            self?.activeRemoteButtons = buttons
        }
        monitor.ensureHardwareSuppression = { [weak self] in
            guard let self else { return false }
            return self.keyHardwareSuppressor.apply(settings: self.settings)
        }
        monitor.shouldInjectInDeviceSuppressedMode = { [weak self] button in
            guard let self else { return false }
            return RemoteKeyHardwareSuppressionPolicy.requiresApplicationDelivery(
                button: button,
                action: self.settings.action(for: button),
                hasSecondaryActions: self.settings.hasSecondaryAction(for: button)
            )
        }
        return monitor
    }()
    private var started = false
    private var terminationObserver: NSObjectProtocol?
    private let audioHardwareListenerQueue = DispatchQueue(label: "RemoteMic.audioHardware")
    private var observedAudioHardwareAddresses: [AudioObjectPropertyAddress] = []
    private var audioRecoveryWorkItem: DispatchWorkItem?
    private var audioRecoveryGeneration: UInt64 = 0
    private lazy var audioHardwareListener: AudioObjectPropertyListenerBlock = { [weak self] count, addresses in
        let properties = Self.audioHardwarePropertyNames(count: count, addresses: addresses)
        self?.scheduleAudioRecovery(reason: "hardware_change", details: "properties=\(properties)")
    }

    init() {
        audioOutput.onConfigurationChange = { [weak self] in
            self?.scheduleAudioRecovery(reason: "engine_configuration_change")
        }
    }

    func startIfNeeded() {
        guard !started else { return }
        started = true
        refreshAudioDevices()
        applyAudioSettings(reason: "startup")
        startObservingAudioHardware()
        applyHIDSettings()
        bluetoothBridge.start()
        terminationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.stop()
        }
        let version = Bundle.main.object(
            forInfoDictionaryKey: "CFBundleShortVersionString"
        ) as? String ?? "development"
        AppLogger.shared.write("APP START version=\(version)")
    }

    func stop() {
        guard started else { return }
        started = false
        audioRecoveryGeneration &+= 1
        audioRecoveryWorkItem?.cancel()
        audioRecoveryWorkItem = nil
        voiceStopGeneration &+= 1
        voiceStopWorkItem?.cancel()
        voiceStopWorkItem = nil
        stopObservingAudioHardware()
        cancelTestToneIfNeeded(statusMessage: "应用已停止", logReason: "app_stop")
        bluetoothBridge.stop()
        updateVoiceFunctionKeyState(streaming: false)
        hidMonitor.stop()
        keyHardwareSuppressor.restore()
        audioOutput.stop()
        if let terminationObserver {
            NotificationCenter.default.removeObserver(terminationObserver)
            self.terminationObserver = nil
        }
        AppLogger.shared.write("APP STOP")
    }

    func reconnect() {
        bluetoothBridge.reconnectNow()
    }

    func refreshAudioDevices() {
        audioDevices = CoreAudioDeviceCatalog.outputDevices()
        let preferredUID = DoubaoAudioDevicePolicy.preferredDeviceUID(
            currentUID: settings.selectedAudioDeviceUID,
            in: audioDevices
        )
        if preferredUID != settings.selectedAudioDeviceUID {
            settings.selectedAudioDeviceUID = preferredUID
            AppLogger.shared.write(
                "AUDIO DEVICE auto_selected uid=\(preferredUID) name=\(DoubaoAudioDevicePolicy.deviceName)"
            )
        }
        doubaoAudioStatus = DoubaoAudioDevicePolicy.status(in: audioDevices)
        AppLogger.shared.write(
            "AUDIO DEVICES refreshed outputs={\(CoreAudioDeviceCatalog.outputDevicesDiagnostic(audioDevices))} " +
                "\(CoreAudioDeviceCatalog.routeDiagnostic())"
        )
    }

    var hasDoubaoAudioDevice: Bool {
        DoubaoAudioDevicePolicy.device(in: audioDevices) != nil
    }

    func selectDoubaoAudioDevice() {
        guard let device = DoubaoAudioDevicePolicy.device(in: audioDevices) else {
            doubaoAudioStatus = "未检测到 \(DoubaoAudioDevicePolicy.deviceName)，请先安装兼容驱动"
            return
        }
        settings.selectedAudioDeviceUID = device.uid
        applyAudioSettings(reason: "doubao_device_selected")
        doubaoAudioStatus = "已选择 \(device.name) 作为遥控器语音输出"
    }

    func openDoubaoDriverInstructions() {
        guard let instructions = Bundle.main.url(
            forResource: "虚拟麦克风说明",
            withExtension: "md"
        ) else {
            return
        }
        NSWorkspace.shared.open(instructions)
    }

    func applyAudioSettings(reason: String = "settings_change") {
        AppLogger.shared.write("AUDIO REBIND begin reason=\(reason) state={\(audioOutput.diagnosticState())}")
        cancelTestToneIfNeeded(statusMessage: "设备已更新，测试音已取消", logReason: "device_reconfigure")
        let configured = audioOutput.configure(deviceUID: settings.selectedAudioDeviceUID)
        audioStatus = audioOutput.status
        testToneStatus = audioOutput.isReadyForTestTone
            ? "可发送测试音"
            : "未选择语音输出设备或设备不可用"
        AppLogger.shared.write(
            "AUDIO REBIND finished reason=\(reason) success=\(configured) status=\(audioStatus) " +
                "state={\(audioOutput.diagnosticState())}"
        )
    }

    private func startObservingAudioHardware() {
        guard observedAudioHardwareAddresses.isEmpty else { return }
        for selector in [
            kAudioHardwarePropertyDevices,
            kAudioHardwarePropertyDefaultInputDevice,
            kAudioHardwarePropertyDefaultOutputDevice,
            kAudioHardwarePropertyDefaultSystemOutputDevice,
        ] {
            var address = AudioObjectPropertyAddress(
                mSelector: selector,
                mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain
            )
            let result = AudioObjectAddPropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject),
                &address,
                audioHardwareListenerQueue,
                audioHardwareListener
            )
            if result == noErr {
                observedAudioHardwareAddresses.append(address)
            } else {
                AppLogger.shared.write("AUDIO RECOVERY listener_failed selector=\(selector) error=\(result)")
            }
        }
        AppLogger.shared.write("AUDIO ROUTE_MONITOR started properties=\(Self.audioHardwarePropertyNames(for: observedAudioHardwareAddresses))")
    }

    private func stopObservingAudioHardware() {
        for var address in observedAudioHardwareAddresses {
            _ = AudioObjectRemovePropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject),
                &address,
                audioHardwareListenerQueue,
                audioHardwareListener
            )
        }
        if !observedAudioHardwareAddresses.isEmpty {
            AppLogger.shared.write("AUDIO ROUTE_MONITOR stopped properties=\(Self.audioHardwarePropertyNames(for: observedAudioHardwareAddresses))")
        }
        observedAudioHardwareAddresses.removeAll()
    }

    private func scheduleAudioRecovery(reason: String, details: String = "") {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.started else { return }
            self.audioRecoveryGeneration &+= 1
            let generation = self.audioRecoveryGeneration
            let replacedPendingRecovery = self.audioRecoveryWorkItem != nil
            self.audioRecoveryWorkItem?.cancel()
            let work = DispatchWorkItem { [weak self] in
                guard let self,
                      self.started,
                      self.audioRecoveryGeneration == generation
                else { return }
                AppLogger.shared.write(
                    "AUDIO RECOVERY begin id=\(generation) reason=\(reason) detail=\(details) " +
                        "state={\(self.audioOutput.diagnosticState())}"
                )
                self.refreshAudioDevices()
                self.applyAudioSettings(reason: "recovery_\(reason)")
                AppLogger.shared.write(
                    "AUDIO RECOVERY completed id=\(generation) reason=\(reason) " +
                        "state={\(self.audioOutput.diagnosticState())}"
                )
                self.audioRecoveryWorkItem = nil
            }
            self.audioRecoveryWorkItem = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 1, execute: work)
            AppLogger.shared.write(
                "AUDIO RECOVERY scheduled id=\(generation) reason=\(reason) detail=\(details) " +
                    "replaced_pending=\(replacedPendingRecovery) state={\(self.audioOutput.diagnosticState())}"
            )
        }
    }

    private static func audioHardwarePropertyNames(
        count: UInt32,
        addresses: UnsafePointer<AudioObjectPropertyAddress>
    ) -> String {
        guard count > 0 else { return "none" }
        return (0..<Int(count))
            .map { audioHardwarePropertyName(addresses[$0].mSelector) }
            .joined(separator: ",")
    }

    private static func audioHardwarePropertyNames(
        for addresses: [AudioObjectPropertyAddress]
    ) -> String {
        addresses.map { audioHardwarePropertyName($0.mSelector) }.joined(separator: ",")
    }

    private static func audioHardwarePropertyName(
        _ selector: AudioObjectPropertySelector
    ) -> String {
        switch selector {
        case kAudioHardwarePropertyDevices:
            return "devices"
        case kAudioHardwarePropertyDefaultInputDevice:
            return "default_input"
        case kAudioHardwarePropertyDefaultOutputDevice:
            return "default_output"
        case kAudioHardwarePropertyDefaultSystemOutputDevice:
            return "default_system_output"
        default:
            return "selector_\(selector)"
        }
    }

    var canSendTestTone: Bool {
        TestToneGate.canPlay(
            hasSelectedDevice: audioOutput.isReadyForTestTone,
            isStreaming: isStreaming,
            isPlaying: isPlayingTestTone
        )
    }

    func sendTestTone() {
        guard TestToneGate.canPlay(
            hasSelectedDevice: audioOutput.isReadyForTestTone,
            isStreaming: isStreaming,
            isPlaying: isPlayingTestTone
        ) else {
            if isStreaming {
                testToneStatus = "小米遥控器语音进行中，已拒绝测试音"
                AppLogger.shared.write("AUDIO TEST_TONE rejected_streaming")
            } else if isPlayingTestTone {
                testToneStatus = "测试音正在播放中"
            } else {
                testToneStatus = "未选择语音输出设备或设备不可用"
            }
            return
        }

        testToneGeneration &+= 1
        let generation = testToneGeneration
        let started = audioOutput.playTestTone { [weak self] finished in
            DispatchQueue.main.async {
                self?.handleTestToneCompletion(generation: generation, finished: finished)
            }
        }
        guard started else {
            testToneStatus = "测试音发送失败：设备未就绪"
            return
        }
        isPlayingTestTone = true
        testToneStatus = "正在播放约 1 秒测试音"
        AppLogger.shared.write("AUDIO TEST_TONE played")
    }

    private func handleTestToneCompletion(generation: Int, finished: Bool) {
        guard generation == testToneGeneration, isPlayingTestTone else { return }
        isPlayingTestTone = false
        testToneStatus = finished ? "测试音已完成" : "测试音已取消"
        AppLogger.shared.write("AUDIO TEST_TONE \(finished ? "finished" : "cut_short")")
    }

    private func cancelTestToneIfNeeded(statusMessage: String, logReason: String) {
        guard isPlayingTestTone else { return }
        testToneGeneration &+= 1
        isPlayingTestTone = false
        audioOutput.cancelTestTone()
        testToneStatus = statusMessage
        AppLogger.shared.write("AUDIO TEST_TONE cancelled reason=\(logReason)")
    }

    func applyHIDSettings() {
        requestNextHIDPermissionIfNeeded()
        hidMonitor.stop()
        let canSafelyMap = HIDPermissionGate.canMonitor(
            mappingEnabled: settings.customMappingEnabled,
            inputMonitoringGranted: HIDRemoteMonitor.isInputMonitoringGranted,
            accessibilityGranted: KeyboardInjector.isAccessibilityTrusted
        )
        if canSafelyMap {
            _ = keyHardwareSuppressor.apply(settings: settings)
        } else {
            keyHardwareSuppressor.restore()
        }
        hidMonitor.start()
        hidStatus = hidMonitor.status
    }

    private func requestNextHIDPermissionIfNeeded() {
        let request = HIDPermissionGate.nextPermissionRequest(
            mappingEnabled: settings.customMappingEnabled,
            inputMonitoringGranted: HIDRemoteMonitor.isInputMonitoringGranted,
            accessibilityGranted: KeyboardInjector.isAccessibilityTrusted
        )
        switch request {
        case .none:
            break
        case .inputMonitoring:
            _ = HIDRemoteMonitor.requestInputMonitoringAccess()
        case .accessibility:
            _ = KeyboardInjector.requestAccessibilityAccess()
        }
    }

    func requestInputMonitoringPermission() {
        _ = HIDRemoteMonitor.requestInputMonitoringAccess()
        openPrivacyPane("Privacy_ListenEvent")
    }

    func requestAccessibilityPermission() {
        _ = KeyboardInjector.requestAccessibilityAccess()
        openPrivacyPane("Privacy_Accessibility")
    }

    func openLogFolder() {
        NSWorkspace.shared.activateFileViewerSelecting([AppLogger.shared.logURL])
    }

    func openProjectFolder() {
        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        var candidate = executable.deletingLastPathComponent()
        if candidate.path.contains(".app/Contents/MacOS") {
            candidate.deleteLastPathComponent()
            candidate.deleteLastPathComponent()
            candidate.deleteLastPathComponent()
        }
        NSWorkspace.shared.open(candidate)
    }

    private func openPrivacyPane(_ pane: String) {
        guard let url = URL(
            string: "x-apple.systempreferences:com.apple.preference.security?\(pane)"
        ) else { return }
        NSWorkspace.shared.open(url)
    }

    func bluetoothBridge(
        _ bridge: XiaomiBluetoothBridge,
        didChange state: BluetoothBridgeState
    ) {
        connectionStatus = state.displayText
    }

    func bluetoothBridgeDidStartVoice(_ bridge: XiaomiBluetoothBridge) {
        cancelTestToneIfNeeded(statusMessage: "小米遥控器语音进行中，已拒绝测试音", logReason: "voice_start")
        voiceStopGeneration &+= 1
        voiceStopWorkItem?.cancel()
        voiceStopWorkItem = nil
        updateVoiceFunctionKeyState(streaming: true)
        isStreaming = true
    }

    func bluetoothBridgeDidStopVoice(_ bridge: XiaomiBluetoothBridge) {
        isStreaming = false
        guard started else {
            audioOutput.endSession()
            updateVoiceFunctionKeyState(streaming: false)
            return
        }
        voiceStopGeneration &+= 1
        let generation = voiceStopGeneration
        voiceStopWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self,
                  self.voiceStopGeneration == generation,
                  !self.isStreaming
            else { return }
            self.audioOutput.endSession()
            self.updateVoiceFunctionKeyState(streaming: false)
            self.voiceStopWorkItem = nil
            AppLogger.shared.write(
                "VOICE DRAIN completed delay_ms=\(Int(Self.voiceDrainDelay * 1_000))"
            )
        }
        voiceStopWorkItem = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + Self.voiceDrainDelay,
            execute: work
        )
        AppLogger.shared.write(
            "VOICE DRAIN scheduled delay_ms=\(Int(Self.voiceDrainDelay * 1_000))"
        )
    }

    func bluetoothBridge(_ bridge: XiaomiBluetoothBridge, didDecode samples: [Int16]) {
        audioOutput.enqueue(samples: samples)
    }

    private func updateVoiceFunctionKeyState(streaming: Bool) {
        guard let transition = voiceFunctionKeyLatch.transition(streaming: streaming) else { return }
        let shouldHold = transition == .press
        guard KeyboardInjector.setCodexDictationHeld(shouldHold) else {
            voiceFunctionKeyLatch.rollback(transition)
            voiceShortcutStatus = "需要辅助功能权限才能触发 Codex 听写"
            AppLogger.shared.write(
                "VOICE CODEX SHORTCUT failed edge=\(shouldHold ? "down" : "up")"
            )
            return
        }
        voiceShortcutStatus = shouldHold
            ? "Codex ⌃⇧D 已按下；松开语音键即释放"
            : "Codex ⌃⇧D 已释放"
        AppLogger.shared.write(
            "VOICE CODEX SHORTCUT \(shouldHold ? "DOWN" : "UP") chord=control+shift+d"
        )
    }
}
