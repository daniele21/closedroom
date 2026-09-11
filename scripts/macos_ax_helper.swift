import AppKit
import ApplicationServices
import Foundation

private let permissionExit: Int32 = 77
private let unavailableExit: Int32 = 69

private func fail(_ message: String, code: Int32 = 1) -> Never {
    if let data = (message + "\n").data(using: .utf8) {
        FileHandle.standardError.write(data)
    }
    exit(code)
}

private func copyAttributeResult(
    _ element: AXUIElement,
    _ name: CFString
) -> (AXError, CFTypeRef?) {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, name, &value)
    return (result, value)
}

private func attribute(_ element: AXUIElement, _ name: CFString) -> CFTypeRef? {
    let (result, value) = copyAttributeResult(element, name)
    return result == .success ? value : nil
}

private func elementArray(_ element: AXUIElement, _ name: CFString) -> [AXUIElement] {
    guard let value = attribute(element, name) else { return [] }
    return value as? [AXUIElement] ?? []
}

private func stringValue(_ element: AXUIElement, _ name: CFString) -> String? {
    guard let value = attribute(element, name) else { return nil }
    if let text = value as? String { return text }
    if let number = value as? NSNumber { return number.stringValue }
    return nil
}

private func boolValue(_ element: AXUIElement, _ name: CFString) -> Bool? {
    guard let value = attribute(element, name) else { return nil }
    if let number = value as? NSNumber { return number.boolValue }
    return nil
}

private func windowBounds(_ window: AXUIElement) -> (position: CGPoint, size: CGSize)? {
    guard let positionValue = attribute(window, kAXPositionAttribute as CFString),
          let sizeValue = attribute(window, kAXSizeAttribute as CFString),
          CFGetTypeID(positionValue) == AXValueGetTypeID(),
          CFGetTypeID(sizeValue) == AXValueGetTypeID() else {
        return nil
    }

    var position = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetValue(positionValue as! AXValue, .cgPoint, &position),
          AXValueGetValue(sizeValue as! AXValue, .cgSize, &size),
          size.width > 0,
          size.height > 0 else {
        return nil
    }
    return (position, size)
}

private func windowArea(_ window: AXUIElement) -> CGFloat {
    guard let bounds = windowBounds(window) else { return 0 }
    return bounds.size.width * bounds.size.height
}

private func orderedWindows(_ app: AXUIElement) -> [AXUIElement] {
    let windows = elementArray(app, kAXWindowsAttribute as CFString)
    guard !windows.isEmpty else {
        fail("closedroom_window_missing", code: unavailableExit)
    }
    // ClosedRoom owns a large WKWebView application window and may also show a
    // small native recording NSPanel. AX does not guarantee stable window order,
    // so prefer the largest window while still retaining every window for search.
    return windows.enumerated().sorted { left, right in
        let leftArea = windowArea(left.element)
        let rightArea = windowArea(right.element)
        if leftArea == rightArea { return left.offset < right.offset }
        return leftArea > rightArea
    }.map { $0.element }
}

private func mainWindow(_ app: AXUIElement) -> AXUIElement {
    return orderedWindows(app)[0]
}

private func labelsFor(_ element: AXUIElement) -> [String] {
    let attributes: [CFString] = [
        kAXTitleAttribute as CFString,
        kAXDescriptionAttribute as CFString,
        kAXValueAttribute as CFString,
        kAXHelpAttribute as CFString,
        kAXRoleDescriptionAttribute as CFString,
    ]
    return attributes.compactMap { stringValue(element, $0) }
}

private func findElementInWindow(_ window: AXUIElement, wanted: Set<String>) -> AXUIElement? {
    var queue: [(AXUIElement, Int)] = [(window, 0)]
    var cursor = 0
    var visited = 0
    let maxDepth = 32
    let maxElements = 2500

    while cursor < queue.count && visited < maxElements {
        let (element, depth) = queue[cursor]
        cursor += 1
        visited += 1

        if labelsFor(element).contains(where: wanted.contains) {
            return element
        }

        if depth < maxDepth {
            for child in elementArray(element, kAXChildrenAttribute as CFString) {
                queue.append((child, depth + 1))
            }
        }
    }
    return nil
}

private func findElementInApp(_ app: AXUIElement, wanted: Set<String>) -> AXUIElement? {
    for window in orderedWindows(app) {
        if let element = findElementInWindow(window, wanted: wanted) {
            return element
        }
    }
    return nil
}

private func windowRect(_ window: AXUIElement) -> String {
    guard let bounds = windowBounds(window) else {
        fail("closedroom_window_bounds_missing", code: unavailableExit)
    }
    return "\(Int(bounds.position.x)),\(Int(bounds.position.y)),\(Int(bounds.size.width)),\(Int(bounds.size.height))"
}

private func focusedDescription(_ app: AXUIElement) -> String {
    guard let value = attribute(app, kAXFocusedUIElementAttribute as CFString),
          CFGetTypeID(value) == AXUIElementGetTypeID() else {
        return "unknown"
    }
    let element = value as! AXUIElement
    let role = stringValue(element, kAXRoleAttribute as CFString) ?? "unknown"
    let detail = stringValue(element, kAXDescriptionAttribute as CFString)
        ?? stringValue(element, kAXTitleAttribute as CFString)
        ?? stringValue(element, kAXValueAttribute as CFString)
        ?? ""
    return "\(role) | \(detail)"
}

