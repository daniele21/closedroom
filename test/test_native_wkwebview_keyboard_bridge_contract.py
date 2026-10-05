from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "src" / "local_asr_server" / "window.py"
SMOKE = ROOT / "scripts" / "real_environment_smoke.py"
DASHBOARD = ROOT / "frontend" / "src" / "pages" / "DashboardPage.tsx"


class NativeWKWebViewKeyboardBridgeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.window = WINDOW.read_text(encoding="utf-8")
        cls.smoke = SMOKE.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD.read_text(encoding="utf-8")

    def test_main_window_installs_and_cleans_up_local_key_monitor(self) -> None:
        self.assertIn("NSEventMaskKeyDown", self.window)
        self.assertIn("NSEventModifierFlagCommand", self.window)
        self.assertIn(
            "NSEvent.addLocalMonitorForEventsMatchingMask_handler_",
            self.window,
        )
        self.assertIn("self._install_local_key_monitor()", self.window)
        self.assertIn("NSEvent.removeMonitor_(self._key_event_monitor)", self.window)

    def test_cmd_k_and_escape_bridge_to_focused_dom_keyboard_path(self) -> None:
        self.assertNotIn("self.window.isKeyWindow()", self.window)
        self.assertIn("command_pressed = bool(modifiers & NSEventModifierFlagCommand)", self.window)
        self.assertIn('key_code == 40 or characters == "k"', self.window)
        self.assertIn("key_code == 53", self.window)
        self.assertIn("document.activeElement || document.body || document", self.window)
        self.assertIn("new KeyboardEvent('keydown'", self.window)
        self.assertIn('key="k", code="KeyK", meta_key=True', self.window)
        self.assertIn('key="Escape", code="Escape"', self.window)
        self.assertIn("return event", self.window)

    def test_screenshot_shortcut_has_local_and_global_overlay_paths(self) -> None:
        self.assertIn("NSEventModifierFlagShift", self.window)
        self.assertIn("command_pressed and shift_pressed and characters == \"9\"", self.window)
        self.assertIn("evaluate_overlay_js", self.window)
        self.assertIn("NSEvent.addGlobalMonitorForEventsMatchingMask_handler_", self.window)
        self.assertIn("self._install_global_key_monitor()", self.window)
        self.assertIn("NSEvent.removeMonitor_(self._global_key_event_monitor)", self.window)
        self.assertIn('key="9", code="Digit9", meta_key=True, shift_key=True', self.window)

    def test_screenshot_exclusion_exports_only_cached_native_overlay_window_id(self) -> None:
        self.assertIn('setTitle_("ClosedRoom Recording Overlay")', self.window)
        self.assertIn("def screenshot_exclusion_window_ids(self) -> list[int]:", self.window)
        self.assertIn("window_id = int(self.overlay_window.windowNumber())", self.window)
        self.assertIn("self._overlay_capture_window_id = window_id if window_id > 0 else None", self.window)
        self.assertIn("if not self._overlay_visible or self._overlay_capture_window_id is None:", self.window)
        self.assertNotIn("run_on_main_thread(_read, wait=True)", self.window)

    def test_frontend_shortcuts_remain_supported_but_release_smoke_uses_search_outcome(self) -> None:
        self.assertIn("window.addEventListener('keydown', handleKeyDown)", self.dashboard)
        self.assertIn("setIsSearchOpen(true)", self.dashboard)
        self.assertIn('ui(pid, "press", LABELS["search"])', self.smoke)
        self.assertIn('check("search_opened_accessibly"', self.smoke)
        self.assertIn('check("search_focus_exposed"', self.smoke)
        self.assertIn('ui(pid, "press", LABELS["close"])', self.smoke)
        self.assertIn('check("search_closed_accessibly"', self.smoke)
        self.assertNotIn('key(pid, "cmd-k")', self.smoke)
        self.assertNotIn('key(pid, "escape")', self.smoke)


if __name__ == "__main__":
    unittest.main()
