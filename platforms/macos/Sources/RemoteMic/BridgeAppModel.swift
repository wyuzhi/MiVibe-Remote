import AppKit
import Combine
import CoreAudio
import Foundation

final class BridgeAppModel: ObservableObject, XiaomiBluetoothBridgeDelegate {
    static let voiceCaptureStartupDelay: TimeInterval = 0.20
    /// The old AVAudioPlayerNode route supplied an implicit tail buffer. The
    /// direct CoreAudio route needs explicit silence before ending dictation so
    /// the target app can consume and finalize the last spoken words.
    static let voiceDrainDelay: TimeInterval = 0.45
    static let maximumVoicePreRollSamples = 16_000 * 4

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
    @Published private(set) var voiceShortcutStatus = "正在准备语音快捷键"
    @Published private(set) var isAudioReady = false
    @Published private(set) var computerMicrophoneStatus = "正在准备 MacBook 麦克风"

    private let audioOutput = StableVirtualAudioOutput()
    private let defaultInputLease = DefaultInputDeviceLease()
    private var testToneGeneration = 0
    private var voiceFunctionKeyLatch = VoiceFunctionKeyLatch()
    private var activeVoiceShortcutProfile: VoiceShortcutProfile?
    private var voicePreRoll = VoiceAudioPreRoll(
        maximumSampleCount: BridgeAppModel.maximumVoicePreRollSamples
    )
    private var voicePreRollReleaseWorkItem: DispatchWorkItem?
    private var voiceStartGeneration: UInt64 = 0
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
        monitor.onCyclePreset = { [weak self] in
            guard let self else { return }
            let profile = self.settings.cyclePreset()
            self.voiceShortcutStatus = profile.readyStatus
            AppLogger.shared.write("PRESET CYCLE active=\(profile.rawValue)")
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
    private var cancellables = Set<AnyCancellable>()
    private lazy var audioHardwareListener: AudioObjectPropertyListenerBlock = { [weak self] count, addresses in
        let properties = Self.audioHardwarePropertyNames(count: count, addresses: addresses)
        self?.scheduleAudioRecovery(reason: "hardware_change", details: "properties=\(properties)")
    }

    init() {
        voiceShortcutStatus = settings.voiceShortcutProfile.readyStatus
        settings.$voiceShortcutProfile
            .dropFirst()
            .sink { [weak self] profile in
                guard let self, !self.voiceFunctionKeyLatch.isHeld else { return }
                self.voiceShortcutStatus = profile.readyStatus
            }
            .store(in: &cancellables)
        audioOutput.onConfigurationChange = { [weak self] in
            self?.scheduleAudioRecovery(reason: "engine_configuration_change")
        }
        audioOutput.onBuiltInMicrophoneStateChange = { [weak self] state in
            self?.computerMicrophoneStatus = state.statusText
        }
    }

    func startIfNeeded() {
        guard !started else { return }
        started = true
        refreshAudioDevices()
        activatePersistentDefaultInput()
        if !applyAudioSettings(reason: "startup") {
            scheduleAudioRecovery(
                reason: "startup_failed",
                delay: AudioRecoveryPolicy.retryDelays[0],
                retryAttempt: 1
            )
        }
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
        voiceStartGeneration &+= 1
        voicePreRollReleaseWorkItem?.cancel()
        voicePreRollReleaseWorkItem = nil
        voicePreRoll.reset()
        stopObservingAudioHardware()
        cancelTestToneIfNeeded(statusMessage: "应用已停止", logReason: "app_stop")
        bluetoothBridge.stop()
        audioOutput.setRemoteActive(false)
        updateVoiceFunctionKeyState(streaming: false)
        hidMonitor.stop()
        keyHardwareSuppressor.restore()
        defaultInputLease.restore()
        audioOutput.stop()
        isAudioReady = false
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

    @discardableResult
    func applyAudioSettings(reason: String = "settings_change") -> Bool {
        AppLogger.shared.write("AUDIO REBIND begin reason=\(reason) state={\(audioOutput.diagnosticState())}")
        cancelTestToneIfNeeded(statusMessage: "设备已更新，测试音已取消", logReason: "device_reconfigure")
        let configured = audioOutput.configure(deviceUID: settings.selectedAudioDeviceUID)
        isAudioReady = configured
        audioStatus = audioOutput.status
        testToneStatus = audioOutput.isReadyForTestTone
            ? "可发送测试音"
            : "未选择语音输出设备或设备不可用"
        AppLogger.shared.write(
            "AUDIO REBIND finished reason=\(reason) success=\(configured) status=\(audioStatus) " +
            "state={\(audioOutput.diagnosticState())}"
        )
        return configured
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

    private func scheduleAudioRecovery(
        reason: String,
        details: String = "",
        delay: TimeInterval = 1,
        retryAttempt: Int = 0
    ) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.started else { return }
            let routeHealthyNow = self.audioOutput.isHealthy(
                configuredDeviceUID: self.settings.selectedAudioDeviceUID,
                availableDevices: self.audioDevices
            )
            self.isAudioReady = routeHealthyNow
            if !routeHealthyNow {
                self.audioStatus = "音频设备切换中，正在自动恢复"
                self.testToneStatus = "音频设备切换中，正在自动恢复"
            }
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
                self.activatePersistentDefaultInput()
                let configured: Bool
                if self.audioOutput.isHealthy(
                    configuredDeviceUID: self.settings.selectedAudioDeviceUID,
                    availableDevices: self.audioDevices
                ) {
                    self.isAudioReady = true
                    configured = true
                    AppLogger.shared.write(
                        "AUDIO RECOVERY skipped id=\(generation) reason=\(reason) " +
                            "detail=\(details) cause=route_still_healthy " +
                            "state={\(self.audioOutput.diagnosticState())}"
                    )
                } else {
                    configured = self.applyAudioSettings(reason: "recovery_\(reason)")
                }
                if configured, self.isStreaming {
                    self.audioOutput.setRemoteActive(true)
                }
                AppLogger.shared.write(
                    "AUDIO RECOVERY completed id=\(generation) reason=\(reason) " +
                        "state={\(self.audioOutput.diagnosticState())}"
                )
                self.audioRecoveryWorkItem = nil
                if !configured,
                   let retryDelay = AudioRecoveryPolicy.retryDelay(
                       afterFailedAttempt: retryAttempt
                   )
                {
                    self.audioStatus = "音频设备切换中，正在自动恢复"
                    self.testToneStatus = "音频设备切换中，正在自动恢复"
                    AppLogger.shared.write(
                        "AUDIO RECOVERY retry_scheduled attempt=\(retryAttempt + 1) " +
                            "delay_ms=\(Int(retryDelay * 1_000)) reason=\(reason)"
                    )
                    self.scheduleAudioRecovery(
                        reason: reason,
                        details: details,
                        delay: retryDelay,
                        retryAttempt: retryAttempt + 1
                    )
                } else if !configured {
                    self.audioStatus = "音频自动恢复未成功；请松开语音键后重试"
                    self.testToneStatus = "音频未就绪，请重新选择虚拟麦克风"
                }
            }
            self.audioRecoveryWorkItem = work
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
            AppLogger.shared.write(
                "AUDIO RECOVERY scheduled id=\(generation) reason=\(reason) detail=\(details) " +
                    "delay_ms=\(Int(delay * 1_000)) retry_attempt=\(retryAttempt) " +
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

    func requestMicrophonePermission() {
        audioOutput.retryBuiltInMicrophoneCapture()
        openPrivacyPane("Privacy_Microphone")
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
        voiceStartGeneration &+= 1
        let generation = voiceStartGeneration
        voicePreRollReleaseWorkItem?.cancel()
        voicePreRoll.begin()
        isStreaming = true
        ensureAudioReadyForVoice()
        audioOutput.setRemoteActive(true)
        updateVoiceFunctionKeyState(streaming: true)
        scheduleVoicePreRollRelease(generation: generation)
        AppLogger.shared.write(
            "VOICE STARTUP source=remote capture_settle_ms=" +
                "\(Int(Self.voiceCaptureStartupDelay * 1_000))"
        )
    }

    func bluetoothBridgeDidStopVoice(_ bridge: XiaomiBluetoothBridge) {
        isStreaming = false
        guard started else {
            voiceStartGeneration &+= 1
            voicePreRollReleaseWorkItem?.cancel()
            voicePreRoll.reset()
            audioOutput.endSession()
            audioOutput.setRemoteActive(false)
            updateVoiceFunctionKeyState(streaming: false)
            return
        }
        voiceStopGeneration &+= 1
        let generation = voiceStopGeneration
        voiceStopWorkItem?.cancel()
        voiceStopWorkItem = nil
        if voicePreRoll.isBuffering {
            AppLogger.shared.write(
                "VOICE DRAIN waiting_for_preroll samples=\(voicePreRoll.bufferedSamples.count)"
            )
            return
        }
        beginVoiceDrain(generation: generation)
    }

    private func beginVoiceDrain(generation: UInt64) {
        voiceStopWorkItem?.cancel()
        voiceStopWorkItem = nil
        let scheduled = audioOutput.drainSession(
            trailingSilenceDuration: Self.voiceDrainDelay
        ) { [weak self] played in
            DispatchQueue.main.async {
                self?.completeVoiceDrain(
                    generation: generation,
                    reason: played ? "queue_played" : "queue_cancelled"
                )
            }
        }
        let timeout: TimeInterval = scheduled ? 2 : Self.voiceDrainDelay
        let safetyWork = DispatchWorkItem { [weak self] in
            self?.completeVoiceDrain(generation: generation, reason: "safety_timeout")
        }
        voiceStopWorkItem = safetyWork
        DispatchQueue.main.asyncAfter(
            deadline: .now() + timeout,
            execute: safetyWork
        )
        AppLogger.shared.write(
            "VOICE DRAIN waiting_for_queue scheduled=\(scheduled) " +
                "safety_timeout_ms=\(Int(timeout * 1_000))"
        )
    }

    private func completeVoiceDrain(generation: UInt64, reason: String) {
        guard voiceStopGeneration == generation,
              !isStreaming
        else { return }
        voiceStopWorkItem?.cancel()
        voiceStopWorkItem = nil
        audioOutput.endSession()
        audioOutput.setRemoteActive(false)
        updateVoiceFunctionKeyState(streaming: false)
        AppLogger.shared.write("VOICE DRAIN completed reason=\(reason)")
    }

    func bluetoothBridge(_ bridge: XiaomiBluetoothBridge, didDecode samples: [Int16]) {
        guard let readySamples = voicePreRoll.accept(samples) else { return }
        audioOutput.enqueue(samples: readySamples)
    }

    func applyHeadsetCompatibilitySetting() {
        if settings.headsetCompatibilityEnabled {
            activatePersistentDefaultInput()
        } else {
            defaultInputLease.restore()
        }
        scheduleAudioRecovery(
            reason: "persistent_virtual_input_changed",
            delay: AudioRecoveryPolicy.retryDelays[0]
        )
        AppLogger.shared.write(
            "AUDIO PERSISTENT_INPUT enabled=\(settings.headsetCompatibilityEnabled) " +
                "active=\(defaultInputLease.isActive)"
        )
    }

    private func activatePersistentDefaultInput() {
        guard settings.headsetCompatibilityEnabled,
              let device = audioDevices.first(where: {
                  $0.uid == settings.selectedAudioDeviceUID
              })
        else { return }
        _ = defaultInputLease.activate(target: device)
    }

    private func ensureAudioReadyForVoice() {
        refreshAudioDevices()
        activatePersistentDefaultInput()
        guard !audioOutput.isHealthy(
            configuredDeviceUID: settings.selectedAudioDeviceUID,
            availableDevices: audioDevices
        ) else {
            isAudioReady = true
            return
        }
        guard !applyAudioSettings(reason: "voice_start") else { return }
        scheduleAudioRecovery(
            reason: "voice_start_failed",
            delay: AudioRecoveryPolicy.retryDelays[0],
            retryAttempt: 1
        )
    }

    private func scheduleVoicePreRollRelease(generation: UInt64) {
        let work = DispatchWorkItem { [weak self] in
            guard let self,
                  self.started,
                  self.voiceStartGeneration == generation
            else { return }
            self.voicePreRollReleaseWorkItem = nil
            guard self.audioOutput.isHealthy(
                configuredDeviceUID: self.settings.selectedAudioDeviceUID,
                availableDevices: self.audioDevices
            ) else {
                self.ensureAudioReadyForVoice()
                self.audioOutput.setRemoteActive(true)
                self.scheduleVoicePreRollRelease(generation: generation)
                return
            }
            self.audioOutput.setRemoteActive(true)
            self.releaseVoicePreRoll(generation: generation, reason: "capture_ready")
        }
        voicePreRollReleaseWorkItem = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + Self.voiceCaptureStartupDelay,
            execute: work
        )
        AppLogger.shared.write(
            "VOICE STARTUP shortcut_sent capture_settle_ms=" +
                "\(Int(Self.voiceCaptureStartupDelay * 1_000))"
        )
    }

    private func releaseVoicePreRoll(generation: UInt64, reason: String) {
        guard voiceStartGeneration == generation,
              voicePreRoll.isBuffering
        else { return }
        let samples = voicePreRoll.release()
        if !samples.isEmpty {
            _ = audioOutput.enqueue(samples: samples)
        }
        let durationMilliseconds = Int(
            (Double(samples.count) / 16_000.0 * 1_000.0).rounded()
        )
        AppLogger.shared.write(
            "VOICE PREROLL released reason=\(reason) samples=\(samples.count) " +
                "duration_ms=\(durationMilliseconds)"
        )
        if started, !isStreaming {
            beginVoiceDrain(generation: voiceStopGeneration)
        }
    }

    private func updateVoiceFunctionKeyState(streaming: Bool) {
        guard let transition = voiceFunctionKeyLatch.transition(streaming: streaming) else { return }
        let profile = transition == .release
            ? activeVoiceShortcutProfile ?? settings.voiceShortcutProfile
            : settings.voiceShortcutProfile
        guard KeyboardInjector.sendVoiceShortcut(profile: profile, transition: transition) else {
            voiceFunctionKeyLatch.rollback(transition)
            voiceShortcutStatus = "需要辅助功能权限才能触发 \(profile.displayName) 语音"
            AppLogger.shared.write(
                "VOICE SHORTCUT failed profile=\(profile.rawValue) edge=\(transition)"
            )
            return
        }
        if transition == .press {
            activeVoiceShortcutProfile = profile
        } else {
            activeVoiceShortcutProfile = nil
        }
        switch (profile, transition) {
        case (.codex, .press):
            voiceShortcutStatus = "Codex ⌃⇧D 已按下；松开语音键即释放"
        case (.codex, .release):
            voiceShortcutStatus = "Codex ⌃⇧D 已释放"
        case (.workBuddy, .press):
            voiceShortcutStatus = "WorkBuddy ⌘D 已点按；正在录音"
        case (.workBuddy, .release):
            voiceShortcutStatus = "WorkBuddy ⌘D 已再次点按；正在转写"
        case (.weChat, .press):
            voiceShortcutStatus = "微信 Fn 已按住；正在语音输入文字"
        case (.weChat, .release):
            voiceShortcutStatus = "微信 Fn 已释放；语音输入结束"
        }
        AppLogger.shared.write(
            "VOICE SHORTCUT profile=\(profile.rawValue) edge=\(transition) " +
                "chord=\(profile.shortcutDisplayName)"
        )
    }
}
