from __future__ import annotations

import unittest

from local_asr_server.runtime.resource_policy import (
    ResourcePolicy,
    ResourcePolicyBlocked,
    recording_has_active_capture,
)


class ResourcePolicyTests(unittest.TestCase):
    def test_policy_allows_heavy_work_without_active_capture(self) -> None:
        policy = ResourcePolicy(capture_active=lambda: False)

        policy.assert_heavy_work_admissible("analysis")

        self.assertEqual(
            policy.snapshot(),
            {"profile": "balanced", "capture_active": False},
        )

    def test_policy_blocks_heavy_work_during_capture(self) -> None:
        policy = ResourcePolicy(capture_active=lambda: True)

        with self.assertRaises(ResourcePolicyBlocked) as ctx:
            policy.assert_heavy_work_admissible("transcription")

        self.assertEqual(ctx.exception.reason, "capture_active")

    def test_policy_reads_capture_state_lazily_from_canonical_owner(self) -> None:
        active = False
        policy = ResourcePolicy(capture_active=lambda: active)

        self.assertFalse(policy.snapshot()["capture_active"])
        active = True
        self.assertTrue(policy.snapshot()["capture_active"])
        with self.assertRaises(ResourcePolicyBlocked):
            policy.assert_heavy_work_admissible("vision")
        active = False
        policy.assert_heavy_work_admissible("vision")

    def test_prepared_recording_is_not_treated_as_active_capture(self) -> None:
        self.assertFalse(recording_has_active_capture({
            "status": "recording",
            "capture_status": "idle",
            "chunk_count": 0,
            "audio_tracks": [{"id": "mic", "chunk_count": 0}],
        }))

    def test_native_and_browser_capture_signals_are_active(self) -> None:
        self.assertTrue(recording_has_active_capture({
            "status": "recording",
            "capture_status": "recording",
            "chunk_count": 0,
        }))
        self.assertTrue(recording_has_active_capture({
            "status": "recording",
            "capture_status": "idle",
            "chunk_count": 1,
        }))
        self.assertTrue(recording_has_active_capture({
            "status": "recording",
            "capture_status": "idle",
            "chunk_count": 0,
            "audio_tracks": [{"id": "system", "chunk_count": 1}],
        }))

    def test_legacy_recording_metadata_remains_fail_safe(self) -> None:
        self.assertTrue(recording_has_active_capture({
            "status": "recording",
            "chunk_count": 0,
        }))

    def test_rejects_unknown_profile(self) -> None:
        with self.assertRaises(ValueError):
            ResourcePolicy(capture_active=lambda: False, profile="unbounded")


if __name__ == "__main__":
    unittest.main()
