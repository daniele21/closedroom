import unittest

from local_asr_server.schemas import TranscribeRecordingRequest
from local_asr_server.services.transcription_service import TranscriptionService


class RecordingTranscriptionDefaultsTests(unittest.TestCase):
    def test_omitted_options_follow_persisted_settings(self) -> None:
        body = TranscribeRecordingRequest()
        settings = {
            "default_model": "configured-model",
            "default_language": "en",
            "default_task": "translate",
            "default_word_timestamps": True,
            "default_temperature": 0.35,
            "default_condition_on_previous": True,
        }

        resolved = TranscriptionService.resolve_recording_defaults(
            body,
            settings,
            fallback_model="startup-model",
        )

        self.assertEqual(resolved.model, "configured-model")
        self.assertEqual(resolved.language, "en")
        self.assertEqual(resolved.task, "translate")
        self.assertTrue(resolved.word_timestamps)
        self.assertEqual(resolved.temperature, 0.35)
        self.assertTrue(resolved.condition_on_previous_text)

    def test_explicit_overrides_remain_authoritative(self) -> None:
        body = TranscribeRecordingRequest(
            model="request-model",
            language=None,
            task="transcribe",
            word_timestamps=False,
            temperature=0.1,
            condition_on_previous_text=False,
        )
        settings = {
            "default_model": "configured-model",
            "default_language": "en",
            "default_task": "translate",
            "default_word_timestamps": True,
            "default_temperature": 0.35,
            "default_condition_on_previous": True,
        }

        resolved = TranscriptionService.resolve_recording_defaults(
            body,
            settings,
            fallback_model="startup-model",
        )

        self.assertEqual(resolved.model, "request-model")
        self.assertIsNone(resolved.language)
        self.assertEqual(resolved.task, "transcribe")
        self.assertFalse(resolved.word_timestamps)
        self.assertEqual(resolved.temperature, 0.1)
        self.assertFalse(resolved.condition_on_previous_text)

    def test_model_falls_back_to_startup_default_when_setting_is_empty(self) -> None:
        resolved = TranscriptionService.resolve_recording_defaults(
            TranscribeRecordingRequest(),
            {"default_model": ""},
            fallback_model="startup-model",
        )

        self.assertEqual(resolved.model, "startup-model")


if __name__ == "__main__":
    unittest.main()
