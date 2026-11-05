from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from local_asr_server.schemas import SettingsRequest
from local_asr_server.settings import DEFAULT_SETTINGS, load_settings
from local_asr_server.services.settings_service import SettingsService


class MeetingDetectionSettingsTests(unittest.TestCase):
    def test_default_enabled_but_saved_explicit_off_is_preserved(self):
        self.assertIs(DEFAULT_SETTINGS["meeting_detection_enabled"], True)
        with TemporaryDirectory() as folder:
            settings_path = Path(folder) / "settings.json"
            with patch("local_asr_server.settings.get_settings_file", return_value=settings_path):
                self.assertIs(load_settings()["meeting_detection_enabled"], True)
                settings_path.write_text('{"meeting_detection_enabled": false}', encoding="utf-8")
                self.assertIs(load_settings()["meeting_detection_enabled"], False)

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
