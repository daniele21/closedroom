from __future__ import annotations

import unittest

from local_asr_server.audio_intelligence.vad_benchmark import (
    build_benchmark_report,
    build_case_report,
    interval_duration,
    timeline_jaccard,
)


class VadBackendBenchmarkTests(unittest.TestCase):
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
        self.assertNotIn("path", str(report).lower())
        self.assertEqual(case["comparison"]["timeline_jaccard"], 0.8)
        self.assertEqual(case["comparison"]["rms_to_silero_wall_ratio"], 0.2)
        self.assertFalse(report["decision_policy"]["automatic_recommendation"])


if __name__ == "__main__":
    unittest.main()
