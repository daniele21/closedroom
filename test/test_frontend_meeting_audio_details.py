from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEETING = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
ACCESSORIES = (ROOT / "frontend/src/hooks/useMeetingAccessories.ts").read_text(encoding="utf-8")
RECORDING_DETAILS = (ROOT / "frontend/src/components/meeting/MeetingRecordingDetails.tsx").read_text(encoding="utf-8")
AUDIO_PANEL = (ROOT / "frontend/src/pages/recording/AudioIntelligencePanel.tsx").read_text(encoding="utf-8")
BROWSER = (ROOT / "scripts/browser_saved_meeting_e2e.mjs").read_text(encoding="utf-8")


class MeetingAudioDetailsContractTests(unittest.TestCase):
    def test_audio_metrics_use_existing_local_api_on_explicit_disclosure_only(self) -> None:
        self.assertIn("ApiClient.recordingIntelligence(recordingId)", ACCESSORIES)
        self.assertIn("if (!recordingId || demoMode) return;", ACCESSORIES)
        self.assertIn("audioIntelligenceGenerationRef", ACCESSORIES)
        self.assertIn("audioIntelligenceGenerationRef.current += 1", ACCESSORIES)
        self.assertIn("audioIntelligenceState === 'idle'", MEETING)
        self.assertIn("aria-expanded={audioIntelligenceOpen}", MEETING)
        self.assertIn("setAudioIntelligenceOpen(opening)", MEETING)
        self.assertIn("aria-controls=\"meeting-audio-intelligence-panel\"", MEETING)
        self.assertIn("void loadAudioIntelligence()", MEETING)
        self.assertIn('data-meeting-audio-intelligence="true"', MEETING)
        self.assertIn("onClick={() => void loadAudioIntelligence()}", MEETING)

    def test_source_audio_tracks_and_quality_warnings_are_not_lost(self) -> None:
        self.assertIn("<MeetingRecordingDetails recording={meeting.recording} />", MEETING)
        self.assertIn('data-meeting-recording-details="true"', RECORDING_DETAILS)
        self.assertIn("aria-expanded={expanded}", RECORDING_DETAILS)
        self.assertIn("track.primary", RECORDING_DETAILS)
        self.assertIn("preload=\"none\"", RECORDING_DETAILS)
        self.assertIn("recording.quality_report", RECORDING_DETAILS)
        self.assertIn("sync_duration_warning", RECORDING_DETAILS)
        self.assertIn("probeUnavailable", RECORDING_DETAILS)
        self.assertIn("qualityProbeUnavailable", RECORDING_DETAILS)
        self.assertIn("qualitySyncLabel", RECORDING_DETAILS)

    def test_scrollable_details_drawer_does_not_shrink_disclosure_targets(self) -> None:
        # Flex children with overflow-hidden otherwise shrink below the button's
        # 44px hit area, so the parent section intercepts the actual pointer.
        self.assertIn(
            '<SheetBody className="flex flex-col gap-5 overflow-y-auto pt-2 [&>*]:shrink-0">',
            MEETING,
        )
        self.assertIn("await clickWhenPointerReady(browser, '[data-meeting-recording-details", BROWSER)
        self.assertIn("await clickWhenPointerReady(browser, '[data-meeting-audio-intelligence", BROWSER)

    def test_reuses_original_audio_projection_with_truthful_mock_disclaimer(self) -> None:
        self.assertIn("<AudioIntelligencePanel", MEETING)
        self.assertIn("compact", AUDIO_PANEL)
        self.assertIn("intelligence?.mock", AUDIO_PANEL)
        self.assertIn("mockDisclaimer", AUDIO_PANEL)

    def test_browser_journey_falsifies_eager_loading(self) -> None:
        self.assertIn("counts.audio_intelligence !== 0", BROWSER)
        self.assertIn("Opening Meeting Details fetched audio metrics", BROWSER)
        self.assertIn("await waitCount('audio_intelligence', 1)", BROWSER)
        self.assertIn("Canonical Meeting lost recording quality", BROWSER)


if __name__ == "__main__":
    unittest.main()
