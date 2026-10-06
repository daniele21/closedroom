from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendDiagnosticContractTests(unittest.TestCase):
    def test_meeting_visual_timeline_exposes_confidence_and_degraded_states(self) -> None:
        page = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/src/components/meeting/VisualIntelligencePanel.tsx").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")
        hook = (ROOT / "frontend/src/hooks/useVisualIntelligence.ts").read_text(encoding="utf-8")
        italian = (ROOT / "frontend/src/i18n/locales/it.ts").read_text(encoding="utf-8")
        english = (ROOT / "frontend/src/i18n/locales/en.ts").read_text(encoding="utf-8")

        self.assertIn("useVisualIntelligence", page)
        self.assertIn("ApiClient.visualIntelligenceV2(recordingId, controller.signal)", hook)
        self.assertIn("controller.abort()", hook)
        self.assertIn("!controller.signal.aborted", hook)
        self.assertIn("VisualIntelligencePanel", page)
        self.assertIn("speakerNeedsReview", panel)
        self.assertIn("visualAbstained", panel)
        self.assertIn("visualTimelineUnavailable", panel)
        self.assertIn("/v2/recordings/${recordingId}/visual-intelligence", client)
        for translations in (italian, english):
            self.assertIn("visualTimelineTitle", translations)
            self.assertIn("visualEvent_screen_share_started", translations)

    def test_meeting_drawer_consumes_diagnostic_endpoint_and_renders_failures(self) -> None:
        page = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        accessories = (ROOT / "frontend/src/hooks/useMeetingAccessories.ts").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")
        self.assertIn("useMeetingAccessories", page)
        self.assertIn("ApiClient.getMeetingDiagnostics(recordingId)", accessories)
        self.assertIn("completed_with_warnings", page)
        self.assertIn("item.requested_backend", page)
        self.assertIn("item.actual_backend", page)
        self.assertIn("item.fallback_reason", page)
        self.assertIn("diagnosticReport.log_file", page)
        self.assertIn("/v1/meetings/${recordingId}/diagnostics", client)

    def test_capture_and_overlay_fallbacks_have_persistent_ui_feedback(self) -> None:
        recorder = (ROOT / "frontend/src/hooks/useRecorder.ts").read_text(encoding="utf-8")
        page = (ROOT / "frontend/src/pages/RecordingPage.tsx").read_text(encoding="utf-8")
        self.assertIn("captureCapabilityFallbackNotice", recorder)
        self.assertIn("captureBrowserFallbackNotice", recorder)
        self.assertIn("overlayFallbackNotice", recorder)
        self.assertIn("recorder.fallbackNotice", page)

    def test_recording_exposes_visual_window_and_diarization_before_start(self) -> None:
        page = (ROOT / "frontend/src/pages/RecordingPage.tsx").read_text(encoding="utf-8")
        self.assertIn("speaker_diarization_enabled", page)
        self.assertIn("visual_intelligence_enabled", page)
        self.assertIn("recording.visualWindowLabel", page)
        self.assertIn("ApiClient.captureWindows()", page)
        self.assertIn("recording.visualNeedsDiarization", page)
        self.assertIn("recording.visualCaptureActive", page)

        overlay = (ROOT / "frontend/src/pages/RecordingOverlayPage.tsx").read_text(encoding="utf-8")
        recorder = (ROOT / "frontend/src/hooks/useRecorder.ts").read_text(encoding="utf-8")
        self.assertIn("visualCaptureLabel", overlay)
        self.assertIn("recording.visualCaptureActive", overlay)
        self.assertIn("visualCaptureLabelRef", recorder)

    def test_transcription_result_surfaces_degraded_outcomes(self) -> None:
        page = (ROOT / "frontend/src/pages/TranscriptionPage.tsx").read_text(encoding="utf-8")
        result = (ROOT / "frontend/src/pages/transcription/components/ResultsStep.tsx").read_text(encoding="utf-8")
        diagnostics = (ROOT / "frontend/src/utils/diagnostics.ts").read_text(encoding="utf-8")
        self.assertIn("showTranscriptionOutcome", page)
        self.assertIn("transcriptionHasWarnings", page)
        self.assertIn("item.requested_backend", result)
        self.assertIn("item.actual_backend", result)
        self.assertIn("item.fallback_reason", result)
        self.assertIn("speaker_diarization", result)
        self.assertIn("visual_intelligence", result)
        self.assertIn("completed_with_warnings", diagnostics)

    def test_settings_surfaces_missing_accessibility_permission(self) -> None:
        page = (ROOT / "frontend/src/pages/SettingsPage.tsx").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")
        self.assertIn("ApiClient.accessibilityStatus()", page)
        self.assertIn("settings.accessibilityWarningTitle", page)
        self.assertIn("/v1/system/accessibility", client)


if __name__ == "__main__":
    unittest.main()
