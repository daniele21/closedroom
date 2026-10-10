from __future__ import annotations

import unittest

from local_asr_server.schemas import SettingsRequest
from local_asr_server.settings import DEFAULT_SETTINGS
from local_asr_server.services.settings_service import SettingsService


class MeetingDetectionSettingsTests(unittest.TestCase):
    def test_opt_in_default_off(self):
        self.assertIs(DEFAULT_SETTINGS["meeting_detection_enabled"], False)

    def test_partial_update_distinguishes_false_from_omitted(self):
        self.assertEqual(
            SettingsService._request_patch(SettingsRequest(meeting_detection_enabled=True)),
            {"meeting_detection_enabled": True},
        )
        self.assertEqual(
            SettingsService._request_patch(SettingsRequest(meeting_detection_enabled=False)),
            {"meeting_detection_enabled": False},
        )
        self.assertNotIn("meeting_detection_enabled", SettingsService._request_patch(SettingsRequest()))


if __name__ == "__main__":
    unittest.main()
