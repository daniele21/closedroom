"""Characterize the path-transcription adapter without real inference or private data."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from local_asr_server.routers.transcriptions import transcribe_path
from local_asr_server.schemas import TranscribePathRequest


class PathTranscriptionAdapterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = Path(self.tmp.name) / "meeting.wav"
        self.audio.write_bytes(b"deterministic-fixture-audio")
        self.request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(default_model="default-model"))
        )

    def test_path_keeps_projection_public_provider_options_and_save(self) -> None:
        store = Mock()
        store.root = Path(self.tmp.name) / "transcripts"
        store.save.return_value = {"id": "tx-1"}
        raw = {
            "text": "ciao",
            "language": "it",
            "segments": [{"start": 0, "end": 1, "text": "ciao"}],
            "metadata": {"source": "fixture"},
        }
        with (
            patch("local_asr_server.routers.transcriptions.load_settings", return_value={}),
            patch(
                "local_asr_server.routers.transcriptions.TranscriptionService.resolve_asr",
                return_value=("local", "resolved-model", {"secret": "internal"}, {"region": "eu"}),
            ),
            patch(
                "local_asr_server.routers.transcriptions.TranscriptionService.backend",
                return_value="mlx",
            ),
            patch(
                "local_asr_server.routers.transcriptions.TranscriptionService.payload_metadata",
                return_value={"asr_provider": "local", "backend": "mlx"},
            ),
            patch(
                "local_asr_server.routers.transcriptions._transcribe_audio_file_with_cache",
                return_value=raw,
            ) as engine,
            patch(
                "local_asr_server.routers.transcriptions._apply_initial_diarization",
                side_effect=lambda app, audio, payload, **kwargs: payload,
            ) as diarize,
            patch(
                "local_asr_server.routers.transcriptions.get_services",
                return_value=SimpleNamespace(transcriptions=store),
            ),
        ):
            response = transcribe_path(
                self.request,
                TranscribePathRequest(file=str(self.audio), response_format="verbose_json"),
            )
        payload = json.loads(response.body)
        self.assertEqual(payload["text"], "ciao")
        self.assertEqual(payload["segments"], raw["segments"])
        self.assertEqual(payload["metadata"], raw["metadata"])
        self.assertEqual(payload["backend"], "mlx")
        self.assertEqual(payload["model"], "resolved-model")
        self.assertEqual(payload["provider_options"], {"region": "eu"})
        self.assertEqual(payload["saved_id"], "tx-1")
        self.assertEqual(payload["saved_file_path"], str(store.root))
        self.assertEqual(payload["stats"]["asr_provider"], "local")
        self.assertIn("time_total_seconds", payload["stats"])
        self.assertNotIn("secret", str(payload))
        self.assertEqual(engine.call_args.args[1], self.audio)
        self.assertEqual(engine.call_args.kwargs["provider_options"], {"secret": "internal"})
        self.assertEqual(diarize.call_args.kwargs["provider"], "none")
        store.save.assert_called_once()
        self.assertEqual(store.save.call_args.kwargs["audio_filename"], "meeting.wav")

    def test_text_format_missing_path_and_engine_errors(self) -> None:
        store = Mock()
        store.root = Path(self.tmp.name)
        store.save.return_value = {"id": "tx-1"}
        with (
            patch("local_asr_server.routers.transcriptions.load_settings", return_value={}),
            patch(
                "local_asr_server.routers.transcriptions.TranscriptionService.resolve_asr",
                return_value=("local", "resolved-model", {}, {}),
            ),
            patch(
                "local_asr_server.routers.transcriptions._apply_initial_diarization",
                side_effect=lambda app, audio, payload, **kwargs: payload,
            ),
            patch(
                "local_asr_server.routers.transcriptions._transcribe_audio_file_with_cache",
                return_value={"text": "hello"},
            ) as engine,
            patch(
                "local_asr_server.routers.transcriptions.get_services",
                return_value=SimpleNamespace(transcriptions=store),
            ),
        ):
            response = transcribe_path(
                self.request,
                TranscribePathRequest(file=str(self.audio), response_format="text"),
            )
            self.assertEqual(response.body.decode(), "hello")
            with self.assertRaises(HTTPException) as missing:
                transcribe_path(self.request, TranscribePathRequest(file=str(self.audio) + ".missing"))
            self.assertEqual(missing.exception.status_code, 404)
            engine.side_effect = RuntimeError("engine-failure")
            with self.assertRaises(HTTPException) as failure:
                transcribe_path(self.request, TranscribePathRequest(file=str(self.audio)))
            self.assertEqual(failure.exception.status_code, 500)
            self.assertIn("engine-failure", failure.exception.detail)


if __name__ == "__main__":
    unittest.main()
