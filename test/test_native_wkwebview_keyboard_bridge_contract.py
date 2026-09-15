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

    def test_existing_frontend_and_real_environment_keyboard_contracts_remain_authoritative(self) -> None:
        self.assertIn("window.addEventListener('keydown', handleKeyDown)", self.dashboard)
        self.assertIn("setIsSearchOpen(true)", self.dashboard)
        self.assertIn('key(pid, "cmd-k")', self.smoke)
        self.assertIn('check("keyboard_cmd_k_search"', self.smoke)
        self.assertIn('key(pid, "escape")', self.smoke)
        self.assertIn('check("keyboard_escape_search"', self.smoke)


if __name__ == "__main__":
    unittest.main()
