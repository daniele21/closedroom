import AVFoundation
import CoreGraphics
import Foundation
import ScreenCaptureKit
import Security

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
