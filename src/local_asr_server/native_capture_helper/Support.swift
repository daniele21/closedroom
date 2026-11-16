import Foundation
import Darwin

enum CaptureOutputReservation {
    static func claim(_ directory: URL, recordingID: String) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try checkOutputs(directory)
        let marker = directory.appendingPathComponent(".native-capture-run")
        let fd = open(marker.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard fd >= 0 else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 80, userInfo: [
                NSLocalizedDescriptionKey: "Capture destination already claimed or unavailable; recover the existing session."
            ])
        }
        defer { close(fd) }
        // Persistent run identity is intentionally retained on all exits. A
        // restarted capture must use a new session, never an old output path.
        let data = Data((String(recordingID.prefix(512)) + "\n").utf8)
        try data.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let count = Darwin.write(fd, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && errno == EINTR { continue }
                guard count > 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
                offset += count
            }
        }
        guard fsync(fd) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        // Persist session/date entries too, not just the marker inode. These
        // ancestors belong to the canonical recordings root in the API layout.
        for ancestor in [directory, directory.deletingLastPathComponent(),
                         directory.deletingLastPathComponent().deletingLastPathComponent()] {
            let parent = open(ancestor.path, O_RDONLY | O_NOFOLLOW)
            guard parent >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            let result = fsync(parent)
            let failure = errno
            close(parent)
            guard result == 0 else { throw POSIXError(POSIXErrorCode(rawValue: failure) ?? .EIO) }
        }
        try checkOutputs(directory)
    }

    private static func checkOutputs(_ directory: URL) throws {
        for name in ["mic.wav", "system.wav", "recording.wav", ".audio-recovery",
                     "mic.wav.part", "system.wav.part", "recording.wav.part"] {
            let path = directory.appendingPathComponent(name).path
            var info = stat()
            if lstat(path, &info) == 0 {
                let emptyPlaceholder = name.hasSuffix(".part") &&
                    (info.st_mode & S_IFMT) == S_IFREG && info.st_size == 0
                if !emptyPlaceholder {
                    throw NSError(domain: "ClosedRoomNativeCapture", code: 81, userInfo: [
                        NSLocalizedDescriptionKey: "Existing capture output must be recovered, never overwritten."
                    ])
                }
            } else if errno != ENOENT {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
        }
    }
}

final class JSONEmitter {
    static let shared = JSONEmitter()
    private let queue = DispatchQueue(label: "closedroom.native.json-emitter")
    private let key = DispatchSpecificKey<Bool>()

    private init() {
        queue.setSpecific(key: key, value: true)
    }

    func emit(_ payload: [String: Any]) {
        queue.async {
            self.write(payload)
        }
    }

    func emitAndExit(_ payload: [String: Any], exitCode: Int32) -> Never {
        if DispatchQueue.getSpecific(key: key) == true {
            write(payload)
            exit(exitCode)
        } else {
            queue.sync {
                self.write(payload)
            }
            exit(exitCode)
        }
    }

    private func write(_ payload: [String: Any]) {
        do {
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([0x0A]))
        } catch {
            let fallback = #"{"type":"error","message":"json_serialization_failed"}"# + "\n"
            FileHandle.standardOutput.write(fallback.data(using: .utf8)!)
        }
    }
}

final class ScreenshotDiagnosticTrace {
    private let traceID: String
    private let startedUptime = ProcessInfo.processInfo.systemUptime
    private let lock = NSLock()

    init(traceID: String) {
        self.traceID = traceID
    }

    func emit(_ stage: String, fields: [String: Any] = [:]) {
        lock.lock()
        defer { lock.unlock() }

        var payload = fields
        payload["type"] = "screenshot_diagnostic"
        payload["trace_id"] = traceID
        payload["stage"] = stage
        payload["elapsed_ms"] = Int(
            max(0.0, ProcessInfo.processInfo.systemUptime - startedUptime) * 1000.0
        )
        payload["pid"] = Int(ProcessInfo.processInfo.processIdentifier)
        payload["main_thread"] = Thread.isMainThread

        do {
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            let prefix = "CR_SCREENSHOT_DIAG ".data(using: .utf8)!
            FileHandle.standardError.write(prefix)
            FileHandle.standardError.write(data)
            FileHandle.standardError.write(Data([0x0A]))
        } catch {
            let fallback = "CR_SCREENSHOT_DIAG {\"type\":\"screenshot_diagnostic\",\"stage\":\"serialization_failed\"}\n"
            FileHandle.standardError.write(fallback.data(using: .utf8)!)
        }
    }
}
