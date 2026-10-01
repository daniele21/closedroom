from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "NewRecordingPage.tsx"


class NewMeetingSimplicityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PAGE.read_text(encoding="utf-8")

    def test_normal_new_meeting_does_not_expose_global_enrichment_controls(self) -> None:
        self.assertNotIn("visualIntelligenceEnabled", self.source)
        self.assertNotIn("speakerDiarizationEnabled", self.source)
        self.assertNotIn("updateEnrichmentSetting", self.source)
        self.assertNotIn("<Checkbox", self.source)

    def test_capture_source_controls_exist_only_in_audio_recovery(self) -> None:
        self.assertIn("showAudioRecovery", self.source)
        self.assertIn("!nativeCaptureReady && nativeCaptureChecked", self.source)
        self.assertIn("new-meeting-audio-recovery", self.source)
        self.assertIn("ClosedRoom could not configure audio automatically", self.source)

    def test_screen_context_is_optional_native_only_and_off_by_default(self) -> None:
        self.assertIn("showScreenContext", self.source)
        self.assertIn("useState('')", self.source)
        self.assertIn("ApiClient.captureWindows()", self.source)
        self.assertIn(
            "recordingFlowLocked = recorder.isRecording || recorder.isPreparingRecording",
            self.source,
        )
        self.assertIn("nativeCaptureReady && !recordingFlowLocked", self.source)
        self.assertIn("Screen context (optional)", self.source)
        self.assertIn("Off by default", self.source)
        self.assertIn("No visual AI runs while recording", self.source)
        self.assertIn("No frames are captured without an explicit selection", self.source)

    def test_normal_start_keeps_automatic_audio_and_only_passes_explicit_visual_source(self) -> None:
        self.assertIn("useState<'both' | 'mic_only' | 'pc_only'>('both')", self.source)
        self.assertIn("visualWindowId ? Number(visualWindowId) : undefined", self.source)
        self.assertIn("selectedVisualWindow", self.source)
        self.assertNotIn("visualWindowId ||", self.source)


if __name__ == "__main__":
    unittest.main()
