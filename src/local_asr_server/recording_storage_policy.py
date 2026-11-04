"""Fail-closed per-meeting audio retention policy for ClosedRoom.

RecordingStore owns the canonical meeting metadata. This pure evaluator must
never delete files, authenticate to GCS or treat a successful upload as proof
that audio can safely be evicted. A true *candidate* still needs an independent
live GCS recheck, local content rehash, active-operation/lease exclusion, and
crash-safe transactional eviction in the RecordingStore owner.

Transcriptions and catalog are never eviction targets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping

RETENTION_DAYS = frozenset({7, 14, 30})
DEFAULT_RETENTION_DAYS = 14
SHA256 = re.compile(r"[a-f0-9]{64}\Z")

# These are observable, not writable by callers through the public API.
LOCAL_ONLY = "local_only"
REMOTE_PENDING = "remote_pending"
REMOTE_VERIFIED = "remote_verified"
RECOVERY_VERIFIED = "recovery_verified"


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def assess_audio_cleanup(
    meeting: Mapping[str, Any],
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    cleanup_enabled: bool = False,
    local_transcript_verified: bool = False,
    active_operations: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return *readiness*, never permission to unlink a local audio file.

    Evidence is meaningful only when written by the future authenticated GCS
    verifier in the canonical RecordingStore. Missing/unknown/legacy evidence,
    corrupt timestamps and partial proof fail closed. The current app never
    runs an eviction worker, even when candidate=True.
    """
    blockers: list[str] = []
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("A timezone-aware current time is required")
    current = current.astimezone(timezone.utc)
    if type(retention_days) is not int or retention_days not in RETENTION_DAYS:
        blockers.append("retention_policy_invalid")
    if cleanup_enabled is not True:
        blockers.append("automatic_cleanup_disabled")
    if meeting.get("status") != "completed":
        blockers.append("meeting_not_completed")
    if not local_transcript_verified:
        blockers.append("local_transcript_unverified")
    # Nobody has yet proven there are no jobs, playback or hydration leases.
    # An unknown activity state must block cleanup, not be treated as idle.
    if active_operations is not False:
        blockers.append("meeting_operations_unverified")

    raw = meeting.get("_audio_cloud_proof")
    proof = raw if isinstance(raw, dict) else {}
    if proof.get("format") != "closedroom-audio-proof-v1":
        blockers.append("remote_proof_missing")
    if proof.get("state") != RECOVERY_VERIFIED:
        blockers.append("independent_recovery_unverified")

    # Only an authenticated remote generation-specific *restore* proof can
    # advance the candidate state, not an upload receipt or a GCS HTTP 200.
    if not isinstance(proof.get("bucket"), str) or not proof.get("bucket"):
        blockers.append("remote_bucket_unverified")
    generation = proof.get("generation")
    if type(generation) is not int or generation < 1:
        blockers.append("remote_generation_unverified")
    for key in ("plaintext_sha256", "ciphertext_sha256"):
        value = proof.get(key)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            blockers.append("remote_digest_unverified")
            break

    uploaded = _utc(proof.get("uploaded_at"))
    restored = _utc(proof.get("restored_at"))
    recovery_exported = _utc(proof.get("recovery_exported_at"))
    if (
        uploaded is None or restored is None or recovery_exported is None
        or uploaded > current or restored > current or recovery_exported > current
        or restored < uploaded or recovery_exported < uploaded
    ):
        blockers.append("recovery_timeline_unverified")
    if proof.get("recovery_independent_of_mac") is not True:
        blockers.append("independent_recovery_material_missing")

    # Guard *all* tracks; no single-track proof may qualify a multi-track
    # meeting, and no legacy/empty track set may qualify.
    tracks = meeting.get("audio_tracks")
    verified = proof.get("tracks")
    track_ids: set[str] = set()
    if not isinstance(tracks, list) or not tracks or not isinstance(verified, dict):
        blockers.append("audio_tracks_unverified")
    else:
        for track in tracks:
            if not isinstance(track, dict) or track.get("id") not in {"mixed", "mic", "system"}:
                blockers.append("audio_tracks_unverified")
                break
            track_id = track["id"]
            if track_id in track_ids:
                blockers.append("audio_tracks_unverified")
                break
            track_ids.add(track_id)
            item = verified.get(track_id)
            if (not isinstance(item, dict)
                    or type(item.get("bytes")) is not int or item["bytes"] <= 0
                    or not isinstance(item.get("sha256"), str)
                    or SHA256.fullmatch(item["sha256"]) is None
                    or type(track.get("bytes_written")) is not int
                    or item["bytes"] != track["bytes_written"]
                    or item["sha256"] != track.get("_content_sha256")):
                blockers.append("audio_tracks_unverified")
                break
        if set(verified) != track_ids:
            blockers.append("audio_tracks_unverified")

    # The delay starts *after* restoration and recoverability verification,
    # not after the recording ended or an upload merely returned success.
    if restored is None or type(retention_days) is not int or retention_days not in RETENTION_DAYS:
        earliest = None
    else:
        earliest = restored + timedelta(days=retention_days)
        if current < earliest:
            blockers.append("temporary_local_redundancy_active")

    distinct = tuple(dict.fromkeys(blockers))
    return {
        "state": proof.get("state") if isinstance(proof.get("state"), str) and proof["state"] in {
            REMOTE_PENDING, REMOTE_VERIFIED, RECOVERY_VERIFIED
        } else LOCAL_ONLY,
        "cleanup_candidate": not distinct,
        "cleanup_blockers": list(distinct),
        "retain_until": earliest.isoformat() if earliest is not None else None,
        "automatic_eviction_implemented": False,
        "transcriptions_kept_local": True,
    }
