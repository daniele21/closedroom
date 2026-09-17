from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HOOK = ROOT / "frontend" / "src" / "hooks" / "useRecorder.ts"


class FrontendRecordingEfficiencyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = HOOK.read_text(encoding="utf-8")

    def test_recording_ui_has_explicit_human_scale_update_budgets(self) -> None:
        self.assertRegex(self.source, r"AUDIO_METER_RENDER_INTERVAL_MS\s*=\s*80")
        self.assertRegex(self.source, r"AUDIO_METER_REACT_INTERVAL_MS\s*=\s*250")
        self.assertRegex(self.source, r"RECORDING_TIMER_INTERVAL_MS\s*=\s*1000")
        self.assertRegex(self.source, r"OVERLAY_STATUS_INTERVAL_MS\s*=\s*500")

    def test_meter_skips_hidden_document_and_throttles_react_state(self) -> None:
        self.assertIn("document.hidden", self.source)
        self.assertIn("lastMeterRenderAtRef", self.source)
        self.assertIn("lastMeterReactAtRef", self.source)
        self.assertIn("AUDIO_METER_RENDER_INTERVAL_MS", self.source)
        self.assertIn("AUDIO_METER_REACT_INTERVAL_MS", self.source)

    def test_timer_and_overlay_use_named_budgets_for_native_and_browser_paths(self) -> None:
        self.assertEqual(
            len(re.findall(r"\}, RECORDING_TIMER_INTERVAL_MS\);", self.source)),
            2,
        )
        self.assertEqual(
            len(re.findall(r"\}, OVERLAY_STATUS_INTERVAL_MS\);", self.source)),
            2,
        )
        self.assertNotIn("}, 250);\n\n              // Start status broadcast", self.source)
        self.assertNotIn("}, 300);", self.source)


if __name__ == "__main__":
    unittest.main()
