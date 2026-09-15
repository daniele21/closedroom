from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "diagnose_macos_keyboard_event_path.py"


class MacOSKeyboardEventPathProbeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = PROBE.read_text(encoding="utf-8")

    def test_probe_uses_same_pid_targeted_driver_and_appkit_monitor_shape(self) -> None:
        self.assertIn('DRIVER.key(os.getpid(), "cmd-k")', self.probe)
        self.assertIn('DRIVER.key(os.getpid(), "escape")', self.probe)
        self.assertIn("NSEvent.addLocalMonitorForEventsMatchingMask_handler_", self.probe)
        self.assertIn("NSEventMaskKeyDown", self.probe)
        self.assertIn("NSEventModifierFlagCommand", self.probe)
        self.assertIn("key_code == 40 or semantic_k", self.probe)
        self.assertIn("key_code == 53", self.probe)

    def test_probe_discriminates_monitor_bridge_and_dom_boundaries(self) -> None:
        self.assertIn('"event": "monitor_received"', self.probe)
        self.assertIn('"event": "cmd_k_matched"', self.probe)
        self.assertIn('"event": "bridge_requested"', self.probe)
        self.assertIn('"event": "bridge_completion"', self.probe)
        self.assertIn("defaultPrevented", self.probe)
        self.assertIn("cmd_k_count", self.probe)
        self.assertIn("pid_targeted_cmd_k_did_not_reach_local_monitor", self.probe)
        self.assertIn("cmd_k_matched_but_webview_bridge_did_not_complete", self.probe)
        self.assertIn("cmd_k_bridge_completed_but_dom_listener_not_reached", self.probe)

    def test_probe_is_diagnostic_only_and_privacy_bounded(self) -> None:
        self.assertIn('"qualification_scope": "diagnostic_only"', self.probe)
        self.assertIn("does not launch ClosedRoom", self.probe)
        self.assertNotIn("/v1/meetings", self.probe)
        self.assertNotIn("transcript", self.probe.lower())
        self.assertNotIn("recording.wav", self.probe)


if __name__ == "__main__":
    unittest.main()
