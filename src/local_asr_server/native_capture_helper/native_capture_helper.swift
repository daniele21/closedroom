import AVFoundation
import CoreGraphics
import CoreImage
import CoreMedia
import Foundation
import ScreenCaptureKit
import Security

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

func calculateDB(from sampleBuffer: CMSampleBuffer) -> Float {
    guard CMSampleBufferDataIsReady(sampleBuffer) else { return -120.0 }
    
    let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer)
    guard let formatDescription = formatDescription else { return -120.0 }
    let absd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription)
    guard let absd = absd else { return -120.0 }
    
    var bufferListSizeNeeded = 0
    var status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
        sampleBuffer,
        bufferListSizeNeededOut: &bufferListSizeNeeded,
        bufferListOut: nil,
        bufferListSize: 0,
        blockBufferAllocator: nil,
        blockBufferMemoryAllocator: nil,
        flags: 0,
        blockBufferOut: nil
    )
    guard status == noErr, bufferListSizeNeeded > 0 else { return -120.0 }
    
    let raw = UnsafeMutableRawPointer.allocate(
        byteCount: bufferListSizeNeeded,
        alignment: MemoryLayout<AudioBufferList>.alignment
    )
    defer { raw.deallocate() }
    
    let bufferListMemory = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
    
    var blockBuffer: CMBlockBuffer?
    status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
        sampleBuffer,
        bufferListSizeNeededOut: nil,
        bufferListOut: bufferListMemory,
        bufferListSize: bufferListSizeNeeded,
        blockBufferAllocator: nil,
        blockBufferMemoryAllocator: nil,
        flags: 0,
        blockBufferOut: &blockBuffer
    )
    guard status == noErr else { return -120.0 }
    
    let bufferList = UnsafeMutableAudioBufferListPointer(bufferListMemory)
    var sumSquares: Float = 0.0
    var sampleCount = 0
    
    let isFloat = (absd.pointee.mFormatFlags & kAudioFormatFlagIsFloat) != 0
    let bitDepth = absd.pointee.mBitsPerChannel
    
    for buffer in bufferList {
        guard let data = buffer.mData else { continue }
        let dataSize = Int(buffer.mDataByteSize)
        
        if isFloat {
            let floatBuffer = data.assumingMemoryBound(to: Float32.self)
            let count = dataSize / MemoryLayout<Float32>.size
            for i in 0..<count {
                let floatSample = floatBuffer[i]
                sumSquares += floatSample * floatSample
            }
            sampleCount += count
        } else if bitDepth == 16 {
            let intBuffer = data.assumingMemoryBound(to: Int16.self)
            let count = dataSize / MemoryLayout<Int16>.size
            for i in 0..<count {
                let floatSample = Float(intBuffer[i]) / 32768.0
                sumSquares += floatSample * floatSample
            }
            sampleCount += count
        }
    }
    
    if sampleCount > 0 {
        let rms = sqrt(sumSquares / Float(sampleCount))
        if rms > 0 {
            let db = 20 * log10(rms)
            return max(-120.0, min(0.0, db))
        }
    }
    return -120.0
}

func requireArg(_ name: String, in args: [String]) -> String? {
    guard let index = args.firstIndex(of: name), index + 1 < args.count else {
        return nil
    }
    return args[index + 1]
}

func runWindows() {
    guard #available(macOS 13.0, *) else {
        JSONEmitter.shared.emitAndExit(["windows": [], "reason": "macos_13_required"], exitCode: 0)
    }
    Task {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
            let ownPID = ProcessInfo.processInfo.processIdentifier
            
            // 1. Get displays
            var list: [[String: Any]] = content.displays.enumerated().map { index, display in
                let displayID = display.displayID
                let sourceID = -Int(displayID)
                return [
                    "id": sourceID,
                    "display_id": Int(displayID),
                    "kind": "display",
                    "title": "Schermo/Screen \(index + 1) (\(display.width)x\(display.height))",
                    "application_name": "Schermo Intero/Full Screen",
                    "bundle_identifier": "com.apple.displays",
                    "width": Int(display.width),
                    "height": Int(display.height),
                ]
            }
            
            // 2. Add windows
            let windows: [[String: Any]] = content.windows.compactMap { window in
                guard window.owningApplication?.processID != ownPID,
                      window.frame.width >= 160, window.frame.height >= 120 else { return nil }
                return [
                    "id": Int(window.windowID),
                    "kind": "window",
                    "title": window.title ?? "",
                    "application_name": window.owningApplication?.applicationName ?? "",
                    "bundle_identifier": window.owningApplication?.bundleIdentifier ?? "",
                    "width": Int(window.frame.width),
                    "height": Int(window.frame.height),
                ]
            }
            list.append(contentsOf: windows)
            JSONEmitter.shared.emitAndExit(["windows": list], exitCode: 0)
        } catch {
            JSONEmitter.shared.emitAndExit(["windows": [], "reason": "window_listing_failed", "error": error.localizedDescription], exitCode: 3)
        }
    }
    RunLoop.main.run()
}

func micStatusString(_ status: AVAuthorizationStatus) -> String {
    switch status {
    case .authorized:
        return "authorized"
    case .denied:
        return "denied"
    case .restricted:
        return "restricted"
    case .notDetermined:
        return "notDetermined"
    @unknown default:
        return "unknown"
    }
}

