from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.services.transcription_service import TranscriptionService


class TranscriptionServiceCacheTests(unittest.TestCase):
    def test_cache_key_uses_supplied_audio_hash_without_rescanning_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "audio.wav"
            audio.write_bytes(b"audio")
            options = {
                "model": "model",
                "language": "it",
                "task": "transcribe",
                "word_timestamps": False,
                "initial_prompt": None,
                "temperature": None,
                "condition_on_previous_text": False,
                "vad_guided": True,
                "vad_post_filter": True,
                "asr_provider": "local",
                "provider_options": {},
            }
            with patch(
                "local_asr_server.services.transcription_service.hash_audio_file",
                side_effect=AssertionError("supplied recording hash should be reused"),
            ):
                key = TranscriptionService.cache_key(
                    audio,
                    audio_hash="a" * 64,
                    **options,
                )
        self.assertEqual(len(key), 64)


if __name__ == "__main__":
    unittest.main()
