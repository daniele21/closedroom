"""Explicit local Community-1 review on a saved transcription.

A full-length native timeline is staged in the canonical JobStore. Projection
is pure; only an explicit apply mutates the TranscriptionStore. No ASR, cloud
fallback, recording metadata write, or original word/timestamp edit.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from local_asr_server.settings import load_settings
from local_asr_server.speaker_diarization import (
    DIARIZATION_ENGINE, LocalSpeakerDiarizationService, clusters_from_timeline,
)
from local_asr_server.speaker_labels import apply_speaker_labels

REVIEW_JOB_TYPE = "diarization_review"
MAX_REVIEW_EXAMPLES = 12


def fingerprint(transcription: dict[str, Any]) -> str:
    """Optimistic lock over source text, all segments and speaker metadata."""
    # Covers every currently visible field (including analysis and source
    # metadata) to reject stale application rather than overwriting a newer
    # edit unrelated to the speaker names.
    material = transcription
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def project_review(
    transcription: dict[str, Any], job: dict[str, Any],
) -> dict[str, Any]:
    """Build the entire speaker-only candidate from a reviewed native timeline.

    The job is validated independently by the router for transcription
    ownership. This function checks model and scope again for defense in depth.
    """
    if job.get("type") != REVIEW_JOB_TYPE or job.get("status") != "completed":
        raise ValueError("Review must finish successfully before it can be applied")
    result = job.get("result") or {}
    runs = result.get("runs") or []
    if result.get("scope") != "full" or len(runs) != 1 or runs[0].get("key") != "community-1":
        raise ValueError("Only complete Community-1 review results may be applied")
    run = runs[0]
    if run.get("status") != "completed" or not isinstance(run.get("timeline"), list):
        raise ValueError("Full speaker timeline is unavailable")
    if result.get("transcription_fingerprint") != fingerprint(transcription):
        raise ValueError("Transcription changed since preview; recompute the review")

    track_id = str(result.get("track_id") or "")
    if track_id not in {"system", "mixed"}:
        raise ValueError("Review requires a system or mixed audio track")
    raw_timeline = run["timeline"]
    if not raw_timeline:
        raise ValueError("Community-1 returned no speaker segments")

    candidate = copy.deepcopy(transcription)
    original_text = transcription.get("text", "")
    segments = candidate.get("segments") or []
    original_segments = transcription.get("segments") or []
    if not segments:
        raise ValueError("Transcription has no timed segments")
    source_labels = {
        str(track.get("id")): str(track.get("label") or track.get("source") or "Audio")
        for track in (transcription.get("source_tracks") or [])
    }

    target_segments: list[dict[str, Any]] = []
    for segment in segments:
        source_track = str(segment.get("track_id") or segment.get("source") or "mixed")
        segment["track_id"] = source_track
        segment.pop("provider_speaker", None)
        segment.pop("speaker_name", None)
        segment["speaker_label"] = source_labels.get(source_track, segment.get("source") or "Audio")
        if source_track == "mic":
            segment["provider_speaker"] = "mic:S1"
        elif source_track == track_id:
            target_segments.append(segment)

    if not target_segments:
        raise ValueError("No transcript segments belong to the reviewed track")
    threshold = float(load_settings().get("speaker_diarization_minimum_overlap", 0.25))
    assigned = LocalSpeakerDiarizationService.assign_segments(
        {"segments": target_segments}, track_id, raw_timeline, threshold, engine=DIARIZATION_ENGINE,
    )
    if assigned == 0:
        raise ValueError("No transcript segments match the detected speakers")

    clusters = clusters_from_timeline(track_id, raw_timeline)
    if any(str(segment.get("track_id")) == "mic" for segment in segments):
        clusters_by_track = {track_id: clusters, "mic": ["mic:S1"]}
    else:
        clusters_by_track = {track_id: clusters}
    summary = {
        "status": "completed", "engine": DIARIZATION_ENGINE,
        "provider": "local", "source": "reviewed_meeting",
        "cluster_count": sum(len(c) for c in clusters_by_track.values()),
        "clusters_by_track": clusters_by_track,
        "assigned_segments": sum(bool(s.get("provider_speaker")) for s in segments),
        "text_preserved": True,
    }
    candidate.pop("speaker_attribution", None)
    stats = dict(candidate.get("stats") or {})
    stats.pop("speaker_attribution", None)
    stats["speaker_diarization"] = summary
    stats["review_preserve_canonical_text"] = True
    candidate["stats"] = stats
    candidate["speaker_diarization"] = summary
    candidate["segments"] = segments
    # apply_speaker_labels resolves display labels, but normally renders a
    # decorated text transcription. Keep canonical text byte-for-byte instead.
    candidate = apply_speaker_labels(candidate)
    candidate["text"] = original_text
    for before, after in zip(original_segments, candidate["segments"]):
        if (before.get("start"), before.get("end"), before.get("text"), before.get("words")) != (
            after.get("start"), after.get("end"), after.get("text"), after.get("words")
        ):
            raise AssertionError("Speaker projection attempted to change ASR content")

    changes = [
        {
            "start": after.get("start"),
            "end": after.get("end"),
            "text": str(after.get("text") or "")[:220],
            "before": str(before.get("speaker_name") or before.get("speaker_label") or "—"),
            "after": str(after.get("speaker_name") or after.get("speaker_label") or "—"),
        }
        for before, after in zip(original_segments, candidate["segments"])
        if after.get("provider_speaker") != before.get("provider_speaker")
    ]
    return {
        "candidate": candidate,
        "assigned_segments": assigned,
        "cluster_count": summary["cluster_count"],
        "changed_segments": len(changes),
        "examples": changes[:MAX_REVIEW_EXAMPLES],
        "engine": DIARIZATION_ENGINE,
    }
