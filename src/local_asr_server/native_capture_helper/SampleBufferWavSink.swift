import Foundation
import AVFoundation
import CoreMedia

final class SampleBufferWavSink {
    let url: URL
    let sourceName: String
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var started = false
    private var finished = false
    private let queue = DispatchQueue(label: "closedroom.native.wav-sink")
    private let admissionLock = NSLock()
    private var pendingBytes = 0
    private var failed = false
    private var mainWriterDisabledAfterSwitch = false
    private var recovery: AudioRecoverySegments?
    var onFailure: (() -> Void)?

    private var droppedBuffers = 0
    private var lastEmitDroppedCount = 0
    private var lastEmitDroppedTime: Double = 0

    init(url: URL, sourceName: String, checkpointed: Bool = true) {
        self.url = url
        self.sourceName = sourceName
        if checkpointed {
            self.recovery = AudioRecoverySegments(
                directory: url.deletingLastPathComponent().appendingPathComponent(".audio-recovery").appendingPathComponent(sourceName),
                source: sourceName
            )
            self.recovery?.onFailure = { [weak self] in self?.reportFailure("audio_checkpoint_failed") }
        }
    }

    private func reportFailure(_ reason: String) {
        admissionLock.lock()
        let first = !failed
        failed = true
        admissionLock.unlock()
        if first {
            JSONEmitter.shared.emit(["type": "error", "source": sourceName, "reason": reason, "message": reason])
            onFailure?()
        }
    }

    // The original WAV becomes a valid, immutable prefix after an input
    // switch. New audio goes exclusively to checkpoint segments; RecordingStore
    // may publish a verified aligned derivative without overwriting the prefix.
    func markInputDiscontinuity() {
        queue.async {
            self.recovery?.markDiscontinuity()
            self.mainWriterDisabledAfterSwitch = true
        }
    }

    func append(_ sampleBuffer: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }
        let size = max(1, CMSampleBufferGetTotalSampleSize(sampleBuffer))
        admissionLock.lock()
        let admitted = !failed && size <= 8 * 1024 * 1024 - pendingBytes
        if admitted { pendingBytes += size }
        admissionLock.unlock()
        guard admitted else {
            reportFailure("audio_writer_backpressure")
            return
        }
        queue.async {
            defer {
                self.admissionLock.lock()
                self.pendingBytes -= size
                self.admissionLock.unlock()
            }
            if self.finished { return }
            do {
                try self.recovery?.append(sampleBuffer)
                if self.mainWriterDisabledAfterSwitch { return }
                if self.writer == nil {
                    let writer = try AVAssetWriter(outputURL: self.url, fileType: .wav)

                    let audioSettings: [String: Any] = [
                        AVFormatIDKey: kAudioFormatLinearPCM,
                        AVSampleRateKey: 16000.0,
                        AVNumberOfChannelsKey: 1,
                        AVLinearPCMBitDepthKey: 16,
                        AVLinearPCMIsNonInterleaved: false,
                        AVLinearPCMIsFloatKey: false,
                        AVLinearPCMIsBigEndianKey: false
                    ]

                    let input = AVAssetWriterInput(mediaType: .audio, outputSettings: audioSettings)
                    input.expectsMediaDataInRealTime = true
                    guard writer.canAdd(input) else {
                        self.reportFailure("audio_writer_input_unavailable")
                        JSONEmitter.shared.emit([
                            "type": "error",
                            "message": "Cannot add WAV audio input",
                            "file": self.url.path,
                        ])
                        return
                    }
                    writer.add(input)
                    self.writer = writer
                    self.input = input
                }

                guard let writer = self.writer, let input = self.input else { return }
                if !self.started {
                    guard writer.startWriting() else {
                        self.reportFailure("audio_writer_start_failed")
                        return
                    }
                    writer.startSession(atSourceTime: CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
                    self.started = true
                }
                if input.isReadyForMoreMediaData {
                    let ok = input.append(sampleBuffer)
                    if !ok {
                        self.reportFailure("audio_writer_append_failed")
                        JSONEmitter.shared.emit([
                            "type": "error",
                            "source": self.sourceName,
                            "message": "AVAssetWriterInput append failed",
                            "writer_status": "\(writer.status)",
                            "error": writer.error?.localizedDescription ?? "unknown"
                        ])
                    }
                } else {
                    // An incomplete checkpoint is never promoted as a complete
                    // prefix. The main WAV keeps its existing health reporting.
                    if self.recovery == nil { self.reportFailure("audio_checkpoint_backpressure") }
                    self.droppedBuffers += 1
                    let now = Date().timeIntervalSince1970
                    if self.droppedBuffers - self.lastEmitDroppedCount >= 10 || (now - self.lastEmitDroppedTime >= 2.0 && self.droppedBuffers > self.lastEmitDroppedCount) {
                        self.lastEmitDroppedCount = self.droppedBuffers
                        self.lastEmitDroppedTime = now
                        JSONEmitter.shared.emit([
                            "type": "health",
                            "source": self.sourceName,
                            "dropped_buffers": self.droppedBuffers
                        ])
                    }
                }
            } catch {
                self.reportFailure("audio_writer_or_checkpoint_failed")
                JSONEmitter.shared.emit([
                    "type": "error",
                    "message": "Failed to initialize WAV writer",
                    "file": self.url.path,
                    "error": String(describing: error),
                ])
            }
        }
    }

    func finish(_ done: @escaping (Bool) -> Void) {
        queue.async {
            if self.finished {
                done(self.writer?.status == .completed)
                return
            }
            self.finished = true
            let group = DispatchGroup()
            if let recovery = self.recovery {
                group.enter()
                recovery.finish { group.leave() }
            }
            group.enter()
            guard let writer = self.writer, let input = self.input, self.started else {
                group.leave()
                group.notify(queue: self.queue) { done(false) }
                return
            }
            input.markAsFinished()
            writer.finishWriting {
                if writer.status == .failed {
                    JSONEmitter.shared.emit([
                        "type": "error",
                        "message": "Failed to finish WAV writer",
                        "file": self.url.path,
                        "error": writer.error?.localizedDescription ?? "unknown",
                    ])
                }
                group.leave()
            }
            group.notify(queue: self.queue) {
                self.admissionLock.lock()
                let failed = self.failed
                self.admissionLock.unlock()
                done(writer.status == .completed && !failed)
            }
        }
    }
}
