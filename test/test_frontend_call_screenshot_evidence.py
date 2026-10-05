from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "frontend" / "src" / "pages" / "RecordingOverlayPage.tsx"
RECORDER = ROOT / "frontend" / "src" / "hooks" / "useRecorder.ts"
MEETING = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
TRANSCRIPT = ROOT / "frontend" / "src" / "components" / "transcription" / "TranscriptTextView.tsx"
NOTES = ROOT / "frontend" / "src" / "components" / "meeting" / "StructuredNotesEditor.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "apiClient.ts"
PREPARATION_API = ROOT / "frontend" / "src" / "api" / "meetingPreparation.ts"
E2E = ROOT / "scripts" / "browser_call_overlay_screenshot_e2e.mjs"


class FrontendCallScreenshotEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = OVERLAY.read_text(encoding="utf-8")
        cls.recorder = RECORDER.read_text(encoding="utf-8")
        cls.meeting = MEETING.read_text(encoding="utf-8")
        cls.transcript = TRANSCRIPT.read_text(encoding="utf-8")
        cls.notes = NOTES.read_text(encoding="utf-8")
        cls.client = CLIENT.read_text(encoding="utf-8")
        cls.preparation_api = PREPARATION_API.read_text(encoding="utf-8")
        cls.e2e = E2E.read_text(encoding="utf-8")

    def test_overlay_uses_persisted_screenshot_api_and_truthful_stop_completion(self) -> None:
        self.assertIn("ApiClient.captureScreenshot(", self.overlay)
        self.assertIn("ApiClient.captureDisplays()", self.overlay)
        self.assertIn("ApiClient.stopRecordingControl(recordingId)", self.overlay)
        self.assertIn("ApiClient.openMeetingWindow(recordingId)", self.overlay)
        self.assertIn("data.type === 'ack' && data.action === 'stop'", self.overlay)
        self.assertIn("void ApiClient.getActiveRecording()", self.overlay)
        self.assertIn("if (!active.active) setIsStopping(false)", self.overlay)
        self.assertIn("window.location.hash = `#meeting/${recordingId}`", self.overlay)
        self.assertIn("screenshot_count?: number", self.client)
        self.assertIn("/screenshots", self.client)

    def test_source_mode_uses_browser_overlay_without_false_warning(self) -> None:
        self.assertIn("res?.fallback_expected", self.recorder)
        self.assertIn("setFallbackNotice(null)", self.recorder)
        self.assertIn("openBrowserPopup()", self.recorder)

    def test_browser_overlay_uses_control_center_dimensions_and_local_resize(self) -> None:
        self.assertIn("const width = 420;", self.recorder)
        self.assertIn("const height = 170;", self.recorder)
        self.assertIn("window.resizeTo(width, height + 52)", self.overlay)
        self.assertIn("resizeOverlayForState(isExpanded, true)", self.overlay)

    def test_overlay_display_selection_has_backend_owner_and_modern_control_center(self) -> None:
        self.assertIn("ApiClient.selectScreenshotDisplay(recordingId, displayId)", self.overlay)
        self.assertIn("/screenshot-display", self.client)
        self.assertIn("pendingDisplayIdRef.current", self.overlay)
        self.assertIn("pendingSelection === null || backendDisplayId === pendingSelection", self.overlay)
        self.assertIn('data-overlay-control-center="true"', self.overlay)
        self.assertIn('data-display-selector="true"', self.overlay)
        self.assertIn('data-display-picker="true"', self.overlay)
        self.assertIn('data-screenshot-action="true"', self.overlay)
        self.assertNotIn("<select", self.overlay)
        self.assertIn("display.width} × {display.height", self.overlay)
        self.assertIn("screenshotFeedback === 'saved'", self.overlay)

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

    def test_meeting_surfaces_saved_screenshots_as_progressive_gallery(self) -> None:
        self.assertIn('data-meeting-screenshot-gallery="true"', self.meeting)
        self.assertIn("screenshots.slice(0, 6)", self.meeting)
        self.assertIn("setShowAllScreenshots((value) => !value)", self.meeting)
        self.assertIn("src={shot.thumbnail_url}", self.meeting)
        self.assertIn("onClick={() => setSelectedScreenshot(shot)}", self.meeting)
        self.assertIn("screenshotTimestampLabel(shot.timestamp)", self.meeting)
        self.assertIn("src={selectedScreenshot.original_url}", self.meeting)
        self.assertIn("handleTimestampClick(selectedScreenshot.timestamp)", self.meeting)

    def test_prepare_notes_exposes_and_persists_screenshot_inclusion_choice(self) -> None:
        self.assertIn("Includi ${savedScreenshotCount} screenshot", self.meeting)
        self.assertIn("includeScreenshots", self.meeting)
        self.assertIn("latestPreparation?.result?.include_screenshots", self.meeting)
        self.assertIn("include_screenshots: includeScreenshots", self.preparation_api)

    def test_full_media_journey_covers_overlay_to_notes_and_audio(self) -> None:
        for evidence in (
            "03-screenshot-persisted",
            "04-meeting-notes-cited",
            "06-transcript-marker-in-turn",
            "07-screenshot-to-audio",
            "call-overlay-screenshot-evidence",
        ):
            self.assertIn(evidence, self.e2e)

    def test_failed_api_response_body_is_consumed_once(self) -> None:
        self.assertIn("const bodyText = await response.text();", self.client)
        self.assertIn("JSON.parse(bodyText)", self.client)
        self.assertNotIn("const payload = await response.json();", self.client)


if __name__ == "__main__":
    unittest.main()