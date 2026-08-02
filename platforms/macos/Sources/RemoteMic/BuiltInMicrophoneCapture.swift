import AVFoundation
import CoreMedia
import Foundation

/// Captures the Mac's physical built-in microphone explicitly, independent of
/// the system default input. This prevents a connected Bluetooth headset or the
/// MiRemoteV virtual device from becoming the idle passthrough source.
final class BuiltInMicrophoneCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    enum State: Equatable {
        case idle
        case requestingPermission
        case running(deviceName: String)
        case permissionDenied
        case deviceUnavailable
        case failed(message: String)

        var statusText: String {
            switch self {
            case .idle:
                return "电脑麦克风尚未启动"
            case .requestingPermission:
                return "正在请求电脑麦克风权限"
            case let .running(deviceName):
                return "电脑语音：\(deviceName) → MiRemoteV 2ch"
            case .permissionDenied:
                return "未授权电脑麦克风；遥控器语音仍可使用"
            case .deviceUnavailable:
                return "未找到 MacBook 内置麦克风"
            case let .failed(message):
                return "电脑麦克风启动失败：\(message)"
            }
        }
    }

    var onSamples: (([Float], Double) -> Void)?
    var onStateChange: ((State) -> Void)?

    private let session = AVCaptureSession()
    private let queue = DispatchQueue(
        label: "com.mivibe.remote.builtin-microphone",
        qos: .userInteractive
    )
    private var configured = false
    private var startRequested = false

    private(set) var state: State = .idle {
        didSet {
            guard state != oldValue else { return }
            DispatchQueue.main.async { [weak self, state] in
                self?.onStateChange?(state)
            }
        }
    }

    func start() {
        guard !startRequested else { return }
        startRequested = true
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            configureAndStart()
        case .notDetermined:
            state = .requestingPermission
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] granted in
                guard let self else { return }
                if granted {
                    self.configureAndStart()
                } else {
                    self.state = .permissionDenied
                }
            }
        default:
            state = .permissionDenied
        }
    }

    func stop() {
        startRequested = false
        queue.async { [weak self] in
            guard let self else { return }
            if self.session.isRunning {
                self.session.stopRunning()
            }
            self.state = .idle
        }
    }

    func retry() {
        guard !session.isRunning else { return }
        startRequested = false
        start()
    }

    private func configureAndStart() {
        queue.async { [weak self] in
            guard let self, self.startRequested else { return }
            if !self.configured, !self.configureSession() {
                return
            }
            guard !self.session.isRunning else { return }
            self.session.startRunning()
            guard self.session.isRunning else {
                self.state = .failed(message: "采集会话未运行")
                return
            }
            let deviceName = (self.session.inputs.first as? AVCaptureDeviceInput)?
                .device.localizedName ?? "MacBook 麦克风"
            self.state = .running(deviceName: deviceName)
            AppLogger.shared.write(
                "AUDIO BUILTIN_CAPTURE started device=\(deviceName)"
            )
        }
    }

    private func configureSession() -> Bool {
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.microphone],
            mediaType: .audio,
            position: .unspecified
        )
        let device = discovery.devices.first {
            $0.uniqueID == "BuiltInMicrophoneDevice"
        } ?? discovery.devices.first {
            $0.localizedName.localizedCaseInsensitiveContains("MacBook")
        }
        guard let device else {
            state = .deviceUnavailable
            AppLogger.shared.write("AUDIO BUILTIN_CAPTURE failed reason=device_unavailable")
            return false
        }

        do {
            let input = try AVCaptureDeviceInput(device: device)
            let output = AVCaptureAudioDataOutput()
            output.audioSettings = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVLinearPCMBitDepthKey: 32,
                AVLinearPCMIsFloatKey: true,
                AVLinearPCMIsNonInterleaved: false,
                AVNumberOfChannelsKey: 1,
            ]
            output.setSampleBufferDelegate(self, queue: queue)

            session.beginConfiguration()
            guard session.canAddInput(input), session.canAddOutput(output) else {
                session.commitConfiguration()
                state = .failed(message: "无法建立采集通道")
                AppLogger.shared.write("AUDIO BUILTIN_CAPTURE failed reason=cannot_add_io")
                return false
            }
            session.addInput(input)
            session.addOutput(output)
            session.commitConfiguration()
            configured = true
            return true
        } catch {
            state = .failed(message: error.localizedDescription)
            AppLogger.shared.write(
                "AUDIO BUILTIN_CAPTURE failed error=\(error.localizedDescription)"
            )
            return false
        }
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer),
              let streamDescription = CMAudioFormatDescriptionGetStreamBasicDescription(
                  formatDescription
              ),
              streamDescription.pointee.mFormatID == kAudioFormatLinearPCM,
              streamDescription.pointee.mBitsPerChannel == 32,
              streamDescription.pointee.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer)
        else { return }

        let byteCount = CMBlockBufferGetDataLength(blockBuffer)
        guard byteCount >= MemoryLayout<Float>.size else { return }
        var data = Data(count: byteCount)
        let copyStatus = data.withUnsafeMutableBytes { bytes in
            CMBlockBufferCopyDataBytes(
                blockBuffer,
                atOffset: 0,
                dataLength: byteCount,
                destination: bytes.baseAddress!
            )
        }
        guard copyStatus == kCMBlockBufferNoErr else { return }

        let channels = max(1, Int(streamDescription.pointee.mChannelsPerFrame))
        let samples: [Float] = data.withUnsafeBytes { rawBuffer in
            let values = rawBuffer.bindMemory(to: Float.self)
            guard channels > 1 else { return Array(values) }
            let frameCount = values.count / channels
            return (0..<frameCount).map { frame in
                var sum: Float = 0
                for channel in 0..<channels {
                    sum += values[frame * channels + channel]
                }
                return sum / Float(channels)
            }
        }
        onSamples?(samples, streamDescription.pointee.mSampleRate)
    }
}
