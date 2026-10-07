from __future__ import annotations

import unittest

from local_asr_server.macos_hotkeys import (
    CMD_KEY,
    DEFAULT_MEETING_HOTKEYS,
    K_EVENT_CLASS_KEYBOARD,
    K_EVENT_PARAM_DIRECT_OBJECT,
    KEY_9,
    KEY_N,
    KEY_R,
    SHIFT_KEY,
    TYPE_EVENT_HOT_KEY_ID,
    CarbonHotKeyManager,
    fourcc,
)


class NativeMeetingHotKeyContractTests(unittest.TestCase):
    def test_fourcc_matches_carbon_event_constants(self) -> None:
        self.assertEqual(fourcc("keyb"), K_EVENT_CLASS_KEYBOARD)
        self.assertEqual(fourcc("----"), K_EVENT_PARAM_DIRECT_OBJECT)
        self.assertEqual(fourcc("hkid"), TYPE_EVENT_HOT_KEY_ID)
        with self.assertRaises(ValueError):
            fourcc("bad")

    def test_default_meeting_shortcuts_preserve_existing_record_and_screenshot_keys(self) -> None:
        expected_modifiers = CMD_KEY | SHIFT_KEY
        self.assertEqual(
            DEFAULT_MEETING_HOTKEYS["toggle_recording"],
            (KEY_R, expected_modifiers, "⌘⇧R"),
        )
        self.assertEqual(
            DEFAULT_MEETING_HOTKEYS["add_note"],
            (KEY_N, expected_modifiers, "⌘⇧N"),
        )
        self.assertEqual(
            DEFAULT_MEETING_HOTKEYS["screenshot"],
            (KEY_9, expected_modifiers, "⌘⇧9"),
        )

    def test_non_macos_runtime_never_silently_claims_native_support(self) -> None:
        if not CarbonHotKeyManager.supported():
            manager = CarbonHotKeyManager([])
            with self.assertRaisesRegex(RuntimeError, "macOS"):
                manager.start()


if __name__ == "__main__":
    unittest.main()
