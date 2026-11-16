from __future__ import annotations

import unittest

from scripts.benchmark_speaker_diarization import approximate_der


class BenchmarkSpeakerDiarizationTests(unittest.TestCase):
    def test_permutation_does_not_count_as_speaker_error(self):
        ref = [{"speaker": "A", "start": 0.0, "end": 1.0},
               {"speaker": "B", "start": 1.0, "end": 2.0}]
        pred = [{"speaker": "42", "start": 0.0, "end": 1.0},
                {"speaker": "13", "start": 1.0, "end": 2.0}]
        self.assertEqual(approximate_der(ref, pred, 2), 0.0)

    def test_missing_overlap_is_counted(self):
        ref = [{"speaker": "A", "start": 0, "end": 2},
               {"speaker": "B", "start": 1, "end": 2}]
        pred = [{"speaker": "A", "start": 0, "end": 2}]
        self.assertGreater(approximate_der(ref, pred, 2), 0)

    def test_empty_reference_has_no_score(self):
        self.assertIsNone(approximate_der([], [], 1))


if __name__ == "__main__":
    unittest.main()
