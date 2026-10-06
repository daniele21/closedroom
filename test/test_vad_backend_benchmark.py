from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from local_asr_server.audio_intelligence.vad_benchmark import (
    build_benchmark_report,
    build_case_report,
    discover_finalized_recording_tracks,
    interval_duration,
    timeline_jaccard,
)


class VadBackendBenchmarkTests(unittest.TestCase):
    def test_discovers_latest_finalized_tracks_without_store_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            older = root / "2026-01-01" / "older"
            newer = root / "2026-01-02" / "newer"
            active = root / "2026-01-03" / "active"
            for directory in (older, newer, active):
                directory.mkdir(parents=True)

            (older / "metadata.json").write_text(json.dumps({
                "status": "completed",
                "created_at": "2026-01-01T10:00:00+00:00",
                "audio_tracks": [{
                    "id": "mixed",
                    "source": "mixed",
                    "extension": ".wav",
                    "primary": True,
                }],
            }), encoding="utf-8")
            (older / "recording.wav").write_bytes(b"old")

            (newer / "metadata.json").write_text(json.dumps({
                "status": "recorded",
                "created_at": "2026-01-02T10:00:00+00:00",
                "audio_tracks": [
                    {"id": "mic", "source": "mic", "extension": ".wav", "primary": True},
                    {"id": "system", "source": "system", "extension": ".wav", "primary": False},
                    {"id": "mixed", "source": "mixed", "extension": ".wav", "primary": False},
                ],
            }), encoding="utf-8")
            (newer / "mic.wav").write_bytes(b"mic")
            (newer / "system.wav").write_bytes(b"system")
            (newer / "recording.wav").write_bytes(b"mixed")

            (active / "metadata.json").write_text(json.dumps({
                "status": "recording",
                "created_at": "2026-01-03T10:00:00+00:00",
                "audio_tracks": [{
                    "id": "mic",
                    "source": "mic",
                    "extension": ".wav",
                    "primary": True,
                }],
            }), encoding="utf-8")
            (active / "mic.wav").write_bytes(b"active")

            paths = discover_finalized_recording_tracks(root, recording_limit=1)

        self.assertEqual([path.name for path in paths], ["mic.wav", "system.wav"])
        self.assertTrue(all("active" not in str(path) for path in paths))

    def test_timeline_jaccard_uses_merged_intervals(self) -> None:
        left = [{"start": 0.0, "end": 2.0}, {"start": 1.5, "end": 3.0}]
        right = [{"start": 1.0, "end": 2.0}]
        self.assertAlmostEqual(interval_duration(left), 3.0)
        self.assertAlmostEqual(timeline_jaccard(left, right), 1.0 / 3.0)

    def test_report_is_privacy_safe_and_has_no_input_path_field(self) -> None:
        case = build_case_report(
            index=0,
            bytes_total=1234,
            duration_seconds=10.0,
            canonical_wav=True,
            silero_runs=[{"wall_seconds": 1.0, "speech_seconds": 4.0, "window_count": 2}],
            rms_runs=[{"wall_seconds": 0.2, "speech_seconds": 5.0, "window_count": 3}],
            silero_windows=[{"start": 1.0, "end": 5.0}],
            rms_windows=[{"start": 1.0, "end": 6.0}],
        )
        report = build_benchmark_report([case])

        self.assertEqual(report["benchmark"], "silero_vad_vs_energy_rms")
        self.assertFalse(report["privacy"]["retains_audio"])
        self.assertFalse(report["privacy"]["retains_transcript"])
        self.assertFalse(report["privacy"]["retains_paths_or_filenames"])
        self.assertNotIn("path", case)
        self.assertNotIn("filename", case)
        self.assertEqual(case["comparison"]["timeline_jaccard"], 0.8)
        self.assertEqual(case["comparison"]["rms_to_silero_wall_ratio"], 0.2)
        self.assertFalse(report["decision_policy"]["automatic_recommendation"])


if __name__ == "__main__":
    unittest.main()
