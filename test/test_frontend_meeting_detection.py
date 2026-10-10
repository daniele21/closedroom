from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class MeetingDetectionFrontendContractTests(unittest.TestCase):
    def test_notification_start_must_claim_one_time_intent_before_capture(self):
        page = (ROOT / "frontend/src/pages/NewRecordingPage.tsx").read_text()
        self.assertIn("claimMeetingStartIntent(autoStartToken)", page)
        self.assertIn("if (!claimed.accepted) return", page)
        self.assertIn("!nativeCaptureReady || !readyToRecord", page)
        self.assertIn("recorder.startRecording('', '', '', 'both', undefined, '', true)", page)
        self.assertIn("meetingStartFeedback(autoStartToken, 'recording_ready')", page)

    def test_auto_route_is_distinct_from_opening_saved_recording(self):
        app = (ROOT / "frontend/src/App.tsx").read_text()
        self.assertIn("routeDetail?.startsWith('auto/')", app)
        self.assertIn("autoStartToken={routeDetail.slice(5)}", app)

    def test_native_only_request_fails_closed_without_fallback(self):
        hook = (ROOT / "frontend/src/hooks/useRecorder.ts").read_text()
        self.assertIn("requireNative && !(capabilities?.default_backend === 'native'", hook)
        self.assertIn("createCaptureReservation()", hook)
        self.assertIn("data.type === 'ready'", hook)

    def test_opt_in_is_off_by_default_and_explicit_in_settings(self):
        page = (ROOT / "frontend/src/pages/SettingsPage.tsx").read_text()
        self.assertIn("data-settings-meeting-detection", page)
        self.assertIn("checked={meetingDetectionEnabled}", page)
        self.assertIn("meeting_detection_enabled: meetingDetectionEnabled", page)
        self.assertIn("meetingDetectionEnabled && !meetingDetectionWasEnabled", page)


if __name__ == "__main__":
    unittest.main()