func capabilityPayload() -> [String: Any] {
    let processInfo = ProcessInfo.processInfo
    let isAtLeastMacOS13 = processInfo.isOperatingSystemAtLeast(
        OperatingSystemVersion(majorVersion: 13, minorVersion: 0, patchVersion: 0)
    )
    let screenCaptureAllowed = CGPreflightScreenCaptureAccess()
    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    let available = isAtLeastMacOS13
    
    let reason: Any
    if !isAtLeastMacOS13 {
        reason = "macos_13_required"
    } else {
        reason = NSNull()
    }
    
    return [
        "available": available,
        "backend": "native",
        "reason": reason,
        "modes": available ? ["both", "mic_only", "pc_only"] : [],
        "minimum_macos": "13.0",
        "visual_window_capture": available,
        "manual_screenshot_capture": available,
        "screen_recording_permission": screenCaptureAllowed ? "granted" : "required",
        "microphone_permission": micStatusString(micStatus),
    ]
}

func permissionsPayload() -> [String: Any] {
    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    let screenCaptureAllowed = CGPreflightScreenCaptureAccess()
    let micOk = micStatus == .authorized
    let screenOk = screenCaptureAllowed
    return [
        "ok": micOk && screenOk,
        "microphone": micStatusString(micStatus),
        "screen_capture": screenCaptureAllowed ? "granted" : "required",
        "modes": [
            "mic_only": ["ok": micOk],
            "pc_only": ["ok": screenOk],
            "both": ["ok": micOk && screenOk]
        ]
    ]
}

func requestPermissions() {
    _ = CGRequestScreenCaptureAccess()
    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    if micStatus == .notDetermined {
        let semaphore = DispatchSemaphore(value: 0)
        AVCaptureDevice.requestAccess(for: .audio) { _ in
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 5.0)
    }
    JSONEmitter.shared.emitAndExit(permissionsPayload(), exitCode: 0)
}

func getCodeSignatureInfo() -> [String: Any] {
    var info: [String: Any] = [
        "signature": "unsigned",
        "team_id": "",
        "identifier": ""
    ]
    var selfCode: SecCode?
    let status = SecCodeCopySelf(SecCSFlags(), &selfCode)
    guard status == errSecSuccess, let code = selfCode else {
        info["error"] = "SecCodeCopySelf failed with status \(status)"
        return info
    }
    var staticCode: SecStaticCode?
    let staticStatus = SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode)
    guard staticStatus == errSecSuccess, let sCode = staticCode else {
        info["error"] = "SecCodeCopyStaticCode failed with status \(staticStatus)"
        return info
    }
    let validityStatus = SecStaticCodeCheckValidity(sCode, SecCSFlags(), nil)
    if validityStatus == errSecSuccess {
        info["signature"] = "signed"
    } else {
        info["validation_error"] = "SecStaticCodeCheckValidity failed with status \(validityStatus)"
    }
    var infoDict: CFDictionary?
    let infoStatus = SecCodeCopySigningInformation(sCode, SecCSFlags(rawValue: kSecCSSigningInformation), &infoDict)
    guard infoStatus == errSecSuccess, let dict = infoDict as? [String: Any] else {
        info["error"] = "SecCodeCopySigningInformation failed with status \(infoStatus)"
        return info
    }
    
    if dict["teamid"] != nil {
        info["team_id"] = dict["teamid"] as? String ?? ""
    }
    info["identifier"] = dict["identifier"] as? String ?? ""
    return info
}

func diagnosticsPayload() -> [String: Any] {
    let processInfo = ProcessInfo.processInfo
    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    let screenCaptureAllowed = CGPreflightScreenCaptureAccess()
    let sigInfo = getCodeSignatureInfo()
    
    return [
        "process_name": processInfo.processName,
        "executable_path": Bundle.main.executablePath ?? CommandLine.arguments.first ?? "",
        "bundle_identifier": Bundle.main.bundleIdentifier ?? "",
        "bundle_path": Bundle.main.bundlePath,
        "screen_capture": screenCaptureAllowed ? "granted" : "required",
        "microphone": micStatusString(micStatus),
        "code_signature": sigInfo["signature"] ?? "unsigned",
        "team_id": sigInfo["team_id"] ?? "",
        "identifier": sigInfo["identifier"] ?? "",
        "macos_version": processInfo.operatingSystemVersionString
    ]
}

final class SampleBufferWavSink {
    let url: URL
    let sourceName: String
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var started = false
    private var finished = false
    private let queue = DispatchQueue(label: "closedroom.native.wav-sink")
    
    private var droppedBuffers = 0
    private var lastEmitDroppedCount = 0
    private var lastEmitDroppedTime: Double = 0

    init(url: URL, sourceName: String) {
        self.url = url
        self.sourceName = sourceName
        try? FileManager.default.removeItem(at: url)
    }

    func append(_ sampleBuffer: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }
        queue.async {
            if self.finished { return }
            do {
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
                    writer.startWriting()
                    writer.startSession(atSourceTime: CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
                    self.started = true
                }
                if input.isReadyForMoreMediaData {
                    let ok = input.append(sampleBuffer)
                    if !ok {
                        JSONEmitter.shared.emit([
                            "type": "error",
                            "source": self.sourceName,
                            "message": "AVAssetWriterInput append failed",
                            "writer_status": "\(writer.status)",
                            "error": writer.error?.localizedDescription ?? "unknown"
                        ])
                    }
                } else {
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
                JSONEmitter.shared.emit([
                    "type": "error",
                    "message": "Failed to initialize WAV writer",
                    "file": self.url.path,
                    "error": String(describing: error),
                ])
            }
        }
    }

    func finish(_ done: @escaping () -> Void) {
        queue.async {
            if self.finished {
                done()
                return
            }
            self.finished = true
            guard let writer = self.writer, let input = self.input, self.started else {
                FileManager.default.createFile(atPath: self.url.path, contents: Data())
                done()
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
                done()
            }
        }
    }
}