private func windowServerCounts(pid: pid_t) -> [String: Int] {
    guard let windowInfo = CGWindowListCopyWindowInfo(
        [.optionAll, .excludeDesktopElements],
        kCGNullWindowID
    ) as? [[String: Any]] else {
        return [
            "cg_window_count": -1,
            "cg_onscreen_window_count": -1,
            "cg_normal_window_count": -1,
            "cg_onscreen_normal_window_count": -1,
        ]
    }

    var total = 0
    var onscreen = 0
    var normal = 0
    var onscreenNormal = 0
    for item in windowInfo {
        guard let owner = item[kCGWindowOwnerPID as String] as? NSNumber,
              owner.int32Value == pid else {
            continue
        }
        total += 1
        let isOnscreen = (item[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue == true
        let isNormal = (item[kCGWindowLayer as String] as? NSNumber)?.intValue == 0
        if isOnscreen { onscreen += 1 }
        if isNormal { normal += 1 }
        if isOnscreen && isNormal { onscreenNormal += 1 }
    }
    return [
        "cg_window_count": total,
        "cg_onscreen_window_count": onscreen,
        "cg_normal_window_count": normal,
        "cg_onscreen_normal_window_count": onscreenNormal,
    ]
}

private func diagnosticSnapshot(_ app: AXUIElement, pid: pid_t) -> String {
    let (windowsResult, windowsValue) = copyAttributeResult(
        app,
        kAXWindowsAttribute as CFString
    )
    let windows = windowsValue as? [AXUIElement] ?? []
    let (mainResult, mainValue) = copyAttributeResult(
        app,
        kAXMainWindowAttribute as CFString
    )
    let (focusedResult, focusedValue) = copyAttributeResult(
        app,
        kAXFocusedWindowAttribute as CFString
    )
    let running = NSRunningApplication(processIdentifier: pid)
    let positiveBounds = windows.filter { windowBounds($0) != nil }.count
    let minimized = windows.filter {
        boolValue($0, kAXMinimizedAttribute as CFString) == true
    }.count

    var payload: [String: Any] = [
        "schema_version": 1,
        "pid": Int(pid),
        "running_application_present": running != nil,
        "running_application_terminated": running?.isTerminated ?? true,
        "running_application_active": running?.isActive ?? false,
        "running_application_hidden": running?.isHidden ?? false,
        "activation_policy": running.map { Int($0.activationPolicy.rawValue) } ?? -1,
        "ax_windows_result": Int(windowsResult.rawValue),
        "ax_windows_count": windows.count,
        "ax_windows_positive_bounds_count": positiveBounds,
        "ax_windows_minimized_count": minimized,
        "ax_main_window_result": Int(mainResult.rawValue),
        "ax_main_window_present": mainValue != nil,
        "ax_focused_window_result": Int(focusedResult.rawValue),
        "ax_focused_window_present": focusedValue != nil,
    ]
    for (key, value) in windowServerCounts(pid: pid) {
        payload[key] = value
    }

    guard JSONSerialization.isValidJSONObject(payload),
          let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
          let json = String(data: data, encoding: .utf8) else {
        fail("window_diagnostic_serialization_failed", code: unavailableExit)
    }
    return json
}

private func postKey(pid: pid_t, code: CGKeyCode, command: Bool = false) {
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) else {
        fail("keyboard_event_creation_failed")
    }
    if command {
        down.flags = .maskCommand
        up.flags = .maskCommand
    }
    down.postToPid(pid)
    up.postToPid(pid)
}

guard CommandLine.arguments.count >= 3,
      let rawPID = Int32(CommandLine.arguments[1]) else {
    fail("usage: macos_ax_helper <pid> <action> [labels...]", code: 64)
}

let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
let trustOptions = [promptKey: true] as CFDictionary
if !AXIsProcessTrustedWithOptions(trustOptions) {
    fail("accessibility_permission_required", code: permissionExit)
}

let pid = pid_t(rawPID)
let action = CommandLine.arguments[2]
let wanted = Set(CommandLine.arguments.dropFirst(3))
let app = AXUIElementCreateApplication(pid)
if let running = NSRunningApplication(processIdentifier: pid) {
    _ = running.activate(options: [.activateAllWindows])
}

switch action {
case "window":
    _ = mainWindow(app)
    print("true")
case "rect":
    print(windowRect(mainWindow(app)))
case "focused":
    print(focusedDescription(app))
case "diagnose":
    print(diagnosticSnapshot(app, pid: pid))
case "exists", "press":
    if wanted.isEmpty {
        fail("labels_required", code: 64)
    }
    guard let element = findElementInApp(app, wanted: wanted) else {
        if action == "exists" {
            print("false")
            exit(0)
        }
        fail("ui_element_not_found", code: unavailableExit)
    }
    if action == "exists" {
        print("true")
    } else {
        let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
        guard result == .success else {
            fail("ax_press_failed:\(result.rawValue)", code: unavailableExit)
        }
        print("pressed")
    }
case "cmd-k":
    _ = mainWindow(app)
    postKey(pid: pid, code: 40, command: true)
    print("sent")
case "escape":
    _ = mainWindow(app)
    postKey(pid: pid, code: 53)
    print("sent")
case "cmd-q":
    _ = mainWindow(app)
    postKey(pid: pid, code: 12, command: true)
    print("sent")
default:
    fail("unsupported_action:\(action)", code: 64)
}
