#!/usr/bin/env python3
"""Discriminate PID-targeted key delivery across AppKit and WKWebView on a real Mac.

This is a diagnostic-only probe. It does not launch ClosedRoom or read meeting data.
It creates a minimal NSWindow + WKWebView, installs the same app-local NSEvent
monitor shape used by ClosedRoom, sends Cmd-K and Escape through the repository's
stable PID-targeted Accessibility helper, and records only bounded technical state.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import AppHelper

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from macos_ui_driver import (  # noqa: E402
    AccessibilityPermissionRequired,
    UIAutomationError,
    default_driver,
)

try:
    objc.loadBundle(
        "WebKit",
        globals(),
        bundle_path="/System/Library/Frameworks/WebKit.framework",
    )
    WKWebView = objc.lookUpClass("WKWebView")
except Exception as exc:  # pragma: no cover - target-Mac only
    raise SystemExit(f"webkit_unavailable:{type(exc).__name__}") from exc

DRIVER = default_driver()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe PID-targeted CGEvent -> NSEvent monitor -> WKWebView DOM delivery"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    return parser.parse_args()


def git_revision(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return completed.stdout.strip()


def bounded_completion_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"default_prevented": None}
    return {"default_prevented": bool(result.get("defaultPrevented"))}


def classify(trace: list[dict[str, Any]], dom: dict[str, Any]) -> str:
    cmd_monitor = any(
        item.get("event") == "monitor_received" and item.get("key_code") == 40
        for item in trace
    )
    cmd_match = any(item.get("event") == "cmd_k_matched" for item in trace)
    cmd_bridge = any(
        item.get("event") == "bridge_completion"
        and item.get("key") == "KeyK"
        and item.get("success") is True
        for item in trace
    )
    cmd_dom = int(dom.get("cmd_k_count") or 0) > 0

    if not cmd_monitor:
        return "pid_targeted_cmd_k_did_not_reach_local_monitor"
    if not cmd_match:
        return "cmd_k_reached_monitor_but_did_not_match"
    if not cmd_bridge:
        return "cmd_k_matched_but_webview_bridge_did_not_complete"
    if not cmd_dom:
        return "cmd_k_bridge_completed_but_dom_listener_not_reached"
    return "minimal_keyboard_path_succeeded"


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    revision = git_revision(root)
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else root
        / "dist"
        / "evidence"
        / "local-real-environment"
        / revision[:12]
        / "macos-keyboard-event-path.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    trace: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic": "macos_keyboard_event_path",
        "status": "error",
        "classification": None,
        "execution_environment": "target-macos-real",
        "qualification_scope": "diagnostic_only",
        "source_revision": revision,
        "pid": os.getpid(),
        "privacy_boundary": (
            "Probe contains only key codes, modifier booleans, bounded bridge completion state, "
            "window-key state and synthetic DOM counters. It does not launch ClosedRoom, inspect "
            "meeting data, persist labels/titles/input values, or establish release qualification."
        ),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "trace": trace,
        "dom": {},
        "errors": [],
    }

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((160, 160), (720, 480)), style, NSBackingStoreBuffered, False
    )
    window.setTitle_("ClosedRoom Keyboard Path Diagnostic")

    webview = WKWebView.alloc().initWithFrame_(window.contentView().frame())
    webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
    window.setContentView_(webview)

    html = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Keyboard Path Diagnostic</title></head>
<body tabindex="0">
<script>
window.__closedroomProbe = {cmdKCount: 0, escapeCount: 0};
window.addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    window.__closedroomProbe.cmdKCount += 1;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    window.__closedroomProbe.escapeCount += 1;
  }
});
document.body.focus();
</script>
</body>
</html>
"""
    webview.loadHTMLString_baseURL_(html, None)

    def bridge(*, key: str, code: str, meta_key: bool) -> None:
        trace.append({"event": "bridge_requested", "key": code})
        meta_value = "true" if meta_key else "false"
        js = (
            "(() => {"
            "const target = document.activeElement || document.body || document;"
            "const event = new KeyboardEvent('keydown', {"
            f"key: {key!r}, code: {code!r}, metaKey: {meta_value}, "
            "bubbles: true, cancelable: true"
            "});"
            "target.dispatchEvent(event);"
            "return {defaultPrevented: event.defaultPrevented};"
            "})();"
        )

        def completed(result: Any, error: Any) -> None:
            item: dict[str, Any] = {
                "event": "bridge_completion",
                "key": code,
                "success": error is None,
            }
            item.update(bounded_completion_result(result))
            if error is not None:
                item["error_type"] = type(error).__name__
            trace.append(item)

        webview.evaluateJavaScript_completionHandler_(js, completed)

    def local_key_monitor(event: Any) -> Any:
        key_code = int(event.keyCode())
        modifiers = int(event.modifierFlags())
        command_pressed = bool(modifiers & NSEventModifierFlagCommand)
        semantic_k = str(event.charactersIgnoringModifiers() or "").lower() == "k"
        trace.append(
            {
                "event": "monitor_received",
                "key_code": key_code,
                "command_pressed": command_pressed,
                "semantic_k": semantic_k,
                "window_is_key": bool(window.isKeyWindow()),
            }
        )
        if command_pressed and (key_code == 40 or semantic_k):
            trace.append({"event": "cmd_k_matched"})
            bridge(key="k", code="KeyK", meta_key=True)
        elif key_code == 53:
            trace.append({"event": "escape_matched"})
            bridge(key="Escape", code="Escape", meta_key=False)
        return event

    monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        NSEventMaskKeyDown,
        local_key_monitor,
    )

    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    def finalize_on_main() -> None:
        js = (
            "JSON.stringify({"
            "cmd_k_count: window.__closedroomProbe ? window.__closedroomProbe.cmdKCount : 0,"
            "escape_count: window.__closedroomProbe ? window.__closedroomProbe.escapeCount : 0"
            "})"
        )

        def completed(result: Any, error: Any) -> None:
            if error is not None:
                report["errors"].append(f"dom_snapshot:{type(error).__name__}")
            else:
                try:
                    payload = json.loads(str(result or "{}"))
                except json.JSONDecodeError:
                    payload = {}
                report["dom"] = {
                    "cmd_k_count": int(payload.get("cmd_k_count") or 0),
                    "escape_count": int(payload.get("escape_count") or 0),
                }
            report["classification"] = classify(trace, report["dom"])
            report["status"] = "complete" if not report["errors"] else "error"
            AppHelper.stopEventLoop()

        webview.evaluateJavaScript_completionHandler_(js, completed)

    def drive() -> None:
        try:
            time.sleep(max(args.settle_seconds, 0.25))
            DRIVER.key(os.getpid(), "cmd-k")
            time.sleep(0.75)
            DRIVER.key(os.getpid(), "escape")
            time.sleep(0.75)
        except AccessibilityPermissionRequired as exc:
            report["status"] = "blocked_permission"
            report["errors"].append(type(exc).__name__)
        except UIAutomationError as exc:
            report["errors"].append(f"ui_automation:{type(exc).__name__}")
        except Exception as exc:  # pragma: no cover - target-Mac only
            report["errors"].append(f"{type(exc).__name__}:{exc}")
        finally:
            AppHelper.callAfter(finalize_on_main)

    threading.Thread(target=drive, daemon=True).start()

    try:
        AppHelper.runEventLoop()
    finally:
        NSEvent.removeMonitor_(monitor)
        window.orderOut_(None)
        DRIVER.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Evidence: {output}")

    if report["status"] == "blocked_permission":
        return 2
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
