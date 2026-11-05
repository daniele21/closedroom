import Foundation
import FluidAudio

struct TrackInput {
    let id: String
    let path: String
}

struct OutputSegment: Codable {
    let speaker: String
    let start: Double
    let end: Double
}

struct TrackOutput: Codable {
    let segments: [OutputSegment]
}

struct HelperOutput: Codable {
    let engine: String
    let preset: String?
    let tracks: [String: TrackOutput]
}

func makeAccurateOfflineConfig() -> OfflineDiarizerConfig {
    var config = OfflineDiarizerConfig(
        segmentationStepRatio: 0.1,
        minSegmentDuration: 0.0
    )
    config.zeroVoteReembed = OfflineDiarizerConfig.ZeroVoteReembed(
        enabled: true,
        minDurationSeconds: 0.4
    )
    return config
}

enum ArgumentError: Error, CustomStringConvertible {
    case invalid(String)

    var description: String {
        switch self {
        case .invalid(let message): return message
        }
    }
}

func parseArguments(_ arguments: [String]) throws -> ([TrackInput], URL?, String, String) {
    guard arguments.first == "process" else {
        throw ArgumentError.invalid("usage: closedroom-speaker-diarizer process --input TRACK_ID=PATH [--input ...]")
    }
    var inputs: [TrackInput] = []
    var modelsDirectory: URL?
    var engine = "fluidaudio-community-1"
    var preset = "fast128"
    var index = 1
    while index < arguments.count {
        guard index + 1 < arguments.count else {
            throw ArgumentError.invalid("unsupported argument: \(arguments[index])")
        }
        if arguments[index] == "--engine" {
            engine = arguments[index + 1]
            index += 2
            continue
        }
        if arguments[index] == "--preset" {
            preset = arguments[index + 1]
            index += 2
            continue
        }
        if arguments[index] == "--models-dir" {
            modelsDirectory = URL(fileURLWithPath: arguments[index + 1], isDirectory: true)
            index += 2
            continue
        }
        guard arguments[index] == "--input" else {
            throw ArgumentError.invalid("unsupported argument: \(arguments[index])")
        }
        let value = arguments[index + 1]
        guard let separator = value.firstIndex(of: "=") else {
            throw ArgumentError.invalid("input must use TRACK_ID=PATH")
        }
        let trackId = String(value[..<separator])
        let path = String(value[value.index(after: separator)...])
        guard !trackId.isEmpty, !path.isEmpty else {
            throw ArgumentError.invalid("track id and path are required")
        }
        inputs.append(TrackInput(id: trackId, path: path))
        index += 2
    }
    guard !inputs.isEmpty else {
        throw ArgumentError.invalid("at least one --input is required")
    }
    guard ["fluidaudio-community-1", "nemotron3-coreml"].contains(engine) else {
        throw ArgumentError.invalid("unsupported diarization engine: \(engine)")
    }
    guard ["fast128", "c128-split-w8a8"].contains(preset) else {
        throw ArgumentError.invalid("unsupported Nemotron 3 preset: \(preset)")
    }
    return (inputs, modelsDirectory, engine, preset)
}

@main
struct ClosedRoomSpeakerDiarizer {
    static func main() async {
        do {
            let (inputs, modelsDirectory, engine, preset) = try parseArguments(Array(CommandLine.arguments.dropFirst()))
            var tracks: [String: TrackOutput] = [:]
            if engine == "fluidaudio-community-1" {
                // Existing Community-1 quality profile remains unchanged.
                let manager = OfflineDiarizerManager(config: makeAccurateOfflineConfig())
                try await manager.prepareModels(directory: modelsDirectory)
                for input in inputs {
                    let result = try await manager.process(URL(fileURLWithPath: input.path))
                    tracks[input.id] = TrackOutput(segments: result.segments.map {
                        OutputSegment(
                            speaker: String(describing: $0.speakerId),
                            start: Double($0.startTimeSeconds),
                            end: Double($0.endTimeSeconds)
                        )
                    })
                }
            } else {
                guard let modelsDirectory else {
                    throw ArgumentError.invalid("Nemotron 3 requires a model cache directory")
                }
                guard let config = Nemotron3Config.preset(named: preset) else {
                    throw ArgumentError.invalid("unsupported Nemotron 3 preset")
                }
                // Download only the requested model weights to ClosedRoom's local cache.
                // The audio itself stays on device; no cloud diarization fallback.
                let models = try await Nemotron3Models.loadFromHuggingFace(
                    config: config, cacheDirectory: modelsDirectory
                )
                let diarizer = Nemotron3Diarizer(config: config, models: models)
                for input in inputs {
                    let audio = try AudioConverter().resampleAudioFile(
                        URL(fileURLWithPath: input.path)
                    )
                    let (probabilities, frameCount) = try diarizer.processComplete(audio)
                    // Preserve simultaneous speakers as overlapping intervals.
                    tracks[input.id] = TrackOutput(segments:
                        Nemotron3Diarizer.segments(
                            probabilities: probabilities, frameCount: frameCount
                        ).map {
                            OutputSegment(
                                speaker: String($0.speakerIndex),
                                start: Double($0.startSeconds),
                                end: Double($0.endSeconds)
                            )
                        }
                    )
                }
            }
            let payload = HelperOutput(
                engine: engine,
                preset: engine == "nemotron3-coreml" ? preset : nil,
                tracks: tracks
            )
            let data = try JSONEncoder().encode(payload)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("\(error)\n".utf8))
            Foundation.exit(1)
        }
    }
}
