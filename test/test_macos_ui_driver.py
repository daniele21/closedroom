from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "macos_ui_driver.py"
SWIFT_HELPER = Path(__file__).resolve().parents[1] / "scripts" / "macos_ax_helper.swift"


def load_module():
    spec = importlib.util.spec_from_file_location("macos_ui_driver_test_module", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load macos_ui_driver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MacOSUIDriverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver_module = load_module()

    def test_action_timeout_is_explicit_and_bounded(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER, action_timeout=2.5)
        driver._ensure_binary = lambda: Path("/tmp/closedroom-ax-helper")
        with mock.patch.object(
            self.driver_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["helper"], timeout=2.5),
        ):
            with self.assertRaises(self.driver_module.UIAutomationTimeout) as caught:
                driver._invoke(123, "window")
        self.assertIn("ui_automation_timeout:window:2.5s", str(caught.exception))

    def test_accessibility_denial_is_not_a_product_failure(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER)
        driver._ensure_binary = lambda: Path("/tmp/closedroom-ax-helper")
        completed = subprocess.CompletedProcess(
            args=["helper"],
            returncode=77,
            stdout="",
            stderr="accessibility_permission_required\n",
        )
        with mock.patch.object(self.driver_module.subprocess, "run", return_value=completed):
            with self.assertRaises(self.driver_module.AccessibilityPermissionRequired):
                driver._invoke(123, "window")

    def test_transient_window_gap_is_retried_before_success(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER, action_timeout=1.0)
        driver._ensure_binary = lambda: Path("/tmp/closedroom-ax-helper")
        missing = subprocess.CompletedProcess(
            args=["helper"],
            returncode=69,
            stdout="",
            stderr="closedroom_window_missing\n",
        )
        ready = subprocess.CompletedProcess(
            args=["helper"],
            returncode=0,
            stdout="true\n",
            stderr="",
        )
        with (
            mock.patch.object(
                self.driver_module.subprocess,
                "run",
                side_effect=[missing, missing, ready],
            ) as run,
            mock.patch.object(self.driver_module.time, "sleep"),
        ):
            self.assertTrue(driver.window_accessible(123))
        self.assertEqual(run.call_count, 3)

    def test_non_transient_ui_failure_is_not_retried(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER)
        driver._ensure_binary = lambda: Path("/tmp/closedroom-ax-helper")
        failed = subprocess.CompletedProcess(
            args=["helper"],
            returncode=69,
            stdout="",
            stderr="ax_press_failed\n",
        )
        with mock.patch.object(
            self.driver_module.subprocess,
            "run",
            return_value=failed,
        ) as run:
            with self.assertRaises(self.driver_module.UIAutomationError) as caught:
                driver._invoke(123, "press", ("Start Recording",))
        self.assertEqual(str(caught.exception), "ax_press_failed")
        self.assertEqual(run.call_count, 1)

    def test_window_rect_rejects_invalid_bounds(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER)
        driver._invoke = lambda *_args, **_kwargs: "10,20,0,500"
        with self.assertRaises(self.driver_module.UIAutomationError):
            driver.window_rect(123)

    def test_swift_helper_handles_main_window_and_recording_overlay(self) -> None:
        source = SWIFT_HELPER.read_text(encoding="utf-8")
        self.assertIn("private func orderedWindows", source)
        self.assertIn("private func windowArea", source)
        self.assertIn("print(windowRect(mainWindow(app)))", source)
        self.assertIn("for window in orderedWindows(app)", source)
        self.assertIn("findElementInWindow(window, wanted: wanted)", source)
        self.assertIn("findElementInApp(app, wanted: wanted)", source)
        self.assertNotIn("firstWindow", source)

    @unittest.skipUnless(platform.system() == "Darwin" and shutil.which("xcrun"), "requires macOS Swift toolchain")
    def test_swift_ax_helper_compiles_on_macos(self) -> None:
        driver = self.driver_module.MacOSUIDriver(source=SWIFT_HELPER)
        try:
            binary = driver._ensure_binary()
            self.assertTrue(binary.is_file())
        finally:
            driver.close()


if __name__ == "__main__":
    unittest.main()
