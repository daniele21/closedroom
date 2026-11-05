from __future__ import annotations

import unittest
from unittest.mock import patch

from local_asr_server.schemas import SettingsRequest
from local_asr_server.services.settings_service import (
    InvalidSettings, SettingsService, validate_storage_selection,
)
from local_asr_server.settings import DEFAULT_SETTINGS


class StorageTargetSelectionTests(unittest.TestCase):
    def test_default_is_local_with_no_automatic_cleanup(self) -> None:
        self.assertEqual(DEFAULT_SETTINGS["storage_preference"], "local")
        self.assertFalse(DEFAULT_SETTINGS["audio_auto_cleanup_enabled"])
        with patch(
            "local_asr_server.services.settings_service.load_settings",
            return_value=DEFAULT_SETTINGS.copy(),
        ):
            result = SettingsService().get_public()
        self.assertEqual(result["storage_preference"], "local")
        self.assertEqual(result["storage_effective_mode"], "local")
        self.assertEqual(result["storage_capability"], "preparation_only")
        self.assertFalse(result["gcs_configuration_complete"])

    def test_opt_in_only_saves_preparation_never_activates_cloud(self) -> None:
        current = DEFAULT_SETTINGS.copy()
        saved = {
            **current,
            "storage_preference": "gcs",
            "gcs_project_id": "project-tests-498508",
            "gcs_bucket_name": "project-tests-498508-closedroom-test",
            "gcs_region": "europe-west8",
        }
        with (
            patch("local_asr_server.services.settings_service.load_settings",
                  side_effect=[current, saved]),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            result = SettingsService().update(SettingsRequest(
                storage_preference="gcs",
                gcs_project_id=saved["gcs_project_id"],
                gcs_bucket_name=saved["gcs_bucket_name"],
                gcs_region=saved["gcs_region"],
            ))
        persisted = save.call_args.args[0]
        self.assertEqual(persisted["storage_preference"], "gcs")
        self.assertFalse(persisted["audio_auto_cleanup_enabled"])
        self.assertEqual(result["storage_effective_mode"], "local")
        self.assertEqual(result["storage_capability"], "preparation_only")
        self.assertTrue(result["gcs_configuration_complete"])
        self.assertNotIn("gcs_access_token", result)

    def test_incomplete_configuration_is_not_reported_as_connected(self) -> None:
        with patch(
            "local_asr_server.services.settings_service.load_settings",
            return_value={**DEFAULT_SETTINGS, "storage_preference": "gcs"},
        ):
            result = SettingsService().get_public()
        self.assertEqual(result["storage_effective_mode"], "local")
        self.assertFalse(result["gcs_configuration_complete"])

    def test_invalid_config_or_mode_is_never_saved(self) -> None:
        invalid = [
            SettingsRequest(storage_preference="remote_auto"),
            SettingsRequest(storage_preference="gcs", gcs_project_id="../private"),
            SettingsRequest(gcs_bucket_name="goog-private"),
            SettingsRequest(gcs_bucket_name="192.168.1.3"),
            SettingsRequest(gcs_bucket_name="UPPERCASE"),
            SettingsRequest(gcs_region=""),
            SettingsRequest(gcs_region="../europe"),
        ]
        for body in invalid:
            with (
                self.subTest(body=body),
                patch("local_asr_server.services.settings_service.load_settings",
                      return_value=DEFAULT_SETTINGS.copy()),
                patch("local_asr_server.services.settings_service.save_settings") as save,
            ):
                with self.assertRaises(InvalidSettings):
                    SettingsService().update(body)
                save.assert_not_called()

    def test_cleanup_still_cannot_be_enabled_with_gcs_selected(self) -> None:
        with (
            patch("local_asr_server.services.settings_service.load_settings",
                  return_value=DEFAULT_SETTINGS.copy()),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            with self.assertRaises(InvalidSettings):
                SettingsService().update(SettingsRequest(
                    storage_preference="gcs",
                    audio_auto_cleanup_enabled=True,
                ))
            save.assert_not_called()

    def test_other_settings_updates_preserve_gcs_intent(self) -> None:
        original = {
            **DEFAULT_SETTINGS,
            "storage_preference": "gcs",
            "gcs_project_id": "project-tests-498508",
            "gcs_bucket_name": "project-tests-498508-closedroom-test",
        }
        validate_storage_selection(original)
        with (
            patch("local_asr_server.services.settings_service.load_settings",
                  side_effect=[original, {**original, "default_language": "en"}]),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            result = SettingsService().update(SettingsRequest(default_language="en"))
        self.assertEqual(save.call_args.args[0]["storage_preference"], "gcs")
        self.assertEqual(result["storage_effective_mode"], "local")
        self.assertTrue(result["gcs_configuration_complete"])


if __name__ == "__main__":
    unittest.main()
