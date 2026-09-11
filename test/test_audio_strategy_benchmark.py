from __future__ import annotations

import unittest

from local_asr_server.audio_strategy_benchmark import (
    build_benchmark_report,
    build_run_report,
    timeline_jaccard,
    transcript_similarity,
)


class AudioStrategyBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dual = {
            "text": "ignored formatted text",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "hello there", "source": "mic", "track_id": "mic"},
                {"start": 3.0, "end": 5.0, "text": "general kenobi", "source": "system", "track_id": "system"},
            ],
        }
        self.mixed = {
            "text": "hello there general kenobi",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "hello there", "source": "mixed", "track_id": "mixed"},
                {"start": 3.0, "end": 5.0, "text": "general kenobi", "source": "mixed", "track_id": "mixed"},
            ],
        }

    def test_similarity_uses_segment_words_not_formatted_merged_text(self) -> None:
        self.assertEqual(transcript_similarity(self.dual, self.mixed), 1.0)

    def test_timeline_jaccard_measures_speech_interval_overlap(self) -> None:
        shifted = {
            "segments": [
                {"start": 1.0, "end": 3.0, "text": "hello there"},
                {"start": 4.0, "end": 6.0, "text": "general kenobi"},
            ]
        }
        self.assertEqual(timeline_jaccard(self.dual, self.mixed), 1.0)
        self.assertAlmostEqual(timeline_jaccard(self.dual, shifted) or 0.0, 1 / 3, places=6)

    def test_run_report_exposes_compute_and_attribution_tradeoff(self) -> None:
        report = build_run_report(
            dual_payload=self.dual,
            mixed_payload=self.mixed,
            dual_wall_seconds=12.0,
            mixed_wall_seconds=7.5,
            dual_audio_seconds=120.0,
            mixed_audio_seconds=60.0,
            order="dual_first",
        )
        self.assertEqual(report["comparison"]["dual_to_mixed_audio_ratio"], 2.0)
        self.assertEqual(report["comparison"]["dual_to_mixed_wall_ratio"], 1.6)
        self.assertEqual(report["comparison"]["transcript_similarity"], 1.0)
        self.assertEqual(report["comparison"]["timeline_jaccard"], 1.0)
        self.assertEqual(report["dual_track"]["attributed_segment_ratio"], 1.0)
        self.assertEqual(report["mixed_track"]["attributed_segment_ratio"], 0.0)
        self.assertEqual(report["comparison"]["attribution_ratio_delta"], 1.0)

    def test_benchmark_report_never_contains_transcript_content(self) -> None:
        run = build_run_report(
            dual_payload=self.dual,
            mixed_payload=self.mixed,
            dual_wall_seconds=12.0,
            mixed_wall_seconds=8.0,
            dual_audio_seconds=120.0,
            mixed_audio_seconds=60.0,
            order="dual_first",
        )
        report = build_benchmark_report(
            runs=[run],
            input_summary={"tracks": {"mixed": {"duration_seconds": 60.0}}},
            model="test-model",
            language="en",
        )
        serialized = str(report).lower()
        self.assertNotIn("hello there", serialized)
        self.assertNotIn("general kenobi", serialized)
        self.assertFalse(report["decision_policy"]["automatic_recommendation"])
        self.assertEqual(report["summary"]["median_dual_to_mixed_wall_ratio"], 1.5)
        self.assertEqual(report["summary"]["dual_to_mixed_audio_ratio"], 2.0)

    def test_empty_transcripts_are_comparable_without_fake_attribution(self) -> None:
        empty = {"text": "", "segments": []}
        report = build_run_report(
            dual_payload=empty,
            mixed_payload=empty,
            dual_wall_seconds=0.0,
            mixed_wall_seconds=0.0,
            dual_audio_seconds=0.0,
            mixed_audio_seconds=0.0,
            order="dual_first",
        )
        self.assertEqual(report["comparison"]["transcript_similarity"], 1.0)
        self.assertEqual(report["comparison"]["timeline_jaccard"], 1.0)
        self.assertIsNone(report["comparison"]["dual_to_mixed_audio_ratio"])
        self.assertIsNone(report["comparison"]["dual_to_mixed_wall_ratio"])
        self.assertIsNone(report["comparison"]["attribution_ratio_delta"])


if __name__ == "__main__":
    unittest.main()
