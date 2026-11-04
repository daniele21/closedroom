"""Fail-closed audio retention policy; all tests offline and no file deletion."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from local_asr_server.recording_storage_policy import assess_audio_cleanup


NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def sample_meeting() -> dict:
    return {
        "status": "completed",
        "audio_tracks": [
            {"id": "mic", "bytes_written": 100, "_content_sha256": "a" * 64},
            {"id": "system", "bytes_written": 200, "_content_sha256": "b" * 64},
        ],
        "_audio_cloud_proof": {
            "format": "closedroom-audio-proof-v1",
            "state": "recovery_verified",
            "bucket": "private-bucket",
            "generation": 91,
            "plaintext_sha256": "c" * 64,
            "ciphertext_sha256": "d" * 64,
            "uploaded_at": (NOW - timedelta(days=25)).isoformat(),
            "restored_at": (NOW - timedelta(days=20)).isoformat(),
            "recovery_exported_at": (NOW - timedelta(days=19)).isoformat(),
            "recovery_independent_of_mac": True,
            "tracks": {
                "mic": {"bytes": 100, "sha256": "a" * 64},
                "system": {"bytes": 200, "sha256": "b" * 64},
            },
        },
    }


def assess(meeting: dict, **overrides) -> dict:
    return assess_audio_cleanup(meeting, now=NOW, retention_days=14,
                                cleanup_enabled=True, local_transcript_verified=True,
                                active_operations=False, **overrides)


class RetentionSafetyTests(unittest.TestCase):
    def test_legacy_and_unverified_meetings_never_qualify(self) -> None:
        legacy = {"status": "completed", "audio_tracks": sample_meeting()["audio_tracks"]}
        r = assess(legacy)
        self.assertFalse(r["cleanup_candidate"])
        self.assertIn("remote_proof_missing", r["cleanup_blockers"])
        self.assertIn("independent_recovery_unverified", r["cleanup_blockers"])
        self.assertFalse(r["automatic_eviction_implemented"])
        self.assertTrue(r["transcriptions_kept_local"])

    def test_successful_upload_without_verified_restore_cannot_free_space(self) -> None:
        m = sample_meeting()
        m["_audio_cloud_proof"]["state"] = "remote_verified"
        m["_audio_cloud_proof"].pop("restored_at")
        r = assess(m)
        self.assertFalse(r["cleanup_candidate"])
        self.assertIn("independent_recovery_unverified", r["cleanup_blockers"])

    def test_cleanup_remains_disabled_even_after_all_proofs(self) -> None:
        r = assess_audio_cleanup(sample_meeting(), now=NOW, cleanup_enabled=False,
                                 local_transcript_verified=True, active_operations=False)
        self.assertFalse(r["cleanup_candidate"])
        self.assertIn("automatic_cleanup_disabled", r["cleanup_blockers"])

    def test_candidates_are_never_deletion_authorizations(self) -> None:
        r = assess(sample_meeting())
        self.assertTrue(r["cleanup_candidate"])
        self.assertFalse(r["automatic_eviction_implemented"])

    def test_14_day_redundancy_begins_at_verified_restore(self) -> None:
        m = sample_meeting()
        m["_audio_cloud_proof"]["restored_at"] = (NOW - timedelta(days=13)).isoformat()
        r = assess(m)
        self.assertFalse(r["cleanup_candidate"])
        self.assertIn("temporary_local_redundancy_active", r["cleanup_blockers"])
        self.assertEqual(r["retain_until"], (NOW + timedelta(days=1)).isoformat())

    def test_all_tracks_must_be_present_and_identical(self) -> None:
        for change in ("removed", "wrong_hash", "wrong_size", "missing_local_hash"):
            m = sample_meeting()
            proof = m["_audio_cloud_proof"]["tracks"]
            if change == "removed":
                proof.pop("system")
            elif change == "wrong_hash":
                proof["system"]["sha256"] = "e" * 64
            elif change == "wrong_size":
                proof["mic"]["bytes"] = 101
            else:
                m["audio_tracks"][0].pop("_content_sha256")
            with self.subTest(change=change):
                r = assess(m)
                self.assertFalse(r["cleanup_candidate"])
                self.assertIn("audio_tracks_unverified", r["cleanup_blockers"])

    def test_missing_recovery_export_or_other_mac_proof_blocks(self) -> None:
        for field in ("recovery_exported_at", "recovery_independent_of_mac",
                      "generation", "plaintext_sha256", "ciphertext_sha256"):
            m = sample_meeting()
            m["_audio_cloud_proof"].pop(field)
            with self.subTest(field=field):
                self.assertFalse(assess(m)["cleanup_candidate"])

    def test_invalid_and_future_timestamps_block(self) -> None:
        for value in ("2026-10-11T12:00:00", "not-a-date",
                      (NOW + timedelta(days=2)).isoformat()):
            m = sample_meeting()
            m["_audio_cloud_proof"]["restored_at"] = value
            with self.subTest(value=value):
                self.assertFalse(assess(m)["cleanup_candidate"])

    def test_processing_and_missing_local_transcript_block(self) -> None:
        m = sample_meeting()
        self.assertFalse(assess_audio_cleanup(
            m, now=NOW, cleanup_enabled=True, local_transcript_verified=False,
            active_operations=False,
        )["cleanup_candidate"])
        self.assertFalse(assess_audio_cleanup(
            m, now=NOW, cleanup_enabled=True, local_transcript_verified=True,
            active_operations=True,
        )["cleanup_candidate"])

    def test_boolean_retention_and_naive_clock_fail_closed(self) -> None:
        m = sample_meeting()
        r = assess_audio_cleanup(m, retention_days=True, cleanup_enabled=True,
                                 local_transcript_verified=True, active_operations=False, now=NOW)
        self.assertFalse(r["cleanup_candidate"])
        with self.assertRaises(ValueError):
            assess_audio_cleanup(m, now=datetime(2026, 11, 4))

    def test_malformed_remote_proof_not_raised_to_client(self) -> None:
        m = sample_meeting()
        m["_audio_cloud_proof"]["state"] = ["not-a-state"]
        self.assertFalse(assess(m)["cleanup_candidate"])
        self.assertEqual(assess(m)["state"], "local_only")


if __name__ == "__main__":
    unittest.main()
