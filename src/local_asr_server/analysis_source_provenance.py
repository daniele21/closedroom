"""Read-only provenance for speaker-attributed analysis.

Keep analysis/source identity in this owner, not as a second speaker-review
persistence store. Digests contain no raw transcript or audio in API metadata.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from local_asr_server.speaker_labels import apply_speaker_labels


def speaker_attribution_digest(transcription: dict[str, Any]) -> str:
    """Stable identity of speaker assignments at generation/review time.

    Keep the original provider ID separate from the effective user attribution.
    The transcript text itself is owned by the existing source/cache fingerprint.
    """
    # Catalog.find_for_recording returns the persisted projection as-is,
    # while TranscriptionStore.get applies the canonical speaker-label resolver.
    # Both read paths must hash *the same effective speaker assignment*, not
    # accidentally label every existing analysis stale on first Meeting load.
    # Resolve on a clone: this must never rewrite the source transcript.
    normalized = apply_speaker_labels(copy.deepcopy(transcription))
    segments = []
    for index, segment in enumerate(normalized.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        segments.append({
            "id": segment.get("id", index),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "provider_speaker": segment.get("provider_speaker"),
            "speaker_group": segment.get("speaker_group"),
            "speaker_name": segment.get("speaker_name"),
            "speaker_label": segment.get("speaker_label"),
        })
    serialized = json.dumps(segments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _reviewed_speaker_identity(transcription: dict[str, Any]) -> bool:
    stats = transcription.get("stats") or {}
    review = stats.get("speaker_review") or {}
    if any(review.get(key) for key in ("names", "merged_into", "excluded", "segment_assignments")):
        return True
    return any(
        mapping.get("status") in {"accepted", "merged", "excluded"}
        for mapping in (stats.get("speaker_attribution") or {}).get("mappings") or []
        if isinstance(mapping, dict)
    )


def project_speaker_source_validity(
    runs: list[dict[str, Any]],
    transcription: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Decorate read models only. Never edit historical analysis or user edits.

    Older runs without a snapshot cannot be declared current or stale after a
    correction; they are explicitly unverifiable instead of silently trusted.
    """
    if not transcription or not transcription.get("id"):
        return list(runs)
    current_id = transcription["id"]
    digest = speaker_attribution_digest(transcription)
    reviewed = _reviewed_speaker_identity(transcription)
    projected = []
    for run in runs:
        if run.get("status") != "completed" or run.get("transcription_id") != current_id:
            projected.append(run)
            continue
        result = run.get("result")
        snapshot = result.get("source_snapshot") if isinstance(result, dict) else None
        original = snapshot.get("speaker_attribution_sha256") if isinstance(snapshot, dict) and snapshot.get("transcription_id") == current_id else None
        if isinstance(original, str) and re.fullmatch(r"[0-9a-f]{64}", original):
            status = "current" if original == digest else "stale"
            projected.append({
                **run,
                "speaker_source_validity": {
                    "status": status,
                    "reason": "speaker_attribution_changed" if status == "stale" else None,
                },
            })
        elif reviewed:
            projected.append({
                **run,
                "speaker_source_validity": {
                    "status": "unverifiable",
                    "reason": "legacy_without_speaker_provenance",
                },
            })
        else:
            projected.append(run)
    return projected