@available(macOS 13.0, *)
final class SystemAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    var onSample: ((CMSampleBuffer) -> Void)?
    var onFatalError: ((String) -> Void)?
    private var stream: SCStream?
    private let queue = DispatchQueue(label: "closedroom.native.system-audio")
    private let stateLock = NSLock()
    private var stopRequested = false

    private func beginStop() -> SCStream? {
        stateLock.lock()
        defer { stateLock.unlock() }
        stopRequested = true
        return stream
    }

    private func finishStop() {
        stateLock.lock()
        defer { stateLock.unlock() }
        stream = nil
    }

    private func isStopRequested() -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return stopRequested
    }

    private var reconnectCount = 0
    private let maxReconnects = 5

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 10, userInfo: [
                NSLocalizedDescriptionKey: "No display available for ScreenCaptureKit audio capture"
            ])
        }

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let configuration = SCStreamConfiguration()
        configuration.width = 64
        configuration.height = 64
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = true
        configuration.sampleRate = 16000
        configuration.channelCount = 1

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        try await stream.startCapture()
        stateLock.lock()
        self.stream = stream
        stateLock.unlock()
    }

    func restart() async throws {
        let activeStream = beginStop()
        if let activeStream = activeStream {
            try? await activeStream.stopCapture()
        }
        finishStop()

        stateLock.lock()
        stopRequested = false
        stateLock.unlock()

        try await start()
    }

    func stop() async {
        let activeStream = beginStop()
        if let activeStream = activeStream {
            try? await activeStream.stopCapture()
        }
        finishStop()
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        if isStopRequested() { return }

        let nsError = error as NSError
        let isInterrupted = (
            nsError.domain == SCStreamErrorDomain ||
            nsError.domain == "com.apple.ScreenCaptureKit.SCStreamErrorDomain" ||
            nsError.code == SCStreamError.failedApplicationConnectionInterrupted.rawValue ||
            nsError.code == SCStreamError.failedApplicationConnectionInvalid.rawValue ||
            nsError.code == -3805 ||
            nsError.code == -3804
        )

        if isInterrupted {
            Task {
                var backoff: UInt64 = 400_000_000 // 400ms
                while self.reconnectCount < self.maxReconnects && !self.isStopRequested() {
                    self.reconnectCount += 1
                    let retryMsg = "ScreenCaptureKit audio stream interrupted (\(error.localizedDescription)). Reconnecting (\(self.reconnectCount)/\(self.maxReconnects))..."
                    JSONEmitter.shared.emit([
                        "type": "warning",
                        "source": "system",
                        "message": retryMsg
                    ])
                    try? await Task.sleep(nanoseconds: backoff)
                    guard !self.isStopRequested() else { return }
                    do {
                        try await self.restart()
                        self.reconnectCount = 0
                        JSONEmitter.shared.emit([
                            "type": "info",
                            "source": "system",
                            "message": "ScreenCaptureKit audio stream reconnected successfully."
                        ])
                        return
                    } catch {
                        JSONEmitter.shared.emit([
                            "type": "warning",
                            "source": "system",
                            "message": "ScreenCaptureKit reconnect attempt \(self.reconnectCount) failed (\(error.localizedDescription)). Retrying..."
                        ])
                        backoff = min(backoff * 2, 2_000_000_000)
                    }
                }

                if !self.isStopRequested() {
                    let msg = "ScreenCaptureKit audio stream ended after \(self.maxReconnects) reconnection attempts: \(error.localizedDescription)"
                    self.onFatalError?(msg)
                }
            }
            return
        }

        let msg = "ScreenCaptureKit session error: \(error.localizedDescription)"
        self.onFatalError?(msg)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        onSample?(sampleBuffer)
    }
}

