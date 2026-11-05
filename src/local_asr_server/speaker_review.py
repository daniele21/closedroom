"""Speaker samples and edits are local projections of immutable diarization evidence.

This module never modifies source audio, text, word timings or raw cluster IDs.
Media retrieval stays with RecordingStore's authorized track endpoints.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from local_asr_server.speaker_labels import apply_speaker_labels
from local_asr_server.recordings import RecordingConflict


def _clusters(transcription: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for mapping in (
        (transcription.get("speaker_attribution") or
         (transcription.get("stats") or {}).get("speaker_attribution") or {}).get("mappings") or []
    ):
        raw = str(mapping.get("speaker_cluster") or "").strip()
        if raw and raw not in found:
            found.append(raw)
    diarization = (
        transcription.get("speaker_diarization")
        or (transcription.get("stats") or {}).get("speaker_diarization")
        or {}
    )
    for values in (diarization.get("clusters_by_track") or {}).values():
        for value in values or []:
            raw = str(value).strip()
            if raw and raw not in found:
                found.append(raw)
    for segment in transcription.get("segments") or []:
        raw = str(segment.get("provider_speaker") or segment.get("speaker_label") or "").strip()
        if raw and raw not in found:
            found.append(raw)
    return found


def _root(cluster: str, merges: dict[str, str]) -> str:
    current = cluster
    seen: set[str] = set()
    while current in merges:
        if current in seen:
            raise ValueError("Invalid cyclic speaker merge state")
        seen.add(current)
        current = merges[current]
    return current


def project_speaker_action(
    transcription: dict[str, Any], *, action: str, cluster: str,
    target: str | None = None, name: str | None = None,
) -> dict[str, Any]:
    """Pure optimistic-review candidate; the store atomically commits it."""
    possible = _clusters(transcription)
    if cluster not in possible:
        raise ValueError("Unknown speaker for this transcription")
    candidate = copy.deepcopy(transcription)
    stats = candidate.setdefault("stats", {})
    review = dict(stats.get("speaker_review") or {})
    names = dict(review.get("names") or {})
    merges = dict(review.get("merged_into") or {})
    excluded = set(review.get("excluded") or [])
    originals = dict(review.get("original_mappings") or {})
    original_mappings = {
        str(m.get("speaker_cluster")): m
        for m in (
            transcription.get("speaker_attribution")
            or (transcription.get("stats") or {}).get("speaker_attribution")
            or {}
        ).get("mappings") or [] if m.get("speaker_cluster")
    }
    if cluster not in originals and cluster in original_mappings:
        item = original_mappings[cluster]
        originals[cluster] = {
            "display_name": item.get("display_name"),
            "status": item.get("status"),
            "source": item.get("source"),
        }
    root = _root(cluster, merges)
    if action == "rename":
        if cluster != root or root in excluded:
            raise ValueError("Choose a non-excluded, unmerged speaker to rename")
        new_name = str(name or "").strip()
        if not new_name or len(new_name) > 120:
            raise ValueError("Speaker name must contain 1–120 characters")
        names[root] = new_name
    elif action == "merge":
        if cluster != root or root in excluded:
            raise ValueError("Choose a non-excluded source speaker")
        if not target or target not in possible:
            raise ValueError("Choose a speaker from this transcription")
        destination = _root(target, merges)
        if destination == root or target != destination or destination in excluded:
            raise ValueError("Cannot merge with this speaker")
        merges[root] = destination
    elif action == "exclude":
        if cluster != root or root in excluded:
            raise ValueError("Speaker is already merged or excluded")
        excluded.add(root)
    elif action == "restore":
        if cluster in merges:
            del merges[cluster]
        elif root in excluded:
            excluded.remove(root)
        else:
            raise ValueError("Speaker has no correction to restore")
    else:
        raise ValueError("Unsupported speaker review action")

    # Only store validated, serializable review intent, never a second copy of
    # transcript segments, diarization audio or user voice characteristics.
    review["names"] = names
    review["original_mappings"] = originals
    review["merged_into"] = merges
    review["excluded"] = sorted(excluded)
    stats["speaker_review"] = review
    stats["review_preserve_canonical_text"] = True
    original_text = transcription.get("text", "")
    apply_speaker_labels(candidate)
    candidate["text"] = original_text
    return candidate


def _finite_interval(start: Any, end: Any) -> tuple[float, float] | None:
    try:
        a, b = float(start), float(end)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b <= a:
        return None
    return a, b


def _pick_samples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Prefer clean, long enough excerpts and different points in the meeting;
    # never synthesize/duplicate speech or stretch clips past the source interval.
    eligible = [row for row in items if row["end"] - row["start"] >= 1.5]
    eligible.sort(key=lambda row: (
        bool(row.get("overlap")),
        -(min(8.0, row["end"] - row["start"])),
        row["start"],
    ))
    chosen: list[dict[str, Any]] = []
    for row in eligible:
        if any(abs(row["start"] - prior["start"]) < 12.0 for prior in chosen):
            continue
        chosen.append({**row, "end": min(row["end"], row["start"] + 8.0)})
        if len(chosen) == 3:
            break
    return chosen


def speaker_audio_samples(transcription: dict[str, Any], recordings: Any) -> dict[str, Any]:
    """Read-only, bounded clip references from the exact saved recording.

    Raw fallback is allowed only for matching persisted native diarization,
    never an unrelated benchmark or a potentially stale reviewed timeline.
    """
    recording_id = str(transcription.get("recording_id") or "")
    if not recording_id or transcription.get("merged_sources"):
        raise ValueError("Speaker audio needs an unmerged saved meeting")
    metadata = recordings.get(recording_id, include_result=False)
    track_ids: set[str] = set()
    for track in metadata.get("audio_tracks") or []:
        track_id = str(track.get("id") or "")
        if not track_id or not track.get("audio_file"):
            continue
        try:
            recordings.track_audio_path(recording_id, track_id)
        except (OSError, ValueError, RecordingConflict):
            continue
        track_ids.add(track_id)

    diarization = (
        transcription.get("speaker_diarization")
        or (transcription.get("stats") or {}).get("speaker_diarization")
        or {}
    )
    # Only cross-correlate the raw file when provenance clearly identifies the
    # current diarization. An applied Community-1 review can have a distinct
    # timeline that has not been persisted in RecordingStore.
    raw = recordings.read_speaker_diarization(recording_id)
    raw_ok = (
        bool(raw)
        and str(raw.get("engine") or "") == str(diarization.get("engine") or "")
        and diarization.get("source") != "reviewed_meeting"
        and bool(diarization.get("clusters_by_track"))
    )
    candidates: dict[str, list[dict[str, Any]]] = {c: [] for c in _clusters(transcription)}
    for seg in transcription.get("segments") or []:
        cluster = str(seg.get("provider_speaker") or "")
        track = str(seg.get("track_id") or seg.get("source") or "")
        window = _finite_interval(seg.get("start"), seg.get("end"))
        if cluster in candidates and track in track_ids and window:
            candidates[cluster].append({
                "track_id": track, "start": window[0], "end": window[1],
                "kind": "transcript", "overlap": bool(seg.get("overlap")),
            })

    if raw_ok:
        for track, data in (raw.get("tracks") or {}).items():
            if track not in track_ids:
                continue
            expected = set((diarization.get("clusters_by_track") or {}).get(track) or [])
            observed = {
                str(turn.get("speaker") or "")
                if str(turn.get("speaker") or "").startswith(f"{track}:")
                else f"{track}:{turn.get('speaker')}"
                for turn in (data.get("segments") or []) if turn.get("speaker")
            }
            if not expected or expected != observed:
                continue
            for turn in (data.get("segments") or []):
                native = str(turn.get("speaker") or "")
                cluster = native if native.startswith(f"{track}:") else f"{track}:{native}"
                window = _finite_interval(turn.get("start"), turn.get("end"))
                if cluster in candidates and not any(
                    item["kind"] == "transcript" for item in candidates[cluster]
                ) and window:
                    candidates[cluster].append({
                        "track_id": track, "start": window[0], "end": window[1],
                        "kind": "diarization", "overlap": False,
                    })
    return {
        "recording_id": recording_id,
        "transcription_id": transcription.get("id"),
        "speakers": [
            {"speaker_cluster": cluster, "samples": _pick_samples(candidates[cluster])}
            for cluster in candidates
        ],
    }


def speaker_timeline_window(
    transcription: dict[str, Any], recordings: Any, *,
    start_seconds: float, end_seconds: float,
    review_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Windowed, read-only timeline from authorized local meeting evidence.

    Prefer the persisted native diarization only when its engine and *whole*
    per-track cluster sets match the applied transcription. Reviewed Community-1
    timelines are not the canonical raw recording, so those use attributed ASR
    intervals and are explicitly labelled as such. No synthesized voice or
    separation, no transcript text and no audio bytes leave this endpoint.
    """
    if not all(math.isfinite(value) for value in (start_seconds, end_seconds)):
        raise ValueError("Timeline range must contain finite timestamps")
    if start_seconds < 0 or end_seconds <= start_seconds or end_seconds - start_seconds > 28800:
        raise ValueError("Timeline range must be positive and at most eight hours")
    recording_id = str(transcription.get("recording_id") or "")
    if not recording_id or transcription.get("merged_sources"):
        raise ValueError("Timeline requires an unmerged saved meeting")
    metadata = recordings.get(recording_id, include_result=False)
    playable: set[str] = set()
    known_tracks: set[str] = set()
    for track in metadata.get("audio_tracks") or []:
        tid = str(track.get("id") or "")
        if not tid:
            continue
        known_tracks.add(tid)
        if not track.get("audio_file"):
            continue
        try:
            recordings.track_audio_path(recording_id, tid)
        except (OSError, ValueError, RecordingConflict):
            continue
        playable.add(tid)

    diarization = (
        transcription.get("speaker_diarization")
        or (transcription.get("stats") or {}).get("speaker_diarization")
        or {}
    )
    expected_by_track = diarization.get("clusters_by_track") or {}
    raw: dict[str, Any] | None = None
    if diarization.get("source") == "reviewed_meeting":
        result = (review_job or {}).get("result") or {}
        runs = result.get("runs") or []
        applied_id = str(diarization.get("applied_review_job_id") or "")
        review_track = str(result.get("track_id") or "")
        if (
            applied_id and str((review_job or {}).get("id") or "") == applied_id
            and review_job.get("type") == "diarization_review"
            and review_job.get("status") == "completed"
            and str(review_job.get("scope_id") or "") == str(transcription.get("id") or "")
            and str(review_job.get("recording_id") or "") == recording_id
            and result.get("scope") == "full"
            and review_track in known_tracks
            and len(runs) == 1
            and runs[0].get("key") == "community-1"
            and runs[0].get("status") == "completed"
            and isinstance(runs[0].get("timeline"), list)
        ):
            # The reviewed native timeline is already persisted by JobStore.
            # A missing/expired or unrelated job cannot produce claimed audio.
            raw = {"engine": diarization.get("engine"), "tracks": {
                review_track: {"segments": runs[0]["timeline"]},
            }}
    else:
        raw = recordings.read_speaker_diarization(recording_id)
    raw_ok = (
        bool(raw)
        and str(diarization.get("status") or "completed") == "completed"
        and str(raw.get("engine") or "") == str(diarization.get("engine") or "")
        and bool(expected_by_track)
    )
    known = set(_clusters(transcription))
    by_cluster: dict[str, list[dict[str, Any]]] = {key: [] for key in known}
    raw_clusters: set[str] = set()
    if raw_ok:
        for track_id, track_data in (raw.get("tracks") or {}).items():
            if track_id not in known_tracks:
                continue
            expected = set(str(value) for value in (expected_by_track.get(track_id) or []))
            observed = {
                str(turn.get("speaker")) if str(turn.get("speaker") or "").startswith(f"{track_id}:")
                else f"{track_id}:{turn.get('speaker')}"
                for turn in (track_data.get("segments") or []) if turn.get("speaker")
            }
            if not expected or expected != observed:
                continue
            for turn in (track_data.get("segments") or []):
                voice = str(turn.get("speaker") or "")
                cluster = voice if voice.startswith(f"{track_id}:") else f"{track_id}:{voice}"
                span = _finite_interval(turn.get("start"), turn.get("end"))
                if cluster not in known or span is None:
                    continue
                raw_clusters.add(cluster)
                by_cluster[cluster].append({
                    "cluster": cluster, "track_id": track_id,
                    "start": span[0], "end": span[1], "origin": "diarization",
                    "overlap": False, "playable": track_id in playable,
                })

    # ASR projection is intentionally a fallback, not blended with a different
    # native timing source for the same identity.
    for segment in transcription.get("segments") or []:
        cluster = str(segment.get("provider_speaker") or "")
        if cluster not in known or cluster in raw_clusters:
            continue
        track_id = str(segment.get("track_id") or segment.get("source") or "")
        if track_id not in known_tracks:
            continue
        span = _finite_interval(segment.get("start"), segment.get("end"))
        if span is None:
            continue
        by_cluster[cluster].append({
            "cluster": cluster, "track_id": track_id,
            "start": span[0], "end": span[1], "origin": "transcript",
            "overlap": bool(segment.get("overlap")),
            "playable": track_id in playable,
        })

    all_intervals = [
        item for items in by_cluster.values() for item in items
        if item["end"] > start_seconds and item["start"] < end_seconds
    ]
    all_intervals.sort(key=lambda item: (item["start"], item["end"], item["cluster"]))
    limit = 5000
    clipped = [
        {**item,
         "start": max(start_seconds, item["start"]),
         "end": min(end_seconds, item["end"])}
        for item in all_intervals[:limit]
    ]
    native = sum(item["origin"] == "diarization" for item in clipped)
    return {
        "recording_id": recording_id,
        "transcription_id": transcription.get("id"),
        "start": start_seconds, "end": end_seconds,
        "intervals": clipped,
        "truncated": len(all_intervals) > limit,
        "coverage": "mixed" if native and native != len(clipped) else
                    "diarization" if native else "transcript",
        "has_audio": bool(playable),
    }
