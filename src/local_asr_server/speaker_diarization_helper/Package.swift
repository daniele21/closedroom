// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "ClosedRoomSpeakerDiarizer",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.17.7")
    ],
    targets: [
        .executableTarget(
            name: "closedroom-speaker-diarizer",
            dependencies: [.product(name: "FluidAudio", package: "FluidAudio")],
            path: "Sources"
        )
    ]
)
