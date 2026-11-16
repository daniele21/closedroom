from __future__ import annotations

from typing import Any


def _time_label(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def apply_speaker_labels(
    payload: dict[str, Any],
    manual_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve diarization clusters to names or stable Speaker N fallbacks."""
    segments = payload.get("segments", []) or []

    # Ensure every segment has a stable provider_speaker cluster identifier
    for segment in segments:
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and not segment.get("provider_speaker"):
            segment["provider_speaker"] = cluster

    existing = (
        payload.get("speaker_attribution")
        or payload.get("stats", {}).get("speaker_attribution")
        or {}
    )
    existing_mappings = {
        str(item.get("speaker_cluster")): dict(item)
        for item in existing.get("mappings", []) or []
        if item.get("speaker_cluster")
    }
    manual = {
        str(cluster): str(name).strip()[:120]
        for cluster, name in (manual_names or {}).items()
        if str(name).strip()
    }
    clusters: list[str] = []
    diarization = (
        payload.get("speaker_diarization")
        or payload.get("stats", {}).get("speaker_diarization")
        or {}
    )
    for track_clusters in (diarization.get("clusters_by_track") or {}).values():
        for cluster in track_clusters or []:
            value = str(cluster)
            if value and value not in clusters:
                clusters.append(value)
    # A turn override does not transfer a name to the raw source cluster.
    turn_overrides = ((payload.get("stats") or {}).get("speaker_review") or {}).get("segment_assignments") or {}
    known_labels: dict[str, str] = {}
    segment_counts: dict[str, int] = {}
    for segment in sorted(segments, key=lambda item: (float(item.get("start") or 0), int(item.get("id") or 0))):
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and str(cluster) not in clusters:
            clusters.append(str(cluster))
        if cluster:
            segment_counts[str(cluster)] = segment_counts.get(str(cluster), 0) + 1
        if cluster and segment.get("speaker_label") and str(segment.get("id")) not in turn_overrides:
            label = str(segment["speaker_label"])
            if not str(cluster).startswith("Speaker "):
                known_labels[str(cluster)] = label

    # A *recording-owned* microphone track already uses one fixed speaker
    # (mic:S1). This is capture-source attribution, not voice biometrics:
    # only a genuine mic track and same-track raw cluster may default to "Tu".
    # Legacy/imported "Tu" labels and unverified track/cluster combinations
    # must still require identification.
    microphone_track = any(
        str(track.get("id") or "") == "mic"
        and str(track.get("source") or "mic") == "mic"
        for track in payload.get("source_tracks") or []
    )
    microphone_segments = [
        segment for segment in segments
        if str(segment.get("provider_speaker") or "") == "mic:S1"
    ]
    microphone_diarization = (
        (diarization.get("clusters_by_track") or {}).get("mic") or []
    )
    microphone_owner = (
        microphone_track
        and (bool(microphone_segments) or "mic:S1" in microphone_diarization)
        and all(str(segment.get("track_id") or "") == "mic"
                for segment in microphone_segments)
    )

    review_baseline = ((payload.get("stats") or {}).get("speaker_review") or {}).get("original_mappings") or {}
    mappings = []
    labels: dict[str, str] = {}
    for index, cluster in enumerate(clusters, start=1):
        previous = {**existing_mappings.get(cluster, {}), **review_baseline.get(cluster, {})}
        accepted_name = previous.get("display_name") if previous.get("status") == "accepted" else None
        owned_microphone = cluster == "mic:S1" and microphone_owner
        display_name = (
            manual.get(cluster) or accepted_name
            or (review_baseline.get(cluster) or {}).get("display_name")
            or ("Tu" if owned_microphone else None)
            or known_labels.get(cluster) or f"Speaker {index}"
        )
        if cluster in manual:
            source = "manual"
        elif accepted_name:
            source = previous.get("source") or "visual"
        elif owned_microphone:
            source = "microphone_track"
        else:
            source = previous.get("source") or "diarization"
        status = (
            "accepted" if cluster in manual or accepted_name or owned_microphone
            else "unassigned"
        )
        labels[cluster] = display_name
        mappings.append({
            **previous,
            "speaker_cluster": cluster,
            "display_name": display_name,
            "status": status,
            "source": source,
            "transcript_segment_count": segment_counts.get(cluster, 0),
        })

    # A speaker review maps raw identities to resolved people. Raw provider
    # clusters and ASR timings are never overwritten, even on merge/exclude.
    review = (payload.get("stats") or {}).get("speaker_review") or {}
    names = review.get("names") or {}
    # Identity confirmation does not alter the detected cluster or display
    # name. Persist it as explicit user intent, separate from a rename.
    confirmed = set(review.get("confirmed") or [])
    merged_into = review.get("merged_into") or {}
    segment_assignments = review.get("segment_assignments") or {}
    excluded = set(review.get("excluded") or [])

    def root_of(raw: str) -> str:
        current = raw
        visited: set[str] = set()
        while current in merged_into:
            if current in visited:
                raise ValueError("Cyclic speaker review mapping")
            visited.add(current)
            current = str(merged_into[current])
        return current

    by_cluster = {str(item["speaker_cluster"]): item for item in mappings}
    for raw, item in by_cluster.items():
        if raw in names:
            item["display_name"] = str(names[raw])[:120]
            item["status"] = "accepted"
            item["source"] = "manual"
        elif raw in confirmed:
            item["status"] = "accepted"
    for raw, item in by_cluster.items():
        canonical = root_of(raw)
        resolved = by_cluster.get(canonical, item)
        item["speaker_group"] = canonical
        if raw != canonical:
            item["merged_into"] = canonical
        else:
            item.pop("merged_into", None)
        if canonical in excluded:
            item["display_name"] = "Non identificato"
            item["status"] = "excluded"
        elif canonical != raw:
            item["display_name"] = resolved["display_name"]
            item["status"] = "merged"
        labels[raw] = str(item["display_name"])

    text_lines = []
    for segment in segments:
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and str(cluster) in labels:
            # Overrides change only the user-facing attribution of this one
            # immutable ASR segment. They never replace provider_speaker.
            override = segment_assignments.get(str(segment.get("id")))
            chosen = root_of(str(override)) if override else root_of(str(cluster))
            resolved = by_cluster.get(chosen)
            label = str(resolved["display_name"]) if resolved else labels[str(cluster)]
            segment["speaker_name"] = label
            segment["speaker_label"] = label
            segment["speaker_group"] = chosen if resolved else root_of(str(cluster))
        label = segment.get("speaker_name") or segment.get("speaker_label") or segment.get("source") or "Audio"
        text = (segment.get("text") or "").strip()
        if text:
            text_lines.append(f"[{_time_label(float(segment.get('start') or 0))}] {label}: {text}")

    attribution = {
        **existing,
        "source": "manual" if manual else existing.get("source") or "diarization",
        "mappings": mappings,
    }
    # Speaker labeling is allowed to rebuild text only when there are transcript
    # segments to label. Text-only/imported transcriptions may legitimately have
    # no segments; replacing their canonical text with an empty reconstruction
    # would be destructive and breaks merge/export workflows.
    if segments and not payload.get("stats", {}).get("review_preserve_canonical_text"):
        payload["text"] = "\n".join(text_lines)
    payload["speaker_attribution"] = attribution
    payload.setdefault("stats", {})["speaker_attribution"] = attribution
    return payload
