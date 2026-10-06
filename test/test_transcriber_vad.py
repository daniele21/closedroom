from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from local_asr_server.schemas import TranscribePathRequest, TranscribeRecordingRequest
from local_asr_server.transcriber import VAD_GUIDED_DEFAULT, _transcribe_vad_guided


def _write_tone_wav(path: Path, *, duration: float = 2.0) -> None:
    sample_rate = 16_000
    frames = bytearray()
    for index in range(int(duration * sample_rate)):
        value = int(math.sin(2 * math.pi * 440 * (index / sample_rate)) * 10_000)
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))


class VadGuidedTranscriptionTests(unittest.TestCase):
    def _kwargs(self) -> dict:
        return {
            "audio_path": "/tmp/meeting.wav",
            "model": "test-model",
            "language": "it",
            "task": "transcribe",
            "word_timestamps": False,
            "initial_prompt": None,
            "temperature": None,
            "condition_on_previous_text": False,
            "verbose": None,
        }

    def test_vad_guided_is_enabled_by_default(self) -> None:
        self.assertTrue(VAD_GUIDED_DEFAULT)
        self.assertTrue(TranscribePathRequest(file="/tmp/meeting.wav").vad_guided)
        self.assertTrue(TranscribeRecordingRequest().vad_guided)
        self.assertFalse(TranscribePathRequest(file="/tmp/meeting.wav").condition_on_previous_text)
        self.assertFalse(TranscribeRecordingRequest().condition_on_previous_text)

    def test_canonical_wav_uses_streaming_vad_and_direct_window_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "meeting.wav"
            _write_tone_wav(source)
            kwargs = {**self._kwargs(), "audio_path": str(source)}
            with patch(
                "local_asr_server.audio_intelligence.vad.detect_speech_windows_vad_chunks",
                return_value=[{"start": 0.5, "end": 1.0}],
            ) as detect_chunks, patch(
                "local_asr_server.audio_intelligence.audio_io.load_audio_samples",
                side_effect=AssertionError("canonical path must not materialize the full track"),
            ), patch(
                "local_asr_server.transcriber._transcribe",
                return_value={"text": "ciao", "segments": [{"id": 0, "start": 0.0, "end": 0.5, "text": "ciao"}]},
            ) as transcribe:
                result = _transcribe_vad_guided(**kwargs)

        detect_chunks.assert_called_once()
        transcribe.assert_called_once()
        self.assertEqual(result["text"], "ciao")
        self.assertAlmostEqual(result["segments"][0]["start"], 0.0, places=3)
        self.assertAlmostEqual(result["segments"][0]["end"], 1.5, places=3)

    @patch("local_asr_server.transcriber._transcribe")
    @patch("local_asr_server.audio_intelligence.vad.detect_speech_windows_vad", return_value=[])
    @patch("local_asr_server.audio_intelligence.audio_io.load_audio_samples")
    def test_no_speech_windows_falls_back_to_full_track(self, load_samples, _detect_windows, transcribe) -> None:
        load_samples.return_value = np.zeros(16_000, dtype=np.float32)
        transcribe.return_value = {"text": "Voce presente", "segments": [{"id": 0}]}

        result = _transcribe_vad_guided(**self._kwargs())

        transcribe.assert_called_once_with(**self._kwargs())
        self.assertEqual(result["text"], "Voce presente")
        self.assertEqual(
            result["metadata"],
            {
                "vad_guided": True,
                "vad_fallback": True,
                "vad_fallback_reason": "no_speech_windows_detected",
                "vad_windows_count": 0,
            },
        )

    @patch("local_asr_server.transcriber._transcribe")
    @patch("local_asr_server.audio_intelligence.vad.detect_speech_windows_vad")
    @patch("local_asr_server.audio_intelligence.audio_io.load_audio_samples")
    def test_empty_vad_window_results_fall_back_to_full_track(self, load_samples, detect_windows, transcribe) -> None:
        load_samples.return_value = np.zeros(32_000, dtype=np.float32)
        detect_windows.return_value = [{"start": 0.5, "end": 1.0}]
        transcribe.side_effect = [
            {"text": "", "segments": []},
            {"text": "Trascrizione completa", "segments": [{"id": 0}]},
        ]

        result = _transcribe_vad_guided(**self._kwargs())

        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(result["text"], "Trascrizione completa")
        self.assertEqual(result["metadata"]["vad_fallback_reason"], "vad_windows_produced_empty_transcript")
        self.assertEqual(result["metadata"]["vad_windows_count"], 1)


if __name__ == "__main__":
    unittest.main()
