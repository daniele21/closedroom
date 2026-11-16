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

    def test_changing_diarization_engine_or_preset_invalidates_pipeline_cache(self) -> None:
        base = {"speaker_diarization_enabled": True, "speaker_diarization_engine": "fluidaudio-community-1",
                "speaker_diarization_nemotron_preset": "fast128"}
        def key(settings):
            return TranscriptionService.recording_pipeline_cache_key(
                recording_id="r1", track_results=[{"track": {"id": "system"}, "result": {"segments": []}}],
                settings=settings, visual_input_fingerprint="", diarization_provider="local",
            )
        original = key(base)
        nemotron = key({**base, "speaker_diarization_engine": "nemotron3-coreml"})
        split = key({**base, "speaker_diarization_engine": "nemotron3-coreml",
                     "speaker_diarization_nemotron_preset": "c128-split-w8a8"})
        self.assertNotEqual(original, nemotron)
        self.assertNotEqual(nemotron, split)


if __name__ == "__main__":
    unittest.main()
