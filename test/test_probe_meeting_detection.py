from __future__ import annotations

import unittest

from local_asr_server.meeting_detection import ActivityObservation
from scripts.probe_meeting_detection import probe


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class Scanner:
    def __init__(self, samples):
        self.samples = iter(samples)

    def scan(self):
        return next(self.samples)


class RealMacProbeContractTests(unittest.TestCase):
    def test_evidence_contains_only_capability_counts_and_supported_labels(self):
        zoom = 'us.zoom.xos'
        clock = Clock()
        result = probe(4, 1,
            observer=Scanner([
                ActivityObservation('supported'),
                ActivityObservation('supported', frozenset({zoom})),
                ActivityObservation('supported', frozenset({zoom})),
                ActivityObservation('supported'),
            ]),
            clock=clock.monotonic, sleeper=clock.sleep,
        )
        self.assertEqual(result['sample_count'], 4)
        self.assertEqual(result['transition_counts'], {'Zoom:on': 1, 'Zoom:off': 1})
        self.assertEqual(result['observed_supported_apps'], ['Zoom'])
        for forbidden in ('pid', 'title', 'audio_buffer', 'window_id', 'recording_id'):
            self.assertNotIn(forbidden, str(result).lower())
        self.assertIs(result['captures_media'], False)
        self.assertIs(result['uploads_data'], False)

    def test_unsupported_or_unknown_does_not_claim_inactive_microphone(self):
        clock = Clock()
        result = probe(2, 1, observer=Scanner([
            ActivityObservation('unsupported', reason='old_macos'),
            ActivityObservation('unknown', reason='coreaudio_unavailable'),
        ]), clock=clock.monotonic, sleeper=clock.sleep)
        self.assertEqual(result['capability_counts'], {'unsupported': 1, 'unknown': 1})
        self.assertEqual(result['observed_supported_apps'], [])


if __name__ == '__main__':
    unittest.main()
