from __future__ import annotations

import unittest

from local_asr_server.meeting_detection import (
    ActivityObservation, CoreAudioInputObserver, MeetingSuggestionPolicy,
)


def active(*ids: str) -> ActivityObservation:
    return ActivityObservation("supported", frozenset(ids))


TEAMS = "com.microsoft.teams2"
ZOOM = "us.zoom.xos"


class MeetingDetectionTests(unittest.TestCase):
    def test_no_prompt_before_opt_in_or_debounce(self):
        policy = MeetingSuggestionPolicy()
        self.assertEqual(policy.observe(active(TEAMS), enabled=False, busy=False, now=0), [])
        self.assertEqual(policy.observe(active(TEAMS), enabled=True, busy=False, now=10), [])
        self.assertEqual(policy.observe(active(TEAMS), enabled=True, busy=False, now=13), [])
        self.assertEqual(len(policy.observe(active(TEAMS), enabled=True, busy=False, now=14)), 1)

    def test_ignored_call_cannot_reprompt_during_short_mute_or_rejoin(self):
        p = MeetingSuggestionPolicy()
        p.observe(active(TEAMS), enabled=True, busy=False, now=0)
        first = p.observe(active(TEAMS), enabled=True, busy=False, now=5)[0]
        self.assertFalse(p.resolve_action(first.candidate_id, "ignore", now=5))
        p.observe(active(), enabled=True, busy=False, now=10)
        self.assertEqual(p.observe(active(TEAMS), enabled=True, busy=False, now=20), [])
        self.assertEqual(p.observe(active(TEAMS), enabled=True, busy=False, now=40), [])
        p.observe(active(), enabled=True, busy=False, now=41)
        p.observe(active(), enabled=True, busy=False, now=67)
        self.assertEqual(p.observe(active(TEAMS), enabled=True, busy=False, now=68), [])
        self.assertEqual(len(p.observe(active(TEAMS), enabled=True, busy=False, now=73)), 1)

    def test_stale_or_duplicate_notification_cannot_start(self):
        p = MeetingSuggestionPolicy(end_grace_seconds=25)
        p.observe(active(ZOOM), enabled=True, busy=False, now=0)
        candidate = p.observe(active(ZOOM), enabled=True, busy=False, now=4)[0]
        self.assertTrue(p.resolve_action(candidate.candidate_id, "record", now=5))
        self.assertFalse(p.resolve_action(candidate.candidate_id, "record", now=5))
        self.assertFalse(p.resolve_action(candidate.candidate_id, "record", now=30))

    def test_busy_and_unknown_fail_closed(self):
        p = MeetingSuggestionPolicy()
        p.observe(active(TEAMS), enabled=True, busy=True, now=0)
        self.assertEqual(p.observe(ActivityObservation("unknown"), enabled=True, busy=False, now=5), [])
        self.assertEqual(len(p.observe(active(TEAMS), enabled=True, busy=False, now=6)), 1)
        self.assertEqual(p.observe(active("com.google.Chrome"), enabled=True, busy=False, now=15), [])

    def test_detector_has_no_non_macos_success_fallback(self):
        observation = CoreAudioInputObserver().scan()
        self.assertIn(observation.capability, {"unsupported", "unknown", "supported"})
        if observation.capability != "supported":
            self.assertFalse(observation.active_bundle_ids)


if __name__ == "__main__":
    unittest.main()