@available(macOS 13.0, *)
final class VisualWindowCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    var onFatalError: ((String) -> Void)?
    private let sourceID: Int
    private let outputDir: URL
    private let fps: Double
    private let epochUptime: Double
    private let queue = DispatchQueue(label: "closedroom.native.visual-window")
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let stateLock = NSLock()
    private var stream: SCStream?
    private var stopRequested = false
    private var sequence = 0

    private func beginStop() -> SCStream? {
        stateLock.lock()
        defer { stateLock.unlock() }
        stopRequested = true
        return stream
    }

    private func finishStop() {
        stateLock.lock()
        defer { stateLock.unlock() }
        stream = nil
    }

    private func isStopRequested() -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return stopRequested
    }

    init(windowID: Int, outputDir: URL, fps: Double, epochUptime: Double) {
        self.sourceID = windowID
        self.outputDir = outputDir
        self.fps = min(2.0, max(0.1, fps))
        self.epochUptime = epochUptime
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
        
        let filter: SCContentFilter
        let frameWidth: CGFloat
        let frameHeight: CGFloat
        
        if sourceID < 0 {
            // It's a display/screen!
            let displayID = CGDirectDisplayID(-sourceID)
            guard let display = content.displays.first(where: { $0.displayID == displayID }) else {
                throw NSError(domain: "ClosedRoomNativeCapture", code: 42, userInfo: [
                    NSLocalizedDescriptionKey: "Selected visual capture display is no longer available"
                ])
            }
            filter = SCContentFilter(display: display, excludingWindows: [])
            frameWidth = CGFloat(display.width)
            frameHeight = CGFloat(display.height)
        } else {
            // It's a window!
            let windowID = CGWindowID(sourceID)
            guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
                throw NSError(domain: "ClosedRoomNativeCapture", code: 41, userInfo: [
                    NSLocalizedDescriptionKey: "Selected visual capture window is no longer available"
                ])
            }
            filter = SCContentFilter(desktopIndependentWindow: window)
            frameWidth = window.frame.width
            frameHeight = window.frame.height
        }
        
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let configuration = SCStreamConfiguration()
        let scale = min(1.0, 1280.0 / max(frameWidth, 1.0))
        configuration.width = max(2, Int(frameWidth * scale))
        configuration.height = max(2, Int(frameHeight * scale))
        configuration.minimumFrameInterval = CMTime(seconds: 1.0 / fps, preferredTimescale: 600)
        configuration.queueDepth = 2
        configuration.showsCursor = false
        configuration.capturesAudio = false
        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try await stream.startCapture()
        self.stream = stream
    }

    func stop() async {
        let activeStream = beginStop()
        if let activeStream = activeStream { try? await activeStream.stopCapture() }
        finishStop()
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        if isStopRequested() { return }

        onFatalError?("Visual ScreenCaptureKit session error: \(error.localizedDescription)")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, CMSampleBufferDataIsReady(sampleBuffer),
              let pixelBuffer = sampleBuffer.imageBuffer else { return }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let qualityKey = CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String)
        guard let data = context.jpegRepresentation(
            of: image, colorSpace: CGColorSpaceCreateDeviceRGB(), options: [qualityKey: 0.75]
        ) else { return }
        let currentSequence = sequence
        sequence += 1
        let timestamp = max(0.0, ProcessInfo.processInfo.systemUptime - epochUptime)
        let name = String(format: "frame-%08d.jpg", currentSequence)
        let path = outputDir.appendingPathComponent(name)
        do {
            try data.write(to: path, options: .atomic)
            let manifest = outputDir.appendingPathComponent("manifest.jsonl")
            let payload: [String: Any] = [
                "sequence": currentSequence, "timestamp": timestamp, "file": name,
                "pts": CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds,
                "observed_uptime": ProcessInfo.processInfo.systemUptime,
            ]
            let line = try JSONSerialization.data(withJSONObject: payload)
            if !FileManager.default.fileExists(atPath: manifest.path) {
                FileManager.default.createFile(atPath: manifest.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: manifest)
            try handle.seekToEnd()
            try handle.write(contentsOf: line)
            try handle.write(contentsOf: Data([0x0A]))
            try handle.synchronize()
            try handle.close()
        } catch {
            try? FileManager.default.removeItem(at: path)
            JSONEmitter.shared.emit(["type": "warning", "source": "visual", "message": error.localizedDescription])
        }
    }
}


@available(macOS 13.0, *)
final class OneShotDisplayCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    var onComplete: ((Result<[String: Any], Error>) -> Void)?
    private let displayID: CGDirectDisplayID
    private let originalURL: URL
    private let thumbnailURL: URL
    private let recordingReadyUptime: Double
    private let queue = DispatchQueue(label: "closedroom.native.screenshot")
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let lock = NSLock()
    private var stream: SCStream?
    private var completed = false

    init(
        displayID: CGDirectDisplayID,
        originalURL: URL,
        thumbnailURL: URL,
        recordingReadyUptime: Double
    ) {
        self.displayID = displayID
        self.originalURL = originalURL
        self.thumbnailURL = thumbnailURL
        self.recordingReadyUptime = recordingReadyUptime
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
        guard let display = content.displays.first(where: { $0.displayID == displayID }) else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 60, userInfo: [
                NSLocalizedDescriptionKey: "Selected screenshot display is no longer available"
            ])
        }

        let ownPID = ProcessInfo.processInfo.processIdentifier
        let excludedWindows = content.windows.filter { window in
            let app = window.owningApplication
            let bundle = (app?.bundleIdentifier ?? "").lowercased()
            let name = (app?.applicationName ?? "").lowercased()
            return app?.processID == ownPID || bundle.contains("closedroom") || name.contains("closedroom")
        }
        let filter = SCContentFilter(display: display, excludingWindows: excludedWindows)
        let configuration = SCStreamConfiguration()
        configuration.width = max(2, Int(display.width))
        configuration.height = max(2, Int(display.height))
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 60)
        configuration.queueDepth = 1
        configuration.showsCursor = false
        configuration.capturesAudio = false

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        self.stream = stream
        try await stream.startCapture()
    }

    func failBeforeStart(_ error: Error) {
        finish(.failure(error), stopStream: false)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        finish(.failure(error), stopStream: false)
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .screen, CMSampleBufferDataIsReady(sampleBuffer),
              let pixelBuffer = sampleBuffer.imageBuffer else { return }

        lock.lock()
        let alreadyCompleted = completed
        lock.unlock()
        if alreadyCompleted { return }

        let capturedUptime = ProcessInfo.processInfo.systemUptime
        let capturedWallTime = Date().timeIntervalSince1970
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let qualityKey = CIImageRepresentationOption(
            rawValue: kCGImageDestinationLossyCompressionQuality as String
        )
        guard let original = context.jpegRepresentation(
            of: image,
            colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [qualityKey: 0.92]
        ) else {
            finish(.failure(NSError(domain: "ClosedRoomNativeCapture", code: 61, userInfo: [
                NSLocalizedDescriptionKey: "Unable to encode screenshot"
            ])))
            return
        }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let scale = min(1.0, 640.0 / Double(max(width, height)))
        let thumbnailImage = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let thumbnail = context.jpegRepresentation(
            of: thumbnailImage,
            colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [qualityKey: 0.78]
        ) else {
            finish(.failure(NSError(domain: "ClosedRoomNativeCapture", code: 62, userInfo: [
                NSLocalizedDescriptionKey: "Unable to encode screenshot thumbnail"
            ])))
            return
        }

        do {
            try original.write(to: originalURL, options: .atomic)
            try thumbnail.write(to: thumbnailURL, options: .atomic)
            let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
            finish(.success([
                "type": "screenshot",
                "display_id": Int(displayID),
                "captured_uptime": capturedUptime,
                "captured_wall_time": capturedWallTime,
                "timestamp": max(0.0, capturedUptime - recordingReadyUptime),
                "pts": pts,
                "width": width,
                "height": height,
                "thumbnail_width": max(1, Int(Double(width) * scale)),
                "thumbnail_height": max(1, Int(Double(height) * scale)),
                "format": "image/jpeg",
                "overlay_exclusion": "closedroom_windows",
            ]))
        } catch {
            try? FileManager.default.removeItem(at: originalURL)
            try? FileManager.default.removeItem(at: thumbnailURL)
            finish(.failure(error))
        }
    }

    private func finish(_ result: Result<[String: Any], Error>, stopStream: Bool = true) {
        lock.lock()
        if completed {
            lock.unlock()
            return
        }
        completed = true
        let callback = onComplete
        onComplete = nil
        let currentStream = stream
        stream = nil
        lock.unlock()

        Task {
            if stopStream, let currentStream = currentStream {
                try? await currentStream.stopCapture()
            }
            callback?(result)
        }
    }
}

