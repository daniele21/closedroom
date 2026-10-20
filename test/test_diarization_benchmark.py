from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
import wave

from local_asr_server.speaker_diarization_benchmark import (
    _preview_segments, run_benchmark, validate_options,
)


def make_wav(path: Path, frames: int = 16_000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * frames)


class FakeRecordingStore:
    def __init__(self, path: Path, *, dual: bool = True) -> None:
        self.metadata = {"status": "recorded", "title": "Private meeting", "note_count": 4}
        self.path = path
        self.dual = dual

    def get(self, recording_id, include_result=False):
        return self.metadata

    def transcribable_tracks(self, recording_id):
        if self.dual:
            return [({"id": "mic"}, self.path), ({"id": "system"}, self.path)]
        return [({"id": "mixed"}, self.path)]


class FakeDiarizer:
    def __init__(self, failed_engine: str | None = None):
        self.inputs = []
        self.failed_engine = failed_engine

    def diarize_paths(self, inputs, *, engine, preset, cancel_requested):
        self.inputs.append((list(inputs.values())[0], engine, preset))
        if engine == self.failed_engine:
            raise ValueError("/private/recordings/never-expose.wav")
        return {
            "tracks": {"benchmark": {"segments": [
                {"speaker": "S1", "start": 0.1, "end": 0.4},
                {"speaker": "S2", "start": 0.4, "end": 0.8},
            ]}},
        }


class DiarizationBenchmarkTests(unittest.TestCase):
    def test_duplicate_and_invalid_engines_rejected(self):
        with self.assertRaises(ValueError):
            validate_options(["community-1", "community-1"], "sample")
        with self.assertRaises(ValueError):
            validate_options(["community-1", "remote-ai"], "sample")
        with self.assertRaises(ValueError):
            validate_options(["community-1", "nemotron3-fast128"], "invalid")

    def test_sample_uses_run_owned_wav_no_meeting_mutation_or_path_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "original.wav"
            make_wav(path)
            store = FakeRecordingStore(path)
            original = copy.deepcopy(store.metadata)
            diarizer = FakeDiarizer()
            progress = []
            result = run_benchmark(
                store, "recording", engines=["community-1", "nemotron3-fast128"],
                scope="sample", service=diarizer, cancel_requested=lambda: False,
                on_progress=lambda *args: progress.append(args),
            )
            self.assertEqual(store.metadata, original)
            self.assertEqual(result["track_id"], "system")
            self.assertEqual(result["scope"], "sample")
            self.assertEqual(result["outcome_status"], "completed")
            self.assertEqual(result["audio_seconds"], 1)
            self.assertEqual(len(result["runs"]), 2)
            self.assertEqual(len(progress), 4)
            self.assertTrue(all(not path.exists() for path, _, _ in diarizer.inputs))
            self.assertEqual(path.stat().st_size, 32044)
            self.assertNotIn(str(path), str(result))
            self.assertNotIn("Private meeting", str(result))
            self.assertFalse(result["reference_scored"])

    def test_full_run_records_failures_without_exposing_sensitive_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "original.wav"
            make_wav(path)
            diarizer = FakeDiarizer(failed_engine="nemotron3-coreml")
            result = run_benchmark(
                FakeRecordingStore(path, dual=False), "recording",
                engines=["community-1", "nemotron3-fast128"], scope="full",
                service=diarizer, cancel_requested=lambda: False,
                on_progress=lambda *_args: None,
            )
            self.assertEqual(result["track_id"], "mixed")
            self.assertEqual(result["outcome_status"], "completed_with_warnings")
            self.assertEqual(result["runs"][1]["status"], "failed")
            self.assertEqual(result["runs"][1]["error_type"], "ValueError")
            self.assertNotIn("/private/", str(result))
            self.assertEqual(diarizer.inputs[0][0], path)

    def test_cancellation_prevents_next_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "original.wav"
            make_wav(path)
            diarizer = FakeDiarizer()
            cancelled = [False]

            def progress(percent, step, detail):
                if detail["index"] == 1 and percent > 40:
                    cancelled[0] = True

            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                run_benchmark(
                    FakeRecordingStore(path), "recording",
                    engines=["community-1", "nemotron3-fast128"],
                    scope="sample", service=diarizer,
                    cancel_requested=lambda: cancelled[0], on_progress=progress,
                )
            self.assertEqual(len(diarizer.inputs), 1)

    def test_preview_preserves_overlap_and_bounds_results(self):
        timeline = [{"speaker": "S1", "start": 0, "end": 4},
                    {"speaker": "S2", "start": 2, "end": 7},
                    {"speaker": "S2", "start": 310, "end": 312}]
        preview, truncated = _preview_segments(timeline, 5)
        self.assertFalse(truncated)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[1]["start"], 2)
        self.assertEqual(preview[1]["end"], 5)


if __name__ == "__main__":
    unittest.main()
