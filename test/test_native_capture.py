from __future__ import annotations

import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from local_asr_server.native_capture import NativeCaptureManager


class NativeCaptureManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.helper = self.root / "helper.py"
        self.helper.write_text(
            """#!/usr/bin/env python3
import json, sys, time
from pathlib import Path

cmd = sys.argv[1]

def arg(name):
    idx = sys.argv.index(name)
    return sys.argv[idx + 1]
if cmd == 'capabilities':
    print(json.dumps({'available': True, 'backend': 'native', 'modes': ['both']}))
elif cmd == 'permissions':
    print(json.dumps({'ok': True, 'microphone': 'authorized', 'screen_capture': 'granted', 'modes': {'mic_only': {'ok': True}, 'pc_only': {'ok': True}, 'both': {'ok': True}}}))
elif cmd == 'request-permissions':
    print(json.dumps({'ok': True, 'requested': True}))
elif cmd == 'diagnostics':
    print(json.dumps({'bundle_identifier': 'com.closedroom.nativecapture', 'code_signature': 'signed', 'screen_capture': 'granted'}))
elif cmd == 'windows':
    print(json.dumps({'windows': [
        {'id': -7, 'display_id': 7, 'kind': 'display', 'title': 'Screen 1', 'application_name': 'Full Screen', 'bundle_identifier': 'com.apple.displays', 'width': 1920, 'height': 1080},
        {'id': 42, 'kind': 'window', 'title': 'Meet', 'application_name': 'Chrome', 'bundle_identifier': 'com.google.Chrome'}
    ]}))
elif cmd == 'screenshot':
    Path(arg('--original-file')).write_bytes(b'\\xff\\xd8\\xfforiginal')
    Path(arg('--thumbnail-file')).write_bytes(b'\\xff\\xd8\\xffthumb')
    print(json.dumps({
        'type': 'screenshot', 'display_id': int(arg('--display-id')),
        'captured_uptime': 12.5, 'captured_wall_time': 1000.0,
        'width': 1920, 'height': 1080, 'thumbnail_width': 640, 'thumbnail_height': 360,
        'format': 'image/jpeg', 'overlay_exclusion': 'closedroom_windows'
    }))
elif cmd == 'start':
    print(json.dumps({'type': 'ready', 'recording_ready_uptime': 10.0}), flush=True)
    time.sleep(0.2)
    print(json.dumps({'type': 'stopped'}), flush=True)
else:
    print(json.dumps({'type': 'stopped'}))
""",
            encoding="utf-8",
        )
        self.helper.chmod(self.helper.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_capabilities_and_event_drain(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)

        self.assertTrue(manager.capabilities()["available"])
        started = manager.start("rec-1", self.root, "both")

        events = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            events.extend(manager.drain_events("rec-1"))
            if any(event.get("type") in {"stopped", "error"} for event in events):
                break
            time.sleep(0.01)

        self.assertEqual(started["backend"], "native")
        self.assertEqual([event["type"] for event in events], ["ready", "stopped"])

    def test_lists_windows_and_starts_visual_capture(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        windows = manager.windows()["windows"]
        self.assertEqual(next(item for item in windows if item.get("kind") == "window")["id"], 42)
        self.assertEqual(manager.displays()["displays"][0]["display_id"], 7)
        started = manager.start("rec-visual", self.root, "both", visual_window_id=42, visual_fps=1.0)
        self.assertEqual(started["status"], "starting")


    def test_manual_screenshot_uses_ready_uptime_and_persists_display_selection(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        manager.start("rec-shot", self.root, "both")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            session = manager.get_session("rec-shot")
            if session and session.ready_event:
                break
            time.sleep(0.01)

        captured = manager.capture_screenshot(
            "rec-shot", request_id="request-1", display_id=7,
        )

        self.assertEqual(captured["display_id"], 7)
        self.assertEqual(captured["timestamp"], 2.5)
        self.assertEqual(captured["original_bytes"], b"\xff\xd8\xfforiginal")
        self.assertEqual(captured["thumbnail_bytes"], b"\xff\xd8\xffthumb")
        self.assertEqual(manager.get_session("rec-shot").screenshot_display_id, 7)


    def test_stop_waits_until_admitted_screenshot_persistence_finishes(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        manager.start("rec-drain", self.root, "both")
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            session = manager.get_session("rec-drain")
            if session and session.ready_event:
                break
            time.sleep(0.005)

        manager.begin_screenshot("rec-drain")
        result = {}

        def stop_capture():
            result.update(manager.stop("rec-drain"))

        thread = threading.Thread(target=stop_capture)
        thread.start()
        time.sleep(0.03)
        self.assertTrue(thread.is_alive())

        manager.finish_screenshot("rec-drain")
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result["status"], "stopped")

    def test_validate_audio_file_behavior(self) -> None:
        from local_asr_server.native_capture import validate_audio_file
        
        # Test file not found
        res = validate_audio_file(self.root / "nonexistent.wav")
        self.assertFalse(res["valid"])
        self.assertEqual(res["error"], "file_not_found")
        
        # Test empty file
        empty_file = self.root / "empty.wav"
        empty_file.touch()
        res = validate_audio_file(empty_file)
        self.assertFalse(res["valid"])
        self.assertEqual(res["error"], "file_empty")

    def test_stop_session_processes_events(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        started = manager.start("rec-2", self.root, "both")
        self.assertEqual(started["status"], "starting")
        
        # Let the process finish
        time.sleep(0.5)
        
        # Stop session
        result = manager.stop("rec-2")
        self.assertEqual(result["status"], "stopped")
        
        # Check that events are returned
        event_types = [evt["type"] for evt in result["events"]]
        self.assertIn("ready", event_types)
        self.assertIn("stopped", event_types)

    def test_ensure_permissions_returns_ready_state_without_prompt(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        result = manager.ensure_permissions("both")

        self.assertTrue(result["ok"])
        self.assertFalse(result["requested"])
        self.assertEqual(result["permissions"]["microphone"], "authorized")
        self.assertEqual(result["diagnostics"]["bundle_identifier"], "com.closedroom.nativecapture")

    def test_ensure_permissions_rejects_invalid_mode(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)

        with self.assertRaises(ValueError):
            manager.ensure_permissions("browser")

    def test_default_manager_refreshes_compiled_helper_on_macos(self) -> None:
        manager = NativeCaptureManager()
        with (
            patch("local_asr_server.native_capture.sys.platform", "darwin"),
            patch(
                "local_asr_server.native_capture_helper.get_helper_binary",
                return_value=str(self.helper),
            ) as get_helper_binary,
        ):
            result = manager.capabilities()

        self.assertTrue(result["available"])
        self.assertEqual(manager.helper_path, self.helper)
        self.assertGreaterEqual(get_helper_binary.call_count, 1)

    def test_native_helper_uses_screenshot_manager_for_macos_14_one_shot_capture(self) -> None:
        helper_source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "local_asr_server"
            / "native_capture_helper"
            / "native_capture_helper.swift"
        ).read_text(encoding="utf-8")

        self.assertIn("@available(macOS 14.0, *)", helper_source)
        self.assertIn("SCScreenshotManager.captureImage(", helper_source)
        self.assertIn('"capture_backend": "screenshot_manager"', helper_source)
        self.assertIn("let capture = OneShotDisplayCapture(", helper_source)

    def test_screenshot_cli_initializes_appkit_windowserver_context(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_source = (
            root
            / "src"
            / "local_asr_server"
            / "native_capture_helper"
            / "native_capture_helper.swift"
        ).read_text(encoding="utf-8")
        compile_source = (
            root
            / "src"
            / "local_asr_server"
            / "native_capture_helper"
            / "compile.py"
        ).read_text(encoding="utf-8")

        self.assertIn("import AppKit", helper_source)
        self.assertIn("let app = NSApplication.shared", helper_source)
        self.assertIn("app.setActivationPolicy(.prohibited)", helper_source)
        self.assertIn("Task { @MainActor in", helper_source)
        self.assertIn("dispatchMain()", helper_source)
        self.assertIn('"AppKit"', compile_source)

    def test_manual_screenshot_timeout_is_reported_without_leaking_timeout_expired(self) -> None:
        manager = NativeCaptureManager(helper_path=self.helper)
        manager.start("rec-timeout", self.root, "both")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            session = manager.get_session("rec-timeout")
            if session and session.ready_event:
                break
            time.sleep(0.01)

        with (
            patch.object(
                manager,
                "displays",
                return_value={
                    "displays": [{
                        "display_id": 7,
                        "source_id": -7,
                        "title": "Screen 1",
                        "width": 1920,
                        "height": 1080,
                    }]
                },
            ),
            patch(
                "local_asr_server.native_capture.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["helper", "screenshot"], timeout=15),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "screenshot_capture_timeout"):
                manager.capture_screenshot(
                    "rec-timeout",
                    request_id="request-timeout",
                    display_id=7,
                )


if __name__ == "__main__":
    unittest.main()