@available(macOS 14.0, *)
func captureDisplayScreenshotWithManager(
    displayID: CGDirectDisplayID,
    originalURL: URL,
    thumbnailURL: URL,
    recordingReadyUptime: Double
) async throws -> [String: Any] {
    let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
    guard let display = content.displays.first(where: { $0.displayID == displayID }) else {
        throw NSError(domain: "ClosedRoomNativeCapture", code: 60, userInfo: [
            NSLocalizedDescriptionKey: "Selected screenshot display is no longer available"
        ])
    }

    let ownPID = ProcessInfo.processInfo.processIdentifier
    let excludedWindows = content.windows.filter { window in
        let app = window.owningApplication
        let bundle = (app?.bundleIdentifier ?? "").lowercased()
        let name = (app?.applicationName ?? "").lowercased()
        let title = (window.title ?? "").lowercased()
        return app?.processID == ownPID
            || bundle.contains("closedroom")
            || name.contains("closedroom")
            || title.contains("closedroom")
    }
    let filter = SCContentFilter(display: display, excludingWindows: excludedWindows)
    let configuration = SCStreamConfiguration()
    configuration.width = max(2, Int(display.width))
    configuration.height = max(2, Int(display.height))
    configuration.showsCursor = false
    configuration.capturesAudio = false
    configuration.captureResolution = .best

    let cgImage = try await SCScreenshotManager.captureImage(
        contentFilter: filter,
        configuration: configuration
    )
    let capturedUptime = ProcessInfo.processInfo.systemUptime
    let capturedWallTime = Date().timeIntervalSince1970
    let image = CIImage(cgImage: cgImage)
    let qualityKey = CIImageRepresentationOption(
        rawValue: kCGImageDestinationLossyCompressionQuality as String
    )

    guard let original = CIContext(options: [.cacheIntermediates: false]).jpegRepresentation(
        of: image,
        colorSpace: CGColorSpaceCreateDeviceRGB(),
        options: [qualityKey: 0.92]
    ) else {
        throw NSError(domain: "ClosedRoomNativeCapture", code: 61, userInfo: [
            NSLocalizedDescriptionKey: "Unable to encode screenshot"
        ])
    }

    let width = cgImage.width
    let height = cgImage.height
    let scale = min(1.0, 640.0 / Double(max(width, height)))
    let thumbnailImage = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    guard let thumbnail = CIContext(options: [.cacheIntermediates: false]).jpegRepresentation(
        of: thumbnailImage,
        colorSpace: CGColorSpaceCreateDeviceRGB(),
        options: [qualityKey: 0.78]
    ) else {
        throw NSError(domain: "ClosedRoomNativeCapture", code: 62, userInfo: [
            NSLocalizedDescriptionKey: "Unable to encode screenshot thumbnail"
        ])
    }

    do {
        try original.write(to: originalURL, options: .atomic)
        try thumbnail.write(to: thumbnailURL, options: .atomic)
    } catch {
        try? FileManager.default.removeItem(at: originalURL)
        try? FileManager.default.removeItem(at: thumbnailURL)
        throw error
    }

    return [
        "type": "screenshot",
        "display_id": Int(displayID),
        "captured_uptime": capturedUptime,
        "captured_wall_time": capturedWallTime,
        "timestamp": max(0.0, capturedUptime - recordingReadyUptime),
        "width": width,
        "height": height,
        "thumbnail_width": max(1, Int(Double(width) * scale)),
        "thumbnail_height": max(1, Int(Double(height) * scale)),
        "format": "image/jpeg",
        "overlay_exclusion": "closedroom_windows",
        "capture_backend": "screenshot_manager",
    ]
}

@available(macOS 13.0, *)
func captureDisplayScreenshot(
    displayID: CGDirectDisplayID,
    originalURL: URL,
    thumbnailURL: URL,
    recordingReadyUptime: Double
) async throws -> [String: Any] {
    if #available(macOS 14.0, *) {
        return try await captureDisplayScreenshotWithManager(
            displayID: displayID,
            originalURL: originalURL,
            thumbnailURL: thumbnailURL,
            recordingReadyUptime: recordingReadyUptime
        )
    }

    let capture = OneShotDisplayCapture(
        displayID: displayID,
        originalURL: originalURL,
        thumbnailURL: thumbnailURL,
        recordingReadyUptime: recordingReadyUptime
    )
    return try await withCheckedThrowingContinuation { continuation in
        capture.onComplete = { [capture] result in
            _ = capture
            continuation.resume(with: result)
        }
        Task {
            do {
                try await capture.start()
            } catch {
                capture.failBeforeStart(error)
            }
        }
    }
}

