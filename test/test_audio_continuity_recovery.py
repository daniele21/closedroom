"""Deterministic missing-audio recovery tests; physical device evidence remains required."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from local_asr_server.recording_audio_recovery import AudioRecoveryError, checkpoint_frame_count, recover_checkpoint_audio
from local_asr_server.recordings import RecordingStore


def checkpoint(session: Path, index: int, start: float, sample_value: int, *, marked: bool):
    directory = session / ".audio-recovery" / "mic"
    directory.mkdir(parents=True, exist_ok=True)
    pcm = struct.pack("<h", sample_value) * 16000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    audio = buffer.getvalue()
    name = f"{index:08d}"
    (directory / f"{name}.wav").write_bytes(audio)
    (directory / f"{name}.json").write_text(json.dumps({
        "version": 1, "source": "mic", "sequence": index,
        "file": f"{name}.wav", "bytes": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "start_pts": start, "end_pts": start + 1.0,
        "frames": 16000, "total_frames": (index + 1) * 16000,
        "discontinuity_before": marked,
    }), encoding="utf-8")


class AudioContinuityRecoveryTests(unittest.TestCase):
    def test_explicit_source_gap_is_silence_padded_and_originals_remain_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            checkpoint(session, 0, 100, 400, marked=False)
            checkpoint(session, 1, 104, 800, marked=True)
            original = session / "mic.wav"
            original.write_bytes(b"unclosed original")
            result = recover_checkpoint_audio(session, "mic")
            self.assertEqual(checkpoint_frame_count(session, "mic"), 5 * 16000)
            self.assertEqual(result, recover_checkpoint_audio(session, "mic"))
            self.assertEqual(original.read_bytes(), b"unclosed original")
            with wave.open(str(result), "rb") as reader:
                self.assertEqual(reader.getnframes(), 5 * 16000)
                self.assertEqual(reader.readframes(16000), struct.pack("<h", 400) * 16000)
                self.assertEqual(reader.readframes(3 * 16000), b"\0\0" * (3 * 16000))
                self.assertEqual(reader.readframes(16000), struct.pack("<h", 800) * 16000)

    def test_unmarked_gap_and_backward_clock_fail_closed(self):
        for marked, start in ((False, 104), (True, 99)):
            with self.subTest(marked=marked, start=start), tempfile.TemporaryDirectory() as temp:
                session = Path(temp)
                checkpoint(session, 0, 100, 400, marked=False)
                checkpoint(session, 1, start, 800, marked=marked)
                with self.assertRaises(AudioRecoveryError):
                    recover_checkpoint_audio(session, "mic")
                self.assertEqual(list(session.glob("*.recovered-*.wav")), [])

    def test_valid_consecutive_legacy_segments_need_no_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            checkpoint(session, 0, 100, 400, marked=False)
            checkpoint(session, 1, 101, 800, marked=False)
            recovered = recover_checkpoint_audio(session, "mic")
            with wave.open(str(recovered), "rb") as reader:
                self.assertEqual(reader.getnframes(), 2 * 16000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "Aligned mix requires bundled or system ffmpeg")
    def test_store_rebuilds_mixed_derivative_without_overwriting_original_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RecordingStore(Path(temp), use_settings_dir=False)
            created = store.create(
                title="Synthetic switch", mime_type="audio/wav",
                model="test", language=None, capture_mode="both", capture_backend="native",
            )
            recording_id = created["id"]
            session = store.session_dir(recording_id)
            store.mark_capture_started(recording_id, backend="native")
            store.mark_capture_event(recording_id, {"type": "ready", "recording_ready_uptime": 100.0})
            store.mark_capture_event(recording_id, {
                "type": "source_interrupted", "source": "mic", "uptime": 101.0,
            })
            store.mark_capture_event(recording_id, {
                "type": "source_recovered", "source": "mic", "uptime": 104.0,
            })
            checkpoint(session, 0, 100, 400, marked=False)
            checkpoint(session, 1, 104, 800, marked=True)
            with wave.open(str(session / "mic.wav"), "wb") as mic:
                mic.setnchannels(1)
                mic.setsampwidth(2)
                mic.setframerate(16000)
                mic.writeframes(struct.pack("<h", 400) * 16000)
            with wave.open(str(session / "system.wav"), "wb") as system:
                system.setnchannels(1)
                system.setsampwidth(2)
                system.setframerate(16000)
                system.writeframes(struct.pack("<h", 100) * (5 * 16000))
            with wave.open(str(session / "recording.wav"), "wb") as legacy_mix:
                legacy_mix.setnchannels(1)
                legacy_mix.setsampwidth(2)
                legacy_mix.setframerate(16000)
                legacy_mix.writeframes(struct.pack("<h", 500) * (5 * 16000))
            old = (session / "recording.wav").read_bytes()
            completed, _ = store.finalize(recording_id)
            self.assertEqual(completed["status"], "recorded")
            self.assertEqual((session / "recording.wav").read_bytes(), old)
            output = store.track_audio_path(recording_id, "mixed")
            self.assertNotEqual(output, session / "recording.wav")
            with wave.open(str(output), "rb") as audio:
                self.assertEqual(audio.getframerate(), 16000)
                self.assertGreaterEqual(audio.getnframes(), 5 * 16000)
            self.assertIn("native_audio_gaps_marked_with_silence_for_alignment", completed["warnings"])
