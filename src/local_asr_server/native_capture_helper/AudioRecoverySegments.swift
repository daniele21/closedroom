import Foundation
import AVFoundation
import CoreMedia
import CryptoKit
import Darwin

// Independent one-second WAVs remain usable when the long-running writer is
// killed before finishWriting. A segment becomes a checkpoint only after both
// its audio and checksum manifest have been synced and published exclusively.
final class AudioRecoverySegments {
    private let directory: URL
    private let source: String
    private let group = DispatchGroup()
    private let lock = NSCondition()
    private var inflight = 0
    private var failed = false
    private var current: SampleBufferWavSink?
    private var startPTS = 0.0
    private var endPTS = 0.0
    private var nextDiscontinuity = false
    private var currentDiscontinuity = false
    private var sequence = 0
    private var nextPublication = 0
    private var totalFrames: Int64 = 0
    var onFailure: (() -> Void)?

    init(directory: URL, source: String) {
        self.directory = directory
        self.source = source
    }

    // Called on the owning SampleBufferWavSink queue. A source handover
    // seals the current immutable checkpoint before the new clock/rate starts.
    func markDiscontinuity() {
        if current != nil { seal() }
        nextDiscontinuity = true
    }

    func append(_ sample: CMSampleBuffer) throws {
        let pts = CMSampleBufferGetPresentationTimeStamp(sample).seconds
        guard pts.isFinite else { throw POSIXError(.EINVAL) }
        lock.lock()
        let unavailable = failed || inflight >= 4
        lock.unlock()
        guard !unavailable else { throw POSIXError(.EIO) }
        if current != nil && pts - startPTS >= 1.0 { seal() }
        if current == nil {
            guard sequence < 86400 else { throw POSIXError(.EFBIG) }
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            // Sync every newly created ancestor before acknowledging a child.
            try Self.syncDirectory(directory.deletingLastPathComponent().deletingLastPathComponent())
            try Self.syncDirectory(directory.deletingLastPathComponent())
            try Self.syncDirectory(directory)
            let sink = SampleBufferWavSink(url: temporaryURL(sequence), sourceName: source, checkpointed: false)
            sink.onFailure = { [weak self] in self?.fail() }
            current = sink
            startPTS = pts
            currentDiscontinuity = nextDiscontinuity
            nextDiscontinuity = false
        }
        var duration = CMSampleBufferGetDuration(sample).seconds
        if !duration.isFinite || duration <= 0 {
            if let format = CMSampleBufferGetFormatDescription(sample),
               let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format), asbd.pointee.mSampleRate > 0 {
                duration = Double(CMSampleBufferGetNumSamples(sample)) / asbd.pointee.mSampleRate
            }
        }
        guard duration.isFinite && duration > 0 else { throw POSIXError(.EINVAL) }
        endPTS = pts + duration
        current?.append(sample)
    }

    func finish(_ done: @escaping () -> Void) {
        if current != nil { seal() }
        group.notify(queue: .global(qos: .utility), execute: done)
    }

    private func temporaryURL(_ index: Int) -> URL {
        directory.appendingPathComponent(String(format: ".%08d.wav.part", index))
    }

    private func fail() {
        lock.lock()
        let first = !failed
        failed = true
        lock.broadcast()
        lock.unlock()
        if first { onFailure?() }
    }

    private func seal() {
        guard let sink = current else { return }
        let index = sequence
        let start = startPTS
        let end = endPTS
        let discontinuity = currentDiscontinuity
        sequence += 1
        current = nil
        lock.lock()
        inflight += 1
        lock.unlock()
        group.enter()
        sink.finish { [self] success in
            defer {
                lock.lock()
                inflight -= 1
                lock.unlock()
                group.leave()
            }
            guard success else { fail(); return }
            // Asset writers may finish out of order. Publish only a contiguous
            // prefix so a crash never leaves a later acknowledged segment behind
            // an uncommitted earlier one. Waiting is bounded and failure wakes all.
            lock.lock()
            let deadline = Date().addingTimeInterval(5)
            while index != nextPublication && !failed {
                if !lock.wait(until: deadline) {
                    lock.unlock()
                    fail()
                    return
                }
            }
            let aborted = failed
            lock.unlock()
            if aborted { return }
            do {
                let started = ProcessInfo.processInfo.systemUptime
                let temporary = temporaryURL(index)
                let audio = directory.appendingPathComponent(String(format: "%08d.wav", index))
                try Self.syncFile(temporary)
                let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size > 0 && size <= 4 * 1024 * 1024 else { throw POSIXError(.EFBIG) }
                let data = try Data(contentsOf: temporary, options: .mappedIfSafe)
                let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
                let frameCount = try AVAudioFile(forReading: temporary).length
                guard frameCount > 0 else { throw POSIXError(.EIO) }
                lock.lock()
                let committedFrames = totalFrames + frameCount
                lock.unlock()
                guard committedFrames <= 16000 * 86400 else { throw POSIXError(.EFBIG) }
                // link() refuses an existing target; unlike rename it never
                // replaces an earlier checkpoint. Keep staging on any failure.
                guard link(temporary.path, audio.path) == 0 else { throw Self.ioError() }
                try Self.syncDirectory(directory)
                let manifest: [String: Any] = [
                    "version": 1, "source": source, "sequence": index,
                    "file": audio.lastPathComponent, "bytes": data.count,
                    "sha256": digest, "start_pts": start, "end_pts": end,
                    "frames": frameCount, "total_frames": committedFrames,
                    "discontinuity_before": discontinuity,
                ]
                let payload = try JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys])
                let pending = directory.appendingPathComponent(String(format: ".%08d.json.part", index))
                let committed = directory.appendingPathComponent(String(format: "%08d.json", index))
                try Self.writeExclusive(payload, to: pending)
                guard link(pending.path, committed.path) == 0 else { throw Self.ioError() }
                try Self.syncDirectory(directory)
                // Only redundant links are removed, after the immutable pair
                // has been committed. Original audio is retained until discard.
                unlink(temporary.path)
                unlink(pending.path)
                lock.lock()
                totalFrames = committedFrames
                nextPublication += 1
                lock.broadcast()
                lock.unlock()
                JSONEmitter.shared.emit([
                    "type": "audio_checkpoint", "source": source,
                    "sequence": index, "start_pts": start, "end_pts": end,
                    "bytes": data.count,
                    "ack_uptime": ProcessInfo.processInfo.systemUptime,
                    "commit_ms": (ProcessInfo.processInfo.systemUptime - started) * 1000,
                ])
            } catch { fail() }
        }
    }

    private static func ioError() -> POSIXError { POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }

    private static func writeExclusive(_ data: Data, to url: URL) throws {
        let fd = open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw ioError() }
        defer { close(fd) }
        try data.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let count = Darwin.write(fd, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && errno == EINTR { continue }
                guard count > 0 else { throw ioError() }
                offset += count
            }
        }
        guard fsync(fd) == 0 else { throw ioError() }
    }

    private static func syncFile(_ url: URL) throws {
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW)
        guard fd >= 0 else { throw ioError() }
        defer { close(fd) }
        guard fsync(fd) == 0 else { throw ioError() }
    }

    private static func syncDirectory(_ url: URL) throws { try syncFile(url) }
}