func runScreenshot(
    displayID: Int,
    recordingReadyUptime: Double,
    originalFile: String,
    thumbnailFile: String
) {
    guard #available(macOS 13.0, *) else {
        JSONEmitter.shared.emitAndExit([
            "type": "error",
            "reason": "macos_13_required",
            "message": "Screenshot capture requires macOS 13.0 or later"
        ], exitCode: 3)
    }
    guard CGPreflightScreenCaptureAccess() else {
        JSONEmitter.shared.emitAndExit([
            "type": "error",
            "reason": "screen_capture_permission_required",
            "message": "Screen Recording permission is required for screenshots"
        ], exitCode: 3)
    }

    Task {
        do {
            let result = try await captureDisplayScreenshot(
                displayID: CGDirectDisplayID(displayID),
                originalURL: URL(fileURLWithPath: originalFile),
                thumbnailURL: URL(fileURLWithPath: thumbnailFile),
                recordingReadyUptime: recordingReadyUptime
            )
            JSONEmitter.shared.emitAndExit(result, exitCode: 0)
        } catch {
            JSONEmitter.shared.emitAndExit([
                "type": "error",
                "reason": "screenshot_capture_failed",
                "message": error.localizedDescription
            ], exitCode: 4)
        }
    }
    RunLoop.main.run()
}

final class MicrophoneCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    var onSample: ((CMSampleBuffer) -> Void)?
    var onFatalError: ((String) -> Void)?
    private let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "closedroom.native.microphone")

    override init() {
        super.init()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleRuntimeError),
            name: .AVCaptureSessionRuntimeError,
            object: session
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    @objc private func handleRuntimeError(notification: Notification) {
        if let error = notification.userInfo?[AVCaptureSessionErrorKey] as? Error {
            let msg = "Microphone session runtime error: \(error.localizedDescription)"
            JSONEmitter.shared.emit([
                "type": "error",
                "source": "mic",
                "message": msg
            ])
            onFatalError?(msg)
        }
    }

    func start() throws {
        session.beginConfiguration()
        session.sessionPreset = .high

        guard let device = AVCaptureDevice.default(for: .audio) else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 20, userInfo: [
                NSLocalizedDescriptionKey: "No default microphone is available"
            ])
        }
        let input = try AVCaptureDeviceInput(device: device)
        guard session.canAddInput(input) else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 21, userInfo: [
                NSLocalizedDescriptionKey: "Cannot add microphone input"
            ])
        }
        session.addInput(input)

        let output = AVCaptureAudioDataOutput()
        output.setSampleBufferDelegate(self, queue: queue)
        guard session.canAddOutput(output) else {
            throw NSError(domain: "ClosedRoomNativeCapture", code: 22, userInfo: [
                NSLocalizedDescriptionKey: "Cannot add microphone output"
            ])
        }
        session.addOutput(output)
        session.commitConfiguration()
        session.startRunning()
    }

    func stop() {
        if session.isRunning {
            session.stopRunning()
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        onSample?(sampleBuffer)
    }
}

final class NativeCaptureRun {
    private let recordingID: String
    private let outputDir: URL
    private let mode: String
    private let visualWindowID: Int?
    private let visualFPS: Double
    private var systemCapture: AnyObject?
    private var visualCapture: AnyObject?
    private var microphoneCapture: MicrophoneCapture?
    private var sinks: [SampleBufferWavSink] = []
    
    private let lock = NSLock()
    private var isReady = false
    private var micStarted = false
    private var systemStarted = false
    private var micWritten = false
    private var systemWritten = false
    private var stopped = false

    private var micSink: SampleBufferWavSink?
    private var systemSink: SampleBufferWavSink?
    
    private var lastMicEmitTime: Double = 0
    private var lastSystemEmitTime: Double = 0
    private let emitInterval: Double = 0.1

    init(recordingID: String, outputDir: String, mode: String, visualWindowID: Int?, visualFPS: Double) {
        self.recordingID = recordingID
        self.outputDir = URL(fileURLWithPath: outputDir, isDirectory: true)
        self.mode = mode
        self.visualWindowID = visualWindowID
        self.visualFPS = visualFPS
    }

    func start() async throws {
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

        let needsMic = mode != "pc_only"
        let needsSystem = mode != "mic_only"

        if needsMic {
            let sink = SampleBufferWavSink(url: outputDir.appendingPathComponent("mic.wav"), sourceName: "mic")
            sinks.append(sink)
            micSink = sink

            let capture = MicrophoneCapture()
            capture.onSample = { [weak self] sampleBuffer in
                self?.handleSample(sampleBuffer, source: .mic)
            }
            capture.onFatalError = { [weak self] errMsg in
                self?.stopAndExit(cancelled: true, errorMsg: errMsg)
            }
            microphoneCapture = capture
        }

        if needsSystem {
            let sink = SampleBufferWavSink(url: outputDir.appendingPathComponent("system.wav"), sourceName: "system")
            sinks.append(sink)
            systemSink = sink

            guard #available(macOS 13.0, *) else {
                throw NSError(domain: "ClosedRoomNativeCapture", code: 30, userInfo: [
                    NSLocalizedDescriptionKey: "ScreenCaptureKit audio capture requires macOS 13.0 or later"
                ])
            }
            let capture = SystemAudioCapture()
            capture.onSample = { [weak self] sampleBuffer in
                self?.handleSample(sampleBuffer, source: .system)
            }
            capture.onFatalError = { [weak self] errMsg in
                guard let self = self else { return }
                if self.mode == "both" && self.microphoneCapture != nil {
                    JSONEmitter.shared.emit([
                        "type": "warning",
                        "source": "system",
                        "message": "System audio capture stopped (\(errMsg)). Recording continues with microphone audio."
                    ])
                    self.systemCapture = nil
                } else {
                    self.stopAndExit(cancelled: true, errorMsg: errMsg)
                }
            }
            systemCapture = capture
        }

