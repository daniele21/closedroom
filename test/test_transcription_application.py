from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_asr_server.services.transcription_application import (
    SingleFileTranscriptionRequest,
    SingleFileTranscriptionUseCase,
)
from local_asr_server.routers.transcriptions import tempfile_NamedTemporaryFile_patch


class _FakeTranscriptionService:
    @staticmethod
    def backend(provider: str, model: str) -> str:
        return f"{provider}:{model}"

    @staticmethod
    def payload_metadata(provider: str, model: str, options: dict) -> dict:
        return {
            "asr_provider": provider,
            "backend": f"{provider}:{model}",
            "model": model,
            "provider_options": options,
        }


class _FakeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.saved = []

    def save(self, payload, *, audio_filename, recording_id):
        self.saved.append((payload, audio_filename, recording_id))
        return {"id": "tx-1"}


class _FakeDiarization:
    def process_audio_payload(self, audio_path, payload, **kwargs):
        result = dict(payload)
        result.setdefault("stats", {})["speaker_diarization"] = {
            "status": "completed",
            "provider": kwargs["provider"],
        }
        return result


class StreamingUploadTemporaryPathTests(unittest.TestCase):
    def test_default_temporary_path_is_cleaned_on_context_exit(self) -> None:
        with tempfile_NamedTemporaryFile_patch(suffix=".wav") as raw_path:
            path = Path(raw_path)
            path.write_bytes(b"audio")
            self.assertTrue(path.exists())
        self.assertFalse(path.exists())

    def test_streaming_can_take_cleanup_ownership(self) -> None:
        with tempfile_NamedTemporaryFile_patch(suffix=".wav", cleanup=False) as raw_path:
            path = Path(raw_path)
            path.write_bytes(b"audio")
        try:
            self.assertTrue(path.exists())
        finally:
            path.unlink(missing_ok=True)


class SingleFileTranscriptionUseCaseTests(unittest.TestCase):
    def test_run_owns_result_shape_diarization_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "meeting.wav"
            audio.write_bytes(b"audio")
            store = _FakeStore(root / "transcriptions")
            services = SimpleNamespace(
                transcriptions=store,
                diarization=_FakeDiarization(),
            )
            request = SingleFileTranscriptionRequest(
                model="model-a",
                language="it",
                task="transcribe",
                word_timestamps=False,
                initial_prompt=None,
                temperature=0.0,
                condition_on_previous_text=False,
                verbose=None,
                vad_guided=True,
                vad_post_filter=True,
                asr_provider="local",
                provider_options={},
                public_provider_options={},
                diarization_provider="local",
            )
            use_case = SingleFileTranscriptionUseCase(_FakeTranscriptionService())
            engine_calls = []

            def engine(**kwargs):
                engine_calls.append(kwargs)
                return {
                    "text": "ciao",
                    "segments": [{"id": 0, "text": "ciao"}],
                    "metadata": {},
                }

            with (
                patch(
                    "local_asr_server.services.transcription_application.get_services",
                    return_value=services,
                ),
                patch(
                    "local_asr_server.services.transcription_application.get_cached_result",
                    return_value=None,
                ),
                patch(
                    "local_asr_server.services.transcription_application.save_cached_result",
                ) as save_cache,
            ):
                payload = use_case.run(
                    SimpleNamespace(),
                    audio,
                    request,
                    audio_filename="meeting.wav",
                    recording_id="rec-1",
                    engine=engine,
                )

            self.assertEqual(len(engine_calls), 1)
            self.assertEqual(payload["text"], "ciao")
            self.assertEqual(payload["recording_id"], "rec-1")
            self.assertEqual(payload["saved_id"], "tx-1")
            self.assertEqual(
                payload["stats"]["speaker_diarization"]["provider"],
                "local",
            )
            self.assertEqual(store.saved[0][1:], ("meeting.wav", "rec-1"))
            save_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
