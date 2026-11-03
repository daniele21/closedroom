import Foundation
import AVFoundation
import CoreMedia

// Owns exactly one microphone source at a time. A route change never ends the
// run or recreates NativeCaptureRun; ScreenCaptureKit keeps recording normally.
final class MicrophoneCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    var onSample: ((CMSampleBuffer) -> Void)?
    var onInputDiscontinuity: (() -> Void)?

    private let control = DispatchQueue(label: "closedroom.native.microphone-control")
    private let samples = DispatchQueue(label: "closedroom.native.microphone-samples")
    private var session: AVCaptureSession?
    private var output: AVCaptureAudioDataOutput?
    private var deviceID: String?
    private var monitor: DispatchSourceTimer?
    private var deviceObservers: [NSObjectProtocol] = []
    private var runtimeObserver: NSObjectProtocol?
    private var stopped = false
    private var recovering = false
    private var unavailable = false
    private var awaitingSamples = false
    private var ptsOffset: CMTime?
    private var lastAttemptUptime = 0.0
    private let retryIntervalSeconds = 1.5
    private let sampleReadyTimeoutSeconds = 4.0

    func start() throws {
        try control.sync {
            guard !stopped else { throw captureError(23, "Microphone is stopped") }
            guard let device = preferredDevice() else {
                throw captureError(20, "No available microphone")
            }
            try configure(device: device)
            installObservers()
            installMonitor()
        }
    }

    func stop() {
        control.sync {
            guard !stopped else { return }
            stopped = true
            monitor?.cancel()
            monitor = nil
            for token in deviceObservers {
                NotificationCenter.default.removeObserver(token)
            }
            deviceObservers.removeAll()
            closeCurrentSession()
        }
    }

    private func captureError(_ code: Int, _ message: String) -> NSError {
        NSError(domain: "ClosedRoomNativeCapture", code: code, userInfo: [
            NSLocalizedDescriptionKey: message
        ])
    }

    private func preferredDevice() -> AVCaptureDevice? {
        AVCaptureDevice.default(for: .audio) ?? AVCaptureDevice.devices(for: .audio).first
    }

    private func emit(_ type: String, reason: String) {
        JSONEmitter.shared.emit([
            "type": type,
            "source": "mic",
            "reason": reason,
            "uptime": ProcessInfo.processInfo.systemUptime,
        ])
    }

    private func installObservers() {
        let center = NotificationCenter.default
        // A connection event avoids waiting for the periodic default-device
        // comparison. Polling also covers a default change with both devices
        // still connected, which does not produce a disconnect notification.
        for name in [AVCaptureDevice.wasConnectedNotification, AVCaptureDevice.wasDisconnectedNotification] {
            let observer = center.addObserver(forName: name, object: nil, queue: nil) { [weak self] _ in
                self?.control.async { [weak self] in self?.reconcileInput() }
            }
            deviceObservers.append(observer)
        }
    }

    private func installMonitor() {
        let timer = DispatchSource.makeTimerSource(queue: control)
        timer.schedule(deadline: .now() + .milliseconds(900), repeating: .seconds(1))
        timer.setEventHandler { [weak self] in self?.reconcileInput() }
        monitor = timer
        timer.resume()
    }

    private func closeCurrentSession() {
        if let observer = runtimeObserver {
            NotificationCenter.default.removeObserver(observer)
            runtimeObserver = nil
        }
        output?.setSampleBufferDelegate(nil, queue: nil)
        // Serial control queue prevents overlapping AVCaptureSession teardown,
        // reconfiguration and explicit Stop.
        session?.stopRunning()
        session = nil
        output = nil
        deviceID = nil
    }

    private func configure(device: AVCaptureDevice) throws {
        let replacement = AVCaptureSession()
        replacement.beginConfiguration()
        replacement.sessionPreset = .high
        let input = try AVCaptureDeviceInput(device: device)
        guard replacement.canAddInput(input) else {
            replacement.commitConfiguration()
            throw captureError(21, "Cannot add microphone input")
        }
        replacement.addInput(input)
        let target = AVCaptureAudioDataOutput()
        target.setSampleBufferDelegate(self, queue: samples)
        guard replacement.canAddOutput(target) else {
            replacement.commitConfiguration()
            throw captureError(22, "Cannot add microphone output")
        }
        replacement.addOutput(target)
        replacement.commitConfiguration()
        replacement.startRunning()
        guard replacement.isRunning else {
            target.setSampleBufferDelegate(nil, queue: nil)
            throw captureError(24, "Microphone session did not start")
        }
        session = replacement
        output = target
        deviceID = device.uniqueID
        awaitingSamples = true
        ptsOffset = nil
        lastAttemptUptime = ProcessInfo.processInfo.systemUptime
        runtimeObserver = NotificationCenter.default.addObserver(
            forName: .AVCaptureSessionRuntimeError,
            object: replacement,
            queue: nil
        ) { [weak self] _ in
            self?.control.async { [weak self] in
                self?.beginRecovery(reason: "microphone_runtime_interruption")
                self?.reconcileInput()
            }
        }
    }

    private func beginRecovery(reason: String) {
        guard !stopped else { return }
        if !recovering {
            recovering = true
            emit("source_interrupted", reason: reason)
            onInputDiscontinuity?()
            emit("source_recovering", reason: reason)
        }
        // The old session must be torn down before a replacement starts.
        closeCurrentSession()
    }

    private func reconcileInput() {
        guard !stopped else { return }
        let now = ProcessInfo.processInfo.systemUptime
        let available = preferredDevice()
        if available == nil {
            if session != nil { beginRecovery(reason: "microphone_disconnected") }
            if recovering && !unavailable {
                unavailable = true
                emit("source_unavailable", reason: "no_authorized_input")
            }
            return
        }
        guard let device = available else { return }
        let deviceChanged = device.uniqueID != deviceID
        let noSamples = awaitingSamples && now - lastAttemptUptime >= sampleReadyTimeoutSeconds
        let inactive = !(session?.isRunning ?? false)
        if !deviceChanged && !noSamples && !inactive { return }
        if !recovering {
            beginRecovery(reason: deviceChanged ? "default_input_changed" : "microphone_not_running")
        }
        guard now - lastAttemptUptime >= retryIntervalSeconds else { return }
        closeCurrentSession()
        lastAttemptUptime = now
        do {
            try configure(device: device)
            if unavailable {
                unavailable = false
                emit("source_recovering", reason: "input_available")
            }
            // Do not report recovery yet: success requires an actual sample.
        } catch {
            if !unavailable {
                unavailable = true
                emit("source_unavailable", reason: "microphone_start_failed")
            }
        }
    }

    // Each AVCaptureSession may use a different presentation clock origin.
    // Normalize at the source boundary to the same system-uptime epoch used
    // by the recording timeline; keep each buffer's packet duration unchanged.
    private func normalizedSample(_ sample: CMSampleBuffer) -> CMSampleBuffer? {
        let presentation = CMSampleBufferGetPresentationTimeStamp(sample)
        guard presentation.isValid && presentation.isNumeric else { return nil }
        if ptsOffset == nil {
            let uptime = CMTime(seconds: ProcessInfo.processInfo.systemUptime, preferredTimescale: 1_000_000)
            ptsOffset = CMTimeSubtract(uptime, presentation)
        }
        guard let delta = ptsOffset else { return nil }
        var count: CMItemCount = 0
        guard CMSampleBufferGetSampleTimingInfoArray(sample, entryCount: 0, arrayToFill: nil, entriesNeededOut: &count) == noErr,
              count > 0 else { return nil }
        var timings = Array(repeating: CMSampleTimingInfo(
            duration: .invalid, presentationTimeStamp: .invalid, decodeTimeStamp: .invalid
        ), count: count)
        let status = timings.withUnsafeMutableBufferPointer { buffer in
            CMSampleBufferGetSampleTimingInfoArray(
                sample, entryCount: count, arrayToFill: buffer.baseAddress, entriesNeededOut: &count
            )
        }
        guard status == noErr else { return nil }
        for i in timings.indices {
            timings[i].presentationTimeStamp = CMTimeAdd(timings[i].presentationTimeStamp, delta)
            if timings[i].decodeTimeStamp.isValid {
                timings[i].decodeTimeStamp = CMTimeAdd(timings[i].decodeTimeStamp, delta)
            }
        }
        var translated: CMSampleBuffer?
        let copyStatus = timings.withUnsafeBufferPointer { buffer in
            CMSampleBufferCreateCopyWithNewTiming(
                allocator: kCFAllocatorDefault, sampleBuffer: sample,
                sampleTimingEntryCount: count, sampleTimingArray: buffer.baseAddress,
                sampleBufferOut: &translated
            )
        }
        guard copyStatus == noErr else { return nil }
        return translated
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        // The delegate queue may still deliver samples from a removed device.
        // Only the current output may write after the serialized handover.
        control.async { [weak self] in
            guard let self = self, !self.stopped, self.output === output else { return }
            guard let normalized = self.normalizedSample(sampleBuffer) else {
                self.beginRecovery(reason: "microphone_timing_invalid")
                return
            }
            if self.awaitingSamples {
                self.awaitingSamples = false
                if self.recovering {
                    self.recovering = false
                    self.unavailable = false
                    self.emit("source_recovered", reason: "microphone_samples_resumed")
                }
            }
            self.onSample?(normalized)
        }
    }
}