        // Start ScreenCaptureKit first (async)
        if #available(macOS 13.0, *), let capture = systemCapture as? SystemAudioCapture {
            do {
                try await capture.start()
            } catch {
                throw error
            }
        }

        // Start AVFoundation Microphone second (immediate)
        if let microphoneCapture = microphoneCapture {
            do {
                try microphoneCapture.start()
            } catch {
                if #available(macOS 13.0, *), let capture = systemCapture as? SystemAudioCapture {
                    Task { await capture.stop() }
                }
                throw error
            }
        }

        let readyUptime = ProcessInfo.processInfo.systemUptime
        if let visualWindowID = visualWindowID {
            guard #available(macOS 13.0, *) else {
                throw NSError(domain: "ClosedRoomNativeCapture", code: 40, userInfo: [
                    NSLocalizedDescriptionKey: "Visual window capture requires macOS 13.0 or later"
                ])
            }
            let capture = VisualWindowCapture(
                windowID: visualWindowID,
                outputDir: outputDir.appendingPathComponent(".visual-staging", isDirectory: true),
                fps: visualFPS,
                epochUptime: readyUptime
            )
            capture.onFatalError = { [weak self] message in
                JSONEmitter.shared.emit(["type": "warning", "source": "visual", "message": message])
                self?.visualCapture = nil
            }
            try await capture.start()
            visualCapture = capture
        }

        lock.lock()
        isReady = true
        lock.unlock()

        let now = Date().timeIntervalSince1970
        let uptime = readyUptime
        JSONEmitter.shared.emit([
            "type": "ready",
            "recording_id": recordingID,
            "recording_ready_at": now,
            "recording_ready_uptime": uptime,
            "output_dir": outputDir.path,
            "mode": mode,
            "sample_rate": 16000,
            "channels": 1,
            "visual_capture": visualWindowID != nil,
            "visual_window_id": visualWindowID.map { Int($0) } ?? NSNull(),
        ])
    }

    enum AudioSource {
        case mic
        case system
    }

    private func handleSample(_ sampleBuffer: CMSampleBuffer, source: AudioSource) {
        let now = Date().timeIntervalSince1970
        let uptime = ProcessInfo.processInfo.systemUptime
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)

        var shouldWrite = false
        var emitFirstSample = false
        var emitFirstWritten = false

        lock.lock()
        if source == .mic {
            if !micStarted {
                micStarted = true
                emitFirstSample = true
            }
            if isReady && !micWritten {
                micWritten = true
                emitFirstWritten = true
            }
        } else {
            if !systemStarted {
                systemStarted = true
                emitFirstSample = true
            }
            if isReady && !systemWritten {
                systemWritten = true
                emitFirstWritten = true
            }
        }
        shouldWrite = isReady
        lock.unlock()

        if emitFirstSample {
            JSONEmitter.shared.emit([
                "type": "track_first_sample",
                "source": source == .mic ? "mic" : "system",
                "observed_wall_time": now,
                "observed_uptime": uptime,
                "pts": pts.seconds
            ])
        }

        if emitFirstWritten {
            JSONEmitter.shared.emit([
                "type": "track_first_written_sample",
                "source": source == .mic ? "mic" : "system",
                "written_wall_time": now,
                "written_uptime": uptime,
                "pts": pts.seconds
            ])
        }

        if shouldWrite {
            if source == .mic {
                micSink?.append(sampleBuffer)

                lock.lock()
                let emit = now - lastMicEmitTime >= emitInterval
                if emit {
                    lastMicEmitTime = now
                }
                lock.unlock()

                if emit {
                    let db = calculateDB(from: sampleBuffer)
                    JSONEmitter.shared.emit([
                        "type": "volume",
                        "source": "mic",
                        "db": db
                    ])
                }
            } else {
                systemSink?.append(sampleBuffer)

                lock.lock()
                let emit = now - lastSystemEmitTime >= emitInterval
                if emit {
                    lastSystemEmitTime = now
                }
                lock.unlock()

                if emit {
                    let db = calculateDB(from: sampleBuffer)
                    JSONEmitter.shared.emit([
                        "type": "volume",
                        "source": "system",
                        "db": db
                    ])
                }
            }
        }
    }

    func stopAndExit(cancelled: Bool = false, errorMsg: String? = nil) {
        lock.lock()
        if stopped {
            lock.unlock()
            return
        }
        stopped = true
        lock.unlock()

        microphoneCapture?.stop()
        if #available(macOS 13.0, *) {
            Task {
                if let capture = visualCapture as? VisualWindowCapture { await capture.stop() }
                if let capture = systemCapture as? SystemAudioCapture { await capture.stop() }
                finishSinks(cancelled: cancelled, errorMsg: errorMsg)
            }
        } else {
            finishSinks(cancelled: cancelled, errorMsg: errorMsg)
        }
    }

    private func finishSinks(cancelled: Bool, errorMsg: String?) {
        let group = DispatchGroup()
        for sink in sinks {
            group.enter()
            sink.finish {
                group.leave()
            }
        }
        group.notify(queue: .main) {
            if let errorMsg = errorMsg {
                for sink in self.sinks {
                    try? FileManager.default.removeItem(at: sink.url)
                }
                try? FileManager.default.removeItem(at: self.outputDir.appendingPathComponent(".visual-staging"))
            } else if cancelled {
                try? FileManager.default.removeItem(at: self.outputDir.appendingPathComponent(".visual-staging"))
            }
            if let errorMsg = errorMsg {
                JSONEmitter.shared.emitAndExit([
                    "type": "error",
                    "recording_id": self.recordingID,
                    "message": errorMsg,
                ], exitCode: 4)
            } else {
                JSONEmitter.shared.emitAndExit([
                    "type": "stopped",
                    "recording_id": self.recordingID,
                    "cancelled": cancelled,
                ], exitCode: 0)
            }
        }
    }
}

