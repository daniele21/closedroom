from __future__ import annotations

import unittest

from local_asr_server.meeting_detection import ActivityObservation
from scripts.probe_meeting_detection import probe


TEAMS = "com.microsoft.teams2"


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class SequenceObserver:
    def __init__(self, samples):
        self.samples = iter(samples)

    def scan(self):
        return next(self.samples)


class MeetingDetectionProbeTests(unittest.TestCase):
    def test_actual_on_off_transition_is_detected_without_audio_or_identity(self):
        clock = FakeClock()
        inactive = ActivityObservation("supported")
        active = ActivityObservation(
            "supported", frozenset({TEAMS}), active_input_processes=1,
        )
        result = probe(
            4, 1,
            observer=SequenceObserver([inactive, active, active, inactive]),
            clock=clock, sleeper=clock.sleep,
        )
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["observed_supported_apps"], ["Microsoft Teams"])
        self.assertEqual(result["transition_counts"]["Microsoft Teams:on"], 1)
        self.assertEqual(result["transition_counts"]["Microsoft Teams:off"], 1)
        self.assertIs(result["captures_media"], False)
        self.assertIs(result["uploads_data"], False)
        self.assertNotIn("pid", str(result).lower())
        self.assertNotIn("meeting_title", str(result).lower())

    def test_unavailable_coreaudio_reports_reason_not_fake_activity(self):
        clock = FakeClock()
        unknown = ActivityObservation("unknown", reason="coreaudio_unavailable")
        result = probe(
            2, 1, observer=SequenceObserver([unknown, unknown]),
            clock=clock, sleeper=clock.sleep,
        )
        self.assertEqual(result["capability_counts"], {"unknown": 2})
        self.assertEqual(result["capability_reasons"], {"coreaudio_unavailable": 2})
        self.assertEqual(result["observed_supported_apps"], [])
        self.assertEqual(result["peak_active_input_processes"], 0)

    def test_unattributed_input_is_not_labeled_a_meeting(self):
        clock = FakeClock()
        unknown_app = ActivityObservation(
            "supported", active_input_processes=1, unattributed_input_processes=1,
        )
        result = probe(
            2, 1, observer=SequenceObserver([unknown_app, unknown_app]),
            clock=clock, sleeper=clock.sleep,
        )
        self.assertEqual(result["peak_unattributed_input_processes"], 1)
        self.assertEqual(result["observed_supported_apps"], [])
        self.assertEqual(result["transition_counts"], {})


if __name__ == "__main__":
    unittest.main()
