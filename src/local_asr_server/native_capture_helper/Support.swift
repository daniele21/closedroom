import Foundation

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