func runStart(recordingID: String, outputDir: String, mode: String, visualWindowID: Int?, visualFPS: Double) {
    guard ["both", "mic_only", "pc_only"].contains(mode) else {
        JSONEmitter.shared.emitAndExit(["type": "error", "message": "Invalid capture mode: \(mode)"], exitCode: 2)
    }

    let capabilities = capabilityPayload()
    guard capabilities["available"] as? Bool == true else {
        JSONEmitter.shared.emitAndExit([
            "type": "error",
            "recording_id": recordingID,
            "output_dir": outputDir,
            "mode": mode,
            "message": "Native capture is not available on this macOS version (macOS 13.0+ required).",
            "reason": capabilities["reason"] ?? "native_unavailable",
        ], exitCode: 3)
    }

    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    let micAllowed = micStatus == .authorized
    let screenCaptureAllowed = CGPreflightScreenCaptureAccess()

    var missing: [String] = []
    if mode == "both" || mode == "mic_only" {
        if !micAllowed {
            missing.append("microphone")
        }
    }
    if mode == "both" || mode == "pc_only" || visualWindowID != nil {
        if !screenCaptureAllowed {
            missing.append("screen_capture")
        }
    }

    if !missing.isEmpty {
        let sigInfo = getCodeSignatureInfo()
        JSONEmitter.shared.emitAndExit([
            "type": "error",
            "recording_id": recordingID,
            "reason": "permissions_missing",
            "missing_permissions": missing,
            "microphone": micStatusString(micStatus),
            "screen_capture": screenCaptureAllowed ? "granted" : "required",
            "executable_path": Bundle.main.executablePath ?? CommandLine.arguments.first ?? "",
            "bundle_identifier": Bundle.main.bundleIdentifier ?? "",
            "code_signature": sigInfo["signature"] ?? "unsigned",
            "team_id": sigInfo["team_id"] ?? "",
            "identifier": sigInfo["identifier"] ?? "",
            "message": "Required permissions are missing: \(missing.joined(separator: ", "))"
        ], exitCode: 3)
    }

    let run = NativeCaptureRun(
        recordingID: recordingID, outputDir: outputDir, mode: mode,
        visualWindowID: visualWindowID, visualFPS: visualFPS
    )
    signal(SIGTERM, SIG_IGN)
    signal(SIGINT, SIG_IGN)
    let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
    termSource.setEventHandler { run.stopAndExit() }
    intSource.setEventHandler { run.stopAndExit(cancelled: true) }
    termSource.resume()
    intSource.resume()

    Task {
        do {
            try await run.start()
        } catch {
            run.stopAndExit(cancelled: true, errorMsg: error.localizedDescription)
        }
    }
    RunLoop.main.run()
}

let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first else {
    JSONEmitter.shared.emitAndExit(["type": "error", "message": "Missing command"], exitCode: 1)
}

switch command {
case "capabilities":
    JSONEmitter.shared.emitAndExit(capabilityPayload(), exitCode: 0)
case "permissions":
    JSONEmitter.shared.emitAndExit(permissionsPayload(), exitCode: 0)
case "request-permissions":
    requestPermissions()
case "diagnostics":
    JSONEmitter.shared.emitAndExit(diagnosticsPayload(), exitCode: 0)
case "windows":
    runWindows()
case "screenshot":
    guard let displayID = requireArg("--display-id", in: args).flatMap({ Int($0) }),
          let recordingReadyUptime = requireArg("--recording-ready-uptime", in: args).flatMap({ Double($0) }),
          let originalFile = requireArg("--original-file", in: args),
          let thumbnailFile = requireArg("--thumbnail-file", in: args) else {
        JSONEmitter.shared.emitAndExit([
            "type": "error",
            "reason": "invalid_screenshot_arguments",
            "message": "Missing required screenshot arguments"
        ], exitCode: 2)
    }
    runScreenshot(
        displayID: displayID,
        recordingReadyUptime: recordingReadyUptime,
        originalFile: originalFile,
        thumbnailFile: thumbnailFile
    )
case "start":
    guard let recordingID = requireArg("--recording-id", in: args),
          let outputDir = requireArg("--output-dir", in: args),
          let mode = requireArg("--mode", in: args) else {
        JSONEmitter.shared.emitAndExit(["type": "error", "message": "Missing required start arguments"], exitCode: 2)
    }
    let visualWindowID = requireArg("--visual-window-id", in: args).flatMap { Int($0) }
    let visualFPS = requireArg("--visual-fps", in: args).flatMap { Double($0) } ?? 0.5
    runStart(
        recordingID: recordingID, outputDir: outputDir, mode: mode,
        visualWindowID: visualWindowID, visualFPS: visualFPS
    )
default:
    JSONEmitter.shared.emitAndExit(["type": "error", "message": "Unknown command: \(command)"], exitCode: 1)
}