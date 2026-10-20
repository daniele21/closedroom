from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.schemas import SettingsRequest
from local_asr_server.services.settings_service import InvalidSettings, SettingsService
from local_asr_server.settings import DEFAULT_SETTINGS


class SettingsServiceTests(unittest.TestCase):
    def test_rejects_unknown_cross_feature_options(self):
        invalid_requests = (
            SettingsRequest(llm_provider="unknown"),
            SettingsRequest(local_llm_mode="sometimes"),
            SettingsRequest(meeting_default_pipeline="missing"),
            SettingsRequest(default_task="summarize"),
            SettingsRequest(speechmatics_timeout_seconds=0),
            SettingsRequest(speaker_diarization_minimum_overlap=1.5),
            SettingsRequest(speaker_diarization_engine="unknown"),
            SettingsRequest(speaker_diarization_nemotron_preset="unvalidated"),
            SettingsRequest(visual_frame_similarity_threshold=-1),
            SettingsRequest(visual_frame_similarity_threshold=65),
        )
        for body in invalid_requests:
            with self.subTest(body=body), patch(
                "local_asr_server.services.settings_service.load_settings",
                return_value=DEFAULT_SETTINGS.copy(),
            ):
                with self.assertRaises(InvalidSettings):
                    SettingsService().update(body)

    def test_nemotron_engine_and_preset_are_persisted(self):
        current = DEFAULT_SETTINGS.copy()
        modified = {
            **current,
            "speaker_diarization_engine": "nemotron3-coreml",
            "speaker_diarization_nemotron_preset": "c128-split-w8a8",
        }
        with (
            patch("local_asr_server.services.settings_service.load_settings", side_effect=[current, modified]),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            SettingsService().update(SettingsRequest(
                speaker_diarization_engine="nemotron3-coreml",
                speaker_diarization_nemotron_preset="c128-split-w8a8",
            ))
        self.assertEqual(save.call_args.args[0]["speaker_diarization_engine"], "nemotron3-coreml")
        self.assertEqual(save.call_args.args[0]["speaker_diarization_nemotron_preset"], "c128-split-w8a8")

    def test_default_temperature_is_persisted_as_number(self):
        current = DEFAULT_SETTINGS.copy()
        with (
            patch(
                "local_asr_server.services.settings_service.load_settings",
                side_effect=[current, {**current, "default_temperature": 0.35}],
            ),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            SettingsService().update(SettingsRequest(default_temperature=0.35))

        value = save.call_args.args[0]["default_temperature"]
        self.assertEqual(value, 0.35)
        self.assertIsInstance(value, float)

    def test_partial_update_only_changes_provided_fields(self):
        current = DEFAULT_SETTINGS.copy()
        with (
            patch(
                "local_asr_server.services.settings_service.load_settings",
                side_effect=[current, {**current, "default_language": "en"}],
            ),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            result = SettingsService().update(SettingsRequest(default_language="en"))

        saved = save.call_args.args[0]
        self.assertEqual(saved["default_language"], "en")
        self.assertEqual(saved["default_model"], current["default_model"])
        self.assertEqual(result["default_language"], "en")

    def test_explicit_nullable_value_is_persisted(self):
        current = {**DEFAULT_SETTINGS, "local_llm_temperature": 0.4}
        with (
            patch(
                "local_asr_server.services.settings_service.load_settings",
                side_effect=[current, {**current, "local_llm_temperature": None}],
            ),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            SettingsService().update(SettingsRequest(local_llm_temperature=None))

        self.assertIsNone(save.call_args.args[0]["local_llm_temperature"])

    def test_directory_is_normalized_and_checked(self):
        current = DEFAULT_SETTINGS.copy()
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "transcriptions"
            expected = {**current, "transcriptions_dir": str(target.resolve())}
            with (
                patch(
                    "local_asr_server.services.settings_service.load_settings",
                    side_effect=[current, expected],
                ),
                patch("local_asr_server.services.settings_service.save_settings") as save,
            ):
                SettingsService().update(SettingsRequest(transcriptions_dir=str(target)))

        self.assertEqual(save.call_args.args[0]["transcriptions_dir"], str(target.resolve()))

    def test_public_settings_hide_credentials(self):
        settings = {
            **DEFAULT_SETTINGS,
            "gemini_api_key": "secret",
            "speechmatics_api_key": "secret",
        }
        with patch("local_asr_server.services.settings_service.load_settings", return_value=settings):
            result = SettingsService().get_public()

        self.assertNotIn("gemini_api_key", result)
        self.assertNotIn("speechmatics_api_key", result)
        self.assertTrue(result["gemini_api_key_configured"])
        self.assertTrue(result["speechmatics_api_key_configured"])

    def test_default_temperature_nullable_is_persisted(self):
        current = {**DEFAULT_SETTINGS, "default_temperature": 0.5}
        with (
            patch(
                "local_asr_server.services.settings_service.load_settings",
                side_effect=[current, {**current, "default_temperature": None}],
            ),
            patch("local_asr_server.services.settings_service.save_settings") as save,
        ):
            SettingsService().update(SettingsRequest(default_temperature=None))

        self.assertIsNone(save.call_args.args[0]["default_temperature"])

    def test_load_settings_normalizes_empty_strings(self):
        from local_asr_server.settings import load_settings
        bad_data = {
            "default_temperature": "",
            "speechmatics_timeout_seconds": "",
            "speechmatics_poll_interval_seconds": "",
            "local_llm_temperature": "",
            "local_llm_max_output_tokens": "",
            "local_llm_ctx_size": "",
            "local_llm_startup_timeout": "",
        }
        with (
            patch("local_asr_server.settings.get_settings_file") as mock_get_file,
            patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(bad_data))),
        ):
            mock_get_file.return_value.exists.return_value = True
            loaded = load_settings()

        for key in bad_data:
            self.assertIsNone(loaded[key])


if __name__ == "__main__":
    unittest.main()
