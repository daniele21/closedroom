import Foundation
import AVFoundation
import CoreMedia
import Darwin

@main
struct NativeDurabilityProbe {
    static func main() {
        do { try run() }
        catch { JSONEmitter.shared.emitAndExit(["type": "probe_error"], exitCode: 8) }
    }

    private static func run() throws {
        let directory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        if CommandLine.arguments[1] == "empty-finish" {
            let sink = SampleBufferWavSink(url: directory.appendingPathComponent("mic.wav"), sourceName: "mic")
            sink.finish { _ in JSONEmitter.shared.emitAndExit(["type": "probe_finished"], exitCode: 0) }
            dispatchMain()
        }
        try CaptureOutputReservation.claim(directory, recordingID: "synthetic-durability-probe")
        if CommandLine.arguments[1] == "claim" { return }
        let floatInput = CommandLine.arguments[1].hasSuffix("48k")
        let rate = floatInput ? 48000 : 16000
        let count = rate / 10
        let width: UInt32 = floatInput ? 4 : 2
        var asbd = AudioStreamBasicDescription(mSampleRate: Double(rate), mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: (floatInput ? kAudioFormatFlagIsFloat : kAudioFormatFlagIsSignedInteger) | kAudioFormatFlagIsPacked,
            mBytesPerPacket: width, mFramesPerPacket: 1, mBytesPerFrame: width,
            mChannelsPerFrame: 1, mBitsPerChannel: width * 8, mReserved: 0)
        var format: CMAudioFormatDescription?
        guard CMAudioFormatDescriptionCreate(allocator: kCFAllocatorDefault, asbd: &asbd,
            layoutSize: 0, layout: nil, magicCookieSize: 0, magicCookie: nil,
            extensions: nil, formatDescriptionOut: &format) == noErr else { exit(2) }
        let sink = SampleBufferWavSink(url: directory.appendingPathComponent("mic.wav"), sourceName: "mic")
        sink.onFailure = { JSONEmitter.shared.emitAndExit(["type": "probe_failure"], exitCode: 3) }
        JSONEmitter.shared.emit(["type": "probe_started", "uptime": ProcessInfo.processInfo.systemUptime])
        for index in 0..<40 {
            let bytes: Data
            if floatInput {
                let samples: [Float32] = (0..<count).map { offset in
                    Float32(0.03 * sin(2 * Double.pi * 440 * Double(index * count + offset) / Double(rate)))
                }
                bytes = samples.withUnsafeBytes { Data($0) }
            } else {
                let samples: [Int16] = (0..<count).map { offset in Int16((index * count + offset) % 2001 - 1000) }
                bytes = samples.withUnsafeBytes { Data($0) }
            }
            var block: CMBlockBuffer?
            guard CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault,
                memoryBlock: nil, blockLength: bytes.count, blockAllocator: kCFAllocatorDefault,
                customBlockSource: nil, offsetToData: 0, dataLength: bytes.count,
                flags: 0, blockBufferOut: &block) == kCMBlockBufferNoErr else { exit(4) }
            guard bytes.withUnsafeBytes({ CMBlockBufferReplaceDataBytes(with: $0.baseAddress!,
                blockBuffer: block!, offsetIntoDestination: 0, dataLength: bytes.count) }) == noErr else { exit(5) }
            var sample: CMSampleBuffer?
            guard CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: kCFAllocatorDefault,
                dataBuffer: block!, formatDescription: format!, sampleCount: count,
                presentationTimeStamp: CMTime(value: Int64(index * count), timescale: Int32(rate)),
                packetDescriptions: nil, sampleBufferOut: &sample) == noErr else { exit(6) }
            sink.append(sample!)
            usleep(100000)
        }
        if CommandLine.arguments[1].hasPrefix("finish") {
            sink.finish { ok in JSONEmitter.shared.emitAndExit(["type": "probe_finished", "ok": ok], exitCode: ok ? 0 : 7) }
        }
        dispatchMain()
    }
}
