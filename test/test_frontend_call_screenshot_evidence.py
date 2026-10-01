from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "frontend" / "src" / "pages" / "RecordingOverlayPage.tsx"
MEETING = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
TRANSCRIPT = ROOT / "frontend" / "src" / "components" / "transcription" / "TranscriptTextView.tsx"
NOTES = ROOT / "frontend" / "src" / "components" / "meeting" / "StructuredNotesEditor.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "apiClient.ts"
E2E = ROOT / "scripts" / "browser_call_overlay_screenshot_e2e.mjs"


class FrontendCallScreenshotEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = OVERLAY.read_text(encoding="utf-8")
        cls.meeting = MEETING.read_text(encoding="utf-8")
        cls.transcript = TRANSCRIPT.read_text(encoding="utf-8")
        cls.notes = NOTES.read_text(encoding="utf-8")
        cls.client = CLIENT.read_text(encoding="utf-8")
        cls.e2e = E2E.read_text(encoding="utf-8")

    def test_overlay_uses_persisted_screenshot_api_and_truthful_stop_completion(self) -> None:
        self.assertIn("ApiClient.captureScreenshot(", self.overlay)
        self.assertIn("ApiClient.captureDisplays()", self.overlay)
        self.assertIn("ApiClient.stopRecordingControl(recordingId)", self.overlay)
        self.assertIn("ApiClient.openMeetingWindow(recordingId)", self.overlay)
        self.assertIn("ACK only means the stop command was received", self.overlay)
        self.assertIn("if (!active.active) setIsStopping(false)", self.overlay)
        self.assertIn("window.location.hash = `#meeting/${recordingId}`", self.overlay)
        self.assertIn("screenshot_count?: number", self.client)
        self.assertIn("/screenshots", self.client)

    def test_transcript_keeps_asr_segments_immutable_and_anchors_screenshot_by_time(self) -> None:
        self.assertIn("segment.start <= shot.timestamp && shot.timestamp <= segment.end", self.transcript)
        self.assertIn("screenshotPlacement.anchored.get(seg.id)", self.transcript)
        self.assertIn("data-screenshot-id={shot.screenshot_id}", self.transcript)
        self.assertIn("renderHighlightedText(seg.text, seg.id)", self.transcript)
        self.assertNotIn("seg.text =", self.transcript)
        self.assertNotIn("seg.id =", self.transcript)

    def test_meeting_and_structured_notes_share_the_same_screenshot_assets(self) -> None:
        self.assertIn("ApiClient.recordingScreenshots(recordingId)", self.meeting)
        self.assertGreaterEqual(self.meeting.count("screenshots={screenshots}"), 2)
        self.assertIn("onOpenScreenshot={setSelectedScreenshot}", self.meeting)
        self.assertIn("ref.source_type === 'screenshot'", self.notes)
        self.assertIn("onOpenScreenshot(screenshot)", self.notes)

    def test_full_media_journey_covers_overlay_to_notes_and_audio(self) -> None:
        for evidence in (
            "03-screenshot-persisted",
            "04-meeting-notes-cited",
            "06-transcript-marker-in-turn",
            "07-screenshot-to-audio",
            "call-overlay-screenshot-evidence",
        ):
            self.assertIn(evidence, self.e2e)


if __name__ == "__main__":
    unittest.main()
